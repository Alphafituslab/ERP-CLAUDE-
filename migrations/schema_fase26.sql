-- Alphafitus OS — Fase 26 (Catálogos do Memorial Técnico ANVISA)
-- Aplicado DEPOIS de todas as fases anteriores, nunca remove nem altera
-- nada delas.
--
-- A Fase 24 (fundação do Memorial Técnico) deixou de propósito os 10
-- catálogos de apoio do sistema original (Metodologias, Nutrientes,
-- Legislações, Alegações, Tipos de Produto, Advertências, Armazenamento,
-- Modo de Uso, Justificativas, Referências) fora de escopo, citando-os
-- explicitamente como próximo passo — esta fase entrega esse próximo
-- passo. São cadastros simples que alimentam seletores usados ao
-- preencher um memorial (em vez de digitar "Vitamina C" ou uma alegação
-- inteira toda vez, cadastra-se uma vez aqui e escolhe-se de uma lista).
--
-- Os 10 catálogos moram numa única tabela (em vez de 10 tabelas quase
-- idênticas): `catalogo` diz qual dos 10 é, `dados` guarda em JSON os
-- campos específicos daquele catálogo (que variam: "Advertências" só tem
-- um texto, "Nutrientes" tem várias doses e unidades). `ordem` e `ativo`
-- ficam como colunas de verdade porque são comuns a todos os catálogos e
-- usados para ordenar a lista e permitir "desativar sem excluir" (o mesmo
-- padrão que o sistema original usa nesses catálogos, em vez de soft-
-- delete). Ver `app/routes/memorial_catalogos.py` para a validação de
-- quais campos cada catálogo aceita.

PRAGMA foreign_keys = ON;

CREATE TABLE memorial_catalogo_itens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    catalogo       TEXT NOT NULL CHECK (catalogo IN (
                       'metodologias', 'nutrientes', 'legislacoes', 'alegacoes',
                       'tipos_produto', 'advertencias', 'armazenamento', 'modo_uso',
                       'justificativas', 'referencias'
                   )),
    ordem          INTEGER NOT NULL DEFAULT 0,
    ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    dados          TEXT NOT NULL DEFAULT '{}',
    criado_por     INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    atualizado_por INTEGER REFERENCES usuarios(id),
    atualizado_em  TEXT
);

CREATE INDEX idx_memorial_catalogo_itens_catalogo ON memorial_catalogo_itens(catalogo, ordem, id);
