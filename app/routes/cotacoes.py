"""
Fase 66 — Cotação Comparativa de Fornecedores (RFQ) antes do Pedido de
Compra.

Ver a nota completa de escopo em migrations/schema_fase66.sql. Resumo do
ciclo de vida: aberta -> fechada (com um fornecedor vencedor escolhido,
gerando automaticamente o Pedido de Compra formal da Fase 58) ou aberta ->
cancelada (sem gerar nada). Uma cotação nasce com a lista de itens a
comprar e os fornecedores convidados a cotar; cada fornecedor convidado
recebe uma resposta (preço por item + prazo opcional) registrada por um
usuário interno de Compras — não há portal externo para o fornecedor
responder diretamente (ver decisão de escopo #2 na migration).
"""
import datetime
import secrets

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission
# Reaproveita o núcleo de criação de pedido de compra já usado desde a
# Fase 58 (criação manual) e Fase 54 (a partir de uma sugestão do MRP) —
# fechar uma cotação escolhendo o vencedor é só mais uma origem possível
# para um Pedido de Compra novo, sempre nascendo em 'rascunho'.
from .compras import _fornecedor_ou_404, _item_ou_404, criar_pedido_compra_interno

bp = Blueprint("cotacoes", __name__, url_prefix="/api/v1/compras/cotacoes")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _gerar_numero_cotacao():
    ano = datetime.datetime.utcnow().year
    return f"COT-{ano}-{secrets.token_hex(4).upper()}"


def _cotacao_ou_404(conn, cotacao_id):
    row = conn.execute("SELECT * FROM cotacoes WHERE id = ?", (cotacao_id,)).fetchone()
    if row is None:
        raise ApiError("Cotação não encontrada.", status=404)
    return row


def _cotacao_detalhada(conn, cotacao_id):
    cotacao = dict(_cotacao_ou_404(conn, cotacao_id))

    if cotacao["fornecedor_vencedor_id"]:
        vencedor = conn.execute(
            "SELECT nome FROM fornecedores WHERE id = ?", (cotacao["fornecedor_vencedor_id"],)
        ).fetchone()
        cotacao["fornecedor_vencedor_nome"] = vencedor["nome"] if vencedor else None
    else:
        cotacao["fornecedor_vencedor_nome"] = None

    if cotacao["pedido_compra_gerado_id"]:
        pedido = conn.execute(
            "SELECT numero FROM pedidos_compra WHERE id = ?", (cotacao["pedido_compra_gerado_id"],)
        ).fetchone()
        cotacao["pedido_compra_gerado_numero"] = pedido["numero"] if pedido else None
    else:
        cotacao["pedido_compra_gerado_numero"] = None

    linhas_itens = conn.execute(
        "SELECT * FROM cotacao_itens WHERE cotacao_id = ? ORDER BY id", (cotacao_id,)
    ).fetchall()
    itens = []
    for linha in linhas_itens:
        d = dict(linha)
        item = conn.execute("SELECT codigo, descricao FROM itens WHERE id = ?", (d["item_id"],)).fetchone()
        d["item_codigo"] = item["codigo"] if item else None
        d["item_descricao"] = item["descricao"] if item else None
        itens.append(d)
    cotacao["itens"] = itens

    linhas_convidados = conn.execute(
        """
        SELECT cfc.id, cfc.fornecedor_id, f.nome AS fornecedor_nome
        FROM cotacao_fornecedores_convidados cfc
        JOIN fornecedores f ON f.id = cfc.fornecedor_id
        WHERE cfc.cotacao_id = ?
        ORDER BY f.nome
        """,
        (cotacao_id,),
    ).fetchall()

    respostas_todas = conn.execute(
        "SELECT * FROM cotacao_respostas WHERE cotacao_id = ?", (cotacao_id,)
    ).fetchall()
    respostas_por_fornecedor = {}
    for r in respostas_todas:
        respostas_por_fornecedor.setdefault(r["fornecedor_id"], []).append(dict(r))

    total_itens = len(itens)
    fornecedores = []
    for c in linhas_convidados:
        respostas = respostas_por_fornecedor.get(c["fornecedor_id"], [])
        valor_total = round(sum(r["preco_unitario"] * next(
            (it["quantidade"] for it in itens if it["item_id"] == r["item_id"]), 0
        ) for r in respostas), 2)
        fornecedores.append({
            "id": c["id"],
            "fornecedor_id": c["fornecedor_id"],
            "fornecedor_nome": c["fornecedor_nome"],
            "respostas": respostas,
            "total_itens_respondidos": len(respostas),
            "respondeu_todos_itens": total_itens > 0 and len(respostas) == total_itens,
            "valor_total_estimado": valor_total,
        })
    cotacao["fornecedores"] = fornecedores
    return cotacao


@bp.get("")
@requires_permission("compras", "visualizar")
def listar_cotacoes():
    conn = get_db()
    status_filtro = request.args.get("status")
    query = "SELECT * FROM cotacoes"
    params = []
    if status_filtro:
        query += " WHERE status = ?"
        params.append(status_filtro)
    query += " ORDER BY id DESC"
    linhas = conn.execute(query, params).fetchall()
    resultado = []
    for linha in linhas:
        d = dict(linha)
        d["total_itens"] = conn.execute(
            "SELECT COUNT(*) AS n FROM cotacao_itens WHERE cotacao_id = ?", (d["id"],)
        ).fetchone()["n"]
        d["total_fornecedores_convidados"] = conn.execute(
            "SELECT COUNT(*) AS n FROM cotacao_fornecedores_convidados WHERE cotacao_id = ?", (d["id"],)
        ).fetchone()["n"]
        resultado.append(d)
    return jsonify(resultado)


@bp.get("/<int:cotacao_id>")
@requires_permission("compras", "visualizar")
def obter_cotacao(cotacao_id):
    return jsonify(_cotacao_detalhada(get_db(), cotacao_id))


@bp.post("")
@requires_permission("compras", "criar_cotacao")
def criar_cotacao():
    usuario_atual = g.usuario_atual
    conn = get_db()
    payload = request.get_json(silent=True) or {}

    itens_payload = payload.get("itens")
    if not itens_payload or not isinstance(itens_payload, list):
        raise ApiError("Informe itens: uma lista com ao menos um item a cotar.", status=400)

    vistos = set()
    itens_normalizados = []
    for i, item_payload in enumerate(itens_payload):
        item_id = item_payload.get("item_id")
        quantidade = item_payload.get("quantidade")
        unidade = (item_payload.get("unidade") or "").strip()
        if not item_id:
            raise ApiError(f"Item na posição {i}: informe item_id.", status=400)
        if item_id in vistos:
            raise ApiError(f"O item {item_id} aparece mais de uma vez na lista de itens a cotar.", status=400)
        vistos.add(item_id)
        _item_ou_404(conn, item_id)
        try:
            quantidade = float(quantidade)
        except (TypeError, ValueError):
            raise ApiError(f"Item na posição {i}: quantidade deve ser numérica.", status=400)
        if quantidade <= 0:
            raise ApiError(f"Item na posição {i}: quantidade deve ser maior que zero.", status=400)
        if not unidade:
            raise ApiError(f"Item na posição {i}: informe unidade.", status=400)
        itens_normalizados.append({"item_id": item_id, "quantidade": quantidade, "unidade": unidade})

    fornecedores_payload = payload.get("fornecedores_convidados")
    if not fornecedores_payload or not isinstance(fornecedores_payload, list):
        raise ApiError("Informe fornecedores_convidados: uma lista com ao menos um fornecedor a cotar.", status=400)
    fornecedores_vistos = set()
    for fornecedor_id in fornecedores_payload:
        if fornecedor_id in fornecedores_vistos:
            raise ApiError(f"O fornecedor {fornecedor_id} aparece mais de uma vez em fornecedores_convidados.", status=400)
        fornecedores_vistos.add(fornecedor_id)
        _fornecedor_ou_404(conn, fornecedor_id)

    numero = _gerar_numero_cotacao()
    cur = conn.execute(
        "INSERT INTO cotacoes (numero, observacoes, criado_por) VALUES (?, ?, ?)",
        (numero, (payload.get("observacoes") or "").strip() or None, usuario_atual["id"]),
    )
    cotacao_id = cur.lastrowid

    for item in itens_normalizados:
        conn.execute(
            "INSERT INTO cotacao_itens (cotacao_id, item_id, quantidade, unidade) VALUES (?, ?, ?, ?)",
            (cotacao_id, item["item_id"], item["quantidade"], item["unidade"]),
        )
    for fornecedor_id in fornecedores_vistos:
        conn.execute(
            "INSERT INTO cotacao_fornecedores_convidados (cotacao_id, fornecedor_id) VALUES (?, ?)",
            (cotacao_id, fornecedor_id),
        )
    conn.commit()

    audit.registrar(
        conn, tabela="cotacoes", registro_id=cotacao_id, usuario_id=usuario_atual["id"],
        acao="cotacao_criada",
        valor_novo={"numero": numero, "total_itens": len(itens_normalizados), "total_fornecedores": len(fornecedores_vistos)},
        ip=client_ip(), dispositivo=client_device(),
    )

    return jsonify(_cotacao_detalhada(conn, cotacao_id)), 201


@bp.post("/<int:cotacao_id>/respostas")
@requires_permission("compras", "registrar_resposta_cotacao")
def registrar_resposta_cotacao(cotacao_id):
    """Registra (ou substitui integralmente) a resposta de UM fornecedor
    convidado a esta cotação — ver decisão de escopo #2 e a nota sobre
    substituição em migrations/schema_fase66.sql: quem chama esta rota é
    sempre um usuário interno de Compras digitando o que o fornecedor
    respondeu por telefone/e-mail, e reenviar substitui a resposta
    anterior por completo (não acumula)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    cotacao = _cotacao_ou_404(conn, cotacao_id)
    if cotacao["status"] != "aberta":
        raise ApiError(f"Só é possível registrar respostas em uma cotação aberta (status atual: '{cotacao['status']}').", status=400)

    payload = request.get_json(silent=True) or {}
    fornecedor_id = payload.get("fornecedor_id")
    if not fornecedor_id:
        raise ApiError("Informe fornecedor_id.", status=400)

    convidado = conn.execute(
        "SELECT id FROM cotacao_fornecedores_convidados WHERE cotacao_id = ? AND fornecedor_id = ?",
        (cotacao_id, fornecedor_id),
    ).fetchone()
    if convidado is None:
        raise ApiError("Este fornecedor não foi convidado para esta cotação.", status=400)

    itens_cotacao = {
        r["item_id"] for r in conn.execute(
            "SELECT item_id FROM cotacao_itens WHERE cotacao_id = ?", (cotacao_id,)
        ).fetchall()
    }

    respostas_payload = payload.get("respostas")
    if not respostas_payload or not isinstance(respostas_payload, list):
        raise ApiError("Informe respostas: uma lista com ao menos um item respondido.", status=400)

    vistos = set()
    respostas_normalizadas = []
    for i, resposta in enumerate(respostas_payload):
        item_id = resposta.get("item_id")
        preco_unitario = resposta.get("preco_unitario")
        prazo_entrega_dias = resposta.get("prazo_entrega_dias")

        if not item_id:
            raise ApiError(f"Resposta na posição {i}: informe item_id.", status=400)
        if item_id not in itens_cotacao:
            raise ApiError(f"O item {item_id} não faz parte desta cotação.", status=400)
        if item_id in vistos:
            raise ApiError(f"O item {item_id} aparece mais de uma vez nas respostas.", status=400)
        vistos.add(item_id)

        try:
            preco_unitario = float(preco_unitario)
        except (TypeError, ValueError):
            raise ApiError(f"Resposta na posição {i}: preco_unitario deve ser numérico.", status=400)
        if preco_unitario < 0:
            raise ApiError(f"Resposta na posição {i}: preco_unitario não pode ser negativo.", status=400)

        if prazo_entrega_dias is not None and prazo_entrega_dias != "":
            try:
                prazo_entrega_dias = int(prazo_entrega_dias)
            except (TypeError, ValueError):
                raise ApiError(f"Resposta na posição {i}: prazo_entrega_dias deve ser um número inteiro de dias.", status=400)
            if prazo_entrega_dias < 0:
                raise ApiError(f"Resposta na posição {i}: prazo_entrega_dias não pode ser negativo.", status=400)
        else:
            prazo_entrega_dias = None

        respostas_normalizadas.append({
            "item_id": item_id, "preco_unitario": preco_unitario, "prazo_entrega_dias": prazo_entrega_dias,
        })

    agora = _now_iso()
    # Substitui integralmente a resposta anterior deste fornecedor nesta
    # cotação (ver nota de escopo no docstring acima).
    conn.execute(
        "DELETE FROM cotacao_respostas WHERE cotacao_id = ? AND fornecedor_id = ?",
        (cotacao_id, fornecedor_id),
    )
    for resposta in respostas_normalizadas:
        conn.execute(
            """
            INSERT INTO cotacao_respostas
                (cotacao_id, fornecedor_id, item_id, preco_unitario, prazo_entrega_dias, registrado_em, registrado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cotacao_id, fornecedor_id, resposta["item_id"], resposta["preco_unitario"],
             resposta["prazo_entrega_dias"], agora, usuario_atual["id"]),
        )
    conn.commit()

    audit.registrar(
        conn, tabela="cotacao_respostas", registro_id=cotacao_id, usuario_id=usuario_atual["id"],
        acao="cotacao_resposta_registrada",
        valor_novo={"fornecedor_id": fornecedor_id, "total_itens_respondidos": len(respostas_normalizadas)},
        ip=client_ip(), dispositivo=client_device(),
    )

    return jsonify(_cotacao_detalhada(conn, cotacao_id))


@bp.post("/<int:cotacao_id>/fechar")
@requires_permission("compras", "fechar_cotacao")
def fechar_cotacao(cotacao_id):
    """Escolhe o fornecedor vencedor e gera automaticamente o Pedido de
    Compra correspondente (ver decisão de escopo #1 e #3 em
    migrations/schema_fase66.sql: um vencedor por cotação inteira, e ele
    precisa ter respondido preço para TODOS os itens da cotação)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    cotacao = _cotacao_ou_404(conn, cotacao_id)
    if cotacao["status"] != "aberta":
        raise ApiError(f"Só é possível fechar uma cotação aberta (status atual: '{cotacao['status']}').", status=400)

    payload = request.get_json(silent=True) or {}
    fornecedor_vencedor_id = payload.get("fornecedor_vencedor_id")
    if not fornecedor_vencedor_id:
        raise ApiError("Informe fornecedor_vencedor_id.", status=400)

    convidado = conn.execute(
        "SELECT id FROM cotacao_fornecedores_convidados WHERE cotacao_id = ? AND fornecedor_id = ?",
        (cotacao_id, fornecedor_vencedor_id),
    ).fetchone()
    if convidado is None:
        raise ApiError("O fornecedor escolhido como vencedor não foi convidado para esta cotação.", status=400)

    itens_cotacao = conn.execute(
        "SELECT item_id, quantidade, unidade FROM cotacao_itens WHERE cotacao_id = ?", (cotacao_id,)
    ).fetchall()
    respostas_vencedor = {
        r["item_id"]: r for r in conn.execute(
            "SELECT * FROM cotacao_respostas WHERE cotacao_id = ? AND fornecedor_id = ?",
            (cotacao_id, fornecedor_vencedor_id),
        ).fetchall()
    }

    itens_faltando = [it["item_id"] for it in itens_cotacao if it["item_id"] not in respostas_vencedor]
    if itens_faltando:
        raise ApiError(
            "O fornecedor escolhido não respondeu preço para todos os itens desta cotação "
            f"(faltam {len(itens_faltando)} de {len(itens_cotacao)}) — registre a resposta completa antes de fechar.",
            status=400,
        )

    itens_pedido_payload = [
        {
            "item_id": it["item_id"],
            "quantidade_pedida": it["quantidade"],
            "unidade": it["unidade"],
            "preco_unitario": respostas_vencedor[it["item_id"]]["preco_unitario"],
        }
        for it in itens_cotacao
    ]

    observacoes_pedido = f"Gerado a partir da cotação {cotacao['numero']}."
    pedido_id = criar_pedido_compra_interno(
        conn, usuario_atual, fornecedor_vencedor_id, itens_pedido_payload, observacoes=observacoes_pedido
    )

    conn.execute(
        """
        UPDATE cotacoes
        SET status = 'fechada', fornecedor_vencedor_id = ?, pedido_compra_gerado_id = ?,
            fechado_em = ?, fechado_por = ?
        WHERE id = ?
        """,
        (fornecedor_vencedor_id, pedido_id, _now_iso(), usuario_atual["id"], cotacao_id),
    )
    conn.commit()

    audit.registrar(
        conn, tabela="cotacoes", registro_id=cotacao_id, usuario_id=usuario_atual["id"],
        acao="cotacao_fechada",
        valor_novo={"fornecedor_vencedor_id": fornecedor_vencedor_id, "pedido_compra_gerado_id": pedido_id},
        ip=client_ip(), dispositivo=client_device(),
    )
    notificacoes_service.notificar_usuarios_com_permissao(
        conn, modulo="compras", acao="visualizar",
        tipo="cotacao_fechada",
        mensagem=(
            f"A cotação {cotacao['numero']} foi fechada — o Pedido de Compra foi gerado automaticamente "
            "a partir da resposta do fornecedor vencedor."
        ),
        excluir_usuario_id=usuario_atual["id"],
    )

    return jsonify(_cotacao_detalhada(conn, cotacao_id))


@bp.post("/<int:cotacao_id>/cancelar")
@requires_permission("compras", "cancelar_cotacao")
def cancelar_cotacao(cotacao_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    cotacao = _cotacao_ou_404(conn, cotacao_id)
    if cotacao["status"] != "aberta":
        raise ApiError(f"Só é possível cancelar uma cotação aberta (status atual: '{cotacao['status']}').", status=400)

    payload = request.get_json(silent=True) or {}
    motivo = (payload.get("motivo") or "").strip() or None

    conn.execute(
        "UPDATE cotacoes SET status = 'cancelada', cancelado_em = ?, cancelado_por = ?, motivo_cancelamento = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], motivo, cotacao_id),
    )
    conn.commit()

    audit.registrar(
        conn, tabela="cotacoes", registro_id=cotacao_id, usuario_id=usuario_atual["id"],
        acao="cotacao_cancelada", valor_novo={"motivo": motivo},
        ip=client_ip(), dispositivo=client_device(),
    )

    return jsonify(_cotacao_detalhada(conn, cotacao_id))
