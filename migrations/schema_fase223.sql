-- Alphafitus OS — Fase 223 (Orçamentos: aprovação interna)
--
-- Pedido do usuário 2026-09-26: além da aprovação do CLIENTE (portal
-- público, Fase 197 — o cliente aprova ou recusa a proposta) e da
-- aprovação FINANCEIRA do cadastro do cliente (Fase 102 —
-- `clientes.aprovacao_financeira_status`), agora existe uma terceira
-- aprovação, INTERNA: alguém revisa o orçamento antes/depois dele ser
-- criado. "Hoje ainda não sei o setor, mas por enquanto deve ser comigo" —
-- reaproveita o mesmo `usuarios.usuario_master` já usado pela Agenda
-- (Fase 202), em vez de inventar um cargo/setor novo que ainda não existe
-- de verdade — só o Clayton por enquanto, mudar quando houver um setor
-- definido é trocar o critério de UMA função no backend, não a modelagem.
--
-- Todo orçamento já nasce "pendente" (pedido do usuário: "mesmo que eu
-- tenha feito o orçamento deve enviar" — a solicitação acontece sempre,
-- não é opt-in). "Enviar novamente solicitando revisar" volta o status pra
-- pendente de novo (mesmo se já tinha sido aprovado) e pode marcar
-- urgente — pedido explícito do usuário.
PRAGMA foreign_keys = ON;

ALTER TABLE orcamentos ADD COLUMN aprovacao_interna_status TEXT NOT NULL DEFAULT 'pendente'
    CHECK (aprovacao_interna_status IN ('pendente', 'aprovada'));
ALTER TABLE orcamentos ADD COLUMN aprovacao_interna_urgente INTEGER NOT NULL DEFAULT 0
    CHECK (aprovacao_interna_urgente IN (0, 1));
ALTER TABLE orcamentos ADD COLUMN aprovacao_interna_observacao TEXT;
ALTER TABLE orcamentos ADD COLUMN aprovacao_interna_aprovado_por INTEGER REFERENCES usuarios(id);
ALTER TABLE orcamentos ADD COLUMN aprovacao_interna_aprovado_em TEXT;
ALTER TABLE orcamentos ADD COLUMN aprovacao_interna_solicitado_em TEXT;

UPDATE orcamentos SET aprovacao_interna_solicitado_em = criado_em WHERE aprovacao_interna_solicitado_em IS NULL;
