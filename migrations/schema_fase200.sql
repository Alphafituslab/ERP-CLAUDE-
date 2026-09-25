-- Alphafitus OS — Fase 200 (Agenda: convidar participante EXTERNO)
--
-- Pedido do usuário (2026-09-25): convidar pra um compromisso não só
-- usuários do sistema, mas também gente de fora (cliente, fornecedor,
-- prestador) — digitando nome + e-mail e/ou WhatsApp na hora. O convite
-- sai igualzinho ao de um usuário interno (WhatsApp/e-mail com link de
-- aceitar/recusar sem login), só que sem chat interno/push (a pessoa não
-- tem conta no ERP nem no Whatts Inbox).
--
-- `agenda_participantes.usuario_id` era NOT NULL — precisa virar opcional
-- (NULL = participante externo). SQLite não altera NOT NULL/CHECK de uma
-- coluna existente com ALTER TABLE — mesmo caminho já usado na Fase 195
-- (reconstruir a tabela: criar nova, copiar dado, apagar a antiga, renomear).
-- A tabela está em produção há poucos minutos (Fase 199) e ainda vazia na
-- prática, mas o rebuild preserva qualquer linha que já exista de qualquer
-- forma, sem perder nada.
PRAGMA foreign_keys = OFF;

CREATE TABLE agenda_participantes_novo (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id               INTEGER NOT NULL REFERENCES agenda_eventos(id) ON DELETE CASCADE,
    usuario_id              INTEGER REFERENCES usuarios(id),
    nome_externo            TEXT,
    email_externo           TEXT,
    celular_externo         TEXT,
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','aceito','recusado')),
    motivo_recusa           TEXT,
    token_convite           TEXT NOT NULL UNIQUE,
    convidado_por           INTEGER NOT NULL REFERENCES usuarios(id),
    convidado_em            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    respondido_em           TEXT,
    UNIQUE(evento_id, usuario_id),
    CHECK (
        (usuario_id IS NOT NULL AND nome_externo IS NULL AND email_externo IS NULL AND celular_externo IS NULL)
        OR
        (usuario_id IS NULL AND nome_externo IS NOT NULL AND (email_externo IS NOT NULL OR celular_externo IS NOT NULL))
    )
);

INSERT INTO agenda_participantes_novo
    (id, evento_id, usuario_id, status, motivo_recusa, token_convite, convidado_por, convidado_em, respondido_em)
SELECT id, evento_id, usuario_id, status, motivo_recusa, token_convite, convidado_por, convidado_em, respondido_em
FROM agenda_participantes;

DROP TABLE agenda_participantes;
ALTER TABLE agenda_participantes_novo RENAME TO agenda_participantes;

PRAGMA foreign_keys = ON;
