-- Alphafitus OS — Fase 86 (Transportadora / Coleta — MVP)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Não existia NENHUM conceito de transportadora/frete/coleta em lugar nenhum do sistema antes
-- desta fase (confirmado por busca exaustiva no repositório inteiro) — isto é inteiramente
-- novo, do zero. Escopo deliberadamente MÍNIMO (MVP): um cadastro simples de transportadoras e
-- um agendamento/confirmação de coleta por pedido de venda já EXPEDIDO — sem rastreamento de
-- entrega, sem integração com API de transportadora nenhuma, sem cálculo de frete. Se o
-- cliente precisar de mais (frete calculado, código de rastreio, múltiplas coletas parciais
-- por pedido), isso é um projeto à parte, maior.
--
-- A confirmação de coleta é o primeiro uso REAL do catálogo de fluxo configurável da Fase 81
-- (`app/fluxo_service.py::marcar_concluida`) para uma etapa `origem = 'sistema'` — ela marca
-- a etapa "Coleta pela Transportadora" automaticamente no momento exato da confirmação, sem
-- duplicar a lógica de negócio em dois lugares.

PRAGMA foreign_keys = ON;

CREATE TABLE transportadoras (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL,
    cnpj            TEXT,
    telefone        TEXT,
    status          TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por      INTEGER REFERENCES usuarios(id)
);

-- Uma linha por tentativa de agendamento de coleta contra um pedido já expedido. Um pedido
-- pode ter mais de uma linha ao longo do tempo (ex.: uma agendada foi cancelada e outra
-- agendada depois), mas isso é decidido em código (mesmo padrão de `boletos`, Fase 71), não
-- por CHECK — SQLite não consulta outras linhas dentro de um CHECK.
CREATE TABLE pedido_venda_coletas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_venda_id     INTEGER NOT NULL REFERENCES pedidos_venda(id),
    transportadora_id   INTEGER NOT NULL REFERENCES transportadoras(id),
    status              TEXT NOT NULL DEFAULT 'agendada' CHECK (status IN ('agendada', 'coletada', 'cancelada')),
    data_agendada       TEXT,
    coletado_em         TEXT,
    coletado_por        INTEGER REFERENCES usuarios(id),
    observacoes         TEXT,
    motivo_cancelamento TEXT,
    cancelado_em        TEXT,
    cancelado_por       INTEGER REFERENCES usuarios(id),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER REFERENCES usuarios(id)
);
CREATE INDEX idx_pedido_venda_coletas_pedido ON pedido_venda_coletas(pedido_venda_id);

-- Primeira etapa de catálogo com origem='sistema' (Fase 81) — marcada
-- automaticamente por app/routes/transportadoras.py::confirmar_coleta,
-- nunca por ação manual avulsa.
INSERT INTO tipos_etapa_fluxo (entidade_tipo, codigo, nome, ordem_padrao, origem) VALUES
    ('pedido_venda', 'coleta_transportadora', 'Coleta pela Transportadora', 2, 'sistema');
