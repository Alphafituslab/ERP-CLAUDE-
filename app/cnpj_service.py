"""
Fase 101 — Consulta de CNPJ ao cadastrar cliente: busca dados públicos (razão social, nome
fantasia, endereço, e-mail quando disponível) na BrasilAPI (https://brasilapi.com.br), um
agregador público e gratuito de dados abertos do governo brasileiro (Receita Federal, CEP,
bancos etc.) já amplamente usado por sistemas brasileiros — não exige cadastro nem chave de API.

Mapeamento de campos confirmado contra uma resposta real da BrasilAPI durante o desenvolvimento
desta fase (CNPJ de teste, HTTP 200) — não é uma suposição. Ponto de atenção real encontrado
nessa verificação: o payload tem DOIS campos parecidos, `codigo_municipio` (código INTERNO da
BrasilAPI) e `codigo_municipio_ibge` (código OFICIAL do IBGE, o mesmo exigido pela NF-e) — usar
o errado geraria uma NF-e com código de município incorreto, por isso `_mapear_resposta` usa
`codigo_municipio_ibge` como prioridade (ver comentário no local). Os `.get(...)` abaixo
continuam defensivos mesmo assim (nunca derrubam a consulta por um campo faltando) — a
BrasilAPI é um serviço de terceiro fora do controle deste sistema, e o formato pode mudar no
futuro.

Nunca é uma trava: se a consulta falhar (CNPJ não encontrado, provedor fora do ar, sem
internet), o cadastro de cliente continua funcionando 100% manual, exatamente como antes desta
fase — a rota só devolve um erro amigável para a tela mostrar, nunca impede de digitar tudo à
mão em vez de consultar.
"""
import re

from .context import ApiError

TIMEOUT_SEGUNDOS = 10
URL_BASE_BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1"


def _requests():
    try:
        import requests
    except ImportError:
        raise ApiError(
            "A biblioteca 'requests' não está instalada neste ambiente Python — necessária para consultar o CNPJ. "
            "Rode: pip install requests",
            status=500,
        )
    return requests


def _somente_digitos(cnpj):
    return re.sub(r"\D", "", cnpj or "")


def _mapear_resposta(dados):
    """Normaliza a resposta da BrasilAPI para os MESMOS nomes de campo já usados em `clientes`
    (ver CAMPOS_FISCAIS_CLIENTE_EDITAVEIS em app/routes/comercial.py, Fase 70) — assim o
    frontend só precisa jogar o resultado direto nos campos do formulário, sem tradução."""
    endereco_partes = [dados.get("logradouro"), dados.get("numero"), dados.get("bairro")]
    endereco_resumido = ", ".join(p for p in endereco_partes if p) or None
    return {
        "razao_social": dados.get("razao_social"),
        "nome_fantasia": dados.get("nome_fantasia") or None,
        "email": dados.get("email") or None,
        "endereco": endereco_resumido,
        "logradouro": dados.get("logradouro"),
        "numero_endereco": dados.get("numero"),
        "complemento_endereco": dados.get("complemento"),
        "bairro": dados.get("bairro"),
        "municipio": dados.get("municipio"),
        # Confirmado contra uma resposta real da BrasilAPI (Fase 101): o
        # payload tem DOIS campos parecidos — `codigo_municipio` é um
        # código INTERNO da BrasilAPI (ex.: 8893), `codigo_municipio_ibge`
        # é o código OFICIAL do IBGE (ex.: 4319505, 7 dígitos) — o mesmo
        # que a NF-e exige. Usar o campo errado geraria uma NF-e com
        # código de município incorreto; por isso `codigo_municipio_ibge`
        # vem PRIMEIRO aqui, nunca o outro como alternativa preferencial.
        "codigo_ibge_municipio": dados.get("codigo_municipio_ibge") or dados.get("codigo_municipio"),
        "uf": dados.get("uf"),
        "cep": dados.get("cep"),
        # Situação cadastral — só INFORMATIVO na tela (ex.: avisar se a
        # empresa consultada consta como "BAIXADA"/inativa na Receita);
        # nunca bloqueia o cadastro, decisão de negócio continua sendo de
        # quem está cadastrando.
        "situacao_cadastral": dados.get("descricao_situacao_cadastral"),
    }


def consultar_cnpj(cnpj):
    cnpj_limpo = _somente_digitos(cnpj)
    if len(cnpj_limpo) != 14:
        raise ApiError("CNPJ inválido — informe os 14 dígitos.", status=400)

    requests = _requests()
    try:
        resp = requests.get(f"{URL_BASE_BRASILAPI}/{cnpj_limpo}", timeout=TIMEOUT_SEGUNDOS)
    except requests.exceptions.RequestException as erro:
        raise ApiError(f"Não foi possível consultar o CNPJ agora (falha de conexão): {erro}", status=502)

    if resp.status_code == 404:
        raise ApiError("CNPJ não encontrado na Receita Federal.", status=404)
    if not resp.ok:
        raise ApiError(f"O serviço de consulta de CNPJ devolveu um erro (status {resp.status_code}).", status=502)

    try:
        dados = resp.json()
    except ValueError:
        raise ApiError("O serviço de consulta de CNPJ devolveu uma resposta inesperada.", status=502)

    return _mapear_resposta(dados)
