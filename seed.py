"""
Popula o banco com o catálogo de permissões, os perfis padrão e o primeiro
usuário administrador. Rode uma única vez após criar o schema (init_db):

    python seed.py

A senha do administrador inicial é lida da variável de ambiente
ALPHAFITUS_ADMIN_SENHA; se não for definida, uma senha aleatória forte é
gerada e IMPRESSA UMA ÚNICA VEZ no terminal — guarde-a, ela não é
recuperável depois (só é armazenado o hash). O usuário é criado com
senha_deve_trocar=1, então o primeiro login exige troca de senha.
"""
import os
import secrets
import sys

from app import db as db_module
from app import security
from app import audit

PERMISSOES_PADRAO = [
    ("usuarios", "visualizar", "Ver lista e detalhes de usuários", 0),
    ("usuarios", "cadastrar", "Criar novos usuários", 0),
    ("usuarios", "editar", "Editar dados e perfis de usuários", 0),
    ("usuarios", "inativar", "Inativar ou reativar usuários", 0),
    ("usuarios", "encerrar_sessao_de_outro", "Encerrar remotamente a sessão de outro usuário", 0),
    ("perfis", "visualizar", "Ver perfis e suas permissões", 0),
    ("perfis", "cadastrar", "Criar novos perfis", 0),
    ("perfis", "editar", "Alterar as permissões de um perfil", 0),
    ("perfis", "excluir", "Excluir um perfil não utilizado", 0),
    ("permissoes", "visualizar", "Ver o catálogo de permissões do sistema", 0),
    ("empresas", "visualizar", "Ver empresas e unidades", 0),
    ("empresas", "cadastrar", "Cadastrar empresas e unidades", 0),
    ("documentos", "visualizar", "Ver documentos controlados", 0),
    ("documentos", "cadastrar", "Cadastrar novos documentos", 0),
    ("documentos", "editar", "Editar ou tornar obsoleto um documento", 0),
    ("auditoria", "visualizar", "Consultar a trilha de auditoria do sistema", 0),
    # ---- Fase 2 (Qualidade e Laboratório) ----
    ("itens", "visualizar", "Ver materiais/itens cadastrados", 0),
    ("itens", "cadastrar", "Cadastrar novos itens (matérias-primas, embalagens etc.)", 0),
    ("itens", "editar", "Editar dados de um item", 0),
    ("fornecedores", "visualizar", "Ver fornecedores e sua homologação", 0),
    ("fornecedores", "cadastrar", "Cadastrar novos fornecedores", 0),
    ("fornecedores", "homologar", "Aprovar/bloquear fornecedores e homologá-los para itens específicos", 0),
    ("lotes", "visualizar", "Ver lotes e sua rastreabilidade", 0),
    ("lotes", "receber", "Registrar recebimento de lote (gera quarentena)", 0),
    ("lotes", "aprovar", "Aprovar/liberar um lote após análise", 1),
    ("lotes", "reprovar", "Reprovar um lote após análise", 1),
    ("lotes", "bloquear", "Bloquear ou desbloquear um lote a qualquer momento", 0),
    ("analises", "visualizar", "Ver análises e resultados de laboratório", 0),
    ("analises", "solicitar", "Solicitar análise de um lote em quarentena", 0),
    ("analises", "registrar_resultado", "Registrar ou corrigir o resultado de um ensaio", 0),
    ("analises", "concluir", "Concluir uma análise (calcula a conclusão geral e libera para aprovação)", 1),
    ("desvios", "visualizar", "Ver desvios e CAPAs", 0),
    ("desvios", "cadastrar", "Abrir um novo desvio", 0),
    ("desvios", "editar", "Registrar causa-raiz e plano de ação de um desvio", 0),
    ("desvios", "encerrar", "Encerrar um desvio (exige verificação de eficácia)", 0),
    # ---- Fase 3 (Produção, PCP e MES básico) ----
    ("formulas", "visualizar", "Ver fórmulas (fichas técnicas/BOM) e suas composições", 0),
    ("formulas", "cadastrar", "Criar uma nova fórmula ou nova versão de uma fórmula existente", 0),
    ("formulas", "aprovar", "Ativar uma fórmula (torna a versão anterior obsoleta automaticamente)", 1),
    ("producao", "visualizar", "Ver ordens de produção e sua genealogia de consumo", 0),
    ("producao", "planejar", "Criar e cancelar ordens de produção", 0),
    ("producao", "liberar", "Liberar uma ordem de produção planejada para início da produção", 1),
    ("producao", "apontar", "Registrar consumo de material e concluir uma ordem de produção (inclui o apontamento de perdas/refugo, quando houver)", 0),
    # ---- Fase 4 (Estoque / WMS básico) ----
    ("estoque", "visualizar", "Ver posições de armazenagem, saldos e movimentações", 0),
    ("estoque", "cadastrar_posicao", "Cadastrar novas posições de armazenagem", 0),
    ("estoque", "enderecar", "Endereçar um lote aprovado a uma posição de armazenagem", 0),
    ("estoque", "transferir", "Transferir estoque entre posições de armazenagem", 0),
    ("estoque", "ajustar", "Registrar ajuste positivo ou negativo de estoque (com motivo)", 1),
    ("estoque", "dar_baixa", "Dar baixa (descarte/saída) de estoque (com motivo)", 1),
    # ---- Fase 5 (Comercial / CRM básico + Pedidos de Venda) ----
    ("comercial", "visualizar", "Ver clientes e pedidos de venda", 0),
    ("comercial", "cadastrar_cliente", "Cadastrar e editar clientes", 0),
    ("comercial", "criar_pedido", "Criar um pedido de venda (rascunho) e ajustar seus itens", 0),
    ("comercial", "confirmar_pedido", "Confirmar um pedido de venda (reserva estoque de verdade via FEFO)", 1),
    ("comercial", "expedir_pedido", "Expedir um pedido confirmado (baixa real do estoque reservado)", 1),
    ("comercial", "cancelar_pedido", "Cancelar um pedido de venda (libera a reserva de estoque, se houver)", 0),
    # ---- Fase 63 (Limite de Crédito do Cliente) ----
    # Mesma segregação por USUÁRIO (não por perfil separado) já usada
    # desde a Fase 21/22/31/61: quem SOLICITOU a confirmação não pode ser
    # quem APROVA — verificado no código (ver aprovar_confirmacao_pedido
    # em app/routes/comercial.py), não por um perfil "Aprovador" à parte.
    # Por isso o perfil "Comercial" abaixo recebe as duas permissões
    # (comercial.confirmar_pedido E
    # comercial.aprovar_pedido_acima_limite_credito): a mesma pessoa pode
    # confirmar UM pedido e aprovar o de OUTRO colega.
    # Fase 83 — desde então esta permissão aprova a confirmação de TODO
    # pedido de venda (aprovação financeira obrigatória), não só os que
    # ultrapassam o limite de crédito do cliente — nome mantido por
    # compatibilidade com perfis/instalações já existentes.
    ("comercial", "aprovar_pedido_acima_limite_credito", "Aprovar ou rejeitar a confirmação (aprovação financeira) de um pedido de venda — quem solicitou não pode aprovar", 0),
    # ---- Fase 6 (Financeiro básico: Contas a Receber e a Pagar) ----
    ("financeiro", "visualizar", "Ver contas a receber e a pagar", 0),
    ("financeiro", "criar_conta_pagar", "Lançar uma nova conta a pagar contra um fornecedor", 0),
    ("financeiro", "registrar_baixa_pagar", "Registrar um pagamento (baixa) contra uma conta a pagar", 1),
    ("financeiro", "cancelar_conta_pagar", "Cancelar uma conta a pagar sem baixas registradas", 0),
    ("financeiro", "registrar_baixa_receber", "Registrar um recebimento (baixa) contra uma conta a receber", 1),
    ("financeiro", "cancelar_conta_receber", "Cancelar uma conta a receber sem baixas registradas", 0),
    # ---- Fase 14 (Estorno de Baixa) ----
    # Deliberadamente permissões PRÓPRIAS, separadas de registrar_baixa_*:
    # quem registra um pagamento/recebimento não necessariamente pode
    # desfazê-lo sozinho — mesma segregação de função já usada em todo o
    # módulo financeiro (Compras lança conta a pagar mas não paga;
    # Financeiro paga mas por padrão não lança).
    ("financeiro", "estornar_baixa_receber", "Estornar (reverter) uma baixa já registrada contra uma conta a receber, sem apagar o lançamento original", 1),
    ("financeiro", "estornar_baixa_pagar", "Estornar (reverter) uma baixa já registrada contra uma conta a pagar, sem apagar o lançamento original", 1),
    # ---- Fase 7 (Painel Gerencial / BI básico) ----
    ("relatorios", "visualizar", "Ver o painel de indicadores gerenciais agregados (produção, qualidade, estoque, comercial, financeiro)", 0),
    # ---- Fase 8 (Rastreabilidade Avançada / Simulação de Recall) ----
    ("rastreabilidade", "visualizar", "Ver a genealogia completa (para trás e para frente) de um lote e o histórico de simulações de recall já executadas", 0),
    ("rastreabilidade", "simular_recall", "Executar e registrar uma simulação de recall a partir de um lote (ação crítica de conformidade, exige motivo)", 1),
    # ---- Fase 13 (Custeio de Produção) ----
    # Dado financeiro sensível (preço pago a fornecedor) — deliberadamente
    # independente de producao.visualizar, mesma filosofia de segregação
    # já usada em financeiro.visualizar (Fase 6) e relatorios.visualizar
    # (Fase 7): ver custo de produção não é a mesma coisa que ver a ordem.
    ("custeio", "visualizar", "Ver o custo real de produção (por ordem e por produto), calculado a partir do custo médio de compra dos insumos, e o custo atribuível às perdas", 0),
    # ---- Fase 16 (Bloqueio em Massa a partir de Recall) ----
    # Deliberadamente separada de "rastreabilidade.simular_recall": simular
    # é só investigar (não muda nada); bloquear em massa muda o status de
    # potencialmente muitos lotes de uma vez (ação de maior impacto), mesmo
    # padrão de segregação usado em "estornar_baixa_receber/pagar" (Fase 14).
    ("rastreabilidade", "bloquear_em_massa", "Bloquear em massa todos os lotes afetados (upstream e downstream) por uma simulação de recall já registrada — ação crítica de conformidade, exige motivo", 1),
    # ---- Fase 17 (Contagem de Inventário Cíclico/Geral) ----
    # Cobre iniciar/adicionar itens/registrar contagem/cancelar. Concluir
    # (que gera os ajustes automáticos) deliberadamente reaproveita
    # "estoque.ajustar" em vez de uma permissão própria — concluir uma
    # contagem É, na prática, autorizar os ajustes que ela vai gerar.
    ("estoque", "contagem", "Iniciar e conduzir uma contagem de inventário (cíclica ou geral): adicionar itens, registrar o que foi contado, cancelar", 0),
    # ---- Fase 21 (Aprovação de 2º usuário para ajuste de contagem com divergência grande) ----
    # Deliberadamente separada de "estoque.ajustar": concluir a contagem
    # continua reaproveitando "estoque.ajustar" para os ajustes PEQUENOS
    # (mesma decisão da Fase 17), mas uma divergência GRANDE não vira
    # ajuste sozinha — precisa de um segundo usuário aprovando, e o
    # próprio código impede que quem contou o item seja quem aprova (não
    # basta ter a permissão, tem que ser outra pessoa) — mesmo padrão de
    # segregação por usuário já usado em `lotes.aprovar` desde a Fase 2.
    ("estoque", "aprovar_ajuste_contagem", "Aprovar ou rejeitar um ajuste de estoque gerado por uma divergência GRANDE numa contagem de inventário (quem contou o item não pode aprovar o próprio ajuste)", 0),
    # ---- Fase 22 (Aprovação dupla para estorno de baixa acima de um valor de alçada) ----
    # Deliberadamente separadas de "estornar_baixa_receber/pagar": pedir um
    # estorno continua exigindo só essas duas (mesmo comportamento desde a
    # Fase 14, para estornos ABAIXO do valor de alçada). Só estornos GRANDES
    # (acima do limiar) ficam pendentes até alguém com a permissão nova
    # aprovar — e o próprio código impede que quem solicitou seja quem
    # aprova, mesmo padrão de segregação por usuário já usado em
    # `estoque.aprovar_ajuste_contagem` (Fase 21).
    ("financeiro", "aprovar_estorno_receber", "Aprovar ou rejeitar uma solicitação de estorno de baixa de conta a receber acima do valor de alçada (quem solicitou não pode aprovar o próprio pedido)", 0),
    ("financeiro", "aprovar_estorno_pagar", "Aprovar ou rejeitar uma solicitação de estorno de baixa de conta a pagar acima do valor de alçada (quem solicitou não pode aprovar o próprio pedido)", 0),
    # ---- Fase 24 (Memorial Técnico ANVISA — Fundação) ----
    # Módulo novo, importado/reconstruído a pedido do cliente a partir de um
    # sistema separado que ele já usava. "memorial_empresas" é o cliente/
    # marca para quem o memorial é feito — deliberadamente uma permissão
    # própria, sem nenhuma relação com "empresas" (Fase 1, que são as
    # unidades/CNPJs da própria Alphafitus).
    ("memorial_empresas", "visualizar", "Ver empresas cadastradas no módulo de Memorial Técnico", 0),
    ("memorial_empresas", "cadastrar", "Cadastrar uma nova empresa no módulo de Memorial Técnico", 0),
    ("memorial_empresas", "editar", "Editar uma empresa já cadastrada no módulo de Memorial Técnico", 0),
    ("memorial_produtos", "visualizar", "Ver produtos cadastrados no módulo de Memorial Técnico", 0),
    ("memorial_produtos", "cadastrar", "Cadastrar um novo produto no módulo de Memorial Técnico", 0),
    ("memorial_produtos", "editar", "Editar um produto já cadastrado no módulo de Memorial Técnico", 0),
    ("memoriais", "visualizar", "Ver memoriais técnicos, seu conteúdo, assinaturas e histórico", 0),
    ("memoriais", "cadastrar", "Criar um novo memorial técnico (gera código automático, começa como rascunho)", 0),
    ("memoriais", "editar", "Editar o conteúdo de um memorial técnico já criado", 0),
    # Deliberadamente separada de "memoriais.editar": editar o conteúdo do
    # documento (texto, cálculos etc.) é uma coisa; avançar/reprovar o
    # status do fluxo (rascunho → ... → concluído/reprovado) é outra —
    # mesma segregação já usada em "producao.planejar" vs "producao.liberar"
    # desde a Fase 3.
    ("memoriais", "concluir", "Alterar o status de um memorial técnico (avançar o fluxo ou reprová-lo)", 0),
    ("memoriais", "assinar", "Assinar um memorial técnico como responsável (2 assinaturas com o memorial 'concluído' aprovam automaticamente)", 0),
    ("memoriais", "excluir", "Excluir um memorial técnico", 0),
    # ---- Fase 25 (APS — Sequenciamento e Capacidade Finita, Fundação) ----
    # "centros_trabalho" é o cadastro dos recursos produtivos (linhas,
    # máquinas, salas); ver visualizar/cadastrar/editar como em qualquer
    # outro cadastro mestre do sistema.
    ("centros_trabalho", "visualizar", "Ver centros de trabalho cadastrados e a agenda de produção", 0),
    ("centros_trabalho", "cadastrar", "Cadastrar novos centros de trabalho", 0),
    ("centros_trabalho", "editar", "Editar um centro de trabalho existente (inclusive ativar/inativar)", 0),
    # Fase 105 — módulo PRÓPRIO "aps" (era uma ação dentro de "producao"
    # até aqui, ver comentário histórico abaixo): o pedido do usuário foi
    # "usuários com acesso ao APS podem ter acesso limitado somente a ele,
    # e vice-versa" — ou seja, alguém precisa poder ganhar acesso ao
    # Sequenciamento/Capacidade Finita SEM automaticamente ganhar
    # visibilidade do resto de Produção (Ordens de Produção, apontamento
    # de consumo etc.), e vice-versa. Reaproveitar "producao.*" tornava
    # essa separação impossível — por isso um módulo "aps" próprio, no
    # mesmo padrão de "centros_trabalho" (Fase 25), que já era separado.
    # A migração `schema_fase105.sql` RENOMEIA (não recria) estas 3
    # permissões — todo perfil que já tinha "producao.agendar"/
    # "producao.gerar_sugestao_compra"/"producao.decidir_sugestao_compra"
    # mantém o acesso equivalente sob o novo nome, sem precisar reconceder
    # nada manualmente.
    #
    # Comentário histórico (Fase 25, quando isto ainda vivia em
    # "producao"): "agendar é uma ação sobre uma ORDEM DE PRODUÇÃO, no
    # mesmo espírito de producao.planejar/producao.liberar/
    # producao.apontar — ver a ordem (producao.visualizar) já é suficiente
    # para ver sua agenda." Essa premissa (ver Produção implica poder ver
    # a agenda do APS) é exatamente o que deixou de valer — daí "aps.
    # visualizar" abaixo, próprio, concedido explicitamente a quem precisa.
    ("aps", "visualizar", "Ver a Agenda (APS), o MRP e as Sugestões de Compra derivadas dele", 0),
    ("aps", "agendar", "Agendar ou reagendar uma ordem de produção num centro de trabalho e janela de tempo", 0),
    # ---- Fase 26 (Catálogos do Memorial Técnico ANVISA) ----
    # Um recurso só cobrindo os 10 catálogos (Metodologias, Nutrientes,
    # Legislações, Alegações, Tipos de Produto, Advertências,
    # Armazenamento, Modo de Uso, Justificativas, Referências) — no
    # sistema original também era uma permissão só ("catalogo.editar"/
    # "catalogo.excluir") cobrindo todos eles, então mantém-se aqui.
    ("memorial_catalogos", "visualizar", "Ver os catálogos de apoio do Memorial Técnico (Metodologias, Nutrientes, Legislações etc.)", 0),
    ("memorial_catalogos", "cadastrar", "Cadastrar um novo item em qualquer catálogo de apoio do Memorial Técnico", 0),
    ("memorial_catalogos", "editar", "Editar (ou ativar/inativar) um item já cadastrado em qualquer catálogo de apoio do Memorial Técnico", 0),
    ("memorial_catalogos", "excluir", "Excluir um item de qualquer catálogo de apoio do Memorial Técnico", 0),
    # ---- Fase 27 (Memorial Técnico ANVISA — Anexos e Padronização de Rótulo) ----
    # Anexos reaproveitam "memoriais.visualizar"/"memoriais.editar" (anexar
    # um arquivo é parte de editar o conteúdo do memorial). Padronização
    # ganha um verbo próprio no recurso "memoriais" já existente — mesmo
    # padrão de "producao.agendar" (Fase 25): editar a padronização é uma
    # ação sobre um memorial específico, não um recurso à parte.
    ("memoriais", "padronizar", "Editar a padronização de rótulo (dizeres de rotulagem) de um memorial técnico", 0),
    # ---- Fase 31 (Aprovação dupla para o REGISTRO de baixa acima de um valor de alçada) ----
    # Deliberadamente separadas de "registrar_baixa_receber/pagar": lançar
    # uma baixa continua exigindo só essas duas (mesmo comportamento desde
    # a Fase 6, para baixas ABAIXO do valor de alçada). Só baixas GRANDES
    # (acima do limiar) ficam pendentes até alguém com a permissão nova
    # aprovar — e o próprio código impede que quem solicitou seja quem
    # aprova, mesmo padrão de segregação por usuário já usado em
    # `financeiro.aprovar_estorno_receber/pagar` (Fase 22).
    ("financeiro", "aprovar_baixa_receber", "Aprovar ou rejeitar uma solicitação de registro de baixa de conta a receber acima do valor de alçada (quem solicitou não pode aprovar o próprio pedido)", 0),
    ("financeiro", "aprovar_baixa_pagar", "Aprovar ou rejeitar uma solicitação de registro de baixa de conta a pagar acima do valor de alçada (quem solicitou não pode aprovar o próprio pedido)", 0),
    # ---- Fase 32 (Limiar de divergência de contagem configurável pela tela) ----
    # Deliberadamente separada de "estoque.ajustar"/"aprovar_ajuste_contagem":
    # mudar a RÉGUA que decide o que conta como divergência grande é uma
    # decisão de controle interno, não uma operação do dia a dia — só o
    # Administrador tem por padrão (ver PERFIS_PADRAO abaixo).
    ("estoque", "configurar_alcada_divergencia", "Alterar o limiar de percentual de divergência que decide se o ajuste de uma contagem exige segunda aprovação (Fase 21)", 0),
    # ---- Fase 33 (Limite de prazo para estorno de baixa configurável pela tela) ----
    # Mesma filosofia da Fase 32: mudar a régua que decide até quando um
    # estorno ainda vale é uma decisão de controle interno (poderia,
    # inclusive, ser usada para "fechar" um mês fiscal contra estornos
    # tardios), não uma operação do dia a dia — deliberadamente separada
    # de "estornar_baixa_receber/pagar" — só o Administrador tem por
    # padrão (ver PERFIS_PADRAO abaixo).
    ("financeiro", "configurar_limite_estorno", "Alterar as configurações do Financeiro: o limite de dias, contados da baixa original, dentro do qual um estorno ainda é permitido (0 = sem limite), e o percentual de imposto sobre vendas usado no DRE (Fase 41)", 0),
    # ---- Fase 35 (Agendamento/cadência automática de contagens cíclicas) ----
    # Cadastrar/editar/desativar uma REGRA que gera contagens sozinha é
    # uma decisão de controle interno (decide o RITMO do inventário da
    # empresa), deliberadamente separada de "estoque.contagem" (conduzir
    # a contagem do dia a dia) — só o Administrador tem por padrão (ver
    # PERFIS_PADRAO abaixo).
    ("estoque", "agendar_contagem", "Criar, editar e desativar agendamentos de cadência automática de contagens de inventário (geral ou cíclica por amostra)", 0),
    # ---- Fase 36 (App de Vendas: rascunho com reserva temporária, verbas comerciais e comissão) ----
    ("vendas_app", "usar", "Usar o aplicativo de vendas em campo: ver catálogo, montar rascunho, aplicar verba, ver suas comissões", 0),
    # Deliberadamente separada de "vendas_app.usar" — ver a mesma
    # segregação já usada em "comercial.confirmar_pedido" (Fase 5): montar
    # o carrinho é uma coisa, mandar de verdade (o que consome saldo real
    # via FEFO) é outra.
    ("vendas_app", "enviar_pedido", "Enviar (confirmar) um rascunho montado no aplicativo de vendas", 0),
    # Mesma filosofia das Fases 32/33/34/35: mudar a RÉGUA (percentual de
    # verba gerada, percentual de comissão, minutos de expiração do
    # rascunho) é uma decisão de controle interno, não uma operação do dia
    # a dia — deliberadamente separada de "vendas_app.usar" — só o
    # Administrador tem por padrão (ver PERFIS_PADRAO abaixo).
    ("comercial", "configurar_comercial", "Alterar o percentual de verba comercial gerada, o percentual de comissão padrão e os minutos de expiração do rascunho do app de vendas", 0),
    # ---- Fase 37 (Notificações do Sistema com Envio Real por E-mail) ----
    # Módulo novo "sistema" (em vez de encaixar em algum módulo de negócio
    # existente): configurar o servidor SMTP usado para o envio de
    # notificações é uma decisão de infraestrutura do sistema como um
    # todo, não de um módulo específico — mesma filosofia de "decisão de
    # controle interno, só o Administrador por padrão" das configurações
    # das Fases 32/33/34/35/36. Ver e marcar como lida as PRÓPRIAS
    # notificações, e desligar o recebimento por e-mail para si mesmo, não
    # exigem nenhuma permissão nova — continuam abertos a qualquer usuário
    # autenticado (`requires_auth`), como já eram desde a Fase 1.
    ("sistema", "configurar_email", "Configurar o servidor de e-mail (SMTP) usado para o envio de notificações por e-mail, e testar o envio", 0),
    # ---- Fase 40 (Conciliação Bancária — Importação de Extrato OFX) ----
    # Um verbo só cobre importar o arquivo, conciliar/ignorar/desconciliar
    # cada transação — mesmo espírito de "estoque.contagem" (Fase 17,
    # também cobre o ciclo inteiro de uma ação com um só verbo): quem
    # importa o extrato do banco é, na prática, a mesma pessoa (o time de
    # Financeiro) que reconcilia as transações contra as baixas já
    # lançadas — diferente das aprovações duplas do resto do módulo
    # (Fases 22/31), aqui não há "outra pessoa" decidindo sobre o pedido
    # de alguém; é o mesmo usuário revisando o próprio trabalho contra um
    # documento externo (o extrato do banco), não contra outra pessoa.
    ("financeiro", "conciliar_extrato", "Importar um extrato bancário (OFX) e conciliar, ignorar ou desconciliar suas transações contra baixas já registradas", 0),
    # ---- Fase 47 (Memorial Técnico ANVISA — Administração: Backups do
    # Sistema) ----
    # Terceiro pedaço da seção "Administração" replicada dentro do
    # Memorial Técnico (depois de Usuários Online na Fase 44 e Snapshots &
    # Restauração na Fase 46) — mas, diferente dos outros dois, o backup
    # aqui é do BANCO DE DADOS INTEIRO (todas as tabelas de todos os
    # módulos), não só das tabelas do Memorial Técnico. Por isso NÃO
    # reaproveita `memoriais.*` como os outros dois pedaços — seria
    # enganoso conceder acesso a um backup de todo o sistema para quem só
    # tem permissão sobre o módulo Memorial Técnico. Fica no módulo
    # genérico "sistema" (mesmo módulo/filosofia da Fase 37 — configurar_email:
    # uma decisão de infraestrutura do sistema como um todo, não de um
    # módulo de negócio específico), só o Administrador por padrão.
    ("sistema", "backup_completo", "Baixar uma cópia de backup do banco de dados do sistema inteiro (todos os módulos, não só o Memorial Técnico)", 0),
    # ---- Fase 49 (Memorial Técnico ANVISA — Administração: Configurações) ----
    # Último pedaço da seção "Administração" replicada dentro do Memorial
    # Técnico (depois de Usuários Online — Fase 44, Snapshots &
    # Restauração — Fase 46, Backups do Sistema — Fase 47, e Gerenciar
    # Usuários — Fase 48). Diferente de "sistema.backup_completo" (Fase
    # 47), esta configuração só afeta regras DENTRO do próprio módulo
    # Memorial Técnico (número de assinaturas para aprovação automática,
    # tamanho máximo de anexo) — por isso segue o padrão das Fases 32-36
    # (`configurar_X` DENTRO do módulo de negócio, não em "sistema"). Ver
    # visualizar/configurar: ver o valor atual não é sensível (liberado
    # para quem já visualiza o módulo); só ALTERAR exige a permissão nova.
    ("memoriais", "configurar", "Alterar as regras configuráveis do Memorial Técnico (nº de assinaturas para aprovação automática, tamanho máximo de anexo)", 0),
    # ---- Fase 53 (Recall: Decisão sobre Pedidos Já Expedidos) ----
    # Deliberadamente separada de "rastreabilidade.simular_recall" e de
    # "rastreabilidade.bloquear_em_massa" (Fase 16): esta ação não muda o
    # status de nenhum lote nem executa nenhum cancelamento/estorno de
    # verdade (isso continua exigindo as permissões já existentes de
    # Comercial/Financeiro) — só REGISTRA, como evento histórico de
    # conformidade, a decisão tomada para um pedido já expedido afetado
    # por um recall. Por não executar nada irreversível sozinha, não exige
    # dupla aprovação (diferente de simular_recall/bloquear_em_massa, que
    # são ações críticas de conformidade).
    ("rastreabilidade", "decidir_pedido_recall", "Registrar a decisão tomada (notificar cliente, aguardar devolução, gerar nota de crédito, cancelar pedido ou sem ação) para um pedido já expedido afetado por uma simulação de recall", 0),
    # ---- Fase 54 (MRP: Sugestão Automática de Compra) ----
    # "gerar" (criar sugestões pendentes a partir do MRP atual) e "decidir"
    # (marcar atendida/descartada) são permissões separadas pelo mesmo
    # motivo de sempre neste sistema: gerar é de baixo risco (só cria um
    # item de trabalho derivado, não uma obrigação financeira de verdade),
    # decidir é quem efetivamente fecha o ciclo de Compras. Módulo "aps"
    # desde a Fase 105 (ver comentário completo junto de "aps.agendar",
    # acima) — eram "producao.gerar_sugestao_compra"/"producao.
    # decidir_sugestao_compra" até aqui.
    ("aps", "gerar_sugestao_compra", "Gerar sugestões de compra a partir da necessidade atual calculada pelo MRP (não cria conta a pagar nem nenhuma obrigação financeira real)", 0),
    ("aps", "decidir_sugestao_compra", "Marcar uma sugestão de compra do MRP como atendida (compra já providenciada) ou descartada (com motivo)", 0),
    # ---- Fase 58 (Pedido de Compra formal) ----
    # Módulo novo "compras" (em vez de continuar encaixando em "producao",
    # como as duas permissões acima da Fase 54 fizeram por reaproveitar a
    # mesma visibilidade da agenda/MRP): um Pedido de Compra é um
    # documento próprio de Compras, com ciclo de vida e itens — justifica
    # seu próprio namespace de permissão, mesmo padrão de "estoque",
    # "comercial" e "financeiro" já usados desde as primeiras fases.
    ("compras", "visualizar", "Ver pedidos de compra e seus itens", 0),
    ("compras", "criar_pedido", "Criar um pedido de compra (rascunho), manualmente ou a partir de uma sugestão do MRP (Fase 54)", 0),
    # Deliberadamente separada de "criar_pedido" — mesma segregação entre
    # "montar" e "comprometer de fato" já usada em Comercial desde a Fase
    # 5 (criar_pedido vs. confirmar_pedido): montar o pedido é uma coisa,
    # enviá-lo de verdade ao fornecedor (a partir daí aceita recebimento)
    # é outra.
    ("compras", "enviar_pedido", "Enviar um pedido de compra ao fornecedor (rascunho -> enviado, passa a aceitar recebimento vinculado)", 0),
    ("compras", "cancelar_pedido", "Cancelar um pedido de compra em rascunho ou enviado, desde que nenhum recebimento já tenha sido registrado contra ele", 0),
    # ---- Fase 61 (Alçada por Valor no Envio do Pedido de Compra) ----
    # Mesma segregação por USUÁRIO (não por perfil separado) já usada desde
    # a Fase 21/22/31: quem SOLICITOU o envio não pode ser quem APROVA —
    # verificado no código (ver aprovar_envio_pedido em
    # app/routes/compras.py), não por um perfil "Aprovador" à parte. Por
    # isso o perfil "Compras" abaixo recebe as duas permissões
    # (compras.enviar_pedido E compras.aprovar_pedido_grande): a mesma
    # pessoa pode solicitar UM pedido e aprovar o de OUTRO colega.
    ("compras", "aprovar_pedido_grande", "Aprovar ou rejeitar o envio de um pedido de compra acima do valor de alçada (quem solicitou o envio não pode aprovar)", 0),
    # Só o Administrador tem essa por padrão — mesma decisão de controle
    # interno reservada a quem decide as regras, não a quem opera o dia a
    # dia, já usada em "estoque.configurar_alcada_divergencia" (Fase 21) e
    # "financeiro.configurar_limite_estorno" (Fase 33/34).
    ("compras", "configurar_alcada_pedido", "Alterar o limiar de valor que decide se enviar um pedido de compra exige segunda aprovação", 0),
    # ---- Fase 66 (Cotação Comparativa de Fornecedores / RFQ) ----
    # Mesmo espírito de granularidade já usado em Compras desde a Fase 58:
    # "montar" a cotação (itens + fornecedores convidados), "registrar" o
    # que cada fornecedor respondeu (só digita o que veio por telefone/
    # e-mail — não decide nada) e "fechar" (decide o vencedor, e ISSO gera
    # o Pedido de Compra de verdade) são três momentos/responsabilidades
    # diferentes, cada um com sua própria permissão — quem só cadastra
    # respostas não necessariamente pode decidir o vencedor sozinho.
    ("compras", "criar_cotacao", "Criar uma cotação comparativa (RFQ), listando os itens a cotar e convidando fornecedores a participar", 0),
    ("compras", "registrar_resposta_cotacao", "Registrar a resposta de um fornecedor convidado a uma cotação (preço e prazo de entrega por item, conforme recebido por telefone/e-mail)", 0),
    ("compras", "fechar_cotacao", "Fechar uma cotação escolhendo o fornecedor vencedor, gerando automaticamente o Pedido de Compra correspondente", 0),
    ("compras", "cancelar_cotacao", "Cancelar uma cotação em aberto, antes de ser fechada", 0),
    # ---- Fase 67 (Backup Automático Agendado, Envio para Nuvem/E-mail, Restauração) ----
    # Mesmo módulo genérico "sistema" já usado por "backup_completo" (Fase
    # 47) — mas com DUAS permissões novas e deliberadamente separadas:
    # "configurar_backup" decide COMO/QUANDO o backup automático roda
    # (horários, credenciais de nuvem, destinatários de e-mail) —
    # infraestrutura de configuração, mesmo espírito de
    # "configurar_email" (Fase 37). "restaurar_backup" é a ação de maior
    # risco do sistema inteiro (substitui o banco de dados completo no
    # próximo início) — fica de propósito separada mesmo de
    # "backup_completo" (que só LÊ/gera cópias), para nunca conceder o
    # poder de restaurar a quem só precisa poder baixar ou agendar
    # backups.
    ("sistema", "configurar_backup", "Configurar o backup automático agendado do sistema (horários, envio para nuvem, destinatários de e-mail)", 0),
    ("sistema", "restaurar_backup", "Restaurar o banco de dados do sistema inteiro a partir de um arquivo de backup — ação de maior risco do sistema, substitui todos os dados atuais no próximo início", 0),
    # ---- Fase 68 (Servidor e Terminais) — só instalador, sem permissão nova ----
    # ---- Fase 69 (Painel Gerencial — Série Histórica/Tendência) — reaproveita relatorios.visualizar, sem permissão nova ----
    # ---- Fase 70 (Fiscal — Emissão de NF-e) ----
    # "empresas.editar" não existia até aqui (só visualizar/cadastrar) —
    # criada agora para permitir preencher os dados fiscais da empresa
    # (endereço, IE, regime tributário) sem misturar com a permissão mais
    # ampla de "cadastrar" uma empresa nova.
    ("empresas", "editar", "Editar dados de uma empresa já cadastrada (inclui dados fiscais para NF-e)", 0),
    # Módulo novo "fiscal": "configurar" (token do provedor, ambiente,
    # série — infraestrutura de configuração, mesmo espírito de
    # "sistema.configurar_email"/"configurar_backup") fica separado de
    # "emitir" (a ação de negócio que de fato gera uma nota) pelo mesmo
    # raciocínio de todo o resto do sistema: quem pode configurar o token
    # de API não necessariamente deveria poder emitir notas no dia a dia, e
    # vice-versa. "cancelar" fica ainda mais separado por ser a ação mais
    # arriscada do módulo (uma NF-e cancelada errado pode gerar problema
    # fiscal de verdade).
    ("fiscal", "visualizar", "Ver notas fiscais emitidas e consultar o status de uma emissão", 0),
    ("fiscal", "configurar", "Configurar o provedor de NF-e (token de API, ambiente de homologação/produção, série)", 0),
    ("fiscal", "emitir", "Emitir uma NF-e a partir de um pedido de venda expedido", 0),
    ("fiscal", "cancelar", "Cancelar uma NF-e já autorizada", 0),
    # ---- Fase 71 (Financeiro — Emissão de Boleto Bancário) ----
    # Reaproveita o módulo "financeiro" já existente (mesmo raciocínio da
    # Fase 67 reaproveitar "sistema" em vez de criar um módulo novo para
    # cada infraestrutura de configuração) em vez de um módulo "boleto"
    # separado — gerar/cancelar boleto é claramente uma ação do dia a dia
    # do Financeiro, não um domínio de negócio à parte como o Fiscal
    # (NF-e) da Fase 70, que tem empresa emitente, regime tributário etc.
    ("financeiro", "gerar_boleto", "Gerar um boleto bancário de verdade para uma conta a receber, via provedor terceirizado", 0),
    ("financeiro", "cancelar_boleto", "Cancelar um boleto ainda pendente (não pago)", 0),
    ("financeiro", "configurar_boleto", "Configurar o provedor de emissão de boleto (token de API, ambiente sandbox/produção)", 0),
    # ---- Fase 75 (Etapas de Processo Configuráveis + Painel de Chão de
    # Fábrica em Tempo Real) ----
    # Reaproveita o módulo "producao" já existente (mesmo raciocínio da
    # Fase 67/71 acima) em vez de um módulo à parte: cadastrar/editar os
    # TIPOS de etapa (Pesagem, Mistura, etc.) é uma decisão de configuração
    # do processo produtivo — separada de "producao.apontar" (a ação do
    # dia a dia no chão de fábrica de iniciar/concluir uma etapa CONCRETA
    # dentro de uma ordem, que continua sem exigir nada novo). Sem
    # permissão de leitura própria: listar os tipos já cadastrados usa
    # "producao.visualizar", a mesma que já abre a tela de Ordens de
    # Produção — não faria sentido alguém ver a ordem mas não o catálogo
    # que a alimenta.
    ("producao", "configurar_etapas", "Cadastrar/editar os tipos de etapa do processo produtivo (Pesagem, Mistura, etc.)", 0),
    # ---- Fase 78 (SPED Fiscal 1/5 — Notas Fiscais de Entrada) ----
    # Reaproveita o módulo "fiscal" já existente (mesmo módulo da NF-e de
    # saída, Fase 70) em vez de criar um módulo à parte — é o mesmo domínio
    # de negócio (documentos fiscais), só que do lado de ENTRADA (compra) em
    # vez de saída (venda). Separada de "fiscal.emitir"/"fiscal.cancelar"
    # porque é uma ação diferente (lançamento manual de dados de uma nota
    # que já chegou, não emissão via provedor) — "fiscal.cancelar" já
    # existente é reaproveitada para cancelar um lançamento de entrada
    # também, mesmo raciocínio de "é a ação mais arriscada do módulo".
    ("fiscal", "registrar_entrada", "Lançar os dados de uma nota fiscal de entrada (compra) recebida de um fornecedor", 0),
    # ---- Fase 79 (SPED Fiscal 2/5 — Configuração Fiscal) ----
    # Mesmo raciocínio de "fiscal.configurar" (Fase 70, token do provedor de
    # NF-e): são parâmetros de infraestrutura fiscal, não uma ação de
    # negócio do dia a dia — errar aqui afeta toda apuração futura, por
    # isso fica só com o Administrador (não entra em nenhum PERFIS_PADRAO
    # abaixo além dele).
    ("fiscal", "configurar_sped", "Configurar os parâmetros de apuração do SPED Fiscal (alíquotas de ICMS/IPI/PIS/COFINS)", 0),
    # ---- Fase 80 (Solicitações de Materiais/EPI) ----
    # "solicitar" é dada de propósito a quase todo perfil operacional
    # abaixo (qualquer setor pode pedir material/EPI) — só "aprovar" fica
    # de fora de qualquer perfil padrão: "alguém designado" para aprovar é
    # uma escolha de cada instalação (SESMT, RH, um supervisor específico
    # etc.), não um papel que já existe hoje no sistema — o Administrador
    # decide quem tem essa permissão pela tela de Perfis, quando for usar
    # o módulo. "entregar" vai para o perfil Estoque (mesmo raciocínio de
    # "o outro setor" do pedido original — quem já mexe com o estoque
    # físico é quem libera a entrega). Segregação de função verificada no
    # código (quem solicita não pode aprovar o próprio pedido), mesmo
    # padrão já usado em lotes.aprovar (Fase 1) e nas aprovações de
    # baixa/estorno do Financeiro.
    ("solicitacoes_material", "visualizar", "Ver solicitações de materiais/EPI", 0),
    ("solicitacoes_material", "solicitar", "Criar uma solicitação de material ou EPI", 0),
    ("solicitacoes_material", "aprovar", "Aprovar ou rejeitar uma solicitação de material/EPI pendente", 0),
    ("solicitacoes_material", "entregar", "Registrar a entrega de uma solicitação já aprovada", 0),
    ("solicitacoes_material", "cadastrar_catalogo", "Cadastrar/editar os materiais e EPIs disponíveis para solicitação", 0),

    # Fase 81 — Catálogo de Fluxo Configurável (base do Painel Kanban, Fase 90). Cobre só as
    # etapas que NÃO têm uma coluna de status própria em nenhuma tabela existente (ex.:
    # "Separação" de um pedido de venda, "Coleta pela Transportadora" na Fase 86) — o restante
    # do pipeline continua lido ao vivo das tabelas de sempre (pedidos_venda, ordens_producao,
    # lotes, pedidos_compra), sem duplicar nada aqui.
    ("fluxo", "configurar", "Cadastrar/editar os tipos de etapa do catálogo de fluxo multi-módulo", 0),
    ("fluxo", "apontar", "Iniciar/concluir uma etapa manual do fluxo (ex.: Separação de um pedido)", 0),

    # Fase 85 — mesma régua de "configurar" mais arriscado, só Administrador
    # por padrão, já usada em fiscal.configurar/fiscal.configurar_sped.
    ("qualidade", "configurar", "Ligar/desligar a exigência de NF-e de entrada vinculada antes de aprovar um lote recebido", 0),

    # Fase 86 — Transportadora / Coleta (MVP).
    ("comercial", "gerenciar_coleta", "Cadastrar transportadoras e agendar/confirmar/cancelar a coleta de um pedido expedido", 0),

    # Fase 99 — Tabelas de Preço (pré-preenchimento de preço no Pedido de Venda, por cliente).
    ("tabelas_preco", "visualizar", "Ver tabelas de preço e os preços cadastrados nelas", 0),
    ("tabelas_preco", "gerenciar", "Criar/editar tabelas de preço e definir o preço de cada item nelas", 0),

    # Fase 111 — Arquitetura Servidor + Terminais: registro de máquinas que já acessam
    # o servidor pela rede (o registro em si, POST /terminais/heartbeat, não exige
    # nenhuma permissão — qualquer sessão autenticada pode registrar presença; só ver a
    # lista e bloquear/liberar um terminal são ações administrativas).
    ("terminais", "visualizar", "Ver a lista de terminais que já se conectaram ao servidor", 0),
    ("terminais", "bloquear", "Bloquear ou liberar o acesso de um terminal específico ao servidor", 0),

    # Fase 123 — Recebimento e Importação de NF-e. Módulo próprio (em vez
    # de encaixar em "compras" ou "fiscal") porque tem seu próprio ciclo de
    # vida (recebida -> conferida -> importada) e ações com risco bem
    # diferente entre si: "conferir" é o dia a dia (vincular item/pedido,
    # aplicar conversão de unidade, registrar manifestação/situação
    # interna); "importar" é o que efetivamente mexe em estoque
    # (`lotes`)/financeiro/fiscal (`notas_fiscais_entrada`, Fase 78) — só
    # quem já confere pode também importar, mas nem todo perfil que
    # confere precisa poder finalizar sozinho; "configurar" (tolerâncias,
    # certificado A1 da Fase B) fica reservado, mesma régua de
    # "compras.configurar_alcada_pedido"/"fiscal.configurar".
    ("nfe_entrada", "visualizar", "Ver a fila de NF-e recebidas e o detalhe de conferência de cada uma", 0),
    ("nfe_entrada", "conferir", "Vincular fornecedor/pedido/produto, cadastrar conversão de unidade e registrar manifestação/situação interna de uma NF-e recebida", 0),
    ("nfe_entrada", "importar", "Importar uma NF-e conferida para o estoque (gera lote por item, com lote/validade, e o lançamento fiscal correspondente)", 0),
    # Separada de "importar" de propósito (seção 11 da especificação:
    # "caso existam divergências críticas, exigir autorização de usuário
    # com permissão apropriada") — importar um item que bateu 🟢 na
    # conferência é o caminho normal; importar um item que ficou 🔴
    # (preço ou quantidade fora da tolerância configurada) exige essa
    # permissão adicional MAIS uma justificativa por escrito (ver
    # validação em app/routes/nfe_entrada.py), nunca passa batido.
    ("nfe_entrada", "importar_com_divergencia", "Importar uma NF-e mesmo com item(ns) em divergência de preço/quantidade fora da tolerância (exige justificativa)", 1),
    ("nfe_entrada", "configurar", "Alterar as tolerâncias de divergência de preço/quantidade e configurar o certificado digital A1 para consulta automática à SEFAZ", 0),

    # Fase 125 — lançamento avulso de conta a receber, sem Pedido de Venda
    # por trás (mesma ideia de "financeiro.criar_conta_pagar", que desde a
    # Fase 41 já não exige Pedido de Compra). Até aqui toda conta a receber
    # só nascia da confirmação de um pedido; isso deixava de fora qualquer
    # saldo devedor que não veio de uma venda feita dentro do próprio
    # Alphafitus — o caso real que motivou esta fase foi a importação do
    # saldo de clientes do sistema anterior (Ema), mas serve para qualquer
    # lançamento avulso futuro (ex.: acordo extrajudicial, reembolso).
    ("financeiro", "criar_conta_receber", "Lançar uma nova conta a receber avulsa contra um cliente, sem um Pedido de Venda por trás", 0),
]

# Fase 92 (depois ajustada na Fase 94) — perfis para os quais o 2FA (TOTP)
# é RECOMENDADO (banner em Minha Conta). A Fase 92 original bloqueava a
# API inteira até a pessoa configurar; a Fase 94 tornou isso não-bloqueante
# a pedido do usuário ("deixar eu escolher quando iniciar... habilitar e
# desabilitar"). Continua uma lista separada (em vez de um 5º elemento em
# cada tupla de PERFIS_PADRAO) de propósito: evita reescrever as ~14
# tuplas já existentes só para acrescentar um campo que só se aplica a
# duas delas.
PERFIS_QUE_EXIGEM_2FA = ("Administrador", "Financeiro")

PERFIS_PADRAO = [
    ("Administrador", "Acesso total ao sistema. Perfil de sistema, não pode ser excluído ou ter permissões removidas.", 0, "TODAS"),
    ("PCP", "Planejamento e Controle da Produção", 1, [
        "itens.visualizar", "lotes.visualizar", "formulas.visualizar", "formulas.cadastrar",
        "producao.visualizar", "producao.planejar", "producao.liberar", "estoque.visualizar", "empresas.visualizar",
        # Fase 25 — o mesmo perfil que planeja/libera ordens é quem monta a
        # agenda (o "S" de APS — Sequenciamento) e cadastra os centros de
        # trabalho contra os quais ela é montada. Fase 105 — "aps.*" é
        # módulo próprio, concedido explicitamente aqui (não vem mais de
        # graça junto com "producao.visualizar").
        "centros_trabalho.visualizar", "centros_trabalho.cadastrar", "centros_trabalho.editar",
        "aps.visualizar", "aps.agendar",
        # Fase 75 — o mesmo perfil que já planeja o processo produtivo é
        # quem decide QUAIS etapas existem (Pesagem, Mistura, etc.);
        # cadastrar uma etapa concreta numa ordem e apontar seu
        # início/fim continua sendo "producao.apontar", do perfil
        # "Produção" (chão de fábrica) abaixo.
        "producao.configurar_etapas",
        # Fase 80 — qualquer setor pode solicitar material/EPI.
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
        # Fase 81 — PCP é quem decide se cadastra uma etapa nova no catálogo
        # de fluxo do painel (mesmo raciocínio de "producao.configurar_etapas"
        # acima, agora estendido para fora da Ordem de Produção).
        "fluxo.configurar", "fluxo.apontar",
        # Fase 82 — PCP passa a poder rodar o MRP e gerar sugestões de
        # compra a partir da necessidade calculada (mesma tela/rota que
        # Compras já usa desde a Fase 54) — "solicita" a compra de matéria-
        # prima. Decidir o que fazer com a sugestão (atender/descartar) e
        # convertê-la num Pedido de Compra real continua EXCLUSIVO de
        # Compras ("aps.decidir_sugestao_compra"/"compras.
        # criar_pedido", perfil "Compras" abaixo) — "aprova e confirma a
        # compra" continua sendo uma responsabilidade só deles.
        "aps.gerar_sugestao_compra",
    ]),
    # Fase 91 — "setor de liberação" das Solicitações de Materiais/EPI: até
    # aqui, "solicitacoes_material.aprovar" não estava em NENHUM perfil
    # padrão (só o Administrador aprovava, por ter TODAS as permissões).
    # Este perfil dá a essa responsabilidade um dono explícito desde a
    # instalação — mas continua tão configurável quanto qualquer outro
    # perfil: em Perfis, dá pra renomear, trocar quem está nele, ou mover
    # a permissão "aprovar" para outro perfil qualquer, se a empresa
    # preferir outro setor decidindo isso (ex.: Segurança do Trabalho).
    ("Liberação de Materiais/EPI", "Aprova ou rejeita solicitações de material/EPI pendentes", 1, [
        "solicitacoes_material.visualizar", "solicitacoes_material.aprovar",
    ]),
    ("Produção", "Execução da produção (MES)", 1, [
        "itens.visualizar", "lotes.visualizar", "formulas.visualizar",
        "producao.visualizar", "producao.apontar", "estoque.visualizar", "empresas.visualizar",
        # Fase 25 — o chão de fábrica só ENXERGA a agenda (o que já foi
        # sequenciado pelo PCP), não pode criar/mudar centro de trabalho
        # nem reagendar — por isso só a permissão de visualizar. Fase 105 —
        # "aps.visualizar" é o que efetivamente abre a tela de Agenda (APS)
        # em si; "centros_trabalho.visualizar" só mostra o cadastro dos
        # recursos.
        "centros_trabalho.visualizar", "aps.visualizar",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
    ]),
    ("Laboratório", "Analistas de laboratório (LIMS)", 1, [
        "itens.visualizar", "fornecedores.visualizar", "lotes.visualizar",
        "analises.visualizar", "analises.solicitar", "analises.registrar_resultado", "analises.concluir",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
    ]),
    ("Qualidade", "Aprovação e liberação de lotes (QMS)", 1, [
        "auditoria.visualizar", "itens.visualizar", "fornecedores.visualizar", "fornecedores.homologar",
        "lotes.visualizar", "lotes.aprovar", "lotes.reprovar", "lotes.bloquear", "analises.visualizar",
        "desvios.visualizar", "desvios.cadastrar", "desvios.editar", "desvios.encerrar",
        "formulas.visualizar", "formulas.aprovar", "producao.visualizar", "estoque.visualizar", "empresas.visualizar",
        # A decisão de investigar/recolher um lote é uma responsabilidade de
        # Qualidade, mesmo dono do processo de desvios/CAPA acima. O
        # bloqueio em massa (Fase 16) é a mesma responsabilidade, só que
        # aplicada de uma vez a todos os lotes que uma investigação aponta.
        # Fase 53 — decidir o que fazer com um pedido já expedido afetado
        # por um recall (notificar cliente, aguardar devolução etc.) é a
        # mesma responsabilidade de conduzir a investigação acima; a
        # EXECUÇÃO da decisão (cancelar de fato, estornar) continua exigindo
        # as permissões próprias de Comercial/Financeiro.
        "rastreabilidade.visualizar", "rastreabilidade.simular_recall", "rastreabilidade.bloquear_em_massa",
        "rastreabilidade.decidir_pedido_recall",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
    ]),
    ("Estoque", "Gestão de armazém (WMS)", 1, [
        "itens.visualizar", "itens.cadastrar", "itens.editar", "lotes.visualizar", "lotes.receber", "lotes.bloquear",
        "estoque.visualizar", "estoque.cadastrar_posicao", "estoque.enderecar", "estoque.transferir",
        "estoque.ajustar", "estoque.dar_baixa", "estoque.contagem", "estoque.aprovar_ajuste_contagem",
        "comercial.visualizar", "comercial.expedir_pedido", "empresas.visualizar",
        # Fase 58 — quem recebe o material quer ver os pedidos de compra
        # abertos para saber o que esperar e linkar o recebimento a eles;
        # só visualizar, não cria/envia/cancela pedido (isso é decisão de
        # Compras, abaixo).
        "compras.visualizar",
        # Fase 80 — quem já lida com estoque físico é "o outro setor" que
        # o pedido original menciona: liberado a ENTREGAR uma solicitação
        # já aprovada, e a manter o catálogo de materiais/EPI disponíveis.
        # Aprovar continua fora daqui de propósito (segregação de função
        # entre quem entrega e quem aprova) — ver a nota completa em
        # PERMISSOES_PADRAO acima.
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
        "solicitacoes_material.entregar", "solicitacoes_material.cadastrar_catalogo",
        # Fase 81 — Estoque é quem fisicamente separa um pedido de venda,
        # então é quem aponta a etapa "Separação" no painel.
        "fluxo.apontar",
        # Fase 86 — quem separa/expede fisicamente também é quem costuma
        # lidar com a transportadora na doca de carregamento.
        "comercial.gerenciar_coleta",
    ]),
    ("Compras", "Compras e homologação de fornecedores", 1, [
        "itens.visualizar", "fornecedores.visualizar", "fornecedores.cadastrar",
        # Quem recebe a NF do fornecedor lança a conta a pagar correspondente.
        "financeiro.visualizar", "financeiro.criar_conta_pagar", "empresas.visualizar",
        # Fase 39 (MRP) — o relatório de necessidade de materiais É a ponte
        # entre PCP e Compras — sem ver o relatório, Compras não teria como
        # saber o que precisa comprar antes que o PCP tente liberar a ordem
        # e seja recusado por falta de saldo. Fase 105 — "aps.visualizar" é
        # exatamente essa fatia (Agenda/MRP/Sugestões), sem conceder de
        # brinde a visão geral de Ordens de Produção que Compras nunca
        # precisou de fato (era um efeito colateral de reaproveitar
        # "producao.visualizar" até aqui).
        "aps.visualizar",
        # Fase 54 — o mesmo perfil que vê a necessidade calculada pelo MRP
        # é quem gera as sugestões de compra a partir dela e decide o que
        # fazer com cada uma (atender, linkando a conta a pagar real
        # lançada logo acima, ou descartar).
        "aps.gerar_sugestao_compra", "aps.decidir_sugestao_compra",
        # Fase 58 — mesmo perfil que decide as sugestões é quem formaliza o
        # Pedido de Compra (a partir de uma sugestão ou manualmente), envia
        # ao fornecedor e pode cancelar enquanto não houver recebimento.
        "compras.visualizar", "compras.criar_pedido", "compras.enviar_pedido", "compras.cancelar_pedido",
        # Fase 61 — ver a nota de escopo acima: segregação por usuário,
        # verificada no código, não por perfil separado.
        "compras.aprovar_pedido_grande",
        # Fase 66 — mesmo perfil que já formaliza o Pedido de Compra manual
        # ganha o ciclo completo da cotação comparativa: montar, registrar
        # as respostas recebidas e fechar escolhendo o vencedor.
        "compras.criar_cotacao", "compras.registrar_resposta_cotacao", "compras.fechar_cotacao",
        "compras.cancelar_cotacao",
        # Fase 78 — mesmo perfil que já lida com o fornecedor e a NF de
        # compra (para lançar a conta a pagar, acima) lança também os dados
        # fiscais da nota — "fiscal.cancelar" fica de propósito fora daqui,
        # mesma régua do resto do módulo (ação mais arriscada, só
        # Administrador).
        "fiscal.visualizar", "fiscal.registrar_entrada",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
        # Fase 123 — mesmo perfil que já lança a NF de compra manualmente
        # (fiscal.registrar_entrada, acima) ganha também o recebimento
        # automatizado via XML: conferir e importar. "lotes.receber" já
        # concedido em outro lugar deste mesmo perfil? Não é necessário —
        # a importação de NF-e gera o lote por dentro (nfe_entrada.importar),
        # sem precisar da permissão separada de recebimento manual de lote.
        "nfe_entrada.visualizar", "nfe_entrada.conferir", "nfe_entrada.importar",
        "nfe_entrada.importar_com_divergencia",
    ]),
    ("Comercial", "CRM e força de vendas interna", 1, [
        "itens.visualizar", "estoque.visualizar", "comercial.visualizar", "comercial.cadastrar_cliente",
        "comercial.criar_pedido", "comercial.confirmar_pedido", "comercial.cancelar_pedido", "empresas.visualizar",
        "financeiro.visualizar",
        # Fase 63 — ver a nota de escopo acima: segregação por usuário,
        # verificada no código, não por perfil separado.
        "comercial.aprovar_pedido_acima_limite_credito",
        # Fase 70 — mesmo perfil que já cuida do ciclo do pedido (criar,
        # confirmar) ganha a emissão da NF-e depois que o Estoque expede —
        # "fiscal.configurar" (token do provedor) e "fiscal.cancelar" (mais
        # arriscada) ficam de propósito fora daqui, só no Administrador.
        "fiscal.visualizar", "fiscal.emitir",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
        # Fase 81 — Comercial também pode apontar etapas manuais do fluxo
        # (ex.: confirmar que a Separação de um pedido foi concluída).
        "fluxo.apontar",
        # Fase 86 — mesmo perfil que já expede o pedido cuida de agendar e
        # confirmar a coleta pela transportadora.
        "comercial.gerenciar_coleta",
        # Fase 99 — mesmo perfil que monta o pedido decide os preços
        # praticados por tabela.
        "tabelas_preco.visualizar", "tabelas_preco.gerenciar",
    ]),
    ("Vendedor", "Uso do aplicativo de vendas em campo", 1, [
        "itens.visualizar", "comercial.visualizar", "comercial.criar_pedido",
        # Fase 103 — cadastrar cliente novo direto em campo (com documento
        # obrigatório, ver POST /vendas-app/clientes) usa a MESMA permissão
        # já usada pela tela desktop de Comercial para cadastrar/editar
        # cliente — nenhuma permissão nova, para não duplicar a régua de
        # quem pode cadastrar cliente.
        "comercial.cadastrar_cliente",
        # Fase 99 — só visualizar: usa o preço pré-preenchido da tabela do
        # cliente, mas não decide os preços praticados (isso é do
        # Comercial/Administrador).
        "tabelas_preco.visualizar",
        # Fase 36 — o próprio aplicativo de vendas (catálogo, rascunho com
        # reserva temporária, verba, envio e "minhas comissões").
        # Deliberadamente SEM "comercial.configurar_comercial": mudar a
        # régua de percentuais/expiração é decisão de administrador, não
        # do vendedor que usa o app no dia a dia.
        "vendas_app.usar", "vendas_app.enviar_pedido",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
    ]),
    # Deliberadamente SEM financeiro.criar_conta_pagar: quem lança a conta
    # (Compras, ao receber a NF) e quem autoriza o pagamento dela
    # (Financeiro) são pessoas diferentes — a mesma segregação de função já
    # usada em Comercial (quem confirma o pedido não é necessariamente quem
    # expede) e em Qualidade (quem analisa não aprova o próprio lote).
    ("Financeiro", "Faturamento e financeiro", 1, [
        "comercial.visualizar", "itens.visualizar", "fornecedores.visualizar", "empresas.visualizar",
        "financeiro.visualizar",
        "financeiro.registrar_baixa_pagar", "financeiro.cancelar_conta_pagar",
        "financeiro.registrar_baixa_receber", "financeiro.cancelar_conta_receber",
        # Fase 14 — o mesmo perfil que registra pagamentos/recebimentos
        # também pode corrigi-los via estorno (perfil pequeno, sem
        # separação adicional de função aqui — ver nota em seed.py sobre
        # as permissões serem próprias mesmo assim, para instalações que
        # queiram restringir depois via perfil customizado).
        "financeiro.estornar_baixa_receber", "financeiro.estornar_baixa_pagar",
        # Fase 22 — mesma observação: perfil pequeno, sem separação
        # adicional de PERFIL aqui (a segregação real é por USUÁRIO — quem
        # solicita o estorno não pode ser quem aprova, verificado no
        # próprio código, não só pela permissão).
        "financeiro.aprovar_estorno_receber", "financeiro.aprovar_estorno_pagar",
        # Fase 31 — mesma observação da Fase 22: perfil pequeno, sem
        # separação adicional de PERFIL aqui (a segregação real é por
        # USUÁRIO — quem solicita o registro de uma baixa grande não pode
        # ser quem aprova, verificado no próprio código).
        "financeiro.aprovar_baixa_receber", "financeiro.aprovar_baixa_pagar",
        # Fase 83 — a confirmação de um pedido de venda agora exige
        # aprovação financeira obrigatória (antes só quando ultrapassava o
        # limite de crédito do cliente); o perfil Financeiro, que já
        # aprova baixas e estornos acima, é quem faz sentido decidir isso
        # de verdade — Comercial mantém a mesma permissão (perfil já
        # existente desde a Fase 63) para instalações pequenas onde não há
        # um Financeiro separado; a segregação real continua por USUÁRIO
        # (quem solicitou não pode aprovar), não por perfil.
        "comercial.aprovar_pedido_acima_limite_credito",
        # Fase 13 — quem cuida do financeiro é quem faz sentido ver quanto
        # a produção realmente custa (preço pago a fornecedor), mesmo sem
        # ter producao.visualizar (a tela "Custo do Produto" é independente
        # da tela operacional de Ordens de Produção — mesma segregação já
        # usada para relatorios.visualizar/Diretoria desde a Fase 7).
        "custeio.visualizar",
        # Fase 40 — quem já lança/baixa contas é quem faz sentido também
        # importar o extrato do banco e conciliar as transações contra
        # elas.
        "financeiro.conciliar_extrato",
        # Fase 71 — mesmo perfil que já registra/baixa contas a receber
        # ganha a emissão de boleto contra elas; "configurar_boleto" (token
        # do provedor) fica de propósito fora daqui, só no Administrador,
        # mesma régua da Fase 70 para "fiscal.configurar".
        "financeiro.gerar_boleto", "financeiro.cancelar_boleto",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
    ]),
    # Visão executiva agregada, deliberadamente SEM nenhuma permissão
    # operacional de módulo (não vê a lista de clientes, não vê lotes
    # individuais etc.) — só os números consolidados do painel. Mostra que
    # `relatorios.visualizar` é uma permissão independente das
    # `*.visualizar` de cada módulo, não uma soma delas.
    ("Diretoria", "Visão executiva agregada (painel gerencial)", 1, [
        "relatorios.visualizar",
        # Visão executiva do histórico de recalls (só leitura — quem decide
        # e registra uma simulação de recall é a Qualidade, acima).
        "rastreabilidade.visualizar",
        # Fase 13 — visão executiva de custo de produção, mesma lógica de
        # "número agregado, sem acesso operacional" já usada acima.
        "custeio.visualizar",
    ]),
    # Fase 24 — perfil novo para quem cuida do Memorial Técnico ANVISA
    # (tipicamente o Responsável Técnico e/ou Controle de Qualidade
    # regulatório). Deliberadamente com TODAS as permissões do módulo
    # (inclusive excluir/assinar) num único perfil por enquanto — o sistema
    # original tinha papéis mais granulares (responsavel-tecnico,
    # controle-qualidade, tecnico-lab, analista, visualizador); dividir
    # dessa forma aqui fica para quando o cliente pedir, um administrador
    # já pode criar perfis customizados com um subconjunto dessas
    # permissões a qualquer momento pela tela de Perfis.
    ("Regulatório", "Memorial Técnico ANVISA (empresas, produtos, memoriais)", 1, [
        "memorial_empresas.visualizar", "memorial_empresas.cadastrar", "memorial_empresas.editar",
        "memorial_produtos.visualizar", "memorial_produtos.cadastrar", "memorial_produtos.editar",
        "memoriais.visualizar", "memoriais.cadastrar", "memoriais.editar",
        "memoriais.concluir", "memoriais.assinar", "memoriais.excluir",
        # Fase 26 — o mesmo perfil que monta o memorial é quem mantém os
        # catálogos de apoio que alimentam os seletores usados nele.
        "memorial_catalogos.visualizar", "memorial_catalogos.cadastrar",
        "memorial_catalogos.editar", "memorial_catalogos.excluir",
        # Fase 27 — mesmo perfil também cuida da padronização de rótulo
        # (anexos já estão cobertos por memoriais.editar, acima).
        "memoriais.padronizar",
        "solicitacoes_material.visualizar", "solicitacoes_material.solicitar",
    ]),
]


def _gerar_senha_forte(tamanho=16):
    # Alfabeto pensado para uma pessoa conseguir digitar ou copiar sem
    # erro, a partir de relatos reais de instalação: sem "0"/"O" nem
    # "1"/"l"/"I" (fáceis de confundir numa fonte de console), e só um
    # punhado de símbolos bem distintos entre si — antes o alfabeto
    # incluía caracteres como "^", "%", "&", "(", ")", que geravam senhas
    # visualmente mais difíceis de conferir letra por letra. Continua
    # forte o bastante para uma senha de uso único, forçada a trocar no
    # primeiro login (`senha_deve_trocar=1`, ver abaixo): com esses ~64
    # caracteres possíveis e 16 posições, ainda são ~2^96 combinações —
    # muito acima do necessário para resistir a qualquer tentativa de
    # adivinhação nesse curtíssimo intervalo de vida da senha.
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789@#$-_"
    while True:
        senha = "".join(secrets.choice(alfabeto) for _ in range(tamanho))
        if not security.validar_politica_senha(senha):
            return senha


def rodar_seed(conn=None, admin_email=None, admin_senha=None, imprimir=True):
    proprio_conn = conn is None
    if proprio_conn:
        conn = db_module._connect()

    ids_permissao = {}
    for modulo, acao, descricao, exige_dupla in PERMISSOES_PADRAO:
        existente = conn.execute(
            "SELECT id FROM permissoes WHERE modulo = ? AND acao = ?", (modulo, acao)
        ).fetchone()
        if existente:
            ids_permissao[(modulo, acao)] = existente["id"]
            continue
        cur = conn.execute(
            "INSERT INTO permissoes (modulo, acao, descricao, exige_dupla_aprovacao) VALUES (?, ?, ?, ?)",
            (modulo, acao, descricao, exige_dupla),
        )
        ids_permissao[(modulo, acao)] = cur.lastrowid

    ids_perfil = {}
    for nome, descricao, editavel, permissoes_alvo in PERFIS_PADRAO:
        existente = conn.execute("SELECT id FROM perfis WHERE nome = ?", (nome,)).fetchone()
        if existente:
            perfil_id = existente["id"]
        else:
            cur = conn.execute(
                "INSERT INTO perfis (nome, descricao, editavel) VALUES (?, ?, ?)",
                (nome, descricao, editavel),
            )
            perfil_id = cur.lastrowid
        ids_perfil[nome] = perfil_id

        if permissoes_alvo == "TODAS":
            alvo_ids = list(ids_permissao.values())
        else:
            alvo_ids = [ids_permissao[tuple(p.split("."))] for p in permissoes_alvo]

        for permissao_id in alvo_ids:
            ja_tem = conn.execute(
                "SELECT 1 FROM perfil_permissao WHERE perfil_id = ? AND permissao_id = ?",
                (perfil_id, permissao_id),
            ).fetchone()
            if not ja_tem:
                conn.execute(
                    "INSERT INTO perfil_permissao (perfil_id, permissao_id) VALUES (?, ?)",
                    (perfil_id, permissao_id),
                )

    # Fase 92 — liga exige_2fa para os perfis da lista acima. Sempre
    # reafirmado no re-seed (idempotente); nunca desliga um perfil que um
    # administrador tenha ligado manualmente para outro perfil além destes
    # dois (por isso é um UPDATE ... SET 1 ..., nunca um "resetar todos
    # para 0 antes").
    for nome_perfil in PERFIS_QUE_EXIGEM_2FA:
        if nome_perfil in ids_perfil:
            conn.execute("UPDATE perfis SET exige_2fa = 1 WHERE id = ?", (ids_perfil[nome_perfil],))

    email = (admin_email or os.environ.get("ALPHAFITUS_ADMIN_EMAIL") or "admin@alphafitus.com.br").strip().lower()
    ja_existe_admin = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()

    senha_gerada = None
    if not ja_existe_admin:
        senha_informada = admin_senha or os.environ.get("ALPHAFITUS_ADMIN_SENHA")
        senha = senha_informada
        if not senha:
            senha = _gerar_senha_forte()
            senha_gerada = senha
        senha_hash = security.hash_password(senha)
        # Uma senha ALEATÓRIA gerada aqui (não escolhida por ninguém)
        # sempre força troca no primeiro login (senha_deve_trocar=1) — é
        # só uma senha de uso único para destravar o primeiro acesso. Já
        # uma senha INFORMADA de propósito (ex.: definida na tela do
        # instalador) é a senha real que a pessoa escolheu usar — fica
        # valendo até quem usa decidir trocar por conta própria, sem essa
        # troca forçada logo de cara.
        deve_trocar = 0 if senha_informada else 1
        cur = conn.execute(
            "INSERT INTO usuarios (nome, email, senha_hash, senha_deve_trocar) VALUES (?, ?, ?, ?)",
            ("Administrador Inicial", email, senha_hash, deve_trocar),
        )
        admin_id = cur.lastrowid
        conn.execute(
            "INSERT INTO usuario_perfil (usuario_id, perfil_id) VALUES (?, ?)",
            (admin_id, ids_perfil["Administrador"]),
        )
        audit.registrar(conn, tabela="usuarios", registro_id=admin_id, usuario_id=None,
                         acao="usuario_admin_inicial_criado_pelo_seed", motivo="seed.py")

    conn.commit()
    if proprio_conn:
        conn.close()

    if imprimir and senha_gerada:
        print("=" * 70)
        print("USUÁRIO ADMINISTRADOR INICIAL CRIADO")
        print(f"  email: {email}")
        print(f"  senha: {senha_gerada}")
        print("Guarde esta senha agora — ela não pode ser recuperada depois.")
        print("No primeiro login o sistema vai exigir a troca dessa senha.")
        print("=" * 70)

    return {"admin_email": email, "senha_gerada": senha_gerada}


if __name__ == "__main__":
    if not os.environ.get("ALPHAFITUS_DB_PATH") and not os.path.exists(db_module.get_db_path()):
        db_module.init_db()
    rodar_seed()
