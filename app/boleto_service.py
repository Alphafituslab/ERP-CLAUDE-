"""
Fase 71 — Financeiro: Emissão de Boleto Bancário via provedor terceirizado
(Asaas).

Ver a nota de escopo completa em migrations/schema_fase71.sql. Resumo: não
integramos direto com nenhum banco — integramos com o Asaas, um gateway de
pagamentos que já é conveniado com a rede bancária e devolve linha
digitável, código de barras e um link de PDF prontos.

AVISO IMPORTANTE (repetido no README e na tela de configuração):
construído a partir do contrato publicamente documentado da API do Asaas,
nunca testado ponta-a-ponta contra o serviço real, porque este ambiente de
desenvolvimento em nuvem não tem acesso à internet externa (mesmo motivo
documentado em app/nfe_service.py, Fase 70). Teste bem em ambiente
"sandbox" antes de confiar em "producao".

Dependência opcional: `requests` (mesmo padrão de app/nfe_service.py —
importado sob demanda dentro das funções que realmente chamam a rede).
"""
import datetime
import re
import secrets

from .context import ApiError

TIMEOUT_PROVEDOR_SEGUNDOS = 30

URLS_BASE_ASAAS = {
    "sandbox": "https://sandbox.asaas.com/api/v3",
    "producao": "https://api.asaas.com/v3",
}

STATUS_ATIVOS_BOLETO = ("pendente",)

# Mapeamento do campo "status" que o Asaas devolve para o nosso status
# interno — nomes documentados: PENDING, RECEIVED, CONFIRMED,
# RECEIVED_IN_CASH, OVERDUE, REFUNDED, CANCELLED (e outros, ex. de
# estorno/chargeback, tratados como "erro" por segurança — o lado seguro
# de não reconhecer um status é NUNCA assumir "recebido" por padrão).
MAPA_STATUS_PROVEDOR = {
    "PENDING": "pendente",
    "RECEIVED": "recebido",
    "CONFIRMED": "recebido",
    "RECEIVED_IN_CASH": "recebido",
    "OVERDUE": "vencido",
    "CANCELLED": "cancelado",
    "REFUNDED": "cancelado",
}


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _somente_digitos(texto):
    return re.sub(r"\D", "", texto or "")


# ============================================================
# CONFIGURAÇÃO (mesmo padrão de app/nfe_service.py::obter_configuracao —
# singleton id=1, token nunca devolvido)
# ============================================================
def obter_configuracao(conn):
    row = conn.execute("SELECT * FROM configuracoes_boleto WHERE id = 1").fetchone()
    if row is None:
        return {
            "id": 1, "provedor": "asaas", "ambiente": "sandbox",
            "token_api": None, "atualizado_em": None, "atualizado_por": None,
        }
    return dict(row)


def config_publica(config):
    d = dict(config)
    d["token_configurado"] = bool(d.get("token_api"))
    d.pop("token_api", None)
    return d


def salvar_configuracao(conn, dados, usuario_id):
    anterior = obter_configuracao(conn)

    provedor = dados.get("provedor") or anterior.get("provedor") or "asaas"
    if provedor not in ("asaas",):
        raise ApiError("provedor deve ser 'asaas' (único suportado nesta versão).", status=400)

    ambiente = dados.get("ambiente") or anterior.get("ambiente") or "sandbox"
    if ambiente not in ("sandbox", "producao"):
        raise ApiError("ambiente deve ser 'sandbox' ou 'producao'.", status=400)

    # Campo vazio/omitido MANTÉM o token já salvo — mesmo padrão de
    # nfe_service.py/nuvem_secret_key/smtp_senha.
    novo_token = dados.get("token_api")
    token_api = anterior.get("token_api") if not novo_token else novo_token.strip()

    conn.execute(
        """
        INSERT INTO configuracoes_boleto (id, provedor, ambiente, token_api, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            provedor = excluded.provedor,
            ambiente = excluded.ambiente,
            token_api = excluded.token_api,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (provedor, ambiente, token_api, _now_iso(), usuario_id),
    )
    return obter_configuracao(conn)


# ============================================================
# CHAMADAS AO PROVEDOR (rede de verdade — só aqui `requests` é importado)
# ============================================================
def _requests():
    try:
        import requests
    except ImportError:
        raise ApiError(
            "A biblioteca 'requests' não está instalada neste ambiente Python — necessária para falar com o "
            "provedor de boleto. Rode: pip install requests",
            status=500,
        )
    return requests


def _cabecalhos(token_api):
    # Asaas usa um cabeçalho próprio "access_token" (não é HTTP Basic Auth
    # nem "Authorization: Bearer") — documentado publicamente na API deles.
    # Não confirmável ponta-a-ponta neste sandbox (sem acesso à internet
    # externa, ver aviso no topo do arquivo); revalide contra a
    # documentação vigente do provedor se o comportamento mudar.
    return {"access_token": token_api, "Content-Type": "application/json"}


def _tratar_resposta(resp):
    try:
        corpo = resp.json()
    except ValueError:
        corpo = {}
    if resp.status_code >= 500:
        raise ApiError(f"O provedor de boleto está indisponível no momento (HTTP {resp.status_code}). Tente novamente em instantes.", status=502)
    if resp.status_code in (401, 403):
        raise ApiError("Token de API do provedor de boleto inválido ou não configurado. Verifique em Financeiro > Configuração de Boleto.", status=502)
    if resp.status_code >= 400:
        erros = corpo.get("errors") or corpo.get("mensagem") or f"HTTP {resp.status_code}"
        raise ApiError(f"O provedor de boleto rejeitou a requisição: {erros}", status=502)
    return corpo


def _buscar_cliente_por_cnpj(config, cnpj):
    requests = _requests()
    base_url = URLS_BASE_ASAAS[config["ambiente"]]
    resp = requests.get(
        f"{base_url}/customers", params={"cpfCnpj": _somente_digitos(cnpj)},
        headers=_cabecalhos(config["token_api"]), timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    corpo = _tratar_resposta(resp)
    dados = corpo.get("data") or []
    return dados[0]["id"] if dados else None


def _criar_cliente(config, cliente):
    requests = _requests()
    base_url = URLS_BASE_ASAAS[config["ambiente"]]
    resp = requests.post(
        f"{base_url}/customers",
        json={"name": cliente["razao_social"], "cpfCnpj": _somente_digitos(cliente["cnpj"])},
        headers=_cabecalhos(config["token_api"]), timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    corpo = _tratar_resposta(resp)
    return corpo["id"]


def buscar_ou_criar_cliente_asaas(config, cliente):
    """Devolve o id do cliente no Asaas — reaproveita `id_externo_asaas`
    se já tiver sido resolvido antes (ver `clientes.id_externo_asaas`,
    schema_fase71.sql); caso contrário busca por CNPJ e só cria um cliente
    novo no provedor se realmente não existir um. Não persiste no banco
    local — quem chama é responsável por gravar o id devolvido, dentro da
    mesma transação da emissão do boleto."""
    if cliente.get("id_externo_asaas"):
        return cliente["id_externo_asaas"]
    encontrado = _buscar_cliente_por_cnpj(config, cliente["cnpj"])
    if encontrado:
        return encontrado
    return _criar_cliente(config, cliente)


def _gerar_no_provedor(config, id_cliente_asaas, valor, vencimento, descricao, referencia):
    requests = _requests()
    base_url = URLS_BASE_ASAAS[config["ambiente"]]
    resp = requests.post(
        f"{base_url}/payments",
        json={
            "customer": id_cliente_asaas, "billingType": "BOLETO",
            "value": round(float(valor), 2), "dueDate": vencimento,
            "description": descricao, "externalReference": referencia,
        },
        headers=_cabecalhos(config["token_api"]), timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    corpo = _tratar_resposta(resp)
    return _resultado_do_pagamento(corpo)


def _consultar_no_provedor(config, id_pagamento_provedor):
    requests = _requests()
    base_url = URLS_BASE_ASAAS[config["ambiente"]]
    resp = requests.get(
        f"{base_url}/payments/{id_pagamento_provedor}",
        headers=_cabecalhos(config["token_api"]), timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    corpo = _tratar_resposta(resp)
    return _resultado_do_pagamento(corpo)


def _cancelar_no_provedor(config, id_pagamento_provedor):
    requests = _requests()
    base_url = URLS_BASE_ASAAS[config["ambiente"]]
    resp = requests.delete(
        f"{base_url}/payments/{id_pagamento_provedor}",
        headers=_cabecalhos(config["token_api"]), timeout=TIMEOUT_PROVEDOR_SEGUNDOS,
    )
    corpo = _tratar_resposta(resp)
    return {
        "status": "cancelado",
        "status_bruto_provedor": "CANCELLED",
        "id_pagamento_provedor": corpo.get("id"),
        "mensagem_provedor": "Cancelado com sucesso." if corpo.get("deleted") else None,
    }


def _resultado_do_pagamento(corpo):
    status_provedor = corpo.get("status")
    status_interno = MAPA_STATUS_PROVEDOR.get(status_provedor, "erro")
    return {
        "status": status_interno,
        "status_bruto_provedor": status_provedor,
        "id_pagamento_provedor": corpo.get("id"),
        "linha_digitavel": corpo.get("identificationField") or corpo.get("nossoNumero"),
        "codigo_barras": corpo.get("barCode"),
        "url_boleto": corpo.get("bankSlipUrl") or corpo.get("invoiceUrl"),
        "mensagem_provedor": corpo.get("description"),
    }


# ============================================================
# ORQUESTRAÇÃO (chamada pelas rotas em app/routes/boletos.py)
# ============================================================
def gerar_referencia(conta_receber_id):
    return f"contareceber{conta_receber_id}-{secrets.token_hex(4)}"


def existe_boleto_ativo_para_conta(conn, conta_receber_id):
    row = conn.execute(
        f"SELECT id FROM boletos WHERE conta_receber_id = ? AND status IN ({','.join('?' * len(STATUS_ATIVOS_BOLETO))})",
        (conta_receber_id, *STATUS_ATIVOS_BOLETO),
    ).fetchone()
    return row is not None
