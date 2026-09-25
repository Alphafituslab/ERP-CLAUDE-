-- Alphafitus OS — Fase 204 (Agenda: contatos externos salvos + empresa)
--
-- Pedido do usuário (2026-09-25): não digitar nome/e-mail/telefone/empresa
-- de um convidado externo toda vez que marcar uma nova call com a mesma
-- pessoa — o primeiro convite já salva o contato numa lista reutilizável
-- (compartilhada entre todo mundo que usa a Agenda, como uma agenda de
-- contatos da empresa), e da próxima vez é só escolher da lista.
ALTER TABLE agenda_participantes ADD COLUMN empresa_externo TEXT;

CREATE TABLE agenda_contatos_externos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL,
    empresa         TEXT,
    email           TEXT,
    celular         TEXT,
    criado_por      INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_em   TEXT
);
