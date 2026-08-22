-- Alphafitus OS — Fase 84 (Granel intermediário como etapa + Centro de Trabalho por etapa +
-- Apontamento Diário de Produção)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- 1) "Vai para estoque em forma de pó" — o usuário confirmou que isso deve ficar como uma
--    ETAPA DENTRO DA MESMA Ordem de Produção (não uma segunda OP com lote/QMS próprio):
--    Pesagem → Mistura → Descarregamento → Encapsulamento/Envase, tudo na mesma ordem. Só
--    precisamos de mais um tipo no catálogo já existente (`tipos_etapa_producao`, Fase 75) —
--    `valor_registrado` (também já existente) já resolve "quantidade visível/rastreável" sem
--    nenhuma tabela nova. Reordenamos `ordem_padrao` dos tipos existentes para refletir a
--    sequência real do processo (isso é só um número de exibição, não é estrutural — seguro
--    de alterar via UPDATE, diferente de uma coluna/CHECK).
--
-- 2) `centro_trabalho_id` em `ordem_producao_etapas` — permite escolher qual das 4
--    encapsuladoras/4 linhas de envase rodou aquela etapa específica. Isso é DIFERENTE de
--    `ordem_producao_agendamentos.centro_trabalho_id` (Fase 25): aquele é o recurso físico que
--    a ORDEM INTEIRA usa para agendamento de capacidade (UNIQUE por ordem — uma ordem só pode
--    estar agendada num centro de trabalho por vez, para a duração inteira); este aqui é por
--    ETAPA, sem UNIQUE nenhum, porque a mesma ordem pode passar por máquinas diferentes em
--    etapas diferentes (ex.: Encapsulamento na Encapsuladora 2, depois nada de centro de
--    trabalho na Rotulagem). Nenhum dos dois substitui o outro.
--
-- 3) Apontamento diário — a Ordem de Produção só registra `quantidade_produzida` UMA VEZ, na
--    conclusão. O pedido de "produção do dia escrita pelo colaborador" é um LOG CORRIDO,
--    paralelo a isso, só para o painel em tempo real mostrar o que está sendo produzido agora
--    — nunca substitui nem valida contra a reconciliação final de `concluir()`.

PRAGMA foreign_keys = ON;

-- ============================================================
-- 1) Novo tipo de etapa: "Descarregamento/Estoque Intermediário"
-- ============================================================
UPDATE tipos_etapa_producao SET ordem_padrao = ordem_padrao + 1 WHERE ordem_padrao >= 3;

INSERT INTO tipos_etapa_producao (nome, unidade_valor, ordem_padrao) VALUES
    ('Descarregamento/Estoque Intermediário', 'kg', 3);

-- ============================================================
-- 2) Centro de trabalho por etapa (encapsuladora/linha de envase específica)
-- ============================================================
ALTER TABLE ordem_producao_etapas ADD COLUMN centro_trabalho_id INTEGER REFERENCES centros_trabalho(id);

INSERT INTO centros_trabalho (nome, capacidade_paralela, status) VALUES
    ('Encapsuladora 1', 1, 'ativo'),
    ('Encapsuladora 2', 1, 'ativo'),
    ('Encapsuladora 3', 1, 'ativo'),
    ('Encapsuladora 4', 1, 'ativo'),
    ('Linha de Envase 1', 1, 'ativo'),
    ('Linha de Envase 2', 1, 'ativo'),
    ('Linha de Envase 3', 1, 'ativo'),
    ('Linha de Envase 4', 1, 'ativo');

-- ============================================================
-- 3) Apontamento diário de produção (log corrido, só para visibilidade em tempo real)
-- ============================================================
CREATE TABLE ordem_producao_apontamentos_diarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem_producao_id   INTEGER NOT NULL REFERENCES ordens_producao(id),
    etapa_id            INTEGER REFERENCES ordem_producao_etapas(id),
    data                TEXT NOT NULL,
    quantidade          REAL NOT NULL CHECK (quantidade > 0),
    unidade             TEXT NOT NULL,
    observacao          TEXT,
    registrado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    registrado_por      INTEGER REFERENCES usuarios(id)
);
CREATE INDEX idx_op_apontamentos_diarios_ordem ON ordem_producao_apontamentos_diarios(ordem_producao_id, data);
