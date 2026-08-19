-- Alphafitus OS — Fase 17 (Contagem de Inventário Cíclico/Geral)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas. Mesmas notas de portabilidade para PostgreSQL das fases
-- anteriores se aplicam aqui.
--
-- Até aqui, uma divergência de inventário físico só podia ser corrigida
-- via "Ajustar" na tela Estoque (Fase 4) — o que já garante motivo
-- obrigatório e histórico completo (via `movimentacoes_estoque`), mas era
-- sempre um lançamento avulso, um lote/posição por vez, sem um fluxo
-- guiado de "iniciar contagem, ir contando o que encontrar, e no fim
-- gerar os ajustes de uma vez". Esta fase adiciona esse fluxo por cima do
-- que já existia — nenhuma tabela ou trigger da Fase 4 muda.
--
-- Duas tabelas, no mesmo padrão de cabeçalho+itens já usado por
-- `ordens_producao`/`ordem_producao_consumo` (Fase 3) e
-- `pedidos_venda`/`pedido_venda_itens` (Fase 5): um cabeçalho mutável que
-- representa o ESTADO ATUAL de um processo em andamento (não um ledger
-- imutável — por isso, diferente de `movimentacoes_estoque`, estas duas
-- tabelas NÃO têm trigger de bloqueio de UPDATE), e uma linha por
-- item contado. O ajuste em si, quando a contagem é concluída, sempre
-- vira uma linha nova em `movimentacoes_estoque` (a mesma rota interna
-- `registrar_ajuste_interno` da Fase 4/17) — o ledger append-only
-- continua sendo a única fonte de verdade sobre saldo físico.

PRAGMA foreign_keys = ON;

CREATE TABLE contagens_inventario (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    unidade_id              INTEGER NOT NULL REFERENCES unidades(id),
    tipo                    TEXT NOT NULL CHECK (tipo IN ('ciclica', 'geral')),
    status                  TEXT NOT NULL DEFAULT 'em_andamento' CHECK (status IN ('em_andamento', 'concluida', 'cancelada')),
    observacao              TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    concluida_em            TEXT,
    concluida_por           INTEGER REFERENCES usuarios(id),
    cancelada_em            TEXT,
    cancelada_por           INTEGER REFERENCES usuarios(id),
    motivo_cancelamento     TEXT
);

CREATE INDEX idx_contagens_unidade ON contagens_inventario(unidade_id);
CREATE INDEX idx_contagens_status ON contagens_inventario(status);

-- `saldo_sistema_no_inicio` é um SNAPSHOT deliberado (não recalculado
-- depois): é o "quanto o sistema dizia que tinha" no momento em que o
-- item entrou na contagem, para comparar com o que foi fisicamente
-- contado — se recalculássemos na hora de concluir, um ajuste ou
-- movimentação lançado por outro processo NO MEIO da contagem
-- mascararia a divergência real que a contagem física encontrou.
CREATE TABLE contagens_inventario_itens (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    contagem_id                 INTEGER NOT NULL REFERENCES contagens_inventario(id),
    lote_id                     INTEGER NOT NULL REFERENCES lotes(id),
    posicao_id                  INTEGER NOT NULL REFERENCES posicoes_estoque(id),
    saldo_sistema_no_inicio     REAL NOT NULL,
    quantidade_contada          REAL,
    status                      TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'contado')),
    contado_em                  TEXT,
    contado_por                 INTEGER REFERENCES usuarios(id),
    ajuste_gerado_id            INTEGER REFERENCES movimentacoes_estoque(id),
    adicionado_em                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    adicionado_por               INTEGER REFERENCES usuarios(id),
    UNIQUE (contagem_id, lote_id, posicao_id)
);

CREATE INDEX idx_contagens_itens_contagem ON contagens_inventario_itens(contagem_id);
CREATE INDEX idx_contagens_itens_status ON contagens_inventario_itens(status);
