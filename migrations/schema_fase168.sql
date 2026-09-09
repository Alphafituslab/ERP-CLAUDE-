-- Fase 168 — Correções de auditoria de segurança (parte 2)
--
-- Achado médio da Fase 167 ainda não corrigido: /auth/login só bloqueia por
-- CONTA individual (tentativas_login_falhas/bloqueado_ate em `usuarios`) —
-- testar 1 senha comum contra muitos e-mails diferentes (password spraying)
-- nunca aciona nenhum bloqueio, porque cada conta só vê 1 tentativa falha.
-- Esta tabela rastreia tentativas por IP, independente de qual conta foi
-- tentada — mesma ideia de janela+bloqueio já usada em `usuarios`, só que
-- chaveada por IP em vez de usuario_id (ver app/routes/auth.py).
CREATE TABLE tentativas_login_ip (
    ip              TEXT PRIMARY KEY,
    tentativas      INTEGER NOT NULL DEFAULT 0,
    janela_inicio   TEXT NOT NULL,
    bloqueado_ate   TEXT
);
