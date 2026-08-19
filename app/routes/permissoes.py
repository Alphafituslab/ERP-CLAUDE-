from flask import jsonify, Blueprint

from ..context import get_db
from ..permissions import requires_permission

bp = Blueprint("permissoes", __name__, url_prefix="/api/v1/permissoes")


@bp.get("")
@requires_permission("permissoes", "visualizar")
def listar():
    conn = get_db()
    rows = conn.execute("SELECT * FROM permissoes ORDER BY modulo, acao").fetchall()
    return jsonify([dict(r) for r in rows])
