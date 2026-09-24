-- Alphafitus OS — Fase 193 (Agenda da equipe)
--
-- Pedido do usuário: uma aba "Agendas" tipo Google Agenda, compartilhada —
-- todo mundo vê os compromissos de todo mundo (com o nome de quem criou),
-- mas só o dono do compromisso ou o Administrador pode editar/excluir.
-- Lembrete configurável por evento em até 3 canais (chat interno,
-- WhatsApp, push do navegador), com antecedência e repetições próprias
-- de cada compromisso, e checagem de conflito de horário para o mesmo
-- dono (com opção de confirmar "mesmo assim").
--
-- Ver/criar/editar-o-próprio/excluir-o-próprio não passam pelo sistema de
-- permissões — são liberados a qualquer usuário autenticado (mesmo
-- espírito de "ver meu próprio perfil"/"minhas sessões" já usado em outras
-- telas, ex.: app/routes/funcionarios.py, POST /setores). Só o acesso
-- CRUZADO (editar/excluir o compromisso de outra pessoa) passa por
-- permissão de verdade — "agenda.editar_todos"/"agenda.excluir_todos",
-- que o Administrador já recebe de graça por ter "TODAS" (ver seed.py).
PRAGMA foreign_keys = ON;

CREATE TABLE agenda_eventos (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo                      TEXT NOT NULL,
    descricao                   TEXT,
    data_inicio                 TEXT NOT NULL,
    data_fim                    TEXT,
    local_texto                 TEXT,
    cor                         TEXT NOT NULL DEFAULT '#3B82F6',
    usuario_dono_id             INTEGER NOT NULL REFERENCES usuarios(id),
    criado_por_id               INTEGER NOT NULL REFERENCES usuarios(id),
    notificar_chat_interno      INTEGER NOT NULL DEFAULT 1 CHECK (notificar_chat_interno IN (0,1)),
    notificar_whatsapp          INTEGER NOT NULL DEFAULT 1 CHECK (notificar_whatsapp IN (0,1)),
    notificar_push              INTEGER NOT NULL DEFAULT 1 CHECK (notificar_push IN (0,1)),
    lembrete_antecedencia_min   INTEGER NOT NULL DEFAULT 30,
    lembrete_repeticoes         INTEGER NOT NULL DEFAULT 1,
    lembrete_intervalo_min      INTEGER NOT NULL DEFAULT 10,
    status                      TEXT NOT NULL DEFAULT 'agendado'
                                CHECK (status IN ('agendado','concluido','cancelado')),
    conflito_confirmado         INTEGER NOT NULL DEFAULT 0 CHECK (conflito_confirmado IN (0,1)),
    criado_em                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_em               TEXT,
    atualizado_por              INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_agenda_eventos_dono_periodo ON agenda_eventos(usuario_dono_id, data_inicio);
CREATE INDEX idx_agenda_eventos_periodo ON agenda_eventos(data_inicio);

-- Log de lembretes já disparados — evita reenviar a mesma repetição se o
-- agendador em background reiniciar no meio do caminho (mesmo cuidado de
-- idempotência que app/backup_service.py já tem para o backup agendado).
CREATE TABLE agenda_lembretes_enviados (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id       INTEGER NOT NULL REFERENCES agenda_eventos(id) ON DELETE CASCADE,
    canal           TEXT NOT NULL CHECK (canal IN ('chat','whatsapp','push')),
    repeticao_num   INTEGER NOT NULL,
    enviado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (evento_id, canal, repeticao_num)
);

-- Inscrições de push do navegador (Web Push padrão W3C — reaproveita o
-- Service Worker do PWA que o sistema já registra em frontend/static/app.js,
-- `navigator.serviceWorker.register("/sw.js")`). Um usuário pode ter mais
-- de uma inscrição (um por navegador/dispositivo em que ativou notificações).
CREATE TABLE agenda_push_subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id),
    endpoint        TEXT NOT NULL UNIQUE,
    p256dh          TEXT NOT NULL,
    auth            TEXT NOT NULL,
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- "agenda.editar_todos"/"agenda.excluir_todos" nascem pelo seed.py normal
-- (INSERT idempotente em PERMISSOES_PADRAO), igual toda outra permissão
-- nova do sistema — nunca inserido direto numa migration.
