-- ============================================================
-- FASE 123 — Recebimento e Importação de NF-e (Compras)
-- ============================================================
-- Fecha o ciclo Cotação (Fase 66) -> Pedido de Compra (Fase 58) -> Lote
-- (Fase 2) com a etapa que faltava: a nota fiscal do fornecedor chegando de
-- verdade. Até aqui, o recebimento de lote (app/routes/lotes.py) não tinha
-- NENHUMA conferência automática contra o que foi cotado/pedido, nem
-- suporte a receber numa unidade diferente da cadastrada no item.
--
-- Deliberadamente dividido em duas fases de entrega (ver plano):
--   Fase A (esta) — motor de conferência/conversão de unidade + telas,
--   alimentado por upload manual do XML. Funciona 100% sem depender da
--   SEFAZ, e é o que valida a lógica de negócio com XMLs reais.
--   Fase B (depois) — consulta automática à SEFAZ (NFeDistribuicaoDFe +
--   RecepçãoEvento, com certificado A1 próprio) alimentando a MESMA tabela
--   `nfe_recebimento` (só muda a coluna `fonte`) — nenhuma tabela
--   nova nessa fase, por isso as colunas relacionadas (certificado,
--   ultimo_nsu, manifestacao_sefaz) já nascem aqui.
--
-- Nenhuma tabela existente (itens, fornecedores, lotes, pedidos_compra,
-- itens_pedido_compra, cotacoes, cotacao_respostas) é alterada — só lida
-- por este módulo para resolver vínculo e conferência.
--
-- ATENÇÃO — colisão de nome evitada de propósito: a Fase 78 (SPED Fiscal)
-- já criou uma tabela `notas_fiscais_entrada` (captura MANUAL dos dados
-- fiscais completos — ICMS/ICMS-ST/IPI por item — usada pelo motor de
-- apuração e pelo bloqueio de aprovação de lote em Qualidade). Esta fase
-- NÃO duplica aquela tabela — as tabelas novas aqui chamam-se
-- `nfe_recebimento`/`nfe_recebimento_itens` (a FILA de recebimento/
-- conferência automatizada, alimentada pelo XML). Ao importar
-- (`POST /nfe-entrada/<id>/importar`, em app/routes/nfe_entrada.py), além
-- de gerar os `lotes`, o import TAMBÉM cria o registro correspondente na
-- `notas_fiscais_entrada` já existente (reaproveitando
-- `criar_nota_entrada_interna`, extraída de app/routes/fiscal.py só para
-- isso) — ou seja, a importação automática de XML passa a alimentar a
-- MESMA tabela fiscal que antes só se preenchia digitando à mão, com os
-- valores de ICMS/IPI lidos direto do XML em vez de recalculados.

PRAGMA foreign_keys = ON;

-- ============================================================
-- UNIDADES DE MEDIDA E CONVERSÃO
-- ============================================================
-- `itens.unidade_medida` (Fase 2) sempre foi um texto livre, sem catálogo
-- nem conversão — suficiente enquanto a nota sempre chegava na mesma
-- unidade do cadastro. Este catálogo cobre os dois casos pedidos:
-- massa/volume têm conversão matemática fixa (fator_para_base, na mesma
-- base: grama para massa, mililitro para volume); contagem (un/cx/pct/fr/
-- pote/sache) não tem — "1 caixa" não tem peso/volume universal, por isso
-- fator_para_base fica NULL e a conversão desse grupo é sempre resolvida
-- por item específico em `item_conversoes_unidade` abaixo.
CREATE TABLE unidades_medida (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo          TEXT NOT NULL UNIQUE,
    nome            TEXT NOT NULL,
    tipo            TEXT NOT NULL CHECK (tipo IN ('massa', 'volume', 'contagem')),
    fator_para_base REAL,
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Fator de conversão não-matemático, específico de um item (ex.: para o
-- item "Frasco 60 cápsulas", 1 caixa = 12 frascos — outro item pode ter uma
-- caixa com 24). Cadastrado uma vez (manual, na conferência de uma NF-e, ou
-- via cadastro do item) e reaproveitado automaticamente nas próximas notas
-- do mesmo item (pedido explícito do usuário, seção 9 da especificação).
CREATE TABLE item_conversoes_unidade (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES itens(id),
    unidade_origem  TEXT NOT NULL REFERENCES unidades_medida(codigo),
    unidade_destino TEXT NOT NULL REFERENCES unidades_medida(codigo),
    -- 1 unidade_origem = fator unidades_destino (ex.: origem='cx',
    -- destino='fr', fator=12).
    fator           REAL NOT NULL CHECK (fator > 0),
    criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    criado_por      INTEGER REFERENCES usuarios(id),
    UNIQUE (item_id, unidade_origem, unidade_destino)
);

CREATE INDEX idx_item_conversoes_item ON item_conversoes_unidade(item_id);

-- ============================================================
-- VÍNCULO CÓDIGO-DO-FORNECEDOR ↔ PRODUTO INTERNO
-- ============================================================
-- Quando o XML de uma NF-e traz o código que O FORNECEDOR usa para o
-- produto (cProd), esta tabela lembra a que item interno ele corresponde,
-- para não pedir esse vínculo de novo a cada nota do mesmo fornecedor
-- (seção 7 da especificação — "não usar apenas comparação textual de
-- descrição como vínculo definitivo").
CREATE TABLE fornecedor_produto_vinculo (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fornecedor_id     INTEGER NOT NULL REFERENCES fornecedores(id),
    codigo_fornecedor TEXT NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES itens(id),
    criado_em         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    criado_por        INTEGER REFERENCES usuarios(id),
    UNIQUE (fornecedor_id, codigo_fornecedor)
);

-- ============================================================
-- FILA DE RECEBIMENTO/CONFERÊNCIA DE NF-e (Central de NF-e Recebidas)
-- ============================================================
-- Não confundir com `notas_fiscais_entrada` (Fase 78) — ver nota no topo
-- deste arquivo. Esta tabela é o estado de trabalho ATÉ a importação;
-- depois de importada, o registro fiscal "oficial" passa a existir também
-- em `notas_fiscais_entrada`, e este aqui permanece como histórico do
-- processo de conferência (conversão de unidade aplicada, divergências
-- encontradas, quem aprovou).
CREATE TABLE nfe_recebimento (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Identificador fiscal único de verdade — trava de duplicidade (seção
    -- 13): uma chave já importada nunca gera um segundo lote/baixa.
    chave_acesso             TEXT NOT NULL UNIQUE,
    numero                   TEXT,
    serie                    TEXT,
    -- Nulável até o fornecedor ser resolvido (por CNPJ) ou vinculado
    -- manualmente — uma NF-e de um fornecedor ainda não cadastrado ainda
    -- assim pode ser recebida e analisada.
    fornecedor_id            INTEGER REFERENCES fornecedores(id),
    cnpj_emitente            TEXT NOT NULL,
    razao_social_emitente    TEXT,
    data_emissao             TEXT,
    valor_total              REAL NOT NULL DEFAULT 0,
    -- XML cru completo, em base64 — nunca alterado depois de gravado
    -- (seção 12: "o XML original deverá permanecer armazenado sem
    -- alteração"). Mesmo padrão de arquivo-em-coluna já usado em
    -- memorial_anexos/documentos.
    xml_original             TEXT NOT NULL,
    -- Evento FISCAL real (o que foi manifestado na SEFAZ) — nunca confundir
    -- com `situacao_interna` abaixo (seção 2: "nunca utilizar uma rejeição
    -- interna do ERP como se fosse automaticamente um evento fiscal").
    manifestacao_sefaz       TEXT NOT NULL DEFAULT 'pendente' CHECK (manifestacao_sefaz IN (
                                 'pendente', 'ciencia_operacao', 'confirmacao_operacao',
                                 'desconhecimento_operacao', 'operacao_nao_realizada'
                             )),
    -- Situação do NOSSO processo interno de conferência/aprovação.
    situacao_interna         TEXT NOT NULL DEFAULT 'aguardando_analise' CHECK (situacao_interna IN (
                                 'aguardando_analise', 'em_conferencia', 'aprovada',
                                 'rejeitada_internamente', 'importada', 'divergencia_encontrada'
                             )),
    -- Resolvido automaticamente (fornecedor + item com pedido em aberto) ou
    -- vinculado manualmente na tela de conferência.
    pedido_compra_id         INTEGER REFERENCES pedidos_compra(id),
    comprador_responsavel_id INTEGER REFERENCES usuarios(id),
    -- Fase A = 'manual_upload' (upload do XML); Fase B = 'sefaz_distribuicao'
    -- (consulta automática) — mesmo pipeline de conferência/importação para
    -- as duas, só muda como o XML chegou até aqui.
    fonte                    TEXT NOT NULL DEFAULT 'manual_upload' CHECK (fonte IN ('manual_upload', 'sefaz_distribuicao')),
    importada_em             TEXT,
    importada_por            INTEGER REFERENCES usuarios(id),
    criado_em                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    criado_por               INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_nfe_entrada_situacao ON nfe_recebimento(situacao_interna);
CREATE INDEX idx_nfe_entrada_fornecedor ON nfe_recebimento(fornecedor_id);
CREATE INDEX idx_nfe_entrada_pedido ON nfe_recebimento(pedido_compra_id);

CREATE TABLE nfe_recebimento_itens (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    nfe_recebimento_id      INTEGER NOT NULL REFERENCES nfe_recebimento(id),
    numero_item                 INTEGER NOT NULL,
    -- Dados crus do XML (nProd/cProd/xProd/NCM/CFOP/uCom/qCom/vUnCom) —
    -- nunca alterados; a conversão/vínculo abaixo é sempre um dado NOSSO,
    -- separado.
    codigo_produto_fornecedor   TEXT,
    descricao_xml               TEXT NOT NULL,
    ncm                         TEXT,
    cfop                        TEXT,
    quantidade_xml               REAL NOT NULL,
    unidade_xml                  TEXT NOT NULL,
    valor_unitario_xml           REAL NOT NULL,
    valor_total_xml               REAL NOT NULL,
    -- Vínculo/conversão — preenchidos pela conferência (automática via
    -- fornecedor_produto_vinculo, ou manual).
    item_id                      INTEGER REFERENCES itens(id),
    unidade_interna_selecionada  TEXT REFERENCES unidades_medida(codigo),
    quantidade_convertida        REAL,
    fator_conversao_aplicado     REAL,
    -- Preenchido só na importação (fecha o ciclo com `lotes`, Fase 2).
    lote_gerado_id               INTEGER REFERENCES lotes(id),
    UNIQUE (nfe_recebimento_id, numero_item)
);

CREATE INDEX idx_nfe_entrada_itens_nota ON nfe_recebimento_itens(nfe_recebimento_id);
CREATE INDEX idx_nfe_entrada_itens_item ON nfe_recebimento_itens(item_id);

-- Log de tudo que acontece com uma NF-e recebida (seção 2 — manifestação —
-- e seção 12 — rastreabilidade de qualquer alteração feita na importação).
CREATE TABLE nfe_recebimento_eventos (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    nfe_recebimento_id INTEGER NOT NULL REFERENCES nfe_recebimento(id),
    tipo_evento            TEXT NOT NULL,
    detalhe                TEXT,
    protocolo_sefaz        TEXT,
    usuario_id             INTEGER REFERENCES usuarios(id),
    criado_em              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_nfe_entrada_eventos_nota ON nfe_recebimento_eventos(nfe_recebimento_id);

-- ============================================================
-- CONFIGURAÇÃO (singleton id=1, mesmo padrão de configuracoes_nfe —
-- Fase 70 — e configuracoes_compras — Fase 61)
-- ============================================================
CREATE TABLE configuracoes_nfe_entrada (
    id                                INTEGER PRIMARY KEY CHECK (id = 1),
    -- Tolerâncias parametrizáveis (seção 5 — "não bloquear automaticamente
    -- toda a nota por qualquer diferença").
    tolerancia_preco_percentual       REAL NOT NULL DEFAULT 5,
    tolerancia_quantidade_percentual  REAL NOT NULL DEFAULT 2,
    -- Fase B — certificado A1 próprio da empresa. Mesmo padrão de segredo
    -- em coluna, nunca devolvido pela API, já usado em
    -- configuracoes_nfe.token_api (ver nota de segurança no plano: isto
    -- não é criptografia forte da chave privada, é o mesmo nível de
    -- proteção que o resto do sistema já usa para outros segredos).
    certificado_pfx                   TEXT,
    certificado_senha                 TEXT,
    certificado_nome_arquivo          TEXT,
    ambiente                          TEXT NOT NULL DEFAULT 'homologacao' CHECK (ambiente IN ('homologacao', 'producao')),
    -- Paginação da consulta à SEFAZ (NFeDistribuicaoDFe usa NSU
    -- incremental) — só usado pela Fase B.
    ultimo_nsu                        TEXT,
    atualizado_em                     TEXT,
    atualizado_por                    INTEGER REFERENCES usuarios(id)
);

-- ============================================================
-- CATÁLOGO INICIAL DE UNIDADES
-- ============================================================
-- massa: base = grama. volume: base = mililitro. contagem: sem fator
-- universal (ver comentário da tabela acima) — sempre resolvida por
-- item_conversoes_unidade quando precisar converter.
INSERT INTO unidades_medida (codigo, nome, tipo, fator_para_base) VALUES
    ('kg',    'Quilograma',  'massa',    1000),
    ('g',     'Grama',       'massa',    1),
    ('mg',    'Miligrama',   'massa',    0.001),
    ('mcg',   'Micrograma',  'massa',    0.000001),
    ('L',     'Litro',       'volume',   1000),
    ('mL',    'Mililitro',   'volume',   1),
    ('un',    'Unidade',     'contagem', NULL),
    ('cx',    'Caixa',       'contagem', NULL),
    ('pct',   'Pacote',      'contagem', NULL),
    ('fr',    'Frasco',      'contagem', NULL),
    ('pote',  'Pote',        'contagem', NULL),
    ('sache', 'Sachê',       'contagem', NULL);
