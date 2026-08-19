-- Fase 78 — Notas Fiscais de Entrada (captura estruturada), primeira fase do
-- projeto de SPED Fiscal (EFD ICMS/IPI). Ver o plano completo (fases 1-5) na
-- conversa que originou esta fase — aqui só entra a CAPTURA dos dados que já
-- estão na nota do fornecedor (papel/PDF), sem nenhum cálculo de imposto ou
-- regra tributária nova: isso vem nas fases seguintes, com parâmetros reais
-- confirmados pelo contador (alíquota por UF, ICMS-ST, DIFAL etc.), nunca
-- inventados aqui.

-- Mesmos campos de endereço/fiscal que a Fase 70 já adicionou em
-- `empresas`/`clientes` — precisamos deles em `fornecedores` para saber se
-- uma operação é interna ou interestadual (usado nas fases seguintes da
-- apuração, não nesta).
ALTER TABLE fornecedores ADD COLUMN inscricao_estadual TEXT;
ALTER TABLE fornecedores ADD COLUMN logradouro TEXT;
ALTER TABLE fornecedores ADD COLUMN numero_endereco TEXT;
ALTER TABLE fornecedores ADD COLUMN complemento_endereco TEXT;
ALTER TABLE fornecedores ADD COLUMN bairro TEXT;
ALTER TABLE fornecedores ADD COLUMN municipio TEXT;
ALTER TABLE fornecedores ADD COLUMN codigo_ibge_municipio TEXT;
ALTER TABLE fornecedores ADD COLUMN uf TEXT;
ALTER TABLE fornecedores ADD COLUMN cep TEXT;

CREATE TABLE notas_fiscais_entrada (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    fornecedor_id           INTEGER NOT NULL REFERENCES fornecedores(id),
    serie                   TEXT NOT NULL,
    numero                  TEXT NOT NULL,
    -- Opcional de propósito: nem toda nota em papel/PDF tem a chave de 44
    -- dígitos fácil de digitar à mão; melhor aceitar sem do que travar o
    -- lançamento.
    chave_acesso            TEXT,
    modelo                  TEXT NOT NULL DEFAULT '55' CHECK (modelo IN ('55', '65', '01')),
    data_emissao            TEXT NOT NULL,
    data_entrada            TEXT NOT NULL,
    valor_produtos          REAL NOT NULL DEFAULT 0,
    valor_frete             REAL NOT NULL DEFAULT 0,
    valor_seguro            REAL NOT NULL DEFAULT 0,
    valor_desconto          REAL NOT NULL DEFAULT 0,
    valor_outras_despesas   REAL NOT NULL DEFAULT 0,
    valor_icms              REAL NOT NULL DEFAULT 0,
    valor_icms_st           REAL NOT NULL DEFAULT 0,
    valor_ipi               REAL NOT NULL DEFAULT 0,
    valor_total_nota        REAL NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'lancada' CHECK (status IN ('lancada', 'cancelada')),
    observacoes             TEXT,
    motivo_cancelamento     TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    cancelada_em            TEXT,
    cancelada_por           INTEGER REFERENCES usuarios(id),
    -- Mesma nota do mesmo fornecedor não pode ser lançada duas vezes.
    UNIQUE (fornecedor_id, serie, numero)
);
CREATE INDEX idx_notas_fiscais_entrada_fornecedor ON notas_fiscais_entrada(fornecedor_id);
CREATE INDEX idx_notas_fiscais_entrada_data_entrada ON notas_fiscais_entrada(data_entrada);
CREATE INDEX idx_notas_fiscais_entrada_status ON notas_fiscais_entrada(status);

CREATE TABLE notas_fiscais_entrada_itens (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    nota_fiscal_entrada_id      INTEGER NOT NULL REFERENCES notas_fiscais_entrada(id),
    item_id                     INTEGER NOT NULL REFERENCES itens(id),
    -- Vínculo opcional com o lote gerado no recebimento físico (Fase 2) —
    -- nem toda linha da nota vira necessariamente um lote em separado.
    lote_id                     INTEGER REFERENCES lotes(id),
    ncm                         TEXT,
    cfop                        TEXT NOT NULL,
    cst_csosn                   TEXT NOT NULL,
    quantidade                  REAL NOT NULL CHECK (quantidade > 0),
    unidade                     TEXT NOT NULL,
    valor_unitario              REAL NOT NULL CHECK (valor_unitario >= 0),
    valor_total                 REAL NOT NULL,
    base_calculo_icms           REAL NOT NULL DEFAULT 0,
    aliquota_icms               REAL NOT NULL DEFAULT 0,
    valor_icms                  REAL NOT NULL DEFAULT 0,
    base_calculo_icms_st        REAL NOT NULL DEFAULT 0,
    aliquota_icms_st            REAL NOT NULL DEFAULT 0,
    valor_icms_st                REAL NOT NULL DEFAULT 0,
    aliquota_ipi                REAL NOT NULL DEFAULT 0,
    valor_ipi                   REAL NOT NULL DEFAULT 0
);
CREATE INDEX idx_notas_fiscais_entrada_itens_nota ON notas_fiscais_entrada_itens(nota_fiscal_entrada_id);
CREATE INDEX idx_notas_fiscais_entrada_itens_item ON notas_fiscais_entrada_itens(item_id);

-- Vínculo opcional do lote com a nota de entrada que o originou — não mexe
-- no campo de texto livre `lotes.nota_fiscal` já existente desde a Fase 2
-- (retrocompatível, nenhum lote antigo muda de comportamento).
ALTER TABLE lotes ADD COLUMN nota_fiscal_entrada_id INTEGER REFERENCES notas_fiscais_entrada(id);
