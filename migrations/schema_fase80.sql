-- Fase 80 — Solicitações de Materiais/EPI: fluxo completo pedido → aprovação
-- (com segregação de função, como toda aprovação sensível do sistema
-- desde a Fase 1) → entrega → confirmação de recebimento pelo próprio
-- solicitante, com trilha de auditoria em cada etapa (via app/audit.py,
-- mesma tabela imutável usada pelo resto do sistema) e comprovante em PDF
-- — para EPI, isso é o equivalente digital da Ficha de Controle de
-- Fornecimento de EPI exigida pela NR-6, com Certificado de Aprovação
-- (CA) do equipamento.
--
-- Catálogo PRÓPRIO (`materiais_solicitaveis`), deliberadamente SEM
-- vínculo com `itens` — é um domínio diferente (consumíveis/EPI entregues
-- a pessoas, não matéria-prima/produto rastreado por lote com FEFO/QMS) e
-- estender o CHECK de `itens.tipo` exigiria recriar a tabela inteira
-- (SQLite não altera CHECK existente), um risco desnecessário para um
-- catálogo que não precisa de nada da infraestrutura de lote/estoque.
CREATE TABLE materiais_solicitaveis (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo              TEXT NOT NULL UNIQUE,
    descricao           TEXT NOT NULL,
    categoria           TEXT,
    e_epi               INTEGER NOT NULL DEFAULT 0 CHECK (e_epi IN (0, 1)),
    -- Certificado de Aprovação (NR-6) — só faz sentido quando e_epi=1, mas
    -- fica sem CHECK cruzado de propósito (mesmo espírito de outros campos
    -- "opcional conforme contexto" já usados no sistema, ex.: empresa_id
    -- em vários lugares desde a Fase 52): mais simples deixar em branco do
    -- que travar o cadastro por causa disso.
    numero_ca           TEXT,
    unidade_medida      TEXT NOT NULL DEFAULT 'un',
    status              TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER REFERENCES usuarios(id),
    atualizado_em       TEXT,
    atualizado_por      INTEGER REFERENCES usuarios(id)
);

CREATE TABLE solicitacoes_material (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                      TEXT NOT NULL UNIQUE,
    solicitante_id              INTEGER NOT NULL REFERENCES usuarios(id),
    -- Texto livre de propósito — o sistema não tem uma tabela de
    -- setores/departamentos hoje, e criar uma só para isto seria escopo
    -- maior do que o pedido; um campo livre já resolve "de qual setor
    -- veio o pedido" para fins de relatório/auditoria.
    setor_solicitante           TEXT,
    prioridade                  TEXT NOT NULL DEFAULT 'media' CHECK (prioridade IN ('baixa', 'media', 'alta', 'urgente')),
    justificativa               TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN (
                                    'pendente', 'aprovada', 'rejeitada', 'entregue',
                                    'recebimento_confirmado', 'cancelada'
                                )),
    aprovador_id                INTEGER REFERENCES usuarios(id),
    decidido_em                 TEXT,
    motivo_rejeicao             TEXT,
    entregue_por_id             INTEGER REFERENCES usuarios(id),
    entregue_em                 TEXT,
    observacoes_entrega         TEXT,
    -- Segundo passo de confirmação, feito pelo PRÓPRIO solicitante — sem
    -- isso, a "prova de entrega" seria só a palavra de quem entregou; com
    -- isso, fica registrado que quem pediu de fato recebeu (mesmo
    -- espírito de assinatura na Ficha de EPI da NR-6). Opcional: uma
    -- entrega pode ficar em 'entregue' sem confirmação se o solicitante
    -- nunca voltar ao sistema — não bloqueia nada, só fica visível.
    recebimento_confirmado_em   TEXT,
    motivo_cancelamento         TEXT,
    cancelado_em                TEXT,
    cancelado_por               INTEGER REFERENCES usuarios(id),
    criado_em                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por                  INTEGER REFERENCES usuarios(id)
);
CREATE INDEX idx_solicitacoes_material_status ON solicitacoes_material(status);
CREATE INDEX idx_solicitacoes_material_solicitante ON solicitacoes_material(solicitante_id);

CREATE TABLE solicitacoes_material_itens (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitacao_id              INTEGER NOT NULL REFERENCES solicitacoes_material(id),
    material_id                 INTEGER NOT NULL REFERENCES materiais_solicitaveis(id),
    quantidade_solicitada       REAL NOT NULL CHECK (quantidade_solicitada > 0),
    -- Preenchido só na entrega — permite entrega PARCIAL (pediu 5, só
    -- havia 3 no momento) sem precisar de um status novo só para isso;
    -- a tela mostra a diferença claramente quando quantidade_entregue <
    -- quantidade_solicitada.
    quantidade_entregue         REAL,
    -- Ex.: tamanho de luva/máscara (P/M/G/GG) — opcional, só texto livre
    -- de propósito (a variação de "especificação" por tipo de EPI é
    -- grande demais para modelar em colunas próprias nesta fase).
    especificacao               TEXT
);
CREATE INDEX idx_solicitacoes_material_itens_solicitacao ON solicitacoes_material_itens(solicitacao_id);
