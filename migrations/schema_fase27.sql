-- Alphafitus OS — Fase 27 (Memorial Técnico ANVISA — Anexos e Padronização de Rótulo)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas.
--
-- A Fase 24 (fundação do Memorial Técnico) deixou de propósito de fora
-- "anexos de arquivo (laudos, especificações, rótulos) e a página de
-- padronização de rótulo (rótulo formatado a partir dos dados do
-- memorial)", citando-os como próximo passo. Esta fase entrega os dois,
-- junto com o redesenho da tela de edição do memorial em abas numeradas
-- (0 a 9, como no sistema original) — ver `app/routes/memorial_anexos.py`,
-- `app/routes/memorial_padronizacao.py` e `renderMemorialDetalhe` em
-- app.js.
--
-- `memorial_anexos`: arquivo guardado como base64 na própria coluna
-- `dados` (TEXT), não em disco/object storage — mesma escolha do sistema
-- original (Postgres) e consistente com o resto do Alphafitus, que já
-- guarda tudo num único arquivo `.db` (mais simples de fazer backup e
-- mover a instalação inteira). Limite de tamanho por arquivo é aplicado
-- na camada de aplicação (ver MAX_ANEXO_BYTES em memorial_anexos.py), não
-- no banco.
--
-- `memorial_padronizacoes`: um registro por memorial (1:1, por isso o
-- UNIQUE em memorial_id) com os "dizeres de rotulagem" — os campos que
-- vão literalmente impressos no rótulo do produto, formatados a partir
-- (mas não substituindo) do conteúdo já preenchido no memorial.

PRAGMA foreign_keys = ON;

CREATE TABLE memorial_anexos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    memorial_id   INTEGER NOT NULL REFERENCES memoriais(id),
    nome          TEXT NOT NULL,
    nome_arquivo  TEXT NOT NULL,
    tipo_mime     TEXT NOT NULL,
    dados         TEXT NOT NULL,
    tamanho       INTEGER NOT NULL,
    usuario_nome  TEXT NOT NULL,
    criado_por    INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_memorial_anexos_memorial ON memorial_anexos(memorial_id);

CREATE TABLE memorial_padronizacoes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    memorial_id          INTEGER NOT NULL UNIQUE REFERENCES memoriais(id),
    produto              TEXT,
    peso_liquido         TEXT,
    contem               TEXT,
    denominacao_legal    TEXT,
    lista_ingredientes   TEXT,
    alergenicos          TEXT,
    advertencias         TEXT,
    conservacao          TEXT,
    informacoes_consumo  TEXT,
    largura_rotulo       TEXT,
    comprimento_rotulo   TEXT,
    altura_rotulo        TEXT,
    cor_capsula          TEXT,
    tamanho_capsulas     TEXT,
    tipo_capsulas        TEXT,
    tamanho_pote         TEXT,
    simbolos_logos       TEXT,
    alegacoes            TEXT,
    dados_distribuidor   TEXT,
    observacoes_tabela   TEXT,
    atualizado_por       INTEGER REFERENCES usuarios(id),
    atualizado_em        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
