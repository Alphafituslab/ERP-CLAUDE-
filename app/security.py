"""
Primitivas de segurança — implementadas apenas com a biblioteca padrão do
Python (hashlib, hmac, secrets, base64) mais PyJWT, porque este ambiente de
desenvolvimento não tem acesso de rede para instalar pacotes adicionais
(ex.: bcrypt, argon2-cffi, pyotp). PBKDF2-HMAC-SHA256 com 200.000 iterações
e TOTP (RFC 6238) implementado manualmente são práticas reconhecidas e
seguras — não são um "atalho inseguro". Ver README.md para notas sobre
evoluir para Argon2id em produção, se desejado.
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time

import jwt

# ---------------------------------------------------------------------------
# Senhas — PBKDF2-HMAC-SHA256
# ---------------------------------------------------------------------------
PBKDF2_ITERATIONS = 200_000


def hash_password(senha: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(senha: str, senha_hash: str) -> bool:
    try:
        algo, iterations_s, salt_hex, hash_hex = senha_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    derived = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def validar_politica_senha(senha: str):
    """Retorna lista de violações (vazia = senha aceita)."""
    problemas = []
    if len(senha) < 12:
        problemas.append("A senha deve ter no mínimo 12 caracteres.")
    if not any(c.islower() for c in senha):
        problemas.append("A senha deve conter ao menos uma letra minúscula.")
    if not any(c.isupper() for c in senha):
        problemas.append("A senha deve conter ao menos uma letra maiúscula.")
    if not any(c.isdigit() for c in senha):
        problemas.append("A senha deve conter ao menos um número.")
    if not any(not c.isalnum() for c in senha):
        problemas.append("A senha deve conter ao menos um caractere especial.")
    senhas_comuns = {"password", "123456789012", "senha1234567", "qwertyuiop12"}
    if senha.lower() in senhas_comuns:
        problemas.append("Esta senha é comum demais e não pode ser usada.")
    return problemas


# ---------------------------------------------------------------------------
# TOTP — RFC 6238 (compatível com Google Authenticator / Microsoft Authenticator)
# ---------------------------------------------------------------------------
def gerar_totp_secret() -> str:
    """Gera um segredo base32 de 20 bytes (160 bits, padrão recomendado)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    padded = secret_b32 + "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(padded.upper())
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code_int = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code_int).zfill(digits)


def totp_atual(secret_b32: str, timestamp: float = None, step: int = 30, digits: int = 6) -> str:
    ts = timestamp if timestamp is not None else time.time()
    counter = int(ts // step)
    return _hotp(secret_b32, counter, digits)


def verificar_totp(secret_b32: str, codigo: str, timestamp: float = None, step: int = 30,
                    janela_tolerancia: int = 1) -> bool:
    """Aceita o código do intervalo atual e de `janela_tolerancia` intervalos
    antes/depois, para tolerar pequena diferença de relógio entre servidor e
    celular do usuário."""
    ts = timestamp if timestamp is not None else time.time()
    counter = int(ts // step)
    codigo = (codigo or "").strip()
    for delta in range(-janela_tolerancia, janela_tolerancia + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + delta), codigo):
            return True
    return False


def otpauth_uri(secret_b32: str, email: str, emissor: str = "Alphafitus OS") -> str:
    return f"otpauth://totp/{emissor}:{email}?secret={secret_b32}&issuer={emissor}&algorithm=SHA1&digits=6&period=30"


# ---------------------------------------------------------------------------
# JWT — tokens de acesso de curta duração; permissões NUNCA vão dentro do
# token (são checadas no banco a cada chamada, para que uma revogação de
# permissão tenha efeito imediato, sem esperar o token expirar).
# ---------------------------------------------------------------------------
ACCESS_TOKEN_TTL_SECONDS = 15 * 60
LOGIN_TICKET_TTL_SECONDS = 5 * 60


def _caminho_chave_persistida() -> str:
    """Mesma pasta do banco de dados (`data/`), então já é criada e
    preservada nos mesmos backups/instalações que o banco em si."""
    from . import db as db_module

    return os.path.join(os.path.dirname(db_module.get_db_path()), ".jwt_secret")


def _carregar_ou_criar_chave_persistida() -> str:
    """Fallback de última instância para quando `ALPHAFITUS_JWT_SECRET`
    não chegou até este processo pela variável de ambiente.

    Motivo de existir: em instalações reais no Windows, esse valor
    normalmente é gerado pelo `_ambiente.bat` e propagado via `set` num
    `config_ambiente.bat` que outro `.bat` chama antes de subir o
    servidor — um encadeamento de scripts que se mostrou frágil na
    prática (ex.: rodar o servidor por um atalho/caminho diferente do
    que gerou o arquivo, ou qualquer coisa que rompa a corrente de
    `call`s antes do processo do Python realmente nascer). Em vez de só
    recusar iniciar toda vez que essa corrente falha por qualquer
    motivo, o processo Python passa a cuidar sozinho de gerar e
    persistir sua própria chave, na mesma pasta do banco de dados —
    fica única por instalação (não é um valor fixo no código) e não
    depende de nenhum script externo ter rodado corretamente antes.
    `ALPHAFITUS_JWT_SECRET`, quando definida, continua tendo prioridade
    (é o que os scripts de Serviço do Windows usam, por exemplo — ver
    `service_windows.py`)."""
    caminho = _caminho_chave_persistida()
    try:
        if os.path.isfile(caminho):
            with open(caminho, "r", encoding="utf-8") as f:
                chave = f.read().strip()
            if chave:
                return chave
    except OSError:
        pass

    nova_chave = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(nova_chave)
    except OSError:
        # Não conseguiu persistir (ex.: pasta sem permissão de escrita) —
        # ainda assim devolve uma chave válida para esta execução, em vez
        # de travar o login; só não vai sobreviver a um reinício do
        # processo (tokens emitidos antes de um reinício assim deixam de
        # validar, o que é inconveniente mas nunca inseguro).
        pass
    return nova_chave


def _get_jwt_secret() -> str:
    secret = os.environ.get("ALPHAFITUS_JWT_SECRET")
    if secret:
        return secret
    return _carregar_ou_criar_chave_persistida()


def emitir_access_token(usuario_id: int, jti: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(usuario_id),
        "jti": jti,
        "tipo": "access",
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def emitir_login_ticket(usuario_id: int) -> str:
    """Token de curtíssima duração emitido após senha correta quando 2FA está
    ativo, usado apenas para completar o passo /auth/2fa/verificar."""
    now = int(time.time())
    payload = {
        "sub": str(usuario_id),
        "tipo": "login_ticket",
        "iat": now,
        "exp": now + LOGIN_TICKET_TTL_SECONDS,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def decodificar_token(token: str) -> dict:
    return jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])


def gerar_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
