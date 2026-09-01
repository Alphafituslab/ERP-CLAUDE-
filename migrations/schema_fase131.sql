-- Alphafitus OS — Fase 131 (Pedidos de Venda: tela própria com filtros)
--
-- Pedido do usuário: uma aba SÓ para Pedidos de Venda (hoje era uma
-- tabelinha pequena dentro de Comercial, sem filtro nenhum), com filtro
-- por status (orçamento/aprovado/cancelado), por cliente, por "faturado"
-- (tem NF-e autorizada vinculada), e por TIPO de pedido — conceito novo,
-- terceirização (fabricação sob encomenda, sem marca do cliente na
-- fórmula) ou marca própria (produto com a marca do próprio cliente).
--
-- "Orçamento"/"Aprovado" são como o usuário chama, na prática, os
-- status que já existem desde a Fase 5 (`rascunho`/`confirmado`+
-- `expedido`) — não precisou de status novo, só de filtro na tela.
-- "Faturado" também não precisou de coluna nova — é derivado de existir
-- uma `notas_fiscais.status = 'autorizada'` vinculada ao pedido (Fase 70).

ALTER TABLE pedidos_venda ADD COLUMN tipo_pedido TEXT CHECK (tipo_pedido IN ('terceirizacao', 'marca_propria'));
