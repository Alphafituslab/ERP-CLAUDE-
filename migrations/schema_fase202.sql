-- Alphafitus OS — Fase 202 (Agenda: "usuário master" vê tudo, só ele)
--
-- Pedido do usuário (2026-09-25), depois de corrigir o bug de privacidade
-- da Fase 200 (Administrador não deveria bypassar visibilidade de detalhe):
-- "eu como sou usuário master gostaria de ter acesso a tudo" — só ELE
-- especificamente, não qualquer Administrador (a Caroline, por exemplo,
-- que também é Administrador, continua precisando de liberação explícita
-- como qualquer um).
--
-- Por que não uma permissão nova ("agenda.ver_tudo") concedida por
-- exceção: o perfil Administrador é definido com `permissoes = "TODAS"`
-- em seed.py — isso significa literalmente TODA permissão que existir no
-- banco, presente ou futura, incluindo uma nova que eu criasse agora.
-- Criar uma permissão nova a daria de graça pra TODO Administrador
-- (Caroline incluída) no primeiro seed, exatamente o oposto do pedido.
-- Por isso "usuário master" é um flag direto na conta (`usuarios.
-- usuario_master`), fora do sistema de perfis/permissões — não é uma
-- permissão que se concede por perfil ou por exceção, é uma conta
-- marcada manualmente (não existe tela pra ativar isso sozinho, de
-- propósito: evita qualquer Administrador se auto-promover a master).
--
-- `id = 1` é a conta "Clayton Borges da Silva" na base de produção real
-- (confirmado direto no banco antes desta migration) — em qualquer outro
-- ambiente (dev/teste) marca quem quer que seja o id 1 por lá, sem efeito
-- prático nenhum fora da produção.
ALTER TABLE usuarios ADD COLUMN usuario_master INTEGER NOT NULL DEFAULT 0 CHECK (usuario_master IN (0,1));

UPDATE usuarios SET usuario_master = 1 WHERE id = 1;
