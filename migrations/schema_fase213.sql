-- Alphafitus OS — Fase 213 (Precificação: margem LÍQUIDA desejada, não bruta)
--
-- Pedido do usuário 2026-09-26, no mesmo dia da Fase 212: o modo "aplicar
-- margem desejada" pedia uma margem BRUTA (markup sobre o preço que só
-- cobre custo+tributos+despesas, calculada ANTES de descontar comissão e
-- IRPJ/CSLL) — "quero ter a margem total não a bruta... aplicando todos os
-- custos e descontando tudo, qual é o lucro limpo da empresa". Ou seja, ele
-- quer INFORMAR a margem líquida (o que sobra de verdade, depois de TUDO)
-- e o sistema descobrir o preço de venda necessário pra chegar nela — não
-- o contrário.
--
-- `margem_bruta_pct` (Fase 212) fica no schema mas para de ser usada como
-- ENTRADA no modo "markup" — nenhum dado real dependia dela ainda (única
-- linha criada nesta mesma tarde foi um teste, já arquivado). O valor de
-- margem bruta continua sendo CALCULADO e devolvido pela API como
-- informação (não perguntado no formulário), então a coluna não precisa
-- ser removida (SQLite não altera CHECK/coluna sem reconstruir a tabela —
-- sem necessidade aqui, é só ADD COLUMN).
PRAGMA foreign_keys = ON;

ALTER TABLE precificacoes ADD COLUMN margem_liquida_desejada_pct REAL;
