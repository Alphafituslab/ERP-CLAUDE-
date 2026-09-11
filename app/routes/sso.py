"""
Pedido do usuário: quem já está logado no ERP e tem a permissão habilitada no
seu cadastro cai direto na tela principal do Memorial Técnico, Protocolo de
Estabilidade ou Treinador de HPLC ao clicar no menu — sem nenhuma tela de
login em nenhum dos três sistemas externos.

Mecanismo: um ticket assinado de curtíssima duração (60s, HMAC-SHA256),
usando o MESMO segredo por sistema que já existe em config_ambiente.env para
sincronizar senha (`ALPHAFITUS_SYNC_*_MASTER`/`_SECRET`, ver
`app/senha_sync_service.py`) — nenhum segredo novo pra distribuir. O sistema
externo valida a assinatura e, na primeira vez que aquele usuário usar SSO,
provisiona a conta dele na hora (cada usuário do ERP ganha sua PRÓPRIA conta
lá, nunca uma compartilhada).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from flask import Blueprint, g, jsonify

from ..context import ApiError, get_db
from ..permissions import requires_auth, usuario_tem_permissao

bp = Blueprint("sso", __name__, url_prefix="/api/v1/sso")

TICKET_TTL_SEGUNDOS = 60

# Memorial usa sessão por cookie: a URL de troca é a própria rota de
# backend, que já termina em redirect. Protocolo/HPLC usam Bearer token
# guardado em localStorage: a URL de troca é uma rota do FRONTEND (`/sso`,
# ver App.tsx de cada um) que faz a troca via fetch e só então grava o token.
_SISTEMAS = {
    "memorial": {
        "modulo": "memoriais", "acao": "visualizar",
        "url_env": "ALPHAFITUS_SYNC_MEMORIAL_URL",
        "segredo_env": "ALPHAFITUS_SYNC_MEMORIAL_SECRET",
        "caminho_exchange": "/api/auth/sso-exchange",
    },
    "protocolo": {
        "modulo": "protocolo_estabilidade", "acao": "visualizar",
        "url_env": "ALPHAFITUS_SYNC_PROTOCOLO_URL",
        "segredo_env": "ALPHAFITUS_SYNC_PROTOCOLO_MASTER",
        "caminho_exchange": "/sso",
    },
    "hplc": {
        "modulo": "hplc_treinador", "acao": "visualizar",
        "url_env": "ALPHAFITUS_SYNC_HPLC_URL",
        "segredo_env": "ALPHAFITUS_SYNC_HPLC_MASTER",
        "caminho_exchange": "/sso",
    },
}


def _usuario_e_administrador(conn, usuario_id: int) -> bool:
    """"Administrador" é o único perfil que recebe todas as permissões
    (ver seed.py, sentinela "TODAS") — usado aqui só como sinal de qual
    papel provisionar do outro lado (admin vs analista/analyst), nunca
    como substituto da checagem de permissão de acesso em si."""
    row = conn.execute(
        """
        SELECT 1
        FROM usuario_perfil up
        JOIN perfis pf ON pf.id = up.perfil_id
        WHERE up.usuario_id = ? AND pf.nome = 'Administrador'
        LIMIT 1
        """,
        (usuario_id,),
    ).fetchone()
    return row is not None


def _emitir_ticket(segredo: str, usuario: dict, papel: str) -> str:
    payload = {
        "login": usuario["email"],
        "nome": usuario["nome"],
        "papel": papel,
        "exp": int(time.time()) + TICKET_TTL_SEGUNDOS,
        "jti": secrets.token_hex(16),
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("ascii")
    assinatura = hmac.new(segredo.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{assinatura}"


@bp.get("/<sistema>")
@requires_auth
def emitir_url_sso(sistema):
    config = _SISTEMAS.get(sistema)
    if not config:
        raise ApiError("Sistema desconhecido.", status=404, codigo="sistema_invalido")

    usuario = g.usuario_atual
    conn = get_db()
    if not usuario_tem_permissao(conn, usuario["id"], config["modulo"], config["acao"]):
        raise ApiError(
            "Você não tem permissão para acessar este sistema. Solicite a um administrador.",
            status=403, codigo="sem_permissao",
        )

    url_base = os.environ.get(config["url_env"])
    segredo = os.environ.get(config["segredo_env"])
    if not url_base or not segredo:
        raise ApiError(
            "Este sistema não está configurado nesta instalação do Alphafitus OS.",
            status=503, codigo="sso_nao_configurado",
        )

    papel = "admin" if _usuario_e_administrador(conn, usuario["id"]) else "comum"
    ticket = _emitir_ticket(segredo, usuario, papel)
    url = f"{url_base.rstrip('/')}{config['caminho_exchange']}?ticket={ticket}"
    return jsonify({"url": url})
