-- Alphafitus OS — Fase 115 (Memorial Técnico: campos e catálogos faltando
-- para paridade com o sistema antigo "Anvisa Technical Memorial")
--
-- Pedido do usuário: "trazer tudo igual, cada funcionalidade ok, não mudar
-- nada, verificar se está tudo funcionando perfeitamente" — depois de uma
-- auditoria campo a campo contra o código-fonte do sistema original, esta
-- é a primeira de várias fases para fechar as lacunas encontradas. Esta
-- fase cobre só os campos/catálogos que faltavam — os módulos inteiros que
-- faltam (editores estruturados, Portfólio, Tabelas Nutricionais, PDF de
-- Padronização, biblioteca de snapshots) ficam para as fases seguintes.

-- `empresasTable.telefoneContato` no sistema original — telefone de um
-- contato específico da empresa, diferente do `telefone` geral.
ALTER TABLE memorial_empresas ADD COLUMN telefone_contato TEXT;

-- `produtosTable.sabor` no sistema original — usado no catálogo de
-- produtos e (quando o módulo Portfólio for portado, Fase 117) na ficha
-- do produto.
ALTER TABLE memorial_produtos ADD COLUMN sabor TEXT;

-- `memorial_catalogo_itens.catalogo` tinha um CHECK fixo com só 10
-- valores (Fase 26) — SQLite não permite ALTER de CHECK diretamente,
-- então a tabela é recriada com a lista ampliada (mais 'componentes',
-- 'opcoes_capsula', 'tipos_pote', que o sistema original tinha como
-- catálogos próprios e o AlphafitusOS ainda não tinha). Os outros 8
-- catálogos que já tinham lacuna de CAMPO (não de categoria inteira —
-- 'nutrientes' e 'referencias') não precisam de migration: a tabela
-- guarda os campos extras dentro da coluna `dados` (JSON), então basta
-- estender `CATALOGOS_CONFIG` em app/routes/memorial_catalogos.py — ver
-- esse arquivo para a lista completa de campos novos de 'nutrientes' e
-- 'referencias'.
CREATE TABLE memorial_catalogo_itens_novo (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    catalogo       TEXT NOT NULL CHECK (catalogo IN (
                       'metodologias', 'nutrientes', 'legislacoes', 'alegacoes',
                       'tipos_produto', 'advertencias', 'armazenamento', 'modo_uso',
                       'justificativas', 'referencias', 'componentes', 'opcoes_capsula',
                       'tipos_pote'
                   )),
    ordem          INTEGER NOT NULL DEFAULT 0,
    ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    dados          TEXT NOT NULL DEFAULT '{}',
    criado_por     INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por INTEGER REFERENCES usuarios(id),
    atualizado_em  TEXT
);

INSERT INTO memorial_catalogo_itens_novo
    SELECT * FROM memorial_catalogo_itens;

DROP TABLE memorial_catalogo_itens;

ALTER TABLE memorial_catalogo_itens_novo RENAME TO memorial_catalogo_itens;

CREATE INDEX idx_memorial_catalogo_itens_catalogo ON memorial_catalogo_itens(catalogo, ordem, id);
