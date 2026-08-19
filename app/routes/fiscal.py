"""
Fase 70 — Fiscal: rotas HTTP finas em cima de app/nfe_service.py (mesmo
padrão de app/routes/sistema.py em cima de app/backup_service.py, Fase 67).
"""
import datetime
import sqlite3

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import nfe_service
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("fiscal", __name__, url_prefix="/api/v1/fiscal")


def _empresa_ou_404(conn, empresa_id):
    row = conn.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if row is None:
        raise ApiError("Empresa não encontrada.", status=404)
    return dict(row)


def _cliente_ou_404(conn, cliente_id):
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if row is None:
        raise ApiError("Cliente não encontrado.", status=404)
    return dict(row)


def _pedido_ou_404(conn, pedido_id):
    row = conn.execute("SELECT * FROM pedidos_venda WHERE id = ?", (pedido_id,)).fetchone()
    if row is None:
        raise ApiError("Pedido de venda não encontrado.", status=404)
    return dict(row)


def _itens_pedido_com_dados_fiscais(conn, pedido_id):
    rows = conn.execute(
        """
        SELECT pvi.*, i.codigo AS item_codigo, i.descricao AS item_descricao,
               i.ncm AS item_ncm, i.cfop_padrao AS item_cfop_padrao,
               i.origem_mercadoria AS item_origem_mercadoria, i.cest AS item_cest,
               i.codigo_tributario_icms AS item_codigo_tributario_icms
        FROM pedido_venda_itens pvi JOIN itens i ON i.id = pvi.item_id
        WHERE pvi.pedido_id = ? ORDER BY pvi.id
        """,
        (pedido_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _nota_ou_404(conn, nota_id):
    row = conn.execute("SELECT * FROM notas_fiscais WHERE id = ?", (nota_id,)).fetchone()
    if row is None:
        raise ApiError("Nota fiscal não encontrada.", status=404)
    return dict(row)


def _nota_detalhada(conn, nota_id):
    nota = _nota_ou_404(conn, nota_id)
    itens = conn.execute(
        "SELECT * FROM notas_fiscais_itens WHERE nota_fiscal_id = ? ORDER BY id", (nota_id,)
    ).fetchall()
    nota["itens"] = [dict(i) for i in itens]
    pedido = conn.execute("SELECT numero FROM pedidos_venda WHERE id = ?", (nota["pedido_id"],)).fetchone()
    nota["pedido_numero"] = pedido["numero"] if pedido else None
    return nota


# ============================================================
# CONFIGURAÇÃO
# ============================================================
@bp.get("/configuracao")
@requires_permission("fiscal", "configurar")
def obter_configuracao():
    conn = get_db()
    return jsonify(nfe_service.config_publica(nfe_service.obter_configuracao(conn)))


@bp.put("/configuracao")
@requires_permission("fiscal", "configurar")
def atualizar_configuracao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = nfe_service.obter_configuracao(conn)

    nova = nfe_service.salvar_configuracao(conn, dados, usuario_atual["id"])

    audit.registrar(
        conn, tabela="configuracoes_nfe", registro_id=1, usuario_id=usuario_atual["id"],
        acao="configuracao_nfe_atualizada",
        valor_anterior={"provedor": anterior.get("provedor"), "ambiente": anterior.get("ambiente"), "serie": anterior.get("serie")},
        valor_novo={"provedor": nova.get("provedor"), "ambiente": nova.get("ambiente"), "serie": nova.get("serie")},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(nfe_service.config_publica(nova))


# ============================================================
# NOTAS FISCAIS
# ============================================================
@bp.get("/notas")
@requires_permission("fiscal", "visualizar")
def listar_notas():
    conn = get_db()
    pedido_id = request.args.get("pedido_id", type=int)
    if pedido_id:
        rows = conn.execute(
            "SELECT * FROM notas_fiscais WHERE pedido_id = ? ORDER BY id DESC", (pedido_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM notas_fiscais ORDER BY id DESC LIMIT 500").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/notas/<int:nota_id>")
@requires_permission("fiscal", "visualizar")
def obter_nota(nota_id):
    conn = get_db()
    return jsonify(_nota_detalhada(conn, nota_id))


@bp.post("/pedidos/<int:pedido_id>/emitir")
@requires_permission("fiscal", "emitir")
def emitir_nfe(pedido_id):
    usuario_atual = g.usuario_atual
    conn = get_db()

    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] != "expedido":
        raise ApiError("Só é possível emitir NF-e de um pedido já expedido.", status=400)
    if nfe_service.existe_nota_ativa_para_pedido(conn, pedido_id):
        raise ApiError("Já existe uma NF-e ativa (processando ou autorizada) para este pedido.", status=409)
    if not pedido["empresa_id"]:
        raise ApiError(
            "Este pedido não tem uma empresa emissora definida (criado sem selecionar 'empresa'). "
            "Não é possível saber qual empresa deve emitir a nota — crie um novo pedido informando a empresa.",
            status=400,
        )

    config = nfe_service.obter_configuracao(conn)
    if not config.get("token_api"):
        raise ApiError("Configure o token de API do provedor de NF-e antes de emitir (Fiscal > Configuração).", status=400)

    empresa = _empresa_ou_404(conn, pedido["empresa_id"])
    cliente = _cliente_ou_404(conn, pedido["cliente_id"])
    itens_pedido = _itens_pedido_com_dados_fiscais(conn, pedido_id)
    if not itens_pedido:
        raise ApiError("Pedido sem itens — não é possível emitir NF-e.", status=400)

    # Normaliza os nomes que validar_pronto_para_emitir espera (ncm/cfop
    # direto, não item_ncm/item_cfop_padrao) sem duplicar a query.
    itens_para_validar = [
        {**it, "ncm": it.get("item_ncm"), "cfop_padrao": it.get("item_cfop_padrao")}
        for it in itens_pedido
    ]
    nfe_service.validar_pronto_para_emitir(conn, empresa, cliente, itens_para_validar)

    referencia = nfe_service.gerar_referencia(pedido_id)
    payload, valor_total = nfe_service.montar_payload_focus_nfe(pedido, empresa, cliente, itens_pedido, referencia)
    resultado = nfe_service._enviar_para_provedor(config, payload, referencia)

    serie = config["serie"]
    numero = nfe_service.proximo_numero(conn, pedido["empresa_id"], serie)

    # Fase 72 (auditoria de segurança): a checagem `existe_nota_ativa_para_
    # pedido` acima e o cálculo de `numero` já rodaram, mas nada os torna
    # atômicos com o INSERT abaixo — duas emissões concorrentes para o
    # mesmo pedido (ou para a mesma empresa+série) poderiam ambas passar
    # pelas checagens em Python antes de qualquer uma gravar. Os índices
    # únicos `idx_notas_fiscais_pedido_ativa_unica` e `idx_notas_fiscais_
    # numero_unico_por_empresa_serie` (schema_fase72.sql) são a garantia
    # de verdade, aplicada pelo próprio banco; aqui só traduzimos a
    # IntegrityError que uma corrida perdida geraria numa resposta 409
    # amigável, em vez de deixá-la virar um 500 genérico.
    try:
        cur = conn.execute(
            """
            INSERT INTO notas_fiscais
                (empresa_id, pedido_id, serie, numero, ambiente, status, referencia_provedor,
                 chave_acesso, protocolo_autorizacao, mensagem_sefaz, url_danfe, url_xml,
                 valor_total, criado_por, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pedido["empresa_id"], pedido_id, serie, numero, config["ambiente"], resultado["status"], referencia,
                resultado.get("chave_acesso"), resultado.get("protocolo_autorizacao"), resultado.get("mensagem_sefaz"),
                resultado.get("url_danfe"), resultado.get("url_xml"),
                valor_total, usuario_atual["id"], nfe_service._now_iso(),
            ),
        )
    except sqlite3.IntegrityError:
        raise ApiError(
            "Já existe uma NF-e ativa para este pedido, ou o número calculado já foi usado — "
            "outra emissão para o mesmo pedido/empresa/série provavelmente aconteceu ao mesmo "
            "tempo. Consulte as notas fiscais deste pedido antes de tentar de novo.",
            status=409,
        )
    nota_id = cur.lastrowid

    for linha in payload["items"]:
        item_original = itens_pedido[linha["numero_item"] - 1]
        conn.execute(
            """
            INSERT INTO notas_fiscais_itens
                (nota_fiscal_id, item_id, descricao, ncm, cfop, origem_mercadoria,
                 codigo_tributario_icms, quantidade, unidade, valor_unitario, valor_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nota_id, item_original["item_id"], linha["descricao"], linha["ncm"], linha["cfop"],
                linha["icms_origem"], linha["icms_situacao_tributaria"], linha["quantidade_comercial"],
                linha["unidade_comercial"], linha["valor_unitario_comercial"], linha["valor_bruto"],
            ),
        )

    audit.registrar(
        conn, tabela="notas_fiscais", registro_id=nota_id, usuario_id=usuario_atual["id"],
        acao="nfe_emissao_solicitada",
        valor_novo={"pedido_id": pedido_id, "ambiente": config["ambiente"], "referencia": referencia, "status": resultado["status"]},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_nota_detalhada(conn, nota_id)), 201


@bp.post("/notas/<int:nota_id>/consultar-status")
@requires_permission("fiscal", "visualizar")
def consultar_status(nota_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    nota = _nota_ou_404(conn, nota_id)

    if nota["status"] not in ("processando_autorizacao",):
        # Já é um status final (autorizada/rejeitada/cancelada/erro) — não
        # há nada novo para consultar; devolve o que já temos gravado sem
        # gastar uma chamada de rede à toa.
        return jsonify(_nota_detalhada(conn, nota_id))

    config = nfe_service.obter_configuracao(conn)
    resultado = nfe_service._consultar_no_provedor(config, nota["referencia_provedor"])

    conn.execute(
        """
        UPDATE notas_fiscais SET status = ?, chave_acesso = ?, protocolo_autorizacao = ?,
               mensagem_sefaz = ?, url_danfe = ?, url_xml = ?, atualizado_em = ?
        WHERE id = ?
        """,
        (
            resultado["status"], resultado.get("chave_acesso"), resultado.get("protocolo_autorizacao"),
            resultado.get("mensagem_sefaz"), resultado.get("url_danfe"), resultado.get("url_xml"),
            nfe_service._now_iso(), nota_id,
        ),
    )
    audit.registrar(
        conn, tabela="notas_fiscais", registro_id=nota_id, usuario_id=usuario_atual["id"],
        acao="nfe_status_consultado", valor_anterior={"status": nota["status"]}, valor_novo={"status": resultado["status"]},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_nota_detalhada(conn, nota_id))


@bp.post("/notas/<int:nota_id>/cancelar")
@requires_permission("fiscal", "cancelar")
def cancelar_nota(nota_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    justificativa = (dados.get("justificativa") or "").strip()
    conn = get_db()
    nota = _nota_ou_404(conn, nota_id)

    if nota["status"] != "autorizada":
        raise ApiError("Só é possível cancelar uma NF-e já autorizada.", status=400)
    # Mesmo mínimo de 15 caracteres exigido pela SEFAZ para a justificativa
    # de cancelamento (Ajuste SINIEF 07/05) — validado aqui para dar um erro
    # claro antes de gastar a chamada ao provedor.
    if len(justificativa) < 15:
        raise ApiError("A justificativa de cancelamento precisa ter ao menos 15 caracteres (exigência da SEFAZ).", status=400)

    config = nfe_service.obter_configuracao(conn)
    nfe_service._cancelar_no_provedor(config, nota["referencia_provedor"], justificativa)

    conn.execute(
        "UPDATE notas_fiscais SET status = 'cancelada', justificativa_cancelamento = ?, cancelada_em = ?, cancelada_por = ?, atualizado_em = ? WHERE id = ?",
        (justificativa, nfe_service._now_iso(), usuario_atual["id"], nfe_service._now_iso(), nota_id),
    )
    audit.registrar(
        conn, tabela="notas_fiscais", registro_id=nota_id, usuario_id=usuario_atual["id"],
        acao="nfe_cancelada", valor_anterior={"status": "autorizada"}, valor_novo={"status": "cancelada", "justificativa": justificativa},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_nota_detalhada(conn, nota_id))


# ============================================================
# NOTAS FISCAIS DE ENTRADA (Fase 78 — SPED Fiscal 1/5)
#
# Captura estruturada dos dados de uma nota de COMPRA (fornecedor) — hoje o
# único registro disso era `lotes.nota_fiscal`, um campo de texto livre sem
# CFOP/CST/imposto nenhum. Isto é só DIGITAÇÃO do que já está na nota em
# papel/PDF do fornecedor: nenhuma alíquota é calculada ou sugerida aqui —
# quem lança informa os valores exatamente como aparecem no documento. As
# fases seguintes do projeto de SPED Fiscal (apuração de ICMS/IPI, etc.) é
# que vão USAR esses dados, com parâmetros confirmados pelo contador.
# ============================================================
def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _fornecedor_ou_404(conn, fornecedor_id):
    row = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    if row is None:
        raise ApiError("Fornecedor não encontrado.", status=404)
    return dict(row)


def _nota_entrada_ou_404(conn, nota_id):
    row = conn.execute("SELECT * FROM notas_fiscais_entrada WHERE id = ?", (nota_id,)).fetchone()
    if row is None:
        raise ApiError("Nota fiscal de entrada não encontrada.", status=404)
    return dict(row)


def _nota_entrada_detalhada(conn, nota_id):
    nota = _nota_entrada_ou_404(conn, nota_id)
    fornecedor = conn.execute("SELECT nome, cnpj FROM fornecedores WHERE id = ?", (nota["fornecedor_id"],)).fetchone()
    nota["fornecedor_nome"] = fornecedor["nome"] if fornecedor else None
    nota["fornecedor_cnpj"] = fornecedor["cnpj"] if fornecedor else None
    itens = conn.execute(
        """
        SELECT nfei.*, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM notas_fiscais_entrada_itens nfei JOIN itens i ON i.id = nfei.item_id
        WHERE nfei.nota_fiscal_entrada_id = ? ORDER BY nfei.id
        """,
        (nota_id,),
    ).fetchall()
    nota["itens"] = [dict(i) for i in itens]
    return nota


def _numero_obrigatorio_ou_padrao(valor, campo, minimo=None, padrao=None):
    """Converte `valor` em float — se ausente/vazio, usa `padrao` (quando
    informado) em vez de exigir o campo; do contrário levanta ApiError. Uso
    duplo (campo realmente obrigatório vs. campo numérico opcional com
    padrão 0) evita duas funções quase idênticas."""
    if valor is None or valor == "":
        if padrao is not None:
            return padrao
        raise ApiError(f"Informe {campo}.", status=400)
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ApiError(f"{campo} deve ser numérico.", status=400)
    if minimo is not None and valor < minimo:
        raise ApiError(f"{campo} não pode ser menor que {minimo}.", status=400)
    return valor


@bp.get("/notas-entrada")
@requires_permission("fiscal", "visualizar")
def listar_notas_entrada():
    conn = get_db()
    fornecedor_id = request.args.get("fornecedor_id", type=int)
    status = request.args.get("status")
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")

    clausulas, params = [], []
    if fornecedor_id:
        clausulas.append("nfe.fornecedor_id = ?")
        params.append(fornecedor_id)
    if status:
        clausulas.append("nfe.status = ?")
        params.append(status)
    if data_inicio:
        clausulas.append("nfe.data_entrada >= ?")
        params.append(data_inicio)
    if data_fim:
        clausulas.append("nfe.data_entrada <= ?")
        params.append(data_fim)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""

    rows = conn.execute(
        f"""
        SELECT nfe.*, f.nome AS fornecedor_nome, f.cnpj AS fornecedor_cnpj
        FROM notas_fiscais_entrada nfe JOIN fornecedores f ON f.id = nfe.fornecedor_id
        {where}
        ORDER BY nfe.data_entrada DESC, nfe.id DESC
        LIMIT 500
        """,
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/notas-entrada/<int:nota_id>")
@requires_permission("fiscal", "visualizar")
def obter_nota_entrada(nota_id):
    conn = get_db()
    return jsonify(_nota_entrada_detalhada(conn, nota_id))


@bp.post("/notas-entrada")
@requires_permission("fiscal", "registrar_entrada")
def criar_nota_entrada():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    fornecedor_id = dados.get("fornecedor_id")
    serie = (dados.get("serie") or "").strip()
    numero = (dados.get("numero") or "").strip()
    modelo = dados.get("modelo") or "55"
    data_emissao = (dados.get("data_emissao") or "").strip()
    data_entrada = (dados.get("data_entrada") or "").strip()
    itens = dados.get("itens") or []

    if not fornecedor_id:
        raise ApiError("Informe fornecedor_id.", status=400)
    if not serie or not numero:
        raise ApiError("Informe serie e numero.", status=400)
    if modelo not in ("55", "65", "01"):
        raise ApiError("modelo deve ser '55' (NF-e), '65' (NFC-e) ou '01' (nota modelo 1/1-A).", status=400)
    if not data_emissao or not data_entrada:
        raise ApiError("Informe data_emissao e data_entrada.", status=400)
    if not itens:
        raise ApiError("Informe ao menos um item em 'itens'.", status=400)

    _fornecedor_ou_404(conn, fornecedor_id)

    if conn.execute(
        "SELECT id FROM notas_fiscais_entrada WHERE fornecedor_id = ? AND serie = ? AND numero = ?",
        (fornecedor_id, serie, numero),
    ).fetchone():
        raise ApiError("Já existe uma nota de entrada lançada com esta série/número para este fornecedor.", status=409)

    valor_frete = _numero_obrigatorio_ou_padrao(dados.get("valor_frete"), "valor_frete", 0, padrao=0.0)
    valor_seguro = _numero_obrigatorio_ou_padrao(dados.get("valor_seguro"), "valor_seguro", 0, padrao=0.0)
    valor_desconto = _numero_obrigatorio_ou_padrao(dados.get("valor_desconto"), "valor_desconto", 0, padrao=0.0)
    valor_outras_despesas = _numero_obrigatorio_ou_padrao(dados.get("valor_outras_despesas"), "valor_outras_despesas", 0, padrao=0.0)

    itens_processados = []
    valor_produtos = 0.0
    valor_icms_total = 0.0
    valor_icms_st_total = 0.0
    valor_ipi_total = 0.0
    for linha in itens:
        item_id = linha.get("item_id")
        cfop = (linha.get("cfop") or "").strip()
        cst_csosn = (linha.get("cst_csosn") or "").strip()
        if not item_id:
            raise ApiError("Cada item precisa de item_id.", status=400)
        if not cfop:
            raise ApiError("Cada item precisa de cfop.", status=400)
        if not cst_csosn:
            raise ApiError("Cada item precisa de cst_csosn.", status=400)
        if not conn.execute("SELECT id FROM itens WHERE id = ?", (item_id,)).fetchone():
            raise ApiError(f"Item id={item_id} não encontrado.", status=404)

        quantidade = _numero_obrigatorio_ou_padrao(linha.get("quantidade"), "quantidade")
        if quantidade <= 0:
            raise ApiError("quantidade deve ser maior que zero.", status=400)
        unidade = (linha.get("unidade") or "").strip()
        if not unidade:
            raise ApiError("Cada item precisa de unidade.", status=400)
        valor_unitario = _numero_obrigatorio_ou_padrao(linha.get("valor_unitario"), "valor_unitario", 0)

        lote_id = linha.get("lote_id")
        if lote_id is not None and not conn.execute("SELECT id FROM lotes WHERE id = ?", (lote_id,)).fetchone():
            raise ApiError(f"Lote id={lote_id} não encontrado.", status=404)

        item_processado = {
            "item_id": item_id, "lote_id": lote_id, "ncm": (linha.get("ncm") or "").strip() or None,
            "cfop": cfop, "cst_csosn": cst_csosn, "quantidade": quantidade, "unidade": unidade,
            "valor_unitario": valor_unitario, "valor_total": round(quantidade * valor_unitario, 2),
            "base_calculo_icms": _numero_obrigatorio_ou_padrao(linha.get("base_calculo_icms"), "base_calculo_icms", 0, padrao=0.0),
            "aliquota_icms": _numero_obrigatorio_ou_padrao(linha.get("aliquota_icms"), "aliquota_icms", 0, padrao=0.0),
            "valor_icms": _numero_obrigatorio_ou_padrao(linha.get("valor_icms"), "valor_icms", 0, padrao=0.0),
            "base_calculo_icms_st": _numero_obrigatorio_ou_padrao(linha.get("base_calculo_icms_st"), "base_calculo_icms_st", 0, padrao=0.0),
            "aliquota_icms_st": _numero_obrigatorio_ou_padrao(linha.get("aliquota_icms_st"), "aliquota_icms_st", 0, padrao=0.0),
            "valor_icms_st": _numero_obrigatorio_ou_padrao(linha.get("valor_icms_st"), "valor_icms_st", 0, padrao=0.0),
            "aliquota_ipi": _numero_obrigatorio_ou_padrao(linha.get("aliquota_ipi"), "aliquota_ipi", 0, padrao=0.0),
            "valor_ipi": _numero_obrigatorio_ou_padrao(linha.get("valor_ipi"), "valor_ipi", 0, padrao=0.0),
        }
        itens_processados.append(item_processado)
        valor_produtos += item_processado["valor_total"]
        valor_icms_total += item_processado["valor_icms"]
        valor_icms_st_total += item_processado["valor_icms_st"]
        valor_ipi_total += item_processado["valor_ipi"]

    valor_produtos = round(valor_produtos, 2)
    valor_ipi_total = round(valor_ipi_total, 2)
    # Fórmula padrão de nota fiscal brasileira: ICMS já está embutido no
    # valor dos produtos (não soma de novo); IPI é destacado À PARTE do
    # preço e soma no total pago pelo comprador.
    valor_total_nota = round(
        valor_produtos + valor_frete + valor_seguro + valor_outras_despesas - valor_desconto + valor_ipi_total, 2
    )

    cur = conn.execute(
        """
        INSERT INTO notas_fiscais_entrada
            (fornecedor_id, serie, numero, chave_acesso, modelo, data_emissao, data_entrada,
             valor_produtos, valor_frete, valor_seguro, valor_desconto, valor_outras_despesas,
             valor_icms, valor_icms_st, valor_ipi, valor_total_nota, observacoes, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fornecedor_id, serie, numero, (dados.get("chave_acesso") or "").strip() or None, modelo,
            data_emissao, data_entrada, valor_produtos, valor_frete, valor_seguro, valor_desconto,
            valor_outras_despesas, round(valor_icms_total, 2), round(valor_icms_st_total, 2),
            valor_ipi_total, valor_total_nota, dados.get("observacoes"), usuario_atual["id"],
        ),
    )
    nota_id = cur.lastrowid

    for item in itens_processados:
        conn.execute(
            """
            INSERT INTO notas_fiscais_entrada_itens
                (nota_fiscal_entrada_id, item_id, lote_id, ncm, cfop, cst_csosn, quantidade, unidade,
                 valor_unitario, valor_total, base_calculo_icms, aliquota_icms, valor_icms,
                 base_calculo_icms_st, aliquota_icms_st, valor_icms_st, aliquota_ipi, valor_ipi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nota_id, item["item_id"], item["lote_id"], item["ncm"], item["cfop"], item["cst_csosn"],
                item["quantidade"], item["unidade"], item["valor_unitario"], item["valor_total"],
                item["base_calculo_icms"], item["aliquota_icms"], item["valor_icms"],
                item["base_calculo_icms_st"], item["aliquota_icms_st"], item["valor_icms_st"],
                item["aliquota_ipi"], item["valor_ipi"],
            ),
        )
        if item["lote_id"]:
            conn.execute("UPDATE lotes SET nota_fiscal_entrada_id = ? WHERE id = ?", (nota_id, item["lote_id"]))

    audit.registrar(
        conn, tabela="notas_fiscais_entrada", registro_id=nota_id, usuario_id=usuario_atual["id"],
        acao="nota_fiscal_entrada_lancada",
        valor_novo={"fornecedor_id": fornecedor_id, "serie": serie, "numero": numero, "valor_total_nota": valor_total_nota},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_nota_entrada_detalhada(conn, nota_id)), 201


@bp.post("/notas-entrada/<int:nota_id>/cancelar")
@requires_permission("fiscal", "cancelar")
def cancelar_nota_entrada(nota_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()
    nota = _nota_entrada_ou_404(conn, nota_id)

    if nota["status"] == "cancelada":
        raise ApiError("Esta nota de entrada já está cancelada.", status=400)
    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    conn.execute(
        "UPDATE notas_fiscais_entrada SET status = 'cancelada', motivo_cancelamento = ?, cancelada_em = ?, cancelada_por = ? WHERE id = ?",
        (motivo, _now_iso(), usuario_atual["id"], nota_id),
    )
    audit.registrar(
        conn, tabela="notas_fiscais_entrada", registro_id=nota_id, usuario_id=usuario_atual["id"],
        acao="nota_fiscal_entrada_cancelada", valor_anterior={"status": nota["status"]},
        valor_novo={"status": "cancelada", "motivo": motivo}, ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_nota_entrada_detalhada(conn, nota_id))
