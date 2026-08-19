-- Alphafitus OS — Fase 3 (Produção / PCP / MES básico)
-- Aplicado DEPOIS de schema.sql e schema_fase2.sql, nunca remove nem altera
-- nada das fases anteriores. Mesmas notas de portabilidade para PostgreSQL.
--
-- Esta fase fecha o elo que faltava na rastreabilidade: até a Fase 2, um
-- lote só podia "nascer" por recebimento de fornecedor. A partir daqui, um
-- lote também pode nascer de uma ordem de produção que CONSOME lotes já
-- aprovados (matérias-primas/embalagens) e PRODUZ um novo lote (produto a
-- granel/intermediário/acabado) — e esse lote produzido entra em
-- quarentena e passa pelo MESMO fluxo de qualidade da Fase 2 (análise,
-- aprovação, CoA) antes de poder ser usado ou vendido. É a genealogia de
-- lote (batch genealogy) exigida no documento mestre: de qualquer lote dá
-- para navegar tanto para trás (de que lotes ele foi feito) quanto para
-- frente (em que lotes/ordens ele foi consumido).

PRAGMA foreign_keys = ON;

-- ============================================================
-- LOTES — estende a tabela da Fase 2 para registrar a origem
-- ============================================================
-- SQLite não permite adicionar múltiplas colunas com uma cláusula CHECK
-- referenciando outra tabela ainda não criada nesta migration, então a
-- FK de ordem_producao_id é adicionada sem REFERENCES formal (o vínculo é
-- garantido pelo código da aplicação) — mantém a migration simples e
-- 100% aditiva sobre uma tabela que já existe em produção.
ALTER TABLE lotes ADD COLUMN origem TEXT NOT NULL DEFAULT 'recebimento' CHECK (origem IN ('recebimento', 'producao'));
ALTER TABLE lotes ADD COLUMN ordem_producao_id INTEGER;

CREATE INDEX idx_lotes_ordem_producao ON lotes(ordem_producao_id);

-- ============================================================
-- FÓRMULAS (ficha técnica / BOM — Bill of Materials)
-- ============================================================
-- Só pode existir UMA fórmula com status='ativa' por item_produzido_id ao
-- mesmo tempo (garantido em código, na ativação — a anterior vira
-- 'obsoleta' automaticamente). Uma ordem de produção sempre referencia uma
-- fórmula ativa no momento da criação; a fórmula fica "congelada" na
-- ordem (suas linhas são copiadas para consulta histórica, mas a
-- genealogia de consumo real vem de ordem_producao_consumo).
CREATE TABLE formulas (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    item_produzido_id       INTEGER NOT NULL REFERENCES itens(id),
    versao                  INTEGER NOT NULL,
    rendimento_teorico      REAL NOT NULL,
    unidade_rendimento      TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'rascunho' CHECK (status IN ('rascunho', 'ativa', 'obsoleta')),
    observacoes             TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER,
    ativado_em              TEXT,
    ativado_por             INTEGER,
    UNIQUE (item_produzido_id, versao)
);

CREATE INDEX idx_formulas_item ON formulas(item_produzido_id);
CREATE INDEX idx_formulas_status ON formulas(status);

-- Linhas do BOM: cada insumo (matéria-prima/embalagem) necessário e sua
-- quantidade para produzir `rendimento_teorico` da fórmula.
CREATE TABLE formula_itens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id      INTEGER NOT NULL REFERENCES formulas(id),
    item_id         INTEGER NOT NULL REFERENCES itens(id),
    quantidade      REAL NOT NULL CHECK (quantidade > 0),
    unidade         TEXT NOT NULL
);

CREATE INDEX idx_formula_itens_formula ON formula_itens(formula_id);

-- ============================================================
-- ORDENS DE PRODUÇÃO
-- ============================================================
CREATE TABLE ordens_producao (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    formula_id              INTEGER NOT NULL REFERENCES formulas(id),
    item_produzido_id       INTEGER NOT NULL REFERENCES itens(id),   -- denormalizado da fórmula, para consulta rápida
    quantidade_planejada    REAL NOT NULL CHECK (quantidade_planejada > 0),
    quantidade_produzida    REAL,
    unidade                 TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'planejada' CHECK (status IN (
                                'planejada', 'liberada', 'em_producao', 'concluida', 'cancelada'
                            )),
    lote_produzido_id       INTEGER,   -- preenchido em /concluir; vira o lote_id do produto gerado
    motivo_cancelamento     TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por               INTEGER,
    liberado_em              TEXT,
    liberado_por             INTEGER,
    concluido_em             TEXT,
    concluido_por            INTEGER
);

CREATE INDEX idx_ordens_producao_status ON ordens_producao(status);
CREATE INDEX idx_ordens_producao_formula ON ordens_producao(formula_id);

-- Genealogia de consumo: qual lote (matéria-prima/embalagem já aprovado)
-- foi usado em qual ordem, e em que quantidade. É a peça central da
-- rastreabilidade "para trás" (de um lote produzido, quais lotes o
-- originaram) e "para frente" (de um lote recebido, em que produções ele
-- entrou). Append-only por design: uma vez apontado o consumo, não se
-- edita — se o apontamento estiver errado, corrige-se com um novo
-- lançamento e uma nota, nunca sobrescrevendo o histórico (mesma
-- filosofia de resultados_analise_historico na Fase 2).
CREATE TABLE ordem_producao_consumo (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem_producao_id   INTEGER NOT NULL REFERENCES ordens_producao(id),
    lote_id             INTEGER NOT NULL REFERENCES lotes(id),
    item_id             INTEGER NOT NULL REFERENCES itens(id),
    quantidade          REAL NOT NULL CHECK (quantidade > 0),
    unidade             TEXT NOT NULL,
    registrado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    registrado_por      INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_consumo_ordem ON ordem_producao_consumo(ordem_producao_id);
CREATE INDEX idx_consumo_lote ON ordem_producao_consumo(lote_id);

CREATE TRIGGER consumo_bloqueia_update
BEFORE UPDATE ON ordem_producao_consumo
BEGIN
    SELECT RAISE(ABORT, 'ordem_producao_consumo é append-only: UPDATE não é permitido (genealogia de lote não pode ser reescrita)');
END;

CREATE TRIGGER consumo_bloqueia_delete
BEFORE DELETE ON ordem_producao_consumo
BEGIN
    SELECT RAISE(ABORT, 'ordem_producao_consumo é append-only: DELETE não é permitido (genealogia de lote não pode ser apagada)');
END;
