-- Fase 53 — Recall: Decisão sobre Pedidos Já Expedidos
--
-- A Fase 8 deu à Qualidade o traversal de rastreabilidade (`simulacoes_recall`)
-- e a Fase 16 deu o bloqueio em massa dos lotes afetados
-- (`bloquear_em_massa`). Mas as duas deliberadamente NÃO tocam em pedidos
-- de venda já EXPEDIDOS do lote sob investigação — o `resultado` da
-- simulação só lista esses pedidos em `resumo.pedidos_expedidos`, como
-- informação para decisão manual de quem está conduzindo o recall (ver
-- docstring de `bloquear_em_massa` em app/routes/rastreabilidade.py).
--
-- Essa lacuna é deliberada, não um esquecimento: um pedido expedido já
-- teve a saída de estoque registrada (`movimentacoes_estoque`) e muitas
-- vezes já tem conta a receber baixada (Fase 6) — "cancelar" esse pedido
-- não é o mesmo problema que cancelar um pedido "confirmado" (que só
-- solta uma reserva). `cancelar_pedido_internamente` (comercial.py) por
-- isso rejeita explicitamente pedidos 'expedido', apontando para uma
-- "devolução como fluxo separado" — uma reversão de estoque física, uma
-- nota de crédito, ou uma simples notificação ao cliente sem
-- movimentação nenhuma, dependendo do caso concreto. Não existe (e esta
-- fase não cria) uma rotina automática de estorno de expedição: seria uma
-- mudança de escopo muito maior, tocando regras já testadas e com
-- implicações de reversão de estoque que precisam ser tratadas com
-- cuidado, uma de cada vez, pelas rotas já existentes em comercial.py e
-- financeiro.py.
--
-- O que ESTA fase resolve é mais estreito e mais seguro: dar à Qualidade
-- um jeito de REGISTRAR a decisão tomada para cada pedido expedido
-- afetado por um recall — "vamos notificar o cliente", "vamos aguardar a
-- devolução física", "vamos emitir nota de crédito", "vamos cancelar o
-- pedido (a cancelar de fato continua sendo feito à parte, pela tela de
-- Comercial)", ou "decidimos não tomar nenhuma ação". Isso fecha o ciclo
-- de conformidade do recall — hoje, depois de rodar uma simulação, não
-- fica registrado em lugar nenhum o que foi de fato decidido para cada
-- cliente afetado, só o que o sistema calculou que estava em risco.
--
-- Assim como `simulacoes_recall`, `decisoes_recall_pedido` é um registro
-- HISTÓRICO de conformidade — cada linha é um evento de decisão num ponto
-- do tempo, não um "status atual" a ser sobrescrito. Isso é deliberado:
-- decisões evoluem (ex.: hoje "aguardar devolução", depois de duas
-- semanas sem retorno do cliente vira "cancelar pedido") e a Qualidade
-- pode precisar demonstrar numa auditoria externa (ANVISA) TODO o
-- histórico de decisões tomadas para aquele pedido, não só a mais
-- recente. Por isso a tabela é append-only (mesmo padrão de
-- `simulacoes_recall`, `auditoria`, `certificados_analise`): múltiplas
-- decisões para o mesmo par (simulação, pedido) ao longo do tempo são
-- esperadas e válidas — quem quiser saber "qual é a decisão atual" olha a
-- última linha por `criado_em` para aquele pedido.

PRAGMA foreign_keys = ON;

-- ============================================================
-- DECISÕES SOBRE PEDIDOS JÁ EXPEDIDOS AFETADOS POR UM RECALL
-- ============================================================
CREATE TABLE decisoes_recall_pedido (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacao_recall_id     INTEGER NOT NULL REFERENCES simulacoes_recall(id),
    pedido_venda_id         INTEGER NOT NULL REFERENCES pedidos_venda(id),
    tipo_decisao            TEXT NOT NULL CHECK (tipo_decisao IN (
                                'notificar_cliente',
                                'aguardar_devolucao',
                                'gerar_nota_credito',
                                'cancelar_pedido',
                                'sem_acao'
                            )),
    motivo                  TEXT NOT NULL,
    observacao              TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_decisoes_recall_pedido_simulacao ON decisoes_recall_pedido(simulacao_recall_id);
CREATE INDEX idx_decisoes_recall_pedido_pedido ON decisoes_recall_pedido(pedido_venda_id);

CREATE TRIGGER decisoes_recall_pedido_bloqueia_update
BEFORE UPDATE ON decisoes_recall_pedido
BEGIN
    SELECT RAISE(ABORT, 'decisoes_recall_pedido é append-only: cada linha é um registro histórico de uma decisão tomada num ponto do tempo e nunca pode ser editada. Registre uma nova decisão se ela mudou.');
END;

CREATE TRIGGER decisoes_recall_pedido_bloqueia_delete
BEFORE DELETE ON decisoes_recall_pedido
BEGIN
    SELECT RAISE(ABORT, 'decisoes_recall_pedido é append-only: cada linha é um registro histórico de uma decisão de recall e nunca pode ser apagada.');
END;
