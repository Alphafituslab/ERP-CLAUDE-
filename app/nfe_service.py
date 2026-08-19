"""
Fase 70 — Fiscal: Emissão de NF-e via provedor terceirizado (Focus NFe).

Ver a nota de escopo completa em migrations/schema_fase70.sql. Resumo:
não falamos com a SEFAZ diretamente — integramos com o Focus NFe, que já
resolve assinatura do XML (usando o certificado que o PRÓPRIO usuário
cadastra no painel deles, nunca aqui), transmissão e retorno.

AVISO IMPORTANTE (repetido no README e na tela de configuração): os
valores-padrão de CST/CSOSN/CFOP usados aqui quando o cadastro do item não
tem um valor específico são PONTOS DE PARTIDA NEUTROS, não uma
recomendação tributária. Antes de emitir qualquer nota em ambiente
"producao" (valendo de verdade), revise com um contador se os códigos
usados são os corretos para o produto/regime/estado de destino. Isto não
é aconselhamento fiscal — é só automação de um formulário.

Dependência opcional: `requests` (mesma filosofia de `boto3` em
app/backup_service.py — importado sob demanda dentro das funções que
realmente chamam a rede, para que este módulo continue importável e
testável mesmo num ambiente sem a biblioteca instalada).
"""
import datetime
import secrets

from .context import ApiError

TIMEOUT_PROVEDOR_SEGUNDOS = 30

# Focus NFe: homologação = ambiente de testes (sem valor fiscal, SEFAZ
# trata como se não tivesse acontecido); producao = nota valendo de
# verdade. A URL base muda entre os dois - nunca a mesma conta/token serve
# para os dois ambientes ao mesmo tempo (o token em si já é por ambiente).
URLS_BASE_FOCUS_NFE = {
    "homologacao": "https://homologacao.focusnfe.com.br",
    "producao": "https://api.focusnfe.com.br",
}

# CSOSN/CST "neutros" usados quando o item não tem codigo_tributario_icms
# próprio — ver aviso no topo do arquivo. 102 = "Tributada pelo Simples
# Nacional sem permissão de crédito" (o caso mais comum para quem vende
# produto acabado como optante do Simples); 00 = "Tributada integralmente"
# (o caso mais comum como ponto de partida fora do Simples). PIS/COFINS
# usam CST 99 ("Outras operações") com valor zero como neutro em ambos os
# regimes, pelo mesmo motivo.
CSOSN_PADRAO_SIMPLES_NACIONAL = "102"
CST_ICMS_PADRAO_OUTROS_REGIMES = "00"
CST_PIS_COFINS_PADRAO = "99"

CAMPOS_FISCAIS_EMPRESA = (
    "inscricao_estadual", "regime_tributario", "logradouro", "numero_endereco",
    "bairro", "municipio", "codigo_ibge_municipio", "uf", "cep",
)
CAMPOS_FISCAIS_CLIENTE = (
    "inscricao_estadual", "logradouro", "numero_endereco",
    "bairro", "municipio", "codigo_ibge_municipio", "uf", "cep",
)
CAMPOS_FISCAIS_ITEM = ("ncm", "cfop_padrao")

STATUS_ATIVOS_NOTA = ("processando_autorizacao", "autorizada")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ============================================================
# CONFIGURAÇÃO (mesmo padrão de app/backup_service.py::obter_configuracao
# e app/routes/notificacoes.py — singleton id=1, token nunca devolvido)
# ============================================================
def obter_configuracao(conn):
    row = conn.execute("SELECT * FROM configuracoes_nfe WHERE id = 1").fetchone()
    if row is None:
        return {
            "id": 1, "provedor": "focus_nfe", "ambiente": "homologacao",
            "token_api": None, "serie": 1, "atualizado_em": None, "atualizado_por": None,
        }
    return dict(row)


def config_publica(config):
    """Nunca devolve o token de API salvo — só um booleano avisando que já
    existe um configurado (mesmo padrão de nuvem_chave_configurada, Fase 67,
    e senha_configurada, Fase 37)."""
    d = dict(config)
    d["token_configurado"] = bool(d.get("token_api"))
    d.pop("token_api", None)
    return d


def salvar_configuracao(conn, dados, usuario_id):
    anterior = obter_configuracao(conn)

    provedor = dados.get("provedor") or anterior.get("provedor") or "focus_nfe"
    if provedor not in ("focus_nfe",):
        raise ApiError("provedor deve ser 'focus_nfe' (único suportado nesta versão).", status=400)

    ambiente = dados.get("ambiente") or anterior.get("ambiente") or "homologacao"
    if ambiente not in ("homologacao", "producao"):
        raise ApiError("ambiente deve ser 'homologacao' ou 'producao'.", status=400)

    serie = dados.get("serie", anterior.get("serie") or 1)
    try:
        serie = int(serie)
    except (TypeError, ValueError):
        raise ApiError("serie deve ser um número inteiro.", status=400)
    if serie <= 0:
        raise ApiError("serie deve ser maior que zero.", status=400)

    # Campo vazio/omitido MANTÉM o token já salvo — mesmo padrão de
    # nuvem_secret_key (Fase 67) e smtp_senha (Fase 37): nunca reenviar à
    # toa um valor que a API nunca devolveu para não sobrescrever com vazio.
    novo_token = dados.get("token_api")
    token_api = anterior.get("token_api") if not novo_token else novo_token.strip()

    conn.execute(
        """
        INSERT INTO configuracoes_nfe (id, provedor, ambiente, token_api, serie, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            provedor = excluded.provedor,
            ambiente = excluded.ambiente,
            token_api = excluded.token_api,
            serie = excluded.serie,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (provedor, ambiente, token_api, serie, _now_iso(), usuario_id),
    )
    return obter_configuracao(conn)


# ============================================================
# VALIDAÇÃO DOS DADOS FISCAIS (antes de tentar emitir)
# ============================================================
def _campos_fiscais_faltando(registro, campos):
    return [c for c in campos if not registro.get(c)]


def validar_pronto_para_emitir(conn, empresa, cliente, itens_do_pedido):
    """Confere, ANTES de gastar uma chamada ao provedor, que emitente,
    destinatário e cada item têm o mínimo de dado fiscal preenchido — dá um
    erro claro e específico em vez de deixar o provedor rejeitar a nota
    (o que só aconteceria depois, de forma assíncrona)."""
    erros = []

    faltando_empresa = _campos_fiscais_faltando(empresa, CAMPOS_FISCAIS_EMPRESA)
    if faltando_empresa:
        erros.append(
            f"Dados fiscais incompletos da empresa emitente ({empresa.get('razao_social')}): "
            f"faltam {', '.join(faltando_empresa)}. Preencha em Administração > Empresas."
        )

    faltando_cliente = _campos_fiscais_faltando(cliente, CAMPOS_FISCAIS_CLIENTE)
    if faltando_cliente:
        erros.append(
            f"Dados fiscais incompletos do cliente ({cliente.get('razao_social')}): "
            f"faltam {', '.join(faltando_cliente)}. Preencha em Comercial > Clientes."
        )

    for it in itens_do_pedido:
        faltando_item = _campos_fiscais_faltando(it, CAMPOS_FISCAIS_ITEM)
        if faltando_item:
            erros.append(
                f"Dados fiscais incompletos do item {it.get('item_codigo')} — {it.get('item_descricao')}: "
                f"faltam {', '.join(faltando_item)}. Preencha em Itens."
            )

    if erros:
        raise ApiError(" | ".join(erros), status=400)


def _codigo_tributario_icms_padrao(item, regime_tributario):
    if item.get("codigo_tributario_icms"):
        return item["codigo_tributario_icms"]
    if regime_tributario == "simples_nacional":
        return CSOSN_PADRAO_SIMPLES_NACIONAL
    return CST_ICMS_PADRAO_OUTROS_REGIMES


# ============================================================
# MONTAGEM DO PAYLOAD (formato JSON documentado do Focus NFe — ver aviso
# no topo do arquivo: construído a partir do contrato publicamente
# documentado da API deles, nunca testado ponta-a-ponta contra o serviço
# real neste ambiente, porque este sandbox de desenvolvimento não tem
# acesso à internet externa. Teste em homologação antes de confiar.)
# ============================================================
def montar_payload_focus_nfe(pedido, empresa, cliente, itens_pedido, referencia):
    regime = empresa.get("regime_tributario") or "simples_nacional"

    itens_payload = []
    for it in itens_pedido:
        ncm = it.get("ncm") or it.get("item_ncm")
        cfop = it.get("cfop_padrao") or it.get("item_cfop_padrao")
        origem = it.get("origem_mercadoria") or it.get("item_origem_mercadoria") or "0"
        codigo_icms = _codigo_tributario_icms_padrao(
            {"codigo_tributario_icms": it.get("codigo_tributario_icms") or it.get("item_codigo_tributario_icms")},
            regime,
        )
        valor_unitario = round(float(it["preco_unitario"]), 2)
        quantidade = float(it["quantidade"])
        valor_bruto = round(valor_unitario * quantidade, 2)

        linha = {
            "numero_item": len(itens_payload) + 1,
            "codigo_produto": it.get("item_codigo"),
            "descricao": it.get("item_descricao"),
            "cfop": cfop,
            "ncm": ncm,
            "unidade_comercial": it.get("unidade"),
            "quantidade_comercial": quantidade,
            "valor_unitario_comercial": valor_unitario,
            "unidade_tributavel": it.get("unidade"),
            "quantidade_tributavel": quantidade,
            "valor_unitario_tributavel": valor_unitario,
            "valor_bruto": valor_bruto,
            "icms_origem": origem,
            # Simples Nacional usa "icms_situacao_tributaria" com um código
            # CSOSN de 3 dígitos; os demais regimes usam um CST de 2
            # dígitos — o Focus NFe usa o mesmo campo para os dois, só o
            # tamanho do código muda (é assim que a API deles distingue).
            "icms_situacao_tributaria": codigo_icms,
            "pis_situacao_tributaria": CST_PIS_COFINS_PADRAO,
            "pis_valor_base_calculo": 0,
            "pis_aliquota_porcentual": 0,
            "cofins_situacao_tributaria": CST_PIS_COFINS_PADRAO,
            "cofins_valor_base_calculo": 0,
            "cofins_aliquota_porcentual": 0,
        }
        if it.get("cest") or it.get("item_cest"):
            linha["cest"] = it.get("cest") or it.get("item_cest")
        itens_payload.append(linha)

    valor_total = round(sum(l["valor_bruto"] for l in itens_payload), 2)

    payload = {
        "natureza_operacao": "Venda de mercadoria",
        "data_emissao": _now_iso(),
        "tipo_documento": 1,          # 1 = saída
        "finalidade_emissao": 1,      # 1 = NF-e normal
        "cnpj_emitente": empresa.get("cnpj"),
        "nome_emitente": empresa.get("razao_social"),
        "inscricao_estadual_emitente": empresa.get("inscricao_estadual"),
        "logradouro_emitente": empresa.get("logradouro"),
        "numero_emitente": empresa.get("numero_endereco"),
        "complemento_emitente": empresa.get("complemento_endereco"),
        "bairro_emitente": empresa.get("bairro"),
        "municipio_emitente": empresa.get("municipio"),
        "codigo_municipio_emitente": empresa.get("codigo_ibge_municipio"),
        "uf_emitente": empresa.get("uf"),
        "cep_emitente": empresa.get("cep"),
        "nome_destinatario": cliente.get("razao_social"),
        "cnpj_destinatario": cliente.get("cnpj"),
        "inscricao_estadual_destinatario": cliente.get("inscricao_estadual"),
        "indicador_inscricao_estadual_destinatario": 1 if (cliente.get("inscricao_estadual") or "").upper() != "ISENTO" else 2,
        "logradouro_destinatario": cliente.get("logradouro"),
        "numero_destinatario": cliente.get("numero_endereco"),
        "complemento_destinatario": cliente.get("complemento_endereco"),
        "bairro_destinatario": cliente.get("bairro"),
        "municipio_destinatario": cliente.get("municipio"),
        "codigo_municipio_destinatario": cliente.get("codigo_ibge_municipio"),
        "uf_destinatario": cliente.get("uf"),
        "cep_destinatario": cliente.get("cep"),
        "valor_frete": 0,
        "valor_seguro": 0,
        "valor_total": valor_total,
        "valor_produtos": valor_total,
        "modalidade_frete": 9,  # 9 = sem frete (padrão neutro; ajuste se o pedido tiver transportadora)
        "items": itens_payload,
        # Referência do nosso lado — usada tanto para a URL de idempotência
        # (PUT /v2/nfe?ref=...) quanto para conseguirmos religar a resposta
        # assíncrona ao pedido de origem.
        "ref": referencia,
    }
    return payload, valor_total


# ============================================================
# CHAMADAS AO PROVEDOR (rede de verdade — só aqui `requests` é importado)
# ============================================================
def _requests():
    try:
        import requests
    except ImportError:
        raise ApiError(
            "A biblioteca 'requests' não está instalada neste ambiente Python — necessária para falar com o "
            "provedor de NF-e. Rode: pip install requests",
            status=500,
        )
    return requests


def _autenticacao(token_api):
    # Focus NFe usa HTTP Basic Auth com o token de API como "usuário" e
    # senha em branco — documentado publicamente na API deles. Não
    # confirmável ponta-a-ponta neste sandbox (sem acesso à internet
    # externa, ver aviso no topo do arquivo); revalide contra a
    # documentação vigente do provedor se o comportamento mudar.
    return (token_api, "")


def _enviar_para_provedor(config, payload, referencia):
    requests = _requests()
    base_url = URLS_BASE_FOCUS_NFE[config["ambiente"]]
    resp = requests.post(
        f"{base_url}/v2/nfe?ref={referencia}",
        json=payload,
        auth=_autenticacao(config["token_api"]),
        timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    return _interpretar_resposta_provedor(resp)


def _consultar_no_provedor(config, referencia):
    requests = _requests()
    base_url = URLS_BASE_FOCUS_NFE[config["ambiente"]]
    resp = requests.get(
        f"{base_url}/v2/nfe/{referencia}",
        auth=_autenticacao(config["token_api"]),
        timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    return _interpretar_resposta_provedor(resp)


def _cancelar_no_provedor(config, referencia, justificativa):
    requests = _requests()
    base_url = URLS_BASE_FOCUS_NFE[config["ambiente"]]
    resp = requests.delete(
        f"{base_url}/v2/nfe/{referencia}",
        json={"justificativa": justificativa},
        auth=_autenticacao(config["token_api"]),
        timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    return _interpretar_resposta_provedor(resp)


# Mapeamento do campo "status" que o Focus NFe devolve para o nosso status
# interno — nomes documentados: "processando_autorizacao", "autorizado",
# "erro_autorizacao", "cancelado". Qualquer valor não reconhecido cai em
# "erro" (nunca assumimos "autorizada" por padrão em caso de dúvida — o
# lado seguro de um erro de interpretação aqui é subestimar o sucesso,
# nunca superestimar).
MAPA_STATUS_PROVEDOR = {
    "processando_autorizacao": "processando_autorizacao",
    "autorizado": "autorizada",
    "erro_autorizacao": "rejeitada",
    "cancelado": "cancelada",
}


def _interpretar_resposta_provedor(resp):
    try:
        corpo = resp.json()
    except ValueError:
        corpo = {}

    if resp.status_code >= 500:
        raise ApiError(f"O provedor de NF-e está indisponível no momento (HTTP {resp.status_code}). Tente novamente em instantes.", status=502)
    if resp.status_code == 401:
        raise ApiError("Token de API do provedor de NF-e inválido ou não configurado. Verifique em Fiscal > Configuração.", status=502)
    if resp.status_code >= 400 and "status" not in corpo:
        mensagem = corpo.get("mensagem") or corpo.get("erros") or f"HTTP {resp.status_code}"
        raise ApiError(f"O provedor de NF-e rejeitou a requisição: {mensagem}", status=502)

    status_provedor = corpo.get("status")
    status_interno = MAPA_STATUS_PROVEDOR.get(status_provedor, "erro")

    return {
        "status": status_interno,
        "status_bruto_provedor": status_provedor,
        "chave_acesso": corpo.get("chave_nfe"),
        "protocolo_autorizacao": corpo.get("numero_protocolo"),
        "mensagem_sefaz": corpo.get("mensagem_sefaz") or corpo.get("mensagem"),
        "url_danfe": corpo.get("caminho_danfe"),
        "url_xml": corpo.get("caminho_xml_nota_fiscal"),
    }


# ============================================================
# ORQUESTRAÇÃO (chamada pelas rotas em app/routes/fiscal.py)
# ============================================================
def gerar_referencia(pedido_id):
    return f"pedido{pedido_id}-{secrets.token_hex(4)}"


def proximo_numero(conn, empresa_id, serie):
    row = conn.execute(
        "SELECT MAX(numero) AS maior FROM notas_fiscais WHERE empresa_id = ? AND serie = ?",
        (empresa_id, serie),
    ).fetchone()
    return (row["maior"] or 0) + 1


def existe_nota_ativa_para_pedido(conn, pedido_id):
    row = conn.execute(
        f"SELECT id FROM notas_fiscais WHERE pedido_id = ? AND status IN ({','.join('?' * len(STATUS_ATIVOS_NOTA))})",
        (pedido_id, *STATUS_ATIVOS_NOTA),
    ).fetchone()
    return row is not None
