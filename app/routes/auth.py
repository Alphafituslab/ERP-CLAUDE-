import datetime
import secrets

from flask import Blueprint, g, jsonify, request

from .. import audit, security
from ..context import ApiError, AuthError, client_device, client_ip, get_current_user, get_db
from ..permissions import requires_auth

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

MAX_TENTATIVAS_LOGIN = 10
BLOQUEIO_MINUTOS = 3
REFRESH_TOKEN_TTL_DIAS = 7


def _now():
    return datetime.datetime.utcnow()


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ")


def _criar_sessao(conn, usuario_id, ip, dispositivo):
    refresh_token = security.gerar_refresh_token()
    token_hash = security.hash_refresh_token(refresh_token)
    expira_em = _iso(_now() + datetime.timedelta(days=REFRESH_TOKEN_TTL_DIAS))
    cur = conn.execute(
        """
        INSERT INTO sessoes (usuario_id, refresh_token_hash, ip, dispositivo, expira_em)
        VALUES (?, ?, ?, ?, ?)
        """,
        (usuario_id, token_hash, ip, dispositivo, expira_em),
    )
    return refresh_token, cur.lastrowid


def _emitir_tokens(conn, usuario_id, ip, dispositivo):
    refresh_token, sessao_id = _criar_sessao(conn, usuario_id, ip, dispositivo)
    jti = secrets.token_hex(16)
    access_token = security.emitir_access_token(usuario_id, jti)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": security.ACCESS_TOKEN_TTL_SECONDS,
    }


@bp.post("/login")
def login():
    dados = request.get_json(silent=True) or {}
    email = (dados.get("email") or "").strip().lower()
    # `.strip()` aqui é deliberado: a senha inicial (gerada por `seed.py`) e
    # as trocadas por um administrador em `/usuarios` são sempre exibidas
    # num console para a pessoa copiar — um triple-click ou "selecionar
    # linha" no terminal do Windows facilmente inclui um espaço ou quebra
    # de linha invisível antes/depois do texto visível, o que faz a senha
    # colada não bater byte-a-byte com o hash mesmo sendo "a mesma senha"
    # aos olhos de quem está tentando entrar. Só afeta espaços nas PONTAS —
    # nunca mexe no meio da senha, então não reduz a entropia dela.
    senha = (dados.get("senha") or "").strip()
    ip = client_ip()
    dispositivo = client_device()
    conn = get_db()

    if not email or not senha:
        raise ApiError("Informe email e senha.", status=400)

    usuario = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()

    if usuario is None:
        # Não revela se o e-mail existe ou não.
        audit.registrar(conn, tabela="usuarios", registro_id=None, usuario_id=None,
                         acao="login_falhou", motivo=f"email não encontrado: {email}", ip=ip, dispositivo=dispositivo)
        raise AuthError("Email ou senha inválidos.")

    usuario = dict(usuario)

    if usuario["status"] != "ativo":
        audit.registrar(conn, tabela="usuarios", registro_id=usuario["id"], usuario_id=usuario["id"],
                         acao="login_negado_status", motivo=f"status={usuario['status']}", ip=ip, dispositivo=dispositivo)
        raise AuthError("Usuário inativo ou bloqueado. Fale com um administrador.")

    if usuario["bloqueado_ate"]:
        bloqueado_ate = _parse_iso(usuario["bloqueado_ate"])
        if bloqueado_ate > _now():
            raise ApiError(
                f"Conta temporariamente bloqueada por excesso de tentativas. Tente novamente após "
                f"{usuario['bloqueado_ate']}.",
                status=423, codigo="conta_bloqueada",
            )

    if not security.verify_password(senha, usuario["senha_hash"]):
        tentativas = usuario["tentativas_login_falhas"] + 1
        bloqueado_ate = None
        if tentativas >= MAX_TENTATIVAS_LOGIN:
            bloqueado_ate = _iso(_now() + datetime.timedelta(minutes=BLOQUEIO_MINUTOS))
        conn.execute(
            "UPDATE usuarios SET tentativas_login_falhas = ?, bloqueado_ate = ? WHERE id = ?",
            (tentativas, bloqueado_ate, usuario["id"]),
        )
        audit.registrar(conn, tabela="usuarios", registro_id=usuario["id"], usuario_id=usuario["id"],
                         acao="login_falhou", motivo=f"senha incorreta (tentativa {tentativas})",
                         ip=ip, dispositivo=dispositivo)
        raise AuthError("Email ou senha inválidos.")

    # Senha correta: zera contador de tentativas.
    conn.execute(
        "UPDATE usuarios SET tentativas_login_falhas = 0, bloqueado_ate = NULL WHERE id = ?",
        (usuario["id"],),
    )

    if usuario["dois_fatores_ativo"]:
        login_ticket = security.emitir_login_ticket(usuario["id"])
        audit.registrar(conn, tabela="usuarios", registro_id=usuario["id"], usuario_id=usuario["id"],
                         acao="login_senha_ok_aguardando_2fa", ip=ip, dispositivo=dispositivo)
        return jsonify({"requires_2fa": True, "login_ticket": login_ticket})

    conn.execute(
        "UPDATE usuarios SET ultimo_login_em = ?, ultimo_login_ip = ? WHERE id = ?",
        (_iso(_now()), ip, usuario["id"]),
    )
    tokens = _emitir_tokens(conn, usuario["id"], ip, dispositivo)
    audit.registrar(conn, tabela="usuarios", registro_id=usuario["id"], usuario_id=usuario["id"],
                     acao="login_sucesso", ip=ip, dispositivo=dispositivo)
    return jsonify(tokens)


@bp.post("/2fa/verificar")
def verificar_2fa():
    dados = request.get_json(silent=True) or {}
    login_ticket = dados.get("login_ticket")
    codigo = dados.get("codigo")
    ip = client_ip()
    dispositivo = client_device()
    conn = get_db()

    if not login_ticket or not codigo:
        raise ApiError("Informe login_ticket e codigo.", status=400)

    try:
        payload = security.decodificar_token(login_ticket)
    except Exception:
        raise AuthError("login_ticket inválido ou expirado. Faça login novamente.")

    if payload.get("tipo") != "login_ticket":
        raise AuthError("Token inválido para esta operação.")

    usuario_id = int(payload["sub"])
    usuario = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if usuario is None:
        raise AuthError("Usuário não encontrado.")
    usuario = dict(usuario)

    if not usuario["dois_fatores_ativo"] or not usuario["dois_fatores_secret"]:
        raise ApiError("Este usuário não tem 2FA ativo.", status=400)

    if not security.verificar_totp(usuario["dois_fatores_secret"], codigo):
        audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_id,
                         acao="login_2fa_falhou", ip=ip, dispositivo=dispositivo)
        raise AuthError("Código de dois fatores inválido.")

    conn.execute(
        "UPDATE usuarios SET ultimo_login_em = ?, ultimo_login_ip = ? WHERE id = ?",
        (_iso(_now()), ip, usuario_id),
    )
    tokens = _emitir_tokens(conn, usuario_id, ip, dispositivo)
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_id,
                     acao="login_sucesso_2fa", ip=ip, dispositivo=dispositivo)
    return jsonify(tokens)


@bp.post("/2fa/setup")
@requires_auth
def setup_2fa():
    usuario = g.usuario_atual
    conn = get_db()
    if usuario["dois_fatores_ativo"]:
        raise ApiError("Dois fatores já está ativo para este usuário. Desative antes de reconfigurar.", status=400)
    secret = security.gerar_totp_secret()
    conn.execute("UPDATE usuarios SET dois_fatores_secret = ? WHERE id = ?", (secret, usuario["id"]))
    audit.registrar(conn, tabela="usuarios", registro_id=usuario["id"], usuario_id=usuario["id"],
                     acao="2fa_setup_iniciado", ip=client_ip(), dispositivo=client_device())
    return jsonify({
        "secret": secret,
        "otpauth_uri": security.otpauth_uri(secret, usuario["email"]),
        "instrucoes": "Adicione este segredo no seu aplicativo autenticador (Google Authenticator, Microsoft "
                       "Authenticator etc.) e confirme com POST /api/v1/auth/2fa/confirmar.",
    })


@bp.post("/2fa/confirmar")
@requires_auth
def confirmar_2fa():
    usuario = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    codigo = dados.get("codigo")
    conn = get_db()

    if not usuario["dois_fatores_secret"]:
        raise ApiError("Chame /2fa/setup antes de confirmar.", status=400)
    if not codigo or not security.verificar_totp(usuario["dois_fatores_secret"], codigo):
        raise ApiError("Código inválido.", status=400)

    conn.execute("UPDATE usuarios SET dois_fatores_ativo = 1 WHERE id = ?", (usuario["id"],))
    audit.registrar(conn, tabela="usuarios", registro_id=usuario["id"], usuario_id=usuario["id"],
                     acao="2fa_ativado", ip=client_ip(), dispositivo=client_device())
    return jsonify({"dois_fatores_ativo": True})


@bp.post("/refresh")
def refresh():
    dados = request.get_json(silent=True) or {}
    refresh_token = dados.get("refresh_token")
    ip = client_ip()
    dispositivo = client_device()
    conn = get_db()

    if not refresh_token:
        raise ApiError("Informe refresh_token.", status=400)

    token_hash = security.hash_refresh_token(refresh_token)
    sessao = conn.execute(
        "SELECT * FROM sessoes WHERE refresh_token_hash = ? AND revogado = 0", (token_hash,)
    ).fetchone()

    if sessao is None:
        raise AuthError("Refresh token inválido ou já revogado.")
    sessao = dict(sessao)

    if _parse_iso(sessao["expira_em"]) <= _now():
        raise AuthError("Refresh token expirado. Faça login novamente.")

    # Rotação: revoga o token usado e emite um novo par.
    conn.execute(
        "UPDATE sessoes SET revogado = 1, revogado_em = ?, revogado_por = ? WHERE id = ?",
        (_iso(_now()), sessao["usuario_id"], sessao["id"]),
    )
    tokens = _emitir_tokens(conn, sessao["usuario_id"], ip, dispositivo)
    audit.registrar(conn, tabela="sessoes", registro_id=sessao["id"], usuario_id=sessao["usuario_id"],
                     acao="refresh_token_rotacionado", ip=ip, dispositivo=dispositivo)
    return jsonify(tokens)


@bp.post("/logout")
def logout():
    dados = request.get_json(silent=True) or {}
    refresh_token = dados.get("refresh_token")
    conn = get_db()
    if not refresh_token:
        raise ApiError("Informe refresh_token.", status=400)
    token_hash = security.hash_refresh_token(refresh_token)
    sessao = conn.execute("SELECT * FROM sessoes WHERE refresh_token_hash = ?", (token_hash,)).fetchone()
    if sessao is not None:
        sessao = dict(sessao)
        conn.execute(
            "UPDATE sessoes SET revogado = 1, revogado_em = ?, revogado_por = ? WHERE id = ?",
            (_iso(_now()), sessao["usuario_id"], sessao["id"]),
        )
        audit.registrar(conn, tabela="sessoes", registro_id=sessao["id"], usuario_id=sessao["usuario_id"],
                         acao="logout", ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.get("/sessoes")
@requires_auth
def minhas_sessoes():
    usuario = g.usuario_atual
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, ip, dispositivo, criado_em, expira_em, revogado, revogado_em
        FROM sessoes WHERE usuario_id = ? ORDER BY criado_em DESC
        """,
        (usuario["id"],),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/sessoes/<int:sessao_id>/encerrar")
@requires_auth
def encerrar_sessao(sessao_id):
    usuario = g.usuario_atual
    conn = get_db()
    sessao = conn.execute("SELECT * FROM sessoes WHERE id = ?", (sessao_id,)).fetchone()
    if sessao is None:
        raise ApiError("Sessão não encontrada.", status=404)
    sessao = dict(sessao)
    if sessao["usuario_id"] != usuario["id"]:
        from ..permissions import usuario_tem_permissao
        if not usuario_tem_permissao(conn, usuario["id"], "usuarios", "encerrar_sessao_de_outro"):
            raise ApiError("Você só pode encerrar suas próprias sessões.", status=403)
    conn.execute(
        "UPDATE sessoes SET revogado = 1, revogado_em = ?, revogado_por = ? WHERE id = ?",
        (_iso(_now()), usuario["id"], sessao_id),
    )
    audit.registrar(conn, tabela="sessoes", registro_id=sessao_id, usuario_id=usuario["id"],
                     acao="sessao_encerrada_manualmente", ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.post("/trocar-senha")
@requires_auth
def trocar_senha():
    usuario = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    # Mesmo motivo do `/auth/login`: a senha atual, nesse fluxo, quase
    # sempre é a senha inicial copiada do console — sujeita ao mesmo risco
    # de espaço/quebra de linha nas pontas ao colar.
    senha_atual = (dados.get("senha_atual") or "").strip()
    senha_nova = dados.get("senha_nova") or ""
    conn = get_db()

    if not security.verify_password(senha_atual, usuario["senha_hash"]):
        raise ApiError("Senha atual incorreta.", status=400)

    problemas = security.validar_politica_senha(senha_nova)
    if problemas:
        raise ApiError("Senha não atende à política de segurança: " + " ".join(problemas), status=400)

    novo_hash = security.hash_password(senha_nova)
    conn.execute(
        "UPDATE usuarios SET senha_hash = ?, senha_deve_trocar = 0, senha_trocada_em = ? WHERE id = ?",
        (novo_hash, _iso(_now()), usuario["id"]),
    )
    audit.registrar(conn, tabela="usuarios", registro_id=usuario["id"], usuario_id=usuario["id"],
                     acao="senha_alterada", ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.get("/me")
@requires_auth
def me():
    from ..permissions import permissoes_do_usuario
    usuario = g.usuario_atual
    conn = get_db()
    perfis = conn.execute(
        """
        SELECT pf.id, pf.nome FROM usuario_perfil up
        JOIN perfis pf ON pf.id = up.perfil_id
        WHERE up.usuario_id = ?
        """,
        (usuario["id"],),
    ).fetchall()
    return jsonify({
        "id": usuario["id"],
        "nome": usuario["nome"],
        "email": usuario["email"],
        "dois_fatores_ativo": bool(usuario["dois_fatores_ativo"]),
        "notificar_por_email": bool(usuario["notificar_por_email"]),
        "perfis": [dict(p) for p in perfis],
        "permissoes": permissoes_do_usuario(conn, usuario["id"]),
    })
