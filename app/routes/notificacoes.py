"""
Fase 1 — tabela e API básica: cada usuário só vê e marca como lida as suas
próprias notificações (nunca as de outra pessoa).

Fase 37 — acrescenta:
  - contagem de não lidas (para o sino da barra superior, sem precisar
    baixar as 100 notificações completas a cada verificação);
  - marcar todas como lidas de uma vez;
  - a própria pessoa poder desligar o recebimento por e-mail para si
    mesma (a notificação em si continua sendo criada de qualquer forma —
    isso só afeta se um e-mail também é disparado);
  - configuração do servidor SMTP usado para o envio real (`sistema.
    configurar_email`, só quem tem essa permissão vê/edita) e um botão de
    teste que manda um e-mail de verdade para o próprio e-mail de quem
    está testando, sem precisar esperar uma notificação de negócio
    acontecer para descobrir se a configuração está certa.
"""
from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_auth, requires_permission

bp = Blueprint("notificacoes", __name__, url_prefix="/api/v1/notificacoes")


def _now_iso():
    return notificacoes_service._now_iso()


@bp.get("")
@requires_auth
def listar_minhas():
    usuario = g.usuario_atual
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notificacoes WHERE usuario_id = ? ORDER BY criado_em DESC LIMIT 100",
        (usuario["id"],),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/nao-lidas/contagem")
@requires_auth
def contagem_nao_lidas():
    usuario = g.usuario_atual
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS contagem FROM notificacoes WHERE usuario_id = ? AND lida = 0",
        (usuario["id"],),
    ).fetchone()
    return jsonify({"contagem": row["contagem"]})


@bp.post("/<int:notificacao_id>/marcar-lida")
@requires_auth
def marcar_lida(notificacao_id):
    usuario = g.usuario_atual
    conn = get_db()
    conn.execute(
        "UPDATE notificacoes SET lida = 1 WHERE id = ? AND usuario_id = ?",
        (notificacao_id, usuario["id"]),
    )
    return jsonify({"ok": True})


@bp.post("/marcar-todas-lidas")
@requires_auth
def marcar_todas_lidas():
    usuario = g.usuario_atual
    conn = get_db()
    conn.execute(
        "UPDATE notificacoes SET lida = 1 WHERE usuario_id = ? AND lida = 0",
        (usuario["id"],),
    )
    return jsonify({"ok": True})


@bp.put("/minhas-preferencias")
@requires_auth
def atualizar_minhas_preferencias():
    """Qualquer usuário logado pode desligar/religar o recebimento de
    notificações por e-mail para si mesmo, sem precisar de nenhuma
    permissão especial — não afeta o que aparece na tela, só o e-mail."""
    usuario = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    if "notificar_por_email" not in dados:
        raise ApiError("Informe notificar_por_email (true ou false).", status=400)
    valor = 1 if dados.get("notificar_por_email") else 0
    conn = get_db()
    conn.execute("UPDATE usuarios SET notificar_por_email = ? WHERE id = ?", (valor, usuario["id"]))
    return jsonify({"ok": True, "notificar_por_email": bool(valor)})


# ---------------------------------------------------------------------
# Configuração do servidor de e-mail (Fase 37) — só quem tem
# "sistema.configurar_email" (Administrador, por padrão).
# ---------------------------------------------------------------------

def _config_publica(config):
    """Nunca devolve a senha salva pela tela — só um booleano avisando se
    já existe uma senha configurada, mesmo padrão de não expor de volta
    valores sensíveis já usado em outras telas de configuração."""
    d = dict(config)
    d["senha_configurada"] = bool(d.get("smtp_senha"))
    d.pop("smtp_senha", None)
    d["ativo"] = bool(d.get("ativo"))
    d["usar_tls"] = bool(d.get("usar_tls"))
    return d


@bp.get("/configuracao-email")
@requires_permission("sistema", "configurar_email")
def obter_configuracao_email():
    conn = get_db()
    return jsonify(_config_publica(notificacoes_service.obter_configuracao_email(conn)))


@bp.put("/configuracao-email")
@requires_permission("sistema", "configurar_email")
def atualizar_configuracao_email():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = notificacoes_service.obter_configuracao_email(conn)

    ativo = 1 if dados.get("ativo") else 0
    smtp_host = (dados.get("smtp_host") or "").strip() or None
    usar_tls = 1 if dados.get("usar_tls", True) else 0
    smtp_usuario = (dados.get("smtp_usuario") or "").strip() or None
    remetente_nome = (dados.get("remetente_nome") or "").strip() or "Alphafitus OS"
    remetente_email = (dados.get("remetente_email") or "").strip() or None

    smtp_porta = dados.get("smtp_porta")
    if smtp_porta in (None, ""):
        smtp_porta = anterior.get("smtp_porta") or 587
    try:
        smtp_porta = int(smtp_porta)
    except (TypeError, ValueError):
        raise ApiError("smtp_porta deve ser numérico.", status=400)
    if smtp_porta <= 0 or smtp_porta > 65535:
        raise ApiError("smtp_porta deve estar entre 1 e 65535.", status=400)

    if ativo and not smtp_host:
        raise ApiError("Para ativar o envio de e-mail, informe smtp_host.", status=400)

    # Senha: campo vazio/omitido MANTÉM a senha já salva (a tela nunca
    # recebe a senha salva de volta para poder reenviá-la sem querer) —
    # só troca de fato se vier um valor novo não vazio.
    nova_senha = dados.get("smtp_senha")
    smtp_senha = anterior.get("smtp_senha") if not nova_senha else nova_senha

    conn.execute(
        """
        INSERT INTO configuracoes_email (id, ativo, smtp_host, smtp_porta, smtp_usuario, smtp_senha,
                                          usar_tls, remetente_nome, remetente_email, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            ativo = excluded.ativo,
            smtp_host = excluded.smtp_host,
            smtp_porta = excluded.smtp_porta,
            smtp_usuario = excluded.smtp_usuario,
            smtp_senha = excluded.smtp_senha,
            usar_tls = excluded.usar_tls,
            remetente_nome = excluded.remetente_nome,
            remetente_email = excluded.remetente_email,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (ativo, smtp_host, smtp_porta, smtp_usuario, smtp_senha, usar_tls, remetente_nome, remetente_email,
         _now_iso(), usuario_atual["id"]),
    )
    audit.registrar(
        conn, tabela="configuracoes_email", registro_id=1, usuario_id=usuario_atual["id"],
        acao="configuracao_email_atualizada",
        valor_anterior={"ativo": bool(anterior.get("ativo")), "smtp_host": anterior.get("smtp_host")},
        valor_novo={"ativo": bool(ativo), "smtp_host": smtp_host},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_config_publica(notificacoes_service.obter_configuracao_email(conn)))


@bp.post("/configuracao-email/testar")
@requires_permission("sistema", "configurar_email")
def testar_configuracao_email():
    """Manda um e-mail de teste de verdade para o e-mail de quem está
    testando — deliberadamente ignora o `ativo` da configuração salva
    (a pessoa pode estar testando ANTES de ligar o envio geral) mas usa o
    resto da configuração salva (host, porta, usuário, senha etc.)."""
    usuario_atual = g.usuario_atual
    if not usuario_atual.get("email"):
        raise ApiError("Seu usuário não tem e-mail cadastrado — não é possível testar.", status=400)
    conn = get_db()
    config = notificacoes_service.obter_configuracao_email(conn)
    if not config.get("smtp_host"):
        raise ApiError("Configure e salve pelo menos o servidor SMTP (smtp_host) antes de testar.", status=400)
    try:
        notificacoes_service._enviar_email_smtp(
            config, usuario_atual["email"],
            "[Alphafitus OS] E-mail de teste",
            "Este é um e-mail de teste da configuração de SMTP do Alphafitus OS.\n\n"
            "Se você recebeu esta mensagem, a configuração está funcionando.",
        )
    except Exception as erro:
        raise ApiError(f"Falha ao enviar o e-mail de teste: {erro}", status=400)
    return jsonify({"ok": True, "enviado_para": usuario_atual["email"]})
