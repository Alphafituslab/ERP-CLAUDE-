-- Alphafitus OS — Fase 146 (Terceirização Premium): múltiplos itens por
-- projeto, cada um com fórmula + embalagem (pote/tampa/cápsula) +
-- quantidade PRÓPRIOS.
--
-- Pedido do usuário (2026-09-03): um cliente pode fechar, no MESMO
-- projeto/contrato, mais de um produto (ex.: Colágeno num pote e
-- Creatina em outro tipo de embalagem) — decisão confirmada com o
-- usuário: cada item tem embalagem própria, não uma embalagem única
-- pro projeto inteiro.
--
-- As colunas antigas em terceirizacao_projetos (item_id, pote_id,
-- tampa_id, capsula_id, quantidade_por_pote, unidade_quantidade,
-- mockup_3d_imagem) NÃO são removidas nem tocadas — ficam paradas,
-- não usadas mais pelo código novo. Projetos que já existiam são
-- migrados automaticamente pra um primeiro item nesta tabela nova, sem
-- perder nenhum dado.
CREATE TABLE terceirizacao_projeto_itens (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id          INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    item_id             INTEGER REFERENCES itens(id),
    pote_id             INTEGER REFERENCES terceirizacao_potes(id),
    tampa_id            INTEGER REFERENCES terceirizacao_tampas(id),
    capsula_id          INTEGER REFERENCES terceirizacao_capsulas(id),
    quantidade_por_pote INTEGER,
    unidade_quantidade  TEXT CHECK (unidade_quantidade IN ('capsulas', 'gramas')),
    ordem               INTEGER NOT NULL DEFAULT 0,
    mockup_3d_imagem    TEXT,   -- captura 3D PRÓPRIA deste item (Fase 144, agora por item)
    solicitacao_alteracao_formula TEXT,
    criado_em           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_terceirizacao_projeto_itens_projeto ON terceirizacao_projeto_itens(projeto_id);

-- Migra projetos existentes: cada um vira o primeiro item da lista nova,
-- preservando fórmula/embalagem/quantidade/mockup que já tinham.
INSERT INTO terceirizacao_projeto_itens
    (projeto_id, item_id, pote_id, tampa_id, capsula_id, quantidade_por_pote,
     unidade_quantidade, ordem, mockup_3d_imagem, solicitacao_alteracao_formula, criado_em)
SELECT id, item_id, pote_id, tampa_id, capsula_id, quantidade_por_pote,
       unidade_quantidade, 0, mockup_3d_imagem, solicitacao_alteracao_formula, criado_em
FROM terceirizacao_projetos
WHERE item_id IS NOT NULL;
