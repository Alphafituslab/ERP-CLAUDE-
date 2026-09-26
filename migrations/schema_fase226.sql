-- Alphafitus OS — Fase 226 (Notificações: contador de repetição, nunca duplicar linha)
--
-- Pedido do usuário: ao reenviar uma solicitação (ex.: "revisar orçamento")
-- repetidas vezes, a tela de Notificações nunca deve ganhar uma linha nova
-- por reenvio — sempre a MESMA linha, com um número mostrando quantas
-- vezes foi reenviada (1ª, 2ª, 3ª...) — a base pro fluxo de escalonamento
-- que ele descreveu (1, depois 2, depois 3, e a partir daí aciona outra
-- coisa). Genérico (não só pra orçamento) — qualquer notificação futura
-- que reaproveite o mesmo "atualiza em vez de duplicar" ganha o contador
-- de graça.
PRAGMA foreign_keys = ON;

ALTER TABLE notificacoes ADD COLUMN contagem INTEGER NOT NULL DEFAULT 1;
