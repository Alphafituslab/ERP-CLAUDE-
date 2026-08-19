-- Alphafitus OS — Fase 31 (Aprovação Dupla para o REGISTRO de uma Baixa
-- Acima de um Valor de Alçada)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas. Mesmas notas de portabilidade para PostgreSQL das fases
-- anteriores se aplicam aqui.
--
-- A Fase 22 aplicou dupla aprovação só para o ESTORNO de uma baixa acima
-- de um valor de alçada — registrar uma baixa NOVA de valor alto
-- continuava exigindo só a permissão comum (`registrar_baixa_receber`/
-- `registrar_baixa_pagar`), sem nenhuma segunda aprovação antes de valer,
-- mesmo o catálogo de permissões já marcando as duas como
-- `exige_dupla_aprovacao=1` desde a Fase 6. Esta fase fecha essa lacuna,
-- espelhando exatamente o mesmo desenho da Fase 22: acima de
-- `LIMIAR_VALOR_BAIXA_DUPLA_APROVACAO` (ver `app/routes/financeiro.py`),
-- registrar uma baixa não entra direto no ledger — vira uma SOLICITAÇÃO
-- pendente até um segundo usuário (permissão nova `aprovar_baixa_receber`/
-- `aprovar_baixa_pagar`, diferente de quem solicitou) aprovar ou
-- rejeitar. Abaixo do limiar, o comportamento é idêntico ao de sempre:
-- a baixa entra direto no ledger, sem nenhuma aprovação extra.
--
-- Por que uma tabela própria em vez de uma coluna em
-- `contas_receber_baixas`/`contas_pagar_baixas`: essas duas tabelas são
-- ledgers 100% append-only (trigger de bloqueio de UPDATE/DELETE desde a
-- Fase 6) — uma baixa só existe ali depois de já estar decidida (aprovada
-- de fato). Uma SOLICITAÇÃO ainda pendente, que pode ser aprovada,
-- rejeitada, e cujo status muda ao longo do tempo, precisa morar numa
-- tabela própria e mutável — mesmo raciocínio já usado em
-- `estornos_pendentes_receber`/`estornos_pendentes_pagar` na Fase 22.

PRAGMA foreign_keys = ON;

CREATE TABLE baixas_pendentes_receber (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_receber_id   INTEGER NOT NULL REFERENCES contas_receber(id),
    valor              REAL NOT NULL CHECK (valor > 0),
    forma_pagamento    TEXT NOT NULL,
    data_pagamento     TEXT NOT NULL,
    observacao         TEXT,
    status             TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovado', 'rejeitado')),
    solicitado_por     INTEGER REFERENCES usuarios(id),
    solicitado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decidido_por       INTEGER REFERENCES usuarios(id),
    decidido_em        TEXT,
    motivo_rejeicao    TEXT,
    baixa_gerada_id    INTEGER REFERENCES contas_receber_baixas(id)
);

CREATE INDEX idx_baixas_pendentes_receber_status ON baixas_pendentes_receber(status);
CREATE INDEX idx_baixas_pendentes_receber_conta ON baixas_pendentes_receber(conta_receber_id);

CREATE TABLE baixas_pendentes_pagar (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_pagar_id     INTEGER NOT NULL REFERENCES contas_pagar(id),
    valor              REAL NOT NULL CHECK (valor > 0),
    forma_pagamento    TEXT NOT NULL,
    data_pagamento     TEXT NOT NULL,
    observacao         TEXT,
    status             TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovado', 'rejeitado')),
    solicitado_por     INTEGER REFERENCES usuarios(id),
    solicitado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decidido_por       INTEGER REFERENCES usuarios(id),
    decidido_em        TEXT,
    motivo_rejeicao    TEXT,
    baixa_gerada_id    INTEGER REFERENCES contas_pagar_baixas(id)
);

CREATE INDEX idx_baixas_pendentes_pagar_status ON baixas_pendentes_pagar(status);
CREATE INDEX idx_baixas_pendentes_pagar_conta ON baixas_pendentes_pagar(conta_pagar_id);
