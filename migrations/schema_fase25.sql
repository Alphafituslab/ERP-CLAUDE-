-- Alphafitus OS — Fase 25 (APS — Sequenciamento e Capacidade Finita, Fundação)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas.
--
-- Até aqui a Fase 3 entregou o PCP básico (planejar → liberar → apontar
-- consumo → concluir uma ordem de produção), mas nenhuma parte do sistema
-- sabia QUANDO, fisicamente, cada ordem ia rodar, nem em qual recurso
-- produtivo (linha, máquina, sala) — o pedido original do cliente foi
-- "continuar criando o ERP e o APS", e um APS (Advanced Planning and
-- Scheduling) de verdade é justamente essa camada de sequenciamento com
-- CAPACIDADE FINITA: não deixar agendar mais ordens num centro de
-- trabalho, ao mesmo tempo, do que ele fisicamente aguenta.
--
-- Duas tabelas novas:
--
-- `centros_trabalho`: os recursos produtivos em si (uma linha de
-- envase, uma máquina de blister, uma sala de pesagem etc.), com uma
-- capacidade_paralela — quantas ordens esse centro consegue processar
-- AO MESMO TEMPO sem violar a capacidade real (a maioria vai ter 1: só
-- uma ordem por vez; uma sala grande com várias bancadas poderia ter
-- mais).
--
-- `ordem_producao_agendamentos`: a agenda em si — um registro por ordem
-- (por isso `ordem_producao_id` é UNIQUE: uma ordem só tem UMA janela
-- planejada de cada vez; reagendar atualiza o mesmo registro, não
-- acumula histórico). Deliberadamente MUTÁVEL, sem gatilho de
-- append-only: isto é uma decisão de planejamento operacional, que muda
-- o tempo todo conforme a fábrica reorganiza a agenda — não é um evento
-- de conformidade que precise ficar registrado para sempre (diferente da
-- trilha de auditoria em `auditoria`, que já registra cada agendamento e
-- reagendamento via audit.registrar, para quem quiser consultar o
-- histórico de mudanças por outro caminho). Mesmo padrão de tabela
-- "estado atual mutável" já usado por `contagens_inventario`/
-- `contagens_inventario_itens` (Fase 17).
--
-- A checagem de capacidade finita (não deixar duas ordens sobrepostas
-- num centro além do que `capacidade_paralela` permite) é feita em
-- código (app/routes/aps.py), não em constraint de banco — SQLite não
-- tem um jeito nativo de expressar "no máximo N linhas cujo intervalo de
-- tempo se sobrepõe" como CHECK constraint.

PRAGMA foreign_keys = ON;

CREATE TABLE centros_trabalho (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL,
    descricao               TEXT,
    capacidade_paralela     INTEGER NOT NULL DEFAULT 1 CHECK (capacidade_paralela >= 1),
    status                  TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    atualizado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por          INTEGER REFERENCES usuarios(id)
);

CREATE INDEX idx_centros_trabalho_status ON centros_trabalho(status);

CREATE TABLE ordem_producao_agendamentos (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem_producao_id       INTEGER NOT NULL UNIQUE REFERENCES ordens_producao(id),
    centro_trabalho_id      INTEGER NOT NULL REFERENCES centros_trabalho(id),
    inicio_planejado        TEXT NOT NULL,
    fim_planejado           TEXT NOT NULL,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER REFERENCES usuarios(id),
    atualizado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por          INTEGER REFERENCES usuarios(id),
    CHECK (fim_planejado > inicio_planejado)
);

CREATE INDEX idx_agendamentos_centro ON ordem_producao_agendamentos(centro_trabalho_id);
CREATE INDEX idx_agendamentos_periodo ON ordem_producao_agendamentos(inicio_planejado, fim_planejado);
