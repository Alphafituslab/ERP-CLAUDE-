-- Fase 155 — Catálogos nomeados do App de Vendas + espelho do pedido por
-- WhatsApp.
--
-- Pedido do usuário (2026-09-05): em vez de um portfólio único (todos os
-- itens ativos, só filtrados por categoria), o admin monta CATÁLOGOS
-- nomeados (ex.: "Linha Própria Alpha", "Linha Terceiros") escolhendo quais
-- itens entram em cada um — um item pode estar em mais de um catálogo. E
-- "posso não deixar aparecer um catálogo para um vendedor": por padrão um
-- catálogo é visível pra todo mundo com `vendas_app.usar`; quando marcado
-- como `restrita`, só os vendedores explicitamente listados em
-- `catalogos_vendas_vendedores` o veem — evita ter que listar vendedor por
-- vendedor no caso comum (catálogo aberto a todos).
CREATE TABLE catalogos_vendas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nome         TEXT NOT NULL,
    descricao    TEXT,
    visibilidade TEXT NOT NULL DEFAULT 'todos' CHECK (visibilidade IN ('todos', 'restrita')),
    status       TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    ordem        INTEGER NOT NULL DEFAULT 0,
    criado_em    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por   INTEGER REFERENCES usuarios(id)
);

-- N:N item <-> catálogo (o mesmo item pode aparecer em vários catálogos,
-- ex.: um produto "carro-chefe" tanto na linha própria quanto numa vitrine
-- promocional).
CREATE TABLE catalogos_vendas_itens (
    catalogo_id INTEGER NOT NULL REFERENCES catalogos_vendas(id),
    item_id     INTEGER NOT NULL REFERENCES itens(id),
    PRIMARY KEY (catalogo_id, item_id)
);
CREATE INDEX idx_catalogos_vendas_itens_item ON catalogos_vendas_itens(item_id);

-- Só populada quando `catalogos_vendas.visibilidade = 'restrita'`.
CREATE TABLE catalogos_vendas_vendedores (
    catalogo_id INTEGER NOT NULL REFERENCES catalogos_vendas(id),
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id),
    PRIMARY KEY (catalogo_id, usuario_id)
);
