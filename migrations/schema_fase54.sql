-- Fase 54 — MRP: Sugestão Automática de Compra
--
-- A Fase 39 entregou o cálculo de necessidade de materiais (MRP):
-- somando a composição de TODAS as ordens ainda `planejada`, contra o
-- saldo real disponível, `GET /aps/mrp` já mostra exatamente o que vai
-- faltar comprar, item por item, com os fornecedores homologados de
-- cada um. Mas até aqui isso era só um RELATÓRIO — Compras via a lista de
-- falta na tela e tinha que copiar cada item manualmente para lançar uma
-- conta a pagar (Fase 6) depois que a compra de fato acontecesse.
--
-- Esta fase fecha esse último passo manual, mas com uma decisão de
-- escopo deliberada: o botão novo "Gerar sugestões de compra" NÃO cria
-- uma conta a pagar de verdade. Uma conta a pagar (Fase 6) representa uma
-- obrigação financeira REAL — precisa de `valor_total` e `vencimento`, que
-- só existem depois que a compra de fato aconteceu e a nota fiscal
-- chegou. Uma necessidade do MRP é só uma PREVISÃO de compra — o sistema
-- não sabe (e não deveria inventar) o preço nem a data de vencimento
-- antes da negociação com o fornecedor acontecer. Criar uma conta a pagar
-- fictícia neste momento contaminaria o Financeiro (Fase 6) e o Fluxo de
-- Caixa Projetado (Fase 15) com uma obrigação que ainda não existe de
-- verdade.
--
-- Por isso `sugestoes_compra_mrp` é uma entidade nova e deliberadamente
-- SEPARADA de `contas_pagar`: um item de trabalho para Compras, com um
-- ciclo de vida de status (`pendente` -> `atendida` ou `descartada`),
-- igual em espírito às filas de aprovação pendente já existentes
-- (`estornos_pendentes_receber/pagar` da Fase 22, `baixas_pendentes_*`
-- da Fase 31) — mutável de propósito, ao contrário do ledger append-only
-- usado para transações financeiras já concluídas. Quando Compras de
-- fato compra o item e lança a conta a pagar pela tela já existente
-- desde a Fase 6, pode marcar a sugestão como "atendida" linkando o
-- `conta_pagar_id` correspondente (opcional — a compra pode ter
-- acontecido fora do sistema por ora, ou a conta ser lançada depois,
-- separadamente).
CREATE TABLE sugestoes_compra_mrp (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id                 INTEGER NOT NULL REFERENCES itens(id),
    quantidade_sugerida     REAL NOT NULL CHECK (quantidade_sugerida > 0),
    fornecedor_sugerido_id  INTEGER REFERENCES fornecedores(id),
    -- Snapshot (JSON) de quais ordens de produção planejadas motivaram
    -- esta sugestão, no formato devolvido por `_calcular_mrp` — mesmo
    -- princípio de "congelar o motivo no momento da geração" já usado em
    -- `simulacoes_recall` (Fase 8): se as ordens planejadas mudarem
    -- depois, a sugestão pendente não se atualiza sozinha — ela reflete a
    -- necessidade de quando foi gerada; uma nova rodada de "Gerar
    -- sugestões" capta o estado atual.
    ordens_relacionadas     TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN (
                                'pendente', 'atendida', 'descartada'
                            )),
    gerada_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    gerada_por              INTEGER REFERENCES usuarios(id),
    decidida_em             TEXT,
    decidida_por            INTEGER REFERENCES usuarios(id),
    motivo_descarte         TEXT,
    -- Preenchido só quando a decisão é "atendida" e Compras linka a conta
    -- a pagar real que lançou pela tela de Financeiro — opcional de
    -- propósito (ver nota acima).
    conta_pagar_id          INTEGER REFERENCES contas_pagar(id)
);

CREATE INDEX idx_sugestoes_compra_mrp_item ON sugestoes_compra_mrp(item_id);
CREATE INDEX idx_sugestoes_compra_mrp_status ON sugestoes_compra_mrp(status);
