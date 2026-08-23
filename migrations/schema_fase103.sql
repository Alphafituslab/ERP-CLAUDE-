-- Alphafitus OS — Fase 103 (Documentos do Cliente — obrigatório ao cadastrar pelo App de Vendas)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário: quando um representante/vendedor visita um cliente e cadastra ele pelo
-- App de Vendas, é OBRIGATÓRIO anexar documentos do cliente — inclusive bater foto direto pelo
-- próprio app (possível: `<input type="file" accept="image/*" capture="environment">` abre a
-- câmera em qualquer navegador de celular moderno, sem precisar de app nativo).
--
-- Mesmo padrão de armazenamento de `memorial_anexos` (Fase 27) — base64 dentro do banco, não em
-- disco/S3 — pelo mesmo motivo: simplicidade de backup (um único arquivo .db contém tudo) e o
-- volume esperado (fotos de documento de poucos clientes novos por dia) não justifica a
-- complexidade de um object storage à parte.
--
-- A obrigatoriedade em si NÃO é imposta por uma constraint de banco (não daria pra garantir "ao
-- menos 1 documento" só com SQL) — é imposta em `POST /vendas-app/clientes`
-- (app/routes/vendas_app.py), que cria cliente + documento(s) numa única chamada atômica e
-- recusa (400) se a lista de documentos vier vazia. O cadastro de cliente pela tela DESKTOP
-- (`POST /comercial/clientes`) continua sem exigir documento nenhum — só o fluxo do vendedor em
-- campo tem essa exigência, por pedido explícito do usuário.

PRAGMA foreign_keys = ON;

CREATE TABLE clientes_documentos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id    INTEGER NOT NULL REFERENCES clientes(id),
    nome          TEXT NOT NULL,
    nome_arquivo  TEXT NOT NULL,
    tipo_mime     TEXT NOT NULL,
    dados         TEXT NOT NULL,
    tamanho       INTEGER NOT NULL,
    criado_por    INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_clientes_documentos_cliente ON clientes_documentos(cliente_id);
