-- ============================================================
-- FASE 57 — MRP: Lead Time de Compra do Fornecedor
-- ============================================================
-- A Fase 39 (MRP) já dizia QUANTO falta comprar de cada item, e a Fase 54
-- (Sugestão Automática de Compra) já dizia DE QUAL fornecedor homologado
-- — mas nenhuma das duas dizia ATÉ QUANDO comprar, porque o cadastro de
-- fornecedor nunca guardou nenhum prazo de entrega. Esta fase fecha essa
-- lacuna documentada desde a Fase 39 ("O que ainda falta") com um único
-- campo novo, OPCIONAL (`NULL` por padrão — significa "prazo de entrega
-- não informado"), preservando 100% o comportamento de antes: um
-- fornecedor sem lead time configurado continua aparecendo no MRP e nas
-- sugestões de compra exatamente como antes desta fase, só sem nenhuma
-- data sugerida de compra calculada para ele (não inventamos um prazo
-- que o usuário nunca informou).
ALTER TABLE fornecedores ADD COLUMN lead_time_dias INTEGER
    CHECK (lead_time_dias IS NULL OR lead_time_dias >= 0);

-- O MRP (`_calcular_mrp` em app/routes/aps.py) passa a calcular, quando
-- possível, uma "data limite de compra" para cada item em falta: a data
-- de início planejado da ordem de produção mais próxima que precisa
-- daquele item (via `ordem_producao_agendamentos`, Fase 25/28) MENOS o
-- lead_time_dias do fornecedor sugerido (o mesmo primeiro fornecedor
-- homologado já usado pela Fase 54). Sem uma ordem agendada que precise
-- do item, ou sem lead time configurado no fornecedor sugerido, o cálculo
-- simplesmente não é feito (fica `null`) — nunca inventamos uma data a
-- partir de informação que não existe.
--
-- Esta coluna nova em `sugestoes_compra_mrp` congela essa data no
-- instante em que "Gerar sugestões de compra" é clicado — mesmo
-- princípio de snapshot já usado em `ordens_relacionadas` na própria
-- tabela desde a Fase 54: se o lead time do fornecedor ou o agendamento
-- da ordem mudarem depois, uma sugestão pendente já gerada NÃO recalcula
-- sozinha; um novo ciclo de "Gerar sugestões" reflete o estado atual.
ALTER TABLE sugestoes_compra_mrp ADD COLUMN data_limite_compra TEXT;
