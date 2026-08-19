-- Alphafitus OS — Fase 32 (Limiar de Divergência de Contagem Configurável
-- pela Tela)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas. Mesmas notas de portabilidade para PostgreSQL das fases
-- anteriores se aplicam aqui.
--
-- A Fase 21 entregou a segunda aprovação para divergência GRANDE (acima
-- de 20% do saldo que o sistema tinha no início da contagem) numa
-- contagem de inventário — mas o valor "20%" ficava fixo no código
-- (`LIMIAR_PERCENTUAL_DIVERGENCIA_GRANDE` em `app/routes/estoque.py`),
-- exigindo alterar e reimplantar o backend pra mudar. Esta fase move
-- esse valor para o banco, editável por uma tela de configuração —
-- assim quem administra o sistema (não necessariamente quem programa)
-- pode ajustar essa régua conforme a política de controle interno da
-- empresa evolui.
--
-- Linha única por design (`id INTEGER PRIMARY KEY CHECK (id = 1)`),
-- mesmo raciocínio de "não é um cadastro com várias linhas, é UMA
-- configuração do sistema inteiro" — mais simples que uma tabela
-- genérica chave/valor para esse caso único, e mais fácil de dar
-- CHECK de faixa válida (0 a 100) diretamente na coluna.
--
-- Valor guardado em PERCENTUAL (0 a 100, ex.: 20 = 20%), não em fração
-- (0 a 1) — mais natural pra tela de configuração e pra API; o código
-- que compara contra a divergência calculada (`diferenca/saldo_inicio`,
-- que É uma fração 0-1) converte na hora da comparação.

PRAGMA foreign_keys = ON;

CREATE TABLE configuracoes_estoque (
    id                                     INTEGER PRIMARY KEY CHECK (id = 1),
    limiar_percentual_divergencia_grande   REAL NOT NULL DEFAULT 20.0
        CHECK (limiar_percentual_divergencia_grande > 0 AND limiar_percentual_divergencia_grande <= 100),
    atualizado_em                          TEXT,
    atualizado_por                         INTEGER REFERENCES usuarios(id)
);

-- Semeia a linha única já com o mesmo valor (20%) que era fixo no código
-- desde a Fase 21 — comportamento de quem já tem o sistema rodando não
-- muda com esta fase, só passa a ser editável.
INSERT INTO configuracoes_estoque (id, limiar_percentual_divergencia_grande) VALUES (1, 20.0);
