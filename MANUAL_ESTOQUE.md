# Módulo Estoque (WMS)

O módulo **Estoque** é acessado pelo menu lateral, no grupo **Estoque**, opção **Estoque (WMS)**. É nele que você cadastra as posições de armazenagem (as "gavetas"/endereços físicos do depósito), endereça os lotes recém-aprovados pela Qualidade, transfere e ajusta saldo, dá baixa em material, faz contagens de inventário e consulta a sugestão de separação por FEFO.

A tela é organizada em cartões, de cima para baixo: **Contagem de Inventário**, **Agendamento de Contagens**, **Lotes pendentes de endereçamento**, **Posições de armazenagem**, **Saldo em estoque** e **Sugestão FEFO**.

> **Atenção:** todo saldo mostrado na tela é sempre recalculado a partir do histórico completo de movimentações — não existe um "número guardado" que possa ficar dessincronizado. Por isso você nunca vai encontrar um botão para "corrigir o saldo direto"; toda correção passa por um Ajuste (com motivo obrigatório) ou por uma Contagem de Inventário concluída.

## Cadastrar uma posição de estoque

Uma posição é o endereço físico (prateleira, rua, box) dentro de um depósito onde o material fica fisicamente guardado. Antes de cadastrar posições, é preciso ter pelo menos um depósito cadastrado no menu **Empresas** (unidade do tipo "Depósito") — se não houver nenhum, o botão de nova posição fica desabilitado com o aviso "Cadastre um depósito em Empresas primeiro".

1. Abra o menu **Estoque** e localize o cartão **Posições de armazenagem**.
2. Clique no botão **+ Nova posição**.
3. No campo **Depósito**, selecione a unidade onde essa posição fica fisicamente.
4. Preencha o campo **Código** com o identificador da posição (exemplo: `A1-01`).
5. Preencha o campo **Descrição**, se quiser detalhar o local (opcional).
6. Clique em **Criar**.

A posição criada aparece na tabela do cartão com o selo **ativa**. Só posições com status **ativa** ficam disponíveis para endereçar lotes, transferir ou registrar itens de contagem cíclica.

## Endereçar um lote recebido

Um lote só aparece disponível para endereçamento depois de já ter sido **aprovado pela Qualidade**. Enquanto isso não acontece, ou enquanto ainda restar quantidade não alocada a nenhuma posição, ele aparece no cartão **Lotes pendentes de endereçamento**.

1. Abra o menu **Estoque** e localize o cartão **Lotes pendentes de endereçamento**.
2. Localize o lote desejado na tabela — a coluna **Pendente** mostra quanto ainda falta endereçar.
3. Clique no botão **Endereçar**, na linha do lote.
4. No campo **Posição**, escolha a posição física onde o material será guardado.
5. No campo **Quantidade**, informe quanto será endereçado ali (o campo já vem preenchido com o total pendente; edite se for endereçar só parte para dividir o lote entre mais de uma posição).
6. Clique em **Endereçar**.

Depois de endereçado, o lote passa a aparecer no cartão **Saldo em estoque (por lote e posição)**, já vinculado à posição escolhida.

> **Atenção:** o campo Quantidade nunca aceita um valor maior do que o pendente do lote — o sistema já desconta automaticamente o que foi consumido em produção e o que já foi endereçado em outras posições, então não é possível "endereçar duas vezes" a mesma quantidade por engano.

## Transferir, ajustar e dar baixa em estoque

No cartão **Saldo em estoque (por lote e posição)**, cada linha (combinação de lote + posição) tem até três botões, conforme sua permissão:

- **Transferir**: move parte ou todo o saldo de uma posição para outra, dentro do mesmo lote. Escolha a **Posição de destino** e a **Quantidade** (não pode passar do saldo disponível na origem).
- **Ajustar**: corrige o saldo de forma pontual, sem passar por um processo de contagem. Informe a **Quantidade do ajuste (+/-)** — valor negativo reduz, positivo aumenta — e o **Motivo**, que é obrigatório e fica registrado na auditoria.
- **Baixa**: retira material do estoque de forma definitiva (descarte, perda, consumo fora do fluxo normal), também com **Motivo** obrigatório.

> **Atenção:** use o botão **Ajustar** apenas para correções pontuais e justificadas. Para conferir fisicamente todo um depósito (ou uma prateleira) e corrigir o saldo de forma auditável, prefira sempre uma **Contagem de Inventário** (próxima seção) — é o mesmo mecanismo de ajuste por trás, mas com registro formal de "o que o sistema esperava" e "o que foi contado".

## Reserva real de material entre módulos

O saldo de um lote mostrado no Estoque, na sugestão de FEFO e no que a Produção pode consumir considera automaticamente o que **já está comprometido** em outro módulo — não é preciso fazer nada manualmente para isso funcionar. Na prática:

- Se um pedido de venda já **confirmado** reservou um lote, esse material some do saldo disponível para separação em Estoque e para consumo em Produção.
- Se uma ordem de produção já **liberada** reservou um lote (via FEFO, no momento em que ela é liberada), esse material também não aparece mais disponível para venda nem para outra ordem de produção.
- Se não houver saldo real suficiente na liberação de uma ordem de produção, a liberação é recusada com uma mensagem explicando o que está faltando — a ordem não avança "no otimismo" para só descobrir a falta depois.

Isso evita que dois módulos (Comercial e Produção) — ou duas ordens de produção liberadas em sequência — disputem e "gastem" o mesmo lote sem que um saiba da existência do outro.

## Sugestão de separação por FEFO

O cartão **Sugestão FEFO (primeiro a vencer, primeiro a sair)** ajuda a decidir de qual lote separar material quando há mais de um lote aprovado do mesmo item em estoque.

1. No cartão **Sugestão FEFO**, selecione o **Item** desejado.
2. Informe a **Quantidade necessária**.
3. Clique em **Consultar**.

O sistema lista os lotes aprovados do item, ordenados pela validade mais próxima primeiro (lotes sem validade cadastrada entram por último), e sugere quanto separar de cada um até completar a quantidade pedida. A tabela de resultado mostra **Lote**, **Validade**, **Saldo disponível** e **Sugerido para separar**, além de indicar se a quantidade pedida foi atendida totalmente ou só parcialmente.

> **Atenção:** um lote **vencido** nunca entra nessa sugestão, mesmo que esteja aprovado e tenha saldo físico positivo — para retirá-lo do estoque, é preciso dar baixa nele. O saldo considerado também já desconta o que outros módulos reservaram (ver seção anterior), então a sugestão reflete o que está realmente livre para separar.

## Fazer uma contagem de inventário (cíclica ou geral)

A contagem de inventário é o processo formal de conferência física do estoque, disponível para quem tem a permissão de **contagem**. Existem dois tipos:

- **Geral**: ao ser criada, já traz automaticamente todos os pares lote + posição com saldo positivo naquele depósito — use para "conferir tudo".
- **Cíclica**: nasce vazia; você adiciona os itens (lote + posição) um a um — use para "conferir só esta prateleira/setor hoje".

### Iniciar a contagem

1. No cartão **Contagem de Inventário**, clique em **+ Nova contagem**.
2. Selecione o **Depósito** a ser contado.
3. Escolha o **Tipo**: **Geral** ou **Cíclica**.
4. Preencha a **Observação**, se quiser (opcional).
5. Clique em **Iniciar contagem**.

### Adicionar itens (somente contagem cíclica)

Se a contagem for do tipo Cíclica, abra o detalhe dela (botão **Ver detalhe** na linha da contagem) e, no formulário exibido no rodapé:

1. Informe o **ID do lote** (visível na tela Lotes/Qualidade ou na coluna "Lote" do cartão Saldo em Estoque).
2. Selecione a **Posição** onde esse lote está fisicamente.
3. Clique em **+ Adicionar item**.

### Registrar o que foi contado

Para cada item da lista (com status **Pendente**), clique no botão **Contar** (ou **Recontar**, se já tiver sido contado antes):

1. Confira o texto "O sistema espera **X** nesta posição".
2. Informe a **Quantidade contada** com o valor fisicamente encontrado.
3. Clique em **Registrar**.

### Concluir a contagem

Só é possível concluir depois que **todos** os itens estiverem com status **Contado** — o botão **Concluir contagem** fica desabilitado enquanto houver item pendente. Ao clicar em **Concluir contagem**, o sistema gera automaticamente um ajuste de estoque em cada item onde a quantidade contada foi diferente do saldo do sistema; itens sem divergência não geram nenhum lançamento.

Se preferir encerrar sem aplicar nada, use **Cancelar contagem** (exige um **Motivo**) — isso não gera nenhum ajuste, mesmo que já haja itens contados.

> **Atenção:** concluir uma contagem exige a mesma permissão do ajuste manual avulso, porque é o momento em que o sistema efetivamente altera o saldo de estoque. É possível uma pessoa conduzir a contagem inteira (contar todos os itens) sem ter permissão para concluí-la sozinha — nesse caso, outra pessoa com a permissão adequada precisa abrir a contagem e clicar em Concluir.

## Divergência de contagem e aprovação de um segundo usuário

Nem toda divergência encontrada numa contagem vira ajuste automaticamente na hora de concluir. Existem dois gatilhos independentes que classificam uma divergência como **grande**; encontrando qualquer um deles, o item **não é ajustado sozinho**:

1. **Por percentual**: a diferença entre o contado e o saldo do sistema ultrapassa o **limiar percentual** configurado (o valor padrão de fábrica é 20%, mas pode ter sido alterado — veja a seção seguinte). Se o saldo do sistema no início da contagem era **zero** e a contagem física encontrou alguma quantidade, isso **sempre** conta como divergência grande, independentemente do percentual.
2. **Por valor financeiro** (se esse gatilho estiver ligado): o valor estimado do ajuste — diferença de quantidade multiplicada pelo custo unitário do lote — ultrapassa o **limiar em R$** configurado. Quando o custo do lote não é conhecido (não foi informado no recebimento e não há outros lotes do mesmo item para calcular uma média), o sistema **sempre** trata como divergência grande por segurança, mesmo que o percentual seja pequeno.

Quando um item cai numa dessas situações, ele fica com o selo **Aguardando aprovação** (mostrando o percentual de divergência e, se aplicável, o valor estimado do ajuste em R$) no detalhe da contagem, e só é liberado quando um **segundo usuário**, diferente de quem contou o item, decidir:

- **Aprovar**: aplica o ajuste ao estoque exatamente como calculado.
- **Rejeitar**: exige um **Motivo** e **não altera** nenhum saldo — a divergência fica registrada para investigação posterior, sem "corrigir" o estoque às cegas.

Enquanto houver qualquer item pendente de aprovação em qualquer contagem, o cartão **Contagem de Inventário** mostra o aviso "*N* ajuste(s) de contagem com divergência grande aguardando aprovação". Quem tem a permissão de aprovar também recebe uma notificação do sistema quando uma contagem gera pendências.

> **Atenção:** quem contou o item **não pode** ser quem aprova (ou rejeita) o ajuste dele, mesmo que tenha a permissão — o sistema bloqueia essa combinação. Essa segregação existe para que a mesma pessoa não possa "contar errado de propósito" e depois se autoaprovar; a divergência precisa ser confirmada por um segundo par de olhos antes de mexer no saldo oficial de estoque.

## Configurar o limiar de divergência e a alçada por valor

Os dois gatilhos da seção anterior são configuráveis, sem precisar alterar o sistema — apenas por quem tem a permissão específica para isso (por padrão, só o perfil Administrador).

1. No cartão **Contagem de Inventário**, clique em **Configurar limiar**.
2. No campo **Limiar por percentual (%)**, informe o percentual acima do qual uma divergência é considerada grande (por exemplo, `20` para 20%).
3. No campo **Limiar por valor do ajuste (R$, 0 = desligado)**, informe o valor em reais acima do qual o ajuste também exige segunda aprovação, mesmo com percentual baixo. Deixe em `0` para desligar esse segundo gatilho — nesse caso, só o percentual decide.
4. Clique em **Salvar**.

A tela mostra sempre o texto de ajuda do cartão de Contagem de Inventário com o percentual **real** configurado no momento (não um número fixo), e a data da última alteração aparece no próprio formulário.

> **Atenção:** qualquer pessoa que já enxergue o módulo Estoque consegue **ver** os limiares atuais (não é uma informação sensível) — só **alterá-los** exige a permissão de configuração. Mudar essa régua é uma decisão de controle interno, não uma operação do dia a dia, por isso fica restrita por padrão ao Administrador.

## Agendamento e cadência automática de contagens

Em vez de depender de alguém lembrar de clicar em "+ Nova contagem", é possível cadastrar uma regra que gera a contagem sozinha quando chega o dia certo. Cadastrar, editar ou excluir uma regra exige a permissão específica de agendamento (por padrão, só o Administrador); ver a lista de regras já cadastradas é liberado a qualquer pessoa que já veja o módulo Estoque.

1. No cartão **Agendamento de Contagens**, clique em **+ Novo agendamento**.
2. Selecione o **Depósito** que será contado.
3. Escolha o **Tipo de contagem**: **Geral** (todos os pares lote + posição com saldo) ou **Cíclica** (sorteia uma amostra aleatória a cada geração).
4. Se escolheu Cíclica, preencha **Amostra (% dos itens)** com o percentual das combinações lote + posição que serão sorteadas a cada vez (por exemplo, `10` para sortear 10%).
5. Escolha a **Cadência**:
   - **Diária** — gera todos os dias;
   - **Semanal** — gera uma vez por semana; escolha o **Dia da semana**;
   - **Mensal** — gera uma vez por mês; escolha o **Dia do mês** (se o mês não tiver esse dia, o sistema usa o último dia do mês).
6. Preencha a **Observação**, se quiser (opcional).
7. Clique em **Salvar**.

A regra aparece na tabela do cartão com Depósito, Tipo, Cadência, Status (ativo/inativo) e a data da **Última geração**. Uma contagem gerada por agendamento aparece na lista de contagens com o selo **Agendamento** na coluna Origem (em vez de "Manual"), deixando claro de onde ela veio.

> **Atenção:** este agendamento não é um processo rodando sozinho em segundo plano o tempo todo — a verificação acontece **sempre que alguém com permissão de contagem abre a tela Estoque**. Ou seja, "automático" aqui significa "gerado na hora certa, assim que alguém abrir o Estoque naquele dia"; se ninguém abrir o módulo no dia agendado, a contagem nasce sozinha na próxima vez que alguém entrar na tela, não exatamente no relógio.

Excluir uma regra de agendamento nunca apaga nem desvincula as contagens que ela já gerou no passado — elas continuam existindo normalmente, só deixam de ter uma regra ativa associada.
