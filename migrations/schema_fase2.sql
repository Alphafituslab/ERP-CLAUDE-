-- Alphafitus OS — Fase 2 (Qualidade e Laboratório)
-- Aplicado DEPOIS de schema.sql, nunca remove nem altera nada da Fase 1.
-- Mesmas notas de portabilidade para PostgreSQL do schema.sql se aplicam aqui.

PRAGMA foreign_keys = ON;

-- ============================================================
-- ITENS (materiais) — matéria-prima, embalagem, produto acabado etc.
-- ============================================================
CREATE TABLE itens (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo              TEXT NOT NULL UNIQUE,
    descricao           TEXT NOT NULL,
    tipo                TEXT NOT NULL CHECK (tipo IN (
                            'materia_prima', 'embalagem_primaria', 'embalagem_secundaria',
                            'produto_intermediario', 'produto_a_granel', 'produto_acabado',
                            'material_de_laboratorio'
                        )),
    unidade_medida      TEXT NOT NULL DEFAULT 'kg',
    requer_analise      INTEGER NOT NULL DEFAULT 1 CHECK (requer_analise IN (0,1)),
    requer_fornecedor_homologado INTEGER NOT NULL DEFAULT 0 CHECK (requer_fornecedor_homologado IN (0,1)),
    estoque_minimo      REAL,
    status              TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo','inativo')),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER,
    atualizado_em       TEXT,
    atualizado_por      INTEGER
);

-- ============================================================
-- FORNECEDORES E HOMOLOGAÇÃO
-- ============================================================
CREATE TABLE fornecedores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL,
    cnpj            TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'em_avaliacao' CHECK (status IN (
                        'em_avaliacao','aprovado','aprovado_com_ressalva','bloqueado','reprovado'
                    )),
    observacoes     TEXT,
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER,
    atualizado_em   TEXT,
    atualizado_por  INTEGER
);

-- Marca quais itens um fornecedor está homologado a fornecer.
CREATE TABLE item_fornecedor_aprovado (
    item_id         INTEGER NOT NULL REFERENCES itens(id),
    fornecedor_id   INTEGER NOT NULL REFERENCES fornecedores(id),
    aprovado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    aprovado_por    INTEGER,
    PRIMARY KEY (item_id, fornecedor_id)
);

-- ============================================================
-- LOTES — o coração da rastreabilidade
-- ============================================================
CREATE TABLE lotes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_lote             TEXT NOT NULL UNIQUE,   -- gerado automaticamente no recebimento
    item_id                 INTEGER NOT NULL REFERENCES itens(id),
    fornecedor_id           INTEGER REFERENCES fornecedores(id),
    lote_fornecedor         TEXT,                    -- lote de origem informado pelo fornecedor
    fabricacao              TEXT,
    validade                TEXT,
    quantidade              REAL NOT NULL,
    unidade                 TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'quarentena' CHECK (status IN (
                                'quarentena', 'em_analise', 'aguardando_aprovacao',
                                'aprovado', 'aprovado_com_ressalva', 'reprovado',
                                'bloqueado', 'devolvido', 'destruido'
                            )),
    status_antes_bloqueio   TEXT,   -- usado para restaurar o status ao desbloquear
    motivo_bloqueio         TEXT,
    nota_fiscal             TEXT,
    pedido_compra           TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por               INTEGER,
    atualizado_em            TEXT,
    atualizado_por           INTEGER
);

CREATE INDEX idx_lotes_item ON lotes(item_id);
CREATE INDEX idx_lotes_status ON lotes(status);

-- ============================================================
-- ANÁLISES E RESULTADOS (LIMS)
-- ============================================================
CREATE TABLE analises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id         INTEGER NOT NULL REFERENCES lotes(id),
    tipo            TEXT NOT NULL DEFAULT 'liberacao',
    status          TEXT NOT NULL DEFAULT 'aguardando_resultado' CHECK (status IN (
                        'aguardando_resultado', 'concluida', 'cancelada'
                    )),
    conclusao       TEXT CHECK (conclusao IN ('conforme', 'nao_conforme') OR conclusao IS NULL),
    analista_id     INTEGER REFERENCES usuarios(id),
    concluida_em    TEXT,
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER
);

-- Cada linha é um ensaio dentro de uma análise. Criada (com resultado=NULL)
-- no momento da solicitação; o preenchimento do resultado é uma ação
-- separada (POST /analises/<id>/resultados/<id>). Correções depois de
-- preenchido NUNCA sobrescrevem esta linha "às cegas" — ver
-- resultados_analise_historico abaixo.
CREATE TABLE resultados_analise (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    analise_id              INTEGER NOT NULL REFERENCES analises(id),
    ensaio                  TEXT NOT NULL,
    especificacao_min       REAL,
    especificacao_max       REAL,
    unidade                 TEXT,
    resultado               REAL,
    conclusao               TEXT CHECK (conclusao IN ('conforme','nao_conforme') OR conclusao IS NULL),
    registrado_por          INTEGER REFERENCES usuarios(id),
    registrado_em           TEXT
);

-- Trilha específica de correções de resultado — preserva TODO valor
-- anterior, nunca é editada depois de criada (mesma filosofia da tabela
-- `auditoria`, mas com o detalhe específico de laboratório).
CREATE TABLE resultados_analise_historico (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    resultado_id        INTEGER NOT NULL REFERENCES resultados_analise(id),
    resultado_anterior  REAL,
    resultado_novo      REAL,
    motivo              TEXT NOT NULL,
    usuario_id          INTEGER REFERENCES usuarios(id),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TRIGGER resultados_historico_bloqueia_update
BEFORE UPDATE ON resultados_analise_historico
BEGIN
    SELECT RAISE(ABORT, 'resultados_analise_historico é append-only: UPDATE não é permitido');
END;

CREATE TRIGGER resultados_historico_bloqueia_delete
BEFORE DELETE ON resultados_analise_historico
BEGIN
    SELECT RAISE(ABORT, 'resultados_analise_historico é append-only: DELETE não é permitido');
END;

-- ============================================================
-- CERTIFICADO DE ANÁLISE (CoA) — gerado automaticamente na aprovação do lote
-- ============================================================
CREATE TABLE certificados_analise (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id         INTEGER NOT NULL REFERENCES lotes(id),
    numero_unico    TEXT NOT NULL UNIQUE,
    revisao         INTEGER NOT NULL DEFAULT 1,
    conclusao       TEXT NOT NULL,
    aprovado_por    INTEGER REFERENCES usuarios(id),
    emitido_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ============================================================
-- DESVIOS E CAPA (versão enxuta da Fase 2 — QMS completo vem depois)
-- ============================================================
CREATE TABLE desvios (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    origem                  TEXT NOT NULL,
    item_id                 INTEGER REFERENCES itens(id),
    lote_id                 INTEGER REFERENCES lotes(id),
    criticidade             TEXT NOT NULL DEFAULT 'media' CHECK (criticidade IN ('baixa','media','alta','critica')),
    descricao               TEXT NOT NULL,
    causa_raiz              TEXT,
    plano_acao              TEXT,
    verificacao_eficacia    TEXT,
    status                  TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto','em_tratativa','encerrado')),
    prazo                   TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER,
    encerrado_em            TEXT,
    encerrado_por           INTEGER
);

CREATE INDEX idx_desvios_status ON desvios(status);
CREATE INDEX idx_analises_lote ON analises(lote_id);
CREATE INDEX idx_resultados_analise ON resultados_analise(analise_id);
