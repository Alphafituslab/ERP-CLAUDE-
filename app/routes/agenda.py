"""
Fase 193 — Agenda da equipe. Ver a lista/criar/editar-o-próprio/excluir-o-
próprio compromisso exigem só estar logado (`@requires_auth`) — igual "ver
meu próprio perfil" já é; mexer no compromisso de OUTRA pessoa passa pela
checagem de verdade dentro de `agenda_service.pode_editar/pode_excluir`
(permissão "agenda.editar_todos"/"agenda.excluir_todos", que o Administrador
já tem de graça por ter "TODAS" — ver seed.py).
"""
from flask import Blueprint, g, jsonify, request

from .. import agenda_service, audit
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..permissions import requires_auth

bp = Blueprint("agenda", __name__, url_prefix="/api/v1/agenda")


def _validar_evento(dados: dict):
    if not (dados.get("titulo") or "").strip():
        raise ApiError("Informe o motivo do compromisso.", status=400)
    if not dados.get("data_inicio"):
        raise ApiError("Informe a data e hora do compromisso.", status=400)


def _obter_evento_ou_404(conn, evento_id: int) -> dict:
    row = conn.execute("SELECT * FROM agenda_eventos WHERE id = ?", (evento_id,)).fetchone()
    if row is None:
        raise ApiError("Compromisso não encontrado.", status=404)
    return dict(row)


@bp.get("/usuarios")
@requires_auth
def listar_usuarios_para_dono():
    """Lista enxuta (id+nome) só para preencher o seletor 'Para quem é esse
    compromisso' — qualquer usuário logado pode ver (é a mesma agenda
    compartilhada de todos), não exige `usuarios.visualizar`."""
    rows = get_db().execute("SELECT id, nome FROM usuarios WHERE status = 'ativo' ORDER BY nome").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/eventos")
@requires_auth
def listar_eventos():
    de = request.args.get("de")
    ate = request.args.get("ate")
    if not de or not ate:
        raise ApiError("Informe o período (de/ate).", status=400)
    return jsonify(agenda_service.listar_eventos(get_db(), de, ate, g.usuario_atual["id"]))


@bp.get("/eventos/<int:evento_id>")
@requires_auth
def obter_evento(evento_id):
    conn = get_db()
    row = conn.execute(
        """
        SELECT e.*, u.nome AS dono_nome, c.nome AS criado_por_nome
        FROM agenda_eventos e
        JOIN usuarios u ON u.id = e.usuario_dono_id
        JOIN usuarios c ON c.id = e.criado_por_id
        WHERE e.id = ?
        """,
        (evento_id,),
    ).fetchone()
    if row is None:
        raise ApiError("Compromisso não encontrado.", status=404)
    donos_visiveis = agenda_service._donos_visiveis_em_detalhe(conn, g.usuario_atual["id"])
    return jsonify(agenda_service._redigir_evento_se_necessario(dict(row), donos_visiveis))


@bp.post("/eventos")
@requires_auth
def criar_evento():
    conn = get_db()
    dados = request.get_json(silent=True) or {}
    _validar_evento(dados)
    dono_id = dados.get("usuario_dono_id") or g.usuario_atual["id"]

    if not dados.get("forcar"):
        conflitos = agenda_service.verificar_conflito(conn, dono_id, dados["data_inicio"], dados.get("data_fim"))
        if conflitos:
            return jsonify({"conflito": True, "eventos_conflitantes": conflitos}), 409

    evento = agenda_service.criar_evento(conn, dados, g.usuario_atual["id"])
    audit.registrar(conn, tabela="agenda_eventos", registro_id=evento["id"], usuario_id=g.usuario_atual["id"],
                     acao="criar", valor_novo=evento, ip=client_ip(), dispositivo=client_device())
    return jsonify(evento), 201


@bp.put("/eventos/<int:evento_id>")
@requires_auth
def atualizar_evento(evento_id):
    conn = get_db()
    evento_atual = _obter_evento_ou_404(conn, evento_id)
    if not agenda_service.pode_editar(conn, g.usuario_atual["id"], evento_atual):
        raise ForbiddenError("Só o dono do compromisso ou um Administrador pode editá-lo.")

    dados = request.get_json(silent=True) or {}
    _validar_evento(dados)
    dados["usuario_dono_id"] = dados.get("usuario_dono_id") or evento_atual["usuario_dono_id"]
    dono_id = dados["usuario_dono_id"]

    if not dados.get("forcar"):
        conflitos = agenda_service.verificar_conflito(conn, dono_id, dados["data_inicio"], dados.get("data_fim"), excluir_evento_id=evento_id)
        if conflitos:
            return jsonify({"conflito": True, "eventos_conflitantes": conflitos}), 409

    evento = agenda_service.atualizar_evento(conn, evento_id, dados, g.usuario_atual["id"])
    audit.registrar(conn, tabela="agenda_eventos", registro_id=evento_id, usuario_id=g.usuario_atual["id"],
                     acao="editar", valor_anterior=evento_atual, valor_novo=evento, ip=client_ip(), dispositivo=client_device())
    return jsonify(evento)


@bp.delete("/eventos/<int:evento_id>")
@requires_auth
def excluir_evento(evento_id):
    conn = get_db()
    evento_atual = _obter_evento_ou_404(conn, evento_id)
    if not agenda_service.pode_excluir(conn, g.usuario_atual["id"], evento_atual):
        raise ForbiddenError("Só o dono do compromisso ou um Administrador pode excluí-lo.")
    agenda_service.excluir_evento(conn, evento_id)
    audit.registrar(conn, tabela="agenda_eventos", registro_id=evento_id, usuario_id=g.usuario_atual["id"],
                     acao="excluir", valor_anterior=evento_atual, ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


# ─── Alerta bloqueante na tela ───────────────────────────────────────────────

@bp.get("/alertas-tela")
@requires_auth
def listar_alertas_tela():
    """Poll do navegador (mesmo espírito de `iniciarPollingNotificacoes`):
    devolve os lembretes da AGENDA DE QUEM ESTÁ LOGADO que já chegaram na
    hora e ainda não foram mostrados/confirmados nesta tela."""
    return jsonify(agenda_service.lembretes_tela_pendentes(get_db(), g.usuario_atual["id"]))


@bp.post("/alertas-tela/<int:evento_id>/<int:repeticao_num>/confirmar")
@requires_auth
def confirmar_alerta_tela(evento_id, repeticao_num):
    conn = get_db()
    evento = conn.execute("SELECT usuario_dono_id FROM agenda_eventos WHERE id = ?", (evento_id,)).fetchone()
    if evento is None:
        raise ApiError("Compromisso não encontrado.", status=404)
    # Só o próprio dono confirma o alerta dele — ninguém fecha um aviso que
    # não é seu (nem o Administrador; é só um "ciente", não uma ação de
    # gerenciar o compromisso).
    if evento["usuario_dono_id"] != g.usuario_atual["id"]:
        raise ForbiddenError("Este alerta não é seu.")
    agenda_service.confirmar_alerta_tela(conn, evento_id, repeticao_num)
    return jsonify({"ok": True})


# ─── Push do navegador (Web Push) ───────────────────────────────────────────

@bp.get("/push/chave-publica")
@requires_auth
def chave_publica_push():
    return jsonify({"chave": agenda_service.VAPID_PUBLIC_KEY})


@bp.post("/push/inscrever")
@requires_auth
def inscrever_push():
    conn = get_db()
    dados = request.get_json(silent=True) or {}
    endpoint = (dados.get("endpoint") or "").strip()
    chaves = dados.get("keys") or {}
    if not endpoint or not chaves.get("p256dh") or not chaves.get("auth"):
        raise ApiError("Inscrição de push inválida.", status=400)
    conn.execute(
        """
        INSERT INTO agenda_push_subscriptions (usuario_id, endpoint, p256dh, auth) VALUES (?, ?, ?, ?)
        ON CONFLICT (endpoint) DO UPDATE SET usuario_id = excluded.usuario_id, p256dh = excluded.p256dh, auth = excluded.auth
        """,
        (g.usuario_atual["id"], endpoint, chaves["p256dh"], chaves["auth"]),
    )
    return jsonify({"ok": True})


@bp.post("/push/desinscrever")
@requires_auth
def desinscrever_push():
    conn = get_db()
    endpoint = (request.get_json(silent=True) or {}).get("endpoint")
    if endpoint:
        conn.execute("DELETE FROM agenda_push_subscriptions WHERE endpoint = ? AND usuario_id = ?", (endpoint, g.usuario_atual["id"]))
    return jsonify({"ok": True})
