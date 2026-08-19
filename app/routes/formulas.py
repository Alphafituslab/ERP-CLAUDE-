import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, get_db, client_device, client_ip
from ..permissions import requires_permission

bp = Blueprint("formulas", __name__, url_prefix="/api/v1/formulas")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _formula_com_itens(conn, formula_id):
    row = conn.execute("SELECT * FROM formulas WHERE id = ?", (formula_id,)).fetchone()
    if row is None:
        raise ApiError("Fórmula não encontrada.", status=404)
    formula = dict(row)
    itens = conn.execute(
        """
        SELECT fi.*, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM formula_itens fi JOIN itens i ON i.id = fi.item_id
        WHERE fi.formula_id = ? ORDER BY fi.id
        """,
        (formula_id,),
    ).fetchall()
    formula["itens"] = [dict(r) for r in itens]
    return formula


@bp.get("")
@requires_permission("formulas", "visualizar")
def listar():
    conn = get_db()
    item_id = request.args.get("item_id", type=int)
    status = request.args.get("status")
    clausulas, params = [], []
    if item_id:
        clausulas.append("item_produzido_id = ?")
        params.append(item_id)
    if status:
        clausulas.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(f"SELECT * FROM formulas {where} ORDER BY item_produzido_id, versao DESC", params).fetchall()
    return jsonify([_formula_com_itens(conn, r["id"]) for r in rows])


@bp.get("/<int:formula_id>")
@requires_permission("formulas", "visualizar")
def obter(formula_id):
    conn = get_db()
    return jsonify(_formula_com_itens(conn, formula_id))


@bp.post("")
@requires_permission("formulas", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    item_produzido_id = dados.get("item_produzido_id")
    rendimento_teorico = dados.get("rendimento_teorico")
    unidade_rendimento = dados.get("unidade_rendimento")
    itens = dados.get("itens") or []

    if not item_produzido_id or not rendimento_teorico or not unidade_rendimento:
        raise ApiError("Informe item_produzido_id, rendimento_teorico e unidade_rendimento.", status=400)
    if not itens:
        raise ApiError("Informe ao menos um item em 'itens' (a composição/BOM da fórmula).", status=400)

    item_produzido = conn.execute("SELECT * FROM itens WHERE id = ?", (item_produzido_id,)).fetchone()
    if item_produzido is None:
        raise ApiError("Item produzido não encontrado.", status=404)

    ultima_versao = conn.execute(
        "SELECT MAX(versao) AS v FROM formulas WHERE item_produzido_id = ?", (item_produzido_id,)
    ).fetchone()["v"]
    nova_versao = (ultima_versao or 0) + 1

    cur = conn.execute(
        """
        INSERT INTO formulas (item_produzido_id, versao, rendimento_teorico, unidade_rendimento, observacoes, criado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_produzido_id, nova_versao, rendimento_teorico, unidade_rendimento, dados.get("observacoes"), usuario_atual["id"]),
    )
    formula_id = cur.lastrowid

    for linha in itens:
        insumo_id = linha.get("item_id")
        quantidade = linha.get("quantidade")
        unidade = linha.get("unidade")
        if not insumo_id or not quantidade or not unidade:
            raise ApiError("Cada item da composição precisa de item_id, quantidade e unidade.", status=400)
        if not conn.execute("SELECT id FROM itens WHERE id = ?", (insumo_id,)).fetchone():
            raise ApiError(f"Item de composição id={insumo_id} não encontrado.", status=404)
        conn.execute(
            "INSERT INTO formula_itens (formula_id, item_id, quantidade, unidade) VALUES (?, ?, ?, ?)",
            (formula_id, insumo_id, quantidade, unidade),
        )

    audit.registrar(conn, tabela="formulas", registro_id=formula_id, usuario_id=usuario_atual["id"],
                     acao="formula_criada", valor_novo={"item_produzido_id": item_produzido_id, "versao": nova_versao},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_formula_com_itens(conn, formula_id)), 201


@bp.put("/<int:formula_id>")
@requires_permission("formulas", "cadastrar")
def editar_itens(formula_id):
    """Substitui a composição (BOM) de uma fórmula ainda em rascunho. Uma
    fórmula já ativada (usada por alguma ordem) nunca é editável — para
    mudar a composição depois de ativa, cria-se uma nova versão via POST."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    formula = conn.execute("SELECT * FROM formulas WHERE id = ?", (formula_id,)).fetchone()
    if formula is None:
        raise ApiError("Fórmula não encontrada.", status=404)
    if formula["status"] != "rascunho":
        raise ApiError(
            "Só é possível editar a composição de uma fórmula em rascunho. "
            "Fórmulas ativas/obsoletas são imutáveis — crie uma nova versão.",
            status=400,
        )

    itens = dados.get("itens") or []
    if not itens:
        raise ApiError("Informe ao menos um item em 'itens'.", status=400)

    conn.execute("DELETE FROM formula_itens WHERE formula_id = ?", (formula_id,))
    for linha in itens:
        insumo_id = linha.get("item_id")
        quantidade = linha.get("quantidade")
        unidade = linha.get("unidade")
        if not insumo_id or not quantidade or not unidade:
            raise ApiError("Cada item da composição precisa de item_id, quantidade e unidade.", status=400)
        conn.execute(
            "INSERT INTO formula_itens (formula_id, item_id, quantidade, unidade) VALUES (?, ?, ?, ?)",
            (formula_id, insumo_id, quantidade, unidade),
        )

    audit.registrar(conn, tabela="formulas", registro_id=formula_id, usuario_id=usuario_atual["id"],
                     acao="formula_composicao_editada", ip=client_ip(), dispositivo=client_device())
    return jsonify(_formula_com_itens(conn, formula_id))


@bp.post("/<int:formula_id>/ativar")
@requires_permission("formulas", "aprovar")
def ativar(formula_id):
    """Ativa uma fórmula em rascunho. Automaticamente torna obsoleta
    qualquer outra fórmula que já estivesse ativa para o mesmo item
    produzido — nunca existem duas fórmulas ativas simultâneas para o
    mesmo item, o que eliminaria a ambiguidade de qual composição usar ao
    abrir uma nova ordem de produção."""
    usuario_atual = g.usuario_atual
    conn = get_db()

    formula = conn.execute("SELECT * FROM formulas WHERE id = ?", (formula_id,)).fetchone()
    if formula is None:
        raise ApiError("Fórmula não encontrada.", status=404)
    if formula["status"] != "rascunho":
        raise ApiError(f"Só é possível ativar uma fórmula em rascunho (status atual: '{formula['status']}').", status=400)

    n_itens = conn.execute("SELECT COUNT(*) c FROM formula_itens WHERE formula_id = ?", (formula_id,)).fetchone()["c"]
    if n_itens == 0:
        raise ApiError("Esta fórmula não tem nenhum item na composição.", status=400)

    anteriores = conn.execute(
        "SELECT id FROM formulas WHERE item_produzido_id = ? AND status = 'ativa'",
        (formula["item_produzido_id"],),
    ).fetchall()
    for anterior in anteriores:
        conn.execute("UPDATE formulas SET status = 'obsoleta' WHERE id = ?", (anterior["id"],))
        audit.registrar(conn, tabela="formulas", registro_id=anterior["id"], usuario_id=usuario_atual["id"],
                         acao="formula_obsoletada_por_nova_versao", valor_novo={"substituida_por": formula_id},
                         ip=client_ip(), dispositivo=client_device())

    conn.execute(
        "UPDATE formulas SET status = 'ativa', ativado_em = ?, ativado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], formula_id),
    )
    audit.registrar(conn, tabela="formulas", registro_id=formula_id, usuario_id=usuario_atual["id"],
                     acao="formula_ativada", ip=client_ip(), dispositivo=client_device())
    return jsonify(_formula_com_itens(conn, formula_id))
