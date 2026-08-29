"""
Formatação fiel dos campos estruturados do Memorial Técnico no "PDF
Completo" (Fase 43).

Bug relatado pelo usuário, com print comparando o PDF gerado pelo
AlphafitusOS com um PDF do sistema original: os editores estruturados da
Fase 116 (Cálculos Nutricionais, Composição Centesimal, Ensaios
Microbiológicos, os 8 seletores de catálogo — Advertências, Armazenamento,
Modo de Uso, Alegações, Legislação Aplicável, Metodologias Aplicadas,
Justificativas Técnicas, Conclusão) trocaram o CONTEÚDO de vários campos
de texto livre para JSON estruturado — mas o gerador de PDF (Fase 43)
nunca foi atualizado: continuava jogando o valor bruto do banco direto num
`Paragraph()`, então pra esses campos o PDF saía com o JSON cru impresso.

Este módulo é o "espelho em Python" das funções de parse/formatação já
existentes em `frontend/static/app.js` (parseCalcNutricionais,
calcularNutriente, parseComposicaoCentesimal, calcularCentesimaisAjustadas,
parseEnsaiosMicrobiologicos, CONFIG_SELETORES_CATALOGO) — cada função
abaixo replica a fórmula/formato exatos do lado JS, pra nunca existir
divergência entre o que a TELA mostra e o que o PDF imprime. Qualquer
mudança de fórmula/formato num dos dois lados precisa ser replicada no
outro (mesmo cuidado de sincronização já documentado noutros pontos do
sistema, ex. `_ROTULOS_TIPO_ITEM` em `relatorios.py`).

Cada função `formatar_*` devolve `None` quando o valor não bate com o
formato estruturado esperado (dado legado/texto livre de antes desses
campos existirem) — nesse caso o chamador (`memorial_anexos.py`) cai de
volta no comportamento antigo (texto livre), nunca quebra o PDF. Toda
função de parse é tolerante a falha: JSON inválido, chave ausente ou tipo
errado nunca derruba a geração do PDF.
"""
import json
import math
import os

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

_ESTILOS = getSampleStyleSheet()

# Fase 122 — o sistema original imprime em serifada ('Lora', Georgia,
# 'Times New Roman', serif — nessa ordem de fallback, ver a folha de
# estilo de impressão original). Não redistribuímos nenhuma fonte dentro
# do instalador — em vez disso, lê a Georgia que o PRÓPRIO Windows já traz
# de fábrica (`C:\Windows\Fonts`), a mesma máquina onde o AlphafitusOS
# roda; se não achar (ex.: uma instalação Windows sem essa fonte), cai
# pra "Times-Roman"/"Times-Bold" — fonte padrão embutida no próprio
# reportlab/PDF, sem precisar de arquivo nenhum, e que é literalmente o
# 3º nível de fallback que o CSS original já usa. Nunca falha, nunca
# baixa nada da internet.
def _registrar_fonte_serifada():
    pasta_fontes = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    try:
        pdfmetrics.registerFont(TTFont("Georgia", os.path.join(pasta_fontes, "georgia.ttf")))
        pdfmetrics.registerFont(TTFont("Georgia-Bold", os.path.join(pasta_fontes, "georgiab.ttf")))
        return "Georgia", "Georgia-Bold"
    except Exception:
        return "Times-Roman", "Times-Bold"


FONTE_CORPO, FONTE_CORPO_NEGRITO = _registrar_fonte_serifada()

# Mesma paleta já usada nos outros PDFs do sistema (Painel Gerencial, CoA)
# — ver `relatorios.py`/`memorial_anexos.py` — para o Memorial não
# destoar visualmente do resto dos exports.
_COR_SECAO = colors.HexColor("#1f3a5f")
_COR_SUAVE = colors.HexColor("#5a6472")
_COR_BORDA = colors.HexColor("#dbe1e8")
_COR_CABECALHO_TABELA = colors.HexColor("#eef2f7")

_ESTILO_CORPO = ParagraphStyle("CorpoCampoMemorialPdf", parent=_ESTILOS["Normal"], fontName=FONTE_CORPO, fontSize=10, leading=13.5, spaceAfter=3)
_ESTILO_CORPO_NEGRITO = ParagraphStyle("CorpoNegritoMemorialPdf", parent=_ESTILO_CORPO, fontName=FONTE_CORPO_NEGRITO)
_ESTILO_SUBSECAO = ParagraphStyle(
    "SubsecaoMemorialPdf", parent=_ESTILOS["Normal"], fontName=FONTE_CORPO_NEGRITO, fontSize=10.5,
    textColor=_COR_SECAO, spaceBefore=8, spaceAfter=3,
)
_ESTILO_SUAVE_PEQUENO = ParagraphStyle("SuavePequenoMemorialPdf", parent=_ESTILO_CORPO, fontSize=8, textColor=_COR_SUAVE)
_ESTILO_TABELA_CEL = ParagraphStyle("CelulaTabelaMemorialPdf", parent=_ESTILO_CORPO, fontSize=8.6, leading=11, spaceAfter=0)
_ESTILO_TABELA_CEL_NEGRITO = ParagraphStyle("CelulaTabelaMemorialPdfNegrito", parent=_ESTILO_TABELA_CEL, fontName=FONTE_CORPO_NEGRITO)

_ESTILO_TABELA_BASE = [
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]


def _xml_seguro(valor):
    """Escapa texto livre pro mini-XML que `Paragraph` espera, sem tratar
    quebra de linha (uso em células/frases de uma linha só)."""
    if valor is None:
        return ""
    return str(valor).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_seguro_multilinha(valor):
    if valor is None:
        return ""
    return _xml_seguro(valor).replace("\n", "<br/>")


def _p(texto, estilo=_ESTILO_CORPO):
    return Paragraph(_xml_seguro_multilinha(texto), estilo)


def _num(valor, default=0.0):
    if valor in (None, ""):
        return default
    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def _fmt_pt(numero, casas=2):
    """Replica `Number.toLocaleString('pt-BR', {min,maxFractionDigits})`."""
    n = _num(numero)
    texto = f"{n:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_mg_pt(numero):
    """Replica `fmtMgPtCalc` (usado em Cálculos Nutricionais): inteiro sem
    casas, fracionário com 2 casas, SEMPRE com separador de milhar — ex.
    "3.000", "5.000". Confirmado contra o PDF de referência real (seção
    "Cálculos Nutricionais" mostra "3.000 mg", "5.000 mg", "2.820", "3.060"
    — com pontos de milhar)."""
    n = _num(numero)
    if n == int(n):
        return f"{int(n):,}".replace(",", ".")
    return _fmt_pt(n, 2)


def _fmt_2dec_pt(numero):
    """Replica `fmt(n) = n.toFixed(2).replace(".", ",")` — usado em
    Composição Centesimal e Cálculo por Cápsula/Porção: SEMPRE 2 casas
    decimais, NUNCA separador de milhar. Confirmado contra o PDF de
    referência real (mesma seção mostra "3092,78", "6000,00", "5907,22" —
    sem ponto de milhar, diferente do formatador de Cálculos
    Nutricionais acima). Duas fórmulas de formatação distintas no
    sistema original — não é engano, é assim mesmo nos dois componentes
    originais (`composicao-centesimal-editor.tsx` vs `calc-nutricionais-editor.tsx`)."""
    n = _num(numero)
    return f"{n:.2f}".replace(".", ",")


def _parse_json_seguro(valor, tipo_esperado=dict):
    if not valor:
        return None
    try:
        dados = json.loads(valor)
    except (TypeError, ValueError):
        return None
    if not isinstance(dados, tipo_esperado):
        return None
    return dados


def _tabela(linhas, larguras, estilo_extra=None):
    tabela = Table(linhas, colWidths=larguras)
    estilo = list(_ESTILO_TABELA_BASE) + [("GRID", (0, 0), (-1, -1), 0.5, _COR_BORDA)]
    if estilo_extra:
        estilo += estilo_extra
    tabela.setStyle(TableStyle(estilo))
    return tabela


# =============================================================================
# Advertências / Armazenamento — {"selecionadas":[{"texto": "..."}]}
# =============================================================================
def formatar_lista_selecionadas_texto(valor_bruto):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or not isinstance(dados.get("selecionadas"), list):
        return None
    itens = [str(i.get("texto") or "").strip() for i in dados["selecionadas"] if isinstance(i, dict)]
    itens = [t for t in itens if t]
    if not itens:
        return [_p("—")]
    return [_p(f"• {t}") for t in itens]


# =============================================================================
# Modo de Uso — {"selecionado":{"descricao": "..."}} (seleção única)
# =============================================================================
def formatar_selecionado_unico_texto(valor_bruto, campo_texto="descricao"):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or "selecionado" not in dados:
        return None
    sel = dados.get("selecionado")
    if not isinstance(sel, dict):
        return [_p("—")]
    return [_p(str(sel.get(campo_texto) or "—"))]


# =============================================================================
# Alegações — {"selecionadas":[{"ativo":"...","alegacao":"..."}]},
# agrupadas por "ativo" (mesmo agrupamento visual do original).
# =============================================================================
def formatar_alegacoes(valor_bruto):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or not isinstance(dados.get("selecionadas"), list):
        return None
    grupos = {}
    for item in dados["selecionadas"]:
        if not isinstance(item, dict):
            continue
        ativo = str(item.get("ativo") or "—").strip()
        grupos.setdefault(ativo, []).append(str(item.get("alegacao") or "").strip())
    if not grupos:
        return [_p("—")]
    elementos = []
    for ativo in sorted(grupos):
        elementos.append(_p(ativo.upper(), _ESTILO_SUBSECAO))
        for texto in grupos[ativo]:
            if texto:
                elementos.append(_p(f"• {texto}"))
    return elementos


# =============================================================================
# Legislação Aplicável — {"selecionadas":[{"codigo","titulo","categoria"}]},
# agrupada por "categoria", código em negrito + título ao lado.
# =============================================================================
def formatar_legislacao_aplicavel(valor_bruto):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or not isinstance(dados.get("selecionadas"), list):
        return None
    # Fallback "Geral" pro grupo sem categoria — mesmo literal do original
    # (`categoria ?? "Geral"`), não a ordenação alfabética (o original usa
    # a ordem natural de inserção do `Object.entries`).
    grupos, ordem = {}, []
    for item in dados["selecionadas"]:
        if not isinstance(item, dict):
            continue
        categoria = str(item.get("categoria") or "Geral").strip() or "Geral"
        if categoria not in grupos:
            grupos[categoria] = []
            ordem.append(categoria)
        grupos[categoria].append(item)
    if not ordem:
        return [_p("—")]
    elementos = []
    for categoria in ordem:
        elementos.append(_p(categoria.upper(), _ESTILO_SUBSECAO))
        linhas = [
            [_p(str(it.get("codigo") or ""), _ESTILO_TABELA_CEL_NEGRITO), _p(str(it.get("titulo") or ""), _ESTILO_TABELA_CEL)]
            for it in grupos[categoria]
        ]
        elementos.append(_tabela(linhas, [4.3 * cm, 12 * cm]))
        elementos.append(Spacer(1, 0.15 * cm))
    return elementos


# =============================================================================
# Metodologias Aplicadas — {"selecionadas":[{"nome","descricao"}]}, numerada.
# =============================================================================
_ESTILO_CRITERIO = ParagraphStyle(
    "CriterioMetodologiaPdf", parent=_ESTILO_CORPO, textColor=colors.HexColor("#1a3c1e"),
)


def _construir_descricao_automatica_metodologia(item_catalogo):
    """Replica `buildAutoDescricao()` do original — junta descrição + norma
    + princípio + aplicação num texto só, na hora de EXIBIR (não na hora
    de selecionar), pra edições no catálogo depois se refletirem em
    memoriais antigos automaticamente."""
    partes = []
    if item_catalogo.get("descricao"):
        partes.append(str(item_catalogo["descricao"]))
    if item_catalogo.get("norma"):
        partes.append(f"Metodologia: {item_catalogo['norma']}")
    if item_catalogo.get("principio"):
        partes.append(f"Princípio: {item_catalogo['principio']}")
    if item_catalogo.get("aplicacao"):
        partes.append(f"Aplicação: {item_catalogo['aplicacao']}")
    return "\n\n".join(partes)


def formatar_metodologias_aplicadas(conn, valor_bruto):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or not isinstance(dados.get("selecionadas"), list):
        return None
    itens = [i for i in dados["selecionadas"] if isinstance(i, dict)]
    if not itens:
        return [_p("—")]

    # Fase 122 — igual ao original em modo leitura: a descrição é
    # RECONSTRUÍDA a partir do catálogo atual (não a que ficou congelada
    # no memorial na hora da seleção) — se o item ainda existe no
    # catálogo. Item apagado do catálogo depois: usa o que ficou salvo no
    # memorial mesmo (nunca vira "—", nunca trava o PDF).
    ids_str = [str(i.get("id")) for i in itens if i.get("id") is not None]
    catalogo_por_id = {}
    if ids_str:
        marcadores = ",".join("?" for _ in ids_str)
        for linha in conn.execute(
            f"SELECT id, dados FROM memorial_catalogo_itens WHERE catalogo = 'metodologias' AND id IN ({marcadores})",
            ids_str,
        ).fetchall():
            try:
                catalogo_por_id[str(linha["id"])] = json.loads(linha["dados"] or "{}")
            except (TypeError, ValueError):
                pass

    elementos = []
    for idx, item in enumerate(itens, start=1):
        item_catalogo = catalogo_por_id.get(str(item.get("id")))
        nome = str((item_catalogo or item).get("nome") or item.get("nome") or "").upper()
        if item_catalogo is not None:
            descricao = _construir_descricao_automatica_metodologia(item_catalogo)
        else:
            descricao = str(item.get("descricao") or "")
        elementos.append(_p(f"{idx}. {nome}", _ESTILO_SUBSECAO))
        if descricao:
            elementos.append(_p(descricao))
        criterio = str(item.get("criterio") or "").strip()
        if criterio:
            elementos.append(_p(f"Critério/Especificação: {criterio}", _ESTILO_CRITERIO))
    return elementos


# =============================================================================
# Conclusão / Justificativas Técnicas — {"selecionadas":[{"titulo","texto"}]}
# =============================================================================
def formatar_conclusao_ou_justificativas(valor_bruto):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or not isinstance(dados.get("selecionadas"), list):
        return None
    itens = [i for i in dados["selecionadas"] if isinstance(i, dict)]
    if not itens:
        return [_p("—")]
    elementos = []
    for idx, item in enumerate(itens, start=1):
        titulo = str(item.get("titulo") or "").strip()
        if titulo:
            elementos.append(_p(f"{idx}. {titulo}", _ESTILO_SUBSECAO))
        texto = item.get("texto")
        if texto:
            elementos.append(_p(str(texto)))
    return elementos


# =============================================================================
# Referências Bibliográficas — array de IDs do catálogo "referencias"
# (`json.dumps(ids_novos)` no script de importação) — precisa consultar o
# banco pra buscar substância/tipo/citação/DOI de cada ID.
# =============================================================================
def formatar_referencias_bibliograficas(conn, valor_bruto):
    ids_brutos = _parse_json_seguro(valor_bruto, tipo_esperado=list)
    if ids_brutos is None:
        return None
    ids = [i for i in ids_brutos if isinstance(i, int)]
    if not ids:
        return [_p("—")]
    marcadores = ",".join("?" for _ in ids)
    linhas = conn.execute(
        f"SELECT id, dados FROM memorial_catalogo_itens WHERE catalogo = 'referencias' AND id IN ({marcadores})",
        ids,
    ).fetchall()
    mapa = {}
    for linha in linhas:
        try:
            mapa[linha["id"]] = json.loads(linha["dados"] or "{}")
        except (TypeError, ValueError):
            mapa[linha["id"]] = {}
    ids_existentes = [i for i in ids if i in mapa]

    # Ordem EXATA do original (`sortAutoFirst`): auto-incluídas primeiro,
    # depois manuais sem DOI, depois manuais com DOI por último — não é a
    # ordem em que foram salvas no array.
    def _auto_incluir(i):
        return bool((mapa.get(i) or {}).get("auto_incluir"))

    def _tem_doi(i):
        return bool((mapa.get(i) or {}).get("doi"))

    autos = [i for i in ids_existentes if _auto_incluir(i)]
    sem_doi = [i for i in ids_existentes if not _auto_incluir(i) and not _tem_doi(i)]
    com_doi = [i for i in ids_existentes if not _auto_incluir(i) and _tem_doi(i)]
    ordem_exibicao = autos + sem_doi + com_doi

    elementos = []
    for numero, id_ref in enumerate(ordem_exibicao, start=1):
        item = mapa[id_ref]
        substancia = str(item.get("substancia") or "").strip().upper()
        tipo = str(item.get("tipo") or "").strip()
        cabecalho = substancia + (f" · {tipo}" if tipo else "")
        elementos.append(_p(f"{numero}. {cabecalho}", _ESTILO_SUBSECAO))
        # O "Disponível em: <doi>" do original já vem EMBUTIDO dentro do
        # texto de `referencia` (montado uma vez, na hora de cadastrar a
        # referência — `buildAbntAuto()`) — nunca é remontado aqui a
        # partir do campo `doi` separado, senão duplicaria o link.
        referencia = item.get("referencia")
        if referencia:
            elementos.append(_p(str(referencia)))
        descricao = item.get("descricao")
        if descricao:
            elementos.append(_p(str(descricao), _ESTILO_SUAVE_PEQUENO))
    return elementos or [_p("—")]


# =============================================================================
# Ensaios Microbiológicos — {"linhas":[{analise,n,c,m,M}], "observacao"}
# =============================================================================
def formatar_ensaios_microbiologicos(valor_bruto):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or not isinstance(dados.get("linhas"), list):
        return None
    linhas_dados = [l for l in dados["linhas"] if isinstance(l, dict)]
    if not linhas_dados:
        return [_p("—")]
    cabecalho = [
        _p(t, _ESTILO_TABELA_CEL_NEGRITO)
        for t in ("Análises Microbiológicas", "n", "c", "m (mínimo aceitável)", "M (máximo aceitável)")
    ]
    linhas = [cabecalho]
    for l in linhas_dados:
        linhas.append([
            _p(str(l.get("analise") or ""), _ESTILO_TABELA_CEL),
            _p(str(l.get("n") or "—"), _ESTILO_TABELA_CEL),
            _p(str(l.get("c") or "—"), _ESTILO_TABELA_CEL),
            _p(str(l.get("m") or "—"), _ESTILO_TABELA_CEL),
            _p(str(l.get("M") or "—"), _ESTILO_TABELA_CEL),
        ])
    elementos = [_tabela(
        linhas, [5.4 * cm, 1.5 * cm, 1.5 * cm, 3.8 * cm, 3.8 * cm],
        estilo_extra=[("BACKGROUND", (0, 0), (-1, 0), _COR_CABECALHO_TABELA)],
    )]
    observacao = dados.get("observacao")
    if observacao:
        elementos.append(Spacer(1, 0.15 * cm))
        elementos.append(_p(str(observacao), _ESTILO_SUAVE_PEQUENO))
    return elementos


# =============================================================================
# Composição Centesimal — {"descricaoMassa", "linhas":[...]}, sem prefixo
# mágico. Replica `calcularCentesimaisAjustadas` fórmula por fórmula.
# =============================================================================
# Ordem FIXA de exibição (não alfabética, não a ordem de cadastro) —
# idêntica ao original: `["ingrediente", "excipiente", "corante",
# "capsula", ""]`. O rótulo do grupo na TABELA de composição centesimal é
# no singular ("Ingrediente Ativo"); o rótulo no resumo "Cálculo por
# Cápsula/Porção" é no plural ("Ingredientes Ativos") — são textos
# diferentes de propósito, replicando os dois componentes originais
# (`composicao-centesimal-editor.tsx` vs `calculo-18-4-editor.tsx`).
_ORDEM_CATEGORIAS_CENTESIMAL = ["ingrediente", "excipiente", "corante", "capsula", ""]
_ROTULO_CATEGORIA_TABELA = {
    "ingrediente": "Ingrediente Ativo", "excipiente": "Excipiente",
    "corante": "Corante", "capsula": "Cápsula", "": "Sem categoria",
}
_ROTULO_CATEGORIA_RESUMO = {
    "ingrediente": "Ingredientes Ativos", "excipiente": "Excipientes",
    "corante": "Corantes", "capsula": "Cápsula",
}


def _calcular_centesimais_ajustadas(linhas):
    valores = []
    for l in linhas:
        v = l.get("quantidadeIngrediente")
        valores.append(None if v in (None, "") else _num(v))
    total_ing = sum(v for v in valores if v is not None)
    if not total_ing:
        return ["—"] * len(linhas)

    itens = []
    for idx, v in enumerate(valores):
        if v is None or v == 0:
            itens.append(None)
            continue
        raw = (v / total_ing) * 100
        floor2 = max(0.01, math.floor(raw * 100) / 100)
        itens.append({"idx": idx, "raw": raw, "floor_cs": round(floor2 * 100)})
    validos = [it for it in itens if it is not None]
    soma_floor_cs = sum(it["floor_cs"] for it in validos)
    delta = 10000 - soma_floor_cs

    if delta > 0:
        ordenados = sorted(validos, key=lambda it: it["raw"])
        for i in range(min(delta, len(ordenados))):
            ordenados[i]["floor_cs"] += 1
    elif delta < 0:
        ordenados = sorted(validos, key=lambda it: -it["raw"])
        for i in range(min(-delta, len(ordenados))):
            ordenados[i]["floor_cs"] -= 1

    resultado = ["—"] * len(linhas)
    for it in validos:
        resultado[it["idx"]] = _fmt_pt(it["floor_cs"] / 100, 2)
    return resultado


def formatar_composicao_centesimal(valor_bruto, valor_calculo_quantidade):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None or not isinstance(dados.get("linhas"), list):
        return None
    linhas = [l for l in dados["linhas"] if isinstance(l, dict)]
    if not linhas:
        return [_p("—")]
    percentuais = _calcular_centesimais_ajustadas(linhas)

    elementos = []
    descricao_massa = dados.get("descricaoMassa")
    if descricao_massa:
        elementos.append(_p(f"Massa total: {descricao_massa}", _ESTILO_CORPO_NEGRITO))

    # Agrupa por categoria, em ORDEM FIXA (não pela ordem de cadastro) —
    # mas o N° de cada linha continua sendo a posição original no array
    # salvo (+1), então os números podem "pular" quando categorias se
    # intercalam nos dados — isso é intencional, replica o original.
    linhas_por_categoria = {chave: [] for chave in _ORDEM_CATEGORIAS_CENTESIMAL}
    soma_ing_total = soma_elem_total = 0.0
    nomes_por_categoria = {"ingrediente": [], "excipiente": [], "corante": [], "capsula": []}
    # Duas somas por categoria: a tabela de Composição Centesimal usa a
    # coluna "Qtd. Elemental"; o resumo "Cálculo por Cápsula/Porção" (mais
    # abaixo) usa "Qtd. Ingrediente" — confirmado contra o PDF de
    # referência real (lá, "Ingredientes Ativos" no resumo mostra
    # 3092,78 = a quantidade de INGREDIENTE da creatina, não os 3000,00
    # de quantidade ELEMENTAR que aparecem na tabela principal).
    somas_elem_por_categoria = {"ingrediente": 0.0, "excipiente": 0.0, "corante": 0.0, "capsula": 0.0}
    somas_ing_por_categoria = {"ingrediente": 0.0, "excipiente": 0.0, "corante": 0.0, "capsula": 0.0}
    for idx, l in enumerate(linhas):
        categoria = l.get("categoria") or ""
        if categoria not in linhas_por_categoria:
            categoria = ""
        linhas_por_categoria[categoria].append((idx, l))
        nome = str(l.get("componente") or "").strip()
        if categoria in nomes_por_categoria and nome:
            nomes_por_categoria[categoria].append(nome)
        qtd_ing = l.get("quantidadeIngrediente")
        qtd_elem = l.get("quantidadeElementar")
        if isinstance(qtd_ing, (int, float)):
            soma_ing_total += qtd_ing
            if categoria in somas_ing_por_categoria:
                somas_ing_por_categoria[categoria] += qtd_ing
        if isinstance(qtd_elem, (int, float)):
            soma_elem_total += qtd_elem
            if categoria in somas_elem_por_categoria:
                somas_elem_por_categoria[categoria] += qtd_elem

    cabecalho = [
        _p(t, _ESTILO_TABELA_CEL_NEGRITO) for t in
        ("N°", "Componente", "% Pureza", "Faixa de Aceitação", "Qtd. Ingred.", "Qtd. Elemental", "Centesimal (%)")
    ]
    larguras = [0.9 * cm, 4.1 * cm, 1.7 * cm, 2.7 * cm, 2.5 * cm, 2.6 * cm, 2.3 * cm]
    linhas_tabela = [cabecalho]
    indices_subcabecalho = []  # linhas que são subcabeçalho de categoria — pra dar fundo diferente
    for categoria in _ORDEM_CATEGORIAS_CENTESIMAL:
        grupo = linhas_por_categoria[categoria]
        if not grupo:
            continue
        indices_subcabecalho.append(len(linhas_tabela))
        linhas_tabela.append([_p(_ROTULO_CATEGORIA_TABELA[categoria], _ESTILO_SUBSECAO), "", "", "", "", "", ""])
        for idx, l in grupo:
            pureza = l.get("purezaAtivo")
            pureza_txt = f"{_fmt_pt(pureza, 0)}%" if pureza not in (None, "") else "100%"
            a_min, a_max = l.get("aceitacaoMin"), l.get("aceitacaoMax")
            if a_min not in (None, "") or a_max not in (None, ""):
                faixa_txt = f"{a_min if a_min not in (None, '') else '—'}% a {a_max if a_max not in (None, '') else '—'}%"
            else:
                faixa_txt = "não definida"
            qtd_ing = l.get("quantidadeIngrediente")
            qtd_elem = l.get("quantidadeElementar")
            linhas_tabela.append([
                _p(str(idx + 1), _ESTILO_TABELA_CEL),
                _p(str(l.get("componente") or "").strip(), _ESTILO_TABELA_CEL),
                _p(pureza_txt, _ESTILO_TABELA_CEL),
                _p(faixa_txt, _ESTILO_TABELA_CEL),
                _p(_fmt_2dec_pt(qtd_ing) if isinstance(qtd_ing, (int, float)) else "—", _ESTILO_TABELA_CEL),
                _p(_fmt_2dec_pt(qtd_elem) if isinstance(qtd_elem, (int, float)) else "—", _ESTILO_TABELA_CEL_NEGRITO),
                _p(percentuais[idx], _ESTILO_TABELA_CEL_NEGRITO),
            ])
    # Linha de totais (idêntica ao `tfoot` do original: descrição da massa
    # ocupando as duas primeiras colunas, "100,00" fixo na última).
    linhas_tabela.append([
        _p(descricao_massa or "Massa total", _ESTILO_TABELA_CEL_NEGRITO), "", "", "",
        _p(_fmt_2dec_pt(soma_ing_total), _ESTILO_TABELA_CEL_NEGRITO),
        _p(_fmt_2dec_pt(soma_elem_total), _ESTILO_TABELA_CEL_NEGRITO),
        _p("100,00", _ESTILO_TABELA_CEL_NEGRITO),
    ])
    idx_totais = len(linhas_tabela) - 1

    estilo_tabela = [("BACKGROUND", (0, 0), (-1, 0), _COR_CABECALHO_TABELA)]
    for i in indices_subcabecalho:
        estilo_tabela.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f0f4f9")))
        estilo_tabela.append(("SPAN", (0, i), (-1, i)))
    estilo_tabela.append(("BACKGROUND", (0, idx_totais), (-1, idx_totais), _COR_SECAO))
    estilo_tabela.append(("SPAN", (0, idx_totais), (1, idx_totais)))

    elementos.append(Spacer(1, 0.1 * cm))
    elementos.append(_tabela(linhas_tabela, larguras, estilo_extra=estilo_tabela))

    # Cálculo por Cápsula/Porção — usa os rótulos cadastrados em
    # `calculo_quantidade` (Fase 116) quando existirem; senão cai num
    # rótulo genérico ("Massa total" / "Total da dose") em vez de inventar
    # um texto que o usuário nunca cadastrou (o original deriva um rótulo
    # automático a partir do tipo de produto — ver README: adaptação
    # deliberada, ainda não portada).
    calc_qtd = _parse_json_seguro(valor_calculo_quantidade)
    unidade = (calc_qtd or {}).get("unidade")
    descricoes = ((calc_qtd or {}).get("descricoes") or {}).get(unidade, {}) if unidade else {}
    massa_descricao = descricoes.get("massaDescricao") or "Massa total"
    total_descricao = descricoes.get("totalDescricao") or "Total da dose"

    # Fase 122 — esta tabela usa a soma da QUANTIDADE DE INGREDIENTE
    # (não a elemental) — confirmado contra o PDF de referência real: lá,
    # "Ingredientes Ativos (Creatina monohidratada)" mostra 3092,78 (a
    # quantidade de ingrediente, já contando a pureza de 97%), não os
    # 3000,00 de quantidade elementar pura que aparecem na tabela de
    # Composição Centesimal logo acima. Bug corrigido: a primeira versão
    # deste formatador usava a soma elemental aqui por engano.
    linhas_resumo = [[_p(massa_descricao, _ESTILO_TABELA_CEL_NEGRITO), _p(_fmt_2dec_pt(soma_ing_total), _ESTILO_TABELA_CEL_NEGRITO)]]
    for chave in ("ingrediente", "excipiente", "corante", "capsula"):
        if nomes_por_categoria[chave]:
            linhas_resumo.append([
                _p(f"{_ROTULO_CATEGORIA_RESUMO[chave]} (" + ", ".join(nomes_por_categoria[chave]) + ")", _ESTILO_TABELA_CEL),
                _p(_fmt_2dec_pt(somas_ing_por_categoria[chave]), _ESTILO_TABELA_CEL),
            ])
    linhas_resumo.append([_p(total_descricao, _ESTILO_TABELA_CEL_NEGRITO), _p(_fmt_2dec_pt(soma_ing_total), _ESTILO_TABELA_CEL_NEGRITO)])
    linhas_resumo.append([_p("Cálculo Centesimal", _ESTILO_TABELA_CEL_NEGRITO), _p("100", _ESTILO_TABELA_CEL_NEGRITO)])

    elementos.append(Spacer(1, 0.2 * cm))
    elementos.append(_p("Cálculo por Cápsula/Porção", _ESTILO_SUBSECAO))
    if unidade:
        elementos.append(_p(f"Unidade: {unidade.upper()}", _ESTILO_SUAVE_PEQUENO))
    elementos.append(_tabela(linhas_resumo, [12.4 * cm, 4.4 * cm]))

    # "Nota Técnica" — texto FIXO do original (não depende do produto),
    # sempre mostrado junto da Composição Centesimal.
    elementos.append(Spacer(1, 0.2 * cm))
    elementos.append(_p("Nota Técnica", ParagraphStyle(
        "RotuloNotaTecnicaPdf", parent=_ESTILO_SUAVE_PEQUENO, fontName=FONTE_CORPO_NEGRITO, textColor=_COR_SECAO,
    )))
    elementos.append(Paragraph(
        "Os ativos de interesse, utilizados como substância bioativa principal. Adicionalmente, a correta "
        "quantificação e declaração de compostos bioativos em suplementos alimentares devem considerar a forma "
        "química efetivamente disponível, bem como sua biodisponibilidade e consistência analítica, conforme "
        "discutido por <b>Cozzolino (2021)</b>.",
        _ESTILO_SUAVE_PEQUENO,
    ))
    return elementos


# =============================================================================
# Composição Nutricional — {"tipoTabela","dadosPadrao" (JSON-em-string),
# "dadosAlimento"}. O campo ainda é texto livre na TELA do AlphafitusOS
# (editor estruturado próprio ainda não construído — ver README), mas os
# dados IMPORTADOS do sistema original já vêm nesse formato estruturado,
# então o PDF precisa entender de qualquer forma.
# =============================================================================
def formatar_composicao_nutricional(valor_bruto):
    dados = _parse_json_seguro(valor_bruto)
    if dados is None:
        return None
    tipo_tabela = dados.get("tipoTabela")

    def _sub_json(bruto):
        if isinstance(bruto, dict):
            return bruto
        if isinstance(bruto, str):
            return _parse_json_seguro(bruto)
        return None

    if tipo_tabela == "padrao":
        padrao = _sub_json(dados.get("dadosPadrao"))
        return _formatar_tabela_nutricional_padrao(padrao) if padrao else [_p("—")]
    if tipo_tabela == "alimento":
        alimento = _sub_json(dados.get("dadosAlimento"))
        return _formatar_tabela_nutricional_alimento(alimento) if alimento else [_p("—")]
    # tipoTabela ausente/desconhecido — dado não bate com o formato
    # estruturado esperado; deixa o chamador decidir (nunca imprime JSON).
    return None


def _formatar_tabela_nutricional_padrao(padrao):
    porcoes = padrao.get("porcoesPorEmbalagem")
    porcao_g = padrao.get("porcaoGramas")
    descricao_porcao = padrao.get("descricaoPorcao")
    linhas_dados = [l for l in (padrao.get("linhas") or []) if isinstance(l, dict) and l.get("ativo", True)]

    elementos = []
    if porcoes:
        elementos.append(_p(f"Porções por embalagem: {porcoes}"))
    if porcao_g or descricao_porcao:
        rotulo = f"Porção: {porcao_g} g" if porcao_g else "Porção"
        if descricao_porcao:
            rotulo += f" ({descricao_porcao})"
        elementos.append(_p(rotulo))
    elementos.append(Spacer(1, 0.1 * cm))

    coluna_qtd = f"{porcao_g} g" if porcao_g else "Quantidade"
    cabecalho = [_p("", _ESTILO_TABELA_CEL_NEGRITO), _p(coluna_qtd, _ESTILO_TABELA_CEL_NEGRITO), _p("%VD*", _ESTILO_TABELA_CEL_NEGRITO)]
    linhas_tabela = [cabecalho]
    for l in linhas_dados:
        linhas_tabela.append([
            _p(str(l.get("nome") or ""), _ESTILO_TABELA_CEL),
            _p(str(l.get("quantidade") if l.get("quantidade") not in (None, "") else "0"), _ESTILO_TABELA_CEL),
            _p(str(l.get("vd") or "**"), _ESTILO_TABELA_CEL),
        ])
    elementos.append(_tabela(
        linhas_tabela, [8.4 * cm, 4.5 * cm, 3.1 * cm],
        estilo_extra=[("BACKGROUND", (0, 0), (-1, 0), _COR_CABECALHO_TABELA)],
    ))
    rodape = padrao.get("rodapeVD")
    if rodape:
        elementos.append(Spacer(1, 0.1 * cm))
        elementos.append(_p(str(rodape), _ESTILO_SUAVE_PEQUENO))
    return elementos


def _formatar_tabela_nutricional_alimento(alimento):
    """Variante "por alimento" (ex.: declaração por 100 g além da porção)
    — formato ainda não confirmado contra o código-fonte original (o
    AlphafitusOS não tem editor próprio pra essa variante ainda). Em vez
    de arriscar inventar colunas que podem não bater com o dado real,
    mostra os pares campo/valor de forma genérica — nunca JSON cru, mas
    também nunca um formato adivinhado que passe por "oficial"."""
    linhas_dados = alimento.get("linhas") if isinstance(alimento.get("linhas"), list) else None
    elementos = []
    for chave in ("grupoEtario", "porcoesPorEmbalagem", "porcaoGramas", "descricaoPorcao"):
        if alimento.get(chave):
            elementos.append(_p(f"{chave}: {alimento.get(chave)}"))
    if linhas_dados:
        cabecalho = [_p("Nome", _ESTILO_TABELA_CEL_NEGRITO), _p("Quantidade", _ESTILO_TABELA_CEL_NEGRITO), _p("%VD*", _ESTILO_TABELA_CEL_NEGRITO)]
        linhas_tabela = [cabecalho]
        for l in linhas_dados:
            if not isinstance(l, dict):
                continue
            linhas_tabela.append([
                _p(str(l.get("nome") or "")), _p(str(l.get("quantidade") or "0")), _p(str(l.get("vd") or "**")),
            ])
        elementos.append(_tabela(
            linhas_tabela, [8.4 * cm, 4.5 * cm, 3.1 * cm],
            estilo_extra=[("BACKGROUND", (0, 0), (-1, 0), _COR_CABECALHO_TABELA)],
        ))
    rodape = alimento.get("rodapeVD")
    if rodape:
        elementos.append(_p(str(rodape), _ESTILO_SUAVE_PEQUENO))
    return elementos or [_p("—")]


# =============================================================================
# Cálculos Nutricionais — "__CALCV1__" + JSON. Fórmula EXATA replicada de
# `calcularNutriente`/`faixaAceitacaoCalc`/`renderizarResultadoCalc` no
# app.js — qualquer mudança de fórmula lá precisa ser replicada aqui.
# =============================================================================
_CALC_MAGIC = "__CALCV1__"


def formatar_calculos_nutricionais(valor_bruto):
    if not valor_bruto or not str(valor_bruto).startswith(_CALC_MAGIC):
        return None
    dados = _parse_json_seguro(str(valor_bruto)[len(_CALC_MAGIC):])
    if dados is None or not isinstance(dados.get("nutrientes"), list):
        return [_p("—")]
    itens = [n for n in dados["nutrientes"] if isinstance(n, dict)]
    if not itens:
        return [_p("—")]
    elementos = []
    for idx, n in enumerate(itens, start=1):
        elementos.extend(_formatar_um_calculo_nutricional(idx, n))
        elementos.append(Spacer(1, 0.25 * cm))
    return elementos


def _formatar_um_calculo_nutricional(indice, n):
    nome = str(n.get("nutriente") or "(sem nome)")
    fonte = str(n.get("fonte") or "").strip()
    unidade = _xml_seguro(n.get("unidade") or "")
    qtd = _num(n.get("qtdIngrediente"))

    dose_min_ref = n.get("doseMinRef")
    min_livre = dose_min_ref in (None, "", 0) or _num(dose_min_ref) == 0
    dose_min = 0 if min_livre else _num(dose_min_ref)
    dose_max_ref = n.get("doseMaxRef")
    max_livre = dose_max_ref in (None, "", 0) or _num(dose_max_ref) == 0
    dose_max = 0 if max_livre else _num(dose_max_ref)
    pct_min = (qtd / dose_min) * 100 if dose_min > 0 else 0
    pct_max = (qtd / dose_max) * 100 if (not max_livre and dose_max > 0) else 0

    a_min_raw, a_max_raw = n.get("aceitacaoMin"), n.get("aceitacaoMax")
    a_min = a_min_raw if isinstance(a_min_raw, (int, float)) and a_min_raw > 0 else None
    a_max = a_max_raw if isinstance(a_max_raw, (int, float)) and a_max_raw > 0 else None
    real_min = (qtd * a_min) / 100 if (a_min is not None and qtd > 0) else None
    real_max = (qtd * a_max) / 100 if (a_max is not None and qtd > 0) else None
    tem_faixa = a_min is not None or a_max is not None

    titulo = f"{indice}. {_xml_seguro(nome)}"
    if fonte:
        titulo += f" — proveniente de {_xml_seguro(fonte)}"
    elementos = [_p(titulo, _ESTILO_SUBSECAO)]

    cabecalho1 = [_p(t, _ESTILO_TABELA_CEL_NEGRITO) for t in
                  ("Qtd. por porção", "Dose mín. IN 28/2018", "% Dose mín.", "Dose máx. IN 28/2018", "% Dose máx.")]
    valores1 = [
        _p(f"{_fmt_mg_pt(qtd)} {unidade}", _ESTILO_TABELA_CEL),
        _p("Livre" if min_livre else (f"{_fmt_mg_pt(dose_min)} {unidade}" if dose_min > 0 else "—"), _ESTILO_TABELA_CEL),
        _p("✓ Livre" if min_livre else (f"{_fmt_pt(pct_min)}%" if dose_min > 0 else "—"), _ESTILO_TABELA_CEL),
        _p("Livre" if max_livre else (f"{_fmt_mg_pt(dose_max)} {unidade}" if dose_max > 0 else "—"), _ESTILO_TABELA_CEL),
        _p("✓ Livre" if max_livre else (f"{_fmt_pt(pct_max)}%" if dose_max > 0 else "—"), _ESTILO_TABELA_CEL),
    ]
    elementos.append(_tabela(
        [cabecalho1, valores1], [3.4 * cm, 3.4 * cm, 2.6 * cm, 3.4 * cm, 2.6 * cm],
        estilo_extra=[("BACKGROUND", (0, 0), (-1, 0), _COR_CABECALHO_TABELA)],
    ))

    if tem_faixa:
        cabecalho2 = [_p(t, _ESTILO_TABELA_CEL_NEGRITO) for t in
                      ("Faixa de Aceitação (%)", f"Qtd. Mín. Aceita ({unidade})", f"Qtd. Declarada ({unidade})")]
        faixa_txt = f"{_fmt_pt(a_min) if a_min is not None else '—'}% a {_fmt_pt(a_max) if a_max is not None else '—'}%"
        valores2 = [
            _p(faixa_txt, _ESTILO_TABELA_CEL),
            _p(f"{_fmt_mg_pt(real_min)} {unidade}" if real_min is not None else "—", _ESTILO_TABELA_CEL),
            _p(f"{_fmt_mg_pt(qtd)} {unidade}", _ESTILO_TABELA_CEL_NEGRITO),
        ]
        elementos.append(Spacer(1, 0.1 * cm))
        elementos.append(_tabela(
            [cabecalho2, valores2], [5.1 * cm, 5.1 * cm, 5.1 * cm],
            estilo_extra=[("BACKGROUND", (0, 0), (-1, 0), _COR_CABECALHO_TABELA)],
        ))

    nome_min = _xml_seguro(nome.lower())
    partes = []
    if min_livre:
        partes.append(f"<b>Dose mínima:</b> Não há dose mínima estabelecida pela IN 28/2018 para {nome_min} — sem exigência de quantidade mínima (<b>livre</b>).")
    elif dose_min > 0:
        diff_min = pct_min - 100
        if diff_min >= 0:
            partes.append(f"<b>Dose mínima:</b> {_fmt_mg_pt(qtd)} {unidade} / {_fmt_mg_pt(dose_min)} {unidade} × 100 = <b>{_fmt_pt(pct_min)}%</b> da dose mínima de referência — o produto está {_fmt_pt(diff_min)}% acima do limite mínimo exigido para {nome_min}.")
        else:
            partes.append(f"<b>Dose mínima:</b> {_fmt_mg_pt(qtd)} {unidade} / {_fmt_mg_pt(dose_min)} {unidade} × 100 = <b>{_fmt_pt(pct_min)}%</b> da dose mínima de referência — o produto está {_fmt_pt(abs(diff_min))}% abaixo do limite mínimo exigido para {nome_min}. ⚠")
    if max_livre:
        partes.append(f"<b>Dose máxima:</b> Não há dose máxima estabelecida pela IN 28/2018 para {nome_min} — consumo máximo <b>livre</b>.")
    elif dose_max > 0:
        if pct_max <= 100:
            partes.append(f"<b>Dose máxima:</b> {_fmt_mg_pt(qtd)} {unidade} / {_fmt_mg_pt(dose_max)} {unidade} × 100 = <b>{_fmt_pt(pct_max)}%</b> da dose máxima permitida — permanecendo dentro do limite máximo estabelecido para {nome_min}.")
        else:
            partes.append(f"<b>Dose máxima:</b> {_fmt_mg_pt(qtd)} {unidade} / {_fmt_mg_pt(dose_max)} {unidade} × 100 = <b>{_fmt_pt(pct_max)}%</b> da dose máxima permitida — ULTRAPASSA em {_fmt_pt(pct_max - 100)}% o limite máximo para {nome_min}. ⚠")
    if tem_faixa and real_min is not None and real_max is not None:
        partes.append(
            f"<b>Faixa de aceitação:</b> A quantidade declarada de {_fmt_mg_pt(qtd)} {unidade} deve situar-se entre "
            f"<b>{_fmt_mg_pt(real_min)} {unidade}</b> ({_fmt_pt(a_min, 0)}%) e <b>{_fmt_mg_pt(real_max)} {unidade}</b> "
            f"({_fmt_pt(a_max, 0)}%), conforme a faixa de aceitação cadastrada para {nome_min}."
        )

    if partes:
        elementos.append(Spacer(1, 0.1 * cm))
        for texto in partes:
            elementos.append(Paragraph(texto, _ESTILO_CORPO))

    fundamento = n.get("fundamentoLegal")
    if fundamento:
        elementos.append(_p(str(fundamento), ParagraphStyle(
            "FundamentoCalcPdf", parent=_ESTILO_SUAVE_PEQUENO, spaceBefore=6,
        )))
    return elementos
