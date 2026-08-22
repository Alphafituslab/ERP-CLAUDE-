-- Alphafitus OS — Fase 85 (Liberação do lote condicionada à NF-e de Entrada)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário: "retenção até a liberação da matéria-prima após entrada da NFe no
-- sistema" — ou seja, um lote recebido de fornecedor só pode ser aprovado pelo CQ depois de
-- estar vinculado a uma Nota Fiscal de Entrada já lançada (Fase 78). Antes desta fase,
-- `lotes.nota_fiscal_entrada_id` (Fase 78) era só um vínculo opcional, nunca checado em
-- lugar nenhum na hora de aprovar.
--
-- Singleton de configuração, MESMO padrão de `configuracoes_fiscais_sped` (Fase 79) —
-- padrão 0 (desligado), para não quebrar nenhum lote que já esteja hoje em
-- 'aguardando_aprovacao' sem NF-e de entrada vinculada (nenhuma instalação existente muda de
-- comportamento só por esta fase existir; é uma escolha explícita do Administrador ligar isso).
--
-- IMPORTANTE — por que a checagem em app/routes/lotes.py::aprovar só se aplica a lotes com
-- `origem = 'recebimento'`: um lote com `origem = 'producao'` (gerado pela conclusão de uma
-- Ordem de Produção, Fase 3) NUNCA teve nem terá uma Nota Fiscal de Entrada — ele não veio de
-- um fornecedor. Aplicar esta trava sem essa distinção bloquearia a aprovação de TODO produto
-- fabricado internamente, o que não é o que o usuário pediu (o pedido é especificamente sobre
-- matéria-prima recebida).

PRAGMA foreign_keys = ON;

CREATE TABLE configuracoes_qualidade (
    id                                              INTEGER PRIMARY KEY CHECK (id = 1),
    exigir_nota_fiscal_entrada_para_aprovar_lote     INTEGER NOT NULL DEFAULT 0
                                                          CHECK (exigir_nota_fiscal_entrada_para_aprovar_lote IN (0, 1)),
    atualizado_em                                    TEXT,
    atualizado_por                                   INTEGER REFERENCES usuarios(id)
);

INSERT INTO configuracoes_qualidade (id) VALUES (1);
