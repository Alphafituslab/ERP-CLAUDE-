-- ============================================================
-- FASE 63 — Limite de Crédito do Cliente (Alçada na Confirmação do
-- Pedido de Venda)
-- ============================================================
-- Espelha, do lado de Comercial, o mesmo desenho já usado na Fase 61 do
-- lado de Compras (alçada por valor no ENVIO do Pedido de Compra): acima
-- de um limiar, a ação não acontece na hora — vira uma SOLICITAÇÃO
-- pendente até um segundo usuário (permissão nova
-- `comercial.aprovar_pedido_acima_limite_credito`, diferente de quem
-- solicitou a confirmação — segregação por USUÁRIO, verificada no
-- código, não por perfil separado, mesmo raciocínio da Fase 21 em
-- diante) aprovar ou rejeitar.
--
-- A diferença de desenho em relação à Fase 61: lá o limiar era um único
-- valor GLOBAL (`configuracoes_compras.limiar_valor_pedido_grande`).
-- Aqui o limiar é o LIMITE DE CRÉDITO DE CADA CLIENTE
-- (`clientes.limite_credito`) — não faz sentido um único teto para todo
-- mundo, já que cada cliente tem um histórico e um porte diferentes.
-- `limite_credito = NULL` (o padrão, cliente recém-cadastrado) significa
-- "sem limite configurado" — a confirmação nunca fica pendente por conta
-- de crédito para esse cliente, mesmo raciocínio de "campo opcional que
-- desliga a checagem quando não preenchido" já usado em
-- `fornecedores.lead_time_dias` desde a Fase 57.
--
-- O que conta contra o limite: o SALDO EM ABERTO do cliente (soma de
-- `contas_receber` com status 'aberto'/'pago_parcial', valor_total menos
-- baixas — não incluímos aqui pedidos ainda não expedidos porque a conta
-- a receber só nasce na expedição, ver nota em app/routes/comercial.py)
-- MAIS o valor do pedido que está sendo confirmado agora
-- (quantidade x preco_unitario de cada linha, ainda rascunho — o mesmo
-- valor que vai gerar a conta a receber lá na frente, na expedição).
--
-- Por que uma tabela própria (`pedidos_venda_confirmacoes_pendentes`) em
-- vez de um novo valor no CHECK de `pedidos_venda.status`: mesmo motivo
-- já registrado na Fase 31/61 — SQLite não permite ALTER num CHECK
-- existente sem recriar a tabela inteira, e uma SOLICITAÇÃO ainda
-- pendente (pode ser aprovada ou rejeitada, e o pedido continua em
-- 'rascunho' normalmente enquanto isso) é um conceito diferente do ciclo
-- de vida do pedido em si.
ALTER TABLE clientes ADD COLUMN limite_credito REAL CHECK (limite_credito IS NULL OR limite_credito >= 0);

CREATE TABLE pedidos_venda_confirmacoes_pendentes (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_venda_id             INTEGER NOT NULL REFERENCES pedidos_venda(id),
    valor_pedido                REAL NOT NULL CHECK (valor_pedido > 0),
    saldo_aberto_no_momento     REAL NOT NULL,
    limite_credito_no_momento   REAL NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovado', 'rejeitado')),
    solicitado_por              INTEGER REFERENCES usuarios(id),
    solicitado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decidido_por                INTEGER REFERENCES usuarios(id),
    decidido_em                 TEXT,
    motivo_rejeicao             TEXT
);

CREATE INDEX idx_pedidos_venda_confirmacoes_pendentes_status ON pedidos_venda_confirmacoes_pendentes(status);
CREATE INDEX idx_pedidos_venda_confirmacoes_pendentes_pedido ON pedidos_venda_confirmacoes_pendentes(pedido_venda_id);
