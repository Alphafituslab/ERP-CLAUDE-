-- Alphafitus OS — Fase 212 (Precificação: cálculo de rentabilidade e custo)
--
-- Pedido do usuário 2026-09-26: uma ferramenta DE VERDADE dentro do
-- sistema pra calcular preço/rentabilidade, substituindo a planilha Excel
-- "Precificação Clayton Eduardo correto.xlsx" — especificamente a lógica
-- da aba "VARIANDO PREÇO" (a aba "MEIA" foi deixada de fora por pedido
-- explícito). Fórmula (ver app/precificacao_service.py para os detalhes e
-- para a correção de um erro real encontrado na planilha original: a
-- comissão era descontada do preço final dividindo por (1+comissão), o
-- que não bate com o resto da própria planilha, que sempre trata comissão
-- como um desconto "por dentro" do preço — corrigido pra (1-comissão)).
--
-- Regime tributário da empresa é Lucro Real (confirmado pelo usuário) —
-- por isso a alíquota combinada de IRPJ+Adicional+CSLL é editável por
-- cenário (default 34%, igual todas as abas da planilha original já
-- usavam), em vez de um número travado no código.
--
-- Nada aqui guarda número CALCULADO (preço final, lucro, IRPJ etc.) — só
-- os INSUMOS do cálculo. Os resultados são sempre derivados na hora pela
-- mesma função usada no cálculo "sem salvar", pro mesmo princípio já usado
-- em custeio/estoque/financeiro: nunca um número guardado que pode
-- dessincronizar da fórmula.
PRAGMA foreign_keys = ON;

CREATE TABLE precificacoes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL,
    item_id                 INTEGER REFERENCES itens(id),
    modo                    TEXT NOT NULL DEFAULT 'markup' CHECK (modo IN ('markup', 'preco_fixo')),
    custo_producao          REAL NOT NULL CHECK (custo_producao >= 0),
    custo_origem            TEXT NOT NULL DEFAULT 'manual' CHECK (custo_origem IN ('manual', 'custeio_sistema')),
    icms_pct                REAL NOT NULL DEFAULT 0,
    pis_pct                 REAL NOT NULL DEFAULT 0,
    cofins_pct              REAL NOT NULL DEFAULT 0,
    analises_pct            REAL NOT NULL DEFAULT 0,
    frete_pct               REAL NOT NULL DEFAULT 0,
    despesas_fixas_pct      REAL NOT NULL DEFAULT 0,
    comissao_pct            REAL NOT NULL DEFAULT 0,
    margem_bruta_pct        REAL,
    preco_venda_final       REAL,
    aliquota_irpj_csll_pct  REAL NOT NULL DEFAULT 34,
    quantidade              REAL NOT NULL DEFAULT 1 CHECK (quantidade > 0),
    observacoes             TEXT,
    status                  TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'arquivado')),
    criado_por_id           INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    atualizado_em           TEXT,
    atualizado_por_id       INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_precificacoes_item ON precificacoes(item_id);

-- "precificacao.visualizar"/"criar"/"excluir" nascem pelo seed.py normal
-- (INSERT idempotente em PERMISSOES_PADRAO), igual toda outra permissão
-- nova do sistema — nunca inserido direto numa migration.
