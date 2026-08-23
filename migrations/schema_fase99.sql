-- Alphafitus OS — Fase 99 (Tabelas de Preço + pré-preenchimento no Pedido de Venda)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário: poder ter uma ou mais tabelas de preço, cada cliente associado a UMA
-- delas, e o preço do item já vir pré-preenchido ao montar um pedido de venda de acordo com a
-- tabela do cliente selecionado. Antes desta fase não existia NENHUM preço de venda padrão em
-- lugar nenhum do sistema — só o valor digitado à mão em cada linha de pedido
-- (`pedido_venda_itens.preco_unitario`, Fase 6). Essa continua sendo a fonte de verdade do que
-- foi de fato vendido; a tabela de preço aqui é só uma SUGESTÃO pré-preenchida na hora de
-- montar o pedido — a pessoa ainda pode editar o valor livremente antes de confirmar.
--
-- `clientes.tabela_preco_id` é OPCIONAL (nullable, sem valor padrão): um cliente sem tabela
-- associada continua funcionando exatamente como antes — preço 100% manual. Um item sem preço
-- cadastrado na tabela do cliente também cai no mesmo comportamento manual, item por item
-- (decisão confirmada com o usuário: "não trava o pedido").
--
-- `tabelas_preco_itens` tem UNIQUE(tabela_preco_id, item_id) — um preço por item por tabela;
-- corrigir um preço é um UPDATE nessa linha (não é um ledger histórico como
-- `verbas_comerciais_lancamentos`/`pedido_venda_reservas` — aqui é só "o preço vigente agora
-- nesta tabela", sem necessidade de guardar todo histórico de reajuste).

PRAGMA foreign_keys = ON;

CREATE TABLE tabelas_preco (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por  INTEGER REFERENCES usuarios(id)
);

CREATE TABLE tabelas_preco_itens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tabela_preco_id INTEGER NOT NULL REFERENCES tabelas_preco(id),
    item_id         INTEGER NOT NULL REFERENCES itens(id),
    preco           REAL NOT NULL CHECK (preco >= 0),
    atualizado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por  INTEGER REFERENCES usuarios(id),
    UNIQUE (tabela_preco_id, item_id)
);
CREATE INDEX idx_tabelas_preco_itens_tabela ON tabelas_preco_itens(tabela_preco_id);

ALTER TABLE clientes ADD COLUMN tabela_preco_id INTEGER REFERENCES tabelas_preco(id);
