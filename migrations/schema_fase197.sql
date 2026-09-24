-- Alphafitus OS — Fase 197 (Orçamentos: proposta formal com aprovação por link)
--
-- Pedido do usuário: uma proposta comercial formal pro cliente — capa,
-- validade, condições, enviável por link público (mesmo mecanismo do
-- Portal de Contrato/Terceirização: token opaco de 256 bits, sem JWT,
-- expira em N dias, revoga o anterior ao gerar um novo). O cliente abre o
-- link sem precisar de login e aprova ou recusa; ao aprovar, o sistema
-- gera automaticamente um Pedido de Venda de verdade (mesma tabela
-- `pedidos_venda`/`pedido_venda_itens` que o Comercial já usa), sem
-- precisar digitar tudo de novo. Preço de cada item é digitável na hora
-- (pode vir sugerido da tabela de preço do cliente, mas nunca travado
-- nela) — cada orçamento pode negociar um preço próprio.
PRAGMA foreign_keys = ON;

CREATE TABLE orcamentos (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,
    cliente_id              INTEGER NOT NULL REFERENCES clientes(id),
    vendedor_id             INTEGER REFERENCES usuarios(id),
    empresa_id              INTEGER REFERENCES empresas(id),
    condicao_pagamento_id   INTEGER REFERENCES condicoes_pagamento(id),
    validade_dias           INTEGER NOT NULL DEFAULT 15,
    condicoes_texto         TEXT,
    observacoes             TEXT,
    status                  TEXT NOT NULL DEFAULT 'rascunho'
                            CHECK (status IN ('rascunho','enviado','aprovado','recusado','expirado','cancelado')),
    motivo_recusa           TEXT,
    pedido_venda_id         INTEGER REFERENCES pedidos_venda(id),
    aprovado_em             TEXT,
    recusado_em             TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER NOT NULL REFERENCES usuarios(id),
    atualizado_em           TEXT,
    atualizado_por          INTEGER REFERENCES usuarios(id)
);

CREATE TABLE orcamento_itens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    orcamento_id    INTEGER NOT NULL REFERENCES orcamentos(id) ON DELETE CASCADE,
    item_id         INTEGER NOT NULL REFERENCES itens(id),
    quantidade      REAL NOT NULL CHECK (quantidade > 0),
    unidade         TEXT,
    preco_unitario  REAL NOT NULL CHECK (preco_unitario >= 0)
);

-- Mesmo desenho de `contrato_links_portal` (Fase 147) — token opaco,
-- expira, revoga o anterior ao emitir um novo, só um ativo por vez.
CREATE TABLE orcamento_links_portal (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    orcamento_id        INTEGER NOT NULL REFERENCES orcamentos(id) ON DELETE CASCADE,
    token               TEXT NOT NULL UNIQUE,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER NOT NULL REFERENCES usuarios(id),
    expira_em           TEXT NOT NULL,
    revogado            INTEGER NOT NULL DEFAULT 0 CHECK (revogado IN (0,1)),
    ultimo_acesso_em    TEXT,
    enviado_via_whatsapp INTEGER NOT NULL DEFAULT 0 CHECK (enviado_via_whatsapp IN (0,1))
);
CREATE UNIQUE INDEX idx_orcamento_link_ativo ON orcamento_links_portal(orcamento_id) WHERE revogado = 0;

-- "orcamentos.visualizar"/"criar"/"cancelar" nascem pelo seed.py normal
-- (INSERT idempotente em PERMISSOES_PADRAO), igual toda outra permissão
-- nova do sistema — nunca inserido direto numa migration.
