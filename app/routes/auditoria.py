from flask import Blueprint, jsonify, request

from .. import audit
from ..context import get_db
from ..permissions import requires_permission

bp = Blueprint("auditoria", __name__, url_prefix="/api/v1/auditoria")

# Nenhuma rota de escrita existe aqui de propósito — a trilha de auditoria
# só é gravada internamente pelas próprias operações (ver app/audit.py) e
# nunca pode ser criada, alterada ou apagada via API. O banco também impede
# UPDATE/DELETE por trigger (migrations/schema.sql).


@bp.get("")
@requires_permission("auditoria", "visualizar")
def listar():
    conn = get_db()
    tabela = request.args.get("tabela")
    usuario_id = request.args.get("usuario_id", type=int)
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    limite = request.args.get("limite", default=200, type=int)
    limite = max(1, min(limite, 1000))

    registros = audit.listar(
        conn, tabela=tabela, usuario_id=usuario_id, data_inicio=data_inicio, data_fim=data_fim, limite=limite
    )
    return jsonify(registros)
