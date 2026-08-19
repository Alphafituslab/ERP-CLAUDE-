"""
Fase 8 — Rastreabilidade Avançada / Simulação de Recall.

Requisito de GMP: dado qualquer lote, ser capaz de responder, em minutos,
duas perguntas — "de onde veio o material deste lote" (matérias-primas e
fornecedores, atravessando quantos níveis de produção intermediária forem
necessários) e "para onde este lote foi" (outros lotes produzidos a partir
dele e, no final da cadeia, quais pedidos e clientes o receberam).

A resposta é um traversal RECURSIVO sobre tabelas que já existem desde as
Fases 3 e 5 (`ordem_producao_consumo` e `pedido_venda_reservas`) — nenhuma
tabela nova é necessária para calcular isso, e o resultado nunca é
guardado como um valor derivado que poderia dessincronizar (mesmo
princípio de todas as fases anteriores).

A única coisa nova de fato é `simulacoes_recall`: um registro histórico e
IMUTÁVEL de que uma investigação foi executada, com um motivo obrigatório
e um snapshot completo do resultado no momento em que foi executada — este
sim é guardado de propósito (não recalculado depois), porque um recall é
uma decisão de conformidade documentada num ponto do tempo, não um saldo
que deveria sempre refletir o estado atual do banco.
"""
import datetime
import io
import json
import secrets

from flask import Blueprint, Response, g, jsonify, request
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..pdf_marca import desenhar_cabecalho_logo
from ..permissions import requires_permission
from .lotes import bloquear_lote_interno

bp = Blueprint("rastreabilidade", __name__, url_prefix="/api/v1/rastreabilidade")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _gerar_numero_recall():
    ano = datetime.datetime.utcnow().year
    return f"RCL-{ano}-{secrets.token_hex(4).upper()}"


def _lote_basico(conn, lote_id):
    row = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if row is None:
        return None
    lote = dict(row)
    item = conn.execute("SELECT codigo, descricao, tipo FROM itens WHERE id = ?", (lote["item_id"],)).fetchone()
    lote["item_codigo"] = item["codigo"] if item else None
    lote["item_descricao"] = item["descricao"] if item else None
    lote["item_tipo"] = item["tipo"] if item else None
    return lote


def _traversal_upstream(conn, lote_id, visitados=None):
    """Para trás: de que lotes (matéria-prima, embalagem, produto
    intermediário) o lote informado foi produzido — recursivamente, até
    chegar em lotes recebidos de fornecedor (as folhas da árvore)."""
    if visitados is None:
        visitados = set()

    lote = _lote_basico(conn, lote_id)
    if lote is None:
        return None

    node = {
        "lote_id": lote["id"],
        "codigo_lote": lote["codigo_lote"],
        "item_codigo": lote["item_codigo"],
        "item_descricao": lote["item_descricao"],
        "item_tipo": lote["item_tipo"],
        "status": lote["status"],
        "origem": lote["origem"],
        "fornecedor": None,
        "ordem_producao": None,
        "componentes": [],
    }
    if lote["fornecedor_id"]:
        forn = conn.execute("SELECT id, nome, cnpj FROM fornecedores WHERE id = ?", (lote["fornecedor_id"],)).fetchone()
        node["fornecedor"] = dict(forn) if forn else None

    if lote["origem"] == "producao" and lote.get("ordem_producao_id") and lote_id not in visitados:
        visitados.add(lote_id)
        ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (lote["ordem_producao_id"],)).fetchone()
        if ordem:
            ordem = dict(ordem)
            node["ordem_producao"] = {"id": ordem["id"], "numero": ordem["numero"], "status": ordem["status"]}
            consumos = conn.execute(
                """
                SELECT lote_id, SUM(quantidade) AS quantidade_consumida
                FROM ordem_producao_consumo
                WHERE ordem_producao_id = ?
                GROUP BY lote_id
                ORDER BY lote_id
                """,
                (ordem["id"],),
            ).fetchall()
            for c in consumos:
                sub = _traversal_upstream(conn, c["lote_id"], visitados)
                if sub is not None:
                    sub = dict(sub)
                    sub["quantidade_consumida_nesta_ordem"] = c["quantidade_consumida"]
                    node["componentes"].append(sub)

    return node


def _traversal_downstream(conn, lote_id, visitados=None):
    """Para frente: em que ordens de produção este lote foi consumido (e
    que lote cada uma gerou, recursivamente) e para quais pedidos de venda
    (e clientes) o material deste lote acabou indo, direta ou
    indiretamente através de produtos feitos a partir dele."""
    if visitados is None:
        visitados = set()

    lote = _lote_basico(conn, lote_id)
    if lote is None:
        return None

    node = {
        "lote_id": lote["id"],
        "codigo_lote": lote["codigo_lote"],
        "item_codigo": lote["item_codigo"],
        "item_descricao": lote["item_descricao"],
        "item_tipo": lote["item_tipo"],
        "status": lote["status"],
        "usado_em_producao": [],
        "pedidos": [],
    }

    if lote_id in visitados:
        return node
    visitados.add(lote_id)

    consumos = conn.execute(
        """
        SELECT ordem_producao_id, SUM(quantidade) AS quantidade_consumida
        FROM ordem_producao_consumo
        WHERE lote_id = ?
        GROUP BY ordem_producao_id
        ORDER BY ordem_producao_id
        """,
        (lote_id,),
    ).fetchall()
    for c in consumos:
        ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (c["ordem_producao_id"],)).fetchone()
        if ordem is None:
            continue
        ordem = dict(ordem)
        entrada = {
            "ordem_producao": {"id": ordem["id"], "numero": ordem["numero"], "status": ordem["status"]},
            "quantidade_consumida": c["quantidade_consumida"],
            "lote_gerado": None,
        }
        if ordem.get("lote_produzido_id"):
            entrada["lote_gerado"] = _traversal_downstream(conn, ordem["lote_produzido_id"], visitados)
        node["usado_em_producao"].append(entrada)

    reservas = conn.execute(
        """
        SELECT pvr.pedido_item_id, pvr.quantidade, pvi.pedido_id
        FROM pedido_venda_reservas pvr
        JOIN pedido_venda_itens pvi ON pvi.id = pvr.pedido_item_id
        WHERE pvr.lote_id = ?
        """,
        (lote_id,),
    ).fetchall()
    quantidade_por_pedido = {}
    for r in reservas:
        quantidade_por_pedido[r["pedido_id"]] = quantidade_por_pedido.get(r["pedido_id"], 0) + r["quantidade"]

    for pedido_id, quantidade in sorted(quantidade_por_pedido.items()):
        pedido = conn.execute("SELECT * FROM pedidos_venda WHERE id = ?", (pedido_id,)).fetchone()
        if pedido is None:
            continue
        pedido = dict(pedido)
        cliente = conn.execute(
            "SELECT id, razao_social, cnpj FROM clientes WHERE id = ?", (pedido["cliente_id"],)
        ).fetchone()
        node["pedidos"].append({
            "pedido_id": pedido_id,
            "numero": pedido["numero"],
            "status": pedido["status"],
            "quantidade_reservada": quantidade,
            "cliente": dict(cliente) if cliente else None,
        })

    return node


def _contar_upstream(node, coletados=None):
    if coletados is None:
        coletados = set()
    if node is None:
        return coletados
    coletados.add(node["lote_id"])
    for c in node.get("componentes", []):
        _contar_upstream(c, coletados)
    return coletados


def _coletar_downstream(node, lotes=None, pedidos=None):
    if lotes is None:
        lotes = set()
    if pedidos is None:
        pedidos = {}
    if node is None:
        return lotes, pedidos
    lotes.add(node["lote_id"])
    for p in node.get("pedidos", []):
        pedidos[p["pedido_id"]] = p
    for u in node.get("usado_em_producao", []):
        if u.get("lote_gerado"):
            _coletar_downstream(u["lote_gerado"], lotes, pedidos)
    return lotes, pedidos


def _lotes_afetados(resultado):
    """A partir do mesmo dicionário devolvido por `_montar_genealogia_completa`
    (ou do snapshot já salvo em `simulacoes_recall.resultado` — o formato é
    idêntico), devolve o conjunto de `lote_id` afetados pelo recall: o
    próprio lote investigado, mais todo o upstream e downstream — usado
    pelo bloqueio em massa (Fase 16). Reaproveita `_contar_upstream` e
    `_coletar_downstream`, os mesmos helpers já usados para montar o
    resumo da simulação, para nunca haver dois jeitos divergentes de
    andar por essas árvores."""
    ids = {resultado["lote_investigado"]["lote_id"]}
    ids |= _contar_upstream(resultado.get("upstream"))
    lotes_downstream, _pedidos = _coletar_downstream(resultado.get("downstream"))
    ids |= lotes_downstream
    return ids


def _montar_genealogia_completa(conn, lote_id):
    lote = _lote_basico(conn, lote_id)
    if lote is None:
        raise ApiError("Lote não encontrado.", status=404)

    upstream = _traversal_upstream(conn, lote_id)
    downstream = _traversal_downstream(conn, lote_id)

    lotes_upstream = _contar_upstream(upstream)
    lotes_upstream.discard(lote_id)

    lotes_downstream, pedidos_por_id = _coletar_downstream(downstream)
    lotes_downstream.discard(lote_id)

    pedidos_expedidos = [p for p in pedidos_por_id.values() if p["status"] == "expedido"]
    pedidos_nao_expedidos = [p for p in pedidos_por_id.values() if p["status"] != "expedido"]
    clientes_afetados = {p["cliente"]["id"] for p in pedidos_expedidos if p.get("cliente")}

    return {
        "lote_investigado": {
            "lote_id": lote["id"],
            "codigo_lote": lote["codigo_lote"],
            "item_codigo": lote["item_codigo"],
            "item_descricao": lote["item_descricao"],
            "item_tipo": lote["item_tipo"],
            "status": lote["status"],
        },
        "upstream": upstream,
        "downstream": downstream,
        "resumo": {
            "total_lotes_upstream": len(lotes_upstream),
            "total_lotes_downstream": len(lotes_downstream),
            "pedidos_expedidos": pedidos_expedidos,
            "pedidos_reservados_nao_expedidos": pedidos_nao_expedidos,
            "total_clientes_afetados": len(clientes_afetados),
        },
    }


def _achatar_upstream(node, saida=None, vistos=None, eh_raiz=True):
    """Achata a árvore de upstream (formato de `_traversal_upstream`) numa
    lista simples de linhas para a tabela do relatório em PDF — o lote
    investigado (raiz) fica de fora, e cada `lote_id` aparece só uma vez
    mesmo que tenha sido consumido em mais de uma ordem de produção."""
    if saida is None:
        saida = []
    if vistos is None:
        vistos = set()
    if node is None:
        return saida
    if not eh_raiz and node["lote_id"] not in vistos:
        vistos.add(node["lote_id"])
        origem = "—"
        if node.get("fornecedor"):
            origem = f"Fornecedor: {node['fornecedor']['nome']}"
        elif node.get("ordem_producao"):
            origem = f"Ordem de produção {node['ordem_producao']['numero']}"
        saida.append({
            "codigo_lote": node["codigo_lote"],
            "item": f"{node['item_codigo']} — {node['item_descricao']}",
            "origem": origem,
        })
    for c in node.get("componentes", []):
        _achatar_upstream(c, saida, vistos, eh_raiz=False)
    return saida


def _achatar_downstream(node, saida=None, vistos=None, eh_raiz=True):
    """Achata a árvore de downstream (formato de `_traversal_downstream`)
    numa lista simples de linhas para a tabela do relatório em PDF — mesmo
    princípio de `_achatar_upstream`: raiz de fora, cada lote uma vez só."""
    if saida is None:
        saida = []
    if vistos is None:
        vistos = set()
    if node is None:
        return saida
    if not eh_raiz and node["lote_id"] not in vistos:
        vistos.add(node["lote_id"])
        saida.append({
            "codigo_lote": node["codigo_lote"],
            "item": f"{node['item_codigo']} — {node['item_descricao']}",
            "status": node["status"],
        })
    for u in node.get("usado_em_producao", []):
        if u.get("lote_gerado"):
            _achatar_downstream(u["lote_gerado"], saida, vistos, eh_raiz=False)
    return saida


def _gerar_pdf_recall(simulacao):
    """Monta o relatório em PDF de uma simulação de recall já registrada,
    a partir do snapshot imutável salvo em `simulacoes_recall.resultado` —
    mesmo padrão da Fase 10 (CoA): um export puro, sem alterar nenhum dado
    de negócio, formatando com reportlab (platypus) o que já está gravado
    no banco. Devolve os bytes do PDF pronto."""
    resultado = simulacao["resultado"]
    resumo = resultado["resumo"]
    lote_investigado = resultado["lote_investigado"]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        "TituloRecall", parent=estilos["Title"], fontSize=16, alignment=TA_CENTER, spaceAfter=2,
    )
    estilo_subtitulo = ParagraphStyle(
        "SubtituloRecall", parent=estilos["Normal"], fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor("#5a6472"), spaceAfter=16,
    )
    estilo_rotulo_secao = ParagraphStyle(
        "RotuloSecaoRecall", parent=estilos["Heading3"], fontSize=11, spaceBefore=12, spaceAfter=6,
        textColor=colors.HexColor("#1f3a5f"),
    )

    elementos = [
        Paragraph("Alphafitus Laboratório Nutracêutico Ltda.", estilo_titulo),
        Paragraph("Relatório de Simulação de Recall", estilo_subtitulo),
    ]

    dados_gerais = [
        ["Número da simulação", simulacao["numero"]],
        ["Lote investigado", lote_investigado["codigo_lote"]],
        ["Item", f"{lote_investigado['item_codigo']} — {lote_investigado['item_descricao']}"],
        ["Motivo da investigação", simulacao["motivo"]],
        ["Registrado por", simulacao.get("criado_por_nome") or "—"],
        ["Registrado em", simulacao["criado_em"]],
    ]
    tabela_geral = Table(dados_gerais, colWidths=[5 * cm, 11 * cm])
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

    elementos.append(Paragraph("Resumo do impacto", estilo_rotulo_secao))
    linhas_resumo = [
        ["Indicador", "Quantidade"],
        ["Lotes acima na cadeia (upstream — matéria-prima/fornecedores)", str(resumo["total_lotes_upstream"])],
        ["Lotes abaixo na cadeia (downstream — produtos derivados)", str(resumo["total_lotes_downstream"])],
        ["Pedidos já expedidos afetados", str(len(resumo["pedidos_expedidos"]))],
        ["Pedidos reservados, ainda não expedidos", str(len(resumo["pedidos_reservados_nao_expedidos"]))],
        ["Clientes afetados", str(resumo["total_clientes_afetados"])],
    ]
    tabela_resumo = Table(linhas_resumo, colWidths=[11 * cm, 5 * cm])
    tabela_resumo.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementos.append(tabela_resumo)

    elementos.append(Paragraph("Pedidos já expedidos afetados (clientes a notificar)", estilo_rotulo_secao))
    if resumo["pedidos_expedidos"]:
        cabecalho = ["Pedido", "Cliente", "CNPJ", "Qtd. reservada"]
        linhas = [cabecalho]
        for p in resumo["pedidos_expedidos"]:
            cliente = p.get("cliente") or {}
            linhas.append([
                p["numero"],
                cliente.get("razao_social") or "—",
                cliente.get("cnpj") or "—",
                str(p["quantidade_reservada"]),
            ])
        tabela_pedidos = Table(linhas, colWidths=[3.2 * cm, 6 * cm, 3.5 * cm, 3.3 * cm])
        tabela_pedidos.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7a1f1f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elementos.append(tabela_pedidos)
    else:
        elementos.append(Paragraph(
            "Nenhum pedido já expedido foi identificado como afetado nesta simulação.", estilos["Normal"],
        ))

    linhas_upstream = _achatar_upstream(resultado.get("upstream"))
    elementos.append(Paragraph("Lotes de origem (upstream)", estilo_rotulo_secao))
    if linhas_upstream:
        cabecalho = ["Lote", "Item", "Origem"]
        linhas = [cabecalho] + [[r["codigo_lote"], r["item"], r["origem"]] for r in linhas_upstream]
        tabela_upstream = Table(linhas, colWidths=[3.5 * cm, 8.5 * cm, 4 * cm])
        tabela_upstream.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabela_upstream)
    else:
        elementos.append(Paragraph("Nenhum lote de origem identificado (lote investigado é a própria origem).", estilos["Normal"]))

    linhas_downstream = _achatar_downstream(resultado.get("downstream"))
    elementos.append(Paragraph("Lotes derivados (downstream)", estilo_rotulo_secao))
    if linhas_downstream:
        cabecalho = ["Lote", "Item", "Status"]
        linhas = [cabecalho] + [[r["codigo_lote"], r["item"], r["status"].replace("_", " ").upper()] for r in linhas_downstream]
        tabela_downstream = Table(linhas, colWidths=[3.5 * cm, 9.5 * cm, 3 * cm])
        tabela_downstream.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabela_downstream)
    else:
        elementos.append(Paragraph("Nenhum lote derivado identificado.", estilos["Normal"]))

    elementos.append(Spacer(1, 24))
    elementos.append(Paragraph(
        "Este relatório é gerado a partir do snapshot IMUTÁVEL registrado no momento em que esta "
        "simulação de recall foi executada — reflete o que se sabia naquele momento, não o estado "
        "atual do banco. Se o estado do sistema mudou desde então, registre uma nova simulação para "
        "capturar os números atualizados. A autenticidade dos dados pode ser conferida no sistema "
        "pelo número da simulação acima.",
        ParagraphStyle("RodapeRecall", parent=estilos["Normal"], fontSize=8, textColor=colors.HexColor("#5a6472")),
    ))

    doc.build(elementos, onFirstPage=desenhar_cabecalho_logo, onLaterPages=desenhar_cabecalho_logo)
    return buffer.getvalue()


@bp.get("/lotes")
@requires_permission("rastreabilidade", "visualizar")
def buscar_lotes():
    """Busca leve de lotes por código ou código do item, só para alimentar
    o campo de busca da tela de Rastreabilidade/Recall. Deliberadamente
    NÃO exige `lotes.visualizar` — mesmo princípio de independência já
    usado em `relatorios.visualizar` na Fase 7: um perfil como Diretoria
    (que só tem `rastreabilidade.visualizar`) precisa conseguir procurar um
    lote para investigar sem ganhar acesso à tela operacional de Lotes."""
    conn = get_db()
    busca = (request.args.get("busca") or "").strip()
    if not busca:
        return jsonify([])
    termo = f"%{busca}%"
    rows = conn.execute(
        """
        SELECT l.id, l.codigo_lote, l.status, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM lotes l
        JOIN itens i ON i.id = l.item_id
        WHERE l.codigo_lote LIKE ? OR i.codigo LIKE ? OR i.descricao LIKE ?
        ORDER BY l.id DESC
        LIMIT 30
        """,
        (termo, termo, termo),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/lotes/<int:lote_id>/genealogia-completa")
@requires_permission("rastreabilidade", "visualizar")
def genealogia_completa(lote_id):
    conn = get_db()
    resultado = _montar_genealogia_completa(conn, lote_id)
    return jsonify(resultado)


@bp.post("/lotes/<int:lote_id>/simular-recall")
@requires_permission("rastreabilidade", "simular_recall")
def simular_recall(lote_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo da simulação de recall (ex.: resultado de análise fora de especificação, reclamação de cliente etc.).", status=400)

    resultado = _montar_genealogia_completa(conn, lote_id)
    resumo = resultado["resumo"]
    numero = _gerar_numero_recall()

    cur = conn.execute(
        """
        INSERT INTO simulacoes_recall (
            numero, lote_id, motivo, total_lotes_upstream, total_lotes_downstream,
            total_pedidos_expedidos, total_clientes_afetados, resultado, criado_por
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            numero, lote_id, motivo, resumo["total_lotes_upstream"], resumo["total_lotes_downstream"],
            len(resumo["pedidos_expedidos"]), resumo["total_clientes_afetados"],
            json.dumps(resultado, ensure_ascii=False), usuario_atual["id"],
        ),
    )
    simulacao_id = cur.lastrowid

    audit.registrar(
        conn, tabela="simulacoes_recall", registro_id=simulacao_id, usuario_id=usuario_atual["id"],
        acao="recall_simulado",
        valor_novo={
            "numero": numero, "lote_id": lote_id, "motivo": motivo,
            "total_lotes_upstream": resumo["total_lotes_upstream"],
            "total_lotes_downstream": resumo["total_lotes_downstream"],
            "total_pedidos_expedidos": len(resumo["pedidos_expedidos"]),
            "total_clientes_afetados": resumo["total_clientes_afetados"],
        },
        motivo=motivo, ip=client_ip(), dispositivo=client_device(),
    )

    row = conn.execute("SELECT * FROM simulacoes_recall WHERE id = ?", (simulacao_id,)).fetchone()
    simulacao = dict(row)
    simulacao["resultado"] = json.loads(simulacao["resultado"])
    return jsonify(simulacao), 201


@bp.get("/recalls")
@requires_permission("rastreabilidade", "visualizar")
def listar_recalls():
    conn = get_db()
    lote_id = request.args.get("lote_id", type=int)
    if lote_id:
        rows = conn.execute(
            """
            SELECT sr.*, l.codigo_lote, u.nome AS criado_por_nome
            FROM simulacoes_recall sr
            JOIN lotes l ON l.id = sr.lote_id
            LEFT JOIN usuarios u ON u.id = sr.criado_por
            WHERE sr.lote_id = ?
            ORDER BY sr.id DESC
            """,
            (lote_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT sr.*, l.codigo_lote, u.nome AS criado_por_nome
            FROM simulacoes_recall sr
            JOIN lotes l ON l.id = sr.lote_id
            LEFT JOIN usuarios u ON u.id = sr.criado_por
            ORDER BY sr.id DESC
            """
        ).fetchall()
    saida = []
    for r in rows:
        d = dict(r)
        d.pop("resultado", None)  # listagem não precisa da árvore inteira, só o resumo
        saida.append(d)
    return jsonify(saida)


@bp.get("/recalls/<int:simulacao_id>")
@requires_permission("rastreabilidade", "visualizar")
def detalhe_recall(simulacao_id):
    conn = get_db()
    row = conn.execute(
        """
        SELECT sr.*, l.codigo_lote, u.nome AS criado_por_nome
        FROM simulacoes_recall sr
        JOIN lotes l ON l.id = sr.lote_id
        LEFT JOIN usuarios u ON u.id = sr.criado_por
        WHERE sr.id = ?
        """,
        (simulacao_id,),
    ).fetchone()
    if row is None:
        raise ApiError("Simulação de recall não encontrada.", status=404)
    d = dict(row)
    d["resultado"] = json.loads(d["resultado"])

    # Fase 16: status de bloqueio ATUAL de cada lote afetado (upstream +
    # downstream + o próprio investigado), calculado agora — nunca
    # guardado, mesmo princípio de sempre recalcular saldo/status a partir
    # da tabela `lotes` em vez de confiar num valor congelado no snapshot
    # da simulação (que é imutável de propósito, mas o status de bloqueio
    # de cada lote pode mudar depois da simulação ter sido registrada).
    ids_afetados = sorted(_lotes_afetados(d["resultado"]))
    if ids_afetados:
        marcadores = ",".join("?" * len(ids_afetados))
        linhas = conn.execute(
            f"SELECT id, codigo_lote, status FROM lotes WHERE id IN ({marcadores})", ids_afetados,
        ).fetchall()
        d["lotes_afetados_status"] = [dict(l) for l in linhas]
    else:
        d["lotes_afetados_status"] = []

    return jsonify(d)


@bp.get("/recalls/<int:simulacao_id>/pdf")
@requires_permission("rastreabilidade", "visualizar")
def relatorio_recall_pdf(simulacao_id):
    """Fase 11 — Relatório de recall em PDF. Export puro (mesmo padrão da
    Fase 10/CoA): formata em PDF o snapshot já gravado em
    `simulacoes_recall`, sem alterar nenhum dado de negócio. Usa a mesma
    permissão `rastreabilidade.visualizar` de `detalhe_recall` — nenhuma
    permissão nova é necessária, e nenhuma tabela nova."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute(
        """
        SELECT sr.*, l.codigo_lote, u.nome AS criado_por_nome
        FROM simulacoes_recall sr
        JOIN lotes l ON l.id = sr.lote_id
        LEFT JOIN usuarios u ON u.id = sr.criado_por
        WHERE sr.id = ?
        """,
        (simulacao_id,),
    ).fetchone()
    if row is None:
        raise ApiError("Simulação de recall não encontrada.", status=404)

    simulacao = dict(row)
    simulacao["resultado"] = json.loads(simulacao["resultado"])

    pdf_bytes = _gerar_pdf_recall(simulacao)

    audit.registrar(
        conn, tabela="simulacoes_recall", registro_id=simulacao_id, usuario_id=usuario_atual["id"],
        acao="recall_pdf_gerado", valor_novo={"numero": simulacao["numero"]},
        ip=client_ip(), dispositivo=client_device(),
    )

    nome_arquivo = f"Recall-{simulacao['numero']}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@bp.post("/recalls/<int:simulacao_id>/bloquear-em-massa")
@requires_permission("rastreabilidade", "bloquear_em_massa")
def bloquear_em_massa(simulacao_id):
    """Fase 16 — item de backlog documentado desde a Fase 8: hoje uma
    simulação de recall já identifica exatamente quais lotes são afetados
    (para trás e para frente), mas bloquear cada um continuava sendo uma
    ação manual, lote a lote, na tela de Lotes/Qualidade. Esta rota aplica
    o bloqueio (Fase 2, `lotes.bloquear`) a TODOS os lotes afetados de uma
    vez, reaproveitando a mesma função `bloquear_lote_interno` da rota de
    bloqueio individual — nenhuma regra de bloqueio nova, só em lote.

    Deliberadamente NÃO mexe em pedidos de venda ainda não expedidos do
    mesmo lote (o próprio backlog já apontava isso como uma decisão de
    negócio maior, fora do escopo de só bloquear os lotes) — o campo
    `pedidos_reservados_nao_expedidos` do resultado da simulação continua
    sendo só informativo, para decisão manual de quem está conduzindo o
    recall.

    Lotes que já estavam bloqueados (de uma investigação anterior, por
    exemplo) são pulados sem erro — a operação é seguramente repetível."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do bloqueio em massa.", status=400)

    row = conn.execute(
        """
        SELECT sr.*, l.codigo_lote
        FROM simulacoes_recall sr
        JOIN lotes l ON l.id = sr.lote_id
        WHERE sr.id = ?
        """,
        (simulacao_id,),
    ).fetchone()
    if row is None:
        raise ApiError("Simulação de recall não encontrada.", status=404)

    resultado = json.loads(row["resultado"])
    ids_afetados = sorted(_lotes_afetados(resultado))
    motivo_completo = f"Bloqueio em massa por recall {row['numero']} (lote investigado {row['codigo_lote']}): {motivo}"

    bloqueados = []
    ja_bloqueados = []
    for lote_id in ids_afetados:
        lote_atualizado = bloquear_lote_interno(
            conn, lote_id, motivo_completo, usuario_atual, pular_se_ja_bloqueado=True,
        )
        if lote_atualizado is None:
            ja_bloqueados.append(lote_id)
        else:
            bloqueados.append(lote_atualizado)

    audit.registrar(
        conn, tabela="simulacoes_recall", registro_id=simulacao_id, usuario_id=usuario_atual["id"],
        acao="recall_bloqueio_em_massa", motivo=motivo,
        valor_novo={
            "numero": row["numero"], "total_afetados": len(ids_afetados),
            "lotes_bloqueados": [l["id"] for l in bloqueados], "lotes_ja_bloqueados": ja_bloqueados,
        },
        ip=client_ip(), dispositivo=client_device(),
    )

    return jsonify({
        "simulacao_id": simulacao_id,
        "total_afetados": len(ids_afetados),
        "lotes_bloqueados": bloqueados,
        "lotes_ja_bloqueados": ja_bloqueados,
    })


# ============================================================
# FASE 53 — Decisão sobre pedidos já expedidos afetados por um recall
# ============================================================

TIPOS_DECISAO_RECALL_PEDIDO = (
    "notificar_cliente",
    "aguardar_devolucao",
    "gerar_nota_credito",
    "cancelar_pedido",
    "sem_acao",
)


def _simulacao_recall_ou_404(conn, simulacao_id):
    row = conn.execute(
        """
        SELECT sr.*, l.codigo_lote
        FROM simulacoes_recall sr
        JOIN lotes l ON l.id = sr.lote_id
        WHERE sr.id = ?
        """,
        (simulacao_id,),
    ).fetchone()
    if row is None:
        raise ApiError("Simulação de recall não encontrada.", status=404)
    return dict(row)


def _pedidos_expedidos_ids(resultado):
    """A partir do `resultado` de uma simulação (mesmo formato usado por
    `_lotes_afetados`), devolve o conjunto de `pedido_id` que estavam
    EXPEDIDOS no momento da simulação — só esses são elegíveis para
    registrar uma decisão nesta fase (pedidos ainda não expedidos são
    tratados pelo fluxo normal de cancelamento de pedido, que já lida bem
    com eles)."""
    return {p["pedido_id"] for p in resultado.get("resumo", {}).get("pedidos_expedidos", [])}


def _status_atual_pedido_recall(conn, pedido_id):
    """Estado ATUAL (recalculado agora, nunca congelado) do pedido e da
    sua conta a receber — mesmo princípio já usado em `detalhe_recall` para
    `lotes_afetados_status`: o snapshot da simulação registra o que se
    sabia no momento da investigação, mas o status de hoje pode ter mudado
    (ex.: a conta já foi baixada, ou o pedido já foi cancelado por outro
    fluxo)."""
    pedido = conn.execute(
        "SELECT pv.id, pv.numero, pv.status, pv.cliente_id, c.razao_social AS cliente_razao_social "
        "FROM pedidos_venda pv LEFT JOIN clientes c ON c.id = pv.cliente_id WHERE pv.id = ?",
        (pedido_id,),
    ).fetchone()
    if pedido is None:
        return None
    pedido = dict(pedido)
    conta = conn.execute(
        "SELECT status, valor_total, vencimento FROM contas_receber WHERE pedido_venda_id = ?", (pedido_id,),
    ).fetchone()
    pedido["conta_receber"] = dict(conta) if conta else None
    return pedido


@bp.post("/recalls/<int:simulacao_id>/pedidos/<int:pedido_id>/decisoes")
@requires_permission("rastreabilidade", "decidir_pedido_recall")
def registrar_decisao_recall_pedido(simulacao_id, pedido_id):
    """Fase 53 — registra a decisão tomada para um pedido já EXPEDIDO
    afetado por um recall (ver nota de escopo no topo de schema_fase53.sql
    e na docstring de `bloquear_em_massa`, que deliberadamente não mexe em
    pedidos). Esta rota só REGISTRA a decisão como um evento histórico —
    não executa nada sozinha: cancelar o pedido de fato continua sendo
    feito pela rota de Comercial, e um estorno de conta a receber pela
    rota de Financeiro, cada uma com sua própria permissão e suas próprias
    regras já testadas. Múltiplas decisões para o mesmo pedido ao longo do
    tempo são esperadas (append-only, ver schema_fase53.sql) — a decisão
    "atual" é sempre a mais recente por `criado_em`."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    tipo_decisao = (dados.get("tipo_decisao") or "").strip()
    motivo = (dados.get("motivo") or "").strip()
    observacao = (dados.get("observacao") or "").strip() or None
    conn = get_db()

    if tipo_decisao not in TIPOS_DECISAO_RECALL_PEDIDO:
        raise ApiError(
            f"tipo_decisao inválido. Use um destes: {', '.join(TIPOS_DECISAO_RECALL_PEDIDO)}.", status=400,
        )
    if not motivo:
        raise ApiError("Informe o motivo da decisão.", status=400)

    simulacao = _simulacao_recall_ou_404(conn, simulacao_id)
    resultado = json.loads(simulacao["resultado"])

    if pedido_id not in _pedidos_expedidos_ids(resultado):
        raise ApiError(
            "Este pedido não está entre os pedidos já expedidos afetados por esta simulação de recall.",
            status=400,
        )

    pedido_atual = _status_atual_pedido_recall(conn, pedido_id)
    if pedido_atual is None:
        raise ApiError("Pedido de venda não encontrado.", status=404)

    cursor = conn.execute(
        """
        INSERT INTO decisoes_recall_pedido
            (simulacao_recall_id, pedido_venda_id, tipo_decisao, motivo, observacao, criado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (simulacao_id, pedido_id, tipo_decisao, motivo, observacao, usuario_atual["id"]),
    )
    conn.commit()
    decisao_id = cursor.lastrowid

    audit.registrar(
        conn, tabela="decisoes_recall_pedido", registro_id=decisao_id, usuario_id=usuario_atual["id"],
        acao="decisao_recall_pedido_registrada", motivo=motivo,
        valor_novo={
            "simulacao_recall_id": simulacao_id, "simulacao_numero": simulacao["numero"],
            "pedido_venda_id": pedido_id, "pedido_numero": pedido_atual["numero"],
            "tipo_decisao": tipo_decisao, "observacao": observacao,
        },
        ip=client_ip(), dispositivo=client_device(),
    )

    decisao = conn.execute("SELECT * FROM decisoes_recall_pedido WHERE id = ?", (decisao_id,)).fetchone()
    return jsonify(dict(decisao)), 201


@bp.get("/recalls/<int:simulacao_id>/decisoes")
@requires_permission("rastreabilidade", "visualizar")
def listar_decisoes_recall_pedido(simulacao_id):
    """Fase 53 — para cada pedido já expedido afetado por esta simulação,
    devolve o status ATUAL do pedido/conta a receber (recalculado agora,
    nunca congelado — mesmo princípio de `detalhe_recall`) junto com todo
    o histórico de decisões já registradas para ele, do mais antigo para o
    mais novo. Usa a permissão `rastreabilidade.visualizar` (a mesma de
    `detalhe_recall`) porque é só leitura — a permissão nova
    `decidir_pedido_recall` só é exigida para CRIAR uma decisão."""
    conn = get_db()
    simulacao = _simulacao_recall_ou_404(conn, simulacao_id)
    resultado = json.loads(simulacao["resultado"])

    pedidos_ids = sorted(_pedidos_expedidos_ids(resultado))
    decisoes_por_pedido = {}
    if pedidos_ids:
        marcadores = ",".join("?" * len(pedidos_ids))
        linhas = conn.execute(
            f"""
            SELECT drp.*, u.nome AS criado_por_nome
            FROM decisoes_recall_pedido drp
            LEFT JOIN usuarios u ON u.id = drp.criado_por
            WHERE drp.simulacao_recall_id = ? AND drp.pedido_venda_id IN ({marcadores})
            ORDER BY drp.id ASC
            """,
            (simulacao_id, *pedidos_ids),
        ).fetchall()
        for linha in linhas:
            d = dict(linha)
            decisoes_por_pedido.setdefault(d["pedido_venda_id"], []).append(d)

    saida = []
    for pedido_id in pedidos_ids:
        pedido_atual = _status_atual_pedido_recall(conn, pedido_id)
        saida.append({
            "pedido_venda_id": pedido_id,
            "pedido_atual": pedido_atual,
            "decisoes": decisoes_por_pedido.get(pedido_id, []),
        })

    return jsonify({
        "simulacao_id": simulacao_id,
        "simulacao_numero": simulacao["numero"],
        "pedidos": saida,
    })
