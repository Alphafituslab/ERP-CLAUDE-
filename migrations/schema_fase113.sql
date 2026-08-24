-- Alphafitus OS — Fase 113 (Foto de perfil do operador)
--
-- Pedido do usuário: "ter a opção de colocar a foto de cada operador
-- logado no sistema, assim cada um tem seu rosto ao logar". Guardada como
-- base64 (data URI completo, pronto pra usar direto num <img src>) na
-- própria linha de `usuarios` — mesmo padrão de `memorial_anexos`/
-- `clientes_documentos` (Fase 27/103), só que sem tabela própria: é UMA
-- foto por usuário, não uma lista de anexos, então uma coluna a mais em
-- `usuarios` já resolve sem duplicar estrutura.
ALTER TABLE usuarios ADD COLUMN foto_perfil TEXT;
