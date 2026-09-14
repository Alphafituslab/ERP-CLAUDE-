-- Alphafitus OS — Fase 177 (confirmação por e-mail antes de instalar em modo SERVIDOR)
--
-- Pedido do usuário (2026-09-14): "não deixar instalar o servidor em outro
-- lugar. Deve pedir algo de confirmação no meu email". Desde a Fase 157b
-- existe um único Servidor oficial (a VPS) — um segundo Servidor instalado
-- por engano (ou de propósito, por alguém sem essa intenção) criaria um
-- banco de dados paralelo, isolado, silenciosamente divergente do real.
--
-- codigos_instalacao_servidor: código de 6 dígitos, uso único, expira em
-- 10 minutos — guardado como HASH (SHA-256 é suficiente aqui: baixa
-- entropia por natureza, a proteção real é o rate limit abaixo + expiração
-- curta, não a força do hash).
--
-- tentativas_instalador_ip: mesmo padrão já usado em tentativas_login_ip
-- (Fase 168), aplicado às duas rotas novas (pedir e verificar código) —
-- protege tanto contra spam de e-mail quanto contra força bruta do código.

PRAGMA foreign_keys = ON;

CREATE TABLE codigos_instalacao_servidor (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_hash     TEXT NOT NULL,
    criado_em       TEXT NOT NULL,
    expira_em       TEXT NOT NULL,
    usado_em        TEXT,
    ip_solicitante  TEXT
);
CREATE INDEX idx_codigos_instalacao_servidor_hash ON codigos_instalacao_servidor(codigo_hash);

CREATE TABLE tentativas_instalador_ip (
    ip              TEXT PRIMARY KEY,
    tentativas      INTEGER NOT NULL DEFAULT 0,
    janela_inicio   TEXT NOT NULL,
    bloqueado_ate   TEXT
);
