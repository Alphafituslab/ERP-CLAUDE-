"""
Fase 177 — confirmação por e-mail antes de instalar em modo SERVIDOR.

Pedido do usuário: nunca mais deixar instalar um segundo Servidor sem ele
saber — desde a Fase 157b existe UM único Servidor oficial (a VPS); um
segundo Servidor instalado por engano criaria um banco de dados paralelo,
isolado, silenciosamente divergente do real. O instalador (Inno Setup, ver
installer/AlphafitusOS.iss) ao escolher "SERVIDOR" chama estas duas rotas
contra o Servidor oficial já rodando na nuvem antes de prosseguir: pede um
código de 6 dígitos (enviado por e-mail a quem tem perfil Administrador) e
depois confirma esse código. Sem confirmar, a instalação em modo Servidor
é abortada pelo próprio instalador — inclusive em modo silencioso (ver
CurStepChanged em AlphafitusOS.iss: o bloqueio não depende da tela
aparecer, só de uma verificação ter sido concluída com sucesso).

Rotas PÚBLICAS (sem @requires_auth) de propósito — o instalador roda ANTES
de qualquer login existir na máquina nova, então não há sessão pra exigir.
Protegidas por: código de uso único, expira em 10 minutos, e rate limit
por IP (mesmo padrão de tentativas_login_ip da Fase 168) contra spam de
e-mail e força bruta do código.
"""
import datetime
import hashlib
import random

from flask import Blueprint, jsonify, request

from .. import notificacoes_service
from ..context import ApiError, client_ip, get_db

bp = Blueprint("instalador", __name__, url_prefix="/api/v1/instalador")

EXPIRA_CODIGO_MINUTOS = 10
JANELA_TENTATIVAS_MINUTOS = 15
MAX_TENTATIVAS_POR_JANELA = 6
BLOQUEIO_MINUTOS = 30


def _now():
    return datetime.datetime.utcnow()


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ")


def _verificar_bloqueio_ip(conn, ip):
    if not ip:
        return
    linha = conn.execute("SELECT * FROM tentativas_instalador_ip WHERE ip = ?", (ip,)).fetchone()
    if linha and linha["bloqueado_ate"] and _parse_iso(linha["bloqueado_ate"]) > _now():
        raise ApiError(
            "Muitas tentativas vindas deste endereço. Tente novamente mais tarde.",
            status=429, codigo="ip_bloqueado",
        )


def _registrar_tentativa_ip(conn, ip, sucesso=False):
    """Mesmo padrão de `_registrar_tentativa_ip` em auth.py (Fase 168), só
    que compartilhado entre as duas rotas deste módulo (pedir e verificar
    código) — ambas contam pro mesmo limite por IP, sem contador separado
    por rota: um uso legítimo precisa de pouquíssimas chamadas no total."""
    if not ip:
        return
    agora = _now()
    linha = conn.execute("SELECT * FROM tentativas_instalador_ip WHERE ip = ?", (ip,)).fetchone()

    if sucesso:
        if linha is not None:
            conn.execute("UPDATE tentativas_instalador_ip SET tentativas = 0, bloqueado_ate = NULL WHERE ip = ?", (ip,))
        return

    if linha is None or _parse_iso(linha["janela_inicio"]) < agora - datetime.timedelta(minutes=JANELA_TENTATIVAS_MINUTOS):
        conn.execute(
            "INSERT INTO tentativas_instalador_ip (ip, tentativas, janela_inicio, bloqueado_ate) VALUES (?, 1, ?, NULL) "
            "ON CONFLICT(ip) DO UPDATE SET tentativas = 1, janela_inicio = excluded.janela_inicio, bloqueado_ate = NULL",
            (ip, _iso(agora)),
        )
        return

    tentativas = linha["tentativas"] + 1
    bloqueado_ate = _iso(agora + datetime.timedelta(minutes=BLOQUEIO_MINUTOS)) if tentativas >= MAX_TENTATIVAS_POR_JANELA else None
    conn.execute(
        "UPDATE tentativas_instalador_ip SET tentativas = ?, bloqueado_ate = ? WHERE ip = ?",
        (tentativas, bloqueado_ate, ip),
    )


def _emails_administradores(conn):
    rows = conn.execute(
        """
        SELECT DISTINCT u.email
        FROM usuarios u
        JOIN usuario_perfil up ON up.usuario_id = u.id
        JOIN perfis p ON p.id = up.perfil_id
        WHERE p.nome = 'Administrador' AND u.status = 'ativo'
        """
    ).fetchall()
    return [r["email"] for r in rows if r["email"]]


@bp.post("/solicitar-codigo-servidor")
def solicitar_codigo_servidor():
    ip = client_ip()
    conn = get_db()
    _verificar_bloqueio_ip(conn, ip)
    _registrar_tentativa_ip(conn, ip)

    destinatarios = _emails_administradores(conn)
    if not destinatarios:
        raise ApiError("Nenhum administrador com e-mail cadastrado para receber o código.", status=500)

    config_email = notificacoes_service.obter_configuracao_email(conn)
    if not config_email.get("smtp_host"):
        raise ApiError(
            "E-mail não configurado no Servidor oficial — não é possível confirmar por e-mail agora. "
            "Fale com quem administra o sistema.",
            status=503,
        )

    codigo = f"{random.randint(0, 999999):06d}"
    codigo_hash = hashlib.sha256(codigo.encode("utf-8")).hexdigest()
    agora = _now()
    conn.execute(
        "INSERT INTO codigos_instalacao_servidor (codigo_hash, criado_em, expira_em, ip_solicitante) VALUES (?, ?, ?, ?)",
        (codigo_hash, _iso(agora), _iso(agora + datetime.timedelta(minutes=EXPIRA_CODIGO_MINUTOS)), ip),
    )

    corpo = (
        "Alguém está tentando instalar o Alphafitus OS em modo SERVIDOR numa nova máquina "
        f"(endereço de rede: {ip or 'desconhecido'}).\n\n"
        "Se foi você mesmo, use este código para confirmar a instalação:\n\n"
        f"    {codigo}\n\n"
        f"Ele expira em {EXPIRA_CODIGO_MINUTOS} minutos e só pode ser usado uma vez.\n\n"
        "Se você NÃO pediu essa instalação, ignore este e-mail e avise imediatamente quem administra "
        "o sistema — alguém pode estar tentando duplicar o banco de dados oficial da empresa."
    )
    enviados = 0
    for destinatario in destinatarios:
        try:
            notificacoes_service._enviar_email_smtp(
                config_email, destinatario, "Código para instalar Servidor — Alphafitus OS", corpo,
            )
            enviados += 1
        except Exception:
            continue
    if enviados == 0:
        raise ApiError("Falha ao enviar o e-mail com o código. Tente novamente em instantes.", status=502)

    return jsonify({"ok": True, "mensagem": f"Código enviado para {enviados} administrador(es)."})


@bp.post("/verificar-codigo-servidor")
def verificar_codigo_servidor():
    ip = client_ip()
    conn = get_db()
    _verificar_bloqueio_ip(conn, ip)

    dados = request.get_json(silent=True) or {}
    codigo = (dados.get("codigo") or "").strip()
    if not codigo:
        _registrar_tentativa_ip(conn, ip)
        raise ApiError("Informe o código recebido por e-mail.", status=400)

    codigo_hash = hashlib.sha256(codigo.encode("utf-8")).hexdigest()
    agora = _now()
    linha = conn.execute(
        "SELECT * FROM codigos_instalacao_servidor WHERE codigo_hash = ? AND usado_em IS NULL ORDER BY id DESC LIMIT 1",
        (codigo_hash,),
    ).fetchone()

    if linha is None or _parse_iso(linha["expira_em"]) < agora:
        _registrar_tentativa_ip(conn, ip)
        raise ApiError("Código inválido ou expirado. Peça um código novo e tente de novo.", status=400)

    conn.execute("UPDATE codigos_instalacao_servidor SET usado_em = ? WHERE id = ?", (_iso(agora), linha["id"]))
    _registrar_tentativa_ip(conn, ip, sucesso=True)
    return jsonify({"ok": True})
