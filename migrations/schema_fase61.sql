-- ============================================================
-- FASE 61 — Alçada por Valor no Envio do Pedido de Compra
-- ============================================================
-- Mesmo desenho já usado desde a Fase 21/22/31/34 para outros
-- compromissos sensíveis (ajuste de contagem, estorno de baixa, registro
-- de baixa): acima de um limiar de VALOR (não de percentual — o Pedido
-- de Compra não tem um "saldo esperado" para comparar, ele É o
-- compromisso), enviar o pedido ao fornecedor não acontece na hora —
-- vira uma SOLICITAÇÃO pendente até um segundo usuário (permissão nova
-- `compras.aprovar_pedido_grande`, diferente de quem solicitou o envio —
-- segregação por USUÁRIO, verificada no código, não por perfil
-- separado, mesmo raciocínio das fases citadas acima) aprovar ou
-- rejeitar. Abaixo do limiar, comportamento idêntico ao de sempre desde
-- a Fase 58: `POST /pedidos/<id>/enviar` manda na hora.
--
-- `limiar_valor_pedido_grande = 0` (o padrão) desliga esse controle por
-- completo — nenhum pedido nunca entra em aprovação pendente — para não
-- mudar nada em quem já usa o sistema sem configurar isso (mesma
-- convenção de "0 desliga" já usada em
-- `configuracoes_estoque.limiar_valor_ajuste_divergencia_grande` desde a
-- Fase 34). Só o Administrador tem `compras.configurar_alcada_pedido`
-- por padrão — mesma decisão de controle interno reservada a quem
-- decide as regras, não a quem opera o dia a dia (mesma nota de escopo
-- de `estoque.configurar_alcada_divergencia` desde a Fase 21).
--
-- Por que uma tabela própria (`pedidos_compra_envios_pendentes`) em vez
-- de um novo valor no CHECK de `pedidos_compra.status`: SQLite não
-- permite alterar um CHECK existente com ALTER TABLE (exigiria recriar a
-- tabela inteira) — e mesmo sem essa limitação técnica, o motivo de
-- fundo é o mesmo já registrado na Fase 31: uma SOLICITAÇÃO ainda
-- pendente (pode ser aprovada ou rejeitada, e o pedido continua em
-- 'rascunho' normalmente enquanto isso) é um conceito diferente do
-- ciclo de vida do pedido em si.
CREATE TABLE configuracoes_compras (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    limiar_valor_pedido_grande  REAL NOT NULL DEFAULT 0 CHECK (limiar_valor_pedido_grande >= 0),
    atualizado_em               TEXT,
    atualizado_por              INTEGER REFERENCES usuarios(id)
);
INSERT INTO configuracoes_compras (id, limiar_valor_pedido_grande) VALUES (1, 0);

CREATE TABLE pedidos_compra_envios_pendentes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_compra_id   INTEGER NOT NULL REFERENCES pedidos_compra(id),
    valor_total        REAL NOT NULL CHECK (valor_total > 0),
    status             TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovado', 'rejeitado')),
    solicitado_por     INTEGER REFERENCES usuarios(id),
    solicitado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decidido_por       INTEGER REFERENCES usuarios(id),
    decidido_em        TEXT,
    motivo_rejeicao    TEXT
);

CREATE INDEX idx_pedidos_compra_envios_pendentes_status ON pedidos_compra_envios_pendentes(status);
CREATE INDEX idx_pedidos_compra_envios_pendentes_pedido ON pedidos_compra_envios_pendentes(pedido_compra_id);
