"""
Fase 6 — Financeiro básico: Contas a Receber (geradas automaticamente ao
expedir um pedido de venda — ver comercial.py:expedir) e Contas a Pagar
(lançadas manualmente contra um fornecedor, com referência opcional a um
lote recebido para rastreabilidade).

Mesmo princípio de saldo já usado em toda a rastreabilidade do sistema: o
valor em aberto de uma conta é sempre `valor_total - SUM(baixas)`, nunca um
número guardado à parte — e as baixas em si são um ledger append-only,
igual a movimentacoes_estoque (Fase 4) e pedido_venda_reservas (Fase 5).
O campo `status` na tabela é uma etiqueta explícita ('aberto'/
'pago_parcial'/'pago'/'cancelado') recalculada em código a cada baixa —
o mesmo padrão usado em pedidos_venda.status, lotes.status etc: o estado
do "documento pai" é sempre armazenado e transicionado explicitamente,
só os ledgers por baixo dele são somados dinamicamente.
"""
import base64
import datetime
import secrets

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..ofx_parser import parse_ofx
from ..permissions import requires_permission

bp = Blueprint("financeiro", __name__, url_prefix="/api/v1/financeiro")

FORMAS_PAGAMENTO = ("dinheiro", "pix", "boleto", "cartao", "transferencia")

# Fase 22 — acima deste valor, um estorno de baixa não reverte na hora:
# fica como solicitação pendente até um segundo usuário aprovar. Abaixo
# do limiar, continua revertendo na hora, exatamente como desde a Fase 14.
LIMIAR_VALOR_ESTORNO_DUPLA_APROVACAO = 1000.0

# Fase 31 — acima deste valor, REGISTRAR uma baixa nova (recebimento ou
# pagamento) não entra direto no ledger: fica como solicitação pendente
# até um segundo usuário aprovar. Abaixo do limiar, continua entrando
# direto no ledger, exatamente como desde a Fase 6. Valor deliberadamente
# igual ao da Fase 22 (mesma ordem de grandeza do que a empresa considera
# "alto risco" — nada no domínio justifica um limiar diferente por só
# registrar em vez de estornar), mas como uma constante própria: dá pra
# afastar os dois no futuro sem confundir os dois fluxos.
LIMIAR_VALOR_BAIXA_DUPLA_APROVACAO = 1000.0


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _limite_dias_estorno_baixa(conn):
    """Fase 33 — lê o limite de dias configurado (0 = sem limite, o
    comportamento padrão, idêntico ao que existe desde a Fase 14). Mesmo
    padrão de "configuração de uma linha só" da Fase 32
    (`configuracoes_estoque`), aqui para o domínio financeiro."""
    row = conn.execute("SELECT limite_dias_estorno_baixa FROM configuracoes_financeiro WHERE id = 1").fetchone()
    return row["limite_dias_estorno_baixa"] if row else 0


def _checar_prazo_estorno(conn, baixa):
    """Levanta ApiError se o limite de dias estiver configurado (>0) e a
    baixa original já tiver passado dele. Conta a partir de `criado_em`
    (o instante em que o sistema efetivamente registrou o lançamento,
    protegido por trigger contra alteração desde a Fase 6) — não de
    `data_pagamento`, que é só um texto digitado pelo usuário e não serve
    como régua confiável de prazo."""
    limite_dias = _limite_dias_estorno_baixa(conn)
    if limite_dias <= 0:
        return
    criado_em = baixa["criado_em"]
    try:
        momento_baixa = datetime.datetime.strptime(criado_em[:26], "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        momento_baixa = datetime.datetime.strptime(criado_em[:19], "%Y-%m-%dT%H:%M:%S")
    dias_passados = (datetime.datetime.utcnow() - momento_baixa).days
    if dias_passados > limite_dias:
        raise ApiError(
            f"O prazo para estornar esta baixa expirou: o limite configurado é de {limite_dias} "
            f"dia(s) a partir do lançamento original, e já se passaram {dias_passados}.",
            status=400,
        )


def _hoje_iso_data():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _gerar_numero(prefixo):
    ano = datetime.datetime.utcnow().year
    return f"{prefixo}-{ano}-{secrets.token_hex(4).upper()}"


def _total_baixado(conn, tabela_baixas, campo_fk, conta_id):
    """Soma as baixas normais e SUBTRAI as baixas de estorno (Fase 14) —
    nunca um número guardado à parte, mesmo princípio de "saldo sempre
    recalculado" usado em toda fase anterior. Uma baixa de estorno sempre
    tem o MESMO valor da baixa original que ela neutraliza, então a
    subtração deixa o saldo em aberto exatamente como se a baixa original
    nunca tivesse existido — sem jamais dar UPDATE/DELETE na linha
    original (bloqueado por trigger desde a Fase 6)."""
    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN estorno_de_id IS NULL THEN valor ELSE 0 END), 0)
            - COALESCE(SUM(CASE WHEN estorno_de_id IS NOT NULL THEN valor ELSE 0 END), 0) AS total
        FROM {tabela_baixas} WHERE {campo_fk} = ?
        """,
        (conta_id,),
    ).fetchone()
    return row["total"]


def _decorar_baixas(baixas):
    """Adiciona campos calculados a cada baixa para a UI distinguir: se ela
    própria é um estorno (`is_estorno`) e se ela já foi estornada por outra
    linha (`estornada` — só pode ser True numa baixa normal, nunca num
    estorno, porque a Fase 14 bloqueia estornar um estorno)."""
    ids_estornados = {b["estorno_de_id"] for b in baixas if b.get("estorno_de_id") is not None}
    for b in baixas:
        b["is_estorno"] = b.get("estorno_de_id") is not None
        b["estornada"] = (not b["is_estorno"]) and (b["id"] in ids_estornados)
    return baixas


def _total_baixado_da_lista(baixas):
    total = 0.0
    for b in baixas:
        total += -b["valor"] if b.get("estorno_de_id") is not None else b["valor"]
    return total


def _status_derivado(valor_total, total_baixado):
    if total_baixado <= 0.0000001:
        return "aberto"
    if total_baixado + 0.0000001 >= valor_total:
        return "pago"
    return "pago_parcial"


def _validar_forma_pagamento(forma):
    if forma not in FORMAS_PAGAMENTO:
        raise ApiError(f"forma_pagamento deve ser uma de: {', '.join(FORMAS_PAGAMENTO)}.", status=400)


def _baixas_pendentes_de_registro(conn, tabela_pendentes, campo_fk, conta_id):
    """Fase 31 — lista as solicitações de REGISTRO de baixa (não de
    estorno — ver `_anexar_estornos_pendentes` para o caso de estorno)
    ainda `pendente`s para uma conta, pra UI mostrar "aguardando
    aprovação" ao lado do saldo em aberto, já que essas solicitações
    ainda não são uma linha do ledger (não têm `baixa_id` — a baixa em si
    só passa a existir quando/se for aprovada)."""
    rows = conn.execute(
        f"SELECT * FROM {tabela_pendentes} WHERE {campo_fk} = ? AND status = 'pendente' ORDER BY id", (conta_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _anexar_estornos_pendentes(conn, baixas, tabela_pendentes):
    """Fase 22 — marca em cada baixa (`estorno_pendente`) se existe uma
    solicitação de estorno ainda `pendente` referenciando ela, pra UI
    mostrar "aguardando aprovação" em vez do botão de estornar de novo."""
    if not baixas:
        return baixas
    ids = [b["id"] for b in baixas]
    marcadores = ",".join("?" for _ in ids)
    pendentes = conn.execute(
        f"SELECT * FROM {tabela_pendentes} WHERE status = 'pendente' AND baixa_id IN ({marcadores})", ids
    ).fetchall()
    mapa = {p["baixa_id"]: dict(p) for p in pendentes}
    for b in baixas:
        b["estorno_pendente"] = mapa.get(b["id"])
    return baixas


# ============================================================
# CONTAS A RECEBER
# ============================================================
def _conta_receber_ou_404(conn, conta_id):
    row = conn.execute("SELECT * FROM contas_receber WHERE id = ?", (conta_id,)).fetchone()
    if row is None:
        raise ApiError("Conta a receber não encontrada.", status=404)
    return dict(row)


def _conta_receber_detalhada(conn, conta_id):
    conta = _conta_receber_ou_404(conn, conta_id)
    conta = _decorar_empresa(conta, conn)
    cliente = conn.execute("SELECT razao_social, cnpj FROM clientes WHERE id = ?", (conta["cliente_id"],)).fetchone()
    conta["cliente_razao_social"] = cliente["razao_social"] if cliente else None
    conta["cliente_cnpj"] = cliente["cnpj"] if cliente else None
    pedido = conn.execute("SELECT numero FROM pedidos_venda WHERE id = ?", (conta["pedido_venda_id"],)).fetchone()
    conta["pedido_numero"] = pedido["numero"] if pedido else None

    baixas = conn.execute(
        "SELECT * FROM contas_receber_baixas WHERE conta_receber_id = ? ORDER BY id", (conta_id,)
    ).fetchall()
    conta["baixas"] = _anexar_estornos_pendentes(conn, _decorar_baixas([dict(b) for b in baixas]), "estornos_pendentes_receber")
    total_baixado = _total_baixado_da_lista(conta["baixas"])
    conta["total_baixado"] = total_baixado
    conta["saldo_aberto"] = conta["valor_total"] - total_baixado
    conta["vencida"] = conta["status"] in ("aberto", "pago_parcial") and conta["vencimento"] < _hoje_iso_data()
    # Fase 31 — solicitações de REGISTRO de baixa acima do valor de
    # alçada ainda aguardando aprovação (distintas de `baixas`, que só
    # tem lançamentos JÁ efetivados no ledger).
    conta["baixas_pendentes_registro"] = _baixas_pendentes_de_registro(conn, "baixas_pendentes_receber", "conta_receber_id", conta_id)
    return conta


@bp.get("/contas-receber")
@requires_permission("financeiro", "visualizar")
def listar_contas_receber():
    conn = get_db()
    status = request.args.get("status")
    cliente_id = request.args.get("cliente_id", type=int)
    clausulas, params = [], []
    if status:
        clausulas.append("cr.status = ?")
        params.append(status)
    if cliente_id:
        clausulas.append("cr.cliente_id = ?")
        params.append(cliente_id)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT cr.*, c.razao_social AS cliente_razao_social, pv.numero AS pedido_numero
        FROM contas_receber cr
        JOIN clientes c ON c.id = cr.cliente_id
        LEFT JOIN pedidos_venda pv ON pv.id = cr.pedido_venda_id
        {where} ORDER BY cr.vencimento ASC, cr.id DESC
        """,
        params,
    ).fetchall()
    resultado = []
    hoje = _hoje_iso_data()
    for row in rows:
        conta = dict(row)
        total_baixado = _total_baixado(conn, "contas_receber_baixas", "conta_receber_id", conta["id"])
        conta["total_baixado"] = total_baixado
        conta["saldo_aberto"] = conta["valor_total"] - total_baixado
        conta["vencida"] = conta["status"] in ("aberto", "pago_parcial") and conta["vencimento"] < hoje
        resultado.append(conta)
    return jsonify(resultado)


@bp.get("/contas-receber/<int:conta_id>")
@requires_permission("financeiro", "visualizar")
def obter_conta_receber(conta_id):
    conn = get_db()
    return jsonify(_conta_receber_detalhada(conn, conta_id))


@bp.post("/contas-receber/<int:conta_id>/baixas")
@requires_permission("financeiro", "registrar_baixa_receber")
def registrar_baixa_receber(conta_id):
    """Fase 31 — se `valor` estiver ACIMA de
    `LIMIAR_VALOR_BAIXA_DUPLA_APROVACAO`, a baixa NÃO entra direto no
    ledger: vira uma solicitação pendente (devolve 202, não 201) até um
    segundo usuário aprovar via
    `/contas-receber/baixas-pendentes/{id}/aprovar`. Abaixo do limiar, o
    comportamento é idêntico ao de sempre desde a Fase 6."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    conta = _conta_receber_ou_404(conn, conta_id)
    if conta["status"] == "cancelado":
        raise ApiError("Esta conta a receber está cancelada — não é possível registrar baixa.", status=400)
    if conta["status"] == "pago":
        raise ApiError("Esta conta a receber já está totalmente paga.", status=400)

    valor = dados.get("valor")
    forma_pagamento = dados.get("forma_pagamento")
    data_pagamento = dados.get("data_pagamento") or _hoje_iso_data()
    if valor is None:
        raise ApiError("Informe valor.", status=400)
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ApiError("valor deve ser numérico.", status=400)
    if valor <= 0:
        raise ApiError("valor deve ser maior que zero.", status=400)
    _validar_forma_pagamento(forma_pagamento)

    total_baixado_atual = _total_baixado(conn, "contas_receber_baixas", "conta_receber_id", conta_id)
    saldo_aberto = conta["valor_total"] - total_baixado_atual
    if valor > saldo_aberto + 0.0000001:
        raise ApiError(
            f"O valor da baixa ({valor}) é maior que o saldo em aberto desta conta ({saldo_aberto}) — "
            "não é possível registrar um recebimento maior do que o devido.",
            status=400,
        )

    if valor > LIMIAR_VALOR_BAIXA_DUPLA_APROVACAO:
        cur = conn.execute(
            """
            INSERT INTO baixas_pendentes_receber (conta_receber_id, valor, forma_pagamento, data_pagamento, observacao, solicitado_por)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conta_id, valor, forma_pagamento, data_pagamento, dados.get("observacao"), usuario_atual["id"]),
        )
        audit.registrar(conn, tabela="baixas_pendentes_receber", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                         acao="baixa_receber_registro_solicitado",
                         valor_novo={"conta_receber_id": conta_id, "valor": valor, "forma_pagamento": forma_pagamento},
                         ip=client_ip(), dispositivo=client_device())
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="financeiro", acao="aprovar_baixa_receber",
            tipo="baixa_receber_pendente",
            mensagem=(
                f"Uma baixa de R$ {valor:.2f} na conta a receber {conta['numero']} está acima da "
                "alçada e precisa de segunda aprovação."
            ),
            excluir_usuario_id=usuario_atual["id"],
        )
        resultado = _conta_receber_detalhada(conn, conta_id)
        resultado["baixa_pendente_criada_id"] = cur.lastrowid
        return jsonify(resultado), 202

    cur = conn.execute(
        """
        INSERT INTO contas_receber_baixas (conta_receber_id, valor, forma_pagamento, data_pagamento, observacao, criado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (conta_id, valor, forma_pagamento, data_pagamento, dados.get("observacao"), usuario_atual["id"]),
    )
    novo_status = _status_derivado(conta["valor_total"], total_baixado_atual + valor)
    conn.execute("UPDATE contas_receber SET status = ? WHERE id = ?", (novo_status, conta_id))

    audit.registrar(conn, tabela="contas_receber_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_receber_registrada",
                     valor_novo={"conta_receber_id": conta_id, "valor": valor, "forma_pagamento": forma_pagamento, "novo_status": novo_status},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_receber_detalhada(conn, conta_id)), 201


def _baixa_pendente_receber_ou_erro(conn, pendente_id):
    row = conn.execute("SELECT * FROM baixas_pendentes_receber WHERE id = ?", (pendente_id,)).fetchone()
    if row is None:
        raise ApiError("Solicitação de baixa não encontrada.", status=404)
    row = dict(row)
    if row["status"] != "pendente":
        raise ApiError(f"Esta solicitação de baixa já está '{row['status']}'.", status=400)
    return row


@bp.post("/contas-receber/baixas-pendentes/<int:pendente_id>/aprovar")
@requires_permission("financeiro", "aprovar_baixa_receber")
def aprovar_baixa_receber(pendente_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    pendente = _baixa_pendente_receber_ou_erro(conn, pendente_id)

    # Segregação de função: quem solicitou o registro não pode ser quem
    # aprova — mesmo padrão já usado em `aprovar_estorno_receber` (Fase 22).
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou o registro desta baixa e por isso não pode aprová-la — a aprovação precisa ser "
            "feita por outro usuário (segregação de função)."
        )

    conta_id = pendente["conta_receber_id"]
    conta = _conta_receber_ou_404(conn, conta_id)
    if conta["status"] == "cancelado":
        raise ApiError("Esta conta a receber foi cancelada — não é possível aprovar o registro da baixa.", status=400)

    total_baixado_atual = _total_baixado(conn, "contas_receber_baixas", "conta_receber_id", conta_id)
    saldo_aberto = conta["valor_total"] - total_baixado_atual
    if pendente["valor"] > saldo_aberto + 0.0000001:
        raise ApiError(
            f"O valor solicitado ({pendente['valor']}) é maior que o saldo em aberto atual desta conta "
            f"({saldo_aberto}) — o saldo mudou desde a solicitação (outra baixa pode ter sido registrada nesse "
            "meio-tempo). Rejeite esta solicitação e peça para registrar de novo com o valor correto.",
            status=400,
        )

    cur = conn.execute(
        """
        INSERT INTO contas_receber_baixas (conta_receber_id, valor, forma_pagamento, data_pagamento, observacao, criado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (conta_id, pendente["valor"], pendente["forma_pagamento"], pendente["data_pagamento"],
         pendente["observacao"], usuario_atual["id"]),
    )
    novo_status = _status_derivado(conta["valor_total"], total_baixado_atual + pendente["valor"])
    conn.execute("UPDATE contas_receber SET status = ? WHERE id = ?", (novo_status, conta_id))
    conn.execute(
        """
        UPDATE baixas_pendentes_receber
        SET status = 'aprovado', decidido_por = ?, decidido_em = ?, baixa_gerada_id = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), cur.lastrowid, pendente_id),
    )
    audit.registrar(conn, tabela="contas_receber_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_receber_registrada",
                     valor_novo={"conta_receber_id": conta_id, "valor": pendente["valor"], "forma_pagamento": pendente["forma_pagamento"],
                                 "novo_status": novo_status, "solicitacao_pendente_id": pendente_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_receber_detalhada(conn, conta_id))


@bp.post("/contas-receber/baixas-pendentes/<int:pendente_id>/rejeitar")
@requires_permission("financeiro", "aprovar_baixa_receber")
def rejeitar_baixa_receber(pendente_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo_rejeicao = (dados.get("motivo") or "").strip()
    conn = get_db()
    pendente = _baixa_pendente_receber_ou_erro(conn, pendente_id)

    if not motivo_rejeicao:
        raise ApiError("Informe o motivo da rejeição.", status=400)
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou o registro desta baixa e por isso não pode decidir sobre ela — a decisão precisa "
            "ser tomada por outro usuário (segregação de função)."
        )

    conn.execute(
        """
        UPDATE baixas_pendentes_receber
        SET status = 'rejeitado', decidido_por = ?, decidido_em = ?, motivo_rejeicao = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), motivo_rejeicao, pendente_id),
    )
    audit.registrar(conn, tabela="baixas_pendentes_receber", registro_id=pendente_id, usuario_id=usuario_atual["id"],
                     acao="baixa_receber_registro_rejeitado",
                     valor_novo={"conta_receber_id": pendente["conta_receber_id"], "valor": pendente["valor"]},
                     motivo=motivo_rejeicao, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_receber_detalhada(conn, pendente["conta_receber_id"]))


@bp.post("/contas-receber/<int:conta_id>/baixas/<int:baixa_id>/estornar")
@requires_permission("financeiro", "estornar_baixa_receber")
def estornar_baixa_receber(conta_id, baixa_id):
    """Fase 14 — reverte uma baixa lançada por engano (valor errado, forma
    de pagamento errada, conta errada) SEM apagar nem alterar a linha
    original (bloqueado por trigger desde a Fase 6): insere uma nova baixa,
    com o MESMO valor, marcada via estorno_de_id — igual a uma nota fiscal
    de devolução que referencia a nota de venda original em vez de
    apagá-la. Requer permissão própria (`estornar_baixa_receber`),
    segregada de quem só registra baixa normal.

    Fase 22 — se o valor da baixa estiver ACIMA de
    `LIMIAR_VALOR_ESTORNO_DUPLA_APROVACAO`, o estorno NÃO reverte na
    hora: vira uma solicitação pendente (devolve 202, não 201) até um
    segundo usuário aprovar via
    `/contas-receber/estornos-pendentes/{id}/aprovar`. Abaixo do limiar,
    o comportamento é idêntico ao de sempre desde a Fase 14."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do estorno.", status=400)

    conta = _conta_receber_ou_404(conn, conta_id)
    baixa = conn.execute(
        "SELECT * FROM contas_receber_baixas WHERE id = ? AND conta_receber_id = ?", (baixa_id, conta_id)
    ).fetchone()
    if baixa is None:
        raise ApiError("Baixa não encontrada nesta conta a receber.", status=404)
    baixa = dict(baixa)
    if baixa["estorno_de_id"] is not None:
        raise ApiError("Não é possível estornar um estorno — o lançamento original já reflete a reversão.", status=400)
    ja_estornada = conn.execute(
        "SELECT id FROM contas_receber_baixas WHERE estorno_de_id = ?", (baixa_id,)
    ).fetchone()
    if ja_estornada is not None:
        raise ApiError("Esta baixa já foi estornada anteriormente.", status=400)
    pendente_existente = conn.execute(
        "SELECT id FROM estornos_pendentes_receber WHERE baixa_id = ? AND status = 'pendente'", (baixa_id,)
    ).fetchone()
    if pendente_existente is not None:
        raise ApiError("Já existe uma solicitação de estorno pendente de aprovação para esta baixa.", status=400)
    _checar_prazo_estorno(conn, baixa)

    if baixa["valor"] > LIMIAR_VALOR_ESTORNO_DUPLA_APROVACAO:
        cur = conn.execute(
            """
            INSERT INTO estornos_pendentes_receber (baixa_id, conta_receber_id, valor, motivo_solicitacao, solicitado_por)
            VALUES (?, ?, ?, ?, ?)
            """,
            (baixa_id, conta_id, baixa["valor"], motivo, usuario_atual["id"]),
        )
        audit.registrar(conn, tabela="estornos_pendentes_receber", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                         acao="estorno_receber_solicitado",
                         valor_novo={"conta_receber_id": conta_id, "baixa_id": baixa_id, "valor": baixa["valor"]},
                         motivo=motivo, ip=client_ip(), dispositivo=client_device())
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="financeiro", acao="aprovar_estorno_receber",
            tipo="estorno_receber_pendente",
            mensagem=(
                f"Um estorno de R$ {baixa['valor']:.2f} na conta a receber {conta['numero']} está acima da "
                "alçada e precisa de segunda aprovação."
            ),
            excluir_usuario_id=usuario_atual["id"],
        )
        resultado = _conta_receber_detalhada(conn, conta_id)
        resultado["estorno_pendente_criado_id"] = cur.lastrowid
        return jsonify(resultado), 202

    cur = conn.execute(
        """
        INSERT INTO contas_receber_baixas
            (conta_receber_id, valor, forma_pagamento, data_pagamento, observacao, criado_por, estorno_de_id, motivo_estorno)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (conta_id, baixa["valor"], baixa["forma_pagamento"], _hoje_iso_data(),
         f"Estorno da baixa #{baixa_id}", usuario_atual["id"], baixa_id, motivo),
    )
    novo_total_baixado = _total_baixado(conn, "contas_receber_baixas", "conta_receber_id", conta_id)
    novo_status = _status_derivado(conta["valor_total"], novo_total_baixado)
    conn.execute("UPDATE contas_receber SET status = ? WHERE id = ?", (novo_status, conta_id))

    audit.registrar(conn, tabela="contas_receber_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_receber_estornada",
                     valor_novo={"conta_receber_id": conta_id, "baixa_original_id": baixa_id, "valor": baixa["valor"],
                                 "motivo_estorno": motivo, "novo_status": novo_status},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_receber_detalhada(conn, conta_id)), 201


def _estorno_pendente_receber_ou_erro(conn, pendente_id):
    row = conn.execute("SELECT * FROM estornos_pendentes_receber WHERE id = ?", (pendente_id,)).fetchone()
    if row is None:
        raise ApiError("Solicitação de estorno não encontrada.", status=404)
    row = dict(row)
    if row["status"] != "pendente":
        raise ApiError(f"Esta solicitação de estorno já está '{row['status']}'.", status=400)
    return row


@bp.post("/contas-receber/estornos-pendentes/<int:pendente_id>/aprovar")
@requires_permission("financeiro", "aprovar_estorno_receber")
def aprovar_estorno_receber(pendente_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    pendente = _estorno_pendente_receber_ou_erro(conn, pendente_id)

    # Segregação de função: quem solicitou o estorno não pode ser quem
    # aprova — mesmo padrão já usado em `estoque.aprovar_ajuste_contagem`
    # (Fase 21) e em `lotes.aprovar` (Fase 2).
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou este estorno e por isso não pode aprová-lo — a aprovação precisa ser feita "
            "por outro usuário (segregação de função)."
        )

    baixa_id = pendente["baixa_id"]
    conta_id = pendente["conta_receber_id"]
    conta = _conta_receber_ou_404(conn, conta_id)
    baixa = conn.execute("SELECT * FROM contas_receber_baixas WHERE id = ?", (baixa_id,)).fetchone()
    if baixa is None:
        raise ApiError("A baixa original não foi encontrada — não é possível concluir o estorno.", status=404)
    baixa = dict(baixa)

    cur = conn.execute(
        """
        INSERT INTO contas_receber_baixas
            (conta_receber_id, valor, forma_pagamento, data_pagamento, observacao, criado_por, estorno_de_id, motivo_estorno)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (conta_id, baixa["valor"], baixa["forma_pagamento"], _hoje_iso_data(),
         f"Estorno da baixa #{baixa_id} (aprovado por segundo usuário)", usuario_atual["id"], baixa_id, pendente["motivo_solicitacao"]),
    )
    novo_total_baixado = _total_baixado(conn, "contas_receber_baixas", "conta_receber_id", conta_id)
    novo_status = _status_derivado(conta["valor_total"], novo_total_baixado)
    conn.execute("UPDATE contas_receber SET status = ? WHERE id = ?", (novo_status, conta_id))
    conn.execute(
        """
        UPDATE estornos_pendentes_receber
        SET status = 'aprovado', decidido_por = ?, decidido_em = ?, baixa_estorno_gerada_id = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), cur.lastrowid, pendente_id),
    )
    audit.registrar(conn, tabela="contas_receber_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_receber_estornada",
                     valor_novo={"conta_receber_id": conta_id, "baixa_original_id": baixa_id, "valor": baixa["valor"],
                                 "motivo_estorno": pendente["motivo_solicitacao"], "novo_status": novo_status,
                                 "solicitacao_pendente_id": pendente_id},
                     motivo=pendente["motivo_solicitacao"], ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_receber_detalhada(conn, conta_id))


@bp.post("/contas-receber/estornos-pendentes/<int:pendente_id>/rejeitar")
@requires_permission("financeiro", "aprovar_estorno_receber")
def rejeitar_estorno_receber(pendente_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo_rejeicao = (dados.get("motivo") or "").strip()
    conn = get_db()
    pendente = _estorno_pendente_receber_ou_erro(conn, pendente_id)

    if not motivo_rejeicao:
        raise ApiError("Informe o motivo da rejeição.", status=400)
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou este estorno e por isso não pode decidir sobre ele — a decisão precisa ser "
            "tomada por outro usuário (segregação de função)."
        )

    conn.execute(
        """
        UPDATE estornos_pendentes_receber
        SET status = 'rejeitado', decidido_por = ?, decidido_em = ?, motivo_rejeicao = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), motivo_rejeicao, pendente_id),
    )
    audit.registrar(conn, tabela="estornos_pendentes_receber", registro_id=pendente_id, usuario_id=usuario_atual["id"],
                     acao="estorno_receber_rejeitado",
                     valor_novo={"conta_receber_id": pendente["conta_receber_id"], "baixa_id": pendente["baixa_id"]},
                     motivo=motivo_rejeicao, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_receber_detalhada(conn, pendente["conta_receber_id"]))


@bp.post("/contas-receber/<int:conta_id>/cancelar")
@requires_permission("financeiro", "cancelar_conta_receber")
def cancelar_conta_receber(conta_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    conta = _conta_receber_ou_404(conn, conta_id)
    if conta["status"] != "aberto":
        raise ApiError(
            f"Só é possível cancelar uma conta a receber sem nenhuma baixa registrada (status atual: "
            f"'{conta['status']}'). Se já houve recebimento parcial ou total, trate como um caso de estorno "
            "separado, fora deste fluxo.",
            status=400,
        )

    conn.execute(
        "UPDATE contas_receber SET status = 'cancelado', motivo_cancelamento = ?, cancelado_em = ?, cancelado_por = ? WHERE id = ?",
        (motivo, _now_iso(), usuario_atual["id"], conta_id),
    )
    audit.registrar(conn, tabela="contas_receber", registro_id=conta_id, usuario_id=usuario_atual["id"],
                     acao="conta_receber_cancelada", valor_anterior={"status": conta["status"]}, valor_novo={"status": "cancelado"},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_receber_detalhada(conn, conta_id))


# ============================================================
# CONTAS A PAGAR
# ============================================================
def _conta_pagar_ou_404(conn, conta_id):
    row = conn.execute("SELECT * FROM contas_pagar WHERE id = ?", (conta_id,)).fetchone()
    if row is None:
        raise ApiError("Conta a pagar não encontrada.", status=404)
    return dict(row)


def _empresa_ou_404(conn, empresa_id):
    """Fase 52 — mesma validação de app/routes/producao.py/lotes.py/
    comercial.py, duplicada de propósito para não criar acoplamento entre
    módulos de rota só por um SELECT de 3 linhas."""
    empresa = conn.execute("SELECT id FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if empresa is None:
        raise ApiError("Empresa não encontrada.", status=404)


def _decorar_empresa(conta, conn):
    """Fase 52 — empresa_id é opcional (ver schema_fase52.sql); a maioria
    das contas continua sem nenhuma. Reaproveitada tanto por contas a
    pagar quanto a receber."""
    if conta["empresa_id"]:
        empresa = conn.execute(
            "SELECT nome_fantasia, razao_social FROM empresas WHERE id = ?", (conta["empresa_id"],)
        ).fetchone()
        conta["empresa_nome"] = (empresa["nome_fantasia"] or empresa["razao_social"]) if empresa else None
    else:
        conta["empresa_nome"] = None
    return conta


def _conta_pagar_detalhada(conn, conta_id):
    conta = _conta_pagar_ou_404(conn, conta_id)
    conta = _decorar_empresa(conta, conn)
    fornecedor = conn.execute("SELECT nome, cnpj FROM fornecedores WHERE id = ?", (conta["fornecedor_id"],)).fetchone()
    conta["fornecedor_nome"] = fornecedor["nome"] if fornecedor else None
    conta["fornecedor_cnpj"] = fornecedor["cnpj"] if fornecedor else None
    if conta["lote_id"]:
        lote = conn.execute("SELECT codigo_lote FROM lotes WHERE id = ?", (conta["lote_id"],)).fetchone()
        conta["lote_codigo"] = lote["codigo_lote"] if lote else None
    else:
        conta["lote_codigo"] = None
    # Fase 59 — mesma ideia do lote_codigo acima, para quem lançou (ou foi
    # gerada automaticamente a partir de) um Pedido de Compra (Fase 58).
    if conta["pedido_compra_id"]:
        pedido = conn.execute("SELECT numero FROM pedidos_compra WHERE id = ?", (conta["pedido_compra_id"],)).fetchone()
        conta["pedido_compra_numero"] = pedido["numero"] if pedido else None
    else:
        conta["pedido_compra_numero"] = None

    baixas = conn.execute(
        "SELECT * FROM contas_pagar_baixas WHERE conta_pagar_id = ? ORDER BY id", (conta_id,)
    ).fetchall()
    conta["baixas"] = _anexar_estornos_pendentes(conn, _decorar_baixas([dict(b) for b in baixas]), "estornos_pendentes_pagar")
    total_baixado = _total_baixado_da_lista(conta["baixas"])
    conta["total_baixado"] = total_baixado
    conta["saldo_aberto"] = conta["valor_total"] - total_baixado
    conta["vencida"] = conta["status"] in ("aberto", "pago_parcial") and conta["vencimento"] < _hoje_iso_data()
    # Fase 31 — espelho do que foi feito em _conta_receber_detalhada.
    conta["baixas_pendentes_registro"] = _baixas_pendentes_de_registro(conn, "baixas_pendentes_pagar", "conta_pagar_id", conta_id)
    return conta


@bp.get("/contas-pagar")
@requires_permission("financeiro", "visualizar")
def listar_contas_pagar():
    conn = get_db()
    status = request.args.get("status")
    fornecedor_id = request.args.get("fornecedor_id", type=int)
    categoria = request.args.get("categoria")  # Fase 41 — 'compra' ou 'despesa_operacional'
    clausulas, params = [], []
    if status:
        clausulas.append("cp.status = ?")
        params.append(status)
    if fornecedor_id:
        clausulas.append("cp.fornecedor_id = ?")
        params.append(fornecedor_id)
    if categoria:
        clausulas.append("cp.categoria = ?")
        params.append(categoria)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT cp.*, f.nome AS fornecedor_nome
        FROM contas_pagar cp
        JOIN fornecedores f ON f.id = cp.fornecedor_id
        {where} ORDER BY cp.vencimento ASC, cp.id DESC
        """,
        params,
    ).fetchall()
    resultado = []
    hoje = _hoje_iso_data()
    for row in rows:
        conta = dict(row)
        total_baixado = _total_baixado(conn, "contas_pagar_baixas", "conta_pagar_id", conta["id"])
        conta["total_baixado"] = total_baixado
        conta["saldo_aberto"] = conta["valor_total"] - total_baixado
        conta["vencida"] = conta["status"] in ("aberto", "pago_parcial") and conta["vencimento"] < hoje
        resultado.append(conta)
    return jsonify(resultado)


@bp.get("/contas-pagar/<int:conta_id>")
@requires_permission("financeiro", "visualizar")
def obter_conta_pagar(conta_id):
    conn = get_db()
    return jsonify(_conta_pagar_detalhada(conn, conta_id))


def criar_conta_receber_interno(conn, usuario_atual, cliente_id, valor_total, vencimento,
                                 descricao=None, empresa_id=None):
    """Fase 125 — espelho de `criar_conta_pagar_interno` logo abaixo, para o
    lançamento avulso de conta a receber (sem Pedido de Venda por trás —
    ver nota de escopo em migrations/schema_fase125.sql). Deliberadamente
    SEM `lote_id`/`pedido_venda_id`: quem precisa de rastreabilidade de
    venda de verdade continua usando o fluxo normal (confirmar pedido),
    esta função é só para o saldo que não tem — e nunca vai ter — essa
    origem."""
    if not cliente_id:
        raise ApiError("Informe cliente_id.", status=400)
    cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if cliente is None:
        raise ApiError("Cliente não encontrado.", status=404)
    if valor_total is None:
        raise ApiError("Informe valor_total.", status=400)
    try:
        valor_total = float(valor_total)
    except (TypeError, ValueError):
        raise ApiError("valor_total deve ser numérico.", status=400)
    if valor_total <= 0:
        raise ApiError("valor_total deve ser maior que zero.", status=400)
    vencimento = (vencimento or "").strip()
    if not vencimento:
        raise ApiError("Informe vencimento (AAAA-MM-DD).", status=400)
    if empresa_id:
        _empresa_ou_404(conn, empresa_id)

    numero = _gerar_numero("CR")
    cur = conn.execute(
        """
        INSERT INTO contas_receber (numero, cliente_id, valor_total, vencimento, descricao, empresa_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (numero, cliente_id, valor_total, vencimento, (descricao or "").strip() or None, empresa_id, usuario_atual["id"]),
    )
    conta_id = cur.lastrowid
    conn.commit()
    audit.registrar(conn, tabela="contas_receber", registro_id=conta_id, usuario_id=usuario_atual["id"],
                     acao="conta_receber_criada_avulsa",
                     valor_novo={"numero": numero, "cliente_id": cliente_id, "valor_total": valor_total, "vencimento": vencimento, "empresa_id": empresa_id},
                     ip=client_ip(), dispositivo=client_device())
    return conta_id


@bp.post("/contas-receber")
@requires_permission("financeiro", "criar_conta_receber")
def criar_conta_receber_avulsa():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    conta_id = criar_conta_receber_interno(
        conn, usuario_atual,
        cliente_id=dados.get("cliente_id"),
        valor_total=dados.get("valor_total"),
        vencimento=dados.get("vencimento"),
        descricao=dados.get("descricao"),
        empresa_id=dados.get("empresa_id"),
    )
    return jsonify(_conta_receber_detalhada(conn, conta_id)), 201


def criar_conta_pagar_interno(conn, usuario_atual, fornecedor_id, descricao, valor_total, vencimento,
                               lote_id=None, categoria="compra", empresa_id=None, pedido_compra_id=None):
    """Núcleo da criação de uma conta a pagar — reaproveitado pela criação
    manual direta (`POST /financeiro/contas-pagar`) e, desde a Fase 59,
    por `POST /compras/pedidos/<id>/gerar-conta-pagar` (ver
    app/routes/compras.py e a nota de escopo em migrations/schema_fase59.sql:
    conta a pagar continua sendo lançada por uma ação explícita, nunca
    automaticamente no recebimento — esta função só evita duplicar a
    validação/INSERT/auditoria entre os dois pontos de entrada). Devolve
    o id da conta criada; quem chama decide o resto (resposta HTTP e,
    no caso do pedido de compra, o vínculo pedidos_compra.conta_pagar_id)."""
    if not fornecedor_id:
        raise ApiError("Informe fornecedor_id.", status=400)
    fornecedor = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
    if fornecedor is None:
        raise ApiError("Fornecedor não encontrado.", status=404)
    descricao = (descricao or "").strip()
    if not descricao:
        raise ApiError("Informe descricao (ex.: número da nota fiscal).", status=400)
    if valor_total is None:
        raise ApiError("Informe valor_total.", status=400)
    try:
        valor_total = float(valor_total)
    except (TypeError, ValueError):
        raise ApiError("valor_total deve ser numérico.", status=400)
    if valor_total <= 0:
        raise ApiError("valor_total deve ser maior que zero.", status=400)
    vencimento = (vencimento or "").strip()
    if not vencimento:
        raise ApiError("Informe vencimento (AAAA-MM-DD).", status=400)
    categoria = (categoria or "compra").strip()
    if categoria not in ("compra", "despesa_operacional"):
        raise ApiError("categoria deve ser 'compra' ou 'despesa_operacional'.", status=400)

    if lote_id:
        lote = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
        if lote is None:
            raise ApiError("Lote não encontrado.", status=404)
        if lote["fornecedor_id"] != fornecedor_id:
            raise ApiError("Este lote não foi recebido deste fornecedor — confira o vínculo antes de lançar a conta.", status=400)
    if empresa_id:
        _empresa_ou_404(conn, empresa_id)
    if pedido_compra_id:
        pedido = conn.execute("SELECT id, fornecedor_id FROM pedidos_compra WHERE id = ?", (pedido_compra_id,)).fetchone()
        if pedido is None:
            raise ApiError("Pedido de compra não encontrado.", status=404)
        if pedido["fornecedor_id"] != fornecedor_id:
            raise ApiError("Este pedido de compra não é deste fornecedor — confira o vínculo antes de lançar a conta.", status=400)

    numero = _gerar_numero("CP")
    cur = conn.execute(
        """
        INSERT INTO contas_pagar (numero, fornecedor_id, lote_id, descricao, valor_total, vencimento, categoria, empresa_id, pedido_compra_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (numero, fornecedor_id, lote_id, descricao, valor_total, vencimento, categoria, empresa_id, pedido_compra_id, usuario_atual["id"]),
    )
    conta_id = cur.lastrowid
    conn.commit()
    audit.registrar(conn, tabela="contas_pagar", registro_id=conta_id, usuario_id=usuario_atual["id"],
                     acao="conta_pagar_criada",
                     valor_novo={"numero": numero, "fornecedor_id": fornecedor_id, "valor_total": valor_total, "vencimento": vencimento, "categoria": categoria, "empresa_id": empresa_id, "pedido_compra_id": pedido_compra_id},
                     ip=client_ip(), dispositivo=client_device())
    return conta_id


@bp.post("/contas-pagar")
@requires_permission("financeiro", "criar_conta_pagar")
def criar_conta_pagar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    conta_id = criar_conta_pagar_interno(
        conn, usuario_atual,
        fornecedor_id=dados.get("fornecedor_id"),
        descricao=dados.get("descricao"),
        valor_total=dados.get("valor_total"),
        vencimento=dados.get("vencimento"),
        lote_id=dados.get("lote_id"),
        # Fase 41 — distingue compra de insumo (o padrão, já embutida no
        # CMV via Custeio) de despesa operacional (aluguel, salário
        # administrativo, marketing etc. — nunca deve entrar no CMV do
        # DRE, só nas despesas operacionais). Omitir o campo preserva o
        # comportamento de sempre.
        categoria=dados.get("categoria") or "compra",
        # Fase 52 — opcional (ver schema_fase52.sql); sem valor,
        # comportamento idêntico ao de antes desta fase.
        empresa_id=dados.get("empresa_id"),
    )
    return jsonify(_conta_pagar_detalhada(conn, conta_id)), 201


@bp.post("/contas-pagar/<int:conta_id>/baixas")
@requires_permission("financeiro", "registrar_baixa_pagar")
def registrar_baixa_pagar(conta_id):
    """Espelho de registrar_baixa_receber (ver comentário lá, inclusive
    sobre a Fase 31) para contas a pagar."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    conta = _conta_pagar_ou_404(conn, conta_id)
    if conta["status"] == "cancelado":
        raise ApiError("Esta conta a pagar está cancelada — não é possível registrar baixa.", status=400)
    if conta["status"] == "pago":
        raise ApiError("Esta conta a pagar já está totalmente paga.", status=400)

    valor = dados.get("valor")
    forma_pagamento = dados.get("forma_pagamento")
    data_pagamento = dados.get("data_pagamento") or _hoje_iso_data()
    if valor is None:
        raise ApiError("Informe valor.", status=400)
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ApiError("valor deve ser numérico.", status=400)
    if valor <= 0:
        raise ApiError("valor deve ser maior que zero.", status=400)
    _validar_forma_pagamento(forma_pagamento)

    total_baixado_atual = _total_baixado(conn, "contas_pagar_baixas", "conta_pagar_id", conta_id)
    saldo_aberto = conta["valor_total"] - total_baixado_atual
    if valor > saldo_aberto + 0.0000001:
        raise ApiError(
            f"O valor da baixa ({valor}) é maior que o saldo em aberto desta conta ({saldo_aberto}) — "
            "não é possível registrar um pagamento maior do que o devido.",
            status=400,
        )

    if valor > LIMIAR_VALOR_BAIXA_DUPLA_APROVACAO:
        cur = conn.execute(
            """
            INSERT INTO baixas_pendentes_pagar (conta_pagar_id, valor, forma_pagamento, data_pagamento, observacao, solicitado_por)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conta_id, valor, forma_pagamento, data_pagamento, dados.get("observacao"), usuario_atual["id"]),
        )
        audit.registrar(conn, tabela="baixas_pendentes_pagar", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                         acao="baixa_pagar_registro_solicitado",
                         valor_novo={"conta_pagar_id": conta_id, "valor": valor, "forma_pagamento": forma_pagamento},
                         ip=client_ip(), dispositivo=client_device())
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="financeiro", acao="aprovar_baixa_pagar",
            tipo="baixa_pagar_pendente",
            mensagem=(
                f"Uma baixa de R$ {valor:.2f} na conta a pagar {conta['numero']} está acima da "
                "alçada e precisa de segunda aprovação."
            ),
            excluir_usuario_id=usuario_atual["id"],
        )
        resultado = _conta_pagar_detalhada(conn, conta_id)
        resultado["baixa_pendente_criada_id"] = cur.lastrowid
        return jsonify(resultado), 202

    cur = conn.execute(
        """
        INSERT INTO contas_pagar_baixas (conta_pagar_id, valor, forma_pagamento, data_pagamento, observacao, criado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (conta_id, valor, forma_pagamento, data_pagamento, dados.get("observacao"), usuario_atual["id"]),
    )
    novo_status = _status_derivado(conta["valor_total"], total_baixado_atual + valor)
    conn.execute("UPDATE contas_pagar SET status = ? WHERE id = ?", (novo_status, conta_id))

    audit.registrar(conn, tabela="contas_pagar_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_pagar_registrada",
                     valor_novo={"conta_pagar_id": conta_id, "valor": valor, "forma_pagamento": forma_pagamento, "novo_status": novo_status},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_pagar_detalhada(conn, conta_id)), 201


def _baixa_pendente_pagar_ou_erro(conn, pendente_id):
    row = conn.execute("SELECT * FROM baixas_pendentes_pagar WHERE id = ?", (pendente_id,)).fetchone()
    if row is None:
        raise ApiError("Solicitação de baixa não encontrada.", status=404)
    row = dict(row)
    if row["status"] != "pendente":
        raise ApiError(f"Esta solicitação de baixa já está '{row['status']}'.", status=400)
    return row


@bp.post("/contas-pagar/baixas-pendentes/<int:pendente_id>/aprovar")
@requires_permission("financeiro", "aprovar_baixa_pagar")
def aprovar_baixa_pagar(pendente_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    pendente = _baixa_pendente_pagar_ou_erro(conn, pendente_id)

    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou o registro desta baixa e por isso não pode aprová-la — a aprovação precisa ser "
            "feita por outro usuário (segregação de função)."
        )

    conta_id = pendente["conta_pagar_id"]
    conta = _conta_pagar_ou_404(conn, conta_id)
    if conta["status"] == "cancelado":
        raise ApiError("Esta conta a pagar foi cancelada — não é possível aprovar o registro da baixa.", status=400)

    total_baixado_atual = _total_baixado(conn, "contas_pagar_baixas", "conta_pagar_id", conta_id)
    saldo_aberto = conta["valor_total"] - total_baixado_atual
    if pendente["valor"] > saldo_aberto + 0.0000001:
        raise ApiError(
            f"O valor solicitado ({pendente['valor']}) é maior que o saldo em aberto atual desta conta "
            f"({saldo_aberto}) — o saldo mudou desde a solicitação (outra baixa pode ter sido registrada nesse "
            "meio-tempo). Rejeite esta solicitação e peça para registrar de novo com o valor correto.",
            status=400,
        )

    cur = conn.execute(
        """
        INSERT INTO contas_pagar_baixas (conta_pagar_id, valor, forma_pagamento, data_pagamento, observacao, criado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (conta_id, pendente["valor"], pendente["forma_pagamento"], pendente["data_pagamento"],
         pendente["observacao"], usuario_atual["id"]),
    )
    novo_status = _status_derivado(conta["valor_total"], total_baixado_atual + pendente["valor"])
    conn.execute("UPDATE contas_pagar SET status = ? WHERE id = ?", (novo_status, conta_id))
    conn.execute(
        """
        UPDATE baixas_pendentes_pagar
        SET status = 'aprovado', decidido_por = ?, decidido_em = ?, baixa_gerada_id = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), cur.lastrowid, pendente_id),
    )
    audit.registrar(conn, tabela="contas_pagar_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_pagar_registrada",
                     valor_novo={"conta_pagar_id": conta_id, "valor": pendente["valor"], "forma_pagamento": pendente["forma_pagamento"],
                                 "novo_status": novo_status, "solicitacao_pendente_id": pendente_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_pagar_detalhada(conn, conta_id))


@bp.post("/contas-pagar/baixas-pendentes/<int:pendente_id>/rejeitar")
@requires_permission("financeiro", "aprovar_baixa_pagar")
def rejeitar_baixa_pagar(pendente_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo_rejeicao = (dados.get("motivo") or "").strip()
    conn = get_db()
    pendente = _baixa_pendente_pagar_ou_erro(conn, pendente_id)

    if not motivo_rejeicao:
        raise ApiError("Informe o motivo da rejeição.", status=400)
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou o registro desta baixa e por isso não pode decidir sobre ela — a decisão precisa "
            "ser tomada por outro usuário (segregação de função)."
        )

    conn.execute(
        """
        UPDATE baixas_pendentes_pagar
        SET status = 'rejeitado', decidido_por = ?, decidido_em = ?, motivo_rejeicao = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), motivo_rejeicao, pendente_id),
    )
    audit.registrar(conn, tabela="baixas_pendentes_pagar", registro_id=pendente_id, usuario_id=usuario_atual["id"],
                     acao="baixa_pagar_registro_rejeitado",
                     valor_novo={"conta_pagar_id": pendente["conta_pagar_id"], "valor": pendente["valor"]},
                     motivo=motivo_rejeicao, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_pagar_detalhada(conn, pendente["conta_pagar_id"]))


@bp.post("/contas-pagar/<int:conta_id>/baixas/<int:baixa_id>/estornar")
@requires_permission("financeiro", "estornar_baixa_pagar")
def estornar_baixa_pagar(conta_id, baixa_id):
    """Espelho de estornar_baixa_receber (ver comentário lá, inclusive
    sobre a Fase 22) para contas a pagar. Permissão própria
    (`estornar_baixa_pagar`), segregada de quem só registra pagamento
    normal."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do estorno.", status=400)

    conta = _conta_pagar_ou_404(conn, conta_id)
    baixa = conn.execute(
        "SELECT * FROM contas_pagar_baixas WHERE id = ? AND conta_pagar_id = ?", (baixa_id, conta_id)
    ).fetchone()
    if baixa is None:
        raise ApiError("Baixa não encontrada nesta conta a pagar.", status=404)
    baixa = dict(baixa)
    if baixa["estorno_de_id"] is not None:
        raise ApiError("Não é possível estornar um estorno — o lançamento original já reflete a reversão.", status=400)
    ja_estornada = conn.execute(
        "SELECT id FROM contas_pagar_baixas WHERE estorno_de_id = ?", (baixa_id,)
    ).fetchone()
    if ja_estornada is not None:
        raise ApiError("Esta baixa já foi estornada anteriormente.", status=400)
    pendente_existente = conn.execute(
        "SELECT id FROM estornos_pendentes_pagar WHERE baixa_id = ? AND status = 'pendente'", (baixa_id,)
    ).fetchone()
    if pendente_existente is not None:
        raise ApiError("Já existe uma solicitação de estorno pendente de aprovação para esta baixa.", status=400)
    _checar_prazo_estorno(conn, baixa)

    if baixa["valor"] > LIMIAR_VALOR_ESTORNO_DUPLA_APROVACAO:
        cur = conn.execute(
            """
            INSERT INTO estornos_pendentes_pagar (baixa_id, conta_pagar_id, valor, motivo_solicitacao, solicitado_por)
            VALUES (?, ?, ?, ?, ?)
            """,
            (baixa_id, conta_id, baixa["valor"], motivo, usuario_atual["id"]),
        )
        audit.registrar(conn, tabela="estornos_pendentes_pagar", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                         acao="estorno_pagar_solicitado",
                         valor_novo={"conta_pagar_id": conta_id, "baixa_id": baixa_id, "valor": baixa["valor"]},
                         motivo=motivo, ip=client_ip(), dispositivo=client_device())
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="financeiro", acao="aprovar_estorno_pagar",
            tipo="estorno_pagar_pendente",
            mensagem=(
                f"Um estorno de R$ {baixa['valor']:.2f} na conta a pagar {conta['numero']} está acima da "
                "alçada e precisa de segunda aprovação."
            ),
            excluir_usuario_id=usuario_atual["id"],
        )
        resultado = _conta_pagar_detalhada(conn, conta_id)
        resultado["estorno_pendente_criado_id"] = cur.lastrowid
        return jsonify(resultado), 202

    cur = conn.execute(
        """
        INSERT INTO contas_pagar_baixas
            (conta_pagar_id, valor, forma_pagamento, data_pagamento, observacao, criado_por, estorno_de_id, motivo_estorno)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (conta_id, baixa["valor"], baixa["forma_pagamento"], _hoje_iso_data(),
         f"Estorno da baixa #{baixa_id}", usuario_atual["id"], baixa_id, motivo),
    )
    novo_total_baixado = _total_baixado(conn, "contas_pagar_baixas", "conta_pagar_id", conta_id)
    novo_status = _status_derivado(conta["valor_total"], novo_total_baixado)
    conn.execute("UPDATE contas_pagar SET status = ? WHERE id = ?", (novo_status, conta_id))

    audit.registrar(conn, tabela="contas_pagar_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_pagar_estornada",
                     valor_novo={"conta_pagar_id": conta_id, "baixa_original_id": baixa_id, "valor": baixa["valor"],
                                 "motivo_estorno": motivo, "novo_status": novo_status},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_pagar_detalhada(conn, conta_id)), 201


def _estorno_pendente_pagar_ou_erro(conn, pendente_id):
    row = conn.execute("SELECT * FROM estornos_pendentes_pagar WHERE id = ?", (pendente_id,)).fetchone()
    if row is None:
        raise ApiError("Solicitação de estorno não encontrada.", status=404)
    row = dict(row)
    if row["status"] != "pendente":
        raise ApiError(f"Esta solicitação de estorno já está '{row['status']}'.", status=400)
    return row


@bp.post("/contas-pagar/estornos-pendentes/<int:pendente_id>/aprovar")
@requires_permission("financeiro", "aprovar_estorno_pagar")
def aprovar_estorno_pagar(pendente_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    pendente = _estorno_pendente_pagar_ou_erro(conn, pendente_id)

    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou este estorno e por isso não pode aprová-lo — a aprovação precisa ser feita "
            "por outro usuário (segregação de função)."
        )

    baixa_id = pendente["baixa_id"]
    conta_id = pendente["conta_pagar_id"]
    conta = _conta_pagar_ou_404(conn, conta_id)
    baixa = conn.execute("SELECT * FROM contas_pagar_baixas WHERE id = ?", (baixa_id,)).fetchone()
    if baixa is None:
        raise ApiError("A baixa original não foi encontrada — não é possível concluir o estorno.", status=404)
    baixa = dict(baixa)

    cur = conn.execute(
        """
        INSERT INTO contas_pagar_baixas
            (conta_pagar_id, valor, forma_pagamento, data_pagamento, observacao, criado_por, estorno_de_id, motivo_estorno)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (conta_id, baixa["valor"], baixa["forma_pagamento"], _hoje_iso_data(),
         f"Estorno da baixa #{baixa_id} (aprovado por segundo usuário)", usuario_atual["id"], baixa_id, pendente["motivo_solicitacao"]),
    )
    novo_total_baixado = _total_baixado(conn, "contas_pagar_baixas", "conta_pagar_id", conta_id)
    novo_status = _status_derivado(conta["valor_total"], novo_total_baixado)
    conn.execute("UPDATE contas_pagar SET status = ? WHERE id = ?", (novo_status, conta_id))
    conn.execute(
        """
        UPDATE estornos_pendentes_pagar
        SET status = 'aprovado', decidido_por = ?, decidido_em = ?, baixa_estorno_gerada_id = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), cur.lastrowid, pendente_id),
    )
    audit.registrar(conn, tabela="contas_pagar_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="baixa_pagar_estornada",
                     valor_novo={"conta_pagar_id": conta_id, "baixa_original_id": baixa_id, "valor": baixa["valor"],
                                 "motivo_estorno": pendente["motivo_solicitacao"], "novo_status": novo_status,
                                 "solicitacao_pendente_id": pendente_id},
                     motivo=pendente["motivo_solicitacao"], ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_pagar_detalhada(conn, conta_id))


@bp.post("/contas-pagar/estornos-pendentes/<int:pendente_id>/rejeitar")
@requires_permission("financeiro", "aprovar_estorno_pagar")
def rejeitar_estorno_pagar(pendente_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo_rejeicao = (dados.get("motivo") or "").strip()
    conn = get_db()
    pendente = _estorno_pendente_pagar_ou_erro(conn, pendente_id)

    if not motivo_rejeicao:
        raise ApiError("Informe o motivo da rejeição.", status=400)
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou este estorno e por isso não pode decidir sobre ele — a decisão precisa ser "
            "tomada por outro usuário (segregação de função)."
        )

    conn.execute(
        """
        UPDATE estornos_pendentes_pagar
        SET status = 'rejeitado', decidido_por = ?, decidido_em = ?, motivo_rejeicao = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), motivo_rejeicao, pendente_id),
    )
    audit.registrar(conn, tabela="estornos_pendentes_pagar", registro_id=pendente_id, usuario_id=usuario_atual["id"],
                     acao="estorno_pagar_rejeitado",
                     valor_novo={"conta_pagar_id": pendente["conta_pagar_id"], "baixa_id": pendente["baixa_id"]},
                     motivo=motivo_rejeicao, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_pagar_detalhada(conn, pendente["conta_pagar_id"]))


@bp.post("/contas-pagar/<int:conta_id>/cancelar")
@requires_permission("financeiro", "cancelar_conta_pagar")
def cancelar_conta_pagar(conta_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    conta = _conta_pagar_ou_404(conn, conta_id)
    if conta["status"] != "aberto":
        raise ApiError(
            f"Só é possível cancelar uma conta a pagar sem nenhuma baixa registrada (status atual: "
            f"'{conta['status']}'). Se já houve pagamento parcial ou total, trate como um caso de estorno "
            "separado, fora deste fluxo.",
            status=400,
        )

    conn.execute(
        "UPDATE contas_pagar SET status = 'cancelado', motivo_cancelamento = ?, cancelado_em = ?, cancelado_por = ? WHERE id = ?",
        (motivo, _now_iso(), usuario_atual["id"], conta_id),
    )
    audit.registrar(conn, tabela="contas_pagar", registro_id=conta_id, usuario_id=usuario_atual["id"],
                     acao="conta_pagar_cancelada", valor_anterior={"status": conta["status"]}, valor_novo={"status": "cancelado"},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify(_conta_pagar_detalhada(conn, conta_id))


# ============================================================
# FASE 22 — Lista consolidada de estornos pendentes de aprovação
# ============================================================
@bp.get("/estornos-pendentes")
@requires_permission("financeiro", "visualizar")
def listar_estornos_pendentes():
    """Junta as pendências de receber e de pagar num só retorno (`tipo`
    diferencia), pra quem tem `aprovar_estorno_receber`/`_pagar` não
    precisar vasculhar conta por conta procurando o que falta decidir —
    mesma ideia de `GET /estoque/ajustes-pendentes-aprovacao` (Fase 21)."""
    conn = get_db()
    receber = conn.execute(
        """
        SELECT ep.*, cr.numero AS conta_numero, cl.razao_social AS contraparte
        FROM estornos_pendentes_receber ep
        JOIN contas_receber cr ON cr.id = ep.conta_receber_id
        JOIN clientes cl ON cl.id = cr.cliente_id
        WHERE ep.status = 'pendente'
        ORDER BY ep.solicitado_em
        """
    ).fetchall()
    pagar = conn.execute(
        """
        SELECT ep.*, cp.numero AS conta_numero, f.nome AS contraparte
        FROM estornos_pendentes_pagar ep
        JOIN contas_pagar cp ON cp.id = ep.conta_pagar_id
        JOIN fornecedores f ON f.id = cp.fornecedor_id
        WHERE ep.status = 'pendente'
        ORDER BY ep.solicitado_em
        """
    ).fetchall()
    resultado = [dict(r, tipo="receber", conta_id=r["conta_receber_id"]) for r in receber]
    resultado += [dict(r, tipo="pagar", conta_id=r["conta_pagar_id"]) for r in pagar]
    resultado.sort(key=lambda r: r["solicitado_em"])
    return jsonify(resultado)


# ============================================================
# FASE 31 — Lista consolidada de REGISTROS de baixa pendentes de aprovação
# ============================================================
@bp.get("/baixas-pendentes")
@requires_permission("financeiro", "visualizar")
def listar_baixas_pendentes():
    """Espelho de `listar_estornos_pendentes` (Fase 22), mas para
    solicitações de REGISTRO de uma baixa nova (Fase 31) — tabela
    diferente, endpoint diferente, porque são dois conceitos diferentes
    (uma pendência de lançar algo novo vs. uma pendência de reverter algo
    já lançado), mesmo os dois usando a mesma ideia de alçada por valor."""
    conn = get_db()
    receber = conn.execute(
        """
        SELECT bp.*, cr.numero AS conta_numero, cl.razao_social AS contraparte
        FROM baixas_pendentes_receber bp
        JOIN contas_receber cr ON cr.id = bp.conta_receber_id
        JOIN clientes cl ON cl.id = cr.cliente_id
        WHERE bp.status = 'pendente'
        ORDER BY bp.solicitado_em
        """
    ).fetchall()
    pagar = conn.execute(
        """
        SELECT bp.*, cp.numero AS conta_numero, f.nome AS contraparte
        FROM baixas_pendentes_pagar bp
        JOIN contas_pagar cp ON cp.id = bp.conta_pagar_id
        JOIN fornecedores f ON f.id = cp.fornecedor_id
        WHERE bp.status = 'pendente'
        ORDER BY bp.solicitado_em
        """
    ).fetchall()
    resultado = [dict(r, tipo="receber", conta_id=r["conta_receber_id"]) for r in receber]
    resultado += [dict(r, tipo="pagar", conta_id=r["conta_pagar_id"]) for r in pagar]
    resultado.sort(key=lambda r: r["solicitado_em"])
    return jsonify(resultado)


# ============================================================
# FASE 33 — Limite de prazo para estorno de baixa, configurável pela tela
# FASE 41 — mesma linha única de configuração ganhou um segundo campo:
# percentual_imposto_venda, usado no DRE (custeio.py) para calcular os
# Impostos sobre Vendas. Continua a MESMA permissão de escrita
# (`configurar_limite_estorno`) — é a mesma tela/formulário de
# "Configurações do Financeiro", só que agora com dois campos em vez de
# um; não parecia valer a pena fragmentar numa permissão nova só por isso.
# ============================================================
@bp.get("/configuracao")
@requires_permission("financeiro", "visualizar")
def obter_configuracao_financeiro():
    """Visualizar o valor atual é liberado pra quem já vê o módulo
    Financeiro (o número em si não é sensível) — só ALTERAR exige a
    permissão nova `configurar_limite_estorno`. Mesmo espírito de
    `estoque.obter_configuracao_estoque` (Fase 32)."""
    conn = get_db()
    row = conn.execute("SELECT * FROM configuracoes_financeiro WHERE id = 1").fetchone()
    if row is None:
        # Defensivo: nunca deveria acontecer num banco inicializado pelas
        # migrations (a Fase 33 já semeia a linha única), mas devolve o
        # padrão em vez de um 404/500 numa tela sensível como esta.
        return jsonify({
            "limite_dias_estorno_baixa": 0, "percentual_imposto_venda": 0,
            "tolerancia_dias_conciliacao": TOLERANCIA_DIAS_CONCILIACAO,
            "percentual_pis": 0, "percentual_cofins": 0, "percentual_icms": 0, "percentual_iss": 0,
            "atualizado_em": None, "atualizado_por": None,
        })
    return jsonify(dict(row))


# Fase 56 — os cinco campos de alíquota da tela "Configurar Financeiro"
# (o `percentual_imposto_venda` genérico da Fase 41 + os quatro novos desta
# fase) seguem todos a MESMA regra de validação/opcionalidade — extraída
# aqui para não repetir o mesmo bloco de try/except cinco vezes.
def _ler_percentual_opcional(conn, dados, campo):
    valor = dados.get(campo)
    if valor is None:
        row_atual = conn.execute(f"SELECT {campo} FROM configuracoes_financeiro WHERE id = 1").fetchone()
        return row_atual[campo] if row_atual else 0.0
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ApiError(f"{campo} deve ser numérico.", status=400)
    if valor < 0 or valor > 100:
        raise ApiError(f"{campo} deve estar entre 0 e 100.", status=400)
    return valor


@bp.put("/configuracao")
@requires_permission("financeiro", "configurar_limite_estorno")
def atualizar_configuracao_financeiro():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    valor = dados.get("limite_dias_estorno_baixa")
    if valor is None:
        raise ApiError("Informe limite_dias_estorno_baixa.", status=400)
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        raise ApiError("limite_dias_estorno_baixa deve ser um número inteiro de dias.", status=400)
    if valor < 0:
        raise ApiError("limite_dias_estorno_baixa não pode ser negativo (use 0 para \"sem limite\").", status=400)

    # Fase 41/55/56 — todos os campos abaixo são OPCIONAIS de propósito:
    # quem só quer atualizar `limite_dias_estorno_baixa` (o único campo
    # obrigatório, desde a Fase 33) continua podendo enviar só ele, sem
    # quebrar por não conhecer os campos adicionados por fases depois —
    # cada um omitido preserva o valor já configurado.
    percentual_imposto = _ler_percentual_opcional(conn, dados, "percentual_imposto_venda")

    tolerancia_dias = dados.get("tolerancia_dias_conciliacao")
    if tolerancia_dias is None:
        row_atual = conn.execute("SELECT tolerancia_dias_conciliacao FROM configuracoes_financeiro WHERE id = 1").fetchone()
        tolerancia_dias = row_atual["tolerancia_dias_conciliacao"] if row_atual else TOLERANCIA_DIAS_CONCILIACAO
    else:
        try:
            tolerancia_dias = int(tolerancia_dias)
        except (TypeError, ValueError):
            raise ApiError("tolerancia_dias_conciliacao deve ser um número inteiro de dias.", status=400)
        if tolerancia_dias < 0:
            raise ApiError("tolerancia_dias_conciliacao não pode ser negativo.", status=400)

    # Fase 56 — as quatro alíquotas detalhadas (PIS/COFINS/ICMS/ISS), cada
    # uma somada à `percentual_imposto_venda` genérica acima no cálculo do
    # DRE (ver `_dre_simplificado` em app/routes/custeio.py) — nunca em
    # substituição a ela.
    percentual_pis = _ler_percentual_opcional(conn, dados, "percentual_pis")
    percentual_cofins = _ler_percentual_opcional(conn, dados, "percentual_cofins")
    percentual_icms = _ler_percentual_opcional(conn, dados, "percentual_icms")
    percentual_iss = _ler_percentual_opcional(conn, dados, "percentual_iss")

    conn.execute(
        """
        INSERT INTO configuracoes_financeiro
            (id, limite_dias_estorno_baixa, percentual_imposto_venda, tolerancia_dias_conciliacao,
             percentual_pis, percentual_cofins, percentual_icms, percentual_iss, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            limite_dias_estorno_baixa = excluded.limite_dias_estorno_baixa,
            percentual_imposto_venda = excluded.percentual_imposto_venda,
            tolerancia_dias_conciliacao = excluded.tolerancia_dias_conciliacao,
            percentual_pis = excluded.percentual_pis,
            percentual_cofins = excluded.percentual_cofins,
            percentual_icms = excluded.percentual_icms,
            percentual_iss = excluded.percentual_iss,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (
            valor, percentual_imposto, tolerancia_dias, percentual_pis, percentual_cofins,
            percentual_icms, percentual_iss, _now_iso(), usuario_atual["id"],
        ),
    )
    audit.registrar(conn, tabela="configuracoes_financeiro", registro_id=1, usuario_id=usuario_atual["id"],
                     acao="limite_estorno_baixa_configurado",
                     valor_novo={
                         "limite_dias_estorno_baixa": valor, "percentual_imposto_venda": percentual_imposto,
                         "tolerancia_dias_conciliacao": tolerancia_dias, "percentual_pis": percentual_pis,
                         "percentual_cofins": percentual_cofins, "percentual_icms": percentual_icms,
                         "percentual_iss": percentual_iss,
                     },
                     motivo=None, ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM configuracoes_financeiro WHERE id = 1").fetchone()
    return jsonify(dict(row))


# ============================================================
# FASE 40 — CONCILIAÇÃO BANCÁRIA (Importação de Extrato OFX)
# ============================================================
# Duas metades: (1) importar um arquivo OFX e conciliar automaticamente
# tudo que tiver candidato ÚNICO e inequívoco (mesmo valor, data próxima);
# (2) uma fila de revisão manual para o resto — 0 candidatos (nada bate)
# ou mais de 1 candidato (ambíguo, uma pessoa precisa escolher). Nunca
# concilia automaticamente na presença de ambiguidade, de propósito: um
# "quase acerto" errado seria pior do que deixar pendente.
#
# Fase 55 — o valor de 3 dias abaixo virou só o PADRÃO de bootstrap (usado
# na migration `schema_fase55.sql` e como fallback defensivo se a linha de
# configuração não existir); o valor efetivo passou a morar em
# `configuracoes_financeiro.tolerancia_dias_conciliacao`, lido por
# `_tolerancia_dias_conciliacao` a cada requisição — ver essa função e o
# comentário na migration para o motivo completo.
TOLERANCIA_DIAS_CONCILIACAO = 3


def _tolerancia_dias_conciliacao(conn):
    row = conn.execute("SELECT tolerancia_dias_conciliacao FROM configuracoes_financeiro WHERE id = 1").fetchone()
    return row["tolerancia_dias_conciliacao"] if row is not None else TOLERANCIA_DIAS_CONCILIACAO


def _candidatos_receber(conn, valor_abs, data, tolerancia_dias):
    return conn.execute(
        """
        SELECT crb.id, crb.valor, crb.data_pagamento, crb.forma_pagamento,
               cr.numero AS conta_numero, cl.razao_social AS contraparte_nome
        FROM contas_receber_baixas crb
        JOIN contas_receber cr ON cr.id = crb.conta_receber_id
        JOIN clientes cl ON cl.id = cr.cliente_id
        WHERE ABS(crb.valor - ?) < 0.005
          AND ABS(julianday(crb.data_pagamento) - julianday(?)) <= ?
          AND crb.id NOT IN (
              SELECT conta_receber_baixa_id FROM extrato_transacoes
              WHERE conta_receber_baixa_id IS NOT NULL AND status = 'conciliada'
          )
        ORDER BY ABS(julianday(crb.data_pagamento) - julianday(?))
        """,
        (valor_abs, data, tolerancia_dias, data),
    ).fetchall()


def _candidatos_pagar(conn, valor_abs, data, tolerancia_dias):
    return conn.execute(
        """
        SELECT cpb.id, cpb.valor, cpb.data_pagamento, cpb.forma_pagamento,
               cp.numero AS conta_numero, f.nome AS contraparte_nome
        FROM contas_pagar_baixas cpb
        JOIN contas_pagar cp ON cp.id = cpb.conta_pagar_id
        JOIN fornecedores f ON f.id = cp.fornecedor_id
        WHERE ABS(cpb.valor - ?) < 0.005
          AND ABS(julianday(cpb.data_pagamento) - julianday(?)) <= ?
          AND cpb.id NOT IN (
              SELECT conta_pagar_baixa_id FROM extrato_transacoes
              WHERE conta_pagar_baixa_id IS NOT NULL AND status = 'conciliada'
          )
        ORDER BY ABS(julianday(cpb.data_pagamento) - julianday(?))
        """,
        (valor_abs, data, tolerancia_dias, data),
    ).fetchall()


def _candidatos_para_transacao(conn, transacao, tolerancia_dias=None):
    """Crédito (valor > 0) procura em contas a receber; débito (valor <
    0) procura em contas a pagar — convenção universal de extrato
    bancário. `tolerancia_dias` pode ser passado já calculado (ex.: num
    laço processando várias transações de uma vez, para não reler a
    configuração a cada iteração) — se omitido, é lido agora mesmo."""
    if tolerancia_dias is None:
        tolerancia_dias = _tolerancia_dias_conciliacao(conn)
    valor_abs = abs(transacao["valor"])
    if transacao["valor"] > 0:
        return "receber", _candidatos_receber(conn, valor_abs, transacao["data"], tolerancia_dias)
    return "pagar", _candidatos_pagar(conn, valor_abs, transacao["data"], tolerancia_dias)


def _transacao_dict(conn, row):
    t = dict(row)
    if t["conta_receber_baixa_id"]:
        conta = conn.execute(
            """
            SELECT cr.numero AS conta_numero, cl.razao_social AS contraparte_nome
            FROM contas_receber_baixas crb JOIN contas_receber cr ON cr.id = crb.conta_receber_id
            JOIN clientes cl ON cl.id = cr.cliente_id WHERE crb.id = ?
            """,
            (t["conta_receber_baixa_id"],),
        ).fetchone()
        t["conciliado_com"] = {"tipo": "receber", **dict(conta)} if conta else None
    elif t["conta_pagar_baixa_id"]:
        conta = conn.execute(
            """
            SELECT cp.numero AS conta_numero, f.nome AS contraparte_nome
            FROM contas_pagar_baixas cpb JOIN contas_pagar cp ON cp.id = cpb.conta_pagar_id
            JOIN fornecedores f ON f.id = cp.fornecedor_id WHERE cpb.id = ?
            """,
            (t["conta_pagar_baixa_id"],),
        ).fetchone()
        t["conciliado_com"] = {"tipo": "pagar", **dict(conta)} if conta else None
    else:
        t["conciliado_com"] = None
    return t


@bp.get("/extratos")
@requires_permission("financeiro", "conciliar_extrato")
def listar_extratos():
    conn = get_db()
    extratos = conn.execute("SELECT * FROM extratos_bancarios ORDER BY importado_em DESC").fetchall()
    resultado = []
    for e in extratos:
        extrato = dict(e)
        contagens = conn.execute(
            "SELECT status, COUNT(*) AS total FROM extrato_transacoes WHERE extrato_id = ? GROUP BY status",
            (extrato["id"],),
        ).fetchall()
        extrato["contagem_por_status"] = {c["status"]: c["total"] for c in contagens}
        resultado.append(extrato)
    return jsonify(resultado)


@bp.get("/extratos/<int:extrato_id>")
@requires_permission("financeiro", "conciliar_extrato")
def obter_extrato(extrato_id):
    conn = get_db()
    extrato = conn.execute("SELECT * FROM extratos_bancarios WHERE id = ?", (extrato_id,)).fetchone()
    if extrato is None:
        raise ApiError("Extrato não encontrado.", status=404)
    transacoes = conn.execute(
        "SELECT * FROM extrato_transacoes WHERE extrato_id = ? ORDER BY data, id", (extrato_id,)
    ).fetchall()
    resultado = dict(extrato)
    resultado["transacoes"] = [_transacao_dict(conn, t) for t in transacoes]
    return jsonify(resultado)


@bp.post("/extratos/importar")
@requires_permission("financeiro", "conciliar_extrato")
def importar_extrato():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome_arquivo = (dados.get("nome_arquivo") or "extrato.ofx").strip()
    conteudo_base64 = dados.get("dados") or ""
    if not conteudo_base64:
        raise ApiError("Informe o conteúdo do arquivo OFX em base64 (campo 'dados').", status=400)
    if "," in conteudo_base64 and conteudo_base64.strip().lower().startswith("data:"):
        conteudo_base64 = conteudo_base64.split(",", 1)[1]

    try:
        bruto = base64.b64decode(conteudo_base64, validate=True)
    except Exception:
        raise ApiError("Conteúdo do arquivo não é um base64 válido.", status=400)

    # OFX não tem um padrão único de codificação de texto — a maioria dos
    # bancos brasileiros usa Latin-1 (ISO-8859-1) por herança de sistemas
    # antigos, mas alguns já exportam em UTF-8; tenta UTF-8 primeiro
    # (falha alto se não for) e cai para Latin-1, que aceita qualquer
    # byte e nunca lança erro de decodificação.
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")

    try:
        extraido = parse_ofx(texto)
    except ValueError as erro:
        raise ApiError(str(erro), status=400)

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO extratos_bancarios (nome_arquivo, banco, conta, total_transacoes, importado_por) VALUES (?, ?, ?, ?, ?)",
        (nome_arquivo, extraido["banco"], extraido["conta"], len(extraido["transacoes"]), usuario_atual["id"]),
    )
    extrato_id = cur.lastrowid

    total_importadas = 0
    total_duplicadas = 0
    total_conciliadas_automaticamente = 0
    # Fase 55 — lida uma vez só antes do laço, não a cada transação: a
    # configuração não muda no meio de uma importação.
    tolerancia_dias = _tolerancia_dias_conciliacao(conn)
    for transacao in extraido["transacoes"]:
        if transacao["fitid"]:
            ja_existe = conn.execute(
                "SELECT 1 FROM extrato_transacoes WHERE fitid = ?", (transacao["fitid"],)
            ).fetchone()
            if ja_existe:
                # Mesma transação já importada antes (arquivo reimportado
                # ou período sobreposto a uma importação anterior) — pula
                # em silêncio em vez de duplicar ou dar erro, para que
                # reimportar um extrato seja sempre seguro.
                total_duplicadas += 1
                continue

        cur_transacao = conn.execute(
            "INSERT INTO extrato_transacoes (extrato_id, fitid, data, valor, descricao) VALUES (?, ?, ?, ?, ?)",
            (extrato_id, transacao["fitid"], transacao["data"], transacao["valor"], transacao["descricao"]),
        )
        transacao_id = cur_transacao.lastrowid
        total_importadas += 1

        tipo, candidatos = _candidatos_para_transacao(
            conn, {"valor": transacao["valor"], "data": transacao["data"]}, tolerancia_dias
        )
        if len(candidatos) == 1:
            campo = "conta_receber_baixa_id" if tipo == "receber" else "conta_pagar_baixa_id"
            conn.execute(
                f"""
                UPDATE extrato_transacoes
                SET status = 'conciliada', {campo} = ?, conciliado_automaticamente = 1,
                    conciliado_em = ?, conciliado_por = ?
                WHERE id = ?
                """,
                (candidatos[0]["id"], _now_iso(), usuario_atual["id"], transacao_id),
            )
            total_conciliadas_automaticamente += 1

    audit.registrar(conn, tabela="extratos_bancarios", registro_id=extrato_id, usuario_id=usuario_atual["id"],
                     acao="extrato_importado",
                     valor_novo={
                         "nome_arquivo": nome_arquivo, "total_importadas": total_importadas,
                         "total_duplicadas": total_duplicadas, "total_conciliadas_automaticamente": total_conciliadas_automaticamente,
                     },
                     ip=client_ip(), dispositivo=client_device())

    extrato = dict(conn.execute("SELECT * FROM extratos_bancarios WHERE id = ?", (extrato_id,)).fetchone())
    extrato["total_importadas"] = total_importadas
    extrato["total_duplicadas_ignoradas"] = total_duplicadas
    extrato["total_conciliadas_automaticamente"] = total_conciliadas_automaticamente
    extrato["total_pendentes_revisao"] = total_importadas - total_conciliadas_automaticamente
    return jsonify(extrato), 201


def _transacao_ou_404(conn, transacao_id):
    row = conn.execute("SELECT * FROM extrato_transacoes WHERE id = ?", (transacao_id,)).fetchone()
    if row is None:
        raise ApiError("Transação de extrato não encontrada.", status=404)
    return dict(row)


@bp.get("/extratos/transacoes/<int:transacao_id>/sugestoes")
@requires_permission("financeiro", "conciliar_extrato")
def sugestoes_conciliacao(transacao_id):
    conn = get_db()
    transacao = _transacao_ou_404(conn, transacao_id)
    tolerancia_dias = _tolerancia_dias_conciliacao(conn)
    tipo, candidatos = _candidatos_para_transacao(conn, transacao, tolerancia_dias)
    return jsonify({
        "tipo": tipo, "candidatos": [dict(c) for c in candidatos],
        "tolerancia_dias_conciliacao": tolerancia_dias,
    })


@bp.post("/extratos/transacoes/<int:transacao_id>/conciliar")
@requires_permission("financeiro", "conciliar_extrato")
def conciliar_transacao(transacao_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    tipo = dados.get("tipo")
    baixa_id = dados.get("baixa_id")
    conn = get_db()
    transacao = _transacao_ou_404(conn, transacao_id)

    if transacao["status"] == "conciliada":
        raise ApiError("Esta transação já está conciliada — desconcilie antes de escolher outra baixa.", status=400)
    if tipo not in ("receber", "pagar"):
        raise ApiError("Informe tipo ('receber' ou 'pagar').", status=400)
    if not baixa_id:
        raise ApiError("Informe baixa_id.", status=400)

    tabela_baixas = "contas_receber_baixas" if tipo == "receber" else "contas_pagar_baixas"
    campo_extrato = "conta_receber_baixa_id" if tipo == "receber" else "conta_pagar_baixa_id"
    baixa = conn.execute(f"SELECT * FROM {tabela_baixas} WHERE id = ?", (baixa_id,)).fetchone()
    if baixa is None:
        raise ApiError("Baixa não encontrada.", status=404)

    ja_conciliada_com_outra = conn.execute(
        f"SELECT 1 FROM extrato_transacoes WHERE {campo_extrato} = ? AND status = 'conciliada' AND id != ?",
        (baixa_id, transacao_id),
    ).fetchone()
    if ja_conciliada_com_outra:
        raise ApiError("Esta baixa já está conciliada com outra transação do extrato.", status=409)

    conn.execute(
        f"""
        UPDATE extrato_transacoes
        SET status = 'conciliada', {campo_extrato} = ?, conciliado_automaticamente = 0,
            conciliado_em = ?, conciliado_por = ?, ignorado_motivo = NULL
        WHERE id = ?
        """,
        (baixa_id, _now_iso(), usuario_atual["id"], transacao_id),
    )
    audit.registrar(conn, tabela="extrato_transacoes", registro_id=transacao_id, usuario_id=usuario_atual["id"],
                     acao="transacao_conciliada_manualmente", valor_novo={"tipo": tipo, "baixa_id": baixa_id},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM extrato_transacoes WHERE id = ?", (transacao_id,)).fetchone()
    return jsonify(_transacao_dict(conn, row))


@bp.post("/extratos/transacoes/<int:transacao_id>/ignorar")
@requires_permission("financeiro", "conciliar_extrato")
def ignorar_transacao(transacao_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()
    transacao = _transacao_ou_404(conn, transacao_id)

    if transacao["status"] == "conciliada":
        raise ApiError("Esta transação já está conciliada — desconcilie antes de ignorá-la.", status=400)
    if not motivo:
        raise ApiError("Informe o motivo de ignorar esta transação (ex.: transferência entre contas próprias).", status=400)

    conn.execute(
        "UPDATE extrato_transacoes SET status = 'ignorada', ignorado_motivo = ? WHERE id = ?",
        (motivo, transacao_id),
    )
    audit.registrar(conn, tabela="extrato_transacoes", registro_id=transacao_id, usuario_id=usuario_atual["id"],
                     acao="transacao_ignorada", valor_novo={"motivo": motivo}, motivo=motivo,
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM extrato_transacoes WHERE id = ?", (transacao_id,)).fetchone()
    return jsonify(_transacao_dict(conn, row))


@bp.post("/extratos/transacoes/<int:transacao_id>/desconciliar")
@requires_permission("financeiro", "conciliar_extrato")
def desconciliar_transacao(transacao_id):
    """Reversível de propósito — diferente da baixa em si (append-only,
    nunca editável), o VÍNCULO entre uma linha de extrato e uma baixa é
    só um apontamento de conciliação; desfazer não altera nem apaga
    nenhum lançamento financeiro real, só volta a transação do extrato
    para 'pendente' para escolher outra baixa (ou deixar em revisão)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    transacao = _transacao_ou_404(conn, transacao_id)

    if transacao["status"] not in ("conciliada", "ignorada"):
        raise ApiError("Esta transação já está pendente.", status=400)

    valor_anterior = {
        "status": transacao["status"], "conta_receber_baixa_id": transacao["conta_receber_baixa_id"],
        "conta_pagar_baixa_id": transacao["conta_pagar_baixa_id"], "ignorado_motivo": transacao["ignorado_motivo"],
    }
    conn.execute(
        """
        UPDATE extrato_transacoes
        SET status = 'pendente', conta_receber_baixa_id = NULL, conta_pagar_baixa_id = NULL,
            conciliado_automaticamente = 0, conciliado_em = NULL, conciliado_por = NULL, ignorado_motivo = NULL
        WHERE id = ?
        """,
        (transacao_id,),
    )
    audit.registrar(conn, tabela="extrato_transacoes", registro_id=transacao_id, usuario_id=usuario_atual["id"],
                     acao="transacao_desconciliada", valor_anterior=valor_anterior,
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM extrato_transacoes WHERE id = ?", (transacao_id,)).fetchone()
    return jsonify(_transacao_dict(conn, row))


# ============================================================
# FASE 55 — Conciliação Bancária: Processamento em Lote de Pendentes
# ============================================================
@bp.post("/extratos/conciliar-pendentes-em-massa")
@requires_permission("financeiro", "conciliar_extrato")
def conciliar_pendentes_em_massa():
    """Reprocessa transações 'pendente' já importadas, aplicando a MESMA
    regra automática da importação (Fase 40): só concilia quando há
    exatamente 1 candidato inequívoco (mesmo valor, dentro da tolerância de
    dias configurada — Fase 55) — nunca na presença de ambiguidade (0 ou
    2+ candidatos), idêntico à importação.

    Existe porque a auto-conciliação da Fase 40 só era tentada UMA VEZ, no
    instante da importação — uma transação que ficou pendente só porque a
    baixa correspondente ainda não existia (extrato chegou antes do
    pagamento ser lançado no Financeiro) nunca era reprocessada depois,
    mesmo que a baixa aparecesse minutos ou dias mais tarde. `extrato_id`
    é opcional no corpo da requisição: informado, escopa o reprocessamento
    a um único extrato; omitido, reprocessa TODAS as transações pendentes
    do sistema de uma vez."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    extrato_id = dados.get("extrato_id")
    conn = get_db()

    if extrato_id is not None:
        extrato = conn.execute("SELECT id FROM extratos_bancarios WHERE id = ?", (extrato_id,)).fetchone()
        if extrato is None:
            raise ApiError("Extrato não encontrado.", status=404)
        pendentes = conn.execute(
            "SELECT * FROM extrato_transacoes WHERE status = 'pendente' AND extrato_id = ? ORDER BY id",
            (extrato_id,),
        ).fetchall()
    else:
        pendentes = conn.execute(
            "SELECT * FROM extrato_transacoes WHERE status = 'pendente' ORDER BY id"
        ).fetchall()

    tolerancia_dias = _tolerancia_dias_conciliacao(conn)
    agora = _now_iso()
    conciliadas = []
    for transacao in pendentes:
        tipo, candidatos = _candidatos_para_transacao(conn, dict(transacao), tolerancia_dias)
        if len(candidatos) != 1:
            continue
        campo = "conta_receber_baixa_id" if tipo == "receber" else "conta_pagar_baixa_id"
        conn.execute(
            f"""
            UPDATE extrato_transacoes
            SET status = 'conciliada', {campo} = ?, conciliado_automaticamente = 1,
                conciliado_em = ?, conciliado_por = ?
            WHERE id = ?
            """,
            (candidatos[0]["id"], agora, usuario_atual["id"], transacao["id"]),
        )
        conciliadas.append({
            "transacao_id": transacao["id"], "extrato_id": transacao["extrato_id"],
            "tipo": tipo, "baixa_id": candidatos[0]["id"],
        })

    total_processadas = len(pendentes)
    total_conciliadas = len(conciliadas)
    audit.registrar(
        conn, tabela="extrato_transacoes", registro_id=extrato_id, usuario_id=usuario_atual["id"],
        acao="conciliacao_em_massa_processada",
        valor_novo={
            "extrato_id": extrato_id, "total_processadas": total_processadas,
            "total_conciliadas": total_conciliadas, "tolerancia_dias_conciliacao": tolerancia_dias,
        },
        ip=client_ip(), dispositivo=client_device(),
    )

    return jsonify({
        "total_processadas": total_processadas,
        "total_conciliadas": total_conciliadas,
        "total_permanecem_pendentes": total_processadas - total_conciliadas,
        "conciliadas": conciliadas,
    })
