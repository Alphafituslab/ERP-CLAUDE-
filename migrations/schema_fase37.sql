-- ============================================================
-- FASE 37 — Notificações do Sistema com Envio Real por E-mail
-- ============================================================
-- Contexto: desde a Fase 1 existe a tabela `notificacoes` e a API para o
-- usuário listar as suas notificações e marcar como lida — mas em nenhuma
-- fase até aqui algo no sistema de fato CRIAVA uma notificação; a tabela
-- sempre ficou vazia. Esta fase resolve as duas pontas que faltavam:
--
--   1. Passa a criar notificações de verdade nos pontos onde o próprio
--      sistema já sabe que alguém específico precisa agir — as filas de
--      segunda aprovação que já existem desde as Fases 21/22/31/34
--      (ajuste de contagem com divergência grande, estorno de baixa e
--      registro de baixa acima do valor de alçada). Nenhuma tabela nova
--      de negócio é necessária para isso — só passar a chamar o helper
--      novo (`app/notificacoes_service.py`) nos pontos onde a fila
--      pendente já é criada.
--
--   2. Acrescenta o envio real por e-mail dessas notificações, via SMTP
--      configurável pela tela (`configuracoes_email`, mesmo padrão de
--      "configuração em linha única" já usado desde a Fase 32). O envio
--      é sempre "melhor esforço": a notificação em si é sempre criada e
--      fica visível na tela mesmo que o e-mail falhe, esteja desligado
--      (`ativo = 0`, o padrão) ou o usuário tenha desativado o
--      recebimento por e-mail para si mesmo — nunca bloqueia a ação de
--      negócio (aprovação, estorno, baixa) que disparou a notificação.

-- Cada notificação passa a guardar se o e-mail foi enviado com sucesso, e
-- o motivo quando não foi (SMTP desligado, usuário sem e-mail configurado,
-- erro de conexão etc.) — útil para quem for depurar "por que não recebi
-- o e-mail" sem precisar vasculhar log de servidor.
ALTER TABLE notificacoes ADD COLUMN email_enviado INTEGER NOT NULL DEFAULT 0 CHECK (email_enviado IN (0,1));
ALTER TABLE notificacoes ADD COLUMN email_erro TEXT;

-- Cada usuário pode desligar o recebimento por e-mail de notificações sem
-- precisar de nenhuma permissão especial — a notificação continua sendo
-- criada e visível na tela de qualquer forma, isso só afeta o e-mail.
ALTER TABLE usuarios ADD COLUMN notificar_por_email INTEGER NOT NULL DEFAULT 1 CHECK (notificar_por_email IN (0,1));

-- ============================================================
-- CONFIGURAÇÃO DO SERVIDOR DE E-MAIL (linha única, editável pela tela)
-- ============================================================
-- Mesmo padrão de configuração em banco já usado nas Fases 32/33/34/35/36.
-- `ativo = 0` é o padrão: nenhum e-mail sai até um administrador configurar
-- o SMTP pela tela e ligar explicitamente — mesma filosofia de "tudo
-- desligado por padrão, comportamento anterior preservado" das fases
-- de configuração anteriores.
--
-- `smtp_senha` fica em texto puro no banco (não é um hash — precisa ser
-- reversível para autenticar no servidor SMTP de verdade, diferente da
-- senha de login de usuário). Mesmo risco/tratamento de qualquer outra
-- credencial de integração externa guardada em configuração de sistema;
-- a API nunca devolve o valor salvo de volta pela tela (só um booleano
-- "senha_configurada"), então não fica exposta a quem visualiza a tela.
CREATE TABLE configuracoes_email (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    ativo             INTEGER NOT NULL DEFAULT 0 CHECK (ativo IN (0,1)),
    smtp_host         TEXT,
    smtp_porta        INTEGER NOT NULL DEFAULT 587,
    smtp_usuario      TEXT,
    smtp_senha        TEXT,
    usar_tls          INTEGER NOT NULL DEFAULT 1 CHECK (usar_tls IN (0,1)),
    remetente_nome    TEXT NOT NULL DEFAULT 'Alphafitus OS',
    remetente_email   TEXT,
    atualizado_em     TEXT,
    atualizado_por    INTEGER REFERENCES usuarios(id)
);
INSERT INTO configuracoes_email (id, ativo, smtp_porta, usar_tls, remetente_nome)
VALUES (1, 0, 587, 1, 'Alphafitus OS');
