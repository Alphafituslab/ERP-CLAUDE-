-- Alphafitus OS — Fase 14 (Estorno de Baixa: Contas a Receber e a Pagar)
-- Aplicado DEPOIS de schema_fase13.sql, nunca remove nem altera nada das
-- fases anteriores (os ALTER TABLE abaixo só ADICIONAM colunas novas,
-- opcionais, com DEFAULT NULL, então nenhuma linha existente quebra).
-- Mesmas notas de portabilidade para PostgreSQL das fases anteriores se
-- aplicam aqui.
--
-- Contexto: desde a Fase 6, as próprias mensagens de erro dos triggers
-- append-only de `contas_receber_baixas`/`contas_pagar_baixas` já
-- diziam "cancele/estorne com um novo lançamento se necessário" — mas
-- esse fluxo de estorno nunca tinha sido implementado (só o de cancelar
-- uma conta SEM nenhuma baixa, que é um caso bem mais simples). Esta
-- fase fecha essa lacuna: uma baixa registrada por engano (valor errado,
-- forma de pagamento errada, lançada na conta errada) agora pode ser
-- CORRIGIDA sem violar o append-only e sem apagar o histórico original —
-- exatamente como uma nota fiscal de devolução não apaga a nota de
-- venda, ela só referencia a original e a neutraliza.
--
-- Mecanismo: um estorno é uma linha NOVA na mesma tabela de baixas
-- (nunca um UPDATE/DELETE na linha original, que continua bloqueada
-- pelos triggers já existentes desde a Fase 6), com o MESMO valor da
-- baixa original, mas marcada via `estorno_de_id` (auto-referência).  O
-- saldo em aberto de uma conta passa a ser:
--     valor_total - SUM(baixas normais) + SUM(baixas de estorno)
-- (na prática, `_total_baixado()` em app/routes/financeiro.py já soma
-- baixas normais e SUBTRAI estornos) — nunca um número guardado à
-- parte, mesmo princípio de "saldo sempre recalculado" usado em toda
-- fase anterior. `motivo_estorno` é obrigatório em código (não em
-- CHECK, para não impedir baixas normais de não ter esse campo) e fica
-- gravado na própria linha de estorno, junto com o evento de auditoria.

PRAGMA foreign_keys = ON;

ALTER TABLE contas_receber_baixas ADD COLUMN estorno_de_id INTEGER REFERENCES contas_receber_baixas(id);
ALTER TABLE contas_receber_baixas ADD COLUMN motivo_estorno TEXT;

ALTER TABLE contas_pagar_baixas ADD COLUMN estorno_de_id INTEGER REFERENCES contas_pagar_baixas(id);
ALTER TABLE contas_pagar_baixas ADD COLUMN motivo_estorno TEXT;

-- Nenhuma tabela nova, nenhum trigger novo: os triggers append-only já
-- existentes desde a Fase 6 (`cr_baixas_bloqueia_update`/`_delete` e
-- `cp_baixas_bloqueia_update`/`_delete`) já cobrem estas colunas novas
-- automaticamente, porque bloqueiam QUALQUER UPDATE/DELETE na tabela —
-- inclusive numa linha de estorno recém-inserida.
