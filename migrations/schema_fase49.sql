-- ============================================================
-- FASE 49 — Memorial Técnico ANVISA: Administração — Configurações
-- ============================================================
-- Último pedaço da seção "Administração" replicada dentro do Memorial
-- Técnico (depois de Usuários Online — Fase 44, Snapshots & Restauração
-- — Fase 46, Backups do Sistema — Fase 47, e Gerenciar Usuários — Fase
-- 48). No sistema original, o item de menu "Configurações" dentro dessa
-- Administração era efetivamente um bug — apontava para a tela de
-- Metodologias por engano — então não existe uma especificação real para
-- copiar. Em vez de inventar telas sem lastro, esta fase segue o mesmo
-- caminho já usado nas Fases 32/33/34/35/36 (pegar uma regra hoje
-- CODIFICADA/fixa no Python, específica do módulo, e virar uma
-- "configuração em linha única" editável pela tela): as duas únicas
-- regras fixas hoje existentes DENTRO do módulo Memorial Técnico (não do
-- resto do sistema) são:
--
--   1. `numero_assinaturas_aprovacao` — hoje o literal `2` repetido em 3
--      lugares de `app/routes/memorial.py` (_memorial_com_assinaturas,
--      _tentar_auto_aprovar, dashboard): quantas assinaturas um memorial
--      em status "Concluído" precisa acumular para ser promovido
--      automaticamente a "Aprovado". Valor padrão 2 preserva o
--      comportamento de sempre.
--
--   2. `tamanho_maximo_anexo_mb` — hoje a constante `MAX_ANEXO_BYTES =
--      40 * 1024 * 1024` em `app/routes/memorial_anexos.py`: tamanho
--      máximo de um único anexo de arquivo (laudo, especificação,
--      rótulo). Valor padrão 40 preserva o comportamento de sempre.
--
-- Mesmo padrão de sempre: `id INTEGER PRIMARY KEY CHECK (id = 1)` (uma
-- única linha, sem tabela de histórico — a trilha de auditoria já
-- registra cada alteração via `audit.registrar`), `atualizado_em`/
-- `atualizado_por` para saber quem mudou e quando, e o INSERT inicial já
-- semeado com os valores que eram o comportamento fixo ANTERIOR a esta
-- fase — nenhum memorial ou anexo existente muda de comportamento só por
-- esta migration rodar.
CREATE TABLE configuracoes_memorial (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    numero_assinaturas_aprovacao INTEGER NOT NULL DEFAULT 2 CHECK (numero_assinaturas_aprovacao > 0),
    tamanho_maximo_anexo_mb      INTEGER NOT NULL DEFAULT 40 CHECK (tamanho_maximo_anexo_mb > 0),
    atualizado_em                TEXT,
    atualizado_por               INTEGER REFERENCES usuarios(id)
);
INSERT INTO configuracoes_memorial (id, numero_assinaturas_aprovacao, tamanho_maximo_anexo_mb)
VALUES (1, 2, 40);
