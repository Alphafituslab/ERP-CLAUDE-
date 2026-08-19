"""
Fase 70 — Fiscal: rotas HTTP finas em cima de app/nfe_service.py (mesmo
padrão de app/routes/sistema.py em cima de app/backup_service.py, Fase 67).
"""
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
