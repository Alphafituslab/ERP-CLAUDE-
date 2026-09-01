import datetime
import secrets
import sqlite3

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import cnpj_service
from .. import notificacoes_service
from .. import security
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..permissions import requires_permission
from .estoque import _reservado_producao_lote, _saldo_posicao

bp = Blueprint("comercial", __name__, url_prefix="/api/v1/comercial")

STATUS_QUE_PERMITEM_EDITAR_ITENS = ("rascunho",)
STATUS_QUE_PERMITEM_CANCELAR = ("rascunho", "confirmado")

# Fase 70 — ver nota completa em `editar_cliente` abaixo.
CAMPOS_FISCAIS_CLIENTE_EDITAVEIS = (
    "inscricao_estadual", "logradouro", "numero_endereco", "complemento_endereco",
    "bairro", "municipio", "codigo_ibge_municipio", "uf", "cep",
)


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hoje_iso_data():
    """Fase 64 — mesmo padrão de `_hoje_iso_data` em app/routes/compras.py:
    só a parte de data (sem hora), para comparar contra `vencimento`
    (que também é só data) sem fuso horário entrar no meio."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _gerar_numero_pedido():
    ano = datetime.datetime.utcnow().year
    return f"PV-{ano}-{secrets.token_hex(4).upper()}"


def _gerar_numero_conta_receber():
    ano = datetime.datetime.utcnow().year
    return f"CR-{ano}-{secrets.token_hex(4).upper()}"


# Fase 36 — 0.0 preserva o comportamento de antes desta fase (nenhuma
# verba é gerada) em qualquer banco onde ninguém configurou um valor pela
# tela nova (ver app/routes/vendas_app.py:obter_configuracao_comercial).
PERCENTUAL_VERBA_GERADA_PADRAO = 0.0


def _percentual_verba_gerada(conn):
    row = conn.execute("SELECT percentual_verba_gerada FROM configuracoes_comercial WHERE id = 1").fetchone()
    return row["percentual_verba_gerada"] if row else PERCENTUAL_VERBA_GERADA_PADRAO


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


# Fase 63 — mesma ideia de _valor_total_pedido em app/routes/compras.py
# (Fase 61): soma quantidade x preco_unitario de todas as linhas do
# pedido, ainda em rascunho — é esse valor que decide se a CONFIRMAÇÃO
# fica pendente de aprovação por estourar o limite de crédito do
# cliente, antes mesmo de existir uma conta a receber (que só nasce na
# expedição, ver nota em `expedir` abaixo).
def _valor_total_pedido_venda(conn, pedido_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(quantidade * preco_unitario), 0) AS total FROM pedido_venda_itens WHERE pedido_id = ?",
        (pedido_id,),
    ).fetchone()
    return round(row["total"], 2)


# Fase 63 — soma o saldo em aberto de TODAS as contas a receber ativas
# deste cliente (status 'aberto' ou 'pago_parcial' — 'pago' e 'cancelado'
# não contam mais contra o limite). O saldo de cada conta é sempre
# valor_total - baixas, nunca um campo guardado à parte (mesmo princípio
# já documentado em schema_fase6.sql).
def _saldo_aberto_cliente(conn, cliente_id):
    contas = conn.execute(
        "SELECT id, valor_total FROM contas_receber WHERE cliente_id = ? AND status IN ('aberto', 'pago_parcial')",
        (cliente_id,),
    ).fetchall()
    total = 0.0
    for conta in contas:
        baixado = conn.execute(
            "SELECT COALESCE(SUM(valor), 0) AS total FROM contas_receber_baixas WHERE conta_receber_id = ?",
            (conta["id"],),
        ).fetchone()["total"]
        total += conta["valor_total"] - baixado
    return round(total, 2)


# Fase 64 — Desempenho de Cliente (Scorecard), mesmo espírito de
# `_desempenho_fornecedor` em app/routes/fornecedores.py (Fase 62): 100%
# agregação de leitura sobre tabelas que já existem, sem nenhuma tabela ou
# coluna nova — reaproveita inclusive `_saldo_aberto_cliente` (Fase 63)
# para mostrar o saldo em aberto ATUAL do cliente dentro do mesmo painel.
def _desempenho_cliente(conn, cliente_id):
    pedidos = conn.execute(
        "SELECT status FROM pedidos_venda WHERE cliente_id = ?", (cliente_id,)
    ).fetchall()
    pedidos_por_status = {"rascunho": 0, "confirmado": 0, "expedido": 0, "cancelado": 0}
    for p in pedidos:
        pedidos_por_status[p["status"]] = pedidos_por_status.get(p["status"], 0) + 1

    # Valor vendido — soma do que virou um compromisso de verdade com o
    # cliente (confirmado ou expedido); 'rascunho' nunca chegou a reservar
    # estoque de verdade e 'cancelado' nunca virou venda, então nenhum dos
    # dois soma aqui — mesmo raciocínio de `valor_total_comprado` em
    # `_desempenho_fornecedor`.
    valor_total_vendido = conn.execute(
        """
        SELECT COALESCE(SUM(pvi.quantidade * pvi.preco_unitario), 0) AS total
        FROM pedido_venda_itens pvi
        JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
        WHERE pv.cliente_id = ? AND pv.status IN ('confirmado', 'expedido')
        """,
        (cliente_id,),
    ).fetchone()["total"]

    # Pontualidade de pagamento — só contas JÁ totalmente pagas entram na
    # taxa (o que já está 'aberto' ou 'pago_parcial' ainda pode ser pago em
    # dia, não é um "atraso" definitivo até a última baixa acontecer); a
    # data efetiva de pagamento é a da ÚLTIMA baixa registrada contra a
    # conta (`MAX(data_pagamento)`), comparada contra o vencimento.
    contas = conn.execute(
        "SELECT id, vencimento, status FROM contas_receber WHERE cliente_id = ?", (cliente_id,)
    ).fetchall()
    pagamentos_no_prazo = 0
    pagamentos_atrasados = 0
    contas_em_atraso_no_momento = 0
    soma_dias_atraso = 0
    hoje = _hoje_iso_data()
    for conta in contas:
        if conta["status"] == "pago":
            ultima_baixa = conn.execute(
                "SELECT MAX(data_pagamento) AS data FROM contas_receber_baixas WHERE conta_receber_id = ?",
                (conta["id"],),
            ).fetchone()["data"]
            if ultima_baixa is not None:
                if ultima_baixa[:10] <= conta["vencimento"]:
                    pagamentos_no_prazo += 1
                else:
                    pagamentos_atrasados += 1
                    # Fase 102 — "score" interno pedido pelo usuário: média
                    # de dias de atraso, não só a taxa de pontualidade
                    # (percentual) que já existia. Comparação por data pura
                    # (sem hora), já que vencimento/data_pagamento são
                    # sempre "AAAA-MM-DD" neste sistema.
                    soma_dias_atraso += (
                        datetime.datetime.strptime(ultima_baixa[:10], "%Y-%m-%d")
                        - datetime.datetime.strptime(conta["vencimento"], "%Y-%m-%d")
                    ).days
        elif conta["status"] in ("aberto", "pago_parcial") and conta["vencimento"] < hoje:
            contas_em_atraso_no_momento += 1
    total_avaliadas = pagamentos_no_prazo + pagamentos_atrasados
    taxa_pontualidade_pct = round((pagamentos_no_prazo / total_avaliadas) * 100, 1) if total_avaliadas > 0 else None
    media_dias_atraso = round(soma_dias_atraso / pagamentos_atrasados, 1) if pagamentos_atrasados > 0 else None

    return {
        "cliente_id": cliente_id,
        "total_pedidos_venda": len(pedidos),
        "pedidos_por_status": pedidos_por_status,
        "valor_total_vendido": round(valor_total_vendido, 2),
        # Fase 63 — mesmo cálculo usado para decidir se uma confirmação
        # precisa de segunda aprovação, exposto aqui só para leitura.
        "saldo_aberto_atual": _saldo_aberto_cliente(conn, cliente_id),
        "pagamentos": {
            "total_avaliados": total_avaliadas,
            "no_prazo": pagamentos_no_prazo,
            "atrasados": pagamentos_atrasados,
            "taxa_pontualidade_pct": taxa_pontualidade_pct,
            "contas_em_atraso_no_momento": contas_em_atraso_no_momento,
            # Fase 102 — média de dias de atraso SÓ das contas pagas com
            # atraso (None quando nunca houve nenhuma) — "score interno"
            # pedido pelo usuário, calculado ao vivo, nunca guardado à
            # parte (mesma filosofia de todo o resto deste painel).
            "media_dias_atraso": media_dias_atraso,
        },
    }


def _empresa_ou_404(conn, empresa_id):
    """Fase 52 — mesma validação de app/routes/producao.py/lotes.py,
    duplicada de propósito para não criar acoplamento entre módulos de
    rota só por um SELECT de 3 linhas."""
    empresa = conn.execute("SELECT id FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if empresa is None:
        raise ApiError("Empresa não encontrada.", status=404)


def _pedido_detalhado(conn, pedido_id):
    pedido = _pedido_ou_404(conn, pedido_id)
    cliente = conn.execute("SELECT razao_social, cnpj FROM clientes WHERE id = ?", (pedido["cliente_id"],)).fetchone()
    pedido["cliente_razao_social"] = cliente["razao_social"] if cliente else None
    pedido["cliente_cnpj"] = cliente["cnpj"] if cliente else None

    # Fase 52 — empresa_id é opcional (ver schema_fase52.sql); a maioria
    # dos pedidos continua sem nenhuma.
    if pedido["empresa_id"]:
        empresa = conn.execute(
            "SELECT nome_fantasia, razao_social FROM empresas WHERE id = ?", (pedido["empresa_id"],)
        ).fetchone()
        pedido["empresa_nome"] = (empresa["nome_fantasia"] or empresa["razao_social"]) if empresa else None
    else:
        pedido["empresa_nome"] = None

    itens = conn.execute(
        """
        SELECT pvi.*, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM pedido_venda_itens pvi JOIN itens i ON i.id = pvi.item_id
        WHERE pvi.pedido_id = ? ORDER BY pvi.id
        """,
        (pedido_id,),
    ).fetchall()
    itens_detalhados = []
    valor_total_pedido = 0.0
    for item in itens:
        item = dict(item)
        reservas = conn.execute(
            """
            SELECT pvr.*, l.codigo_lote, p.codigo AS posicao_codigo
            FROM pedido_venda_reservas pvr
            JOIN lotes l ON l.id = pvr.lote_id
            JOIN posicoes_estoque p ON p.id = pvr.posicao_id
            WHERE pvr.pedido_item_id = ? ORDER BY pvr.id
            """,
            (item["id"],),
        ).fetchall()
        item["reservas"] = [dict(r) for r in reservas]
        item["valor_total"] = item["quantidade"] * item["preco_unitario"]
        valor_total_pedido += item["valor_total"]
        itens_detalhados.append(item)
    pedido["itens"] = itens_detalhados
    pedido["valor_total"] = valor_total_pedido

    conta_receber = conn.execute("SELECT * FROM contas_receber WHERE pedido_venda_id = ?", (pedido_id,)).fetchone()
    pedido["conta_receber"] = dict(conta_receber) if conta_receber else None

    # Fase 63 — se há uma solicitação de confirmação pendente de aprovação
    # (limite de crédito do cliente estourado, ver
    # migrations/schema_fase63.sql), expõe aqui para o front mostrar
    # "aguardando aprovação" em vez de tratar como um rascunho comum.
    confirmacao_pendente = conn.execute(
        "SELECT * FROM pedidos_venda_confirmacoes_pendentes WHERE pedido_venda_id = ? AND status = 'pendente'",
        (pedido_id,),
    ).fetchone()
    pedido["confirmacao_pendente"] = dict(confirmacao_pendente) if confirmacao_pendente else None
    return pedido


def _saldo_reservado_ativo(conn, lote_id, posicao_id):
    """Quanto de um (lote, posição) está comprometido por pedidos AINDA
    ativos (status 'confirmado' — um pedido em rascunho ainda não reservou
    nada de verdade, e um pedido expedido/cancelado já parou de contar,
    sem precisar apagar ou editar a reserva histórica: ela só some do
    cálculo porque o pedido pai mudou de status)."""
    total = conn.execute(
        """
        SELECT COALESCE(SUM(pvr.quantidade), 0) AS total
        FROM pedido_venda_reservas pvr
        JOIN pedido_venda_itens pvi ON pvi.id = pvr.pedido_item_id
        JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
        WHERE pvr.lote_id = ? AND pvr.posicao_id = ? AND pv.status = 'confirmado'
        """,
        (lote_id, posicao_id),
    ).fetchone()["total"]
    return total


def _saldo_disponivel_para_reserva(conn, lote_id, posicao_id):
    return _saldo_posicao(conn, lote_id, posicao_id) - _saldo_reservado_ativo(conn, lote_id, posicao_id)


def _alocar_fefo(conn, item_id, quantidade_necessaria, reservado_extra=None):
    """Aloca a quantidade necessária de um item contra o saldo físico já
    endereçado em posições (Fase 4), priorizando sempre o lote que vence
    primeiro (FEFO) e descontando o que já está reservado por outros
    pedidos 'confirmado'. Devolve (alocacoes, quantidade_coberta) — quem
    chama decide se cobertura parcial é aceitável (na confirmação de
    pedido, não é).

    `reservado_extra` é um dict opcional {(lote_id, posicao_id): quantidade}
    com alocações já PLANEJADAS nesta mesma confirmação mas ainda não
    gravadas no banco (ver confirmar() abaixo — necessário quando um
    pedido tem duas linhas do mesmo item: a segunda linha não pode alocar
    o mesmo saldo que a primeira já reservou, mesmo que a primeira ainda
    não tenha sido persistida).

    Fase 12: também desconta o que uma ordem de produção liberada já
    reservou daquele LOTE (`_reservado_producao_lote`, que é por lote, não
    por posição — Produção não trabalha com posições de WMS). Como o
    "hold" de produção é por lote e este loop aloca por (lote, posição),
    o hold de cada lote é consumido progressivamente à medida que suas
    posições aparecem em ordem de FEFO, garantindo que a soma alocada
    entre TODAS as posições de um mesmo lote nunca ultrapasse o que
    sobrou depois do que Produção já reservou — sem precisar mexer em
    `_saldo_disponivel_para_reserva` (que continua sendo só "físico menos
    reserva de venda", usada também em outros lugares).

    Fase 65 — um lote com `validade` já passada NUNCA entra nesta lista,
    mesmo que ainda esteja com saldo físico positivo e status
    'aprovado'/'aprovado_com_ressalva': antes desta fase, a ordenação por
    validade (FEFO) priorizava vender o lote vencido primeiro, mas nunca
    IMPEDIA vender um lote vencido — um bug real de conformidade para um
    ERP de nutracêuticos/farma. Continua aparecendo normalmente nas telas
    de Estoque/Lotes (com o selo "Vencido", ver `_lote_ou_404`), só não
    conta mais como saldo disponível para nenhuma alocação — a saída
    correta para esse saldo é dar baixa dele (`/estoque/baixas`)."""
    reservado_extra = reservado_extra or {}
    combos = conn.execute(
        """
        SELECT m.lote_id, m.posicao_id, l.validade
        FROM movimentacoes_estoque m
        JOIN lotes l ON l.id = m.lote_id
        WHERE l.item_id = ? AND l.status IN ('aprovado', 'aprovado_com_ressalva')
          AND (l.validade IS NULL OR l.validade >= ?)
        GROUP BY m.lote_id, m.posicao_id
        HAVING SUM(m.quantidade) > 0.0000001
        ORDER BY (l.validade IS NULL), l.validade ASC, m.lote_id ASC, m.posicao_id ASC
        """,
        (item_id, _hoje_iso_data()),
    ).fetchall()

    alocacoes = []
    restante = quantidade_necessaria
    holds_producao_por_lote = {}
    for combo in combos:
        if restante <= 0.0000001:
            break
        lote_id = combo["lote_id"]
        if lote_id not in holds_producao_por_lote:
            holds_producao_por_lote[lote_id] = _reservado_producao_lote(conn, lote_id)
        chave = (lote_id, combo["posicao_id"])
        disponivel = _saldo_disponivel_para_reserva(conn, lote_id, combo["posicao_id"]) - reservado_extra.get(chave, 0)
        hold_restante = holds_producao_por_lote[lote_id]
        if hold_restante > 0.0000001 and disponivel > 0:
            absorvido = min(hold_restante, disponivel)
            disponivel -= absorvido
            holds_producao_por_lote[lote_id] -= absorvido
        if disponivel <= 0.0000001:
            continue
        quantidade = min(disponivel, restante)
        alocacoes.append({"lote_id": lote_id, "posicao_id": combo["posicao_id"], "quantidade": quantidade})
        restante -= quantidade
    return alocacoes, quantidade_necessaria - restante


def _validar_item_vendavel(conn, item_id):
    item = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError("Item não encontrado.", status=404)
    if item["tipo"] != "produto_acabado":
        raise ApiError(
            f"Só é possível vender itens do tipo 'produto_acabado' (item '{item['codigo']}' é do tipo '{item['tipo']}').",
            status=400,
        )
    return dict(item)


# ============================================================
# CLIENTES
# ============================================================
@bp.get("/clientes/consultar-cnpj/<cnpj>")
@requires_permission("comercial", "cadastrar_cliente")
def consultar_cnpj_cliente(cnpj):
    """Fase 101 — busca razão social/endereço/e-mail públicos na Receita
    Federal (via BrasilAPI, ver app/cnpj_service.py) para pré-preencher o
    formulário de novo cliente. Mesma permissão de cadastrar cliente (não
    faz sentido consultar CNPJ sem poder usar o resultado para nada)."""
    conn = get_db()
    resultado = cnpj_service.consultar_cnpj(cnpj)
    # Mesmo estilo de comparação usado em `criar_cliente` (WHERE cnpj = ?
    # contra o texto exato como foi digitado) — este sistema não impõe
    # máscara/normalização de CNPJ em lugar nenhum ainda, então compara
    # tanto o valor recebido quanto a versão só-dígitos, cobrindo cliente
    # já cadastrado com ou sem pontuação.
    ja_cadastrado = conn.execute(
        "SELECT id, razao_social FROM clientes WHERE cnpj = ? OR cnpj = ?",
        (cnpj, cnpj_service._somente_digitos(cnpj)),
    ).fetchone()
    resultado["cliente_ja_cadastrado"] = dict(ja_cadastrado) if ja_cadastrado else None
    return jsonify(resultado)


@bp.get("/clientes")
@requires_permission("comercial", "visualizar")
def listar_clientes():
    conn = get_db()
    # Fase 129 — `busca` opcional, usada pela lupa de pesquisa global (o
    # índice de menu não sabe nada sobre dado real — nome de cliente,
    # CNPJ etc. — então a busca por um cliente específico precisa vir
    # daqui, não do índice estático de telas). Sem `busca`, comportamento
    # idêntico a antes (lista tudo).
    termo_busca = (request.args.get("busca") or "").strip()
    if termo_busca:
        termo_like = f"%{termo_busca}%"
        rows = conn.execute(
            """
            SELECT c.*, tp.nome AS tabela_preco_nome FROM clientes c
            LEFT JOIN tabelas_preco tp ON tp.id = c.tabela_preco_id
            WHERE c.razao_social LIKE ? OR c.nome_fantasia LIKE ? OR c.cnpj LIKE ?
            ORDER BY c.razao_social LIMIT 8
            """,
            (termo_like, termo_like, termo_like),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    rows = conn.execute(
        """
        SELECT c.*, tp.nome AS tabela_preco_nome FROM clientes c
        LEFT JOIN tabelas_preco tp ON tp.id = c.tabela_preco_id
        ORDER BY c.razao_social
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/clientes/<int:cliente_id>")
@requires_permission("comercial", "visualizar")
def obter_cliente(cliente_id):
    conn = get_db()
    return jsonify(_cliente_ou_404(conn, cliente_id))


@bp.get("/clientes/<int:cliente_id>/tabela-preco")
@requires_permission("comercial", "visualizar")
def tabela_preco_do_cliente(cliente_id):
    """Fase 99 — usado pela tela de novo pedido para pré-preencher o preço
    assim que o cliente e o item são escolhidos: devolve todo o conteúdo
    da tabela de preço do cliente de uma vez (em vez de uma chamada por
    item), já que a busca de item é feita em memória no frontend."""
    conn = get_db()
    cliente = _cliente_ou_404(conn, cliente_id)
    if not cliente["tabela_preco_id"]:
        return jsonify({"tabela_preco_id": None, "tabela_preco_nome": None, "itens": []})
    tabela = conn.execute("SELECT nome FROM tabelas_preco WHERE id = ?", (cliente["tabela_preco_id"],)).fetchone()
    itens = conn.execute(
        "SELECT item_id, preco FROM tabelas_preco_itens WHERE tabela_preco_id = ?",
        (cliente["tabela_preco_id"],),
    ).fetchall()
    return jsonify({
        "tabela_preco_id": cliente["tabela_preco_id"],
        "tabela_preco_nome": tabela["nome"] if tabela else None,
        "itens": [dict(i) for i in itens],
    })


@bp.get("/clientes/<int:cliente_id>/desempenho")
@requires_permission("comercial", "visualizar")
def desempenho_cliente(cliente_id):
    """Fase 64 — reaproveita a mesma permissão de LEITURA já usada para
    listar/ver clientes (`comercial.visualizar`), em vez de criar uma
    permissão nova: é agregação de dados que quem já vê Comercial também
    pode ver, mesmo raciocínio do Painel Gerencial (Fase 7) e do
    Desempenho de Fornecedor (Fase 62)."""
    conn = get_db()
    _cliente_ou_404(conn, cliente_id)
    return jsonify(_desempenho_cliente(conn, cliente_id))


@bp.post("/clientes")
@requires_permission("comercial", "cadastrar_cliente")
def criar_cliente():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    razao_social = (dados.get("razao_social") or "").strip()
    cnpj = (dados.get("cnpj") or "").strip()
    conn = get_db()

    if not razao_social or not cnpj:
        raise ApiError("Informe razao_social e cnpj.", status=400)
    if conn.execute("SELECT id FROM clientes WHERE cnpj = ?", (cnpj,)).fetchone():
        raise ApiError("Já existe um cliente com este CNPJ.", status=409)

    # Fase 101 — os campos fiscais/endereço (mesmos de CAMPOS_FISCAIS_
    # CLIENTE_EDITAVEIS, já usados na edição desde a Fase 70) e o e-mail
    # agora também podem vir preenchidos já na CRIAÇÃO — normalmente a
    # partir da consulta de CNPJ (`GET /clientes/consultar-cnpj/<cnpj>`),
    # mas continuam 100% opcionais: um cadastro manual sem consultar nada
    # funciona exatamente como antes desta fase.
    valores_fiscais = [dados.get(campo) for campo in CAMPOS_FISCAIS_CLIENTE_EDITAVEIS]
    metodo_pagamento_padrao_id = dados.get("metodo_pagamento_padrao_id")
    condicao_pagamento_padrao_id = dados.get("condicao_pagamento_padrao_id")

    cur = conn.execute(
        f"""
        INSERT INTO clientes (razao_social, nome_fantasia, cnpj, endereco, email, criado_por,
               metodo_pagamento_padrao_id, condicao_pagamento_padrao_id,
               {', '.join(CAMPOS_FISCAIS_CLIENTE_EDITAVEIS)})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, {', '.join('?' for _ in CAMPOS_FISCAIS_CLIENTE_EDITAVEIS)})
        """,
        (razao_social, dados.get("nome_fantasia"), cnpj, dados.get("endereco"), dados.get("email"),
         usuario_atual["id"], metodo_pagamento_padrao_id, condicao_pagamento_padrao_id, *valores_fiscais),
    )
    cliente_id = cur.lastrowid
    audit.registrar(conn, tabela="clientes", registro_id=cliente_id, usuario_id=usuario_atual["id"],
                     acao="cliente_criado", valor_novo={"razao_social": razao_social, "cnpj": cnpj},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_cliente_ou_404(conn, cliente_id)), 201


@bp.put("/clientes/<int:cliente_id>")
@requires_permission("comercial", "cadastrar_cliente")
def editar_cliente(cliente_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = _cliente_ou_404(conn, cliente_id)
    nome_fantasia = dados.get("nome_fantasia", anterior["nome_fantasia"])
    endereco = dados.get("endereco", anterior["endereco"])
    email = dados.get("email", anterior["email"])
    status = dados.get("status", anterior["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    # Fase 99 — tabela de preço é OPCIONAL (null = sem tabela, preço 100%
    # manual como sempre foi); só valida que a tabela informada existe.
    tabela_preco_id = dados.get("tabela_preco_id", anterior["tabela_preco_id"])
    if tabela_preco_id is not None:
        if not conn.execute("SELECT 1 FROM tabelas_preco WHERE id = ?", (tabela_preco_id,)).fetchone():
            raise ApiError("Tabela de preço não encontrada.", status=404)

    # Fase 127 — método/condição de pagamento PADRÃO do cliente, ambos
    # opcionais (null = sem padrão definido, escolhe-se na hora de cada
    # pedido); só valida que o id informado existe e está ativo.
    metodo_pagamento_padrao_id = dados.get("metodo_pagamento_padrao_id", anterior["metodo_pagamento_padrao_id"])
    if metodo_pagamento_padrao_id is not None:
        if not conn.execute("SELECT 1 FROM metodos_pagamento WHERE id = ? AND ativo = 1", (metodo_pagamento_padrao_id,)).fetchone():
            raise ApiError("Método de pagamento não encontrado ou inativo.", status=404)
    condicao_pagamento_padrao_id = dados.get("condicao_pagamento_padrao_id", anterior["condicao_pagamento_padrao_id"])
    if condicao_pagamento_padrao_id is not None:
        if not conn.execute("SELECT 1 FROM condicoes_pagamento WHERE id = ? AND ativo = 1", (condicao_pagamento_padrao_id,)).fetchone():
            raise ApiError("Condição de pagamento não encontrada ou inativa.", status=404)

    # Fase 63 — limite_credito é sempre OPCIONAL: `None`/omitido significa
    # "sem limite configurado" (nenhuma confirmação de pedido deste
    # cliente nunca fica pendente por conta de crédito), mesmo raciocínio
    # de `fornecedores.lead_time_dias` desde a Fase 57. Envie
    # limite_credito: null para limpar um valor já configurado.
    limite_credito = dados.get("limite_credito", anterior["limite_credito"])
    if limite_credito is not None:
        try:
            limite_credito = float(limite_credito)
        except (TypeError, ValueError):
            raise ApiError("limite_credito deve ser numérico (ou null para remover o limite).", status=400)
        if limite_credito < 0:
            raise ApiError("limite_credito não pode ser negativo.", status=400)

    # Fase 70 — dados fiscais do cliente (destinatário da NF-e), nenhum
    # obrigatório para o cadastro em si — só na hora de tentar emitir uma
    # nota (validado em app/nfe_service.py::validar_pronto_para_emitir).
    # Convenção: inscricao_estadual = "ISENTO" para cliente não contribuinte
    # de ICMS (pessoa física ou empresa isenta), em vez de deixar em branco
    # — é isso que decide o indicador_inscricao_estadual_destinatario no
    # payload enviado ao provedor.
    valores_fiscais = {campo: dados.get(campo, anterior.get(campo)) for campo in CAMPOS_FISCAIS_CLIENTE_EDITAVEIS}

    conn.execute(
        f"""
        UPDATE clientes SET nome_fantasia = ?, endereco = ?, email = ?, status = ?, limite_credito = ?, tabela_preco_id = ?,
               metodo_pagamento_padrao_id = ?, condicao_pagamento_padrao_id = ?,
               {', '.join(f'{c} = ?' for c in CAMPOS_FISCAIS_CLIENTE_EDITAVEIS)}
        WHERE id = ?
        """,
        (nome_fantasia, endereco, email, status, limite_credito, tabela_preco_id,
         metodo_pagamento_padrao_id, condicao_pagamento_padrao_id,
         *[valores_fiscais[c] for c in CAMPOS_FISCAIS_CLIENTE_EDITAVEIS], cliente_id),
    )
    novo = _cliente_ou_404(conn, cliente_id)
    audit.registrar(conn, tabela="clientes", registro_id=cliente_id, usuario_id=usuario_atual["id"],
                     acao="cliente_editado", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


# ============================================================
# MÉTODOS E CONDIÇÕES DE PAGAMENTO (Fase 127/128)
# ============================================================
# Restrição por cliente (Fase 127): sem nenhum cliente vinculado =
# disponível pra QUALQUER cliente (comportamento padrão); assim que
# algum cliente é vinculado, só fica disponível pra quem está na lista.
# Isso é independente de tabela de preço — a combinação método+prazo
# ESPECÍFICA de cada tabela (ex.: "na tabela Terceirização, Boleto tem
# 7/14/28 ou 28/42/56") é outra coisa, resolvida por `tabela_preco_
# condicoes` (Fase 128) e usada na hora de montar/faturar um pedido, não
# aqui na listagem geral do catálogo.
def _decorar_clientes_vinculados(conn, tabela_link, campo_fk, registro_id):
    rows = conn.execute(
        f"""
        SELECT c.id, c.razao_social FROM {tabela_link} l
        JOIN clientes c ON c.id = l.cliente_id
        WHERE l.{campo_fk} = ? ORDER BY c.razao_social
        """,
        (registro_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _disponivel_para_cliente_sql(tabela, alias, cliente_alias="c"):
    """Fragmento SQL reaproveitado nas listagens filtradas por cliente —
    ver a regra de restrição documentada acima."""
    tabela_link = "metodos_pagamento_clientes" if tabela == "metodos_pagamento" else "condicoes_pagamento_clientes"
    campo_fk = "metodo_pagamento_id" if tabela == "metodos_pagamento" else "condicao_pagamento_id"
    return f"""(
        NOT EXISTS (SELECT 1 FROM {tabela_link} WHERE {campo_fk} = {alias}.id)
    ) OR EXISTS (
        SELECT 1 FROM {tabela_link} WHERE {campo_fk} = {alias}.id AND cliente_id = {cliente_alias}.id
    )"""


@bp.get("/metodos-pagamento")
@requires_permission("comercial", "visualizar")
def listar_metodos_pagamento():
    conn = get_db()
    apenas_ativos = request.args.get("ativos") == "1"
    cliente_id = request.args.get("cliente_id", type=int)
    apenas_app_vendas = request.args.get("app_vendas") == "1"
    clausulas = []
    if apenas_ativos:
        clausulas.append("m.ativo = 1")
    if apenas_app_vendas:
        clausulas.append("m.visivel_app_vendas = 1")
    params = []
    if cliente_id:
        clausulas.append(f"({_disponivel_para_cliente_sql('metodos_pagamento', 'm')})")
        params.append(cliente_id)
    where = f"JOIN clientes c ON c.id = ? " if cliente_id else ""
    where_final = ("WHERE " + " AND ".join(clausulas)) if clausulas else ""
    rows = conn.execute(f"SELECT m.* FROM metodos_pagamento m {where} {where_final} ORDER BY m.nome", params).fetchall()
    resultado = []
    for r in rows:
        item = dict(r)
        item["clientes_vinculados"] = _decorar_clientes_vinculados(conn, "metodos_pagamento_clientes", "metodo_pagamento_id", item["id"])
        resultado.append(item)
    return jsonify(resultado)


@bp.post("/metodos-pagamento")
@requires_permission("comercial", "configurar_pagamento")
def criar_metodo_pagamento():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ApiError("Informe nome.", status=400)
    conn = get_db()
    if conn.execute("SELECT id FROM metodos_pagamento WHERE nome = ?", (nome,)).fetchone():
        raise ApiError("Já existe um método de pagamento com este nome.", status=409)
    visivel_app_vendas = 1 if dados.get("visivel_app_vendas", True) else 0
    cur = conn.execute(
        "INSERT INTO metodos_pagamento (nome, visivel_app_vendas, criado_por) VALUES (?, ?, ?)",
        (nome, visivel_app_vendas, usuario_atual["id"]),
    )
    metodo_id = cur.lastrowid
    for cliente_id in (dados.get("cliente_ids") or []):
        conn.execute("INSERT OR IGNORE INTO metodos_pagamento_clientes (metodo_pagamento_id, cliente_id) VALUES (?, ?)", (metodo_id, cliente_id))
    audit.registrar(conn, tabela="metodos_pagamento", registro_id=metodo_id, usuario_id=usuario_atual["id"],
                     acao="metodo_pagamento_criado", valor_novo={"nome": nome},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(conn.execute("SELECT * FROM metodos_pagamento WHERE id = ?", (metodo_id,)).fetchone())), 201


@bp.put("/metodos-pagamento/<int:metodo_id>")
@requires_permission("comercial", "configurar_pagamento")
def editar_metodo_pagamento(metodo_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = conn.execute("SELECT * FROM metodos_pagamento WHERE id = ?", (metodo_id,)).fetchone()
    if anterior is None:
        raise ApiError("Método de pagamento não encontrado.", status=404)
    nome = (dados.get("nome") or anterior["nome"]).strip()
    ativo = 1 if dados.get("ativo", anterior["ativo"]) else 0
    visivel_app_vendas = 1 if dados.get("visivel_app_vendas", anterior["visivel_app_vendas"]) else 0
    if conn.execute("SELECT id FROM metodos_pagamento WHERE nome = ? AND id != ?", (nome, metodo_id)).fetchone():
        raise ApiError("Já existe um método de pagamento com este nome.", status=409)
    conn.execute(
        "UPDATE metodos_pagamento SET nome = ?, ativo = ?, visivel_app_vendas = ? WHERE id = ?",
        (nome, ativo, visivel_app_vendas, metodo_id),
    )
    if "cliente_ids" in dados:
        conn.execute("DELETE FROM metodos_pagamento_clientes WHERE metodo_pagamento_id = ?", (metodo_id,))
        for cliente_id in (dados.get("cliente_ids") or []):
            conn.execute("INSERT OR IGNORE INTO metodos_pagamento_clientes (metodo_pagamento_id, cliente_id) VALUES (?, ?)", (metodo_id, cliente_id))
    novo = dict(conn.execute("SELECT * FROM metodos_pagamento WHERE id = ?", (metodo_id,)).fetchone())
    audit.registrar(conn, tabela="metodos_pagamento", registro_id=metodo_id, usuario_id=usuario_atual["id"],
                     acao="metodo_pagamento_editado", valor_anterior=dict(anterior), valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.get("/condicoes-pagamento")
@requires_permission("comercial", "visualizar")
def listar_condicoes_pagamento():
    conn = get_db()
    apenas_ativos = request.args.get("ativos") == "1"
    cliente_id = request.args.get("cliente_id", type=int)
    apenas_app_vendas = request.args.get("app_vendas") == "1"
    clausulas = []
    if apenas_ativos:
        clausulas.append("m.ativo = 1")
    if apenas_app_vendas:
        clausulas.append("m.visivel_app_vendas = 1")
    params = []
    if cliente_id:
        clausulas.append(f"({_disponivel_para_cliente_sql('condicoes_pagamento', 'm')})")
        params.append(cliente_id)
    where = f"JOIN clientes c ON c.id = ? " if cliente_id else ""
    where_final = ("WHERE " + " AND ".join(clausulas)) if clausulas else ""
    rows = conn.execute(f"SELECT m.* FROM condicoes_pagamento m {where} {where_final} ORDER BY m.nome", params).fetchall()
    resultado = []
    for r in rows:
        item = dict(r)
        item["clientes_vinculados"] = _decorar_clientes_vinculados(conn, "condicoes_pagamento_clientes", "condicao_pagamento_id", item["id"])
        resultado.append(item)
    return jsonify(resultado)


@bp.post("/condicoes-pagamento")
@requires_permission("comercial", "configurar_pagamento")
def criar_condicao_pagamento():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ApiError("Informe nome.", status=400)
    try:
        numero_parcelas = int(dados.get("numero_parcelas") or 1)
    except (TypeError, ValueError):
        raise ApiError("numero_parcelas deve ser um número inteiro.", status=400)
    if numero_parcelas < 1:
        raise ApiError("numero_parcelas deve ser pelo menos 1.", status=400)
    dias_entre_parcelas = dados.get("dias_entre_parcelas")
    conn = get_db()
    if conn.execute("SELECT id FROM condicoes_pagamento WHERE nome = ?", (nome,)).fetchone():
        raise ApiError("Já existe uma condição de pagamento com este nome.", status=409)
    visivel_app_vendas = 1 if dados.get("visivel_app_vendas", True) else 0
    cur = conn.execute(
        "INSERT INTO condicoes_pagamento (nome, numero_parcelas, dias_entre_parcelas, visivel_app_vendas, criado_por) VALUES (?, ?, ?, ?, ?)",
        (nome, numero_parcelas, dias_entre_parcelas, visivel_app_vendas, usuario_atual["id"]),
    )
    condicao_id = cur.lastrowid
    for cliente_id in (dados.get("cliente_ids") or []):
        conn.execute("INSERT OR IGNORE INTO condicoes_pagamento_clientes (condicao_pagamento_id, cliente_id) VALUES (?, ?)", (condicao_id, cliente_id))
    audit.registrar(conn, tabela="condicoes_pagamento", registro_id=condicao_id, usuario_id=usuario_atual["id"],
                     acao="condicao_pagamento_criada", valor_novo={"nome": nome, "numero_parcelas": numero_parcelas},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(conn.execute("SELECT * FROM condicoes_pagamento WHERE id = ?", (condicao_id,)).fetchone())), 201


@bp.put("/condicoes-pagamento/<int:condicao_id>")
@requires_permission("comercial", "configurar_pagamento")
def editar_condicao_pagamento(condicao_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = conn.execute("SELECT * FROM condicoes_pagamento WHERE id = ?", (condicao_id,)).fetchone()
    if anterior is None:
        raise ApiError("Condição de pagamento não encontrada.", status=404)
    nome = (dados.get("nome") or anterior["nome"]).strip()
    numero_parcelas = dados.get("numero_parcelas", anterior["numero_parcelas"])
    try:
        numero_parcelas = int(numero_parcelas)
    except (TypeError, ValueError):
        raise ApiError("numero_parcelas deve ser um número inteiro.", status=400)
    if numero_parcelas < 1:
        raise ApiError("numero_parcelas deve ser pelo menos 1.", status=400)
    dias_entre_parcelas = dados.get("dias_entre_parcelas", anterior["dias_entre_parcelas"])
    ativo = 1 if dados.get("ativo", anterior["ativo"]) else 0
    visivel_app_vendas = 1 if dados.get("visivel_app_vendas", anterior["visivel_app_vendas"]) else 0
    if conn.execute("SELECT id FROM condicoes_pagamento WHERE nome = ? AND id != ?", (nome, condicao_id)).fetchone():
        raise ApiError("Já existe uma condição de pagamento com este nome.", status=409)
    conn.execute(
        "UPDATE condicoes_pagamento SET nome = ?, numero_parcelas = ?, dias_entre_parcelas = ?, ativo = ?, "
        "visivel_app_vendas = ? WHERE id = ?",
        (nome, numero_parcelas, dias_entre_parcelas, ativo, visivel_app_vendas, condicao_id),
    )
    if "cliente_ids" in dados:
        conn.execute("DELETE FROM condicoes_pagamento_clientes WHERE condicao_pagamento_id = ?", (condicao_id,))
        for cliente_id in (dados.get("cliente_ids") or []):
            conn.execute("INSERT OR IGNORE INTO condicoes_pagamento_clientes (condicao_pagamento_id, cliente_id) VALUES (?, ?)", (condicao_id, cliente_id))
    novo = dict(conn.execute("SELECT * FROM condicoes_pagamento WHERE id = ?", (condicao_id,)).fetchone())
    audit.registrar(conn, tabela="condicoes_pagamento", registro_id=condicao_id, usuario_id=usuario_atual["id"],
                     acao="condicao_pagamento_editada", valor_anterior=dict(anterior), valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.post("/clientes/<int:cliente_id>/aprovar-financeiramente")
@requires_permission("comercial", "aprovar_pedido_acima_limite_credito")
def aprovar_cliente_financeiramente(cliente_id):
    """Fase 102 — mesma permissão de quem já aprova pedido acima do limite
    de crédito (Financeiro): é a mesma responsabilidade de avaliar o
    risco de vender para aquele cliente, só que feita uma vez, no
    cadastro, em vez de pedido a pedido."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = _cliente_ou_404(conn, cliente_id)

    conn.execute(
        "UPDATE clientes SET aprovacao_financeira_status = 'aprovado', aprovacao_financeira_decidido_por = ?, "
        "aprovacao_financeira_decidido_em = ?, aprovacao_financeira_motivo = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), dados.get("observacao"), cliente_id),
    )
    novo = _cliente_ou_404(conn, cliente_id)
    audit.registrar(conn, tabela="clientes", registro_id=cliente_id, usuario_id=usuario_atual["id"],
                     acao="cliente_aprovado_financeiramente", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.post("/clientes/<int:cliente_id>/reprovar-financeiramente")
@requires_permission("comercial", "aprovar_pedido_acima_limite_credito")
def reprovar_cliente_financeiramente(cliente_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    if not motivo:
        raise ApiError("Informe o motivo da reprovação.", status=400)
    conn = get_db()
    anterior = _cliente_ou_404(conn, cliente_id)

    conn.execute(
        "UPDATE clientes SET aprovacao_financeira_status = 'reprovado', aprovacao_financeira_decidido_por = ?, "
        "aprovacao_financeira_decidido_em = ?, aprovacao_financeira_motivo = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), motivo, cliente_id),
    )
    novo = _cliente_ou_404(conn, cliente_id)
    audit.registrar(conn, tabela="clientes", registro_id=cliente_id, usuario_id=usuario_atual["id"],
                     acao="cliente_reprovado_financeiramente", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


# ============================================================
# PEDIDOS DE VENDA
# ============================================================
@bp.get("/pedidos")
@requires_permission("comercial", "visualizar")
def listar_pedidos():
    conn = get_db()
    status = request.args.get("status")
    cliente_id = request.args.get("cliente_id", type=int)
    # Fase 131 — tela própria de Pedidos de Venda, com filtros que a
    # mini-tabela dentro de Comercial nunca teve: tipo (terceirização/
    # marca própria) e "faturado" (existe NF-e AUTORIZADA vinculada —
    # 'sim'/'nao', qualquer outro valor é ignorado, mesmo raciocínio de
    # nunca quebrar com um parâmetro inesperado).
    tipo_pedido = request.args.get("tipo_pedido")
    faturado = request.args.get("faturado")
    # Pedido do usuário (2026-09-01) — filtro por período, além dos que já
    # existiam: compara só a DATA de `criado_em` (que é timestamp ISO
    # completo), então "de 01/09 até 01/09" pega o dia inteiro, não só o
    # instante exato.
    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")
    clausulas, params = [], []
    if status:
        clausulas.append("pv.status = ?")
        params.append(status)
    if cliente_id:
        clausulas.append("pv.cliente_id = ?")
        params.append(cliente_id)
    if tipo_pedido:
        clausulas.append("pv.tipo_pedido = ?")
        params.append(tipo_pedido)
    if faturado in ("sim", "nao"):
        existe_nfe_autorizada = "EXISTS (SELECT 1 FROM notas_fiscais nf WHERE nf.pedido_id = pv.id AND nf.status = 'autorizada')"
        clausulas.append(existe_nfe_autorizada if faturado == "sim" else f"NOT {existe_nfe_autorizada}")
    if data_de:
        clausulas.append("DATE(pv.criado_em) >= DATE(?)")
        params.append(data_de)
    if data_ate:
        clausulas.append("DATE(pv.criado_em) <= DATE(?)")
        params.append(data_ate)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT pv.*, c.razao_social AS cliente_razao_social,
               (SELECT COALESCE(SUM(quantidade * preco_unitario), 0) FROM pedido_venda_itens WHERE pedido_id = pv.id) AS valor_total,
               EXISTS (SELECT 1 FROM notas_fiscais nf WHERE nf.pedido_id = pv.id AND nf.status = 'autorizada') AS faturado
        FROM pedidos_venda pv JOIN clientes c ON c.id = pv.cliente_id
        {where} ORDER BY pv.id DESC
        """,
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/pedidos/<int:pedido_id>")
@requires_permission("comercial", "visualizar")
def obter_pedido(pedido_id):
    conn = get_db()
    return jsonify(_pedido_detalhado(conn, pedido_id))


@bp.post("/pedidos")
@requires_permission("comercial", "criar_pedido")
def criar_pedido():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    cliente_id = dados.get("cliente_id")
    itens = dados.get("itens") or []
    # Fase 52 — opcional, sem valor padrão (ver schema_fase52.sql): quando
    # informado, é o que permite este pedido entrar no filtro por empresa
    # do Painel Gerencial (bloco Comercial) — e a conta a receber gerada
    # automaticamente na expedição (ver `expedir()` abaixo) herda esta
    # MESMA empresa, sem precisar informar de novo.
    empresa_id = dados.get("empresa_id")
    # Fase 127 — opcional; quando não informado, herda o padrão do
    # próprio cliente (se ele tiver um configurado) — mesma ideia de
    # `tabela_preco_id` já herdado no lançamento de pedido pelo App de
    # Vendas, só que aqui é explícito no corpo da resposta pro operador
    # ver o que foi assumido.
    condicao_pagamento_id = dados.get("condicao_pagamento_id")
    # Fase 131 — opcional: terceirização (fabricação sob encomenda) ou
    # marca própria (produto com a marca do próprio cliente). Sem
    # obrigar no cadastro — pedido antigo/importado sem essa informação
    # continua existindo normalmente, só não aparece nos filtros por tipo.
    tipo_pedido = dados.get("tipo_pedido")
    if tipo_pedido is not None and tipo_pedido not in ("terceirizacao", "marca_propria"):
        raise ApiError("tipo_pedido deve ser 'terceirizacao' ou 'marca_propria' (ou omitido).", status=400)
    conn = get_db()

    if not cliente_id:
        raise ApiError("Informe cliente_id.", status=400)
    if empresa_id is not None:
        _empresa_ou_404(conn, empresa_id)
    cliente = _cliente_ou_404(conn, cliente_id)
    if cliente["status"] != "ativo":
        raise ApiError("Não é possível criar pedido para um cliente inativo.", status=400)
    if not itens:
        raise ApiError("Informe ao menos um item em 'itens'.", status=400)
    if condicao_pagamento_id is None:
        condicao_pagamento_id = cliente["condicao_pagamento_padrao_id"]
    if condicao_pagamento_id is not None:
        if not conn.execute("SELECT 1 FROM condicoes_pagamento WHERE id = ? AND ativo = 1", (condicao_pagamento_id,)).fetchone():
            raise ApiError("Condição de pagamento não encontrada ou inativa.", status=404)

    numero = _gerar_numero_pedido()
    cur = conn.execute(
        "INSERT INTO pedidos_venda (numero, cliente_id, empresa_id, condicao_pagamento_id, tipo_pedido, criado_por) VALUES (?, ?, ?, ?, ?, ?)",
        (numero, cliente_id, empresa_id, condicao_pagamento_id, tipo_pedido, usuario_atual["id"]),
    )
    pedido_id = cur.lastrowid

    for linha in itens:
        item_id = linha.get("item_id")
        quantidade = linha.get("quantidade")
        unidade = linha.get("unidade")
        preco_unitario = linha.get("preco_unitario")
        if not item_id or not quantidade or not unidade or preco_unitario is None:
            raise ApiError("Cada item precisa de item_id, quantidade, unidade e preco_unitario.", status=400)
        try:
            quantidade = float(quantidade)
            preco_unitario = float(preco_unitario)
        except (TypeError, ValueError):
            raise ApiError("quantidade e preco_unitario devem ser numéricos.", status=400)
        if quantidade <= 0:
            raise ApiError("quantidade deve ser maior que zero.", status=400)
        if preco_unitario <= 0:
            raise ApiError("preco_unitario deve ser maior que zero.", status=400)
        _validar_item_vendavel(conn, item_id)
        conn.execute(
            "INSERT INTO pedido_venda_itens (pedido_id, item_id, quantidade, unidade, preco_unitario) VALUES (?, ?, ?, ?, ?)",
            (pedido_id, item_id, quantidade, unidade, preco_unitario),
        )

    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_criado", valor_novo={"numero": numero, "cliente_id": cliente_id, "itens": itens},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pedido_id)), 201


@bp.put("/pedidos/<int:pedido_id>/tipo")
@requires_permission("comercial", "criar_pedido")
def definir_tipo_pedido(pedido_id):
    """Fase 131 — classificar (ou reclassificar) terceirização/marca
    própria em QUALQUER status do pedido, inclusive já cancelado/expedido
    — é só uma etiqueta de classificação, não uma transição de fluxo, não
    faz sentido travar isso ao status do pedido."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    tipo_pedido = dados.get("tipo_pedido")
    if tipo_pedido not in ("terceirizacao", "marca_propria", None):
        raise ApiError("tipo_pedido deve ser 'terceirizacao', 'marca_propria' ou null (limpar).", status=400)
    conn = get_db()
    anterior = _pedido_ou_404(conn, pedido_id)
    conn.execute("UPDATE pedidos_venda SET tipo_pedido = ? WHERE id = ?", (tipo_pedido, pedido_id))
    novo = _pedido_ou_404(conn, pedido_id)
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_tipo_definido", valor_anterior={"tipo_pedido": anterior.get("tipo_pedido")},
                     valor_novo={"tipo_pedido": tipo_pedido}, ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.post("/pedidos/<int:pedido_id>/duplicar")
@requires_permission("comercial", "criar_pedido")
def duplicar_pedido(pedido_id):
    """Fase 77 — "usar como modelo": cria um pedido NOVO, em 'rascunho', com
    o mesmo cliente/empresa e os mesmos itens (quantidade e preço) do pedido
    de origem — qualquer status de origem serve (rascunho, confirmado,
    expedido ou até cancelado), já que o objetivo é só reaproveitar a
    COMPOSIÇÃO do pedido como ponto de partida, não o pedido em si. Itens
    que hoje não passam mais em `_validar_item_vendavel` (ex.: foram
    inativados desde então) são pulados em vez de travar a duplicação
    inteira — o vendedor vê no retorno quais ficaram de fora."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    origem = _pedido_ou_404(conn, pedido_id)
    itens_origem = conn.execute(
        "SELECT item_id, quantidade, unidade, preco_unitario FROM pedido_venda_itens WHERE pedido_id = ? ORDER BY id",
        (pedido_id,),
    ).fetchall()
    if not itens_origem:
        raise ApiError("Este pedido não tem itens para duplicar.", status=400)

    cliente = _cliente_ou_404(conn, origem["cliente_id"])
    if cliente["status"] != "ativo":
        raise ApiError("Não é possível duplicar: o cliente deste pedido está inativo.", status=400)

    numero = _gerar_numero_pedido()
    cur = conn.execute(
        "INSERT INTO pedidos_venda (numero, cliente_id, empresa_id, criado_por) VALUES (?, ?, ?, ?)",
        (numero, origem["cliente_id"], origem["empresa_id"], usuario_atual["id"]),
    )
    novo_pedido_id = cur.lastrowid

    itens_incluidos = []
    itens_pulados = []
    for linha in itens_origem:
        item_id, quantidade, unidade, preco_unitario = linha["item_id"], linha["quantidade"], linha["unidade"], linha["preco_unitario"]
        try:
            _validar_item_vendavel(conn, item_id)
        except ApiError as erro:
            itens_pulados.append({"item_id": item_id, "motivo": erro.mensagem})
            continue
        conn.execute(
            "INSERT INTO pedido_venda_itens (pedido_id, item_id, quantidade, unidade, preco_unitario) VALUES (?, ?, ?, ?, ?)",
            (novo_pedido_id, item_id, quantidade, unidade, preco_unitario),
        )
        itens_incluidos.append(item_id)

    audit.registrar(conn, tabela="pedidos_venda", registro_id=novo_pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_duplicado_de_outro_pedido",
                     valor_novo={"numero": numero, "pedido_origem_id": pedido_id, "itens_incluidos": itens_incluidos, "itens_pulados": itens_pulados},
                     ip=client_ip(), dispositivo=client_device())

    pedido = _pedido_detalhado(conn, novo_pedido_id)
    pedido["itens_pulados_da_duplicacao"] = itens_pulados
    return jsonify(pedido), 201


@bp.post("/pedidos/<int:pedido_id>/itens")
@requires_permission("comercial", "criar_pedido")
def adicionar_item(pedido_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    item_id = dados.get("item_id")
    quantidade = dados.get("quantidade")
    unidade = dados.get("unidade")
    preco_unitario = dados.get("preco_unitario")
    conn = get_db()

    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] not in STATUS_QUE_PERMITEM_EDITAR_ITENS:
        raise ApiError(
            f"Só é possível adicionar itens a um pedido 'rascunho' (status atual: '{pedido['status']}').", status=400,
        )
    if not item_id or not quantidade or not unidade or preco_unitario is None:
        raise ApiError("Informe item_id, quantidade, unidade e preco_unitario.", status=400)
    try:
        quantidade = float(quantidade)
        preco_unitario = float(preco_unitario)
    except (TypeError, ValueError):
        raise ApiError("quantidade e preco_unitario devem ser numéricos.", status=400)
    if quantidade <= 0:
        raise ApiError("quantidade deve ser maior que zero.", status=400)
    if preco_unitario <= 0:
        raise ApiError("preco_unitario deve ser maior que zero.", status=400)
    _validar_item_vendavel(conn, item_id)

    cur = conn.execute(
        "INSERT INTO pedido_venda_itens (pedido_id, item_id, quantidade, unidade, preco_unitario) VALUES (?, ?, ?, ?, ?)",
        (pedido_id, item_id, quantidade, unidade, preco_unitario),
    )
    audit.registrar(conn, tabela="pedido_venda_itens", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="item_pedido_adicionado",
                     valor_novo={"pedido_id": pedido_id, "item_id": item_id, "quantidade": quantidade, "preco_unitario": preco_unitario},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pedido_id)), 201


@bp.delete("/pedidos/<int:pedido_id>/itens/<int:item_linha_id>")
@requires_permission("comercial", "criar_pedido")
def remover_item(pedido_id, item_linha_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] not in STATUS_QUE_PERMITEM_EDITAR_ITENS:
        raise ApiError(
            f"Só é possível remover itens de um pedido 'rascunho' (status atual: '{pedido['status']}').", status=400,
        )
    linha = conn.execute(
        "SELECT * FROM pedido_venda_itens WHERE id = ? AND pedido_id = ?", (item_linha_id, pedido_id)
    ).fetchone()
    if linha is None:
        raise ApiError("Item do pedido não encontrado.", status=404)

    conn.execute("DELETE FROM pedido_venda_itens WHERE id = ?", (item_linha_id,))
    audit.registrar(conn, tabela="pedido_venda_itens", registro_id=item_linha_id, usuario_id=usuario_atual["id"],
                     acao="item_pedido_removido", valor_anterior=dict(linha),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pedido_id))


@bp.get("/pedidos/<int:pedido_id>/pre-checagem-estoque")
@requires_permission("comercial", "visualizar")
def pre_checagem_estoque(pedido_id):
    """Fase 88 — pré-checagem só de leitura de saldo por item do rascunho,
    pensada para o frontend mostrar um aviso NÃO-BLOQUEANTE antes de
    tentar confirmar de verdade. Reaproveita a mesma `_alocar_fefo` que
    `confirmar_pedido_internamente` usa para o gate real (PASSO 1, mais
    abaixo) — que é puramente leitura — sem nunca gravar nenhuma reserva."""
    conn = get_db()
    _pedido_ou_404(conn, pedido_id)
    itens = conn.execute("SELECT * FROM pedido_venda_itens WHERE pedido_id = ?", (pedido_id,)).fetchall()

    reservado_planejado = {}
    resultado_itens = []
    for item in itens:
        item = dict(item)
        alocacoes, coberto = _alocar_fefo(conn, item["item_id"], item["quantidade"], reservado_planejado)
        for alocacao in alocacoes:
            chave = (alocacao["lote_id"], alocacao["posicao_id"])
            reservado_planejado[chave] = reservado_planejado.get(chave, 0) + alocacao["quantidade"]
        item_row = conn.execute("SELECT codigo, descricao FROM itens WHERE id = ?", (item["item_id"],)).fetchone()
        resultado_itens.append({
            "item_id": item["item_id"], "codigo": item_row["codigo"], "descricao": item_row["descricao"],
            "necessario": item["quantidade"], "disponivel": round(coberto, 6),
            "suficiente": coberto + 0.0000001 >= item["quantidade"],
        })
    return jsonify({"itens": resultado_itens, "todos_suficientes": all(i["suficiente"] for i in resultado_itens)})


def confirmar_pedido_internamente(conn, pedido_id, usuario_id):
    """Núcleo da confirmação de um pedido de venda (alocação FEFO +
    mudança de status) — extraído para função própria na Fase 36 para que
    o aplicativo de vendas (app/routes/vendas_app.py) possa reaproveitar
    exatamente esta mesma lógica ao "enviar" um rascunho criado pelo
    próprio vendedor, sem duplicar código nem arriscar a alocação FEFO
    ficar diferente entre os dois pontos de entrada (desktop e app). Não
    faz nenhuma checagem de permissão HTTP — quem chama decide isso."""
    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] != "rascunho":
        raise ApiError(f"Só é possível confirmar um pedido 'rascunho' (status atual: '{pedido['status']}').", status=400)

    itens = conn.execute("SELECT * FROM pedido_venda_itens WHERE pedido_id = ?", (pedido_id,)).fetchall()
    if not itens:
        raise ApiError("Este pedido não tem nenhum item — adicione ao menos um antes de confirmar.", status=400)

    # PASSO 1 — valida e calcula a alocação FEFO de TODOS os itens ANTES de
    # escrever qualquer coisa no banco. Um `raise ApiError` no meio de uma
    # rota NÃO desfaz escritas já feitas (ver nota em app/context.py:
    # close_db) — a única forma segura de garantir tudo-ou-nada aqui é não
    # escrever nada até ter certeza de que o pedido inteiro pode ser
    # atendido. `reservado_planejado` acumula as alocações já decididas
    # nesta mesma passada (mas ainda não persistidas) para que uma segunda
    # linha do mesmo item não possa alocar o mesmo saldo que a primeira
    # linha já tomou para si.
    reservado_planejado = {}
    plano = []
    for item in itens:
        item = dict(item)
        alocacoes, coberto = _alocar_fefo(conn, item["item_id"], item["quantidade"], reservado_planejado)
        if coberto + 0.0000001 < item["quantidade"]:
            item_row = conn.execute("SELECT codigo, descricao FROM itens WHERE id = ?", (item["item_id"],)).fetchone()
            raise ApiError(
                f"Saldo em estoque insuficiente para {item_row['codigo']} — {item_row['descricao']}: "
                f"necessário {item['quantidade']}, disponível apenas {coberto} (já considerando o que outros "
                "pedidos confirmados reservaram e excluindo lotes vencidos, que não contam mais como saldo "
                "disponível — Fase 65). Nenhuma reserva foi feita para este pedido.",
                status=400,
            )
        for alocacao in alocacoes:
            chave = (alocacao["lote_id"], alocacao["posicao_id"])
            reservado_planejado[chave] = reservado_planejado.get(chave, 0) + alocacao["quantidade"]
        plano.append((item, alocacoes))

    # PASSO 2 — tudo cabe: agora sim grava as reservas e confirma o pedido.
    # Fase 73: mesmo com o PASSO 1 dizendo "cabe", outra requisição
    # concorrente pode ter reservado o mesmo lote/posição entre a leitura
    # (PASSO 1) e esta escrita — o trigger `trg_pedido_venda_reservas_
    # bloqueia_saldo_negativo` (schema_fase73.sql) é quem garante, a nível
    # de banco, que isso não gera saldo negativo; se acontecer, vira
    # IntegrityError aqui. Como um `raise ApiError` NÃO desfaz escritas já
    # feitas nesta mesma requisição (close_db faz COMMIT mesmo em erro
    # 4xx/409 — ver o comentário grande em app/context.py:close_db, e
    # pedido_venda_reservas é append-only, então nem dá pra apagar à mão
    # no except), usamos um SAVEPOINT explícito: se o laço falhar no meio,
    # `ROLLBACK TO SAVEPOINT` desfaz só as reservas já inseridas NESTA
    # tentativa antes de levantar o erro, para não deixar reservas "órfãs"
    # penduradas num pedido que continua em rascunho.
    resumo_alocacoes = []
    conn.execute("SAVEPOINT reserva_pedido_venda")
    try:
        for item, alocacoes in plano:
            for alocacao in alocacoes:
                conn.execute(
                    "INSERT INTO pedido_venda_reservas (pedido_item_id, lote_id, posicao_id, quantidade) VALUES (?, ?, ?, ?)",
                    (item["id"], alocacao["lote_id"], alocacao["posicao_id"], alocacao["quantidade"]),
                )
            resumo_alocacoes.append({"pedido_item_id": item["id"], "item_id": item["item_id"], "alocacoes": alocacoes})
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK TO SAVEPOINT reserva_pedido_venda")
        conn.execute("RELEASE SAVEPOINT reserva_pedido_venda")
        raise ApiError(
            "Não foi possível reservar o estoque deste pedido — outra confirmação de pedido concorrente "
            "provavelmente reservou o mesmo lote/posição ao mesmo tempo, e o saldo não é mais suficiente. "
            "Nenhuma reserva foi feita para este pedido. Consulte o saldo disponível e tente confirmar de novo.",
            status=409,
        )
    conn.execute("RELEASE SAVEPOINT reserva_pedido_venda")

    conn.execute(
        "UPDATE pedidos_venda SET status = 'confirmado', confirmado_em = ?, confirmado_por = ? WHERE id = ?",
        (_now_iso(), usuario_id, pedido_id),
    )
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_id,
                     acao="pedido_confirmado", valor_anterior={"status": "rascunho"},
                     valor_novo={"status": "confirmado", "reservas": resumo_alocacoes},
                     ip=client_ip(), dispositivo=client_device())
    return _pedido_detalhado(conn, pedido_id)


def confirmar_pedido_ou_solicitar_aprovacao(conn, pedido_id, usuario_id):
    """Fase 83 — desde a Fase 63, isso só criava uma solicitação pendente
    quando o pedido ultrapassava o limite de crédito do cliente; a pedido
    explícito do usuário, TODA confirmação agora passa por esta fila de
    aprovação financeira antes de reservar estoque de verdade — não é mais
    um desvio raro, é o caminho único. Os números de limite de crédito
    continuam sendo calculados e gravados (ainda são um contexto útil para
    quem aprova), só que `motivo_solicitacao` é quem diz POR QUE a
    aprovação foi pedida: `'acima_do_limite'` quando de fato estourou o
    limite configurado, `'aprovacao_obrigatoria_padrao'` no caso comum
    (dentro do limite, ou cliente sem limite configurado). Nunca use
    `limite_credito_no_momento == 0` para inferir "sem limite" — um
    cliente pode ter um limite configurado que é literalmente zero;
    `limite_credito_no_momento` grava `0` só como preenchimento quando
    `cliente["limite_credito"] IS NULL` (a coluna continua NOT NULL, ver
    a nota de escopo completa em migrations/schema_fase83.sql).

    Chamada tanto pela tela de desktop (`confirmar` abaixo) quanto pelo
    aplicativo de vendas (`enviar_rascunho` em app/routes/vendas_app.py)
    — um só ponto de decisão para os dois pontos de entrada, mesmo
    raciocínio de `confirmar_pedido_internamente` já ser compartilhada
    entre os dois desde a Fase 36.

    Devolve (pedido_detalhado, status_http) — sempre 202 agora (a
    confirmação de verdade só acontece depois de aprovada, via
    `aprovar_confirmacao_pedido` abaixo); o pedido continua em
    'rascunho' até lá."""
    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] != "rascunho":
        raise ApiError(f"Só é possível confirmar um pedido 'rascunho' (status atual: '{pedido['status']}').", status=400)

    cliente = _cliente_ou_404(conn, pedido["cliente_id"])

    # Fase 102 — pedido do usuário: um cliente NOVO só fica apto a comprar
    # depois que o Financeiro liberar o cadastro dele com uma avaliação
    # financeira própria. Isto é DIFERENTE da aprovação por PEDIDO acima
    # (Fase 83) — é uma trava anterior, sobre o CLIENTE em si, feita uma
    # vez só; depois de aprovado o cliente, todo pedido dele continua
    # seguindo o fluxo normal de aprovação por pedido. Cliente que já
    # existia antes desta fase começou 'aprovado' automaticamente (ver
    # schema_fase102.sql) — só cliente cadastrado a partir de agora nasce
    # 'pendente' de verdade.
    if cliente["aprovacao_financeira_status"] != "aprovado":
        raise ApiError(
            f"Este cliente ainda não foi liberado pelo Financeiro para comprar "
            f"(status do cadastro: '{cliente['aprovacao_financeira_status']}'). "
            "Peça para o Financeiro avaliar e aprovar o cadastro do cliente antes de confirmar este pedido.",
            status=400, codigo="cliente_nao_aprovado_financeiramente",
        )

    valor_pedido = _valor_total_pedido_venda(conn, pedido_id)
    saldo_aberto = _saldo_aberto_cliente(conn, pedido["cliente_id"])
    limite = cliente["limite_credito"]
    acima_do_limite = limite is not None and (saldo_aberto + valor_pedido > limite)
    motivo_solicitacao = "acima_do_limite" if acima_do_limite else "aprovacao_obrigatoria_padrao"

    cur = conn.execute(
        """
        INSERT INTO pedidos_venda_confirmacoes_pendentes
            (pedido_venda_id, valor_pedido, saldo_aberto_no_momento, limite_credito_no_momento, motivo_solicitacao, solicitado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (pedido_id, valor_pedido, saldo_aberto, limite if limite is not None else 0, motivo_solicitacao, usuario_id),
    )
    conn.commit()
    audit.registrar(conn, tabela="pedidos_venda_confirmacoes_pendentes", registro_id=cur.lastrowid, usuario_id=usuario_id,
                     acao="pedido_venda_confirmacao_solicitada",
                     valor_novo={"pedido_venda_id": pedido_id, "valor_pedido": valor_pedido,
                                 "saldo_aberto_no_momento": saldo_aberto,
                                 "limite_credito_no_momento": limite, "motivo_solicitacao": motivo_solicitacao},
                     ip=client_ip(), dispositivo=client_device())
    notificacoes_service.notificar_usuarios_com_permissao(
        conn, modulo="comercial", acao="aprovar_pedido_acima_limite_credito",
        tipo="pedido_venda_confirmacao_pendente",
        mensagem=(
            f"O pedido de venda {pedido['numero']} (R$ {valor_pedido:.2f}) aguarda aprovação financeira antes de "
            f"ser confirmado." + (f" Ultrapassa o limite de crédito do cliente {cliente['razao_social']}." if acima_do_limite else "")
        ),
        excluir_usuario_id=usuario_id,
    )
    resultado = _pedido_detalhado(conn, pedido_id)
    resultado["confirmacao_pendente_criada_id"] = cur.lastrowid
    return resultado, 202


def _confirmacao_pendente_ou_erro(conn, pendente_id):
    row = conn.execute("SELECT * FROM pedidos_venda_confirmacoes_pendentes WHERE id = ?", (pendente_id,)).fetchone()
    if row is None:
        raise ApiError("Solicitação de confirmação não encontrada.", status=404)
    row = dict(row)
    if row["status"] != "pendente":
        raise ApiError(f"Esta solicitação de confirmação já está '{row['status']}'.", status=400)
    return row


@bp.post("/pedidos/<int:pedido_id>/confirmar")
@requires_permission("comercial", "confirmar_pedido")
def confirmar(pedido_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    resultado, status_http = confirmar_pedido_ou_solicitar_aprovacao(conn, pedido_id, usuario_atual["id"])
    return jsonify(resultado), status_http


@bp.post("/pedidos/confirmacoes-pendentes/<int:pendente_id>/aprovar")
@requires_permission("comercial", "aprovar_pedido_acima_limite_credito")
def aprovar_confirmacao_pedido(pendente_id):
    """Aprova uma solicitação de confirmação acima do limite de crédito —
    efetivamente confirma o pedido (mesma alocação FEFO de sempre, via
    `confirmar_pedido_internamente` — o saldo físico é revalidado na hora,
    então se o estoque mudou entre a solicitação e a aprovação, a
    confirmação pode falhar normalmente, do mesmo jeito que falharia numa
    confirmação direta). Mesma segregação de função de
    `aprovar_envio_pedido` em app/routes/compras.py: quem solicitou não
    pode aprovar."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    pendente = _confirmacao_pendente_ou_erro(conn, pendente_id)

    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou a confirmação deste pedido e por isso não pode aprová-la — a aprovação precisa ser "
            "feita por outro usuário (segregação de função)."
        )

    # Marca a solicitação como decidida ANTES de confirmar o pedido: assim,
    # quando `confirmar_pedido_internamente` monta o `_pedido_detalhado` de
    # resposta, o campo `confirmacao_pendente` já vem None (a consulta ali
    # só considera status = 'pendente') em vez de ainda mostrar a
    # solicitação que acabou de ser decidida.
    conn.execute(
        "UPDATE pedidos_venda_confirmacoes_pendentes SET status = 'aprovado', decidido_por = ?, decidido_em = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), pendente_id),
    )
    pedido_resultado = confirmar_pedido_internamente(conn, pendente["pedido_venda_id"], usuario_atual["id"])
    conn.commit()
    return jsonify(pedido_resultado)


@bp.post("/pedidos/confirmacoes-pendentes/<int:pendente_id>/rejeitar")
@requires_permission("comercial", "aprovar_pedido_acima_limite_credito")
def rejeitar_confirmacao_pedido(pendente_id):
    """Rejeita a solicitação — o pedido permanece em 'rascunho' (pode ser
    editado/cancelado, ou ter a confirmação solicitada de novo depois).
    Mesmo formato de `rejeitar_envio_pedido` em app/routes/compras.py."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo_rejeicao = (dados.get("motivo") or "").strip()
    conn = get_db()
    pendente = _confirmacao_pendente_ou_erro(conn, pendente_id)

    if not motivo_rejeicao:
        raise ApiError("Informe o motivo da rejeição.", status=400)
    if pendente["solicitado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você solicitou a confirmação deste pedido e por isso não pode decidir sobre ela — a decisão precisa "
            "ser tomada por outro usuário (segregação de função)."
        )

    conn.execute(
        "UPDATE pedidos_venda_confirmacoes_pendentes SET status = 'rejeitado', decidido_por = ?, decidido_em = ?, motivo_rejeicao = ? WHERE id = ?",
        (usuario_atual["id"], _now_iso(), motivo_rejeicao, pendente_id),
    )
    audit.registrar(conn, tabela="pedidos_venda_confirmacoes_pendentes", registro_id=pendente_id, usuario_id=usuario_atual["id"],
                     acao="pedido_venda_confirmacao_rejeitada",
                     valor_novo={"pedido_venda_id": pendente["pedido_venda_id"], "valor_pedido": pendente["valor_pedido"]},
                     motivo=motivo_rejeicao, ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pendente["pedido_venda_id"]))


@bp.post("/pedidos/<int:pedido_id>/expedir")
@requires_permission("comercial", "expedir_pedido")
def expedir(pedido_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] != "confirmado":
        raise ApiError(f"Só é possível expedir um pedido 'confirmado' (status atual: '{pedido['status']}').", status=400)

    reservas = conn.execute(
        """
        SELECT pvr.* FROM pedido_venda_reservas pvr
        JOIN pedido_venda_itens pvi ON pvi.id = pvr.pedido_item_id
        WHERE pvi.pedido_id = ?
        """,
        (pedido_id,),
    ).fetchall()
    if not reservas:
        raise ApiError("Este pedido não tem reservas de estoque — não é possível expedir.", status=400)

    reservas = [dict(r) for r in reservas]

    # Calcula o valor da conta a receber que será gerada — feito aqui, no
    # início, ainda na fase de validação (nenhuma escrita ainda), porque um
    # pedido com valor_total <= 0 (só possível em dados legados de antes da
    # Fase 6, quando pedido_venda_itens não tinha preço) não pode ser
    # expedido sem gerar uma conta a receber válida.
    itens_pedido = conn.execute("SELECT quantidade, preco_unitario FROM pedido_venda_itens WHERE pedido_id = ?", (pedido_id,)).fetchall()
    valor_bruto_pedido = sum(i["quantidade"] * i["preco_unitario"] for i in itens_pedido)
    # Fase 36 — a verba comercial usada (congelada na confirmação, ver
    # app/routes/vendas_app.py) abate o valor faturado — nunca fica
    # negativo mesmo num cenário defensivo (não deveria acontecer, já que
    # é validada contra o saldo disponível do cliente no momento em que é
    # aplicada, mas um pedido antigo de antes desta fase sempre tem
    # verba_utilizada = 0, então este `min()` nunca muda o comportamento
    # de nenhum pedido que já existia).
    verba_utilizada_pedido = min(pedido["verba_utilizada"], valor_bruto_pedido)
    valor_total_conta = valor_bruto_pedido - verba_utilizada_pedido
    if valor_total_conta <= 0.0000001:
        raise ApiError(
            "Este pedido não tem valor (preço unitário) definido em nenhum item, ou a verba usada cobre o "
            "valor inteiro — não é possível expedir sem gerar uma conta a receber válida. Isso só deveria "
            "acontecer em pedidos criados antes da Fase 6; cancele este pedido e crie um novo.",
            status=400,
        )

    # PASSO 1 — agrega as reservas por (lote_id, posicao_id) e valida o
    # saldo físico ATUAL de cada combinação ANTES de escrever qualquer
    # movimentação. Agregar primeiro é necessário porque duas reservas
    # diferentes podem apontar para o mesmo (lote, posição) — validar cada
    # uma isoladamente contra o mesmo saldo (sem descontar a outra)
    # deixaria as duas passarem mesmo que a soma delas exceda o disponível.
    # Também não escrevemos nada aqui: um `raise ApiError` no meio de uma
    # rota não desfaz INSERTs já feitos (ver app/context.py:close_db).
    agregados = {}
    for reserva in reservas:
        chave = (reserva["lote_id"], reserva["posicao_id"])
        agregados[chave] = agregados.get(chave, 0) + reserva["quantidade"]

    for (lote_id, posicao_id), quantidade_total in agregados.items():
        # Revalida o saldo físico na hora de expedir (não só na
        # confirmação): entre confirmar e expedir, alguém pode ter dado
        # baixa ou feito um ajuste negativo direto na tela de Estoque no
        # mesmo lote/posição, o que quebraria a garantia da reserva.
        saldo_atual = _saldo_posicao(conn, lote_id, posicao_id)
        if saldo_atual + 0.0000001 < quantidade_total:
            lote = conn.execute("SELECT codigo_lote FROM lotes WHERE id = ?", (lote_id,)).fetchone()
            posicao = conn.execute("SELECT codigo FROM posicoes_estoque WHERE id = ?", (posicao_id,)).fetchone()
            raise ApiError(
                f"O saldo físico do lote {lote['codigo_lote']} na posição {posicao['codigo']} mudou desde a "
                f"confirmação deste pedido (reservado: {quantidade_total}, disponível agora: {saldo_atual}) "
                "— provavelmente por um ajuste ou baixa feito diretamente na tela de Estoque. Corrija o estoque "
                "antes de expedir, ou cancele este pedido.",
                status=409,
            )

    # PASSO 2 — tudo validado: agora sim grava uma saída por reserva
    # (mantendo granularidade de auditoria igual à das reservas originais)
    # e muda o status do pedido.
    resumo_saidas = []
    for reserva in reservas:
        conn.execute(
            """
            INSERT INTO movimentacoes_estoque (lote_id, posicao_id, tipo, quantidade, motivo, registrado_por)
            VALUES (?, ?, 'saida', ?, ?, ?)
            """,
            (reserva["lote_id"], reserva["posicao_id"], -reserva["quantidade"],
             f"Expedição do pedido de venda {pedido['numero']}", usuario_atual["id"]),
        )
        resumo_saidas.append({"lote_id": reserva["lote_id"], "posicao_id": reserva["posicao_id"], "quantidade": reserva["quantidade"]})

    conn.execute(
        "UPDATE pedidos_venda SET status = 'expedido', expedido_em = ?, expedido_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], pedido_id),
    )
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_expedido", valor_anterior={"status": "confirmado"},
                     valor_novo={"status": "expedido", "saidas": resumo_saidas},
                     ip=client_ip(), dispositivo=client_device())

    # Gera a conta a receber automaticamente — ver nota no topo de
    # schema_fase6.sql sobre por que isso é automático aqui (mas manual do
    # lado de contas a pagar). O valor é congelado a partir do preço de
    # cada item NESTE momento — mudar o preço de um item depois, na tela
    # de Itens, não altera contas já geradas. Fase 52 — a conta HERDA o
    # `empresa_id` do próprio pedido (nunca perguntado de novo aqui): se o
    # pedido não tiver empresa definida, a conta também não tem.
    numero_conta = _gerar_numero_conta_receber()
    vencimento = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    cur = conn.execute(
        """
        INSERT INTO contas_receber (numero, pedido_venda_id, cliente_id, valor_total, vencimento, empresa_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (numero_conta, pedido_id, pedido["cliente_id"], valor_total_conta, vencimento, pedido["empresa_id"], usuario_atual["id"]),
    )
    conta_receber_id = cur.lastrowid
    audit.registrar(conn, tabela="contas_receber", registro_id=conta_receber_id, usuario_id=usuario_atual["id"],
                     acao="conta_receber_gerada_automaticamente",
                     valor_novo={"numero": numero_conta, "pedido_venda_id": pedido_id, "valor_total": valor_total_conta, "vencimento": vencimento},
                     ip=client_ip(), dispositivo=client_device())

    # Fase 36 — verbas comerciais: geradas e usadas só na EXPEDIÇÃO (não na
    # confirmação), no mesmo momento em que a conta a receber nasce — é
    # quando o valor da venda deixa de ser um plano e passa a ser um fato.
    # Se este pedido for cancelado antes de chegar até aqui, nenhum
    # lançamento de verba é gravado, então não há nada a desfazer.
    if verba_utilizada_pedido > 0.0000001:
        conn.execute(
            """
            INSERT INTO verbas_comerciais_lancamentos (cliente_id, tipo, valor, pedido_venda_id, observacao, criado_por)
            VALUES (?, 'utilizada', ?, ?, ?, ?)
            """,
            (pedido["cliente_id"], verba_utilizada_pedido, pedido_id,
             f"Abatimento no pedido {pedido['numero']}", usuario_atual["id"]),
        )
    percentual_verba = _percentual_verba_gerada(conn)
    if percentual_verba > 0.0000001:
        valor_verba_gerada = valor_total_conta * percentual_verba / 100.0
        conn.execute(
            """
            INSERT INTO verbas_comerciais_lancamentos (cliente_id, tipo, valor, pedido_venda_id, observacao, criado_por)
            VALUES (?, 'gerada', ?, ?, ?, ?)
            """,
            (pedido["cliente_id"], valor_verba_gerada, pedido_id,
             f"Gerada pela venda do pedido {pedido['numero']} ({percentual_verba}% sobre R$ {valor_total_conta:.2f})",
             usuario_atual["id"]),
        )
    return jsonify(_pedido_detalhado(conn, pedido_id))


def cancelar_pedido_internamente(conn, pedido_id, usuario_id, motivo):
    """Núcleo do cancelamento de um pedido de venda — extraído na Fase 36
    pelo mesmo motivo de `confirmar_pedido_internamente` acima: o
    aplicativo de vendas reaproveita esta função para encerrar (por
    expiração ou por o vendedor descartar) um rascunho criado por ele
    mesmo, sem duplicar a regra de "quais status podem ser cancelados"
    nem o jeito como a reserva é liberada."""
    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    pedido = _pedido_ou_404(conn, pedido_id)
    if pedido["status"] not in STATUS_QUE_PERMITEM_CANCELAR:
        raise ApiError(
            f"Não é possível cancelar um pedido com status '{pedido['status']}' "
            "(um pedido já expedido não pode ser cancelado — trate devolução como um fluxo separado).",
            status=400,
        )

    # Cancelar um pedido 'confirmado' libera a reserva automaticamente: a
    # linha em pedido_venda_reservas continua existindo para sempre (é
    # append-only, é histórico), mas _saldo_reservado_ativo só soma
    # reservas de pedidos com status='confirmado' — assim que o status
    # muda para 'cancelado' aqui, o saldo volta a ficar disponível para
    # outros pedidos na próxima consulta, sem editar/apagar nada.
    conn.execute(
        "UPDATE pedidos_venda SET status = 'cancelado', motivo_cancelamento = ? WHERE id = ?",
        (motivo, pedido_id),
    )
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_id,
                     acao="pedido_cancelado", valor_anterior={"status": pedido["status"]}, valor_novo={"status": "cancelado"},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return _pedido_detalhado(conn, pedido_id)


@bp.post("/pedidos/<int:pedido_id>/cancelar")
@requires_permission("comercial", "cancelar_pedido")
def cancelar(pedido_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()
    return jsonify(cancelar_pedido_internamente(conn, pedido_id, usuario_atual["id"], motivo))


@bp.post("/pedidos/<int:pedido_id>/reverter-para-rascunho")
@requires_permission("comercial", "cancelar_pedido")
def reverter_para_rascunho(pedido_id):
    """Fase 97 — pedido do usuário: "revertido em orçamento". Só a partir
    de 'confirmado' (nunca 'expedido' — mesma fronteira de
    STATUS_QUE_PERMITEM_CANCELAR/cancelar_pedido_internamente acima: uma
    vez expedido, a mercadoria já pode ter saído fisicamente, e reverter
    o status aqui não desfaria isso). A liberação da reserva de estoque é
    automática, de graça: `_saldo_reservado_ativo` só soma reservas de
    pedidos com status='confirmado' (ver a nota completa em
    cancelar_pedido_internamente acima) — assim que o status muda para
    'rascunho' aqui, o saldo reservado volta a ficar livre, sem precisar
    tocar em `pedido_venda_reservas` (que é append-only, histórico)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    pedido = _pedido_ou_404(conn, pedido_id)

    if pedido["status"] != "confirmado":
        raise ApiError(
            f"Só é possível reverter para rascunho um pedido 'confirmado' (status atual: '{pedido['status']}') — "
            "um pedido já expedido não pode ser revertido (trate devolução como um fluxo separado).",
            status=400,
        )

    conn.execute("UPDATE pedidos_venda SET status = 'rascunho' WHERE id = ?", (pedido_id,))
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_revertido_para_rascunho", valor_anterior={"status": "confirmado"},
                     valor_novo={"status": "rascunho"}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_pedido_detalhado(conn, pedido_id))


@bp.post("/pedidos/<int:pedido_id>/excluir")
@requires_permission("comercial", "cancelar_pedido")
def excluir_pedido(pedido_id):
    """Fase 97 — pedido do usuário: "excluído com senha". Restrito a
    'rascunho' de propósito: é o ÚNICO status em que o pedido ainda não
    tem nenhuma consequência de negócio real (sem reserva de estoque, sem
    aprovação financeira concedida, sem nota fiscal) — a partir de
    'confirmado' em diante, a única forma de desfazer continua sendo
    cancelar (ou reverter-para-rascunho, acima), nunca apagar de vez.
    Exige a senha atual — mesma régua de reautenticação de
    `trocar_senha`/`desativar_2fa`, para uma ação irreversível como esta.

    Um rascunho com lançamento de verba comercial vinculado (Fase 36) não
    pode ser excluído: `verbas_comerciais_lancamentos` é append-only por
    trigger (UPDATE e DELETE bloqueados no próprio banco, de propósito —
    ver schema_fase36.sql) — apagar o pedido violaria a referência
    (FOREIGN KEY) sem nenhuma forma legal de limpar antes. Nesse caso,
    cancelar continua sendo o caminho certo."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    senha_atual = (dados.get("senha_atual") or "").strip()
    conn = get_db()
    pedido = _pedido_ou_404(conn, pedido_id)

    if pedido["status"] != "rascunho":
        raise ApiError(
            f"Só é possível excluir definitivamente um pedido ainda em 'rascunho' (status atual: '{pedido['status']}') "
            "— um pedido já confirmado ou expedido precisa ser cancelado, nunca excluído.",
            status=400,
        )
    if not security.verify_password(senha_atual, usuario_atual["senha_hash"]):
        raise ApiError("Senha atual incorreta.", status=400)

    tem_verba_vinculada = conn.execute(
        "SELECT 1 FROM verbas_comerciais_lancamentos WHERE pedido_venda_id = ? LIMIT 1", (pedido_id,)
    ).fetchone()
    if tem_verba_vinculada:
        raise ApiError(
            "Este pedido tem um lançamento de verba comercial vinculado (registro financeiro permanente, "
            "nunca apagado) — não é possível excluir. Cancele o pedido em vez de excluir.",
            status=400,
        )

    numero = pedido["numero"]
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="pedido_excluido", valor_anterior=dict(pedido), valor_novo=None,
                     ip=client_ip(), dispositivo=client_device())
    conn.execute("DELETE FROM pedidos_venda_confirmacoes_pendentes WHERE pedido_venda_id = ?", (pedido_id,))
    conn.execute("DELETE FROM sessoes_rascunho_app_vendas WHERE pedido_venda_id = ?", (pedido_id,))
    conn.execute("DELETE FROM pedido_venda_itens WHERE pedido_id = ?", (pedido_id,))
    conn.execute("DELETE FROM pedidos_venda WHERE id = ?", (pedido_id,))
    return jsonify({"ok": True, "numero": numero})
