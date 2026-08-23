-- Alphafitus OS — Fase 102 (Aprovação Financeira de Cadastro de Cliente)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário: "ao cadastrar um cliente novo ele só fica apto a comprar se o financeiro
-- liberar o cadastro com a avaliação financeira". Diferente da Fase 83 (aprovação obrigatória
-- de CADA PEDIDO), esta é uma aprovação do CLIENTE em si, feita uma vez — depois de aprovado, os
-- pedidos daquele cliente seguem o fluxo normal (que já exige aprovação financeira própria,
-- Fase 83); a trava aqui é ANTES disso, na hora de CONFIRMAR o primeiro (e qualquer) pedido de
-- um cliente ainda não aprovado.
--
-- `aprovacao_financeira_status` começa 'pendente' por padrão (`DEFAULT 'pendente'`, para todo
-- cliente CRIADO DE AGORA EM DIANTE) — mas o UPDATE logo abaixo marca todo cliente que JÁ
-- EXISTIA antes desta fase como 'aprovado' de uma vez: ninguém que já era cliente ativo, já
-- comprando normalmente, fica subitamente travado por uma regra nova que não existia quando foi
-- cadastrado. Só cliente cadastrado a partir de agora nasce 'pendente' de verdade.

PRAGMA foreign_keys = ON;

ALTER TABLE clientes ADD COLUMN aprovacao_financeira_status TEXT NOT NULL DEFAULT 'pendente'
    CHECK (aprovacao_financeira_status IN ('pendente', 'aprovado', 'reprovado'));
ALTER TABLE clientes ADD COLUMN aprovacao_financeira_decidido_por INTEGER REFERENCES usuarios(id);
ALTER TABLE clientes ADD COLUMN aprovacao_financeira_decidido_em TEXT;
ALTER TABLE clientes ADD COLUMN aprovacao_financeira_motivo TEXT;

UPDATE clientes SET aprovacao_financeira_status = 'aprovado' WHERE aprovacao_financeira_status = 'pendente';
