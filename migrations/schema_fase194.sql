-- Alphafitus OS — Fase 194 (Agenda: e-mail próprio pro chat interno)
--
-- Pedido do usuário: o chat interno (Whatts Inbox) é um sistema SEPARADO
-- com sua própria conta por colaborador — o e-mail de LOGIN do ERP nem
-- sempre é o mesmo cadastrado lá. Em vez de assumir que são iguais (o que
-- já funcionava por coincidência pro Administrador, mas quebraria pra
-- qualquer usuário cujo e-mail no Whatts seja diferente), o cadastro de
-- Usuário ganha um campo PRÓPRIO e opcional — só usado pra endereçar o
-- lembrete da Agenda no chat interno. Vazio = usa o e-mail de login do
-- ERP (comportamento de hoje, mantido como padrão).
PRAGMA foreign_keys = ON;

ALTER TABLE usuarios ADD COLUMN email_chat_interno TEXT;
