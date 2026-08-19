-- Alphafitus OS — Fase 22 (Aprovação Dupla para Estorno de Baixa Acima de
-- um Valor de Alçada)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas. Mesmas notas de portabilidade para PostgreSQL das fases
-- anteriores se aplicam aqui.
--
-- Desde a Fase 14, estornar uma baixa (contas a receber ou a pagar) exige
-- só um motivo e a permissão dedicada (`estornar_baixa_receber`/
-- `estornar_baixa_pagar`) — uma única pessoa decide e o estorno vale na
-- hora. O catálogo de permissões desde a Fase 6 já marca essas duas (e
-- outras ações sensíveis) com `exige_dupla_aprovacao=1`, mas até aqui
-- esse campo era só informativo: nenhuma rota realmente aplicava uma
-- segunda aprovação.
--
-- Esta fase fecha essa lacuna com uma ALÇADA POR VALOR (não por
-- percentual, que não faz sentido pra dinheiro do jeito que fez pra
-- saldo físico na Fase 21): estornos de baixas ACIMA de
-- `LIMIAR_VALOR_ESTORNO_DUPLA_APROVACAO` (ver `app/routes/financeiro.py`)
-- não revertem na hora — ficam como uma SOLICITAÇÃO pendente até um
-- segundo usuário (com a permissão nova `aprovar_estorno_receber`/
-- `aprovar_estorno_pagar`, diferente de quem solicitou) aprovar ou
-- rejeitar. Estornos abaixo do limiar continuam revertendo na hora,
-- exatamente como desde a Fase 14 — comportamento aditivo, o caso comum
-- não muda.
--
-- As baixas em si (`contas_receber_baixas`/`contas_pagar_baixas`)
-- continuam 100% append-only (trigger de bloqueio de UPDATE/DELETE desde
-- a Fase 6) — por isso a solicitação pendente PRECISA morar numa tabela
-- própria e mutável (como as duas abaixo), nunca como uma coluna extra
-- numa baixa já lançada.

PRAGMA foreign_keys = ON;

CREATE TABLE estornos_pendentes_receber (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    baixa_id                INTEGER NOT NULL REFERENCES contas_receber_baixas(id),
    conta_receber_id        INTEGER NOT NULL REFERENCES contas_receber(id),
    valor                   REAL NOT NULL,
    motivo_solicitacao      TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovado', 'rejeitado')),
    solicitado_por          INTEGER REFERENCES usuarios(id),
    solicitado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decidido_por            INTEGER REFERENCES usuarios(id),
    decidido_em             TEXT,
    motivo_rejeicao         TEXT,
    baixa_estorno_gerada_id INTEGER REFERENCES contas_receber_baixas(id)
);

CREATE INDEX idx_estornos_pendentes_receber_status ON estornos_pendentes_receber(status);
CREATE INDEX idx_estornos_pendentes_receber_baixa ON estornos_pendentes_receber(baixa_id);

CREATE TABLE estornos_pendentes_pagar (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    baixa_id                INTEGER NOT NULL REFERENCES contas_pagar_baixas(id),
    conta_pagar_id          INTEGER NOT NULL REFERENCES contas_pagar(id),
    valor                   REAL NOT NULL,
    motivo_solicitacao      TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovado', 'rejeitado')),
    solicitado_por          INTEGER REFERENCES usuarios(id),
    solicitado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decidido_por            INTEGER REFERENCES usuarios(id),
    decidido_em             TEXT,
    motivo_rejeicao         TEXT,
    baixa_estorno_gerada_id INTEGER REFERENCES contas_pagar_baixas(id)
);

CREATE INDEX idx_estornos_pendentes_pagar_status ON estornos_pendentes_pagar(status);
CREATE INDEX idx_estornos_pendentes_pagar_baixa ON estornos_pendentes_pagar(baixa_id);
