-- Fase 188 — pedido do usuário: cadastro de FUNCIONÁRIOS da empresa
-- (produção, laboratório, vendas etc.), separado do cadastro de USUÁRIOS
-- (login no sistema) — nem todo funcionário precisa de acesso ao ERP, e
-- quem tem os dois (função/cargo, telefone, endereço) pode ser a mesma
-- pessoa em ambos os cadastros, por isso `usuario_id` é OPCIONAL e só liga
-- as duas pontas quando fizer sentido. Salário é sensível de propósito:
-- fica numa permissão própria (`funcionarios.ver_salario`, ver seed.py),
-- separada de só ver/editar o cadastro do funcionário.
CREATE TABLE funcionarios (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    TEXT NOT NULL,
    setor                   TEXT,                    -- ex.: Produção, Laboratório, Vendas, Financeiro
    funcao                  TEXT,                    -- cargo, ex.: "Responsável Técnico", "Auxiliar de Produção"
    registro_profissional   TEXT,                    -- ex.: "CRF 18580", "CRQ 7698" — conselho de classe
    cpf                     TEXT,
    telefone                TEXT,
    -- Pedido do usuário: email SEMPRE obrigatório — é a chave usada pra
    -- casar este funcionário com uma conta do Whatts Inbox na hora de
    -- mandar login/senha nova pelo chat interno (ver nota em
    -- app/routes/funcionarios.py).
    email                   TEXT NOT NULL,
    endereco                TEXT,
    salario                 REAL CHECK (salario IS NULL OR salario >= 0),
    data_admissao           TEXT,                    -- data ISO (YYYY-MM-DD)
    usuario_id              INTEGER REFERENCES usuarios(id),
    status                  TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo','inativo')),
    observacoes             TEXT,
    criado_em               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    criado_por              INTEGER,
    atualizado_em           TEXT,
    atualizado_por          INTEGER
);
CREATE INDEX idx_funcionarios_usuario ON funcionarios(usuario_id);
CREATE INDEX idx_funcionarios_status ON funcionarios(status);
