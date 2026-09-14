-- Fase 172 — pedido do usuário (2026-09-14): poder desligar a exigência de
-- código do autenticador (2FA) no login, de forma configurável, em vez de
-- ser uma regra fixa no código. Continua LIGADA por padrão (ativo = 1) —
-- não muda o comportamento de ninguém até um administrador decidir mudar
-- em Administração > Segurança.
CREATE TABLE configuracoes_seguranca (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    exigir_2fa     INTEGER NOT NULL DEFAULT 1 CHECK (exigir_2fa IN (0,1)),
    atualizado_em  TEXT,
    atualizado_por INTEGER REFERENCES usuarios(id)
);

INSERT INTO configuracoes_seguranca (id, exigir_2fa) VALUES (1, 1);
