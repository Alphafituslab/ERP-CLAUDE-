-- Fase 158 — recuperação de senha (pedido do usuário 2026-09-07): "caso
-- não lembrar da senha colocar um recuperar senha... digita o email
-- correto e vai um link para troca de senha" + "pode ser no whatts,
-- e em email também, ter as duas possibilidades" — o sistema manda o
-- link por QUALQUER canal já disponível pro usuário (celular cadastrado
-- + Evolution API configurada, e/ou SMTP configurado), sem precisar
-- escolher um só antecipadamente.

ALTER TABLE usuarios ADD COLUMN celular TEXT;

CREATE TABLE IF NOT EXISTS usuarios_recuperacao_senha (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    token TEXT NOT NULL UNIQUE,
    criado_em TEXT NOT NULL,
    expira_em TEXT NOT NULL,
    usado_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_recuperacao_senha_token ON usuarios_recuperacao_senha(token);
CREATE INDEX IF NOT EXISTS idx_recuperacao_senha_usuario ON usuarios_recuperacao_senha(usuario_id);
