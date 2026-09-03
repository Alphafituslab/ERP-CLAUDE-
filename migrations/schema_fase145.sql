-- Alphafitus OS — Fase 145 (Terceirização Premium / Fase E do plano):
-- aprovação de arte (V1/V2/V3), foto final do produto real, comentários
-- internos vs compartilhados com o cliente.
--
-- Diferente do "congelamento de versão" da Fase D (que trava o PROJETO
-- inteiro depois de assinado — fórmula, embalagem, briefing), aqui é só
-- o arquivo de ARTE do rótulo/embalagem que tem ciclo de versão próprio
-- (V1, V2, V3...) e aprovação — pode acontecer várias vezes, mesmo
-- depois do projeto já assinado, sem precisar abrir uma nova versão do
-- projeto inteiro pra isso.

CREATE TABLE terceirizacao_artes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id          INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    versao              INTEGER NOT NULL,   -- V1, V2, V3... sequencial por projeto
    nome_arquivo        TEXT NOT NULL,
    tipo_mime           TEXT NOT NULL,
    dados               TEXT NOT NULL,      -- base64, mesmo padrão de terceirizacao_arquivos
    tamanho             INTEGER NOT NULL,
    observacoes         TEXT,               -- nota de quem enviou (o que mudou desde a versão anterior)
    status              TEXT NOT NULL DEFAULT 'aguardando_aprovacao'
                        CHECK (status IN ('aguardando_aprovacao', 'aprovado', 'alteracao_solicitada')),
    solicitacao_texto   TEXT,               -- preenchido só quando status = 'alteracao_solicitada'
    decidido_por_nome   TEXT,               -- quem decidiu: nome do cliente (portal) OU nome do usuário interno
    decidido_em         TEXT,
    enviado_por         INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (projeto_id, versao)
);
CREATE INDEX idx_terceirizacao_artes_projeto ON terceirizacao_artes(projeto_id);

-- Foto final do produto real (rótulo aplicado no pote de verdade, depois
-- de produzido) — reaproveita a MESMA tabela de arquivos já existente
-- (terceirizacao_arquivos, Fase A), só adiciona 'foto_produto_final'
-- como categoria nova possível. SQLite não deixa alterar um CHECK
-- existente com ALTER TABLE — reconstrói a tabela (mesmo padrão já
-- usado nas Fases 115/125/128 quando um enum precisou crescer).
CREATE TABLE terceirizacao_arquivos_nova (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id    INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    nome          TEXT NOT NULL,
    nome_arquivo  TEXT NOT NULL,
    tipo_mime     TEXT NOT NULL,
    dados         TEXT NOT NULL,
    tamanho       INTEGER NOT NULL,
    categoria     TEXT NOT NULL DEFAULT 'outro' CHECK (categoria IN (
        'embalagem', 'rotulo', 'cor', 'estilo', 'logotipo', 'concorrente', 'referencia',
        'documento_empresa', 'foto_produto_final', 'outro'
    )),
    visibilidade  TEXT NOT NULL DEFAULT 'compartilhado' CHECK (visibilidade IN ('interno', 'compartilhado')),
    comentario    TEXT,
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por    INTEGER NOT NULL REFERENCES usuarios(id)
);
INSERT INTO terceirizacao_arquivos_nova SELECT * FROM terceirizacao_arquivos;
DROP TABLE terceirizacao_arquivos;
ALTER TABLE terceirizacao_arquivos_nova RENAME TO terceirizacao_arquivos;
CREATE INDEX idx_terceirizacao_arquivos_projeto ON terceirizacao_arquivos(projeto_id);

CREATE TABLE terceirizacao_comentarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id          INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    texto               TEXT NOT NULL,
    visibilidade        TEXT NOT NULL DEFAULT 'interno' CHECK (visibilidade IN ('interno', 'compartilhado')),
    autor_nome          TEXT NOT NULL,      -- nome do usuário interno OU nome digitado pelo cliente no portal
    autor_usuario_id    INTEGER REFERENCES usuarios(id),  -- NULL quando o autor é o cliente (via portal)
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_terceirizacao_comentarios_projeto ON terceirizacao_comentarios(projeto_id);
