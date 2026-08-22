"""
Fase 80 — Solicitações de Materiais/EPI: pedido → aprovação (segregação de
função: quem pede não pode aprovar o próprio pedido, mesmo padrão de
lotes.aprovar desde a Fase 1) → entrega (setor diferente do aprovador,
tipicamente Estoque) → confirmação de recebimento pelo próprio solicitante
— com comprovante em PDF ao final (para EPI, o equivalente digital da
Ficha de Controle de Fornecimento de EPI exigida pela NR-6).

Catálogo próprio (`materiais_solicitaveis`), sem vínculo com `itens` — ver
a nota de escopo completa em migrations/schema_fase80.sql.
"""
import datetime
import io
import secrets

from flask import Blueprint, Response, g, jsonify, request
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..pdf_marca import desenhar_cabecalho_logo
from ..permissions import requires_permission

bp = Blueprint("solicitacoes_material", __name__, url_prefix="/api/v1/solicitacoes-material")

PRIORIDADES_VALIDAS = ("baixa", "media", "alta", "urgente")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _gerar_numero():
    ano = datetime.datetime.utcnow().year
    return f"SM-{ano}-{secrets.token_hex(4).upper()}"


# ============================================================
# CATÁLOGO DE MATERIAIS/EPI
# ============================================================
@bp.get("/materiais")
@requires_permission("solicitacoes_material", "visualizar")
def listar_materiais():
    conn = get_db()
    incluir_inativos = request.args.get("incluir_inativos") == "1"
    where = "" if incluir_inativos else "WHERE status = 'ativo'"
    rows = conn.execute(f"SELECT * FROM materiais_solicitaveis {where} ORDER BY descricao").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/materiais")
@requires_permission("solicitacoes_material", "cadastrar_catalogo")
def criar_material():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    descricao = (dados.get("descricao") or "").strip()
    if not descricao:
        raise ApiError("Informe a descrição.", status=400)
    codigo = (dados.get("codigo") or "").strip()
    if codigo:
        if conn.execute("SELECT id FROM materiais_solicitaveis WHERE codigo = ?", (codigo,)).fetchone():
            raise ApiError("Já existe um material com este código.", status=409)
    else:
        prefixo = "EPI" if dados.get("e_epi") else "MAT"
        for tentativa in range(1000):
            candidato = f"{prefixo}{tentativa:04d}"
            if not conn.execute("SELECT id FROM materiais_solicitaveis WHERE codigo = ?", (candidato,)).fetchone():
                codigo = candidato
                break
        if not codigo:
            raise ApiError("Não foi possível gerar um código automático — informe um manualmente.", status=500)

    e_epi = 1 if dados.get("e_epi") else 0
    cur = conn.execute(
        """
        INSERT INTO materiais_solicitaveis (codigo, descricao, categoria, e_epi, numero_ca, unidade_medida, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (codigo, descricao, dados.get("categoria"), e_epi, dados.get("numero_ca"),
         dados.get("unidade_medida") or "un", usuario_atual["id"]),
    )
    material_id = cur.lastrowid
    audit.registrar(conn, tabela="materiais_solicitaveis", registro_id=material_id, usuario_id=usuario_atual["id"],
                     acao="material_solicitavel_criado", valor_novo={"codigo": codigo, "descricao": descricao, "e_epi": bool(e_epi)},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM materiais_solicitaveis WHERE id = ?", (material_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.put("/materiais/<int:material_id>")
@requires_permission("solicitacoes_material", "cadastrar_catalogo")
def editar_material(material_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = conn.execute("SELECT * FROM materiais_solicitaveis WHERE id = ?", (material_id,)).fetchone()
    if anterior is None:
        raise ApiError("Material não encontrado.", status=404)
    anterior = dict(anterior)

    descricao = dados.get("descricao", anterior["descricao"])
    categoria = dados.get("categoria", anterior["categoria"])
    e_epi = 1 if dados.get("e_epi", anterior["e_epi"]) else 0
    numero_ca = dados.get("numero_ca", anterior["numero_ca"])
    unidade_medida = dados.get("unidade_medida", anterior["unidade_medida"])
    status = dados.get("status", anterior["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    conn.execute(
        """
        UPDATE materiais_solicitaveis SET descricao = ?, categoria = ?, e_epi = ?, numero_ca = ?,
               unidade_medida = ?, status = ?, atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (descricao, categoria, e_epi, numero_ca, unidade_medida, status, _now_iso(), usuario_atual["id"], material_id),
    )
    novo_row = conn.execute("SELECT * FROM materiais_solicitaveis WHERE id = ?", (material_id,)).fetchone()
    audit.registrar(conn, tabela="materiais_solicitaveis", registro_id=material_id, usuario_id=usuario_atual["id"],
                     acao="material_solicitavel_editado", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo_row))


# ============================================================
# SOLICITAÇÕES
# ============================================================
def _solicitacao_ou_404(conn, solicitacao_id):
    row = conn.execute("SELECT * FROM solicitacoes_material WHERE id = ?", (solicitacao_id,)).fetchone()
    if row is None:
        raise ApiError("Solicitação não encontrada.", status=404)
    return dict(row)


def _solicitacao_detalhada(conn, solicitacao_id):
    solicitacao = _solicitacao_ou_404(conn, solicitacao_id)
    for campo, tabela in (("solicitante_id", "solicitante"), ("aprovador_id", "aprovador"), ("entregue_por_id", "entregador")):
        usuario_id = solicitacao[campo]
        if usuario_id:
            usuario = conn.execute("SELECT nome, email FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            solicitacao[f"{tabela}_nome"] = usuario["nome"] if usuario else None
        else:
            solicitacao[f"{tabela}_nome"] = None

    itens = conn.execute(
        """
        SELECT smi.*, m.codigo AS material_codigo, m.descricao AS material_descricao,
               m.e_epi AS material_e_epi, m.numero_ca AS material_numero_ca
        FROM solicitacoes_material_itens smi JOIN materiais_solicitaveis m ON m.id = smi.material_id
        WHERE smi.solicitacao_id = ? ORDER BY smi.id
        """,
        (solicitacao_id,),
    ).fetchall()
    solicitacao["itens"] = [dict(i) for i in itens]
    return solicitacao


@bp.get("")
@requires_permission("solicitacoes_material", "visualizar")
def listar_solicitacoes():
    conn = get_db()
    status = request.args.get("status")
    solicitante_id = request.args.get("solicitante_id", type=int)
    clausulas, params = [], []
    if status:
        clausulas.append("status = ?")
        params.append(status)
    if solicitante_id:
        clausulas.append("solicitante_id = ?")
        params.append(solicitante_id)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT sm.*, u.nome AS solicitante_nome
        FROM solicitacoes_material sm JOIN usuarios u ON u.id = sm.solicitante_id
        {where}
        ORDER BY sm.id DESC LIMIT 500
        """,
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:solicitacao_id>")
@requires_permission("solicitacoes_material", "visualizar")
def obter_solicitacao(solicitacao_id):
    conn = get_db()
    return jsonify(_solicitacao_detalhada(conn, solicitacao_id))


@bp.post("")
@requires_permission("solicitacoes_material", "solicitar")
def criar_solicitacao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    justificativa = (dados.get("justificativa") or "").strip()
    if not justificativa:
        raise ApiError("Informe a justificativa do pedido.", status=400)
    prioridade = dados.get("prioridade") or "media"
    if prioridade not in PRIORIDADES_VALIDAS:
        raise ApiError(f"prioridade deve ser uma de: {', '.join(PRIORIDADES_VALIDAS)}.", status=400)
    itens = dados.get("itens") or []
    if not itens:
        raise ApiError("Informe ao menos um item em 'itens'.", status=400)

    itens_validados = []
    for linha in itens:
        material_id = linha.get("material_id")
        quantidade = linha.get("quantidade_solicitada")
        if not material_id or not quantidade:
            raise ApiError("Cada item precisa de material_id e quantidade_solicitada.", status=400)
        try:
            quantidade = float(quantidade)
        except (TypeError, ValueError):
            raise ApiError("quantidade_solicitada deve ser numérica.", status=400)
        if quantidade <= 0:
            raise ApiError("quantidade_solicitada deve ser maior que zero.", status=400)
        material = conn.execute("SELECT * FROM materiais_solicitaveis WHERE id = ?", (material_id,)).fetchone()
        if material is None:
            raise ApiError(f"Material id={material_id} não encontrado.", status=404)
        if material["status"] != "ativo":
            raise ApiError(f"O material '{material['descricao']}' não está mais disponível para solicitação.", status=400)
        itens_validados.append({
            "material_id": material_id, "quantidade": quantidade,
            "especificacao": (linha.get("especificacao") or "").strip() or None,
        })

    numero = _gerar_numero()
    cur = conn.execute(
        """
        INSERT INTO solicitacoes_material (numero, solicitante_id, setor_solicitante, prioridade, justificativa, criado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (numero, usuario_atual["id"], dados.get("setor_solicitante"), prioridade, justificativa, usuario_atual["id"]),
    )
    solicitacao_id = cur.lastrowid
    for item in itens_validados:
        conn.execute(
            "INSERT INTO solicitacoes_material_itens (solicitacao_id, material_id, quantidade_solicitada, especificacao) VALUES (?, ?, ?, ?)",
            (solicitacao_id, item["material_id"], item["quantidade"], item["especificacao"]),
        )

    audit.registrar(conn, tabela="solicitacoes_material", registro_id=solicitacao_id, usuario_id=usuario_atual["id"],
                     acao="solicitacao_material_criada", valor_novo={"numero": numero, "prioridade": prioridade, "itens": len(itens_validados)},
                     ip=client_ip(), dispositivo=client_device())
    # Envia para o setor de liberação — todo usuário com a permissão
    # "solicitacoes_material.aprovar" (a mesma que libera o botão Aprovar
    # abaixo). Quem for esse setor é decidido no cadastro de Perfis, não
    # aqui — dar/tirar essa permissão de um perfil É a forma de configurar
    # qual setor libera as solicitações, sem precisar de tela nova.
    notificacoes_service.notificar_usuarios_com_permissao(
        conn, modulo="solicitacoes_material", acao="aprovar",
        tipo="solicitacao_material_pendente",
        mensagem=f"Nova solicitação de material/EPI {numero} ({prioridade}) de {usuario_atual['nome']} aguardando liberação.",
        excluir_usuario_id=usuario_atual["id"],
    )
    return jsonify(_solicitacao_detalhada(conn, solicitacao_id)), 201


@bp.post("/<int:solicitacao_id>/aprovar")
@requires_permission("solicitacoes_material", "aprovar")
def aprovar_solicitacao(solicitacao_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    solicitacao = _solicitacao_ou_404(conn, solicitacao_id)

    if solicitacao["status"] != "pendente":
        raise ApiError(f"Só é possível aprovar uma solicitação 'pendente' (status atual: '{solicitacao['status']}').", status=400)
    # Segregação de função — mesmo padrão de lotes.aprovar (Fase 1):
    # quem pediu não pode ser quem aprova o próprio pedido.
    if solicitacao["solicitante_id"] == usuario_atual["id"]:
        raise ForbiddenError("Você solicitou este pedido — a aprovação precisa ser feita por outra pessoa (segregação de função).")

    conn.execute(
        "UPDATE solicitacoes_material SET status = 'aprovada', aprovador_id = ?, decidido_em = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), solicitacao_id),
    )
    audit.registrar(conn, tabela="solicitacoes_material", registro_id=solicitacao_id, usuario_id=usuario_atual["id"],
                     acao="solicitacao_material_aprovada", valor_anterior={"status": "pendente"}, valor_novo={"status": "aprovada"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_solicitacao_detalhada(conn, solicitacao_id))


@bp.post("/<int:solicitacao_id>/rejeitar")
@requires_permission("solicitacoes_material", "aprovar")
def rejeitar_solicitacao(solicitacao_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()
    solicitacao = _solicitacao_ou_404(conn, solicitacao_id)

    if solicitacao["status"] != "pendente":
        raise ApiError(f"Só é possível rejeitar uma solicitação 'pendente' (status atual: '{solicitacao['status']}').", status=400)
    if solicitacao["solicitante_id"] == usuario_atual["id"]:
        raise ForbiddenError("Você solicitou este pedido — a decisão precisa ser tomada por outra pessoa (segregação de função).")
    if not motivo:
        raise ApiError("Informe o motivo da rejeição.", status=400)

    conn.execute(
        "UPDATE solicitacoes_material SET status = 'rejeitada', aprovador_id = ?, decidido_em = ?, motivo_rejeicao = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), motivo, solicitacao_id),
    )
    audit.registrar(conn, tabela="solicitacoes_material", registro_id=solicitacao_id, usuario_id=usuario_atual["id"],
                     acao="solicitacao_material_rejeitada", valor_anterior={"status": "pendente"},
                     valor_novo={"status": "rejeitada", "motivo": motivo}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_solicitacao_detalhada(conn, solicitacao_id))


@bp.post("/<int:solicitacao_id>/entregar")
@requires_permission("solicitacoes_material", "entregar")
def entregar_solicitacao(solicitacao_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    solicitacao = _solicitacao_ou_404(conn, solicitacao_id)

    if solicitacao["status"] != "aprovada":
        raise ApiError(f"Só é possível entregar uma solicitação 'aprovada' (status atual: '{solicitacao['status']}').", status=400)

    itens_pedido = conn.execute(
        "SELECT * FROM solicitacoes_material_itens WHERE solicitacao_id = ?", (solicitacao_id,)
    ).fetchall()
    quantidades_entregues = {i.get("item_id"): i.get("quantidade_entregue") for i in (dados.get("itens") or [])}
    for linha in itens_pedido:
        quantidade_entregue = quantidades_entregues.get(linha["id"], linha["quantidade_solicitada"])
        try:
            quantidade_entregue = float(quantidade_entregue)
        except (TypeError, ValueError):
            raise ApiError(f"Quantidade entregue inválida para o item id={linha['id']}.", status=400)
        if quantidade_entregue < 0:
            raise ApiError("Quantidade entregue não pode ser negativa.", status=400)
        conn.execute(
            "UPDATE solicitacoes_material_itens SET quantidade_entregue = ? WHERE id = ?",
            (quantidade_entregue, linha["id"]),
        )

    conn.execute(
        "UPDATE solicitacoes_material SET status = 'entregue', entregue_por_id = ?, entregue_em = ?, observacoes_entrega = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), dados.get("observacoes"), solicitacao_id),
    )
    audit.registrar(conn, tabela="solicitacoes_material", registro_id=solicitacao_id, usuario_id=usuario_atual["id"],
                     acao="solicitacao_material_entregue", valor_anterior={"status": "aprovada"}, valor_novo={"status": "entregue"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_solicitacao_detalhada(conn, solicitacao_id))


@bp.post("/<int:solicitacao_id>/confirmar-recebimento")
@requires_permission("solicitacoes_material", "solicitar")
def confirmar_recebimento(solicitacao_id):
    """Segundo passo de confirmação, feito pelo PRÓPRIO solicitante — sem
    isso, a "prova de entrega" seria só a palavra de quem entregou (ver a
    nota de escopo completa em migrations/schema_fase80.sql, mesmo
    espírito da assinatura na Ficha de EPI da NR-6)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    solicitacao = _solicitacao_ou_404(conn, solicitacao_id)

    if solicitacao["solicitante_id"] != usuario_atual["id"]:
        raise ForbiddenError("Só quem fez a solicitação pode confirmar o recebimento dela.")
    if solicitacao["status"] != "entregue":
        raise ApiError(f"Só é possível confirmar recebimento de uma solicitação 'entregue' (status atual: '{solicitacao['status']}').", status=400)

    conn.execute(
        "UPDATE solicitacoes_material SET status = 'recebimento_confirmado', recebimento_confirmado_em = ? WHERE id = ?",
        (_now_iso(), solicitacao_id),
    )
    audit.registrar(conn, tabela="solicitacoes_material", registro_id=solicitacao_id, usuario_id=usuario_atual["id"],
                     acao="solicitacao_material_recebimento_confirmado", valor_anterior={"status": "entregue"},
                     valor_novo={"status": "recebimento_confirmado"}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_solicitacao_detalhada(conn, solicitacao_id))


@bp.post("/<int:solicitacao_id>/cancelar")
@requires_permission("solicitacoes_material", "solicitar")
def cancelar_solicitacao(solicitacao_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()
    solicitacao = _solicitacao_ou_404(conn, solicitacao_id)

    if solicitacao["solicitante_id"] != usuario_atual["id"]:
        raise ForbiddenError("Só quem fez a solicitação pode cancelá-la.")
    if solicitacao["status"] != "pendente":
        raise ApiError(
            f"Só é possível cancelar uma solicitação ainda 'pendente' (status atual: '{solicitacao['status']}') — "
            "uma já aprovada precisa ser tratada por quem aprova.",
            status=400,
        )

    conn.execute(
        "UPDATE solicitacoes_material SET status = 'cancelada', motivo_cancelamento = ?, cancelado_em = ?, cancelado_por = ? WHERE id = ?",
        (motivo or None, _now_iso(), usuario_atual["id"], solicitacao_id),
    )
    audit.registrar(conn, tabela="solicitacoes_material", registro_id=solicitacao_id, usuario_id=usuario_atual["id"],
                     acao="solicitacao_material_cancelada", valor_anterior={"status": "pendente"},
                     valor_novo={"status": "cancelada", "motivo": motivo}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_solicitacao_detalhada(conn, solicitacao_id))


# ============================================================
# COMPROVANTE DE ENTREGA (PDF) — Ficha de EPI (NR-6) quando aplicável
# ============================================================
@bp.get("/<int:solicitacao_id>/comprovante/pdf")
@requires_permission("solicitacoes_material", "visualizar")
def comprovante_pdf(solicitacao_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    solicitacao = _solicitacao_detalhada(conn, solicitacao_id)

    if solicitacao["status"] not in ("entregue", "recebimento_confirmado"):
        raise ApiError("Esta solicitação ainda não foi entregue — não há comprovante para gerar ainda.", status=400)

    tem_epi = any(item["material_e_epi"] for item in solicitacao["itens"])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("Titulo", parent=estilos["Title"], fontSize=16, alignment=TA_CENTER, spaceAfter=2)
    estilo_subtitulo = ParagraphStyle(
        "Subtitulo", parent=estilos["Normal"], fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor("#5a6472"), spaceAfter=16,
    )
    estilo_secao = ParagraphStyle(
        "Secao", parent=estilos["Heading3"], fontSize=11, spaceBefore=12, spaceAfter=6,
        textColor=colors.HexColor("#1f3a5f"),
    )

    titulo = "Ficha de Controle de Fornecimento de EPI" if tem_epi else "Comprovante de Entrega de Material"
    elementos = [
        Paragraph("Alphafitus Nutracêuticos Ltda.", estilo_titulo),
        Paragraph(titulo, estilo_subtitulo),
    ]

    dados_gerais = [
        ["Número da solicitação", solicitacao["numero"]],
        ["Solicitante", solicitacao["solicitante_nome"] or "—"],
        ["Setor", solicitacao["setor_solicitante"] or "—"],
        ["Justificativa", solicitacao["justificativa"]],
        ["Aprovado por", solicitacao["aprovador_nome"] or "—"],
        ["Aprovado em", solicitacao["decidido_em"] or "—"],
        ["Entregue por", solicitacao["entregador_nome"] or "—"],
        ["Entregue em", solicitacao["entregue_em"] or "—"],
        ["Recebimento confirmado pelo solicitante em", solicitacao["recebimento_confirmado_em"] or "Ainda não confirmado"],
    ]
    tabela_geral = Table(dados_gerais, colWidths=[6 * cm, 10 * cm])
    tabela_geral.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#5a6472")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
    ]))
    elementos.append(tabela_geral)

    elementos.append(Paragraph("Itens entregues", estilo_secao))
    cabecalho = ["Item", "C.A." if tem_epi else "", "Qtd. solicitada", "Qtd. entregue", "Especificação"]
    linhas = [cabecalho]
    for item in solicitacao["itens"]:
        linhas.append([
            f"{item['material_codigo']} — {item['material_descricao']}",
            item["material_numero_ca"] or "—" if item["material_e_epi"] else "",
            str(item["quantidade_solicitada"]),
            str(item["quantidade_entregue"]) if item["quantidade_entregue"] is not None else "—",
            item["especificacao"] or "—",
        ])
    tabela_itens = Table(linhas, colWidths=[6 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 3 * cm])
    tabela_itens.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementos.append(tabela_itens)

    if tem_epi:
        elementos.append(Spacer(1, 20))
        elementos.append(Paragraph(
            "Declaro ter recebido treinamento sobre o uso correto do(s) Equipamento(s) de Proteção Individual "
            "acima, e estar ciente da obrigatoriedade de uso conforme a NR-6, sob pena das sanções previstas.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 30))
        elementos.append(Paragraph("_" * 40, estilos["Normal"]))
        elementos.append(Paragraph(f"Assinatura — {solicitacao['solicitante_nome'] or ''}", estilos["Normal"]))

    elementos.append(Spacer(1, 24))
    elementos.append(Paragraph(
        "Documento gerado automaticamente a partir dos registros eletrônicos do Alphafitus OS, com trilha de "
        "auditoria imutável de cada etapa (solicitação, aprovação, entrega e confirmação de recebimento).",
        ParagraphStyle("Rodape", parent=estilos["Normal"], fontSize=8, textColor=colors.HexColor("#5a6472")),
    ))

    doc.build(elementos, onFirstPage=desenhar_cabecalho_logo, onLaterPages=desenhar_cabecalho_logo)
    pdf_bytes = buffer.getvalue()

    audit.registrar(conn, tabela="solicitacoes_material", registro_id=solicitacao_id, usuario_id=usuario_atual["id"],
                     acao="solicitacao_material_comprovante_pdf_gerado", valor_novo={"numero": solicitacao["numero"]},
                     ip=client_ip(), dispositivo=client_device())

    nome_arquivo = f"Comprovante-{solicitacao['numero']}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
