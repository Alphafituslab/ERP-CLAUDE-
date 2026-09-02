-- Alphafitus OS — Fase 135 (Terceirização Premium, Fase B — documento +
-- aprovação interna multi-departamento)
--
-- Continuação da Fase 134 (fundação de dados). Esta fase adiciona a
-- aprovação interna (Comercial/P&D/Qualidade/Regulatório) antes do
-- projeto poder ir para assinatura (Fase D, futura) e a geração do
-- "Dossiê de Desenvolvimento de Produto" em PDF (sem tabela nova — o PDF
-- é gerado sob demanda a partir do que já existe).
--
-- Modelo escolhido: uma linha por departamento (não o modelo paralelo de
-- contagem do Memorial Técnico, que usa cargo em texto livre) — cada
-- departamento tem sua PRÓPRIA permissão de aprovar
-- (`terceirizacao.aprovar_<departamento>`), então uma pessoa de
-- Qualidade literalmente não consegue aprovar a linha do Comercial.
-- Mesmo raciocínio de "uma linha por decisão + status próprio" já usado
-- em `pedidos_compra_envios_pendentes` (Fase 61).

CREATE TABLE terceirizacao_aprovacoes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id        INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    departamento      TEXT NOT NULL CHECK (departamento IN ('comercial', 'pd', 'qualidade', 'regulatorio')),
    status            TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovado', 'reprovado')),
    decidido_por      INTEGER REFERENCES usuarios(id),
    decidido_em       TEXT,
    motivo_reprovacao TEXT,
    UNIQUE (projeto_id, departamento)
);
CREATE INDEX idx_terceirizacao_aprovacoes_projeto ON terceirizacao_aprovacoes(projeto_id);
