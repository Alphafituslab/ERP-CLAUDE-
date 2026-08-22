# Alphafitus OS — Fase 1 (Fundação) + Fase 2 (Qualidade) + Fase 3 (Produção) + Fase 4 (Estoque) + Fase 5 (Comercial) + Fase 6 (Financeiro) + Fase 7 (Painel Gerencial / BI) + Fase 8 (Rastreabilidade Avançada / Recall) + Fase 9 (Perdas/Refugo na Produção) + Fase 10 (Certificado de Análise em PDF) + Fase 11 (Relatório de Recall em PDF) + Fase 12 (Reserva Real de Material entre Módulos) + Fase 13 (Custeio de Produção) + Fase 14 (Estorno de Baixa) + Fase 15 (Fluxo de Caixa Projetado) + Fase 16 (Bloqueio em Massa por Recall) + Fase 17 (Contagem de Inventário Cíclico/Geral) + Fase 18 (Painel Gerencial em PDF) + Fase 19 (Painel Gerencial em CSV) + Fase 20 (DRE Simplificado) + Fase 21 (Aprovação de 2º Usuário para Ajuste de Contagem com Divergência Grande) + Fase 22 (Aprovação Dupla para Estorno de Baixa Acima de um Valor de Alçada) + Fase 23 (Geração Automática de Código de Item) + Fase 24 (Memorial Técnico ANVISA — Fundação, com visual fiel ao sistema original) + Fase 25 (APS — Sequenciamento e Capacidade Finita — Fundação) + Fase 26 (Catálogos do Memorial Técnico ANVISA) + Fase 27 (Memorial Técnico ANVISA — Anexos, Padronização de Rótulo e tela de edição em abas numeradas) + Fase 28 (APS — Agenda Visual/Gantt) + Fase 29 (Memorial Técnico ANVISA — Catálogos como Seletores) + Fase 30 (Custo de Mão de Obra e Overhead na Produção) + Fase 31 (Aprovação Dupla para o Registro de Baixa Acima de um Valor de Alçada) + Fase 32 (Limiar de Divergência de Contagem Configurável pela Tela) + Fase 33 (Limite de Prazo para Estorno de Baixa Configurável pela Tela) + Fase 34 (Alçada por Valor Monetário do Ajuste de Contagem) + Fase 35 (Agendamento/Cadência Automática de Contagens Cíclicas) + Fase 36 (App de Vendas para Vendedores — Reserva Temporária, Verbas Comerciais e Comissão) + Fase 37 (Notificações do Sistema com Envio Real por E-mail) + Fase 38 (Responsividade e App Instalável para Celular/Tablet) + Fase 39 (APS — MRP: Cálculo de Necessidade de Materiais) + Fase 40 (Conciliação Bancária — Importação de Extrato OFX) + Fase 41 (DRE Completo — Despesas Operacionais e Impostos sobre Vendas) + Fase 42 (Painel Gerencial — Filtro por Período) + Fase 43 (Memorial Técnico ANVISA — Exportar "PDF Completo") + Fase 44 (Memorial Técnico ANVISA — Administração: Usuários Online) + Fase 45 (Painel Gerencial — Exportar em XLSX) + Fase 46 (Memorial Técnico ANVISA — Administração: Snapshots & Restauração) + Fase 47 (Memorial Técnico ANVISA — Administração: Backups do Sistema) + Fase 48 (Memorial Técnico ANVISA — Administração: Gerenciar Usuários) + Fase 49 (Memorial Técnico ANVISA — Administração: Configurações) + Fase 50 (Apontamento de Perda/Refugo por ETAPA do Processo) + Fase 51 (Menu Lateral Agrupado por Módulo) + Fase 52 (Painel Gerencial — Filtro por Empresa) + Fase 53 (Recall — Decisão sobre Pedidos Já Expedidos) + Fase 54 (MRP — Sugestão Automática de Compra) + Fase 55 (Conciliação Bancária — Processamento em Lote e Janela de Dias Configurável) + Fase 56 (DRE — Impostos Detalhados: PIS/COFINS/ICMS/ISS) + Fase 57 (MRP — Lead Time de Compra do Fornecedor)

Backend **e frontend web** das trinta e nove primeiras fases do sistema:

- **Fase 1 — Fundação:** usuários, perfis, permissões granulares,
  autenticação (senha + 2FA), sessões revogáveis e trilha de auditoria
  imutável.
- **Fase 2 — Qualidade e Laboratório (LIMS/QMS):** cadastro de itens
  (matérias-primas, embalagens etc.), fornecedores e sua homologação por
  item, recebimento de lote com entrada automática em quarentena,
  solicitação e registro de análises de laboratório (com histórico
  imutável de correções), conclusão de análise, aprovação/reprovação de
  lote com segregação de função (quem concluiu a análise não pode aprovar
  o mesmo lote), emissão de Certificado de Análise (CoA), bloqueio/
  desbloqueio de lote a qualquer momento, e abertura/tratamento/
  encerramento de desvios (CAPA).
- **Fase 3 — Produção, PCP e MES básico:** fórmulas (ficha técnica/BOM)
  com versionamento — só existe uma versão **ativa** por produto, e ativar
  uma nova torna a anterior obsoleta automaticamente; ordens de produção
  (planejar → liberar → registrar consumo → concluir → cancelar); cada
  ordem só pode consumir lotes **já aprovados** pela Qualidade (nunca em
  quarentena, reprovados ou bloqueados) e nunca além da quantidade
  realmente disponível; ao concluir, a ordem gera um novo lote — que nasce
  em quarentena e passa pelo **mesmo fluxo de qualidade da Fase 2** antes
  de poder ser usado ou vendido; e uma tela de **genealogia de lote** nos
  dois sentidos (de que lotes um produto foi feito, e em que lotes/ordens
  um lote foi consumido), navegável direto na tela de detalhe do lote.
- **Fase 4 — Estoque (WMS básico):** fecha o elo físico da rastreabilidade
  que faltava desde a Fase 3 — até ali sabíamos a genealogia lógica de um
  lote (de que lote foi feito, em que foi consumido), mas não onde ele
  estava fisicamente no armazém. Esta fase adiciona posições de
  armazenagem (vinculadas a um depósito cadastrado em Empresas) e um
  livro-razão (ledger) **append-only** de movimentações — cada saldo é
  sempre recalculado a partir da soma das movimentações, nunca um campo
  guardado à parte que poderia dessincronizar (o mesmo princípio já usado
  na Fase 3 para "quantidade disponível" de produção). Cobre: endereçar um
  lote aprovado pela primeira vez a uma posição; transferir estoque entre
  posições (duas linhas ligadas por um token compartilhado, nunca uma
  editando a outra, porque o ledger não permite UPDATE); ajuste de
  inventário e baixa/descarte, ambos com **motivo obrigatório** e sujeitos
  a dupla aprovação (`exige_dupla_aprovacao`); e sugestão de separação
  **FEFO** (primeiro a vencer, primeiro a sair) para um item e quantidade
  informados.
- **Fase 5 — Comercial (CRM básico) + Pedidos de Venda:** fecha o ciclo
  entre o estoque físico endereçado na Fase 4 e uma venda de verdade.
  Cadastro simples de clientes (CNPJ único, ativo/inativo); pedido de
  venda criado como **rascunho** (pode adicionar/remover itens
  livremente, só vende itens do tipo `produto_acabado`); ao
  **confirmar**, o sistema aloca estoque de verdade pelo critério FEFO —
  não é mais só uma sugestão como na Fase 4, é uma **reserva real**, que
  impede duas vendas concorrentes de reservar o mesmo saldo físico (a
  reserva é um registro **append-only**: "liberar" uma reserva ao
  cancelar um pedido não apaga nem edita nada, só para de contar porque o
  pedido pai mudou de status); se o saldo não for suficiente para todos
  os itens, a confirmação inteira falha e nenhuma reserva é feita (nunca
  fica um pedido "confirmado pela metade"); ao **expedir**, o sistema
  revalida o saldo físico atual (algo pode ter mudado entre confirmar e
  expedir, ex. um ajuste manual no Estoque) e só então gera a saída real
  no ledger de movimentações da Fase 4; e **cancelar** um pedido em
  rascunho ou confirmado (com motivo obrigatório) — cancelar um
  confirmado libera a reserva automaticamente para outros pedidos.
  Segregação de função entre quem confirma (perfil Comercial) e quem
  expede (perfil Estoque).
- **Fase 6 — Financeiro básico (Contas a Receber e a Pagar):** fecha o
  ciclo financeiro em volta do que as Fases 2 e 5 já fazem fisicamente. Todo
  item de pedido de venda passa a ter **preço unitário** (novidade desta
  fase); ao **expedir** um pedido (Fase 5), o sistema gera **automaticamente**
  uma conta a receber, com valor congelado a partir de `quantidade *
  preco_unitario` de cada item **no momento da expedição** (mudar o preço
  depois, na tela de Itens, não altera contas já geradas — mesma filosofia
  de "composição congelada" já usada em `pedido_venda_itens` e
  `formula_itens`). Contas a pagar, ao contrário, são lançadas
  **manualmente** contra um fornecedor (uma nota fiscal de compra raramente
  corresponde 1:1 a um único lote recebido — pode cobrir vários itens, frete,
  impostos etc.), com um vínculo **opcional** a um lote recebido, só para
  rastreabilidade. As baixas (recebimentos/pagamentos) contra uma conta são
  um ledger **append-only** (mesmo princípio da Fase 4/5): o saldo em
  aberto de uma conta é sempre `valor_total - SUM(baixas)`, nunca um campo
  guardado à parte — só o status (`aberto` / `pago_parcial` / `pago` /
  `cancelado`) é armazenado e recalculado a cada baixa, porque `cancelado`
  é um estado explícito que não dá para derivar só da soma. Segregação de
  função entre quem lança a conta a pagar (perfil Compras, ao receber a NF
  do fornecedor) e quem autoriza o pagamento dela (perfil Financeiro) — a
  mesma pessoa não faz as duas coisas.
- **Fase 7 — Painel Gerencial (BI básico):** um único endpoint (e uma única
  tela) somente-leitura que agrega indicadores das seis fases anteriores —
  Produção, Qualidade, Estoque, Comercial e Financeiro — num só lugar, para
  quem precisa de visão executiva sem navegar tela por tela. Não existe
  nenhuma tabela nova nesta fase: é 100% `SELECT`/agregação sobre as
  tabelas que já existem desde a Fase 1, recalculada a cada chamada a
  partir das mesmas fontes de verdade que as telas operacionais já usam
  (ex.: saldo de estoque = soma de `movimentacoes_estoque`, saldo de conta
  = `valor_total - SUM(baixas)`) — nunca um valor pré-calculado e guardado
  à parte que poderia dessincronizar. A permissão `relatorios.visualizar` é
  deliberadamente **independente** das permissões `*.visualizar` de cada
  módulo (não é a união delas) — demonstrado pelo novo perfil "Diretoria",
  que só tem essa permissão e consegue ver o painel agregado sem conseguir
  abrir nenhuma tela operacional individual.
- **Fase 8 — Rastreabilidade Avançada / Simulação de Recall:** fecha o
  requisito de rastreabilidade total exigido pelas boas práticas de
  fabricação (GMP) — dado qualquer lote, responder em minutos "de onde veio
  o material dele" (matérias-primas e fornecedores, atravessando quantos
  níveis de produção intermediária forem necessários — matéria-prima →
  produto intermediário → produto acabado, por exemplo) e "para onde ele
  foi" (outros lotes produzidos a partir dele e, no fim da cadeia, quais
  pedidos e clientes o receberam). O traversal é **recursivo** sobre as
  mesmas tabelas de ledger já existentes desde as Fases 3 e 5
  (`ordem_producao_consumo` e `pedido_venda_reservas`) — nenhuma tabela
  nova é necessária para calculá-lo, e o resultado nunca é guardado como um
  valor derivado que poderia dessincronizar (mesmo princípio de todas as
  fases anteriores). A única tabela nova desta fase é
  `simulacoes_recall`: um registro **imutável** (append-only, como a
  auditoria e o Certificado de Análise) de que uma investigação foi
  executada — motivo obrigatório, e um snapshot completo do resultado no
  momento em que a Qualidade decidiu investigar, porque um recall é uma
  decisão de conformidade documentada num ponto do tempo (para auditoria
  externa, ANVISA etc.), não um saldo que deveria sempre refletir o estado
  atual do banco. Segregação de função: a Qualidade decide e registra uma
  simulação de recall; a Diretoria tem visão executiva completa (vê a
  genealogia e o histórico) mas não o botão de registrar uma nova
  investigação — a mesma independência de permissão `*.visualizar` já
  demonstrada na Fase 7.
- **Fase 9 — Apontamento de Perdas/Refugo na Produção:** fecha uma lacuna
  que já estava documentada desde a Fase 3 ("O que ainda falta") — até
  aqui, concluir uma ordem de produção só registrava a quantidade
  **produzida**, sem nenhum jeito de o sistema saber se a diferença entre
  o planejado e o produzido foi perda de processo real (evaporação, ajuste
  de umidade, quebra de comprimido etc.) ou simplesmente ninguém apontou.
  Esta fase é **100% aditiva**: o mesmo endpoint de sempre
  (`POST /producao/ordens/<id>/concluir`) ganha dois campos **opcionais** —
  `quantidade_perda` (default 0, nunca negativa) e `motivo_perda`
  (obrigatório só quando há perda maior que zero) — sem quebrar nenhum
  chamador que continue concluindo ordens do jeito antigo. Nenhuma tabela
  nova, nenhuma permissão nova: só duas colunas a mais em
  `ordens_producao` e a mesma permissão `producao.apontar` que já protegia
  a conclusão desde a Fase 3 (apontar perda é parte do mesmo ato de
  concluir a ordem, não uma ação separada). A tela de detalhe da ordem
  passa a mostrar, depois de concluída, um cartão com o percentual de
  perda (`perda / (produzido + perda)`) e o percentual de rendimento sobre
  o planejado (`produzido / planejado`) — ambos calculados na hora a
  partir das colunas gravadas, nunca armazenados, mesmo princípio de saldo
  "sempre recalculado" já usado em todas as fases anteriores.
- **Fase 10 — Certificado de Análise (CoA) em PDF:** o CoA já existia desde
  a Fase 2 como um registro estruturado no banco (`certificados_analise`),
  exibido na tela — mas faltava o formato que o mercado espera de verdade
  para anexar a uma nota fiscal ou enviar a um cliente: um documento PDF.
  Esta fase é **puramente um export**: a nova rota
  `GET /lotes/<id>/certificado-analise/pdf` monta um PDF (cabeçalho, dados
  do lote/item, origem — fornecedor **ou** ordem de produção, nunca as
  duas —, tabela de ensaios/resultados com especificação e conclusão,
  quem aprovou e quando) a partir exatamente dos mesmos dados que a tela
  já mostra, sem gravar nada de negócio novo no banco — só um evento de
  auditoria (`coa_pdf_gerado`) registrando quem baixou o PDF e quando,
  para rastreabilidade de quem já teve acesso a um certificado específico.
  Não existe permissão nova: quem já pode **ver** o CoA na tela
  (`lotes.visualizar`) já pode baixar o PDF dele — é a mesma informação,
  só formatada diferente. Baixar o PDF é idempotente: gerar duas vezes
  seguidas não cria um novo certificado nem muda o status do lote.
- **Fase 11 — Relatório de Recall em PDF:** mesmo padrão da Fase 10,
  aplicado ao snapshot imutável que a Fase 8 já grava em
  `simulacoes_recall` — a nova rota
  `GET /rastreabilidade/recalls/<id>/pdf` formata em PDF o que já está
  gravado (número da simulação, lote investigado, motivo, resumo do
  impacto, lista de pedidos já expedidos afetados com cliente e CNPJ —
  para saber exatamente quem notificar —, e as listas achatadas de lotes
  de origem/upstream e derivados/downstream), sem recalcular nem alterar
  nada: é o mesmo princípio de "o relatório reflete o que se sabia no
  momento da investigação, não o estado atual do banco" que já rege a
  própria tabela `simulacoes_recall` desde a Fase 8. Também **puramente
  um export**, sem tabela nova e sem permissão nova — quem já pode ver o
  detalhe de uma simulação (`rastreabilidade.visualizar`, a mesma que o
  perfil Diretoria tem desde a Fase 7/8) já pode baixar o PDF dela, o que
  o teste automatizado prova explicitamente criando um usuário Diretoria
  do zero e baixando o relatório sem tocar em nenhuma outra permissão. Só
  um evento de auditoria a mais (`recall_pdf_gerado`) por download, e
  gerar o PDF várias vezes não altera a simulação nem nenhum outro dado.
- **Fase 12 — Reserva Real de Material entre Módulos:** fecha uma lacuna
  documentada desde a Fase 3/5 — até aqui, três lugares diferentes podiam
  comprometer o **mesmo lote** sem nenhum saber da existência do outro:
  Produção só olhava para o que já tinha sido fisicamente consumido
  (`ordem_producao_consumo`), Comercial só olhava para o saldo físico
  endereçado menos as próprias reservas de venda, e duas ordens de
  produção liberadas ao mesmo tempo competiam pelo mesmo saldo até a
  primeira delas apontar consumo de verdade. Esta fase resolve os três
  problemas de uma vez com uma única mudança de arquitetura: `liberar()`
  agora **reserva de verdade** (por FEFO, lote a lote) o material da
  composição (BOM) no momento da liberação — se não houver saldo real
  suficiente, a liberação é recusada com uma mensagem explicando
  exatamente o que falta, em vez de deixar a ordem avançar e descobrir a
  falta só na hora de registrar o consumo. E a disponibilidade usada por
  **Produção**, **Comercial** (alocação FEFO de venda) e pela sugestão de
  FEFO do **Estoque** passa a vir de uma função só,
  `saldo_real_disponivel_producao()` (em `app/routes/estoque.py`), que
  soma de uma vez: consumo já apontado (qualquer ordem), reserva de venda
  confirmada (Comercial, em qualquer posição), reserva de produção de
  outra ordem liberada/em produção, e saída líquida de baixa/ajuste de
  estoque. Na prática isso significa: uma ordem de produção não consegue
  mais reservar um lote que o Comercial já vendeu (pedido confirmado); o
  Comercial não consegue mais confirmar uma venda que uma ordem de
  produção já reservou; e duas ordens liberadas em sequência disputam o
  mesmo saldo real, não um saldo "otimista" que ignora a outra. A reserva
  fica registrada numa tabela nova e **append-only**
  (`ordem_producao_reservas`, mesmo princípio de "nunca UPDATE/DELETE, só
  INSERT" já usado no ledger de estoque desde a Fase 4), visível na tela
  de detalhe da ordem numa seção própria ("Material reservado — garantido
  via FEFO ao liberar"), e liberada automaticamente (deixa de contar) se
  a ordem for cancelada. Não existe permissão nova: continua sendo só
  `producao.liberar`, a mesma de sempre — o teste automatizado prova isso
  liberando uma ordem com o perfil PCP sem tocar em nenhuma permissão
  nova. Também registrado em auditoria: o evento `ordem_liberada` agora
  carrega a lista de reservas feitas, além da mudança de status.
- **Fase 13 — Custeio de Produção:** feature pedida diretamente por você,
  fora do roteiro original de 42 seções — responde "quanto custou de
  verdade esta produção, e quanto disso foi perda?". Decidimos juntos,
  antes de eu implementar, três pontos que mudam a resposta: (1) o custo
  de cada insumo vem do **custo médio real de compra**, não de um valor
  cadastrado à mão no item — por isso `lotes` ganhou um campo novo e
  opcional, `custo_unitario` (informado no recebimento, por quem já tem
  `lotes.receber` — nenhuma permissão nova para isso); (2) a fórmula
  (BOM) de cada produto já pode listar itens de embalagem — rótulo,
  tampa, sílica etc. — como insumo, exatamente como a matéria-prima
  principal (isso já era possível desde a Fase 3, sem mudança de schema,
  só faltava o custo por trás); (3) a visão de custo vive em dois
  lugares: dentro do detalhe de cada Ordem de Produção (duas abas —
  "Custo de Produção" e "Custo com Perdas" — logo abaixo do cartão de
  Perda/Refugo da Fase 9) e numa tela nova, agregada, "Custo do Produto"
  (aba 1: custo padrão **projetado** de cada fórmula ativa a partir do
  custo médio de compra atual; aba 2, no detalhe de cada produto:
  histórico real de custo de perda das últimas ordens já concluídas,
  ordem por ordem — deliberadamente não resume num único número
  "esperado", para não sugerir uma precisão que os dados não têm). Toda a
  matemática é **100% derivada em tempo real** a partir de dados que já
  existiam (`ordem_producao_consumo` da Fase 3, `quantidade_perda`/
  `quantidade_produzida` da Fase 9), o mesmo princípio de "nunca guardar
  um número calculado que poderia dessincronizar" usado em toda fase
  anterior — nenhuma tabela nova de "custo calculado" foi criada. Quando
  um lote consumido não tem custo informado, o motor cai para a **média
  ponderada** de custo do item entre os lotes que têm custo (nunca trata
  a ausência como zero, o que subestimaria o custo real) e, se nem isso
  existir, marca a resposta como `custo_incompleto` de forma visível — em
  vez de mostrar um número que parece exato mas não é. A alocação do
  custo da perda entre os insumos é **proporcional** ao percentual de
  perda já calculado pela Fase 9 (documentado como uma simplificação
  deliberada: não tenta adivinhar em que etapa do processo a perda
  ocorreu — se ela acontece antes de embalar, por exemplo, o custo real
  de rótulo/tampa perdido pode ser menor do que esta alocação sugere).
  Permissão nova, **`custeio.visualizar`**, deliberadamente independente
  de `producao.visualizar` — dado financeiro sensível (preço pago a
  fornecedor), mesma filosofia de segregação já usada para
  `financeiro.visualizar` (Fase 6) e `relatorios.visualizar` (Fase 7): só
  Financeiro, Diretoria e Administrador têm por padrão; PCP/Produção
  (que operam as ordens no dia a dia) não têm, e o teste automatizado
  prova a independência nos dois sentidos — Financeiro vê custo sem
  conseguir ver a lista de ordens, PCP abre uma ordem sem ver o cartão de
  custo dentro dela.
- **Fase 14 — Estorno de Baixa:** eu mesmo escolhi este item como próximo,
  de um backlog que eu já tinha sinalizado desde a Fase 6 — as próprias
  mensagens de erro dos triggers append-only de `contas_receber_baixas`/
  `contas_pagar_baixas` já diziam "cancele/estorne com um novo lançamento
  se necessário", mas esse fluxo de estorno nunca tinha sido implementado
  (só existia o de cancelar uma conta que ainda não tinha nenhuma baixa,
  um caso bem mais simples). Agora, uma baixa lançada por engano (valor
  errado, forma de pagamento errada, lançada na conta errada) pode ser
  corrigida sem quebrar o append-only e sem apagar o histórico original:
  o estorno é sempre uma **linha nova** na mesma tabela de baixas — nunca
  um UPDATE/DELETE na linha original, que continua bloqueada pelos
  mesmos triggers desde a Fase 6 — com o **mesmo valor** da baixa
  original, marcada via uma auto-referência nova (`estorno_de_id`), mais
  um `motivo_estorno` obrigatório em código. O saldo em aberto de uma
  conta nunca é um número guardado à parte: continua sendo sempre
  recalculado a partir do ledger completo, agora como baixas normais
  **menos** estornos, o mesmo princípio de "nunca guardar um valor
  derivado" usado desde o saldo de estoque na Fase 4. Duas permissões
  novas, **`financeiro.estornar_baixa_receber`** e
  **`financeiro.estornar_baixa_pagar`**, deliberadamente separadas de
  `registrar_baixa_receber`/`registrar_baixa_pagar` — mesma segregação de
  função já usada em todo o módulo financeiro (quem lança a conta a pagar
  não é necessariamente quem paga; aqui, quem registra a baixa não é
  necessariamente quem pode desfazê-la). Uma baixa que já foi estornada
  não pode ser estornada de novo, e um estorno em si não pode ser
  estornado (o lançamento original já reflete a reversão) — ambas as
  regras cobertas por teste automatizado e pelo teste de navegador. Na
  tela Financeiro, cada conta com pelo menos uma baixa ganhou um botão
  "Ver baixas" que abre o ledger completo (baixas normais e estornos,
  cada um com seu selo visual), com o botão "Estornar" aparecendo só em
  baixas normais ainda não estornadas, e só para quem tem a permissão
  correspondente. **Correção encontrada e já corrigida antes de eu te
  entregar:** o agregador financeiro do Painel Gerencial
  (`app/routes/relatorios.py`, Fase 7) soma as baixas de
  `contas_receber`/`contas_pagar` de forma independente de
  `financeiro.py` — ao revisar essa segunda leitura, percebi que ela
  ainda não excluía as linhas de estorno novas desta fase, então um
  estorno inflaria "Recebido (total)"/"Pago (total)" e subestimaria "A
  receber em aberto"/"A pagar em aberto" no painel, mesmo com a tela
  Financeiro já mostrando os números certos. Corrigido para usar a mesma
  lógica (baixas normais menos estornos) nos dois lugares, com dois
  testes de regressão novos provando que o painel reflete um estorno
  corretamente.
- **Fase 15 — Fluxo de Caixa Projetado:** eu mesmo escolhi este item como
  próximo, direto do backlog que eu já tinha documentado desde a Fase 7:
  "o painel mostra só o saldo agregado, não uma projeção por data".
  Responde "como fica o caixa daqui a X dias, se nada mais entrar/sair
  além do que já está lançado?" agrupando o saldo em aberto de contas a
  receber (entradas previstas) e contas a pagar (saídas previstas) por
  faixa de dias até o vencimento — o mesmo "aging" de qualquer relatório
  de contas a receber/pagar: Vencido, 0 a 7 dias, 8 a 15, 16 a 30, 31 a
  60, 61 a 90 e Mais de 90 dias — com um **saldo acumulado** faixa a
  faixa. Sem tabela nova: 100% derivado a cada chamada
  (`GET /relatorios/fluxo-caixa-projetado`) a partir da mesma leitura de
  saldo em aberto que o bloco "financeiro" do dashboard da Fase 7 já usa
  — na verdade, ao construir esta fase eu extraí essa leitura para uma
  função só (`_contas_em_aberto`/`_baixado_liquido`, em
  `app/routes/relatorios.py`), reaproveitada pelos dois lugares, para a
  duplicação que causou o bug do item acima não poder se repetir. Mesma
  permissão `relatorios.visualizar` do resto do Painel Gerencial —
  nenhuma permissão nova. Na tela, o cartão novo "Fluxo de Caixa
  Projetado" aparece logo abaixo do cartão "Financeiro", com a faixa
  "Vencido" destacada visualmente quando tem algum valor.
- **Fase 16 — Bloqueio em Massa a partir de Recall:** outro item de
  backlog que eu já tinha documentado desde a própria Fase 8: "bloquear
  cada lote afetado ainda é uma ação manual, lote a lote". A simulação de
  recall já calcula exatamente quais lotes são afetados (para trás e para
  frente, atravessando quantos níveis forem necessários); esta fase só
  aplica o bloqueio já existente da Fase 2 (`lotes.bloquear`) a todos eles
  de uma vez (`POST /rastreabilidade/recalls/{id}/bloquear-em-massa`),
  reaproveitando a mesma função interna (`bloquear_lote_interno`, extraída
  de `app/routes/lotes.py` durante esta fase) tanto para o bloqueio
  individual quanto para o em massa — para nunca haver dois jeitos
  divergentes de bloquear um lote. Nenhuma tabela nova: o "quais lotes são
  afetados" já vinha do snapshot da simulação (Fase 8), e o "isso já está
  bloqueado?" é sempre recalculado na hora a partir da própria tabela
  `lotes`, nunca guardado (por isso o detalhe de uma simulação de recall
  agora também devolve `lotes_afetados_status`, o status ATUAL de cada
  lote, que pode mudar depois da simulação ter sido registrada — a árvore
  de genealogia continua sendo o snapshot congelado de sempre). Lotes já
  bloqueados de uma investigação anterior são pulados sem erro — a
  operação é seguramente repetível. Deliberadamente NÃO mexe em pedidos de
  venda já expedidos do mesmo lote: essa continua sendo uma decisão
  manual, exatamente como o backlog original já apontava ("o que fazer com
  uma reserva ainda não expedida do mesmo lote" é uma decisão de negócio
  maior, fora do escopo de só bloquear os lotes). Permissão nova e
  deliberadamente separada de `rastreabilidade.simular_recall` —
  `rastreabilidade.bloquear_em_massa` — porque investigar não deveria dar
  automaticamente o poder de bloquear em massa (mesmo padrão de
  segregação já usado em `estornar_baixa_receber/pagar` na Fase 14); o
  perfil Qualidade já sai com as duas por padrão.
- **Fase 17 — Contagem de Inventário Cíclico/Geral:** mais um item que já
  estava no backlog desde a Fase 4 — até aqui, o único jeito de corrigir
  um saldo de estoque era o ajuste manual avulso (`estoque.ajustar`), lote
  a lote, sem nenhum processo formal de conferência física. Esta fase
  adiciona duas tabelas novas e deliberadamente **mutáveis**
  (`contagens_inventario`/`contagens_inventario_itens` — ao contrário de
  `movimentacoes_estoque` e das outras tabelas realmente imutáveis do
  sistema, elas representam o estado atual de um processo em andamento,
  não um livro-razão em que cada linha é definitiva, então não têm os
  gatilhos de bloqueio de UPDATE/DELETE das tabelas append-only). Uma
  contagem pode ser **geral** (`POST /estoque/contagens` com
  `tipo=geral` já popula automaticamente todos os pares lote+posição com
  saldo positivo naquele depósito, para o caso "conferir tudo") ou
  **cíclica** (começa vazia, e os itens são adicionados um a um via
  `POST /estoque/contagens/{id}/itens`, para o caso "conferir só esta
  prateleira hoje"). Cada item guarda o `saldo_sistema_no_inicio` como
  fotografia do momento em que entrou na contagem — o que foi
  efetivamente contado fica em `quantidade_contada`, e a diferença entre
  os dois nunca é armazenada, sempre recalculada na hora
  (`saldo_sistema_no_inicio - quantidade_contada`, no mesmo espírito de
  nunca guardar um valor derivado que já rege saldo de estoque, status de
  conta e custo de produção nas fases anteriores). Ao concluir
  (`POST /estoque/contagens/{id}/concluir`), o sistema gera
  automaticamente um ajuste de estoque (o mesmo mecanismo da Fase 4) só
  nos itens onde houve divergência real — para isso, o lançamento que
  antes só existia dentro da rota `estoque.ajustar` foi extraído para uma
  função interna comum (`registrar_ajuste_interno`, em
  `app/routes/estoque.py`), reaproveitada tanto pelo ajuste manual avulso
  quanto pela conclusão de contagem, para as duas formas de ajustar
  estoque nunca poderem divergir uma da outra. Duas permissões
  deliberadamente segregadas: `estoque.contagem` (iniciar, adicionar
  item, registrar o que foi contado, cancelar — uma tarefa operacional,
  do dia a dia de quem faz a conferência física) e a já existente
  `estoque.ajustar`, reaproveitada especificamente para o passo de
  **concluir** uma contagem — porque concluir é o momento em que o
  sistema efetivamente altera saldo de estoque, exatamente a mesma ação
  sensível que o ajuste manual avulso já protegia, então faz sentido
  exigir a mesma permissão em vez de criar uma terceira; ou seja, alguém
  pode conduzir uma contagem inteira sem conseguir concluí-la sozinho, se
  não tiver `estoque.ajustar` — uma segregação de função deliberada,
  igual ao padrão já usado em `estornar_baixa_receber/pagar` (Fase 14) e
  em `rastreabilidade.bloquear_em_massa` (Fase 16). Não deixa concluir
  com itens ainda pendentes de contagem (400), e cancelar sempre exige um
  motivo, sem gerar nenhum ajuste.
- **Fase 18 — Exportação do Painel Gerencial em PDF:** mesmo padrão da
  Fase 10 (CoA) e da Fase 11 (Relatório de Recall) aplicado ao Painel
  Gerencial da Fase 7: um botão novo, "Baixar PDF", no topo da tela, que
  baixa um documento formatado com reportlab reunindo os cinco blocos do
  dashboard (Produção, Qualidade, Estoque, Comercial, Financeiro) e a
  tabela do Fluxo de Caixa Projetado (Fase 15) — útil para levar os
  números pra uma reunião ou arquivar um snapshot do dia sem precisar
  printar a tela. Nenhuma tabela nova, nenhum valor pré-calculado: o PDF
  é montado a partir da MESMA agregação que `GET /dashboard` já serve
  para a tela — extraí essa montagem para uma função só
  (`_montar_dashboard`, em `app/routes/relatorios.py`), reaproveitada
  pelos dois lugares, para o PDF nunca correr o risco de mostrar um
  número calculado de um jeito sutilmente diferente do que a tela já
  mostra (mesmo motivo pelo qual `_contas_em_aberto`/`_baixado_liquido`
  foram centralizadas na Fase 15). Reaproveita a mesma permissão
  `relatorios.visualizar` de todo o resto do Painel Gerencial — nenhuma
  permissão nova, porque exportar é a mesma capacidade de "visualizar",
  só num formato diferente. Cada PDF gerado grava um evento de auditoria
  (`painel_pdf_gerado`) com `tabela="painel_gerencial"` — um rótulo
  sintético, já que o painel inteiro é 100% agregação e não existe uma
  tabela `painel_gerencial` de verdade no banco, só para deixar
  rastreável quem exportou o quê e quando.
- **Fase 19 — Exportação do Painel Gerencial em CSV:** mesma ideia da
  Fase 18, mas pra quem quer os números crus numa planilha em vez de um
  documento formatado — um segundo botão, "Baixar CSV", ao lado do
  "Baixar PDF". Reaproveita exatamente a mesma `_montar_dashboard`/
  `_fluxo_caixa_projetado` da Fase 18 (então o CSV, o PDF e a própria
  tela nunca podem divergir um do outro), a mesma permissão
  `relatorios.visualizar` (nenhuma permissão nova) e o mesmo rótulo
  sintético de auditoria (`painel_csv_gerado`, `tabela="painel_gerencial"`).
  A única dependência é a biblioteca padrão `csv` do Python — deliberado:
  um `.xlsx` de verdade precisaria de uma biblioteca nova (ex.: openpyxl),
  enquanto um CSV abre direto no Excel/LibreOffice sem nenhuma dependência
  extra, mantendo o backend com a mesma pegada mínima de sempre. Separado
  por `;` (não por `,`) e com BOM UTF-8 no início do arquivo — sem isso,
  o Excel no Windows abre um CSV em português com os acentos quebrados
  (ex.: "Produção" vira "ProduÃ§Ã£o"); com o BOM, abre corretamente sem o
  usuário precisar saber importar como UTF-8 manualmente.
- **Fase 20 — DRE Simplificado:** um Demonstrativo de Resultado
  (`GET /custeio/dre`) que fecha a ponta financeira do que o Custeio de
  Produção (Fase 13) já vinha calculando: Receita Bruta = soma dos itens
  de todo pedido com status `expedido`; CMV = custo real de produção (ou
  de compra, se o lote foi recebido pronto em vez de fabricado) de cada
  lote efetivamente reservado/vendido nesses pedidos; Lucro Bruto =
  Receita − CMV; Margem Bruta % = Lucro Bruto / Receita. Nenhuma tabela
  nova e nenhum valor pré-calculado — tudo é recalculado a cada consulta
  a partir de `pedidos_venda`, `pedido_venda_itens` e
  `pedido_venda_reservas`, reaproveitando sem duplicar a lógica de custo
  já testada da Fase 13 (`custo_ordem_producao`/`custo_lote`, agora
  também por trás de um novo helper, `_custo_unitario_lote_vendido`, em
  `app/routes/custeio.py`). Assim como no Painel Gerencial, quando o
  custo de algum lote vendido não está disponível o DRE não finge que é
  zero: marca `custo_incompleto=true`, lista os `lotes_sem_custo_disponivel`
  e deixa claro que a margem mostrada está subestimada. Aceita filtro
  opcional por período (`?data_inicio=AAAA-MM-DD&data_fim=AAAA-MM-DD`,
  sobre `pedidos_venda.expedido_em`) — sem os parâmetros, cobre todo o
  histórico já expedido. Decisão deliberada de permissão: reaproveita
  `custeio.visualizar` (a mesma da tela "Custo do Produto" da Fase 13),
  **não** `relatorios.visualizar` do Painel Gerencial — porque o perfil
  Financeiro tem a primeira mas não a segunda, e um DRE expõe margem
  (calculada a partir de dado de custo sensível), então travar atrás de
  `relatorios.visualizar` deixaria de fora justamente o perfil que mais
  precisa enxergar essa tela.
- **Fase 21 — Aprovação de 2º Usuário para Ajuste de Contagem com
  Divergência Grande:** fecha uma lacuna de controle interno que ficou
  aberta desde a Fase 17 — até aqui, TODA divergência encontrada numa
  contagem de inventário virava um ajuste automático na hora de concluir,
  não importa o tamanho, autorizado sozinho por quem tinha
  `estoque.ajustar` e conduziu a contagem inteira. Agora, uma divergência
  GRANDE (acima de 20% do saldo que o sistema tinha no início da
  contagem, ou "achou alguma coisa onde o sistema não sabia de nada",
  quando o percentual nem é calculável) não ajusta sozinha: o item fica
  `aprovacao_status='pendente'` até um segundo usuário, com a permissão
  nova `estoque.aprovar_ajuste_contagem`, decidir via
  `POST /estoque/contagens/{id}/itens/{item_id}/aprovar-ajuste` ou
  `.../rejeitar-ajuste` (rejeitar não altera o saldo — só registra a
  decisão e o motivo, pra investigar depois). Divergências pequenas
  continuam sendo ajustadas na hora, exatamente como antes — comportamento
  aditivo, não muda nada do caminho comum. E não basta ter a permissão: o
  próprio código impede que quem contou o item seja quem aprova o ajuste
  dele (`item.contado_por == usuário atual` → 403), o mesmo padrão de
  segregação por usuário (não por perfil) já usado em `lotes.aprovar`
  desde a Fase 2. Um novo endpoint,
  `GET /estoque/ajustes-pendentes-aprovacao`, lista de forma consolidada
  (todas as contagens de uma vez) tudo que ainda está aguardando decisão —
  a tela Estoque mostra um aviso com essa contagem sempre que houver
  alguma pendência. Só adiciona colunas na tabela de itens de contagem já
  existente (nenhuma tabela nova), com DEFAULT compatível com toda
  contagem antiga, então bancos de fases anteriores continuam válidos sem
  nenhuma migração de dado.
- **Fase 22 — Aprovação Dupla para Estorno de Baixa Acima de um Valor de
  Alçada:** aplica ao dinheiro a mesma ideia de controle interno que a
  Fase 21 aplicou à contagem física — até aqui, TODO estorno de baixa
  (Fase 14) revertia na hora, sozinho, por quem tivesse
  `estornar_baixa_receber`/`estornar_baixa_pagar`, não importa o valor.
  Agora, uma baixa acima de `LIMIAR_VALOR_ESTORNO_DUPLA_APROVACAO`
  (R$ 1.000,00 — constante em `app/routes/financeiro.py`) não reverte na
  hora: a solicitação fica pendente (a rota de estornar devolve **202**,
  não 201) até um segundo usuário, com a permissão nova
  `financeiro.aprovar_estorno_receber`/`_pagar`, decidir via
  `POST /financeiro/contas-{receber|pagar}/estornos-pendentes/{id}/aprovar`
  ou `.../rejeitar` (rejeitar não reverte nada — só registra a decisão e o
  motivo). Baixas abaixo do limiar continuam revertendo imediatamente,
  exatamente como desde a Fase 14 — comportamento aditivo. Diferente da
  Fase 21, aqui não deu pra só adicionar colunas na tabela existente: as
  tabelas `contas_receber_baixas`/`contas_pagar_baixas` são **append-only**
  desde a Fase 6 (um trigger bloqueia UPDATE/DELETE), então o estado
  "pendente de aprovação" precisou de duas tabelas novas e mutáveis,
  `estornos_pendentes_receber`/`estornos_pendentes_pagar`. E, de novo como
  na Fase 21, não basta ter a permissão: o próprio código impede que quem
  solicitou o estorno seja quem aprova (`solicitado_por == usuário atual`
  → 403) — a mesma segregação por usuário (não por perfil) de
  `lotes.aprovar` (Fase 2) e `estoque.aprovar_ajuste_contagem` (Fase 21);
  por isso o perfil Financeiro ganhou as permissões novas sem precisar de
  um perfil "Financeiro Sênior" separado. Um novo endpoint,
  `GET /financeiro/estornos-pendentes`, consolida receber e pagar numa só
  lista (campo `tipo` diferencia) — a tela Financeiro mostra um aviso com
  essa contagem sempre que houver alguma pendência, e o modal "Ver baixas"
  de cada conta mostra o selo "Estorno pendente de aprovação" (com os
  botões Aprovar/Rejeitar, para quem tem permissão) em vez do botão
  "Estornar" normal.
- **Instalador para Windows (`installer/`):** fecha o item "empacotamento
  como cliente Windows instalável" que estava na minha lista de
  pendências desde a Fase 1. Entrega um `AlphafitusOS_Instalar.exe` (um
  instalador auto-extraível de verdade, montado sem precisar de
  compilador nem de rede — ver `installer/README.md` para os detalhes
  técnicos de como isso foi feito e, principalmente, para as limitações
  honestas de eu não ter um Windows real para confirmar que funciona de
  ponta a ponta antes de entregar) e uma alternativa em `.zip` + `.bat`
  que faz exatamente a mesma coisa sem depender do `.exe`, como
  garantia. Cria atalho na Área de Trabalho/Menu Iniciar, prepara o
  ambiente Python automaticamente na primeira execução, e abre o sistema
  direto no navegador — sem precisar digitar nenhum comando.
- **Fase 23 — Geração Automática de Código de Item:** até aqui, `codigo`
  era um campo obrigatório e digitado à mão em `POST /itens`, sem nenhuma
  regra de formato — abria espaço para inconsistência entre quem cadastra
  (cada um podia escolher um padrão diferente) e para erro de digitação
  usado depois em OPs, pedidos de venda etc. Agora, se `codigo` não for
  informado no cadastro, o sistema gera um automaticamente a partir do
  `tipo` do item, no formato PREFIXO + 6 dígitos sequenciais (`MP000001`
  para matéria-prima, `EPP000001`/`EPS000001` para embalagem primária/
  secundária, `PI000001` para produto intermediário, `PG000001` para
  produto a granel, `PA000001` para produto acabado, `LAB000001` para
  material de laboratório — ver `PREFIXOS_CODIGO` em
  `app/routes/itens.py`). A sequência é por prefixo (cada tipo tem a sua
  própria contagem, independente dos outros) e só considera, para achar o
  próximo número, códigos que já estão exatamente nesse formato — um
  código antigo digitado manualmente não interfere e não é sobrescrito. A
  unicidade final continua garantida pela constraint `UNIQUE` da coluna
  `codigo` no banco, como desde a Fase 2. Informar `codigo` manualmente
  continua funcionando exatamente como antes (nenhuma mudança de
  comportamento para quem já integra com a API passando um código
  próprio) — é só o campo que passou de obrigatório para opcional. Na
  tela "Novo item", o campo "Código" foi removido do formulário (a
  mensagem de sucesso mostra o código que o sistema gerou). Esse mesmo
  código será usado de forma consistente em OPs, no APS e nos módulos
  futuros (ex.: Estabilidades), como pedido.
- **Fase 24 — Memorial Técnico ANVISA (Fundação):** novo módulo,
  reconstruído nesta mesma tecnologia (Flask/SQLite/JS puro) a partir de um
  sistema separado (Node.js/React/Postgres, hospedado no Replit/GitHub do
  cliente) que ele já usava para gerar o memorial técnico exigido pela
  ANVISA no registro/notificação de suplementos alimentares — a decisão de
  reconstruir em vez de rodar o sistema original junto foi do próprio
  cliente, para não complicar a instalação (já trabalhosa) no Windows dele
  com um segundo servidor/banco. Esta é a base do módulo: cadastro de
  **empresas** (`memorial_empresas` — razão social, CNPJ único,
  responsável técnico/CRF) e de **produtos** vinculados a uma empresa
  (`memorial_produtos` — categoria, forma farmacêutica, porção, etc.), e o
  próprio **memorial** (`memoriais`), com cerca de 35 campos de conteúdo
  técnico (identificação, composição/conteúdo nutricional, plano de
  estudo, advertências, responsáveis) agrupados em 3 seções na tela de
  detalhe. Segue um fluxo de status
  `rascunho → em_andamento → em_revisao → concluído → aprovado/reprovado`,
  com histórico de mudanças **append-only** (`memorial_historico` — só a
  edição/apagamento de uma entrada individual é bloqueada; excluir o
  memorial inteiro, e com ele seu histórico, continua possível, mas só
  enquanto o memorial ainda está em rascunho — depois disso vira 409, para
  preservar o rastro de conformidade). Cada memorial recebe um código
  (`codigo`) e um número de certificado (`numero_certificado`) gerados
  automaticamente no formato `CERT-AF-AAAAMMDD/NNN` (sequência global por
  dia) se não forem informados manualmente — mesmo princípio da geração
  automática de código da Fase 23, aplicado aqui a um formato próprio
  espelhando o do sistema original do cliente. Assinatura eletrônica
  simples: cada usuário só pode assinar uma vez por memorial (cargo e
  iniciais preenchidos a partir do usuário logado); ao reunir **2
  assinaturas de usuários diferentes** com o memorial já em status
  "Concluído", o sistema **aprova automaticamente** (registrado no
  histórico) — sem precisar de uma ação manual extra. Um novo perfil,
  **Regulatório**, reúne as 12 permissões novas
  (`memorial_empresas.*`, `memorial_produtos.*`, `memoriais.*`, com
  `memoriais.editar` separado de `memoriais.concluir` e de
  `memoriais.assinar`, seguindo a mesma segregação por ação já usada em
  `producao.planejar`/`producao.liberar`). Ficam fora do escopo desta
  fase — e são a lista de pendências natural para as próximas entregas
  deste módulo — os catálogos auxiliares do sistema original (nutrientes,
  metodologias, alegações, componentes, referências normativas etc., que
  no sistema original eram seletores/autocomplete e aqui por ora são texto
  livre), o anexo de documentos ao memorial, a padronização de rótulo, e o
  "protocolo de estabilidade" — uma peça relacionada, mas separada, que o
  próprio cliente pediu para tratar depois de ver como este módulo se
  comporta já em uso.
- **Fase 24 (atualização) — Memorial Técnico, visual fiel ao sistema
  original:** depois de ver o painel da Fase 24 pela primeira vez, o
  cliente apontou que o layout não batia com o do sistema original (que
  ele mostrou por print). Na entrega inicial eu só tinha lido a lógica de
  negócio do backend original (`artifacts/api-server`), sem abrir o
  frontend React (`artifacts/memorial-anvisa/src`) — corrigido agora lendo
  o código-fonte de verdade do frontend original (não só prints), para
  reproduzir cores, ícones e estrutura fielmente, não por aproximação. O
  item de menu "Memorial Técnico" agora abre uma **Visão Geral** (nova
  tela inicial do módulo, em `#/memorial/visao-geral`) com cartões
  coloridos de estatística (Total de Memoriais, Aprovados, Em Andamento,
  Em Revisão, Rascunhos, Reprovados — mesmas cores do tema original,
  convertidas de HSL para hex), um cartão-resumo de Empresas/Produtos, um
  cartão de alerta (laranja) quando há assinaturas pendentes, e uma lista
  "Progresso dos Documentos" com barra de progresso colorida por
  memorial ainda não finalizado. As quatro telas do módulo (Visão Geral,
  Empresas, Produtos, Memoriais Técnicos) passaram a compartilhar uma
  navegação aninhada própria (barra escura à esquerda do conteúdo, dentro
  do único item "Memorial Técnico" da barra lateral principal — não uma
  tela separada), reproduzindo a navegação do sistema original em vez das
  abas simples que existiam antes. O percentual de progresso de cada
  memorial (`progresso.pct`) segue o mesmo critério do sistema original
  (10 seções de conteúdo checadas; 100% automático quando o status já é
  "Concluído" ou "Aprovado") — sempre **recalculado a partir do conteúdo
  atual**, nunca armazenado, para não haver risco de ficar desatualizado.
  Os catálogos/seletores estruturados que o cálculo de progresso do
  sistema original usa (JSON de nutrientes, alegações etc.) ainda não
  foram portados — aqui o progresso usa os mesmos 10 campos de texto livre
  já existentes na Fase 24 como aproximação, documentado no código
  (`SECOES_PROGRESSO_MEMORIAL` em `app/routes/memorial.py`).
- **Fase 25 — APS: Sequenciamento e Capacidade Finita (Fundação):** base
  do módulo de Advanced Planning & Scheduling. Cadastro de **centros de
  trabalho** (`centros_trabalho` — nome, capacidade paralela, ativo/
  inativo) e agendamento de uma ordem de produção num centro de trabalho
  e janela de tempo (`ordem_producao_agendamentos` — uma linha por ordem,
  mutável, porque representa planejamento atual e não um registro de
  conformidade). Ao agendar, o sistema verifica sobreposição de horário
  contra os outros agendamentos do mesmo centro e rejeita (409) se o
  número de agendamentos sobrepostos já atingir a capacidade paralela do
  centro — permitindo, de propósito, mais de uma ordem simultânea num
  centro com capacidade > 1. Reagendar uma ordem já agendada faz upsert
  na mesma linha (não duplica). Só ordens em `planejada`, `liberada` ou
  `em_producao` podem ser agendadas/reagendadas; canceladas e concluídas,
  não. Dois novos verbos de permissão sobre recursos já existentes:
  `centros_trabalho.*` (visualizar/cadastrar/editar, concedido ao perfil
  PCP; Produção só visualiza) e `producao.agendar` (concedido ao PCP),
  seguindo a mesma segregação por ação já usada em
  `producao.planejar`/`producao.liberar`. Interface no navegador: novo
  item de menu **"Centros de Trabalho (APS)"** (cadastro/edição, com
  ativar/inativar) e, na própria tela de detalhe de uma Ordem de Produção,
  um novo cartão **"Agendamento (APS)"** — mostra o centro/janela de tempo
  já agendados (se houver) e os botões Agendar/Reagendar/Desagendar
  (gated por `producao.agendar`, com o seletor de centro de trabalho só
  aparecendo para quem também tem `centros_trabalho.visualizar`). Ao
  tentar agendar um horário que estoura a capacidade, o erro 409 do
  backend aparece na tela citando explicitamente com qual outra ordem o
  conflito é. Ainda faltam: uma agenda/calendário visual (hoje só dá para
  ver o agendamento de UMA ordem por vez, na tela de detalhe dela — não
  existe uma visão consolidada "o que está agendado nesta semana neste
  centro"), e o próprio endpoint `GET /aps/agenda` (já pronto no backend)
  ainda não tem nenhuma tela que o consuma.
- **Fase 26 — Catálogos do Memorial Técnico ANVISA:** a Fase 24 (fundação
  do módulo) deixou de propósito de fora os 10 cadastros de apoio do
  sistema original que alimentam seletores usados ao preencher um
  memorial (**Metodologias, Nutrientes, Legislações, Alegações, Tipos de
  Produto, Advertências, Armazenamento, Modo de Uso, Justificativas,
  Referências**) — em vez de digitar "Vitamina C" ou uma alegação inteira
  toda vez, cadastra-se uma vez aqui e escolhe-se de uma lista depois.
  Esta fase entrega esses 10 catálogos. Decisão de implementação: em vez
  de 10 tabelas quase idênticas e 10 conjuntos de rotas copiados e
  colados, os 10 catálogos moram numa única tabela
  (`memorial_catalogo_itens`, coluna `catalogo` diz qual dos 10 é, coluna
  `dados` guarda em JSON os campos específicos daquele catálogo — que
  variam: "Advertências" só tem um texto, "Nutrientes" tem várias doses e
  unidades) e uma única tela genérica no frontend
  (`renderMemorialCatalogo`), reaproveitada pelos 10 — `ordem` e `ativo`
  ficam como colunas de verdade (comuns a todos, usadas para ordenar a
  lista e "desativar sem excluir", mesmo padrão do sistema original em
  vez de soft-delete). Um recurso de permissão só, `memorial_catalogos`
  (visualizar/cadastrar/editar/excluir), cobre os 10 catálogos — no
  sistema original também era uma permissão só. Interface no navegador:
  novo grupo colapsável **"Catálogos"** dentro da navegação aninhada do
  Memorial Técnico, listando os 10 itens; cada um abre a mesma tela
  genérica de listagem + modal de criar/editar, com os campos daquele
  catálogo específico (a tabela mostra só os 3 primeiros campos, para não
  ficar gigante — os demais aparecem completos no modal de edição).
  Deliberadamente fora de escopo desta entrega: os 10 catálogos ainda não
  estão conectados como *seletores* dentro do formulário de edição de um
  memorial (que continua com os mesmos campos de texto livre da Fase 24)
  — fica para uma próxima entrega (ver backlog).
- **Fase 27 — Memorial Técnico ANVISA: Anexos e Padronização de Rótulo,
  tela de edição redesenhada em abas numeradas:** a Fase 24 (fundação do
  módulo) tinha deixado de propósito de fora "anexos de arquivo" e "a
  página de padronização de rótulo", com a tela de edição do memorial
  organizada num scroll único de 3 seções. Esta fase entrega os dois
  recursos que faltavam e redesenha a tela de edição nas mesmas 10 abas
  numeradas do sistema original — "0. Identificação" a "9. Referências" —
  mais 4 sub-abas com nome (Assinaturas, Anexos, Padronização, Exportar),
  todas na mesma faixa de navegação, exatamente como no sistema original.
  Nenhum campo mudou de nome nem foi removido do banco — são os MESMOS
  ~35 campos de sempre, só reagrupados nas 10 abas em vez de 3 seções; as
  10 abas ficam dentro de um único `<form>` (trocar de aba não perde o
  que já foi digitado nas outras, porque todas continuam no DOM, só
  escondidas — só ao clicar em "Salvar conteúdo do memorial", que
  aparece em toda aba numerada, tudo é enviado de uma vez).
  **Anexos** (`memorial_anexos`): upload, listagem, download e exclusão
  de arquivos (PDF/Word, até 40 MB) ligados a um memorial — o arquivo é
  guardado como base64 na própria coluna `dados` da tabela (não em
  disco/object storage), mesma escolha do sistema original e consistente
  com o resto do Alphafitus, que já guarda tudo num único arquivo `.db`.
  Reaproveita as permissões que já existiam (`memoriais.visualizar` para
  ver/baixar, `memoriais.editar` para enviar/excluir — anexar um arquivo
  é parte de editar o conteúdo do memorial, não uma ação à parte).
  **Padronização de Rótulo** (`memorial_padronizacoes`): um registro 1:1
  por memorial com os "dizeres de rotulagem" (produto, peso líquido,
  lista de ingredientes, alergênicos, dimensões do rótulo, etc.) — um
  verbo de permissão novo no recurso `memoriais` já existente
  (`memoriais.padronizar`, mesmo padrão de `producao.agendar` da Fase 25)
  em vez de um recurso à parte, já que editar a padronização é uma ação
  sobre um memorial específico. **Exportar** é 100% client-side (usa a
  função de impressão do próprio navegador, com uma folha de estilos
  `@media print` que esconde a navegação e os botões de ação) — mais
  simples do que a combinação de PDF+Word do sistema original (que
  convertia cada anexo para imagem/HTML e injetava tudo antes de
  imprimir), documentado como simplificação deliberada no backlog.
  **Assinaturas** já existia desde a Fase 24; ficou dentro da nova
  sub-aba de mesmo nome, agora acompanhada do Histórico (como no sistema
  original, onde as duas coisas vivem juntas na mesma aba).
- **Fase 28 — APS: Agenda Visual (calendário/Gantt):** a Fase 25 tinha
  entregado agendar uma ordem de produção num centro de trabalho, mas só
  ordem por ordem, dentro do detalhe da própria ordem — para saber o que
  um centro de trabalho tem programado numa semana era preciso abrir
  ordem por ordem. Esta fase entrega a visão consolidada que faltava:
  uma linha por centro de trabalho, uma coluna por dia da semana, e uma
  barra colorida (mesmas cores dos selos de status já usados no resto do
  sistema) por agendamento que toca aquele dia — um agendamento que
  atravessa mais de um dia aparece repetido em cada dia que toca
  (simplificação deliberada, documentada no código, em vez de uma única
  barra "esticada" cobrindo vários dias). Dá para navegar entre semanas
  (anterior/hoje/próxima) e filtrar por um centro de trabalho específico;
  clicar numa barra leva direto para o detalhe da ordem de produção
  correspondente. 100% construída em cima do endpoint `GET /aps/agenda`
  que a própria Fase 25 já tinha deixado pronto (já aceitava filtro por
  centro e por período) — nenhuma rota, tabela ou permissão nova, só a
  tela que faltava, reaproveitando a permissão `producao.visualizar` que
  já existia.
- **Fase 29 — Memorial Técnico ANVISA: Catálogos como Seletores:** a Fase
  24 (fundação do módulo) deixou ~10 campos do memorial como texto livre
  de propósito, citando os catálogos de apoio como o próximo passo; a
  Fase 26 entregou os 10 catálogos em si e a Fase 27 reorganizou a tela de
  edição nas 10 abas numeradas do sistema original — mas os campos
  continuaram sendo texto livre. Esta fase conecta os dois: cada um dos 10
  campos mapeados (Tipo de Produto, Composição Nutricional, Metodologias
  Aplicadas, Alegações, Justificativas Técnicas, Legislação Aplicável,
  Referências Bibliográficas, Advertências, Armazenamento e Modo de Uso)
  ganha um botão **"+ Catálogo"** ao lado do rótulo, que abre um modal
  listando os itens já cadastrados naquele catálogo (reaproveitando
  `GET /memorial/catalogos/<catalogo>` que a própria Fase 26 já tinha
  deixado pronto — nenhuma rota, tabela ou permissão nova) — escolher um
  item **insere** o texto formatado dele no campo (mesmo estilo "- título:
  corpo1 — corpo2" que o script de importação do backup antigo já usa,
  para o texto ficar no mesmo formato de um memorial que veio de lá).
  Campos de texto único (`<textarea>`) acrescentam uma linha sem apagar o
  que já estava escrito; o único campo de valor único (`<input>`, "Tipo de
  Produto") substitui o valor. Decisão deliberada: os campos continuam
  sendo texto livre no banco — nenhuma coluna nova, nenhuma migração —
  então digitar manualmente por cima do que o catálogo inseriu (ou editar
  depois) continua funcionando normalmente; o catálogo é um atalho para
  não digitar de novo algo já cadastrado, não uma trava. O botão só
  aparece pra quem já tem as duas permissões que essa ação de fato exige
  (`memoriais.editar` e `memorial_catalogos.visualizar`, ambas já
  existentes) — sem elas o botão nem aparece, em vez de aparecer e falhar.
- **Fase 30 — Custo de Mão de Obra e Overhead na Produção:** a Fase 13
  entregou o custeio real de uma ordem de produção, mas só a partir do
  custo de MATERIAL (matéria-prima e embalagem consumidos) — uma lacuna
  documentada desde então como "não há apontamento de horas/turno nem
  rateio de custo fixo de fábrica". Esta fase entrega os dois pedaços que
  faltavam, do jeito mais simples que já resolve o problema real: os
  centros de trabalho (Fase 25) ganham dois campos opcionais, custo por
  HORA de mão de obra e custo por HORA de overhead (aluguel, energia,
  depreciação de máquina rateados por hora de linha); e a conclusão de
  uma ordem (mesmo padrão do campo opcional `quantidade_perda` da Fase 9)
  ganha um campo opcional "horas apontadas". O custeio reaproveita o
  agendamento da Fase 25 (não pede de novo qual centro produziu — usa o
  que já foi agendado) para descobrir a taxa/hora daquele centro e
  multiplicar pelas horas apontadas. Filosofia de transparência mantida
  (mesma da Fase 13): o sistema NUNCA inventa um número — se faltar
  qualquer uma das três informações (horas apontadas na conclusão,
  agendamento num centro, ou taxa cadastrada naquele centro), o card de
  Custo de Produção mostra claramente "indisponível" com o motivo exato,
  em vez de mostrar R$ 0,00 como se fosse um custo real. O
  `custo_total_producao` original (só material) continua existindo com
  exatamente o mesmo valor e significado de antes — o novo total
  combinado entra como um campo adicional
  (`custo_total_producao_com_mao_de_obra`), então nada que já dependia do
  campo antigo quebra. Zero permissões novas: reaproveita
  `centros_trabalho.editar` (Fase 25), `producao.apontar` (Fase 3/9) e
  `custeio.visualizar` (Fase 13).
- **Fase 31 — Aprovação Dupla para o Registro de Baixa Acima de um Valor
  de Alçada:** a Fase 22 já tinha aplicado dupla aprovação ao ESTORNO de
  uma baixa acima de R$1.000,00 — REGISTRAR uma baixa nova de valor alto
  continuava exigindo só a permissão comum, sem nenhuma segunda
  aprovação, mesmo o catálogo de permissões já marcando
  `registrar_baixa_receber`/`registrar_baixa_pagar` como
  `exige_dupla_aprovacao=1` desde a Fase 6 (um sinalizador puramente
  informativo até aqui, do jeito que `exige_dupla_aprovacao` já era antes
  da própria Fase 22 aplicar isso ao estorno). Esta fase fecha essa
  lacuna espelhando exatamente o mesmo desenho: acima do valor de alçada,
  registrar um recebimento ou pagamento não entra no ledger na hora —
  vira uma solicitação pendente até um segundo usuário (permissão nova
  `aprovar_baixa_receber`/`aprovar_baixa_pagar`, diferente de quem
  solicitou) aprovar ou rejeitar. Abaixo do limiar, nada muda: a baixa
  entra direto no ledger, exatamente como desde a Fase 6. A tela de "Ver
  baixas" de cada conta ganha uma seção nova, separada do histórico de
  baixas já lançadas, listando as solicitações pendentes com os botões
  Aprovar/Rejeitar (só pra quem tem a permissão) — e o topo da tela
  Financeiro mostra um aviso consolidado de quantas solicitações estão
  aguardando decisão, buscado do endpoint novo `GET
  /financeiro/baixas-pendentes` (espelho do `/estornos-pendentes` da Fase
  22, mas para registro em vez de estorno — tabelas e endpoints
  deliberadamente separados, porque são dois conceitos diferentes: uma
  solicitação de lançar algo novo, não de reverter algo já lançado).
- **Fase 32 — Limiar de Divergência de Contagem Configurável pela Tela:**
  a Fase 21 entregou a segunda aprovação para divergência GRANDE (acima
  de 20% do saldo que o sistema tinha no início da contagem) numa
  contagem de inventário — mas esse "20%" ficava fixo no código
  (`LIMIAR_PERCENTUAL_DIVERGENCIA_GRANDE` em `app/routes/estoque.py`),
  exigindo alterar e reimplantar o backend pra mudar. Esta fase move
  esse valor para uma tabela nova de configuração (`configuracoes_
  estoque`, linha única) e ganha uma tela para editá-lo: um botão
  "Configurar limiar" (só pra quem tem a permissão nova `estoque.
  configurar_alcada_divergencia`, que por padrão só o Administrador tem
  — mudar essa régua é uma decisão de controle interno, não uma
  operação do dia a dia) abre um formulário simples, e o texto de ajuda
  da tela Estoque passa a mostrar o percentual REAL configurado, não um
  número fixo no texto. O valor é guardado em PERCENTUAL (0 a 100, ex.:
  20 = 20%) por ser mais natural pra tela e pra API — o código que
  compara contra a divergência calculada (que é uma fração 0-1) converte
  na hora da comparação. Visualizar o valor atual é liberado a qualquer
  um que já veja o módulo Estoque (não é um dado sensível); só ALTERAR
  exige a permissão nova. Comportamento de quem já tem o sistema rodando
  não muda: a migração semeia a linha única já com 20%, o mesmo valor
  que era fixo no código antes desta fase.
- **Fase 33 — Limite de Prazo para Estorno de Baixa Configurável pela
  Tela:** desde a Fase 14, um estorno de baixa podia ser feito a qualquer
  momento depois da baixa original, sem nenhuma janela de tempo — uma
  regra de controle interno real poderia exigir, por exemplo, que o
  estorno só valha dentro de um número limitado de dias, pra não deixar
  reverter lançamentos de meses fiscais já fechados. Mesmo espírito da
  Fase 32: a régua (em dias, contados a partir de `criado_em`, o instante
  em que o sistema efetivamente registrou o lançamento — não da data de
  pagamento digitada pelo usuário, que não serve como referência
  confiável de prazo) agora mora numa tabela de configuração nova
  (`configuracoes_financeiro`, linha única) e ganha uma tela para
  editá-la: um botão "Configurar prazo de estorno" (só pra quem tem a
  permissão nova `financeiro.configurar_limite_estorno`, que por padrão
  só o Administrador tem) abre um formulário simples, e o texto de ajuda
  da tela Financeiro passa a mostrar o prazo REAL configurado.
  `limite_dias_estorno_baixa = 0` (o valor padrão, semeado pela migração)
  significa "sem limite" — o comportamento idêntico ao que já existe
  desde a Fase 14, então ninguém que já usa o sistema é afetado até
  alguém configurar um valor. O bloqueio de prazo é checado ANTES até de
  entrar no fluxo de dupla aprovação da Fase 22: não faz sentido deixar
  solicitar um estorno de uma baixa que já nem pode mais ser estornada,
  então mesmo um estorno de valor alto (que ficaria pendente de um
  segundo usuário) é recusado de cara se já passou do prazo.
- **Fase 34 — Alçada por Valor Monetário do Ajuste de Contagem, além do
  Percentual de Divergência:** a Fase 21 (com o percentual configurável
  desde a Fase 32) só olha para o PERCENTUAL de divergência de um item
  de contagem em relação ao saldo que o sistema tinha — um item de baixo
  valor com 90% de divergência dispara a segunda aprovação, mas um item
  caríssimo com só 5% de divergência não, mesmo que o valor financeiro
  do ajuste seja bem maior. Esta fase adiciona um SEGUNDO gatilho,
  independente do percentual: se o valor financeiro do ajuste (diferença
  de quantidade × custo unitário do lote — mesma lógica de custeio já
  usada no CMV do DRE da Fase 20, generalizada numa função pública nova,
  `custeio.custo_unitario_lote`, que cobre tanto lote recebido quanto
  lote produzido) ultrapassar um limiar em R$, o ajuste também exige
  segunda aprovação. O campo novo `limiar_valor_ajuste_divergencia_
  grande` mora na MESMA linha única de `configuracoes_estoque` (Fase 32)
  e é editável pelo MESMO formulário "Configurar limiar" (agora com dois
  campos), com a mesma permissão `estoque.configurar_alcada_
  divergencia` — é a mesma decisão de controle interno, só que num
  segundo campo. `limiar_valor_ajuste_divergencia_grande = 0` (o padrão)
  desliga esse gatilho por completo, então ninguém que já usa o sistema
  é afetado até alguém configurar um valor — e, na mesma filosofia de
  transparência da Fase 13, quando o custo do lote não é conhecido (não
  informado no recebimento, sem lotes do mesmo item pra calcular uma
  média), o sistema nunca arrisca deixar passar sem segunda aprovação:
  trata como divergência grande por segurança, nunca o contrário. O
  valor estimado do ajuste aparece de forma transparente tanto no
  detalhe da contagem quanto na lista consolidada de pendências.
- **Fase 35 — Agendamento/Cadência Automática de Contagens Cíclicas:** até
  aqui (Fase 17) toda contagem de inventário só nascia quando alguém com
  a permissão `estoque.contagem` clicava em "Nova contagem". Esta fase
  acrescenta uma REGRA cadastrada uma vez — depósito, tipo (geral ou
  cíclica, com uma amostra aleatória de X% dos itens no caso cíclico) e
  cadência (diária, semanal num dia fixo, ou mensal num dia fixo, com o
  mês sem esse dia caindo no último dia dele) — que gera a contagem
  sozinha quando o dia certo chega, sem exigir que ninguém lembre de
  criar manualmente. Este backend não tem um agendador de tarefas do
  sistema operacional de verdade rodando em segundo plano, então
  "automático" aqui significa "verificado e disparado na hora certa": a
  tela de Estoque chama a verificação sozinha cada vez que é aberta por
  alguém com `estoque.contagem`, e se algum agendamento estiver vencido
  (dia certo, ainda não gerado hoje), a contagem nasce ali mesmo,
  rotulada com `origem='agendamento'` e vinculada à regra que a gerou —
  nada escondido, quem abrir a contagem sabe exatamente de onde ela veio.
  Cadastrar/editar/desativar uma regra exige a permissão nova
  `estoque.agendar_contagem` (só o Administrador, por padrão — é uma
  decisão de controle interno, não uma operação do dia a dia); ver a
  lista de regras já cadastradas é liberado a quem já vê o módulo
  Estoque, na mesma filosofia da Fase 32. Excluir uma regra nunca afeta
  as contagens que ela já gerou — elas continuam com o rótulo de origem,
  só perdem o vínculo com uma regra que não existe mais.
- **Fase 36 — Aplicativo de Vendas para Vendedores (Reserva Temporária de
  Item, Verbas Comerciais e Comissão do Vendedor):** até aqui só existia
  UMA porta de entrada para montar/confirmar um pedido de venda — a tela
  de desktop de Comercial (Fase 5). Esta fase acrescenta uma SEGUNDA porta
  de entrada, pensada para o vendedor em campo (nova tela "App de Vendas",
  dentro do mesmo `app.js`, sem exigir instalação separada), sem mudar
  nada do comportamento de quem já usa a tela de desktop. Três ideias
  novas, todas cadastradas no ERP e funcionais no App, como pedido:
  1) **Reserva temporária ("soft-hold")** — enquanto um vendedor tem um
     item no carrinho de um rascunho, esse item passa a contar como
     "comprometido" para TODOS OS OUTROS vendedores (o saldo disponível
     mostrado a eles já desconta essa quantidade), sem tocar em nenhuma
     tabela de reserva física de estoque — essa continua só existindo
     depois da confirmação de verdade (`pedido_venda_reservas`), exatamente
     como desde a Fase 5. A reserva se libera de três formas: o vendedor
     envia o pedido (a reserva física real assume o lugar dela), o
     vendedor descarta o rascunho explicitamente (ex.: fecha o app), ou o
     rascunho fica `minutos_expiracao_rascunho` (configurável, padrão 240)
     sem nenhuma interação — verificado de forma OPORTUNISTA (não um cron
     de sistema operacional de verdade, mesmo espírito da Fase 35) no
     início de toda chamada do App de Vendas. Quem realmente "ganha" a
     disputa entre dois vendedores que reservaram o mesmo item é decidido
     no ENVIO, que reaproveita a mesma alocação FEFO tudo-ou-nada da
     confirmação de sempre (`confirmar_pedido_internamente`, extraída de
     `comercial.py` para ser compartilhada pelos dois pontos de entrada) —
     nenhum lock novo foi necessário: o primeiro a confirmar com sucesso
     consome o saldo físico real, e o outro recebe o mesmo erro de "saldo
     insuficiente" que a tela de desktop sempre teve.
  2) **Verbas comerciais** — um crédito do CLIENTE (não do vendedor),
     gerado automaticamente na expedição de uma venda como um percentual
     configurável (`percentual_verba_gerada`, 0% por padrão) sobre o valor
     faturado, lançado num ledger append-only
     (`verbas_comerciais_lancamentos`, mesmo princípio de todo ledger deste
     sistema — o saldo é sempre `SUM('gerada') - SUM('utilizada')`
     recalculado na hora, nunca um número guardado à parte). O vendedor
     pode aplicar parte ou todo esse saldo para abater o valor de um
     pedido futuro do mesmo cliente ainda no rascunho; o valor é congelado
     na confirmação e o lançamento de uso só entra no ledger na expedição
     (mesmo momento em que a venda deixa de ser um plano e passa a ser um
     fato) — se o pedido for cancelado antes disso, nada precisa ser
     desfeito porque nada chegou a ser lançado.
  3) **Comissão do vendedor** — cada vendedor vê suas próprias vendas e a
     comissão a receber no mês (tela "Minhas Comissões"), sempre com dois
     números lado a lado: a comissão PROJETADA (percentual configurável,
     `percentual_comissao_padrao`, sobre o valor total da conta a receber
     gerada pela venda) e a comissão REALIZADA (o mesmo percentual, mas só
     sobre o que já foi efetivamente baixado/liquidado daquela conta —
     nunca sobre o valor cheio antes do cliente pagar, exatamente como
     pedido: "a comissão será sempre na liquidez do boleto, ou no
     pagamento efetivo da compra").
  O app também resolve o fluxo de sincronização pedido: ao gerar um
  pedido, o vendedor pode continuar trabalhando mesmo sem internet no
  MOMENTO DO ENVIO — se a tentativa de enviar falhar por falta de conexão
  (não por um erro de negócio), o app marca o pedido como "aguardando
  envio", avisa o vendedor com um banner permanente na tela, e tenta
  enviar de novo automaticamente assim que o navegador detectar que a
  internet voltou (ou por um botão "Tentar enviar agora"); toda
  sincronização bem-sucedida com o ERP (abrir a tela, adicionar/remover um
  item) também renova a validade da reserva temporária. Limitações desta
  fase, documentadas de propósito (evoluções possíveis, não bugs — ver
  também a seção "O que ainda falta" abaixo): um vendedor só monta UM
  rascunho por vez neste app (não um carrinho por cliente); a comissão usa
  um único percentual global, ainda sem um valor diferente por vendedor;
  não existe reversão de verba (nenhum fluxo de devolução de pedido existe
  ainda no sistema); e "fechar o app" é detectado por melhor esforço (o
  app avisa o servidor ao fechar, mas nenhum evento de fechamento de
  navegador é 100% confiável — por isso existe também a expiração
  automática por inatividade, como rede de segurança).
- **Fase 37 — Notificações do Sistema com Envio Real por E-mail:** desde a
  Fase 1 existia a tabela `notificacoes` e a API para o usuário listar as
  suas notificações e marcar como lida — mas em nenhuma fase até aqui algo
  no sistema de fato CRIAVA uma notificação; a tabela sempre ficou vazia,
  e não havia nenhuma tela mostrando isso (sem sino, sem lista). Esta fase
  resolve as duas pontas: um sino na barra superior (com o número de não
  lidas) e uma tela nova, "Notificações", abertas a qualquer usuário
  logado; e um serviço central (`app/notificacoes_service.py`, mesmo
  espírito de `app/audit.py`: um helper simples, sem blueprint próprio,
  chamado de dentro da MESMA transação da ação de negócio que o dispara)
  que passa a avisar de verdade quem precisa agir nas filas de segunda
  aprovação que já existiam desde as Fases 21/22/31/34: ajuste de
  contagem com divergência grande, e as quatro filas do financeiro
  (registrar/estornar baixa a receber/pagar acima da alçada) — cada
  pendência nova notifica quem tem a permissão de aprovar, exceto quem
  disparou a própria pendência (mesma segregação de função já aplicada
  nessas fases). Além da notificação aparecer na tela, ela pode ser
  enviada por e-mail de verdade — servidor SMTP configurável pela própria
  tela (cartão "Configuração de E-mail (SMTP)", só quem tem a permissão
  nova `sistema.configurar_email`, o Administrador por padrão), com um
  botão "Enviar e-mail de teste" para validar a configuração sem precisar
  esperar um gatilho de negócio acontecer. O envio é sempre "melhor
  esforço": enquanto `ativo` estiver desligado (o padrão, preserva o
  comportamento de todas as fases anteriores), enquanto o SMTP não
  estiver configurado, ou enquanto a própria pessoa tiver desligado o
  recebimento por e-mail para si mesma (nova preferência, ligada por
  padrão, qualquer usuário pode desligar na própria tela de
  Notificações), a notificação continua sendo criada e aparece na tela
  normalmente — só o e-mail não sai, e o motivo exato (desligado,
  sem SMTP, usuário optou por não receber, ou erro de conexão) fica
  registrado em cada notificação (`email_enviado`/`email_erro`), nunca
  escondido. Nenhum pacote novo foi instalado para isso — o envio usa só
  `smtplib`/`email` da biblioteca padrão do Python, a mesma restrição de
  "sem acesso à rede para instalar pacotes novos" documentada no restante
  deste README (foi o motivo de esta fase ter sido escolhida em vez de,
  por exemplo, gerar um QR code visual para o 2FA, que exigiria uma
  biblioteca nova indisponível neste ambiente — ver "O que ainda falta").
  A senha do SMTP nunca volta para a tela depois de salva (a API só
  devolve um booleano "senha configurada"), e deixar o campo em branco ao
  salvar de novo preserva a senha já salva, em vez de apagá-la.
- **Fase 38 — Responsividade e App Instalável para Celular/Tablet:** até
  aqui o sistema era usável em qualquer navegador, mas o layout era
  desenhado só para tela de computador (barra lateral fixa de 240px,
  tabelas largas sem rolagem própria) — em um celular ou tablet, a barra
  lateral sozinha já tomava boa parte da tela útil. Esta fase reorganiza o
  layout para telas estreitas (até 900px de largura, o suficiente para
  cobrir celular e tablet em retrato) sem mudar NADA do layout em tela de
  computador: a barra lateral passa a ser uma "gaveta" escondida por
  padrão, aberta por um botão de hambúrguer novo na barra superior e
  fechada tocando fora dela ou navegando para qualquer tela; toda tabela
  do sistema (não só as novas — todas, incluindo as de fases anteriores)
  passa a ficar dentro de um contêiner com rolagem horizontal própria,
  para nunca mais "quebrar" o layout numa tela estreita; e botões/campos
  ganham uma altura mínima maior, mais fácil de acertar com o dedo do que
  com o cursor do mouse. Além disso, o sistema agora pode ser "instalado"
  na tela inicial do celular ou tablet como um aplicativo de verdade
  (Progressive Web App): abrindo o site pelo navegador do aparelho e
  usando a opção "Adicionar à tela inicial"/"Instalar app" (o próprio
  navegador oferece essa opção quando os dois requisitos técnicos estão
  presentes — um `manifest.json` descrevendo o app e um "service worker"
  registrado, ambos entregues nesta fase), o ícone da Alphafitus passa a
  aparecer junto dos outros apps do aparelho, e abrir por ele mostra o
  sistema em janela própria, sem a barra de endereço do navegador. Vale a
  pena deixar claro o que esta fase NÃO é: não é um aplicativo nativo
  (Android/iOS) publicado numa loja de aplicativos — este ambiente de
  desenvolvimento não tem acesso a nenhum SDK nativo de celular nem à
  infraestrutura de publicação de uma loja, então essa opção está fora de
  alcance por ora. O que foi entregue é a alternativa tecnicamente honesta
  e totalmente funcional: o MESMO sistema, um único código-fonte, que
  também se comporta e se instala como um app de celular/tablet — sem
  duplicar telas, sem duplicar lógica de negócio, e sem exigir nenhum
  pacote novo (só recursos nativos do navegador). O service worker
  deliberadamente NUNCA guarda em cache nenhuma chamada à API (`/api/...`)
  — só o "shell" do app (HTML/CSS/JS) — para que dado de negócio (saldo de
  estoque, pedido, notificação etc.) seja sempre buscado de verdade, nunca
  uma cópia antiga silenciosa vinda de um cache, o que seria perigoso numa
  fábrica.
- **Fase 39 — APS: MRP (Cálculo de Necessidade de Materiais):** a Fase 25
  já garantia, ao LIBERAR uma ordem de produção, que havia saldo real
  disponível para reservar a BOM (fórmula) inteira — senão recusa com 400,
  citando exatamente o que falta. Mas essa verificação só acontecia ordem
  por ordem, no momento de liberar; para saber, com antecedência, "o que
  vai faltar comprar" somando TODAS as ordens ainda planejadas, era
  preciso abrir ordem por ordem e fazer a conta na mão — e pior, duas
  ordens planejadas que competem pelo mesmo insumo (cada uma sozinha
  parece ter saldo suficiente) só revelam o problema quando somadas.
  Esta fase entrega essa visão consolidada: uma tela nova, **"MRP
  (Necessidade de Materiais)"**, soma a necessidade de cada insumo em
  TODAS as ordens de produção ainda em status `planejada` (deliberado:
  ordens já `liberada`/`em_producao` NÃO entram nessa soma — elas já
  RESERVARAM de verdade seu material ao serem liberadas, Fase 12, então
  contar a composição delas de novo aqui contaria a mesma necessidade
  duas vezes; o que elas já reservaram continua descontado do saldo
  disponível mostrado, através da mesma função `saldo_real_disponivel_producao`
  que a Fase 12 já usa), compara contra o saldo real hoje disponível
  (aprovado em qualidade, já descontando o que outras ordens liberadas,
  vendas confirmadas e ajustes de estoque já comprometeram) e aponta a
  falta — com a lista de quais ordens específicas geram aquela
  necessidade e, para o insumo em falta, quais fornecedores já estão
  homologados para fornecê-lo (reaproveitando o cadastro
  `item_fornecedor_aprovado` que já existia desde a Fase 2), uma ponte
  direta entre o PCP (quem planeja) e Compras (quem resolve a falta).
  Nenhuma tabela nova, nenhuma migração — 100% calculado na hora a partir
  de dados que já existiam (`ordens_producao`, `formula_itens`, `lotes`,
  `item_fornecedor_aprovado`), mesmo espírito de simplicidade já usado na
  Fase 28 (Agenda Visual), que também não precisou de nenhuma tabela
  nova. Endpoint novo (`GET /aps/mrp`) reaproveita a permissão
  `producao.visualizar` que já existia (mesma filosofia da Fase 25: "ver
  a ordem/agenda já é suficiente para ver isto também") — e o perfil
  **Compras** passou a ter essa permissão por padrão (decisão nova desta
  fase, documentada em `seed.py`), já que o relatório existe justamente
  para avisar Compras do que precisa comprar antes que o PCP tente
  liberar uma ordem e seja recusado por falta de saldo.
- **Fase 40 — Conciliação Bancária (Importação de Extrato OFX):** até
  aqui, toda baixa de conta a receber/pagar era registrada manualmente
  no Financeiro — sem nenhum cruzamento automático contra o extrato real
  do banco, o que deixava passar (ou duplicar) lançamentos silenciosamente.
  Esta fase entrega a tela **"Conciliação Bancária"**: o usuário exporta o
  extrato do próprio Internet Banking em formato **OFX** (todo banco tem
  essa opção — "Exportar extrato"/"OFX/Money/Quicken") e importa pela
  tela; o sistema lê cada transação, e quando existe **exatamente um**
  candidato batendo (mesmo valor absoluto, e data dentro de uma janela de
  3 dias — créditos contra `contas_receber_baixas`, débitos contra
  `contas_pagar_baixas`) concilia sozinho na hora; quando existem 0 ou 2+
  candidatos, a transação fica `pendente` para revisão manual — decisão
  deliberada: é sempre mais seguro deixar pendente do que arriscar um
  "quase acerto" errado que ninguém revisaria depois. Reimportar o mesmo
  arquivo (ou um novo extrato com período sobreposto a um anterior) é
  seguro: cada transação é identificada por um ID único que o próprio
  banco fornece (`FITID`), então duplicatas são silenciosamente ignoradas
  na reimportação, nunca contadas ou conciliadas duas vezes. O parser de
  OFX (`app/ofx_parser.py`) foi escrito do zero, sem nenhuma biblioteca
  externa (este ambiente não tem acesso a novos pacotes), tratando o
  formato SGML do OFX 1.x — a maioria dos bancos ainda usa esse formato,
  onde tags de valor como `<TRNAMT>` não têm fechamento, só as tags de
  bloco como `<STMTTRN>` fecham de verdade. As duas tabelas novas
  (`extratos_bancarios`, `extrato_transacoes`) são deliberadamente
  MUTÁVEIS — diferente do ledger de baixas (`contas_receber_baixas`/
  `contas_pagar_baixas`), que continua 100% imutável e nunca é alterado
  por esta fase: conciliar/ignorar/desconciliar só muda o status e o
  vínculo da linha do extrato, nunca toca a baixa em si, e é
  **reversível** (`desconciliar` volta a transação para `pendente` e
  libera a baixa para ser escolhida de novo, por esta ou por outra
  transação). Uma única permissão nova, `financeiro.conciliar_extrato`,
  cobre todo o ciclo (importar, conciliar, ignorar, desconciliar) — sem a
  separação de aprovador que as Fases 22/31 exigem, porque aqui é a
  mesma pessoa revisando a própria importação contra um documento
  externo do banco, não aprovando a solicitação de outra pessoa (mesmo
  raciocínio documentado em `seed.py`).
- **Fase 41 — DRE Completo (Despesas Operacionais e Impostos sobre
  Vendas):** a Fase 20 entregava Receita Bruta − CMV = Lucro Bruto, e
  parava exatamente aí — documentado desde então em "O que ainda falta"
  como faltando despesas operacionais e impostos. Esta fase chega em
  **Lucro Líquido** de verdade, sem nenhuma tabela nova. Despesas
  operacionais (aluguel, salário administrativo, marketing, contas de
  consumo) reaproveitam `contas_pagar` (Fase 6) com uma coluna nova,
  `categoria` ('compra', o padrão — preserva 100% o comportamento de
  quem já usa o sistema — ou 'despesa_operacional'); o DRE soma as
  contas categorizadas como despesa operacional lançadas dentro do
  período (pela data de LANÇAMENTO, mesmo regime de competência já usado
  do lado da receita, que reconhece na expedição, não no recebimento do
  dinheiro) e NUNCA as de categoria 'compra' — essas já estão embutidas
  no CMV via Custeio (Fase 13), contá-las de novo aqui duplicaria o
  custo. Impostos sobre vendas usam um percentual único configurável na
  MESMA linha/tela "Configurar Financeiro" da Fase 33 (que ganhou um
  segundo campo, `percentual_imposto_venda`), aplicado sobre a receita
  bruta do período — uma simplificação deliberada e documentada abaixo
  ("O que ainda falta"): um regime tributário brasileiro real tem várias
  bases e alíquotas diferentes (PIS/COFINS/ICMS/ISS, Simples/Presumido/
  Real), bem mais complexo do que uma alíquota efetiva única. Nenhuma
  permissão nova foi criada: lançar uma despesa operacional reaproveita
  `financeiro.criar_conta_pagar` de sempre (perfil Compras, por padrão —
  mesma segregação de função da Fase 6), e configurar o percentual de
  imposto reaproveita `financeiro.configurar_limite_estorno` da Fase 33
  (mesmo formulário, agora com dois campos).
- **Fase 42 — Painel Gerencial: Filtro por Período:** o Painel Gerencial
  (Fase 7) sempre mostrou só a "situação atual" — uma foto de agora, sem
  filtro nenhum — desde o início, item documentado em "O que ainda
  falta" há várias fases. Esta fase acrescenta um sexto cartão,
  OPCIONAL e aditivo — **"No período"** —, com indicadores de FLUXO (o
  que aconteceu dentro de uma janela `data_inicio`/`data_fim`), no mesmo
  padrão de filtro que o DRE já usa desde a Fase 20/41. Os cinco
  cartões de sempre (Produção, Qualidade, Estoque, Comercial,
  Financeiro) continuam INTACTOS e sempre sem filtro — de propósito:
  saldo de estoque e contas em aberto são o estado ATUAL das coisas, não
  faz sentido "o saldo de estoque de 1º de janeiro", só o saldo de
  agora. Sem os parâmetros, `GET /relatorios/dashboard` devolve
  exatamente o que devolvia antes desta fase, com `periodo.aplicado =
  false` e nenhuma consulta extra rodando — 100% compatível com quem já
  integra com esse endpoint. Com os parâmetros, o cartão novo mostra:
  ordens concluídas, lotes aprovados/reprovados, pedidos expedidos,
  valor expedido, valor recebido e valor pago no período — reaproveitando
  as mesmas colunas de data que o resto do sistema já usa
  (`concluido_em`, `expedido_em`, `criado_em` da baixa) e a mesma regra
  de baixa líquida (baixas normais − estornos) da Fase 14/15. Os exports
  em PDF (Fase 18) e CSV (Fase 19) aceitam os mesmos `data_inicio`/
  `data_fim` e imprimem a mesma seção nova quando o filtro é usado.
  Nenhuma tabela nova, nenhuma permissão nova — reaproveita
  `relatorios.visualizar` de sempre.
- **Fase 56 — DRE: Impostos Detalhados (PIS/COFINS/ICMS/ISS):** a Fase 41
  documentava, em "O que ainda falta", que um regime tributário brasileiro
  real usa várias alíquotas diferentes em vez de um percentual único —
  esta fase entrega exatamente isso, de forma puramente ADITIVA. Quatro
  colunas novas em `configuracoes_financeiro` (`percentual_pis`,
  `percentual_cofins`, `percentual_icms`, `percentual_iss`, migration
  `schema_fase56.sql`, todas `DEFAULT 0`), configuráveis na MESMA tela
  "Configurar Financeiro" e reaproveitando a MESMA permissão já usada
  desde a Fase 33/41 (`configurar_limite_estorno`) — nenhuma permissão
  nova. A decisão de escopo central: as quatro alíquotas novas SOMAM com
  a genérica da Fase 41 (`percentual_imposto_venda`), nunca a substituem
  — uma instalação que já tinha o percentual único configurado continua
  com ele funcionando exatamente igual, e quem quiser detalhar por
  tributo simplesmente soma os quatro em cima, sem precisar reconfigurar
  nada. Cada alíquota é aplicada isoladamente sobre a Receita Bruta do
  período (`impostos_detalhe` na resposta do DRE, com percentual e valor
  de cada tributo) e a soma de todas vira o mesmo `impostos_sobre_vendas`
  de sempre — o KPI "Impostos sobre Vendas" e o cálculo de Lucro Líquido
  continuam existindo sem mudança de forma para quem só olha o total. Na
  tela do DRE, uma tabela nova "detalhamento por tributo" aparece
  listando cada alíquota configurada (> 0) com seu valor no período —
  mas só aparece quando pelo menos uma das cinco está configurada; numa
  instalação nova, sem nada configurado ainda, a tela do DRE fica
  pixel-idêntica à de antes desta fase, sem tabela vazia nem zero
  poluindo a visão. Variações que ainda ficariam de fora se o cliente
  pedir: um regime tributário completo por Simples/Presumido/Real (hoje
  são cinco alíquotas efetivas fixas, sem uma tabela de faixas/regras por
  regime); ICMS com substituição tributária ou diferencial de alíquota
  interestadual (hoje é uma alíquota efetiva única sobre a receita
  bruta, não uma apuração por operação); e um cálculo automático a
  partir da NCM/CFOP de cada item vendido (hoje as cinco alíquotas são
  globais para toda a empresa, não por item ou por operação).
- **Fase 57 — MRP: Lead Time de Compra do Fornecedor:** a Fase 39
  documentava, em "O que ainda falta", que o MRP dizia QUANTO faltava
  comprar mas nunca ATÉ QUANDO, porque o cadastro de fornecedor nunca
  guardou um prazo de entrega. Esta fase fecha essa lacuna com um campo
  novo e OPCIONAL, `lead_time_dias` (migration `schema_fase57.sql`, `NULL`
  por padrão — "prazo não informado"), editável na criação do fornecedor
  ou por uma rota dedicada nova, `PUT /fornecedores/{id}/lead-time`
  (reaproveita `fornecedores.cadastrar` — mesmo risco de editar um dado de
  cadastro, não uma decisão de homologação, por isso NÃO usa
  `fornecedores.homologar`). O MRP passa a calcular, quando possível, uma
  `data_limite_compra` por item em falta: a data de início planejado
  (Agenda Visual do APS, Fase 25/28) da ordem MAIS PRÓXIMA que precisa
  daquele item, menos o lead time do fornecedor sugerido — o mesmo
  primeiro fornecedor homologado (por nome) já usado pela sugestão
  automática da Fase 54. Decisão de escopo deliberada: sem nenhuma ordem
  agendada, OU sem lead time configurado no fornecedor sugerido, NENHUMA
  data é calculada — o MRP mostra o motivo em texto ("nenhuma ordem
  agendada ainda" / "fornecedor sugerido sem lead time configurado") em
  vez de inventar um prazo a partir de informação que não existe. Quando
  "Gerar sugestões de compra" (Fase 54) é clicado, essa data é congelada
  (snapshot, coluna nova `data_limite_compra` em `sugestoes_compra_mrp`)
  no momento da geração — mudar o lead time do fornecedor DEPOIS não
  altera uma sugestão já criada, só o próximo cálculo ao vivo na tela de
  MRP (mesmo princípio de `ordens_relacionadas`, já usado desde a Fase
  54). Nenhuma permissão nova. Variações que ainda ficariam de fora se o
  cliente pedir: MRP de múltiplos níveis / explosão de BOM recursiva e
  considerar um "plano mestre de produção" com demanda futura sem ordem
  ainda criada — ambos já documentados como fora de escopo desde a Fase
  39, e continuam fora aqui; e lead time por ITEM+fornecedor (hoje é um
  valor único por fornecedor, para todos os itens que ele fornece — um
  fornecedor que entrega rápido um item e devagar outro precisaria de um
  cadastro só para o pior caso).

Tudo isso com uma interface de verdade para usar pelo navegador, não só por
linha de comando. Este é o núcleo sobre o qual as próximas fases
(faturamento fiscal, relatórios mais avançados) serão construídas — a
estrutura de migrações incrementais (ver `migrations/`) garante que
instalar as próximas fases nunca vai apagar ou exigir recriar os dados que
você já tiver cadastrado.

## Acessando pelo navegador

Depois de seguir os passos de instalação abaixo e o servidor estar
rodando, abra `http://127.0.0.1:5000` (ou o endereço do servidor na rede
da empresa) em qualquer navegador. A tela de login aparece imediatamente —
não precisa de nenhuma instalação adicional no computador de quem vai usar
o sistema no dia a dia, só um navegador. O frontend foi escrito em
JavaScript puro (sem framework, sem etapa de build, sem depender de nenhum
CDN externo) exatamente para funcionar sem sobressaltos mesmo numa rede de
fábrica com firewall restritivo.

## Sobre a escolha de tecnologia nesta entrega

O documento de arquitetura (seção 3.1) recomendava .NET (C#) + PostgreSQL.
O ambiente de desenvolvimento usado para *escrever e testar* esta Fase 1 não
tinha acesso de rede para instalar o SDK do .NET nem novos pacotes, então
esta entrega foi implementada em **Python (Flask) + SQLite** — o que estava
disponível para eu conseguir rodar os testes automatizados de verdade antes
de te entregar, em vez de te dar código não verificado.

Isso não é um desvio "escondido" da arquitetura: todas as regras de
negócio, segurança e auditoria do documento foram mantidas 100% —
permissão granular por ação, trilha de auditoria append-only, 2FA,
segregação de função, bloqueio por tentativas de login. Só a linguagem do
backend e o banco de desenvolvimento mudaram. Se você preferir seguir com
.NET/PostgreSQL de fato (como aprovado originalmente), qualquer ambiente
com internet liberada consegue instalar o SDK e eu reescrevo este mesmo
módulo em C# a partir desta especificação — me avise.

Python + Flask, aliás, roda muito bem como serviço do Windows (via NSSM ou
`waitress` + Task Scheduler) e SQLite pode seguir sendo usado em produção
para uma empresa deste porte sem problema — mas PostgreSQL fica preparado
como caminho de crescimento (ver seção "Migrando para PostgreSQL" abaixo).

## Estrutura do projeto

```
backend/
  app/
    __init__.py       # fábrica da aplicação Flask, tratamento de erros
    db.py              # conexão SQLite e inicialização do schema
    security.py        # hashing de senha (PBKDF2), TOTP (2FA), JWT
    audit.py            # gravação e consulta da trilha de auditoria
    context.py           # extração do usuário autenticado a partir do JWT
    permissions.py         # decorator de autorização granular por ação
    routes/
      auth.py               # login, 2FA, refresh, logout, sessões, /me
      usuarios.py             # CRUD de usuários e atribuição de perfis
      perfis.py                 # CRUD de perfis e suas permissões
      permissoes.py               # catálogo de permissões (somente leitura)
      empresas.py                   # empresas e unidades/depósitos/laboratórios
      auditoria.py                    # consulta (somente leitura) da trilha
      documentos.py                     # documentos controlados (escopo mínimo)
      notificacoes.py                     # notificações do usuário
      itens.py                              # [Fase 2] cadastro de itens/materiais
      fornecedores.py                         # [Fase 2] fornecedores e homologação
      lotes.py                                  # [Fase 2/3] recebimento, quarentena, aprovação, CoA (registro + PDF na Fase 10), rastreabilidade
      analises.py                                 # [Fase 2] LIMS: solicitação, resultados, conclusão
      desvios.py                                    # [Fase 2] desvios/CAPA
      formulas.py                                     # [Fase 3] fórmulas/BOM, versionamento e ativação
      producao.py                                       # [Fase 3] ordens de produção, consumo, genealogia
      estoque.py                                          # [Fase 4] posições, movimentações (ledger append-only), FEFO
      comercial.py                                          # [Fase 5] clientes, pedidos de venda, reserva/expedição
      financeiro.py                                           # [Fase 6] contas a receber/pagar, baixas (ledger append-only)
      relatorios.py                                             # [Fase 7] painel gerencial — agregação somente-leitura, sem schema novo
      rastreabilidade.py                                          # [Fase 8] genealogia recursiva + simulação de recall (snapshot imutável)
                                                                       # [Fase 9] apontamento de perdas/refugo vive dentro de producao.py (concluir())
      custeio.py                                                        # [Fase 13] custo real de ordem + custo projetado por produto, 100% derivado
                                                                             # [Fase 14] estorno de baixa vive dentro de financeiro.py (estornar_baixa_receber/pagar)
      memorial.py                                                             # [Fase 24] Memorial Técnico ANVISA — empresas, produtos, memoriais, assinaturas, histórico, dashboard
  migrations/
    schema.sql          # schema SQLite Fase 1 (com notas de portabilidade p/ PostgreSQL)
    schema_fase2.sql     # schema SQLite Fase 2 — aplicado por cima do anterior, sem apagar dados
    schema_fase3.sql      # schema SQLite Fase 3 — idem, só adiciona (inclui 2 novas colunas em `lotes`)
    schema_fase4.sql       # schema SQLite Fase 4 — idem, adiciona posições e o ledger de estoque
    schema_fase5.sql         # schema SQLite Fase 5 — idem, adiciona clientes/pedidos/reservas
    schema_fase6.sql           # schema SQLite Fase 6 — idem, adiciona preço em itens de pedido + contas a receber/pagar
    # (Fase 7 não adiciona migração — é agregação pura sobre tabelas já existentes)
    schema_fase8.sql             # schema SQLite Fase 8 — idem, adiciona só a tabela imutável simulacoes_recall
    schema_fase9.sql               # schema SQLite Fase 9 — idem, adiciona quantidade_perda/motivo_perda em ordens_producao
    # (Fase 10 não adiciona migração — é 100% export/leitura sobre tabelas já existentes desde a Fase 2)
    # (Fase 11 não adiciona migração — é 100% export/leitura sobre a tabela simulacoes_recall já existente desde a Fase 8)
    schema_fase12.sql               # schema SQLite Fase 12 — idem, adiciona só a tabela imutável ordem_producao_reservas
    schema_fase13.sql                 # schema SQLite Fase 13 — idem, adiciona só a coluna opcional lotes.custo_unitario
    schema_fase14.sql                   # schema SQLite Fase 14 — idem, adiciona estorno_de_id + motivo_estorno em contas_receber_baixas/contas_pagar_baixas
    # (Fase 15 não adiciona migração — é 100% agregação/leitura sobre contas a receber/pagar já existentes)
    # (Fase 16 não adiciona migração — é 100% reaproveitamento do bloqueio de lote já existente desde a Fase 2)
    schema_fase17.sql                     # schema SQLite Fase 17 — idem, adiciona contagens_inventario/contagens_inventario_itens (mutáveis, sem gatilho append-only, ao contrário do ledger de estoque)
    # (Fase 18 não adiciona migração — é 100% export/leitura sobre a mesma agregação do dashboard já existente desde a Fase 7)
    # (Fase 19 não adiciona migração — mesmo motivo da Fase 18, só num formato de arquivo diferente)
    # (Fase 20 não adiciona migração — é 100% agregação/leitura sobre pedidos/custeio já existentes)
    schema_fase21.sql                       # schema SQLite Fase 21 — idem, adiciona aprovacao_status/aprovado_por/aprovado_em/motivo_rejeicao em contagens_inventario_itens
    schema_fase22.sql                         # schema SQLite Fase 22 — idem, adiciona as tabelas mutáveis estornos_pendentes_receber/estornos_pendentes_pagar (as baixas em si continuam append-only desde a Fase 6)
    # (Fase 23 não adiciona migração — reaproveita a mesma coluna "codigo" já UNIQUE desde a Fase 2, só muda a regra de aplicação em app/routes/itens.py)
    schema_fase24.sql                           # schema SQLite Fase 24 — módulo novo: memorial_empresas, memorial_produtos, memoriais, memorial_assinaturas, memorial_historico (append-only só contra UPDATE)
  tests/
    test_fase1.py        # 14 testes automatizados da Fase 1
    test_fase2.py         # 9 testes automatizados da Fase 2 (fluxo de qualidade completo)
    test_fase3.py          # 8 testes automatizados da Fase 3 (fórmulas, ordens, genealogia)
    test_fase4.py           # 20 testes automatizados da Fase 4 (posições, endereçamento, transferência, ajuste, baixa, FEFO)
    test_fase5.py            # 20 testes automatizados da Fase 5 (clientes, pedidos, confirmação FEFO, expedição, cancelamento)
    test_fase6.py             # 26 testes automatizados da Fase 6 (conta a receber automática, baixas, contas a pagar, segregação)
    test_fase7.py              # 5 testes automatizados da Fase 7 (agregação batendo com cenário real, banco vazio, permissões)
    test_fase8.py               # 17 testes automatizados da Fase 8 (genealogia recursiva de dois níveis, snapshot de recall, permissões)
    test_fase9.py                 # 11 testes automatizados da Fase 9 (perda/refugo, validações, percentuais, auditoria, permissão reutilizada)
    test_fase10.py                  # 7 testes automatizados da Fase 10 (PDF gerado, magic bytes, sem CoA ainda, auditoria, permissão reutilizada)
    test_fase11.py                    # 5 testes automatizados da Fase 11 (PDF do relatório de recall gerado, 404, auditoria, permissão reutilizada)
    test_fase12.py                      # 11 testes automatizados da Fase 12 (reserva via FEFO ao liberar, append-only, integração bidirecional com Comercial/Estoque, permissão reutilizada)
    test_fase13.py                        # 15 testes automatizados da Fase 13 (custo médio, custo do lote/ordem, custo com perdas, custo projetado por produto, permissão nova nos dois sentidos)
    test_fase14.py                          # 16 testes automatizados da Fase 14 (estorno total/parcial, não estornar duas vezes, não estornar um estorno, motivo obrigatório, append-only, permissão própria nos dois sentidos, regressão do Painel Gerencial)
    test_fase15.py                            # 19 testes automatizados da Fase 15 (fronteiras de bucket, saldo acumulado, exclusão de contas pagas/canceladas, baixa parcial, regressão do estorno, banco vazio, permissão reutilizada)
    test_fase16.py                              # 12 testes automatizados da Fase 16 (bloqueio bidirecional upstream/downstream, não mexe em pedido expedido, motivo obrigatório, idempotência, status recalculado no detalhe do recall, permissão própria, regressão do bloqueio individual)
    test_fase17.py                                # 15 testes automatizados da Fase 17 (contagem geral auto-popula, conclusão sem/com divergência, bloqueio de conclusão com pendente, contagem cíclica manual, item duplicado, cancelamento exige motivo, segregação contagem x ajustar, bordas)
    test_fase18.py                                  # 5 testes automatizados da Fase 18 (PDF gerado com sucesso, banco vazio ainda gera PDF válido, idempotência/não altera dado nenhum, auditoria, permissão reutilizada nos dois sentidos)
    test_fase19.py                                    # 5 testes automatizados da Fase 19 (CSV gerado com sucesso e com BOM/seções/valores esperados, banco vazio ainda gera CSV válido, idempotência, auditoria, permissão reutilizada nos dois sentidos)
    test_fase20.py                                      # 6 testes automatizados da Fase 20 (cálculo determinístico de receita/CMV/lucro/margem, banco vazio, pedido não-expedido excluído, custo incompleto quando lote sem custo, filtro de período, permissão reutilizada nos dois sentidos)
    test_fase21.py                                        # 12 testes automatizados da Fase 21 (divergência grande fica pendente sem ajustar, divergência pequena continua ajustando na hora, saldo inicial zero é sempre grande, aprovar/rejeitar por outro usuário, segregação de função quem contou x quem aprova, permissão, lista de pendências)
    test_fase22.py                                          # 10 testes automatizados da Fase 22 (abaixo do limiar reverte na hora, acima do limiar fica pendente sem reverter, não permite segunda solicitação pendente, aprovar/rejeitar por outro usuário, segregação de função quem solicitou x quem aprova, permissão, lista consolidada, espelho receber/pagar)
    test_fase23.py                                            # 10 testes automatizados da Fase 23 (código gerado ao omitir o campo, prefixo por tipo, sequência incrementando, sequências independentes por tipo, código manual antigo não atrapalha a sequência, código informado continua funcionando, duplicado ainda dá 409, descrição/tipo ainda validados, código aparece na listagem)
    test_fase24.py                                              # 26 testes automatizados da Fase 24 (empresas, produtos, código/certificado automático, edição de conteúdo, fluxo de status, histórico, assinaturas, auto-aprovação com 2 assinaturas + concluído, segregação de exclusão, permissões, dashboard, progresso de preenchimento por seção)
    test_fase25.py                                                # 21 testes automatizados da Fase 25 (centros de trabalho, capacidade esgotada/liberada, sobreposição de horário, reagendamento, desagendamento, permissões)
    test_fase26.py                                                  # 11 testes automatizados da Fase 26 (lista dos 10 catálogos, catálogo inexistente 404, CRUD completo com campo obrigatório, defaults e merge parcial na edição, campo booleano, ordenação, permissões)
    test_fase27.py                                                    # 10 testes automatizados da Fase 27 (upload/listagem/download/exclusão de anexo, data URL, base64 inválido, arquivo acima do limite, anexo de outro memorial não encontrado, padronização nula por padrão, criar/editar com merge parcial, permissões dos dois recursos)
  frontend/
    index.html              # página única da aplicação
    static/
      app.js                  # toda a lógica do frontend (JS puro, sem build) — Fase 1 a 24
      styles.css                # tema claro/escuro, layout, componentes
  seed.py                 # popula permissões, perfis padrão e o admin inicial
  run.py                    # ponto de entrada (desenvolvimento)
  requirements.txt
```

Fora da pasta `backend/`, o pacote entregue também inclui:
```
tests_e2e/
  teste_fase1_navegador.js   # teste automatizado num navegador real (Playwright) — Fase 1
  teste_fase2_navegador.js    # idem, cobrindo as telas de Itens/Fornecedores/Lotes/Desvios
  teste_fase3_navegador.js     # idem, cobrindo Fórmulas, Ordens de Produção e genealogia de lote
  teste_fase4_navegador.js      # idem, cobrindo a tela de Estoque (WMS) — posições, endereçamento, transferência, ajuste, baixa, FEFO
  teste_fase5_navegador.js       # idem, cobrindo Comercial (CRM) — cliente, pedido, confirmação, expedição, segregação de função
  teste_fase6_navegador.js        # idem, cobrindo Financeiro — conta a receber automática, baixas, contas a pagar, segregação Compras/Financeiro
  teste_fase7_navegador.js         # idem, cobrindo o Painel Gerencial (BI) — números agregados batendo com o cenário real, segregação Diretoria/Vendedor
  teste_fase8_navegador.js          # idem, cobrindo Rastreabilidade/Recall — árvore de genealogia de dois níveis, registro e detalhe de uma simulação, segregação Qualidade/Diretoria/Vendedor
  teste_fase9_navegador.js           # idem, cobrindo apontamento de perda/refugo — validação de motivo obrigatório, percentuais corretos, compatibilidade com conclusão sem perda
  teste_fase10_navegador.js            # idem, cobrindo o download do CoA em PDF — nome do arquivo, magic bytes, botão ausente sem CoA emitido
  teste_fase11_navegador.js             # idem, cobrindo o download do Relatório de Recall em PDF — nome do arquivo, magic bytes, permissão reutilizada (Diretoria)
  teste_fase12_navegador.js              # idem, cobrindo a reserva de material visível na tela de detalhe da ordem, liberação recusada por saldo real insuficiente, permissão reutilizada (PCP)
  teste_fase13_navegador.js               # idem, cobrindo as duas abas de custo no detalhe da ordem, a tela "Custo do Produto", e a segregação de custeio.visualizar nos dois sentidos (Financeiro x PCP)
  teste_fase14_navegador.js                # idem, cobrindo estorno de baixa (a receber e a pagar) — botão "Ver baixas"/"Estornar", motivo obrigatório, bloqueio de estornar duas vezes
  teste_fase15_navegador.js                 # idem, cobrindo o cartão "Fluxo de Caixa Projetado" no Painel Gerencial — valores por faixa de dias, saldo acumulado, destaque visual da faixa "Vencido"
  teste_fase16_navegador.js                  # idem, cobrindo o bloqueio em massa a partir do detalhe de um recall — status "antes"/"depois" de cada lote afetado, botão que some quando não há mais nada a bloquear
  teste_fase17_navegador.js                   # idem, cobrindo o card "Contagem de Inventário" na tela Estoque — contagem geral auto-populada, registro de contagem com divergência, botão "Concluir" habilitado só sem pendentes, saldo físico corrigido após concluir
  teste_fase18_navegador.js                    # idem, cobrindo o botão "Baixar PDF" no Painel Gerencial — download capturado via evento nativo do Chromium, nome de arquivo com a data do dia, magic bytes %PDF, perfil sem relatorios.visualizar nem vê o link do painel no menu
  teste_fase19_navegador.js                     # idem, cobrindo o botão "Baixar CSV" ao lado do "Baixar PDF" — download capturado via evento nativo do Chromium, nome de arquivo com a data do dia, BOM UTF-8, seções esperadas no conteúdo
  teste_fase20_navegador.js                      # idem, cobrindo a tela "DRE Simplificado" — receita/CMV/lucro/margem batendo com um cenário determinístico, filtro de período restringindo a lista de pedidos, permissão reutilizada nos dois sentidos (PCP sem menu, Financeiro com menu e tela)
  teste_fase21_navegador.js                       # idem, cobrindo o detalhe da contagem de inventário — aprovar/rejeitar um ajuste de divergência grande por um segundo usuário, recusa da auto-aprovação por quem contou o item, aviso de pendência e ausência dos botões de decisão para quem não tem a permissão nova
  teste_fase22_navegador.js                        # idem, cobrindo o modal "Ver baixas" em Financeiro — aprovar/rejeitar um estorno acima do valor de alçada por um segundo usuário (receber e pagar), recusa da auto-aprovação por quem solicitou o estorno, aviso de pendência e ausência dos botões de decisão para o perfil Compras
  README.md                    # como reexecutar esses testes, se quiser
```

## Instalador automático (mais fácil, para quem só quer usar o sistema)

Se você só quer instalar e usar o Alphafitus OS (não vai mexer no
código), existe um instalador que faz os passos 1-6 abaixo automaticamente
— veja a pasta `installer/` entregue junto com este pacote
(`installer/README.md` tem todos os detalhes, incluindo as limitações de
eu não ter testado num Windows real). Os passos manuais abaixo continuam
válidos e são o caminho recomendado para quem vai desenvolver ou já sabe
usar terminal.

A partir da Fase 68, existem DOIS instaladores, um para a máquina que vai
ser o **servidor** e outro (bem mais leve) para as demais máquinas que só
vão **acessar** o sistema pelo navegador ("terminais") — ver a seção
"Fase 68 — Servidor e Terminais" mais abaixo para o passo a passo
completo, incluindo acesso pela rede local e pela internet.

## Como rodar no Windows

1. **Instale o Python 3.11 ou mais recente**: baixe em
   https://www.python.org/downloads/windows/ e marque a opção "Add Python
   to PATH" durante a instalação.

2. **Copie esta pasta `backend/` para o computador/servidor da Alphafitus**
   (ex.: `C:\AlphafitusOS\backend`).

3. **Abra o PowerShell nessa pasta** e crie um ambiente virtual:
   ```powershell
   cd C:\AlphafitusOS\backend
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Defina as variáveis de ambiente obrigatórias** (no PowerShell, ou de
   forma permanente em Painel de Controle → Variáveis de Ambiente):
   ```powershell
   $env:ALPHAFITUS_JWT_SECRET = python -c "import secrets;print(secrets.token_hex(32))"
   $env:ALPHAFITUS_DB_PATH = "C:\AlphafitusOS\dados\alphafitus.db"
   $env:ALPHAFITUS_ADMIN_EMAIL = "admin@alphafitus.com.br"
   ```
   Guarde o valor de `ALPHAFITUS_JWT_SECRET` em local seguro — se ele mudar,
   todos os usuários são deslogados. Não o coloque em nenhum repositório
   Git.

5. **Crie o banco e o usuário administrador inicial:**
   ```powershell
   python -c "from app import db; db.init_db()"
   python seed.py
   ```
   O terminal vai imprimir a senha gerada para o e-mail definido em
   `ALPHAFITUS_ADMIN_EMAIL` — **copie e guarde agora**, ela não aparece de
   novo (só o hash é salvo). No primeiro login o sistema pede para trocar
   essa senha (via `POST /api/v1/auth/trocar-senha`).

6. **Rode o servidor** (ainda dentro do ambiente virtual):
   ```powershell
   waitress-serve --host=0.0.0.0 --port=5000 run:app
   ```
   `waitress` é um servidor de produção puro-Python (sem compilação nativa),
   por isso é a opção recomendada no Windows em vez do servidor de
   desenvolvimento do Flask. `--host=0.0.0.0` deixa o servidor acessível a
   partir de outros computadores da mesma rede (não só desta máquina) — ver
   a seção "Fase 68 — Servidor e Terminais" para o cenário completo de rede
   local/internet; se quiser deixar acessível só nesta máquina, use
   `--host=127.0.0.1`.

7. **Para deixar rodando sempre, mesmo após reiniciar o computador**, use o
   Serviço do Windows nativo do próprio Alphafitus OS (Fase 68 —
   `service_windows.py`, com o atalho "Instalar como Serviço do Windows"
   criado pelo instalador): reinicia sozinho, funciona sem ninguém logado,
   e não depende de nenhuma ferramenta de terceiros. Ver a seção "Fase 68 —
   Servidor e Terminais" abaixo para o passo a passo.

## Fase 68 — Servidor e Terminais (instalação real, rede local e internet)

Pensado para o cenário: UM computador roda o Alphafitus OS de verdade (o
"servidor"), e os demais computadores da empresa só **acessam** o sistema
pelo navegador, sem instalar nada pesado (os "terminais") — inclusive de
fora do escritório, pela internet, se precisar.

### 1. Instalando o servidor

Use `installer/AlphafitusOS_Servidor_Instalar.exe`, mas **clique com o
botão direito nele e escolha "Executar como administrador"** — isso é o
que diferencia uma instalação "de verdade" (Arquivos de Programas, aparece
em "Aplicativos e Recursos", pode virar Serviço do Windows) de uma
instalação simples (sem esses três itens, mas funcionando igual no dia a
dia). Sem "Executar como administrador", o instalador funciona do mesmo
jeito de sempre (Fase 22 em diante) — só cai automaticamente para a
instalação simples e avisa isso na tela.

Depois de instalado (e do primeiro uso normal, criando o usuário
administrador etc. — mesmos passos de sempre, numa janela que abre
sozinha), use os atalhos criados no Menu Iniciar, dentro da pasta
"Alphafitus OS":

- **Instalar como Serviço do Windows** — faz o sistema iniciar sozinho
  junto com o Windows, mesmo sem ninguém logar, sem nenhuma janela aberta,
  e reiniciar sozinho se cair. Pede confirmação de Administrador.
- **Iniciar Serviço** / **Parar Serviço** / **Status do Serviço** —
  gerenciar o dia a dia depois de instalado.
- **Remover Serviço do Windows** — volta a exigir abrir manualmente pelo
  atalho comum, sem desinstalar nada.

Sem instalar como serviço, o sistema também funciona normalmente pelo
atalho comum ("Alphafitus OS") — só precisa deixar aquela janela aberta
enquanto estiver em uso, como sempre foi.

### 2. Descobrindo o endereço do servidor

Toda vez que o Alphafitus OS inicia (pelo atalho comum ou pelo Serviço do
Windows), a tela mostra o(s) endereço(s) desta máquina na rede local, algo
como:

```
  http://192.168.1.10:5000
```

Anote esse endereço — é ele que as outras máquinas ("terminais") vão usar.
Se o servidor tiver mais de uma placa de rede (ex.: Wi-Fi e cabo), pode
aparecer mais de um endereço; use o que os terminais realmente conseguem
alcançar (normalmente o da mesma rede Wi-Fi/cabo do escritório).

### 3. Instalando um terminal

Nos outros computadores, use `installer/Terminal_Instalar.bat` (não
precisa "Executar como administrador", e não precisa ter Python instalado
nessa máquina — é só um atalho, o sistema continua rodando só no
servidor). Ele pergunta o endereço do servidor (o do passo 2) e cria um
atalho "Alphafitus OS" na Área de Trabalho e no Menu Iniciar que abre o
navegador direto na tela de login. Se o endereço do servidor mudar no
futuro, rode o `Terminal_Instalar.bat` de novo com o endereço novo — ele
só atualiza o atalho existente.

Cada terminal continua usando login e senha individuais (o controle de
quem pode ver/fazer o quê continua sendo o mesmo sistema de perfis e
permissões de sempre, por usuário — nada muda aí).

### 4. Acesso pela internet (fora da rede local)

O endereço do passo 2 (`http://192.168.1.10:5000` ou parecido) só funciona
**dentro da mesma rede local** do servidor. Para acessar de fora (outra
loja, home office, celular fora do Wi-Fi da empresa), **não recomendo**
simplesmente abrir a porta 5000 no roteador (isso expõe o sistema
diretamente à internet sem criptografia — o login e a navegação passariam
em texto simples, visível para qualquer um no meio do caminho).

O caminho recomendado é uma **VPN de malha (mesh VPN)** como o
[Tailscale](https://tailscale.com) (tem plano gratuito, suficiente para
uma empresa pequena): instala um programinha pequeno tanto no servidor
quanto em cada terminal que for acessar de fora, cria uma rede privada
criptografada entre eles (sem precisar mexer no roteador nem ter IP fixo),
e dá um endereço fixo tipo `alphafitus-servidor` que funciona de qualquer
lugar com internet, exatamente como se estivesse na rede local. Depois de
configurado, é só usar esse endereço (em vez do IP da rede local) no passo
3 acima.

Se a empresa já tiver um domínio próprio e alguém que administre isso,
outra opção válida é um túnel reverso como o [Cloudflare
Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
(exige uma conta Cloudflare e um domínio) — dá um endereço HTTPS de
verdade, mas tem mais passos de configuração do que o Tailscale. Qualquer
uma das duas opções evita a necessidade de abrir portas no roteador.

### 5. Desinstalando

O atalho "Desinstalar Alphafitus OS" (Menu Iniciar) remove o Serviço do
Windows (se tiver instalado), os atalhos e o ambiente Python, mas
preserva a pasta `data\` (o banco de dados) por segurança — apague-a
manualmente depois, se realmente não precisar mais dos dados.

## Como testar

### Testes automatizados (o que eu já rodei antes de te entregar)
```powershell
python -m unittest discover -s tests -v
```
Devem passar **741 testes** no total (o número cresce a cada fase nova — o
comando acima sempre mostra a contagem exata e atual, é a fonte de
verdade). A quebra por fase abaixo cobre 1 a 27; cada fase entregue depois
disso (28 em diante) trouxe seu próprio arquivo `tests/test_faseNN.py`, na
mesma convenção — a Fase 37, por exemplo, é `test_fase37.py` com 25 testes
novos, cobrindo o serviço de notificação/e-mail em si (criar, enviar,
capturar falha, excluir quem disparou a pendência — sempre com o envio
real de e-mail substituído por um dublê via `unittest.mock`, nenhum teste
toca rede de verdade), a API de "minhas notificações"
(contagem/marcar lida/preferência), o CRUD da configuração de SMTP
(nunca devolve a senha salva, testar-e-mail com sucesso/falha), e os
gatilhos de negócio reais ponta a ponta (ajuste de contagem com
divergência grande e as quatro filas do financeiro, confirmando que o
aprovador é notificado e quem disparou a pendência não é): 14 da Fase 1 + 9 da Fase 2 + 8 da Fase 3 + 20 da
Fase 4 + 20 da Fase 5 + 26 da Fase 6 + 5 da Fase 7 + 17 da Fase 8 + 11 da
Fase 9 + 7 da Fase 10 + 5 da Fase 11 + 11 da Fase 12 + 15 da Fase 13 + 16 da
Fase 14 + 19 da Fase 15 + 12 da Fase 16 + 15 da Fase 17 + 5 da Fase 18 + 5 da
Fase 19 + 6 da Fase 20 + 12 da Fase 21 + 10 da Fase 22 + 10 da Fase 23 + 26 da
Fase 24 + 21 da Fase 25 + 11 da Fase 26 + 10 da Fase 27 + ... (fases 28-35,
cada uma no seu próprio arquivo) + 22 da Fase 36 + 25 da Fase 37. A Fase 38
não trouxe teste unitário novo — é inteiramente frontend (CSS/JS) mais dois
arquivos estáticos (`manifest.json`/`sw.js`), sem regra de negócio nova
para testar de forma unitária; a cobertura dela é o teste de navegador
(ver "Como testar (na prática, pelo navegador)" mais abaixo), que emula
viewport de celular e de tablet de verdade. A Fase 39 é `test_fase39.py`
com 12 testes novos, cobrindo o cálculo do MRP em si: soma correta da
necessidade quando duas ordens planejadas competem pelo mesmo insumo,
ordem liberada não soma na necessidade mas sua reserva reduz o saldo
disponível mostrado (confirmando a integração com a mesma função de
saldo real da Fase 12), lote reprovado/em quarentena não conta como
disponível, item sem nenhuma ordem planejada não aparece no relatório,
ordenação por maior falta primeiro, filtro de fornecedores homologados
só por status aprovado, e a permissão (inclusive o perfil Compras
passando a ver o relatório). A Fase 40 é `test_fase40.py` com **17 testes
novos**: 3 testam o parser de OFX isoladamente (crédito e débito
corretos, arquivo inválido levanta erro, transação sem valor é pulada
sem quebrar o resto do arquivo), 6 testam importação e conciliação
automática (candidato único concilia sozinho tanto para crédito quanto
para débito, nenhum candidato fica pendente, dois candidatos ambíguos
ficam pendentes e aparecem nas sugestões, reimportar o mesmo arquivo não
duplica nada, arquivo inválido devolve 400), 5 testam a conciliação
manual (escolher um candidato pela tela, não é possível vincular a
mesma baixa a duas transações diferentes — 409, ignorar exige motivo,
desconciliar libera a baixa para outra transação, não é possível
ignorar uma transação já conciliada), e 2 testam a permissão
(`financeiro.conciliar_extrato` — 403 sem ela, perfil Financeiro
consegue o ciclo completo com ela). A Fase 41 é `test_fase41.py` com
**14 testes novos**: 7 testam despesas operacionais (só a categoria
certa entra no DRE, categoria omitida assume 'compra' por padrão —
regressão, categoria inválida é rejeitada, despesa cancelada não conta,
filtro por data de lançamento, listagem filtra por categoria, e nenhuma
permissão nova foi exigida — testado com o perfil Compras, que já tinha
`criar_conta_pagar`), 5 testam o imposto sobre vendas (percentual padrão
zero, configurar aplica no DRE, fora da faixa 0-100 é rejeitado, omitir
o campo preserva o valor já configurado — regressão central desta fase,
e a mesma permissão de sempre é exigida para configurar), e 2 testam o
Lucro Líquido completo (cálculo combinando receita + despesas
operacionais + imposto dá o número certo, banco vazio não quebra). A
Fase 42 é `test_fase42.py` com **9 testes novos**: 2 confirmam que sem
filtro o comportamento é idêntico ao de antes desta fase
(`periodo.aplicado = false` e os cinco cartões antigos intactos), 3
testam o filtro com um cenário real (números batem dentro do período,
somem quando o evento está fora da janela e voltam a aparecer na janela
certa, e uma baixa de estorno se cancela com a baixa original no valor
líquido do período — mesma regra da Fase 14/15), e 4 testam permissão e
os exports (reaproveita `relatorios.visualizar` sem permissão nova,
403 sem ela mesmo com o filtro, PDF e CSV aceitam os mesmos parâmetros
e o CSV só imprime a seção "No período" quando o filtro é usado). A
Fase 43 é `test_fase43.py` com **10 testes novos**: 3 testam o conteúdo
do memorial em si (memorial sem nenhum anexo já gera um PDF válido com
o texto dos campos preenchidos, memorial inexistente dá 404, e a
exportação registra evento de auditoria), 5 testam a incorporação de
anexos (um PDF de verdade cresce o arquivo final e seu CONTEÚDO aparece
no texto extraído do PDF combinado — não só o nome do anexo; uma imagem
é convertida e incorporada; um anexo de tipo não suportado, como uma
planilha, NUNCA quebra a exportação — só aparece na página de apêndice;
o mesmo vale para um PDF corrompido; e excluir um anexo faz ele sumir
do PDF Completo na exportação seguinte), e 2 testam permissão
(reaproveita `memoriais.visualizar` — testado com o perfil Regulatório,
que já tinha essa permissão — sem nenhuma nova, e 403 para quem não
tem). A Fase 44 é `test_fase44.py` com **11 testes novos**: 2 testam a
atualização automática de `ultimo_acesso_em` (qualquer requisição
autenticada marca o próprio usuário como online; um usuário recém-criado
que nunca fez login sequer aparece com o campo NULL, sem quebrar o
cálculo), 2 testam a janela de tolerância de 5 minutos (dentro da janela
aparece online, fora aparece offline mas com o timestamp preservado — a
diferença entre "nunca acessou" e "acessou e saiu"), 1 confirma que a
janela em minutos vem na resposta, 1 confirma que quem está online
aparece antes de quem está offline mesmo fora de ordem alfabética, 1
confirma que um usuário inativado desaparece da lista, 2 testam a
permissão (reaproveita `usuarios.visualizar` — 403 sem ela, testado com o
perfil Vendedor que não tem, e funciona para qualquer perfil que tenha,
não só o Administrador seedado), e 2 testam um banco com o mínimo
possível de usuários (só o admin, e o admin mais um usuário que nunca
acessou) sem quebrar. A Fase 45 é `test_fase45.py` com **11 testes
novos**: 5 testam a geração do arquivo em si (as duas abas esperadas —
"Painel Gerencial" e "Fluxo de Caixa Projetado" — existem, os valores do
cenário aparecem corretamente na aba Painel Gerencial, a célula de valor
monetário tem formatação de moeda de verdade aplicada, banco vazio ainda
gera um arquivo válido, e gerar o arquivo não altera nenhum dado de
negócio), 2 testam a aba de Fluxo de Caixa (a linha de Total usa uma
fórmula `=SUM(...)` DE VERDADE, escrita na própria célula — não um valor
já somado em Python — e o total de "Saldo acumulado" copia o último
valor da série em vez de somar todos os buckets, que seria
matematicamente errado), 2 testam o filtro de período da Fase 42 (com o
filtro aparece uma terceira seção "No período" na aba Painel Gerencial,
sem o filtro ela não aparece), e 2 testam auditoria e permissão
(reaproveita `relatorios.visualizar` de sempre — 403 sem ela, e o perfil
Diretoria, que só tem essa permissão, consegue gerar o arquivo). A Fase 46
é `test_fase46.py` com **17 testes novos**: 4 testam a exportação em si
(o snapshot de um banco vazio já gera as 8 tabelas presentes e zeradas —
não faltando nenhuma, o snapshot reflete fielmente um cenário cadastrado
via API, o download tem o nome de arquivo e o `Content-Type` esperados, e
exportar registra evento de auditoria sem alterar nenhum dado), 3 testam
a restauração em si (restaurar um snapshot anterior desfaz o que foi
cadastrado depois dele, os IDs originais dos registros são preservados
— não vira uma cópia com IDs novos, o que quebraria qualquer referência
já existente fora do módulo, e o evento de auditoria registra a
contagem de linhas restauradas por tabela), 4 testam a validação de
formato do arquivo enviado (corpo que não é JSON, JSON sem o campo
"tabelas", JSON faltando uma das 8 tabelas, e um registro que não é um
objeto válido — todos rejeitados com 400 antes de tocar no banco), 3 são
as garantias de "tudo ou nada" via `SAVEPOINT` (um snapshot com um
produto apontando para uma empresa inexistente — violação de chave
estrangeira — não altera absolutamente nada, mesma coisa para uma
referência a um usuário inexistente, e depois de uma restauração falhar
no meio, uma restauração BOA imediatamente depois ainda funciona —
confirmando que o `SAVEPOINT` foi de fato liberado/desfeito, não deixado
pendurado), e 3 testam permissão (exportar exige `memoriais.visualizar`
— 403 sem ela; restaurar exige `memoriais.excluir` — ter só
`memoriais.visualizar` não basta, e 403 nesse caso; e um perfil
customizado com `memoriais.excluir` de verdade consegue restaurar). A
Fase 47 é `test_fase47.py` com **10 testes novos**: 5 testam o download em
si (nome de arquivo e `Content-Type` binário esperados, o conteúdo
baixado tem a assinatura binária OFICIAL de um arquivo SQLite — não só um
`Content-Type` de mentirinha, o backup contém tabelas de QUALQUER módulo
— não só do Memorial Técnico, testado com `usuarios` e `permissoes`, que
nem fazem parte do Snapshot da Fase 46 — o backup reflete dados
cadastrados via API, e baixar o backup — mesmo repetidas vezes — não
altera nenhum dado), 1 confirma o evento de auditoria com o tamanho em
bytes do arquivo gerado, e 4 testam permissão: 403 sem
`sistema.backup_completo`, 401 sem autenticação, um perfil customizado
com essa permissão consegue baixar, e — a garantia mais importante desta
fase — um perfil com TODAS as permissões de `memoriais.*` (incluindo
`memoriais.excluir`, a mais forte do módulo, usada até para restaurar um
Snapshot inteiro na Fase 46) recebe 403 mesmo assim, confirmando que
acesso total ao Memorial Técnico não abre a porta para um backup de todo
o sistema. A Fase 48 não trouxe teste unitário novo — de propósito: ela
não cria nenhuma rota nem regra de negócio nova (é a MESMA tela/API de
Usuários de sempre, só acessível também a partir de um item de menu novo
dentro do Memorial Técnico), então não há nada de backend para testar de
forma unitária que os testes de `usuarios`/`perfis` já existentes não
cubram; a cobertura dela é o teste de navegador (`teste_fase48_navegador.js`),
que confirma que uma ação feita a partir de dentro do Memorial (inativar
um usuário) é visível pela API central — ou seja, é o mesmo dado, não uma
cópia. Mesmo espírito da Fase 38 (só frontend, sem teste unitário novo). A
Fase 49 é `test_fase49.py` com **17 testes novos**: 1 confirma que os
valores padrão da configuração (2 assinaturas / 40 MB) preservam
exatamente o comportamento fixo de sempre, 4 testam permissão (visualizar
o valor atual só exige `memoriais.visualizar` — testado com o perfil
Regulatório, que já tinha essa permissão — 403 sem ela mesmo assim; já
ALTERAR exige a permissão nova `memoriais.configurar` — 403 pra quem só
visualiza, e o Administrador, que tem "TODAS", consegue), 4 testam a
atualização em si (alterar só um dos dois campos preserva o outro —
regressão central deste tipo de configuração desde a Fase 32/34, nenhum
campo informado é rejeitado, e cada campo fora do intervalo permitido —
zero ou negativo — também é rejeitado), 1 confirma o evento de auditoria
com o valor anterior e o novo, e 7 testam o EFEITO REAL da configuração
sobre as duas regras que ela substitui: com a configuração padrão, 2
assinaturas ainda aprovam automaticamente um memorial "Concluído" —
regressão direta dos testes da própria Fase 24 —, configurando para 3,
essas mesmas 2 assinaturas deixam de bastar, a terceira assinatura então
aprova, o painel (`/memorial/dashboard`) conta "assinaturas pendentes" de
acordo com o novo limiar (não mais o `2` fixo), e o limite de tamanho de
anexo (Fase 27) muda de verdade quando o MB configurado é reduzido — um
arquivo que cabia no limite anterior passa a ser rejeitado, e um arquivo
menor que o novo limite continua sendo aceito.
A Fase 50 é `test_fase50.py` com **21 testes novos**: 2 confirmam que uma
ordem SEM nenhuma etapa cadastrada continua se comportando exatamente
como antes desta fase existir (regressão direta da Fase 9 — perda
agregada informada na hora de concluir, sem nenhuma das novas exigências),
7 cobrem o CRUD de etapas (numeração automática de sequência, sequência
duplicada rejeitada com 409, editar/excluir só enquanto pendente, ordem
em status errado rejeitada, permissão `producao.apontar` reutilizada —
nenhuma permissão nova criada), 5 cobrem o apontamento de perda de cada
etapa (mesmas validações da Fase 9: quantidade não-negativa, motivo
obrigatório só se a quantidade for maior que zero, não permite apontar
duas vezes a mesma etapa), 4 cobrem a conclusão da ordem quando ela tem
etapas (rejeita quantidade_perda/motivo_perda manuais com 400 pedindo para
usar os endpoints de etapa, rejeita concluir com etapa ainda pendente,
soma automaticamente a perda das etapas concluídas e sintetiza o
motivo), 1 confirma a matemática exata da fatia de custo por etapa
(Custeio, Fase 13) — duas etapas com 0,5kg e 1,5kg de perda (25%/75%
de um total de 2kg) ficam com R$10 e R$30 de um custo total de perda de
R$40, batendo exatamente com a proporção —, e 2 confirmam que nenhuma
permissão nova foi criada (a mesma `producao.apontar` que já existia
desde a Fase 9 cobre também o CRUD de etapas e o apontamento de perda por
etapa).
A Fase 51 não trouxe teste unitário novo — de propósito, mesmo espírito
das Fases 38 e 48: ela não cria nenhuma rota nem regra de negócio no
backend, é só reorganização visual do menu lateral (`ITENS_MENU` em
`app.js`, que já era filtrado por permissão desde a Fase 1, passou a
poder ter itens agrupados dentro de um `<details>/<summary>` recolhível —
a mesma filtragem de permissão de sempre, só aplicada item a item DENTRO
do grupo, escondendo o grupo inteiro quando nenhum item dele sobra
visível). A cobertura dela é o teste de navegador
(`teste_fase51_navegador.js`), que confirma: nenhum grupo abre sozinho
partindo do Painel (que não pertence a nenhum módulo); um link dentro de
um grupo fechado não é clicável até abrir o grupo; navegar para dentro de
um grupo abre ele automaticamente; abrir/fechar um grupo manualmente é
lembrado entre um F5 e outro (guardado no navegador, não no servidor); e
o perfil "Vendedor" (só tem permissão para Itens e o módulo
Comercial/Vendas) vê exatamente 1 dos 7 grupos no menu — os outros 6
desaparecem por completo, não ficam "vazios".
A Fase 52 é `test_fase52.py` com **15 testes novos**: 3 confirmam
retrocompatibilidade (sem `empresa_id`, o dashboard, o fluxo de caixa
projetado e os cinco blocos de sempre ficam idênticos a antes desta
fase), 6 cobrem o filtro aplicado a um cenário real com 2 empresas — um
por bloco (Produção, Qualidade com as sub-métricas fora do escopo
permanecendo globais, Estoque com o caminho duplo saldo-via-lote/
posições-via-unidade, Comercial com `clientes_ativos` global, Financeiro,
e o filtro por empresa compondo com o filtro por período da Fase 42), 1
confirma que `contas_receber.empresa_id` é herdado automaticamente do
pedido na expedição, 1 confirma 404 para `empresa_id` inválido nos 5
endpoints (dashboard, fluxo de caixa, PDF, CSV, XLSX), 1 confirma que
nenhuma permissão nova foi criada (`relatorios.visualizar` de sempre), 1
confirma que os três exports aceitam e exibem o filtro de empresa no
cabeçalho, 1 confirma a ausência da seção "Filtrando por" no CSV sem
filtro, e 1 confirma que o dado `empresa_filtrada` só aparece no retorno
quando o filtro é de fato usado.
A Fase 53 é `test_fase53.py` com **16 testes novos**: 9 cobrem o registro
da decisão (todos os 5 tipos aceitos, `tipo_decisao` inválido → 400,
motivo obrigatório → 400, pedido fora da simulação → 400, simulação
inexistente → 404, a rota confirmadamente não mexe no pedido de verdade,
múltiplas decisões ao longo do tempo preservadas — append-only — e o
evento de auditoria correto), 4 cobrem a listagem (status atual do pedido
e da conta a receber, status refletindo uma baixa registrada depois da
simulação, 404 para simulação inexistente, lista vazia quando não há
pedido expedido afetado), 2 cobrem permissão (403 sem
`decidir_pedido_recall`, perfil Qualidade já com a permissão por padrão),
e 1 é a regressão explícita confirmando que `bloquear_em_massa` (Fase 16)
continua sem mexer em pedidos já expedidos.
A Fase 54 é `test_fase54.py` com **24 testes novos**: 6 cobrem a geração
de sugestões (uma por item em falta, item sem falta não gera nada, gerar
duas vezes seguidas não duplica pendente, fornecedor homologado aparece
como sugerido, múltiplos itens em falta geram múltiplas sugestões, e uma
nova sugestão pode ser gerada para o mesmo item depois que a anterior foi
decidida), 3 cobrem a listagem (vazia, filtro por status, status
inválido → 400), 5 cobrem atender (sem `conta_pagar_id`, linkando uma
conta a pagar real, `conta_pagar_id` inexistente → 404, atender duas
vezes → 400, sugestão inexistente → 404), 4 cobrem descartar (com motivo,
sem motivo → 400, descartar uma já atendida → 400, sugestão inexistente →
404), 3 cobrem permissão (PCP não pode gerar por padrão, Compras pode
gerar e decidir por padrão, um perfil sem nenhuma das duas novas
permissões recebe 403 em tudo — inclusive na listagem, que exige
`producao.visualizar`), 1 confirma os três eventos de auditoria
(`sugestao_compra_gerada`/`_atendida`/`_descartada`), e 1 é a regressão
confirmando que o cálculo do MRP em si (Fase 39) continua idêntico.
A Fase 55 é `test_fase55.py` com **21 testes novos**: 3 cobrem o valor
padrão/preservação da tolerância configurável (padrão de 3 dias — mesmo
comportamento de sempre desde a Fase 40 —, alterar só a tolerância
preserva os outros dois campos da mesma tela e vice-versa), 3 cobrem
validação (rejeita negativo, rejeita não numérico, aceita zero), 2 cobrem
permissão para alterar a configuração (só quem tem
`configurar_limite_estorno`, `financeiro.visualizar` continua bastando
para só ver o valor), 3 confirmam que a tolerância configurada afeta de
fato a correspondência na importação (fora da janela padrão de 3 dias não
concilia, aumentar a janela permite conciliar uma diferença maior, reduzir
para zero exige o mesmo dia exato), 6 cobrem o processamento em lote
(transação pendente concilia depois que a baixa é lançada, transação
ambígua continua pendente, escopo por `extrato_id` não toca outro extrato,
`extrato_id` inexistente → 404, transações já conciliadas/ignoradas não
são reprocessadas, evento de auditoria `conciliacao_em_massa_processada`),
2 cobrem permissão do lote (403 sem `conciliar_extrato`, perfil Financeiro
já habilitado por padrão), e 2 são regressão explícita confirmando que a
conciliação automática na importação (Fase 40) e a rota de sugestões
continuam funcionando exatamente como antes.
A Fase 56 é `test_fase56.py` com **13 testes novos**: 2 confirmam o valor
padrão (as quatro alíquotas detalhadas começam zeradas numa instalação
nova, e o DRE sem nenhuma configuração continua com os impostos zerados —
regressão explícita da Fase 41), 4 cobrem validação (rejeita percentual
negativo, rejeita maior que 100, rejeita valor não numérico, aceita 0 e
100 exatamente nos limites — mesma regra 0–100 já usada desde a Fase 41
para o percentual genérico, repetida para as quatro novas), 1 confirma que
configurar só uma das quatro alíquotas preserva as outras três E os campos
de fases anteriores na mesma tela (`tolerancia_dias_conciliacao` da Fase
55, `percentual_imposto_venda` da Fase 41), 2 cobrem permissão (perfil
Financeiro comum não pode configurar, mas pode visualizar — mesma
separação de sempre via `configurar_limite_estorno`), e 4 cobrem o cálculo
no DRE (as quatro alíquotas somam no total e cada uma aparece
individualmente no `impostos_detalhe`; a soma acontece JUNTO com a
genérica da Fase 41, nunca a substituindo; o Lucro Líquido reflete a soma
detalhada; e receita zero no período mantém todos os impostos detalhados
zerados, sem divisão por zero).
A Fase 57 é `test_fase57.py` com **18 testes novos**: 4 cobrem o cadastro
do lead time (criar fornecedor sem informar fica `None` — regressão —,
criar informando um valor válido, rejeita negativo, rejeita não numérico),
6 cobrem a rota dedicada de editar o lead time (admin configura, enviar
`null` limpa um valor já configurado, exige o campo `lead_time_dias` no
corpo, fornecedor inexistente dá 404, perfil Qualidade — que tem
`fornecedores.homologar` mas não `fornecedores.cadastrar` — recebe 403, e
perfil Compras consegue configurar), 5 cobrem o cálculo da
`data_limite_compra` no MRP (sem ordem agendada fica `None` — regressão —,
ordem agendada mas fornecedor sem lead time também fica `None`, ordem
agendada COM lead time calcula a data corretamente subtraindo os dias,
usa o primeiro fornecedor homologado por nome — mesmo critério da Fase
54 —, e escolhe a data de necessidade MAIS PRÓXIMA entre várias ordens
que precisam do mesmo insumo), e 3 cobrem o snapshot na sugestão de
compra (gerar a sugestão congela a data calculada, sugestão sem data
calculável fica com `None` — regressão —, e sugestão sem nenhum
fornecedor homologado continua funcionando normalmente — regressão da
Fase 54).
Fase 1 cobre: login com sucesso/falha, bloqueio após 10 tentativas erradas
(por 3 minutos — ajustado a pedido do cliente para ficar mais tolerante a
erro de digitação numa senha longa; ver `MAX_TENTATIVAS_LOGIN`/
`BLOQUEIO_MINUTOS` em `app/routes/auth.py`),
fluxo completo de 2FA, permissão negada (403) vs. permitida, efeito
imediato de revogar uma permissão, criação de registro de auditoria,
imutabilidade da auditoria a nível de banco, e a regra de segregação de
função (ninguém pode se autoconceder o perfil Administrador). Fase 2
cobre: fluxo completo de recebimento → quarentena → análise → conclusão →
aprovação → emissão de CoA; a regra de que quem concluiu a análise não
pode aprovar/reprovar o mesmo lote; exigência de ressalva e justificativa
para aprovar um resultado fora de especificação; reprovação de lote;
correção de um resultado já registrado (exige motivo e preserva o valor
anterior no histórico); bloqueio/desbloqueio de lote restaurando o status
anterior; e a exigência de fornecedor homologado antes de aceitar um item
que exige homologação. Fase 3 cobre: só uma fórmula ativa por produto
(ativar uma nova torna a anterior obsoleta); uma ordem só pode ser criada
a partir de uma fórmula ativa; bloqueio de consumo de lote não aprovado;
bloqueio de consumo além da quantidade disponível (calculada em tempo
real a partir da genealogia, nunca um saldo separado que poderia
dessincronizar); bloqueio de consumo de um item que não faz parte da
composição da fórmula; o fluxo completo gera o lote produzido em
quarentena com a genealogia correta nos dois sentidos; esse lote produzido
segue exatamente o mesmo fluxo de aprovação de qualidade da Fase 2 (sem
nenhuma rota especial); e uma ordem só pode ser cancelada antes do
primeiro consumo (depois disso, precisa ser concluída, para preservar a
rastreabilidade do material já consumido). Fase 4 cobre: cadastro de
posição de armazenagem e bloqueio de código duplicado na mesma unidade;
bloqueio de endereçamento de lote que ainda não foi aprovado; bloqueio de
endereçar além da quantidade pendente do lote; um lote some da lista de
pendentes assim que totalmente endereçado — e **não volta** para essa
lista mesmo depois de uma baixa ou ajuste negativo (regressão de um bug
real, encontrado no teste e2e de navegador, corrigido antes da entrega);
transferência entre posições gera saldo correto nas duas pontas e não
altera o total físico do lote; bloqueio de transferir mais que o saldo de
origem ou para a mesma posição; o ledger de movimentações é
comprovadamente append-only a nível de banco (UPDATE/DELETE bloqueados
por trigger, mesmo via SQL direto); ajuste e baixa exigem motivo e nunca
deixam o saldo negativo; sugestão FEFO prioriza corretamente o lote que
vence primeiro e sinaliza atendimento parcial quando não há saldo
suficiente; e segregação de função — cada ação de estoque exige a
permissão granular certa (o perfil PCP só visualiza, só o perfil Estoque
endereça/transfere/ajusta/baixa). Fase 5 cobre: cadastro de cliente e
bloqueio de CNPJ duplicado; criação de pedido com itens, bloqueio de
vender item que não é `produto_acabado`, adicionar/remover item só em
rascunho; confirmação aloca FEFO de verdade e reduz o saldo disponível
para outros pedidos, prioriza o lote que vence primeiro, um pedido sem
item não pode ser confirmado, e — regressão importante — um pedido com
duas linhas do mesmo item não reserva o mesmo saldo em dobro (a segunda
linha já enxerga o que a primeira reservou); expedição gera saída real no
estoque e libera a reserva do cálculo de disponibilidade, falha com 409
se o saldo físico mudou desde a confirmação (ex.: alguém deu baixa direto
no Estoque nesse meio-tempo), e só pode expedir um pedido já confirmado;
cancelamento exige motivo e um pedido já expedido não pode ser cancelado
(devolução é um fluxo separado, fora de escopo); cancelar um confirmado
libera a reserva automaticamente para outros pedidos poderem usar o
mesmo saldo; as reservas são comprovadamente append-only a nível de banco
(mesmo princípio da Fase 4); e segregação de função entre os perfis
Vendedor (cria mas não confirma), Comercial (confirma mas não expede) e
Estoque (expede). Fase 6 cobre: expedir um pedido gera automaticamente
uma conta a receber com o valor correto (congelado a partir do preço de
cada item) e vencimento 30 dias após a expedição; baixa parcial deixa o
status `pago_parcial` e baixa total deixa `pago`, com o saldo em aberto
sempre recalculado a partir da soma das baixas; bloqueio de baixa maior
que o saldo em aberto, de forma de pagamento inválida, e de nova baixa
numa conta já totalmente paga ou cancelada; cancelamento de conta exige
motivo e só é permitido sem nenhuma baixa registrada; as baixas são
comprovadamente append-only a nível de banco (mesmo princípio das Fases
4/5); criação de conta a pagar valida que o fornecedor existe e que,
se informado, o lote de referência realmente pertence a esse fornecedor
(rejeita lote de um fornecedor diferente); filtros de listagem por status
e por cliente/fornecedor; e segregação de função — o perfil Compras
lança a conta a pagar mas não pode registrar a baixa dela (403), e o
perfil Financeiro registra baixas de receber e pagar. Fase 7 cobre: os
números do painel batem exatamente com um cenário real construído passo a
passo pela API de cada fase anterior (produção concluída, lotes aprovados
e reprovados — taxa de aprovação calculada corretamente —, desvio aberto,
saldo de estoque líquido de uma expedição parcial, pedido expedido com seu
valor, conta a receber com baixa parcial e conta a pagar em aberto, com o
saldo projetado sendo a diferença entre as duas); o painel não quebra com
o banco praticamente vazio (a taxa de aprovação vira `null` em vez de uma
divisão por zero); e a segregação entre a permissão agregada
`relatorios.visualizar` e as permissões operacionais de cada módulo — o
perfil Diretoria vê o painel mas recebe 403 ao tentar ver a lista de
clientes do Comercial, prova de que não é uma soma de permissões. Fase 8
cobre: um cenário de produção de **dois níveis** construído via API
(matéria-prima → produto intermediário → produto acabado → pedido
expedido) para provar que a recursão da genealogia realmente atravessa
mais de um hop em ambas as direções — "para trás" (upstream) chega até o
fornecedor da matéria-prima, "para frente" (downstream) chega até o
cliente que recebeu o produto acabado; um pedido apenas confirmado (ainda
não expedido) conta como "reservado, não expedido" e não entra na lista de
pedidos/clientes efetivamente afetados; um lote isolado, nunca usado, não
tem upstream nem downstream; simular um recall sem informar o motivo é
rejeitado (400); a simulação grava um snapshot com os totais corretos e
aparece tanto no histórico (resumo) quanto no detalhe (árvore completa);
as simulações são comprovadamente append-only a nível de banco (mesmo
princípio das Fases 4, 5 e 6) e geram um evento de auditoria; a busca de
apoio de lote por código funciona sem exigir `lotes.visualizar` (mesma
independência de permissão da Fase 7); e a segregação de função — a
Qualidade visualiza e simula recall, a Diretoria só visualiza (não tem o
botão/permissão de simular), e um perfil sem `rastreabilidade.visualizar`
recebe 403 em tudo. Fase 9 cobre: concluir uma ordem sem informar nenhuma
perda continua gravando `quantidade_perda = 0` e `motivo_perda = null`
(comportamento anterior à Fase 9 preservado); conclusão com perda e motivo
é aceita e o lote produzido nasce só com a quantidade **produzida** (a
perda nunca vira produto); o percentual de perda e o percentual de
rendimento sobre o planejado são calculados corretamente
(`_ordem_detalhada`); quantidade de perda negativa é rejeitada (400) e a
ordem não fica "concluída pela metade" (continua `em_producao`); perda
maior que zero sem `motivo_perda` (ou com motivo só espaços em branco) é
rejeitada; quantidade de perda não numérica é rejeitada; o evento de
auditoria de `ordem_concluida` carrega os novos campos; uma ordem ainda
não concluída tem os indicadores derivados como `null` (não `0`, que
seria enganoso); e a permissão continua sendo exatamente `producao.apontar`
— sem permissão nova — provado tanto pelo bloqueio de quem não a tem
quanto pela confirmação de que quem já a tinha desde a Fase 3 continua
conseguindo concluir com perda sem nenhuma mudança de perfil. Fase 10
cobre: o PDF é gerado com sucesso para um lote aprovado (content-type
`application/pdf`, `Content-Disposition: attachment` com o nome do
arquivo baseado no código do lote, corpo começando com os magic bytes
`%PDF`, tamanho maior que o trivial); o mesmo funciona tanto para um lote
recebido de fornecedor quanto para um lote produzido (a seção de origem
no PDF mostra fornecedor **ou** ordem de produção, nunca as duas); um
lote que ainda não tem CoA (nunca foi aprovado) recebe 400 ao tentar
baixar o PDF; lote inexistente dá 404; gerar o PDF duas vezes seguidas
não altera o status do lote nem cria um novo certificado (é
comprovadamente um export, sem efeito colateral de negócio); cada
geração registra um evento de auditoria `coa_pdf_gerado`; e a permissão
continua sendo exatamente `lotes.visualizar` — sem permissão nova —
provado tanto pelo bloqueio de um perfil sem nenhuma permissão quanto
pela confirmação de que o perfil Laboratório (que já tem
`lotes.visualizar` desde a Fase 2) consegue baixar o PDF sem nenhuma
mudança de perfil. Fase 11 cobre: o PDF do relatório de recall é gerado
com sucesso para uma simulação existente (content-type
`application/pdf`, `Content-Disposition: attachment` com o nome do
arquivo baseado no número da simulação — `Recall-RCL-....pdf` —, corpo
começando com os magic bytes `%PDF`, tamanho maior que o trivial);
simulação inexistente dá 404; gerar o PDF duas vezes seguidas não altera
nenhum dado da simulação nem de mais nada (comprovadamente um export,
mesmo princípio da Fase 10); cada geração registra um evento de
auditoria `recall_pdf_gerado`; e a permissão continua sendo exatamente
`rastreabilidade.visualizar` — sem permissão nova — provado tanto pelo
bloqueio de um perfil sem nenhuma permissão quanto pela confirmação de
que o perfil Diretoria (que só tem `rastreabilidade.visualizar`, nenhuma
permissão de lotes/produção) consegue baixar o PDF sem nenhuma mudança
de perfil. Fase 12 cobre: liberar uma ordem reserva de verdade o material
da composição via FEFO (lote correto, quantidade correta, aparece em
`reservas_material` na resposta da API); liberar sem nenhum lote aprovado
suficiente é recusado com 400 e mensagem explicando exatamente o que
falta; uma ordem consegue consumir até o que ela mesma reservou (nunca
menos, mesmo com outras reservas concorrentes no sistema); duas ordens
liberadas em sequência disputam o mesmo saldo real — a segunda é recusada
se a primeira já reservou tudo; cancelar uma ordem liberada devolve a
reserva, permitindo que outra ordem a use; a reserva é registrada no
evento de auditoria `ordem_liberada`; a tabela `ordem_producao_reservas`
é comprovadamente append-only a nível de banco (UPDATE/DELETE bloqueados
por trigger, mesmo via SQL direto — mesmo princípio do ledger de estoque
desde a Fase 4); um lote vendido e confirmado pelo Comercial não pode
mais ser reservado por uma ordem de produção liberada depois (e
vice-versa: uma reserva de produção já feita bloqueia o Comercial de
alocá-la via FEFO); uma baixa de estoque reduz a disponibilidade real
enxergada pela Produção mesmo sem tocar em `lotes.quantidade` (o saldo
nominal); e a permissão continua sendo exatamente `producao.liberar` —
sem permissão nova — provado tanto pela liberação funcionando com o
perfil PCP (que já tinha essa permissão desde a Fase 3) quanto pelo
bloqueio de um perfil sem ela. Fase 13 cobre: um lote recebido sem
`custo_unitario` informado devolve `null` (nunca um zero silencioso);
`custo_unitario` negativo ou não numérico é rejeitado; o custo de uma
ordem soma corretamente insumo a insumo — incluindo item de embalagem
(rótulo) além da matéria-prima principal — batendo com o cálculo manual;
quando o lote consumido não tem custo informado, o motor cai para a
média ponderada do item entre os lotes que TÊM custo (não trata os sem
custo como zero); quando nenhum lote do item tem custo, a resposta marca
`custo_incompleto=true` e lista o item em `itens_sem_custo_disponivel`;
ordem inexistente dá 404; o custo da perda é exatamente proporcional ao
`percentual_perda` já calculado pela Fase 9 (validado item a item,
inclusive para a embalagem); uma ordem concluída sem nenhuma perda tem
custo de perda zero e custo de produção boa igual ao total; a lista de
produtos mostra o custo projetado de cada fórmula ativa a partir do
custo médio atual dos insumos da BOM; o detalhe de um produto traz o
histórico de perdas das ordens concluídas; fórmula inexistente dá 404; e
a permissão nova `custeio.visualizar` funciona nos dois sentidos — um
perfil sem ela (PCP, que opera produção) recebe 403, o perfil Financeiro
consegue ver custeio mesmo SEM `producao.visualizar` (prova de
independência), e o perfil Diretoria também vê. Fase 14 cobre: estornar
uma baixa total volta a conta para "aberto" com saldo em aberto igual ao
valor total de novo; estornar apenas uma entre duas baixas recalcula o
saldo líquido corretamente (baixas normais menos estornos, nunca um
número solto); a mesma baixa não pode ser estornada duas vezes; um
estorno não pode ser estornado (o lançamento original já reflete a
reversão); motivo é obrigatório (400 sem ele); baixa ou conta inexistente
dá 404; uma baixa de uma conta não pode ser estornada informando outra
conta na URL; o estorno é registrado no evento de auditoria
`baixa_receber_estornada`/`baixa_pagar_estornada` com o motivo; a linha
de estorno em si continua bloqueada por UPDATE/DELETE a nível de banco
(os mesmos triggers append-only da Fase 6, que nunca precisaram de
alteração); e as permissões novas `estornar_baixa_receber`/
`estornar_baixa_pagar` funcionam de forma independente de
`registrar_baixa_receber`/`registrar_baixa_pagar` — um perfil customizado
com só a permissão de registrar (sem a de estornar) recebe 403 ao tentar
estornar, provado nos dois sentidos (receber e pagar). Mais dois testes de
regressão provam que o agregador financeiro independente do Painel
Gerencial (Fase 7) também reflete um estorno corretamente — o bug real
que a correção descrita acima resolveu. Fase 15 cobre: as fronteiras
exatas de cada faixa (uma conta vencendo daqui a 7 dias cai em "0 a 7
dias", daqui a 8 dias já cai em "8 a 15 dias" — testado nos dois lados de
cada fronteira, não só no meio da faixa); uma conta com vencimento no
passado cai em "Vencido" mesmo que o `status` ainda esteja "aberto"; o
saldo acumulado soma corretamente faixa a faixa, inclusive quando há
entrada (contas a receber) e saída (contas a pagar) na mesma faixa; uma
conta paga integralmente ou cancelada some do fluxo de caixa; uma baixa
parcial reduz exatamente o saldo em aberto daquela conta no bucket certo;
um teste de regressão direta da Fase 14 prova que estornar uma baixa
devolve o saldo ao bucket certo (a mesma leitura `_contas_em_aberto` que
serve o Painel Gerencial); banco vazio devolve os 7 buckets zerados sem
quebrar; a ordem dos buckets é sempre a mesma (`vencido`, `0_7`, `8_15`,
`16_30`, `31_60`, `61_90`, `mais_90`); e a permissão reaproveitada
`relatorios.visualizar` funciona nos dois sentidos — um perfil sem ela
(Vendedor) recebe 403, e o perfil Diretoria consegue ver o fluxo de caixa
normalmente. Fase 16 cobre: bloquear a partir do lote FINAL da cadeia
bloqueia toda a cadeia upstream (o investigado + os de trás); bloquear a
partir do lote do MEIO da cadeia atravessa upstream E downstream ao mesmo
tempo, provando que o bloqueio em massa é bidirecional igual à própria
simulação; um pedido já expedido do mesmo lote NÃO tem seu status alterado
(decisão de escopo deliberada); motivo em branco dá 400; simulação de
recall inexistente dá 404; um lote já bloqueado manualmente antes (de uma
investigação anterior) é pulado sem erro, aparece em `lotes_ja_bloqueados`
em vez de `lotes_bloqueados`, e rodar a operação de novo com tudo já
bloqueado continua devolvendo 200 (idempotência); o detalhe de uma
simulação de recall mostra o status ATUAL de cada lote afetado — antes do
bloqueio "Aprovado", depois "Bloqueado" — provando que esse campo é
recalculado a cada chamada e não um valor congelado no snapshot da
simulação; a auditoria registra o evento `recall_bloqueio_em_massa` com o
motivo; a permissão nova `rastreabilidade.bloquear_em_massa` funciona nos
dois sentidos — um perfil com só `rastreabilidade.simular_recall` (sem a
nova) recebe 403, e o perfil Qualidade (que já sai com as duas por
padrão) consegue bloquear; e dois testes de regressão provam que a rota
de bloqueio individual (`POST /lotes/{id}/bloquear`), refatorada nesta
fase para reaproveitar a mesma função central do bloqueio em massa,
continua se comportando exatamente como antes (motivo obrigatório, 400 ao
bloquear um lote já bloqueado).

Fase 17 cobre: uma contagem geral, ao ser iniciada, auto-popula
automaticamente todos os pares lote+posição com saldo positivo naquele
depósito, cada um com o `saldo_sistema_no_inicio` correto; concluir uma
contagem sem nenhuma divergência não gera nenhum ajuste de estoque;
concluir com divergência gera exatamente um ajuste só no item divergente,
com `ajuste_gerado_id` apontando pra ele, e o saldo físico
(`GET /estoque/saldo`) reflete a correção; não é possível concluir uma
contagem com itens ainda pendentes de contagem (400); uma contagem
cíclica começa vazia e aceita item adicionado manualmente, mas rejeita o
mesmo par lote+posição duas vezes (409) e rejeita adicionar item numa
contagem do tipo geral (400); cancelar sempre exige motivo (400 em
branco) e nunca gera ajuste, e itens não podem mais ser contados depois
do cancelamento; a segregação entre `estoque.contagem` e `estoque.ajustar`
funciona nos dois sentidos — um perfil (PCP) sem `estoque.contagem`
recebe 403 ao tentar iniciar uma contagem, o perfil Estoque (que já sai
com as duas permissões) funciona normalmente, e um perfil customizado com
só `estoque.contagem` (sem `estoque.ajustar`) consegue iniciar/contar mas
recebe 403 especificamente ao tentar concluir; e casos de borda como
unidade inexistente (404), tipo inválido (400) e um depósito vazio (que
simplesmente gera uma contagem geral sem itens, sem quebrar) também são
cobertos.

Fase 18 cobre: o PDF é gerado com sucesso a partir de um cenário real
tocando os cinco blocos do painel (content-type correto, corpo começa
com os magic bytes %PDF, nome de arquivo com a data do dia); um banco
totalmente vazio ainda assim gera um PDF válido, sem quebrar com KPIs
zerados; gerar o PDF (inclusive duas vezes seguidas) não altera nenhum
dado de negócio — o `GET /dashboard` antes e depois é idêntico; cada
PDF gerado grava um evento de auditoria `painel_pdf_gerado`; e a
permissão continua sendo só `relatorios.visualizar`, sem nenhuma
permissão nova — um perfil sem ela recebe 403, e o perfil Diretoria
(que só tem essa permissão, nenhuma operacional) consegue baixar o PDF
normalmente.

Fase 19 cobre: o CSV é gerado com sucesso e contém o BOM UTF-8 no início,
as seis seções esperadas (Produção, Qualidade, Estoque, Comercial,
Financeiro, Fluxo de Caixa Projetado) e o valor exato de uma conta a
pagar lançada no cenário; um banco totalmente vazio ainda assim gera um
CSV válido; gerar o CSV (inclusive duas vezes seguidas) não altera
nenhum dado de negócio; cada CSV gerado grava um evento de auditoria
`painel_csv_gerado`; e a mesma prova de permissão reaproveitada das
Fases 10/11/18 — sem permissão nova, 403 sem `relatorios.visualizar`,
200 para quem só tem essa permissão.

Fase 20 cobre: o cálculo do DRE bate exatamente com um cenário
determinístico (MP a R$10/kg, fórmula 2kg MP → 1kg PA, ordem de 10kg sem
perda — custo real R$20/kg, venda de 6kg a R$50/kg: receita=R$300,
CMV=R$120, lucro=R$180, margem=60%); um banco totalmente vazio devolve
zeros sem quebrar; um pedido que não foi expedido (rascunho/confirmado/
cancelado) fica de fora do cálculo; quando o custo de algum lote vendido
não está disponível, `custo_incompleto` vem `true` e o lote afetado
aparece em `lotes_sem_custo_disponivel` (a margem nunca finge que o
custo é zero); o filtro `data_inicio`/`data_fim` realmente restringe o
cálculo à janela pedida; e a permissão é `custeio.visualizar` — 403 para
o perfil PCP (que não tem essa permissão), 200 para os perfis Financeiro
e Diretoria (que têm).

Fase 21 cobre: uma divergência acima de 20% do saldo inicial fica
`aprovacao_status='pendente'` ao concluir a contagem, sem gerar ajuste
nenhum e sem alterar o saldo físico; uma divergência abaixo de 20%
continua ajustando na hora, exatamente como desde a Fase 17 (teste de
regressão explícito); quando o saldo inicial era zero (achou algo onde o
sistema não sabia de nada), a divergência é SEMPRE tratada como grande,
mesmo que o percentual não seja calculável; aprovar por um segundo
usuário gera o ajuste e corrige o saldo; rejeitar por um segundo usuário
não gera ajuste nenhum, só registra o motivo; quem contou o item recebe
403 tanto ao tentar aprovar quanto ao tentar rejeitar o próprio ajuste
(segregação de função por usuário, não só por perfil); um perfil sem
`estoque.aprovar_ajuste_contagem` recebe 403; e a lista consolidada de
pendências (`GET /estoque/ajustes-pendentes-aprovacao`) mostra o item
enquanto pendente e fica vazia depois de qualquer decisão.

Fase 22 cobre: uma baixa de valor abaixo do limiar de R$1.000,00 continua
estornando (revertendo) na hora, exatamente como desde a Fase 14 (teste
de regressão explícito); uma baixa acima do limiar não reverte — fica
pendente, a rota devolve 202 (não 201), e o `estorno_pendente_criado_id`
vem no corpo; não é possível abrir uma segunda solicitação enquanto já
existe uma pendente para a mesma baixa; aprovar por um segundo usuário
insere de fato a baixa de reversão e corrige o saldo/status da conta;
rejeitar por um segundo usuário exige motivo e não altera o saldo em
nada; quem solicitou o estorno recebe 403 tanto ao tentar aprovar quanto
ao tentar rejeitar o próprio pedido (segregação de função por usuário,
não só por perfil); um perfil sem `financeiro.aprovar_estorno_receber`/
`_pagar` recebe 403; a lista consolidada
(`GET /financeiro/estornos-pendentes`) mostra a pendência com o campo
`tipo` certo e fica vazia depois de qualquer decisão; e o mesmo fluxo é
espelhado ponta a ponta no lado "a receber" (pedido → confirmação →
expedição → baixa → estorno pendente → aprovação), confirmando que a
duplicação de código entre `contas_receber`/`contas_pagar` não introduziu
nenhuma assimetria de comportamento.

Fase 23 cobre: criar um item sem informar `codigo` gera automaticamente
`MP000001` (matéria-prima, primeiro item); os 7 tipos válidos têm cada um
seu próprio prefixo (`MP`/`EPP`/`EPS`/`PI`/`PG`/`PA`/`LAB`); um segundo
item do mesmo tipo recebe o próximo número da sequência (`MP000002`); as
sequências de tipos diferentes são independentes entre si; um código
manual antigo que por coincidência começa com o mesmo prefixo (mas em
outro formato, ex.: `MP-001`) não interfere na sequência automática nem é
sobrescrito; informar `codigo` explicitamente continua funcionando
exatamente como antes; um `codigo` explícito duplicado continua rejeitado
com 409; faltar `descricao` ou informar um `tipo` inválido continuam
rejeitados com 400 mesmo sem informar `codigo`; e o código gerado é
persistido de verdade e aparece na listagem (`GET /itens`).

Fase 24 cobre: cadastro e listagem de empresa e de produto vinculado a uma
empresa (com 404 se a empresa não existir e rejeição de CNPJ duplicado);
edição de ambos; criar um memorial gera `codigo`/`numero_certificado`
automáticos no formato `CERT-AF-AAAAMMDD/NNN`, e códigos gerados em
sequência são diferentes e crescentes; informar `numero_certificado`
manualmente é respeitado, e um duplicado é rejeitado com 409; a listagem
de memoriais traz o nome do produto e da empresa já resolvidos (sem
precisar de outra chamada); editar o conteúdo do memorial persiste;
alterar o status registra entrada no histórico; assinar registra a
assinatura (cargo/iniciais a partir do usuário logado) e o mesmo usuário
não pode assinar duas vezes; duas assinaturas de usuários diferentes com o
memorial em "Concluído" aprovam automaticamente — mas sem o status
"Concluído" as mesmas duas assinaturas não aprovam sozinhas; excluir um
memorial só é permitido em rascunho (409 se já avançou no fluxo, para
preservar o histórico de conformidade); status inválido é rejeitado; quem
não tem a permissão certa recebe 403; e o dashboard agrega as contagens
por status corretamente.

### Teste manual guiado pelo navegador (o jeito mais fácil de confirmar)
Com o servidor rodando (passo 6 acima), abra `http://127.0.0.1:5000` no
navegador e:
1. Faça login com o e-mail/senha do administrador que o `seed.py` criou.
2. Vá em **Usuários** → **+ Novo usuário** e crie alguém com o perfil
   "Laboratório", por exemplo, e outro com o perfil "Qualidade".
3. Vá em **Perfis** e confira as permissões desses perfis.
4. Vá em **Itens** e cadastre uma matéria-prima (ex.: marque "exige
   fornecedor homologado" para testar essa regra).
5. Vá em **Fornecedores**, cadastre um fornecedor, aprove o status dele e
   homologue-o para o item que você criou.
6. Vá em **Lotes / Qualidade** → **+ Registrar recebimento** — o lote
   nasce em quarentena.
7. Abra o lote, clique em **Solicitar análise** e informe um ensaio (ex.:
   `pH;6.5;7.5;pH`).
8. Faça login como o usuário "Laboratório" e registre o resultado do
   ensaio, depois clique em **Concluir análise**.
9. Faça login como o usuário "Qualidade" (um usuário **diferente** de quem
   concluiu a análise — o sistema bloqueia a autoaprovação) e aprove ou
   reprove o lote. Se aprovado, um Certificado de Análise (CoA) é gerado e
   mostrado na tela.
10. Vá em **Desvios** e abra, trate e encerre um desvio.
11. Vá em **Fórmulas (BOM)** → **+ Nova fórmula**: escolha um produto
    (pode ser o mesmo item que você aprovou acima, se ele for do tipo
    produto acabado/a granel, ou cadastre um novo item desse tipo em
    **Itens** primeiro), informe o rendimento teórico e a composição no
    formato `codigo_do_item;quantidade;unidade` (um insumo por linha,
    usando os códigos da tela Itens). Depois clique em **Ativar**.
12. Vá em **Ordens de Produção** → **+ Nova ordem**, escolha a fórmula
    ativa e a quantidade planejada. Abra a ordem criada e clique em
    **Liberar**.
13. Clique em **Registrar consumo** e escolha o lote de matéria-prima que
    você aprovou no passo 9 (só lotes aprovados aparecem na lista). Depois
    clique em **Concluir ordem** informando a quantidade realmente
    produzida — isso gera um novo lote, em quarentena.
14. Abra o lote gerado (clique no código dele na tela da ordem): a seção
    **Rastreabilidade / Genealogia** mostra de que lote ele foi produzido.
    Volte ao lote de matéria-prima consumido e veja a mesma seção mostrar
    em que ordem ele foi usado e qual lote ela gerou — a genealogia
    funciona nos dois sentidos.
15. Rode esse lote produzido pelo mesmo fluxo de qualidade dos passos 7-9
    (solicitar análise → registrar resultado → concluir → aprovar) para
    liberá-lo — é literalmente a mesma tela e as mesmas regras de antes.
16. Vá em **Empresas**, se ainda não tiver, cadastre uma unidade do tipo
    **Depósito** — é o pré-requisito para cadastrar posições de
    armazenagem na Fase 4.
17. Vá em **Estoque (WMS)**: qualquer lote já aprovado que ainda não tenha
    sido endereçado aparece em **Lotes pendentes de endereçamento**. Cadastre
    uma ou duas posições (ex.: `A1-01`, `A1-02`) e clique em **Endereçar**
    no lote.
18. Na tabela **Saldo em estoque**, use **Transferir** para mover parte do
    saldo para a outra posição, **Ajustar** para corrigir uma divergência
    de contagem (motivo obrigatório) e **Baixa** para registrar um
    descarte/amostra (motivo obrigatório também).
19. Use a seção **Sugestão FEFO** informando o item e a quantidade
    necessária: o sistema sugere separar primeiro do lote que vence mais
    cedo, e avisa se o saldo total não é suficiente para atender o pedido.
20. Vá em **Auditoria** e veja todos os eventos acima registrados — com
    data/hora, usuário e IP.
21. Vá em **Comercial (CRM)** → **+ Novo cliente** e cadastre um cliente
    (CNPJ obrigatório e único).
22. Clique em **+ Novo pedido**: escolha o cliente, um item do tipo
    produto acabado que já esteja endereçado em estoque (o mesmo que você
    aprovou e endereçou nos passos 15-17), a quantidade e o **preço
    unitário** (campo obrigatório desde a Fase 6 — é ele que vai definir o
    valor da conta a receber gerada ao expedir). O pedido é criado como
    **Rascunho** — na tela de detalhe dá para **+ Adicionar item** ou
    remover itens livremente enquanto estiver nesse status.
23. Clique em **Confirmar (reservar estoque)**: o sistema aloca o saldo
    pelo critério FEFO e mostra a reserva real (lote e posição) na tela.
    Se pedir mais do que existe disponível, a confirmação falha com uma
    mensagem clara e o pedido continua em rascunho — nada fica
    "meio-confirmado".
24. Faça login com um usuário do perfil "Estoque" (ou o administrador) e
    clique em **Expedir**: isso dá baixa real no estoque — confira na
    tela **Estoque (WMS)** que o saldo da posição caiu exatamente a
    quantidade do pedido. Repare também na seção **Conta a receber
    gerada** que aparece na tela do pedido — ela é criada automaticamente,
    com o valor calculado a partir do preço informado no passo 22.
25. Experimente **Cancelar** um pedido em rascunho ou confirmado
    (obrigatório informar o motivo) — se ele estava confirmado, a reserva
    é liberada automaticamente e passa a contar como disponível de novo
    para outros pedidos.
26. Saia e entre com um usuário sem certas permissões (ex.: perfil
    "Vendedor"): note que o menu lateral e os botões de ação se ajustam
    automaticamente — o link "Estoque (WMS)" nem aparece, e na tela de um
    pedido confirmado não aparece o botão "Expedir" (Vendedor não tem
    essa permissão).
27. Vá em **Financeiro**: a conta a receber gerada no passo 24 aparece na
    tabela **Contas a Receber**, com status **Aberto**. Clique em
    **Registrar recebimento**, informe um valor menor que o total (ex.:
    metade) e uma forma de pagamento — o status muda para **Pago
    parcial** e o saldo em aberto é recalculado. Registre outra baixa
    com o restante do saldo (o campo já vem pré-preenchido com o valor
    exato) e veja o status virar **Pago**, quando o botão de recebimento
    desaparece.
28. Ainda em Financeiro, clique em **+ Nova conta a pagar**: escolha um
    fornecedor já cadastrado, uma descrição (ex.: número da nota fiscal),
    valor, vencimento e, opcionalmente, o ID de um lote recebido desse
    mesmo fornecedor (para rastreabilidade — o sistema recusa se o lote
    informado pertencer a outro fornecedor). Registre o pagamento dela
    do mesmo jeito que a conta a receber.
29. Faça login com um usuário do perfil "Compras": ele consegue lançar
    uma nova conta a pagar, mas o botão **Registrar pagamento** não
    aparece para ele — só o perfil "Financeiro" autoriza o pagamento.
    Essa segregação (quem lança a conta não é quem paga) é a mesma
    lógica de "quem confirma o pedido não é quem expede" já vista na
    Fase 5.
30. Faça login de novo como administrador e vá em **Painel Gerencial
    (BI)**: você vai ver, num só lugar, os números que passou pelas telas
    de Produção, Qualidade, Estoque, Comercial e Financeiro nos passos
    anteriores (ordens concluídas, taxa de aprovação de lotes, saldo de
    estoque por tipo de item, valor total expedido, contas a receber/pagar
    em aberto e o saldo projetado entre elas). O botão **Atualizar**
    refaz a consulta na hora — os números nunca ficam desatualizados
    porque não existe cache nem valor pré-calculado guardado à parte.
31. Vá em **Usuários** e crie alguém com o perfil "Diretoria": faça login
    com esse usuário e note que ele só vê os links "Painel", "Painel
    Gerencial (BI)" e "Rastreabilidade (Recall)" no menu — nenhuma tela
    operacional (Comercial, Estoque etc.) aparece, e forçar a URL delas
    também não funciona (o servidor recusa com 403). Esse perfil tem só as
    permissões `relatorios.visualizar` e `rastreabilidade.visualizar`,
    deliberadamente separadas das permissões de cada módulo, não uma soma
    delas.
32. Faça login de novo como administrador (ou como um usuário do perfil
    "Qualidade") e vá em **Rastreabilidade (Recall)**: no campo de busca,
    digite o código de um item ou de um lote que você já produziu nos
    passos 13-15 (ex.: o código do produto acabado) e clique em **Ver
    genealogia**. A árvore "Para trás" mostra de que matéria-prima aquele
    lote foi feito — atravessando quantos níveis de produção existirem no
    seu cenário —, e a árvore "Para frente" mostra em que pedidos e para
    quais clientes ele acabou indo (se já tiver sido expedido).
33. Ainda na tela de Rastreabilidade, clique em **Simular Recall**,
    informe um motivo (obrigatório — ex.: "resultado de estabilidade fora
    de especificação") e confirme: isso registra permanentemente um
    snapshot da genealogia completa daquele momento na tabela de
    histórico, abaixo. Clique em **Ver detalhe** numa linha do histórico
    para conferir que o snapshot gravado é fiel à árvore que você viu na
    consulta ao vivo. Se você fizer login como um usuário do perfil
    "Diretoria", repare que o botão **Simular Recall** não aparece — só
    Qualidade decide e registra uma investigação; Diretoria só visualiza.
34. Volte em **Ordens de Produção**, crie e libere mais uma ordem, registre
    o consumo e clique em **Concluir ordem**: repare que o formulário agora
    tem dois campos novos — **Quantidade de perda/refugo** (opcional,
    default 0) e **Motivo da perda**. Informe uma quantidade de perda
    menor que a planejada (ex.: se planejou 10kg, produza 8kg e informe
    2kg de perda) e tente enviar **sem** preencher o motivo: o sistema
    recusa com uma mensagem clara e a ordem continua `em_producao`, pronta
    para você tentar de novo. Preencha o motivo (ex.: "perda de umidade no
    processo") e conclua — a tela de detalhe passa a mostrar um cartão
    **Perda/refugo e rendimento**, com o percentual de perda e o
    percentual de rendimento sobre o planejado calculados automaticamente,
    e o motivo que você informou.
35. Volte a um lote **aprovado** (ex.: o que você aprovou nos passos 7-9)
    e clique em **Baixar CoA (PDF)**, no cartão do Certificado de Análise:
    o navegador baixa um PDF de verdade com o cabeçalho da empresa, os
    dados do lote e a tabela de ensaios/resultados. Abra o arquivo baixado
    para conferir. Repare que um lote ainda em quarentena (nunca aprovado)
    não mostra esse botão — só existe CoA (e, portanto, PDF) depois da
    aprovação.
36. Volte em **Rastreabilidade (Recall)** e clique em **Ver detalhe** numa
    das simulações do histórico (a que você registrou no passo 33): o
    modal agora mostra um botão **Baixar Relatório (PDF)** logo no topo.
    Clique nele e o navegador baixa um PDF com o resumo do impacto, a
    lista de pedidos já expedidos afetados (com cliente e CNPJ, para saber
    quem notificar) e as listas de lotes de origem/derivados — o mesmo
    snapshot que você já vê na tela, só formatado para imprimir ou anexar
    a um processo de conformidade. Repita como um usuário do perfil
    "Diretoria": o botão aparece igual, mesmo esse perfil não tendo
    nenhuma permissão de Lotes/Produção — é a mesma permissão
    `rastreabilidade.visualizar` que já mostrava a tela.
37. Volte em **Ordens de Produção** e clique em **Liberar** numa ordem
    ainda planejada: repare que agora, ao liberar, o sistema já reserva de
    verdade o material da composição (via FEFO) — a tela de detalhe passa
    a mostrar uma seção nova, **Material reservado (garantido via FEFO ao
    liberar)**, com o lote, item e quantidade exatos que ficaram
    comprometidos com essa ordem. Tente liberar uma segunda ordem que
    exigiria mais do item do que sobrou de saldo real (por exemplo, depois
    de já ter vendido ou reservado a maior parte pelo Comercial): a
    liberação é recusada com uma mensagem explicando exatamente o que
    falta, item por item, e a ordem continua **Planejada** — nada fica
    "meio-liberado". Cancele a primeira ordem e tente liberar a segunda de
    novo: agora funciona, porque o material voltou a ficar livre. Também
    vale conferir o sentido inverso: tente **Confirmar** um pedido no
    Comercial pedindo mais do que sobrou depois de uma ordem de produção
    reservar o mesmo item — a confirmação falha do mesmo jeito, porque os
    dois módulos agora enxergam exatamente o mesmo saldo real.
38. Volte em **Lotes / Qualidade** → **+ Registrar recebimento** e desta
    vez preencha o campo novo **Custo unitário pago (R$, opcional)** —
    esse é o preço que alimenta o custo médio de compra do item. Repita
    para os insumos de embalagem da sua fórmula (rótulo, tampa, sílica —
    se você já os cadastrou como itens do tipo "embalagem" e os incluiu
    na composição da fórmula no passo 11). Aprove os lotes pelo fluxo de
    qualidade de sempre.
39. Vá em **Custo do Produto** (novo item de menu — só aparece para quem
    tem a permissão `custeio.visualizar`, por padrão os perfis
    Financeiro, Diretoria e Administrador): você vê o custo padrão
    **projetado** de cada fórmula ativa, calculado a partir do custo
    médio de compra que você acabou de informar. Clique num produto para
    ver o detalhe: os insumos um a um (incluindo a embalagem) e, mais
    abaixo, o histórico de perdas das ordens já concluídas daquele
    produto.
40. Volte na Ordem de Produção que você concluiu no passo 34 (ou conclua
    uma nova): o detalhe agora tem um cartão **Custo de Produção**, com
    duas abas. A primeira, **Custo de Produção**, mostra o custo real
    de cada insumo consumido (quantidade × custo do lote, ou a média do
    item quando o lote específico não tinha custo informado) e o total.
    Clique na aba **Custo com Perdas** para ver a mesma composição, agora
    com a fatia proporcional ao percentual de perda daquela ordem — o
    valor gasto com matéria-prima, rótulo, tampa, sílica etc. que virou
    perda, item por item, exatamente como pedido.
41. Faça login com um usuário do perfil "PCP" (opera produção no dia a
    dia): repare que ele abre a Ordem de Produção normalmente, mas o
    cartão "Custo de Produção" **não aparece** — e o item "Custo do
    Produto" nem aparece no menu. Depois faça login com um usuário do
    perfil "Financeiro": ele vê "Custo do Produto" no menu e consegue
    abrir a tela normalmente, mesmo **sem** ver "Ordens de Produção" (não
    tem essa permissão) — prova visual de que custo é uma permissão
    independente, não uma extensão da permissão de produção.
42. Volte em **Financeiro**: em qualquer conta (a receber ou a pagar) que
    já tenha ao menos uma baixa registrada, clique em **Ver baixas** — um
    modal lista o ledger completo daquela conta. Clique em **Estornar**
    numa baixa lançada por engano, informe o motivo (obrigatório) e
    confirme: a conta é recalculada na hora (volta para "Aberto" se era a
    única baixa, ou fica "Pago parcial" com o saldo certo se havia outras)
    e, ao abrir **Ver baixas** de novo, a baixa original aparece marcada
    com o selo **Estornada** e uma nova linha aparece com o selo
    **Estorno** — nenhuma das duas pode ser estornada de novo (o botão
    some em ambas). Faça login com um usuário do perfil "Compras": ele
    ainda consegue abrir **Ver baixas** normalmente (tem
    `financeiro.visualizar`), mas o botão **Estornar** não aparece em
    nenhuma linha — só o perfil "Financeiro" (e o Administrador) tem as
    permissões novas `estornar_baixa_receber`/`estornar_baixa_pagar`.
43. Volte em **Painel Gerencial**: logo abaixo do cartão **Financeiro**
    aparece o novo cartão **Fluxo de Caixa Projetado** — uma tabela com
    uma linha por faixa (Vencido, 0 a 7 dias, 8 a 15, 16 a 30, 31 a 60, 61
    a 90, Mais de 90 dias), mostrando entradas previstas (contas a
    receber em aberto), saídas previstas (contas a pagar em aberto),
    saldo líquido da faixa e saldo acumulado somando as faixas em ordem.
    A faixa "Vencido" aparece destacada visualmente quando tem algum
    valor. Lance uma conta a pagar ou a receber nova com vencimento em
    datas diferentes (ex.: uma vencida, uma daqui a poucos dias, uma
    daqui a mais de 90 dias) e recarregue o Painel Gerencial: os valores
    de cada faixa mudam na hora, sem precisar de nenhuma migração de
    banco — é 100% calculado a partir das mesmas contas que já aparecem
    em **Financeiro**.
44. Volte em **Rastreabilidade (Recall)**, abra o histórico de simulações
    e clique em **Ver detalhe** numa simulação já registrada (ou registre
    uma nova a partir de um lote com genealogia — passos 33/36 acima): no
    fim do modal aparece a seção **"Bloqueio em massa — status atual de
    cada lote afetado"**, com uma tabela mostrando o status ATUAL (não o
    congelado no snapshot) de cada lote da árvore. Se você tiver a
    permissão `rastreabilidade.bloquear_em_massa` (perfil Qualidade ou
    Administrador), clique em **Bloquear todos os lotes afetados**,
    informe o motivo e confirme: todos os lotes da árvore (o investigado +
    upstream + downstream) viram "Bloqueado" de uma vez, e o mesmo status
    aparece se você for conferir esses lotes na tela **Lotes / Qualidade**
    diretamente. Rode a mesma ação de novo na mesma simulação: nada quebra
    (o botão simplesmente some, porque não há mais nada para bloquear) —
    é seguro clicar de novo por engano. Um pedido de venda já expedido do
    mesmo lote continua com o status normal, sem ser afetado.
45. Vá em **Estoque (WMS)**: logo no topo, antes de "Lotes pendentes de
    endereçamento", aparece o novo cartão **Contagem de Inventário**.
    Clique em **+ Nova contagem**, escolha um depósito e o tipo **Geral**:
    a contagem é criada já com todos os pares lote+posição daquele
    depósito, cada um com o saldo do sistema no momento. Para cada item,
    clique em **Contar** e informe a quantidade fisicamente encontrada —
    se for diferente do saldo do sistema, a diferença aparece destacada em
    vermelho (falta) ou verde (sobra). Enquanto houver item pendente de
    contagem, o botão **Concluir contagem** fica desabilitado. Depois de
    contar todos os itens, clique em **Concluir contagem**: o status muda
    para "Concluída", e se você for conferir a tabela **Saldo em estoque**
    logo abaixo, o saldo físico da posição divergente já está corrigido —
    um ajuste (Fase 4) foi gerado automaticamente só ali. Para testar uma
    contagem **Cíclica**, crie uma nova contagem desse tipo: ela começa
    vazia, e você adiciona os itens um a um informando o ID do lote (visto
    na tela Lotes/Qualidade) e a posição. Tente cancelar uma contagem sem
    informar o motivo: o sistema recusa; informe um motivo e confirme: a
    contagem vira "Cancelada" e nenhum ajuste é gerado.
46. Volte em **Painel Gerencial**: no topo da tela, ao lado do botão
    **Atualizar**, agora tem um botão **Baixar PDF**. Clique nele: o
    navegador baixa um arquivo `Painel-Gerencial-AAAA-MM-DD.pdf` com os
    cinco blocos do painel (Produção, Qualidade, Estoque, Comercial,
    Financeiro) e a tabela do Fluxo de Caixa Projetado, formatados num
    documento pronto pra imprimir ou anexar num e-mail — os mesmos
    números que já estão na tela, só num formato que dá pra levar pra
    uma reunião.
47. Ainda em **Painel Gerencial**, ao lado do botão **Baixar PDF** agora
    tem um botão **Baixar CSV**. Clique nele: o navegador baixa um
    arquivo `Painel-Gerencial-AAAA-MM-DD.csv` com os mesmos números,
    prontos pra abrir direto no Excel/LibreOffice e continuar
    trabalhando neles numa planilha (somar, filtrar, colar num relatório
    maior) em vez de só ler um PDF formatado.
48. Vá em **DRE Simplificado** (só aparece se seu usuário tiver
    `custeio.visualizar` — ex.: perfis Financeiro, PCP com custeio, ou
    Diretoria): a tela mostra Receita Bruta, CMV, Lucro Bruto e Margem
    Bruta calculados a partir dos pedidos já expedidos, mais a tabela de
    pedidos considerados. Use os campos **Expedido de**/**Expedido até**
    e clique em **Filtrar** para restringir a um período — se nenhum
    pedido expedido cair na janela escolhida, a tabela mostra "Nenhum
    pedido expedido no período selecionado." e os KPIs zeram. Se algum
    lote vendido não tiver custo de produção/compra disponível, aparece
    um aviso vermelho listando os lotes afetados, deixando claro que a
    margem mostrada está subestimada em vez de fingir que o custo é zero.
49. Volte em **Estoque (WMS)**, no card **Contagem de Inventário**, e faça
    uma nova contagem geral num depósito com pelo menos um lote — desta
    vez, ao registrar a contagem de um item, informe uma quantidade bem
    diferente do saldo do sistema (mais de 20% de diferença). Ao
    **Concluir contagem**, esse item aparece com o selo **"Aguardando
    aprovação"** em vez de já corrigido — e a tela Estoque passa a
    mostrar um aviso vermelho contando quantos ajustes estão pendentes.
    Se o seu usuário tiver `estoque.aprovar_ajuste_contagem` mas foi você
    mesmo quem contou aquele item, tentar **Aprovar** é recusado (a
    mesma pessoa não pode aprovar o próprio ajuste); faça login com outro
    usuário do perfil Estoque para aprovar (o saldo é corrigido e o selo
    vira "Aprovado") ou rejeitar com um motivo (o selo vira "Rejeitado",
    o motivo aparece na linha, e o saldo não muda).
50. Volte em **Financeiro**, registre um pagamento/recebimento com valor
    acima de R$ 1.000,00 e clique em **Estornar** informando o motivo —
    em vez de reverter na hora, aparece uma mensagem avisando que a
    solicitação ficou pendente de um segundo usuário, e a tela passa a
    mostrar um aviso vermelho contando as solicitações pendentes. Abra
    **Ver baixas** da mesma conta: a baixa aparece com o selo "Estorno
    pendente de aprovação" no lugar do botão "Estornar". Se o seu usuário
    tiver `financeiro.aprovar_estorno_pagar`/`_receber` mas foi você
    mesmo quem solicitou aquele estorno, tentar **Aprovar** é recusado;
    faça login com outro usuário do perfil Financeiro para aprovar (a
    baixa é revertida de fato e o saldo volta a ficar em aberto) ou
    rejeitar com um motivo (nenhuma alteração no saldo). Um pagamento/
    recebimento abaixo de R$ 1.000,00 continua estornando na hora, sem
    nenhuma aprovação extra.
51. Vá em **Itens** e clique em **+ Novo item**: repare que não existe mais
    campo de "Código" no formulário — só descrição, tipo, unidade etc.
    Preencha e clique em **Criar**: a mensagem de sucesso mostra o código
    que o sistema gerou (ex.: "Item criado com o código MP000001." para um
    item de matéria-prima). Crie outro item do mesmo tipo e veja o número
    incrementar (`MP000002`); crie um de tipo diferente (ex.: produto
    acabado) e veja que ele começa sua própria sequência em `PA000001`.
52. Vá em **Memorial Técnico** (novo item de menu — perfil "Regulatório"
    ou administrador): você cai na **Visão Geral**, o painel do módulo,
    com cartões coloridos de estatística e uma barra de navegação escura à
    esquerda (Visão Geral / Empresas / Produtos / Memoriais Técnicos) —
    igual ao sistema original do cliente. Clique em **Empresas** nessa
    barra e depois em **+ Nova empresa**, cadastre uma (nome fantasia,
    razão social, CNPJ, responsável técnico). Clique em **Produtos**,
    depois em **+ Novo produto**, escolha a empresa que você acabou de
    criar e preencha nome/categoria/forma farmacêutica/porção.
53. Clique em **Memoriais Técnicos** na mesma barra, depois em **+ Novo
    memorial**, escolha o produto e deixe o campo de número de certificado
    em branco. Ao criar, você cai na tela de detalhe e o título mostra um
    código gerado automaticamente no formato `CERT-AF-AAAAMMDD/001`. Edite
    algum campo de conteúdo (ex.: composição nutricional) e clique em
    **Salvar** — recarregue a página (F5) e confirme que o texto continua
    lá.
54. Ainda na tela de detalhe, mude o status para **Concluído**: a mudança
    aparece no histórico, na parte de baixo da tela. Clique em **Assinar**,
    preencha o cargo e confirme: sua assinatura aparece na tabela de
    assinaturas, e o botão de assinar some (o mesmo usuário não assina duas
    vezes). Cadastre um segundo usuário com permissão de assinar, faça
    login com ele e assine também: com as **duas assinaturas** e o status
    já em "Concluído", o memorial passa sozinho para **Aprovado** — sem
    precisar de nenhuma ação manual extra.
55. Volte para a lista de **Memoriais Técnicos**: os cartões no topo (KPIs)
    mostram o total de memoriais e quantos estão aguardando
    assinatura/aprovados, batendo com o que você acabou de cadastrar.
    Clique em **Visão Geral** na barra de navegação e confirme que os
    cartões coloridos do painel e a lista "Progresso dos Documentos"
    também batem com o mesmo cenário.
56. Vá em **Centros de Trabalho (APS)** (novo item de menu — perfil PCP ou
    administrador) e clique em **+ Novo centro de trabalho**: dê um nome
    (ex.: "Linha de Encapsulamento 1") e deixe a capacidade paralela em 1.
57. Vá em **Ordens de Produção**, abra uma ordem qualquer (planejada,
    liberada ou em produção) e role até o cartão **"Agendamento (APS)"**.
    Clique em **Agendar**, escolha o centro que você acabou de criar e
    uma janela de início/fim, e confirme: o cartão passa a mostrar o
    centro e o período escolhidos, com os botões **Reagendar**/
    **Desagendar**.
58. Abra uma SEGUNDA ordem de produção e tente agendá-la no MESMO centro
    de trabalho, num horário que se sobreponha ao da primeira: o sistema
    recusa (capacidade paralela 1 já ocupada) e mostra uma mensagem
    dizendo com qual outra ordem é o conflito. Tente de novo com um
    horário que não se sobrepõe — funciona normalmente. Volte na primeira
    ordem e clique em **Desagendar** para liberar a capacidade de novo.
59. Volte em **Memorial Técnico** e clique no grupo **Catálogos** na
    navegação lateral (abre e mostra os 10 itens: Metodologias,
    Nutrientes, Legislações, Alegações, Tipos de Produto, Advertências,
    Armazenamento, Modo de Uso, Justificativas, Referências). Clique em
    **Advertências**, depois em **+ Novo item**, preencha o texto e
    confirme — o item aparece na tabela. Clique em **Editar**, desmarque
    **Ativo** e salve: o item passa a aparecer marcado como "Inativo" na
    tabela (continua listado, só sinalizado — para tirar da lista de vez
    use **Excluir**).
60. Clique em **Tipos de Produto** (outro catálogo, com um campo de
    marcar/desmarcar) e cadastre um item com **Tem Cápsula** marcado —
    confirme que a tabela mostra "Sim" na coluna correspondente.
61. Abra um memorial qualquer (**Memoriais Técnicos** → clique num
    memorial da lista) e repare na nova faixa de abas logo abaixo do
    cartão de resumo: **0. Identificação** a **9. Referências**, mais
    **Assinaturas**, **Anexos**, **Padronização** e **Exportar**. Digite
    algo na aba **1. Objetivo**, troque para a aba **3. Formulação** SEM
    salvar e confirme que o que você digitou na aba 1 continua lá quando
    você volta (não se perde ao trocar de aba). Clique em **Salvar
    conteúdo do memorial** (o botão aparece em qualquer aba numerada).
62. Clique na sub-aba **Anexos** e em **+ Novo anexo**: escolha um
    arquivo PDF ou Word do seu computador, dê um nome e envie — confirme
    que ele aparece na tabela com tamanho e quem enviou. Clique em
    **Baixar** e confirme que o arquivo baixa com o nome original.
63. Clique na sub-aba **Padronização** e preencha alguns campos (ex.:
    Produto, Peso Líquido) — clique em **Salvar padronização**, recarregue
    a página e volte na mesma sub-aba: os valores devem continuar lá.
    Depois clique na sub-aba **Exportar** e em **Imprimir / Salvar como
    PDF** — o diálogo de impressão do navegador abre sem a barra lateral
    nem os botões de ação.
64. Clique em **Agenda (APS)** no menu (mesma área da Fase 25) e confirme
    que aparece uma grade semanal — uma linha por centro de trabalho, uma
    coluna por dia, com a coluna de hoje destacada. Se você já tiver
    agendado alguma ordem (passo da Fase 25), a barra dela aparece na
    célula certa; clique nela e confirme que abre o detalhe da ordem de
    produção correspondente. Use os botões **Semana anterior** /
    **Hoje** / **Próxima semana** para navegar, e o filtro de centro de
    trabalho no topo para ver só uma linha por vez.
65. Abra um memorial qualquer e repare que campos como **Tipo de
    Produto**, **Metodologias Aplicadas**, **Alegações** e
    **Advertências** agora têm um botão **+ Catálogo** ao lado do rótulo.
    Clique nele, escolha um item da lista (cadastre um antes em Memorial
    Técnico → Catálogos, se a lista estiver vazia) e confirme que o texto
    formatado entra no campo — se o campo já tinha algo escrito, o texto
    novo é ACRESCENTADO, não apaga o que já estava lá. Clique em **Salvar
    conteúdo do memorial** e recarregue a página para confirmar que ficou
    gravado.
66. Clique em **Centros de Trabalho** (mesma área da Fase 25), crie ou
    edite um centro e preencha **Custo/hora de mão de obra** e
    **Custo/hora de overhead** (ex.: 60 e 20) — confirme que a tabela
    passa a mostrar uma coluna **Custo/hora** com "MdO: R$ 60,00 / OH:
    R$ 20,00". Agende uma ordem de produção nesse centro (passo da Fase
    25) e conclua-a preenchendo o novo campo opcional **Horas
    apontadas** (ex.: 4). Abra o detalhe da ordem, aba **Custo de
    Produção**, e confirme o novo bloco "Mão de obra e overhead": centro
    de trabalho, horas apontadas, custo de mão de obra (horas × taxa),
    custo de overhead (horas × taxa) e o novo total combinado
    (material + mão de obra + overhead). Conclua outra ordem SEM
    agendamento e SEM apontar horas e confirme que o bloco mostra
    "indisponível" com o motivo exato, em vez de um número inventado.
67. Na tela **Financeiro**, registre um pagamento ou recebimento de valor
    ACIMA de R$1.000,00 (ex.: R$1.500,00) contra uma conta em aberto —
    confirme a mensagem avisando que a solicitação ficou pendente por
    estar acima do valor de alçada, e que o saldo em aberto da conta NÃO
    mudou. Abra **Ver baixas** dessa conta e confirme a nova seção
    "Registros de baixa aguardando aprovação", separada do histórico de
    baixas já lançadas (que continua vazio). Faça login com um segundo
    usuário do perfil Financeiro e clique em **Aprovar** — confirme que
    a baixa agora aparece lançada no ledger e que o saldo em aberto (e o
    status da conta) foi atualizado. Repita registrando outra baixa
    grande e desta vez **Rejeite** com um motivo — confirme que nada foi
    lançado e o saldo continua o mesmo de antes.
68. Na tela **Estoque**, repare no texto de ajuda do card "Contagem de
    Inventário" citando o limiar atual ("acima de 20%..."). Clique em
    **Configurar limiar**, mude para outro valor (ex.: 50) e salve —
    confirme que o texto de ajuda passa a citar o novo percentual.
    Inicie uma contagem geral com uma divergência ENTRE o valor antigo e
    o novo (ex.: 30%, se você mudou de 20% para 50%) e conclua — confirme
    que agora ela ajusta direto, sem pedir segunda aprovação (antes da
    mudança, teria ficado pendente). Faça login com um usuário sem a
    permissão nova e confirme que ele vê o valor atual do limiar (o
    texto de ajuda), mas não vê o botão **Configurar limiar**.
69. Na tela **Financeiro**, repare no texto de ajuda logo abaixo do
    título citando o prazo de estorno atual ("sem limite de prazo" por
    padrão). Clique em **Configurar Financeiro** (renomeado na Fase 41 —
    a mesma tela ganhou um segundo campo, o percentual de imposto sobre
    vendas), informe um número de dias (ex.: 5) e salve — confirme que o
    texto de ajuda passa a citar o novo prazo. Registre uma baixa nova e tente
    estorná-la depois de "envelhecê-la" artificialmente além do prazo
    configurado (só possível manipulando o banco de teste diretamente —
    veja `tests_e2e/teste_fase33_navegador.js` para o script auxiliar; na
    operação normal do dia a dia, isso nunca precisa acontecer, é só uma
    baixa mais antiga que o prazo configurado tentando ser estornada) —
    confirme que o servidor recusa com uma mensagem explicando o prazo
    expirado. Aumente o limite e confirme que o mesmo estorno passa a
    ser aceito. Faça login com um usuário do perfil Financeiro comum e
    confirme que ele vê o prazo atual, mas não vê o botão **Configurar
    prazo de estorno**.
70. Na tela **Estoque**, abra **Configurar limiar** e repare no campo
    novo "Limiar por valor do ajuste (R$, 0 = desligado)". Configure um
    valor (ex.: R$40) mantendo o percentual em 20% e salve — confirme
    que o texto de ajuda passa a citar o gatilho de valor. Faça uma
    contagem em que a diferença seja PEQUENA em percentual (ex.: 5%,
    abaixo do limiar de 20%) mas de item com custo alto o bastante para
    o ajuste financeiro passar de R$40 — conclua e confirme que o item
    fica "Aguardando aprovação" mesmo com percentual pequeno, mostrando
    o valor estimado do ajuste. Aprove com um segundo usuário e confirme
    o ajuste aplicado.
71. Na tela **Estoque**, no novo cartão **Agendamento de Contagens (Fase
    35)**, clique em **+ Novo agendamento**: escolha um depósito, tipo
    "Geral" e cadência "Diária" e salve — repare que a mensagem confirma
    a criação E já avisa que uma contagem foi gerada automaticamente
    (cadência diária está sempre "vencida"). Reabra a tela (troque de
    página e volte): a mesma contagem não se duplica. Edite o
    agendamento e desmarque "Ativo" — confirme o selo "inativo" na
    tabela. Exclua o agendamento e confirme que a contagem que ele já
    tinha gerado continua na lista de Contagens, só sem o vínculo (a
    exclusão da regra nunca apaga o histórico).
72. Como **Administrador**, na tela **Comercial**, clique em
    **Configurar** no cartão **App de Vendas (Fase 36)** e defina, por
    exemplo, 10% de verba gerada, 5% de comissão padrão e 240 minutos de
    expiração — salve e confirme a mensagem. Crie dois usuários do perfil
    **Vendedor** e um cliente ativo (se ainda não tiver).
73. Logado como o primeiro **Vendedor**, abra a nova tela **App de
    Vendas**: clique em **+ Novo rascunho**, escolha o cliente, depois
    **+ Adicionar item** e reserve uma parte do saldo de um produto
    acabado — confirme que o valor total do rascunho aparece certo.
    **Sem enviar**, faça logout.
74. Logado como o **segundo Vendedor**, abra o mesmo cliente num rascunho
    novo e repare que o saldo "disponível" do mesmo item já está menor (o
    que o primeiro vendedor reservou desapareceu do que sobra para você).
    Tente reservar mais do que sobrou — confirme o erro "Saldo
    insuficiente". Reserve só o que sobrou e **envie o pedido**.
75. Volte a logar como o primeiro vendedor, confirme que o rascunho dele
    continua exatamente como deixou, e **envie o pedido** também — os
    dois pedidos confirmados, cada um com o vendedor certo.
76. Como Administrador, expeça um dos pedidos acima (tela **Comercial** →
    abrir o pedido → **Expedir**) e confirme, na tela **App de Vendas**
    (como o vendedor daquele pedido, num rascunho novo para o mesmo
    cliente), que o botão **Aplicar verba neste pedido** mostra o saldo
    de verba gerado pela venda anterior, e que aplicá-lo abate o valor
    total do novo rascunho na tela.
77. Registre uma baixa parcial na conta a receber gerada (tela
    **Financeiro**), depois abra **Minhas Comissões** (logado como o
    vendedor da venda) e confirme que a comissão **projetada** e a
    **realizada** aparecem como dois números diferentes — a realizada só
    reflete o que já foi baixado.
78. Conclua uma contagem de inventário com divergência grande (mesmo
    roteiro do passo 49) logado como quem CONTOU o item — não aprove
    ainda. Clique no sino de notificações (barra superior, ao lado do
    botão de tema) e confirme que ele mostra um número; abra a tela
    **Notificações** e confirme que a mensagem sobre a contagem aparece
    destacada como não lida.
79. Faça login como outro usuário com `estoque.aprovar_ajuste_contagem`
    (quem CONTOU não recebe a própria notificação — segregação de
    função) e confirme que ELE vê a notificação. Marque como lida e
    confirme que o sino esconde o número; clique em **Marcar todas como
    lidas** com mais de uma pendência para confirmar o atalho.
80. Na mesma tela **Notificações**, logado como Administrador, desmarque
    "Também receber estas notificações por e-mail" e salve — confirme
    que a caixinha continua desmarcada depois de recarregar a tela
    (qualquer usuário pode fazer isso para si mesmo, sem permissão
    especial). Volte a marcar, para não afetar os próximos testes.
81. Ainda como Administrador (só ele tem `sistema.configurar_email` por
    padrão), preencha o cartão **Configuração de E-mail (SMTP)** com os
    dados do seu servidor de e-mail de verdade (ou de um serviço de
    teste como o Mailtrap) e clique em **Salvar**, depois em **Enviar
    e-mail de teste** — confirme que a mensagem de confirmação aparece
    na tela e que o e-mail chega de verdade na caixa de entrada
    configurada. Repare que o campo de senha nunca mostra a senha já
    salva de volta (só o texto "deixe em branco para manter a senha
    atual"); salve de novo sem preencher a senha e confirme que o envio
    de teste continua funcionando (a senha antiga foi preservada).
82. Estreite a janela do navegador até menos de 900px de largura (ou abra
    as ferramentas de desenvolvedor e emule um celular, ex.: iPhone SE) e
    confirme que a barra lateral desaparece e um botão de hambúrguer (☰)
    aparece na barra superior; clique nele para abrir a "gaveta" com o
    menu, toque fora dela (na área escurecida) para fechar, e clique num
    link do menu para confirmar que ela fecha sozinha ao navegar.
83. Ainda com a janela estreita, abra qualquer tela com uma tabela grande
    (ex.: **Itens** ou **Fornecedores**) e confirme que a tabela ficou
    dentro de uma faixa com rolagem horizontal própria, sem "quebrar" o
    layout da página nem empurrar o restante da tela para o lado.
84. No celular ou tablet de verdade (não só emulado), abra o endereço do
    servidor pelo navegador (Chrome/Safari) e use o menu do navegador
    para **"Adicionar à tela inicial"** ou **"Instalar app"** — confirme
    que o ícone da Alphafitus aparece na tela inicial do aparelho, e que
    abrir por ele mostra o sistema em janela própria, sem a barra de
    endereço do navegador por cima.
85. Cadastre um item de matéria-prima e um de produto acabado, uma
    fórmula ativa ligando os dois, e crie uma ordem de produção planejada
    pedindo mais insumo do que você tem em estoque aprovado (ou não
    receba/aprove nenhum lote do insumo). Vá em **MRP (Necessidade de
    Materiais)** (novo item de menu) e confirme que o insumo aparece
    destacado com a falta calculada corretamente (necessidade menos
    disponível), citando o número da ordem que gera a necessidade.
86. Homologue um fornecedor para esse mesmo item (tela **Fornecedores**,
    aprove o fornecedor e homologue-o para o item) e confirme que ele
    aparece listado na linha do insumo em falta na tela de MRP.
87. Crie uma segunda ordem planejada usando o MESMO insumo em falta acima
    e confirme que a necessidade total na tela de MRP é a SOMA das duas
    ordens (não é preciso ter saldo suficiente para nenhuma delas
    isoladamente para o problema aparecer). Libere uma das duas ordens
    (com saldo suficiente reservado só para ela) e confirme que ela some
    de saldo hoje "disponível" mostrado (a reserva dela já foi descontada
    do disponível), mas que ela mesma DEIXA de aparecer na necessidade
    somada (só ordens `planejada` entram na soma).
88. Registre uma baixa de uma conta a receber (tela **Financeiro**) com um
    valor e data que você vai lembrar (ex.: R$ 150,00 em 01/08/2026). No
    seu Internet Banking (ou editando um arquivo `.ofx` de exemplo à mão,
    num editor de texto simples), monte um extrato com uma transação de
    crédito com o mesmo valor e uma data dentro de 3 dias. Vá em
    **Conciliação Bancária** (novo item de menu), clique em "Importar
    extrato (OFX)", escolha o arquivo e confirme que a transação aparece
    já **conciliada automaticamente** com a baixa certa, marcada como
    "(automático)".
89. Registre duas baixas de contas diferentes com o MESMO valor (ex.: duas
    de R$ 80,00) e importe um extrato com uma transação de crédito de R$
    80,00. Confirme que ela fica **pendente** (não escolhe nenhuma das
    duas sozinha) e que abrir "Conciliar" mostra as DUAS opções para você
    escolher manualmente. Escolha uma, confirme que concilia sem a marca
    de "automático", clique em "Desconciliar" e confirme que ela volta
    para pendente e libera a baixa para ser escolhida de novo.
90. Reimporte o MESMO arquivo `.ofx` do passo 88 (ou 89) e confirme que a
    tela avisa "0 transação(ões) nova(s)" e que todas aparecem como "já
    importada(s) antes" — nada é duplicado nem reconciliado de novo.
91. Na tela **Financeiro**, clique em **+ Nova conta a pagar** e lance uma
    despesa (ex.: "Aluguel do galpão", R$800,00), escolhendo a categoria
    **Despesa operacional**. Confirme que a coluna "Categoria" da tabela
    mostra o selo certo. Lance outra conta SEM tocar na categoria (deve
    assumir "Compra" automaticamente). Vá em **DRE Simplificado** e
    confirme que só a despesa operacional aparece no card "Despesas
    Operacionais" e na tabela "Despesas operacionais no período" — a
    compra nunca deveria aparecer ali.
92. Ainda na tela **Financeiro**, clique em **Configurar Financeiro** e
    informe um percentual de imposto sobre vendas (ex.: 10%). Salve e
    confirme que o texto de ajuda passa a citar o percentual. Volte para
    o **DRE Simplificado** e confirme que o card "Impostos sobre Vendas"
    mostra o rótulo com o percentual configurado e o valor calculado
    (percentual × Receita Bruta do período), e que o "Lucro Líquido"
    é igual a Lucro Bruto − Despesas Operacionais − Impostos sobre
    Vendas. Faça login com um usuário do perfil Financeiro comum (sem
    `configurar_limite_estorno`) e confirme que ele NÃO vê o botão
    **Configurar Financeiro** nem **+ Nova conta a pagar** (mesmas
    permissões de sempre, nenhuma nova).
93. Na tela **Painel Gerencial**, confirme que ele abre sem nenhum cartão
    "No período" — só os cartões de sempre (Produção, Qualidade, Estoque,
    Comercial, Financeiro). No cartão novo **Filtrar por período**,
    preencha "De" e "Até" com o dia de hoje e clique em **Filtrar**.
    Confirme que aparece o cartão **"No período (Fase 42)"** com Ordens
    concluídas, Lotes aprovados/reprovados, Pedidos expedidos e os
    valores expedido/recebido/pago — todos batendo com o que você
    cadastrou nas telas de Produção/Qualidade/Comercial/Financeiro hoje.
94. Ainda no Painel Gerencial, mude o filtro para uma data bem antiga
    (ex.: 01/01/2000 a 02/01/2000) e confirme que o cartão "No período"
    continua aparecendo, só que com os números zerados. Clique em
    **Atualizar** e confirme que o filtro preenchido continua lá (não
    volta pro padrão). Clique em **Baixar CSV** com o filtro aplicado e
    confirme que o arquivo baixado tem uma seção "No período" no fim —
    baixe de novo sem nenhum filtro preenchido e confirme que essa seção
    não aparece.
95. Abra um memorial qualquer, vá na sub-aba **Exportar** e clique em
    **Baixar PDF Completo**. Abra o PDF baixado e confirme que ele tem o
    conteúdo do memorial formatado (com os títulos das abas, "0.
    Identificação", "1. Objetivo" etc., só aparecendo quando o campo
    correspondente tiver algo preenchido).
96. Ainda no mesmo memorial, vá na sub-aba **Anexos** e envie um arquivo
    de imagem de verdade (JPG ou PNG) e, em seguida, um arquivo de Word
    ou Excel qualquer. Volte em **Exportar** e baixe o **PDF Completo**
    de novo: confirme que ele cresceu de tamanho (a imagem virou uma
    página nova) e que, no fim do PDF, existe uma página "Anexos não
    incorporados neste PDF" listando o arquivo de Word/Excel com o
    motivo — e que ele continua disponível para baixar separadamente na
    tabela de Anexos.
97. No menu do **Memorial Técnico**, confirme que existe um item novo
    **Usuários Online**. Clique nele: você mesmo (o usuário logado agora)
    deve aparecer com o selo **Online** e o "último acesso" preenchido
    com a hora de agora. Se tiver outro usuário cadastrado que nunca fez
    login, confirme que ele aparece **Offline** com o "último acesso"
    vazio ("—") — espere 5 minutos sem usar o sistema com um usuário e
    atualize a tela: ele deve passar de Online para Offline sozinho
    (ver `ONLINE_JANELA_MINUTOS` em `app/routes/usuarios.py`).
98. Na tela **Painel Gerencial**, clique em **Baixar XLSX** (ao lado de
    "Baixar PDF"/"Baixar CSV") e abra o arquivo baixado no Excel/
    LibreOffice Calc/Google Sheets. Confirme que existem duas abas
    ("Painel Gerencial" e "Fluxo de Caixa Projetado"), que os números
    batem com o que a tela mostra, e que a célula de moeda está formatada
    de verdade (aparece "R$" alinhado, não um número cru). Na aba "Fluxo
    de Caixa Projetado", clique na célula da linha "Total" — a barra de
    fórmulas deve mostrar `=SOMA(...)` (ou `=SUM(...)`, dependendo do
    idioma do programa), não um número fixo.
99. No menu do **Memorial Técnico**, abra o grupo **Administração** (ao
    lado de "Usuários Online") e clique em **Snapshots & Restauração**.
    Clique em **Baixar Snapshot (.json)** e confirme que baixa um arquivo
    JSON com a situação atual — abra num editor de texto e confira que
    existe a chave `"tabelas"` com as 8 tabelas do módulo. Cadastre algo
    novo (por exemplo, um item em qualquer catálogo), depois volte em
    **Restaurar snapshot**, escolha o arquivo baixado ANTES desse
    cadastro e clique em **Restaurar**: confirme que aparece um aviso
    resumindo quantos registros de cada tabela serão restaurados antes de
    perguntar se você quer continuar, e que, depois de confirmar, o item
    que você cadastrou depois do snapshot desaparece (a tela mostra uma
    mensagem de sucesso com o total de registros restaurados). Tente
    também subir um arquivo qualquer que não seja um snapshot válido (um
    `.json` vazio, por exemplo) — confirme que a tela mostra um erro
    claro e que nada no sistema muda. Repita o teste logado com um
    usuário que só tem `memoriais.visualizar` (sem `memoriais.excluir`):
    o botão **Restaurar** não deve aparecer, só a explicação de que falta
    permissão.
100. No mesmo grupo **Administração**, clique em **Backups do Sistema**.
     Clique em **Baixar Backup Completo (.db)** e confirme que baixa um
     arquivo `.db`. Se tiver o `sqlite3` instalado, abra-o
     (`sqlite3 Alphafitus-Backup-Completo-*.db "select count(*) from
     usuarios;"`) e confirme que ele tem os MESMOS usuários do sistema —
     diferente do Snapshot da Fase 46, este arquivo é o banco INTEIRO, não
     só as tabelas do Memorial Técnico. Confirme que a tela NÃO tem nenhum
     botão de "restaurar" (é proposital — restaurar este tipo de backup é
     um procedimento manual, com o serviço parado, não uma ação de um
     clique). Repita o teste logado com um usuário que tem TODAS as
     permissões do Memorial Técnico (incluindo `memoriais.excluir`, usada
     para restaurar Snapshots) mas não tem `sistema.backup_completo`:
     confirme que o item **Backups do Sistema** nem aparece no menu para
     esse usuário.
101. No mesmo grupo **Administração**, clique em **Gerenciar Usuários**
     (aparece ANTES de "Usuários Online" na lista). Confirme que a nav
     escura do Memorial Técnico continua visível ao redor da tabela — não
     é a tela central "pura". Crie, edite ou inative um usuário por aqui
     (os mesmos botões de sempre) e confirme que a lista central (menu
     **Usuários**, fora do Memorial Técnico) reflete exatamente a mesma
     mudança — é o mesmo cadastro, não uma cópia separada.
102. No mesmo grupo **Administração**, clique em **Configurações** (o
     último item, fecha a seção). Confirme que os dois campos mostram os
     valores padrão (2 assinaturas / 40 MB). Altere o "Nº de assinaturas
     para aprovação automática" para 3 e salve; volte em qualquer memorial
     com status "Concluído" e confirme que, com só 2 assinaturas, ele NÃO é
     mais aprovado automaticamente — a terceira assinatura é que aprova.
     Depois reduza o "Tamanho máximo de anexo (MB)" para um valor pequeno
     (ex.: 1) e confirme, na sub-aba **Anexos** de um memorial, que um
     arquivo maior que esse limite é rejeitado com a mensagem de erro
     mostrando o novo limite. Repita o teste logado com um usuário que só
     tem `memoriais.visualizar` (sem `memoriais.configurar`): a tela deve
     mostrar os valores atuais, mas sem nenhum formulário para editá-los.
103. Abra uma ordem de produção **liberada** (ou já **em produção**, com
     algum consumo registrado) em **Ordens de Produção**. No cartão novo
     **Etapas do processo (opcional)**, clique em **+ Nova etapa** e
     cadastre "Pesagem", depois cadastre "Embalagem" da mesma forma.
     Clique em **Concluir ordem** e confirme que o modal avisa que há
     etapas pendentes e que o botão de enviar fica desabilitado — feche o
     modal sem enviar. Volte ao cartão de etapas, clique em **Apontar
     perda** na linha "Pesagem", informe 0,5kg com um motivo, e conclua;
     repita para "Embalagem" com 1,5kg e outro motivo. Agora clique em
     **Concluir ordem** de novo: note que os campos de quantidade/motivo
     de perda não aparecem mais (a ordem já tem etapas) e o botão de
     enviar está habilitado; informe a quantidade produzida e conclua.
     Confirme que o cartão **Perda/refugo e rendimento** mostra 20% de
     perda com o motivo sintetizado automaticamente citando as duas
     etapas, e que a aba **Custo com Perdas** (dentro de Custo de
     Produção) mostra a tabela nova **Fatia do custo da perda por etapa**
     repartindo o mesmo custo total da perda entre "Pesagem" e
     "Embalagem", proporcionalmente ao que cada uma apontou.
104. Repare que o menu lateral agora vem dividido em seções recolhíveis
     por módulo ("Qualidade", "Produção & PCP", "Estoque", "Comercial &
     Vendas", "Financeiro", "Relatórios & Custos", "Administração") —
     Painel, Itens, Memorial Técnico, Minha Conta e Notificações continuam
     soltos, fora de qualquer grupo. Clique no título de um grupo fechado
     (ex.: "Financeiro") e confirme que ele expande mostrando os itens de
     dentro; clique de novo para fechar. Navegue para uma tela dentro de
     outro grupo ainda fechado (ex.: **Custo do Produto**, dentro de
     "Relatórios & Custos") direto por uma busca no navegador ou um link
     — confirme que o grupo dela abre por conta própria, sem precisar
     clicar em nada. Dê um F5 de verdade na página (não só clique num
     link) e confirme que os grupos que você abriu manualmente continuam
     abertos, e os que nunca tocou continuam fechados — essa preferência
     fica salva no seu navegador, não no servidor (cada usuário tem a
     própria). Faça login com um usuário do perfil "Vendedor" e confirme
     que só aparece o grupo "Comercial & Vendas" no menu — os outros 6
     grupos somem por completo (não ficam vazios), exatamente como os
     itens soltos que esse perfil não tem permissão de ver desde a Fase 1.
105. Cadastre 2 empresas em **Empresas** (ex.: "Unidade A" e "Unidade B").
     Em **Ordens de Produção**, clique em **+ Nova ordem** e confirme que
     apareceu um campo opcional **Empresa** — crie uma ordem marcando
     "Unidade A". Em **Lotes/Qualidade**, registre um recebimento também
     marcando "Unidade A"; em seguida registre outro marcando "Unidade B".
     Em **Comercial**, crie um pedido marcando "Unidade A"; em
     **Financeiro**, lance uma conta a pagar marcando "Unidade B". Abra o
     **Painel Gerencial**: confirme que o cartão "Filtros" agora tem um
     seletor **Empresa** ao lado do de período. Filtre por "Unidade A" e
     confirme que aparece o indicador **Filtrando por: Unidade A** logo
     abaixo dos botões de exportar, e que os cinco cartões de situação
     atual (Produção, Qualidade, Estoque, Comercial, Financeiro) mostram
     só o que foi marcado com essa empresa. Troque para "Unidade B" e
     confirme que os números mudam de acordo. Clique em **Limpar filtro
     de empresa** e confirme que o indicador some e os números voltam a
     somar as duas empresas. Baixe o CSV com um filtro de empresa
     aplicado e confirme que o arquivo tem uma linha **Filtrando por**
     logo no topo. Por fim, tente aplicar o filtro com uma empresa que
     não existe editando a URL manualmente (ex.:
     `#/painel-gerencial` seguido de forçar `empresa_id=999999` numa
     chamada direta à API) e confirme que a resposta é 404 — a tela em si
     não deixa escolher uma empresa inválida, então isso só é visível
     inspecionando a chamada de rede.
106. Em **Lotes/Qualidade**, receba e aprove um lote qualquer, produza um
     pedido expedido a partir dele (mesmo fluxo de sempre: fórmula ativa,
     ordem concluída, endereçamento, cliente, pedido confirmado e
     expedido). Vá em **Rastreabilidade**, busque esse lote e clique em
     **Simular Recall** informando um motivo. Abra o detalhe da simulação
     recém-criada e confirme a nova seção **Decisões sobre pedidos já
     expedidos**, mostrando o pedido que você acabou de expedir com seu
     status atual e o da conta a receber. Clique em **Registrar decisão**,
     escolha por exemplo "Notificar cliente", preencha o motivo e
     confirme — o modal reabre já mostrando a decisão no histórico. Repita
     registrando uma segunda decisão (ex.: "Cancelar pedido") e confirme
     que AMBAS aparecem no histórico, nenhuma sobrescreveu a outra. Por
     fim, vá em **Comercial** e confirme que o pedido continua com status
     **Expedido** — registrar a decisão não cancela nada automaticamente,
     isso continua exigindo a ação própria da tela de Comercial.
107. Cadastre uma fórmula ativa e crie uma ordem de produção **planejada**
     (não libere) pedindo mais insumo do que existe em estoque, de forma
     que sobre falta. Vá em **MRP (Necessidade de Materiais)** e confirme
     que o insumo aparece com a falta calculada e o botão **Gerar
     sugestões de compra**. Clique nele — você é levado para a tela nova
     **Sugestões de Compra (MRP)**, com a sugestão pendente mostrando a
     quantidade e (se você tiver homologado algum fornecedor para esse
     insumo) o fornecedor sugerido. Clique em **Gerar sugestões de
     compra** de novo a partir do MRP e confirme que aparece "0 sugestões
     novas" — não duplicou. Na tela de Sugestões, clique em **Atender**
     na sugestão, informe opcionalmente o ID de uma conta a pagar já
     lançada em Financeiro e confirme; a sugestão sai da aba Pendentes e
     aparece em Atendidas, com o ID linkado. Gere sugestões de novo (a
     falta persiste) e, na nova sugestão pendente, clique em **Descartar**
     informando um motivo — confirme que ela aparece na aba Descartadas
     com o motivo visível. Por fim, clique na aba **Todas** e confirme que
     as duas sugestões decididas (atendida e descartada) aparecem juntas.

108. Em **Financeiro**, clique em **Configurar Financeiro** e confirme que
     o campo **Tolerância de dias para conciliação bancária** mostra 3 (o
     padrão). Em **Conciliação Bancária**, importe um extrato OFX com uma
     transação cuja data fique 4 ou 5 dias longe de uma baixa já
     registrada com o mesmo valor — confirme que ela fica **pendente**
     (fora da janela padrão). Volte em **Configurar Financeiro**, aumente
     a tolerância para um valor que cubra essa diferença e salve — a dica
     no topo da tela já mostra o novo valor. Volte para **Conciliação
     Bancária** e clique em **Conciliar todos os candidatos únicos**
     (tanto na lista de extratos quanto na tela de detalhe de um extrato
     específico) — confirme que a transação antes pendente agora aparece
     conciliada, e que o botão fica desabilitado quando não sobra nenhuma
     pendente. Lance uma conta a pagar SEM baixa, importe um extrato com
     uma transação débito do mesmo valor (fica pendente por falta de
     candidato), registre a baixa dessa conta DEPOIS da importação e
     clique em **Conciliar todos os candidatos únicos** de novo — confirme
     que agora ela concilia automaticamente, sem precisar escolher
     manualmente.

109. Feche um pedido expedido (Comercial) gerando alguma Receita Bruta no
     período — se você já tem um pedido expedido de um teste anterior,
     pode reaproveitar. Vá em **DRE Simplificado** e confirme que, sem
     nada configurado ainda, NÃO existe nenhuma tabela "Impostos sobre
     Vendas — detalhamento por tributo" na tela (comportamento idêntico
     ao de antes desta fase). Vá em **Financeiro → Configurar Financeiro**
     e preencha PIS = 1,65, COFINS = 7,6, ICMS = 18 e ISS = 5 (deixando o
     percentual genérico em branco/0) e salve. Volte ao **DRE
     Simplificado** e confirme que "Impostos sobre Vendas" agora soma as
     quatro alíquotas sobre a Receita Bruta do período, que a nova tabela
     de detalhamento aparece com exatamente 4 linhas (uma por tributo,
     sem a linha "Imposto genérico" porque ela ainda está zerada) e que o
     Total no rodapé da tabela bate com o KPI. Volte em **Configurar
     Financeiro**, confirme que os quatro campos reabrem já preenchidos
     com os valores salvos, preencha também o percentual genérico (por
     exemplo 10) e salve — confirme que os quatro campos anteriores NÃO
     foram zerados. No DRE, confirme que o total agora soma as cinco
     alíquotas juntas (a genérica somando, não substituindo as quatro
     detalhadas) e que a tabela de detalhamento passa a mostrar 5 linhas,
     incluindo a nova linha "Imposto genérico".

110. Em **Fornecedores**, clique em **+ Novo fornecedor** e cadastre um
     informando um **Lead time de entrega (dias)**, por exemplo 10 —
     confirme que a lista mostra "10 dia(s)" na coluna nova. Clique em
     **Homologar item** para vincular um insumo a esse fornecedor e em
     **Status** para aprová-lo. Cadastre uma fórmula ativa e crie uma
     ordem de produção **planejada** pedindo mais desse insumo do que
     existe em estoque, de forma que sobre falta. Vá em **MRP
     (Necessidade de Materiais)** e confirme que a coluna nova **Comprar
     até** mostra "nenhuma ordem agendada ainda" (nenhuma data
     inventada). Abra a ordem, clique em **Agendar**, escolha um centro
     de trabalho e uma janela de data/hora futura, e salve. Volte ao MRP
     e confirme que **Comprar até** agora mostra uma data — o início
     planejado da ordem menos os 10 dias de lead time. Clique em **Gerar
     sugestões de compra** e confirme que a tela de **Sugestões de
     Compra** mostra a MESMA data na coluna **Comprar até**. Volte em
     **Fornecedores**, clique em **Lead time** no fornecedor, confirme
     que o campo já vem preenchido com 10, altere para um valor menor e
     salve — confirme que a lista reflete o novo valor. Volte em
     **Sugestões de Compra** e confirme que a sugestão JÁ GERADA continua
     mostrando a data ANTIGA (o snapshot não muda sozinho), enquanto o
     MRP (cálculo ao vivo) já mostra uma data nova, mais próxima, refletindo
     o lead time reduzido.

Eu já verifiquei os cinquenta e sete fluxos completos (Fase 1 a 57, já com o
visual atualizado do Memorial Técnico, a interface da Fase 25, os 10
catálogos da Fase 26, a tela de edição em abas + Anexos + Padronização da
Fase 27, a Agenda Visual/Gantt da Fase 28, os catálogos como seletores da
Fase 29, o custo de mão de obra/overhead na produção da Fase 30, a
aprovação dupla de registro de baixa da Fase 31, o limiar de divergência
configurável da Fase 32, o limite de prazo para estorno configurável da
Fase 33, a alçada por valor do ajuste de contagem da Fase 34, o
agendamento automático de contagens da Fase 35, o Aplicativo de Vendas
com reserva temporária, verbas comerciais e comissão do vendedor da Fase
36, e o sino/tela de Notificações com envio real de e-mail (incluindo um
servidor SMTP de teste rodando localmente, para confirmar que o e-mail
disparado pela própria tela chega de verdade a um servidor, sem precisar
de nenhuma conta de e-mail real) da Fase 37, a gaveta de menu/rolagem de
tabelas/registro do service worker emulando viewport de celular e de
tablet em retrato da Fase 38, o relatório de MRP com um insumo em
falta (necessidade somada de duas ordens planejadas, fornecedor
homologado listado, link para a ordem) e um sem falta da Fase 39, e a
Conciliação Bancária importando um extrato OFX de verdade pelo upload
de arquivo da tela — crédito e débito com match único conciliando
automaticamente, um crédito ambíguo (dois candidatos do mesmo valor)
ficando pendente até a escolha manual pela tela, uma transação sem
nenhum candidato sendo ignorada com motivo, desconciliar e reconciliar
manualmente, e reimportar o mesmo arquivo sem duplicar nada — da Fase
40, e o DRE Completo lançando uma despesa operacional e uma compra
comum pela tela (só a despesa entra nas Despesas Operacionais),
configurando o percentual de imposto sobre vendas pelo modal
"Configurar Financeiro" e confirmando Impostos sobre Vendas/Lucro
Líquido/Margem Líquida corretos no DRE, com a segregação de permissão
verificada na própria UI (perfil Financeiro comum não vê nenhum dos
dois botões) — da Fase 41, e o Painel Gerencial sem filtro nenhum
mostrando só os cinco cartões de sempre, filtrando pelo dia de hoje e
vendo o cartão novo "No período" com os números batendo com um cenário
real (ordem concluída, lote aprovado e reprovado, pedido expedido com a
baixa da conta a receber, conta a pagar baixada), filtrando por uma
janela sem eventos e vendo o mesmo cartão zerado, "Atualizar"
preservando o filtro aplicado, e o CSV baixado incluindo a seção "No
período" só quando o filtro é usado — da Fase 42, e o Memorial Técnico
baixando o "PDF Completo" pelo botão novo na sub-aba Exportar (confirma
a assinatura `%PDF-` do arquivo e um tamanho mínimo razoável para o
memorial sozinho), depois enviando um anexo de imagem de verdade e um
de Word pela tela de Anexos e baixando o PDF Completo de novo,
confirmando que ele cresceu (a imagem foi incorporada) e continua
sendo um PDF válido mesmo com o anexo de Word não incorporável — da
Fase 43, e o novo item de menu "Usuários Online" dentro do Memorial
Técnico mostrando o próprio admin (que acabou de navegar) como Online e
um usuário criado mas que nunca fez login como Offline com o "último
acesso" vazio — da Fase 44, e o botão novo "Baixar XLSX" no Painel
Gerencial baixando um arquivo com a assinatura binária de um ZIP de
verdade ("PK", já que um .xlsx é um ZIP por dentro), com o nome sugerido
no formato esperado, e crescendo de tamanho quando o filtro de período é
aplicado (ganhando a terceira seção na aba) — da Fase 45, e o novo item
"Snapshots & Restauração" dentro do grupo "Administração" baixando um
snapshot .json de verdade, cadastrando um item de catálogo novo DEPOIS
do download, restaurando esse snapshot mais antigo pela tela (aceitando
o aviso de confirmação, que mostra o resumo de quantos registros de cada
tabela serão restaurados) e confirmando pela API que o item cadastrado
depois desapareceu, além de subir um arquivo malformado e confirmar que
a tela rejeita com um erro claro sem alterar nada — da Fase 46, e o novo
item "Backups do Sistema" (também dentro do grupo "Administração")
baixando um arquivo com a assinatura binária OFICIAL de um SQLite de
verdade ("SQLite format 3\0"), confirmando que a tela não tem nenhum
campo de upload/botão de restaurar (decisão de segurança, não uma
lacuna), e confirmando pela API que o cenário do sistema (usuários,
permissões) é o mesmo capturado no backup — da Fase 47, e o novo item
"Gerenciar Usuários" (também dentro do grupo "Administração") mostrando a
MESMA tabela de usuários que a tela central mostra, com a nav do Memorial
continuando visível ao redor dela, e inativando um usuário a partir de
dentro do Memorial para confirmar, pela API, que a mudança é visível pela
tela central — provando que é o mesmo dado, não uma cópia — da Fase 48, e
o novo item "Configurações" (fechando o grupo "Administração") mostrando
os valores padrão (2 assinaturas / 40 MB), assinando um memorial
"Concluído" duas vezes com a configuração padrão e confirmando que ele é
aprovado automaticamente (mesmo comportamento de sempre — Fase 24),
depois aumentando o número de assinaturas exigidas pela tela e confirmando
o campo salvo refletindo o novo valor, e confirmando que um perfil sem
`memoriais.configurar` vê os valores em modo só-leitura, sem nenhum
formulário — da Fase 49, e o cartão novo "Etapas do processo" cadastrando
duas etapas ("Pesagem" e "Embalagem"), o modal de concluir a ordem
avisando e desabilitando o envio enquanto houver etapa pendente,
apontando a perda de cada uma pela tela, concluindo a ordem sem informar
perda/motivo diretamente (vêm somados das etapas), e confirmando o
percentual de perda/motivo sintetizado no cartão "Perda/refugo e
rendimento" e a tabela nova "Fatia do custo da perda por etapa" na aba
"Custo com Perdas", com a matemática batendo exatamente com a proporção
apontada em cada etapa — da Fase 50, e o menu lateral agora agrupado por
módulo (Qualidade, Produção & PCP, Estoque, Comercial & Vendas,
Financeiro, Relatórios & Custos, Administração) confirmando que nenhum
grupo abre sozinho partindo do Painel, que um link dentro de um grupo
fechado não é clicável até abrir o grupo, que navegar para dentro de um
grupo abre ele automaticamente, que abrir/fechar manualmente é lembrado
depois de um F5 de verdade (não só troca de hash), e que o perfil
"Vendedor" só vê 1 dos 7 grupos no menu (os outros somem por completo,
não ficam vazios) — da Fase 51, e o Painel Gerencial filtrado por
empresa: com 2 empresas cadastradas e uma ordem/lote/pedido/conta a pagar
marcados em cada uma, confirmando que filtrar por uma empresa mostra o
indicador "Filtrando por" e só os números daquela empresa nos cinco
cartões de situação atual, que trocar de empresa muda os números, que
"Limpar filtro de empresa" volta a somar as duas, que o CSV exportado com
o filtro aplicado mostra a mesma seção "Filtrando por", e que o
formulário de nova ordem de produção ganhou o seletor opcional de
empresa — da Fase 52, e o Recall — Decisão sobre Pedidos Já Expedidos:
simulando um recall a partir de um lote com pedido já expedido, abrindo o
detalhe da simulação e confirmando a nova seção "Decisões sobre pedidos
já expedidos" listando o pedido com seu status atual, registrando uma
primeira decisão ("Aguardar devolução") e confirmando que ela aparece no
histórico com motivo e observação completos, registrando uma segunda
decisão ("Cancelar pedido") e confirmando que AMBAS ficam preservadas no
histórico (nada é sobrescrito), e confirmando, na tela de Comercial, que
o pedido continua com status "Expedido" mesmo depois de uma decisão de
"cancelar" ser registrada — a rota só registra, nunca executa sozinha —
da Fase 53, e o MRP — Sugestão Automática de Compra: confirmando que o
botão "Gerar sugestões de compra" só aparece na tela de MRP quando há
insumo em falta, que clicar nele leva à tela nova "Sugestões de Compra"
já mostrando a quantidade e o fornecedor homologado sugerido, que clicar
de novo não duplica a sugestão pendente do mesmo item, que "Atender"
linkando o ID de uma conta a pagar real move a sugestão para a aba
Atendidas mostrando esse link, que "Descartar" com motivo move para a
aba Descartadas mostrando o motivo, e que uma sugestão nova pode ser
gerada para o mesmo item depois que a anterior foi decidida — da Fase 54,
e a Conciliação Bancária em Lote e Janela Configurável: importando 3
extratos (um com uma transação 5 dias longe de uma baixa já registrada, e
dois com transação débito SEM baixa lançada ainda), confirmando que as 3
ficam pendentes na importação com a tolerância padrão de 3 dias,
aumentando a tolerância para 5 dias pela tela "Configurar Financeiro" e
confirmando que a dica no topo do Financeiro já mostra o novo valor,
lançando as baixas dos dois fornecedores via API (simulando "a baixa
chegou depois"), clicando no botão escopado "Conciliar candidatos únicos
deste extrato" num dos extratos e confirmando que SÓ ele foi reprocessado
(o outro extrato continua pendente), e por fim clicando no botão global
"Conciliar todos os candidatos únicos" na lista de extratos e confirmando
que ele resolve de uma vez tanto a transação da baixa tardia quanto a da
tolerância aumentada, terminando com o botão global desabilitado por não
sobrar mais nenhuma transação pendente no sistema — da Fase 55, e o DRE
com Impostos Detalhados: confirmando que, sem nenhuma alíquota
configurada, a tela do DRE não mostra a tabela de detalhamento por
tributo (pixel-idêntica à de antes desta fase), configurando PIS, COFINS,
ICMS e ISS pela tela "Configurar Financeiro" e confirmando que o total de
"Impostos sobre Vendas" soma as quatro corretamente, que a nova tabela de
detalhamento aparece com exatamente 4 linhas e valores individuais
corretos, que reabrir o formulário mostra os valores já preenchidos, e
que configurar TAMBÉM a alíquota genérica soma junto com as quatro (nunca
substituindo), passando a tabela a mostrar 5 linhas com uma nova linha
"Imposto genérico" — da Fase 56, e o MRP com Lead Time de Compra do
Fornecedor: cadastrando um fornecedor com lead time de 10 dias pela tela,
homologando-o para um insumo em falta, confirmando que o MRP mostra
"nenhuma ordem agendada ainda" em vez de uma data inventada, agendando a
ordem pela tela de detalhe (Agenda do APS) e confirmando que a coluna
"Comprar até" passa a mostrar a data correta (início planejado menos o
lead time), gerando uma sugestão de compra e confirmando que ela mostra a
MESMA data, e por fim reduzindo o lead time do fornecedor e confirmando
que a sugestão JÁ GERADA mantém a data antiga (snapshot) enquanto o
cálculo ao vivo do MRP já reflete o valor novo — da Fase 57) num
navegador de verdade (Chromium, via
Playwright) antes de te entregar — scripts em `tests_e2e/`, se quiser
reexecutar.

### Teste manual via linha de comando (alternativa)
```powershell
curl -X POST http://127.0.0.1:5000/api/v1/auth/login -H "Content-Type: application/json" -d "{\"email\":\"admin@alphafitus.com.br\",\"senha\":\"<a senha que o seed imprimiu>\"}"
# copie o access_token da resposta, depois:
curl http://127.0.0.1:5000/api/v1/auth/me -H "Authorization: Bearer <access_token>"
curl http://127.0.0.1:5000/api/v1/usuarios -H "Authorization: Bearer <access_token>"
curl http://127.0.0.1:5000/api/v1/auditoria -H "Authorization: Bearer <access_token>"
curl -i http://127.0.0.1:5000/api/v1/usuarios   # sem token: deve dar 401
```

## Restaurando um Backup do Sistema (Fase 47 / Fase 67)

Um backup deste tipo é uma cópia do arquivo `.db` inteiro (todos os
módulos) — diferente do Snapshot da Fase 46 (JSON só das tabelas do
Memorial Técnico, restaurado dentro de uma transação seguindo regras de
tudo-ou-nada, seguro de fazer com o sistema no ar), substituir o `.db`
inteiro com o servidor já respondendo requisições arriscaria corromper o
banco. Por isso a restauração NUNCA acontece na hora, mesmo pela tela.

**Caminho recomendado (Fase 67 — pela própria tela):** em **Memorial
Técnico → Administração → Backups do Sistema → Restaurar backup**, envie
o arquivo `.db` (baixado anteriormente, recebido por e-mail ou baixado da
nuvem). O sistema valida o arquivo, guarda uma cópia de segurança do banco
ATUAL automaticamente, e deixa a restauração PENDENTE. A troca de verdade
só acontece na PRÓXIMA VEZ que o Alphafitus OS for iniciado — feche a
janela (ou reinicie o serviço do Windows, se instalado como serviço) e
abra de novo para concluir. Isso continua respeitando a mesma regra de
segurança de sempre (nunca troca o arquivo com o servidor no ar): só que
agora o UPLOAD é feito pela tela, e a troca acontece automaticamente no
próximo início, sem precisar copiar arquivo manualmente por fora do
sistema.

**Caminho manual (alternativa, ex.: sistema não liga de jeito nenhum):**

1. Pare o Alphafitus OS (feche a janela do `iniciar.bat`/do serviço, ou
   pare o serviço do Windows se tiver instalado como serviço).
2. Faça uma cópia de segurança do banco ATUAL antes de sobrescrever nada
   (`backend\data\alphafitus.db`) — para o caso de precisar voltar atrás.
3. Copie o arquivo de backup baixado pela tela para
   `backend\data\alphafitus.db`, substituindo o arquivo atual.
4. Inicie o Alphafitus OS de novo (mesmo comando/atalho de sempre).

Nos dois caminhos, o sistema volta a funcionar exatamente no estado em
que estava no momento em que aquele backup foi gerado — qualquer coisa
cadastrada DEPOIS do backup e ANTES da restauração é perdida (por isso a
cópia de segurança automática/manual: se restaurar o backup errado, dá
para voltar).

**Backup automático agendado (Fase 67):** a mesma tela também deixa
cadastrar quantos horários por dia forem necessários para o backup rodar
sozinho, enviando simultaneamente para nuvem (padrão S3-compatível —
AWS S3, Backblaze B2, Cloudflare R2, Wasabi, MinIO etc.) e/ou e-mail
(reaproveita o SMTP já configurado em Notificações). O histórico de cada
execução (sucesso ou erro, por destino) fica visível na mesma tela.

## Importando um backup do sistema antigo do Memorial Técnico (Replit)

O cliente já usava um sistema separado (Node.js/React/Postgres, hospedado
no Replit) só para o Memorial Técnico ANVISA antes da Fase 24 recriar esse
módulo aqui dentro do Alphafitus OS. Esse sistema antigo consegue exportar
um backup completo em JSON (`Memorial-backup-alphafitus-AAAA-MM-DD_HHhMM.json`)
com empresas, produtos, memoriais (todo o conteúdo técnico), assinaturas,
histórico, anexos (o arquivo em si) e os catálogos de apoio.

`scripts/importar_backup_replit.py` lê esse JSON e importa tudo para dentro
de um banco Alphafitus OS já inicializado (schema + `seed.py` já rodados),
mapeando cada campo do sistema antigo para a coluna/tabela correspondente
aqui — inclusive convertendo os campos que lá eram tabelas dinâmicas
(composição nutricional, composição centesimal, legislação aplicável,
conclusão, metodologias aplicadas, referências bibliográficas, cálculo de
quantidade, advertências/armazenamento/modo de uso do memorial) em texto
formatado e legível, já que aqui esses campos são texto livre. Uso:

```powershell
python scripts/importar_backup_replit.py --backup "Memorial-backup-....json" --db data\alphafitus.db
```

É seguro rodar mais de uma vez contra o mesmo banco — cada entidade é
checada por uma chave natural (CNPJ da empresa, código do memorial, e-mail
do usuário) antes de importar, então não duplica se você rodar de novo.
Os únicos usuários do backup que de fato assinaram algum memorial são
criados como usuários de verdade aqui (perfil "Regulatório"), com senha
temporária e troca obrigatória no primeiro login, para satisfazer a
integridade referencial de `memorial_assinaturas`.

Fora do escopo desta importação (documentado em detalhe no topo do próprio
script): 4 catálogos que o sistema antigo tinha só para uso interno
(componentes de fórmula, tabela nutricional "por alimento", tipos de pote,
opções de cápsula) e que o Alphafitus OS ainda não tem como cadastro
próprio — ficam para uma fase futura, se o cliente pedir.

## Migrando para PostgreSQL

O arquivo `migrations/schema.sql` tem comentários `-- PG:` explicando a
tradução de cada tipo de coluna. Resumo das mudanças ao migrar:
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `id BIGSERIAL PRIMARY KEY` (ou
  `GENERATED ALWAYS AS IDENTITY`).
- Colunas `TEXT` usadas como data/hora ISO → `TIMESTAMPTZ`.
- Colunas `TEXT` usadas para guardar JSON (ex.: `auditoria.valor_anterior`)
  → `JSONB`.
- O trigger de imutabilidade da auditoria precisa ser reescrito na sintaxe
  de trigger do PostgreSQL (`CREATE OR REPLACE FUNCTION` + `CREATE TRIGGER
  ... FOR EACH ROW EXECUTE FUNCTION ...`), mas a regra é a mesma: bloquear
  UPDATE/DELETE.
- No código Python, troque o driver (`sqlite3` → `psycopg`) em `app/db.py`
  — o restante do código (rotas, regras de negócio) não referencia nada
  específico do SQLite e não deveria precisar mudar.

## O que ainda falta (próximas entregas, fora do escopo de Fase 1 a 24)

- (Entregue na Fase 50) Alocação do custo de perda por ETAPA do processo
  — a ordem de produção agora pode ter etapas cadastradas (ex.: Pesagem,
  Granulação, Compressão, Embalagem), cada uma com sua própria perda
  apontada; o Custeio (Fase 13) reparte o MESMO custo total da perda já
  calculado entre as etapas, proporcionalmente à quantidade que cada uma
  apontou. Limitação que fica documentada para uma fase futura, se o
  cliente pedir: dentro de cada etapa o custo ainda vem do rateio
  proporcional de sempre entre os insumos da fórmula — o sistema
  continua sem saber em que etapa cada INSUMO específico entra (a
  composição/BOM não tem esse vínculo), então se a perda de rótulo, por
  exemplo, ocorre só na etapa de embalagem, esta alocação ainda reparte
  o custo de rótulo entre todas as etapas de forma proporcional à
  quantidade perdida, não ao insumo real perdido em cada uma.
- (Entregue na Fase 30) Custo de mão de obra e overhead — os centros de
  trabalho ganharam taxa/hora de mão de obra e overhead, e a conclusão da
  ordem ganhou apontamento opcional de horas; o custeio REAL de uma
  ordem (depois de concluída) agora soma material + mão de obra +
  overhead. Limitação que fica documentada para uma fase futura, se o
  cliente pedir: o custo PROJETADO/padrão de uma fórmula (antes de
  produzir) continua só material — mão de obra/overhead só aparece no
  custo real, depois da ordem concluída, e só se ela tiver sido agendada
  num centro de trabalho (Fase 25) com taxa cadastrada e horas
  apontadas; sem isso o card mostra "indisponível" com o motivo, nunca
  um número inventado.
- (Entregue na Fase 31) Aprovação dupla para o próprio REGISTRO de uma
  baixa — acima de R$1.000,00, registrar um recebimento ou pagamento
  agora também vira uma solicitação pendente até um segundo usuário
  aprovar, espelhando exatamente o que a Fase 22 já fazia para o
  ESTORNO. O sinalizador `exige_dupla_aprovacao=1` (Fase 6) em
  `registrar_baixa_receber`/`registrar_baixa_pagar` agora tem aplicação
  de fato, igual ao dos dois pares de estorno.
- (Entregue na Fase 33) Limite de prazo para estornar uma baixa — hoje
  configurável pela tela (`configuracoes_financeiro.limite_dias_estorno_baixa`,
  0 = sem limite por padrão), contado em dias a partir do lançamento
  original da baixa. Uma variação que ainda ficaria de fora se o cliente
  pedir: limitar por MÊS FISCAL fechado (ex.: "nada lançado em janeiro
  pode ser estornado depois que fevereiro começar"), em vez de uma janela
  fixa de N dias — hoje a régua é sempre "N dias a partir do
  lançamento", não "até o fim do mês/período corrente".
- Assinatura digital do instalador
  (`installer/AlphafitusOS_Servidor_Instalar.exe`) com um certificado de
  assinatura de código, para o Windows SmartScreen parar de alertar sobre
  "editor desconhecido" — isso exige comprar um certificado de uma
  autoridade certificadora, fora do que dá para resolver só com código.
- Empacotar o próprio Python dentro do instalador (hoje ele depende de o
  usuário já ter Python 3.11+ instalado na máquina) — evitaria esse
  pré-requisito, mas exigiria baixar e embutir um Python "embeddable" de
  ~25MB dentro do instalador, algo que não deu para fazer nesta entrega
  por falta de acesso de rede no ambiente onde montei o instalador (ver
  `installer/README.md`).
- (Entregue na Fase 50) Detalhar a perda/refugo **por etapa** do processo
  — a Fase 9 entregou o apontamento de perda de forma agregada, um único
  total por ordem concluída; agora uma ordem pode ter etapas cadastradas
  (Pesagem, Granulação, Compressão, Embalagem etc.), cada uma com sua
  própria perda apontada — quando há etapas, a perda agregada da ordem
  passa a ser somada automaticamente a partir delas (o total manual na
  conclusão é rejeitado, para não haver dois números divergentes para a
  mesma coisa). Continua 100% opcional: uma ordem sem nenhuma etapa
  cadastrada funciona exatamente como antes.
- (Entregue na Fase 70) Nota Fiscal Eletrônica (NF-e) — emissão via
  provedor terceirizado (Focus NFe) a partir de um pedido de venda já
  expedido. Decisão de escopo deliberada: em vez de falar direto com a
  SEFAZ (montar/assinar XML por estado, gerenciar contingência — um
  projeto gigante à parte), o Alphafitus OS integra com a API REST do
  Focus NFe, que já resolve isso; o certificado digital A1/A3 da empresa é
  cadastrado DIRETAMENTE no painel do provedor — o sistema nunca guarda
  nem manipula o arquivo do certificado, só o token de API (mascarado,
  nunca devolvido em texto puro, mesmo padrão de `nuvem_secret_key` da
  Fase 67 e `smtp_senha` da Fase 37). Empresas, clientes e itens ganharam
  campos fiscais novos (regime tributário, Inscrição Estadual, endereço
  estruturado, NCM, CFOP, CST/CSOSN — ver `migrations/schema_fase70.sql`),
  todos OPCIONAIS para o cadastro em si, só exigidos na hora de tentar
  emitir (com uma mensagem específica dizendo exatamente o que falta,
  antes de gastar uma chamada ao provedor). Nova tela "Notas Fiscais" e
  "Configuração NF-e" (Comercial & Vendas no menu), e um cartão novo no
  detalhe do pedido de venda para emitir/consultar/ver o histórico.
  **Aviso importante, repetido na tela de configuração:** os códigos
  fiscais padrão usados quando o cadastro não tem um valor específico
  (CSOSN 102 para Simples Nacional, CST 00 para os demais regimes, PIS/
  COFINS CST 99) são pontos de partida NEUTROS, não uma recomendação
  tributária — a legislação brasileira tem centenas de combinações
  possíveis dependendo do produto/regime/estado; confirme com um contador
  antes de emitir qualquer nota em ambiente de produção (o padrão do
  sistema é sempre "homologação", que não tem valor fiscal — trocar para
  produção é uma escolha explícita na tela de configuração). Limitação
  honesta: a integração com o Focus NFe foi construída a partir do
  contrato publicamente documentado da API deles, mas nunca testada
  ponta-a-ponta contra o serviço real durante o desenvolvimento, porque
  este ambiente de desenvolvimento em nuvem não tem acesso à internet
  externa (mesmo motivo documentado para pywin32 na Fase 68) — teste bem
  em ambiente de homologação antes de confiar em produção. Variações que
  ficam de fora se o cliente pedir: cálculo automático de ICMS-ST,
  suporte a mais de um provedor (hoje só Focus NFe), NF-e de devolução/
  complementar, e recebimento de webhook do provedor em vez de consulta
  manual de status (hoje "Consultar status" é um botão, não automático).
- (Entregue na Fase 78) Notas Fiscais de Entrada — primeira etapa de um
  projeto maior (SPED Fiscal / EFD ICMS/IPI, a escrituração fiscal digital
  mensal exigida de empresas do Lucro Presumido/Real). Antes desta fase,
  uma nota de compra de fornecedor só existia como o campo de texto livre
  `lotes.nota_fiscal` — sem CFOP, CST/CSOSN, chave de acesso ou imposto
  destacado. Agora há um lançamento estruturado (`notas_fiscais_entrada` +
  `notas_fiscais_entrada_itens`, tela "Notas Fiscais de Entrada" no menu
  Comercial & Vendas), com fornecedores ganhando os mesmos campos fiscais
  que empresas/clientes já tinham desde a Fase 70 (Inscrição Estadual,
  endereço estruturado, UF — editáveis pelo botão "Dados fiscais" na tela
  de Fornecedores). **Escopo desta fase, de propósito:** só CAPTURA os
  valores exatamente como aparecem na nota do fornecedor — nenhum imposto é
  calculado, nenhuma alíquota é sugerida. A apuração de ICMS/IPI de verdade
  (débito das saídas × crédito das entradas, por alíquota/UF/CST — o motivo
  do SPED Fiscal existir) é um motor à parte, ainda não construído, que
  depende de parâmetros reais (alíquota interna do estado, substituição
  tributária, DIFAL) confirmados por um contador — nunca inventados no
  código. Lançamento pelo formulário aceita itens num formato de linha só
  (`codigo;quantidade;unidade;valor_unitario;cfop;cst_csosn;valor_icms;
  valor_icms_st;valor_ipi`, os três últimos opcionais), mesmo padrão já
  usado no Pedido de Compra (Fase 58) em vez de uma UI de linhas dinâmicas.
- (Entregue na Fase 71) Emissão de Boleto Bancário via provedor
  terceirizado (Asaas) — a partir de uma conta a receber em aberto,
  gera-se um boleto de verdade (linha digitável, código de barras, link
  do boleto), em vez de apenas registrar manualmente a baixa quando o
  cliente diz que pagou. Decisão de escopo deliberada: em vez de uma
  integração bancária direta (convênio de cobrança por banco, cada um com
  seu próprio layout/CNAB — um projeto grande por si só), o Alphafitus OS
  integra com a API REST do Asaas, um gateway de pagamentos que já cuida
  de registrar o boleto junto ao banco por trás. Diferente da Fase 70
  (NF-e), a conta do provedor de boleto é ÚNICA/global (não por empresa),
  guardada em `configuracoes_boleto` — só o token de API é armazenado,
  sempre mascarado e nunca devolvido em texto puro (`token_configurado`,
  mesmo padrão de `nuvem_secret_key` da Fase 67, `smtp_senha` da Fase 37 e
  do token do Focus NFe na Fase 70). O cliente Asaas correspondente a cada
  cliente do sistema é criado (ou reaproveitado, via
  `clientes.id_externo_asaas`) automaticamente na primeira emissão, sem
  exigir nenhum cadastro fiscal extra além do que já existe (razão
  social/CNPJ). Nova tela "Configuração de Boleto" (Financeiro no menu) e
  uma seção nova "Boleto bancário" dentro do modal "Ver baixas" de cada
  conta a receber, para gerar, consultar status e cancelar um boleto
  pendente. **Comportamento deliberado:** quando a consulta de status
  mostra que o provedor CONFIRMOU o pagamento (`RECEIVED`/`CONFIRMED`), o
  sistema registra a baixa automaticamente — pulando a fila de dupla
  aprovação por alçada da Fase 31, porque essa fila existe para não
  confiar cegamente na palavra de um humano dizendo "eu paguei", e a
  confirmação de um gateway de pagamento externo já é um sinal mais forte
  que isso. Limitação honesta, igual à da Fase 70: a integração com o
  Asaas foi construída a partir do contrato publicamente documentado da
  API deles, mas nunca testada ponta-a-ponta contra o serviço real
  durante o desenvolvimento, porque este ambiente de desenvolvimento em
  nuvem não tem acesso à internet externa — teste bem em ambiente sandbox
  do Asaas antes de confiar em produção (o padrão do sistema é sempre
  "sandbox"; trocar para produção é uma escolha explícita na tela de
  configuração). Variações que ficam de fora se o cliente pedir: outros
  meios de cobrança do Asaas (PIX, cartão), outros provedores além do
  Asaas, e recebimento de webhook do provedor em vez de consulta manual
  de status (hoje "Consultar status" é um botão, não automático — mesma
  limitação documentada para NF-e na Fase 70).
- (Entregue na Fase 72) Revisão geral de segurança e qualidade — auditoria
  em 5 frentes (segurança, integridade de dados/regras de negócio,
  consistência arquitetural, cobertura de testes, frontend), com correção
  das falhas confirmadas mais graves: (1) uma injeção de SQL no restaurador
  de snapshot do Memorial Técnico ANVISA (Fase 46) — os nomes de coluna de
  cada registro enviado eram usados diretamente para montar o `INSERT`, sem
  checar contra o schema real; agora todo nome de coluna é validado contra
  `PRAGMA table_info` antes de qualquer restauração, rejeitando com erro
  claro qualquer campo desconhecido; (2) uma escalação de privilégio na
  tela de Perfis de Acesso — um usuário com a permissão `perfis.editar`
  conseguia alterar as permissões de um perfil ao qual ele mesmo pertence
  (dando a si mesmo qualquer permissão exceto virar Administrador, que já
  era bloqueado desde a Fase 1), quebrando a regra de segregação de função
  que já existe para outras aprovações no sistema; agora essa mesma regra
  se aplica aqui — é sempre necessário outro usuário para alterar as
  permissões do próprio perfil; (3) duas condições de corrida (dois
  cliques/duas abas gerando dois registros ao mesmo tempo, antes de o
  primeiro salvar) na emissão de NF-e (Fase 70) e na geração de Boleto
  (Fase 71) — a checagem "já existe?" era feita em Python antes do
  `INSERT`, o que não impede duas requisições simultâneas de passarem pela
  checagem ao mesmo tempo; agora o próprio banco de dados garante isso via
  índices únicos (inclusive parciais, só sobre os registros ainda
  pendentes/ativos), como uma segunda camada de proteção por trás da
  checagem em Python — se a corrida acontecer, a segunda tentativa recebe
  um erro amigável em vez de criar um registro duplicado; e (4) um duplo-
  clique no frontend que permitia disparar duas emissões de NF-e ou duas
  gerações de Boleto antes da primeira resposta do servidor voltar — os
  botões agora desabilitam no clique e voltam a habilitar sozinhos quando a
  tela é atualizada. Todas as quatro correções têm teste de regressão
  dedicado provando o cenário exato do problema (incluindo, para as
  condições de corrida, um teste que simula a checagem em Python "perdendo
  a corrida" e confirma que é o índice único do banco que impede o segundo
  registro). A auditoria também documentou, sem corrigir por não terem sido
  pedidas, algumas oportunidades de menor severidade: uma possível corrida
  na reserva de estoque por FEFO entre confirmações de pedido simultâneas,
  uma etiqueta de permissão da consulta de status de boleto que hoje também
  permite dar baixa financeira, e duas tabelas de configuração que ainda
  usam `UPDATE` simples em vez do padrão de upsert usado nas demais.
- (Entregue na Fase 73) Continuação da auditoria de segurança e qualidade
  da Fase 72 — resolve as quatro pendências de menor severidade que
  tinham ficado só documentadas: (1) a corrida na reserva de estoque por
  FEFO entre confirmações de pedido/liberações de ordem simultâneas —
  diferente das corridas da Fase 72 (que eram sobre "existe no máximo um
  registro", resolvidas com índice único), esta é sobre "a SOMA das
  reservas não pode passar do saldo físico", então a correção é um
  TRIGGER `BEFORE INSERT` (com `RAISE(ABORT, ...)`) em
  `pedido_venda_reservas` e `ordem_producao_reservas` que recalcula o
  saldo disponível no momento exato da escrita — uma segunda camada atrás
  da checagem em Python (`_alocar_fefo`/`_alocar_fefo_producao`), no
  mesmo espírito de defesa em profundidade da Fase 72. Como confirmar/
  liberar grava VÁRIAS reservas em sequência (uma por lote alocado) e um
  erro no meio do caminho não desfaz sozinho o que já foi gravado nesta
  mesma requisição (`close_db` sempre comita, mesmo em erro — ver a nota
  em `app/context.py`), as duas rotas agora usam um `SAVEPOINT` explícito
  ao redor do laço de inserção: se o trigger abortar a N-ésima reserva, um
  `ROLLBACK TO SAVEPOINT` desfaz as reservas já gravadas nesta tentativa
  antes de devolver 409, para nunca deixar reserva "órfã" pendurada num
  pedido/ordem que continua em rascunho/planejada; (2) a rota "Consultar
  status" de um boleto (Financeiro) exigia só `financeiro.visualizar`,
  mas registra uma baixa financeira de verdade quando o provedor confirma
  pagamento — passou a exigir `financeiro.registrar_baixa_receber` (a
  mesma permissão de escrita da baixa manual), fechando a brecha de um
  perfil só-leitura (ex.: Comercial, que tem `financeiro.visualizar` para
  ver contas do próprio cliente) conseguir, na prática, dar baixa numa
  conta clicando em "Consultar status"; (3) as duas tabelas de
  configuração singleton que ainda faziam `UPDATE` simples
  (`configuracoes_comercial` em `vendas_app.py`, `configuracoes_compras`
  em `compras.py`) passaram a usar `INSERT ... ON CONFLICT DO UPDATE`,
  igual às outras 7 — um `UPDATE` simples falha silenciosamente (0 linhas
  afetadas, sem erro) se a linha única algum dia não existir; a função de
  leitura de cada uma também ganhou o mesmo tratamento defensivo
  (`if row else PADRÃO`) já usado em `estoque.py`/`financeiro.py`, em vez
  de deixar um `TypeError` virar 500; e (4) 16 lacunas de cobertura de
  teste identificadas pela auditoria — os quatro ramos de erro do
  provedor (5xx, 401/403, 400 genérico, corpo não-JSON) tanto de
  `boleto_service._tratar_resposta` quanto de
  `nfe_service._interpretar_resposta_provedor` nunca eram exercitados
  porque todo teste anterior mockava um nível acima; o teto de `min()` da
  baixa automática de boleto (`app/routes/boletos.py`) nunca era testado
  no caso em que o valor do boleto passa a exceder o saldo em aberto
  (porque uma baixa manual parcial entrou no meio do caminho); faltava um
  teste de "aprovar o mesmo lote de qualidade duas vezes" e de "aprovar a
  mesma solicitação pendente de baixa financeira duas vezes"; e faltava
  teste de 403 no PUT (não só no GET) da configuração de boleto e da
  configuração fiscal. Nenhuma mudança de comportamento visível para quem
  já usa o sistema corretamente — só bloqueia cenários que já deveriam
  estar bloqueados.
- (Entregue na Fase 74) Correção crítica do instalador do Windows — desde
  algum reempacotamento anterior deste mesmo projeto, os arquivos de
  arranque do instalador (`iniciar.bat`, `desinstalar.bat`, os `.vbs` de
  criação/remoção de atalho, e os `.bat` de instalar/iniciar/parar/status/
  remover o Serviço do Windows) tinham ficado de fora do pacote — eles
  nunca tiveram uma cópia de origem dentro de `backend/` (são artefatos só
  do instalador), então cada vez que o `payload/` do instalador era
  reconstruído copiando de `backend/` do zero, esses arquivos somem sem
  aviso. O sintoma: `__main__.py` (o bootstrap que roda dentro do .exe)
  sempre tenta abrir `iniciar.bat` ao final da instalação
  (`cmd.exe /k iniciar.bat`) para dar continuidade ao setup numa janela
  separada — com o arquivo ausente, o Windows respondia
  `'C:\Program' não é reconhecido como um comando interno ou externo...`
  (interpretando o caminho com espaço como um comando), deixando
  literalmente qualquer instalação nova travada num terminal sem servidor
  nenhum no ar. Reconstruídos todos os nove arquivos que faltavam, mais um
  décimo novo (`_ambiente.bat`, script interno compartilhado que cria/
  ativa o `venv`, instala as dependências só na primeira vez e gera a
  chave `ALPHAFITUS_JWT_SECRET` — usado tanto por `iniciar.bat` quanto
  pelos atalhos de Serviço, para as duas cópias dessa lógica nunca saírem
  dessincronizadas): `iniciar.bat` agora prepara o ambiente, roda
  `seed.py` (idempotente — seguro rodar toda vez), detecta o endereço IPv4
  desta máquina na rede local (para os outros terminais acessarem) e sobe
  o servidor de produção de verdade (`waitress-serve`, não o `run.py` de
  desenvolvimento, que só escuta em `127.0.0.1`); `desinstalar.bat` para/
  remove o Serviço do Windows se existir, remove os atalhos e a entrada em
  "Aplicativos e Recursos", e apaga a pasta de instalação (o próprio
  arquivo se autoapaga através de um processo desacoplado, já que uma
  pasta não pode se apagar enquanto um `.bat` de dentro dela ainda está
  rodando); os cinco `.bat` de gerenciar o Serviço do Windows
  (`instalar_servico.bat`/`iniciar_servico.bat`/`parar_servico.bat`/
  `status_servico.bat`/`remover_servico.bat`) chamam
  `service_windows.py` (Fase 68) com os verbos que o `pywin32` já suporta
  nativamente, e `status_servico.bat` usa `sc query` diretamente (o
  `pywin32` não tem um verbo "status" pronto); os dois `.vbs` de atalho
  (instalação simples vs. instalação completa como Administrador) e o de
  remoção foram reconstruídos seguindo a mesma estrutura de grupo de
  atalhos documentada desde a Fase 68. Para evitar que isso se repita, os
  dez arquivos agora vivem só em `installer/payload/` (nunca em
  `backend/`, que é só o código do sistema em si, multiplataforma) — uma
  futura reconstrução do `payload/` a partir de `backend/` precisa
  mesclar por cima dessa pasta, nunca apagá-la primeiro e copiar do zero,
  ou esses dez arquivos voltam a ser perdidos silenciosamente. Ajuste
  feito ainda dentro da Fase 74, a partir do primeiro teste real de um
  usuário: `_ambiente.bat` escolhia o Python com `py -3`, que o launcher
  do Windows sempre resolve para a MAIOR versão instalada — inclusive
  uma versão de pré-lançamento/beta, se essa for a única (ou a mais
  nova) no computador. Uma versão assim costuma não ter ainda pacote
  `.whl` pronto de bibliotecas com código C (ex.: `lxml`, puxado
  indiretamente por uma das dependências do `requirements.txt`), e o
  Windows tenta compilar na hora, falhando com "Microsoft Visual C++
  14.0 or greater is required" quando a máquina não tem esse compilador
  instalado (o que é o normal — a maioria dos computadores não tem).
  `_ambiente.bat` agora testa explicitamente por versões estáveis
  conhecidas (3.13, 3.12, 3.11, 3.10, nessa ordem) antes de cair para o
  `py -3` genérico, então uma instalação estável coexistindo com uma
  beta passa a ser preferida automaticamente; e a mensagem de erro,
  quando a instalação de dependências falha mesmo assim, agora explica
  as duas causas mais comuns (sem internet, ou Python novo demais sem
  wheel pronto) e como resolver cada uma. Correção rápida seguinte,
  ainda no mesmo teste real: a primeira versão desse ajuste ainda tinha
  o `py -3` genérico do launcher do Windows como alternativa antes do
  `python` simples do PATH — só que é justamente o `py -3` que sempre
  escolhe a versão mais nova instalada (a beta, se for o caso), enquanto
  o comando `python` batia com a mesma versão estável que a pessoa já
  tinha usado manualmente com sucesso um passo antes. A ordem de
  preferência foi invertida: agora `_ambiente.bat` tenta primeiro o
  `python` simples do PATH (o mesmo que responde quando alguém digita
  `python` no terminal), e só recorre ao launcher `py` — sempre com uma
  versão específica e conhecida (3.13/3.12/3.11/3.10), nunca o `-3`
  genérico sozinho — se `python` não existir no PATH. Correção final,
  depois de identificar a causa raiz de verdade do erro do Visual C++:
  não é o `lxml` em si que o sistema usa, e sim uma dependência
  transitiva — `img2pdf` (usado para incorporar anexos de imagem no
  "PDF Completo" da Fase 43) depende do `pikepdf`, que por sua vez
  depende do `lxml` — nenhum dos dois tem, ainda, pacote pronto (`.whl`)
  publicado para uma versão de Python tão nova quanto a 3.15 (beta em
  2026, lançamento final só previsto para outubro), então o Windows
  tenta compilar os dois na hora e falha sem o Visual C++ Build Tools.
  Em vez de continuar pedindo para a pessoa instalar manualmente outra
  versão do Python, `_ambiente.bat` agora só aceita uma versão já
  testada (3.9 a 3.13); se não achar nenhuma no PATH nem no launcher
  `py`, baixa e instala sozinho, silenciosamente, uma cópia PRIVADA do
  Python 3.12 (`InstallAllUsers=0`, sem mexer no PATH do sistema, isolada
  dentro da própria pasta de instalação) — o instalador deixa de
  depender de a pessoa já ter (ou saber instalar) uma versão compatível
  do Python na máquina. Último ajuste, já com o Python resolvido e as
  dependências instaladas com sucesso num teste real: `seed.py` falhava
  com `sqlite3.OperationalError: no such table: permissoes`, porque o
  próprio `config_ambiente.bat` gerado por `_ambiente.bat` sempre define
  `ALPHAFITUS_DB_PATH` (necessário para o Serviço do Windows — ver
  `service_windows.py`), e é justamente essa variável estar definida
  que faz o `if __name__ == "__main__"` de `seed.py` decidir NÃO criar o
  schema sozinho (a suposição ali é: se alguém apontou manualmente o
  caminho do banco, presume-se que essa pessoa já cuidou de criá-lo por
  conta própria). `iniciar.bat` e `instalar_servico.bat` agora chamam
  `db_module.init_db()` explicitamente antes do `seed.py`, do mesmo
  jeito que `run.py` e `service_windows.py` já fazem, em vez de confiar
  no comportamento "cria sozinho se não existir" do `seed.py`, que só
  vale quando ninguém definiu esse caminho na mão.
- (Entregue na Fase 74) Identidade visual da empresa — logo real e cores
  da marca na tela de login, com um toque 3D, e a logo nos documentos
  PDF gerados pelo sistema, a pedido explícito do cliente ("essa sao as
  cores e a logo da nossa empresa incrementar algo 3D ao logar. e os
  documentos devem ter a logo"). Na tela de login (`renderLogin` e
  `renderLogin2fa`, em `app.js`), o quadrado genérico que ficava acima do
  título deu lugar à logo de verdade (`logo_alphafitus.png`), e o
  título "Alphafitus OS" passou a usar um gradiente nas cores extraídas
  da própria logo (`--marca-teal`/`--marca-verde`, em `tema-3d.css`) no
  lugar do azul genérico usado até aqui. O efeito 3D não criou nenhuma
  mecânica nova: a Fase já tinha `tema-3d.css`/`tema-3d.js` (o tilt de
  mouse que já inclina `.cartao-login` alguns graus, via `--rx`/`--ry`),
  então a logo só ganhou `translateZ()` num eixo próprio dentro desse
  mesmo cartão — ela "flutua" acima do resto do card e se move junto no
  tilt, com uma animação de flutuação sutil em repouso
  (`@keyframes af3d-logo-flutuar`, respeitando
  `prefers-reduced-motion`). Aproveitando essa mesma mexida na tela de
  login e um relato do cliente de erro ao digitar a senha, o campo de
  senha ganhou um ícone de olho para alternar entre texto oculto/visível
  antes de enviar o formulário (`data-acao="alternar-visibilidade-senha"`
  no switch já existente de `tratarAcao`, sem mecanismo novo de eventos).
  Nos documentos: um módulo novo e único,
  `app/pdf_marca.py::desenhar_cabecalho_logo`, plugado via
  `onFirstPage`/`onLaterPages` do `SimpleDocTemplate.build()` do
  reportlab nos quatro PDFs do sistema — Certificado de Análise
  (`lotes.py`), Relatório de Simulação de Recall (`rastreabilidade.py`),
  Painel Gerencial (`relatorios.py`) e Memorial Técnico/"PDF Completo"
  (`memorial_anexos.py`, nas suas duas rotinas de geração) — desenhando a
  logo no canto superior esquerdo de TODA página, dentro da margem
  superior já reservada por cada documento, sem empurrar ou sobrepor o
  conteúdo normal (testado visualmente e via suíte de testes). Módulo
  central de propósito: se a logo mudar de arquivo ou posição um dia, só
  esse arquivo precisa mudar, em vez de replicar a lógica de desenho nas
  quatro rotas; e se o arquivo da logo não existir por algum motivo, o
  desenho é pulado silenciosamente — nunca quebra a emissão do PDF em si,
  que é o que realmente importa para quem pediu o documento. Combinação
  já pedida pelo cliente e ainda fora do escopo desta entrega, para
  quando vier o próximo pedido explícito: mudanças adicionais de
  identidade visual além da tela de login e dos PDFs ("faremos mais
  mudanças", nas palavras do próprio cliente).
- (Entregue na Fase 74) Oferecer salvar o login/senha no navegador — a
  tela de login é uma SPA: o `fetch` para `/auth/login` não é uma
  submissão de formulário de verdade, e o `<form>` é substituído pelo
  dashboard (`navegarPara`) logo após o sucesso, então o navegador não
  tinha como detectar sozinho "esse login deu certo, ofereça salvar a
  senha" — daí o pedido explícito do cliente por essa opção. Duas partes:
  (1) os campos de email/senha do formulário de login ganharam
  `autocomplete="username"`/`autocomplete="current-password"` (antes não
  tinham nenhum), o que já ajuda o preenchimento automático de uma senha
  salva anteriormente; e (2) depois de um login bem-sucedido — inclusive
  quando passa por 2FA, guardando email/senha só em memória
  (`credenciaisPendentes2fa`, nunca enviado a lugar nenhum além do já
  existente `/auth/login`/`/auth/2fa/verificar`, apagado assim que o
  login termina) — o front chama explicitamente a Credential Management
  API do navegador (`navigator.credentials.store(new PasswordCredential(...))`),
  que é o mecanismo padrão para uma SPA pedir o popup nativo "Salvar
  senha?" do Chrome/Edge. Só existe nesses dois navegadores (Firefox e
  Safari não implementam `store()`); por isso a chamada é protegida por
  `typeof PasswordCredential === "undefined"` e por um `try/catch` que
  nunca deixa uma falha aqui (navegador sem suporte, HTTP sem ser
  localhost, etc.) atrapalhar o login em si — salvar a senha é sempre uma
  conveniência a mais, nunca um requisito para conseguir entrar no
  sistema. Verificado com um teste automatizado de navegador de ponta a
  ponta (Playwright) interceptando a chamada real à Credential Management
  API para confirmar que o email e a senha corretos chegam nela.
- (Entregue na Fase 74) Login falhando com "Email ou senha inválidos"
  mesmo copiando a senha certinho do console — relatado por um cliente
  que, mesmo copiando/colando a senha inicial exibida pelo `seed.py`
  (visualmente idêntica, inclusive conferida com o ícone de olho da
  Fase 74), continuava recebendo o erro. Causa raiz: `POST /auth/login`
  usava a senha enviada no corpo da requisição sem nenhum tratamento —
  um "selecionar linha" ou triple-click no console do Windows (o jeito
  mais natural de copiar aquela senha) facilmente inclui um espaço ou
  quebra de linha invisível antes/depois do texto visível, e uma senha
  colada com esse espaço a mais não bate byte-a-byte com o hash salvo,
  mesmo sendo "a mesma senha" aos olhos de quem está tentando entrar —
  e visualmente indistinguível num campo de senha, mesmo com o texto
  visível. `email` já passava por `.strip()` desde sempre; `senha` agora
  também passa (só nas pontas — nunca no meio do valor, então não reduz
  a entropia de nenhuma senha de verdade), tanto em `/auth/login` quanto
  em `senha_atual` de `/auth/trocar-senha` (o próximo passo depois do
  primeiro login, já que `seed.py` sempre marca a senha inicial como
  `senha_deve_trocar`). Reproduzido e confirmado via `test_client`: uma
  senha com espaço à esquerda e quebra de linha à direita, que antes
  falhava com 401, agora autentica normalmente.
- (Entregue na Fase 74) Senha inicial do administrador mais fácil de
  digitar/conferir — a pedido de um cliente enfrentando dificuldade
  repetida para logar com a senha aleatória de 20 caracteres gerada por
  `seed.py`. O alfabeto de `_gerar_senha_forte` excluía só os símbolos
  mais óbvios de se confundir, mas ainda incluía letras/dígitos
  visualmente ambíguos numa fonte de console (`0`/`O`, `1`/`l`/`I`) e um
  conjunto grande de símbolos (`!@#$%^&*()-_=`, 13 opções). Reduzido para
  um alfabeto sem esses caracteres ambíguos e com só 5 símbolos bem
  distintos entre si (`@#$-_`), e o tamanho caiu de 20 para 16 caracteres
  — ainda assim, ~2^96 combinações possíveis, muito acima do necessário
  para uma senha de uso único que o próprio sistema já força a trocar no
  primeiro login (`senha_deve_trocar=1`). Verificado programaticamente
  que toda senha gerada continua satisfazendo a política de senha em
  vigor (`security.validar_politica_senha`) e nunca contém nenhum dos
  caracteres excluídos.
- (Entregue na Fase 74) Causa raiz de verdade do login que "não fazia
  nada" — o mesmo cliente relatou, depois das correções acima, que às
  vezes o login com a senha CERTA simplesmente voltava para a tela vazia,
  sem nenhuma mensagem de erro, como se nada tivesse acontecido.
  Reproduzido com um teste automatizado de navegador (Playwright)
  submetendo uma senha errada logo na primeira carga da página: era uma
  condição de corrida em `chamarApi`, não um problema de senha. Todo 401
  (não só o de sessão expirada) fazia `chamarApi` chamar
  `navegarPara("#/login")` — e, bem na primeira carga da página, ANTES de
  qualquer navegação anterior ter definido `location.hash`, isso definia
  `location.hash = "#/login"` pela primeira vez, o que dispara um evento
  `hashchange` ASSÍNCRONO do navegador. Enquanto isso, o formulário de
  login já tinha seu próprio tratamento de erro correndo em paralelo
  (`definirFlash("erro", ...)` seguido de `montarRota()`, que é o que de
  fato mostra a mensagem "Email ou senha inválidos" na tela) — e
  o `hashchange` disparado por `navegarPara` podia terminar de processar
  DEPOIS desse tratamento, re-renderizando a tela de login do zero sem a
  mensagem (que só existe em `state.flash`, e a re-renderização não sabia
  dela), apagando o aviso e deixando a pessoa sem nenhuma pista do que
  aconteceu — mesmo com a senha exata, correta, sendo rejeitada por outro
  motivo qualquer (ou nem sendo rejeitada, só demonstrando o bug com uma
  senha errada de propósito no teste). Corrigido restringindo esse
  "limpar sessão e voltar pro login" a chamadas AUTENTICADAS de verdade
  (`!semAuth`) — um 401 em `/auth/login` ou `/auth/2fa/verificar` (ambas
  chamadas `semAuth`, já que são o próprio ato de logar) significa
  "credencial errada", nunca "sessão expirou", então nunca precisou
  disparar essa navegação para começo de conversa. Verificado com dois
  testes de navegador de ponta a ponta: um confirmando que a mensagem de
  erro aparece corretamente numa carga de página nova (o cenário que
  antes falhava) e outro confirmando que o login com a senha certa
  continua levando ao painel normalmente.
- (Entregue na Fase 74) Causa raiz de verdade do erro "ALPHAFITUS_JWT_SECRET
  não configurado" (tela preta do console travando o login com "Erro interno
  do servidor") — mesmo depois de apagar e gerar de novo o
  `config_ambiente.bat`, o mesmo cliente voltou a ver o mesmo erro. A chave
  secreta usada para assinar os tokens de login (JWT) sempre dependeu de uma
  corrente de scripts `.bat` (`_ambiente.bat` gera a chave → grava em
  `config_ambiente.bat` via `set` → `iniciar.bat` chama esse arquivo antes de
  subir o servidor) — funciona na maioria das vezes, mas é frágil: qualquer
  coisa que rompa essa corrente antes do processo Python realmente nascer
  (rodar o sistema a partir de uma cópia extraída manualmente em outra
  pasta, por exemplo — o que se descobriu ser exatamente o caso desse
  cliente) deixa a variável de ambiente vazia quando o Python vai ler, e o
  sistema recusava iniciar o login por completo. Corrigido na raiz: o
  processo Python agora não depende mais só da variável de ambiente — se ela
  não estiver definida, ele mesmo gera uma chave própria (aleatória, única
  por instalação) e a guarda em `data/.jwt_secret`, na mesma pasta do banco
  de dados (logo, preservada nos mesmos backups/cópias que o banco). Nas
  próximas vezes que o servidor iniciar, ele relê essa mesma chave do
  arquivo em vez de gerar outra — os logins continuam válidos normalmente
  entre reinícios do sistema. `ALPHAFITUS_JWT_SECRET`, quando definida
  corretamente, continua tendo prioridade (é o que o modo de Serviço do
  Windows usa). Verificado de ponta a ponta com a variável de ambiente
  propositalmente vazia: `POST /auth/login` respondendo 200 com tokens
  válidos, a mesma chave persistida sendo reaproveitada num processo novo
  simulando um reinício do servidor, e um token emitido antes desse
  "reinício" continuando aceito por uma rota protegida depois dele — e a
  suíte completa de testes automatizados (1017 testes) seguiu passando sem
  nenhuma quebra.
- (Entregue na Fase 74) "Lembrar meu email" na tela de login — a pedido de
  um cliente, para não precisar redigitar o email todo dia, só a senha
  (que o navegador já pode salvar sozinho, ver o item de "salvar login e
  senha" acima). Uma caixinha nova "Lembrar meu email" abaixo dos campos:
  quando marcada, o email (nunca a senha) fica guardado no navegador
  (`localStorage`) e a tela de login já vem com ele pré-preenchido da
  próxima vez, com o foco indo direto para o campo de senha; quando
  desmarcada, o email guardado é apagado e a tela volta a abrir em branco
  com foco no campo de email, como sempre foi. Verificado com quatro
  cenários de navegador de ponta a ponta: primeira visita sem nada
  lembrado, login com a caixinha marcada, nova visita confirmando o email
  pré-preenchido e a caixinha já marcada, e login desmarcando a caixinha
  confirmando que o email lembrado é esquecido corretamente.
- (Entregue na Fase 75) Etapas de Processo Configuráveis (Pesagem, Tempo
  de Mistura) + Painel de Chão de Fábrica em Tempo Real — a pedido de um
  cliente pensando já numa "empresa 4.0": até aqui, uma etapa dentro de
  uma Ordem de Produção (Fase 50) era só um nome livre digitado na hora,
  sem catálogo reaproveitável, sem hora de início e sem nenhum valor
  numérico próprio (ex.: quanto pesou de verdade na Pesagem). Duas
  mudanças, as duas 100% compatíveis com o que já existia (nenhuma etapa
  antiga precisa de nada novo para continuar funcionando exatamente como
  antes): primeiro, um catálogo novo e reaproveitável de tipos de etapa
  (`tipos_etapa_producao` — Pesagem, Mistura, Granulação, Compressão,
  Encapsulamento, Envase, Rotulagem, Embalagem, já cadastrados por padrão
  na própria migration, e livremente editável/expansível pela tela nova
  "Tipos de Etapa"), cada um com uma `unidade de valor` opcional (ex.:
  "kg" para Pesagem) que dá contexto ao campo novo `valor_registrado` de
  cada etapa; segundo, um botão "Iniciar" novo ao lado do "Concluir" que
  já existia, que grava `iniciado_em`/`iniciado_por` — a partir daí o
  "tempo de mistura" pedido pelo cliente passa a ser calculável
  (concluído menos iniciado, sempre dois timestamps, nunca uma duração
  guardada à parte que poderia dessincronizar). Uma decisão técnica
  deliberada, pela mesma limitação do SQLite já documentada desde a Fase
  61 (não dá para alterar um CHECK existente sem recriar a tabela
  inteira): o estado "em andamento" de uma etapa NÃO é um valor novo no
  CHECK de `status` (que continua só 'pendente'/'concluida' como sempre)
  — é DERIVADO na hora, tanto no backend quanto no frontend, a partir de
  `iniciado_em` estar preenchido enquanto `status` ainda é 'pendente'.
  Pensando no "cada setor terá um tablet" pedido pelo cliente, os botões
  "Iniciar"/"Concluir" ganharam uma classe CSS própria (`.botao-tablet`)
  com alvo de toque maior, e passaram a aparecer em DOIS lugares: dentro
  da Ordem de Produção (como sempre) e — novidade desta fase — direto no
  Painel de Chão de Fábrica em Tempo Real (`#/painel-tempo-real`, tela
  nova, sem exigir abrir a ordem inteira). Esse painel atende o terceiro
  pedido do cliente ("preciso de um dashboard em tempo real de tudo que é
  feito, e que cada setor possa ver só o que é do seu setor, incluindo
  pedidos"): em vez de criar um cadastro novo de "Setor" (opção
  descartada explicitamente pelo cliente), o painel reaproveita os PERFIS
  DE ACESSO que já existem desde a Fase 1 — cada seção da resposta
  (Produção, Pedidos de Venda, Pedidos de Compra) só aparece se o usuário
  logado tiver a permissão operacional daquele módulo
  (`producao.visualizar`/`comercial.visualizar`/`compras.visualizar`),
  exatamente a mesma permissão que já controla se ele vê a tela normal
  daquele módulo — um usuário do perfil "Produção" (chão de fábrica) só
  vê a seção de Produção; um perfil com mais permissões vê mais seções.
  Atualiza sozinho por polling a cada 8 segundos (este stack não tem
  websocket) e para automaticamente ao sair da tela, mesmo padrão já
  usado pela sincronização do App de Vendas desde a Fase 51. Permissão
  nova e sozinha nesta fase: `producao.configurar_etapas` (cadastrar/
  editar os TIPOS de etapa — decisão de configuração do processo, dada
  por padrão só ao perfil "PCP"), separada de `producao.apontar` (a ação
  do dia a dia de iniciar/concluir uma etapa CONCRETA, que não muda).
  Verificado de ponta a ponta com testes automatizados (catálogo,
  permissões, iniciar/concluir com valor_registrado, filtragem por seção
  do painel) e com um fluxo real via navegador (Playwright): cadastrar
  etapa pelo catálogo, iniciar, concluir com valor registrado na tela da
  ordem, e concluir uma segunda etapa direto pelo Painel Tempo Real, sem
  nenhum erro de console.
- (Entregue na Fase 76) Painel Executivo — visão "Power BI" da empresa,
  em tempo real: primeira etapa de um pedido maior do cliente (dividido
  em 3 fases — esta é a Fase A: o painel visual + o caminho completo da
  OP + o desempenho comercial; a Fase B, sincronização em tempo real do
  App de Vendas, e a Fase C, geolocalização do vendedor, ficam para as
  próximas fases). Uma tela nova (`#/painel-executivo`), com um visual
  propositalmente diferente do resto do sistema — tema escuro fixo,
  cartões com indicador colorido, gráfico de linha e barras — pensada
  para ficar num telão ou tablet de parede, no mesmo espírito das
  referências visuais que o cliente enviou. Mostra, por seção (reaproveita
  as MESMAS permissões operacionais da Fase 75, sem cadastro novo de
  "setor"): na seção Comercial, os indicadores Total Vendido, Total
  Faturado, Pedidos Novos, Notas Emitidas e Cobertura de Clientes; o total
  vendido mês a mês no ano selecionado; o funil de pedidos AGORA (novo →
  sendo produzido → em finalização → aguardando faturamento → faturado,
  classificado cruzando `pedidos_venda` com a Ordem de Produção que
  reservou o lote vendido e com a Nota Fiscal emitida — não é um campo
  novo, é 100% derivado na hora); o desempenho de cada vendedor no
  período; o faturamento por região (as 27 UFs agrupadas nas 5 regiões do
  Brasil) comparado com o MESMO período do ano anterior, com seta de
  tendência subindo/caindo; e a lista de clientes ativos que não tiveram
  nenhum pedido no período selecionado. Na seção Produção, quantas ordens
  estão em cada status agora, e a lista das ordens liberadas/em produção
  — cada uma com um link para a novidade central desta fase: a **linha do
  tempo completa da Ordem de Produção**, juntando em uma única tela
  eventos de três módulos que não têm nenhuma tabela em comum entre si
  (Produção, Qualidade/Análises e Fiscal/NF-e) — emissão, separação de
  matéria-prima (aproximada pelo primeiro apontamento de consumo de
  material da ordem), liberação da OP, cada etapa configurável da Fase 75
  com início/fim, as análises de laboratório do lote produzido, a
  conclusão da OP e, quando já existe, a nota fiscal autorizada do pedido
  que vendeu aquele lote (rastreada subindo de lote → reserva → pedido →
  nota fiscal, o mesmo caminho de rastreabilidade já usado pela simulação
  de recall desde a Fase 8) — com o tempo gasto entre cada evento
  calculado automaticamente. Duas aproximações ficam documentadas no
  código pelo mesmo motivo já registrado em outras fases (não existe uma
  coluna própria de data para esses dois eventos): "separação de
  matéria-prima" usa o instante do primeiro consumo apontado, e "liberado
  faturamento" usa `atualizado_em` da nota fiscal autorizada. Nenhuma
  migração de banco foi necessária nesta fase — a região é derivada em
  código a partir do UF que a Fase 70 já tinha adicionado ao cadastro de
  clientes, e todo o resto é lido, na hora, das tabelas que várias fases
  anteriores já mantêm. Verificado com 13 testes automatizados novos
  (KPIs, ranking de vendedores, região com tendência, funil de pedidos,
  clientes sem atendimento, linha do tempo da OP em ordem cronológica com
  as durações certas) e visualmente via Playwright, sem nenhum erro de
  console, inclusive checando que o painel filtra corretamente por seção
  para um usuário só com permissão de Produção.
- Evolução do Painel Gerencial (Fase 7 entregou a base — números atuais,
  agregados, em tempo real; Fase 15 entregou o fluxo de caixa projetado
  por faixa de vencimento; Fase 18 entregou a exportação em PDF; Fase 19
  entregou a exportação em CSV; Fase 20/41 entregaram o DRE, hoje vivendo
  em `custeio.py` e não no próprio Painel Gerencial; Fase 42 entregou o
  filtro por PERÍODO e a Fase 52 o filtro por EMPRESA; Fase 69 entregou a
  série histórica/tendência, ver bullet próprio abaixo): o export em
  `.xlsx` de verdade, que também estava listado aqui, foi entregue na
  Fase 45, e o filtro por empresa, que também estava listado aqui, foi
  entregue na Fase 52 (ver bullets próprios abaixo).
- (Entregue na Fase 69) Painel Gerencial — Série Histórica/Tendência: até
  aqui, o painel só mostrava a "foto" de agora — mesmo com o filtro de
  período da Fase 42, que olha o que ACONTECEU numa janela, não como os
  números foram MUDANDO ao longo do tempo. A Fase 69 adiciona a primeira
  tabela do Painel Gerencial que GUARDA um valor histórico em vez de
  recalculá-lo (`painel_snapshots` — ver a nota de escopo completa em
  `migrations/schema_fase69.sql`), com uma decisão de captura deliberada:
  em vez de um agendador em segundo plano (que exigiria o servidor ligado
  24h para não perder um dia), o snapshot do dia é gravado/atualizado
  como efeito colateral de `GET /relatorios/dashboard` — a mesma chamada
  que a tela já faz toda vez que alguém abre o Painel Gerencial, sem
  thread nova, mesmo espírito "melhor esforço, sem infraestrutura nova"
  já usado em `usuarios.ultimo_acesso_em` (Fase 44). Limitação
  documentada: um dia em que ninguém abrir o painel (com aquele filtro de
  empresa específico) fica sem ponto na série — a tendência mostra um
  intervalo em branco, nunca um valor inventado. A tela ganhou um cartão
  novo, "Tendência", com seis mini-gráficos de linha em SVG puro (sem
  biblioteca de gráficos nova — mesmo espírito vanilla-JS do resto do
  front-end): Saldo projetado, A receber em aberto, A pagar em aberto,
  Taxa de aprovação (Qualidade), Valor total expedido e Clientes ativos,
  com uma janela selecionável (30/90/180 dias). Reaproveita a mesma
  permissão `relatorios.visualizar` de sempre — nenhuma permissão nova —
  e o mesmo filtro de empresa da Fase 52. Variações que ainda ficariam de
  fora se o cliente pedir: granularidade menor que um dia (ex.: por
  hora), e um agendador de verdade para garantir captura mesmo em dias
  sem ninguém abrir o painel.
- (Entregue na Fase 42) Painel Gerencial — Filtro por Período: um sexto
  cartão, opcional e aditivo, "No período", com indicadores de FLUXO
  (ordens concluídas, lotes aprovados/reprovados, pedidos expedidos,
  valor expedido/recebido/pago) filtráveis por `data_inicio`/`data_fim`
  — os cinco cartões de "situação atual" da Fase 7 continuam sempre sem
  filtro, de propósito (saldo de estoque e contas em aberto são o estado
  ATUAL, não fazem sentido filtrados por período). Variação que ainda
  ficaria de fora se o cliente pedir: ver o bullet acima (série
  histórica/tendência).
- (Entregue na Fase 52) Painel Gerencial — Filtro por Empresa: um
  `empresa_id` opcional, nullable e sem valor padrão nem backfill (ver
  `migrations/schema_fase52.sql`), acrescentado direto em
  `ordens_producao`, `lotes`, `pedidos_venda`, `contas_receber` e
  `contas_pagar` (não em `itens`/`formulas`, que continuam sendo
  cadastros compartilhados entre todas as empresas do grupo). Ao
  contrário do filtro por período (Fase 42), que só afeta o sexto
  cartão "No período", o filtro por empresa afeta os CINCO cartões de
  "situação atual" inteiros (Produção, Qualidade, Estoque, Comercial,
  Financeiro) — sem o filtro, o painel continua 100% idêntico a antes
  desta fase; com ele, cada cartão passa a contar só o que foi
  explicitamente marcado com aquela empresa. `contas_receber.empresa_id`
  nunca é perguntado de novo: é herdado automaticamente do pedido de
  venda no momento da expedição (`comercial.py:expedir`), do mesmo jeito
  que o valor da conta já era. O bloco Estoque usa DOIS caminhos
  diferentes de propósito: saldo/lotes vencidos usam a coluna nova
  `lotes.empresa_id` (mesma fonte de verdade do bloco Qualidade), mas
  "posições ativas" — uma métrica de infraestrutura do armazém, não do
  lote que está ocupando a posição agora — continua usando o caminho já
  existente desde a Fase 1 (`posicoes_estoque → unidades → empresas`).
  Três sub-métricas ficam DELIBERADAMENTE fora do escopo do filtro,
  porque não têm um vínculo natural com uma única empresa:
  `desvios_por_status` (um desvio pode não ter lote nenhum —
  `desvios.lote_id` é opcional), `analises_aguardando_resultado` (uma
  análise não tem nenhum vínculo com empresa) e `clientes_ativos` (um
  cliente não pertence a uma empresa específica do grupo). O filtro
  compõe livremente com o de período da Fase 42 (os dois são
  independentes) e reaproveita a mesma permissão `relatorios.visualizar`
  de sempre — nenhuma permissão nova. Os quatro formulários de criação
  que ganharam a coluna nova (Nova ordem de produção, Registrar
  recebimento, Novo pedido de venda, Nova conta a pagar) mostram um
  seletor de empresa OPCIONAL, que só aparece para quem tem a permissão
  `empresas.visualizar` — sem essa permissão, o formulário continua
  idêntico a antes desta fase.
- (Entregue na Fase 45) Painel Gerencial — Exportar em XLSX de verdade:
  um terceiro botão, "Baixar XLSX", ao lado de "Baixar PDF"/"Baixar CSV"
  — a Fase 19 já apontava isso como pendente por depender de uma
  biblioteca nova (`openpyxl`), que passou a estar disponível. Duas
  abas: "Painel Gerencial" (os cinco blocos de sempre + a seção "No
  período" da Fase 42, quando o filtro é usado) e "Fluxo de Caixa
  Projetado" (Fase 15), com célula de moeda formatada de verdade e uma
  linha de Total que usa uma fórmula `=SOMA(...)` calculada pela própria
  planilha — não um número já somado em Python — exceto a coluna "Saldo
  acumulado", que copia o último valor da série (correto por definição,
  já que somar todos os buckets estaria matematicamente errado ali).
  Reaproveita exatamente a mesma agregação e a mesma permissão
  `relatorios.visualizar` do PDF/CSV — nenhuma tabela nova, nenhuma
  permissão nova.
- (Entregue na Fase 41) DRE Completo — Despesas Operacionais e Impostos
  sobre Vendas: a Fase 20 cobria só Receita − CMV = Lucro Bruto; a Fase
  41 chega em Lucro Líquido, reaproveitando `contas_pagar` (categoria
  'despesa_operacional', sem tabela nova) e um percentual único de
  imposto configurável. Variações que ainda ficariam de fora se o
  cliente pedir: um DRE por regime de competência fiscal completo (mês
  fiscal fechado, não só um filtro de data_inicio/data_fim); despesas
  operacionais recorrentes lançadas automaticamente todo mês (hoje cada
  lançamento é manual, um por vez, como qualquer conta a pagar); e um
  centro de custo/rateio por departamento para a despesa operacional
  (hoje é um valor único por lançamento, sem dividir entre setores). O
  detalhamento de PIS/COFINS/ICMS/ISS em alíquotas separadas, que também
  estava listado aqui, foi entregue na Fase 56 (ver bullet próprio
  abaixo).
- QR code visual para configurar o 2FA (hoje o endpoint `/2fa/setup`
  devolve o `otpauth_uri` e o segredo em texto, que já funcionam para
  digitar manualmente no aplicativo autenticador, mas sem imagem de QR
  code ainda) — avaliado como candidato para a Fase 37 e adiado de
  propósito: gerar a imagem de verdade (matriz de módulos + correção de
  erro Reed-Solomon) exigiria uma biblioteca nova (`qrcode` ou
  equivalente) indisponível no ambiente onde esta fase foi construída, e
  implementar um codificador QR do zero, à mão, seria um esforço grande e
  arriscado para um ganho cosmético — o fluxo manual (copiar o segredo)
  já funciona desde a Fase 1. Se o ambiente de uma entrega futura tiver
  acesso a essa biblioteca, é uma fase pequena e isolada.
- (Entregue na Fase 37) Envio real de notificações por e-mail — a tabela e
  a API para listar/marcar como lida já existiam desde a Fase 1, mas
  nada criava uma notificação de verdade; a Fase 37 entregou o gatilho
  (avisar quem precisa aprovar uma pendência) e o envio real via SMTP
  configurável pela tela, sempre em modo melhor esforço. Variações que
  ainda ficariam de fora se o cliente pedir: notificação em outros
  eventos além das filas de segunda aprovação (ex.: lote reprovado,
  desvio aberto, recall simulado); um provedor de e-mail transacional de
  terceiros (SendGrid, SES) em vez de SMTP genérico; e notificação por
  outros canais além de e-mail (push no navegador, SMS, WhatsApp).
- (Entregue na Fase 38) App instalável para celular/tablet — todo o
  sistema (não só a tela do App de Vendas da Fase 36) agora fica
  responsivo em tela estreita e pode ser "instalado" na tela inicial do
  aparelho como Progressive Web App (PWA): `manifest.json` + service
  worker, layout com gaveta de menu e tabelas com rolagem própria abaixo
  de 900px de largura. Deixando claro o que ficou de fora, por ser
  tecnicamente inalcançável neste ambiente: um aplicativo NATIVO
  (Android/iOS) publicado numa loja de aplicativos (Google Play/App
  Store) — isso exigiria um SDK nativo (Android Studio/Kotlin, Xcode/
  Swift, ou um framework híbrido como React Native/Flutter) e acesso à
  infraestrutura de publicação de cada loja, nenhum dos dois disponível
  neste ambiente de desenvolvimento (sem acesso de rede para instalar
  SDKs, sem as ferramentas de build nativas). A PWA entregue é a
  alternativa honesta e plenamente funcional dentro dessa restrição:
  mesmo código-fonte, mesma lógica de negócio, ícone próprio na tela
  inicial, abre em janela sem barra de endereço — só não passa por uma
  loja de aplicativos. Notificação push de verdade (que dependeria de um
  serviço de push como o Firebase Cloud Messaging) também fica de fora
  por ora — a Fase 37 já cobre o aviso por e-mail, que continua
  funcionando normalmente dentro do app instalado.
- (Entregue na Fase 39) MRP — Cálculo de Necessidade de Materiais: a Fase
  25 já recusava, ao liberar UMA ordem, o material insuficiente; a Fase
  39 entrega a visão somada de TODAS as ordens ainda planejadas, com
  fornecedores homologados para cada falta. Variações que ainda ficariam
  de fora se o cliente pedir: MRP de múltiplos níveis / explosão de BOM
  recursiva (hoje cada ordem soma só os insumos DIRETOS da sua fórmula —
  se um insumo fosse, ele mesmo, produzido a partir de outra fórmula com
  sua própria ordem, o sistema não "explode" automaticamente essa segunda
  camada de necessidade); e considerar ordens ainda nem criadas mas
  previstas (hoje o MRP só olha ordens que já existem no sistema como
  `planejada` — não existe ainda um "plano mestre de produção" prevendo
  demanda futura que ainda não gerou ordem). A sugestão automática de
  compra a partir da falta, que também estava listada aqui, foi entregue
  na Fase 54 (ver bullet próprio abaixo), e considerar o lead time de
  compra de cada fornecedor para dizer "compre até tal data" foi entregue
  na Fase 57 (ver bullet próprio abaixo).
- (Entregue na Fase 54) MRP — Sugestão Automática de Compra: até aqui o
  MRP (Fase 39) só INFORMAVA a falta — Compras tinha que copiar cada item
  manualmente para lançar depois. O botão novo "Gerar sugestões de
  compra", na própria tela de MRP, recalcula a necessidade atual e cria
  uma `sugestao_compra_mrp` `pendente` por item em falta (pulando os que
  já têm uma pendente em aberto, para não duplicar clicando duas vezes),
  com o fornecedor homologado sugerido (o primeiro da lista, quando
  existe algum) e um snapshot das ordens de produção que motivaram a
  necessidade. Decisão de escopo central, deliberada: isto NÃO cria uma
  conta a pagar de verdade — uma sugestão é só uma PREVISÃO, sem preço
  nem vencimento reais ainda (ver a nota completa em
  `migrations/schema_fase54.sql`); só quando Compras efetivamente compra
  e lança a conta a pagar pela tela já existente desde a Fase 6 é que a
  sugestão é marcada como **Atendida**, linkando opcionalmente o ID dessa
  conta real (o link é opcional — a compra pode ter sido fechada fora do
  sistema, ou a nota fiscal só chegar depois). Uma sugestão também pode
  ser **Descartada**, com motivo obrigatório, se Compras decidir não
  comprar por ora — e um novo ciclo de "Gerar sugestões" pode criar uma
  sugestão nova para o mesmo item mais tarde, se a necessidade persistir
  ou voltar a existir. Duas permissões novas, separadas pelo mesmo motivo
  de sempre (gerar é de baixo risco; decidir fecha o ciclo de Compras):
  `producao.gerar_sugestao_compra` e `producao.decidir_sugestao_compra`,
  ambas já concedidas ao perfil Compras por padrão. Variações que ainda
  ficariam de fora se o cliente pedir: gerar automaticamente um PEDIDO DE
  COMPRA formal (com múltiplos itens do mesmo fornecedor agrupados) em
  vez de uma sugestão por item isolado; e um fluxo de aprovação para a
  própria sugestão antes de virar compra (hoje qualquer um com
  `decidir_sugestao_compra` pode atender/descartar sozinho, sem segunda
  aprovação — decisão consistente com o baixo risco da ação, já que
  nenhuma obrigação financeira real é criada automaticamente).
- (Entregue na Fase 40) Conciliação Bancária — Importação de Extrato OFX:
  importar o extrato do banco e conciliar automaticamente quando o
  candidato é único, com revisão manual (conciliar escolhendo entre
  candidatos, ignorar, desconciliar) para o resto. Variações que ainda
  ficariam de fora se o cliente pedir: outros formatos de arquivo além
  de OFX — em especial o **CNAB** (padrão FEBRABAN usado por muitos
  bancos brasileiros para retorno de cobrança/pagamento), que tem um
  layout de posição fixa totalmente diferente do OFX e exigiria um
  parser próprio; correspondência aproximada/difusa além da regra atual
  (mesmo valor exato — tolerância de meio centavo só para erro de
  arredondamento —, ver Fase 55 para a janela de DATA), por exemplo
  permitir um pequeno desvio no VALOR (útil para taxa de boleto descontada
  automaticamente pelo banco); e importação automática/agendada via Open
  Finance ou integração direta com o banco, em vez de exigir que o usuário
  baixe e envie o arquivo manualmente. A janela de dias configurável pela
  tela e o botão de "conciliar todos os candidatos únicos" em lote, que
  também estavam listados aqui, foram entregues na Fase 55 (ver bullet
  próprio abaixo).
- (Entregue na Fase 55) Conciliação Bancária — Processamento em Lote e
  Janela de Dias Configurável: duas melhorias sobre a Fase 40, ambas de
  escopo puramente local (nenhuma integração de rede/banco nova, nenhuma
  tabela nova). Primeiro, a tolerância de dias entre a data de uma
  transação do extrato e a data de uma baixa já registrada — antes fixa em
  3 dias no código — passou a morar em `configuracoes_financeiro`
  (coluna `tolerancia_dias_conciliacao`, migration `schema_fase55.sql`),
  editável na MESMA tela "Configurar Financeiro" e com a MESMA permissão
  já usadas desde a Fase 33/41 (`configurar_limite_estorno`) — o padrão
  continua 3, idêntico ao comportamento de sempre. Segundo, um botão novo,
  "Conciliar todos os candidatos únicos" (rota
  `POST /financeiro/extratos/conciliar-pendentes-em-massa`), que reprocessa
  transações `pendente` já importadas usando a MESMA regra automática da
  importação (só concilia com exatamente 1 candidato inequívoco) — existe
  porque essa auto-conciliação antes só era tentada UMA VEZ, no instante da
  importação: uma transação que ficou pendente só porque a baixa
  correspondente ainda não existia no Financeiro nunca era reprocessada
  depois, mesmo que a baixa aparecesse minutos ou dias mais tarde. O botão
  aparece em dois lugares — na lista de extratos (reprocessa TODAS as
  transações pendentes do sistema) e na tela de detalhe de UM extrato
  (escopado só a ele, via `extrato_id` opcional no corpo da requisição) —
  e fica desabilitado quando não há nenhuma transação pendente para
  processar. Reaproveita a mesma permissão de sempre
  (`financeiro.conciliar_extrato`) — nenhuma permissão nova, já que o botão
  só repete uma regra automática que já existia, nunca inventa uma
  correspondência nova. Variações que ainda ficariam de fora se o cliente
  pedir: ver as variações já documentadas no bullet da Fase 40 acima
  (CNAB, desvio no valor, Open Finance).
- (Entregue na Fase 56) DRE — Impostos Detalhados (PIS/COFINS/ICMS/ISS): a
  Fase 41 calculava "Impostos sobre Vendas" com um percentual único e
  documentava, em "O que ainda falta", a ausência das quatro alíquotas
  reais brasileiras separadas. Esta fase entrega exatamente isso, de forma
  puramente aditiva — quatro colunas novas em `configuracoes_financeiro`
  (`percentual_pis`, `percentual_cofins`, `percentual_icms`,
  `percentual_iss`, migration `schema_fase56.sql`, todas `DEFAULT 0`),
  configuráveis na MESMA tela "Configurar Financeiro" e reaproveitando a
  MESMA permissão de sempre (`configurar_limite_estorno`) — nenhuma
  permissão nova. As quatro SOMAM com a alíquota genérica da Fase 41,
  nunca a substituem: quem já tinha o percentual único configurado
  continua com ele funcionando, e o total (`impostos_sobre_vendas`) e o
  Lucro Líquido continuam sendo os mesmos campos de sempre para quem só
  olha o resultado consolidado. A tela do DRE ganha uma tabela nova,
  "detalhamento por tributo", que lista cada alíquota configurada com seu
  valor no período — mas só aparece quando pelo menos uma das cinco está
  configurada (> 0); numa instalação nova, sem nada configurado, a tela
  fica pixel-idêntica à de antes desta fase. Variações que ainda ficariam
  de fora se o cliente pedir: um regime tributário completo por
  Simples/Presumido/Real (hoje são cinco alíquotas efetivas fixas, sem
  faixas/regras por regime); ICMS com substituição tributária ou
  diferencial de alíquota interestadual (hoje é uma alíquota efetiva
  única sobre a receita bruta); e cálculo automático a partir da NCM/CFOP
  de cada item vendido (hoje as cinco alíquotas são globais para a
  empresa, não por item ou operação).
- (Entregue na Fase 57) MRP — Lead Time de Compra do Fornecedor: a Fase 39
  dizia QUANTO faltava comprar, mas nunca ATÉ QUANDO, porque o cadastro de
  fornecedor não guardava nenhum prazo de entrega. Um campo novo e
  OPCIONAL, `lead_time_dias` (migration `schema_fase57.sql`, `NULL` por
  padrão), editável na criação do fornecedor ou pela rota dedicada
  `PUT /fornecedores/{id}/lead-time` (reaproveita `fornecedores.cadastrar`
  — mesmo risco de um dado de cadastro, não de uma decisão de
  homologação), permite ao MRP calcular uma `data_limite_compra` por item
  em falta: a data de início planejado (Agenda Visual do APS, Fase 25/28)
  da ordem mais próxima que precisa daquele item, menos o lead time do
  fornecedor sugerido (o mesmo primeiro fornecedor homologado, por nome,
  já usado pela sugestão automática da Fase 54). Sem ordem agendada, ou
  sem lead time configurado, nenhuma data é inventada — o MRP mostra o
  motivo em texto. Gerar uma sugestão de compra (Fase 54) congela essa
  data no momento da geração (coluna nova `data_limite_compra` em
  `sugestoes_compra_mrp`) — mudar o lead time depois não altera uma
  sugestão já criada, só o próximo cálculo ao vivo do MRP. Nenhuma
  permissão nova. Variações que ainda ficariam de fora se o cliente
  pedir: MRP de múltiplos níveis / explosão de BOM recursiva e um plano
  mestre de produção com demanda futura sem ordem ainda criada — ambos já
  fora de escopo desde a Fase 39; e lead time por ITEM+fornecedor, em vez
  de um valor único por fornecedor para tudo que ele entrega.
- (Entregue na Fase 53) Recall — Decisão sobre Pedidos Já Expedidos: a
  Fase 16 entregou o bloqueio em massa dos LOTES afetados por um recall,
  mas deliberadamente não mexia em pedidos de venda já expedidos do mesmo
  lote — o campo `resumo.pedidos_expedidos` da simulação ficava só como
  informação para decisão manual. Esta fase fecha essa lacuna com duas
  rotas novas, `POST /rastreabilidade/recalls/{id}/pedidos/{pedido_id}/decisoes`
  e `GET /rastreabilidade/recalls/{id}/decisoes`, que REGISTRAM (não
  executam) a decisão tomada para cada pedido já expedido afetado —
  `notificar_cliente`, `aguardar_devolucao`, `gerar_nota_credito`,
  `cancelar_pedido` ou `sem_acao` — num motivo obrigatório e observação
  opcional. A nova tabela `decisoes_recall_pedido`
  (`migrations/schema_fase53.sql`) é append-only, mesma filosofia de
  `simulacoes_recall`: cada decisão é um evento histórico de conformidade,
  nunca um status a sobrescrever — múltiplas decisões para o mesmo pedido
  ao longo do tempo são esperadas (ex.: hoje "aguardar devolução", depois
  "cancelar pedido") e todas ficam preservadas. Decisão de escopo
  deliberada e conservadora: a rota NÃO executa nada sozinha — cancelar o
  pedido de fato continua exigindo a rota própria de Comercial
  (`cancelar_pedido_internamente`, que continua rejeitando pedidos
  'expedido', ver Fase 5/6) e estornar uma conta a receber continua
  exigindo a rota própria de Financeiro; reabrir essas regras já testadas
  para permitir cancelamento automático de pedido expedido envolveria
  reverter uma saída de estoque física já ocorrida, um problema maior e
  fora do escopo desta fase. A permissão nova
  `rastreabilidade.decidir_pedido_recall` é separada de
  `simular_recall`/`bloquear_em_massa` (mesmo padrão de segregação da
  Fase 16) e, ao contrário delas, não exige dupla aprovação — por não
  executar nada irreversível. A listagem (`GET .../decisoes`) sempre
  recalcula o status ATUAL do pedido e da conta a receber (nunca
  congelado), mesmo princípio já usado em `detalhe_recall`/Fase 16 para o
  status dos lotes afetados. Um pedido que não está entre os
  `pedidos_expedidos` daquela simulação específica não pode receber uma
  decisão (400), mesmo que exista e esteja expedido — a decisão precisa
  estar ligada à investigação que a motivou.
- (Entregue na Fase 34) Alçada por VALOR monetário do ajuste, não só por
  percentual de divergência — hoje um segundo gatilho independente
  (`configuracoes_estoque.limiar_valor_ajuste_divergencia_grande`, 0 =
  desligado por padrão) também exige segunda aprovação quando o valor
  financeiro do ajuste (diferença × custo unitário do lote) ultrapassa
  um limiar em R$, mesmo com percentual pequeno. Quando o custo não é
  conhecido, conta como divergência grande por segurança (filosofia de
  transparência da Fase 13). Uma variação que ainda ficaria de fora se o
  cliente pedir: hoje o custo usado é o "melhor disponível no momento do
  ajuste" (custo do lote, média do item, ou custo real de produção via
  `custeio.custo_unitario_lote`) — não existe um registro histórico de
  "qual era o custo exato no dia em que o saldo divergente se formou",
  então em teoria o valor estimado do ajuste pode não refletir
  exatamente o custo da época se o preço do item mudou entre o
  desalinhamento físico e a contagem que o descobriu.
- (Entregue na Fase 32) Limiar de divergência configurável pela tela —
  hoje fixo em 20% no código (`LIMIAR_PERCENTUAL_DIVERGENCIA_GRANDE`)
  desde a Fase 21, agora mora em `configuracoes_estoque` e é editável
  por quem tem a permissão nova `estoque.configurar_alcada_divergencia`
  (só o Administrador, por padrão).
- (Entregue na Fase 35) Agendamento/cadência automática de contagens
  cíclicas — uma regra cadastrada uma vez (depósito, tipo, cadência
  diária/semanal/mensal) gera a contagem sozinha quando o dia certo
  chega, verificada sempre que a tela de Estoque é aberta (não um cron
  de sistema operacional de verdade — ver README de `tests_e2e/` ou o
  comentário em `app/routes/estoque.py`). Uma variação que ainda ficaria
  de fora se o cliente pedir: seleção da amostra cíclica por critério de
  criticidade/curva ABC (hoje a amostra é sempre um sorteio aleatório
  simples entre TODAS as combinações lote+posição com saldo — não existe
  ainda uma classificação de itens por importância/valor de movimento
  para priorizar o que entra na amostra).
- (Entregue na Fase 36) Aplicativo de Vendas para Vendedores — nova tela
  "App de Vendas" com rascunho e reserva temporária de item (soft-hold),
  verbas comerciais do cliente e comissão do vendedor (projetada vs.
  realizada na liquidação). Variações que ainda ficariam de fora se o
  cliente pedir: um vendedor só monta UM rascunho por vez (não vários
  carrinhos simultâneos, um por cliente); a comissão usa um único
  percentual global (`configuracoes_comercial.percentual_comissao_padrao`),
  sem ainda permitir um percentual diferente por vendedor ou por produto;
  não existe reversão de verba (`estorno_de_id` como o de Contas a Receber
  da Fase 14) porque o sistema ainda não tem um fluxo de devolução de
  pedido de venda; não existe uma tabela de preços por item (o vendedor
  digita o preço unitário manualmente, igual à tela de desktop desde a
  Fase 5); e "fechar o app" é detectado por melhor esforço (o app tenta
  avisar o servidor ao fechar, mas nenhum evento de fechamento de
  navegador é 100% confiável) — a expiração automática por inatividade é
  a rede de segurança para quando esse aviso não chega.
- (Entregue na Fase 29) Conectar os catálogos da Fase 26 como seletores
  dentro do formulário de edição de um memorial: cada campo mapeado ganha
  um botão "+ Catálogo" que INSERE o texto de um item já cadastrado (o
  campo continua sendo texto livre — não virou um `<select>` de verdade,
  então ainda dá pra digitar/editar por cima livremente). Uma
  simplificação que ficou de propósito: é "inserir texto", não "vincular
  o registro" — depois de inserido, o texto no memorial não fica mais
  ligado ao item do catálogo (se o item for editado ou excluído depois, o
  texto já inserido em memoriais antigos não muda); se o cliente
  precisar de rastreabilidade de verdade entre um memorial e os itens de
  catálogo usados nele (não só o texto copiado), isso viraria uma
  modelagem diferente — uma tabela de associação em vez de um campo de
  texto — e ficaria para um refinamento futuro, só se pedido.
- (Entregue na Fase 43) Exportar "PDF Completo" combinando anexos: um
  botão novo, "Baixar PDF Completo", na mesma sub-aba Exportar da Fase
  27 (que continua com o "Imprimir / Salvar como PDF" de sempre), gera
  no SERVIDOR um único PDF com o memorial inteiro (renderizado com
  reportlab, mesma biblioteca das Fases 10/11/18) mais os anexos que
  forem PDF (páginas mescladas com `pypdf`) ou imagem (convertidas para
  uma página nova com `img2pdf`) — nessa ordem, um depois do outro.
  Limite deliberado e documentado: um anexo de outro tipo (Word, Excel,
  texto puro, etc.) NUNCA derruba a exportação — ele só não entra
  fisicamente no PDF, e aparece listado numa página de apêndice
  ("Anexos não incorporados neste PDF") explicando o motivo, continuando
  disponível para baixar separadamente como sempre. Converter Word/
  Excel para PDF de verdade exigiria um conversor de documentos (ex.:
  LibreOffice em modo headless) como dependência extra instalada na
  máquina do cliente — um passo bem mais pesado que só `pip install`, e
  que decidimos não exigir só por causa deste recurso; se o cliente
  precisar disso no futuro, é uma extensão pontual desta mesma fase.
  Nenhuma tabela nova, nenhuma permissão nova (reaproveita
  `memoriais.visualizar` de sempre).
- Protocolo de Estabilidade — um módulo relacionado ao Memorial Técnico,
  mas tratado pelo cliente como uma peça separada e deliberadamente fora
  do escopo desta entrega ("vamos implantar esse [Memorial] e ver como se
  comporta após implantado" — as próprias palavras do cliente ao definir
  o escopo).
- (Entregue na Fase 28) Agenda/calendário visual da Fase 25 — APS: já
  tinha o endpoint pronto desde a Fase 25 (`GET /aps/agenda`), faltava a
  tela; a Fase 28 entregou a visão consolidada tipo calendário/Gantt
  (uma linha por centro de trabalho, uma coluna por dia da semana). Uma
  simplificação que ficou de propósito: um agendamento que atravessa mais
  de um dia aparece repetido em cada dia, em vez de uma única barra
  "esticada" cobrindo o intervalo todo — se o cliente quiser a barra
  única (visualmente mais parecida com um Gantt "de verdade"), isso pode
  entrar como refinamento futuro.
- Seção administrativa própria do sistema original do Memorial Técnico
  (gerenciar usuários daquele sistema, ver usuários online, snapshots e
  restauração de banco, backups do sistema): a decisão original (Fase 24)
  foi não portar, já que a Alphafitus já tem seu próprio módulo de
  Usuários/Perfis/Permissões e sua própria trilha de auditoria (Fase 1),
  e duplicar essa administração dentro do Memorial Técnico criaria dois
  lugares diferentes para a mesma coisa — mas o cliente pediu
  explicitamente para replicar mesmo assim ("Replicar tudo, incluindo
  Administração"), então isso entrou como entregas seguintes, uma peça
  por vez. Usuários Online, Snapshots & Restauração, Backups do Sistema,
  Gerenciar Usuários e Configurações foram entregues nas Fases 44, 46,
  47, 48 e 49 — ver bullets próprios abaixo. Com a Fase 49, a seção
  "Administração" replicada dentro do Memorial Técnico está
  COMPLETA — nenhuma peça pendente.
- (Entregue na Fase 44) Usuários Online, o primeiro pedaço da seção
  administrativa acima: um novo item de menu dentro do Memorial Técnico
  ("Usuários Online", visível para quem tem `usuarios.visualizar` —
  nenhuma permissão nova) lista todos os usuários ativos com um selo
  Online/Offline. O sistema original guardava sessão em Postgres
  (connect-pg-simple) e não tinha um equivalente pronto em SQLite; em vez
  de portar uma tabela de sessões com polling (o que o cliente
  originalmente descreveu), a solução ficou mais simples e sem nenhuma
  tabela nova de verdade: uma coluna `usuarios.ultimo_acesso_em`,
  atualizada silenciosamente (sem entrada na trilha de auditoria — vira
  ruído a cada requisição) a cada requisição autenticada com sucesso.
  "Online" é qualquer usuário cujo último acesso caiu dentro de uma janela
  de 5 minutos (`ONLINE_JANELA_MINUTOS`, em `app/routes/usuarios.py`) —
  não é uma conexão em tempo real (sem WebSocket nesta versão), então
  pode levar até esse tempo para alguém aparecer como offline depois de
  sair; ele se resolve sozinho na próxima vez que a tela for atualizada,
  sem precisar de nenhum processo de fundo novo.
- (Entregue na Fase 46) Snapshots & Restauração, o segundo pedaço da
  seção administrativa acima: um novo item de menu dentro do grupo
  "Administração" ("Snapshots & Restauração") com dois botões — "Baixar
  Snapshot (.json)" exporta o conteúdo INTEIRO das tabelas do Memorial
  Técnico (empresas, produtos, memoriais, assinaturas, histórico, anexos,
  padronizações e os 10 catálogos) num único arquivo, o "backup" deste
  módulo; "Restaurar" faz o caminho inverso, SUBSTITUINDO por completo o
  conteúdo atual pelo conteúdo do arquivo escolhido (por isso a tela pede
  confirmação explícita, com o resumo de quantos registros de cada tabela
  serão restaurados, antes de chamar a API). Como o sistema original
  guardava isso em Postgres com `pg_dump`/`pg_restore` e aqui cada tabela
  já é lida/escrita como um dict Python comum, um "snapshot" é simplesmente
  JSON puro — DB-agnóstico por natureza, funciona igual se o sistema for
  migrado de SQLite para PostgreSQL no futuro. Reaproveita permissões que
  já existem: `memoriais.visualizar` para exportar (é só uma leitura maior
  do módulo) e `memoriais.excluir` para restaurar (a mais destrutiva do
  módulo, de propósito, já que restaurar pode apagar qualquer coisa
  cadastrada depois do snapshot). A restauração roda inteira dentro de um
  `SAVEPOINT` próprio do SQLite — se qualquer coisa falhar no meio
  (arquivo de uma versão diferente, referência a um registro que não
  existe), o `SAVEPOINT` é desfeito antes de devolver o erro, então uma
  restauração que falha não deixa o módulo pela metade: ou restaura tudo,
  ou nada muda.
- (Entregue na Fase 47) Backups do Sistema, o terceiro pedaço da seção
  administrativa acima: um novo item de menu dentro do grupo
  "Administração" ("Backups do Sistema") com um botão só, "Baixar Backup
  Completo (.db)". Diferente dos outros dois pedaços — que são só sobre o
  módulo Memorial Técnico — este é uma cópia do BANCO DE DADOS INTEIRO
  (todos os módulos: usuários, produção, estoque, financeiro etc.),
  gerada com a API de backup nativa do próprio `sqlite3` do Python
  (`Connection.backup()`), que faz uma cópia consistente sem precisar
  parar o servidor. Por ter um escopo bem maior que o dos outros dois
  pedaços, usa uma permissão NOVA e separada, `sistema.backup_completo`
  (mesmo módulo genérico "sistema" da Fase 37 — `configurar_email` — em
  vez de `memoriais.*`): ter todas as permissões do Memorial Técnico
  (incluindo `memoriais.excluir`) não dá, por si só, acesso a um backup
  de todo o sistema, só o Administrador tem essa permissão por padrão.
  Ao contrário dos outros dois pedaços, esta tela não tem NENHUM botão de
  "restaurar" — decisão de segurança deliberada: substituir o arquivo
  `.db` inteiro com o servidor rodando arriscaria corromper o banco (ver
  "Restaurando um Backup do Sistema" mais acima), então a restauração
  deste tipo de backup é sempre um procedimento manual, com o serviço
  parado, nunca uma ação de um clique dentro do sistema no ar.
- (Entregue na Fase 48) Gerenciar Usuários, o quarto e último pedaço da
  seção administrativa acima — mas, diferente dos outros três, este não é
  uma tela nova: é a MESMA tela central de Usuários (`renderUsuarios`),
  agora acessível também por um item de menu dentro de "Administração"
  ("Gerenciar Usuários", logo acima de "Usuários Online"), com a nav do
  Memorial Técnico ao redor. Nenhuma tabela nova, nenhuma rota nova,
  nenhuma permissão nova (reaproveita `usuarios.visualizar`/`cadastrar`/
  `editar`/`inativar` de sempre) — a função de renderização passou a
  aceitar um parâmetro que só troca a MOLDURA (nav do Memorial em vez da
  barra lateral central), sem duplicar a consulta à API, os modais nem os
  botões. Essa é a diferença central em relação à objeção original da
  Fase 24 ("duplicar essa administração criaria dois lugares diferentes
  para a mesma coisa"): agora há dois CAMINHOS de menu, mas continua
  havendo só UM lugar onde o dado de usuário de fato mora e é editado —
  criar, editar ou inativar um usuário por aqui tem exatamente o mesmo
  efeito, imediatamente visível, que fazer isso pelo menu central
  "Usuários".
- (Entregue na Fase 49) Configurações, o quinto e ÚLTIMO pedaço da seção
  administrativa acima — fecha por completo a réplica de "Administração"
  dentro do Memorial Técnico. Diferente dos outros quatro pedaços, esta
  tela não existia de verdade no sistema original (o item de menu
  "Configurações" lá era, na prática, um bug que apontava para a tela de
  Metodologias) — então, em vez de inventar uma tela sem nenhuma
  especificação real para copiar, a Fase 49 seguiu o mesmo caminho já
  usado nas Fases 32 a 36: pegar uma regra hoje CODIFICADA/fixa no Python
  e específica do módulo Memorial Técnico, e transformá-la numa
  "configuração em linha única" editável pela tela. As duas únicas regras
  desse tipo existentes hoje no módulo: quantas assinaturas um memorial
  "Concluído" precisa acumular para ser promovido automaticamente a
  "Aprovado" (`numero_assinaturas_aprovacao`, era o literal `2` fixo em
  três lugares de `app/routes/memorial.py` — a regra de negócio da Fase
  24), e o tamanho máximo de um único anexo de arquivo
  (`tamanho_maximo_anexo_mb`, era a constante `MAX_ANEXO_BYTES` fixa em
  `app/routes/memorial_anexos.py` — a regra da Fase 27). Os dois valores
  padrão (2 e 40) preservam exatamente o comportamento de sempre — nenhum
  memorial ou anexo já existente muda de comportamento só por esta fase
  existir. Ver o valor atual (`GET`) só exige `memoriais.visualizar` — o
  número em si não é sensível; só ALTERAR (`PUT`) exige a permissão nova
  `memoriais.configurar`, que por padrão só o Administrador tem (mesmo
  padrão GET-mais-fraco/PUT-mais-forte já usado no limiar de divergência
  de contagem, Fase 32/34). Com isso, a seção "Administração" do Memorial
  Técnico está 100% completa.
- (Entregue na Fase 80) Solicitações de Materiais/EPI — novo módulo, novo
  grupo "Materiais & EPI" no menu. Fluxo completo: qualquer setor abre uma
  solicitação (`solicitacoes_material.solicitar`) → alguém com a permissão
  `solicitacoes_material.aprovar` decide (aprovar/rejeitar) — com a MESMA
  trava de segregação de função usada desde a Fase 1 na aprovação de lote
  (quem solicitou nunca pode aprovar o próprio pedido) — → só depois de
  aprovada o setor de entrega (normalmente Estoque, único perfil padrão
  com `solicitacoes_material.entregar`) pode registrar a entrega, inclusive
  parcial (quantidade entregue por item pode ser menor que a solicitada) →
  o PRÓPRIO solicitante confirma o recebimento, fechando o ciclo com uma
  segunda assinatura eletrônica (sem isso, a "prova de entrega" seria só a
  palavra de quem entregou). Cada etapa grava um registro de auditoria
  (`app/audit.py`, mesma tabela imutável de todo o resto do sistema).
  Catálogo próprio (`materiais_solicitaveis`, tela "Catálogo de Materiais/
  EPI"), DELIBERADAMENTE sem vínculo com a tabela `itens` — é um domínio
  diferente (consumível/EPI entregue a uma pessoa, não matéria-prima/
  produto rastreado por lote com FEFO) e o SQLite não permite alterar um
  CHECK constraint existente sem recriar a tabela inteira, um risco
  desnecessário para um catálogo que não precisa de nada da infraestrutura
  de lote/estoque. Um item do catálogo marcado como EPI pode levar o
  número do Certificado de Aprovação (C.A.); ao final de uma entrega
  (status `entregue` ou `recebimento_confirmado`), a tela oferece um
  "Comprovante de Entrega" em PDF (`GET /solicitacoes-material/<id>/
  comprovante/pdf`, mesmo padrão ReportLab do Certificado de Análise da
  Fase 1) que, quando algum item da solicitação é EPI, se transforma numa
  Ficha de Controle de Fornecimento de EPI com o texto de declaração de
  recebimento exigido pela NR-6 — documento pensado para uma eventual
  auditoria trabalhista, exatamente o pedido original desta fase. A
  aprovação (`solicitacoes_material.aprovar`) foi deliberadamente deixada
  SEM nenhum perfil padrão — cabe ao Administrador designar, pela tela de
  Perfis já existente, quem tem autoridade para aprovar essas solicitações
  na empresa real.
- (Entregue na Fase 81) Catálogo de Fluxo Configurável — primeira peça de um
  projeto maior (redesenho do Painel Tempo Real em formato Kanban/pipeline,
  ainda em andamento nas próximas fases) para acompanhar um pedido/matéria-
  prima atravessando de verdade todas as etapas do negócio, com espaço para
  cadastrar etapas novas sem precisar de código. **Escopo desta fase, de
  propósito:** a maior parte do pipeline já tem uma coluna de status de
  verdade em alguma tabela existente (`pedidos_venda.status`,
  `ordens_producao.status` + `ordem_producao_etapas`, `pedidos_compra.
  status`, `sugestoes_compra_mrp.status`, `lotes.status`) — duplicar isso
  aqui criaria duas fontes de verdade para a mesma coisa, o problema que
  este projeto sempre evitou (o Painel Tempo Real desde a Fase 44 sempre lê
  ao vivo, nunca guarda snapshot). Por isso `tipos_etapa_fluxo`/
  `fluxo_instancias` cobrem DELIBERADAMENTE só o que hoje não tem nenhuma
  coluna de status própria — a primeira etapa semeada é "Separação" de um
  pedido de venda (o espaço entre "confirmado" e "expedido" que hoje não
  tem nenhum checkpoint). Uma etapa cadastrada pelo Administrador ou PCP
  (`fluxo.configurar`) é materializada de forma PREGUIÇOSA: a primeira vez
  que a tela de uma entidade é aberta depois do cadastro, a etapa nova
  aparece "pendente" automaticamente, mesmo em pedidos que já existiam
  antes — sem nenhuma migração de backfill. Etapas com `origem='sistema'`
  (nenhuma ainda nesta fase; a primeira será "Coleta pela Transportadora"
  mais adiante) são pensadas para serem marcadas automaticamente por uma
  rota real via `app/fluxo_service.py::marcar_concluida(...)` no momento
  exato de uma transição de negócio — nunca inferidas batendo o relógio.
  Etapas `origem='manual'` (o caso de "Separação" hoje) são um checklist
  livre: qualquer usuário com `fluxo.apontar` inicia/conclui pela tela, sem
  nenhum outro efeito colateral no sistema. Testado no detalhe do Pedido de
  Venda (novo card "Etapas de Fluxo"); o Painel Tempo Real em si ainda não
  foi redesenhado — isso vem numa fase posterior deste mesmo projeto.
- (Entregue na Fase 82) PCP pode gerar Sugestão de Compra — antes desta
  fase, só o perfil Compras conseguia rodar o MRP e transformar a
  necessidade calculada numa sugestão de compra (`producao.
  gerar_sugestao_compra`), mesmo o PCP sendo quem primeiro enxerga que uma
  Ordem de Produção não vai ter matéria-prima suficiente. Mudança mínima
  de propósito: PCP ganhou só essa permissão em `seed.py` — decidir o que
  fazer com a sugestão (atender/descartar, `producao.
  decidir_sugestao_compra`) e convertê-la num Pedido de Compra real
  (`compras.criar_pedido`) continuam EXCLUSIVOS do perfil Compras, sem
  nenhuma mudança de código além do rótulo da tela (que passa a se chamar
  "Solicitações de Compra (MRP)" para quem não tem `compras.
  criar_pedido`, e "Sugestões de Compra (MRP)" para quem tem) — na
  prática, isso já implementa "PCP solicita, Compras aprova e confirma"
  reaproveitando 100% do mecanismo de MRP que já existia desde a Fase 54.
- (Entregue na Fase 83) Aprovação Financeira obrigatória em todo Pedido de
  Venda — antes desta fase, `pedidos_venda_confirmacoes_pendentes` (Fase
  63) só ganhava uma solicitação quando o pedido ultrapassava o limite de
  crédito do cliente; sem limite configurado, ou dentro do limite, a
  confirmação acontecia na hora (HTTP 200, estoque já reservado). A pedido
  explícito do usuário, **toda** confirmação agora passa por essa mesma
  fila (`confirmar_pedido_ou_solicitar_aprovacao` em
  `app/routes/comercial.py` sempre devolve 202, nunca mais 200 direto) —
  a reserva de estoque de verdade só acontece depois de aprovada
  (`aprovar_confirmacao_pedido`), com a MESMA segregação de função de
  sempre (quem solicitou não pode aprovar). Os números de limite de
  crédito continuam calculados e gravados (contexto útil para quem
  aprova), mas um novo campo `motivo_solicitacao`
  (`'acima_do_limite'`/`'aprovacao_obrigatoria_padrao'`,
  `ALTER TABLE pedidos_venda_confirmacoes_pendentes`) é quem diz de
  verdade por que a aprovação foi pedida — a coluna
  `limite_credito_no_momento` continua `NOT NULL` (SQLite não relaxa isso
  sem recriar a tabela), então sem limite configurado ela grava `0` só
  como preenchimento; nunca interprete esse `0` como "sem limite", porque
  um cliente pode ter um limite configurado que é literalmente zero. A
  permissão `comercial.aprovar_pedido_acima_limite_credito` manteve o
  nome (só a descrição mudou) para não quebrar perfis já concedidos em
  instalações existentes, e passou a ser concedida também ao perfil
  Financeiro por padrão (além do Comercial, que já a tinha desde a Fase
  63) — faz mais sentido um financeiro de verdade aprovar isso agora que
  virou o caminho único, não a exceção. **Mudança de comportamento
  relevante:** o App de Vendas (`vendas_app.py::enviar_rascunho`)
  reaproveita a mesma função e já herda o comportamento automaticamente,
  sem nenhuma alteração de código lá — mas qualquer fluxo externo que
  chamava "Confirmar" esperando 200 direto agora sempre recebe 202.
- (Entregue na Fase 84) Granel intermediário como etapa + Centro de
  Trabalho por etapa + Apontamento Diário de Produção — três mudanças
  pequenas e independentes na mesma fase, todas dentro da Ordem de
  Produção já existente:
  1. Novo tipo no catálogo de etapas (Fase 75) — "Descarregamento/Estoque
     Intermediário" (kg) — para o usuário registrar a quantidade de
     "produto a granel em pó" que sai da Mistura antes de ir para
     Encapsulamento/Envase, DENTRO da mesma ordem (decisão explícita do
     usuário: sem gerar um lote/CQ separado para isso). `ordem_padrao`
     dos tipos existentes foi renumerado (`UPDATE`, não é estrutural) para
     refletir a sequência real: Pesagem → Mistura → Descarregamento →
     Granulação → Compressão → Encapsulamento → Envase → Rotulagem →
     Embalagem.
  2. `ordem_producao_etapas.centro_trabalho_id` (nova coluna, opcional) —
     permite escolher qual das 4 encapsuladoras/4 linhas de envase (8
     `centros_trabalho` novos, semeados nesta mesma migração) rodou UMA
     etapa específica. **Deliberadamente diferente** de
     `ordem_producao_agendamentos.centro_trabalho_id` (Fase 25): aquele é
     o recurso físico que a ORDEM INTEIRA usa para agendamento de
     capacidade (`UNIQUE` por ordem — um só centro de trabalho pela
     duração toda); este é por ETAPA, sem nenhum `UNIQUE`, porque a mesma
     ordem pode passar por máquinas diferentes em etapas diferentes. A
     lista de centros de trabalho no frontend passou a carregar para
     quem tem só `centros_trabalho.visualizar` (antes exigia também
     `producao.agendar`, que nem todo perfil que aponta etapa tem).
  3. `ordem_producao_apontamentos_diarios` (tabela nova) — log CORRIDO de
     produção do dia, pedido explícito do usuário ("produção do dia
     escrita pelo colaborador"). Deliberadamente **nunca** lido nem
     validado por `quantidade_produzida` (a reconciliação final, gravada
     uma única vez em "Concluir ordem") — existe só para o painel em
     tempo real mostrar o que está sendo produzido agora, sem esperar a
     ordem inteira terminar.
- (Entregue na Fase 85) Liberação do lote condicionada à NF-e de Entrada —
  antes desta fase, `lotes.nota_fiscal_entrada_id` (Fase 78) era só um
  vínculo opcional, nunca checado em lugar nenhum. Agora, com um novo
  singleton `configuracoes_qualidade` (`exigir_nota_fiscal_entrada_para_
  aprovar_lote`, padrão DESLIGADO — não quebra nenhum lote já em
  `aguardando_aprovacao` em instalações existentes), ligar essa exigência
  em Qualidade → Configuração de Qualidade faz `POST /lotes/<id>/aprovar`
  recusar (400) qualquer lote com `origem = 'recebimento'` que ainda não
  esteja vinculado a uma Nota Fiscal de Entrada lançada. **Detalhe
  importante:** a checagem é restrita a `origem = 'recebimento'` de
  propósito — um lote com `origem = 'producao'` (produto fabricado
  internamente, Fase 3) nunca teve nem terá uma NF-e de entrada, então
  nunca é bloqueado por esta trava; sem essa distinção, ligar a exigência
  travaria a aprovação de todo produto acabado da fábrica, o que não é o
  que foi pedido (o pedido é especificamente sobre matéria-prima recebida
  de fornecedor). `receber()` não muda — continua criando o lote em
  quarentena normalmente; a trava é só na hora de aprovar. Nova permissão
  `qualidade.configurar` (só Administrador por padrão, mesma régua de
  `fiscal.configurar`).
- (Entregue na Fase 86) Transportadora / Coleta (MVP) — não existia
  NENHUM conceito de transportadora/frete/coleta em lugar nenhum do
  sistema antes desta fase (confirmado por busca exaustiva no
  repositório). Escopo deliberadamente mínimo: cadastro de
  `transportadoras` (nome/CNPJ/telefone) e agendamento/confirmação/
  cancelamento de uma coleta (`pedido_venda_coletas`) contra um pedido de
  venda já `expedido` — sem rastreamento de entrega, sem integração com
  API de transportadora nenhuma, sem cálculo de frete (um projeto à parte
  se o cliente precisar disso depois). Nova permissão
  `comercial.gerenciar_coleta` (perfis Comercial e Estoque, quem já lida
  com a expedição física). **Marco técnico**: confirmar uma coleta é o
  PRIMEIRO uso real do Catálogo de Fluxo Configurável (Fase 81) para uma
  etapa `origem = 'sistema'` — `app/fluxo_service.py::marcar_concluida`
  marca a etapa "Coleta pela Transportadora" automaticamente no momento
  exato da confirmação, sem duplicar a lógica de negócio em dois lugares.
  Por causa disso, o card genérico "Etapas de Fluxo" (Fase 81) foi
  ajustado: uma etapa `origem = 'sistema'` nunca mostra botão manual de
  iniciar/concluir (nem no frontend, nem na API — `fluxo_service.
  iniciar_etapa`/`concluir_etapa` agora recusam com 400) — ela só existe
  para ser lida, nunca para ser operada manualmente por engano.
- (Entregue na Fase 87) Alerta de Estoque Mínimo — `itens.estoque_minimo`
  já existia no banco desde a Fase 2, mas era 100% inerte (só CRUD
  passthrough, nunca comparado contra nada). Novo helper
  `app/routes/estoque.py::saldo_total_disponivel_item` (mesma agregação
  que o MRP, Fase 39, já fazia lote a lote — extraída para ser
  reaproveitada em vez de duplicada; `aps.py::_calcular_mrp` foi
  atualizado para chamar essa mesma função) alimenta dois campos novos na
  resposta de `GET /itens`/`GET /itens/<id>`: `estoque_atual` e
  `abaixo_do_minimo` — calculados só para itens que TÊM um mínimo
  cadastrado (a maioria não tem, e o cálculo não é gratuito). Tela de
  Itens ganhou uma coluna "Estoque" com selo "Abaixo do mínimo"/"OK" por
  linha, mais um aviso agregado no topo quando algum item estiver abaixo.
  **Decisão confirmada com o usuário:** o valor é um número ABSOLUTO por
  item (ex.: B12 = 10g, amido de milho = 50kg), não uma porcentagem — os
  itens variam demais em escala/unidade para uma regra percentual única
  fazer sentido.
- (Entregue na Fase 88) Pré-checagem de Saldo ao Criar Pedido/OP — antes
  desta fase, o único jeito de saber se havia saldo suficiente era tentar
  confirmar/liberar de verdade e torcer para não dar erro. Dois novos
  endpoints, **só leitura, nunca reservam nada**: `GET /producao/ordens/
  <id>/disponibilidade` (extraído de `liberar()` via a nova função
  compartilhada `_verificar_disponibilidade_composicao` — chamada duas
  vezes, uma na pré-checagem e outra dentro do próprio `liberar()`, já
  que `_alocar_fefo_producao` sempre foi puramente leitura) e `GET
  /comercial/pedidos/<id>/pre-checagem-estoque` (mesma ideia, reaproveita
  `_alocar_fefo`). O frontend chama os dois de forma oportunista — na
  tela de uma Ordem de Produção 'planejada' e de um Pedido de Venda
  'rascunho' — e mostra um aviso amarelo/vermelho **não-bloqueante**
  quando o saldo parece insuficiente; o botão de liberar/confirmar
  continua sempre disponível, porque o saldo pode mudar até lá (chegada
  de matéria-prima, cancelamento de outro pedido) — o gate de verdade
  continua sendo só na hora de liberar/confirmar, exatamente como antes.
- (Entregue na Fase 89) Relatório "Últimas Compras por Item" — não
  existia nenhum relatório assim antes desta fase (o mais parecido,
  `custeio.custo_medio_item`, calcula uma MÉDIA ponderada entre todos os
  lotes recebidos, nunca mostra as compras individuais). Nova função
  `compras.py::_ultimas_compras_item` (junta `itens_pedido_compra` +
  `pedidos_compra` + `fornecedores`, ordenado por mais recente) exposta
  em `GET /compras/itens/<item_id>/ultimas-compras`. Usada no modal
  "Gerar pedido de compra" (a partir de uma sugestão do MRP): mostra o
  histórico e pré-preenche o preço unitário com a compra mais recente que
  tinha preço registrado — só um valor inicial, o usuário edita livremente
  antes de enviar.
- (Entregue na Fase 90) Painel Tempo Real redesenhado em Kanban/pipeline —
  fecha o projeto de 10 fases (81 a 90) iniciado a pedido do usuário para
  transformar o antigo painel (3 seções soltas por módulo: Produção,
  Comercial, Compras) num quadro único mostrando um pedido/matéria-prima
  atravessando de verdade todas as etapas do negócio, do PCP solicitando
  compra até a coleta pela transportadora. `app/routes/painel_tempo_real.py`
  foi reescrito do zero: em vez de 3 seções por módulo, 8 COLUNAS por
  ETAPA real (Aprovação Financeira pendente, Separação, Sugestões de
  Compra do PCP, Compras em andamento, Quarentena/CQ, Etapas de Produção,
  Abaixo do Estoque Mínimo, Expedido/Aguardando Coleta) — cada uma uma
  query pequena e AO VIVO contra as tabelas já existentes das Fases
  anteriores (nenhuma tabela nova, nenhum snapshot persistido, mesma
  filosofia desde a Fase 75), gated pela MESMA permissão que já controla
  a tela normal daquele módulo (nunca uma permissão nova "ver o painel
  inteiro" — um perfil estreito continua vendo só as colunas que já
  fazem sentido pra ele). A coluna "Separação" é o único uso do Catálogo
  de Fluxo Configurável (Fase 81) neste conjunto, com `LEFT JOIN` +
  `COALESCE` para mostrar corretamente um pedido confirmado que ninguém
  ainda visitou (a etapa só é materializada na primeira visita à tela do
  pedido — sem essa combinação, o painel ficaria incompleto até alguém
  abrir cada pedido manualmente). "Cara de Power BI" sem nenhuma
  biblioteca nova: barra de contagem por coluna em CSS puro, e um selo de
  "idade" do card (verde/amarelo/vermelho, reaproveitando as cores já
  existentes de `.selo`) calculado no FRONTEND a partir do timestamp que
  a API já devolve — nenhum cálculo de idade novo no backend. Continua
  sem WebSocket (polling a cada 8s, mesma decisão de sempre). **Detalhe
  de continuidade importante:** a coluna "Etapas de Produção" preservou a
  capacidade do painel original (Fase 75) de iniciar/concluir uma etapa
  direto pelo tablet do chão de fábrica, sem abrir o detalhe da ordem —
  mostra tanto a etapa já em andamento (com "Concluir") quanto a próxima
  da fila ainda não iniciada (com "Iniciar"), não só as já iniciadas.
- (Entregue na Fase 91) Solicitações de Materiais/EPI — busca de item
  cadastrado + notificação automática do setor de liberação. Dois ajustes
  de acompanhamento à Fase 80: (1) o campo "Itens" da tela de nova
  solicitação, que era uma caixa de texto livre no formato
  `codigo;quantidade;especificacao` (exigia decorar/copiar o código do
  Catálogo de Materiais/EPI), virou um campo de busca de verdade —
  digita parte do código ou da descrição, resultados aparecem na hora, um
  clique adiciona o item já ligado ao registro do catálogo a uma lista
  editável (quantidade/especificação por linha, com opção de remover) —
  só é possível solicitar material já cadastrado, exatamente o pedido
  original; (2) `POST /solicitacoes-material` agora chama
  `notificacoes_service.notificar_usuarios_com_permissao(modulo=
  "solicitacoes_material", acao="aprovar", ...)` assim que a solicitação é
  criada — a mesma notificação (painel de sino + tentativa de e-mail) já
  usada desde a Fase 61 para outras aprovações pendentes, agora avisando
  em tempo real quem pode liberar aquele pedido, sem precisar ficar
  checando a tela manualmente. Como a Fase 80 tinha deixado
  `solicitacoes_material.aprovar` sem NENHUM perfil padrão (só o
  Administrador aprovava, por ter todas as permissões), esta fase também
  cria o perfil padrão "Liberação de Materiais/EPI" (com
  `solicitacoes_material.visualizar` + `.aprovar`) para dar um dono
  imediato a essa responsabilidade — continua 100% reconfigurável pela
  tela de Perfis já existente (renomear, mover a permissão para outro
  perfil, adicionar/remover pessoas), exatamente o "deixar cadastrar qual
  setor aprova" pedido: a configuração é o próprio cadastro de Perfis, não
  uma tela nova.
- (Entregue na Fase 92) 2FA obrigatório por perfil — pedido do usuário por
  "máxima proteção"; o 2FA (TOTP, RFC 6238, compatível com Google/Microsoft
  Authenticator) já existia desde antes, mas era 100% opcional (cada
  usuário ativava por conta própria em "Minha Conta"). Nova coluna
  `perfis.exige_2fa` (`schema_fase92.sql`) torna essa exigência uma
  propriedade do PERFIL, não do usuário — assim, promover alguém a um
  perfil que exige 2FA já vale a partir do próximo login, sem migração de
  dado por pessoa. `seed.py::PERFIS_QUE_EXIGEM_2FA` liga por padrão para
  "Administrador" e "Financeiro" (recomendação aceita pelo usuário: as duas
  contas com mais poder no sistema — permissões e dinheiro). **Onde o
  bloqueio de verdade acontece:** `app/context.py::get_current_user` — o
  único ponto por onde toda rota autenticada passa — nega (403,
  `codigo=2fa_obrigatorio_pendente`) qualquer chamada de um usuário sem
  `dois_fatores_ativo` cujo perfil exija, EXCETO uma lista branca mínima
  (`/auth/me`, `/auth/logout`, `/auth/2fa/setup`, `/auth/2fa/confirmar`) —
  sem essa lista branca a pessoa ficaria trancada para sempre, sem conseguir
  nem chegar nas rotas que resolvem a própria pendência. O LOGIN em si
  continua liberando o token normalmente mesmo pendente (senão o token
  nunca existiria para chamar as rotas da lista branca); é o RESTO da API
  que fica bloqueado. No frontend, `chamarApi` (ponto único por onde toda
  chamada passa) reconhece esse código de erro e redireciona para uma tela
  cheia dedicada (`#/configurar-2fa-obrigatorio`, não um modal — não pode
  ter "x" para fechar) que já chama `/2fa/setup` e mostra o QR/chave na
  hora; isso cobre tanto quem acabou de logar quanto uma sessão JÁ ABERTA
  antes do perfil passar a exigir 2FA (o backend é sempre a fonte de
  verdade, nunca um cálculo feito só no momento do login). A tela de Perfis
  agora mostra um selo "exige 2FA" nos perfis marcados, para transparência.
- (Entregue na Fase 93) Número de versão visível + ícone novo do sistema —
  dois pedidos pequenos, entregues juntos. `GET /api/v1/saude` (rota sem
  autenticação, existia desde a Fase 1 só como healthcheck) agora devolve
  `versao` (`app/__init__.py::VERSAO_SISTEMA`, MESMO número de
  `installer/AlphafitusOS.iss::MyAppVersion` — uma fonte de verdade só, não
  duas). O frontend busca isso uma única vez ao carregar e mostra no rodapé
  do menu lateral ("v92.0") — dá pra confirmar visualmente, numa olhada, se
  uma instalação já recebeu a atualização mais recente, sem precisar abrir
  nenhum log. Convenção daqui pra frente: bumpar `VERSAO_SISTEMA` e
  `MyAppVersion` juntos a cada fase que for para produção. `installer/
  icone.ico` foi substituído pela nova identidade visual (fornecida pelo
  usuário) — como é a ÚNICA fonte de ícone usada tanto pelo PyInstaller
  (`alphafitus.spec`, ícone do .exe principal e do console de diagnóstico)
  quanto pelo Inno Setup (`SetupIconFile`/`UninstallDisplayIcon`), um
  rebuild propaga o ícone novo para o instalador, o .exe, o desinstalador
  e os atalhos (que apontam para o ícone do .exe, não embutem um próprio)
  de uma vez só.
