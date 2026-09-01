-- Alphafitus OS — Fase 130 (Backup: mais 3 destinos — Local, Google
-- Drive, aviso por WhatsApp)
--
-- Pedido do usuário: além de Nuvem (já rodando, MinIO no VPS) e E-mail
-- (já existia, faltava só configurar SMTP), quer também uma cópia LOCAL,
-- Google Drive de verdade, e um aviso por WhatsApp quando o backup roda.
--
-- Decisões confirmadas com o usuário antes desta fase:
--   - WhatsApp manda só um AVISO de texto (não o arquivo — ~110MB hoje,
--     só cresce, e o limite de anexo do WhatsApp gira perto de 100MB).
--   - Google Drive é o de verdade (não o MinIO já configurado como
--     "nuvem") — precisa de credencial OAuth que só o usuário consegue
--     gerar (Google Cloud Console); o refresh_token fica guardado aqui
--     depois da autorização (ver rotas /sistema/backup/drive/*).
--
-- Nenhum segredo (chave de API, senha) entra em texto puro num arquivo
-- de migration commitado no git — mesmo cuidado já tomado com a chave
-- do banco (SQLCipher) e outras credenciais este projeto todo. O valor
-- real de `whatsapp_evolution_apikey` é preenchido direto no banco de
-- cada instalação, nunca aqui.

ALTER TABLE configuracoes_backup ADD COLUMN local_ativo INTEGER NOT NULL DEFAULT 0 CHECK (local_ativo IN (0,1));
-- Pasta pode ser um caminho de rede/HD externo — sem validar existência
-- aqui (não dá pra saber se um pendrive vai estar plugado na hora que o
-- agendador rodar de madrugada); a tentativa de salvar cria a pasta se
-- não existir e só falha (registrado no histórico) se o caminho for
-- realmente inacessível naquele momento.
ALTER TABLE configuracoes_backup ADD COLUMN local_pasta TEXT;

ALTER TABLE configuracoes_backup ADD COLUMN drive_ativo INTEGER NOT NULL DEFAULT 0 CHECK (drive_ativo IN (0,1));
ALTER TABLE configuracoes_backup ADD COLUMN drive_client_id TEXT;
ALTER TABLE configuracoes_backup ADD COLUMN drive_client_secret TEXT;
-- Preenchido automaticamente pela tela depois que o usuário autoriza
-- (fluxo OAuth) — nunca digitado à mão.
ALTER TABLE configuracoes_backup ADD COLUMN drive_refresh_token TEXT;
-- ID da pasta no Drive (opcional — pego da URL da pasta no navegador);
-- sem isso, o arquivo vai pra raiz do Drive do usuário que autorizou.
ALTER TABLE configuracoes_backup ADD COLUMN drive_pasta_id TEXT;
-- Nonce de proteção CSRF do fluxo OAuth (gerado em /autorizar, conferido
-- e apagado em /callback — sem isso, alguém poderia induzir o
-- administrador a autorizar a CONTA DO ATACANTE, fazendo os backups
-- futuros irem parar no Drive de outra pessoa).
ALTER TABLE configuracoes_backup ADD COLUMN drive_oauth_state TEXT;

ALTER TABLE configuracoes_backup ADD COLUMN whatsapp_ativo INTEGER NOT NULL DEFAULT 0 CHECK (whatsapp_ativo IN (0,1));
ALTER TABLE configuracoes_backup ADD COLUMN whatsapp_numero_destino TEXT;
-- URL/instância pré-preenchidas com o Evolution API já rodando e
-- conectado (o mesmo que alimenta o Whatts Inbox de produção), exposto
-- no mesmo domínio numa porta própria (Fase 130, Caddyfile do VPS,
-- mesmo padrão já usado pro MinIO na Fase 123) — o usuário só precisa
-- preencher o número de destino e a chave de API (gerada no VPS) e
-- ligar; não precisa mexer em infraestrutura nenhuma.
ALTER TABLE configuracoes_backup ADD COLUMN whatsapp_evolution_url TEXT DEFAULT 'https://whatts.alphafitus.com.br:9444';
ALTER TABLE configuracoes_backup ADD COLUMN whatsapp_evolution_apikey TEXT;
ALTER TABLE configuracoes_backup ADD COLUMN whatsapp_instancia_nome TEXT DEFAULT 'whatts';

-- Mesmo padrão de nuvem_tentado/nuvem_sucesso/nuvem_erro (Fase 67) pros
-- 3 destinos novos, no histórico de execuções.
ALTER TABLE backups_executados ADD COLUMN local_tentado INTEGER;
ALTER TABLE backups_executados ADD COLUMN local_sucesso INTEGER;
ALTER TABLE backups_executados ADD COLUMN local_erro TEXT;
ALTER TABLE backups_executados ADD COLUMN drive_tentado INTEGER;
ALTER TABLE backups_executados ADD COLUMN drive_sucesso INTEGER;
ALTER TABLE backups_executados ADD COLUMN drive_erro TEXT;
ALTER TABLE backups_executados ADD COLUMN whatsapp_tentado INTEGER;
ALTER TABLE backups_executados ADD COLUMN whatsapp_sucesso INTEGER;
ALTER TABLE backups_executados ADD COLUMN whatsapp_erro TEXT;
