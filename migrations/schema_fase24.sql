-- Alphafitus OS — Fase 24 (Memorial Técnico ANVISA — Fundação)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas. Mesmas notas de portabilidade para PostgreSQL das fases
-- anteriores se aplicam aqui.
--
-- Primeira entrega de um módulo novo e maior, importado (reconstruído na
-- mesma tecnologia do resto do sistema, a pedido do cliente) a partir de um
-- sistema separado que ele já usava (Node.js/React/Postgres, hospedado no
-- Replit) para gerar o "Memorial Técnico" exigido pela ANVISA no registro/
-- notificação de suplementos alimentares: um documento por produto que reúne
-- composição nutricional, alegações, justificativas técnicas, métodos
-- analíticos, plano de estudo de estabilidade acelerada, ensaios
-- microbiológicos, referências bibliográficas e a conclusão técnica, com um
-- fluxo de rascunho → assinatura de responsáveis → aprovação.
--
-- Esta fase entrega a FUNDAÇÃO do módulo: empresas (o cliente/marca para
-- quem o memorial é feito — não confundir com a tabela `empresas` já
-- existente desde a Fase 1, que representa as unidades/CNPJs da PRÓPRIA
-- Alphafitus; por isso o nome `memorial_empresas`, para nunca colidir),
-- produtos (por empresa) e o memorial em si, com código interno automático
-- (formato CERT-AF-AAAAMMDD/NNN, sequência global), fluxo de status
-- (rascunho → em_andamento → em_revisao → concluido → aprovado, ou
-- reprovado a qualquer momento), assinatura de responsáveis (aprovação
-- automática ao atingir 2 assinaturas com o memorial em "concluido") e um
-- histórico narrativo próprio por memorial (mais legível que a auditoria
-- genérica da Fase 1 para quem acompanha o andamento de um documento
-- específico — ambos são gravados, não são excludentes).
--
-- Deliberadamente FORA do escopo desta primeira entrega (fica para as
-- próximas): os catálogos de apoio (advertências, alegações, modo de uso,
-- armazenamento, legislações, metodologias, nutrientes, referências
-- bibliográficas padrão) que no sistema original alimentam seletores/
-- autocompletar — por enquanto os campos correspondentes do memorial são
-- texto livre, e o memorial já funciona de ponta a ponta sem eles; anexos
-- de arquivo e a página de padronização de rótulo (rótulo formatado a
-- partir dos dados do memorial) também ficam para depois.

PRAGMA foreign_keys = ON;

CREATE TABLE memorial_empresas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_fantasia       TEXT NOT NULL,
    razao_social        TEXT NOT NULL,
    cnpj                TEXT NOT NULL UNIQUE,
    ie                  TEXT,
    responsavel_tecnico TEXT,
    crf                 TEXT,
    endereco            TEXT,
    cidade              TEXT,
    estado              TEXT,
    cep                 TEXT,
    telefone            TEXT,
    email               TEXT,
    status              TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_por          INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por      INTEGER REFERENCES usuarios(id),
    atualizado_em       TEXT
);

CREATE TABLE memorial_produtos (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id                INTEGER NOT NULL REFERENCES memorial_empresas(id),
    nome                      TEXT NOT NULL,
    categoria                 TEXT NOT NULL,
    forma_farmaceutica        TEXT NOT NULL,
    porcao_gramas             REAL NOT NULL,
    quantidade_porcoes        INTEGER NOT NULL,
    ingredientes_ativos       TEXT,
    excipientes               TEXT,
    embalagem                 TEXT,
    advertencias              TEXT,
    modo_de_uso               TEXT,
    armazenamento             TEXT,
    quantidade_capsulas_totais TEXT,
    peso_liquido              TEXT,
    tamanho_capsulas          TEXT,
    tipo_capsulas             TEXT,
    tipo_produto              TEXT,
    referencias_comerciais    TEXT,
    comprimento_rotulo        TEXT,
    largura_rotulo            TEXT,
    tamanho_pote              TEXT,
    tamanho_capsula           TEXT,
    numero_protocolo_anvisa   TEXT,
    status                    TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_por                INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por            INTEGER REFERENCES usuarios(id),
    atualizado_em             TEXT
);

CREATE INDEX idx_memorial_produtos_empresa ON memorial_produtos(empresa_id);

CREATE TABLE memoriais (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id                INTEGER NOT NULL REFERENCES memorial_produtos(id),
    codigo                    TEXT NOT NULL UNIQUE,
    numero_certificado        TEXT NOT NULL UNIQUE,
    status                    TEXT NOT NULL DEFAULT 'rascunho'
                              CHECK (status IN ('rascunho', 'em_andamento', 'em_revisao', 'concluido', 'aprovado', 'reprovado')),
    data_inicio               TEXT NOT NULL,
    data_fim                  TEXT NOT NULL,
    data_emissao              TEXT,
    objetivo                  TEXT,
    composicao_nutricional    TEXT,
    lista_ingredientes        TEXT,
    alegacoes                 TEXT,
    justificativas_tecnicas   TEXT,
    metodos_analiticos        TEXT,
    estabilidade_acelerada    TEXT,
    ensaios_microbiologicos   TEXT,
    calculos_nutricionais     TEXT,
    legislacao_aplicavel      TEXT,
    observacoes               TEXT,
    conclusao                 TEXT,
    referencias_bibliograficas TEXT,
    composicao_centesimal     TEXT,
    calculo_quantidade        TEXT,
    metodologias_aplicadas    TEXT,
    tipo_produto              TEXT,
    tipo_pote                 TEXT,
    ingredientes_ativos       TEXT,
    excipientes               TEXT,
    composicao_capsula        TEXT,
    -- Plano de estudo de estabilidade acelerada
    temperatura               TEXT,
    umidade_relativa          TEXT,
    periodo_estudo            TEXT,
    intervalos_teste          TEXT,
    -- Advertências, armazenamento e modo de uso (texto livre nesta fase;
    -- viram seletor a partir de catálogo numa fase futura)
    advertencias              TEXT,
    armazenamento             TEXT,
    modo_uso                  TEXT,
    -- Responsáveis
    elaborado_por             TEXT,
    aprovado_por              TEXT,
    laudo_emitido_por         TEXT,
    analista_senior           TEXT,
    email_rt                  TEXT,
    email_analista_senior     TEXT,
    observacao_analista       TEXT,
    criado_por                INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por            INTEGER REFERENCES usuarios(id),
    atualizado_em             TEXT
);

CREATE INDEX idx_memoriais_produto ON memoriais(produto_id);
CREATE INDEX idx_memoriais_status ON memoriais(status);

-- Uma assinatura por usuário por memorial (não por nome digitado, como no
-- sistema original — mais robusto contra homônimos/erro de digitação).
CREATE TABLE memorial_assinaturas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    memorial_id  INTEGER NOT NULL REFERENCES memoriais(id),
    usuario_id   INTEGER NOT NULL REFERENCES usuarios(id),
    nome         TEXT NOT NULL,
    cargo        TEXT NOT NULL,
    iniciais     TEXT NOT NULL,
    assinado_em  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (memorial_id, usuario_id)
);

CREATE INDEX idx_memorial_assinaturas_memorial ON memorial_assinaturas(memorial_id);

-- Histórico narrativo por memorial (append-only, mesma proteção a nível de
-- banco já usada em `auditoria` desde a Fase 1) — complementa a auditoria
-- genérica do sistema com uma linha do tempo legível por documento
-- ("Memorial criado", "Status alterado para: Concluído", "Fulano assinou
-- como Responsável Técnico" etc.), como no sistema original.
CREATE TABLE memorial_historico (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    memorial_id  INTEGER NOT NULL REFERENCES memoriais(id),
    usuario_id   INTEGER REFERENCES usuarios(id),
    usuario_nome TEXT NOT NULL DEFAULT 'Sistema',
    acao         TEXT NOT NULL,
    descricao    TEXT,
    criado_em    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_memorial_historico_memorial ON memorial_historico(memorial_id);

-- Só o UPDATE é bloqueado a nível de banco (ninguém pode reescrever uma
-- entrada do histórico já gravada — essa é a garantia de imutabilidade que
-- importa). DELETE não tem o mesmo bloqueio incondicional de
-- `auditoria` (Fase 1) de propósito: `DELETE /memoriais/<id>` (só permitido
-- em memoriais ainda "rascunho", ver `app/routes/memorial.py`) precisa
-- poder limpar o histórico do documento junto com o documento inteiro —
-- isso é remover o documento por completo, não editar/apagar um evento
-- específico do seu passado, que é o que a imutabilidade pretende evitar.
CREATE TRIGGER memorial_historico_bloqueia_update
BEFORE UPDATE ON memorial_historico
BEGIN
    SELECT RAISE(ABORT, 'memorial_historico é append-only: UPDATE não é permitido');
END;
