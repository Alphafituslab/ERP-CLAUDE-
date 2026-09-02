-- Alphafitus OS — Fase 134 (Terceirização Premium, Fase A — fundação de
-- dados: catálogo de embalagem, projeto, briefing, arquivos)
--
-- Pedido do usuário (2026-09-01): módulo novo de terceirização white-label
-- onde o cliente escolhe uma fórmula já cadastrada, personaliza embalagem
-- (pote/tampa/cápsula/quantidade) e preenche um briefing — construído em
-- fases (A: fundação de dados/uso interno; B: documento+aprovação;
-- C: portal do cliente+WhatsApp; D: assinatura+versionamento; E: extras).
-- Este arquivo é só a Fase A.
--
-- Decisão confirmada com o usuário: a tabela nutricional/lista de
-- ingredientes vem do Memorial Técnico ANVISA já existente (memoriais/
-- memorial_produtos) quando houver um aprovado pra aquele produto — por
-- isso o vínculo novo `itens.memorial_produto_id` abaixo. Nenhuma coluna
-- nova em `memoriais`/`memorial_produtos` — o vínculo é unidirecional,
-- partindo de `itens` (o produto interno) até o memorial correspondente.

ALTER TABLE itens ADD COLUMN memorial_produto_id INTEGER REFERENCES memorial_produtos(id);

-- ── Catálogo de embalagem (pote/tampa/cápsula) ──────────────────────────
-- Nunca existiu em nenhuma tabela do sistema antes desta fase (confirmado
-- por busca ampla no schema inteiro) — cadastro 100% novo, administrado
-- pela mesma tela de configuração que outros catálogos do sistema
-- (mesmo padrão de metodos_pagamento/condicoes_pagamento: ativo/inativo,
-- nunca DELETE físico depois de usado em algum projeto).

CREATE TABLE terceirizacao_potes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo        TEXT NOT NULL UNIQUE,
    nome          TEXT NOT NULL,
    cor           TEXT NOT NULL,
    material      TEXT,
    capacidade_ml REAL,
    capacidade_capsulas INTEGER,
    imagem        TEXT,  -- base64 data URI, mesmo padrão de itens.imagem (schema_fase114)
    ativo         INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por    INTEGER REFERENCES usuarios(id)
);

CREATE TABLE terceirizacao_tampas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo        TEXT NOT NULL UNIQUE,
    nome          TEXT NOT NULL,
    cor           TEXT NOT NULL,
    modelo        TEXT,
    imagem        TEXT,
    ativo         INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por    INTEGER REFERENCES usuarios(id)
);

CREATE TABLE terceirizacao_capsulas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo        TEXT NOT NULL UNIQUE,
    nome          TEXT NOT NULL,
    cor_cabeca    TEXT NOT NULL,
    cor_corpo     TEXT NOT NULL,
    material      TEXT,  -- ex.: "gelatina bovina", "vegetal (HPMC)"
    imagem        TEXT,
    ativo         INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por    INTEGER REFERENCES usuarios(id)
);

-- Pote x Tampa compatíveis — presença na tabela = compatível. Ausência de
-- QUALQUER linha pra um pote = "compatível com todas" (evita ter que
-- cadastrar N linhas pra um pote genérico antes dele funcionar).
CREATE TABLE terceirizacao_compat_pote_tampa (
    pote_id  INTEGER NOT NULL REFERENCES terceirizacao_potes(id),
    tampa_id INTEGER NOT NULL REFERENCES terceirizacao_tampas(id),
    PRIMARY KEY (pote_id, tampa_id)
);

-- ── Projeto de terceirização ─────────────────────────────────────────────
CREATE TABLE terceirizacao_projetos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    numero              TEXT NOT NULL UNIQUE,  -- TER-2026-000001
    cliente_id          INTEGER NOT NULL REFERENCES clientes(id),
    item_id             INTEGER REFERENCES itens(id),  -- fórmula/produto escolhido (itens.tipo = 'produto_acabado')
    pote_id             INTEGER REFERENCES terceirizacao_potes(id),
    tampa_id            INTEGER REFERENCES terceirizacao_tampas(id),
    capsula_id          INTEGER REFERENCES terceirizacao_capsulas(id),
    quantidade_por_pote INTEGER,
    unidade_quantidade  TEXT CHECK (unidade_quantidade IN ('capsulas', 'gramas')),
    -- Ciclo de vida completo já modelado agora (evita ALTER TABLE +
    -- reconstrução de CHECK constraint no SQLite mais tarde) — a Fase A só
    -- transita entre 'rascunho' e 'cancelado'; os demais valores entram em
    -- uso nas Fases B/C/D/E.
    status TEXT NOT NULL DEFAULT 'rascunho' CHECK (status IN (
        'rascunho', 'aguardando_cliente', 'em_preenchimento',
        'aguardando_revisao', 'aguardando_aprovacao', 'aguardando_assinatura',
        'assinado', 'em_desenvolvimento', 'arte_em_desenvolvimento',
        'arte_em_aprovacao', 'em_producao', 'concluido', 'cancelado'
    )),
    versao              INTEGER NOT NULL DEFAULT 1,
    responsavel_id      INTEGER REFERENCES usuarios(id),  -- vendedor/responsável interno
    solicitacao_alteracao_formula TEXT,  -- "Solicitar alteração da fórmula" (Etapa 1 do pedido do usuário) — texto livre, avaliado internamente
    motivo_cancelamento TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER NOT NULL REFERENCES usuarios(id),
    atualizado_em       TEXT
);
CREATE INDEX idx_terceirizacao_projetos_cliente ON terceirizacao_projetos(cliente_id);

CREATE TABLE terceirizacao_briefings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id          INTEGER NOT NULL UNIQUE REFERENCES terceirizacao_projetos(id),
    ideia_projeto       TEXT,
    publico_alvo        TEXT,
    posicionamento      TEXT,
    sensacao_desejada   TEXT,
    estilo_visual       TEXT,  -- JSON array de strings (múltipla escolha: Luxuoso, Premium, Minimalista, ...)
    cores_preferidas    TEXT,  -- JSON array de HEX
    cores_evitar        TEXT,  -- JSON array de HEX
    marcas_referencia   TEXT,  -- JSON array de {nome, site, instagram, observacao}
    atualizado_em       TEXT
);

-- ── Arquivos/anexos do projeto ───────────────────────────────────────────
-- Mesmo padrão de app/routes/clientes_documentos.py (o upload mais robusto
-- já existente no sistema: allowlist de MIME, limite de tamanho, nome de
-- arquivo sanitizado, base64 na coluna) — só troca cliente_id por
-- projeto_id e adiciona categoria/visibilidade.
CREATE TABLE terceirizacao_arquivos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id    INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    nome          TEXT NOT NULL,
    nome_arquivo  TEXT NOT NULL,
    tipo_mime     TEXT NOT NULL,
    dados         TEXT NOT NULL,  -- base64
    tamanho       INTEGER NOT NULL,
    categoria     TEXT NOT NULL DEFAULT 'outro' CHECK (categoria IN (
        'embalagem', 'rotulo', 'cor', 'estilo', 'logotipo', 'concorrente', 'referencia', 'documento_empresa', 'outro'
    )),
    visibilidade  TEXT NOT NULL DEFAULT 'compartilhado' CHECK (visibilidade IN ('interno', 'compartilhado')),
    comentario    TEXT,
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por    INTEGER NOT NULL REFERENCES usuarios(id)
);
CREATE INDEX idx_terceirizacao_arquivos_projeto ON terceirizacao_arquivos(projeto_id);
