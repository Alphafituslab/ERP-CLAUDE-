-- Fase 69 — Painel Gerencial: Série Histórica / Tendência.
--
-- Contexto (ver README.md, "O que ainda falta"): o Painel Gerencial (Fase
-- 7 em diante) sempre foi 100% "foto de agora" — todo número é
-- recalculado a cada chamada a partir das tabelas operacionais, nunca um
-- valor guardado à parte (ver a nota de design no topo de
-- app/routes/relatorios.py: "este módulo NÃO CRIA nenhum dado novo").
-- Isso é correto e deliberado para a "situação atual", mas significa que
-- não existe nenhum jeito de responder "como esse número estava há 30
-- dias?" — cada consulta só enxerga o presente, mesmo com o filtro de
-- período da Fase 42 (que olha o que ACONTECEU numa janela, não como os
-- números foram MUDANDO ao longo do tempo).
--
-- Esta fase adiciona, pela primeira vez no Painel Gerencial, uma tabela
-- que GUARDA um valor histórico em vez de recalculá-lo — uma exceção
-- deliberada e documentada à regra acima, no mesmo espírito de
-- `auditoria`/`historico_*`, que já são "fotos" acumuladas de eventos
-- passados, não estado atual recalculável.
--
-- Decisão de escopo — como a captura acontece: em vez de um agendador em
-- segundo plano (que exigiria o servidor ficar ligado 24 horas por dia
-- para não perder nenhum dia — ver a ressalva completa em
-- app/painel_snapshot_service.py), a captura acontece como efeito
-- colateral de ALGUÉM VISUALIZAR o Painel Gerencial: no máximo uma
-- gravação por dia por combinação empresa/"grupo todo" (sempre
-- sobrescrevendo o snapshot do próprio dia atual até a virada da data,
-- quando um novo dia — e uma nova linha — começa). É o mesmo espírito
-- "melhor esforço, sem infraestrutura nova" já usado em
-- `usuarios.ultimo_acesso_em` (Fase 44, "Usuários Online"). Limitação
-- documentada: um dia em que ninguém abrir o Painel Gerencial (com aquele
-- filtro de empresa específico) fica sem snapshot — a tendência mostra um
-- intervalo em branco naquele dia, nunca um valor inventado.
CREATE TABLE painel_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_referencia TEXT NOT NULL,               -- "AAAA-MM-DD" (UTC) do snapshot
    empresa_id INTEGER REFERENCES empresas(id),  -- NULL = grupo todo (mesmo padrão da Fase 52)
    capturado_em TEXT NOT NULL,                  -- datetime da última gravação/atualização desta linha
    -- Os cinco blocos de "situação atual" do dashboard (producao,
    -- qualidade, estoque, comercial, financeiro — exatamente o mesmo
    -- formato que _montar_dashboard já produz), serializados como JSON.
    -- NUNCA o bloco "periodo" (Fase 42), que já é, ele mesmo, uma janela
    -- de tempo — não faz sentido "congelar" um agregado de período dentro
    -- de outro agregado de período.
    dados_json TEXT NOT NULL
);
CREATE INDEX idx_painel_snapshots_data ON painel_snapshots(data_referencia);
CREATE INDEX idx_painel_snapshots_empresa ON painel_snapshots(empresa_id);
