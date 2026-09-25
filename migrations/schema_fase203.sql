-- Alphafitus OS — Fase 203 (Agenda: link de videochamada no compromisso)
--
-- Pedido do usuário (2026-09-25): poder colar o link de uma reunião online
-- (Google Meet ou qualquer outro) no compromisso, pra ir junto no convite —
-- WhatsApp/chat interno/push/e-mail — sem precisar mandar separado depois.
-- Gerar a chamada automaticamente via API do Google exigiria integração
-- OAuth própria (projeto no Google Cloud, tela de consentimento, tokens por
-- usuário) — fora de escopo por agora; colar o link resolve o pedido e
-- funciona com QUALQUER serviço (Meet, Zoom, Teams), não só Google.
ALTER TABLE agenda_eventos ADD COLUMN link_video TEXT;
