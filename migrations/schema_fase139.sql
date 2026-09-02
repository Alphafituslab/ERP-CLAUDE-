-- Alphafitus OS — Fase 139 (Terceirização Premium / "Monte sua linha" —
-- ficha cadastral: campos que o cliente precisa informar antes de o
-- contrato ser confeccionado)
--
-- Modelo real recebido do usuário em 2026-09-02: uma "FICHA CADASTRAL -
-- BASE PARA CONTRATOS" já usada por fora do sistema (Excel), com 4 blocos:
-- Da Empresa, De quem assina, Dados do produto (já coberto pelo módulo:
-- fórmula + pote/tampa/cápsula/quantidade — só faltava Cartucho/Pouch) e
-- Condição comercial. Decisão do usuário: dados fiscais/legais da empresa
-- (que não mudam de contrato pra contrato) vão pro cadastro permanente do
-- CLIENTE; quem assina e a condição comercial (que podem mudar a cada
-- pedido) ficam por PROJETO, dentro do briefing já existente.
--
-- Nenhum destes campos é obrigatório — mesmo raciocínio de todo campo
-- fiscal em `clientes` desde a Fase 70: fica em branco até quem for
-- confeccionar o contrato realmente precisar dele.

-- =============================================================================
-- Bloco "DA EMPRESA" da ficha — permanente, no cadastro do cliente.
-- Junta-se a CAMPOS_FISCAIS_CLIENTE_EDITAVEIS em app/routes/comercial.py
-- (mesmo mecanismo já usado por inscricao_estadual/endereço desde a
-- Fase 70) — nenhuma rota nova precisa ser escrita.
-- =============================================================================
ALTER TABLE clientes ADD COLUMN cpf TEXT;
ALTER TABLE clientes ADD COLUMN data_nascimento TEXT;
ALTER TABLE clientes ADD COLUMN alvara_sanitario TEXT;
ALTER TABLE clientes ADD COLUMN responsavel_correspondencia_nome_endereco TEXT;
ALTER TABLE clientes ADD COLUMN responsavel_correspondencia_telefone_email TEXT;
ALTER TABLE clientes ADD COLUMN email_financeiro TEXT;
ALTER TABLE clientes ADD COLUMN email_danfe_xml TEXT;
ALTER TABLE clientes ADD COLUMN crf_numero TEXT;

-- =============================================================================
-- Bloco "DE QUEM ASSINA" da ficha — por projeto (o signatário pode mudar
-- de um contrato pro outro mesmo sendo o mesmo cliente).
-- =============================================================================
ALTER TABLE terceirizacao_briefings ADD COLUMN assinante_nome TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN assinante_cpf TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN assinante_data_nascimento TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN assinante_telefone_whats TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN assinante_endereco TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN assinante_cidade_domicilio TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN assinante_email TEXT;

-- =============================================================================
-- Bloco "DADOS DO PRODUTO" — só faltava Cartucho/Pouch (fórmula e
-- pote/tampa/cápsula/quantidade já existem desde a Fase A).
-- =============================================================================
ALTER TABLE terceirizacao_briefings ADD COLUMN embalagem_secundaria TEXT;

-- =============================================================================
-- Bloco "CONDIÇÃO COMERCIAL" — por projeto.
-- =============================================================================
ALTER TABLE terceirizacao_briefings ADD COLUMN forma_pagamento TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN prazo_pagamento TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN valor_unitario REAL;
ALTER TABLE terceirizacao_briefings ADD COLUMN valor_total REAL;
ALTER TABLE terceirizacao_briefings ADD COLUMN notificacao_observacao TEXT;
ALTER TABLE terceirizacao_briefings ADD COLUMN excedente_rotulos TEXT;
