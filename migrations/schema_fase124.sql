-- Alphafitus OS — Fase 124 (Importação Ema: campos que faltavam nos
-- cadastros mestres para receber os dados reais do backup do sistema
-- anterior)
--
-- Pedido do usuário: importar o backup completo do "Ema" (ERP anterior,
-- pg_dump do Postgres, 1207 tabelas) para dentro do Alphafitus, criando
-- os poucos campos que faltam nos módulos que já existem. Esta fase cobre
-- só os campos novos usados pela importação de clientes/fornecedores/itens
-- (script scripts/importar_ema.py) — os módulos que o Ema tem e o
-- Alphafitus ainda não (CRM, Caixa/PDV, Comissão, conciliação bancária
-- CNAB) ficam para fases seguintes, dedicadas.
--
-- `codigo_legado_ema` existe em toda tabela que recebe dado importado —
-- guarda a chave primária original do Ema (ex.: 'cliforemp:74',
-- 'item:1586') só para rastreabilidade/auditoria ("de onde veio esse
-- registro") e para permitir reimportar com segurança no futuro sem
-- duplicar (o script sempre confere por este campo antes de criar).

ALTER TABLE clientes ADD COLUMN telefone TEXT;
ALTER TABLE clientes ADD COLUMN nome_contato TEXT;
ALTER TABLE clientes ADD COLUMN codigo_legado_ema TEXT;

ALTER TABLE fornecedores ADD COLUMN email TEXT;
ALTER TABLE fornecedores ADD COLUMN telefone TEXT;
ALTER TABLE fornecedores ADD COLUMN nome_contato TEXT;
ALTER TABLE fornecedores ADD COLUMN codigo_legado_ema TEXT;

-- `peso_bruto_kg`/`peso_liquido_kg`: existiam no Ema (item.pesobruto/
-- pesoliquido) e não tinham equivalente aqui — úteis para logística/
-- expedição no futuro, sem relação com nenhuma regra de negócio atual.
-- `dias_validade_padrao`: Ema guarda por item o prazo de validade padrão
-- do lote (item.diaslotevalidade) — o Alphafitus só guarda a validade
-- em cada LOTE individualmente (lotes.validade, preenchida no
-- recebimento); este campo novo é só um valor sugerido/padrão para
-- pré-preencher a tela de recebimento, nunca usado para calcular nada
-- sozinho.
ALTER TABLE itens ADD COLUMN peso_bruto_kg REAL;
ALTER TABLE itens ADD COLUMN peso_liquido_kg REAL;
ALTER TABLE itens ADD COLUMN dias_validade_padrao INTEGER;
ALTER TABLE itens ADD COLUMN codigo_legado_ema TEXT;

ALTER TABLE lotes ADD COLUMN codigo_legado_ema TEXT;

ALTER TABLE contas_pagar ADD COLUMN codigo_legado_ema TEXT;
ALTER TABLE contas_receber ADD COLUMN codigo_legado_ema TEXT;

CREATE UNIQUE INDEX idx_clientes_legado_ema ON clientes(codigo_legado_ema) WHERE codigo_legado_ema IS NOT NULL;
CREATE UNIQUE INDEX idx_fornecedores_legado_ema ON fornecedores(codigo_legado_ema) WHERE codigo_legado_ema IS NOT NULL;
CREATE UNIQUE INDEX idx_itens_legado_ema ON itens(codigo_legado_ema) WHERE codigo_legado_ema IS NOT NULL;
CREATE UNIQUE INDEX idx_lotes_legado_ema ON lotes(codigo_legado_ema) WHERE codigo_legado_ema IS NOT NULL;
CREATE UNIQUE INDEX idx_contas_pagar_legado_ema ON contas_pagar(codigo_legado_ema) WHERE codigo_legado_ema IS NOT NULL;
CREATE UNIQUE INDEX idx_contas_receber_legado_ema ON contas_receber(codigo_legado_ema) WHERE codigo_legado_ema IS NOT NULL;
