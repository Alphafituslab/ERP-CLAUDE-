-- Alphafitus OS — Fase 1 (Fundação)
-- Schema de referência em SQLite (usado no ambiente de desenvolvimento/testes).
-- Notas de portabilidade para PostgreSQL (produção alvo) estão nos comentários
-- "-- PG:" ao lado de cada tabela — a tradução é mecânica.

PRAGMA foreign_keys = ON;

-- ============================================================
-- NÚCLEO: EMPRESAS E UNIDADES
-- PG: INTEGER PRIMARY KEY AUTOINCREMENT -> id SERIAL PRIMARY KEY (ou GENERATED ALWAYS AS IDENTITY)
-- PG: TEXT (datas ISO) -> TIMESTAMPTZ
-- ============================================================
CREATE TABLE empresas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social    TEXT NOT NULL,
    nome_fantasia   TEXT,
    cnpj            TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa','inativa')),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER,
    atualizado_em   TEXT,
    atualizado_por  INTEGER
);

CREATE TABLE unidades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id      INTEGER NOT NULL REFERENCES empresas(id),
    nome            TEXT NOT NULL,
    tipo            TEXT NOT NULL DEFAULT 'unidade' CHECK (tipo IN ('unidade','deposito','laboratorio')),
    endereco        TEXT,
    status          TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa','inativa')),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER,
    atualizado_em   TEXT,
    atualizado_por  INTEGER
);

-- ============================================================
-- USUÁRIOS, PERFIS E PERMISSÕES GRANULARES
-- ============================================================
CREATE TABLE usuarios (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL,
    email                   TEXT NOT NULL UNIQUE,
    senha_hash              TEXT NOT NULL,           -- formato: pbkdf2_sha256$iteracoes$salt_hex$hash_hex
    dois_fatores_secret     TEXT,                     -- base32, só existe após /2fa/setup
    dois_fatores_ativo      INTEGER NOT NULL DEFAULT 0 CHECK (dois_fatores_ativo IN (0,1)),
    status                  TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo','inativo','bloqueado')),
    tentativas_login_falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate           TEXT,                     -- timestamp ISO; NULL = não bloqueado
    senha_deve_trocar       INTEGER NOT NULL DEFAULT 0 CHECK (senha_deve_trocar IN (0,1)),
    senha_trocada_em        TEXT,
    ultimo_login_em         TEXT,
    ultimo_login_ip         TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER,
    atualizado_em           TEXT,
    atualizado_por          INTEGER
);

CREATE TABLE perfis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL UNIQUE,
    descricao       TEXT,
    editavel        INTEGER NOT NULL DEFAULT 1 CHECK (editavel IN (0,1)),  -- 0 = perfil de sistema (ex.: Administrador), não pode ser excluído
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER,
    atualizado_em   TEXT,
    atualizado_por  INTEGER
);

-- Catálogo de ações possíveis do sistema. Cada linha é uma permissão atômica
-- ("modulo.acao"), nunca "acesso à tela inteira".
CREATE TABLE permissoes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    modulo                  TEXT NOT NULL,
    acao                    TEXT NOT NULL,
    descricao               TEXT,
    exige_dupla_aprovacao   INTEGER NOT NULL DEFAULT 0 CHECK (exige_dupla_aprovacao IN (0,1)),
    UNIQUE(modulo, acao)
);

CREATE TABLE perfil_permissao (
    perfil_id       INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    permissao_id    INTEGER NOT NULL REFERENCES permissoes(id) ON DELETE CASCADE,
    PRIMARY KEY (perfil_id, permissao_id)
);

CREATE TABLE usuario_perfil (
    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    perfil_id       INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    atribuido_em    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atribuido_por   INTEGER,
    PRIMARY KEY (usuario_id, perfil_id)
);

-- ============================================================
-- SESSÕES E REFRESH TOKENS (permitem revogação remota, exigida no plano de segurança)
-- ============================================================
CREATE TABLE sessoes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id          INTEGER NOT NULL REFERENCES usuarios(id),
    refresh_token_hash  TEXT NOT NULL,      -- sha256 do refresh token; o token em si nunca é armazenado em texto puro
    ip                  TEXT,
    dispositivo         TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expira_em           TEXT NOT NULL,
    revogado            INTEGER NOT NULL DEFAULT 0 CHECK (revogado IN (0,1)),
    revogado_em         TEXT,
    revogado_por        INTEGER
);

-- ============================================================
-- TRILHA DE AUDITORIA — SOMENTE INSERÇÃO (imposto por trigger abaixo)
-- ============================================================
CREATE TABLE auditoria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tabela          TEXT NOT NULL,
    registro_id     TEXT,
    usuario_id      INTEGER,
    acao            TEXT NOT NULL,
    valor_anterior  TEXT,      -- JSON serializado -- PG: usar JSONB
    valor_novo      TEXT,      -- JSON serializado -- PG: usar JSONB
    motivo          TEXT,
    ip              TEXT,
    dispositivo     TEXT,
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Bloqueio de banco: ninguém (nem o próprio backend) consegue alterar ou apagar
-- um registro de auditoria já gravado. Regra "impossibilidade de apagar
-- registros críticos sem evidência" do documento de arquitetura, seção 9.4.
CREATE TRIGGER auditoria_bloqueia_update
BEFORE UPDATE ON auditoria
BEGIN
    SELECT RAISE(ABORT, 'auditoria é append-only: UPDATE não é permitido');
END;

CREATE TRIGGER auditoria_bloqueia_delete
BEFORE DELETE ON auditoria
BEGIN
    SELECT RAISE(ABORT, 'auditoria é append-only: DELETE não é permitido');
END;

-- ============================================================
-- DOCUMENTOS E NOTIFICAÇÕES (escopo mínimo da Fase 1)
-- ============================================================
CREATE TABLE documentos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo          TEXT NOT NULL UNIQUE,
    titulo          TEXT NOT NULL,
    tipo            TEXT NOT NULL,
    revisao         INTEGER NOT NULL DEFAULT 1,
    vigencia_inicio TEXT,
    vigencia_fim    TEXT,
    arquivo_hash    TEXT,
    status          TEXT NOT NULL DEFAULT 'vigente' CHECK (status IN ('vigente','obsoleto')),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER,
    atualizado_em   TEXT,
    atualizado_por  INTEGER
);

CREATE TABLE notificacoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id),
    tipo        TEXT NOT NULL,
    mensagem    TEXT NOT NULL,
    lida        INTEGER NOT NULL DEFAULT 0 CHECK (lida IN (0,1)),
    criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_auditoria_tabela_registro ON auditoria(tabela, registro_id);
CREATE INDEX idx_auditoria_usuario ON auditoria(usuario_id);
CREATE INDEX idx_auditoria_criado_em ON auditoria(criado_em);
CREATE INDEX idx_sessoes_usuario ON sessoes(usuario_id);
CREATE INDEX idx_notificacoes_usuario ON notificacoes(usuario_id, lida);
