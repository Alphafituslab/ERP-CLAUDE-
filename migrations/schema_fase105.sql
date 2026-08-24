-- Alphafitus OS — Fase 105 (APS como módulo de permissão próprio)
--
-- Pedido do usuário: "tudo que for relacionado ao APS... usuários com
-- acesso ao APS podem ter acesso limitado somente a ele e assim vice-versa".
-- Até aqui, agendar uma ordem (Fase 25), gerar sugestão de compra do MRP e
-- decidir uma sugestão (Fase 54/82) viviam dentro do módulo "producao"
-- (reaproveitando "producao.visualizar" para ENXERGAR a Agenda/MRP também)
-- — ou seja, era impossível conceder acesso só ao APS sem também abrir a
-- visão geral de Ordens de Produção, e vice-versa.
--
-- Esta migração RENOMEIA (não recria) as 3 permissões que já existiam sob
-- "producao" para o módulo novo "aps", preservando o MESMO id de
-- permissão — todo perfil que já tinha "producao.agendar"/
-- "producao.gerar_sugestao_compra"/"producao.decidir_sugestao_compra"
-- mantém automaticamente o acesso equivalente sob o nome novo, sem
-- precisar reconceder nada manualmente e sem deixar nenhuma permissão
-- órfã para trás. A quarta permissão nova, "aps.visualizar" (que cobre
-- ver a Agenda/MRP/Sugestões — antes de graça junto de
-- "producao.visualizar"), é genuinamente NOVA — não existia antes sob
-- nenhum nome — e por isso não tem nada para renomear aqui: ela nasce
-- pelo `seed.py` normal (INSERT idempotente), concedida explicitamente
-- aos perfis PCP/Produção/Compras (ver PERFIS_PADRAO).
--
-- "centros_trabalho.*" (cadastro dos recursos produtivos) já era um
-- módulo próprio desde a Fase 25 — não muda nada aqui.
PRAGMA foreign_keys = ON;

UPDATE permissoes SET modulo = 'aps'
WHERE modulo = 'producao' AND acao IN ('agendar', 'gerar_sugestao_compra', 'decidir_sugestao_compra');
