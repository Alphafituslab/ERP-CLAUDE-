-- Alphafitus OS — Fase 21 (Aprovação de Segundo Usuário para Ajuste de
-- Contagem com Divergência Grande)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas. Mesmas notas de portabilidade para PostgreSQL das fases
-- anteriores se aplicam aqui.
--
-- Até aqui (Fase 17), TODA divergência encontrada numa contagem de
-- inventário virava um ajuste automático no momento de concluir a
-- contagem, não importa o tamanho da diferença — a mesma pessoa que
-- conduziu a contagem inteira (com `estoque.ajustar`) também autorizava,
-- sozinha, ajustes potencialmente grandes de saldo. Esta fase adiciona um
-- segundo filtro: divergências GRANDES (ver `LIMIAR_PERCENTUAL_DIVERGENCIA_
-- GRANDE` em `app/routes/estoque.py`) não geram o ajuste na hora — ficam
-- "pendente" até um segundo usuário (com a permissão nova
-- `estoque.aprovar_ajuste_contagem`, diferente de quem registrou aquela
-- contagem física) aprovar ou rejeitar. Divergências pequenas continuam
-- sendo ajustadas automaticamente ao concluir, exatamente como antes —
-- comportamento aditivo, não muda nada do que já existia para o caso
-- comum.
--
-- Só adiciona colunas na tabela de itens de contagem já existente (Fase
-- 17) — nenhuma tabela nova, e as colunas novas têm DEFAULT compatível
-- com toda linha já existente (`aprovacao_status='nao_aplicavel'`, as
-- demais NULL), então bancos com contagens antigas continuam válidos sem
-- nenhuma migração de dado.

PRAGMA foreign_keys = ON;

ALTER TABLE contagens_inventario_itens
    ADD COLUMN aprovacao_status TEXT NOT NULL DEFAULT 'nao_aplicavel'
    CHECK (aprovacao_status IN ('nao_aplicavel', 'pendente', 'aprovado', 'rejeitado'));

ALTER TABLE contagens_inventario_itens ADD COLUMN aprovado_por INTEGER REFERENCES usuarios(id);
ALTER TABLE contagens_inventario_itens ADD COLUMN aprovado_em TEXT;
ALTER TABLE contagens_inventario_itens ADD COLUMN motivo_rejeicao TEXT;

CREATE INDEX idx_contagens_itens_aprovacao_status ON contagens_inventario_itens(aprovacao_status);
