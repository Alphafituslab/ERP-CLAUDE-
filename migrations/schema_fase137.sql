-- Alphafitus OS — Fase 137 (Terceirização Premium — ajustes pedidos pelo
-- usuário em 2026-09-02: nome do Memorial na fórmula, reordenação da
-- tela, prévia do documento pro cliente antes de enviar, e uma
-- confirmação/assinatura LEVE do cliente ao concluir)
--
-- IMPORTANTE — isso NÃO é a Fase D (assinatura eletrônica de verdade,
-- ainda pendente no plano: hash SHA-256 do PDF final + congelamento de
-- versão). É uma confirmação leve — nome + e-mail digitados pelo
-- cliente + IP + data/hora — capturada no momento em que ele diz "está
-- tudo certo, pode enviar". Documentado assim de propósito pra nunca
-- ser confundido com uma assinatura juridicamente vinculante.

ALTER TABLE terceirizacao_projetos ADD COLUMN assinatura_cliente_nome TEXT;
ALTER TABLE terceirizacao_projetos ADD COLUMN assinatura_cliente_email TEXT;
ALTER TABLE terceirizacao_projetos ADD COLUMN assinatura_cliente_em TEXT;
ALTER TABLE terceirizacao_projetos ADD COLUMN assinatura_cliente_ip TEXT;
