-- Alphafitus OS — Fase 196 (Agenda: mensagem de lembrete personalizável)
--
-- Pedido do usuário: poder escrever a própria mensagem que vai no
-- lembrete (chat interno/WhatsApp/push/tela), em vez de depender só do
-- texto automático (título + data + local + descrição). Vazio continua
-- usando o texto automático de sempre — isso é um EXTRA, não substitui
-- nada que já funcionava.
PRAGMA foreign_keys = ON;

ALTER TABLE agenda_eventos ADD COLUMN lembrete_mensagem_custom TEXT;
