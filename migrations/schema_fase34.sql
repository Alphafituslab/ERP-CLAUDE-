-- Fase 34 — Alçada por VALOR Monetário do Ajuste de Contagem, além do
-- Percentual de Divergência
--
-- A Fase 21 (com o percentual tornado configurável pela Fase 32) só
-- olha para o PERCENTUAL de divergência de um item de contagem em
-- relação ao saldo que o sistema tinha no início. Um item de baixo
-- valor com 90% de divergência dispara a segunda aprovação; um item
-- caríssimo com só 5% de divergência não dispara — mesmo que o valor
-- financeiro do ajuste seja bem maior. Esta fase adiciona um SEGUNDO
-- gatilho, independente do percentual: se o valor financeiro do ajuste
-- (diferença de quantidade × custo unitário do lote, mesma lógica de
-- custeio já usada no CMV do DRE da Fase 20) ultrapassar um limiar em
-- R$, o ajuste também exige segunda aprovação.
--
-- `limiar_valor_ajuste_divergencia_grande = 0` (o padrão) desliga esse
-- segundo gatilho por completo — só o percentual (comportamento de
-- sempre desde a Fase 21) decide, para não mudar nada em quem já usa o
-- sistema sem configurar isso. Vive na MESMA linha única de
-- `configuracoes_estoque` (Fase 32) e é editável pelo mesmo formulário
-- "Configurar limiar", com a mesma permissão
-- `estoque.configurar_alcada_divergencia` — é a mesma decisão de
-- controle interno, só que num segundo campo.
ALTER TABLE configuracoes_estoque
    ADD COLUMN limiar_valor_ajuste_divergencia_grande REAL NOT NULL DEFAULT 0
        CHECK (limiar_valor_ajuste_divergencia_grande >= 0);
