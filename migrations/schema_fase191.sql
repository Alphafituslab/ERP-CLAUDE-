-- Fase 191 — pedido do usuário: no cadastro de "Novo usuário", escolher a
-- Função já aplica os Perfis de acesso de uma vez, sem precisar marcar um
-- por um toda vez que contratar alguém pra uma função repetida (ex.:
-- "Televendas" -> Vendedor + Memorial Técnico visualização restrita).
-- `funcao` é TEXTO livre de propósito (mesmo espírito de
-- `funcionarios.funcao`, Fase 189 — sem FK pro catálogo, só bate pelo
-- nome) — assim funciona tanto pra função já cadastrada em
-- catalogo_funcoes quanto pra uma digitada na hora.
CREATE TABLE funcao_perfis_padrao (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    funcao      TEXT NOT NULL,
    perfil_id   INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por  INTEGER,
    UNIQUE(funcao, perfil_id)
);

CREATE INDEX idx_funcao_perfis_padrao_funcao ON funcao_perfis_padrao(funcao);
