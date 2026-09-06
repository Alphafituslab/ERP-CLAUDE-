"""
Fase 155 — Catálogos nomeados do App de Vendas.

Pedido do usuário: em vez do portfólio único de sempre (todos os itens
ativos, só agrupados por categoria — ver `vendas_app.py::portfolio`), o
admin monta CATÁLOGOS nomeados (ex.: "Linha Própria Alpha", "Linha
Terceiros") escolhendo quais itens entram em cada um; um item pode estar em
mais de um catálogo. Visibilidade por vendedor: por padrão (`'todos'`) todo
mundo com `vendas_app.usar` vê o catálogo; marcado como `'restrita'`, só os
vendedores explicitamente listados o veem (evita ter que listar vendedor por
vendedor no caso comum de catálogo aberto a todos).

Este arquivo é a administração (tela desktop/ERP, cadastrar/editar
catálogo, escolher itens, escolher vendedores). O lado do VENDEDOR (listar
só os catálogos que ELE pode ver, navegar os itens de um catálogo) mora em
`vendas_app.py`, que já tinha o portfólio."""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("catalogos_vendas", __name__, url_prefix="/api/v1/catalogos-vendas")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _catalogo_ou_404(conn, catalogo_id):
    row = conn.execute("SELECT * FROM catalogos_vendas WHERE id = ?", (catalogo_id,)).fetchone()
    if row is None:
        raise ApiError("Catálogo não encontrado.", status=404)
    return dict(row)


def _catalogo_detalhado(conn, catalogo_id):
    catalogo = _catalogo_ou_404(conn, catalogo_id)
    itens = conn.execute(
        """
        SELECT i.id, i.codigo, i.descricao
        FROM catalogos_vendas_itens cvi JOIN itens i ON i.id = cvi.item_id
        WHERE cvi.catalogo_id = ? ORDER BY i.descricao
        """,
        (catalogo_id,),
    ).fetchall()
    catalogo["itens"] = [dict(i) for i in itens]
    vendedores = conn.execute(
        """
        SELECT u.id, u.nome
        FROM catalogos_vendas_vendedores cvv JOIN usuarios u ON u.id = cvv.usuario_id
        WHERE cvv.catalogo_id = ? ORDER BY u.nome
        """,
        (catalogo_id,),
    ).fetchall()
    catalogo["vendedores_permitidos"] = [dict(v) for v in vendedores]
    return catalogo


@bp.get("")
@requires_permission("catalogos_vendas", "visualizar")
def listar():
    conn = get_db()
    rows = conn.execute("SELECT * FROM catalogos_vendas ORDER BY ordem, nome").fetchall()
    resultado = []
    for row in rows:
        catalogo = dict(row)
        catalogo["total_itens"] = conn.execute(
            "SELECT COUNT(*) AS n FROM catalogos_vendas_itens WHERE catalogo_id = ?", (catalogo["id"],)
        ).fetchone()["n"]
        if catalogo["visibilidade"] == "restrita":
            catalogo["total_vendedores_permitidos"] = conn.execute(
                "SELECT COUNT(*) AS n FROM catalogos_vendas_vendedores WHERE catalogo_id = ?", (catalogo["id"],)
            ).fetchone()["n"]
        else:
            catalogo["total_vendedores_permitidos"] = None
        resultado.append(catalogo)
    return jsonify(resultado)


@bp.get("/<int:catalogo_id>")
@requires_permission("catalogos_vendas", "visualizar")
def obter(catalogo_id):
    conn = get_db()
    return jsonify(_catalogo_detalhado(conn, catalogo_id))


@bp.post("")
@requires_permission("catalogos_vendas", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ApiError("Informe o nome do catálogo.", status=400)
    visibilidade = dados.get("visibilidade") or "todos"
    if visibilidade not in ("todos", "restrita"):
        raise ApiError("visibilidade deve ser 'todos' ou 'restrita'.", status=400)

    cur = conn.execute(
        "INSERT INTO catalogos_vendas (nome, descricao, visibilidade, criado_por) VALUES (?, ?, ?, ?)",
        (nome, dados.get("descricao") or None, visibilidade, usuario_atual["id"]),
    )
    catalogo_id = cur.lastrowid
    audit.registrar(conn, tabela="catalogos_vendas", registro_id=catalogo_id, usuario_id=usuario_atual["id"],
                     acao="catalogo_vendas_criado", valor_novo={"nome": nome, "visibilidade": visibilidade},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_catalogo_detalhado(conn, catalogo_id)), 201


@bp.put("/<int:catalogo_id>")
@requires_permission("catalogos_vendas", "editar")
def editar(catalogo_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = _catalogo_ou_404(conn, catalogo_id)

    nome = (dados.get("nome", anterior["nome"]) or "").strip()
    if not nome:
        raise ApiError("Informe o nome do catálogo.", status=400)
    descricao = dados.get("descricao", anterior["descricao"])
    visibilidade = dados.get("visibilidade", anterior["visibilidade"])
    if visibilidade not in ("todos", "restrita"):
        raise ApiError("visibilidade deve ser 'todos' ou 'restrita'.", status=400)
    status = dados.get("status", anterior["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)
    ordem = dados.get("ordem", anterior["ordem"])

    conn.execute(
        "UPDATE catalogos_vendas SET nome = ?, descricao = ?, visibilidade = ?, status = ?, ordem = ? WHERE id = ?",
        (nome, descricao, visibilidade, status, ordem, catalogo_id),
    )
    audit.registrar(conn, tabela="catalogos_vendas", registro_id=catalogo_id, usuario_id=usuario_atual["id"],
                     acao="catalogo_vendas_editado", valor_anterior=anterior,
                     valor_novo={"nome": nome, "visibilidade": visibilidade, "status": status},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_catalogo_detalhado(conn, catalogo_id))


@bp.put("/<int:catalogo_id>/itens")
@requires_permission("catalogos_vendas", "editar")
def definir_itens(catalogo_id):
    """Substitui a lista INTEIRA de itens do catálogo pela informada — mais
    simples de operar numa tela de "marcar/desmarcar itens" do que
    adicionar/remover um de cada vez."""
    conn = get_db()
    _catalogo_ou_404(conn, catalogo_id)
    dados = request.get_json(silent=True) or {}
    item_ids = dados.get("item_ids") or []
    if not isinstance(item_ids, list):
        raise ApiError("item_ids deve ser uma lista de ids de item.", status=400)
    item_ids = [int(i) for i in item_ids]
    if item_ids:
        existentes = {
            r["id"] for r in conn.execute(
                f"SELECT id FROM itens WHERE id IN ({','.join('?' * len(item_ids))})", item_ids
            ).fetchall()
        }
        faltando = set(item_ids) - existentes
        if faltando:
            raise ApiError(f"Item(ns) não encontrado(s): {', '.join(str(i) for i in sorted(faltando))}.", status=404)

    conn.execute("DELETE FROM catalogos_vendas_itens WHERE catalogo_id = ?", (catalogo_id,))
    for item_id in item_ids:
        conn.execute(
            "INSERT INTO catalogos_vendas_itens (catalogo_id, item_id) VALUES (?, ?)", (catalogo_id, item_id)
        )
    return jsonify(_catalogo_detalhado(conn, catalogo_id))


@bp.put("/<int:catalogo_id>/vendedores")
@requires_permission("catalogos_vendas", "editar")
def definir_vendedores(catalogo_id):
    """Mesma ideia de `definir_itens` — substitui a lista inteira de
    vendedores permitidos. Só faz sentido quando `visibilidade='restrita'`,
    mas grava mesmo assim (fica pronta se o admin trocar a visibilidade
    depois sem perder a seleção)."""
    conn = get_db()
    _catalogo_ou_404(conn, catalogo_id)
    dados = request.get_json(silent=True) or {}
    usuario_ids = dados.get("usuario_ids") or []
    if not isinstance(usuario_ids, list):
        raise ApiError("usuario_ids deve ser uma lista de ids de usuário.", status=400)
    usuario_ids = [int(i) for i in usuario_ids]
    if usuario_ids:
        existentes = {
            r["id"] for r in conn.execute(
                f"SELECT id FROM usuarios WHERE id IN ({','.join('?' * len(usuario_ids))})", usuario_ids
            ).fetchall()
        }
        faltando = set(usuario_ids) - existentes
        if faltando:
            raise ApiError(f"Usuário(s) não encontrado(s): {', '.join(str(i) for i in sorted(faltando))}.", status=404)

    conn.execute("DELETE FROM catalogos_vendas_vendedores WHERE catalogo_id = ?", (catalogo_id,))
    for usuario_id in usuario_ids:
        conn.execute(
            "INSERT INTO catalogos_vendas_vendedores (catalogo_id, usuario_id) VALUES (?, ?)",
            (catalogo_id, usuario_id),
        )
    return jsonify(_catalogo_detalhado(conn, catalogo_id))
