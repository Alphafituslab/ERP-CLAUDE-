import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit, security
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import bloquear_autoelevacao, requires_permission

bp = Blueprint("usuarios", __name__, url_prefix="/api/v1/usuarios")

# Fase 44 — "Usuários Online" (Administração do Memorial Técnico): janela
# de tolerância para considerar alguém "online agora". `ultimo_acesso_em`
# (app/context.py) é atualizado a cada requisição autenticada — 5 minutos
# cobre alguém que está de fato navegando pelo sistema (mesmo com telas
# que não fazem chamada nenhuma por um tempo) sem contar como "online"
# quem só logou de manhã e não voltou a usar o sistema.
ONLINE_JANELA_MINUTOS = 5


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _publico(usuario_row):
    d = dict(usuario_row)
    d.pop("senha_hash", None)
    d.pop("dois_fatores_secret", None)
    return d


def _perfis_do_usuario(conn, usuario_id):
    rows = conn.execute(
        "SELECT pf.id, pf.nome FROM usuario_perfil up JOIN perfis pf ON pf.id = up.perfil_id WHERE up.usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@bp.get("")
@requires_permission("usuarios", "visualizar")
def listar():
    conn = get_db()
    rows = conn.execute("SELECT * FROM usuarios ORDER BY nome").fetchall()
    resultado = []
    for r in rows:
        u = _publico(r)
        u["perfis"] = _perfis_do_usuario(conn, u["id"])
        resultado.append(u)
    return jsonify(resultado)


@bp.get("/<int:usuario_id>")
@requires_permission("usuarios", "visualizar")
def obter(usuario_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    u = _publico(row)
    u["perfis"] = _perfis_do_usuario(conn, usuario_id)
    return jsonify(u)


@bp.post("")
@requires_permission("usuarios", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip().lower()
    senha = dados.get("senha") or ""
    perfil_ids = dados.get("perfil_ids") or []
    conn = get_db()

    if not nome or not email or not senha:
        raise ApiError("Informe nome, email e senha.", status=400)

    problemas = security.validar_politica_senha(senha)
    if problemas:
        raise ApiError("Senha não atende à política de segurança: " + " ".join(problemas), status=400)

    existente = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
    if existente:
        raise ApiError("Já existe um usuário com este email.", status=409)

    senha_hash = security.hash_password(senha)
    cur = conn.execute(
        """
        INSERT INTO usuarios (nome, email, senha_hash, senha_deve_trocar, criado_por)
        VALUES (?, ?, ?, 1, ?)
        """,
        (nome, email, senha_hash, usuario_atual["id"]),
    )
    novo_id = cur.lastrowid

    for perfil_id in perfil_ids:
        conn.execute(
            "INSERT INTO usuario_perfil (usuario_id, perfil_id, atribuido_por) VALUES (?, ?, ?)",
            (novo_id, perfil_id, usuario_atual["id"]),
        )

    audit.registrar(conn, tabela="usuarios", registro_id=novo_id, usuario_id=usuario_atual["id"],
                     acao="usuario_criado", valor_novo={"nome": nome, "email": email, "perfil_ids": perfil_ids},
                     ip=client_ip(), dispositivo=client_device())

    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (novo_id,)).fetchone()
    u = _publico(row)
    u["perfis"] = _perfis_do_usuario(conn, novo_id)
    return jsonify(u), 201


@bp.put("/<int:usuario_id>")
@requires_permission("usuarios", "editar")
def editar(usuario_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    anterior = _publico(row)

    nome = dados.get("nome", row["nome"])
    email = (dados.get("email", row["email"]) or "").strip().lower()

    conn.execute(
        "UPDATE usuarios SET nome = ?, email = ?, atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (nome, email, _now_iso(), usuario_atual["id"], usuario_id),
    )

    novo_row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    novo = _publico(novo_row)
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="usuario_editado", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    novo["perfis"] = _perfis_do_usuario(conn, usuario_id)
    return jsonify(novo)


@bp.put("/<int:usuario_id>/perfis")
@requires_permission("usuarios", "editar")
def definir_perfis(usuario_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    perfil_ids = dados.get("perfil_ids")
    conn = get_db()

    if perfil_ids is None or not isinstance(perfil_ids, list):
        raise ApiError("Informe perfil_ids como lista.", status=400)

    alvo = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if alvo is None:
        raise ApiError("Usuário não encontrado.", status=404)

    bloquear_autoelevacao(conn, usuario_atual["id"], usuario_id, perfil_ids)

    anteriores = _perfis_do_usuario(conn, usuario_id)
    conn.execute("DELETE FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,))
    for perfil_id in perfil_ids:
        conn.execute(
            "INSERT INTO usuario_perfil (usuario_id, perfil_id, atribuido_por) VALUES (?, ?, ?)",
            (usuario_id, perfil_id, usuario_atual["id"]),
        )
    novos = _perfis_do_usuario(conn, usuario_id)

    audit.registrar(conn, tabela="usuario_perfil", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="perfis_do_usuario_alterados", valor_anterior=anteriores, valor_novo=novos,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"usuario_id": usuario_id, "perfis": novos})


@bp.post("/<int:usuario_id>/inativar")
@requires_permission("usuarios", "inativar")
def inativar(usuario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    if usuario_id == usuario_atual["id"]:
        raise ApiError("Você não pode inativar a própria conta.", status=400)
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    conn.execute(
        "UPDATE usuarios SET status = 'inativo', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], usuario_id),
    )
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="usuario_inativado", valor_anterior={"status": row["status"]}, valor_novo={"status": "inativo"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.post("/<int:usuario_id>/reativar")
@requires_permission("usuarios", "inativar")
def reativar(usuario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    conn.execute(
        "UPDATE usuarios SET status = 'ativo', tentativas_login_falhas = 0, bloqueado_ate = NULL, "
        "atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], usuario_id),
    )
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="usuario_reativado", valor_anterior={"status": row["status"]}, valor_novo={"status": "ativo"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.get("/online")
@requires_permission("usuarios", "visualizar")
def usuarios_online():
    """Fase 44 — "Usuários Online" (item da Administração do Memorial
    Técnico que o cliente pediu para replicar, ver schema_fase44.sql).
    Reaproveita a mesma permissão `usuarios.visualizar` de sempre — ver
    quem está online é uma extensão natural de ver a lista de usuários,
    não uma capacidade nova. Devolve TODOS os usuários ativos, cada um já
    com `online` calculado a partir de `ultimo_acesso_em` — o front decide
    como destacar/ordenar; banco vazio ou sem ninguém navegando agora
    simplesmente devolve todo mundo com `online: false`, sem quebrar."""
    conn = get_db()
    limite = (datetime.datetime.utcnow() - datetime.timedelta(minutes=ONLINE_JANELA_MINUTOS)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    rows = conn.execute("SELECT * FROM usuarios WHERE status = 'ativo' ORDER BY nome").fetchall()
    resultado = []
    for r in rows:
        u = _publico(r)
        u["perfis"] = _perfis_do_usuario(conn, u["id"])
        u["online"] = bool(u["ultimo_acesso_em"]) and u["ultimo_acesso_em"] >= limite
        resultado.append(u)
    resultado.sort(key=lambda u: (not u["online"], u["nome"]))
    return jsonify({"janela_minutos": ONLINE_JANELA_MINUTOS, "usuarios": resultado})
