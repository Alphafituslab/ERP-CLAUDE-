-- ============================================================
-- FASE 58 — Pedido de Compra formal
-- ============================================================
-- A Fase 54 (Sugestão Automática de Compra) deliberadamente NÃO criava
-- nenhum documento de compra de verdade — só um item de trabalho para
-- Compras (`sugestoes_compra_mrp`), sem preço nem fornecedor
-- compromissado. A Fase 57 acrescentou "até quando comprar" (lead time).
-- Mas depois que Compras decide atender uma sugestão, o sistema ainda não
-- tinha NENHUM documento formal amarrando "o que foi pedido, a quem, e o
-- que já chegou" — o recebimento de lote (Fase 2) sempre teve uma coluna
-- `pedido_compra` (ver schema.sql/schema_fase2.sql), mas é só um campo de
-- TEXTO LIVRE (o número que a pessoa digitou na hora de receber), sem
-- nenhuma tabela por trás, sem itens, sem quantidade pedida vs. recebida,
-- sem status. Esta fase fecha esse ciclo com um documento de verdade.
--
-- Decisão de escopo deliberada (mesmo espírito das fases anteriores de
-- Compras/MRP): um Pedido de Compra aqui é o COMPROMISSO com o fornecedor
-- (itens, quantidade, fornecedor, preço unitário estimado/negociado) —
-- ainda NÃO é uma obrigação financeira (isso continua sendo
-- `contas_pagar`, Fase 6, lançada separadamente por Compras/Financeiro
-- quando a nota fiscal chega) nem um lote de estoque (isso continua sendo
-- `lotes`, Fase 2, criado no recebimento). As três entidades ficam
-- deliberadamente separadas, cada uma representando um momento diferente
-- do ciclo de compra — mesma filosofia de separação já usada entre
-- `sugestoes_compra_mrp` e `contas_pagar` desde a Fase 54.
--
-- Ciclo de vida do pedido: rascunho -> enviado -> parcialmente_recebido
-- -> recebido, com "cancelado" possível a partir de rascunho ou enviado
-- (nunca depois de qualquer recebimento parcial — ver validação em
-- app/routes/compras.py). Itens ficam numa tabela própria
-- (`itens_pedido_compra`), cada um rastreando quanto já foi recebido
-- contra ele — de propósito UM ÚNICO LINK a uma sugestão do MRP por
-- item (não por pedido inteiro), porque um pedido pode agrupar itens que
-- vieram de sugestões diferentes (ou nenhuma, quando criado manualmente).
CREATE TABLE pedidos_compra (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    numero              TEXT NOT NULL UNIQUE,
    fornecedor_id       INTEGER NOT NULL REFERENCES fornecedores(id),
    status              TEXT NOT NULL DEFAULT 'rascunho' CHECK (status IN (
                            'rascunho', 'enviado', 'parcialmente_recebido', 'recebido', 'cancelado'
                        )),
    observacoes         TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER REFERENCES usuarios(id),
    enviado_em          TEXT,
    enviado_por         INTEGER REFERENCES usuarios(id),
    concluido_em        TEXT,
    cancelado_em        TEXT,
    cancelado_por       INTEGER REFERENCES usuarios(id),
    motivo_cancelamento TEXT
);

CREATE INDEX idx_pedidos_compra_fornecedor ON pedidos_compra(fornecedor_id);
CREATE INDEX idx_pedidos_compra_status ON pedidos_compra(status);

-- UNIQUE(pedido_compra_id, item_id): de propósito um item aparece no
-- MÁXIMO uma vez por pedido — se Compras precisar de mais do item, edita
-- a quantidade desta linha (via novo pedido, já que este MVP não tem
-- edição de item depois de criado — ver decisão de escopo em
-- app/routes/compras.py) em vez de duplicar a linha, o que deixaria
-- ambíguo contra qual linha um recebimento deveria abater.
CREATE TABLE itens_pedido_compra (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_compra_id       INTEGER NOT NULL REFERENCES pedidos_compra(id),
    item_id                INTEGER NOT NULL REFERENCES itens(id),
    quantidade_pedida      REAL NOT NULL CHECK (quantidade_pedida > 0),
    unidade                TEXT NOT NULL,
    -- Preço unitário estimado/negociado — OPCIONAL: uma sugestão do MRP
    -- (Fase 54) nunca tem preço (é só previsão de quantidade), então um
    -- pedido gerado a partir dela nasce sem preço; Compras pode informar
    -- depois de negociar, mas isso não é feito por este MVP (só na
    -- criação). Não alimenta custeio nem financeiro automaticamente —
    -- é só um valor de referência para quem está comprando.
    preco_unitario         REAL CHECK (preco_unitario IS NULL OR preco_unitario >= 0),
    quantidade_recebida    REAL NOT NULL DEFAULT 0 CHECK (quantidade_recebida >= 0),
    -- Link opcional para a sugestão do MRP que originou esta linha (ver
    -- nota acima) — mesmo princípio de rastreabilidade de origem já usado
    -- em `sugestoes_compra_mrp.conta_pagar_id` desde a Fase 54, só que na
    -- direção contrária (aqui é o PEDIDO apontando para a sugestão que o
    -- originou, não a sugestão apontando para o que a atendeu).
    sugestao_compra_mrp_id INTEGER REFERENCES sugestoes_compra_mrp(id),
    UNIQUE (pedido_compra_id, item_id)
);

CREATE INDEX idx_itens_pedido_compra_pedido ON itens_pedido_compra(pedido_compra_id);
CREATE INDEX idx_itens_pedido_compra_item ON itens_pedido_compra(item_id);

-- Quando o recebimento de lote (Fase 2, POST /api/v1/lotes/recebimento)
-- informa `pedido_compra_id`, o lote passa a contar contra a linha
-- correspondente em `itens_pedido_compra` (abate `quantidade_recebida`,
-- recalcula o status do pedido). Deliberadamente uma coluna NOVA — a
-- coluna `pedido_compra` (texto livre, sem tabela por trás) que já
-- existia desde a Fase 2 continua exatamente como estava, sem nenhuma
-- mudança de comportamento para quem não usa o Pedido de Compra formal;
-- as duas podem, inclusive, ser preenchidas juntas (uma é o vínculo
-- estruturado novo, a outra é só o texto livre de sempre).
ALTER TABLE lotes ADD COLUMN pedido_compra_id INTEGER REFERENCES pedidos_compra(id);

-- Link, na sugestão do MRP, para o Pedido de Compra formal gerado a
-- partir dela — mesmo padrão de `conta_pagar_id` (Fase 54): gerar um
-- pedido a partir de uma sugestão pendente PASSA A SER, a partir desta
-- fase, uma das formas de "atender" a sugestão (a outra, `POST
-- .../atender` linkando só um `conta_pagar_id`, continua existindo sem
-- nenhuma mudança, para compras fechadas fora deste fluxo novo).
ALTER TABLE sugestoes_compra_mrp ADD COLUMN pedido_compra_id INTEGER REFERENCES pedidos_compra(id);
