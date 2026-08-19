-- Alphafitus OS — Fase 70 (Fiscal — Emissão de NF-e via provedor terceirizado)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera
-- nada já existente (só ADD COLUMN em tabelas antigas e CREATE TABLE
-- novas — mesmo princípio de todas as migrações desde a Fase 2).
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- 1. Não implementamos comunicação direta com a SEFAZ (isso exigiria
--    montar/assinar XML conforme o schema oficial por estado, gerenciar
--    contingência, manter os webservices de cada UF atualizados — um
--    projeto gigante por si só). Em vez disso, integramos com um
--    PROVEDOR terceirizado (Focus NFe, escolhido por ter plano gratuito
--    de homologação e API JSON simples) que já resolve isso. O usuário
--    faz upload do certificado digital A1 DIRETAMENTE no painel do
--    provedor — o Alphafitus OS nunca guarda nem manipula o arquivo do
--    certificado, só o token de API do provedor (mascarado, nunca
--    devolvido em texto puro, mesmo padrão de `nuvem_secret_key` na Fase
--    67 e `smtp_senha` na Fase 37).
--
-- 2. Os CAMPOS FISCAIS novos (regime_tributario, NCM, CFOP,
--    codigo_tributario_icms etc.) vêm com valores-padrão SEGUROS/NEUTROS
--    quando o usuário não preenche nada — mas esses padrões são só um
--    PONTO DE PARTIDA. A legislação tributária brasileira tem centenas de
--    combinações possíveis de CST/CSOSN dependendo do produto, do regime
--    e do estado de destino; nenhum desses padrões substitui a revisão de
--    um contador antes de emitir uma nota que vale de verdade (ambiente
--    "producao"). Ver a seção correspondente no README para o texto
--    completo desse alerta.
--
-- 3. Uma NF-e não é um ledger append-only como movimentacoes_estoque ou
--    resultados_analise_historico: o status de verdade MUDA com o tempo
--    (processando -> autorizada/rejeitada, autorizada -> cancelada,
--    dias depois) porque a autorização acontece de forma assíncrona do
--    lado da SEFAZ/provedor. Por isso `notas_fiscais` é uma tabela de
--    status mutável (mesmo padrão de `pedidos_compra`/`contas_receber`),
--    não uma tabela travada por trigger.

PRAGMA foreign_keys = ON;

-- ============================================================
-- DADOS FISCAIS DO EMITENTE (empresa) — exigidos no bloco <emit> do XML
-- ============================================================
ALTER TABLE empresas ADD COLUMN inscricao_estadual TEXT;
ALTER TABLE empresas ADD COLUMN regime_tributario TEXT NOT NULL DEFAULT 'simples_nacional'
    CHECK (regime_tributario IN ('simples_nacional', 'lucro_presumido', 'lucro_real'));
ALTER TABLE empresas ADD COLUMN logradouro TEXT;
ALTER TABLE empresas ADD COLUMN numero_endereco TEXT;
ALTER TABLE empresas ADD COLUMN complemento_endereco TEXT;
ALTER TABLE empresas ADD COLUMN bairro TEXT;
ALTER TABLE empresas ADD COLUMN municipio TEXT;
ALTER TABLE empresas ADD COLUMN codigo_ibge_municipio TEXT;
ALTER TABLE empresas ADD COLUMN uf TEXT;
ALTER TABLE empresas ADD COLUMN cep TEXT;

-- ============================================================
-- DADOS FISCAIS DO CLIENTE (destinatário) — exigidos no bloco <dest>
-- ============================================================
ALTER TABLE clientes ADD COLUMN inscricao_estadual TEXT;
ALTER TABLE clientes ADD COLUMN logradouro TEXT;
ALTER TABLE clientes ADD COLUMN numero_endereco TEXT;
ALTER TABLE clientes ADD COLUMN complemento_endereco TEXT;
ALTER TABLE clientes ADD COLUMN bairro TEXT;
ALTER TABLE clientes ADD COLUMN municipio TEXT;
ALTER TABLE clientes ADD COLUMN codigo_ibge_municipio TEXT;
ALTER TABLE clientes ADD COLUMN uf TEXT;
ALTER TABLE clientes ADD COLUMN cep TEXT;

-- ============================================================
-- DADOS FISCAIS DO ITEM (produto) — exigidos em cada linha <det>
-- ============================================================
-- `codigo_tributario_icms` fica em branco por padrão de propósito: o
-- serviço (app/nfe_service.py::_codigo_tributario_icms_padrao) só usa um
-- valor-padrão neutro (CSOSN 102 para Simples Nacional, CST 00 para os
-- demais regimes) quando este campo está vazio — preenchê-lo aqui
-- sobrepõe o padrão automático para este item específico.
ALTER TABLE itens ADD COLUMN ncm TEXT;
ALTER TABLE itens ADD COLUMN cfop_padrao TEXT;
ALTER TABLE itens ADD COLUMN origem_mercadoria TEXT NOT NULL DEFAULT '0'
    CHECK (origem_mercadoria IN ('0', '1', '2', '3', '4', '5', '6', '7', '8'));
ALTER TABLE itens ADD COLUMN cest TEXT;
ALTER TABLE itens ADD COLUMN codigo_tributario_icms TEXT;

-- ============================================================
-- CONFIGURAÇÃO DO PROVEDOR DE NF-e — singleton (id sempre 1), mesmo
-- padrão de configuracoes_backup (Fase 67) e configuracoes_email (Fase 37)
-- ============================================================
CREATE TABLE configuracoes_nfe (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    provedor            TEXT NOT NULL DEFAULT 'focus_nfe' CHECK (provedor IN ('focus_nfe')),
    ambiente            TEXT NOT NULL DEFAULT 'homologacao' CHECK (ambiente IN ('homologacao', 'producao')),
    token_api           TEXT,
    serie               INTEGER NOT NULL DEFAULT 1 CHECK (serie > 0),
    atualizado_em       TEXT,
    atualizado_por      INTEGER REFERENCES usuarios(id)
);

-- ============================================================
-- NOTAS FISCAIS EMITIDAS — uma linha por tentativa de emissão
-- ============================================================
-- `referencia_provedor` é a chave de idempotência que enviamos ao
-- provedor (evita que uma tentativa de reenvio por falha de rede duplique
-- a nota do lado da SEFAZ) — gerada uma vez por tentativa, nunca reaproveitada.
-- `numero` é calculado como MAX(numero) já usado por esta empresa+série
-- (incluindo rejeitadas/canceladas, de propósito: nunca reaproveitar um
-- número já usado, mesmo que a tentativa anterior tenha falhado, para
-- nunca arriscar mandar um numero_nf duplicado à SEFAZ) + 1, nunca guardado
-- como contador à parte — mesmo princípio de "recalcular, nunca guardar
-- separado" já usado em toda a Fase 4/5/6.
CREATE TABLE notas_fiscais (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id                  INTEGER NOT NULL REFERENCES empresas(id),
    pedido_id                   INTEGER NOT NULL REFERENCES pedidos_venda(id),
    serie                       INTEGER NOT NULL,
    numero                      INTEGER NOT NULL,
    ambiente                    TEXT NOT NULL CHECK (ambiente IN ('homologacao', 'producao')),
    status                      TEXT NOT NULL DEFAULT 'processando_autorizacao' CHECK (status IN (
                                    'processando_autorizacao', 'autorizada', 'rejeitada', 'erro', 'cancelada'
                                )),
    referencia_provedor         TEXT NOT NULL UNIQUE,
    chave_acesso                TEXT,
    protocolo_autorizacao       TEXT,
    mensagem_sefaz               TEXT,
    url_danfe                   TEXT,
    url_xml                     TEXT,
    valor_total                 REAL NOT NULL,
    criado_em                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por                  INTEGER REFERENCES usuarios(id),
    atualizado_em                TEXT,
    justificativa_cancelamento  TEXT,
    cancelada_em                 TEXT,
    cancelada_por                INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_notas_fiscais_pedido ON notas_fiscais(pedido_id);
CREATE INDEX idx_notas_fiscais_empresa_serie ON notas_fiscais(empresa_id, serie);
CREATE INDEX idx_notas_fiscais_status ON notas_fiscais(status);

-- Linhas da nota — um retrato CONGELADO dos dados fiscais do item no
-- momento da emissão (mesmo raciocínio de pedido_venda_itens ficar
-- congelado depois de confirmado, Fase 5): se o cadastro do item mudar de
-- NCM/CFOP depois, uma nota já emitida continua mostrando o que foi
-- DE FATO declarado à SEFAZ naquele momento.
CREATE TABLE notas_fiscais_itens (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nota_fiscal_id      INTEGER NOT NULL REFERENCES notas_fiscais(id),
    item_id             INTEGER NOT NULL REFERENCES itens(id),
    descricao           TEXT NOT NULL,
    ncm                 TEXT NOT NULL,
    cfop                TEXT NOT NULL,
    origem_mercadoria   TEXT NOT NULL,
    codigo_tributario_icms TEXT NOT NULL,
    quantidade          REAL NOT NULL,
    unidade             TEXT NOT NULL,
    valor_unitario      REAL NOT NULL,
    valor_total          REAL NOT NULL
);

CREATE INDEX idx_notas_fiscais_itens_nota ON notas_fiscais_itens(nota_fiscal_id);
