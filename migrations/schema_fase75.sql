-- Fase 75 — Etapas de Processo Configuráveis (Pesagem, Tempo de Mistura) +
-- Painel de Chão de Fábrica em Tempo Real
--
-- Pedido do cliente: acompanhar, DENTRO de cada Ordem de Produção, em que
-- pé está cada etapa do processo (a Fase 50 já criou o conceito de "etapa"
-- dentro de uma ordem, mas só para apontar PERDA — cada etapa era só um
-- nome livre digitado na hora, sem catálogo reaproveitável, sem hora de
-- início e sem nenhum valor numérico próprio, ex.: quanto pesou na
-- Pesagem) e um painel que atualiza sozinho, em tempo real, mostrando o
-- que está acontecendo agora em cada setor — pensando já numa "empresa
-- 4.0", com tablets no chão de fábrica apontando o início/fim de cada
-- etapa ao vivo.
--
-- Duas mudanças, as duas 100% compatíveis com o que já existe:
--
-- 1) `tipos_etapa_producao`: catálogo de tipos de etapa reaproveitável
-- (Pesagem, Mistura, Granulação, Compressão, Encapsulamento, Envase,
-- Rotulagem, Embalagem — os mesmos nomes já citados no comentário da
-- Fase 50, mais os que o cliente pediu agora), com uma `unidade_valor`
-- opcional (ex.: "kg" para Pesagem) que dá contexto ao campo genérico
-- `valor_registrado` adicionado na tabela de etapas abaixo. Nasce com
-- alguns tipos padrão já cadastrados (INSERT direto nesta migration, não
-- em seed.py — seed.py só roda a fundação de permissões/perfis/admin;
-- isto aqui é dado de configuração operacional, e uma instalação já
-- existente também deve ganhar esses tipos padrão ao atualizar, sem
-- precisar de nenhum cadastro manual no primeiro uso). Continua 100%
-- editável/expansível pela tela (cadastrar novos tipos, inativar os que
-- não fizerem sentido para esta fábrica).
--
-- 2) Quatro colunas NOVAS em `ordem_producao_etapas` (Fase 50), todas
-- opcionais (`ALTER TABLE ... ADD COLUMN`, sem CHECK novo — SQLite não
-- permite alterar um CHECK existente sem recriar a tabela inteira, mesma
-- limitação técnica já documentada no comentário da Fase 61; por isso o
-- estado "em andamento" de uma etapa NÃO é um novo valor no CHECK de
-- `status` — continua só 'pendente'/'concluida' como sempre — e sim
-- DERIVADO na aplicação a partir de `iniciado_em` estar preenchido ou não
-- enquanto `status` ainda é 'pendente'):
--   `tipo_etapa_id`     — de qual tipo do catálogo acima esta etapa é
--                         (opcional: uma etapa cadastrada só com `nome`
--                         livre, do jeito que a Fase 50 sempre permitiu,
--                         continua funcionando exatamente igual);
--   `iniciado_em`       — quando o operador apertou "Iniciar" nesta etapa
--                         (novo botão, ao lado do "Concluir" que já
--                         existia) — é a partir daqui que "tempo de
--                         mistura", por exemplo, passa a ser calculável
--                         (`concluido_em` menos `iniciado_em`), sem
--                         precisar guardar a duração como um número à
--                         parte que poderia dessincronizar;
--   `iniciado_por`      — quem apertou "Iniciar" (nem sempre é a mesma
--                         pessoa que depois aperta "Concluir", numa troca
--                         de turno, por exemplo);
--   `valor_registrado`  — o valor específico daquela etapa, registrado no
--                         momento de concluir (ex.: quantos kg pesou de
--                         verdade na Pesagem) — só faz sentido para tipos
--                         de etapa que têm `unidade_valor` preenchida;
--                         para as demais (ex.: Mistura, onde o que
--                         importa é só o TEMPO, já calculado sozinho a
--                         partir de início/fim) fica NULL sem problema
--                         nenhum.
--
-- O painel de chão de fábrica em tempo real (Fase 75 também) não precisou
-- de nenhuma tabela nova: ele só lê, ao vivo, as ordens de produção e
-- suas etapas (esta fase), mais pedidos de venda e pedidos de compra que
-- já existem desde as Fases 5 e 58 — ver app/routes/painel_tempo_real.py.

CREATE TABLE tipos_etapa_producao (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                TEXT NOT NULL UNIQUE,
    unidade_valor       TEXT,
    ordem_padrao        INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER REFERENCES usuarios(id)
);

INSERT INTO tipos_etapa_producao (nome, unidade_valor, ordem_padrao) VALUES
    ('Pesagem', 'kg', 1),
    ('Mistura', NULL, 2),
    ('Granulação', NULL, 3),
    ('Compressão', NULL, 4),
    ('Encapsulamento', NULL, 5),
    ('Envase', NULL, 6),
    ('Rotulagem', NULL, 7),
    ('Embalagem', NULL, 8);

ALTER TABLE ordem_producao_etapas ADD COLUMN tipo_etapa_id INTEGER REFERENCES tipos_etapa_producao(id);
ALTER TABLE ordem_producao_etapas ADD COLUMN iniciado_em TEXT;
ALTER TABLE ordem_producao_etapas ADD COLUMN iniciado_por INTEGER REFERENCES usuarios(id);
ALTER TABLE ordem_producao_etapas ADD COLUMN valor_registrado REAL;

CREATE INDEX idx_tipos_etapa_producao_status ON tipos_etapa_producao(status);
