-- Fase 79 — SPED Fiscal (2/5): Configuração Fiscal (parâmetros de apuração).
--
-- "Livro de regras" configurável — NENHUM cálculo de imposto roda ainda
-- (isso é a Fase 80, o motor de apuração do Bloco E). Esta fase só guarda
-- os parâmetros que a apuração vai usar, com valores padrão baseados em
-- Santa Catarina (estado da empresa) e nas regras federais estáveis
-- (Resolução do Senado 22/89 + 13/2012 para ICMS interestadual) — TODOS
-- editáveis na tela, nunca fixos no código. Alíquotas estaduais mudam por
-- lei; confirme o valor vigente com o contador antes de usar em produção
-- (aviso permanente na tela, não só aqui no comentário).
CREATE TABLE configuracoes_fiscais_sped (
    id                                          INTEGER PRIMARY KEY CHECK (id = 1),
    uf_empresa                                  TEXT NOT NULL DEFAULT 'SC',
    -- ICMS interno (dentro do próprio estado) — 17% é a alíquota geral
    -- histórica de SC; CONFIRME o valor vigente.
    aliquota_icms_interna                       REAL NOT NULL DEFAULT 17.0,
    -- ICMS interestadual — regra federal estável (Resolução do Senado
    -- 22/89): 12% para vendas Sul/Sudeste, 7% para Norte/Nordeste/Centro-
    -- Oeste/ES, saindo de SC (Sul).
    aliquota_icms_interestadual_sul_sudeste     REAL NOT NULL DEFAULT 12.0,
    aliquota_icms_interestadual_norte_nordeste_co REAL NOT NULL DEFAULT 7.0,
    -- ICMS interestadual para produto com conteúdo importado > 40%
    -- (Resolução do Senado 13/2012) — federal, não muda por estado.
    aliquota_icms_interestadual_importado       REAL NOT NULL DEFAULT 4.0,
    -- PIS/COFINS — Lucro Real = não-cumulativo (1,65% + 7,6%, com direito
    -- a crédito); Lucro Presumido = cumulativo (0,65% + 3%, sem crédito).
    regime_pis_cofins                           TEXT NOT NULL DEFAULT 'nao_cumulativo'
                                                     CHECK (regime_pis_cofins IN ('cumulativo', 'nao_cumulativo')),
    aliquota_pis                                REAL NOT NULL DEFAULT 1.65,
    aliquota_cofins                             REAL NOT NULL DEFAULT 7.6,
    -- Empresa industrial (fabrica) é contribuinte de IPI, com direito a
    -- crédito na compra de insumos — desliga toda a apuração de IPI
    -- (Bloco E parte IPI) quando marcado como false.
    contribuinte_ipi                            INTEGER NOT NULL DEFAULT 1 CHECK (contribuinte_ipi IN (0, 1)),
    -- DIFAL (EC 87/2015) só se aplica a venda interestadual para
    -- consumidor final NÃO contribuinte — sinalizador simples aqui; a
    -- tabela de alíquota interna + FCP de cada um dos 26 outros estados
    -- fica para quando/se isso for realmente necessário (não construída
    -- nesta fase para não adicionar 26 linhas de dado nunca usado).
    ha_vendas_consumidor_final_fora_estado      INTEGER NOT NULL DEFAULT 0
                                                     CHECK (ha_vendas_consumidor_final_fora_estado IN (0, 1)),
    observacoes                                 TEXT,
    atualizado_em                               TEXT,
    atualizado_por                              INTEGER REFERENCES usuarios(id)
);
