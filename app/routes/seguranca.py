"""
Fase 172 — pedido do usuário (2026-09-14): a exigência de código do
autenticador (2FA) no login virou configurável em vez de regra fixa no
código. Continua LIGADA por padrão (`exigir_2fa = 1`, ver
migrations/schema_fase172.sql) — só muda se um administrador desligar
explicitamente aqui.

Quem lê essa configuração de verdade é `app/routes/auth.py::login()`, no
mesmo ponto em que hoje já checa "dispositivo confiável" — se
`exigir_2fa = 0`, o login pula o passo de 2FA por completo (mesmo pra quem
já tem `dois_fatores_ativo = 1` na própria conta), exatamente como pedido.
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("seguranca", __name__, url_prefix="/api/v1/seguranca")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def obter_configuracao(conn) -> dict:
    row = conn.execute("SELECT * FROM configuracoes_seguranca WHERE id = 1").fetchone()
    if row is None:
        return {"exigir_2fa": True}
    return {"exigir_2fa": bool(row["exigir_2fa"])}


@bp.get("/configuracao")
@requires_permission("seguranca", "visualizar")
def obter_configuracao_seguranca():
    conn = get_db()
    return jsonify(obter_configuracao(conn))


@bp.put("/configuracao")
@requires_permission("seguranca", "configurar")
def atualizar_configuracao_seguranca():
    usuario = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    exigir_2fa = 1 if dados.get("exigir_2fa") else 0
    conn = get_db()
    conn.execute(
        "UPDATE configuracoes_seguranca SET exigir_2fa = ?, atualizado_em = ?, atualizado_por = ? WHERE id = 1",
        (exigir_2fa, _now_iso(), usuario["id"]),
    )
    conn.commit()
    audit.registrar(
        conn, tabela="configuracoes_seguranca", registro_id=1, usuario_id=usuario["id"],
        acao="configuracao_2fa_alterada", valor_novo={"exigir_2fa": bool(exigir_2fa)},
        ip=client_ip(), dispositivo=client_device(),
    )
    conn.commit()
    return jsonify({"exigir_2fa": bool(exigir_2fa)})
