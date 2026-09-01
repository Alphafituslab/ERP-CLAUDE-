-- Alphafitus OS — Fase 125 (Importação Ema: lançamento avulso de conta a
-- receber, sem pedido de venda)
--
-- `contas_receber.pedido_venda_id` nascia NOT NULL UNIQUE (Fase 6) porque,
-- até aqui, toda conta a receber vinha de um Pedido de Venda confirmado —
-- nunca existiu um jeito de lançar uma conta a receber "avulsa", diferente
-- de `contas_pagar` (que desde a Fase 41 já permite lançamento manual via
-- `POST /financeiro/contas-pagar`, sem exigir um Pedido de Compra).
--
-- A importação do backup do Ema trouxe ~316 títulos a receber em aberto
-- (saldo de abertura de clientes antigos) que não têm — e nunca vão ter —
-- um Pedido de Venda real do Alphafitus por trás: forçá-los pelo fluxo
-- normal de confirmação de pedido reservaria estoque de verdade (via FEFO,
-- Fase 4) contra um pedido fictício, o que é errado. A solução correta é
-- dar a `contas_receber` a MESMA flexibilidade que `contas_pagar` já tem:
-- `pedido_venda_id` agora é OPCIONAL. Nenhum pedido de venda existente é
-- afetado — quem sempre veio de um pedido continua exatamente igual.
--
-- SQLite não permite ALTER de NOT NULL diretamente, por isso a tabela é
-- recriada (mesmo padrão da Fase 115 para memorial_catalogo_itens).
PRAGMA foreign_keys = OFF;

CREATE TABLE contas_receber_novo (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    pedido_venda_id         INTEGER UNIQUE REFERENCES pedidos_venda(id),
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
    cancelado_por           INTEGER REFERENCES usuarios(id),
    empresa_id              INTEGER,
    descricao               TEXT,
    codigo_legado_ema       TEXT
);

INSERT INTO contas_receber_novo (id, numero, pedido_venda_id, cliente_id, valor_total, vencimento,
       status, motivo_cancelamento, criado_em, criado_por, cancelado_em, cancelado_por, empresa_id,
       codigo_legado_ema)
    SELECT id, numero, pedido_venda_id, cliente_id, valor_total, vencimento,
           status, motivo_cancelamento, criado_em, criado_por, cancelado_em, cancelado_por, empresa_id,
           codigo_legado_ema
    FROM contas_receber;

DROP TABLE contas_receber;
ALTER TABLE contas_receber_novo RENAME TO contas_receber;

CREATE INDEX idx_contas_receber_cliente ON contas_receber(cliente_id);
CREATE INDEX idx_contas_receber_status ON contas_receber(status);
CREATE INDEX idx_contas_receber_vencimento ON contas_receber(vencimento);
CREATE UNIQUE INDEX idx_contas_receber_legado_ema ON contas_receber(codigo_legado_ema) WHERE codigo_legado_ema IS NOT NULL;

PRAGMA foreign_keys = ON;
