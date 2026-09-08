-- Alphafitus OS — Fase 160 (Histórico de Comissão e CNAB do Ema)
--
-- Pedido do usuário (2026-09-08): trazer o HISTÓRICO de comissão de
-- vendedores e de retornos bancários (CNAB) do ERP anterior "Ema" — só o
-- histórico, os saldos/cadastros já vieram na migração de 2026-08-31
-- (ver [[project_migracao_erp_ema]]). Investigação real no Postgres
-- restaurado do Ema (banco "ema_import") mostrou:
--   - Funil de vendas (CRM): NÃO migrado — a tabela de nomes de fase do
--     Ema (`crm_funil_fase`) está vazia, então os 230 registros de
--     "mudança de fase" existentes não têm rótulo nenhum pra mostrar.
--   - Comissão: 1707 registros reais (`comissao_extrato`), 14 vendedores
--     nomeados — o Alphafitus não tinha nenhuma tabela de "extrato de
--     comissão" até hoje (só um percentual global de config e uma
--     estimativa exibida ao vendedor, nunca persistida).
--   - CNAB: 959 retornos bancários reais, mas só uma fração bate com um
--     "nosso número" conhecido — o resto não tem onde amarrar hoje. Isso
--     aqui é um ARQUIVO histórico/consulta, separado da tabela `boletos`
--     operacional (que continua exigindo `conta_receber_id` de verdade
--     pra qualquer boleto ATIVO) — nunca mistura os dois.
--
-- Ambas as tabelas guardam o nome/dado bruto do Ema mesmo quando dá pra
-- ligar a um registro já existente no Alphafitus (usuario_id/cliente_id/
-- contas_receber_id ficam NULL quando não bate com nada) — histórico
-- nunca fica ilegível só porque o vínculo não foi encontrado.

CREATE TABLE comissoes_historico_ema (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id          INTEGER REFERENCES usuarios(id),
    nome_vendedor_ema   TEXT NOT NULL,
    cliente_id          INTEGER REFERENCES clientes(id),
    data                TEXT NOT NULL,
    valor               REAL NOT NULL,
    valor_entrada       REAL NOT NULL DEFAULT 0,
    valor_saida         REAL NOT NULL DEFAULT 0,
    numero_nf           TEXT,
    descricao           TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    codigo_legado_ema   TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_comissoes_historico_ema_legado ON comissoes_historico_ema(codigo_legado_ema);
CREATE INDEX idx_comissoes_historico_ema_usuario ON comissoes_historico_ema(usuario_id);
CREATE INDEX idx_comissoes_historico_ema_data ON comissoes_historico_ema(data);

CREATE TABLE cnab_historico_ema (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id          INTEGER REFERENCES clientes(id),
    contas_receber_id   INTEGER REFERENCES contas_receber(id),
    nosso_numero        TEXT,
    documento           TEXT,
    vencimento          TEXT,
    valor_titulo        REAL,
    valor_recebido      REAL,
    data_pagamento      TEXT,
    data_processamento  TEXT,
    codigo_ocorrencia   TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    codigo_legado_ema   TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_cnab_historico_ema_legado ON cnab_historico_ema(codigo_legado_ema);
CREATE INDEX idx_cnab_historico_ema_cliente ON cnab_historico_ema(cliente_id);
