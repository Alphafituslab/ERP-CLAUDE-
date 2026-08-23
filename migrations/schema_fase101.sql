-- Alphafitus OS — Fase 101 (Consulta de CNPJ ao cadastrar cliente)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário: ao digitar o CNPJ de um cliente novo, buscar automaticamente razão social,
-- endereço, CEP, email etc. em vez de digitar tudo à mão. `clientes` já tinha TODOS os campos de
-- endereço/fiscais desde a Fase 70 (logradouro, numero_endereco, complemento_endereco, bairro,
-- municipio, codigo_ibge_municipio, uf, cep) — só faltava e-mail, que esta fase acrescenta.
--
-- `email` é OPCIONAL (nullable): nem toda consulta de CNPJ devolve um e-mail público, e o
-- cliente pode ser cadastrado sem consultar nada (digitação manual continua funcionando
-- exatamente como antes).

PRAGMA foreign_keys = ON;

ALTER TABLE clientes ADD COLUMN email TEXT;
