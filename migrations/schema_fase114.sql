-- Alphafitus OS — Fase 114 (Portfólio com fotos + forma de pagamento no App de Vendas)
--
-- Pedido do usuário: "ao clicar em portfólio deixar eu criar um portfólio
-- com fotos, nomes, imagens... e esse portfólio deve aparecer no app de
-- vendas onde a partir dele ao clicar em uma imagem ela vai sendo
-- adicionada ao carrinho até colocar o cliente, forma de pagamento e ser
-- enviado ao módulo de pedidos". A tela Portfólio (Fase 77) já existe e já
-- faz o carrinho/cliente/envio — faltavam só a foto por produto e a forma
-- de pagamento no envio.
--
-- `itens.imagem`: mesmo padrão base64 (data URI completo) de
-- `usuarios.foto_perfil` (Fase 113) — uma foto por item, sem tabela própria.
ALTER TABLE itens ADD COLUMN imagem TEXT;

-- `pedidos_venda.forma_pagamento`: nulável de propósito — só o fluxo do App
-- de Vendas (vendas_app.py::enviar_rascunho) exige o preenchimento; um
-- pedido criado pela tela de desktop (Comercial) continua sem essa
-- exigência, decidindo a forma de pagamento depois, no Financeiro, como
-- sempre foi.
ALTER TABLE pedidos_venda ADD COLUMN forma_pagamento TEXT;
