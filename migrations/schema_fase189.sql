-- Fase 189 — pedido do usuário: cadastrar Setores e Funções como listas
-- próprias (não digitar toda vez), pra escolher num seletor no cadastro do
-- Funcionário. `funcionarios.setor`/`funcionarios.funcao` continuam como
-- texto livre (sem FK) — o valor escolhido aqui só preenche esse texto,
-- então nada muda pra quem já tinha dado cadastrado antes desta fase.
CREATE TABLE catalogo_setores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL UNIQUE,
    criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por  INTEGER
);
CREATE TABLE catalogo_funcoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL UNIQUE,
    criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por  INTEGER
);
