-- Alphafitus OS — Fase 132 (Pedidos de Venda: canal de origem + vendedor
-- visível na lista — base pra amarrar comissão à venda)
--
-- Pedido do usuário (2026-09-01): "consigo ver todos os pedidos e me dizer
-- de onde veio, do portal, do app, qual vendedor fez a venda. Assim já
-- amarra comissão dele ao cliente." Prioridade confirmada: esta é a
-- PRIMEIRA das 4 frentes pedidas (a de comissão do televendas e o alerta
-- de inatividade por cliente vêm depois, em cima desta base).
--
-- `vendedor_id` já existia desde a Fase 36 (App de Vendas), mas só era
-- preenchido por aquele canal — pedido lançado manualmente em Comercial
-- nunca perguntava quem era o vendedor responsável. `canal_origem` é
-- novo: hoje só existem DOIS pontos reais de criação de pedido no sistema
-- (conferido em app/routes/comercial.py e app/routes/vendas_app.py) — o
-- que o usuário chama de "portal" é o lançamento manual em Comercial
-- (inclui "Lançar & Faturar"), e "app" é o App de Vendas de campo.
ALTER TABLE pedidos_venda ADD COLUMN canal_origem TEXT CHECK (canal_origem IN ('comercial', 'app_vendas')) DEFAULT 'comercial';

-- Backfill dos pedidos já existentes: até esta fase, SÓ o App de Vendas
-- preenchia vendedor_id na criação (Fase 36) — o lançamento manual em
-- Comercial nunca tinha essa coluna no INSERT. Então qualquer pedido já
-- existente com vendedor_id preenchido só pode ter vindo de lá — não é
-- suposição, é o único caminho de código que já existiu até aqui.
UPDATE pedidos_venda SET canal_origem = 'app_vendas' WHERE vendedor_id IS NOT NULL;
