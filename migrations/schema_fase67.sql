-- ============================================================
-- FASE 67 — Backup Automático Agendado, com Envio Simultâneo para Nuvem
-- e E-mail, e Restauração Simplificada
-- ============================================================
-- A Fase 47 já tinha um "Backup do Sistema" (cópia do banco INTEIRO,
-- gerada com a API de backup nativa do sqlite3 — ver `_gerar_backup_bytes`
-- em app/routes/sistema.py), mas 100% MANUAL: alguém precisava lembrar de
-- entrar na tela e clicar em "Baixar backup" — e o arquivo baixado ficava
-- só no computador de quem baixou, sem nenhuma cópia automática em outro
-- lugar. Esta fase fecha essa lacuna com três coisas:
--
--   1. AGENDAMENTO — quantos horários por dia forem necessários (ex.:
--      08:00, 14:00, 20:00). Um horário local (do próprio computador
--      onde o sistema está rodando) — de propósito, já que quem cadastra
--      "às 8 da manhã" está pensando no relógio da parede, não em UTC
--      (diferente dos timestamps internos do sistema, que continuam em
--      UTC como sempre — ver `_now_iso()` em vários módulos). Rodando de
--      dentro do próprio processo Python (ver `backup_service.py`,
--      thread em segundo plano iniciada por run.py — NUNCA por
--      `create_app()`, para não disparar sozinha durante os testes
--      automatizados).
--
--   2. DOIS DESTINOS EM PARALELO — nuvem (padrão S3-compatível: funciona
--      com AWS S3, Backblaze B2, Cloudflare R2, Wasabi, MinIO etc., só
--      trocando endpoint/credenciais — em vez de amarrar num fornecedor
--      só) e e-mail (reaproveita o SERVIDOR SMTP já configurado desde a
--      Fase 37 em `configuracoes_email` — só a LISTA DE DESTINATÁRIOS é
--      nova aqui, ver `email_destinatarios` abaixo). Os dois disparam ao
--      mesmo tempo (threads paralelas, não uma fila sequencial) e o
--      resultado de CADA UM é gravado separadamente em
--      `backups_executados` — mesma filosofia "melhor esforço" já usada
--      no envio de e-mail de notificação (Fase 37): um destino falhar
--      nunca impede o outro nem esconde que o backup em si foi gerado
--      com sucesso.
--
--   3. RESTAURAÇÃO — a Fase 47 dizia, de propósito, que restaurar exigia
--      um procedimento manual com o serviço PARADO, porque substituir o
--      arquivo .db enquanto o Flask está rodando arrisca corromper o
--      banco (sobretudo no Windows, onde um arquivo em uso não pode
--      simplesmente ser sobrescrito por outro processo). Esta fase
--      mantém exatamente essa mesma cautela, mas facilita o UPLOAD: a
--      tela aceita o arquivo de backup e o deixa PRONTO
--      (`restauracao_pendente.db`, ao lado do banco de verdade); a troca
--      de fato só acontece na PRÓXIMA VEZ que o sistema for iniciado
--      (ver `aplicar_restauracao_pendente_se_houver` em app/db.py,
--      chamada por run.py ANTES de abrir o banco) — nunca com o servidor
--      já respondendo requisições. Antes de trocar, o banco atual
--      (mesmo que "hackeado"/corrompido) é preservado numa cópia de
--      segurança carimbada com data/hora, para nunca destruir evidência
--      ou dados por engano.
--
-- Decisão de escopo deliberada: a senha/chave secreta da nuvem
-- (`nuvem_secret_key`) segue o MESMO padrão já usado para
-- `configuracoes_email.smtp_senha` desde a Fase 37 — gravada em texto
-- puro nesta tabela (não existe, neste sistema, um cofre de segredos
-- separado) mas NUNCA devolvida pela API depois de salva (a tela só
-- informa se já existe uma chave configurada, ver `_config_publica` em
-- app/routes/sistema.py).
CREATE TABLE configuracoes_backup (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    -- Chave-mestra: desligada por padrão, mesmo espírito de
    -- `configuracoes_email.ativo` — precisa ser ligada explicitamente
    -- depois de configurar ao menos um horário e um destino.
    ativo                INTEGER NOT NULL DEFAULT 0 CHECK (ativo IN (0,1)),
    nuvem_ativo          INTEGER NOT NULL DEFAULT 0 CHECK (nuvem_ativo IN (0,1)),
    nuvem_endpoint_url   TEXT,
    nuvem_regiao         TEXT,
    nuvem_bucket         TEXT,
    nuvem_access_key     TEXT,
    nuvem_secret_key     TEXT,
    -- Prefixo/pasta dentro do bucket (opcional) — útil para quem
    -- reaproveita o mesmo bucket para outra coisa e quer isolar os
    -- backups do Alphafitus numa "subpasta" lógica (S3 não tem pastas de
    -- verdade, só chaves com "/" no nome).
    nuvem_prefixo        TEXT,
    email_ativo          INTEGER NOT NULL DEFAULT 0 CHECK (email_ativo IN (0,1)),
    -- Lista de destinatários separada por vírgula — deliberadamente
    -- INDEPENDENTE de quem tem `notificacoes` configuradas: backup é uma
    -- preocupação de continuidade do negócio, não de notificação de
    -- evento, então a lista pode (e normalmente deve) incluir um e-mail
    -- externo ao sistema (ex.: uma caixa postal só para isso).
    email_destinatarios  TEXT,
    atualizado_em        TEXT,
    atualizado_por       INTEGER REFERENCES usuarios(id)
);
INSERT INTO configuracoes_backup (id, ativo, nuvem_ativo, email_ativo) VALUES (1, 0, 0, 0);

-- "Quantos horários por dia forem necessários" — de propósito uma tabela
-- própria (não uma coluna de texto com horários separados por vírgula em
-- `configuracoes_backup`), para permitir desativar UM horário específico
-- sem apagar os outros, e para o agendador (`backup_service.py`) poder
-- fazer uma consulta simples "quais horários ATIVOS batem com agora".
CREATE TABLE backup_horarios (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Formato "HH:MM", 24 horas, hora LOCAL do computador (ver nota de
    -- escopo no topo deste arquivo) — ex.: "08:00", "14:30", "23:00".
    hora    TEXT NOT NULL UNIQUE,
    ativo   INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1))
);

-- Histórico — cada linha é UMA execução de backup (agendada ou manual),
-- com o resultado de CADA destino gravado separadamente (ver nota de
-- escopo #2 no topo deste arquivo). `nuvem_sucesso`/`email_sucesso` só
-- fazem sentido quando o respectivo `_tentado = 1` (destino estava
-- ligado no momento da execução) — NULL quando o destino nem estava
-- ativo, então nunca aparece como "falhou" algo que não foi nem tentado.
CREATE TABLE backups_executados (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    executado_em      TEXT NOT NULL,
    origem            TEXT NOT NULL CHECK (origem IN ('agendado', 'manual')),
    -- NULL quando `origem = 'agendado'` (disparado pelo agendador em
    -- segundo plano, sem nenhum usuário logado no momento).
    disparado_por     INTEGER REFERENCES usuarios(id),
    tamanho_bytes     INTEGER,
    nuvem_tentado     INTEGER NOT NULL DEFAULT 0 CHECK (nuvem_tentado IN (0,1)),
    nuvem_sucesso     INTEGER CHECK (nuvem_sucesso IN (0,1)),
    nuvem_erro        TEXT,
    email_tentado     INTEGER NOT NULL DEFAULT 0 CHECK (email_tentado IN (0,1)),
    email_sucesso     INTEGER CHECK (email_sucesso IN (0,1)),
    email_erro        TEXT
);
CREATE INDEX idx_backups_executados_executado_em ON backups_executados(executado_em);
