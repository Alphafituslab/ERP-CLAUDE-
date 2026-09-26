"""
Fase 197 — Orçamentos (proposta comercial formal com aprovação por link).

Pedido do usuário: uma proposta de verdade pro cliente — capa, validade,
condições — enviável por link público (mesmo mecanismo do Portal de
Contrato/Terceirização: token opaco ~256 bits, expira, revoga o anterior
ao emitir um novo). O cliente abre sem login e aprova ou recusa; ao
aprovar, o sistema gera um Pedido de Venda de VERDADE (mesma tabela que o
Comercial já usa — `pedidos_venda`/`pedido_venda_itens`) automaticamente,
sem digitar tudo de novo. Preço de cada item é digitado na hora da
proposta (pode sugerir a partir da tabela de preço do cliente, mas nunca
travado nela — cada orçamento negocia o próprio preço).

Cliente BLOQUEADO financeiramente (`aprovacao_financeira_status !=
'aprovado'`) ainda pode ter orçamento gerado e enviado normalmente — a
trava de verdade é só na hora de aprovar/converter em pedido, igual já
acontece pro Pedido de Venda manual (Fase 102: a aprovação financeira do
CLIENTE trava a CONFIRMAÇÃO do pedido, não a criação de propostas).
"""
import datetime
import secrets as secrets_lib

from flask import Blueprint, Response, g, jsonify, request

from .. import audit
from .. import backup_service
from .. import whatts_contatos_service
from ..context import ApiError, client_device, client_ip, get_db
from ..pdf_marca import desenhar_cabecalho_formal
from ..permissions import requires_auth, requires_permission
from . import comercial as com  # reaproveita _cliente_ou_404/_validar_item_vendavel — nunca duplica a query

bp = Blueprint("orcamentos", __name__, url_prefix="/api/v1/orcamentos")

# Mesmo esquema de URL pública dos outros portais (Contrato/Terceirização)
URL_BASE_PORTAL_PUBLICO = "https://whatts.alphafitus.com.br:9445"
TTL_LINK_PORTAL_DIAS = 30
STATUS_EDITAVEL = ("rascunho",)


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _expira_em_daqui_a_dias(dias):
    return (datetime.datetime.utcnow() + datetime.timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _gerar_numero_orcamento(conn):
    ano = datetime.datetime.utcnow().year
    total = conn.execute("SELECT COUNT(*) AS c FROM orcamentos WHERE numero LIKE ?", (f"ORC-{ano}-%",)).fetchone()["c"]
    return f"ORC-{ano}-{total + 1:06d}"


def _orcamento_ou_404(conn, orcamento_id):
    row = conn.execute("SELECT * FROM orcamentos WHERE id = ?", (orcamento_id,)).fetchone()
    if row is None:
        raise ApiError("Orçamento não encontrado.", status=404)
    return dict(row)


def orcamento_detalhado(conn, orcamento_id):
    orcamento = _orcamento_ou_404(conn, orcamento_id)
    itens = conn.execute(
        """
        SELECT oi.*, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM orcamento_itens oi JOIN itens i ON i.id = oi.item_id
        WHERE oi.orcamento_id = ? ORDER BY oi.id
        """,
        (orcamento_id,),
    ).fetchall()
    orcamento["itens"] = [dict(r) for r in itens]
    orcamento["valor_total"] = round(sum(i["quantidade"] * i["preco_unitario"] for i in orcamento["itens"]), 2)
    cliente = conn.execute("SELECT id, razao_social, cnpj, aprovacao_financeira_status, telefone FROM clientes WHERE id = ?", (orcamento["cliente_id"],)).fetchone()
    orcamento["cliente"] = dict(cliente) if cliente else None
    link_ativo = conn.execute(
        "SELECT token, expira_em FROM orcamento_links_portal WHERE orcamento_id = ? AND revogado = 0", (orcamento_id,)
    ).fetchone()
    orcamento["link_portal"] = f"{URL_BASE_PORTAL_PUBLICO}/portal/orcamento/{link_ativo['token']}" if link_ativo else None
    return orcamento


def _validar_e_gravar_itens(conn, orcamento_id, itens):
    if not itens:
        raise ApiError("Informe ao menos um item em 'itens'.", status=400)
    conn.execute("DELETE FROM orcamento_itens WHERE orcamento_id = ?", (orcamento_id,))
    for linha in itens:
        item_id = linha.get("item_id")
        quantidade = linha.get("quantidade")
        preco_unitario = linha.get("preco_unitario")
        unidade = linha.get("unidade")
        if not item_id or not quantidade or preco_unitario is None:
            raise ApiError("Cada item precisa de item_id, quantidade e preco_unitario.", status=400)
        try:
            quantidade = float(quantidade)
            preco_unitario = float(preco_unitario)
        except (TypeError, ValueError):
            raise ApiError("quantidade e preco_unitario devem ser numéricos.", status=400)
        if quantidade <= 0:
            raise ApiError("quantidade deve ser maior que zero.", status=400)
        if preco_unitario < 0:
            raise ApiError("preco_unitario não pode ser negativo.", status=400)
        com._validar_item_vendavel(conn, item_id)
        conn.execute(
            "INSERT INTO orcamento_itens (orcamento_id, item_id, quantidade, unidade, preco_unitario) VALUES (?, ?, ?, ?, ?)",
            (orcamento_id, item_id, quantidade, unidade, preco_unitario),
        )


@bp.get("")
@requires_permission("orcamentos", "visualizar")
def listar_orcamentos():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT o.*, c.razao_social AS cliente_razao_social
        FROM orcamentos o JOIN clientes c ON c.id = o.cliente_id
        ORDER BY o.criado_em DESC
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:orcamento_id>")
@requires_permission("orcamentos", "visualizar")
def obter_orcamento(orcamento_id):
    return jsonify(orcamento_detalhado(get_db(), orcamento_id))


@bp.post("")
@requires_permission("orcamentos", "criar")
def criar_orcamento():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    cliente_id = dados.get("cliente_id")
    itens = dados.get("itens") or []
    conn = get_db()

    if not cliente_id:
        raise ApiError("Informe cliente_id.", status=400)
    com._cliente_ou_404(conn, cliente_id)  # 404 se não existir — não exige aprovado (ver docstring do módulo)

    condicao_pagamento_id = dados.get("condicao_pagamento_id")
    if condicao_pagamento_id is not None:
        if not conn.execute("SELECT 1 FROM condicoes_pagamento WHERE id = ? AND ativo = 1", (condicao_pagamento_id,)).fetchone():
            raise ApiError("Condição de pagamento não encontrada ou inativa.", status=404)

    numero = _gerar_numero_orcamento(conn)
    cur = conn.execute(
        """
        INSERT INTO orcamentos (numero, cliente_id, vendedor_id, empresa_id, condicao_pagamento_id,
                                 validade_dias, condicoes_texto, observacoes, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            numero, cliente_id, dados.get("vendedor_id"), dados.get("empresa_id"), condicao_pagamento_id,
            dados.get("validade_dias") or 15, dados.get("condicoes_texto"), dados.get("observacoes"),
            usuario_atual["id"],
        ),
    )
    orcamento_id = cur.lastrowid
    _validar_e_gravar_itens(conn, orcamento_id, itens)

    audit.registrar(conn, tabela="orcamentos", registro_id=orcamento_id, usuario_id=usuario_atual["id"],
                     acao="orcamento_criado", valor_novo={"numero": numero, "cliente_id": cliente_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(orcamento_detalhado(conn, orcamento_id)), 201


@bp.put("/<int:orcamento_id>")
@requires_permission("orcamentos", "criar")
def editar_orcamento(orcamento_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    orcamento = _orcamento_ou_404(conn, orcamento_id)
    if orcamento["status"] not in STATUS_EDITAVEL:
        raise ApiError("Só é possível editar um orçamento em rascunho.", status=400)

    dados = request.get_json(silent=True) or {}
    anterior = orcamento_detalhado(conn, orcamento_id)
    conn.execute(
        """
        UPDATE orcamentos SET condicao_pagamento_id = ?, validade_dias = ?, condicoes_texto = ?,
               observacoes = ?, atualizado_em = ?, atualizado_por = ? WHERE id = ?
        """,
        (
            dados.get("condicao_pagamento_id", orcamento["condicao_pagamento_id"]),
            dados.get("validade_dias", orcamento["validade_dias"]),
            dados.get("condicoes_texto", orcamento["condicoes_texto"]),
            dados.get("observacoes", orcamento["observacoes"]),
            _now_iso(), usuario_atual["id"], orcamento_id,
        ),
    )
    if "itens" in dados:
        _validar_e_gravar_itens(conn, orcamento_id, dados["itens"])

    novo = orcamento_detalhado(conn, orcamento_id)
    audit.registrar(conn, tabela="orcamentos", registro_id=orcamento_id, usuario_id=usuario_atual["id"],
                     acao="orcamento_editado", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.post("/<int:orcamento_id>/cancelar")
@requires_permission("orcamentos", "cancelar")
def cancelar_orcamento(orcamento_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    orcamento = _orcamento_ou_404(conn, orcamento_id)
    if orcamento["status"] in ("aprovado", "cancelado"):
        raise ApiError(f"Não é possível cancelar um orçamento '{orcamento['status']}'.", status=400)
    conn.execute("UPDATE orcamentos SET status = 'cancelado', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
                 (_now_iso(), usuario_atual["id"], orcamento_id))
    conn.execute("UPDATE orcamento_links_portal SET revogado = 1 WHERE orcamento_id = ? AND revogado = 0", (orcamento_id,))
    audit.registrar(conn, tabela="orcamentos", registro_id=orcamento_id, usuario_id=usuario_atual["id"],
                     acao="orcamento_cancelado", ip=client_ip(), dispositivo=client_device())
    return jsonify(orcamento_detalhado(conn, orcamento_id))


@bp.get("/contatos-whatsapp")
@requires_permission("orcamentos", "criar")
def buscar_contatos_whatsapp_orcamento():
    """Fase 222 — pedido do usuário: em vez de mandar direto pro telefone
    genérico do cadastro do cliente (achado real: um número de linha fixa
    sem WhatsApp derrubou o envio), busca nos contatos JÁ SALVOS no WhatsApp
    integrado (Whatts Inbox) — a mesma lista que a pessoa já vê lá dentro."""
    termo = request.args.get("termo", "")
    if len(termo.strip()) < 3:
        return jsonify([])
    return jsonify(whatts_contatos_service.buscar_contatos(termo))


@bp.post("/<int:orcamento_id>/link")
@requires_permission("orcamentos", "criar")
def gerar_link_orcamento(orcamento_id):
    """Gera (ou renova — revoga o anterior primeiro) o link de aprovação
    deste orçamento. `enviar_whatsapp: true` manda a mensagem na hora.

    Fase 222 — o número usado é sempre um CONTATO de WhatsApp escolhido na
    tela (`telefone_whatsapp`, com `nome_contato` opcional pra salvar um
    contato novo) — nunca mais o `clientes.telefone` cego de antes (podia
    ser uma linha fixa sem WhatsApp, como aconteceu de verdade em produção).
    `telefone_whatsapp` continua opcional por retrocompatibilidade de API,
    mas a tela sempre manda."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    orcamento = _orcamento_ou_404(conn, orcamento_id)
    if orcamento["status"] in ("cancelado", "aprovado"):
        raise ApiError(f"Não é possível gerar link para um orçamento '{orcamento['status']}'.", status=400)
    cliente = com._cliente_ou_404(conn, orcamento["cliente_id"])

    dados = request.get_json(silent=True) or {}
    enviar_whatsapp = bool(dados.get("enviar_whatsapp"))
    telefone_escolhido = (dados.get("telefone_whatsapp") or "").strip()
    nome_contato = (dados.get("nome_contato") or "").strip() or cliente.get("razao_social")

    conn.execute("UPDATE orcamento_links_portal SET revogado = 1 WHERE orcamento_id = ? AND revogado = 0", (orcamento_id,))
    token = secrets_lib.token_urlsafe(32)
    expira_em = _expira_em_daqui_a_dias(TTL_LINK_PORTAL_DIAS)
    conn.execute(
        "INSERT INTO orcamento_links_portal (orcamento_id, token, criado_por, expira_em) VALUES (?, ?, ?, ?)",
        (orcamento_id, token, usuario_atual["id"], expira_em),
    )
    url = f"{URL_BASE_PORTAL_PUBLICO}/portal/orcamento/{token}"

    enviado_com_sucesso = False
    erro_envio = None
    if enviar_whatsapp:
        telefone = telefone_escolhido or (cliente.get("telefone") or "").strip()
        if not telefone:
            erro_envio = "Escolha (ou cadastre) um contato de WhatsApp pra enviar."
        else:
            try:
                numero = backup_service.normalizar_numero_brasileiro(telefone)
                whatts_contatos_service.salvar_contato(nome_contato, numero)
                config = backup_service.obter_configuracao(conn)
                texto = (
                    f"Olá! Segue o orçamento {orcamento['numero']} da Alphafitus para sua aprovação:\n{url}\n\n"
                    f"O link expira em {TTL_LINK_PORTAL_DIAS} dias."
                )
                backup_service.enviar_texto_whatsapp(config, numero, texto)
                enviado_com_sucesso = True
                conn.execute("UPDATE orcamento_links_portal SET enviado_via_whatsapp = 1 WHERE token = ?", (token,))
            except Exception as erro:
                erro_envio = str(erro)

    if orcamento["status"] == "rascunho":
        conn.execute("UPDATE orcamentos SET status = 'enviado', atualizado_em = ? WHERE id = ?", (_now_iso(), orcamento_id))

    audit.registrar(conn, tabela="orcamentos", registro_id=orcamento_id, usuario_id=usuario_atual["id"],
                     acao="link_gerado", valor_novo={"expira_em": expira_em}, ip=client_ip(), dispositivo=client_device())
    return jsonify({"url": url, "expira_em": expira_em, "enviado_via_whatsapp": enviado_com_sucesso, "erro_envio_whatsapp": erro_envio})


@bp.get("/<int:orcamento_id>/pdf")
@requires_permission("orcamentos", "visualizar")
def baixar_pdf_orcamento(orcamento_id):
    conn = get_db()
    orcamento = orcamento_detalhado(conn, orcamento_id)
    pdf_bytes = gerar_pdf_orcamento(orcamento)
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{orcamento["numero"]}.pdf"'},
    )


def gerar_pdf_orcamento(orcamento):
    """Documento formal da proposta — mesmo cabeçalho institucional dos
    Contratos (`desenhar_cabecalho_formal`, Fase 147), pra ter a mesma
    cara de empresa grande em qualquer papel que sai daqui."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    cor_titulo = colors.HexColor("#1a3c2e")
    cor_dourado = colors.HexColor("#a8863f")
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("TituloOrcamento", parent=estilos["Title"], textColor=cor_titulo, alignment=TA_CENTER, fontSize=15, spaceAfter=6)
    estilo_normal = ParagraphStyle("NormalOrcamento", parent=estilos["Normal"], fontSize=9.5, leading=13, spaceAfter=6)
    estilo_suave = ParagraphStyle("SuaveOrcamento", parent=estilos["Normal"], textColor=colors.HexColor("#666666"), fontSize=8.5)

    cliente = orcamento["cliente"] or {}
    criado_em = datetime.datetime.fromisoformat(orcamento["criado_em"].replace("Z", ""))
    validade = criado_em + datetime.timedelta(days=orcamento["validade_dias"])

    elementos = [
        Spacer(1, 0.6 * cm),
        Paragraph("PROPOSTA COMERCIAL / ORÇAMENTO", estilo_titulo),
        HRFlowable(width="100%", thickness=1, color=cor_dourado, spaceAfter=10),
        Paragraph(f"<b>Nº:</b> {escape(orcamento['numero'])} &nbsp;&nbsp; <b>Data:</b> {criado_em.strftime('%d/%m/%Y')} &nbsp;&nbsp; <b>Válido até:</b> {validade.strftime('%d/%m/%Y')}", estilo_normal),
        Paragraph(f"<b>Cliente:</b> {escape(cliente.get('razao_social') or '—')} &nbsp;&nbsp; <b>CNPJ:</b> {escape(cliente.get('cnpj') or '—')}", estilo_normal),
        Spacer(1, 0.3 * cm),
    ]

    estilo_cab = ParagraphStyle("CabOrc", parent=estilo_normal, textColor=colors.white, fontName="Helvetica-Bold", fontSize=9, spaceAfter=0)
    estilo_cel = ParagraphStyle("CelOrc", parent=estilo_normal, fontSize=8.5, leading=11, spaceAfter=0)
    estilo_cel_num = ParagraphStyle("CelOrcNum", parent=estilo_cel, alignment=TA_RIGHT)
    linhas = [[Paragraph(t, estilo_cab) for t in ("Produto", "Qtd.", "Preço unit.", "Subtotal")]]
    for it in orcamento["itens"]:
        subtotal = it["quantidade"] * it["preco_unitario"]
        linhas.append([
            Paragraph(escape(it["item_descricao"]), estilo_cel),
            Paragraph(f"{it['quantidade']:g} {escape(it.get('unidade') or '')}", estilo_cel_num),
            Paragraph(f"R$ {it['preco_unitario']:.2f}", estilo_cel_num),
            Paragraph(f"R$ {subtotal:.2f}", estilo_cel_num),
        ])
    tabela = Table(linhas, colWidths=[7.5 * cm, 3 * cm, 3 * cm, 3 * cm], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), cor_titulo),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f5ef")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementos.append(tabela)
    elementos.append(Spacer(1, 0.3 * cm))
    elementos.append(Paragraph(f"<b>Valor total:</b> R$ {orcamento['valor_total']:.2f}", ParagraphStyle("Total", parent=estilo_normal, alignment=TA_RIGHT, fontSize=12)))

    if orcamento.get("condicoes_texto"):
        elementos.append(Paragraph(f"<b>Condições:</b> {escape(orcamento['condicoes_texto'])}", estilo_normal))
    if orcamento.get("observacoes"):
        elementos.append(Paragraph(f"<b>Observações:</b> {escape(orcamento['observacoes'])}", estilo_normal))
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(Paragraph("Esta proposta é válida até a data indicada acima. A aprovação pode ser feita pelo link enviado, sem necessidade de login.", estilo_suave))

    buffer = __import__("io").BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=3.4 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm)
    doc.build(elementos, onFirstPage=desenhar_cabecalho_formal, onLaterPages=desenhar_cabecalho_formal)
    return buffer.getvalue()
