-- Alphafitus OS — Fase 95 (2FA: confiar neste dispositivo por 24h)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário, depois de já ter ativado o 2FA (Fase 92/94) na conta real: "pedir a
-- senha do autenticador 1x ao dia" — ou seja, não repetir o código do app autenticador em
-- TODO login, só de tempos em tempos. Antes desta fase, `POST /auth/login` pedia o código TOTP
-- (via `POST /auth/2fa/verificar`) em toda vez que a senha era digitada de novo — mesmo que a
-- pessoa tivesse acabado de confirmar o código minutos atrás (o `access_token` de 15 minutos e
-- o `refresh_token` de 7 dias já evitam repetir login o tempo todo ENQUANTO a aba/app continua
-- aberta, mas cada login NOVO — depois de sair, fechar o navegador, etc. — pedia o código de
-- novo, sempre).
--
-- Mesmo padrão de `sessoes` (refresh token) já usado neste projeto: o token de confiança do
-- dispositivo NUNCA é guardado em texto puro, só o hash (sha256, reaproveita
-- `security.hash_refresh_token`); um cookie/valor perdido não vaza nada usável direto do banco.
-- Janela fixa de 24h a partir da ÚLTIMA verificação de TOTP bem-sucedida (não é "for sempre"): a
-- pessoa ainda precisa confirmar o código pelo menos uma vez por dia, exatamente o que foi
-- pedido — não é uma forma de desativar o 2FA de fato, é só não repetir o código a cada login
-- dentro do mesmo dia.
--
-- `usuario_id` sem UNIQUE de propósito: a mesma pessoa pode ter mais de um dispositivo
-- confiável ativo ao mesmo tempo (computador do escritório + notebook, por exemplo) — cada
-- confirmação de TOTP bem-sucedida gera o SEU PRÓPRIO token, e cada dispositivo guarda o dele.

PRAGMA foreign_keys = ON;

CREATE TABLE dispositivos_confiaveis_2fa (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
    token_hash    TEXT NOT NULL,
    ip            TEXT,
    dispositivo   TEXT,
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expira_em     TEXT NOT NULL,
    revogado      INTEGER NOT NULL DEFAULT 0 CHECK (revogado IN (0, 1))
);
CREATE INDEX idx_dispositivos_confiaveis_2fa_usuario ON dispositivos_confiaveis_2fa(usuario_id);
