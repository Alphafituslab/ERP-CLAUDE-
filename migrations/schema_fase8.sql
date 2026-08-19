-- Alphafitus OS — Fase 8 (Rastreabilidade Avançada / Simulação de Recall)
-- Aplicado DEPOIS de schema.sql, schema_fase2.sql, schema_fase3.sql,
-- schema_fase4.sql, schema_fase5.sql, schema_fase6.sql e schema_fase7
-- (que não existe — a Fase 7 não precisou de nenhuma migração, era só
-- agregação). Não altera nem remove nada das fases anteriores.
-- Mesmas notas de portabilidade para PostgreSQL das fases anteriores se
-- aplicam aqui.
--
-- Esta fase fecha o requisito de rastreabilidade total exigido pelas boas
-- práticas de fabricação (GMP): dado qualquer lote, ser capaz de
-- responder, em minutos, duas perguntas — "de onde veio o material deste
-- lote (matérias-primas e fornecedores, atravessando quantos níveis de
-- produção intermediária forem necessários)" e "para onde este lote foi
-- (outros lotes produzidos a partir dele, e finalmente quais pedidos e
-- clientes o receberam)". A resposta em si NÃO precisa de tabela nova —
-- é um traversal recursivo sobre `ordem_producao_consumo` (Fase 3) e
-- `pedido_venda_reservas` (Fase 5), as mesmas tabelas de ledger que já
-- existem, na mesma filosofia de "nunca guardar um valor derivado que
-- poderia dessincronizar" já usada em todas as fases anteriores.
--
-- O que ESTA fase adiciona é só o registro histórico de que uma
-- investigação de recall foi executada: `simulacoes_recall` é um
-- snapshot IMUTÁVEL (append-only, como `auditoria` e
-- `certificados_analise`) do resultado do traversal no momento em que a
-- Qualidade decidiu investigar — diferente do resto do sistema, aqui
-- guardar o valor calculado é o comportamento CORRETO: um recall é uma
-- decisão registrada num ponto do tempo, para fins de conformidade
-- (auditoria externa, ANVISA etc.), não um saldo que deveria sempre
-- refletir o estado atual do banco. Se o estado do banco mudar depois
-- (ex.: mais um pedido do mesmo lote for expedido), isso NÃO deve alterar
-- retroativamente o que já foi registrado como "o que sabíamos quando
-- investigamos" — precisaria de uma NOVA simulação para capturar isso.

PRAGMA foreign_keys = ON;

-- ============================================================
-- SIMULAÇÕES DE RECALL — snapshot append-only
-- ============================================================
CREATE TABLE simulacoes_recall (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                      TEXT NOT NULL UNIQUE,
    lote_id                     INTEGER NOT NULL REFERENCES lotes(id),
    motivo                      TEXT NOT NULL,
    total_lotes_upstream        INTEGER NOT NULL DEFAULT 0,
    total_lotes_downstream      INTEGER NOT NULL DEFAULT 0,
    total_pedidos_expedidos     INTEGER NOT NULL DEFAULT 0,
    total_clientes_afetados     INTEGER NOT NULL DEFAULT 0,
    resultado                   TEXT NOT NULL,  -- JSON completo do traversal (árvores upstream/downstream, pedidos, clientes) no momento da simulação
    criado_em                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por                  INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_simulacoes_recall_lote ON simulacoes_recall(lote_id);
CREATE INDEX idx_simulacoes_recall_criado_em ON simulacoes_recall(criado_em);

CREATE TRIGGER simulacoes_recall_bloqueia_update
BEFORE UPDATE ON simulacoes_recall
BEGIN
    SELECT RAISE(ABORT, 'simulacoes_recall é append-only: uma simulação de recall é um registro histórico de conformidade e nunca pode ser editada. Registre uma nova simulação se precisar de números atualizados.');
END;

CREATE TRIGGER simulacoes_recall_bloqueia_delete
BEFORE DELETE ON simulacoes_recall
BEGIN
    SELECT RAISE(ABORT, 'simulacoes_recall é append-only: uma simulação de recall é um registro histórico de conformidade e nunca pode ser apagada.');
END;
