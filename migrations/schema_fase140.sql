-- Alphafitus OS — Fase 140 (Terceirização Premium / Fase D do plano):
-- assinatura eletrônica de verdade + congelamento de versão.
--
-- Diferente da confirmação LEVE da Fase 137 (nome+e-mail digitados, sem
-- hash, sem congelamento — captura só o "cliente disse que está tudo
-- ok" no MEIO do fluxo, antes da revisão/aprovação interna), esta é a
-- assinatura de verdade: acontece quando o projeto chega em
-- 'aguardando_assinatura' (todos os departamentos já aprovaram — ver
-- decidir_aprovacao em app/routes/terceirizacao.py), captura CPF além
-- de nome/e-mail, IP e navegador, e grava um SNAPSHOT completo e
-- IMUTÁVEL do projeto + o PDF exato que foi assinado + o hash SHA-256
-- desse PDF — nunca sobrescrito. Uma linha por versão assinada.
CREATE TABLE terceirizacao_versoes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id          INTEGER NOT NULL REFERENCES terceirizacao_projetos(id),
    versao              INTEGER NOT NULL,
    snapshot_json       TEXT NOT NULL,   -- estado completo do projeto (fórmula, embalagem, briefing, nutrição) no momento da assinatura
    hash_pdf_sha256     TEXT NOT NULL,
    pdf_dados           TEXT NOT NULL,   -- base64 do PDF exato que foi assinado — nunca regenerado depois
    pdf_tamanho         INTEGER NOT NULL,
    assinante_nome      TEXT NOT NULL,
    assinante_email     TEXT,
    assinante_cpf       TEXT NOT NULL,
    assinante_ip        TEXT,
    assinante_navegador TEXT,
    assinado_em         TEXT NOT NULL,
    UNIQUE (projeto_id, versao)
);
CREATE INDEX idx_terceirizacao_versoes_projeto ON terceirizacao_versoes(projeto_id);
