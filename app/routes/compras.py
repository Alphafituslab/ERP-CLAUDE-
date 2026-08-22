"""
Fase 58 — Pedido de Compra formal.

Ver a nota completa de escopo em migrations/schema_fase58.sql. Resumo: um
Pedido de Compra é o COMPROMISSO com o fornecedor (itens, quantidade,
fornecedor, preço estimado) — nem obrigação financeira (`contas_pagar`,
Fase 6) nem lote de estoque (`lotes`, Fase 2), as três entidades ficam
deliberadamente separadas.

Ciclo de vida: rascunho -> enviado -> parcialmente_recebido -> recebido,
com cancelado possível a partir de rascunho ou enviado (nunca depois de
qualquer recebimento parcial). O recebimento em si continua acontecendo
pela tela de Lotes já existente desde a Fase 2 (`POST
/api/v1/lotes/recebimento`), agora aceitando um `pedido_compra_id`
opcional — a lógica de abater `quantidade_recebida` e recalcular o status
do pedido mora em `dar_baixa_recebimento_no_pedido`, chamada por
`app/routes/lotes.py`.

Decisão de escopo deliberada: este MVP não tem edição de itens depois que
o pedido é criado (nem em rascunho) — para mudar a lista de itens ou
quantidades, cancele (se ainda não houve recebimento) e crie outro. Isso
evita ter que decidir o que fazer com uma linha que edita justamente a
que já tem recebimento parcial contra ela.
"""
import datetime
import secrets

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..permissions import requires_permission
# Fase 59 — reaproveita o núcleo de criação de conta a pagar já usado por
# `POST /financeiro/contas-pagar` (ver a nota de escopo em
# migrations/schema_fase59.sql e em criar_conta_pagar_interno em
# app/routes/financeiro.py). Import de rotas.financeiro -> rotas.compras
# não existe no sentido contrário, então isto não cria import circular.
from .financeiro import criar_conta_pagar_interno

bp = Blueprint("compras", __name__, url_prefix="/api/v1/compras")


def _gerar_numero_pedido():
    ano = datetime.datetime.utcnow().year
    return f"PC-{ano}-{secrets.token_hex(4).upper()}"


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hoje_iso_data():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


# Fase 61 — mesmo padrão de _configuracao_comercial em app/routes/vendas_app.py:
# uma única linha (id=1), sempre existente desde o INSERT em
# migrations/schema_fase61.sql.
def _configuracao_compras(conn):
    row = conn.execute("SELECT * FROM configuracoes_compras WHERE id = 1").fetchone()
    if row is None:
        # Defensivo (Fase 73): nunca deveria acontecer num banco
        # inicializado pelas migrations, mas devolve o padrão em vez de um
        # 500 — mesmo espírito de vendas_app._configuracao_comercial.
        return {"id": 1, "limiar_valor_pedido_grande": 0, "atualizado_em": None, "atualizado_por": None}
    return dict(row)


def _valor_total_pedido(conn, pedido_id):
    """Soma quantidade_pedida x preco_unitario de todas as linhas — usa o
    que foi PEDIDO (não o recebido, ver Fase 59 para essa outra conta),
    porque a alçada decide sobre o COMPROMISSO assumido no envio, antes
    de qualquer recebimento existir. Linha sem preco_unitario ainda
    definido conta como 0 nesta soma (o valor final só é conhecido depois
    de negociado — não bloqueia o envio; só significa que aquela linha
    não pesa na alçada até ter um preço)."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(quantidade_pedida * COALESCE(preco_unitario, 0)), 0) AS total
        FROM itens_pedido_compra WHERE pedido_compra_id = ?
        """,
        (pedido_id,),
    ).fetchone()
    return round(row["total"], 2)


def _fornecedor_ou_404(conn, fornecedor_id):
    fornecedor = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    if fornecedor is None:
        raise ApiError("Fornecedor não encontrado.", status=404)
    return fornecedor


def _item_ou_404(conn, item_id):
    item = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError(f"Item {item_id} não encontrado.", status=404)
    return item


def _pedido_ou_404(conn, pedido_id):
    row = conn.execute("SELECT * FROM pedidos_compra WHERE id = ?", (pedido_id,)).fetchone()
    if row is None:
        raise ApiError("Pedido de compra não encontrado.", status=404)
    return row


def _pedido_detalhado(conn, pedido_id):
    pedido = dict(_pedido_ou_404(conn, pedido_id))
    fornecedor = conn.execute("SELECT nome, cnpj FROM fornecedores WHERE id = ?", (pedido["fornecedor_id"],)).fetchone()
    pedido["fornecedor_nome"] = fornecedor["nome"] if fornecedor else None
    pedido["fornecedor_cnpj"] = fornecedor["cnpj"] if fornecedor else None

    # Fase 59 — mesma ideia do fornecedor acima: se este pedido já gerou
    # uma conta a pagar (ver `gerar_conta_pagar_do_pedido` abaixo), mostra
    # o número dela direto no detalhe do pedido, sem o front precisar
    # buscar em Financeiro separadamente.
    if pedido["conta_pagar_id"]:
        conta = conn.execute("SELECT numero FROM contas_pagar WHERE id = ?", (pedido["conta_pagar_id"],)).fetchone()
        pedido["conta_pagar_numero"] = conta["numero"] if conta else None
    else:
        pedido["conta_pagar_numero"] = None

    # Fase 60 — mesmo padrão de `contas_pagar.vencida`/`contas_receber.vencida`
    # desde a Fase 6: um campo calculado on-the-fly, nunca gravado, então
    # nunca fica desatualizado nem depende de nenhum job em segundo plano.
    # Só é 'atrasado' quem: (a) ainda não terminou de chegar (enviado ou
    # parcialmente_recebido — 'recebido'/'cancelado'/'rascunho' nunca são
    # atrasados), (b) tem uma data prevista congelada no envio (Fase 57 —
    # sem lead time configurado no fornecedor na hora do envio, nunca
    # inventamos uma data), e (c) essa data já passou.
    pedido["atrasado"] = (
        pedido["status"] in ("enviado", "parcialmente_recebido")
        and pedido["data_prevista_entrega"] is not None
        and pedido["data_prevista_entrega"] < _hoje_iso_data()
    )

    # Fase 61 — se há uma solicitação de envio pendente de aprovação
    # (alçada de valor, ver migrations/schema_fase61.sql), expõe aqui para
    # o front mostrar "aguardando aprovação" em vez de tratar como um
    # rascunho comum.
    envio_pendente = conn.execute(
        "SELECT * FROM pedidos_compra_envios_pendentes WHERE pedido_compra_id = ? AND status = 'pendente'",
        (pedido_id,),
    ).fetchone()
    pedido["envio_pendente"] = dict(envio_pendente) if envio_pendente else None

    linhas = conn.execute(
        "SELECT * FROM itens_pedido_compra WHERE pedido_compra_id = ? ORDER BY id", (pedido_id,)
    ).fetchall()
    itens = []
    for linha in linhas:
        d = dict(linha)
        item = conn.execute("SELECT codigo, descricao FROM itens WHERE id = ?", (d["item_id"],)).fetchone()
        d["item_codigo"] = item["codigo"] if item else None
        d["item_descricao"] = item["descricao"] if item else None
        d["quantidade_pendente"] = round(max(0.0, d["quantidade_pedida"] - d["quantidade_recebida"]), 6)
        itens.append(d)
    pedido["itens"] = itens
    return pedido


def _validar_itens_payload(conn, itens_payload):
    """Valida e normaliza a lista de itens de um pedido novo — usada tanto
    pela criação manual (`POST /pedidos`) quanto pela criação a partir de
    uma sugestão do MRP (ver app/routes/aps.py). Não grava nada; só valida
    e devolve a lista pronta para INSERT."""
    if not itens_payload or not isinstance(itens_payload, list):
        raise ApiError("Informe itens: uma lista com ao menos um item.", status=400)

    vistos = set()
    itens_normalizados = []
    for i, item_payload in enumerate(itens_payload):
        item_id = item_payload.get("item_id")
        quantidade_pedida = item_payload.get("quantidade_pedida")
        unidade = (item_payload.get("unidade") or "").strip()
        preco_unitario = item_payload.get("preco_unitario")
        sugestao_compra_mrp_id = item_payload.get("sugestao_compra_mrp_id")

        if not item_id:
            raise ApiError(f"Item na posição {i}: informe item_id.", status=400)
        if item_id in vistos:
            raise ApiError(
                f"O item {item_id} aparece mais de uma vez — cada item entra em uma única linha do pedido "
                "(some as quantidades antes de enviar).",
                status=400,
            )
        vistos.add(item_id)
        _item_ou_404(conn, item_id)

        try:
            quantidade_pedida = float(quantidade_pedida)
        except (TypeError, ValueError):
            raise ApiError(f"Item na posição {i}: quantidade_pedida deve ser numérica.", status=400)
        if quantidade_pedida <= 0:
            raise ApiError(f"Item na posição {i}: quantidade_pedida deve ser maior que zero.", status=400)
        if not unidade:
            raise ApiError(f"Item na posição {i}: informe unidade.", status=400)

        if preco_unitario is not None and preco_unitario != "":
            try:
                preco_unitario = float(preco_unitario)
            except (TypeError, ValueError):
                raise ApiError(f"Item na posição {i}: preco_unitario deve ser numérico.", status=400)
            if preco_unitario < 0:
                raise ApiError(f"Item na posição {i}: preco_unitario não pode ser negativo.", status=400)
        else:
            preco_unitario = None

        if sugestao_compra_mrp_id:
            sugestao = conn.execute(
                "SELECT id FROM sugestoes_compra_mrp WHERE id = ?", (sugestao_compra_mrp_id,)
            ).fetchone()
            if sugestao is None:
                raise ApiError(f"Item na posição {i}: sugestao_compra_mrp_id informado não existe.", status=404)

        itens_normalizados.append({
            "item_id": item_id,
            "quantidade_pedida": quantidade_pedida,
            "unidade": unidade,
            "preco_unitario": preco_unitario,
            "sugestao_compra_mrp_id": sugestao_compra_mrp_id,
        })
    return itens_normalizados


def criar_pedido_compra_interno(conn, usuario_atual, fornecedor_id, itens_payload, observacoes=None):
    """Núcleo da criação de um pedido — reaproveitado por `POST
    /compras/pedidos` (manual) e por `POST
    /aps/sugestoes-compra/<id>/gerar-pedido-compra` (a partir do MRP).
    Sempre nasce em status 'rascunho'. Devolve o id do pedido criado; quem
    chama decide o resto (resposta HTTP, e-no caso da sugestão-marcar a
    sugestão como atendida)."""
    _fornecedor_ou_404(conn, fornecedor_id)
    itens = _validar_itens_payload(conn, itens_payload)

    numero = _gerar_numero_pedido()
    cur = conn.execute(
        "INSERT INTO pedidos_compra (numero, fornecedor_id, observacoes, criado_por) VALUES (?, ?, ?, ?)",
        (numero, fornecedor_id, (observacoes or "").strip() or None, usuario_atual["id"]),
    )
    pedido_id = cur.lastrowid

    for item in itens:
        conn.execute(
            """
            INSERT INTO itens_pedido_compra
                (pedido_compra_id, item_id, quantidade_pedida, unidade, preco_unitario, sugestao_compra_mrp_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pedido_id, item["item_id"], item["quantidade_pedida"], item["unidade"],
             item["preco_unitario"], item["sugestao_compra_mrp_id"]),
        )
    conn.commit()

    audit.registrar(
        conn, tabela="pedidos_compra", registro_id=pedido_id, usuario_id=usuario_atual["id"],
        acao="pedido_compra_criado",
        valor_novo={"numero": numero, "fornecedor_id": fornecedor_id, "total_itens": len(itens)},
        ip=client_ip(), dispositivo=client_device(),
    )
    return pedido_id


def _ultimas_compras_item(conn, item_id, limite=2):
    """Fase 89 — junta `itens_pedido_compra` + `pedidos_compra` +
    `fornecedores` para responder "quando e por quanto compramos isso da
    última vez, e de quem" — não existia nenhum relatório assim antes
    desta fase (a única coisa parecida, `custeio.custo_medio_item`, faz
    uma MÉDIA ponderada entre todos os lotes já recebidos, não mostra as
    últimas compras individualmente)."""
    rows = conn.execute(
        """
        SELECT pc.numero, pc.criado_em, pc.enviado_em, pc.status, f.nome AS fornecedor_nome,
               ipc.quantidade_pedida, ipc.quantidade_recebida, ipc.preco_unitario, ipc.unidade
        FROM itens_pedido_compra ipc
        JOIN pedidos_compra pc ON pc.id = ipc.pedido_compra_id
        JOIN fornecedores f ON f.id = pc.fornecedor_id
        WHERE ipc.item_id = ?
        ORDER BY pc.criado_em DESC
        LIMIT ?
        """,
        (item_id, limite),
    ).fetchall()
    return [dict(r) for r in rows]


@bp.get("/itens/<int:item_id>/ultimas-compras")
@requires_permission("compras", "visualizar")
def ultimas_compras_item(item_id):
    conn = get_db()
    return jsonify(_ultimas_compras_item(conn, item_id))


@bp.get("/pedidos")
@requires_permission("compras", "visualizar")
def listar_pedidos():
    conn = get_db()
    status_filtro = request.args.get("status")
    fornecedor_id = request.args.get("fornecedor_id")

    query = "SELECT id FROM pedidos_compra WHERE 1=1"
    params = []
    if status_filtro:
        opcoes = ("rascunho", "enviado", "parcialmente_recebido", "recebido", "cancelado")
        if status_filtro not in opcoes:
            raise ApiError(f"status deve ser um de: {', '.join(opcoes)}.", status=400)
        query += " AND status = ?"
        params.append(status_filtro)
    if fornecedor_id:
        query += " AND fornecedor_id = ?"
        params.append(fornecedor_id)
    query += " ORDER BY id DESC"

    ids = [row["id"] for row in conn.execute(query, params).fetchall()]
    return jsonify([_pedido_detalhado(conn, pedido_id) for pedido_id in ids])


@bp.get("/pedidos/<int:pedido_id>")
@requires_permission("compras", "visualizar")
def obter_pedido(pedido_id):
    conn = get_db()
    return jsonify(_pedido_detalhado(conn, pedido_id))


@bp.post("/pedidos")
@requires_permission("compras", "criar_pedido")
def criar_pedido():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    fornecedor_id = dados.get("fornecedor_id")
    if not fornecedor_id:
        raise ApiError("Informe fornecedor_id.", status=400)

    pedido_id = criar_pedido_compra_interno(
        conn, usuario_atual, fornecedor_id, dados.get("itens"), observacoes=dados.get("observacoes")
    )
    return jsonify(_pedido_detalhado(conn, pedido_id)), 201


def _executar_envio_pedido(conn, pedido, usuario_atual, envio_pendente_id=None):
    """Efetivamente muda o pedido de 'rascunho' para 'enviado' — o que era
    todo o corpo de `enviar_pedido` antes da Fase 61. Extraído para um
    helper porque agora existem DOIS caminhos que chegam aqui: o envio
    direto (abaixo do limiar de alçada, ou limiar desligado) e a aprovação
    de uma solicitação pendente (`aprovar_envio_pedido`, acima do limiar) —
    ambos precisam do mesmo cálculo de data prevista de entrega (Fase 60) e
    do mesmo registro de auditoria, só muda o que disparou a chamada
    (`envio_pendente_id` fica registrado na auditoria só no segundo caso,
    para rastrear qual solicitação originou o envio)."""
    pedido_id = pedido["id"]
    agora = _now_iso()
    # Fase 60 — congela a data prevista de entrega NESTE instante, a
    # partir do lead_time_dias do fornecedor (Fase 57). Fornecedor sem
    # lead time configurado -> fica NULL, sem inventar prazo (mesma nota
    # de escopo de migrations/schema_fase60.sql).
    data_prevista_entrega = None
    fornecedor = conn.execute("SELECT lead_time_dias FROM fornecedores WHERE id = ?", (pedido["fornecedor_id"],)).fetchone()
    if fornecedor and fornecedor["lead_time_dias"] is not None:
        data_envio = datetime.datetime.strptime(agora[:10], "%Y-%m-%d")
        data_prevista_entrega = (data_envio + datetime.timedelta(days=fornecedor["lead_time_dias"])).strftime("%Y-%m-%d")

    conn.execute(
        "UPDATE pedidos_compra SET status = 'enviado', enviado_em = ?, enviado_por = ?, data_prevista_entrega = ? WHERE id = ?",
        (agora, usuario_atual["id"], data_prevista_entrega, pedido_id),
    )
    conn.commit()
    valor_novo = {"data_prevista_entrega": data_prevista_entrega}
    if envio_pendente_id is not None:
        valor_novo["envio_pendente_id"] = envio_pendente_id
    audit.registrar(conn, tabela="pedidos_compra", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_compra_enviado",
                     valor_novo=valor_novo,
                     ip=client_ip(), dispositivo=client_device())


@bp.post("/pedidos/<int:pedido_id>/enviar")
@requires_permission("compras", "enviar_pedido")
def enviar_pedido(pedido_id):
    """rascunho -> enviado — a partir daqui o recebimento de lote (Fase 2)
    já pode ser vinculado a este pedido. Mesma segregação já usada em todo
    o sistema entre "montar" e "comprometer de fato" (ex.: Comercial —
    criar_pedido vs. confirmar_pedido, desde a Fase 5).

    Fase 61 — se o valor total do pedido ultrapassar o limiar de alçada
    configurado (`configuracoes_compras.limiar_valor_pedido_grande`, "0"
    desliga o controle), o envio não acontece na hora: vira uma
    solicitação pendente (`pedidos_compra_envios_pendentes`) até um
    segundo usuário aprovar (ver `aprovar_envio_pedido` abaixo). Mesmo
    formato de resposta 202 já usado por `registrar_baixa_pagar` em
    app/routes/financeiro.py desde a Fase 31."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] != "rascunho":
        raise ApiError(f"Só é possível enviar um pedido em rascunho (status atual: '{pedido['status']}').", status=400)

    limiar = _configuracao_compras(conn)["limiar_valor_pedido_grande"]
    valor_total = _valor_total_pedido(conn, pedido_id)
    if limiar > 0 and valor_total > limiar:
        cur = conn.execute(
            "INSERT INTO pedidos_compra_envios_pendentes (pedido_compra_id, valor_total, solicitado_por) VALUES (?, ?, ?)",
            (pedido_id, valor_total, usuario_atual["id"]),
        )
        conn.commit()
        audit.registrar(conn, tabela="pedidos_compra_envios_pendentes", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                         acao="pedido_compra_envio_solicitado",
                         valor_novo={"pedido_compra_id": pedido_id, "valor_total": valor_total},
                         ip=client_ip(), dispositivo=client_device())
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="compras", acao="aprovar_pedido_grande",
            tipo="pedido_compra_envio_pendente",
            mensagem=(
                f"O envio do pedido de compra {pedido['numero']} (R$ {valor_total:.2f}) está acima da "
                "alçada e precisa de segunda aprovação."
            ),
            excluir_usuario_id=usuario_atual["id"],
        )
        resultado = _pedido_detalhado(conn, pedido_id)
        resultado["envio_pendente_criado_id"] = cur.lastrowid
        return jsonify(resultado), 202

    _executar_envio_pedido(conn, pedido, usuario_atual)
    return jsonify(_pedido_detalhado(conn, pedido_id))


def _envio_pendente_ou_erro(conn, pendente_id):
    row = conn.execute("SELECT * FROM pedidos_compra_envios_pendentes WHERE id = ?", (pendente_id,)).fetchone()
    if row is None:
        raise ApiError("Solicitação de envio não encontrada.", status=404)
    row = dict(row)
    if row["status"] != "pendente":
        raise ApiError(f"Esta solicitação de envio já está '{row['status']}'.", status=400)
    return row


@bp.post("/pedidos/envios-pendentes/<int:pendente_id>/aprovar")
@requires_permission("compras", "aprovar_pedido_grande")
def aprovar_envio_pedido(pendente_id):
    """Aprova uma solicitação de envio acima da alçada — efetivamente
    envia o pedido ao fornecedor (mesmo cálculo de data prevista de
    entrega do envio direto, via `_executar_envio_pedido`). Mesma
    segregação de função de `aprovar_baixa_pagar` em
    app/routes/financeiro.py: quem solicitou não pode aprovar."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    pendente = _envio_pendente_ou_erro(conn, pendente_id)

    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou o envio deste pedido e por isso não pode aprová-lo — a aprovação precisa ser "
            "feita por outro usuário (segregação de função)."
        )

    pedido_id = pendente["pedido_compra_id"]
    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] != "rascunho":
        raise ApiError(
            f"Este pedido não está mais em rascunho (status atual: '{pedido['status']}') — não é possível "
            "aprovar o envio.",
            status=400,
        )

    _executar_envio_pedido(conn, pedido, usuario_atual, envio_pendente_id=pendente_id)
    conn.execute(
        "UPDATE pedidos_compra_envios_pendentes SET status = 'aprovado', decidido_por = ?, decidido_em = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), pendente_id),
    )
    conn.commit()
    return jsonify(_pedido_detalhado(conn, pedido_id))


@bp.post("/pedidos/envios-pendentes/<int:pendente_id>/rejeitar")
@requires_permission("compras", "aprovar_pedido_grande")
def rejeitar_envio_pedido(pendente_id):
    """Rejeita a solicitação — o pedido permanece em 'rascunho' (pode ser
    editado/cancelado ou ter o envio solicitado de novo depois). Mesmo
    formato de `rejeitar_baixa_pagar` em app/routes/financeiro.py."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo_rejeicao = (dados.get("motivo") or "").strip()
    conn = get_db()
    pendente = _envio_pendente_ou_erro(conn, pendente_id)

    if not motivo_rejeicao:
        raise ApiError("Informe o motivo da rejeição.", status=400)
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou o envio deste pedido e por isso não pode decidir sobre ele — a decisão precisa "
            "ser tomada por outro usuário (segregação de função)."
        )

    conn.execute(
        "UPDATE pedidos_compra_envios_pendentes SET status = 'rejeitado', decidido_por = ?, decidido_em = ?, motivo_rejeicao = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), motivo_rejeicao, pendente_id),
    )
    audit.registrar(conn, tabela="pedidos_compra_envios_pendentes", registro_id=pendente_id, usuario_id=usuario_atual["id"],
                     acao="pedido_compra_envio_rejeitado",
                     valor_novo={"pedido_compra_id": pendente["pedido_compra_id"], "valor_total": pendente["valor_total"]},
                     motivo=motivo_rejeicao, ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pendente["pedido_compra_id"]))


# ============================================================
# CONFIGURAÇÃO DO MÓDULO COMPRAS (Fase 61)
# ============================================================
@bp.get("/configuracao")
@requires_permission("compras", "configurar_alcada_pedido")
def obter_configuracao():
    conn = get_db()
    return jsonify(_configuracao_compras(conn))


@bp.put("/configuracao")
@requires_permission("compras", "configurar_alcada_pedido")
def editar_configuracao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    atual = _configuracao_compras(conn)

    limiar_valor_pedido_grande = dados.get("limiar_valor_pedido_grande", atual["limiar_valor_pedido_grande"])
    try:
        limiar_valor_pedido_grande = float(limiar_valor_pedido_grande)
    except (TypeError, ValueError):
        raise ApiError("limiar_valor_pedido_grande deve ser numérico.", status=400)
    if limiar_valor_pedido_grande < 0:
        raise ApiError("limiar_valor_pedido_grande não pode ser negativo.", status=400)

    # Fase 73 (achado de auditoria — Fase 72): esta era uma das duas
    # tabelas de configuração singleton que ainda usava UPDATE simples em
    # vez do padrão INSERT...ON CONFLICT DO UPDATE já usado nas outras 7
    # (ver o mesmo comentário em vendas_app.py:editar_configuracao). Um
    # UPDATE simples silenciosamente não faz nada se a linha id=1 nunca
    # existiu; o upsert cria a linha se faltar, atualiza se já existir.
    conn.execute(
        """
        INSERT INTO configuracoes_compras (id, limiar_valor_pedido_grande, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            limiar_valor_pedido_grande = excluded.limiar_valor_pedido_grande,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (limiar_valor_pedido_grande, _now_iso(), usuario_atual["id"]),
    )
    audit.registrar(conn, tabela="configuracoes_compras", registro_id=1, usuario_id=usuario_atual["id"],
                     acao="configuracao_compras_alterada", valor_anterior=atual,
                     valor_novo={"limiar_valor_pedido_grande": limiar_valor_pedido_grande},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_configuracao_compras(conn))


@bp.post("/pedidos/<int:pedido_id>/cancelar")
@requires_permission("compras", "cancelar_pedido")
def cancelar_pedido(pedido_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] not in ("rascunho", "enviado"):
        raise ApiError(
            f"Só é possível cancelar um pedido em rascunho ou enviado (status atual: '{pedido['status']}').",
            status=400,
        )
    total_recebido = conn.execute(
        "SELECT COALESCE(SUM(quantidade_recebida), 0) AS total FROM itens_pedido_compra WHERE pedido_compra_id = ?",
        (pedido_id,),
    ).fetchone()["total"]
    if total_recebido > 0:
        raise ApiError(
            "Este pedido já tem recebimento registrado contra ele e não pode mais ser cancelado.", status=400
        )

    conn.execute(
        """
        UPDATE pedidos_compra
        SET status = 'cancelado', cancelado_em = ?, cancelado_por = ?, motivo_cancelamento = ?
        WHERE id = ?
        """,
        (_now_iso(), usuario_atual["id"], motivo, pedido_id),
    )
    conn.commit()
    audit.registrar(conn, tabela="pedidos_compra", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_compra_cancelado", motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pedido_id))


@bp.post("/pedidos/<int:pedido_id>/gerar-conta-pagar")
# Fase 59 — MESMA permissão exigida pela criação direta em Financeiro
# (`POST /financeiro/contas-pagar`), porque é exatamente a mesma ação
# sensível (lançar uma obrigação financeira real), só chegando por um
# atalho que pré-calcula fornecedor e valor a partir do que já foi
# recebido. Ver a nota de escopo completa em migrations/schema_fase59.sql
# — isto continua sendo uma ação explícita, nunca automática no
# recebimento.
@requires_permission("financeiro", "criar_conta_pagar")
def gerar_conta_pagar_do_pedido(pedido_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    pedido = dict(_pedido_ou_404(conn, pedido_id))
    if pedido["conta_pagar_id"]:
        raise ApiError(
            "Este pedido de compra já tem uma conta a pagar gerada por este caminho — para uma NF adicional "
            "(ex.: fornecedor faturando em partes), lance manualmente em Financeiro.",
            status=409,
        )
    if pedido["status"] not in ("parcialmente_recebido", "recebido"):
        raise ApiError(
            f"Só é possível gerar a conta a pagar depois que algo tiver sido recebido contra este pedido "
            f"(status atual: '{pedido['status']}').",
            status=400,
        )

    linhas = conn.execute(
        "SELECT * FROM itens_pedido_compra WHERE pedido_compra_id = ? AND quantidade_recebida > 0 ORDER BY id",
        (pedido_id,),
    ).fetchall()
    valor_total = 0.0
    for linha in linhas:
        if linha["preco_unitario"] is None:
            item = conn.execute("SELECT codigo FROM itens WHERE id = ?", (linha["item_id"],)).fetchone()
            raise ApiError(
                f"O item {item['codigo'] if item else linha['item_id']} não tem preço unitário definido neste "
                "pedido — informe o preço (cancele e recrie o pedido com o preço, ou lance a conta a pagar "
                "manualmente em Financeiro) antes de gerar a conta por aqui.",
                status=400,
            )
        valor_total += linha["preco_unitario"] * linha["quantidade_recebida"]
    valor_total = round(valor_total, 2)
    if valor_total <= 0:
        # Não deveria acontecer dado o filtro em quantidade_recebida > 0
        # acima e a checagem de status logo no início — mantido como
        # última linha de defesa.
        raise ApiError("Nada foi recebido ainda contra este pedido.", status=400)

    vencimento = (dados.get("vencimento") or "").strip()
    if not vencimento:
        raise ApiError("Informe vencimento (AAAA-MM-DD).", status=400)
    descricao = (dados.get("descricao") or "").strip() or f"Nota fiscal referente ao Pedido de Compra {pedido['numero']}"
    empresa_id = dados.get("empresa_id")

    conta_id = criar_conta_pagar_interno(
        conn, usuario_atual, fornecedor_id=pedido["fornecedor_id"], descricao=descricao,
        valor_total=valor_total, vencimento=vencimento, categoria="compra",
        empresa_id=empresa_id, pedido_compra_id=pedido_id,
    )
    conn.execute("UPDATE pedidos_compra SET conta_pagar_id = ? WHERE id = ?", (conta_id, pedido_id))
    conn.commit()
    audit.registrar(conn, tabela="pedidos_compra", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_compra_conta_pagar_gerada", valor_novo={"conta_pagar_id": conta_id, "valor_total": valor_total},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pedido_id)), 201


# ---------------------------------------------------------------------
# Chamadas por app/routes/lotes.py no recebimento (Fase 2) quando o
# formulário informa `pedido_compra_id` — mantidas aqui (não em lotes.py)
# porque são lógica do PEDIDO (validar saldo, abater, recalcular status),
# não do LOTE. `validar_pedido_para_recebimento` roda ANTES de criar o
# lote (falha rápido, sem deixar nenhum lote "órfão" com um vínculo
# inválido); `dar_baixa_recebimento_no_pedido` roda DEPOIS, já com o
# `lote_id` gerado para o registro de auditoria.
# ---------------------------------------------------------------------
def validar_pedido_para_recebimento(conn, pedido_id, item_id):
    """Confere que o pedido existe, está num status que aceita
    recebimento, e que o item informado faz parte dele. Devolve o pedido
    (dict) — quem chama usa, por exemplo, para preencher `fornecedor_id`
    automaticamente quando o recebimento não o informa."""
    pedido = dict(_pedido_ou_404(conn, pedido_id))
    if pedido["status"] not in ("enviado", "parcialmente_recebido"):
        raise ApiError(
            f"Este pedido de compra está com status '{pedido['status']}' e não pode receber "
            "material agora — só pedidos 'enviado' ou 'parcialmente_recebido' aceitam recebimento.",
            status=400,
        )
    linha = conn.execute(
        "SELECT * FROM itens_pedido_compra WHERE pedido_compra_id = ? AND item_id = ?",
        (pedido_id, item_id),
    ).fetchone()
    if linha is None:
        raise ApiError(
            "Este item não faz parte do pedido de compra informado — confira o pedido ou receba sem "
            "vínculo a um pedido.",
            status=400,
        )
    return pedido


def dar_baixa_recebimento_no_pedido(conn, pedido_id, item_id, quantidade_recebida_agora, usuario_atual, lote_id):
    """Pressupõe que `validar_pedido_para_recebimento` já foi chamada com
    sucesso para o mesmo (pedido_id, item_id) — chamada de novo aqui
    porque o pedido pode, em teoria, ter mudado de status entre as duas
    chamadas (não há transação cobrindo as duas); se mudou, falha aqui
    antes de abater qualquer coisa, e o lote já criado fica sem vínculo
    de recebimento efetivo contra o pedido (mas continua existindo — o
    recebimento do material em si já aconteceu de verdade)."""
    validar_pedido_para_recebimento(conn, pedido_id, item_id)
    linha = conn.execute(
        "SELECT * FROM itens_pedido_compra WHERE pedido_compra_id = ? AND item_id = ?",
        (pedido_id, item_id),
    ).fetchone()

    conn.execute(
        "UPDATE itens_pedido_compra SET quantidade_recebida = quantidade_recebida + ? WHERE id = ?",
        (quantidade_recebida_agora, linha["id"]),
    )

    linhas_atualizadas = conn.execute(
        "SELECT quantidade_pedida, quantidade_recebida FROM itens_pedido_compra WHERE pedido_compra_id = ?",
        (pedido_id,),
    ).fetchall()
    todas_completas = all(l["quantidade_recebida"] >= l["quantidade_pedida"] for l in linhas_atualizadas)
    novo_status = "recebido" if todas_completas else "parcialmente_recebido"

    if novo_status == "recebido":
        conn.execute(
            "UPDATE pedidos_compra SET status = ?, concluido_em = ? WHERE id = ?",
            (novo_status, _now_iso(), pedido_id),
        )
    else:
        conn.execute("UPDATE pedidos_compra SET status = ? WHERE id = ?", (novo_status, pedido_id))
    conn.commit()

    audit.registrar(
        conn, tabela="pedidos_compra", registro_id=pedido_id, usuario_id=usuario_atual["id"],
        acao="pedido_compra_recebimento_vinculado",
        valor_novo={"item_id": item_id, "quantidade": quantidade_recebida_agora, "lote_id": lote_id, "novo_status": novo_status},
        ip=client_ip(), dispositivo=client_device(),
    )
