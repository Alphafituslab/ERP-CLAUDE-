"""
Contexto de requisição: conexão de banco por requisição e resolução do
usuário autenticado a partir do JWT enviado no header Authorization.
"""
import datetime
import sqlite3

from flask import g, request

from . import db as db_module
from . import security


class ApiError(Exception):
    def __init__(self, mensagem, status=400, codigo="erro"):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.codigo = codigo


class AuthError(ApiError):
    def __init__(self, mensagem="Não autenticado."):
        super().__init__(mensagem, status=401, codigo="nao_autenticado")


class ForbiddenError(ApiError):
    def __init__(self, mensagem="Você não tem permissão para executar esta ação."):
        super().__init__(mensagem, status=403, codigo="sem_permissao")


def get_db() -> sqlite3.Connection:
    if "db_conn" not in g:
        g.db_conn = db_module._connect()
    return g.db_conn


def close_db(exception=None):
    # IMPORTANTE: `exception` só vem preenchido aqui para uma exceção
    # verdadeiramente NÃO tratada (que não bateu em nenhum @app.errorhandler
    # registrado) — uma ApiError normal (400/403/404/423 etc.) É tratada por
    # _handle_api_error em app/__init__.py e devolve uma resposta comum, então
    # o Flask considera a requisição "bem-sucedida" para efeito de teardown e
    # chama isto aqui com exception=None, ou seja, ainda faz COMMIT.
    #
    # Isso é proposital, não um bug: em vários lugares do sistema (ex.:
    # auth.py registrando uma tentativa de login falha e incrementando o
    # contador de bloqueio ANTES de levantar AuthError) a escrita deve ser
    # persistida mesmo que a requisição termine em erro para quem chamou —
    # é assim que o bloqueio por tentativas seguidas (MAX_TENTATIVAS_LOGIN,
    # em auth.py) e a trilha de auditoria de tentativas malsucedidas
    # funcionam.
    #
    # Por isso, qualquer rota que precise fazer VÁRIAS escritas
    # relacionadas de forma tudo-ou-nada (ex.: reservar estoque para cada
    # item de um pedido de venda) não pode contar com um `raise ApiError`
    # no meio do caminho para desfazer o que já foi escrito — precisa
    # validar TUDO primeiro (sem escrever nada) e só depois gravar,
    # exatamente como as rotas de fórmulas/produção/estoque/comercial
    # já fazem.
    conn = g.pop("db_conn", None)
    if conn is not None:
        if exception is None:
            conn.commit()
        else:
            conn.rollback()
        conn.close()


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "desconhecido"


def client_device() -> str:
    return request.headers.get("User-Agent", "desconhecido")[:255]


def get_current_user() -> dict:
    """Lê o header Authorization: Bearer <token>, valida o JWT e carrega o
    usuário do banco (sempre "fresco" — nunca confia em dados cacheados no
    token para status/permite, só o id do usuário)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AuthError("Token de acesso ausente.")
    token = auth_header[len("Bearer "):].strip()

    try:
        payload = security.decodificar_token(token)
    except Exception:
        raise AuthError("Token de acesso inválido ou expirado.")

    if payload.get("tipo") != "access":
        raise AuthError("Tipo de token inválido para esta operação.")

    usuario_id = int(payload["sub"])
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise AuthError("Usuário não encontrado.")
    usuario = dict(row)
    if usuario["status"] != "ativo":
        raise AuthError("Usuário inativo ou bloqueado.")

    # Fase 44 — "Usuários Online" (Administração do Memorial Técnico):
    # atualização silenciosa, de propósito SEM entrada na trilha de
    # auditoria (uma linha de auditoria por requisição autenticada seria
    # puro ruído — o mesmo raciocínio de não auditar leituras simples) e
    # sem impedir a requisição de continuar se a escrita falhar por
    # qualquer motivo (nunca pode ser a causa de um 500 numa rota que não
    # tem nada a ver com isso).
    agora = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    try:
        conn.execute("UPDATE usuarios SET ultimo_acesso_em = ? WHERE id = ?", (agora, usuario_id))
        usuario["ultimo_acesso_em"] = agora
    except sqlite3.Error:
        pass

    g.usuario_atual = usuario
    return usuario
