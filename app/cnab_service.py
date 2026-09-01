"""
Fase 126 — Boleto bancário via CNAB 240 direto com Sicredi (748) e
Unicred (136), substituindo por completo a integração com o Asaas
(Fase 71 — nunca teve nenhum boleto real gerado em produção, substituição
segura). Ver a nota de escopo completa em migrations/schema_fase126.sql.

AVISO IMPORTANTE, repetido na tela de configuração: este módulo implementa
o layout FEBRABAN/CNAB 240 documentado publicamente. As partes abaixo têm
NÍVEIS DE CONFIANÇA DIFERENTES:

  - Header de Arquivo, Trailer de Lote, Trailer de Arquivo, e o cálculo
    de dígito verificador (módulo 11 geral do código de barras, módulo 10
    de cada campo da linha digitável): padrão FEBRABAN universal, igual
    em qualquer banco — alta confiança.
  - Header de Lote e Segmentos P/Q (dados de cada título): seguem o
    layout padrão de cobrança FEBRABAN, mas o "campo livre" de 25
    dígitos do código de barras (posições 20-44) É ESPECÍFICO DE CADA
    BANCO — cada banco define o que vai ali (geralmente uma combinação
    de agência/conta/carteira/nosso número, mas a ORDEM e o TAMANHO de
    cada pedaço varia). Sem o "Manual de Especificação Técnica" que o
    Sicredi/Unicred fornecem, isso está com uma estrutura RAZOÁVEL mas
    NÃO CONFIRMADA — marcado explicitamente abaixo em `_campo_livre()`.

NUNCA gerar uma remessa de verdade para enviar ao banco antes de validar
_campo_livre() e a posição exata de cada campo do Segmento P contra o
manual do banco. Até lá, isto serve pra estruturar o fluxo (config,
emissão local, geração de arquivo, leitura de retorno) e pode ser testado
em ambiente de homologação do próprio banco, se ele oferecer.
"""
import datetime

from .context import ApiError

BANCOS = {
    "748": "Sicredi",
    "136": "Unicred",
}

# Fator de vencimento do código de barras: dias corridos desde uma
# data-base, começando em 1000 (padrão FEBRABAN histórico, data-base
# 07/10/1997). Esse campo tem só 4 posições (máximo 9999), o que fazia o
# contador estourar em 21/02/2025 — a FEBRABAN publicou a "Nova
# Sistemática de Fator de Vencimento" reiniciando o contador em 1000 a
# partir de 22/02/2025. Como o fator de vencimento sozinho não diz mais
# em qual "ciclo" (antigo/novo) o título está, bancos que adotaram a nova
# sistemática (Sicredi/Unicred inclusos, pelo que é público) tratam TODO
# vencimento a partir de 22/02/2025 como pertencente ao novo ciclo — não
# há mais ambiguidade na prática porque o ciclo antigo não alcança mais
# nenhuma data futura. NÃO CONFIRMADO contra o manual do banco (mesma
# ressalva do topo do arquivo) — se o banco documentar uma data-base
# diferente, só este bloco precisa mudar.
_DATA_BASE_FATOR_VENCIMENTO_ANTIGA = datetime.date(1997, 10, 7)
_DATA_BASE_FATOR_VENCIMENTO_NOVA = datetime.date(2025, 2, 22)

# Códigos de ocorrência do CNAB 240 de retorno que indicam que o título
# foi efetivamente pago — mapeamento conservador: só os códigos
# claramente documentados como liquidação entram aqui; qualquer código
# não reconhecido é gravado em `ultima_ocorrencia_retorno` mas NÃO gera
# baixa automática (mesmo princípio de app/boleto_service.py — nunca
# assumir "pago" por padrão diante de um código desconhecido).
OCORRENCIAS_LIQUIDACAO = {"06", "17"}  # 06=Liquidação normal, 17=Liquidação após baixa/protesto
OCORRENCIAS_BAIXA = {"09", "10"}  # 09=Baixado automaticamente, 10=Baixado conforme instruções


def config_publica(config: dict) -> dict:
    return dict(config)


def obter_configuracao(conn) -> dict:
    row = conn.execute("SELECT * FROM configuracoes_boleto WHERE id = 1").fetchone()
    return dict(row)


CAMPOS_CONFIGURAVEIS = (
    "banco_codigo", "ambiente", "agencia", "digito_agencia", "conta", "digito_conta",
    "carteira", "convenio", "codigo_cedente",
)


def salvar_configuracao(conn, dados: dict, usuario_id: int) -> dict:
    anterior = obter_configuracao(conn)
    banco_codigo = dados.get("banco_codigo", anterior["banco_codigo"])
    if banco_codigo is not None and banco_codigo not in BANCOS:
        raise ApiError(f"banco_codigo deve ser um de: {', '.join(BANCOS)} (748=Sicredi, 136=Unicred).", status=400)
    ambiente = dados.get("ambiente", anterior["ambiente"])
    if ambiente not in ("homologacao", "producao"):
        raise ApiError("ambiente deve ser 'homologacao' ou 'producao'.", status=400)

    valores = {campo: dados.get(campo, anterior[campo]) for campo in CAMPOS_CONFIGURAVEIS}
    conn.execute(
        f"""
        UPDATE configuracoes_boleto SET {', '.join(f'{c} = ?' for c in CAMPOS_CONFIGURAVEIS)},
               atualizado_em = ?, atualizado_por = ?
        WHERE id = 1
        """,
        (*[valores[c] for c in CAMPOS_CONFIGURAVEIS], _now_iso(), usuario_id),
    )
    return obter_configuracao(conn)


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validar_config_completa(config: dict):
    obrigatorios = ("banco_codigo", "agencia", "conta", "carteira", "convenio", "codigo_cedente")
    faltando = [c for c in obrigatorios if not config.get(c)]
    if faltando:
        raise ApiError(
            f"Configuração de boleto incompleta — falta preencher: {', '.join(faltando)} "
            "(Financeiro > Configuração de Boleto).",
            status=400,
        )


# ============================================================
# FORMATAÇÃO DE CAMPO (fixed-width, padrão CNAB)
# ============================================================
def _alfa(valor, tamanho):
    """Campo alfanumérico: maiúsculo, alinhado à esquerda, preenchido
    com espaço à direita, sem acentuação (CNAB não define encoding além
    de ASCII/Latin, então acento vira o mais próximo sem acento)."""
    texto = (str(valor) if valor is not None else "").upper()
    substituicoes = str.maketrans("ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ", "AAAAAEEEEIIIIOOOOOUUUUCN")
    texto = texto.translate(substituicoes)
    texto = "".join(c for c in texto if c.isalnum() or c == " ")
    return texto[:tamanho].ljust(tamanho)


def _num(valor, tamanho):
    """Campo numérico: alinhado à direita, preenchido com zero à
    esquerda. Aceita None (vira tudo zero) — várias posições reservadas
    do CNAB são numéricas e ficam zeradas quando não usadas."""
    if valor is None or valor == "":
        valor = 0
    texto = "".join(c for c in str(valor) if c.isdigit())
    if len(texto) > tamanho:
        raise ApiError(f"Campo numérico '{valor}' não cabe em {tamanho} posições.", status=400)
    return texto.zfill(tamanho)


def _brancos(tamanho):
    return " " * tamanho


def _zeros(tamanho):
    return "0" * tamanho


# ============================================================
# DÍGITOS VERIFICADORES (módulo 11 e módulo 10 — padrão FEBRABAN,
# idêntico em qualquer banco)
# ============================================================
def _modulo11_dv_geral(quarenta_e_tres_digitos: str) -> str:
    """DV geral do código de barras (posição 5) — módulo 11 com pesos
    2..9 cíclicos, calculado da direita pra esquerda sobre as outras 43
    posições do código de barras."""
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = 0
    for i, digito in enumerate(reversed(quarenta_e_tres_digitos)):
        soma += int(digito) * pesos[i % len(pesos)]
    resto = soma % 11
    if resto in (0, 1):
        return "1"
    return str(11 - resto)


def _modulo10_dv_campo(digitos: str) -> str:
    """DV de cada um dos 3 primeiros campos da linha digitável —
    módulo 10 com pesos 2/1 alternados da direita pra esquerda; quando o
    produto passa de 9, soma os dois algarismos do resultado (regra
    clássica do módulo 10 bancário, igual em cartão de crédito/EAN)."""
    pesos = [2, 1]
    soma = 0
    for i, digito in enumerate(reversed(digitos)):
        produto = int(digito) * pesos[i % 2]
        soma += produto if produto < 10 else (produto - 9)
    resto = soma % 10
    return "0" if resto == 0 else str(10 - resto)


def _fator_vencimento(vencimento_iso: str) -> int:
    data = datetime.date.fromisoformat(vencimento_iso)
    if data >= _DATA_BASE_FATOR_VENCIMENTO_NOVA:
        return 1000 + (data - _DATA_BASE_FATOR_VENCIMENTO_NOVA).days
    return 1000 + (data - _DATA_BASE_FATOR_VENCIMENTO_ANTIGA).days


def _campo_livre(config: dict, nosso_numero: str) -> str:
    """25 dígitos — ESPECÍFICO DE CADA BANCO, ver aviso no topo do
    arquivo. Estrutura provisória usada aqui (carteira + agência + conta
    + nosso número, tudo numérico) É UM PALPITE RAZOÁVEL baseado no
    padrão mais comum entre cooperativas de crédito, NÃO confirmado
    contra o manual do Sicredi/Unicred. Ajustar aqui assim que o manual
    chegar — é o único lugar que precisa mudar."""
    return (
        _num(config["carteira"], 2)
        + _num(config["agencia"], 4)
        + _num(config["conta"], 8)
        + _num(nosso_numero, 11)
    )


def gerar_codigo_barras_e_linha_digitavel(config: dict, nosso_numero: str, valor: float, vencimento_iso: str):
    _validar_config_completa(config)
    fator = _fator_vencimento(vencimento_iso)
    if fator < 0 or fator > 9999:
        raise ApiError("Vencimento fora da faixa representável pelo fator de vencimento do código de barras (padrão FEBRABAN).", status=400)
    valor_centavos = round(valor * 100)

    campo_livre = _campo_livre(config, nosso_numero)
    if len(campo_livre) != 25:
        raise ApiError("campo livre do código de barras precisa ter exatamente 25 posições — revisar _campo_livre().", status=500)

    corpo_sem_dv = (
        config["banco_codigo"]
        + "9"  # código da moeda: Real
        + _num(fator, 4)
        + _num(valor_centavos, 10)
        + campo_livre
    )
    if len(corpo_sem_dv) != 43:
        raise ApiError(f"código de barras malformado: {len(corpo_sem_dv)} posições antes do DV (esperado 43).", status=500)
    dv_geral = _modulo11_dv_geral(corpo_sem_dv)
    codigo_barras = corpo_sem_dv[:4] + dv_geral + corpo_sem_dv[4:]

    campo1_base = codigo_barras[0:4] + codigo_barras[19:24]
    campo2_base = codigo_barras[24:34]
    campo3_base = codigo_barras[34:44]
    campo1 = campo1_base + _modulo10_dv_campo(campo1_base)
    campo2 = campo2_base + _modulo10_dv_campo(campo2_base)
    campo3 = campo3_base + _modulo10_dv_campo(campo3_base)
    campo4 = dv_geral
    campo5 = _num(fator, 4) + _num(valor_centavos, 10)
    linha_digitavel = f"{campo1} {campo2} {campo3} {campo4} {campo5}"

    return codigo_barras, linha_digitavel


# ============================================================
# REMESSA (arquivo enviado ao banco) — CNAB 240
# ============================================================
def montar_remessa(config: dict, empresa: dict, boletos: list) -> str:
    """Monta o conteúdo (texto, linhas de 240 posições, separadas por
    \\r\\n conforme padrão FEBRABAN) de um arquivo de remessa contendo
    todos os `boletos` informados. `empresa` precisa ter razao_social e
    cnpj. Não grava nada no banco — só monta o texto; quem chama decide
    o que fazer com o resultado (baixar, registrar em cnab_remessas)."""
    _validar_config_completa(config)
    if not boletos:
        raise ApiError("Nenhum boleto informado para gerar remessa.", status=400)

    agora = datetime.datetime.utcnow()
    numero_arquivo = config["proximo_numero_remessa"]
    linhas = []

    # Header de Arquivo (registro 0)
    linhas.append(
        config["banco_codigo"]
        + "0000"
        + "0"
        + _brancos(9)
        + "2"  # tipo de inscrição: CNPJ
        + _num(empresa["cnpj"], 14)
        + _alfa(config["convenio"], 20)
        + _num(config["agencia"], 5)
        + _alfa(config.get("digito_agencia") or "", 1)
        + _num(config["conta"], 12)
        + _alfa(config.get("digito_conta") or "", 1)
        + _brancos(1)  # DV agência/conta
        + _alfa(empresa["razao_social"], 30)
        + _alfa(BANCOS.get(config["banco_codigo"], ""), 30)
        + _brancos(1)
        + "1"  # 1=remessa
        + agora.strftime("%d%m%Y")
        + agora.strftime("%H%M%S")
        + _num(numero_arquivo, 7)
        + "103"  # versão do layout
        + _num(1600, 5)  # densidade de gravação (valor convencional, 1600 BPI)
        + _brancos(28)
        + _brancos(20)
        + _brancos(29)
    )

    # Header de Lote (registro 1) — tipo de serviço 01 = Cobrança
    linhas.append(
        config["banco_codigo"]
        + "0001"
        + "1"
        + "R"  # tipo de operação: remessa
        + "01"  # tipo de serviço: cobrança
        + _brancos(2)
        + "040"  # versão do layout do lote
        + _brancos(1)
        + "2"
        + _num(empresa["cnpj"], 14)
        + _alfa(config["convenio"], 20)
        + _num(config["agencia"], 5)
        + _alfa(config.get("digito_agencia") or "", 1)
        + _num(config["conta"], 12)
        + _alfa(config.get("digito_conta") or "", 1)
        + _brancos(1)
        + _alfa(empresa["razao_social"], 30)
        + _brancos(40)  # mensagem 1
        + _brancos(40)  # mensagem 2
        + _num(numero_arquivo, 8)
        + _brancos(8)
        + _brancos(42)
    )

    quantidade_registros_lote = 2  # header de lote + trailer de lote, incrementado abaixo por título
    numero_registro = 2
    for boleto in boletos:
        numero_registro += 1
        # Segmento P — dados do título
        linhas.append(
            config["banco_codigo"]
            + "0001"
            + "3"
            + _num(numero_registro, 5)
            + "P"
            + _brancos(1)
            + "01"  # código de movimento: 01=entrada de título
            + _num(config["agencia"], 5)
            + _alfa(config.get("digito_agencia") or "", 1)
            + _num(config["conta"], 12)
            + _alfa(config.get("digito_conta") or "", 1)
            + _brancos(1)
            + _num(config["carteira"], 3)
            + _num(boleto["nosso_numero"], 11)
            + _num(config["carteira"], 1)  # código da carteira
            + "1"  # cadastramento: 1=registrada
            + "2"  # tipo de documento: duplicata mercantil
            + "2"  # emissão do boleto: banco emite
            + "3"  # distribuição: banco distribui (não emite via sistema próprio ainda)
            + _alfa(str(boleto["numero"]), 15)  # número do documento (nosso número de venda)
            + datetime.date.fromisoformat(boleto["vencimento"]).strftime("%d%m%Y")
            + _num(round(boleto["valor"] * 100), 15)
            + "0000"  # agência cobradora (não usado)
            + "0"
            + "02"  # espécie do título: 02=duplicata mercantil
            + "N"  # aceite: não
            + agora.strftime("%d%m%Y")
            + "00"  # instrução 1
            + "00"  # instrução 2
            + _num(0, 13)  # valor de mora ao dia
            + "00000000"  # data limite de desconto (nenhum)
            + _num(0, 15)  # valor de desconto
            + _num(0, 15)  # valor de IOF
            + _num(0, 15)  # valor de abatimento
            + _alfa(str(boleto["numero"]), 25)  # número de controle do participante
            + "00"  # código do protesto/negativação: sem instrução
            + _num(0, 2)
            + "0"
            + _brancos(30)  # uso do banco / campos residuais do Segmento P não mapeados aqui — ver aviso no topo do arquivo
        )
        numero_registro += 1
        cliente = boleto["cliente"]
        # Segmento Q — dados do sacado (pagador)
        linhas.append(
            config["banco_codigo"]
            + "0001"
            + "3"
            + _num(numero_registro, 5)
            + "Q"
            + _brancos(1)
            + "01"
            + "2"  # tipo de inscrição do sacado: CNPJ
            + _num(cliente["cnpj"], 15)
            + _alfa(cliente["razao_social"], 40)
            + _alfa(cliente.get("logradouro") or cliente.get("endereco") or "", 40)
            + _alfa(cliente.get("numero_endereco") or "", 5)
            + _alfa(cliente.get("complemento_endereco") or "", 15)
            + _alfa(cliente.get("bairro") or "", 15)
            + _num((cliente.get("cep") or "").replace("-", ""), 8)
            + _alfa(cliente.get("municipio") or "", 15)
            + _alfa(cliente.get("uf") or "", 2)
            + "0" * 1  # tipo inscrição do sacador/avalista: nenhum
            + _num(0, 15)
            + _brancos(40)
            + _brancos(11)  # uso do banco / campos residuais do Segmento Q não mapeados aqui — ver aviso no topo do arquivo
        )
        quantidade_registros_lote += 2

    # Trailer de Lote (registro 5)
    numero_registro += 1
    quantidade_registros_lote = numero_registro  # inclui header (1) + segmentos + este trailer
    linhas.append(
        config["banco_codigo"]
        + "0001"
        + "5"
        + _brancos(9)
        + _num(quantidade_registros_lote, 6)
        + _num(0, 6)  # quantidade de títulos em cobrança (uso do banco no retorno)
        + _num(0, 17)  # valor total dos títulos (uso do banco no retorno)
        + _brancos(8)
        + _num(0, 6)
        + _brancos(180)
    )

    # Trailer de Arquivo (registro 9)
    total_linhas = len(linhas) + 1
    linhas.append(
        config["banco_codigo"]
        + "9999"
        + "9"
        + _brancos(9)
        + _num(1, 6)  # quantidade de lotes
        + _num(total_linhas, 6)
        + _brancos(6)
        + _brancos(205)
    )

    for i, linha in enumerate(linhas):
        if len(linha) != 240:
            raise ApiError(f"linha {i + 1} da remessa ficou com {len(linha)} posições (esperado 240) — revisar montar_remessa().", status=500)

    return "\r\n".join(linhas) + "\r\n"


# ============================================================
# RETORNO (arquivo que o banco devolve) — CNAB 240
# ============================================================
def processar_retorno(conteudo: str):
    """Lê um arquivo de retorno CNAB 240 e devolve uma lista de
    ocorrências: [{"nosso_numero": ..., "codigo_ocorrencia": ...,
    "valor_pago": ..., "data_ocorrencia": ...}, ...] — uma por Segmento T
    (ou P, dependendo do banco) encontrado. Não grava nada no banco;
    quem chama (rota) decide o que fazer com cada ocorrência."""
    ocorrencias = []
    for linha in conteudo.splitlines():
        linha = linha.rstrip("\r\n")
        if len(linha) < 8:
            continue
        tipo_registro = linha[7]
        if tipo_registro != "3":
            continue  # só registros de detalhe (segmento) interessam aqui
        segmento = linha[13] if len(linha) > 13 else ""
        if segmento not in ("T", "P"):
            continue
        try:
            codigo_ocorrencia = linha[15:17]
            nosso_numero = linha[37:57].strip().lstrip("0") or "0"
            data_ocorrencia = linha[137:145]  # DDMMAAAA
            valor_pago = int(linha[152:167]) / 100.0
        except (ValueError, IndexError):
            continue
        ocorrencias.append({
            "nosso_numero": nosso_numero,
            "codigo_ocorrencia": codigo_ocorrencia,
            "valor_pago": valor_pago,
            "data_ocorrencia_ddmmaaaa": data_ocorrencia,
        })
    return ocorrencias
