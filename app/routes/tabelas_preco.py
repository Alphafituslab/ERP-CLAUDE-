"""
Fase 99 — Tabelas de Preço: uma ou mais listas de preço por item, cada cliente associado a UMA
delas (`clientes.tabela_preco_id`, opcional). Usado para pré-preencher o preço unitário na hora
de montar um Pedido de Venda — a pessoa ainda pode editar o valor livremente antes de confirmar,
isso é só uma sugestão, nunca uma trava (ver a nota de escopo completa em
migrations/schema_fase99.sql).
"""
from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("tabelas_preco", __name__, url_prefix="/api/v1/tabelas-preco")


def _tabela_ou_404(conn, tabela_id):
    row = conn.execute("SELECT * FROM tabelas_preco WHERE id = ?", (tabela_id,)).fetchone()
    if row is None:
        raise ApiError("Tabela de preço não encontrada.", status=404)
    return dict(row)


@bp.get("")
@requires_permission("tabelas_preco", "visualizar")
def listar():
    conn = get_db()
    incluir_inativas = request.args.get("incluir_inativas") == "1"
    apenas_app_vendas = request.args.get("app_vendas") == "1"
    clausulas = [] if incluir_inativas else ["status = 'ativo'"]
    if apenas_app_vendas:
        clausulas.append("visivel_app_vendas = 1")
    where = ("WHERE " + " AND ".join(clausulas)) if clausulas else ""
    rows = conn.execute(f"SELECT * FROM tabelas_preco {where} ORDER BY nome").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@requires_permission("tabelas_preco", "gerenciar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    conn = get_db()

    if not nome:
        raise ApiError("Informe o nome da tabela de preço.", status=400)
    if conn.execute("SELECT id FROM tabelas_preco WHERE nome = ?", (nome,)).fetchone():
        raise ApiError("Já existe uma tabela de preço com este nome.", status=409)

    visivel_app_vendas = 1 if dados.get("visivel_app_vendas", True) else 0
    cur = conn.execute(
        "INSERT INTO tabelas_preco (nome, visivel_app_vendas, criado_por) VALUES (?, ?, ?)",
        (nome, visivel_app_vendas, usuario_atual["id"]),
    )
    tabela_id = cur.lastrowid
    audit.registrar(conn, tabela="tabelas_preco", registro_id=tabela_id, usuario_id=usuario_atual["id"],
                     acao="tabela_preco_criada", valor_novo={"nome": nome}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_tabela_ou_404(conn, tabela_id)), 201


@bp.put("/<int:tabela_id>")
@requires_permission("tabelas_preco", "gerenciar")
def editar(tabela_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = _tabela_ou_404(conn, tabela_id)
    nome = (dados.get("nome") or anterior["nome"]).strip()
    status = dados.get("status", anterior["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)
    if nome != anterior["nome"] and conn.execute("SELECT id FROM tabelas_preco WHERE nome = ? AND id != ?", (nome, tabela_id)).fetchone():
        raise ApiError("Já existe uma tabela de preço com este nome.", status=409)
    visivel_app_vendas = 1 if dados.get("visivel_app_vendas", anterior["visivel_app_vendas"]) else 0

    conn.execute("UPDATE tabelas_preco SET nome = ?, status = ?, visivel_app_vendas = ? WHERE id = ?", (nome, status, visivel_app_vendas, tabela_id))
    novo = _tabela_ou_404(conn, tabela_id)
    audit.registrar(conn, tabela="tabelas_preco", registro_id=tabela_id, usuario_id=usuario_atual["id"],
                     acao="tabela_preco_editada", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.get("/<int:tabela_id>/itens")
@requires_permission("tabelas_preco", "visualizar")
def listar_itens(tabela_id):
    conn = get_db()
    _tabela_ou_404(conn, tabela_id)
    rows = conn.execute(
        """
        SELECT tpi.*, i.codigo AS item_codigo, i.descricao AS item_descricao, i.unidade_medida
        FROM tabelas_preco_itens tpi JOIN itens i ON i.id = tpi.item_id
        WHERE tpi.tabela_preco_id = ? ORDER BY i.codigo
        """,
        (tabela_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.put("/<int:tabela_id>/itens/<int:item_id>")
@requires_permission("tabelas_preco", "gerenciar")
def definir_preco_item(tabela_id, item_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    _tabela_ou_404(conn, tabela_id)
    item = conn.execute("SELECT id, codigo, descricao FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError("Item não encontrado.", status=404)

    try:
        preco = float(dados.get("preco"))
    except (TypeError, ValueError):
        raise ApiError("Informe preco (numérico).", status=400)
    if preco < 0:
        raise ApiError("preco não pode ser negativo.", status=400)

    anterior = conn.execute(
        "SELECT * FROM tabelas_preco_itens WHERE tabela_preco_id = ? AND item_id = ?", (tabela_id, item_id)
    ).fetchone()
    anterior = dict(anterior) if anterior else None

    conn.execute(
        """
        INSERT INTO tabelas_preco_itens (tabela_preco_id, item_id, preco, atualizado_por)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (tabela_preco_id, item_id) DO UPDATE SET
            preco = excluded.preco, atualizado_em = strftime('%Y-%m-%dT%H:%M:%fZ','now'), atualizado_por = excluded.atualizado_por
        """,
        (tabela_id, item_id, preco, usuario_atual["id"]),
    )
    novo = dict(conn.execute(
        "SELECT * FROM tabelas_preco_itens WHERE tabela_preco_id = ? AND item_id = ?", (tabela_id, item_id)
    ).fetchone())
    audit.registrar(conn, tabela="tabelas_preco_itens", registro_id=novo["id"], usuario_id=usuario_atual["id"],
                     acao="preco_item_definido", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.delete("/<int:tabela_id>/itens/<int:item_id>")
@requires_permission("tabelas_preco", "gerenciar")
def remover_preco_item(tabela_id, item_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _tabela_ou_404(conn, tabela_id)

    anterior = conn.execute(
        "SELECT * FROM tabelas_preco_itens WHERE tabela_preco_id = ? AND item_id = ?", (tabela_id, item_id)
    ).fetchone()
    if anterior is None:
        raise ApiError("Este item não tem preço cadastrado nesta tabela.", status=404)

    conn.execute("DELETE FROM tabelas_preco_itens WHERE tabela_preco_id = ? AND item_id = ?", (tabela_id, item_id))
    audit.registrar(conn, tabela="tabelas_preco_itens", registro_id=anterior["id"], usuario_id=usuario_atual["id"],
                     acao="preco_item_removido", valor_anterior=dict(anterior), ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})
