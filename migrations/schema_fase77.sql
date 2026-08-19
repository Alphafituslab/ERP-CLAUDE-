-- Fase 77 — Portfólio dinâmico no App de Vendas + Duplicar Pedido (Comercial
-- e App de Vendas).
--
-- categoria: campo NOVO e opcional (NULL por padrão) em `itens` — usado só
-- para agrupar visualmente os produtos vendáveis na tela de Portfólio do
-- App de Vendas (ex.: "Proteínas", "Vitaminas", "Aminoácidos", "Creatina").
-- NULL preserva o comportamento de qualquer item já cadastrado antes desta
-- fase (aparece no Portfólio na categoria "Outros"); não é usado em nenhuma
-- regra de negócio (estoque, produção, fiscal) — é só metadado de exibição.
ALTER TABLE itens ADD COLUMN categoria TEXT;
