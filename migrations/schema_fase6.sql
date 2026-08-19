-- Alphafitus OS — Fase 6 (Financeiro básico: Contas a Receber e a Pagar)
-- Aplicado DEPOIS de schema.sql, schema_fase2.sql, schema_fase3.sql,
-- schema_fase4.sql e schema_fase5.sql, nunca remove nem altera nada das
-- fases anteriores (o ALTER TABLE abaixo só ADICIONA uma coluna nova,
-- com DEFAULT, então nenhuma linha existente quebra).
-- Mesmas notas de portabilidade para PostgreSQL das fases anteriores se
-- aplicam aqui.
--
-- Esta fase fecha o ciclo financeiro em volta do que as Fases 2 e 5 já
-- fazem fisicamente:
--   - Ao EXPEDIR um pedido de venda (Fase 5), o sistema agora também gera
--     automaticamente uma conta a receber, com valor calculado a partir do
--     preço unitário de cada item do pedido (novidade desta fase — até
--     aqui pedidos não tinham preço, só quantidade).
--   - Ao receber uma nota fiscal de um fornecedor (o recebimento físico do
--     lote já existe desde a Fase 2), o setor de Compras/Financeiro lança
--     manualmente uma conta a pagar referenciando o fornecedor (e,
--     opcionalmente, o lote recebido, para rastreabilidade) — isso NÃO é
--     automático como a conta a receber, porque uma nota fiscal de compra
--     raramente corresponde 1:1 a um único lote (pode cobrir vários itens,
--     frete, impostos etc.), então lançar automaticamente seria inventar
--     um valor que o sistema não conhece.
--
-- Tanto contas a receber quanto contas a pagar seguem o MESMO princípio já
-- usado em toda a rastreabilidade do sistema (saldo de estoque na Fase 4,
-- saldo reservado na Fase 5): o status de uma conta nunca é um campo
-- guardado à parte que poderia dessincronizar — é sempre recalculado a
-- partir da soma das baixas (pagamentos/recebimentos) registradas contra
-- ela, e as baixas em si são um ledger append-only, igual a
-- movimentacoes_estoque e pedido_venda_reservas.

PRAGMA foreign_keys = ON;

-- ============================================================
-- PREÇO NOS ITENS DE PEDIDO DE VENDA
-- ============================================================
-- Até a Fase 5, um pedido de venda só tinha quantidade — não havia
-- necessidade de preço porque nada financeiro dependia dele ainda. Agora
-- que a conta a receber precisa de um valor, todo item de pedido passa a
-- exigir um preço unitário (validado em código: precisa ser > 0 para
-- confirmar/adicionar item a partir desta fase). O DEFAULT 0 aqui é só
-- para não quebrar a migração em cima de linhas que já existirem num
-- banco de uma instalação anterior — na prática, nenhuma linha nova é
-- criada com 0 (a rota valida isso).
ALTER TABLE pedido_venda_itens ADD COLUMN preco_unitario REAL NOT NULL DEFAULT 0 CHECK (preco_unitario >= 0);

-- ============================================================
-- CONTAS A RECEBER
-- ============================================================
-- Uma conta por pedido de venda expedido (relação 1:1 — ver
-- comercial.py:expedir). valor_total é a soma congelada de
-- quantidade*preco_unitario dos itens no momento da expedição: mesmo que
-- o preço de um item mude depois na tela de Itens, o valor já faturado
-- não muda retroativamente (mesma filosofia de "composição congelada" já
-- usada para pedido_venda_itens e formula_itens).
CREATE TABLE contas_receber (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    pedido_venda_id         INTEGER NOT NULL UNIQUE REFERENCES pedidos_venda(id),
    cliente_id              INTEGER NOT NULL REFERENCES clientes(id),
    valor_total             REAL NOT NULL CHECK (valor_total > 0),
    vencimento              TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN (
                                'aberto', 'pago_parcial', 'pago', 'cancelado'
                            )),
    motivo_cancelamento     TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    cancelado_em            TEXT,
    cancelado_por           INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_contas_receber_cliente ON contas_receber(cliente_id);
CREATE INDEX idx_contas_receber_status ON contas_receber(status);
CREATE INDEX idx_contas_receber_vencimento ON contas_receber(vencimento);

-- Ledger append-only de recebimentos (baixas) contra uma conta a receber.
-- O saldo em aberto de uma conta é sempre `valor_total - SUM(baixas)`,
-- nunca um campo separado — o status ('aberto'/'pago_parcial'/'pago') é
-- só uma etiqueta derivada desse cálculo, recalculada em cada baixa.
CREATE TABLE contas_receber_baixas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_receber_id    INTEGER NOT NULL REFERENCES contas_receber(id),
    valor               REAL NOT NULL CHECK (valor > 0),
    forma_pagamento     TEXT NOT NULL CHECK (forma_pagamento IN (
                            'dinheiro', 'pix', 'boleto', 'cartao', 'transferencia'
                        )),
    data_pagamento      TEXT NOT NULL,
    observacao          TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_contas_receber_baixas_conta ON contas_receber_baixas(conta_receber_id);

CREATE TRIGGER cr_baixas_bloqueia_update
BEFORE UPDATE ON contas_receber_baixas
BEGIN
    SELECT RAISE(ABORT, 'contas_receber_baixas é append-only: UPDATE não é permitido (cancele/estorne com um novo lançamento se necessário)');
END;

CREATE TRIGGER cr_baixas_bloqueia_delete
BEFORE DELETE ON contas_receber_baixas
BEGIN
    SELECT RAISE(ABORT, 'contas_receber_baixas é append-only: DELETE não é permitido (cancele/estorne com um novo lançamento se necessário)');
END;

-- ============================================================
-- CONTAS A PAGAR
-- ============================================================
-- Diferente da conta a receber, é lançada MANUALMENTE (ver nota no topo
-- do arquivo) — por isso tem uma descrição livre em vez de derivar tudo
-- de uma tabela de origem. O vínculo com lote_id é opcional e só para
-- rastreabilidade (qual recebimento gerou esta nota fiscal).
CREATE TABLE contas_pagar (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    fornecedor_id           INTEGER NOT NULL REFERENCES fornecedores(id),
    lote_id                 INTEGER REFERENCES lotes(id),
    descricao               TEXT NOT NULL,
    valor_total             REAL NOT NULL CHECK (valor_total > 0),
    vencimento              TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN (
                                'aberto', 'pago_parcial', 'pago', 'cancelado'
                            )),
    motivo_cancelamento     TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    cancelado_em            TEXT,
    cancelado_por           INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_contas_pagar_fornecedor ON contas_pagar(fornecedor_id);
CREATE INDEX idx_contas_pagar_status ON contas_pagar(status);
CREATE INDEX idx_contas_pagar_vencimento ON contas_pagar(vencimento);

CREATE TABLE contas_pagar_baixas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_pagar_id      INTEGER NOT NULL REFERENCES contas_pagar(id),
    valor               REAL NOT NULL CHECK (valor > 0),
    forma_pagamento     TEXT NOT NULL CHECK (forma_pagamento IN (
                            'dinheiro', 'pix', 'boleto', 'cartao', 'transferencia'
                        )),
    data_pagamento      TEXT NOT NULL,
    observacao          TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_contas_pagar_baixas_conta ON contas_pagar_baixas(conta_pagar_id);

CREATE TRIGGER cp_baixas_bloqueia_update
BEFORE UPDATE ON contas_pagar_baixas
BEGIN
    SELECT RAISE(ABORT, 'contas_pagar_baixas é append-only: UPDATE não é permitido (cancele/estorne com um novo lançamento se necessário)');
END;

CREATE TRIGGER cp_baixas_bloqueia_delete
BEFORE DELETE ON contas_pagar_baixas
BEGIN
    SELECT RAISE(ABORT, 'contas_pagar_baixas é append-only: DELETE não é permitido (cancele/estorne com um novo lançamento se necessário)');
END;
