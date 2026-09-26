-- Alphafitus OS — Fase 225 (Notificações clicáveis: abrir o item de onde o aviso veio)
--
-- Pedido do usuário: "eu não consigo abrir e ver o que é — se for orçamento,
-- poder ver o orçamento e aprovar ou não". A notificação até então era só
-- texto — sem nenhum jeito de saber PRA ONDE ir. `referencia_tipo`/
-- `referencia_id` são genéricos de propósito (não só "orcamento_id") pra
-- qualquer aviso futuro (solicitação de material, etc.) poder linkar pro
-- próprio registro sem precisar de outra coluna nova — o frontend decide
-- pra onde navegar com base no `referencia_tipo`. Ambos NULLABLE: toda
-- notificação já existente no sistema (dezenas de lugares que já chamam
-- `notificacoes_service.criar` sem essa informação) continua funcionando
-- exatamente igual, só sem link — nada quebra por não ter sido atualizado.
PRAGMA foreign_keys = ON;

ALTER TABLE notificacoes ADD COLUMN referencia_tipo TEXT;
ALTER TABLE notificacoes ADD COLUMN referencia_id INTEGER;
