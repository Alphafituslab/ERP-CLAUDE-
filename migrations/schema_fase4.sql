-- Alphafitus OS — Fase 4 (Estoque / WMS básico)
-- Aplicado DEPOIS de schema.sql, schema_fase2.sql e schema_fase3.sql, nunca
-- remove nem altera nada das fases anteriores. Mesmas notas de
-- portabilidade para PostgreSQL das fases anteriores se aplicam aqui.
--
-- Fecha o elo físico da rastreabilidade: até a Fase 3 sabíamos QUE lote
-- existe e sua genealogia lógica (de que lote foi feito / em que foi
-- consumido), mas não ONDE ele está fisicamente no armazém. Esta fase
-- adiciona posições de armazenagem e um livro-razão (ledger) append-only
-- de movimentações — cada posição de cada lote é sempre recalculada a
-- partir da soma das movimentações, nunca um saldo guardado à parte que
-- poderia dessincronizar (mesmo princípio de "quantidade disponível" já
-- usado na Fase 3 para consumo de produção).

PRAGMA foreign_keys = ON;

-- ============================================================
-- POSIÇÕES DE ARMAZENAGEM
-- ============================================================
-- Sempre vinculadas a uma unidade (tipicamente do tipo 'deposito',
-- cadastrada na Fase 1) — o mesmo endereço físico ("A1-01") pode se
-- repetir em depósitos diferentes, por isso o código é único só DENTRO da
-- unidade, não globalmente.
CREATE TABLE posicoes_estoque (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    unidade_id      INTEGER NOT NULL REFERENCES unidades(id),
    codigo          TEXT NOT NULL,
    descricao       TEXT,
    status          TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'inativa')),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER,
    UNIQUE (unidade_id, codigo)
);

CREATE INDEX idx_posicoes_unidade ON posicoes_estoque(unidade_id);

-- ============================================================
-- MOVIMENTAÇÕES DE ESTOQUE — livro-razão append-only
-- ============================================================
-- `quantidade` é sempre assinada: positiva aumenta o saldo do lote naquela
-- posição, negativa diminui. O saldo de um lote numa posição, a qualquer
-- momento, é SUM(quantidade) WHERE lote_id=X AND posicao_id=Y — nunca um
-- campo de saldo armazenado à parte.
--
-- Uma transferência entre posições gera DUAS linhas na mesma transação
-- (uma saída negativa na origem, uma entrada positiva no destino),
-- linkadas por um `transferencia_grupo` (token) comum às duas — não por
-- id de uma apontando para a outra, porque a tabela é append-only
-- (UPDATE bloqueado por trigger) e não daria para "voltar" e preencher o
-- id de uma linha na outra depois de inserida.
--
-- Corrigir um lançamento errado nunca edita a linha original — sempre um
-- novo ajuste, com motivo obrigatório, preservando o histórico completo
-- (mesma filosofia de resultados_analise_historico e
-- ordem_producao_consumo das fases anteriores).
CREATE TABLE movimentacoes_estoque (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id                 INTEGER NOT NULL REFERENCES lotes(id),
    posicao_id              INTEGER NOT NULL REFERENCES posicoes_estoque(id),
    tipo                    TEXT NOT NULL CHECK (tipo IN (
                                'enderecamento', 'transferencia_saida', 'transferencia_entrada',
                                'ajuste_positivo', 'ajuste_negativo', 'saida'
                            )),
    quantidade              REAL NOT NULL,
    motivo                  TEXT,
    transferencia_grupo     TEXT,
    registrado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    registrado_por          INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_mov_estoque_lote ON movimentacoes_estoque(lote_id);
CREATE INDEX idx_mov_estoque_posicao ON movimentacoes_estoque(posicao_id);
CREATE INDEX idx_mov_estoque_lote_posicao ON movimentacoes_estoque(lote_id, posicao_id);
CREATE INDEX idx_mov_estoque_transferencia_grupo ON movimentacoes_estoque(transferencia_grupo);

CREATE TRIGGER mov_estoque_bloqueia_update
BEFORE UPDATE ON movimentacoes_estoque
BEGIN
    SELECT RAISE(ABORT, 'movimentacoes_estoque é append-only: UPDATE não é permitido (corrija com um novo lançamento de ajuste)');
END;

CREATE TRIGGER mov_estoque_bloqueia_delete
BEFORE DELETE ON movimentacoes_estoque
BEGIN
    SELECT RAISE(ABORT, 'movimentacoes_estoque é append-only: DELETE não é permitido (corrija com um novo lançamento de ajuste)');
END;
