-- Alphafitus OS — Fase 176 (painel ao vivo: quem está online e em qual tela)
--
-- Pedido do usuário (2026-09-14): depois de identificar terminal + operador
-- na pílula do topo (Fase 175), ele pediu um passo além — saber, em tempo
-- real, o que cada terminal está fazendo agora. A tabela `terminais` (Fase
-- 111) já registra terminal+operador a cada heartbeat (60s); só faltava a
-- TELA atual. Guardamos o hash de rota cru (ex.: "#/financeiro") — o
-- rótulo amigável ("Financeiro") é resolvido no frontend a partir do mesmo
-- ITENS_MENU já usado pela busca global, sem duplicar essa lista aqui.

PRAGMA foreign_keys = ON;

ALTER TABLE terminais ADD COLUMN tela_atual TEXT;
ALTER TABLE terminais ADD COLUMN tela_atualizada_em TEXT;
