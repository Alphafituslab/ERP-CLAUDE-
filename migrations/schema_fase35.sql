-- Fase 35 — Agendamento/Cadência Automática de Contagens Cíclicas
--
-- Hoje (Fase 17) toda contagem de inventário — geral ou cíclica — só
-- nasce quando alguém com a permissão `estoque.contagem` clica em "Nova
-- contagem". Esta fase acrescenta uma segunda forma de nascer: uma
-- REGRA cadastrada uma vez ("todo dia", "toda segunda", "todo dia 5 do
-- mês", com ou sem uma amostra percentual de itens no caso cíclico) que
-- gera a contagem sozinha quando o dia certo chega — sem exigir que
-- ninguém lembre de criar manualmente.
--
-- `agendamentos_contagem` guarda a REGRA (não as contagens geradas por
-- ela — essas continuam vivendo em `contagens_inventario`, só que agora
-- rotuladas com `origem` e `agendamento_id`, ver ALTER abaixo).
CREATE TABLE agendamentos_contagem (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    unidade_id          INTEGER NOT NULL REFERENCES unidades(id),
    tipo                TEXT NOT NULL CHECK (tipo IN ('ciclica', 'geral')),
    -- Só usado (e só exigido) quando tipo='ciclica': tamanho da amostra
    -- ALEATÓRIA de combinações lote+posição sorteada a cada geração.
    -- Contagem 'geral' sempre inclui tudo — não há o que sortear, então
    -- fica NULL.
    percentual_itens    REAL CHECK (percentual_itens IS NULL OR (percentual_itens > 0 AND percentual_itens <= 100)),
    cadencia            TEXT NOT NULL CHECK (cadencia IN ('diaria', 'semanal', 'mensal')),
    -- 0 = segunda-feira ... 6 = domingo (convenção do Python `date.weekday()`,
    -- documentada na tela para não haver ambiguidade com "0 = domingo",
    -- comum em outros sistemas).
    dia_semana          INTEGER CHECK (dia_semana IS NULL OR (dia_semana BETWEEN 0 AND 6)),
    -- Se o mês não tiver esse dia (ex.: 31 em abril), a geração ocorre no
    -- ÚLTIMO dia daquele mês em vez de falhar ou pular o mês inteiro.
    dia_mes             INTEGER CHECK (dia_mes IS NULL OR (dia_mes BETWEEN 1 AND 31)),
    ativo               INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    observacao          TEXT,
    criado_por          INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    atualizado_por      INTEGER REFERENCES usuarios(id),
    atualizado_em       TEXT,
    -- Data (YYYY-MM-DD) da última geração — usada só para nunca gerar
    -- duas contagens no mesmo dia para o mesmo agendamento, mesmo que a
    -- tela de Estoque seja aberta várias vezes naquele dia.
    ultima_geracao_em   TEXT,
    ultima_contagem_id  INTEGER REFERENCES contagens_inventario(id)
);

CREATE INDEX idx_agendamentos_contagem_unidade ON agendamentos_contagem(unidade_id);
CREATE INDEX idx_agendamentos_contagem_ativo ON agendamentos_contagem(ativo);

-- Rastreabilidade total: qualquer contagem gerada por um agendamento
-- carrega a marca de onde veio. `origem='manual'` continua sendo o
-- padrão para toda contagem já existente e para toda contagem nova
-- criada do jeito de sempre (botão "Nova contagem").
ALTER TABLE contagens_inventario ADD COLUMN origem TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('manual', 'agendamento'));
-- ON DELETE SET NULL: excluir a REGRA (o agendamento) nunca deveria
-- apagar nem bloquear a exclusão de uma contagem já gerada por ela — a
-- contagem em si (e o rótulo `origem='agendamento'`, que não depende
-- desta FK) continua intacta, só perde o vínculo com uma regra que já
-- não existe mais.
ALTER TABLE contagens_inventario ADD COLUMN agendamento_id INTEGER REFERENCES agendamentos_contagem(id) ON DELETE SET NULL;
