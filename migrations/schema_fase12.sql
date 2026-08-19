-- Alphafitus OS — Fase 12 (Reserva de Material ao Liberar Ordem de
-- Produção + Disponibilidade Real de Lote compartilhada entre Produção,
-- Estoque e Comercial).
-- Aplicado DEPOIS de todos os schemas anteriores (Fase 1 a Fase 9 — as
-- Fases 7, 10 e 11 não adicionaram migração). Não altera nem remove nada
-- das fases anteriores.
--
-- Contexto do problema que esta fase fecha: até aqui, três módulos
-- diferentes podiam comprometer o MESMO lote sem nenhum saber da
-- existência do outro —
--   1) Produção consumia material olhando só para `lotes.quantidade`
--      menos o que já tinha sido apontado em `ordem_producao_consumo`,
--      sem checar se aquele material já tinha sido vendido (Comercial,
--      Fase 5) ou baixado/ajustado no estoque (Estoque, Fase 4);
--   2) Comercial reservava material olhando só para o saldo físico já
--      endereçado (Fase 4) menos as próprias reservas de venda, sem
--      checar se aquele mesmo lote já tinha sido reservado por uma ordem
--      de produção liberada;
--   3) duas ordens de produção liberadas ao mesmo tempo competiam pelo
--      mesmo saldo de um lote até a primeira apontar consumo — sem
--      nenhuma trava antecipada (item já documentado como pendência
--      desde a Fase 3/5 no README).
--
-- Esta fase fecha os três ao mesmo tempo: ao LIBERAR uma ordem de
-- produção, o sistema agora reserva de verdade (FEFO, por lote) o
-- material necessário segundo a composição (BOM) da fórmula, gravando um
-- registro imutável em `ordem_producao_reservas` — mesmo princípio de
-- `pedido_venda_reservas` (Fase 5): a reserva nunca é editada ou
-- apagada, ela só "para de contar" quando a ordem muda de status
-- (concluída ou cancelada), sem precisar tocar no histórico. As funções
-- de disponibilidade em `app/routes/estoque.py` passam a ser o único
-- lugar que soma as três origens (consumo de produção, reserva de venda
-- confirmada, saída líquida de baixa/ajuste) e são reutilizadas tanto por
-- Produção (para decidir se pode reservar/consumir) quanto por Comercial
-- (para decidir se pode reservar/vender) — uma única fonte de verdade
-- compartilhada entre os três módulos, em vez de cada um calcular
-- "disponível" do seu jeito.

PRAGMA foreign_keys = ON;

-- ============================================================
-- RESERVAS DE MATERIAL DE PRODUÇÃO — snapshot append-only
-- ============================================================
CREATE TABLE ordem_producao_reservas (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem_producao_id    INTEGER NOT NULL REFERENCES ordens_producao(id),
    item_id              INTEGER NOT NULL REFERENCES itens(id),
    lote_id              INTEGER NOT NULL REFERENCES lotes(id),
    quantidade           REAL NOT NULL CHECK (quantidade > 0),
    criado_em            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por           INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_ordem_producao_reservas_ordem ON ordem_producao_reservas(ordem_producao_id);
CREATE INDEX idx_ordem_producao_reservas_lote ON ordem_producao_reservas(lote_id);

CREATE TRIGGER ordem_producao_reservas_bloqueia_update
BEFORE UPDATE ON ordem_producao_reservas
BEGIN
    SELECT RAISE(ABORT, 'ordem_producao_reservas é append-only: uma reserva de material registra que a ordem garantiu aquele lote ao ser liberada, e nunca pode ser editada — mesmo princípio de pedido_venda_reservas (Fase 5).');
END;

CREATE TRIGGER ordem_producao_reservas_bloqueia_delete
BEFORE DELETE ON ordem_producao_reservas
BEGIN
    SELECT RAISE(ABORT, 'ordem_producao_reservas é append-only: uma reserva de material nunca pode ser apagada — ela só deixa de "contar" quando a ordem muda de status (concluída/cancelada), sem precisar apagar o histórico.');
END;
