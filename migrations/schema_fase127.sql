-- Alphafitus OS — Fase 127 (Métodos e Condições de Pagamento)
--
-- Pedido do usuário: catálogo próprio de métodos de pagamento (Dinheiro,
-- PIX, Boleto, Cartão...) e condições de pagamento (À Vista, 30 dias,
-- 30/60/90 dias...) — o sistema anterior (Ema) tinha os dois como
-- cadastros editáveis; o Alphafitus só tinha `forma_pagamento` como uma
-- lista fixa (CHECK) usada na hora da BAIXA (contas_pagar_baixas/
-- contas_receber_baixas, Fase 6) — deliberadamente NÃO mexida aqui (é o
-- registro histórico de como um pagamento já feito foi liquidado; mudar
-- isso pra um catálogo editável exigiria migrar dado real já lançado).
--
-- Pedido em cima do pedido (mesma conversa): cada método/condição
-- precisa poder ser (a) restrito a um ou mais clientes específicos, ou a
-- uma tabela de preço, em vez de valer pra todo mundo, e (b) marcado
-- como visível (ou não) no App de Vendas — quem decide o que aparece pro
-- vendedor externo em campo é quem cadastra aqui, não o código.
--
-- Regra de restrição (a mesma pros dois catálogos): SEM nenhuma linha em
-- `*_clientes` E SEM `tabela_preco_restrita_id` = disponível pra
-- QUALQUER cliente (comportamento padrão, igual ao que já existia antes
-- desta fase). Assim que qualquer uma das duas restrições é usada, só
-- fica disponível pra quem bate com pelo menos uma delas (cliente listado
-- diretamente, OU cliente cuja tabela_preco_id é a tabela restrita).

CREATE TABLE metodos_pagamento (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL UNIQUE,
    ativo                   INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    visivel_app_vendas      INTEGER NOT NULL DEFAULT 1 CHECK (visivel_app_vendas IN (0, 1)),
    tabela_preco_restrita_id INTEGER REFERENCES tabelas_preco(id),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id)
);

CREATE TABLE metodos_pagamento_clientes (
    metodo_pagamento_id INTEGER NOT NULL REFERENCES metodos_pagamento(id) ON DELETE CASCADE,
    cliente_id           INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    PRIMARY KEY (metodo_pagamento_id, cliente_id)
);

-- `numero_parcelas`/`dias_entre_parcelas` são só INFORMATIVOS (mostrados
-- na tela, ajudam a montar o texto) — nenhuma regra de negócio calcula
-- vencimento de parcela automaticamente a partir daqui ainda; quem lança
-- o pedido/conta continua escolhendo a data de vencimento na hora.
CREATE TABLE condicoes_pagamento (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL UNIQUE,
    numero_parcelas         INTEGER NOT NULL DEFAULT 1 CHECK (numero_parcelas >= 1),
    dias_entre_parcelas     INTEGER,
    ativo                   INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    visivel_app_vendas      INTEGER NOT NULL DEFAULT 1 CHECK (visivel_app_vendas IN (0, 1)),
    tabela_preco_restrita_id INTEGER REFERENCES tabelas_preco(id),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id)
);

CREATE TABLE condicoes_pagamento_clientes (
    condicao_pagamento_id INTEGER NOT NULL REFERENCES condicoes_pagamento(id) ON DELETE CASCADE,
    cliente_id             INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    PRIMARY KEY (condicao_pagamento_id, cliente_id)
);

-- Tabelas de preço (Fase 99) ganham o mesmo interruptor de visibilidade
-- no App de Vendas — hoje toda tabela ativa aparece lá; algumas (ex.:
-- tabela de atacado negociada só por telefone) podem precisar ficar de
-- fora do app e só serem usadas no Comercial normal.
ALTER TABLE tabelas_preco ADD COLUMN visivel_app_vendas INTEGER NOT NULL DEFAULT 1 CHECK (visivel_app_vendas IN (0, 1));

ALTER TABLE clientes ADD COLUMN metodo_pagamento_padrao_id INTEGER REFERENCES metodos_pagamento(id);
ALTER TABLE clientes ADD COLUMN condicao_pagamento_padrao_id INTEGER REFERENCES condicoes_pagamento(id);

-- Complementa `pedidos_venda.forma_pagamento` (Fase 114, texto livre, só
-- usado hoje pelo App de Vendas) — este é o vínculo estruturado, opcional,
-- pro pedido lançado no Comercial normal também poder registrar a
-- condição combinada com o cliente.
ALTER TABLE pedidos_venda ADD COLUMN condicao_pagamento_id INTEGER REFERENCES condicoes_pagamento(id);

-- Catálogo inicial: um conjunto pequeno e limpo, consistente com os
-- valores que `contas_receber_baixas`/`contas_pagar_baixas` já usam
-- (Fase 6) — não importado em peso da lista real do Ema (tinha ~20
-- opções, várias específicas de uma máquina de cartão ou já inativas);
-- o usuário edita/acrescenta pela tela conforme precisar. Sem restrição
-- de cliente/tabela = disponíveis pra todo mundo, como é hoje.
INSERT INTO metodos_pagamento (nome) VALUES
    ('Dinheiro'), ('PIX'), ('Boleto'), ('Cartão de Crédito'), ('Cartão de Débito'), ('Transferência');

INSERT INTO condicoes_pagamento (nome, numero_parcelas, dias_entre_parcelas) VALUES
    ('À vista', 1, NULL),
    ('30 dias', 1, 30),
    ('30/60 dias', 2, 30),
    ('30/60/90 dias', 3, 30),
    ('28/56/84 dias', 3, 28);
