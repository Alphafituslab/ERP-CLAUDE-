-- ============================================================
-- FASE 66 — Cotação Comparativa de Fornecedores (RFQ) antes do Pedido de
-- Compra
-- ============================================================
-- Desde a Fase 58, Compras já tem um documento formal para o COMPROMISSO
-- com um fornecedor (`pedidos_compra`) — mas o sistema nunca teve nada
-- para a etapa ANTES desse compromisso: hoje, quando Compras precisa
-- decidir com qual fornecedor comprar um item, essa comparação de preço e
-- prazo entre fornecedores concorrentes acontece 100% fora do sistema
-- (planilha, papel, e-mail), sem nenhum registro do que cada fornecedor
-- ofereceu nem de por que um foi escolhido em vez de outro. Esta fase
-- fecha essa lacuna com uma "Cotação" (RFQ — Request for Quotation): lista
-- de itens/quantidades a comprar, fornecedores convidados a cotar, a
-- resposta (preço unitário + prazo de entrega) de cada um por item, e o
-- fechamento da cotação escolhendo um vencedor — que gera automaticamente
-- o Pedido de Compra formal já existente desde a Fase 58, reaproveitando
-- `criar_pedido_compra_interno` em app/routes/compras.py, exatamente como
-- a Fase 54 (MRP) já faz ao gerar um pedido a partir de uma sugestão.
--
-- Decisão de escopo deliberada #1 — um vencedor por COTAÇÃO, não por
-- item: este MVP não faz "split de fornecedor" (comprar o item A do
-- fornecedor X e o item B do fornecedor Y dentro da mesma cotação) — isso
-- viraria N pedidos de compra diferentes a partir de uma única cotação,
-- com uma tela de decisão bem mais complexa. Quem precisar comprar itens
-- de fornecedores diferentes hoje já pode simplesmente abrir DUAS
-- cotações separadas (uma por fornecedor pretendido), ou usar o Pedido de
-- Compra manual (Fase 58) direto, sem cotação.
--
-- Decisão de escopo deliberada #2 — quem digita a resposta do fornecedor
-- é sempre um usuário interno (Compras), não o fornecedor diretamente:
-- este sistema não tem portal externo para fornecedor logar e responder
-- sozinho — a cotação por telefone/e-mail continua acontecendo fora do
-- sistema, e Compras registra o que cada fornecedor respondeu (mesmo
-- espírito de `cotacao_respostas.registrado_por` abaixo).
--
-- Decisão de escopo deliberada #3 — fechar a cotação exige que o
-- fornecedor vencedor tenha respondido preço para TODOS os itens da
-- cotação (ver validação em `fechar_cotacao`, app/routes/cotacoes.py) —
-- um Pedido de Compra sem preço em alguma linha até é permitido quando
-- criado manualmente (Fase 58), mas aqui, já que o preço veio de uma
-- cotação formal, exigir a resposta completa evita fechar comparando
-- "quem foi mais barato" com uma cotação incompleta.
CREATE TABLE cotacoes (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                   TEXT NOT NULL UNIQUE,
    status                   TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN (
                                 'aberta', 'fechada', 'cancelada'
                             )),
    observacoes              TEXT,
    criado_em                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por               INTEGER REFERENCES usuarios(id),
    fechado_em               TEXT,
    fechado_por              INTEGER REFERENCES usuarios(id),
    cancelado_em             TEXT,
    cancelado_por            INTEGER REFERENCES usuarios(id),
    motivo_cancelamento      TEXT,
    -- Preenchidos só no fechamento (ver decisão de escopo #1 acima) — o
    -- pedido de compra gerado automaticamente reaproveita
    -- `criar_pedido_compra_interno`, já usado desde a Fase 58/54.
    fornecedor_vencedor_id   INTEGER REFERENCES fornecedores(id),
    pedido_compra_gerado_id  INTEGER REFERENCES pedidos_compra(id)
);

CREATE INDEX idx_cotacoes_status ON cotacoes(status);

-- Itens a cotar — quantidade/unidade são as mesmas para TODOS os
-- fornecedores convidados (é o que está sendo comparado); cada fornecedor
-- só varia no preço e no prazo (ver `cotacao_respostas` abaixo). Mesmo
-- padrão de UNIQUE por (cotação, item) já usado em
-- `itens_pedido_compra` desde a Fase 58.
CREATE TABLE cotacao_itens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id   INTEGER NOT NULL REFERENCES cotacoes(id),
    item_id      INTEGER NOT NULL REFERENCES itens(id),
    quantidade   REAL NOT NULL CHECK (quantidade > 0),
    unidade      TEXT NOT NULL,
    UNIQUE (cotacao_id, item_id)
);

CREATE INDEX idx_cotacao_itens_cotacao ON cotacao_itens(cotacao_id);

-- Fornecedores convidados a participar da cotação — só um fornecedor
-- convidado pode ter resposta registrada contra ele (ver validação em
-- `registrar_resposta_cotacao`), e só um convidado pode ser escolhido
-- como vencedor no fechamento.
CREATE TABLE cotacao_fornecedores_convidados (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id     INTEGER NOT NULL REFERENCES cotacoes(id),
    fornecedor_id  INTEGER NOT NULL REFERENCES fornecedores(id),
    UNIQUE (cotacao_id, fornecedor_id)
);

CREATE INDEX idx_cotacao_convidados_cotacao ON cotacao_fornecedores_convidados(cotacao_id);

-- Resposta de UM fornecedor convidado a UM item da cotação — preço
-- unitário obrigatório (é o que está sendo comparado), prazo de entrega
-- em dias opcional (nem todo fornecedor informa, e não bloqueia a
-- comparação de preço). Registrar de novo para o mesmo (cotação,
-- fornecedor, item) SUBSTITUI a resposta anterior (ver
-- `registrar_resposta_cotacao`) — negociação é normal até o fechamento,
-- então não faz sentido acumular histórico de "tentativas" aqui (quem
-- quiser auditoria de quem registrou o quê e quando já tem
-- `registrado_por`/`registrado_em` nesta própria linha, mais o log de
-- auditoria padrão do sistema).
CREATE TABLE cotacao_respostas (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id            INTEGER NOT NULL REFERENCES cotacoes(id),
    fornecedor_id         INTEGER NOT NULL REFERENCES fornecedores(id),
    item_id               INTEGER NOT NULL REFERENCES itens(id),
    preco_unitario        REAL NOT NULL CHECK (preco_unitario >= 0),
    prazo_entrega_dias    INTEGER CHECK (prazo_entrega_dias IS NULL OR prazo_entrega_dias >= 0),
    registrado_em         TEXT NOT NULL,
    registrado_por        INTEGER REFERENCES usuarios(id),
    UNIQUE (cotacao_id, fornecedor_id, item_id)
);

CREATE INDEX idx_cotacao_respostas_cotacao ON cotacao_respostas(cotacao_id);
CREATE INDEX idx_cotacao_respostas_fornecedor ON cotacao_respostas(cotacao_id, fornecedor_id);
