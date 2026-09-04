"""
Fase 147 — Gerador de Contratos: texto PADRÃO do "Contrato de
Industrialização de Produtos Nutracêuticos por Encomenda", copiado
VERBATIM do modelo real que o usuário enviou (arquivo "CONTRATO PADRAO
ALPHAFITUS 1.docx", 2026-09-03) — nenhuma cláusula foi reescrita ou
resumida, só formatada com a convenção abaixo pra virar texto editável
em `contratos.texto_clausulas`.

Convenção de marcação (texto puro, pensado pra ficar editável numa
caixa de texto simples na tela, sem precisar de um editor rico):
  - Linha começando com "# "  → título principal do documento.
  - Linha começando com "## " → cabeçalho de seção (I – OBJETO, etc.).
  - `{{CONTRATANTE_BLOCO}}`   → substituído na hora de gerar o PDF pelos
    dados do cliente (razão social/CNPJ/endereço/representante), puxados
    do projeto de Terceirização vinculado — nunca digitados de novo.
  - `{{DATA_CONTRATO}}`, `{{REPRESENTANTE_CONTRATANTE}}` → idem, também
    resolvidos na hora de montar o PDF.

O endereço da CONTRATADA usado abaixo divergia do endereço do papel
timbrado que o usuário tinha mostrado antes ("Rua Cel. Marcos Rovaris,
1574, Primeiro de Maio") — mesmo CNPJ nos dois. Usuário confirmou em
2026-09-03 o endereço correto/atual, com CEP: Rua Agenor Martinho Lima,
nº 41, Bairro Nossa Senhora de Fátima, Içara/SC, CEP 88823-290.
`app/pdf_marca.py::DADOS_EMPRESA_CONTRATO` (timbre) usa o mesmo.
"""

TEXTO_PADRAO_CONTRATO = """# CONTRATO DE INDUSTRIALIZAÇÃO DE PRODUTOS NUTRACÊUTICOS POR ENCOMENDA

Pelo presente instrumento particular, celebrando entre as partes, a saber:

CONTRATADA: ALPHAFITUS LABORATÓRIO NUTRACÊUTICO LTDA, empresa estabelecida à Rua Agenor Martinho Lima, nº 41, Bairro Nossa Senhora de Fátima, Içara/SC, CEP 88823-290, inscrita no CNPJ sob o n° 01.481.057/0001-12 neste ato devidamente representado pela Sr. CLAYTON BORGES DA SILVA, inscrito no CPF sob n° 008.467.509-88.

{{CONTRATANTE_BLOCO}}

A CONTRATANTE e a CONTRATADA têm entre si justo e acertado, o presente CONTRATO DE INDUSTRIALIZAÇÃO DE PRODUTOS NUTRACÊUTICOS POR ENCOMENDA, WHITE LABEL ficando desde já aceito que se regerá pelas seguintes cláusulas e condições:

## I – OBJETO

1ª – A CONTRATANTE, por intermédio do presente instrumento, contrata os serviços especializados da CONTRATADA na área da industrialização, preparação, confecção e tudo que envolve o processo produção dos produtos segundo especificações e encomendas da CONTRATANTE.

Parágrafo Único – A CONTRATADA se compromete a fornecer os produtos por ela produzidos, em volume, qualidade, prazo (60) dias úteis, contados da aprovação das etapas constantes na cláusula 5ª e disposições previstas pela CONTRATANTE, em pedidos específicos.

## II – DO PROCESSO E NORMAS DE PRODUÇÃO

2ª – A industrialização dos produtos será realizada com atendimento das normas do processo produtivo em vigência com a ANVISA, com matérias primas de qualidade, especificados em manual técnico, instruções ou especificações.

3ª - Na execução do processo a CONTRATADA seguirá as normas de segurança, ambientais e de natureza técnica, inerentes ao processo de produção.

4ª – Os serviços contratados serão prestados com orientação e responsabilidade técnica da CONTRATADA, no estabelecimento da CONTRATADA, em conformidade com os cronogramas de execução dos serviços, estabelecido de comum acordo entre as partes contratantes, devendo sempre ser respeitado os prazos estipulados entre as partes.

5ª – Para cada linha de produtos a ser industrializada exclusivamente para a CONTRATANTE, compreendendo produtos fabricados com a marca, identidade visual e layout próprios da CONTRATANTE, deverão ser observadas e seguidas as etapas do respectivo processo produtivo:

Aprovação das fórmulas, sejam as já existentes ou as exclusivas para a CONTRATANTE, estas devem expressamente estar dentro das normas da ANVISA (IN 28/2018);

Aprovação dos rótulos com a criação das artes devendo sempre conter as especificações conforme legislação vigente;

Aprovação dos frascos PET e tampas, com as cores e modelos que a CONTRATADA fornece para escolhas. (cores disponíveis no checklist de aprovação todas com selo de indução);

Após aprovação de todas as etapas acima, essas serão colocadas em linha de produção, conforme ordem cronológica da CONTRATADA, tendo como prazo máximo de entrega 45 (quarenta e cinco) dias úteis após aprovação final do rotulo pela contratante.

## III – PEDIDOS MÍNIMOS PARA CADA APRESENTAÇÃO (SKUs)

6ª – Fica acordado entre as partes que cada produto, apresentação ou SKU solicitado pela CONTRATANTE estará sujeito às condições mínimas de produção, quantidades, especificações técnicas, requisitos regulatórios e demais condições comerciais previamente negociadas e aprovadas entre as partes.

Parágrafo Primeiro – As condições específicas de cada SKU, incluindo, mas não se limitando a descrição do produto, composição, apresentação, quantidade a ser produzida, preço unitário, custos regulatórios, materiais de embalagem, excedentes de rótulos e demais particularidades, serão formalizadas por meio de Pedido de Compra, Proposta Comercial, Anexo Contratual ou outro documento escrito aceito por ambas as partes.

Parágrafo Segundo – A inclusão de novos SKUs, bem como alterações em produtos já contratados, não implicará necessidade de aditamento deste instrumento, desde que as respectivas condições sejam formalizadas nos documentos previstos no parágrafo anterior.

Parágrafo Terceiro – Os pedidos serão produzidos de acordo com a capacidade operacional da CONTRATADA e com as condições comerciais previamente acordadas entre as partes para cada SKU.

## CLÁUSULA - ESTABILIDADE E PRODUÇÃO

Estabilidade: A produção do item especificado neste contrato deverá ter sua estabilizada concluída.

Laboratório Próprio: O Contratado dispõe de um laboratório próprio para a fazer sua estabilidade, o que permitirá a redução de custos para parceiros envolvidos na fabricação. As partes concordam que o uso do laboratório próprio contribuirá para a diminuição dos custos de produção para os parceiros.

Notificação e Registro: A partir da data estabelecida, todos os processos relacionados ao item deverão ser formalmente notificados e registrados. A notificação deverá ser feita em formato de Notificação, conforme as diretrizes e regulamentações aplicáveis, garantindo a conformidade e a transparência no acompanhamento da produção e demais processos relacionados.

Parágrafo Único: O valor associado à notificação será determinado e acordado entre a indústria produtora e o Contratado, de acordo com as condições e custos aplicáveis conforme parágrafo único do inciso 3.

## IV – DOS FRASCOS OU POTES PET, TAMPAS E CLICHÊS

7º – Os frascos(potes), tampas, sílicas e rótulos serão fornecidos pela CONTRATADA conforme modelo e especificações previamente aprovados por ambas as partes, também ficará responsável pelo fornecimento da matéria prima bem como pela execução do envase, fechamento e acondicionamento final dos produtos.

## V – DO PRAZO DE ENTREGA DO PRODUTO ACABADO

9ª - Esse prazo para entrega começa a correr após a aprovação dos itens constantes do artigo 5ª, ou seja, depois de ter toda suas etapas aprovadas, cada apresentação terá sua entrega em até 45 (quarenta e cinco) dias úteis.

## VI – CONDIÇÕES DO PAGAMENTO

10ª – A CONTRATANTE efetuará o pagamento dos pedidos de acordo com as condições comerciais estabelecidas no Anexo I – Produtos e Condições Comerciais, que integra este contrato para todos os fins de direito.

Parágrafo Primeiro – Salvo disposição diversa constante no Anexo I ou em documento comercial específico firmado entre as partes, o pagamento será realizado da seguinte forma:

a) 50% (cinquenta por cento) do valor total do pedido na aprovação do orçamento e/ou assinatura do pedido de fabricação;

b) 50% (cinquenta por cento) do valor total do pedido no faturamento dos produtos.

Parágrafo Segundo – Os pagamentos destinados à CONTRATADA deverão ser efetuados por transferência bancária, PIX ou outro meio acordado entre as partes, em conta de titularidade da Alphafitus Laboratório Nutracêutico LTDA.

Parágrafo Terceiro – Os valores dos produtos, custos regulatórios, notificações, materiais de embalagem, serviços adicionais e demais condições comerciais aplicáveis a cada SKU constarão do Anexo I ou de documento comercial específico aprovado entre as partes.

Parágrafo Único – Após a assinatura do presente contrato, a CONTRATANTE ficará sujeita à análise e aprovação financeira e cadastral pela CONTRATADA, a qual poderá, a seu exclusivo critério, validar, manter, alterar, restringir ou até recusar as condições de pagamento inicialmente ajustadas, sempre que forem identificadas inconsistências cadastrais, restrições de crédito, risco de inadimplência ou qualquer outra circunstância que comprometa a segurança financeira da operação. A emissão dos boletos, bem como a continuidade da produção, ficará condicionada à referida aprovação financeira. A CONTRATANTE deverá emitir e encaminhar à CONTRATADA a competente Nota Fiscal de Remessa para Industrialização, relativa às embalagens, insumos e demais materiais de sua responsabilidade, observando-se que o envio desses materiais somente poderá ocorrer após a aprovação prévia da documentação fiscal pela CONTRATADA e mediante agendamento prévio de data e horário para recebimento, não sendo admitido, em nenhuma hipótese, o recebimento de materiais enviados sem agendamento prévio. Fica ainda expressamente ajustado que qualquer atraso no pagamento de quaisquer boletos ensejará a constituição imediata em mora da CONTRATANTE, independentemente de aviso ou notificação prévia, autorizando a suspensão da produção, retenção de mercadorias, protesto dos títulos, negativação junto aos órgãos de proteção ao crédito, cobrança extrajudicial e judicial, além da incidência dos encargos legais e contratuais cabíveis, incluindo multa, juros de mora, correção monetária, custas processuais e honorários advocatícios, sem prejuízo das demais medidas previstas em lei e neste contrato.

## VII – NOTIFICAÇÃO NA VIGILÂNCIA SANITÁRIA/ANVISA

11º - Toda documentação/notificação será feita pela CONTRATADA.

## VIII – DA POLÍTICA DE TROCA DE MERCADORIAS

12ª - Por se tratar de terceirização a responsabilidade de comercialização é da CONTRATANTE não se aplicando nenhuma troca de produtos, após 48 (quarenta e oito) horas do recebimento da mercadoria pela CONTRATANTE.

Parágrafo Único - Apenas produtos que apresentarem algum problema de fabricação ou que foram avariados durante o transporte serão trocados.

## IX – DA EXCLUSIVIDADE DE PRODUÇÃO

13ª – Fica ajustado entre as partes que a CONTRATADA terá exclusividade para fabricar os produtos da CONTRATANTE até a finalização total dos rótulos ou itens adquiridos especialmente para a contratante, salvo para os produtos em que a CONTRATADA não tenha capacidade técnica ou equipamentos adequados para produção.

## X – DAS ENTREGAS E FRETE

14ª – Fica acordado entre as partes que o frete será por conta da CONTRATANTE.

Parágrafo Primeiro – A CONTRATANTE também poderá optar por retirar seus pedidos diretamente no depósito da CONTRATADA.

## XI – PRAZO DE VIGÊNCIA E HIPÓTESES DE RESCISÃO

15ª O presente contrato vigorará por pelo prazo determinado de 12 (doze) meses, contados a partir da sua assinatura, sendo renovado automaticamente, por igual período no silêncio das partes.

16ª Este contrato poderá ser rescindido por falta de pagamentos da CONTRATANTE à CONTRATADA, ou por descumprimento das cláusulas contratuais por qualquer das partes.

17ª Após os primeiros 06 (seis) meses, poderá ocorrer a resilição do contrato por qualquer das partes, sem que haja multa, bastando para tanto que a parte desistente comunique sua intenção, de forma expressa e com 60 (sessenta) dias de antecedência.

Parágrafo Único - Sendo a CONTRATANTE a responsável pela extinção do contrato, esta será responsável por adquirir da CONTRATADA o estoque de rótulos e excedentes de itens oriundos para sua produção em estoque pelo preço constante na nota fiscal de compra.

## XIII – DISPOSIÇÕES FINAIS

18ª – Qualquer omissão ou tolerância em exigir o estrito cumprimento de quaisquer termos ou condições deste contrato, ou em exercer direito dele decorrente, não constituirá renúncia a ele se não prejudicará assim, a faculdade de qualquer das partes em exigi-los ou exercê-los a qualquer tempo.

19ª - A celebração do presente não implica em nenhuma espécie de sociedade, associação, solidariedade obrigacional, nem em qualquer responsabilidade direta ou indireta, seja societária, comercial, tributária, trabalhista, previdenciárias ou de qualquer outra natureza, nem em alienação ou sucessão, seja entre as partes, seus empregados ou prepostos, seja perante terceiros, estando preservada a autonomia jurídica e funcional de cada uma das partes.

## XIV – FORO DO CONTRATO

20ª – As partes elegem o foro da Comarca de Içara/SC, como único e competente, para reconhecer e dirimir quaisquer questões oriundas do presente contrato, como expressas renúncia de qualquer outro foro, por mais privilegiado que seja.

E por estarem justos e contratados, firmam o presente contrato em 2 (duas) vias de igual teor e forma, na presença de 2 (duas) testemunhas.

Içara/SC, {{DATA_CONTRATO}}.

Contratante: ___________________________________________________
{{REPRESENTANTE_CONTRATANTE}}

Contratada: ___________________________________________________
ALPHAFITUS LABORATÓRIO NUTRACÊUTICO LTDA"""
