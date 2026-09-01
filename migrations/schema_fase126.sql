-- Alphafitus OS — Fase 126 (Boleto: substitui Asaas por CNAB 240 direto
-- com Sicredi/Unicred)
--
-- Retomando o projeto pausado em 2026-08-22: usuário escolheu substituir
-- o Asaas por completo (não manter como opção paralela). Confirmado antes
-- desta fase: `boletos`/`configuracoes_boleto` (Fase 71) nunca tiveram
-- nenhum registro real em produção (0 linhas, Asaas nunca chegou a ser
-- configurado) — substituição segura, sem dado real pra migrar/perder.
--
-- Diferença fundamental do Asaas: CNAB é baseado em ARQUIVO, não em
-- chamada de API. O fluxo passa a ser: gerar remessa (baixa um .txt) ->
-- operador sobe manualmente no internet banking do banco -> banco
-- processa e devolve um arquivo de retorno -> operador sobe o retorno
-- aqui -> sistema lê e dá baixa automática nos títulos confirmados.
-- Nenhuma chamada de rede a banco nenhum em nenhum momento.
--
-- AVISO IMPORTANTE (repetido no serviço e na tela de configuração):
-- o layout abaixo segue o padrão FEBRABAN/CNAB 240 documentado
-- publicamente (Sicredi=748 e Unicred=136 seguem esse padrão comum de
-- cooperativas), mas cada banco tem pequenas variações próprias
-- documentadas no "Manual de Especificação Técnica" que ele mesmo
-- fornece ao cliente PJ. O usuário ainda não tem esse manual nem os
-- dados de convênio de cobrança — a estrutura é construída mesmo assim,
-- pronta pra validar campo a campo assim que esses dados existirem.
-- NUNCA enviar uma remessa de verdade ao banco antes dessa validação.

-- ============================================================
-- CONFIGURAÇÃO — substitui completamente a de Asaas (Fase 71)
-- ============================================================
DROP TABLE configuracoes_boleto;

CREATE TABLE configuracoes_boleto (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    banco_codigo            TEXT CHECK (banco_codigo IN ('748', '136')),  -- 748=Sicredi, 136=Unicred
    ambiente                TEXT NOT NULL DEFAULT 'homologacao' CHECK (ambiente IN ('homologacao', 'producao')),
    agencia                 TEXT,
    digito_agencia          TEXT,
    conta                   TEXT,
    digito_conta            TEXT,
    carteira                TEXT,
    convenio                TEXT,
    codigo_cedente          TEXT,
    -- Sequencial que a remessa usa pra numerar cada título (campo "nosso
    -- número") — precisa ser único e crescente pro banco nunca confundir
    -- dois títulos diferentes. Incrementado a cada boleto emitido, nunca
    -- reaproveitado mesmo se o boleto for cancelado depois.
    proximo_nosso_numero    INTEGER NOT NULL DEFAULT 1,
    -- Sequencial do PRÓPRIO ARQUIVO de remessa (campo "número sequencial
    -- do arquivo" do Header de Arquivo) — incrementado a cada remessa
    -- gerada, não a cada título.
    proximo_numero_remessa  INTEGER NOT NULL DEFAULT 1,
    atualizado_em           TEXT,
    atualizado_por          INTEGER REFERENCES usuarios(id)
);

INSERT INTO configuracoes_boleto (id) VALUES (1);

-- ============================================================
-- BOLETOS — mesma tabela, campos de provedor externo trocados por
-- campos de identificação bancária (CNAB)
-- ============================================================
DROP TABLE boletos;

CREATE TABLE boletos (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_receber_id        INTEGER NOT NULL REFERENCES contas_receber(id),
    cliente_id              INTEGER NOT NULL REFERENCES clientes(id),
    ambiente                TEXT NOT NULL CHECK (ambiente IN ('homologacao', 'producao')),
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN (
                                'pendente', 'em_remessa', 'recebido', 'vencido', 'cancelado'
                            )),
    banco_codigo            TEXT NOT NULL,
    -- "Nosso número" — identificador que o BANCO usa pra reconhecer este
    -- título quando o arquivo de retorno chega; é o que liga uma linha do
    -- retorno de volta a este boleto (não dá pra usar o id interno pra
    -- isso, o banco não sabe nada sobre nossos ids).
    nosso_numero            TEXT NOT NULL UNIQUE,
    valor                   REAL NOT NULL CHECK (valor > 0),
    vencimento              TEXT NOT NULL,
    linha_digitavel         TEXT,
    codigo_barras           TEXT,
    -- Preenchido quando o boleto entra numa remessa gerada (liga o
    -- título ao arquivo que foi de fato enviado ao banco); NULL enquanto
    -- só existe no sistema mas ainda não foi remetido.
    cnab_remessa_id         INTEGER REFERENCES cnab_remessas(id),
    -- Último código de ocorrência lido de um arquivo de retorno pra este
    -- título (ex.: '02'=confirmação de entrada, '06'=liquidação,
    -- '09'=baixado) — guardado cru, sem traduzir, pra auditoria/depuração
    -- caso um código não mapeado apareça.
    ultima_ocorrencia_retorno TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    atualizado_em           TEXT,
    justificativa_cancelamento TEXT,
    cancelado_em            TEXT,
    cancelado_por           INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_boletos_conta_receber ON boletos(conta_receber_id);
CREATE INDEX idx_boletos_status ON boletos(status);
CREATE INDEX idx_boletos_remessa ON boletos(cnab_remessa_id);

-- Mesma trava da Fase 72: nunca dois boletos 'pendente' (nem 'em_remessa')
-- ativos ao mesmo tempo pra a mesma conta a receber.
CREATE UNIQUE INDEX idx_boletos_conta_receber_ativo_unico
    ON boletos(conta_receber_id)
    WHERE status IN ('pendente', 'em_remessa');

-- ============================================================
-- REMESSAS E RETORNOS — histórico de arquivos trocados com o banco
-- ============================================================
CREATE TABLE cnab_remessas (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    banco_codigo            TEXT NOT NULL,
    numero_sequencial_arquivo INTEGER NOT NULL,
    quantidade_titulos      INTEGER NOT NULL,
    valor_total             REAL NOT NULL,
    nome_arquivo            TEXT NOT NULL,
    gerado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    gerado_por              INTEGER REFERENCES usuarios(id)
);

-- Append-only por design (mesma filosofia de ordem_producao_consumo,
-- Fase 3): um arquivo de retorno processado é um FATO histórico — nunca
-- se edita ou apaga o registro de que ele foi processado, mesmo que o
-- conteúdo dele tenha sido usado incorretamente (corrige-se com uma nova
-- baixa/estorno, nunca reescrevendo o que já aconteceu).
CREATE TABLE cnab_retornos (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    banco_codigo            TEXT NOT NULL,
    nome_arquivo            TEXT NOT NULL,
    quantidade_titulos_lidos INTEGER NOT NULL,
    quantidade_baixas_geradas INTEGER NOT NULL,
    conteudo_bruto          TEXT NOT NULL,  -- guarda o arquivo inteiro recebido, pra reprocessar/auditar se precisar
    processado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    processado_por          INTEGER REFERENCES usuarios(id)
);

CREATE TRIGGER cnab_retornos_bloqueia_update
BEFORE UPDATE ON cnab_retornos
BEGIN
    SELECT RAISE(ABORT, 'cnab_retornos é append-only: UPDATE não é permitido (histórico de arquivo processado não pode ser reescrito)');
END;

CREATE TRIGGER cnab_retornos_bloqueia_delete
BEFORE DELETE ON cnab_retornos
BEGIN
    SELECT RAISE(ABORT, 'cnab_retornos é append-only: DELETE não é permitido');
END;
