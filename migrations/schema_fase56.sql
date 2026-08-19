-- Fase 56 — DRE: Impostos Detalhados (PIS/COFINS/ICMS/ISS)
--
-- A Fase 41 entregou o Lucro Líquido usando uma ÚNICA alíquota efetiva
-- (`percentual_imposto_venda`) aplicada sobre a Receita Bruta — uma
-- simplificação deliberada, documentada desde então em "O que ainda
-- falta": um regime tributário brasileiro real tem várias bases e
-- alíquotas diferentes (PIS, COFINS, ICMS, ISS), cada uma com sua própria
-- regra. Esta fase entrega essa granularidade, mas de um jeito
-- deliberadamente ADITIVO — nenhuma instalação existente muda de
-- comportamento sozinha:
--
--   - `percentual_imposto_venda` (Fase 41) continua existindo, com o
--     MESMO significado de sempre (uma alíquota efetiva única/genérica) —
--     quem já configurou um valor ali continua vendo exatamente o mesmo
--     resultado no DRE, sem precisar reconfigurar nada.
--   - As 4 colunas novas abaixo são cada uma sua PRÓPRIA alíquota,
--     também aplicada sobre a Receita Bruta, e somada ao total de
--     "Impostos sobre Vendas" do DRE ao lado da alíquota genérica —
--     nunca em substituição a ela. Um cliente pode usar só a alíquota
--     genérica (comportamento de sempre), só as 4 novas, ou uma
--     combinação das duas (ex.: PIS/COFINS/ICMS/ISS detalhados + uma
--     alíquota genérica residual para outro tributo não modelado
--     nominalmente) — o DRE simplesmente soma tudo que estiver
--     configurado com valor maior que zero.
--
-- Todos os quatro têm DEFAULT 0 (igual ao padrão já usado para
-- `percentual_imposto_venda` desde a Fase 41) — uma instalação que nunca
-- configurar nenhum dos quatro continua com o DRE idêntico ao de antes
-- desta fase.
ALTER TABLE configuracoes_financeiro
    ADD COLUMN percentual_pis REAL NOT NULL DEFAULT 0
        CHECK (percentual_pis >= 0 AND percentual_pis <= 100);

ALTER TABLE configuracoes_financeiro
    ADD COLUMN percentual_cofins REAL NOT NULL DEFAULT 0
        CHECK (percentual_cofins >= 0 AND percentual_cofins <= 100);

ALTER TABLE configuracoes_financeiro
    ADD COLUMN percentual_icms REAL NOT NULL DEFAULT 0
        CHECK (percentual_icms >= 0 AND percentual_icms <= 100);

ALTER TABLE configuracoes_financeiro
    ADD COLUMN percentual_iss REAL NOT NULL DEFAULT 0
        CHECK (percentual_iss >= 0 AND percentual_iss <= 100);
