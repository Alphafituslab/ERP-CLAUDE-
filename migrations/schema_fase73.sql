-- ============================================================
-- Fase 73 — Auditoria de Segurança (continuação da Fase 72):
-- corrida na RESERVA DE ESTOQUE POR FEFO entre confirmações de pedido
-- de venda e liberações de ordem de produção concorrentes.
-- ============================================================
--
-- Contexto: a Fase 72 fechou duas corridas do tipo "existe no máximo um
-- registro ativo" com ÍNDICES ÚNICOS (inclusive parciais). Esta corrida
-- é de outra natureza: o invariante que pode ser violado não é sobre
-- duplicidade de uma linha, é sobre SOMA — "a soma das reservas ativas
-- de um lote (e, no caso de vendas, de um lote+posição) nunca pode
-- ultrapassar o saldo físico realmente disponível". Um índice único não
-- tem nada a dizer sobre SUM(), então a ferramenta certa aqui é um
-- TRIGGER BEFORE INSERT com RAISE(ABORT, ...) que recalcula o saldo
-- disponível no momento exato da escrita.
--
-- Por que isso fecha a corrida: cada requisição HTTP roda inteira dentro
-- de uma única transação SQLite (uma conexão por requisição, commit só
-- no fim — ver app/context.py:close_db). O comentário da Fase 72 já
-- documentava que SQLite serializa ESCRITORES (só um escreve por vez; o
-- segundo espera a transação do primeiro comitar), mas NÃO serializa
-- leituras entre requisições concorrentes. A checagem em Python
-- (_alocar_fefo em comercial.py, _alocar_fefo_producao em producao.py) é
-- só LEITURA — duas requisições concorrentes disputando o mesmo lote
-- podem ambas ler "cabe" antes de qualquer uma escrever. O trigger abaixo
-- roda dentro do INSERT propriamente dito: quando a segunda transação
-- finalmente consegue escrever (depois que a primeira já comitou), ele
-- recalcula a soma já enxergando os dados comitados da primeira — e
-- aborta se não couber mais, igual a Fase 72 fez com índice único.
--
-- Nenhuma reescrita de arquitetura: as tabelas de reserva continuam
-- append-only (saldo sempre calculado por SUM(), nunca guardado à parte
-- — princípio estabelecido desde a Fase 4/5/12). O trigger só espelha,
-- em SQL, exatamente as mesmas funções Python que já calculam
-- disponibilidade (_saldo_disponivel_para_reserva em comercial.py e
-- saldo_real_disponivel_producao em estoque.py) — é uma segunda camada
-- de defesa por trás da checagem em Python, não uma checagem nova.
--
-- A margem de 0.0000001 espelha a mesma tolerância de ponto flutuante já
-- usada nas comparações Python equivalentes (ex.: "coberto + 0.0000001 <
-- item['quantidade']" em comercial.py e producao.py).

CREATE TRIGGER trg_pedido_venda_reservas_bloqueia_saldo_negativo
BEFORE INSERT ON pedido_venda_reservas
BEGIN
    SELECT RAISE(ABORT, 'Saldo em estoque insuficiente para esta reserva de venda — outra confirmação de pedido concorrente provavelmente reservou o mesmo lote/posição ao mesmo tempo. Consulte o saldo disponível e tente confirmar o pedido novamente.')
    WHERE (
        (SELECT COALESCE(SUM(m.quantidade), 0) FROM movimentacoes_estoque m
            WHERE m.lote_id = NEW.lote_id AND m.posicao_id = NEW.posicao_id)
        -
        (SELECT COALESCE(SUM(pvr.quantidade), 0)
           FROM pedido_venda_reservas pvr
           JOIN pedido_venda_itens pvi ON pvi.id = pvr.pedido_item_id
           JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
           WHERE pvr.lote_id = NEW.lote_id AND pvr.posicao_id = NEW.posicao_id AND pv.status = 'confirmado')
        - NEW.quantidade
    ) < -0.0000001;
END;

CREATE TRIGGER trg_ordem_producao_reservas_bloqueia_saldo_negativo
BEFORE INSERT ON ordem_producao_reservas
BEGIN
    SELECT RAISE(ABORT, 'Saldo real do lote insuficiente para esta reserva de produção — outra liberação de ordem concorrente provavelmente reservou o mesmo lote ao mesmo tempo. Consulte o saldo disponível e tente liberar a ordem novamente.')
    WHERE (
        (SELECT quantidade FROM lotes WHERE id = NEW.lote_id)
        - (SELECT COALESCE(SUM(quantidade), 0) FROM ordem_producao_consumo WHERE lote_id = NEW.lote_id)
        - (SELECT COALESCE(SUM(pvr.quantidade), 0) FROM pedido_venda_reservas pvr
             JOIN pedido_venda_itens pvi ON pvi.id = pvr.pedido_item_id
             JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
             WHERE pvr.lote_id = NEW.lote_id AND pv.status = 'confirmado')
        - (SELECT COALESCE(SUM(opr.quantidade), 0) FROM ordem_producao_reservas opr
             JOIN ordens_producao op ON op.id = opr.ordem_producao_id
             WHERE opr.lote_id = NEW.lote_id AND op.status IN ('liberada', 'em_producao'))
        - (SELECT MAX(0.0, -x.total) FROM (
             SELECT COALESCE(SUM(quantidade), 0) AS total FROM movimentacoes_estoque
             WHERE lote_id = NEW.lote_id AND tipo IN ('saida', 'ajuste_negativo')
           ) x)
        - NEW.quantidade
    ) < -0.0000001;
END;
