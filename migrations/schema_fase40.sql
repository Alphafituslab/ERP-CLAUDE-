-- Fase 40 — Conciliação Bancária (Importação de Extrato OFX)
--
-- Duas tabelas novas: um cabeçalho por arquivo importado, e uma linha por
-- transação do extrato. Deliberadamente MUTÁVEIS (diferente das tabelas
-- de baixa de conta a receber/pagar, que são append-only) — a conciliação
-- é um fluxo de trabalho com estado (pendente → conciliada/ignorada, e
-- reversível via "desconciliar"), não um lançamento contábil definitivo.
-- O lançamento definitivo continua sendo a baixa em si
-- (contas_receber_baixas/contas_pagar_baixas, ambas já append-only desde
-- a Fase 6) — esta fase só guarda o VÍNCULO entre uma linha do extrato e
-- uma baixa já existente, nunca cria nem altera a baixa.
CREATE TABLE extratos_bancarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_arquivo        TEXT NOT NULL,
    banco               TEXT,
    conta               TEXT,
    total_transacoes    INTEGER NOT NULL DEFAULT 0,
    importado_em        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    importado_por       INTEGER REFERENCES usuarios(id)
);

CREATE TABLE extrato_transacoes (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    extrato_id                  INTEGER NOT NULL REFERENCES extratos_bancarios(id),
    -- Identificador único da transação dado pelo PRÓPRIO BANCO (tag FITID
    -- do OFX) — permite reimportar o mesmo arquivo (ou um novo extrato
    -- com período sobreposto ao anterior) sem duplicar transação
    -- nenhuma; a UNIQUE abaixo (parcial, só quando não nulo — nem todo
    -- banco preenche FITID) é o que garante isso a nível de banco.
    fitid                       TEXT,
    data                        TEXT NOT NULL,   -- YYYY-MM-DD
    -- Positivo = crédito (dinheiro entrando, candidato a conta a
    -- receber); negativo = débito (dinheiro saindo, candidato a conta a
    -- pagar) — mesma convenção universal de extrato bancário.
    valor                       REAL NOT NULL,
    descricao                   TEXT,
    status                      TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'conciliada', 'ignorada')),
    conta_receber_baixa_id      INTEGER REFERENCES contas_receber_baixas(id),
    conta_pagar_baixa_id        INTEGER REFERENCES contas_pagar_baixas(id),
    conciliado_automaticamente  INTEGER NOT NULL DEFAULT 0 CHECK (conciliado_automaticamente IN (0,1)),
    conciliado_em               TEXT,
    conciliado_por              INTEGER REFERENCES usuarios(id),
    ignorado_motivo             TEXT,
    criado_em                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_extrato_transacoes_extrato ON extrato_transacoes(extrato_id);
CREATE INDEX idx_extrato_transacoes_status ON extrato_transacoes(status);
CREATE UNIQUE INDEX idx_extrato_transacoes_fitid_unico ON extrato_transacoes(fitid) WHERE fitid IS NOT NULL;
