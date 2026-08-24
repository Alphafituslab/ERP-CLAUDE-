"""
Fase 111 — Arquitetura Servidor + Terminais: registro de terminais.

Ver o cabeçalho de migrations/schema_fase111.sql para o racional completo. Resumindo:
o sistema já era cliente-servidor de verdade desde a Fase 1 (frontend nunca acessa o
SQLite direto, só via API) — o que faltava era um REGISTRO de quais máquinas já estão
usando o servidor pela rede, para o administrador acompanhar e, se precisar, bloquear
uma máquina específica (ex.: notebook que saiu da empresa) sem mexer em usuário/senha.

`heartbeat` é chamado pelo frontend periodicamente (mesmo timer que já existia para o
polling de notificações — ver app.js) com um `terminal_uid` gerado uma vez no
navegador (`crypto.randomUUID()`, persistido em localStorage) e reenviado sempre. Um
terminal bloqueado recebe 403 no próprio heartbeat — o frontend trata isso mostrando
o aviso de conexão interrompida (não é um erro de rede de verdade, mas o efeito
visível para o usuário deve ser o mesmo: "pare de operar até isso ser resolvido").
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_auth, requires_permission

bp = Blueprint("terminais", __name__, url_prefix="/api/v1/terminais")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _terminal_ou_404(conn, terminal_id):
    row = conn.execute("SELECT * FROM terminais WHERE id = ?", (terminal_id,)).fetchone()
    if row is None:
        raise ApiError("Terminal não encontrado.", status=404)
    return dict(row)


@bp.post("/heartbeat")
@requires_auth
def heartbeat():
    """Sem @requires_permission de propósito: qualquer usuário autenticado (mesmo sem
    nenhuma permissão de módulo) deve conseguir registrar presença — o próprio JWT
    (checado por dentro, via g.usuario_atual, já resolvido pelo middleware de auth
    padrão do sistema) já garante que só sessão válida chega aqui. Só exige um
    terminal_uid no corpo; o resto é inferido da própria requisição."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    terminal_uid = (dados.get("terminal_uid") or "").strip()
    if not terminal_uid:
        raise ApiError("Informe terminal_uid.", status=400)
    versao_app = (dados.get("versao_app") or "").strip() or None
    nome_sugerido = (dados.get("nome") or "").strip() or None

    conn = get_db()
    existente = conn.execute("SELECT * FROM terminais WHERE terminal_uid = ?", (terminal_uid,)).fetchone()
    if existente and existente["bloqueado"]:
        raise ApiError(
            "Este terminal foi bloqueado por um administrador. Fale com quem administra o sistema.",
            status=403, codigo="terminal_bloqueado",
        )

    agora = _now_iso()
    if existente:
        conn.execute(
            """
            UPDATE terminais
            SET ip_ultimo_acesso = ?, user_agent_ultimo_acesso = ?, usuario_id_ultimo_acesso = ?,
                versao_app_ultima = ?, ultimo_acesso_em = ?
            WHERE id = ?
            """,
            (client_ip(), client_device(), usuario_atual["id"], versao_app, agora, existente["id"]),
        )
        terminal_id = existente["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO terminais
                (terminal_uid, nome, ip_ultimo_acesso, user_agent_ultimo_acesso,
                 usuario_id_ultimo_acesso, versao_app_ultima, ultimo_acesso_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (terminal_uid, nome_sugerido, client_ip(), client_device(),
             usuario_atual["id"], versao_app, agora),
        )
        terminal_id = cur.lastrowid
        audit.registrar(
            conn, tabela="terminais", registro_id=terminal_id, usuario_id=usuario_atual["id"],
            acao="terminal_registrado", valor_novo={"terminal_uid": terminal_uid, "ip": client_ip()},
            ip=client_ip(), dispositivo=client_device(),
        )

    return jsonify({"ok": True})


@bp.get("")
@requires_permission("terminais", "visualizar")
def listar_terminais():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT t.*, u.nome AS usuario_ultimo_acesso_nome
        FROM terminais t LEFT JOIN usuarios u ON u.id = t.usuario_id_ultimo_acesso
        ORDER BY t.ultimo_acesso_em DESC
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.put("/<int:terminal_id>/nome")
@requires_permission("terminais", "visualizar")
def renomear_terminal(terminal_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip() or None
    conn = get_db()
    anterior = _terminal_ou_404(conn, terminal_id)
    conn.execute("UPDATE terminais SET nome = ? WHERE id = ?", (nome, terminal_id))
    audit.registrar(conn, tabela="terminais", registro_id=terminal_id, usuario_id=usuario_atual["id"],
                     acao="terminal_renomeado", valor_anterior={"nome": anterior["nome"]}, valor_novo={"nome": nome},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_terminal_ou_404(conn, terminal_id))


@bp.post("/<int:terminal_id>/bloquear")
@requires_permission("terminais", "bloquear")
def bloquear_terminal(terminal_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    anterior = _terminal_ou_404(conn, terminal_id)
    if anterior["bloqueado"]:
        raise ApiError("Este terminal já está bloqueado.", status=400)
    conn.execute(
        "UPDATE terminais SET bloqueado = 1, bloqueado_em = ?, bloqueado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], terminal_id),
    )
    audit.registrar(conn, tabela="terminais", registro_id=terminal_id, usuario_id=usuario_atual["id"],
                     acao="terminal_bloqueado", valor_anterior={"bloqueado": 0}, valor_novo={"bloqueado": 1},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_terminal_ou_404(conn, terminal_id))


@bp.post("/<int:terminal_id>/liberar")
@requires_permission("terminais", "bloquear")
def liberar_terminal(terminal_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    anterior = _terminal_ou_404(conn, terminal_id)
    if not anterior["bloqueado"]:
        raise ApiError("Este terminal não está bloqueado.", status=400)
    conn.execute(
        "UPDATE terminais SET bloqueado = 0, bloqueado_em = NULL, bloqueado_por = NULL WHERE id = ?",
        (terminal_id,),
    )
    audit.registrar(conn, tabela="terminais", registro_id=terminal_id, usuario_id=usuario_atual["id"],
                     acao="terminal_liberado", valor_anterior={"bloqueado": 1}, valor_novo={"bloqueado": 0},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_terminal_ou_404(conn, terminal_id))
