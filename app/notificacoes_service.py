"""
Fase 37 — helper de notificações + envio real de e-mail.

Mesma filosofia do `app/audit.py`: um módulo pequeno, sem blueprint próprio,
importado pelos módulos de rota que precisam avisar alguém que uma ação
está pendente (ex.: `estoque.py` quando uma contagem gera divergência
grande, `financeiro.py` quando um estorno ou uma baixa grande fica
aguardando segunda aprovação).

Duas responsabilidades bem separadas:

  1. `criar` / `notificar_usuarios_com_permissao` — sempre gravam a
     notificação na tabela `notificacoes` (isso NUNCA falha por causa de
     e-mail: é só um INSERT).
  2. O envio por e-mail em si é "melhor esforço": qualquer problema (SMTP
     desligado, sem host configurado, usuário sem e-mail, erro de rede,
     credencial errada etc.) é capturado e gravado em
     `notificacoes.email_erro` — a notificação continua existindo e
     visível na tela, e a ação de negócio que a disparou (aprovação,
     estorno, baixa) nunca é revertida ou impedida por causa disso.

Rodar dentro da MESMA transação/conexão da ação que dispara a notificação
é seguro: o envio de e-mail acontece só depois do INSERT já commitado
implicitamente pela mesma `conn` (SQLite autocommit deste projeto), então
mesmo que o processo de e-mail demore ou falhe, o dado de negócio já foi
gravado.
"""
import smtplib
from email.message import EmailMessage

TIMEOUT_SMTP_SEGUNDOS = 10


def _now_iso():
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def obter_configuracao_email(conn):
    row = conn.execute("SELECT * FROM configuracoes_email WHERE id = 1").fetchone()
    if row is None:
        return {
            "ativo": False, "smtp_host": None, "smtp_porta": 587, "smtp_usuario": None,
            "usar_tls": True, "remetente_nome": "Alphafitus OS", "remetente_email": None,
        }
    return dict(row)


def _enviar_email_smtp(config, destinatario_email, assunto, corpo):
    """Conecta no SMTP configurado e envia UM e-mail em texto puro. Deixa
    qualquer exceção do smtplib/socket subir para quem chamou decidir o
    que fazer (aqui, sempre é capturada e virou `email_erro` — nunca deixa
    a ação de negócio que disparou a notificação quebrar por causa disso)."""
    if not config.get("smtp_host"):
        raise ValueError("Nenhum servidor SMTP configurado (smtp_host vazio).")

    msg = EmailMessage()
    remetente_nome = config.get("remetente_nome") or "Alphafitus OS"
    remetente_email = config.get("remetente_email") or config.get("smtp_usuario") or "nao-responda@alphafitus.local"
    msg["From"] = f"{remetente_nome} <{remetente_email}>"
    msg["To"] = destinatario_email
    msg["Subject"] = assunto
    msg.set_content(corpo)

    porta = config.get("smtp_porta") or 587
    if porta == 465:
        # 465 é sempre SMTPS (TLS implícito desde a conexão) — não usa STARTTLS.
        servidor = smtplib.SMTP_SSL(config["smtp_host"], porta, timeout=TIMEOUT_SMTP_SEGUNDOS)
    else:
        servidor = smtplib.SMTP(config["smtp_host"], porta, timeout=TIMEOUT_SMTP_SEGUNDOS)
    try:
        if porta != 465 and config.get("usar_tls"):
            servidor.starttls()
        if config.get("smtp_usuario"):
            servidor.login(config["smtp_usuario"], config.get("smtp_senha") or "")
        servidor.send_message(msg)
    finally:
        try:
            servidor.quit()
        except Exception:
            pass


def enviar_email_com_anexo(config, destinatarios, assunto, corpo, nome_anexo, dados_anexo):
    """Fase 67 — mesma conexão SMTP de `_enviar_email_smtp` acima (mesmo
    `configuracoes_email`, nenhum servidor de e-mail novo), mas para MAIS
    de um destinatário de uma vez (lista, não um único e-mail) e com um
    arquivo anexado (o backup em si) — usada só pelo envio automático de
    backup por e-mail (`backup_service.py`), nunca pelas notificações de
    evento normais. Mesmo contrato de erro: deixa a exceção subir, quem
    chama decide o que fazer (aqui, sempre vira `email_erro` gravado em
    `backups_executados`)."""
    if not config.get("smtp_host"):
        raise ValueError("Nenhum servidor SMTP configurado (smtp_host vazio).")
    if not destinatarios:
        raise ValueError("Nenhum destinatário informado.")

    msg = EmailMessage()
    remetente_nome = config.get("remetente_nome") or "Alphafitus OS"
    remetente_email = config.get("remetente_email") or config.get("smtp_usuario") or "nao-responda@alphafitus.local"
    msg["From"] = f"{remetente_nome} <{remetente_email}>"
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto
    msg.set_content(corpo)
    msg.add_attachment(dados_anexo, maintype="application", subtype="octet-stream", filename=nome_anexo)

    porta = config.get("smtp_porta") or 587
    if porta == 465:
        servidor = smtplib.SMTP_SSL(config["smtp_host"], porta, timeout=TIMEOUT_SMTP_SEGUNDOS)
    else:
        servidor = smtplib.SMTP(config["smtp_host"], porta, timeout=TIMEOUT_SMTP_SEGUNDOS)
    try:
        if porta != 465 and config.get("usar_tls"):
            servidor.starttls()
        if config.get("smtp_usuario"):
            servidor.login(config["smtp_usuario"], config.get("smtp_senha") or "")
        servidor.send_message(msg)
    finally:
        try:
            servidor.quit()
        except Exception:
            pass


def _tentar_enviar_email_para_notificacao(conn, notificacao_id, usuario, tipo, mensagem):
    """Melhor esforço: tenta enviar e sempre grava o resultado (sucesso ou
    o motivo de não ter enviado) em `notificacoes.email_enviado` /
    `email_erro`. Nunca levanta exceção para quem chamou."""
    config = obter_configuracao_email(conn)
    motivo_nao_enviado = None

    if not config.get("ativo"):
        motivo_nao_enviado = "Envio de e-mail está desligado na configuração do sistema."
    elif not usuario.get("notificar_por_email"):
        motivo_nao_enviado = "Usuário desativou o recebimento de notificações por e-mail."
    elif not usuario.get("email"):
        motivo_nao_enviado = "Usuário não tem e-mail cadastrado."

    if motivo_nao_enviado:
        conn.execute(
            "UPDATE notificacoes SET email_enviado = 0, email_erro = ? WHERE id = ?",
            (motivo_nao_enviado, notificacao_id),
        )
        return

    assunto = f"[Alphafitus OS] {tipo.replace('_', ' ').capitalize()}"
    corpo = (
        f"{mensagem}\n\n"
        "--\n"
        "Esta é uma notificação automática do Alphafitus OS. Para ver todas as "
        "suas notificações ou desativar o recebimento por e-mail, acesse "
        "\"Notificações\" no sistema."
    )
    try:
        _enviar_email_smtp(config, usuario["email"], assunto, corpo)
        conn.execute(
            "UPDATE notificacoes SET email_enviado = 1, email_erro = NULL WHERE id = ?",
            (notificacao_id,),
        )
    except Exception as erro:
        conn.execute(
            "UPDATE notificacoes SET email_enviado = 0, email_erro = ? WHERE id = ?",
            (str(erro)[:500], notificacao_id),
        )


def criar(conn, *, usuario_id, tipo, mensagem):
    """Cria UMA notificação para um usuário específico e tenta o envio por
    e-mail (melhor esforço). Devolve o id da notificação criada."""
    usuario = conn.execute("SELECT id, email, notificar_por_email FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if usuario is None:
        return None
    usuario = dict(usuario)

    cur = conn.execute(
        "INSERT INTO notificacoes (usuario_id, tipo, mensagem) VALUES (?, ?, ?)",
        (usuario_id, tipo, mensagem),
    )
    notificacao_id = cur.lastrowid
    _tentar_enviar_email_para_notificacao(conn, notificacao_id, usuario, tipo, mensagem)
    return notificacao_id


def notificar_usuarios_com_permissao(conn, *, modulo, acao, tipo, mensagem, excluir_usuario_id=None):
    """Cria uma notificação para cada usuário ATIVO que tenha a permissão
    'modulo.acao' — o mesmo critério usado por `requires_permission` para
    liberar a ação de aprovar. `excluir_usuario_id` evita notificar quem
    disparou a própria pendência (ex.: quem solicitou o estorno não
    precisa ser avisado de que precisa aprovar o próprio pedido — aliás
    nem consegue, por segregação de função). Devolve a lista de ids de
    usuário notificados."""
    linhas = conn.execute(
        """
        SELECT DISTINCT u.id, u.email, u.notificar_por_email
        FROM usuarios u
        JOIN usuario_perfil up ON up.usuario_id = u.id
        JOIN perfil_permissao pp ON pp.perfil_id = up.perfil_id
        JOIN permissoes p ON p.id = pp.permissao_id
        WHERE p.modulo = ? AND p.acao = ? AND u.status = 'ativo'
        """,
        (modulo, acao),
    ).fetchall()

    notificados = []
    for linha in linhas:
        usuario = dict(linha)
        if excluir_usuario_id is not None and usuario["id"] == excluir_usuario_id:
            continue
        notificacao_id = criar(conn, usuario_id=usuario["id"], tipo=tipo, mensagem=mensagem)
        if notificacao_id is not None:
            notificados.append(usuario["id"])
    return notificados
