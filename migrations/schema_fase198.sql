-- Alphafitus OS — Fase 198 (Agenda: visibilidade de detalhe por usuário)
--
-- Pedido do usuário (2026-09-25): hoje a Agenda de Compromissos (Fase 193) é
-- 100% compartilhada — qualquer usuário logado vê o motivo/local/descrição
-- de QUALQUER compromisso de QUALQUER dono. Isso vai mudar pra um modelo de
-- permissão explícita por PAR de usuário: ao configurar um usuário, dá pra
-- marcar de quem mais (Clayton/Carol/Daiana etc.) ele pode ver o compromisso
-- em detalhe. Sem essa marcação, o compromisso do outro continua aparecendo
-- na grade (pra não esconder que a pessoa está ocupada naquele horário), só
-- que com um rótulo genérico ("Agenda de <nome>") no lugar do
-- título/descrição/local reais — nunca 100% escondido, só sem detalhe.
--
-- Um Administrador (permissão "agenda.editar_todos", que o perfil
-- Administrador já tem de graça via "TODAS") sempre vê tudo em detalhe,
-- independente desta tabela — mesmo raciocínio de "editar_todos"/
-- "excluir_todos" já usados na Fase 193. Ver própria agenda também nunca
-- passa por aqui (óbvio, não precisa de linha nesta tabela).
PRAGMA foreign_keys = ON;

CREATE TABLE agenda_permissoes_visualizacao (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_visualizador_id     INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    usuario_dono_id             INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por                  INTEGER NOT NULL REFERENCES usuarios(id),
    UNIQUE(usuario_visualizador_id, usuario_dono_id)
);
