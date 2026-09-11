-- Fase 171 — CRM: Funil de Vendas (Oportunidades)
--
-- Pedido do usuário: "CRM de vendas em tempo real, cada mudança do que
-- está sendo feita pelos vendedores e usuários". Decisão de arquitetura
-- (conversa completa): em vez de só um feed de atividades solto, o que
-- genuinamente faltava no sistema é um FUNIL DE VENDAS de verdade — hoje
-- o Alphafitus só passa a acompanhar a venda DEPOIS que ela já virou
-- `pedidos_venda` (Fase 5); não existe rastreamento do que acontece ANTES
-- disso (prospecção, contato, proposta, negociação, perda). As duas
-- tabelas abaixo cobrem isso, e a segunda (atividades) É o feed em tempo
-- real pedido — tanto por oportunidade (linha do tempo) quanto agregado
-- (GET /crm/atividades-recentes, ver app/routes/crm.py).
--
-- Deliberadamente um módulo PRÓPRIO (`oportunidades`, não reaproveita
-- `comercial`) — a tela "Comercial (CRM)" já existente é cadastro de
-- cliente/pedido; este é um estágio ANTERIOR e nem todo vendedor que
-- monta pedido precisa (ou deve) ver o funil de prospecção de outro.

CREATE TABLE crm_oportunidades (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    -- Cliente já cadastrado (venda recorrente/expansão de conta) OU um
    -- prospect que ainda não tem cadastro em `clientes` — pelo menos um
    -- dos dois é obrigatório, nunca os dois ao mesmo tempo (checado no
    -- backend, não dá pra expressar como CHECK simples aqui porque um
    -- prospect pode legitimamente virar cliente_id depois, sem apagar o
    -- nome_prospect original).
    cliente_id              INTEGER REFERENCES clientes(id),
    nome_prospect           TEXT,
    contato_nome            TEXT,
    contato_telefone        TEXT,
    contato_email           TEXT,
    titulo                  TEXT NOT NULL,
    etapa                   TEXT NOT NULL DEFAULT 'novo_contato' CHECK (etapa IN (
                                'novo_contato', 'qualificacao', 'proposta_enviada',
                                'negociacao', 'fechado_ganho', 'fechado_perdido'
                            )),
    valor_estimado          REAL CHECK (valor_estimado IS NULL OR valor_estimado >= 0),
    origem                  TEXT,
    motivo_perda            TEXT,
    vendedor_responsavel_id INTEGER NOT NULL REFERENCES usuarios(id),
    -- Preenchido quando a oportunidade é marcada 'fechado_ganho' e
    -- vinculada a um pedido de venda de verdade (o pedido em si continua
    -- sendo criado pelo fluxo normal do Comercial — esta coluna só
    -- amarra os dois registros pra dar pra navegar de um pro outro e pro
    -- funil calcular taxa de conversão em cima de venda real).
    pedido_venda_id         INTEGER REFERENCES pedidos_venda(id),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER NOT NULL REFERENCES usuarios(id),
    atualizado_em           TEXT,
    etapa_atualizada_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    fechado_em              TEXT
);

CREATE INDEX idx_crm_oportunidades_vendedor ON crm_oportunidades(vendedor_responsavel_id);
CREATE INDEX idx_crm_oportunidades_etapa ON crm_oportunidades(etapa);
CREATE INDEX idx_crm_oportunidades_cliente ON crm_oportunidades(cliente_id);

-- Linha do tempo de cada oportunidade — toda mudança de etapa é logada
-- AQUI automaticamente pelo backend (nunca confia em nada vindo do
-- cliente pra `etapa_anterior`/`etapa_nova`), e o vendedor também
-- registra manualmente nota/ligação/reunião/e-mail. Consultada de duas
-- formas: por oportunidade (a "linha do tempo" da tela de detalhe) e de
-- forma agregada entre todas as oportunidades visíveis ao usuário (o
-- feed ao vivo geral, "o que o time de vendas está fazendo agora").
CREATE TABLE crm_oportunidades_atividades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    oportunidade_id     INTEGER NOT NULL REFERENCES crm_oportunidades(id),
    tipo                TEXT NOT NULL CHECK (tipo IN (
                            'criacao', 'nota', 'ligacao', 'reuniao', 'email', 'mudanca_etapa'
                        )),
    descricao           TEXT NOT NULL,
    etapa_anterior      TEXT,
    etapa_nova          TEXT,
    usuario_id          INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_crm_atividades_oportunidade ON crm_oportunidades_atividades(oportunidade_id);
CREATE INDEX idx_crm_atividades_criado_em ON crm_oportunidades_atividades(criado_em);
