import datetime
import secrets

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("desvios", __name__, url_prefix="/api/v1/desvios")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _gerar_numero():
    ano = datetime.datetime.utcnow().year
    return f"DEV-{ano}-{secrets.token_hex(4).upper()}"


@bp.get("")
@requires_permission("desvios", "visualizar")
def listar():
    conn = get_db()
    status = request.args.get("status")
    if status:
        rows = conn.execute("SELECT * FROM desvios WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM desvios ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@requires_permission("desvios", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    origem = (dados.get("origem") or "").strip()
    descricao = (dados.get("descricao") or "").strip()
    criticidade = dados.get("criticidade") or "media"
    conn = get_db()

    if not origem or not descricao:
        raise ApiError("Informe origem e descricao.", status=400)
    if criticidade not in ("baixa", "media", "alta", "critica"):
        raise ApiError("criticidade deve ser baixa, media, alta ou critica.", status=400)

    numero = _gerar_numero()
    cur = conn.execute(
        """
        INSERT INTO desvios (numero, origem, item_id, lote_id, criticidade, descricao, prazo, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (numero, origem, dados.get("item_id"), dados.get("lote_id"), criticidade, descricao,
         dados.get("prazo"), usuario_atual["id"]),
    )
    desvio_id = cur.lastrowid
    audit.registrar(conn, tabela="desvios", registro_id=desvio_id, usuario_id=usuario_atual["id"],
                     acao="desvio_aberto", valor_novo={"numero": numero, "origem": origem, "criticidade": criticidade},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM desvios WHERE id = ?", (desvio_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.put("/<int:desvio_id>")
@requires_permission("desvios", "editar")
def editar(desvio_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM desvios WHERE id = ?", (desvio_id,)).fetchone()
    if row is None:
        raise ApiError("Desvio não encontrado.", status=404)
    if row["status"] == "encerrado":
        raise ApiError("Este desvio já está encerrado e não pode mais ser editado.", status=400)
    anterior = dict(row)

    causa_raiz = dados.get("causa_raiz", row["causa_raiz"])
    plano_acao = dados.get("plano_acao", row["plano_acao"])
    status = dados.get("status", row["status"])
    if status not in ("aberto", "em_tratativa", "encerrado"):
        raise ApiError("status inválido.", status=400)
    if status == "encerrado":
        raise ApiError("Use POST /desvios/<id>/encerrar para encerrar um desvio (exige verificação de eficácia).", status=400)

    conn.execute(
        "UPDATE desvios SET causa_raiz = ?, plano_acao = ?, status = ? WHERE id = ?",
        (causa_raiz, plano_acao, status, desvio_id),
    )
    novo_row = conn.execute("SELECT * FROM desvios WHERE id = ?", (desvio_id,)).fetchone()
    audit.registrar(conn, tabela="desvios", registro_id=desvio_id, usuario_id=usuario_atual["id"],
                     acao="desvio_editado", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo_row))


@bp.post("/<int:desvio_id>/encerrar")
@requires_permission("desvios", "encerrar")
def encerrar(desvio_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    verificacao_eficacia = (dados.get("verificacao_eficacia") or "").strip()
    conn = get_db()

    row = conn.execute("SELECT * FROM desvios WHERE id = ?", (desvio_id,)).fetchone()
    if row is None:
        raise ApiError("Desvio não encontrado.", status=404)
    if row["status"] == "encerrado":
        raise ApiError("Este desvio já está encerrado.", status=400)
    if not row["causa_raiz"] or not row["plano_acao"]:
        raise ApiError("Registre causa_raiz e plano_acao (PUT /desvios/<id>) antes de encerrar.", status=400)
    if not verificacao_eficacia:
        raise ApiError("Informe verificacao_eficacia para encerrar o desvio.", status=400)

    conn.execute(
        "UPDATE desvios SET status = 'encerrado', verificacao_eficacia = ?, encerrado_em = ?, encerrado_por = ? WHERE id = ?",
        (verificacao_eficacia, _now_iso(), usuario_atual["id"], desvio_id),
    )
    audit.registrar(conn, tabela="desvios", registro_id=desvio_id, usuario_id=usuario_atual["id"],
                     acao="desvio_encerrado", valor_novo={"verificacao_eficacia": verificacao_eficacia},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(conn.execute("SELECT * FROM desvios WHERE id = ?", (desvio_id,)).fetchone()))
