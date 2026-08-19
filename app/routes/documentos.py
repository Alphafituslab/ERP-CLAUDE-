import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("documentos", __name__, url_prefix="/api/v1/documentos")


@bp.get("")
@requires_permission("documentos", "visualizar")
def listar():
    conn = get_db()
    rows = conn.execute("SELECT * FROM documentos ORDER BY codigo").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@requires_permission("documentos", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    codigo = (dados.get("codigo") or "").strip()
    titulo = (dados.get("titulo") or "").strip()
    tipo = (dados.get("tipo") or "").strip()
    conn = get_db()

    if not codigo or not titulo or not tipo:
        raise ApiError("Informe codigo, titulo e tipo.", status=400)
    if conn.execute("SELECT id FROM documentos WHERE codigo = ?", (codigo,)).fetchone():
        raise ApiError("Já existe um documento com este código.", status=409)

    cur = conn.execute(
        "INSERT INTO documentos (codigo, titulo, tipo, vigencia_inicio, vigencia_fim, criado_por) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (codigo, titulo, tipo, dados.get("vigencia_inicio"), dados.get("vigencia_fim"), usuario_atual["id"]),
    )
    documento_id = cur.lastrowid
    audit.registrar(conn, tabela="documentos", registro_id=documento_id, usuario_id=usuario_atual["id"],
                     acao="documento_criado", valor_novo={"codigo": codigo, "titulo": titulo, "tipo": tipo},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM documentos WHERE id = ?", (documento_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.post("/<int:documento_id>/tornar-obsoleto")
@requires_permission("documentos", "editar")
def tornar_obsoleto(documento_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute("SELECT * FROM documentos WHERE id = ?", (documento_id,)).fetchone()
    if row is None:
        raise ApiError("Documento não encontrado.", status=404)
    conn.execute(
        "UPDATE documentos SET status = 'obsoleto', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"), usuario_atual["id"], documento_id),
    )
    audit.registrar(conn, tabela="documentos", registro_id=documento_id, usuario_id=usuario_atual["id"],
                     acao="documento_tornado_obsoleto", valor_anterior={"status": row["status"]},
                     valor_novo={"status": "obsoleto"}, ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})
