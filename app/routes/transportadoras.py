"""
Fase 86 — Transportadora / Coleta (MVP): cadastro simples de transportadoras + agendamento e
confirmação de coleta contra um Pedido de Venda já expedido. Ver a nota de escopo completa em
migrations/schema_fase86.sql.
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import fluxo_service
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("transportadoras", __name__, url_prefix="/api/v1")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _transportadora_ou_404(conn, transportadora_id):
    row = conn.execute("SELECT * FROM transportadoras WHERE id = ?", (transportadora_id,)).fetchone()
    if row is None:
        raise ApiError("Transportadora não encontrada.", status=404)
    return dict(row)


def _pedido_venda_ou_404(conn, pedido_id):
    row = conn.execute("SELECT * FROM pedidos_venda WHERE id = ?", (pedido_id,)).fetchone()
    if row is None:
        raise ApiError("Pedido de venda não encontrado.", status=404)
    return dict(row)


def _coleta_ou_404(conn, coleta_id):
    row = conn.execute(
        """
        SELECT pvc.*, t.nome AS transportadora_nome
        FROM pedido_venda_coletas pvc JOIN transportadoras t ON t.id = pvc.transportadora_id
        WHERE pvc.id = ?
        """,
        (coleta_id,),
    ).fetchone()
    if row is None:
        raise ApiError("Coleta não encontrada.", status=404)
    return dict(row)


# ============================================================
# CADASTRO DE TRANSPORTADORAS
# ============================================================
@bp.get("/transportadoras")
@requires_permission("comercial", "gerenciar_coleta")
def listar_transportadoras():
    conn = get_db()
    incluir_inativas = request.args.get("incluir_inativas") == "1"
    where = "" if incluir_inativas else "WHERE status = 'ativo'"
    rows = conn.execute(f"SELECT * FROM transportadoras {where} ORDER BY nome").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/transportadoras")
@requires_permission("comercial", "gerenciar_coleta")
def criar_transportadora():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ApiError("Informe o nome da transportadora.", status=400)

    cur = conn.execute(
        "INSERT INTO transportadoras (nome, cnpj, telefone, criado_por) VALUES (?, ?, ?, ?)",
        (nome, dados.get("cnpj"), dados.get("telefone"), usuario_atual["id"]),
    )
    transportadora_id = cur.lastrowid
    audit.registrar(conn, tabela="transportadoras", registro_id=transportadora_id, usuario_id=usuario_atual["id"],
                     acao="transportadora_criada", valor_novo={"nome": nome},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_transportadora_ou_404(conn, transportadora_id)), 201


@bp.put("/transportadoras/<int:transportadora_id>")
@requires_permission("comercial", "gerenciar_coleta")
def editar_transportadora(transportadora_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = _transportadora_ou_404(conn, transportadora_id)
    nome = (dados.get("nome") or anterior["nome"]).strip()
    status = dados.get("status", anterior["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    conn.execute(
        "UPDATE transportadoras SET nome = ?, cnpj = ?, telefone = ?, status = ? WHERE id = ?",
        (nome, dados.get("cnpj", anterior["cnpj"]), dados.get("telefone", anterior["telefone"]), status, transportadora_id),
    )
    novo = _transportadora_ou_404(conn, transportadora_id)
    audit.registrar(conn, tabela="transportadoras", registro_id=transportadora_id, usuario_id=usuario_atual["id"],
                     acao="transportadora_editada", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


# ============================================================
# COLETA (agendamento + confirmação, por Pedido de Venda expedido)
# ============================================================
@bp.get("/pedidos-venda/<int:pedido_id>/coletas")
@requires_permission("comercial", "visualizar")
def listar_coletas_pedido(pedido_id):
    conn = get_db()
    _pedido_venda_ou_404(conn, pedido_id)
    rows = conn.execute(
        """
        SELECT pvc.*, t.nome AS transportadora_nome
        FROM pedido_venda_coletas pvc JOIN transportadoras t ON t.id = pvc.transportadora_id
        WHERE pvc.pedido_venda_id = ? ORDER BY pvc.id DESC
        """,
        (pedido_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/pedidos-venda/<int:pedido_id>/coletas")
@requires_permission("comercial", "gerenciar_coleta")
def agendar_coleta(pedido_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    pedido = _pedido_venda_ou_404(conn, pedido_id)
    if pedido["status"] != "expedido":
        raise ApiError(f"Só é possível agendar coleta para um pedido já 'expedido' (status atual: '{pedido['status']}').", status=400)

    transportadora_id = dados.get("transportadora_id")
    if not transportadora_id:
        raise ApiError("Informe transportadora_id.", status=400)
    transportadora = _transportadora_ou_404(conn, transportadora_id)
    if transportadora["status"] != "ativo":
        raise ApiError("Esta transportadora está inativa.", status=400)

    if conn.execute(
        "SELECT id FROM pedido_venda_coletas WHERE pedido_venda_id = ? AND status = 'agendada'", (pedido_id,)
    ).fetchone():
        raise ApiError("Já existe uma coleta agendada para este pedido — confirme ou cancele antes de agendar outra.", status=409)

    cur = conn.execute(
        "INSERT INTO pedido_venda_coletas (pedido_venda_id, transportadora_id, data_agendada, observacoes, criado_por) VALUES (?, ?, ?, ?, ?)",
        (pedido_id, transportadora_id, dados.get("data_agendada"), dados.get("observacoes"), usuario_atual["id"]),
    )
    coleta_id = cur.lastrowid
    audit.registrar(conn, tabela="pedido_venda_coletas", registro_id=coleta_id, usuario_id=usuario_atual["id"],
                     acao="coleta_agendada", valor_novo={"pedido_venda_id": pedido_id, "transportadora_id": transportadora_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_coleta_ou_404(conn, coleta_id)), 201


@bp.post("/pedidos-venda/coletas/<int:coleta_id>/confirmar-coleta")
@requires_permission("comercial", "gerenciar_coleta")
def confirmar_coleta(coleta_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    coleta = _coleta_ou_404(conn, coleta_id)

    if coleta["status"] != "agendada":
        raise ApiError(f"Só é possível confirmar uma coleta 'agendada' (status atual: '{coleta['status']}').", status=400)

    conn.execute(
        "UPDATE pedido_venda_coletas SET status = 'coletada', coletado_em = ?, coletado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], coleta_id),
    )
    audit.registrar(conn, tabela="pedido_venda_coletas", registro_id=coleta_id, usuario_id=usuario_atual["id"],
                     acao="coleta_confirmada", valor_anterior={"status": "agendada"}, valor_novo={"status": "coletada"},
                     ip=client_ip(), dispositivo=client_device())

    # Fase 81 — marca a etapa "Coleta pela Transportadora" (origem
    # 'sistema') automaticamente, no momento exato da confirmação real —
    # primeiro uso de fato desse mecanismo desde que foi criado.
    fluxo_service.marcar_concluida(
        conn, "pedido_venda", coleta["pedido_venda_id"], "coleta_transportadora", usuario_atual["id"],
        observacao=f"Coletado por {coleta['transportadora_nome']}.",
    )
    return jsonify(_coleta_ou_404(conn, coleta_id))


@bp.post("/pedidos-venda/coletas/<int:coleta_id>/cancelar")
@requires_permission("comercial", "gerenciar_coleta")
def cancelar_coleta(coleta_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()
    coleta = _coleta_ou_404(conn, coleta_id)

    if coleta["status"] != "agendada":
        raise ApiError(f"Só é possível cancelar uma coleta ainda 'agendada' (status atual: '{coleta['status']}').", status=400)
    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    conn.execute(
        "UPDATE pedido_venda_coletas SET status = 'cancelada', motivo_cancelamento = ?, cancelado_em = ?, cancelado_por = ? WHERE id = ?",
        (motivo, _now_iso(), usuario_atual["id"], coleta_id),
    )
    audit.registrar(conn, tabela="pedido_venda_coletas", registro_id=coleta_id, usuario_id=usuario_atual["id"],
                     acao="coleta_cancelada", valor_anterior={"status": "agendada"},
                     valor_novo={"status": "cancelada", "motivo": motivo}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_coleta_ou_404(conn, coleta_id))
