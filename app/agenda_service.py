"""
Fase 193 — Agenda da equipe (pedido do usuário: "tipo Google Agenda", com
lembrete configurável em chat interno + WhatsApp + push do navegador,
checagem de conflito de horário e permissão "dono ou Administrador").

Mesmo padrão de agendador em background já usado por `app/backup_service.py`
(`iniciar_agendador_em_background`/`_loop_agendador`/`_rodar_ciclo`) — uma
thread daemon simples, sem biblioteca de cron, que roda a cada
INTERVALO_VERIFICACAO_SEGUNDOS e é chamada nos MESMOS pontos de entrada que
já chamam a do backup (run.py, run_producao.py, service_windows.py,
installer/app_launcher.py, installer/app_launcher_tray.py).

Canais de lembrete reaproveitados, nenhum inventado do zero:
  - chat interno: app/chat_interno_service.enviar_mensagem_chat_interno
  - WhatsApp:     app/backup_service.obter_configuracao + enviar_texto_whatsapp
  - push:         Web Push padrão (pywebpush) usando o Service Worker que o
                   PWA já registra em frontend/static/app.js (`/sw.js`)
"""
import datetime
import os
import threading
import time

from . import backup_service
from . import chat_interno_service
from .permissions import usuario_tem_permissao

INTERVALO_VERIFICACAO_SEGUNDOS = 60
# Web Push (padrão W3C) exige um par de chaves VAPID — geradas UMA vez com
# `python -m py_vapid` (biblioteca `pywebpush` traz o helper) e guardadas só
# como variável de ambiente, nunca commitadas (mesmo espírito de
# ALPHAFITUS_JWT_SECRET em app/security.py). Sem essas variáveis definidas,
# o canal "push" simplesmente não dispara — os outros dois continuam normais.
VAPID_PUBLIC_KEY = os.environ.get("ALPHAFITUS_VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("ALPHAFITUS_VAPID_PRIVATE_KEY")
VAPID_CLAIMS_EMAIL = os.environ.get("ALPHAFITUS_VAPID_CLAIMS_EMAIL", "contato@alphafitus.com.br")
# Se o processo ficar horas/dias parado, não dispara uma enxurrada de
# lembretes "atrasados" ao voltar — um lembrete cujo horário já passou há
# mais tempo que isso é simplesmente pulado (mesmo espírito de robustez do
# `_rodar_ciclo` do backup, que também tolera o processo ficar fora do ar).
JANELA_TOLERANCIA_ATRASO_MINUTOS = 180


# ─── Permissões ────────────────────────────────────────────────────────────

def pode_editar(conn, usuario_id: int, evento: dict) -> bool:
    return usuario_id == evento["usuario_dono_id"] or usuario_tem_permissao(conn, usuario_id, "agenda", "editar_todos")


def pode_excluir(conn, usuario_id: int, evento: dict) -> bool:
    return usuario_id == evento["usuario_dono_id"] or usuario_tem_permissao(conn, usuario_id, "agenda", "excluir_todos")


# ─── Conflito de horário ────────────────────────────────────────────────────

def _fim_efetivo(data_inicio_iso: str, data_fim_iso: str | None) -> str:
    """Quando o evento não tem fim declarado, usa 1h de duração só para
    efeito de checagem de conflito — não é gravado no banco."""
    if data_fim_iso:
        return data_fim_iso
    inicio = datetime.datetime.fromisoformat(data_inicio_iso)
    return (inicio + datetime.timedelta(hours=1)).isoformat()


def verificar_conflito(conn, usuario_dono_id: int, data_inicio: str, data_fim: str | None, excluir_evento_id=None):
    """Devolve a lista de eventos (dicts) do MESMO dono que colidem no
    intervalo informado. Só considera eventos com status='agendado' —
    cancelado/concluído não bloqueia nada novo."""
    fim_novo = _fim_efetivo(data_inicio, data_fim)
    candidatos = conn.execute(
        """
        SELECT * FROM agenda_eventos
        WHERE usuario_dono_id = ? AND status = 'agendado'
          AND (? IS NULL OR id != ?)
        """,
        (usuario_dono_id, excluir_evento_id, excluir_evento_id),
    ).fetchall()
    conflitos = []
    for row in candidatos:
        evento = dict(row)
        fim_existente = _fim_efetivo(evento["data_inicio"], evento["data_fim"])
        # Sobreposição clássica de intervalos: começa antes do outro terminar
        # E termina depois do outro começar.
        if data_inicio < fim_existente and fim_novo > evento["data_inicio"]:
            conflitos.append(evento)
    return conflitos


# ─── CRUD ───────────────────────────────────────────────────────────────────

CAMPOS_EVENTO = (
    "titulo", "descricao", "data_inicio", "data_fim", "local_texto", "cor",
    "usuario_dono_id", "notificar_chat_interno", "notificar_whatsapp", "notificar_push",
    "lembrete_antecedencia_min", "lembrete_repeticoes", "lembrete_intervalo_min",
)

# Defaults explícitos: o corpo da requisição pode simplesmente não mandar um
# campo opcional (ex.: criar via API/teste sem escolher cor) — sem isso, o
# valor vira `None` e pisa no DEFAULT da coluna no INSERT/UPDATE (que só se
# aplica quando a coluna nem aparece na instrução, não quando ela recebe
# `NULL` explicitamente).
DEFAULTS_EVENTO = {
    "descricao": None,
    "data_fim": None,
    "local_texto": None,
    "cor": "#3B82F6",
    "notificar_chat_interno": 1,
    "notificar_whatsapp": 1,
    "notificar_push": 1,
    "lembrete_antecedencia_min": 30,
    "lembrete_repeticoes": 1,
    "lembrete_intervalo_min": 10,
}


def _valores_com_default(dados: dict) -> dict:
    valores = {}
    for campo in CAMPOS_EVENTO:
        valor = dados.get(campo)
        valores[campo] = valor if valor is not None else DEFAULTS_EVENTO.get(campo)
    return valores


def listar_eventos(conn, de: str, ate: str):
    rows = conn.execute(
        """
        SELECT e.*, u.nome AS dono_nome, c.nome AS criado_por_nome
        FROM agenda_eventos e
        JOIN usuarios u ON u.id = e.usuario_dono_id
        JOIN usuarios c ON c.id = e.criado_por_id
        WHERE e.status != 'cancelado' AND e.data_inicio < ? AND COALESCE(e.data_fim, e.data_inicio) >= ?
        ORDER BY e.data_inicio
        """,
        (ate, de),
    ).fetchall()
    return [dict(r) for r in rows]


def criar_evento(conn, dados: dict, criado_por_id: int) -> dict:
    valores = _valores_com_default(dados)
    valores["usuario_dono_id"] = valores["usuario_dono_id"] or criado_por_id
    valores["conflito_confirmado"] = 1 if dados.get("forcar") else 0
    cur = conn.execute(
        f"""
        INSERT INTO agenda_eventos ({", ".join(CAMPOS_EVENTO)}, criado_por_id, conflito_confirmado)
        VALUES ({", ".join("?" for _ in CAMPOS_EVENTO)}, ?, ?)
        """,
        (*[valores[c] for c in CAMPOS_EVENTO], criado_por_id, valores["conflito_confirmado"]),
    )
    return dict(conn.execute("SELECT * FROM agenda_eventos WHERE id = ?", (cur.lastrowid,)).fetchone())


def atualizar_evento(conn, evento_id: int, dados: dict, atualizado_por_id: int) -> dict:
    valores = _valores_com_default(dados)
    sets = ", ".join(f"{c} = ?" for c in CAMPOS_EVENTO)
    conn.execute(
        f"""
        UPDATE agenda_eventos SET {sets},
            conflito_confirmado = ?, atualizado_em = strftime('%Y-%m-%dT%H:%M:%fZ','now'), atualizado_por = ?
        WHERE id = ?
        """,
        (*[valores[c] for c in CAMPOS_EVENTO], 1 if dados.get("forcar") else 0, atualizado_por_id, evento_id),
    )
    return dict(conn.execute("SELECT * FROM agenda_eventos WHERE id = ?", (evento_id,)).fetchone())


def excluir_evento(conn, evento_id: int):
    conn.execute("DELETE FROM agenda_eventos WHERE id = ?", (evento_id,))


# ─── Envio de lembretes ─────────────────────────────────────────────────────

def _texto_lembrete(evento: dict) -> str:
    inicio = datetime.datetime.fromisoformat(evento["data_inicio"])
    linhas = [f"🗓️ Lembrete: {evento['titulo']}", f"📅 {inicio.strftime('%d/%m/%Y às %H:%M')}"]
    if evento.get("local_texto"):
        linhas.append(f"📍 {evento['local_texto']}")
    if evento.get("descricao"):
        linhas.append(evento["descricao"])
    return "\n".join(linhas)


def _ja_enviado(conn, evento_id: int, canal: str, repeticao_num: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM agenda_lembretes_enviados WHERE evento_id = ? AND canal = ? AND repeticao_num = ?",
        (evento_id, canal, repeticao_num),
    ).fetchone() is not None


def _marcar_enviado(conn, evento_id: int, canal: str, repeticao_num: int):
    conn.execute(
        "INSERT OR IGNORE INTO agenda_lembretes_enviados (evento_id, canal, repeticao_num) VALUES (?, ?, ?)",
        (evento_id, canal, repeticao_num),
    )


def enviar_push(conn, usuario_id: int, titulo: str, corpo: str, dados_extra: dict | None = None):
    """Web Push padrão (pywebpush) — dependência OPCIONAL, mesmo espírito do
    `boto3` em backup_service.py: só quem realmente ativa notificações push
    precisa dela instalada. Remove sozinha uma inscrição expirada (HTTP 404/410,
    o navegador cancelou por conta própria)."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return
    import json

    if not VAPID_PRIVATE_KEY:
        return
    inscricoes = conn.execute("SELECT * FROM agenda_push_subscriptions WHERE usuario_id = ?", (usuario_id,)).fetchall()
    payload = json.dumps({"title": titulo, "body": corpo, "data": dados_extra or {}})
    for inscricao in inscricoes:
        try:
            webpush(
                subscription_info={
                    "endpoint": inscricao["endpoint"],
                    "keys": {"p256dh": inscricao["p256dh"], "auth": inscricao["auth"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
            )
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                conn.execute("DELETE FROM agenda_push_subscriptions WHERE id = ?", (inscricao["id"],))


def enviar_lembrete(conn, evento: dict, repeticao_num: int):
    dono = conn.execute("SELECT * FROM usuarios WHERE id = ?", (evento["usuario_dono_id"],)).fetchone()
    if dono is None:
        return
    texto = _texto_lembrete(evento)

    if evento["notificar_chat_interno"] and not _ja_enviado(conn, evento["id"], "chat", repeticao_num):
        # Fase 194 — o chat interno (Whatts Inbox) é um sistema separado com
        # conta própria por colaborador; o e-mail de login do ERP nem
        # sempre é o mesmo cadastrado lá — usa o campo dedicado quando
        # existir, senão cai no e-mail de login (comportamento de antes).
        email_destino = dono["email_chat_interno"] or dono["email"]
        sucesso, _motivo = chat_interno_service.enviar_mensagem_chat_interno(email_destino, texto)
        # Só marca como enviado quando realmente deu certo — se o e-mail
        # não bater com nenhuma conta do Whatts Inbox, tenta de novo no
        # próximo ciclo (1 min) em vez de desistir silenciosamente pra
        # sempre.
        if sucesso:
            _marcar_enviado(conn, evento["id"], "chat", repeticao_num)

    if evento["notificar_whatsapp"] and dono["celular"] and not _ja_enviado(conn, evento["id"], "whatsapp", repeticao_num):
        # Achado real (2026-09-24): NÃO usar `whatsapp_ativo` daqui — esse
        # interruptor é "mandar aviso de BACKUP por WhatsApp" (tela
        # Sistema > Backups), sem relação nenhuma com a Agenda; se
        # estivesse desligado (caso comum, já que backup por WhatsApp é
        # opt-in), a Agenda nunca mandava nada mesmo com a Evolution API
        # configurada e funcionando. `enviar_texto_whatsapp` já valida
        # sozinho se a URL/chave da Evolution API existem.
        try:
            config = backup_service.obter_configuracao(conn)
            backup_service.enviar_texto_whatsapp(config, dono["celular"], texto)
            _marcar_enviado(conn, evento["id"], "whatsapp", repeticao_num)
        except Exception:
            pass  # lembrete não pode derrubar o ciclo do agendador; tenta de novo no próximo ciclo

    if evento["notificar_push"] and not _ja_enviado(conn, evento["id"], "push", repeticao_num):
        enviar_push(conn, evento["usuario_dono_id"], evento["titulo"], texto, {"eventoId": evento["id"]})
        _marcar_enviado(conn, evento["id"], "push", repeticao_num)


# ─── Agendador em background ────────────────────────────────────────────────

def _rodar_ciclo(db_path):
    from . import db as db_module

    with db_module.get_conn(db_path) as conn:
        agora = datetime.datetime.now()
        limite_atraso = agora - datetime.timedelta(minutes=JANELA_TOLERANCIA_ATRASO_MINUTOS)
        eventos = conn.execute(
            "SELECT * FROM agenda_eventos WHERE status = 'agendado' AND data_inicio >= ?",
            (limite_atraso.isoformat(),),
        ).fetchall()
        for row in eventos:
            evento = dict(row)
            inicio = datetime.datetime.fromisoformat(evento["data_inicio"])
            base = inicio - datetime.timedelta(minutes=evento["lembrete_antecedencia_min"])
            for repeticao_num in range(1, evento["lembrete_repeticoes"] + 1):
                horario_lembrete = base + datetime.timedelta(minutes=evento["lembrete_intervalo_min"] * (repeticao_num - 1))
                if horario_lembrete > agora or horario_lembrete > inicio or horario_lembrete < limite_atraso:
                    continue
                enviar_lembrete(conn, evento, repeticao_num)


def _loop_agendador(db_path):
    while True:
        try:
            _rodar_ciclo(db_path)
        except Exception:
            pass
        time.sleep(INTERVALO_VERIFICACAO_SEGUNDOS)


def iniciar_agendador_em_background(db_path=None):
    """Chamada nos mesmos pontos de entrada que já chamam
    `backup_service.iniciar_agendador_em_background()` — nunca por
    `create_app()` (ver docstring de lá)."""
    thread = threading.Thread(target=_loop_agendador, args=(db_path,), daemon=True, name="alphafitus-agenda-agendador")
    thread.start()
    return thread
