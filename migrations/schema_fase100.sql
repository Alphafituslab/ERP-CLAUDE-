-- Alphafitus OS — Fase 100 (Catálogo de Fluxo: setor responsável por cada etapa)
-- Aplicado depois de todas as fases anteriores, nunca remove nem altera nada já existente.
--
-- ESCOPO DA DECISÃO (leia antes de mexer neste arquivo):
--
-- Pedido do usuário: "colocar mais opções de ações, deixar poder cadastrar cada uma delas e
-- que cada setor só possa ver a sua ação". O Catálogo de Fluxo Configurável (Fase 81) já
-- permitia cadastrar quantas etapas quiser via `POST /fluxo/tipos-etapa` — o que faltava era
-- (1) uma TELA de verdade para isso (só existia a API, nunca uma tela) e (2) a possibilidade de
-- restringir CADA etapa a um único setor/perfil, em vez de qualquer um com a permissão genérica
-- `fluxo.apontar` ver e agir sobre TODAS as etapas de todos os setores.
--
-- `perfil_id` é OPCIONAL (nullable, sem valor padrão): uma etapa sem perfil associado continua
-- visível para QUALQUER usuário com `fluxo.apontar`, exatamente como antes desta fase — nenhuma
-- etapa já cadastrada (Separação, Coleta pela Transportadora) muda de comportamento. Só uma
-- etapa NOVA, cadastrada já com um perfil escolhido, fica restrita àquele setor.
--
-- O filtro por perfil acontece só na hora de LISTAR as etapas de uma entidade concreta
-- (`fluxo_service.etapas_da_entidade`, o que aparece no cartão de um pedido/ordem/lote) — a
-- MATERIALIZAÇÃO (criar a linha 'pendente' em fluxo_instancias) continua acontecendo para
-- TODAS as etapas ativas, independente de quem está olhando: é assim que a etapa já existe
-- pronta para quando alguém do setor certo abrir a tela, sem precisar de nenhum backfill.

PRAGMA foreign_keys = ON;

ALTER TABLE tipos_etapa_fluxo ADD COLUMN perfil_id INTEGER REFERENCES perfis(id);
