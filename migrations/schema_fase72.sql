-- Alphafitus OS — Fase 72 (Auditoria de Segurança — Reforço de Integridade
-- em Nível de Banco contra Condições de Corrida)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera
-- nada já existente.
--
-- CONTEXTO: uma auditoria de segurança encomendada pelo cliente encontrou
-- duas condições de corrida reais (não teóricas) em fluxos que fazem uma
-- checagem em Python ("já existe algo ativo?") e só DEPOIS gravam a linha
-- nova — sem nada no banco impedindo que duas requisições simultâneas
-- passem ambas pela mesma checagem antes de qualquer uma delas gravar
-- (nem SQLite nem a arquitetura de uma conexão por requisição deste
-- sistema — ver app/context.py — serializam LEITURAS entre requisições
-- concorrentes, só as ESCRITAS). Em vez de reescrever a arquitetura de
-- conexão do zero (mudança grande e arriscada para dois casos pontuais),
-- esta fase fecha os dois casos encontrados com a ferramenta certa para
-- isso: um índice UNIQUE, que o próprio SQLite garante mesmo sob
-- concorrência (a segunda escrita simplesmente falha com
-- IntegrityError, tratada no código como um 409 comum). Ver
-- app/nfe_service.py e app/boleto_service.py para a checagem em Python
-- que já existia e continua existindo — o índice aqui é uma segunda
-- camada de proteção, não uma substituição da validação com mensagem
-- amigável.
--
-- 1. NF-e (Fase 70): o `numero` de uma nota fiscal é calculado como
--    MAX(numero)+1 por (empresa_id, serie) na hora da emissão, sem nunca
--    reaproveitar um número mesmo de uma tentativa rejeitada/cancelada
--    (ver o comentário original em schema_fase70.sql) — mas nada
--    impedia, até aqui, que duas emissões concorrentes para a mesma
--    empresa+série calculassem o MESMO próximo número e as duas
--    inserissem, gerando dois documentos fiscais com o mesmo número
--    enviados à SEFAZ (via Focus NFe). Este índice único torna essa
--    dupla inserção fisicamente impossível no banco.
CREATE UNIQUE INDEX idx_notas_fiscais_numero_unico_por_empresa_serie
    ON notas_fiscais(empresa_id, serie, numero);

--    Um pedido de venda também não deveria nunca ter duas notas fiscais
--    ATIVAS ao mesmo tempo (`processando_autorizacao` ou `autorizada` —
--    ver STATUS_ATIVOS_NOTA em app/nfe_service.py); a checagem em Python
--    (`existe_nota_ativa_para_pedido`) tinha a mesma janela de corrida
--    entre duas emissões simultâneas para o mesmo pedido. Índice parcial
--    (só cobre as duas linhas de status "ativo") — SQLite suporta
--    WHERE em CREATE UNIQUE INDEX desde a versão 3.8.0.
CREATE UNIQUE INDEX idx_notas_fiscais_pedido_ativa_unica
    ON notas_fiscais(pedido_id)
    WHERE status IN ('processando_autorizacao', 'autorizada');

-- 2. Boleto Bancário (Fase 71): mesma classe de problema —
--    `existe_boleto_ativo_para_conta` (app/boleto_service.py) checa em
--    Python se já existe um boleto "pendente" para a conta a receber
--    antes de gerar um novo, com uma chamada de rede ao Asaas no meio do
--    caminho (ainda mais tempo de janela para a corrida acontecer). O
--    próprio comentário original em schema_fase71.sql já reconhecia que
--    essa invariante era "verificada em código, não em CHECK — SQLite
--    não suporta CHECK que consulte outras linhas" — o que é verdade
--    para CHECK, mas não para um índice único PARCIAL, que consegue
--    expressar exatamente "no máximo um boleto com status='pendente' por
--    conta_receber_id".
CREATE UNIQUE INDEX idx_boletos_conta_receber_pendente_unico
    ON boletos(conta_receber_id)
    WHERE status = 'pendente';
