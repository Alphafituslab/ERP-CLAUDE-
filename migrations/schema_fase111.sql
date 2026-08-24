-- Alphafitus OS — Fase 111 (Arquitetura Servidor + Terminais: registro de terminais)
--
-- Contexto (ver plano completo na conversa): investigação confirmou que o sistema já
-- é uma arquitetura cliente-servidor de verdade desde a Fase 1 — o frontend nunca
-- acessa o SQLite diretamente, só via API; não existe banco local em nenhum "cliente".
-- O que faltava era um REGISTRO dos terminais que já se conectam via rede local (o
-- servidor já escuta em 0.0.0.0:5000, então isso já era possível, só não era rastreado).
--
-- `terminal_uid` é gerado UMA VEZ pelo frontend (crypto.randomUUID, persistido em
-- localStorage) e enviado em todo heartbeat — não depende de IP (que muda em redes
-- DHCP) nem de User-Agent (que não distingue duas instalações do mesmo navegador).
-- `bloqueado` é a forma de a Administração encerrar o acesso de uma máquina
-- específica sem precisar mexer em usuário/senha (ex.: notebook que saiu da empresa).
PRAGMA foreign_keys = ON;

CREATE TABLE terminais (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    terminal_uid            TEXT NOT NULL UNIQUE,
    nome                    TEXT,
    ip_ultimo_acesso        TEXT,
    user_agent_ultimo_acesso TEXT,
    usuario_id_ultimo_acesso INTEGER REFERENCES usuarios(id),
    versao_app_ultima       TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ultimo_acesso_em        TEXT,
    bloqueado               INTEGER NOT NULL DEFAULT 0 CHECK (bloqueado IN (0, 1)),
    bloqueado_em            TEXT,
    bloqueado_por           INTEGER REFERENCES usuarios(id)
);
CREATE INDEX idx_terminais_ultimo_acesso ON terminais(ultimo_acesso_em);
