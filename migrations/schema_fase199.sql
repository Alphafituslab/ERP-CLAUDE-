-- Alphafitus OS — Fase 199 (Agenda: convidar participantes pro compromisso)
--
-- Pedido do usuário (2026-09-25): poder convidar mais de uma pessoa pra um
-- compromisso da Agenda. Só dispara aviso quando alguém é CONVIDADO — um
-- compromisso pessoal (sem participante nenhum) continua exatamente como
-- era, sem avisar ninguém. Ao convidar, a pessoa recebe o convite por
-- WhatsApp, chat interno, push e e-mail (melhor esforço — o que estiver
-- configurado), com um link pra aceitar ou recusar sem precisar logar
-- (mesma receita de token opaco dos portais de Contrato/Orçamento). Aceitar
-- ou recusar também pode ser feito de dentro do próprio sistema, se a
-- pessoa já estiver logada. Cada convidado tem seu PRÓPRIO status — decisão
-- confirmada com o usuário: a mudança visual (convite pendente → aceito) é
-- por pessoa, nunca depende dos outros convidados aceitarem também.
PRAGMA foreign_keys = ON;

CREATE TABLE agenda_participantes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id               INTEGER NOT NULL REFERENCES agenda_eventos(id) ON DELETE CASCADE,
    usuario_id              INTEGER NOT NULL REFERENCES usuarios(id),
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','aceito','recusado')),
    motivo_recusa           TEXT,
    token_convite           TEXT NOT NULL UNIQUE,
    convidado_por           INTEGER NOT NULL REFERENCES usuarios(id),
    convidado_em            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    respondido_em           TEXT,
    UNIQUE(evento_id, usuario_id)
);
