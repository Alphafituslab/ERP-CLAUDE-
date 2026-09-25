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
import logging
import os
import threading
import time

import secrets

from . import backup_service
from . import chat_interno_service
from . import notificacoes_service
from .permissions import usuario_tem_permissao

INTERVALO_VERIFICACAO_SEGUNDOS = 60
# Web Push (padrão W3C) exige um par de chaves VAPID — geradas UMA vez com
# `python -m py_vapid` (biblioteca `pywebpush` traz o helper) e guardadas só
# como variável de ambiente, nunca commitadas (mesmo espírito de
# ALPHAFITUS_JWT_SECRET em app/security.py). Sem essas variáveis definidas,
# o canal "push" simplesmente não dispara — os outros dois continuam normais.
_log = logging.getLogger(__name__)

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


# ─── Visibilidade de detalhe (Fase 198) ─────────────────────────────────────
# Quem tem "agenda.editar_todos" (Administrador, de graça via "TODAS") sempre
# vê tudo em detalhe. Os demais só veem o motivo/local/descrição de outro
# dono se houver uma linha explícita em `agenda_permissoes_visualizacao` — a
# própria agenda é sempre visível, sem precisar de linha nenhuma. Quem não
# tem a permissão pra um dono continua vendo QUE existe um compromisso
# naquele horário (nunca escondido — é uma agenda de equipe, ninguém marca
# por cima sem saber), só que com um rótulo genérico no lugar do conteúdo.
def _donos_visiveis_em_detalhe(conn, usuario_visualizador_id: int):
    """`None` = enxerga todo mundo em detalhe (só o "usuário master", Fase
    202). Do contrário, devolve o conjunto de `usuario_dono_id` que este
    usuário pode ver em detalhe (sempre incluindo ele mesmo).

    Achado real (2026-09-25): a permissão "agenda.editar_todos" (que o
    perfil Administrador tem de graça via "TODAS") NÃO libera visualização
    de detalhe — ela existe só pra editar/excluir o compromisso de outra
    pessoa. Sem isso, qualquer Administrador via o motivo/local reais de um
    compromisso PESSOAL de outro Administrador (achado com Caroline vendo o
    compromisso "Gaúcha" do Clayton) — visibilidade de detalhe nunca passa
    mais por atalho de perfil/permissão. O único bypass que existe é o flag
    `usuarios.usuario_master` (conta marcada manualmente, fora do sistema
    de perfis — nunca "TODAS", que daria de graça pra todo Administrador,
    o oposto do pedido de ser só uma conta específica)."""
    eh_master = conn.execute("SELECT usuario_master FROM usuarios WHERE id = ?", (usuario_visualizador_id,)).fetchone()
    if eh_master and eh_master["usuario_master"]:
        return None
    rows = conn.execute(
        "SELECT usuario_dono_id FROM agenda_permissoes_visualizacao WHERE usuario_visualizador_id = ?",
        (usuario_visualizador_id,),
    ).fetchall()
    donos = {r["usuario_dono_id"] for r in rows}
    donos.add(usuario_visualizador_id)
    return donos


def _redigir_evento_se_necessario(evento: dict, donos_visiveis) -> dict:
    if donos_visiveis is None or evento["usuario_dono_id"] in donos_visiveis:
        return evento
    evento = dict(evento)
    evento["titulo"] = f"Agenda de {evento.get('dono_nome') or 'outro usuário'}"
    evento["descricao"] = None
    evento["local_texto"] = None
    evento["link_video"] = None
    evento["lembrete_mensagem_custom"] = None
    return evento


def permissoes_visualizacao_do_usuario(conn, usuario_visualizador_id: int):
    rows = conn.execute(
        "SELECT usuario_dono_id FROM agenda_permissoes_visualizacao WHERE usuario_visualizador_id = ?",
        (usuario_visualizador_id,),
    ).fetchall()
    return [r["usuario_dono_id"] for r in rows]


def definir_permissoes_visualizacao(conn, usuario_visualizador_id: int, donos_ids: list, criado_por_id: int):
    conn.execute("DELETE FROM agenda_permissoes_visualizacao WHERE usuario_visualizador_id = ?", (usuario_visualizador_id,))
    for dono_id in donos_ids:
        if dono_id == usuario_visualizador_id:
            continue  # a própria agenda já é sempre visível, não precisa de linha
        conn.execute(
            "INSERT INTO agenda_permissoes_visualizacao (usuario_visualizador_id, usuario_dono_id, criado_por) VALUES (?, ?, ?)",
            (usuario_visualizador_id, dono_id, criado_por_id),
        )
    return permissoes_visualizacao_do_usuario(conn, usuario_visualizador_id)


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
    "titulo", "descricao", "data_inicio", "data_fim", "local_texto", "link_video", "cor",
    "usuario_dono_id", "notificar_chat_interno", "notificar_whatsapp", "notificar_push",
    "lembrete_antecedencia_min", "lembrete_repeticoes", "lembrete_intervalo_min",
    "lembrete_mensagem_custom",
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
    "link_video": None,
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


def listar_eventos(conn, de: str, ate: str, usuario_visualizador_id: int):
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
    donos_visiveis = _donos_visiveis_em_detalhe(conn, usuario_visualizador_id)
    meus_convites = {
        r["evento_id"]: r["status"]
        for r in conn.execute(
            "SELECT evento_id, status FROM agenda_participantes WHERE usuario_id = ?", (usuario_visualizador_id,)
        ).fetchall()
    }
    # Pedido do usuário (2026-09-25): dar pra ver de relance, sem abrir o
    # compromisso, quantos convidados já responderam — resumo por evento
    # (total de convidados / quantos já aceitaram), pra mostrar como um
    # selinho no próprio card do calendário.
    resumo_participantes = {}
    for r in conn.execute("SELECT evento_id, status FROM agenda_participantes").fetchall():
        resumo = resumo_participantes.setdefault(r["evento_id"], {"total": 0, "aceitos": 0})
        resumo["total"] += 1
        if r["status"] == "aceito":
            resumo["aceitos"] += 1

    resultado = []
    for r in rows:
        evento = dict(r)
        meu_status = meus_convites.get(evento["id"])
        if meu_status == "recusado":
            continue  # convite recusado some da própria agenda de quem recusou
        if meu_status in ("pendente", "aceito"):
            # Convidado pra ESSE compromisso específico: vê o detalhe
            # completo pra poder decidir/já sabe do que se trata, mesmo que
            # a Fase 198 não libere a agenda geral do dono pra essa pessoa.
            evento["meu_convite_status"] = meu_status
        else:
            evento = _redigir_evento_se_necessario(evento, donos_visiveis)
            evento["meu_convite_status"] = None
        evento["participantes_resumo"] = resumo_participantes.get(evento["id"])
        resultado.append(evento)
    return resultado


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


# ─── Participantes / convites (Fase 199) ────────────────────────────────────
# Só existe aviso quando alguém é CONVIDADO — um compromisso pessoal (sem
# `participante_ids`) nunca dispara nada disso, exatamente como antes desta
# fase. Cada convidado tem seu próprio status (`pendente`/`aceito`/
# `recusado`) — decisão confirmada com o usuário: a mudança visual de
# "convite pendente" pra "aceito" é por pessoa, nunca depende dos outros
# convidados do mesmo compromisso.

def participantes_do_evento(conn, evento_id: int):
    """Fase 200 — o convidado pode ser um usuário do sistema (`usuario_id`
    preenchido, `usuario_nome` vem do JOIN) ou alguém de fora (`usuario_id`
    nulo, nome/e-mail/celular digitados na hora do convite) — o front trata
    os dois de forma parecida usando `nome`/`externo`."""
    rows = conn.execute(
        """
        SELECT p.id, p.usuario_id, u.nome AS usuario_nome, p.nome_externo, p.empresa_externo, p.email_externo,
               p.celular_externo, p.status, p.motivo_recusa, p.convidado_em, p.respondido_em
        FROM agenda_participantes p
        LEFT JOIN usuarios u ON u.id = p.usuario_id
        WHERE p.evento_id = ?
        ORDER BY COALESCE(u.nome, p.nome_externo)
        """,
        (evento_id,),
    ).fetchall()
    resultado = []
    for r in rows:
        p = dict(r)
        p["externo"] = p["usuario_id"] is None
        p["nome"] = p["usuario_nome"] or p["nome_externo"]
        resultado.append(p)
    return resultado


def _texto_convite(evento: dict, convidado_por_nome: str, link: str | None) -> str:
    inicio = datetime.datetime.fromisoformat(evento["data_inicio"])
    linhas = [
        f"📅 Você foi convidado(a) para um compromisso por {convidado_por_nome}:",
        f"*{evento['titulo']}*",
        f"🗓️ {inicio.strftime('%d/%m/%Y às %H:%M')}",
    ]
    if evento.get("local_texto"):
        linhas.append(f"📍 {evento['local_texto']}")
    if evento.get("link_video"):
        linhas.append(f"📹 Videochamada: {evento['link_video']}")
    if link:
        linhas.append(f"\nAceitar ou recusar: {link}")
    else:
        linhas.append("\nAbra a Agenda no sistema para aceitar ou recusar.")
    return "\n".join(linhas)


def _texto_confirmacao(evento: dict, aceito: bool) -> str:
    inicio = datetime.datetime.fromisoformat(evento["data_inicio"])
    if aceito:
        return f"✅ Presença confirmada em \"{evento['titulo']}\" — {inicio.strftime('%d/%m/%Y às %H:%M')}."
    return f"❌ Você recusou o convite para \"{evento['titulo']}\" — {inicio.strftime('%d/%m/%Y às %H:%M')}."


def _link_convite(token: str) -> str:
    base = os.environ.get("ALPHAFITUS_URL_PUBLICA", "https://erp.alphafitus.com.br")
    return f"{base.rstrip('/')}/portal/agenda-convite/{token}"


def _dispatch_mensagem_usuario(conn, usuario_row, texto: str, evento_id: int | None = None, evento: dict | None = None):
    """Manda `texto` pro usuário pelos 3 canais internos (chat interno,
    WhatsApp, push) — melhor esforço, cada canal isolado (um falhar não
    impede os outros). Mesmo padrão de `enviar_lembrete`, só que disparado
    na hora (convite/confirmação), não pelo agendador em background.

    Pedido do usuário (2026-09-25): "às vezes a agenda é só interna, não
    precisa mandar no WhatsApp" — os MESMOS 3 interruptores do compromisso
    (`notificar_chat_interno`/`notificar_whatsapp`/`notificar_push`, hoje já
    escolhidos na tela) agora valem pro CONVITE também, não só pro lembrete
    de antes do horário. Sem `evento` (chamada antiga/legado), assume os
    3 ligados — mantém compatível.

    Achado real (2026-09-25): um `except Exception: pass` sem log nenhum
    deixa uma falha de envio (WhatsApp/e-mail fora do ar, número inválido,
    etc.) completamente invisível — ninguém percebe que o convite não
    chegou até o convidado reclamar. Sempre registra o motivo agora."""
    if evento is None or evento.get("notificar_chat_interno"):
        try:
            email_destino = usuario_row["email_chat_interno"] or usuario_row["email"]
            sucesso, motivo = chat_interno_service.enviar_mensagem_chat_interno(email_destino, texto)
            if not sucesso:
                _log.warning("Agenda: chat interno não enviado pra usuário %s — %s", usuario_row["id"], motivo)
        except Exception:
            _log.exception("Agenda: falha ao enviar chat interno pra usuário %s", usuario_row["id"])
    if usuario_row["celular"] and (evento is None or evento.get("notificar_whatsapp")):
        try:
            config = backup_service.obter_configuracao(conn)
            numero = backup_service.normalizar_numero_brasileiro(usuario_row["celular"])
            backup_service.enviar_texto_whatsapp(config, numero, texto)
        except Exception:
            _log.exception("Agenda: falha ao enviar WhatsApp pra usuário %s (numero=%s)", usuario_row["id"], usuario_row["celular"])
    if evento is None or evento.get("notificar_push"):
        try:
            enviar_push(conn, usuario_row["id"], "Agenda", texto, {"eventoId": evento_id} if evento_id else None)
        except Exception:
            _log.exception("Agenda: falha ao enviar push pra usuário %s", usuario_row["id"])


def _dispatch_email_direto(conn, email: str, assunto: str, texto: str):
    """E-mail é opcional/melhor-esforço igual aos outros canais — sem SMTP
    configurado (`configuracoes_email.ativo`), simplesmente não manda nada,
    sem quebrar o convite pelos outros canais."""
    if not email:
        return
    try:
        config = notificacoes_service.obter_configuracao_email(conn)
        if not config.get("ativo") or not config.get("smtp_host"):
            _log.info("Agenda: e-mail pra %s não enviado — SMTP não configurado/ativo.", email)
            return
        notificacoes_service._enviar_email_smtp(config, email, assunto, texto)
    except Exception:
        _log.exception("Agenda: falha ao enviar e-mail pra %s", email)


def _dispatch_whatsapp_direto(conn, celular: str, texto: str):
    if not celular:
        return
    try:
        config = backup_service.obter_configuracao(conn)
        numero = backup_service.normalizar_numero_brasileiro(celular)
        backup_service.enviar_texto_whatsapp(config, numero, texto)
    except Exception:
        _log.exception("Agenda: falha ao enviar WhatsApp pro contato externo (numero=%s)", celular)


def convidar_participantes(conn, evento: dict, usuario_ids: list, convidado_por_id: int, convidado_por_nome: str):
    """Cria as linhas novas em `agenda_participantes` (ignora quem já é
    participante — não reenvia convite pra quem já foi convidado antes) e
    dispara o convite multi-canal só pros RECÉM-adicionados."""
    for usuario_id in usuario_ids:
        if usuario_id == evento["usuario_dono_id"]:
            continue  # o dono já é dono, não precisa convidar a si mesmo
        ja_participante = conn.execute(
            "SELECT 1 FROM agenda_participantes WHERE evento_id = ? AND usuario_id = ?",
            (evento["id"], usuario_id),
        ).fetchone()
        if ja_participante:
            continue
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO agenda_participantes (evento_id, usuario_id, token_convite, convidado_por) VALUES (?, ?, ?, ?)",
            (evento["id"], usuario_id, token, convidado_por_id),
        )
        usuario_row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if usuario_row is None:
            continue
        link = _link_convite(token)
        texto = _texto_convite(evento, convidado_por_nome, link)
        _dispatch_mensagem_usuario(conn, usuario_row, texto, evento["id"], evento)
        _dispatch_email_direto(conn, usuario_row["email"], f"Convite: {evento['titulo']}", texto)


def convidar_participantes_externos(conn, evento: dict, participantes_externos: list, convidado_por_id: int, convidado_por_nome: str):
    """Fase 200 — pedido do usuário: convidar gente de FORA do sistema
    (cliente, fornecedor, prestador), digitando nome + e-mail e/ou WhatsApp
    na hora. Convite igual ao de um usuário interno (WhatsApp/e-mail com
    link de aceitar/recusar sem login), só sem chat interno/push — a
    pessoa não tem conta no ERP nem no Whatts Inbox.

    Fase 204 — cada convidado externo é salvo (ou atualizado) na agenda de
    contatos reutilizável (`salvar_contato_externo`), pra não precisar
    digitar tudo de novo numa próxima reunião com a mesma pessoa."""
    for participante in participantes_externos:
        nome = (participante.get("nome") or "").strip()
        empresa = (participante.get("empresa") or "").strip() or None
        email = (participante.get("email") or "").strip() or None
        celular = (participante.get("celular") or "").strip() or None
        if not nome or not (email or celular):
            continue  # nome + pelo menos um contato são obrigatórios (checado de novo na rota)
        token = secrets.token_urlsafe(32)
        conn.execute(
            """
            INSERT INTO agenda_participantes (evento_id, nome_externo, empresa_externo, email_externo, celular_externo, token_convite, convidado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (evento["id"], nome, empresa, email, celular, token, convidado_por_id),
        )
        salvar_contato_externo(conn, nome, empresa, email, celular, convidado_por_id)
        link = _link_convite(token)
        texto = _texto_convite(evento, convidado_por_nome, link)
        if evento.get("notificar_whatsapp"):
            _dispatch_whatsapp_direto(conn, celular, texto)
        _dispatch_email_direto(conn, email, f"Convite: {evento['titulo']}", texto)


# ─── Contatos externos salvos (Fase 204) ────────────────────────────────────
# Lista compartilhada entre todo mundo que usa a Agenda (como uma agenda de
# contatos da empresa) — não é por usuário, pra qualquer um poder reaproveitar
# um contato que outra pessoa já convidou antes.

def listar_contatos_externos(conn):
    rows = conn.execute("SELECT * FROM agenda_contatos_externos ORDER BY nome").fetchall()
    return [dict(r) for r in rows]


def salvar_contato_externo(conn, nome: str, empresa: str | None, email: str | None, celular: str | None, criado_por_id: int):
    """Upsert por e-mail OU celular (o que tiver) — evita duplicar o mesmo
    contato a cada convite novo, mas sempre atualiza nome/empresa/o outro
    contato com o valor mais recente informado."""
    existente = None
    if email:
        existente = conn.execute("SELECT * FROM agenda_contatos_externos WHERE email = ?", (email,)).fetchone()
    if existente is None and celular:
        existente = conn.execute("SELECT * FROM agenda_contatos_externos WHERE celular = ?", (celular,)).fetchone()

    if existente:
        conn.execute(
            """
            UPDATE agenda_contatos_externos
            SET nome = ?, empresa = COALESCE(?, empresa), email = COALESCE(?, email), celular = COALESCE(?, celular),
                atualizado_em = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id = ?
            """,
            (nome, empresa, email, celular, existente["id"]),
        )
        return existente["id"]

    cur = conn.execute(
        "INSERT INTO agenda_contatos_externos (nome, empresa, email, celular, criado_por) VALUES (?, ?, ?, ?, ?)",
        (nome, empresa, email, celular, criado_por_id),
    )
    return cur.lastrowid


def excluir_contato_externo(conn, contato_id: int):
    conn.execute("DELETE FROM agenda_contatos_externos WHERE id = ?", (contato_id,))


def remover_participantes_ausentes(conn, evento_id: int, usuario_ids_mantidos: list, participantes_externos_ids_mantidos: list):
    """Ao editar um compromisso, quem foi TIRADO da lista de convidados tem
    sua linha apagada — cancela o convite (pendente) ou a confirmação
    (aceito) dela pra esse compromisso, sem avisar (é uma remoção
    administrativa, não uma recusa da própria pessoa). Um convidado externo
    só existe pra esse compromisso (não tem cadastro pra "reencontrar"),
    então ele é identificado pelo próprio id da linha em
    `agenda_participantes`, não por usuario_id como o interno."""
    participantes_atuais = conn.execute(
        "SELECT id, usuario_id FROM agenda_participantes WHERE evento_id = ?", (evento_id,)
    ).fetchall()
    for row in participantes_atuais:
        if row["usuario_id"] is not None:
            if row["usuario_id"] not in usuario_ids_mantidos:
                conn.execute("DELETE FROM agenda_participantes WHERE id = ?", (row["id"],))
        else:
            if row["id"] not in participantes_externos_ids_mantidos:
                conn.execute("DELETE FROM agenda_participantes WHERE id = ?", (row["id"],))


def sincronizar_participantes(
    conn, evento: dict, usuario_ids: list, participantes_externos: list, convidado_por_id: int, convidado_por_nome: str
):
    """`participantes_externos` é uma lista de dicts — os que já existem
    (editando um compromisso) trazem `id` (o id da linha em
    `agenda_participantes`, pra saber quem manter) e os NOVOS não trazem
    `id` (só nome/email/celular), disparando um convite novo pra eles."""
    ids_externos_existentes = [p["id"] for p in participantes_externos if p.get("id")]
    externos_novos = [p for p in participantes_externos if not p.get("id")]
    remover_participantes_ausentes(conn, evento["id"], usuario_ids, ids_externos_existentes)
    convidar_participantes(conn, evento, usuario_ids, convidado_por_id, convidado_por_nome)
    convidar_participantes_externos(conn, evento, externos_novos, convidado_por_id, convidado_por_nome)


def convites_pendentes_do_usuario(conn, usuario_id: int):
    rows = conn.execute(
        """
        SELECT p.id AS participante_id, e.*, c.nome AS convidado_por_nome
        FROM agenda_participantes p
        JOIN agenda_eventos e ON e.id = p.evento_id
        JOIN usuarios c ON c.id = p.convidado_por
        WHERE p.usuario_id = ? AND p.status = 'pendente' AND e.status = 'agendado'
        ORDER BY e.data_inicio
        """,
        (usuario_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _responder_convite_nucleo(conn, participante_id: int, aceitar: bool, motivo: str | None = None):
    """Núcleo comum — identidade já foi provada por quem chamou (rota
    autenticada checou `usuario_id`, ou o portal resolveu pelo token opaco).
    Ao responder, confirma pro próprio convidado (interno pelos 3 canais
    internos, externo por WhatsApp/e-mail) e avisa quem convidou."""
    participante = conn.execute("SELECT * FROM agenda_participantes WHERE id = ?", (participante_id,)).fetchone()
    if participante is None:
        return None
    evento = conn.execute("SELECT * FROM agenda_eventos WHERE id = ?", (participante["evento_id"],)).fetchone()
    if evento is None:
        return None
    participante = dict(participante)
    evento = dict(evento)
    novo_status = "aceito" if aceitar else "recusado"
    conn.execute(
        "UPDATE agenda_participantes SET status = ?, motivo_recusa = ?, respondido_em = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (novo_status, (motivo or None) if not aceitar else None, participante_id),
    )

    texto_confirmacao = _texto_confirmacao(evento, aceitar)
    nome_convidado = None
    if participante["usuario_id"]:
        usuario_row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (participante["usuario_id"],)).fetchone()
        if usuario_row is not None:
            nome_convidado = usuario_row["nome"]
            _dispatch_mensagem_usuario(conn, usuario_row, texto_confirmacao, evento["id"], evento)
    else:
        nome_convidado = participante["nome_externo"]
        if evento.get("notificar_whatsapp"):
            _dispatch_whatsapp_direto(conn, participante["celular_externo"], texto_confirmacao)
        _dispatch_email_direto(conn, participante["email_externo"], f"Confirmação: {evento['titulo']}", texto_confirmacao)

    convidado_por = conn.execute("SELECT * FROM usuarios WHERE id = ?", (participante["convidado_por"],)).fetchone()
    if convidado_por is not None and nome_convidado:
        acao = "aceitou" if aceitar else "recusou"
        texto_organizador = f"{nome_convidado} {acao} o convite para \"{evento['titulo']}\"."
        if not aceitar and motivo:
            texto_organizador += f" Motivo: {motivo}"
        _dispatch_mensagem_usuario(conn, convidado_por, texto_organizador, evento["id"], evento)

    return dict(conn.execute("SELECT * FROM agenda_participantes WHERE id = ?", (participante_id,)).fetchone())


def responder_convite(conn, participante_id: int, usuario_id: int, aceitar: bool, motivo: str | None = None):
    """Versão pra rota AUTENTICADA — só o próprio convidado (usuario_id
    bate) responde o convite dele. Um convidado externo nunca passa por
    aqui (não tem login) — só pelo portal público, que resolve pelo token
    e chama `_responder_convite_nucleo` direto."""
    participante = conn.execute(
        "SELECT id FROM agenda_participantes WHERE id = ? AND usuario_id = ?", (participante_id, usuario_id)
    ).fetchone()
    if participante is None:
        return None
    return _responder_convite_nucleo(conn, participante_id, aceitar, motivo)


def resolver_convite_por_token(conn, token: str):
    row = conn.execute("SELECT * FROM agenda_participantes WHERE token_convite = ?", (token,)).fetchone()
    return dict(row) if row else None


def _texto_atualizacao(evento: dict, atualizado_por_nome: str) -> str:
    inicio = datetime.datetime.fromisoformat(evento["data_inicio"])
    linhas = [
        f"🔄 {atualizado_por_nome} atualizou um compromisso que você já tinha sido convidado:",
        f"*{evento['titulo']}*",
        f"🗓️ {inicio.strftime('%d/%m/%Y às %H:%M')}",
    ]
    if evento.get("local_texto"):
        linhas.append(f"📍 {evento['local_texto']}")
    if evento.get("link_video"):
        linhas.append(f"📹 Videochamada: {evento['link_video']}")
    return "\n".join(linhas)


def notificar_atualizacao_participantes(conn, evento: dict, atualizado_por_nome: str):
    """Pedido do usuário (2026-09-25): mudar detalhe de um compromisso que
    já tem gente convidada (pendente ou já aceito) pergunta ANTES se avisa
    essas pessoas — nunca reseta a resposta de quem já respondeu, é só um
    aviso informativo da mudança."""
    participantes = conn.execute(
        "SELECT * FROM agenda_participantes WHERE evento_id = ? AND status IN ('pendente','aceito')", (evento["id"],)
    ).fetchall()
    texto = _texto_atualizacao(evento, atualizado_por_nome)
    for p in participantes:
        p = dict(p)
        if p["usuario_id"]:
            usuario_row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (p["usuario_id"],)).fetchone()
            if usuario_row is not None:
                _dispatch_mensagem_usuario(conn, usuario_row, texto, evento["id"], evento)
        else:
            if evento.get("notificar_whatsapp"):
                _dispatch_whatsapp_direto(conn, p["celular_externo"], texto)
            _dispatch_email_direto(conn, p["email_externo"], f"Atualização: {evento['titulo']}", texto)


# ─── Envio de lembretes ─────────────────────────────────────────────────────

def _texto_lembrete(evento: dict) -> str:
    # Fase 196 — pedido do usuário: poder escrever a própria mensagem do
    # lembrete. Quando preenchida, vai exatamente como digitada (sem
    # anexar título/data/local automaticamente por cima) — "eu poder
    # escrever o que eu quero e assim vai conforme eu escolher".
    if evento.get("lembrete_mensagem_custom"):
        return evento["lembrete_mensagem_custom"]
    inicio = datetime.datetime.fromisoformat(evento["data_inicio"])
    linhas = [f"🗓️ Lembrete: {evento['titulo']}", f"📅 {inicio.strftime('%d/%m/%Y às %H:%M')}"]
    if evento.get("local_texto"):
        linhas.append(f"📍 {evento['local_texto']}")
    if evento.get("link_video"):
        linhas.append(f"📹 Videochamada: {evento['link_video']}")
    if evento.get("descricao"):
        linhas.append(evento["descricao"])
    return "\n".join(linhas)


def _ja_enviado(conn, evento_id: int, canal: str, repeticao_num: int, participante_id: int | None = None) -> bool:
    """`participante_id=None` = lembrete do DONO do compromisso; um valor
    identifica o lembrete de um participante específico que aceitou o
    convite — cada um com seu próprio controle de idempotência (Fase 201),
    senão o envio pro dono "usaria" o mesmo registro de controle do envio
    pro participante e vice-versa, pulando um dos dois por engano."""
    return conn.execute(
        "SELECT 1 FROM agenda_lembretes_enviados WHERE evento_id = ? AND canal = ? AND repeticao_num = ? AND participante_id IS ?",
        (evento_id, canal, repeticao_num, participante_id),
    ).fetchone() is not None


def _marcar_enviado(conn, evento_id: int, canal: str, repeticao_num: int, participante_id: int | None = None):
    conn.execute(
        "INSERT OR IGNORE INTO agenda_lembretes_enviados (evento_id, canal, repeticao_num, participante_id) VALUES (?, ?, ?, ?)",
        (evento_id, canal, repeticao_num, participante_id),
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
            numero = backup_service.normalizar_numero_brasileiro(dono["celular"])
            backup_service.enviar_texto_whatsapp(config, numero, texto)
            _marcar_enviado(conn, evento["id"], "whatsapp", repeticao_num)
        except Exception:
            pass  # lembrete não pode derrubar o ciclo do agendador; tenta de novo no próximo ciclo

    if evento["notificar_push"] and not _ja_enviado(conn, evento["id"], "push", repeticao_num):
        enviar_push(conn, evento["usuario_dono_id"], evento["titulo"], texto, {"eventoId": evento["id"]})
        _marcar_enviado(conn, evento["id"], "push", repeticao_num)

    # Fase 201 — pedido do usuário: quem ACEITOU o convite (interno ou
    # externo) recebe o MESMO lembrete que o dono, respeitando a mesma
    # antecedência/repetições/intervalo do compromisso — não é uma
    # configuração separada por pessoa, só uma audiência maior pro mesmo
    # aviso. Continua enquanto o compromisso não for cancelado (ver
    # `_repeticoes_devidas`/agendador, que já ignora eventos cancelados) —
    # aceitar não depende dos outros convidados, então cada aceite garante
    # o lembrete daquela pessoa até alguém cancelar o compromisso.
    participantes_aceitos = conn.execute(
        "SELECT * FROM agenda_participantes WHERE evento_id = ? AND status = 'aceito'", (evento["id"],)
    ).fetchall()
    for p in participantes_aceitos:
        p = dict(p)
        if p["usuario_id"]:
            usuario_row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (p["usuario_id"],)).fetchone()
            if usuario_row is None:
                continue
            if evento["notificar_chat_interno"] and not _ja_enviado(conn, evento["id"], "chat", repeticao_num, p["id"]):
                email_destino = usuario_row["email_chat_interno"] or usuario_row["email"]
                sucesso, _motivo = chat_interno_service.enviar_mensagem_chat_interno(email_destino, texto)
                if sucesso:
                    _marcar_enviado(conn, evento["id"], "chat", repeticao_num, p["id"])
            if evento["notificar_whatsapp"] and usuario_row["celular"] and not _ja_enviado(conn, evento["id"], "whatsapp", repeticao_num, p["id"]):
                try:
                    config = backup_service.obter_configuracao(conn)
                    numero = backup_service.normalizar_numero_brasileiro(usuario_row["celular"])
                    backup_service.enviar_texto_whatsapp(config, numero, texto)
                    _marcar_enviado(conn, evento["id"], "whatsapp", repeticao_num, p["id"])
                except Exception:
                    pass
            if evento["notificar_push"] and not _ja_enviado(conn, evento["id"], "push", repeticao_num, p["id"]):
                enviar_push(conn, p["usuario_id"], evento["titulo"], texto, {"eventoId": evento["id"]})
                _marcar_enviado(conn, evento["id"], "push", repeticao_num, p["id"])
        else:
            # Convidado externo — só WhatsApp/e-mail (não tem conta no ERP
            # nem no Whatts Inbox pra chat interno/push).
            if evento["notificar_whatsapp"] and p["celular_externo"] and not _ja_enviado(conn, evento["id"], "whatsapp", repeticao_num, p["id"]):
                _dispatch_whatsapp_direto(conn, p["celular_externo"], texto)
                _marcar_enviado(conn, evento["id"], "whatsapp", repeticao_num, p["id"])
            if p["email_externo"] and not _ja_enviado(conn, evento["id"], "email", repeticao_num, p["id"]):
                _dispatch_email_direto(conn, p["email_externo"], f"Lembrete: {evento['titulo']}", texto)
                _marcar_enviado(conn, evento["id"], "email", repeticao_num, p["id"])


def _repeticoes_devidas(evento: dict, agora: datetime.datetime, limite_atraso: datetime.datetime):
    """Quais números de repetição do lembrete já chegaram na hora (entre o
    horário calculado e agora, sem contar os velhos demais nem os que
    aconteceriam depois do início do evento). Compartilhado pelo
    agendador em background (chat/whatsapp/push) e pelo alerta bloqueante
    de tela (que é sob demanda, cada vez que o navegador pergunta)."""
    inicio = datetime.datetime.fromisoformat(evento["data_inicio"])
    base = inicio - datetime.timedelta(minutes=evento["lembrete_antecedencia_min"])
    devidas = []
    for repeticao_num in range(1, evento["lembrete_repeticoes"] + 1):
        horario_lembrete = base + datetime.timedelta(minutes=evento["lembrete_intervalo_min"] * (repeticao_num - 1))
        if horario_lembrete > agora or horario_lembrete > inicio or horario_lembrete < limite_atraso:
            continue
        devidas.append(repeticao_num)
    return devidas


# ─── Alerta bloqueante na tela ──────────────────────────────────────────────
# Pedido do usuário (2026-09-24): quando chegar a hora do lembrete (ex.: 4h
# antes), quem marcou o compromisso vê um alerta NA TELA que não sai
# sozinho — só fecha quando a pessoa clicar em "Ciente". Diferente dos
# outros 3 canais (que "enviam" pra fora), esse é sob demanda: o navegador
# pergunta a cada poucos segundos (mesmo padrão do sino de notificações,
# `iniciarPollingNotificacoes`) "tem algum alerta meu pendente?" — e só
# quando a pessoa fecha o alerta é que ele conta como "mostrado" (canal
# 'tela' em agenda_lembretes_enviados), pra nunca reaparecer sozinho.

def lembretes_tela_pendentes(conn, usuario_id: int):
    agora = datetime.datetime.now()
    limite_atraso = agora - datetime.timedelta(minutes=JANELA_TOLERANCIA_ATRASO_MINUTOS)
    eventos = conn.execute(
        "SELECT * FROM agenda_eventos WHERE usuario_dono_id = ? AND status = 'agendado' AND data_inicio >= ?",
        (usuario_id, limite_atraso.isoformat()),
    ).fetchall()
    pendentes = []
    for row in eventos:
        evento = dict(row)
        for repeticao_num in _repeticoes_devidas(evento, agora, limite_atraso):
            if not _ja_enviado(conn, evento["id"], "tela", repeticao_num):
                pendentes.append({**evento, "repeticao_num": repeticao_num})
    return pendentes


def confirmar_alerta_tela(conn, evento_id: int, repeticao_num: int):
    _marcar_enviado(conn, evento_id, "tela", repeticao_num)


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
            for repeticao_num in _repeticoes_devidas(evento, agora, limite_atraso):
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
