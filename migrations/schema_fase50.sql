-- Fase 50 — Apontamento de Perda/Refugo por ETAPA do Processo
--
-- Pendência documentada desde a Fase 9 (e reforçada na Fase 13): até aqui,
-- a perda/refugo de uma ordem de produção é um NÚMERO ÚNICO, agregado,
-- informado de uma vez só no momento da conclusão (POST
-- /producao/ordens/<id>/concluir) — o sistema não tinha como saber SE a
-- perda aconteceu na pesagem, na granulação, na compressão, no
-- encapsulamento ou na embalagem, por exemplo, só o total final. Isso
-- também limitava o custeio (Fase 13): o custo da perda é ratado
-- PROPORCIONALMENTE entre todos os insumos, porque não havia como saber em
-- qual ponto do processo ela ocorreu.
--
-- Esta fase adiciona o conceito de "etapa" (operação/passo do processo,
-- ex.: "Pesagem", "Granulação", "Compressão", "Encapsulamento",
-- "Embalagem") DENTRO de uma ordem de produção específica — não é um
-- roteiro de fabricação genérico cadastrado uma vez na fórmula (o sistema
-- não tem isso hoje, e cadastrar um roteiro por fórmula seria uma
-- modelagem bem maior); cada ordem cadastra as etapas que ela mesma vai
-- ter, na ordem em que o operador realmente as executa, e aponta a perda
-- (se houver) em cada uma separadamente.
--
-- Deliberadamente uma tabela NOVA, independente de `centros_trabalho`
-- (Fase 25): centro de trabalho é um RECURSO físico (linha/máquina/sala)
-- usado para AGENDAR quando/onde a ordem inteira roda
-- (`ordem_producao_agendamentos`, com UNIQUE por ordem — uma ordem só tem
-- UM agendamento por vez); "etapa do processo" é um conceito diferente,
-- ortogonal — várias etapas de uma mesma ordem, cada uma com sua própria
-- perda. Misturar os dois exigiria remover aquele UNIQUE (usado também
-- pelo custeio de mão de obra/overhead da Fase 30) só para forçar dois
-- conceitos diferentes numa tabela pensada para outra coisa.
--
-- `sequencia`: ordem em que a etapa acontece dentro do processo desta
-- ordem (1, 2, 3...) — UNIQUE junto com `ordem_producao_id`, então não dá
-- para cadastrar duas etapas com a mesma posição na mesma ordem.
--
-- `quantidade_perda`/`motivo_perda`: mesma regra de sempre (Fase 9) — >=0,
-- motivo obrigatório (validado na aplicação) quando a perda for > 0 — só
-- que agora POR ETAPA, apontada quando a etapa é concluída, não só uma
-- vez no fim de tudo.
--
-- `status`: uma etapa cadastrada nasce 'pendente' e só pode ser apontada
-- (perda + motivo) uma vez, virando 'concluida' — igual ao espírito de
-- "fato único e final apurado no momento" que já vale para a perda
-- agregada da ordem inteira. A ordem só pode ser concluída (rota já
-- existente desde a Fase 3) depois que TODAS as suas etapas, se houver
-- alguma cadastrada, estiverem 'concluida' — ver validação em
-- app/routes/producao.py.
--
-- Compatibilidade total com o que já existe: uma ordem SEM nenhuma etapa
-- cadastrada continua funcionando exatamente como antes (perda agregada
-- informada direto no /concluir, sem nenhuma mudança de comportamento) —
-- etapas são inteiramente OPCIONAIS, um recurso adicional para quem quiser
-- o detalhe mais fino, não uma obrigação nova para ordens que já existem
-- ou para quem não precisa desse nível de detalhe.
CREATE TABLE ordem_producao_etapas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem_producao_id   INTEGER NOT NULL REFERENCES ordens_producao(id),
    sequencia           INTEGER NOT NULL CHECK (sequencia > 0),
    nome                TEXT NOT NULL,
    quantidade_perda    REAL NOT NULL DEFAULT 0 CHECK (quantidade_perda >= 0),
    motivo_perda        TEXT,
    status              TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'concluida')),
    concluido_em        TEXT,
    concluido_por       INTEGER REFERENCES usuarios(id),
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por          INTEGER REFERENCES usuarios(id),
    UNIQUE (ordem_producao_id, sequencia)
);
