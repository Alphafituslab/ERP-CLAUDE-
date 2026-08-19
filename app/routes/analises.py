import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("analises", __name__, url_prefix="/api/v1/analises")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _analise_com_resultados(conn, analise_id):
    row = conn.execute("SELECT * FROM analises WHERE id = ?", (analise_id,)).fetchone()
    if row is None:
        raise ApiError("Análise não encontrada.", status=404)
    analise = dict(row)
    resultados = conn.execute("SELECT * FROM resultados_analise WHERE analise_id = ? ORDER BY id", (analise_id,)).fetchall()
    analise["resultados"] = [dict(r) for r in resultados]
    return analise


def _calcular_conclusao(resultado, especificacao_min, especificacao_max):
    if resultado is None:
        return None
    if especificacao_min is not None and resultado < especificacao_min:
        return "nao_conforme"
    if especificacao_max is not None and resultado > especificacao_max:
        return "nao_conforme"
    return "conforme"


@bp.get("")
@requires_permission("analises", "visualizar")
def listar():
    conn = get_db()
    lote_id = request.args.get("lote_id", type=int)
    status = request.args.get("status")
    clausulas, params = [], []
    if lote_id:
        clausulas.append("lote_id = ?")
        params.append(lote_id)
    if status:
        clausulas.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(f"SELECT * FROM analises {where} ORDER BY id DESC", params).fetchall()
    return jsonify([_analise_com_resultados(conn, r["id"]) for r in rows])


@bp.get("/<int:analise_id>")
@requires_permission("analises", "visualizar")
def obter(analise_id):
    conn = get_db()
    return jsonify(_analise_com_resultados(conn, analise_id))


@bp.post("")
@requires_permission("analises", "solicitar")
def solicitar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    lote_id = dados.get("lote_id")
    tipo = dados.get("tipo") or "liberacao"
    ensaios = dados.get("ensaios") or []
    conn = get_db()

    if not lote_id or not ensaios:
        raise ApiError("Informe lote_id e ao menos um ensaio em 'ensaios'.", status=400)

    lote = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if lote is None:
        raise ApiError("Lote não encontrado.", status=404)
    lote = dict(lote)
    if lote["status"] != "quarentena":
        raise ApiError(
            f"Só é possível solicitar análise para um lote em quarentena (status atual: '{lote['status']}').",
            status=400,
        )

    cur = conn.execute(
        "INSERT INTO analises (lote_id, tipo, criado_por) VALUES (?, ?, ?)",
        (lote_id, tipo, usuario_atual["id"]),
    )
    analise_id = cur.lastrowid

    for ensaio in ensaios:
        nome_ensaio = (ensaio.get("ensaio") or "").strip()
        if not nome_ensaio:
            raise ApiError("Cada ensaio precisa de um nome em 'ensaio'.", status=400)
        conn.execute(
            """
            INSERT INTO resultados_analise (analise_id, ensaio, especificacao_min, especificacao_max, unidade)
            VALUES (?, ?, ?, ?, ?)
            """,
            (analise_id, nome_ensaio, ensaio.get("especificacao_min"), ensaio.get("especificacao_max"),
             ensaio.get("unidade")),
        )

    conn.execute(
        "UPDATE lotes SET status = 'em_analise', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], lote_id),
    )

    audit.registrar(conn, tabela="analises", registro_id=analise_id, usuario_id=usuario_atual["id"],
                     acao="analise_solicitada", valor_novo={"lote_id": lote_id, "tipo": tipo, "ensaios": len(ensaios)},
                     ip=client_ip(), dispositivo=client_device())
    audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                     acao="lote_em_analise", valor_anterior={"status": "quarentena"},
                     valor_novo={"status": "em_analise"}, ip=client_ip(), dispositivo=client_device())

    return jsonify(_analise_com_resultados(conn, analise_id)), 201


@bp.post("/<int:analise_id>/resultados/<int:resultado_id>")
@requires_permission("analises", "registrar_resultado")
def registrar_resultado(analise_id, resultado_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    if "resultado" not in dados:
        raise ApiError("Informe 'resultado'.", status=400)
    try:
        resultado_novo = float(dados["resultado"])
    except (TypeError, ValueError):
        raise ApiError("'resultado' deve ser numérico.", status=400)

    analise = conn.execute("SELECT * FROM analises WHERE id = ?", (analise_id,)).fetchone()
    if analise is None:
        raise ApiError("Análise não encontrada.", status=404)
    if analise["status"] != "aguardando_resultado":
        raise ApiError("Esta análise já foi concluída; resultados não podem mais ser registrados aqui.", status=400)

    row = conn.execute(
        "SELECT * FROM resultados_analise WHERE id = ? AND analise_id = ?", (resultado_id, analise_id)
    ).fetchone()
    if row is None:
        raise ApiError("Ensaio não encontrado nesta análise.", status=404)
    row = dict(row)

    e_correcao = row["resultado"] is not None
    if e_correcao:
        motivo = (dados.get("motivo") or "").strip()
        if not motivo:
            raise ApiError(
                "Este ensaio já tem um resultado registrado. Para corrigir, informe 'motivo' — o valor "
                "anterior é preservado no histórico, nunca sobrescrito silenciosamente.",
                status=400,
            )
        conn.execute(
            """
            INSERT INTO resultados_analise_historico (resultado_id, resultado_anterior, resultado_novo, motivo, usuario_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (resultado_id, row["resultado"], resultado_novo, motivo, usuario_atual["id"]),
        )

    conclusao = _calcular_conclusao(resultado_novo, row["especificacao_min"], row["especificacao_max"])
    conn.execute(
        "UPDATE resultados_analise SET resultado = ?, conclusao = ?, registrado_por = ?, registrado_em = ? WHERE id = ?",
        (resultado_novo, conclusao, usuario_atual["id"], _now_iso(), resultado_id),
    )

    audit.registrar(conn, tabela="resultados_analise", registro_id=resultado_id, usuario_id=usuario_atual["id"],
                     acao="resultado_corrigido" if e_correcao else "resultado_registrado",
                     valor_anterior={"resultado": row["resultado"]} if e_correcao else None,
                     valor_novo={"resultado": resultado_novo, "conclusao": conclusao},
                     motivo=dados.get("motivo"), ip=client_ip(), dispositivo=client_device())

    return jsonify(_analise_com_resultados(conn, analise_id))


@bp.post("/<int:analise_id>/concluir")
@requires_permission("analises", "concluir")
def concluir(analise_id):
    usuario_atual = g.usuario_atual
    conn = get_db()

    analise = conn.execute("SELECT * FROM analises WHERE id = ?", (analise_id,)).fetchone()
    if analise is None:
        raise ApiError("Análise não encontrada.", status=404)
    analise = dict(analise)
    if analise["status"] != "aguardando_resultado":
        raise ApiError("Esta análise já foi concluída.", status=400)

    resultados = conn.execute("SELECT * FROM resultados_analise WHERE analise_id = ?", (analise_id,)).fetchall()
    pendentes = [r["ensaio"] for r in resultados if r["resultado"] is None]
    if pendentes:
        raise ApiError(f"Ainda há ensaios sem resultado registrado: {', '.join(pendentes)}.", status=400)

    conclusao_geral = "conforme" if all(r["conclusao"] == "conforme" for r in resultados) else "nao_conforme"

    conn.execute(
        "UPDATE analises SET status = 'concluida', conclusao = ?, analista_id = ?, concluida_em = ? WHERE id = ?",
        (conclusao_geral, usuario_atual["id"], _now_iso(), analise_id),
    )
    conn.execute(
        "UPDATE lotes SET status = 'aguardando_aprovacao', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], analise["lote_id"]),
    )

    audit.registrar(conn, tabela="analises", registro_id=analise_id, usuario_id=usuario_atual["id"],
                     acao="analise_concluida", valor_novo={"conclusao": conclusao_geral},
                     ip=client_ip(), dispositivo=client_device())
    audit.registrar(conn, tabela="lotes", registro_id=analise["lote_id"], usuario_id=usuario_atual["id"],
                     acao="lote_aguardando_aprovacao", valor_novo={"status": "aguardando_aprovacao"},
                     ip=client_ip(), dispositivo=client_device())

    return jsonify(_analise_com_resultados(conn, analise_id))
