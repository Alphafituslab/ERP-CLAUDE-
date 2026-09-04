-- Alphafitus OS — Fase 150: App de Vendas — crédito pessoal do vendedor
-- ("gordurinha") + check-in/check-out de visita por geolocalização.
--
-- Pedido do usuário (2026-09-04): "onde o vendedor tenha como fazer uma
-- gordurinha ao vender um produto acima do valor acordado... consegue
-- utilizar esse crédito com quem ele realmente precisa" — decisões
-- confirmadas: o crédito vira saldo AUTOMATICAMENTE na expedição do
-- pedido (sem aprovação), e pode ser usado em pedido de QUALQUER
-- cliente, não só o de origem da venda.
--
-- Visita: "ao chegar no cliente... acionar que chegou... ao chegar ele
-- avisa e ao sair ele avisa, não podendo ter dois clientes abertos, e se
-- ele esquecer de apontar que saiu, deve voltar e marcar o encerramento
-- lá, ou solicitar que seja feito por dentro do ERP por quem tem acesso"
-- — revisão feita ainda no mesmo dia, antes de qualquer deploy, por isso
-- editada direto neste arquivo em vez de uma migração incremental nova.

-- ============================================================
-- CRÉDITO PESSOAL DO VENDEDOR ("gordurinha")
-- ============================================================
-- Mesmo desenho de `verbas_comerciais_lancamentos` (Fase 36) — ledger
-- append-only, saldo sempre recalculado (SUM('gerado') - SUM('utilizado'),
-- nunca guardado à parte) — só que por VENDEDOR em vez de por CLIENTE.
-- Gerado automaticamente na EXPEDIÇÃO (mesmo momento em que a verba do
-- cliente é gerada, ver app/routes/comercial.py::expedir) quando o
-- preço vendido de um item é MAIOR que o preço registrado na tabela de
-- preço do cliente daquele pedido — sem tabela de preço configurada pro
-- cliente (ou item fora dela), não há base de comparação, então nenhum
-- crédito é gerado por aquele item (nunca inventa um "preço padrão" que
-- não existe no cadastro).
CREATE TABLE creditos_vendedor_lancamentos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vendedor_id     INTEGER NOT NULL REFERENCES usuarios(id),
    tipo            TEXT NOT NULL CHECK (tipo IN ('gerado', 'utilizado')),
    valor           REAL NOT NULL CHECK (valor > 0),
    pedido_venda_id INTEGER REFERENCES pedidos_venda(id),
    observacao      TEXT,
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER NOT NULL REFERENCES usuarios(id)
);
CREATE INDEX idx_creditos_vendedor ON creditos_vendedor_lancamentos(vendedor_id);

CREATE TRIGGER creditos_vendedor_bloqueia_update
BEFORE UPDATE ON creditos_vendedor_lancamentos
BEGIN
    SELECT RAISE(ABORT, 'creditos_vendedor_lancamentos é append-only: UPDATE não é permitido (lance uma linha nova se precisar corrigir)');
END;

CREATE TRIGGER creditos_vendedor_bloqueia_delete
BEFORE DELETE ON creditos_vendedor_lancamentos
BEGIN
    SELECT RAISE(ABORT, 'creditos_vendedor_lancamentos é append-only: DELETE não é permitido (lance uma linha nova se precisar corrigir)');
END;

-- Quanto do crédito pessoal do vendedor foi abatido NESTE pedido — mesmo
-- padrão de `pedidos_venda.verba_utilizada` (Fase 36): congelado na
-- CONFIRMAÇÃO, lançado no ledger só na EXPEDIÇÃO (se o pedido for
-- cancelado antes de expedir, nada precisa ser desfeito).
ALTER TABLE pedidos_venda ADD COLUMN credito_vendedor_utilizado REAL NOT NULL DEFAULT 0 CHECK (credito_vendedor_utilizado >= 0);

-- Revisão no mesmo dia, ainda antes de qualquer deploy — o usuário
-- restringiu o uso do crédito: "o vendedor só pode usar o seu crédito
-- gerado e para os seus clientes, onde o admin, por dentro do sistema,
-- pode transferir essas verbas caso necessário para outro vendedor".
-- Isso exige um conceito que o sistema ainda não tinha: "vendedor DONO
-- da conta" de um cliente, diferente de `pedidos_venda.vendedor_id`
-- (quem processou UMA venda específica) — mesmo campo que a Fase da
-- "comissão do televendas" (ver roadmap) também vai precisar no futuro.
-- Opcional (NULL = ninguém responsável ainda definido) — enquanto não
-- for definido, nenhum vendedor consegue aplicar crédito pessoal nesse
-- cliente (ver app/routes/vendas_app.py::aplicar_credito_rascunho).
ALTER TABLE clientes ADD COLUMN vendedor_responsavel_id INTEGER REFERENCES usuarios(id);

-- ============================================================
-- CHECK-IN / CHECK-OUT DE VISITA (geolocalização)
-- ============================================================
-- Diferente de um log simples (uma linha = um evento): aqui cada LINHA é
-- a visita INTEIRA — nasce na chegada (`chegada_em` sempre preenchido) e
-- fecha na saída (`saida_em` NULL enquanto a visita está em andamento).
-- `idx_visitas_vendedor_aberta_unica` abaixo é o que garante de verdade
-- (no banco, não só na tela) que um vendedor nunca tem duas visitas
-- abertas ao mesmo tempo — pedido explícito do usuário.
--
-- `saida_registrada_por`/`saida_encerrada_pelo_erp` registram QUEM
-- encerrou: o próprio vendedor (de volta no local, ou "esqueci de
-- apontar minha saída" de qualquer lugar — os dois são a MESMA ação,
-- sem exigir GPS pra fechar) OU alguém do ERP fechando em nome dele
-- (`saida_encerrada_pelo_erp = 1`) — nunca fica "aberta pra sempre" sem
-- ninguém poder resolver.
CREATE TABLE visitas_clientes (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id                INTEGER NOT NULL REFERENCES clientes(id),
    vendedor_id               INTEGER NOT NULL REFERENCES usuarios(id),
    chegada_em                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    chegada_latitude          REAL,
    chegada_longitude         REAL,
    chegada_precisao_metros   REAL,
    saida_em                  TEXT,
    saida_latitude            REAL,
    saida_longitude           REAL,
    saida_precisao_metros     REAL,
    saida_registrada_por      INTEGER REFERENCES usuarios(id),
    saida_encerrada_pelo_erp  INTEGER NOT NULL DEFAULT 0 CHECK (saida_encerrada_pelo_erp IN (0,1))
);
CREATE INDEX idx_visitas_cliente ON visitas_clientes(cliente_id, chegada_em);
CREATE INDEX idx_visitas_vendedor ON visitas_clientes(vendedor_id, chegada_em);
CREATE UNIQUE INDEX idx_visitas_vendedor_aberta_unica ON visitas_clientes(vendedor_id) WHERE saida_em IS NULL;
