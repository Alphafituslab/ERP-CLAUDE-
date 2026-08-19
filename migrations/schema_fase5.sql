-- Alphafitus OS — Fase 5 (Comercial / CRM básico + Pedidos de Venda)
-- Aplicado DEPOIS de schema.sql, schema_fase2.sql, schema_fase3.sql e
-- schema_fase4.sql, nunca remove nem altera nada das fases anteriores.
-- Mesmas notas de portabilidade para PostgreSQL das fases anteriores se
-- aplicam aqui.
--
-- Esta fase liga o Comercial ao Estoque físico da Fase 4: confirmar um
-- pedido de venda RESERVA estoque de verdade (alocação FEFO — primeiro a
-- vencer, primeiro a sair — contra o saldo já endereçado em posições),
-- impedindo que dois pedidos confirmados concorram pelo mesmo material
-- sem que o sistema perceba. Expedir o pedido converte a reserva em uma
-- saída real no livro-razão de movimentacoes_estoque da Fase 4 (mesma
-- tabela, mesmo trigger de imutabilidade — nenhuma tabela nova de
-- movimentação física é necessária).

PRAGMA foreign_keys = ON;

-- ============================================================
-- CLIENTES
-- ============================================================
CREATE TABLE clientes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social    TEXT NOT NULL,
    nome_fantasia   TEXT,
    cnpj            TEXT NOT NULL UNIQUE,
    endereco        TEXT,
    status          TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER REFERENCES usuarios(id)
);

-- ============================================================
-- PEDIDOS DE VENDA
-- ============================================================
-- Ciclo de vida: rascunho -> confirmado -> expedido
--                rascunho -> cancelado
--                confirmado -> cancelado (libera a reserva — ver nota em
--                pedido_venda_reservas sobre como a liberação funciona
--                sem precisar apagar/editar nada)
CREATE TABLE pedidos_venda (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    cliente_id              INTEGER NOT NULL REFERENCES clientes(id),
    status                  TEXT NOT NULL DEFAULT 'rascunho' CHECK (status IN (
                                'rascunho', 'confirmado', 'expedido', 'cancelado'
                            )),
    motivo_cancelamento     TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    confirmado_em           TEXT,
    confirmado_por          INTEGER REFERENCES usuarios(id),
    expedido_em             TEXT,
    expedido_por            INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_pedidos_venda_cliente ON pedidos_venda(cliente_id);
CREATE INDEX idx_pedidos_venda_status ON pedidos_venda(status);

-- Linhas do pedido — só podem ser inseridas/removidas enquanto o pedido
-- está em 'rascunho' (garantido em código); uma vez confirmado, a
-- composição do pedido fica congelada (mesma filosofia de formula_itens
-- na Fase 3: a "receita" do pedido não muda depois de comprometida).
CREATE TABLE pedido_venda_itens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id       INTEGER NOT NULL REFERENCES pedidos_venda(id),
    item_id         INTEGER NOT NULL REFERENCES itens(id),
    quantidade      REAL NOT NULL CHECK (quantidade > 0),
    unidade         TEXT NOT NULL
);

CREATE INDEX idx_pedido_venda_itens_pedido ON pedido_venda_itens(pedido_id);

-- ============================================================
-- RESERVAS DE ESTOQUE — ledger append-only
-- ============================================================
-- Gerado automaticamente ao CONFIRMAR um pedido, por alocação FEFO contra
-- o saldo físico já endereçado em posições (Fase 4) menos o que já está
-- reservado por OUTROS pedidos ainda ativos. Uma linha por combinação
-- (lote, posição) usada para cobrir a quantidade de um item do pedido.
--
-- Comprometida: append-only, igual às demais tabelas de ledger do sistema
-- (resultados_analise_historico, ordem_producao_consumo,
-- movimentacoes_estoque) — uma reserva nunca é editada ou apagada.
--
-- "Liberar" uma reserva (ao cancelar um pedido confirmado) NÃO é uma
-- operação que apaga ou edita linha nenhuma aqui: o saldo reservado ativo
-- de um lote/posição é sempre calculado juntando esta tabela com o status
-- ATUAL do pedido pai (SUM(quantidade) WHERE pedido.status = 'confirmado').
-- Assim que o pedido muda para 'cancelado' ou 'expedido', a reserva para
-- de "contar" automaticamente, sem precisar tocar em nenhuma linha desta
-- tabela — mesmo princípio de saldo sempre recalculado, nunca guardado à
-- parte, já usado em toda a Fase 4.
CREATE TABLE pedido_venda_reservas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_item_id      INTEGER NOT NULL REFERENCES pedido_venda_itens(id),
    lote_id             INTEGER NOT NULL REFERENCES lotes(id),
    posicao_id          INTEGER NOT NULL REFERENCES posicoes_estoque(id),
    quantidade          REAL NOT NULL CHECK (quantidade > 0),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_pv_reservas_item ON pedido_venda_reservas(pedido_item_id);
CREATE INDEX idx_pv_reservas_lote_posicao ON pedido_venda_reservas(lote_id, posicao_id);

CREATE TRIGGER pv_reservas_bloqueia_update
BEFORE UPDATE ON pedido_venda_reservas
BEGIN
    SELECT RAISE(ABORT, 'pedido_venda_reservas é append-only: UPDATE não é permitido (cancele o pedido para liberar a reserva)');
END;

CREATE TRIGGER pv_reservas_bloqueia_delete
BEFORE DELETE ON pedido_venda_reservas
BEGIN
    SELECT RAISE(ABORT, 'pedido_venda_reservas é append-only: DELETE não é permitido (cancele o pedido para liberar a reserva)');
END;
