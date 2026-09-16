-- Alphafitus OS — Fase 184 (exceções de permissão por usuário)
--
-- Pedido do usuário (2026-09-16): hoje o acesso vem só dos PERFIS
-- atribuídos a cada pessoa (ex.: perfil "Qualidade" já embute um conjunto
-- fixo de permissões) — dois usuários com o mesmo perfil têm exatamente o
-- mesmo acesso. O pedido foi: "dentro de um único, como exemplo Qualidade,
-- tem vários abas dentro que gostaria que usuários possam ou não acessar...
-- uns teriam mais acesso às páginas que contemplam o financeiro e assim
-- segue para todos os outros" — ou seja, precisa dar ou tirar uma permissão
-- específica de UMA pessoa, sem mexer no perfil (que afeta todo mundo que o
-- tem) e sem precisar criar um perfil novo pra cada combinação possível.
--
-- usuario_permissao_excecao guarda só o DESVIO em relação ao que os perfis
-- da pessoa já dariam — não duplica a lista inteira de permissões dela.
-- 'conceder' dá uma permissão que nenhum perfil da pessoa dá; 'negar' tira
-- uma permissão que algum perfil dela dá (negar sempre vence — ver
-- `usuario_tem_permissao` em app/permissions.py). Índice único em
-- (usuario_id, permissao_id): uma pessoa não pode ter as duas exceções ao
-- mesmo tempo para a mesma permissão (não faz sentido conceder e negar a
-- mesma coisa) — trocar o tipo é um UPDATE, não um INSERT novo.

PRAGMA foreign_keys = ON;

CREATE TABLE usuario_permissao_excecao (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id   INTEGER NOT NULL REFERENCES usuarios(id),
    permissao_id INTEGER NOT NULL REFERENCES permissoes(id),
    tipo         TEXT NOT NULL CHECK (tipo IN ('conceder', 'negar')),
    criado_em    TEXT NOT NULL,
    criado_por   INTEGER REFERENCES usuarios(id),
    UNIQUE (usuario_id, permissao_id)
);
CREATE INDEX idx_usuario_permissao_excecao_usuario ON usuario_permissao_excecao(usuario_id);
