from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("fornecedores", __name__, url_prefix="/api/v1/fornecedores")

STATUS_VALIDOS = ("em_avaliacao", "aprovado", "aprovado_com_ressalva", "bloqueado", "reprovado")


# ============================================================
# FASE 62 — Desempenho de Fornecedor (Scorecard)
# ============================================================
# 100% agregação sobre dados que já existem (Pedido de Compra desde a
# Fase 58, data prevista de entrega da Fase 60, e o status de qualidade
# dos lotes desde a Fase 2) — mesmo espírito da Fase 7 (Painel Gerencial):
# nenhuma tabela nova, nenhum job em segundo plano, sempre calculado na
# hora da consulta. Por isso não há migrations/schema_fase62.sql nem
# entrada nova em app/db.py.
def _desempenho_fornecedor(conn, fornecedor_id):
    pedidos = conn.execute(
        "SELECT status, data_prevista_entrega, concluido_em FROM pedidos_compra WHERE fornecedor_id = ?",
        (fornecedor_id,),
    ).fetchall()
    pedidos_por_status = {"rascunho": 0, "enviado": 0, "parcialmente_recebido": 0, "recebido": 0, "cancelado": 0}
    for p in pedidos:
        pedidos_por_status[p["status"]] = pedidos_por_status.get(p["status"], 0) + 1

    # Valor comprado — soma do que foi PEDIDO (quantidade_pedida x
    # preco_unitario), contado só em pedidos que chegaram a virar um
    # compromisso de verdade com o fornecedor (enviado, parcial ou
    # totalmente recebido) — 'rascunho' nunca foi enviado e 'cancelado'
    # nunca virou compra, então nenhum dos dois soma aqui.
    valor_total_comprado = conn.execute(
        """
        SELECT COALESCE(SUM(ip.quantidade_pedida * COALESCE(ip.preco_unitario, 0)), 0) AS total
        FROM itens_pedido_compra ip
        JOIN pedidos_compra pc ON pc.id = ip.pedido_compra_id
        WHERE pc.fornecedor_id = ? AND pc.status IN ('enviado', 'parcialmente_recebido', 'recebido')
        """,
        (fornecedor_id,),
    ).fetchone()["total"]

    # Entregas no prazo — só pedidos JÁ totalmente recebidos e que
    # tinham uma data prevista de entrega congelada no envio (Fase 60);
    # sem essa data (fornecedor sem lead_time_dias configurado na época
    # do envio) não há como avaliar prazo, então o pedido simplesmente
    # não entra nem no numerador nem no denominador — mesmo princípio de
    # "não inventar dado" já documentado em schema_fase60.sql.
    no_prazo = 0
    atrasadas = 0
    for p in pedidos:
        if p["status"] == "recebido" and p["data_prevista_entrega"] and p["concluido_em"]:
            if p["concluido_em"][:10] <= p["data_prevista_entrega"]:
                no_prazo += 1
            else:
                atrasadas += 1
    total_avaliadas = no_prazo + atrasadas
    taxa_no_prazo_pct = round((no_prazo / total_avaliadas) * 100, 1) if total_avaliadas > 0 else None

    # Qualidade — mesmo cálculo de taxa_aprovacao_lotes_pct já usado no
    # Painel Gerencial (_bloco_qualidade em app/routes/relatorios.py: só
    # 'aprovado'/'aprovado_com_ressalva' contam como aprovados e
    # 'reprovado' como reprovado; lotes ainda em julgamento —
    # quarentena/em_analise/aguardando_aprovacao/bloqueado — ficam de
    # fora do percentual, não contam nem a favor nem contra), agora
    # recortado por fornecedor em vez do sistema inteiro.
    lotes_por_status = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS total FROM lotes WHERE fornecedor_id = ? GROUP BY status", (fornecedor_id,)
    ).fetchall():
        lotes_por_status[row["status"]] = row["total"]
    aprovados = lotes_por_status.get("aprovado", 0) + lotes_por_status.get("aprovado_com_ressalva", 0)
    reprovados = lotes_por_status.get("reprovado", 0)
    total_julgados = aprovados + reprovados
    taxa_aprovacao_pct = round((aprovados / total_julgados) * 100, 1) if total_julgados > 0 else None

    return {
        "fornecedor_id": fornecedor_id,
        "total_pedidos_compra": len(pedidos),
        "pedidos_por_status": pedidos_por_status,
        "valor_total_comprado": round(valor_total_comprado, 2),
        "entregas": {
            "total_avaliadas": total_avaliadas,
            "no_prazo": no_prazo,
            "atrasadas": atrasadas,
            "taxa_no_prazo_pct": taxa_no_prazo_pct,
        },
        "qualidade": {
            "lotes_recebidos": sum(lotes_por_status.values()),
            "lotes_aprovados": aprovados,
            "lotes_reprovados": reprovados,
            "taxa_aprovacao_pct": taxa_aprovacao_pct,
        },
    }


def _validar_lead_time(valor):
    """Fase 57 — `lead_time_dias` é sempre OPCIONAL: `None` significa
    "prazo de entrega não informado" (comportamento idêntico ao de antes
    desta fase, sem nenhuma data sugerida de compra calculada para este
    fornecedor) e nunca é um erro. Só valida quando um valor de verdade é
    enviado."""
    if valor is None:
        return None
    try:
        valor_int = int(valor)
    except (TypeError, ValueError):
        raise ApiError("lead_time_dias deve ser um número inteiro de dias.", status=400)
    if valor_int < 0:
        raise ApiError("lead_time_dias não pode ser negativo.", status=400)
    return valor_int


@bp.get("")
@requires_permission("fornecedores", "visualizar")
def listar():
    conn = get_db()
    rows = conn.execute("SELECT * FROM fornecedores ORDER BY nome").fetchall()
    resultado = []
    for r in rows:
        f = dict(r)
        itens = conn.execute(
            """
            SELECT i.id, i.codigo, i.descricao FROM item_fornecedor_aprovado ifa
            JOIN itens i ON i.id = ifa.item_id WHERE ifa.fornecedor_id = ?
            """,
            (f["id"],),
        ).fetchall()
        f["itens_homologados"] = [dict(i) for i in itens]
        resultado.append(f)
    return jsonify(resultado)


@bp.post("")
@requires_permission("fornecedores", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    cnpj = (dados.get("cnpj") or "").strip()
    lead_time_dias = _validar_lead_time(dados.get("lead_time_dias"))
    conn = get_db()

    if not nome or not cnpj:
        raise ApiError("Informe nome e cnpj.", status=400)
    if conn.execute("SELECT id FROM fornecedores WHERE cnpj = ?", (cnpj,)).fetchone():
        raise ApiError("Já existe um fornecedor com este CNPJ.", status=409)

    cur = conn.execute(
        "INSERT INTO fornecedores (nome, cnpj, lead_time_dias, criado_por) VALUES (?, ?, ?, ?)",
        (nome, cnpj, lead_time_dias, usuario_atual["id"]),
    )
    fornecedor_id = cur.lastrowid
    audit.registrar(conn, tabela="fornecedores", registro_id=fornecedor_id, usuario_id=usuario_atual["id"],
                     acao="fornecedor_criado", valor_novo={"nome": nome, "cnpj": cnpj, "lead_time_dias": lead_time_dias},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    return jsonify(dict(row)), 201


CAMPOS_FISCAIS_FORNECEDOR_EDITAVEIS = (
    "inscricao_estadual", "logradouro", "numero_endereco", "complemento_endereco",
    "bairro", "municipio", "codigo_ibge_municipio", "uf", "cep",
)


@bp.put("/<int:fornecedor_id>/dados-fiscais")
@requires_permission("fornecedores", "cadastrar")
def editar_dados_fiscais(fornecedor_id):
    """Fase 78 — mesmos campos que a Fase 70 já adicionou em
    empresas/clientes, agora em fornecedores: necessários para saber se uma
    compra é operação interna ou interestadual (usado nas fases seguintes
    do projeto de SPED Fiscal). Rota dedicada e de escopo único, mesmo
    raciocínio de `configurar_lead_time` abaixo — é dado de cadastro, não
    uma decisão de homologação (`fornecedores.homologar`), por isso
    reaproveita `fornecedores.cadastrar`."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    if anterior is None:
        raise ApiError("Fornecedor não encontrado.", status=404)
    anterior = dict(anterior)

    valores = {campo: dados.get(campo, anterior[campo]) for campo in CAMPOS_FISCAIS_FORNECEDOR_EDITAVEIS}
    conn.execute(
        f"""
        UPDATE fornecedores SET {', '.join(f'{c} = ?' for c in CAMPOS_FISCAIS_FORNECEDOR_EDITAVEIS)}
        WHERE id = ?
        """,
        (*[valores[c] for c in CAMPOS_FISCAIS_FORNECEDOR_EDITAVEIS], fornecedor_id),
    )
    novo_row = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    audit.registrar(conn, tabela="fornecedores", registro_id=fornecedor_id, usuario_id=usuario_atual["id"],
                     acao="fornecedor_dados_fiscais_editados", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo_row))


@bp.put("/<int:fornecedor_id>/lead-time")
@requires_permission("fornecedores", "cadastrar")
def configurar_lead_time(fornecedor_id):
    """Fase 57 — edita só o prazo de entrega (lead time, em dias) de um
    fornecedor já cadastrado. Rota dedicada e de escopo único (como
    `configurar-limite-estorno` do Financeiro), separada de
    `alterar_status`/`homologar_item` porque o risco é diferente: isto é
    só um dado informativo de cadastro, não uma decisão de
    aprovação/homologação — por isso reaproveita `fornecedores.cadastrar`
    (mesma permissão de criar um fornecedor), não `fornecedores.homologar`.
    Envie `lead_time_dias: null` para limpar um valor já configurado
    (volta a "prazo não informado")."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    if "lead_time_dias" not in dados:
        raise ApiError("Informe lead_time_dias (um número de dias, ou null para limpar).", status=400)
    lead_time_dias = _validar_lead_time(dados["lead_time_dias"])
    conn = get_db()

    row = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    if row is None:
        raise ApiError("Fornecedor não encontrado.", status=404)

    conn.execute(
        "UPDATE fornecedores SET lead_time_dias = ?, atualizado_por = ?, atualizado_em = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (lead_time_dias, usuario_atual["id"], fornecedor_id),
    )
    audit.registrar(conn, tabela="fornecedores", registro_id=fornecedor_id, usuario_id=usuario_atual["id"],
                     acao="fornecedor_lead_time_alterado", valor_anterior={"lead_time_dias": row["lead_time_dias"]},
                     valor_novo={"lead_time_dias": lead_time_dias},
                     ip=client_ip(), dispositivo=client_device())
    novo_row = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    return jsonify(dict(novo_row))


@bp.post("/<int:fornecedor_id>/status")
@requires_permission("fornecedores", "homologar")
def alterar_status(fornecedor_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    novo_status = dados.get("status")
    conn = get_db()

    if novo_status not in STATUS_VALIDOS:
        raise ApiError(f"status deve ser um de: {', '.join(STATUS_VALIDOS)}.", status=400)
    row = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    if row is None:
        raise ApiError("Fornecedor não encontrado.", status=404)

    conn.execute(
        "UPDATE fornecedores SET status = ?, observacoes = ?, atualizado_por = ? WHERE id = ?",
        (novo_status, dados.get("observacoes"), usuario_atual["id"], fornecedor_id),
    )
    audit.registrar(conn, tabela="fornecedores", registro_id=fornecedor_id, usuario_id=usuario_atual["id"],
                     acao="fornecedor_status_alterado", valor_anterior={"status": row["status"]},
                     valor_novo={"status": novo_status}, motivo=dados.get("observacoes"),
                     ip=client_ip(), dispositivo=client_device())
    novo_row = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    return jsonify(dict(novo_row))


@bp.post("/<int:fornecedor_id>/itens")
@requires_permission("fornecedores", "homologar")
def homologar_item(fornecedor_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    item_id = dados.get("item_id")
    conn = get_db()

    if not conn.execute("SELECT id FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone():
        raise ApiError("Fornecedor não encontrado.", status=404)
    if not conn.execute("SELECT id FROM itens WHERE id = ?", (item_id,)).fetchone():
        raise ApiError("Item não encontrado.", status=404)
    if conn.execute(
        "SELECT 1 FROM item_fornecedor_aprovado WHERE item_id = ? AND fornecedor_id = ?", (item_id, fornecedor_id)
    ).fetchone():
        raise ApiError("Este fornecedor já está homologado para este item.", status=409)

    conn.execute(
        "INSERT INTO item_fornecedor_aprovado (item_id, fornecedor_id, aprovado_por) VALUES (?, ?, ?)",
        (item_id, fornecedor_id, usuario_atual["id"]),
    )
    audit.registrar(conn, tabela="item_fornecedor_aprovado", registro_id=f"{item_id}-{fornecedor_id}",
                     usuario_id=usuario_atual["id"], acao="fornecedor_homologado_para_item",
                     valor_novo={"item_id": item_id, "fornecedor_id": fornecedor_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True}), 201


@bp.get("/<int:fornecedor_id>/desempenho")
@requires_permission("fornecedores", "visualizar")
def desempenho(fornecedor_id):
    """Fase 62 — reaproveita a mesma permissão de LEITURA já usada para
    listar fornecedores (`fornecedores.visualizar`), em vez de criar uma
    permissão nova: é agregação de dados que quem já vê Fornecedores/
    Compras também pode ver, o mesmo raciocínio do Painel Gerencial
    (Fase 7) não ter uma permissão própria separada de cada módulo que
    agrega."""
    conn = get_db()
    if not conn.execute("SELECT id FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone():
        raise ApiError("Fornecedor não encontrado.", status=404)
    return jsonify(_desempenho_fornecedor(conn, fornecedor_id))
