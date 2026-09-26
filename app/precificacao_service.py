"""
Fase 212 — Precificação: cálculo de rentabilidade e custo, dentro do
sistema, substituindo a planilha Excel "Precificação Clayton Eduardo
correto.xlsx" (aba "VARIANDO PREÇO" — a aba "MEIA" foi deixada de fora por
pedido explícito do usuário, 2026-09-26).

A empresa é tributada pelo Lucro Real (confirmado pelo usuário) — por isso
a alíquota combinada de IRPJ + Adicional de IRPJ + CSLL é um CAMPO editável
por cenário (`aliquota_irpj_csll_pct`, default 34%), nunca um número travado
no código: 34% é a soma de 15% (IRPJ) + 10% (adicional, incidente sobre o
lucro que ultrapassa a faixa isenta) + 9% (CSLL) — a mesma composição que já
estava, sem explicação, em TODAS as abas da planilha original. Manter isso
editável permite ao Financeiro ajustar se a alíquota efetiva real da empresa
for outra (ex.: em meses sem lucro suficiente pra entrar na faixa do
adicional).

MÉTODO (revisado e corrigido a partir da planilha original — ver a nota
grande abaixo sobre o erro real encontrado):

  1. `preco_1` ("preço mínimo"): o preço de venda que cobre o custo de
     produção MAIS todos os tributos/despesas que, no Brasil, incidem como
     percentual SOBRE O PREÇO DE VENDA (não sobre o custo) — ICMS, PIS,
     COFINS, análises laboratoriais, frete de venda, despesas fixas. A
     técnica de "markup por dentro" (dividir por 1 menos a soma dos
     percentuais, em vez de multiplicar) é a forma matematicamente correta
     de embutir um percentual-do-preço no próprio preço — é a mesma técnica
     que a planilha original já usava corretamente nesta linha, em TODAS as
     abas, sem erro.

  2. Dois modos de uso, escolhidos pelo usuário por cenário:

     - `markup`: o usuário informa a MARGEM LÍQUIDA desejada — quanto ele
       quer que sobre de verdade pra empresa, JÁ descontando comissão E
       IRPJ/CSLL (não uma margem bruta antes desses dois descontos, que foi
       a versão original da Fase 212 — mudada por pedido explícito do
       usuário na Fase 213: "quero ter a margem total não a bruta...
       aplicando todos os custos e descontando tudo, qual é o lucro limpo
       da empresa"). O sistema resolve algebricamente o preço de venda
       necessário pra chegar nessa margem líquida:

           lucro_final = (preco_final*(1-comissao) - preco_1) * (1-aliquota)
           margem_liquida_desejada = lucro_final / preco_final

       Isolando `preco_final`:

           preco_final = preco_1*(1-aliquota) / ((1-comissao)*(1-aliquota) - margem_liquida_desejada)

       Se `margem_liquida_desejada` for maior ou igual a
       `(1-comissao)*(1-aliquota)`, a margem pedida é matematicamente
       impossível (a comissão e o imposto sozinhos já comeriam tudo ou mais
       que isso) — validado em `validar_e_normalizar` com uma mensagem que
       mostra o teto real. (Este modo substitui o antigo "aplicar margem
       BRUTA sobre o preço-que-cobre-custo", que era o caminho "eu quero
       ganhar X% de markup, qual preço eu cobro?" — igual à aba "TABELA
       PRECIFICAÇÃO" da planilha original; esse número de markup continua
       calculado e devolvido como informação em `margem_bruta_pct`, só
       deixou de ser o que o usuário PREENCHE.)

     - `preco_fixo`: o usuário já tem um preço de venda (de mercado, de
       negociação) e quer saber a rentabilidade real dele — o caminho
       "reverso", que é exatamente o que a aba "VARIANDO PREÇO" da planilha
       original fazia. AQUI ESTAVA O ERRO REAL encontrado na planilha do
       usuário: pra descontar a comissão do preço final informado, a
       planilha original dividia por `(1 + comissão)`
       (`=preco_final/(1+comissao)`). Isso não bate com o resto da MESMA
       planilha: a comissão é sempre tratada como um percentual "por dentro"
       do preço de venda (a própria planilha calcula "COMISSÃO REAL" como
       `preco_final * comissao`, não como uma fração de `preco_final`
       dividido por algo) — e um percentual "por dentro" se desconta
       MULTIPLICANDO por `(1 - taxa)`, nunca dividindo por `(1 + taxa)`.
       Prova numérica com os dados reais da planilha (Cliente A):
       preço final R$ 27,90, comissão 5%.
         - Método da planilha original (ERRADO):
           preco_2 = 27,90 / 1,05 = 26,571 ; comissão "real" reportada
           separadamente = 27,90 * 0,05 = 1,395 ; soma = 27,966 ≠ 27,90.
           Ou seja, o próprio preço final informado não fecha com a soma de
           "quanto sobra pra empresa" + "quanto vai de comissão" — sobra
           R$ 0,066 por unidade que não existe em lugar nenhum.
         - Método corrigido (usado aqui): preco_2 = 27,90 * (1 - 0,05) =
           26,505 ; comissão real = 27,90 * 0,05 = 1,395 ; soma = 27,90 ✓.
       Esse erro inflava ligeiramente o "Lucro Final p/Produtor" mostrado na
       planilha (o valor líquido de comissão usado no cálculo do lucro era
       maior do que deveria) e, por consequência, também inflava um pouco o
       IRPJ/CSLL cobrado em cima dele (a base tributável ficava maior).
       Corrigido aqui pra sempre fechar exatamente com o preço final
       informado.

  3. `base_tributavel` = `preco_2 - preco_1` — o lucro bruto (já líquido de
     comissão, mas antes do IRPJ/CSLL) sobre o qual incide a alíquota
     combinada. `irpj_csll = base_tributavel * aliquota`. Isso é linear em
     `base_tributavel`, então funciona igual em cenário de prejuízo (base
     negativa vira uma "economia" de IRPJ/CSLL proporcional — modelagem
     simplificada e deliberada, assumindo que a empresa como um todo é
     lucrativa e compensa entre produtos; o mesmo pressuposto, implícito e
     não documentado, que a planilha original já usava).

  4. `lucro_final_produtor` = `base_tributavel - irpj_csll` — o que sobra de
     verdade pra empresa depois de tudo.

  5. Métricas por quantidade (pedido/lote inteiro): `valor_total_pedido`,
     `lucro_real_total`, `comissao_total`, e `lucro_hipotetico_total` (o
     lucro que a empresa teria SE NÃO pagasse IRPJ/CSLL — útil pra
     enxergar o tamanho da mordida do imposto). A planilha original só
     calculava essas duas últimas métricas pra 2 das 3 colunas de cada aba
     (a terceira ficava sempre em branco) — aqui elas sempre existem, pra
     qualquer cenário.

Nada aqui é guardado calculado — `calcular()` é chamada tanto pra uma
prévia sem salvar (`POST /precificacao/calcular`) quanto pra formatar
qualquer cenário já salvo na hora de exibi-lo (`GET`), igual o resto do
sistema já faz com custo/margem/saldo.
"""
from .context import ApiError


CAMPOS_PERCENTUAIS = (
    "icms_pct", "pis_pct", "cofins_pct", "analises_pct", "frete_pct", "despesas_fixas_pct", "comissao_pct",
)


def validar_e_normalizar(dados):
    """Valida os campos de entrada de um cenário e devolve um dict limpo,
    pronto pra `calcular()` ou pra persistir. Lança ApiError (400) com uma
    mensagem específica pra cada campo inválido — nunca deixa o cálculo
    rodar com dado incompleto/absurdo pra depois estourar uma divisão por
    zero mais adiante."""
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ApiError("Informe um nome pra esse cenário (ex.: 'Creatina sem sabor — Cliente Farma').", status=400)

    custo_producao = dados.get("custo_producao")
    if custo_producao is None or custo_producao < 0:
        raise ApiError("Informe o custo de produção (maior ou igual a zero).", status=400)

    modo = dados.get("modo") or "markup"
    if modo not in ("markup", "preco_fixo"):
        raise ApiError("Modo inválido — use 'markup' ou 'preco_fixo'.", status=400)

    normalizado = {
        "nome": nome,
        "item_id": dados.get("item_id"),
        "modo": modo,
        "custo_producao": float(custo_producao),
        "custo_origem": dados.get("custo_origem") or "manual",
        "aliquota_irpj_csll_pct": float(dados.get("aliquota_irpj_csll_pct") if dados.get("aliquota_irpj_csll_pct") is not None else 34),
        "quantidade": float(dados.get("quantidade") or 1),
        "observacoes": dados.get("observacoes"),
    }
    if normalizado["quantidade"] <= 0:
        raise ApiError("Quantidade deve ser maior que zero.", status=400)

    soma_percentuais = 0.0
    for campo in CAMPOS_PERCENTUAIS:
        valor = dados.get(campo)
        valor = float(valor) if valor is not None else 0.0
        if valor < 0 or valor >= 100:
            raise ApiError(f"'{campo}' deve estar entre 0 e 100.", status=400)
        normalizado[campo] = valor
        if campo != "comissao_pct":
            soma_percentuais += valor
    if soma_percentuais >= 100:
        raise ApiError(
            "A soma de ICMS + PIS + COFINS + Análises + Frete + Despesas Fixas não pode chegar a 100% — "
            "não sobraria preço nenhum pra cobrir o custo de produção.",
            status=400,
        )
    if normalizado["comissao_pct"] >= 100:
        raise ApiError("Comissão não pode ser 100% ou mais.", status=400)

    if modo == "markup":
        margem_liquida = dados.get("margem_liquida_desejada_pct")
        if margem_liquida is None:
            raise ApiError("No modo 'aplicar margem', informe a margem líquida desejada (%).", status=400)
        margem_liquida = float(margem_liquida)
        if margem_liquida < 0:
            raise ApiError("Margem líquida desejada não pode ser negativa.", status=400)
        teto = (1 - normalizado["comissao_pct"] / 100) * (1 - normalizado["aliquota_irpj_csll_pct"] / 100) * 100
        if margem_liquida >= teto:
            raise ApiError(
                f"Margem líquida de {margem_liquida:.2f}% é impossível com essa comissão ({normalizado['comissao_pct']}%) "
                f"e alíquota de IRPJ/CSLL ({normalizado['aliquota_irpj_csll_pct']}%) — o máximo que dá pra pedir aqui "
                f"é {teto:.2f}%.",
                status=400,
            )
        normalizado["margem_liquida_desejada_pct"] = margem_liquida
        normalizado["preco_venda_final"] = None
    else:
        preco_final = dados.get("preco_venda_final")
        if preco_final is None or preco_final <= 0:
            raise ApiError("No modo 'já tenho o preço', informe o preço de venda final (maior que zero).", status=400)
        normalizado["preco_venda_final"] = float(preco_final)
        normalizado["margem_liquida_desejada_pct"] = None

    return normalizado


def calcular(cenario):
    """Recebe um cenário já validado (`validar_e_normalizar`, ou uma linha
    do banco convertida em dict — mesmos nomes de campo) e devolve todos os
    valores derivados. Nunca lança exceção por conta própria pra dado já
    validado — os `raise` de divisão por zero/percentual absurdo já
    aconteceram na validação."""
    custo = cenario["custo_producao"]
    icms = cenario["icms_pct"] / 100
    pis = cenario["pis_pct"] / 100
    cofins = cenario["cofins_pct"] / 100
    analises = cenario["analises_pct"] / 100
    frete = cenario["frete_pct"] / 100
    despesas_fixas = cenario["despesas_fixas_pct"] / 100
    comissao = cenario["comissao_pct"] / 100
    aliquota_irpj_csll = cenario["aliquota_irpj_csll_pct"] / 100
    quantidade = cenario["quantidade"]

    soma_percentuais_venda = icms + pis + cofins + analises + frete + despesas_fixas
    preco_1 = custo / (1 - soma_percentuais_venda)

    if cenario["modo"] == "markup":
        # Fase 213 — o usuário informa a margem LÍQUIDA que quer (já
        # descontando comissão e IRPJ/CSLL); resolve-se `preco_final`
        # algebricamente (ver a dedução completa na docstring do módulo).
        margem_liquida_desejada = cenario["margem_liquida_desejada_pct"] / 100
        denominador = (1 - comissao) * (1 - aliquota_irpj_csll) - margem_liquida_desejada
        preco_final = preco_1 * (1 - aliquota_irpj_csll) / denominador
        preco_2 = preco_final * (1 - comissao)
        margem_bruta_pct_exibicao = round(((preco_2 / preco_1) - 1) * 100, 4) if preco_1 else None
    else:
        preco_final = cenario["preco_venda_final"]
        # Correção do erro real da planilha original (ver docstring do
        # módulo): comissão é "por dentro" do preço, então se desconta
        # MULTIPLICANDO por (1 - comissão), nunca dividindo por (1 + comissão).
        preco_2 = preco_final * (1 - comissao)
        margem_bruta_pct_exibicao = round(((preco_2 / preco_1) - 1) * 100, 4) if preco_1 else None

    comissao_real = preco_final * comissao
    base_tributavel = preco_2 - preco_1
    irpj_csll = base_tributavel * aliquota_irpj_csll
    lucro_final_produtor = base_tributavel - irpj_csll

    valor_total_pedido = preco_final * quantidade
    lucro_real_total = lucro_final_produtor * quantidade
    comissao_total = comissao_real * quantidade
    lucro_hipotetico_total = base_tributavel * quantidade

    return {
        "preco_1": round(preco_1, 4),
        "preco_2": round(preco_2, 4),
        "preco_final": round(preco_final, 4),
        "margem_bruta_pct": margem_bruta_pct_exibicao,
        "comissao_real": round(comissao_real, 4),
        "base_tributavel_irpj": round(base_tributavel, 4),
        "irpj_csll": round(irpj_csll, 4),
        "lucro_final_produtor": round(lucro_final_produtor, 4),
        "lucro_hipotetico_sem_irpj": round(base_tributavel, 4),
        "quantidade": quantidade,
        "valor_total_pedido": round(valor_total_pedido, 2),
        "lucro_real_total": round(lucro_real_total, 2),
        "comissao_total": round(comissao_total, 2),
        "lucro_hipotetico_total": round(lucro_hipotetico_total, 2),
        "margem_liquida_pct": round((lucro_final_produtor / preco_final) * 100, 4) if preco_final else None,
    }


def linha_para_cenario(row):
    """Converte uma linha da tabela `precificacoes` (sqlite3.Row) no mesmo
    formato de dict que `calcular()` espera — pra reaproveitar a MESMA
    função de cálculo tanto na prévia (sem salvar) quanto na leitura de um
    cenário já salvo."""
    d = dict(row)
    return d
