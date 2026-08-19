-- Alphafitus OS — Fase 71 (Financeiro — Emissão de Boleto Bancário via
-- provedor terceirizado)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera
-- nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- 1. Não integramos direto com nenhum banco (isso exigiria homologação
--    bilateral banco a banco, convênio de cobrança, certificados
--    próprios por instituição — um projeto à parte por banco). Em vez
--    disso, integramos com um gateway de pagamentos terceirizado (Asaas,
--    escolhido pelo mesmo motivo do Focus NFe na Fase 70: API REST
--    simples, ambiente de testes — "sandbox" — gratuito), que já é
--    conveniado com a rede bancária e devolve linha digitável, código de
--    barras e um link de PDF prontos.
--
-- 2. Diferente da Fase 70 (NF-e, que é por EMPRESA emitente), a conta no
--    provedor de boleto é uma única conta GLOBAL do sistema (o token de
--    API não é por empresa) — `configuracoes_boleto` é um singleton sem
--    `empresa_id`, mesma simplificação consciente de que este sistema
--    ainda não modela múltiplas contas bancárias por empresa em nenhum
--    outro lugar (Conciliação Bancária, Fase 40, também é uma única
--    conta/extrato).
--
-- 3. `clientes.id_externo_asaas` existe para EVITAR duplicar o cadastro
--    do cliente no provedor a cada boleto novo: na primeira vez que um
--    cliente recebe um boleto, o sistema busca (por CNPJ) ou cria o
--    cliente no Asaas e GUARDA o id devolvido aqui — as próximas emissões
--    para o mesmo cliente reaproveitam esse id em vez de criar um cliente
--    novo no provedor a cada boleto.
--
-- 4. `boletos` não é um ledger append-only como `contas_receber_baixas`:
--    o status muda de verdade com o tempo (pendente -> recebido/vencido/
--    cancelado), assim como `notas_fiscais` na Fase 70 — mesmo raciocínio,
--    mesma estrutura de tabela mutável.

PRAGMA foreign_keys = ON;

ALTER TABLE clientes ADD COLUMN id_externo_asaas TEXT;

-- ============================================================
-- CONFIGURAÇÃO DO PROVEDOR DE BOLETO — singleton (id sempre 1), mesmo
-- padrão de configuracoes_nfe (Fase 70), configuracoes_backup (Fase 67)
-- ============================================================
CREATE TABLE configuracoes_boleto (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    provedor            TEXT NOT NULL DEFAULT 'asaas' CHECK (provedor IN ('asaas')),
    ambiente            TEXT NOT NULL DEFAULT 'sandbox' CHECK (ambiente IN ('sandbox', 'producao')),
    token_api           TEXT,
    atualizado_em       TEXT,
    atualizado_por      INTEGER REFERENCES usuarios(id)
);

-- ============================================================
-- BOLETOS EMITIDOS — uma linha por tentativa de emissão contra uma conta
-- a receber
-- ============================================================
-- `referencia_provedor` é a chave de idempotência enviada ao provedor
-- (campo `externalReference` do Asaas) — gerada uma vez por tentativa.
-- Uma conta a receber pode ter mais de uma linha aqui ao longo do tempo
-- (ex.: um boleto vencido é cancelado e outro é gerado com novo
-- vencimento), mas nunca duas linhas com status 'pendente' AO MESMO
-- TEMPO para a mesma conta (verificado em código, não em CHECK — SQLite
-- não suporta CHECK que consulte outras linhas).
CREATE TABLE boletos (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_receber_id        INTEGER NOT NULL REFERENCES contas_receber(id),
    cliente_id              INTEGER NOT NULL REFERENCES clientes(id),
    ambiente                TEXT NOT NULL CHECK (ambiente IN ('sandbox', 'producao')),
    status                  TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN (
                                'pendente', 'recebido', 'vencido', 'cancelado', 'erro'
                            )),
    referencia_provedor     TEXT NOT NULL UNIQUE,
    id_pagamento_provedor   TEXT,
    valor                   REAL NOT NULL CHECK (valor > 0),
    vencimento              TEXT NOT NULL,
    linha_digitavel         TEXT,
    codigo_barras           TEXT,
    url_boleto              TEXT,
    mensagem_provedor       TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    atualizado_em            TEXT,
    justificativa_cancelamento TEXT,
    cancelado_em             TEXT,
    cancelado_por            INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_boletos_conta_receber ON boletos(conta_receber_id);
CREATE INDEX idx_boletos_status ON boletos(status);
