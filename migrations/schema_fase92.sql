-- Alphafitus OS — Fase 92 (2FA obrigatório por perfil)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário: "máxima proteção" no sistema, com 2FA obrigatório para os perfis mais
-- sensíveis (Administrador e Financeiro, que decidiu como recomendado). O 2FA (TOTP, RFC 6238)
-- já existe desde antes desta fase — cada usuário podia ativá-lo por conta própria em "Minha
-- Conta" (`usuarios.dois_fatores_ativo`/`dois_fatores_secret`, `app/security.py`). O que faltava
-- era a possibilidade de EXIGIR isso de certos perfis, em vez de deixar 100% opcional.
--
-- `exige_2fa` é uma propriedade do PERFIL, não do usuário — assim, se amanhã alguém for
-- promovido a um perfil que exige 2FA, a exigência já vale a partir do próximo login, sem
-- precisar de nenhuma migração de dado por usuário. Padrão 0 (não exige) para não quebrar
-- nenhum perfil customizado já existente; `seed.py` liga explicitamente para "Administrador" e
-- "Financeiro" (ver PERFIS_QUE_EXIGEM_2FA em seed.py).
--
-- ENFORCEMENT: `app/context.py::get_current_user` passa a bloquear (403,
-- codigo="2fa_obrigatorio_pendente") toda rota que não esteja na lista branca mínima
-- (`/api/v1/auth/me`, `/api/v1/auth/logout`, `/api/v1/auth/2fa/setup`,
-- `/api/v1/auth/2fa/confirmar`) quando o usuário pertence a um perfil com `exige_2fa = 1` e
-- ainda não tem `dois_fatores_ativo = 1` — o login em si continua funcionando normalmente
-- (senão a pessoa nunca conseguiria chegar na tela de configurar o 2FA), só o RESTO da API fica
-- bloqueado até a configuração ser concluída. Mesmo raciocínio de "token continua valendo, mas
-- uma condição pendente bloqueia quase tudo" já não existia antes desta fase para nenhum outro
-- caso (`senha_deve_trocar` é só informativo hoje) — esta é a primeira vez que o sistema força
-- de verdade uma ação de segurança antes de liberar o uso normal.

PRAGMA foreign_keys = ON;

ALTER TABLE perfis ADD COLUMN exige_2fa INTEGER NOT NULL DEFAULT 0 CHECK (exige_2fa IN (0, 1));
