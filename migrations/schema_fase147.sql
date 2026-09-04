-- Alphafitus OS — Fase 147: Gerador de Contratos.
--
-- Pedido do usuário (2026-09-03): gerar o "Contrato de Industrialização
-- de Produtos Nutracêuticos por Encomenda" (modelo real enviado pelo
-- usuário) puxando automaticamente os dados da Alphafitus (cabeçalho) e
-- do cliente. Assinatura eletrônica reaproveita o MESMO método já
-- construído pra Terceirização (Fase 140/145): link do portal sem
-- login, captura de nome/CPF/e-mail/IP/navegador, hash SHA-256 do PDF
-- final, snapshot congelado por versão.
--
-- Revisão no mesmo dia (2026-09-03), ainda ANTES de ir pra produção —
-- desenho original amarrava contrato 1:1 a um projeto do "Monte sua
-- linha" (`projeto_id NOT NULL`). Pedido do usuário revisou isso: "o
-- contrato deve ficar linkado ao cadastro do CLIENTE, e pode ser feito
-- mais de um contrato" — e o vínculo com um projeto do Monte sua linha
-- vira OPCIONAL, decidido depois se quiser ("se desejar linkar ele com
-- o monte sua linha ter a opção depois"). Por isso:
--   - `cliente_id` NOT NULL (dono de verdade do contrato).
--   - `projeto_id` agora aceita NULL (contrato avulso) — quando
--     preenchido, os campos de condição comercial/Anexo I continuam
--     puxando automático do projeto na criação, mas o vínculo pode ser
--     adicionado/removido depois via `POST .../vincular-projeto`.
--   - Link do portal deixa de ser o do projeto (`terceirizacao_links_
--     portal`, que não existe pra contrato avulso) e ganha uma tabela
--     PRÓPRIA (`contrato_links_portal`), mesma receita de segurança da
--     Fase 136 (token de 256 bits, TTL, revogação, único ativo por
--     contrato) — assim TODO contrato pode ser assinado por link, tenha
--     ou não projeto vinculado.

CREATE TABLE contratos (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                  TEXT NOT NULL UNIQUE,  -- CT-2026-000001
    cliente_id              INTEGER NOT NULL REFERENCES clientes(id),
    -- Vínculo OPCIONAL com um projeto do Monte sua linha — de onde a
    -- criação puxa produtos/condição comercial automaticamente quando
    -- presente; pode ser definido na criação ou depois (nunca obrigatório).
    projeto_id              INTEGER REFERENCES terceirizacao_projetos(id),
    versao                  INTEGER NOT NULL DEFAULT 1,
    status                  TEXT NOT NULL DEFAULT 'rascunho'
                            CHECK (status IN ('rascunho', 'aguardando_assinatura', 'assinado', 'cancelado')),
    -- Corpo do contrato (as cláusulas) — pré-preenchido com o modelo
    -- padrão na criação, mas editável por contrato ("preciso se for
    -- necessário editar o contrato", pedido do usuário) sem afetar o
    -- modelo padrão nem contratos já criados.
    texto_clausulas         TEXT NOT NULL,
    -- Representante de quem assina pela CONTRATANTE (cliente) — pré-
    -- preenchido a partir de terceirizacao_briefings.assinante_* quando
    -- vinculado a um projeto, editável aqui.
    representante_nome      TEXT,
    representante_cpf       TEXT,
    -- Anexo I — Produtos e Condições Comerciais. "deixar que eu escolha
    -- ele se aparece ou não no contrato" (pedido do usuário): o anexo
    -- inteiro pode ser omitido, e mesmo aparecendo, cada item do
    -- projeto pode ser incluído ou não individualmente. Só faz sentido
    -- com um projeto vinculado (sem projeto, fica sempre vazio).
    incluir_anexo_produtos  INTEGER NOT NULL DEFAULT 1 CHECK (incluir_anexo_produtos IN (0, 1)),
    itens_anexo_json        TEXT,  -- JSON: lista de terceirizacao_projeto_itens.id incluídos no Anexo I
    condicao_pagamento_texto TEXT,
    prazo_producao_texto    TEXT,
    observacoes_gerais      TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER NOT NULL REFERENCES usuarios(id),
    atualizado_em           TEXT
);
CREATE INDEX idx_contratos_cliente ON contratos(cliente_id);
CREATE INDEX idx_contratos_projeto ON contratos(projeto_id);

-- Assinatura eletrônica — mesmo padrão de terceirizacao_versoes (Fase
-- 140): snapshot completo + PDF exato assinado + hash SHA-256, uma
-- linha por versão assinada, NUNCA sobrescrita.
CREATE TABLE contrato_versoes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contrato_id         INTEGER NOT NULL REFERENCES contratos(id),
    versao              INTEGER NOT NULL,
    snapshot_json        TEXT NOT NULL,
    hash_pdf_sha256      TEXT NOT NULL,
    pdf_dados            TEXT NOT NULL,
    pdf_tamanho          INTEGER NOT NULL,
    assinante_nome       TEXT NOT NULL,
    assinante_email      TEXT,
    assinante_cpf        TEXT NOT NULL,
    assinante_ip         TEXT,
    assinante_navegador  TEXT,
    assinado_em          TEXT NOT NULL,
    UNIQUE (contrato_id, versao)
);
CREATE INDEX idx_contrato_versoes_contrato ON contrato_versoes(contrato_id);

-- Link do portal — próprio de cada CONTRATO (não do projeto), mesma
-- receita de segurança de `terceirizacao_links_portal` (Fase 136):
-- token de ~256 bits, TTL, revogação, único link ativo por vez. Único
-- jeito de assinar um contrato sem login, tenha ou não projeto vinculado.
CREATE TABLE contrato_links_portal (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    contrato_id      INTEGER NOT NULL REFERENCES contratos(id),
    token            TEXT NOT NULL UNIQUE,
    criado_em        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por       INTEGER NOT NULL REFERENCES usuarios(id),
    expira_em        TEXT NOT NULL,
    revogado         INTEGER NOT NULL DEFAULT 0 CHECK (revogado IN (0,1)),
    ultimo_acesso_em TEXT,
    enviado_via_whatsapp INTEGER NOT NULL DEFAULT 0 CHECK (enviado_via_whatsapp IN (0,1))
);
CREATE INDEX idx_contrato_links_portal_contrato ON contrato_links_portal(contrato_id);
CREATE UNIQUE INDEX idx_contrato_links_portal_ativo_unico
    ON contrato_links_portal(contrato_id) WHERE revogado = 0;
