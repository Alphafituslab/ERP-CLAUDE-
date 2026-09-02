-- Alphafitus OS — Fase 136 (Terceirização Premium, Fase C — link seguro +
-- portal do cliente + envio por WhatsApp)
--
-- Pedido do usuário: "enviar um link no whats... que o cliente consiga
-- preencher... ao devolver o preenchimento deve avisar o usuário
-- responsável". Confirmado no plano salvo na sessão: não existe NENHUM
-- precedente de acesso externo sem login no sistema inteiro — toda
-- autenticação hoje é login normal (JWT) ou OAuth admin (Google Drive).
-- Este é o primeiro.
--
-- Simplificação real em relação ao plano original: a ideia de um
-- "webhook de entrada do WhatsApp" pra detectar "cliente respondeu" foi
-- abandonada — o cliente preenche um FORMULÁRIO NA WEB (o portal abaixo),
-- não conversa por chat. O próprio backend já sabe, na hora, quando o
-- cliente clica em "concluir" — não precisa esperar uma mensagem de volta
-- no WhatsApp pra saber disso. O WhatsApp entra só como CANAL DE ENVIO do
-- link (e, opcionalmente, de aviso), nunca como canal de recebimento.

CREATE TABLE terceirizacao_links_portal (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id       INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    token            TEXT NOT NULL UNIQUE,  -- secrets.token_urlsafe(32) — ~256 bits, inviável de adivinhar
    criado_em        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por       INTEGER NOT NULL REFERENCES usuarios(id),
    expira_em        TEXT NOT NULL,
    revogado         INTEGER NOT NULL DEFAULT 0 CHECK (revogado IN (0,1)),
    ultimo_acesso_em TEXT,
    enviado_via_whatsapp INTEGER NOT NULL DEFAULT 0 CHECK (enviado_via_whatsapp IN (0,1))
);
CREATE INDEX idx_terceirizacao_links_portal_projeto ON terceirizacao_links_portal(projeto_id);
-- Índice único PARCIAL: só pode existir UM link ATIVO (não revogado) por
-- projeto ao mesmo tempo — gerar um novo revoga o anterior primeiro (ver
-- app/routes/terceirizacao.py). Evita links órfãos esquecidos circulando.
CREATE UNIQUE INDEX idx_terceirizacao_links_portal_ativo_unico
    ON terceirizacao_links_portal(projeto_id) WHERE revogado = 0;
