"""
Fase 123 — Recebimento e Importação de NF-e (Compras).

Orquestração HTTP sobre `app/nfe_entrada_service.py` (parsing/conversão/
conferência) e reaproveitamento direto do que já existe em `lotes.py`
(criação de lote) e `compras.py` (baixa contra o Pedido de Compra) — mesmo
padrão de `fiscal.py` orquestrando `nfe_service.py`.

Fluxo (Fase A — upload manual do XML; a Fase B, consulta automática à
SEFAZ, alimenta a mesma tabela por outro caminho, ver `app/sefaz_service.py`
quando existir):

    upload-xml -> nota criada (situacao_interna=aguardando_analise,
    fornecedor/pedido resolvidos automaticamente quando possível)
    -> tela de conferência (vincular item/unidade quando faltar,
    conferir preço/quantidade)
    -> manifestar (situação interna: aprovada/rejeitada/divergência)
    -> importar (gera lote por item, com lote/validade obrigatórios,
    abate o Pedido de Compra, marca importada — chave de acesso trava
    reimportação).
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import nfe_entrada_service as servico
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission, usuario_tem_permissao
from .compras import dar_baixa_recebimento_no_pedido, validar_pedido_para_recebimento
from .fiscal import criar_nota_entrada_interna
from .lotes import _gerar_codigo_lote

bp = Blueprint("nfe_entrada", __name__, url_prefix="/api/v1/nfe-entrada")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _registrar_evento(conn, nota_id, tipo_evento, usuario_id, detalhe=None, protocolo_sefaz=None):
    conn.execute(
        """
        INSERT INTO nfe_recebimento_eventos
            (nfe_recebimento_id, tipo_evento, detalhe, protocolo_sefaz, usuario_id, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (nota_id, tipo_evento, detalhe, protocolo_sefaz, usuario_id, _now_iso()),
    )


def _nota_ou_404(conn, nota_id):
    row = conn.execute("SELECT * FROM nfe_recebimento WHERE id = ?", (nota_id,)).fetchone()
    if row is None:
        raise ApiError("NF-e não encontrada.", status=404)
    return dict(row)


def _itens_da_nota(conn, nota_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM nfe_recebimento_itens WHERE nfe_recebimento_id = ? ORDER BY numero_item",
        (nota_id,),
    ).fetchall()]


def _nota_detalhada(conn, nota_id, incluir_conferencia=True):
    nota = _nota_ou_404(conn, nota_id)
    if nota["fornecedor_id"]:
        fornecedor = conn.execute("SELECT nome, cnpj FROM fornecedores WHERE id = ?", (nota["fornecedor_id"],)).fetchone()
        nota["fornecedor_nome"] = fornecedor["nome"] if fornecedor else None
    else:
        nota["fornecedor_nome"] = None
    if nota["pedido_compra_id"]:
        pedido = conn.execute("SELECT numero, status FROM pedidos_compra WHERE id = ?", (nota["pedido_compra_id"],)).fetchone()
        nota["pedido_compra_numero"] = pedido["numero"] if pedido else None
    else:
        nota["pedido_compra_numero"] = None

    itens = _itens_da_nota(conn, nota_id)
    if incluir_conferencia:
        config = servico.obter_config(conn)
        for item in itens:
            if item["item_id"]:
                item_row = conn.execute("SELECT descricao, unidade_medida FROM itens WHERE id = ?", (item["item_id"],)).fetchone()
                item["item_descricao"] = item_row["descricao"] if item_row else None
                if not item.get("unidade_interna_selecionada"):
                    item["unidade_interna_selecionada"] = item_row["unidade_medida"] if item_row else item["unidade_xml"]
                try:
                    item["conferencia"] = servico.conferir_item_nota(conn, item, nota["pedido_compra_id"], nota["fornecedor_id"], config)
                except ApiError as e:
                    item["conferencia"] = None
                    item["erro_conferencia"] = e.mensagem
            else:
                item["item_descricao"] = None
                item["conferencia"] = None
    nota["itens"] = itens
    nota["eventos"] = [dict(r) for r in conn.execute(
        "SELECT * FROM nfe_recebimento_eventos WHERE nfe_recebimento_id = ? ORDER BY id", (nota_id,)
    ).fetchall()]
    nota.pop("xml_original", None)  # nunca vai na listagem/detalhe — só no endpoint de download dedicado
    return nota


@bp.get("")
@requires_permission("nfe_entrada", "visualizar")
def listar():
    conn = get_db()
    situacao = request.args.get("situacao_interna")
    fornecedor_id = request.args.get("fornecedor_id", type=int)
    clausulas, params = [], []
    if situacao:
        clausulas.append("n.situacao_interna = ?")
        params.append(situacao)
    if fornecedor_id:
        clausulas.append("n.fornecedor_id = ?")
        params.append(fornecedor_id)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT n.id, n.chave_acesso, n.numero, n.serie, n.data_emissao, n.valor_total,
               n.cnpj_emitente, n.razao_social_emitente, n.manifestacao_sefaz, n.situacao_interna,
               n.fornecedor_id, n.pedido_compra_id, n.fonte, n.criado_em,
               f.nome AS fornecedor_nome,
               (SELECT COUNT(*) FROM nfe_recebimento_itens i WHERE i.nfe_recebimento_id = n.id) AS quantidade_itens
        FROM nfe_recebimento n
        LEFT JOIN fornecedores f ON f.id = n.fornecedor_id
        {where}
        ORDER BY n.criado_em DESC
        """,
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/unidades")
@requires_permission("nfe_entrada", "visualizar")
def listar_unidades():
    conn = get_db()
    rows = conn.execute("SELECT * FROM unidades_medida ORDER BY tipo, codigo").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:nota_id>")
@requires_permission("nfe_entrada", "visualizar")
def obter(nota_id):
    conn = get_db()
    nota = _nota_detalhada(conn, nota_id)
    if nota["situacao_interna"] in ("aguardando_analise",) and not nota["pedido_compra_id"]:
        nota["pedidos_compra_candidatos"] = servico.resolver_pedidos_compra_candidatos(conn, nota["fornecedor_id"])
    else:
        nota["pedidos_compra_candidatos"] = []
    return jsonify(nota)


@bp.post("/upload-xml")
@requires_permission("nfe_entrada", "conferir")
def upload_xml():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    xml_base64 = dados.get("xml_base64")
    if not xml_base64:
        raise ApiError("Envie o XML da NF-e em 'xml_base64'.", status=400)
    xml_texto = servico.decodificar_xml_bytes(xml_base64)
    dados_nfe = servico.parsear_xml_nfe(xml_texto)

    existente = get_db().execute(
        "SELECT id, situacao_interna, importada_em, importada_por FROM nfe_recebimento WHERE chave_acesso = ?",
        (dados_nfe["chave_acesso"],),
    ).fetchone()
    if existente:
        raise ApiError(
            f"Esta NF-e já foi recebida (chave {dados_nfe['chave_acesso']}) — situação atual: "
            f"'{existente['situacao_interna']}'"
            + (f", importada em {existente['importada_em']}." if existente["importada_em"] else "."),
            status=409,
        )

    conn = get_db()
    fornecedor_id = servico.resolver_fornecedor_por_cnpj(conn, dados_nfe["cnpj_emitente"])

    cur = conn.execute(
        """
        INSERT INTO nfe_recebimento
            (chave_acesso, numero, serie, fornecedor_id, cnpj_emitente, razao_social_emitente,
             data_emissao, valor_total, xml_original, comprador_responsavel_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (dados_nfe["chave_acesso"], dados_nfe["numero"], dados_nfe["serie"], fornecedor_id,
         dados_nfe["cnpj_emitente"], dados_nfe["razao_social_emitente"], dados_nfe["data_emissao"],
         dados_nfe["valor_total"], servico.normalizar_base64(xml_base64), usuario_atual["id"], usuario_atual["id"]),
    )
    nota_id = cur.lastrowid

    pedido_compra_id = None
    if fornecedor_id:
        candidatos = servico.resolver_pedidos_compra_candidatos(conn, fornecedor_id)
        if len(candidatos) == 1:
            pedido_compra_id = candidatos[0]["id"]
            conn.execute("UPDATE nfe_recebimento SET pedido_compra_id = ? WHERE id = ?", (pedido_compra_id, nota_id))

    for item in dados_nfe["itens"]:
        item_id = servico.resolver_item_por_vinculo(conn, fornecedor_id, item["codigo_produto_fornecedor"])
        conn.execute(
            """
            INSERT INTO nfe_recebimento_itens
                (nfe_recebimento_id, numero_item, codigo_produto_fornecedor, descricao_xml, ncm, cfop,
                 quantidade_xml, unidade_xml, valor_unitario_xml, valor_total_xml, item_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nota_id, item["numero_item"], item["codigo_produto_fornecedor"], item["descricao_xml"],
             item["ncm"], item["cfop"], item["quantidade_xml"], item["unidade_xml"],
             item["valor_unitario_xml"], item["valor_total_xml"], item_id),
        )

    _registrar_evento(conn, nota_id, "nota_recebida", usuario_atual["id"], detalhe=f"Upload manual — fonte: manual_upload")
    audit.registrar(conn, tabela="nfe_recebimento", registro_id=nota_id, usuario_id=usuario_atual["id"],
                     acao="nfe_entrada_recebida", valor_novo={"chave_acesso": dados_nfe["chave_acesso"], "valor_total": dados_nfe["valor_total"]},
                     ip=client_ip(), dispositivo=client_device())
    conn.commit()

    return jsonify(_nota_detalhada(conn, nota_id)), 201


@bp.patch("/<int:nota_id>/vincular-fornecedor")
@requires_permission("nfe_entrada", "conferir")
def vincular_fornecedor(nota_id):
    """Quando o CNPJ do emitente não bate com nenhum fornecedor cadastrado
    (fornecedor novo, ou CNPJ cadastrado com formatação diferente), esta
    rota permite apontar manualmente para o fornecedor certo — necessário
    antes de importar, já que o registro fiscal (`notas_fiscais_entrada`,
    Fase 78) exige um fornecedor_id."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    fornecedor_id = dados.get("fornecedor_id")
    if not fornecedor_id:
        raise ApiError("Informe fornecedor_id.", status=400)
    conn = get_db()
    _nota_ou_404(conn, nota_id)
    if conn.execute("SELECT id FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone() is None:
        raise ApiError("Fornecedor não encontrado.", status=404)
    conn.execute("UPDATE nfe_recebimento SET fornecedor_id = ? WHERE id = ?", (fornecedor_id, nota_id))
    _registrar_evento(conn, nota_id, "fornecedor_vinculado", usuario_atual["id"], detalhe=str(fornecedor_id))
    conn.commit()
    return jsonify(_nota_detalhada(conn, nota_id))


@bp.patch("/<int:nota_id>/vincular-pedido")
@requires_permission("nfe_entrada", "conferir")
def vincular_pedido(nota_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    pedido_compra_id = dados.get("pedido_compra_id")
    conn = get_db()
    nota = _nota_ou_404(conn, nota_id)
    if pedido_compra_id:
        pedido = conn.execute("SELECT fornecedor_id FROM pedidos_compra WHERE id = ?", (pedido_compra_id,)).fetchone()
        if pedido is None:
            raise ApiError("Pedido de compra não encontrado.", status=404)
        if nota["fornecedor_id"] and pedido["fornecedor_id"] != nota["fornecedor_id"]:
            raise ApiError("Este pedido de compra é de outro fornecedor, diferente do emitente desta NF-e.", status=400)
    conn.execute("UPDATE nfe_recebimento SET pedido_compra_id = ? WHERE id = ?", (pedido_compra_id, nota_id))
    _registrar_evento(conn, nota_id, "pedido_compra_vinculado", usuario_atual["id"], detalhe=str(pedido_compra_id))
    conn.commit()
    return jsonify(_nota_detalhada(conn, nota_id))


@bp.patch("/<int:nota_id>/itens/<int:item_id>")
@requires_permission("nfe_entrada", "conferir")
def atualizar_item(nota_id, item_id):
    """Vincula o item interno e/ou define a unidade interna a usar —
    quando `item_id` é informado e o item já tem `codigo_produto_fornecedor`
    no XML, salva o vínculo fornecedor->produto para reaproveitar
    automaticamente nas próximas notas (seção 7)."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    nota = _nota_ou_404(conn, nota_id)
    linha = conn.execute(
        "SELECT * FROM nfe_recebimento_itens WHERE id = ? AND nfe_recebimento_id = ?",
        (item_id, nota_id),
    ).fetchone()
    if linha is None:
        raise ApiError("Item não encontrado nesta NF-e.", status=404)

    novo_item_id = dados.get("item_id", linha["item_id"])
    nova_unidade = dados.get("unidade_interna_selecionada") or linha["unidade_interna_selecionada"]

    if novo_item_id and novo_item_id != linha["item_id"]:
        item_existe = conn.execute("SELECT id, unidade_medida FROM itens WHERE id = ?", (novo_item_id,)).fetchone()
        if item_existe is None:
            raise ApiError("Item interno não encontrado.", status=404)
        if not nova_unidade:
            nova_unidade = item_existe["unidade_medida"]
        if nota["fornecedor_id"] and linha["codigo_produto_fornecedor"]:
            servico.salvar_vinculo_fornecedor_produto(
                conn, nota["fornecedor_id"], linha["codigo_produto_fornecedor"], novo_item_id, usuario_atual["id"]
            )

    conn.execute(
        "UPDATE nfe_recebimento_itens SET item_id = ?, unidade_interna_selecionada = ? WHERE id = ?",
        (novo_item_id, nova_unidade, item_id),
    )
    _registrar_evento(conn, nota_id, "item_vinculado", usuario_atual["id"],
                       detalhe=f"item_id={novo_item_id} unidade={nova_unidade}")
    conn.commit()
    return jsonify(_nota_detalhada(conn, nota_id))


@bp.post("/conversoes-unidade")
@requires_permission("nfe_entrada", "conferir")
def cadastrar_conversao_unidade():
    """Cadastra o fator de conversão não-matemático de um item (seção 9 —
    ex.: 1 caixa = 12 frascos), reaproveitado automaticamente depois por
    `obter_fator_conversao`."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    item_id = dados.get("item_id")
    unidade_origem = dados.get("unidade_origem")
    unidade_destino = dados.get("unidade_destino")
    fator = dados.get("fator")
    if not item_id or not unidade_origem or not unidade_destino or not fator:
        raise ApiError("Informe item_id, unidade_origem, unidade_destino e fator.", status=400)
    try:
        fator = float(fator)
    except (TypeError, ValueError):
        raise ApiError("fator deve ser numérico.", status=400)
    if fator <= 0:
        raise ApiError("fator deve ser maior que zero.", status=400)

    conn = get_db()
    if conn.execute("SELECT id FROM itens WHERE id = ?", (item_id,)).fetchone() is None:
        raise ApiError("Item não encontrado.", status=404)
    conn.execute(
        """
        INSERT INTO item_conversoes_unidade (item_id, unidade_origem, unidade_destino, fator, criado_por)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(item_id, unidade_origem, unidade_destino) DO UPDATE SET
            fator = excluded.fator, criado_por = excluded.criado_por, criado_em = excluded.criado_em
        """,
        (item_id, unidade_origem, unidade_destino, fator, usuario_atual["id"]),
    )
    conn.commit()
    return jsonify({"ok": True}), 201


@bp.patch("/<int:nota_id>/manifestacao")
@requires_permission("nfe_entrada", "conferir")
def registrar_manifestacao(nota_id):
    """Fase A — registra o que FOI manifestado na SEFAZ por fora do
    sistema (ex.: já manifestou "Ciência da Operação" direto no portal).
    Nunca confundir com `situacao_interna` (seção 2) — este endpoint só
    grava o evento fiscal informado, não aprova nem rejeita nada aqui
    dentro. A Fase B substitui isto por uma chamada de verdade à SEFAZ
    (RecepçãoEvento), mantendo a mesma coluna."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    manifestacao = dados.get("manifestacao_sefaz")
    opcoes = ("ciencia_operacao", "confirmacao_operacao", "desconhecimento_operacao", "operacao_nao_realizada")
    if manifestacao not in opcoes:
        raise ApiError(f"manifestacao_sefaz deve ser uma de: {', '.join(opcoes)}.", status=400)
    conn = get_db()
    _nota_ou_404(conn, nota_id)
    conn.execute("UPDATE nfe_recebimento SET manifestacao_sefaz = ? WHERE id = ?", (manifestacao, nota_id))
    _registrar_evento(conn, nota_id, "manifestacao_sefaz", usuario_atual["id"], detalhe=manifestacao)
    conn.commit()
    return jsonify(_nota_detalhada(conn, nota_id))


@bp.patch("/<int:nota_id>/situacao")
@requires_permission("nfe_entrada", "conferir")
def alterar_situacao_interna(nota_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nova_situacao = dados.get("situacao_interna")
    opcoes = ("em_conferencia", "aprovada", "rejeitada_internamente", "divergencia_encontrada")
    if nova_situacao not in opcoes:
        raise ApiError(f"situacao_interna deve ser uma de: {', '.join(opcoes)} (para marcar como importada, use POST .../importar).", status=400)
    conn = get_db()
    nota = _nota_ou_404(conn, nota_id)
    if nota["situacao_interna"] == "importada":
        raise ApiError("Esta NF-e já foi importada — situação interna não pode mais ser alterada.", status=400)
    conn.execute("UPDATE nfe_recebimento SET situacao_interna = ? WHERE id = ?", (nova_situacao, nota_id))
    _registrar_evento(conn, nota_id, "situacao_interna_alterada", usuario_atual["id"],
                       detalhe=f"{nota['situacao_interna']} -> {nova_situacao}")
    conn.commit()
    return jsonify(_nota_detalhada(conn, nota_id))


@bp.post("/<int:nota_id>/importar")
@requires_permission("nfe_entrada", "importar")
def importar(nota_id):
    """Seção 11/13 da especificação: importa a NF-e pro estoque (um lote
    por item, exigindo lote de origem/validade — fecha também o pedido
    anterior do usuário sobre lote obrigatório na importação de NF-e),
    abate o Pedido de Compra vinculado (reaproveitando
    `dar_baixa_recebimento_no_pedido` já usado no recebimento manual de
    lote), e trava a chave de acesso contra reimportação."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    itens_payload = dados.get("itens") or []

    conn = get_db()
    nota = _nota_ou_404(conn, nota_id)
    if nota["situacao_interna"] == "importada":
        raise ApiError(
            f"Esta NF-e já foi importada em {nota['importada_em']}"
            + (f" por outro usuário." if nota["importada_por"] != usuario_atual["id"] else "."),
            status=409,
        )
    if not nota["fornecedor_id"]:
        raise ApiError(
            "Esta NF-e ainda não está vinculada a um fornecedor cadastrado — vincule "
            "(PATCH .../vincular-fornecedor) antes de importar.",
            status=400,
        )

    itens_nota = {i["id"]: i for i in _itens_da_nota(conn, nota_id)}
    if not itens_payload:
        raise ApiError("Informe os itens a importar (lote/validade por item).", status=400)

    # Seção 11 da especificação — "caso existam divergências críticas,
    # exigir autorização de usuário com permissão apropriada": antes de
    # gravar qualquer coisa, confere se algum item a importar está com
    # status 🔴 (preço ou quantidade fora da tolerância configurada). Se
    # sim, exige a permissão nfe_entrada.importar_com_divergencia MAIS uma
    # justificativa por escrito — nunca passa batido, e nunca bloqueia
    # sozinho sem dar um jeito de prosseguir para quem tem autorização.
    config_conferencia = servico.obter_config(conn)
    descricoes_divergentes = []
    for entrada in itens_payload:
        linha_check = itens_nota.get(entrada.get("nfe_recebimento_item_id"))
        if linha_check is None or not linha_check["item_id"]:
            continue
        unidade_check = entrada.get("unidade_interna_selecionada") or linha_check["unidade_interna_selecionada"] or linha_check["unidade_xml"]
        linha_para_conferencia = dict(linha_check)
        linha_para_conferencia["unidade_interna_selecionada"] = unidade_check
        try:
            conf_check = servico.conferir_item_nota(conn, linha_para_conferencia, nota["pedido_compra_id"], nota["fornecedor_id"], config_conferencia)
        except ApiError:
            continue  # sem conversão cadastrada ainda — bloqueado mais abaixo, no loop principal, com mensagem específica.
        if conf_check["status_preco"] == "divergente" or conf_check["status_quantidade"] == "divergente":
            descricoes_divergentes.append(linha_check["descricao_xml"])

    justificativa_divergencia = (dados.get("justificativa_divergencia") or "").strip()
    if descricoes_divergentes:
        if not usuario_tem_permissao(conn, usuario_atual["id"], "nfe_entrada", "importar_com_divergencia"):
            raise ApiError(
                "Item(ns) com divergência de preço/quantidade fora da tolerância: "
                f"{', '.join(descricoes_divergentes)}. Importar mesmo assim exige a permissão "
                "'nfe_entrada.importar_com_divergencia' — peça a um administrador, ou corrija o "
                "vínculo/conversão do item antes de importar.",
                status=403,
            )
        if not justificativa_divergencia:
            raise ApiError(
                "Item(ns) com divergência de preço/quantidade fora da tolerância: "
                f"{', '.join(descricoes_divergentes)}. Informe 'justificativa_divergencia' explicando "
                "por que importar mesmo assim.",
                status=400,
            )

    # Reparse do XML original — a fila de recebimento (`nfe_recebimento_itens`)
    # só guarda o que a conferência precisa; os campos fiscais completos
    # (CST/CSOSN, bases e alíquotas de ICMS/ICMS-ST/IPI) usados para
    # alimentar `notas_fiscais_entrada` (Fase 78) abaixo vêm direto do XML
    # de novo, por número de item — nunca duplicados/guardados à parte.
    dados_xml = servico.parsear_xml_nfe(servico.decodificar_xml_bytes(
        conn.execute("SELECT xml_original FROM nfe_recebimento WHERE id = ?", (nota_id,)).fetchone()["xml_original"]
    ))
    impostos_por_numero_item = {i["numero_item"]: i for i in dados_xml["itens"]}

    resumo = []
    itens_fase78 = []
    for entrada in itens_payload:
        item_nfe_id = entrada.get("nfe_recebimento_item_id")
        linha = itens_nota.get(item_nfe_id)
        if linha is None:
            raise ApiError(f"Item {item_nfe_id} não pertence a esta NF-e.", status=400)
        if not linha["item_id"]:
            raise ApiError(f"O item '{linha['descricao_xml']}' ainda não foi vinculado a um produto interno — vincule antes de importar.", status=400)
        validade = entrada.get("validade")
        if not validade:
            raise ApiError(f"Informe a validade do lote para o item '{linha['descricao_xml']}' — obrigatório na importação de NF-e.", status=400)

        unidade_interna = entrada.get("unidade_interna_selecionada") or linha["unidade_interna_selecionada"] or linha["unidade_xml"]
        quantidade_convertida, fator = servico.converter_quantidade(
            conn, linha["item_id"], linha["quantidade_xml"], linha["unidade_xml"], unidade_interna
        )
        custo_unitario = servico.converter_preco_unitario(
            conn, linha["item_id"], linha["valor_unitario_xml"], linha["unidade_xml"], unidade_interna
        )

        temp_codigo = f"NFE-{nota_id}-{item_nfe_id}"
        cur = conn.execute(
            """
            INSERT INTO lotes (codigo_lote, item_id, fornecedor_id, lote_fornecedor, validade,
                                quantidade, unidade, status, nota_fiscal, pedido_compra_id, custo_unitario, criado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'quarentena', ?, ?, ?, ?)
            """,
            (temp_codigo, linha["item_id"], nota["fornecedor_id"], entrada.get("lote_fornecedor"), validade,
             quantidade_convertida, unidade_interna, nota["numero"], nota["pedido_compra_id"], custo_unitario,
             usuario_atual["id"]),
        )
        lote_id = cur.lastrowid
        codigo_lote = _gerar_codigo_lote(conn, lote_id)
        conn.execute("UPDATE lotes SET codigo_lote = ? WHERE id = ?", (codigo_lote, lote_id))

        audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                         acao="lote_recebido_via_nfe", valor_novo={"codigo_lote": codigo_lote, "nfe_recebimento_id": nota_id},
                         ip=client_ip(), dispositivo=client_device())

        if nota["pedido_compra_id"]:
            try:
                validar_pedido_para_recebimento(conn, nota["pedido_compra_id"], linha["item_id"])
                dar_baixa_recebimento_no_pedido(conn, nota["pedido_compra_id"], linha["item_id"], quantidade_convertida, usuario_atual, lote_id)
            except ApiError:
                # Pedido pode não ter esta linha (nota com item fora do
                # pedido) ou já ter mudado de status — o lote já foi
                # recebido de verdade; só a baixa estruturada no pedido
                # fica pendente de ajuste manual, sinalizado no resumo.
                resumo.append({"item": linha["descricao_xml"], "aviso": "Não foi possível abater contra o pedido de compra — confira manualmente."})

        conn.execute(
            "UPDATE nfe_recebimento_itens SET unidade_interna_selecionada = ?, quantidade_convertida = ?, fator_conversao_aplicado = ?, lote_gerado_id = ? WHERE id = ?",
            (unidade_interna, quantidade_convertida, fator, lote_id, item_nfe_id),
        )
        resumo.append({"item": linha["descricao_xml"], "lote_gerado": codigo_lote, "quantidade": quantidade_convertida, "unidade": unidade_interna})

        # Dados fiscais completos deste item, na unidade FISCAL original
        # (não na convertida — `notas_fiscais_entrada`, Fase 78, espelha o
        # documento como declarado), para o registro fiscal ligado logo
        # abaixo. `lote_id` aqui é o que já marca `lotes.nota_fiscal_entrada_id`
        # dentro de `criar_nota_entrada_interna`, satisfazendo também a
        # exigência de Qualidade (Fase 85) de lote vinculado à NF-e antes
        # de aprovar o CQ.
        impostos = impostos_por_numero_item.get(linha["numero_item"], {})
        itens_fase78.append({
            "item_id": linha["item_id"], "lote_id": lote_id, "ncm": linha["ncm"], "cfop": linha["cfop"],
            "cst_csosn": impostos.get("cst_csosn") or "00",
            "quantidade": linha["quantidade_xml"], "unidade": linha["unidade_xml"],
            "valor_unitario": linha["valor_unitario_xml"],
            "base_calculo_icms": impostos.get("base_calculo_icms", 0), "aliquota_icms": impostos.get("aliquota_icms", 0),
            "valor_icms": impostos.get("valor_icms", 0), "base_calculo_icms_st": impostos.get("base_calculo_icms_st", 0),
            "aliquota_icms_st": impostos.get("aliquota_icms_st", 0), "valor_icms_st": impostos.get("valor_icms_st", 0),
            "aliquota_ipi": impostos.get("aliquota_ipi", 0), "valor_ipi": impostos.get("valor_ipi", 0),
        })

    conn.execute(
        "UPDATE nfe_recebimento SET situacao_interna = 'importada', importada_em = ?, importada_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], nota_id),
    )
    detalhe_importacao = f"{len(itens_payload)} item(ns)"
    if descricoes_divergentes:
        detalhe_importacao += f" — importado COM DIVERGÊNCIA ({', '.join(descricoes_divergentes)}). Justificativa: {justificativa_divergencia}"
    _registrar_evento(conn, nota_id, "importacao_realizada", usuario_atual["id"], detalhe=detalhe_importacao)
    audit.registrar(conn, tabela="nfe_recebimento", registro_id=nota_id, usuario_id=usuario_atual["id"],
                     acao="nfe_entrada_importada", valor_novo={"itens": len(itens_payload)},
                     ip=client_ip(), dispositivo=client_device())

    # Alimenta o registro fiscal já existente (Fase 78) automaticamente —
    # mesma validação/inserção de quem lançaria isso à mão em Fiscal >
    # Notas de Entrada, só que preenchido a partir do XML. Se já existir
    # uma nota lançada manualmente com a mesma série/número deste
    # fornecedor (corrida rara — alguém digitou antes do XML chegar), o
    # estoque já foi recebido de verdade; só o espelho fiscal fica
    # pendente de conciliação manual, sinalizado no resumo.
    try:
        dados_fase78 = {
            "fornecedor_id": nota["fornecedor_id"], "serie": nota["serie"] or "1", "numero": nota["numero"],
            "modelo": "55", "chave_acesso": nota["chave_acesso"],
            "data_emissao": (nota["data_emissao"] or "")[:10] or _now_iso()[:10],
            "data_entrada": _now_iso()[:10],
            "valor_frete": dados_xml.get("valor_frete", 0), "valor_seguro": dados_xml.get("valor_seguro", 0),
            "valor_desconto": dados_xml.get("valor_desconto", 0), "valor_outras_despesas": dados_xml.get("valor_outras_despesas", 0),
            "observacoes": f"Lançada automaticamente pela importação de NF-e (chave {nota['chave_acesso']}).",
            "itens": itens_fase78,
        }
        criar_nota_entrada_interna(conn, usuario_atual, dados_fase78)
    except ApiError as e:
        resumo.append({"aviso_fiscal": f"Estoque recebido normalmente, mas o lançamento fiscal automático (Fase 78) falhou: {e.mensagem}"})

    conn.commit()

    nota_final = _nota_detalhada(conn, nota_id)
    nota_final["resumo_importacao"] = resumo
    return jsonify(nota_final)


@bp.get("/<int:nota_id>/xml")
@requires_permission("nfe_entrada", "visualizar")
def baixar_xml(nota_id):
    from flask import Response
    conn = get_db()
    row = conn.execute("SELECT xml_original, chave_acesso FROM nfe_recebimento WHERE id = ?", (nota_id,)).fetchone()
    if row is None:
        raise ApiError("NF-e não encontrada.", status=404)
    xml_texto = servico.decodificar_xml_bytes(row["xml_original"])
    return Response(
        xml_texto, mimetype="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{row["chave_acesso"]}.xml"'},
    )


@bp.get("/configuracao")
@requires_permission("nfe_entrada", "configurar")
def obter_configuracao():
    return jsonify(servico.obter_config(get_db()))


@bp.put("/configuracao")
@requires_permission("nfe_entrada", "configurar")
def salvar_configuracao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = conn.execute("SELECT * FROM configuracoes_nfe_entrada WHERE id = 1").fetchone()
    anterior = dict(anterior) if anterior else {}

    tolerancia_preco = dados.get("tolerancia_preco_percentual", anterior.get("tolerancia_preco_percentual", servico.TOLERANCIA_PRECO_PADRAO))
    tolerancia_quantidade = dados.get("tolerancia_quantidade_percentual", anterior.get("tolerancia_quantidade_percentual", servico.TOLERANCIA_QUANTIDADE_PADRAO))
    try:
        tolerancia_preco = float(tolerancia_preco)
        tolerancia_quantidade = float(tolerancia_quantidade)
    except (TypeError, ValueError):
        raise ApiError("Tolerâncias devem ser numéricas.", status=400)
    if tolerancia_preco < 0 or tolerancia_quantidade < 0:
        raise ApiError("Tolerâncias não podem ser negativas.", status=400)

    ambiente = dados.get("ambiente", anterior.get("ambiente", "homologacao"))
    if ambiente not in ("homologacao", "producao"):
        raise ApiError("ambiente deve ser 'homologacao' ou 'producao'.", status=400)

    conn.execute(
        """
        INSERT INTO configuracoes_nfe_entrada (id, tolerancia_preco_percentual, tolerancia_quantidade_percentual, ambiente, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            tolerancia_preco_percentual = excluded.tolerancia_preco_percentual,
            tolerancia_quantidade_percentual = excluded.tolerancia_quantidade_percentual,
            ambiente = excluded.ambiente,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (tolerancia_preco, tolerancia_quantidade, ambiente, _now_iso(), usuario_atual["id"]),
    )
    conn.commit()
    return jsonify(servico.obter_config(conn))
