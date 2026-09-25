-- Alphafitus OS — Fase 201 (Agenda: lembrete também pros participantes que aceitaram)
--
-- Pedido do usuário (2026-09-25): o lembrete de "faltam X minutos" não pode
-- ser só do dono — quem ACEITOU o convite (interno ou externo) também
-- precisa ser avisado no dia, respeitando a MESMA configuração de
-- antecedência/repetições/intervalo que já existe no compromisso (não é um
-- agendamento separado por pessoa).
--
-- `agenda_lembretes_enviados` tinha UNIQUE(evento_id, canal, repeticao_num)
-- — sem uma coluna que identifique O DESTINATÁRIO, o envio pro dono e pra
-- cada participante concorreriam pela MESMA linha de controle (o primeiro
-- que fosse enviado "usaria" o registro e os outros seriam pulados por
-- engano, achando que já tinha sido enviado). SQLite não altera UNIQUE/CHECK
-- existente com ALTER TABLE — mesmo caminho das Fases 195/200 (reconstruir).
PRAGMA foreign_keys = OFF;

CREATE TABLE agenda_lembretes_enviados_novo (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id       INTEGER NOT NULL REFERENCES agenda_eventos(id) ON DELETE CASCADE,
    participante_id INTEGER REFERENCES agenda_participantes(id) ON DELETE CASCADE,
    canal           TEXT NOT NULL CHECK (canal IN ('chat','whatsapp','push','tela','email')),
    repeticao_num   INTEGER NOT NULL,
    enviado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (evento_id, canal, repeticao_num, participante_id)
);

INSERT INTO agenda_lembretes_enviados_novo (id, evento_id, canal, repeticao_num, enviado_em)
SELECT id, evento_id, canal, repeticao_num, enviado_em FROM agenda_lembretes_enviados;

DROP TABLE agenda_lembretes_enviados;
ALTER TABLE agenda_lembretes_enviados_novo RENAME TO agenda_lembretes_enviados;

PRAGMA foreign_keys = ON;
