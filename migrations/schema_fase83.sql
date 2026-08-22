-- Alphafitus OS — Fase 83 (Aprovação Financeira obrigatória em todo Pedido de Venda)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Antes desta fase, `pedidos_venda_confirmacoes_pendentes` (Fase 63) só ganhava uma linha
-- quando o pedido ultrapassava o limite de crédito do cliente — sem limite configurado, ou
-- dentro do limite, a confirmação acontecia na hora. A pedido explícito do usuário, TODO
-- pedido agora passa por essa mesma fila de aprovação antes de reservar estoque de verdade,
-- não só os que estouram o limite.
--
-- `limite_credito_no_momento` continua NOT NULL (SQLite não permite relaxar um NOT NULL sem
-- recriar a tabela inteira) — quando o cliente não tem limite configurado, o código grava `0`
-- ali como valor de preenchimento, nunca um "limite de verdade". Por isso este novo campo
-- `motivo_solicitacao` existe: é ele, não o valor de `limite_credito_no_momento`, que a tela
-- deve usar para explicar por que a aprovação foi pedida ('acima_do_limite' vs.
-- 'aprovacao_obrigatoria_padrao') — nunca interprete `limite_credito_no_momento = 0` como "sem
-- limite configurado", porque um cliente pode ter um limite configurado que é literalmente zero.

PRAGMA foreign_keys = ON;

ALTER TABLE pedidos_venda_confirmacoes_pendentes ADD COLUMN motivo_solicitacao TEXT;
