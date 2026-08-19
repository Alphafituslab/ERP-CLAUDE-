-- Fase 41 — DRE Completo: Despesas Operacionais e Impostos sobre Vendas
--
-- A Fase 20 entregou o primeiro DRE (Demonstrativo de Resultado), mas
-- deliberadamente simplificado: Receita Bruta − CMV = Lucro Bruto, parando
-- exatamente aí. Duas peças ficavam de fora, documentadas desde então em
-- "O que ainda falta": despesas operacionais (aluguel, salários
-- administrativos, marketing, contas de consumo — tudo que não é custo
-- direto de produção/matéria-prima) e impostos sobre a venda. Esta fase
-- entrega as duas, chegando a Lucro Líquido de verdade.
--
-- ============================================================
-- DESPESAS OPERACIONAIS — reaproveitando `contas_pagar`, não uma tabela
-- nova
-- ============================================================
-- Uma despesa operacional (aluguel, telefonia, salário administrativo
-- etc.) é, financeiramente, exatamente igual a uma conta a pagar comum:
-- tem um beneficiário (cadastrado como "fornecedor" — o mesmo cadastro já
-- serve para uma imobiliária, uma operadora de telefonia ou uma folha de
-- pagamento terceirizada, sem forçar ninguém a inventar um cadastro de
-- "fornecedor" fictício), um valor, um vencimento, e o mesmo ciclo de
-- baixa/estorno/cancelamento já construído desde a Fase 6. A ÚNICA coisa
-- que faltava era distinguir, na hora de montar o DRE, "isto foi uma
-- compra de insumo (já embutida no custo do produto, via Custeio/CMV)"
-- de "isto foi uma despesa operacional (nunca deveria contar dentro do
-- CMV, senão o custo do produto ficaria inflado por engano)".
--
-- `categoria` resolve isso com uma coluna nova, DEFAULT 'compra' — todo
-- lançamento já existente antes desta fase continua classificado como
-- 'compra' automaticamente, sem exigir nenhuma migração de dados manual
-- e sem mudar nenhum número já calculado em instalações antigas.
ALTER TABLE contas_pagar
    ADD COLUMN categoria TEXT NOT NULL DEFAULT 'compra'
        CHECK (categoria IN ('compra', 'despesa_operacional'));

-- ============================================================
-- IMPOSTOS SOBRE VENDAS — mesma linha única de configuração da Fase 33
-- ============================================================
-- Um percentual único aplicado sobre a Receita Bruta do período (ex.:
-- Simples Nacional simplificado numa alíquota efetiva única) — uma
-- simplificação deliberada: um regime tributário real brasileiro
-- (Simples/Lucro Presumido/Lucro Real, com PIS/COFINS/ICMS/ISS calculados
-- separadamente, cada um com sua própria base e alíquota) é
-- significativamente mais complexo do que um único percentual sobre a
-- receita — documentado no README como limitação conhecida desta fase.
-- `percentual_imposto_venda = 0` (o padrão) preserva o comportamento
-- atual do DRE para quem não configurar nada.
ALTER TABLE configuracoes_financeiro
    ADD COLUMN percentual_imposto_venda REAL NOT NULL DEFAULT 0
        CHECK (percentual_imposto_venda >= 0 AND percentual_imposto_venda <= 100);
