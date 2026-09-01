-- Alphafitus OS — Fase 128 (Tabela de preço vira também "tabela de
-- condições comerciais": método + prazo pré-configurados)
--
-- Correção de modelagem em cima da Fase 127, pedida pelo usuário logo
-- depois: uma tabela de preço (ex.: "Terceirização") não deve só
-- restringir método/condição a UMA tabela solta (o que a Fase 127
-- fazia com `tabela_preco_restrita_id`) — ela deve ser o lugar onde se
-- configura, PARA CADA MÉTODO, quais prazos estão disponíveis (ex.: na
-- tabela "Terceirização", Boleto pode ter 7/14/28 OU 28/42/56, PIX só
-- tem À Vista). Isso é uma estrutura de 3 pontas (tabela × método ×
-- condição), não uma restrição de 1 ponta — por isso troca de coluna
-- pra tabela de junção.
--
-- `tabela_preco_restrita_id` (Fase 127) nunca teve nenhum dado real
-- usando essa restrição (feature tinha acabado de ser publicada) —
-- removida sem migração de dado, substituída de vez por isto.

PRAGMA foreign_keys = OFF;

CREATE TABLE metodos_pagamento_novo (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL UNIQUE,
    ativo                   INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    visivel_app_vendas      INTEGER NOT NULL DEFAULT 1 CHECK (visivel_app_vendas IN (0, 1)),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id)
);
INSERT INTO metodos_pagamento_novo (id, nome, ativo, visivel_app_vendas, criado_em, criado_por)
    SELECT id, nome, ativo, visivel_app_vendas, criado_em, criado_por FROM metodos_pagamento;
DROP TABLE metodos_pagamento;
ALTER TABLE metodos_pagamento_novo RENAME TO metodos_pagamento;

CREATE TABLE condicoes_pagamento_novo (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL UNIQUE,
    numero_parcelas         INTEGER NOT NULL DEFAULT 1 CHECK (numero_parcelas >= 1),
    dias_entre_parcelas     INTEGER,
    ativo                   INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    visivel_app_vendas      INTEGER NOT NULL DEFAULT 1 CHECK (visivel_app_vendas IN (0, 1)),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id)
);
INSERT INTO condicoes_pagamento_novo (id, nome, numero_parcelas, dias_entre_parcelas, ativo, visivel_app_vendas, criado_em, criado_por)
    SELECT id, nome, numero_parcelas, dias_entre_parcelas, ativo, visivel_app_vendas, criado_em, criado_por FROM condicoes_pagamento;
DROP TABLE condicoes_pagamento;
ALTER TABLE condicoes_pagamento_novo RENAME TO condicoes_pagamento;

PRAGMA foreign_keys = ON;

-- O coração desta fase: para cada tabela de preço, quais combinações de
-- método+condição estão disponíveis. Uma tabela pode ter vários métodos,
-- e cada método pode ter vários prazos — exatamente o pedido ("podendo
-- ter mais de um método e prazo na mesma tabela").
CREATE TABLE tabela_preco_condicoes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    tabela_preco_id         INTEGER NOT NULL REFERENCES tabelas_preco(id) ON DELETE CASCADE,
    metodo_pagamento_id     INTEGER NOT NULL REFERENCES metodos_pagamento(id),
    condicao_pagamento_id   INTEGER NOT NULL REFERENCES condicoes_pagamento(id),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    UNIQUE (tabela_preco_id, metodo_pagamento_id, condicao_pagamento_id)
);
CREATE INDEX idx_tabela_preco_condicoes_tabela ON tabela_preco_condicoes(tabela_preco_id);
