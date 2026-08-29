"""
Fase 123 — Recebimento e Importação de NF-e (Fase A: motor de negócio).

Mesma separação já usada em `nfe_service.py` (emissão, Fase 70): este
módulo não importa nada do Flask nem sabe de `g`/request — só recebe uma
conexão de banco (`conn`) e dados já extraídos, e devolve dicts/valores.
Toda a orquestração HTTP (autenticação, `g.usuario_atual`, auditoria) fica
em `app/routes/nfe_entrada.py`, no mesmo padrão de `fiscal.py` orquestrando
`nfe_service.py`.

Escopo desta fase: parsing do XML da NF-e padrão nacional, resolução de
fornecedor/produto/pedido de compra, motor de conversão de unidade, e motor
de conferência (NF-e × Pedido × Cotação). A consulta automática à SEFAZ
(Fase B) fica em `app/sefaz_service.py`, ainda não escrito — este módulo já
nasce pronto para receber XMLs de lá também (mesma função `parsear_xml_nfe`,
independente de como o XML chegou).
"""
import base64
import datetime
import re
import xml.etree.ElementTree as ET

from .context import ApiError

# Namespace padrão do XML de NF-e (Ambiente Nacional) — todo elemento do
# corpo da nota vive dentro dele.
_NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

TOLERANCIA_PRECO_PADRAO = 5.0
TOLERANCIA_QUANTIDADE_PADRAO = 2.0

STATUS_CONFERENCIA = ("correto", "atencao", "divergente")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _normalizar_data_emissao(valor):
    """`dhEmi` do XML vem com o fuso próprio do emitente embutido (ex.:
    '2026-08-20T10:00:00-03:00') — diferente do formato que o resto do
    AlphafitusOS usa internamente (sempre UTC, terminado em 'Z', nunca com
    offset explícito — ver `_now_iso()` em app/db.py e equivalentes). O
    frontend (`fmtData()`, app.js) assume esse segundo formato e só
    completa o 'Z' quando falta — colar um 'Z' depois de um offset
    explícito (`...-03:00Z`) vira uma data inválida. Por isso convertemos
    para UTC aqui, na origem, em vez de mexer no formatador genérico usado
    por todo o resto do sistema. `dEmi` (só data, sem hora/fuso — notas
    mais antigas) passa direto, sem conversão a fazer."""
    if not valor:
        return valor
    try:
        momento = datetime.datetime.fromisoformat(valor)
    except ValueError:
        return valor  # formato inesperado — devolve como veio, sem quebrar o upload por causa disso.
    if momento.tzinfo is None:
        return valor  # já não tem offset (ex.: dEmi, só data) — nada a converter.
    momento_utc = momento.astimezone(datetime.timezone.utc)
    return momento_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _texto(elemento, caminho, obrigatorio=False, padrao=None):
    achado = elemento.find(caminho, _NS)
    if achado is None or achado.text is None:
        if obrigatorio:
            raise ApiError(f"XML da NF-e inválido — campo obrigatório ausente: {caminho}", status=400)
        return padrao
    return achado.text.strip()


def _numero(elemento, caminho, obrigatorio=False, padrao=0.0):
    valor = _texto(elemento, caminho, obrigatorio=obrigatorio)
    if valor is None:
        return padrao
    try:
        return float(valor)
    except ValueError:
        raise ApiError(f"XML da NF-e inválido — valor numérico esperado em {caminho}: '{valor}'", status=400)


# ============================================================
# PARSING DO XML (padrão nacional — infNFe/det/prod)
# ============================================================
def parsear_xml_nfe(xml_texto):
    """Extrai os dados relevantes de um XML de NF-e (padrão nacional,
    autorizada — aceita tanto o XML "puro" `<NFe>` quanto o `<nfeProc>`
    que embrulha a NFe junto do protocolo de autorização, formato mais
    comum de quem baixa a nota do portal do fornecedor ou da própria
    SEFAZ). Nunca modifica o texto recebido — quem chama é responsável por
    guardar o XML original intacto (`nfe_recebimento.xml_original`)
    à parte deste retorno estruturado."""
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError as e:
        raise ApiError(f"XML inválido — não foi possível interpretar: {e}", status=400)

    inf_nfe = raiz.find(".//nfe:infNFe", _NS)
    if inf_nfe is None:
        raise ApiError(
            "XML não parece ser uma NF-e válida (elemento <infNFe> não encontrado). "
            "Confira se o arquivo é o XML autorizado da nota, não o DANFE em PDF.",
            status=400,
        )

    chave_acesso = (inf_nfe.get("Id") or "").replace("NFe", "").strip()
    if not chave_acesso or len(chave_acesso) != 44:
        raise ApiError("Não foi possível identificar a chave de acesso (44 dígitos) no XML.", status=400)

    ide = inf_nfe.find("nfe:ide", _NS)
    emit = inf_nfe.find("nfe:emit", _NS)
    total = inf_nfe.find("nfe:total/nfe:ICMSTot", _NS)

    numero = _texto(ide, "nfe:nNF") if ide is not None else None
    serie = _texto(ide, "nfe:serie") if ide is not None else None
    data_emissao = _normalizar_data_emissao(
        _texto(ide, "nfe:dhEmi") or (_texto(ide, "nfe:dEmi") if ide is not None else None)
    )

    cnpj_emitente = _texto(emit, "nfe:CNPJ") if emit is not None else None
    if not cnpj_emitente:
        raise ApiError("XML sem CNPJ do emitente — não é possível identificar o fornecedor.", status=400)
    razao_social_emitente = _texto(emit, "nfe:xNome") if emit is not None else None

    valor_total = _numero(total, "nfe:vNF") if total is not None else 0.0
    # Totais declarados pelo próprio emitente (nunca recalculados aqui) —
    # usados só para alimentar `notas_fiscais_entrada` (Fase 78) na
    # importação, com a mesma fidelidade de quem digitaria a nota à mão.
    valor_frete = _numero(total, "nfe:vFrete", padrao=0.0) if total is not None else 0.0
    valor_seguro = _numero(total, "nfe:vSeg", padrao=0.0) if total is not None else 0.0
    valor_desconto = _numero(total, "nfe:vDesc", padrao=0.0) if total is not None else 0.0
    valor_outras_despesas = _numero(total, "nfe:vOutro", padrao=0.0) if total is not None else 0.0

    itens = []
    for det in inf_nfe.findall("nfe:det", _NS):
        prod = det.find("nfe:prod", _NS)
        if prod is None:
            continue
        numero_item = int(det.get("nItem") or (len(itens) + 1))
        item = {
            "numero_item": numero_item,
            "codigo_produto_fornecedor": _texto(prod, "nfe:cProd"),
            "descricao_xml": _texto(prod, "nfe:xProd", obrigatorio=True),
            "ncm": _texto(prod, "nfe:NCM"),
            "cfop": _texto(prod, "nfe:CFOP"),
            "quantidade_xml": _numero(prod, "nfe:qCom", obrigatorio=True),
            "unidade_xml": _texto(prod, "nfe:uCom", obrigatorio=True),
            "valor_unitario_xml": _numero(prod, "nfe:vUnCom", obrigatorio=True),
            "valor_total_xml": _numero(prod, "nfe:vProd", padrao=None),
        }
        item.update(_extrair_impostos_item(det.find("nfe:imposto", _NS)))
        itens.append(item)

    if not itens:
        raise ApiError("XML não tem nenhum item (<det>/<prod>) — nada para conferir.", status=400)

    return {
        "chave_acesso": chave_acesso,
        "numero": numero,
        "serie": serie,
        "data_emissao": data_emissao,
        "cnpj_emitente": cnpj_emitente,
        "razao_social_emitente": razao_social_emitente,
        "valor_total": valor_total,
        "valor_frete": valor_frete,
        "valor_seguro": valor_seguro,
        "valor_desconto": valor_desconto,
        "valor_outras_despesas": valor_outras_despesas,
        "itens": itens,
    }


def _num_opcional(elemento, caminho):
    if elemento is None:
        return 0.0
    achado = elemento.find(caminho, _NS)
    if achado is None or not achado.text:
        return 0.0
    try:
        return float(achado.text)
    except ValueError:
        return 0.0


def _extrair_impostos_item(imposto):
    """Lê CST/CSOSN e as bases/alíquotas/valores de ICMS, ICMS-ST e IPI
    exatamente como DECLARADOS no XML — nunca calculados aqui (mesma régua
    de `nfe_service.py`: isto não é aconselhamento fiscal, é leitura do
    que o emitente já declarou). O nome do elemento-filho de <ICMS>/<IPI>
    muda conforme o CST/CSOSN (ICMS00, ICMS60, ICMSSN101, IPITrib, IPINT
    etc.) — por isso pega genericamente o primeiro (e único) filho, em vez
    de tentar adivinhar qual tag específica virá."""
    resultado = {
        "cst_csosn": None, "base_calculo_icms": 0.0, "aliquota_icms": 0.0, "valor_icms": 0.0,
        "base_calculo_icms_st": 0.0, "aliquota_icms_st": 0.0, "valor_icms_st": 0.0,
        "aliquota_ipi": 0.0, "valor_ipi": 0.0,
    }
    if imposto is None:
        return resultado

    icms_pai = imposto.find("nfe:ICMS", _NS)
    if icms_pai is not None and len(icms_pai):
        icms = list(icms_pai)[0]
        resultado["cst_csosn"] = _texto(icms, "nfe:CST") or _texto(icms, "nfe:CSOSN")
        resultado["base_calculo_icms"] = _num_opcional(icms, "nfe:vBC")
        resultado["aliquota_icms"] = _num_opcional(icms, "nfe:pICMS")
        resultado["valor_icms"] = _num_opcional(icms, "nfe:vICMS")
        resultado["base_calculo_icms_st"] = _num_opcional(icms, "nfe:vBCST")
        resultado["aliquota_icms_st"] = _num_opcional(icms, "nfe:pICMSST")
        resultado["valor_icms_st"] = _num_opcional(icms, "nfe:vICMSST")

    ipi_pai = imposto.find("nfe:IPI", _NS)
    if ipi_pai is not None and len(ipi_pai):
        # <IPI> pode trazer <cEnq> como primeiro filho antes de
        # <IPITrib>/<IPINT> — procura o filho que realmente tem CST.
        for filho in ipi_pai:
            cst_ipi = _texto(filho, "nfe:CST")
            if cst_ipi:
                if not resultado["cst_csosn"]:
                    pass  # CST do IPI é um código diferente do de ICMS — não sobrescreve.
                resultado["aliquota_ipi"] = _num_opcional(filho, "nfe:pIPI")
                resultado["valor_ipi"] = _num_opcional(filho, "nfe:vIPI")
                break

    return resultado


def normalizar_base64(valor):
    """Remove o prefixo `data:...;base64,` quando o navegador manda o
    arquivo lido via `readAsDataURL` (mesmo formato aceito por
    `memorial_anexos.py`) — o que fica guardado em `xml_original` é
    sempre só a parte base64, nunca o prefixo."""
    if "," in valor and valor.strip().lower().startswith("data:"):
        return valor.split(",", 1)[1]
    return valor


def decodificar_xml_bytes(xml_base64):
    """Decodifica o XML PRESERVANDO os bytes originais (nunca reencoda) —
    importante porque XML de NF-e é comum vir declarado como
    'ISO-8859-1' (acentuação/Latin-1), não só UTF-8; decodificar sempre
    como UTF-8 quebraria (ou corromperia silenciosamente) esses casos.
    Lê a declaração `<?xml ... encoding="..."?>` dos primeiros bytes
    (sempre ASCII puro, então segura de ler antes de saber a codificação
    do resto) para decidir como decodificar o restante; sem declaração
    reconhecida, assume UTF-8 (padrão do XML e o mais comum hoje)."""
    try:
        bruto = base64.b64decode(normalizar_base64(xml_base64), validate=True)
    except Exception:
        raise ApiError("Não foi possível decodificar o XML — confira se o conteúdo está em base64 válido.", status=400)

    cabecalho = bruto[:200].decode("ascii", errors="ignore")
    encoding = "utf-8"
    match_encoding = re.search(r'encoding\s*=\s*["\']([\w-]+)["\']', cabecalho, re.IGNORECASE)
    if match_encoding:
        encoding = match_encoding.group(1)
    try:
        return bruto.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        # Codificação declarada não bateu com o conteúdo real (arquivo
        # mal formado) — tenta UTF-8 puro antes de desistir; se nem isso
        # funcionar, o erro real aparece na hora de fazer o parse do XML
        # de qualquer forma (ET.fromstring também recebe bytes crus como
        # último recurso).
        try:
            return bruto.decode("utf-8")
        except UnicodeDecodeError:
            return bruto.decode(encoding, errors="replace")


# ============================================================
# RESOLUÇÃO — fornecedor, produto, pedido de compra
# ============================================================
def _normalizar_cnpj(cnpj):
    return "".join(c for c in (cnpj or "") if c.isdigit())


def resolver_fornecedor_por_cnpj(conn, cnpj_emitente):
    alvo = _normalizar_cnpj(cnpj_emitente)
    if not alvo:
        return None
    linhas = conn.execute("SELECT id, cnpj FROM fornecedores").fetchall()
    for linha in linhas:
        if _normalizar_cnpj(linha["cnpj"]) == alvo:
            return linha["id"]
    return None


def resolver_item_por_vinculo(conn, fornecedor_id, codigo_produto_fornecedor):
    if not fornecedor_id or not codigo_produto_fornecedor:
        return None
    row = conn.execute(
        "SELECT item_id FROM fornecedor_produto_vinculo WHERE fornecedor_id = ? AND codigo_fornecedor = ?",
        (fornecedor_id, codigo_produto_fornecedor),
    ).fetchone()
    return row["item_id"] if row else None


def salvar_vinculo_fornecedor_produto(conn, fornecedor_id, codigo_produto_fornecedor, item_id, usuario_id):
    """Grava (ou atualiza, se o mesmo código já apontava para outro item —
    correção deliberada de um vínculo salvo errado antes) a associação
    código-do-fornecedor -> produto interno, reaproveitada automaticamente
    nas próximas NF-e do mesmo fornecedor (seção 7 da especificação)."""
    if not codigo_produto_fornecedor:
        return
    conn.execute(
        """
        INSERT INTO fornecedor_produto_vinculo (fornecedor_id, codigo_fornecedor, item_id, criado_por)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(fornecedor_id, codigo_fornecedor) DO UPDATE SET
            item_id = excluded.item_id, criado_por = excluded.criado_por, criado_em = excluded.criado_em
        """,
        (fornecedor_id, codigo_produto_fornecedor, item_id, usuario_id),
    )


def resolver_pedidos_compra_candidatos(conn, fornecedor_id):
    """Pedidos do fornecedor ainda abertos para recebimento (mesmos status
    aceitos por `validar_pedido_para_recebimento` em compras.py) — se
    houver exatamente um, a rota resolve automático; mais de um, quem usa
    a tela escolhe manualmente entre estes."""
    if not fornecedor_id:
        return []
    rows = conn.execute(
        """
        SELECT id, numero, status, criado_em FROM pedidos_compra
        WHERE fornecedor_id = ? AND status IN ('enviado', 'parcialmente_recebido')
        ORDER BY criado_em DESC
        """,
        (fornecedor_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# CONVERSÃO DE UNIDADE
# ============================================================
def _unidade_ou_none(conn, codigo):
    if not codigo:
        return None
    row = conn.execute(
        "SELECT * FROM unidades_medida WHERE lower(codigo) = lower(?)", (codigo,)
    ).fetchone()
    return dict(row) if row else None


def obter_fator_conversao(conn, item_id, unidade_origem, unidade_destino):
    """Devolve o fator tal que `quantidade_destino = quantidade_origem *
    fator`, ou lança ApiError se não existir conversão conhecida. Ordem de
    resolução: (1) mesma unidade -> fator 1; (2) as duas são massa ou as
    duas são volume, com fator_para_base cadastrado -> conversão
    matemática via base comum (grama/mililitro); (3) fator específico do
    item em `item_conversoes_unidade` (direto ou invertido)."""
    if not unidade_origem or not unidade_destino:
        raise ApiError("Informe a unidade de origem e a unidade interna de destino.", status=400)
    if unidade_origem.lower() == unidade_destino.lower():
        return 1.0

    origem = _unidade_ou_none(conn, unidade_origem)
    destino = _unidade_ou_none(conn, unidade_destino)

    if (
        origem and destino
        and origem["tipo"] == destino["tipo"]
        and origem["tipo"] in ("massa", "volume")
        and origem["fator_para_base"] is not None
        and destino["fator_para_base"] is not None
    ):
        # 1 unidade_origem = origem.fator_para_base unidades-base;
        # 1 unidade-base = 1/destino.fator_para_base unidades_destino.
        return origem["fator_para_base"] / destino["fator_para_base"]

    if item_id:
        row = conn.execute(
            "SELECT fator FROM item_conversoes_unidade WHERE item_id = ? AND lower(unidade_origem) = lower(?) AND lower(unidade_destino) = lower(?)",
            (item_id, unidade_origem, unidade_destino),
        ).fetchone()
        if row:
            return row["fator"]
        row_inverso = conn.execute(
            "SELECT fator FROM item_conversoes_unidade WHERE item_id = ? AND lower(unidade_origem) = lower(?) AND lower(unidade_destino) = lower(?)",
            (item_id, unidade_destino, unidade_origem),
        ).fetchone()
        if row_inverso and row_inverso["fator"]:
            return 1.0 / row_inverso["fator"]

    raise ApiError(
        f"Não existe conversão conhecida de '{unidade_origem}' para '{unidade_destino}' para este item. "
        "Cadastre o fator de conversão (ex.: 1 caixa = 12 frascos) antes de continuar.",
        status=400,
    )


def converter_quantidade(conn, item_id, quantidade, unidade_origem, unidade_destino):
    fator = obter_fator_conversao(conn, item_id, unidade_origem, unidade_destino)
    return quantidade * fator, fator


def converter_preco_unitario(conn, item_id, preco_unitario, unidade_origem, unidade_destino):
    """Preço é o inverso da quantidade na conversão: se 1 unidade_origem
    vale `fator` unidades_destino, cada unidade_destino vale menos (ou
    mais) que cada unidade_origem na mesma proporção inversa (seção 10 —
    nunca comparar R$/kg direto com R$/mg sem normalizar primeiro)."""
    fator = obter_fator_conversao(conn, item_id, unidade_origem, unidade_destino)
    return preco_unitario / fator


# ============================================================
# CONFERÊNCIA (NF-e × Pedido de Compra × Cotação/Orçamento aprovado)
# ============================================================
def _classificar(diferenca_percentual_abs, tolerancia):
    if diferenca_percentual_abs <= tolerancia:
        return "correto"
    if diferenca_percentual_abs <= tolerancia * 2:
        return "atencao"
    return "divergente"


def obter_config(conn):
    row = conn.execute("SELECT * FROM configuracoes_nfe_entrada WHERE id = 1").fetchone()
    if row is None:
        return {
            "id": 1, "tolerancia_preco_percentual": TOLERANCIA_PRECO_PADRAO,
            "tolerancia_quantidade_percentual": TOLERANCIA_QUANTIDADE_PADRAO,
            "certificado_nome_arquivo": None, "ambiente": "homologacao",
        }
    d = dict(row)
    d.pop("certificado_pfx", None)
    d.pop("certificado_senha", None)
    d["certificado_configurado"] = bool(row["certificado_pfx"])
    return d


def _preco_cotado_e_pedido(conn, pedido_compra_id, fornecedor_id, item_id):
    """Devolve (preco_pedido, unidade_pedido, preco_cotado, unidade_cotado)
    — qualquer um pode vir None se não existir. `preco_cotado` vem da
    cotação que gerou este pedido (Fase 66 — cotacoes.pedido_compra_gerado_id),
    quando existir; `preco_pedido` vem sempre da linha do próprio Pedido de
    Compra (Fase 58), que é o mínimo que qualquer nota tem para conferir
    contra, mesmo quando o pedido nasceu manual, sem cotação por trás."""
    preco_pedido = unidade_pedido = preco_cotado = unidade_cotado = None

    if pedido_compra_id:
        linha_pedido = conn.execute(
            "SELECT preco_unitario, unidade FROM itens_pedido_compra WHERE pedido_compra_id = ? AND item_id = ?",
            (pedido_compra_id, item_id),
        ).fetchone()
        if linha_pedido:
            preco_pedido = linha_pedido["preco_unitario"]
            unidade_pedido = linha_pedido["unidade"]

        cotacao = conn.execute(
            "SELECT id FROM cotacoes WHERE pedido_compra_gerado_id = ?", (pedido_compra_id,)
        ).fetchone()
        if cotacao and fornecedor_id:
            resposta = conn.execute(
                "SELECT preco_unitario FROM cotacao_respostas WHERE cotacao_id = ? AND fornecedor_id = ? AND item_id = ?",
                (cotacao["id"], fornecedor_id, item_id),
            ).fetchone()
            item_cotacao = conn.execute(
                "SELECT unidade FROM cotacao_itens WHERE cotacao_id = ? AND item_id = ?",
                (cotacao["id"], item_id),
            ).fetchone()
            if resposta:
                preco_cotado = resposta["preco_unitario"]
                unidade_cotado = item_cotacao["unidade"] if item_cotacao else unidade_pedido

    return preco_pedido, unidade_pedido, preco_cotado, unidade_cotado


def conferir_item_nota(conn, nfe_item, pedido_compra_id, fornecedor_id, config):
    """Confere UM item da NF-e contra o que foi pedido/cotado. `nfe_item`
    é um dict com pelo menos: item_id, unidade_xml, valor_unitario_xml,
    quantidade_xml, unidade_interna_selecionada (a unidade que o usuário
    escolheu usar internamente — por padrão, a do cadastro do item).
    Devolve um dict pronto para a tela mostrar 🟢/🟡/🔴, seguindo a seção 5/6
    da especificação. Nunca lança exceção por divergência — divergência é
    resultado, não erro; só lança se faltar conversão de unidade cadastrada
    (ver `converter_quantidade`)."""
    item_id = nfe_item.get("item_id")
    unidade_interna = nfe_item.get("unidade_interna_selecionada") or nfe_item["unidade_xml"]

    quantidade_convertida, fator_quantidade = converter_quantidade(
        conn, item_id, nfe_item["quantidade_xml"], nfe_item["unidade_xml"], unidade_interna
    )
    preco_nfe_convertido = converter_preco_unitario(
        conn, item_id, nfe_item["valor_unitario_xml"], nfe_item["unidade_xml"], unidade_interna
    )

    preco_pedido, unidade_pedido, preco_cotado, unidade_cotado = _preco_cotado_e_pedido(
        conn, pedido_compra_id, fornecedor_id, item_id
    )

    preco_pedido_convertido = None
    if preco_pedido is not None:
        preco_pedido_convertido = converter_preco_unitario(conn, item_id, preco_pedido, unidade_pedido, unidade_interna)
    preco_cotado_convertido = None
    if preco_cotado is not None:
        preco_cotado_convertido = converter_preco_unitario(conn, item_id, preco_cotado, unidade_cotado, unidade_interna)

    # Referência de comparação: cotado tem prioridade (é o preço que
    # embasou a decisão de compra — seção 4: "o orçamento utilizado como
    # base da decisão da compra deverá permanecer registrado para
    # auditoria"); sem cotação, cai para o preço do próprio pedido.
    preco_referencia = preco_cotado_convertido if preco_cotado_convertido is not None else preco_pedido_convertido

    status_preco = None
    diferenca_preco_percentual = None
    if preco_referencia:
        diferenca_preco_percentual = ((preco_nfe_convertido - preco_referencia) / preco_referencia) * 100
        status_preco = _classificar(abs(diferenca_preco_percentual), config["tolerancia_preco_percentual"])

    quantidade_pedida = None
    status_quantidade = None
    diferenca_quantidade_percentual = None
    if pedido_compra_id and item_id:
        linha_pedido = conn.execute(
            "SELECT quantidade_pedida, unidade FROM itens_pedido_compra WHERE pedido_compra_id = ? AND item_id = ?",
            (pedido_compra_id, item_id),
        ).fetchone()
        if linha_pedido:
            quantidade_pedida_convertida, _ = converter_quantidade(
                conn, item_id, linha_pedido["quantidade_pedida"], linha_pedido["unidade"], unidade_interna
            )
            quantidade_pedida = quantidade_pedida_convertida
            if quantidade_pedida_convertida:
                diferenca_quantidade_percentual = (
                    (quantidade_convertida - quantidade_pedida_convertida) / quantidade_pedida_convertida
                ) * 100
                status_quantidade = _classificar(abs(diferenca_quantidade_percentual), config["tolerancia_quantidade_percentual"])

    return {
        "item_id": item_id,
        "produto_identificado": item_id is not None,
        "unidade_interna_selecionada": unidade_interna,
        "quantidade_convertida": quantidade_convertida,
        "fator_conversao_aplicado": fator_quantidade,
        "preco_nfe_por_unidade_fiscal": nfe_item["valor_unitario_xml"],
        "preco_nfe_convertido": preco_nfe_convertido,
        "preco_pedido": preco_pedido_convertido,
        "preco_cotado": preco_cotado_convertido,
        "diferenca_preco_percentual": diferenca_preco_percentual,
        "status_preco": status_preco,
        "quantidade_pedida": quantidade_pedida,
        "diferenca_quantidade_percentual": diferenca_quantidade_percentual,
        "status_quantidade": status_quantidade,
    }
