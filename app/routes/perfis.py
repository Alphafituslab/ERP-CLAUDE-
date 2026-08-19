from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import bloquear_autoedicao_de_permissoes_do_proprio_perfil, requires_permission

bp = Blueprint("perfis", __name__, url_prefix="/api/v1/perfis")


def _permissoes_do_perfil(conn, perfil_id):
    rows = conn.execute(
        """
        SELECT p.id, p.modulo, p.acao, p.descricao, p.exige_dupla_aprovacao
        FROM perfil_permissao pp JOIN permissoes p ON p.id = pp.permissao_id
        WHERE pp.perfil_id = ? ORDER BY p.modulo, p.acao
        """,
        (perfil_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@bp.get("")
@requires_permission("perfis", "visualizar")
def listar():
    conn = get_db()
    rows = conn.execute("SELECT * FROM perfis ORDER BY nome").fetchall()
    resultado = []
    for r in rows:
        pf = dict(r)
        pf["permissoes"] = _permissoes_do_perfil(conn, pf["id"])
        resultado.append(pf)
    return jsonify(resultado)


@bp.post("")
@requires_permission("perfis", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    descricao = dados.get("descricao")
    permissao_ids = dados.get("permissao_ids") or []
    conn = get_db()

    if not nome:
        raise ApiError("Informe o nome do perfil.", status=400)
    if conn.execute("SELECT id FROM perfis WHERE nome = ?", (nome,)).fetchone():
        raise ApiError("Já existe um perfil com este nome.", status=409)

    cur = conn.execute(
        "INSERT INTO perfis (nome, descricao, editavel, criado_por) VALUES (?, ?, 1, ?)",
        (nome, descricao, usuario_atual["id"]),
    )
    perfil_id = cur.lastrowid
    for permissao_id in permissao_ids:
        conn.execute(
            "INSERT INTO perfil_permissao (perfil_id, permissao_id) VALUES (?, ?)",
            (perfil_id, permissao_id),
        )

    audit.registrar(conn, tabela="perfis", registro_id=perfil_id, usuario_id=usuario_atual["id"],
                     acao="perfil_criado", valor_novo={"nome": nome, "permissao_ids": permissao_ids},
                     ip=client_ip(), dispositivo=client_device())

    row = conn.execute("SELECT * FROM perfis WHERE id = ?", (perfil_id,)).fetchone()
    pf = dict(row)
    pf["permissoes"] = _permissoes_do_perfil(conn, perfil_id)
    return jsonify(pf), 201


@bp.put("/<int:perfil_id>/permissoes")
@requires_permission("perfis", "editar")
def definir_permissoes(perfil_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    permissao_ids = dados.get("permissao_ids")
    conn = get_db()

    if permissao_ids is None or not isinstance(permissao_ids, list):
        raise ApiError("Informe permissao_ids como lista.", status=400)

    perfil = conn.execute("SELECT * FROM perfis WHERE id = ?", (perfil_id,)).fetchone()
    if perfil is None:
        raise ApiError("Perfil não encontrado.", status=404)
    if not perfil["editavel"]:
        raise ApiError(
            "Este é um perfil de sistema (ex.: Administrador) e suas permissões não podem ser alteradas "
            "para preservar a integridade do controle de acesso.",
            status=403,
        )
    bloquear_autoedicao_de_permissoes_do_proprio_perfil(conn, usuario_atual["id"], perfil_id)

    anteriores = _permissoes_do_perfil(conn, perfil_id)
    conn.execute("DELETE FROM perfil_permissao WHERE perfil_id = ?", (perfil_id,))
    for permissao_id in permissao_ids:
        conn.execute(
            "INSERT INTO perfil_permissao (perfil_id, permissao_id) VALUES (?, ?)",
            (perfil_id, permissao_id),
        )
    novas = _permissoes_do_perfil(conn, perfil_id)

    audit.registrar(conn, tabela="perfil_permissao", registro_id=perfil_id, usuario_id=usuario_atual["id"],
                     acao="permissoes_do_perfil_alteradas", valor_anterior=anteriores, valor_novo=novas,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"perfil_id": perfil_id, "permissoes": novas})


@bp.delete("/<int:perfil_id>")
@requires_permission("perfis", "excluir")
def excluir(perfil_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    perfil = conn.execute("SELECT * FROM perfis WHERE id = ?", (perfil_id,)).fetchone()
    if perfil is None:
        raise ApiError("Perfil não encontrado.", status=404)
    if not perfil["editavel"]:
        raise ApiError("Perfis de sistema não podem ser excluídos.", status=403)
    em_uso = conn.execute("SELECT COUNT(*) AS n FROM usuario_perfil WHERE perfil_id = ?", (perfil_id,)).fetchone()
    if em_uso["n"] > 0:
        raise ApiError("Este perfil está atribuído a usuários e não pode ser excluído. Remova as atribuições primeiro.",
                        status=409)
    conn.execute("DELETE FROM perfis WHERE id = ?", (perfil_id,))
    audit.registrar(conn, tabela="perfis", registro_id=perfil_id, usuario_id=usuario_atual["id"],
                     acao="perfil_excluido", valor_anterior=dict(perfil),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})
