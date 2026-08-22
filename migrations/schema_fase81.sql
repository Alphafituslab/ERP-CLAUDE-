-- Alphafitus OS — Fase 81 (Catálogo de Fluxo Configurável, multi-entidade)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- O pedido do usuário foi "deixar que seja possível cadastrar mais fluxos no caminho caso
-- seja necessário" para o painel de acompanhamento ponta a ponta (Fase 90). A maior parte do
-- pipeline descrito por ele JÁ tem uma coluna de status real em alguma tabela existente
-- (pedidos_venda.status, ordens_producao.status + ordem_producao_etapas, pedidos_compra.status,
-- sugestoes_compra_mrp.status, lotes.status) — duplicar isso aqui criaria duas fontes de
-- verdade para a mesma coisa, o problema que este projeto sempre evitou (ver painel_tempo_real.py:
-- sempre lê ao vivo, nunca guarda snapshot).
--
-- Por isso, este catálogo cobre DELIBERADAMENTE só o que HOJE não tem nenhuma coluna de status
-- própria (ex.: "Separação" de um pedido de venda antes de virar OP ou ser expedido direto; e,
-- mais adiante na Fase 86, "Coleta pela Transportadora") — e fica aberto para o Administrador
-- cadastrar QUALQUER etapa nova no futuro, sem precisar de código novo para o caso simples
-- (uma etapa manual, tipo checklist, sem side-effect nenhum no restante do sistema).
--
-- Uma etapa cadastrada com origem='sistema' só faz sentido quando uma rota REAL também chama
-- app/fluxo_service.py::marcar_concluida(...) no momento exato da transição de negócio — nunca
-- infira isso batendo o relógio ou "adivinhando"; é sempre um INSERT/UPDATE explícito disparado
-- por quem já sabe que aquilo aconteceu de verdade (mesmo espírito de toda a trilha de
-- auditoria do sistema: nunca inferir, sempre registrar no momento certo).

PRAGMA foreign_keys = ON;

-- ============================================================
-- CATÁLOGO DE TIPOS DE ETAPA (configurável pelo Administrador/PCP)
-- ============================================================
CREATE TABLE tipos_etapa_fluxo (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entidade_tipo   TEXT NOT NULL CHECK (entidade_tipo IN
                        ('pedido_venda', 'ordem_producao', 'pedido_compra', 'lote')),
    -- Chave estável usada pelo CÓDIGO para reconhecer uma etapa "sistema" específica (ex.:
    -- 'coleta_transportadora') — nunca muda depois de criada, mesmo que o "nome" (exibido)
    -- seja editado. Etapas 'manual' também têm um código, só que nunca lido por código nenhum.
    codigo          TEXT NOT NULL,
    nome            TEXT NOT NULL,
    ordem_padrao    INTEGER NOT NULL DEFAULT 0,
    -- 'sistema': uma rota real do próprio módulo marca conclusão via fluxo_service.py, no
    -- momento exato da transição de negócio (ex.: confirmar coleta). 'manual': só existe um
    -- checklist livre — qualquer usuário com permissão `fluxo.apontar` inicia/conclui pela
    -- tela, sem nenhum outro efeito colateral no sistema.
    origem          TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('sistema', 'manual')),
    status          TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER REFERENCES usuarios(id),
    UNIQUE (entidade_tipo, codigo)
);
CREATE INDEX idx_tipos_etapa_fluxo_entidade ON tipos_etapa_fluxo(entidade_tipo, status);

-- ============================================================
-- INSTÂNCIAS — uma linha por (tipo de etapa, entidade concreta). Materializada de forma
-- PREGUIÇOSA (lazy) pela rota GET .../etapas na primeira vez que alguém abre a tela daquela
-- entidade — assim uma etapa cadastrada AMANHÃ aparece como 'pendente' em pedidos/ordens que
-- já existem hoje, sem precisar de nenhuma migração de backfill.
-- ============================================================
CREATE TABLE fluxo_instancias (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_etapa_fluxo_id     INTEGER NOT NULL REFERENCES tipos_etapa_fluxo(id),
    entidade_id             INTEGER NOT NULL,
    -- Diferente de ordem_producao_etapas.status (Fase 50), que só podia ser 'pendente'/
    -- 'concluida' porque o CHECK já existia e o SQLite não permite alterá-lo — esta tabela é
    -- nova, então já nasce com 'em_andamento' de verdade em vez de precisar derivar isso de
    -- iniciado_em IS NOT NULL no código.
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN
                                ('pendente', 'em_andamento', 'concluida')),
    iniciado_em             TEXT,
    iniciado_por            INTEGER REFERENCES usuarios(id),
    concluido_em            TEXT,
    concluido_por           INTEGER REFERENCES usuarios(id),
    observacao              TEXT,
    UNIQUE (tipo_etapa_fluxo_id, entidade_id)
);
CREATE INDEX idx_fluxo_instancias_tipo_status ON fluxo_instancias(tipo_etapa_fluxo_id, status);

-- Primeira etapa do catálogo: "Separação" de um pedido de venda — hoje não existe nenhuma
-- coluna/status para isso entre 'confirmado' e 'expedido' em pedidos_venda.
INSERT INTO tipos_etapa_fluxo (entidade_tipo, codigo, nome, ordem_padrao, origem) VALUES
    ('pedido_venda', 'separacao', 'Separação', 1, 'manual');
