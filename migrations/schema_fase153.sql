-- Fase 153 — Galeria de mídia dos itens (múltiplas fotos + vídeo).
--
-- Pedido do usuário (2026-09-04), depois de ver o Portfólio do App de
-- Vendas em mobile: "em cada um tem que aparecer a foto do item junto" e,
-- na sequência, "deixar que tenha mais de uma foto por produto se for
-- necessário, até um pequeno vídeo poder incluir se for necessário".
--
-- `itens.imagem` (Fase 114) continua existindo e sendo o FALLBACK/capa
-- para um item que ainda não tem nenhuma linha aqui — nenhuma migração de
-- dado é necessária: quem lê primeiro tenta `itens_midias` (a primeira
-- FOTO, por `ordem`), só cai pra `itens.imagem` se a lista vier vazia.
-- Um vídeo nunca vira capa sozinho (precisa dar play, não faz sentido
-- como thumbnail) — a capa é sempre uma foto.
CREATE TABLE itens_midias (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER NOT NULL REFERENCES itens(id),
    tipo          TEXT NOT NULL CHECK (tipo IN ('foto', 'video')),
    mime_tipo     TEXT NOT NULL,
    -- Data URI completo ("data:<mime>;base64,..."), mesmo padrão de
    -- `itens.imagem`/`usuarios.foto_perfil` (ver app/imagens.py) — quem lê
    -- joga direto num <img>/<video src="...">, sem reconstruir prefixo.
    conteudo      TEXT NOT NULL,
    tamanho_bytes INTEGER NOT NULL,
    ordem         INTEGER NOT NULL DEFAULT 0,
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por    INTEGER REFERENCES usuarios(id)
);
CREATE INDEX idx_itens_midias_item ON itens_midias(item_id, ordem);
