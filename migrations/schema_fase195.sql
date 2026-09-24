-- Alphafitus OS — Fase 195 (Agenda: alerta bloqueante na tela)
--
-- Pedido do usuário: quando chegar a hora do lembrete (ex.: 4h antes),
-- quem marcou o compromisso vê um alerta NA TELA que não some sozinho —
-- só fecha quando a pessoa clicar em "Ciente". Reaproveita a mesma tabela
-- `agenda_lembretes_enviados` que já existia pros outros 3 canais
-- (chat/whatsapp/push), só que o novo canal 'tela' é marcado pelo
-- NAVEGADOR (quando a pessoa fecha o alerta), não pelo agendador em
-- background — SQLite não deixa alterar um CHECK existente, então a
-- tabela precisa ser recriada com o canal novo permitido.
PRAGMA foreign_keys = ON;

CREATE TABLE agenda_lembretes_enviados_novo (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id       INTEGER NOT NULL REFERENCES agenda_eventos(id) ON DELETE CASCADE,
    canal           TEXT NOT NULL CHECK (canal IN ('chat','whatsapp','push','tela')),
    repeticao_num   INTEGER NOT NULL,
    enviado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (evento_id, canal, repeticao_num)
);

INSERT INTO agenda_lembretes_enviados_novo (id, evento_id, canal, repeticao_num, enviado_em)
SELECT id, evento_id, canal, repeticao_num, enviado_em FROM agenda_lembretes_enviados;

DROP TABLE agenda_lembretes_enviados;
ALTER TABLE agenda_lembretes_enviados_novo RENAME TO agenda_lembretes_enviados;
