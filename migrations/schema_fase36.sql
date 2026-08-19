-- Fase 36 — App de Vendas para Vendedores: Fundação
-- (Rascunho com Reserva Temporária de Item, Verbas Comerciais e Comissão
-- do Vendedor)
--
-- Este arquivo NÃO altera o comportamento do módulo Comercial existente
-- (Fase 5/6/12) para quem já usa a tela de desktop: todo campo novo tem
-- DEFAULT que preserva o comportamento de sempre, e a lógica nova
-- (reserva temporária, verba, comissão) só se aplica a pedidos criados
-- PELO APLICATIVO de vendas — um pedido criado pela tela de Comercial de
-- sempre nunca passa por nenhuma tabela nova daqui.
--
-- ============================================================
-- QUEM VENDEU (para efeito de comissão)
-- ============================================================
-- `criado_por` já existe desde a Fase 5, mas é genérico (quem digitou o
-- pedido) — nem sempre é a mesma pessoa que deveria receber a comissão
-- (ex.: um assistente lançando em nome do vendedor). `vendedor_id` fica
-- NULL em todo pedido criado pela tela de Comercial de sempre; só o
-- aplicativo de vendas o define, no momento em que o próprio vendedor
-- inicia um rascunho.
ALTER TABLE pedidos_venda ADD COLUMN vendedor_id INTEGER REFERENCES usuarios(id);

-- ============================================================
-- VERBA COMERCIAL USADA NESTE PEDIDO
-- ============================================================
-- Quanto do saldo de verba comercial do cliente foi abatido do valor
-- deste pedido. Congelado na CONFIRMAÇÃO (não na expedição) para o
-- vendedor já saber o valor final antes de enviar o pedido ao cliente;
-- o lançamento no ledger de verbas (`verbas_comerciais_lancamentos`,
-- abaixo) só é gravado na EXPEDIÇÃO, junto com a conta a receber — se o
-- pedido for cancelado antes de expedir, nada precisa ser desfeito
-- porque nada chegou a ser lançado.
ALTER TABLE pedidos_venda ADD COLUMN verba_utilizada REAL NOT NULL DEFAULT 0 CHECK (verba_utilizada >= 0);

-- ============================================================
-- SESSÃO DE RASCUNHO DO APP DE VENDAS (reserva temporária de item)
-- ============================================================
-- Existe uma linha aqui para cada pedido em rascunho CRIADO PELO
-- APLICATIVO de vendas (nunca para um rascunho criado pela tela de
-- Comercial). Enquanto essa linha existir com `encerrada_em IS NULL` e
-- `expira_em` no futuro, a quantidade de cada item do rascunho conta
-- como "comprometida" no cálculo de saldo disponível mostrado a OUTROS
-- vendedores (ver `_comprometido_em_rascunhos_abertos` em
-- app/routes/vendas_app.py) — NUNCA uma reserva de estoque real: essa
-- continua só acontecendo em `pedido_venda_reservas`, na confirmação,
-- exatamente como desde a Fase 5. É por isso que "selecionar um item"
-- pode reservá-lo de fato para o vendedor sem depender de nenhuma
-- alteração na lógica de estoque físico já existente.
--
-- Encerra de três jeitos (`motivo_encerramento`):
--   'enviado'            — o vendedor confirmou o pedido (a reserva de
--                          estoque real já existe; a sessão não precisa
--                          mais existir, mas a linha fica de histórico)
--   'fechado_pelo_usuario' — o vendedor descartou o rascunho explicitamente
--                          (ex.: fechou o app) — o pedido é cancelado
--   'expirado'           — ninguém tocou no rascunho por
--                          `minutos_expiracao_rascunho` (config abaixo) —
--                          verificado de forma oportunista (não um cron
--                          de sistema de verdade, mesmo espírito da Fase
--                          35) sempre que qualquer rota do app de vendas
--                          é chamada — o pedido também é cancelado
CREATE TABLE sessoes_rascunho_app_vendas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_venda_id      INTEGER NOT NULL UNIQUE REFERENCES pedidos_venda(id),
    vendedor_id          INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expira_em            TEXT NOT NULL,
    encerrada_em         TEXT,
    motivo_encerramento  TEXT CHECK (
                             motivo_encerramento IS NULL OR
                             motivo_encerramento IN ('enviado', 'fechado_pelo_usuario', 'expirado')
                         )
);
CREATE INDEX idx_sessoes_rascunho_vendedor ON sessoes_rascunho_app_vendas(vendedor_id);
CREATE INDEX idx_sessoes_rascunho_ativa ON sessoes_rascunho_app_vendas(encerrada_em, expira_em);

-- ============================================================
-- VERBAS COMERCIAIS (crédito do CLIENTE, gerado por venda e usável em
-- vendas futuras)
-- ============================================================
-- Ledger append-only — mesmo princípio já usado em TODO ledger deste
-- sistema (contas_receber_baixas, pedido_venda_reservas,
-- movimentacoes_estoque): nunca um saldo guardado à parte que poderia
-- dessincronizar. O saldo disponível de um cliente é sempre
-- SUM('gerada') - SUM('utilizada'), recalculado a cada consulta (ver
-- `_saldo_verba_disponivel` em app/routes/vendas_app.py).
--
-- Limitação desta fase, documentada com propósito: não existe ainda um
-- tipo de lançamento para REVERTER uma verba já gerada ou já usada (ex.:
-- devolução de mercadoria depois de expedida) — o sistema não tem hoje
-- um fluxo de devolução de pedido de venda (ver backlog do README). Se
-- isso for pedido no futuro, a forma correta de resolver, seguindo o
-- mesmo padrão de `estorno_de_id` já usado em `contas_receber_baixas`
-- desde a Fase 14, é uma nova coluna de auto-referência — não reescrever
-- nem apagar nenhum lançamento já gravado.
CREATE TABLE verbas_comerciais_lancamentos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id      INTEGER NOT NULL REFERENCES clientes(id),
    tipo            TEXT NOT NULL CHECK (tipo IN ('gerada', 'utilizada')),
    valor           REAL NOT NULL CHECK (valor > 0),
    pedido_venda_id INTEGER REFERENCES pedidos_venda(id),
    observacao      TEXT,
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER NOT NULL REFERENCES usuarios(id)
);
CREATE INDEX idx_verbas_cliente ON verbas_comerciais_lancamentos(cliente_id);

CREATE TRIGGER verbas_bloqueia_update
BEFORE UPDATE ON verbas_comerciais_lancamentos
BEGIN
    SELECT RAISE(ABORT, 'verbas_comerciais_lancamentos é append-only: UPDATE não é permitido (lance uma linha nova se precisar corrigir)');
END;

CREATE TRIGGER verbas_bloqueia_delete
BEFORE DELETE ON verbas_comerciais_lancamentos
BEGIN
    SELECT RAISE(ABORT, 'verbas_comerciais_lancamentos é append-only: DELETE não é permitido (lance uma linha nova se precisar corrigir)');
END;

-- ============================================================
-- CONFIGURAÇÃO DO MÓDULO COMERCIAL (linha única, editável pela tela)
-- ============================================================
-- Mesmo padrão de configuração em banco já usado nas Fases 32/33/34/35.
-- Todos os valores em 0 preservam o comportamento anterior a esta fase
-- (nenhuma verba é gerada, nenhuma comissão é calculada) até alguém
-- configurar um valor pela tela.
CREATE TABLE configuracoes_comercial (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    percentual_verba_gerada     REAL NOT NULL DEFAULT 0 CHECK (percentual_verba_gerada >= 0 AND percentual_verba_gerada <= 100),
    percentual_comissao_padrao  REAL NOT NULL DEFAULT 0 CHECK (percentual_comissao_padrao >= 0 AND percentual_comissao_padrao <= 100),
    minutos_expiracao_rascunho  INTEGER NOT NULL DEFAULT 240 CHECK (minutos_expiracao_rascunho > 0),
    atualizado_em               TEXT,
    atualizado_por              INTEGER REFERENCES usuarios(id)
);
INSERT INTO configuracoes_comercial (id, percentual_verba_gerada, percentual_comissao_padrao, minutos_expiracao_rascunho)
VALUES (1, 0, 0, 240);
