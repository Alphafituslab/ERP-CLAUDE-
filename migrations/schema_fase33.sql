-- Fase 33 — Limite de Prazo para Estorno de Baixa Configurável pela Tela
--
-- Hoje (desde a Fase 14) um estorno de baixa pode ser feito a qualquer
-- momento depois da baixa original, sem janela de tempo. Uma regra de
-- controle interno real poderia exigir, por exemplo, que o estorno só
-- valha dentro de um número limitado de dias — para não deixar reverter
-- lançamentos de meses fiscais já fechados.
--
-- Mesmo espírito da Fase 32 (`configuracoes_estoque`): a régua fica numa
-- tabela de configuração de uma linha só, editável pela tela, em vez de
-- fixa no código. `limite_dias_estorno_baixa = 0` significa "sem limite"
-- — o comportamento padrão, idêntico ao que já existe desde a Fase 14,
-- para não quebrar ninguém que já usa o sistema sem essa régua.
CREATE TABLE configuracoes_financeiro (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    limite_dias_estorno_baixa   INTEGER NOT NULL DEFAULT 0
        CHECK (limite_dias_estorno_baixa >= 0),
    atualizado_em               TEXT,
    atualizado_por              INTEGER REFERENCES usuarios(id)
);

INSERT INTO configuracoes_financeiro (id, limite_dias_estorno_baixa) VALUES (1, 0);
