import datetime
import math
import secrets

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..permissions import requires_permission
from .custeio import custo_unitario_lote

bp = Blueprint("estoque", __name__, url_prefix="/api/v1/estoque")

STATUS_ENDERECAVEIS = ("aprovado", "aprovado_com_ressalva")

# Fase 21 — acima deste percentual de divergência (em relação ao saldo que
# o sistema tinha no início da contagem), o ajuste NÃO é aplicado sozinho
# ao concluir a contagem: fica "pendente" até um segundo usuário aprovar.
# Quando o saldo inicial era 0 (o sistema não sabia de nada ali e a
# contagem física encontrou alguma coisa), o percentual não é calculável
# (divisão por zero) — tratado sempre como divergência grande, por
# definição: "achar" estoque que o sistema desconhecia por completo é o
# caso mais sensível de todos, não o menos.
#
# Fase 32 — o valor em si (era fixo em 20% aqui no código) agora mora em
# `configuracoes_estoque` (linha única) e é editável pela tela — este
# valor continua aqui só como FALLBACK, usado unicamente se por algum
# motivo a linha de configuração não existir no banco (nunca deveria
# acontecer num banco inicializado pelas migrations, mas defensivo é
# melhor que um 500 numa tela sensível como esta).
LIMIAR_PERCENTUAL_DIVERGENCIA_GRANDE_PADRAO = 20.0

# Fase 34 — segundo gatilho para divergência grande, independente do
# percentual: se o VALOR FINANCEIRO do ajuste (diferença × custo unitário
# do lote) ultrapassar este limiar em R$, também exige segunda aprovação.
# 0.0 = desligado (só o percentual decide, comportamento de sempre desde
# a Fase 21) — mesmo espírito de "padrão que preserva o comportamento
# antigo" já usado em toda fase de configuração opcional deste sistema.
LIMIAR_VALOR_AJUSTE_DIVERGENCIA_GRANDE_PADRAO = 0.0


def _limiar_percentual_divergencia_grande(conn):
    """Fase 32 — lê o limiar configurado (em PERCENTUAL, 0 a 100) e
    devolve como FRAÇÃO (0 a 1), a mesma unidade que `percentual`
    (calculado como `diferenca/saldo_inicio`) já usa na comparação
    abaixo — a tela e a API trabalham em percentual por ser mais natural
    para quem configura, mas a matemática interna continua em fração."""
    row = conn.execute("SELECT limiar_percentual_divergencia_grande FROM configuracoes_estoque WHERE id = 1").fetchone()
    valor_percentual = row["limiar_percentual_divergencia_grande"] if row else LIMIAR_PERCENTUAL_DIVERGENCIA_GRANDE_PADRAO
    return valor_percentual / 100.0


def _limiar_valor_ajuste_divergencia_grande(conn):
    """Fase 34 — lê o limiar configurado, em R$ (0 = gatilho desligado)."""
    row = conn.execute("SELECT limiar_valor_ajuste_divergencia_grande FROM configuracoes_estoque WHERE id = 1").fetchone()
    return row["limiar_valor_ajuste_divergencia_grande"] if row else LIMIAR_VALOR_AJUSTE_DIVERGENCIA_GRANDE_PADRAO


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hoje_iso_data():
    """Fase 65 — mesmo padrão de `_hoje_iso_data` em app/routes/compras.py:
    só a parte de data (sem hora), para comparar contra `validade` (que
    também é só data) sem fuso horário entrar no meio."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _posicao_ou_404(conn, posicao_id):
    row = conn.execute("SELECT * FROM posicoes_estoque WHERE id = ?", (posicao_id,)).fetchone()
    if row is None:
        raise ApiError("Posição de estoque não encontrada.", status=404)
    return dict(row)


def _lote_ou_404(conn, lote_id):
    row = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if row is None:
        raise ApiError("Lote não encontrado.", status=404)
    return dict(row)


def _saldo_posicao(conn, lote_id, posicao_id):
    total = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS total FROM movimentacoes_estoque WHERE lote_id = ? AND posicao_id = ?",
        (lote_id, posicao_id),
    ).fetchone()["total"]
    return total


def _saldo_lote_total(conn, lote_id):
    """Soma de tudo que já foi contabilizado no estoque físico para este
    lote, em todas as posições. Transferências somam líquido zero (uma
    linha negativa na origem, uma positiva no destino), então isso sempre
    reflete o que fisicamente ainda está em alguma posição."""
    total = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS total FROM movimentacoes_estoque WHERE lote_id = ?", (lote_id,)
    ).fetchone()["total"]
    return total


def _quantidade_consumida_em_producao(conn, lote_id):
    total = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS total FROM ordem_producao_consumo WHERE lote_id = ?", (lote_id,)
    ).fetchone()["total"]
    return total


def _quantidade_ja_enderecada(conn, lote_id):
    """Soma apenas dos lançamentos do tipo 'enderecamento' (o primeiro
    endereçamento de um lote recém-aprovado a uma posição) — de propósito,
    NÃO usa o saldo físico líquido atual. Ajustes negativos e baixas
    representam saída legítima do estoque (descarte, amostra, correção de
    contagem), não "material que ainda falta endereçar"; se usássemos o
    saldo líquido aqui, um lote já endereçado por completo voltaria a
    aparecer como pendente de endereçamento assim que alguém desse baixa ou
    fizesse um ajuste negativo nele, o que é errado — o endereçamento
    inicial já aconteceu, o que mudou depois foi o saldo, não a pendência."""
    total = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS total FROM movimentacoes_estoque WHERE lote_id = ? AND tipo = 'enderecamento'",
        (lote_id,),
    ).fetchone()["total"]
    return total


def _quantidade_pendente_de_enderecamento(conn, lote_id):
    """Quanto do lote ainda não foi nem endereçado no estoque, nem
    consumido em produção — ou seja, quanto ainda 'falta aparecer' em
    alguma posição física pela primeira vez. Nunca negativo por construção
    (as validações de cada rota impedem passar do total recebido/produzido)."""
    lote = _lote_ou_404(conn, lote_id)
    consumido = _quantidade_consumida_em_producao(conn, lote_id)
    ja_enderecada = _quantidade_ja_enderecada(conn, lote_id)
    return lote["quantidade"] - consumido - ja_enderecada


# ============================================================
# Fase 12 — DISPONIBILIDADE REAL COMPARTILHADA (Produção + Comercial + Estoque)
# ============================================================
# Estas funções são a ÚNICA fonte de verdade sobre "quanto de um lote
# ainda pode ser comprometido para um uso novo" — reutilizadas tanto por
# `producao.py` (reservar/consumir material) quanto por `comercial.py`
# (reservar para venda) e pelo `/estoque/fefo` deste próprio módulo, para
# que os três módulos nunca comprometam o mesmo saldo físico duas vezes
# sem saber um do outro.

def _reservado_vendas_lote_total(conn, lote_id):
    """Soma de tudo que está reservado por pedidos de venda AINDA
    confirmados (Fase 5) para este lote, somando TODAS as posições —
    Produção enxerga o lote como um todo (ela não trabalha com posições de
    WMS), então precisa do total, não de um valor por posição."""
    total = conn.execute(
        """
        SELECT COALESCE(SUM(pvr.quantidade), 0) AS total
        FROM pedido_venda_reservas pvr
        JOIN pedido_venda_itens pvi ON pvi.id = pvr.pedido_item_id
        JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
        WHERE pvr.lote_id = ? AND pv.status = 'confirmado'
        """,
        (lote_id,),
    ).fetchone()["total"]
    return total


def _reservado_producao_lote(conn, lote_id, excluir_ordem_id=None):
    """Soma de tudo que está reservado por ordens de produção AINDA
    ativas (Fase 12 — status 'liberada' ou 'em_producao'; uma ordem
    concluída já convertida esse material em consumo real, uma cancelada
    nunca chegou a usar, então nenhuma das duas deve continuar
    'segurando' o saldo). `excluir_ordem_id` deixa de fora a própria
    ordem que está checando sua disponibilidade — a reserva que ELA MESMA
    já garantiu não deve bloquear o consumo dela mesma contra esse lote."""
    params = [lote_id]
    clausula_excluir = ""
    if excluir_ordem_id is not None:
        clausula_excluir = "AND opr.ordem_producao_id != ?"
        params.append(excluir_ordem_id)
    total = conn.execute(
        f"""
        SELECT COALESCE(SUM(opr.quantidade), 0) AS total
        FROM ordem_producao_reservas opr
        JOIN ordens_producao op ON op.id = opr.ordem_producao_id
        WHERE opr.lote_id = ? AND op.status IN ('liberada', 'em_producao') {clausula_excluir}
        """,
        params,
    ).fetchone()["total"]
    return total


def _saida_liquida_fora_de_producao(conn, lote_id):
    """Quanto desse lote já saiu fisicamente do estoque por baixa ou
    ajuste negativo (descarte, amostra, correção de contagem para menos)
    — esse material não existe mais fisicamente, então Produção também
    não pode consumi-lo, mesmo que `lotes.quantidade` (o valor nominal
    recebido/produzido) ainda mostre o total original. Só considera o
    lado negativo de propósito: um ajuste POSITIVO (contagem encontrou
    mais do que o registrado) não aumenta a disponibilidade para produção
    além do nominal — mantém o cálculo conservador."""
    total = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS total FROM movimentacoes_estoque WHERE lote_id = ? AND tipo IN ('saida', 'ajuste_negativo')",
        (lote_id,),
    ).fetchone()["total"]
    return max(0.0, -total)


def saldo_real_disponivel_producao(conn, lote_id, excluir_ordem_id=None):
    """Quanto de um lote ainda pode ser reservado/consumido por uma nova
    ordem de produção, cruzando as três origens que podem comprometer o
    mesmo lote — consumo já apontado em qualquer ordem de produção, saída
    líquida já lançada no Estoque (baixa/ajuste negativo) e reserva ativa
    de um pedido de venda confirmado no Comercial — mais o que outras
    ordens de produção já garantiram ao serem liberadas (Fase 12)."""
    lote = conn.execute("SELECT quantidade FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if lote is None:
        return 0
    consumido = _quantidade_consumida_em_producao(conn, lote_id)
    reservado_vendas = _reservado_vendas_lote_total(conn, lote_id)
    reservado_producao = _reservado_producao_lote(conn, lote_id, excluir_ordem_id=excluir_ordem_id)
    saida_estoque = _saida_liquida_fora_de_producao(conn, lote_id)
    return lote["quantidade"] - consumido - reservado_vendas - reservado_producao - saida_estoque


# ============================================================
# POSIÇÕES DE ARMAZENAGEM
# ============================================================
@bp.get("/posicoes")
@requires_permission("estoque", "visualizar")
def listar_posicoes():
    conn = get_db()
    unidade_id = request.args.get("unidade_id", type=int)
    if unidade_id:
        rows = conn.execute(
            "SELECT * FROM posicoes_estoque WHERE unidade_id = ? ORDER BY codigo", (unidade_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM posicoes_estoque ORDER BY unidade_id, codigo").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/posicoes")
@requires_permission("estoque", "cadastrar_posicao")
def criar_posicao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    unidade_id = dados.get("unidade_id")
    codigo = (dados.get("codigo") or "").strip()
    conn = get_db()

    if not unidade_id or not codigo:
        raise ApiError("Informe unidade_id e codigo.", status=400)
    unidade = conn.execute("SELECT * FROM unidades WHERE id = ?", (unidade_id,)).fetchone()
    if unidade is None:
        raise ApiError("Unidade não encontrada.", status=404)
    if conn.execute(
        "SELECT id FROM posicoes_estoque WHERE unidade_id = ? AND codigo = ?", (unidade_id, codigo)
    ).fetchone():
        raise ApiError("Já existe uma posição com este código nesta unidade.", status=409)

    cur = conn.execute(
        "INSERT INTO posicoes_estoque (unidade_id, codigo, descricao, criado_por) VALUES (?, ?, ?, ?)",
        (unidade_id, codigo, dados.get("descricao"), usuario_atual["id"]),
    )
    posicao_id = cur.lastrowid
    audit.registrar(conn, tabela="posicoes_estoque", registro_id=posicao_id, usuario_id=usuario_atual["id"],
                     acao="posicao_criada", valor_novo={"unidade_id": unidade_id, "codigo": codigo},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_posicao_ou_404(conn, posicao_id)), 201


# ============================================================
# SALDO E LOTES PENDENTES DE ENDEREÇAMENTO
# ============================================================
@bp.get("/saldo")
@requires_permission("estoque", "visualizar")
def saldo():
    conn = get_db()
    lote_id = request.args.get("lote_id", type=int)
    posicao_id = request.args.get("posicao_id", type=int)
    item_id = request.args.get("item_id", type=int)

    clausulas, params = [], []
    if lote_id:
        clausulas.append("m.lote_id = ?")
        params.append(lote_id)
    if posicao_id:
        clausulas.append("m.posicao_id = ?")
        params.append(posicao_id)
    if item_id:
        clausulas.append("l.item_id = ?")
        params.append(item_id)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""

    rows = conn.execute(
        f"""
        SELECT m.lote_id, m.posicao_id, SUM(m.quantidade) AS saldo,
               l.codigo_lote, l.item_id, l.validade, l.status AS lote_status,
               i.codigo AS item_codigo, i.descricao AS item_descricao,
               p.codigo AS posicao_codigo, p.unidade_id
        FROM movimentacoes_estoque m
        JOIN lotes l ON l.id = m.lote_id
        JOIN itens i ON i.id = l.item_id
        JOIN posicoes_estoque p ON p.id = m.posicao_id
        {where}
        GROUP BY m.lote_id, m.posicao_id
        HAVING SUM(m.quantidade) > 0.0000001
        ORDER BY i.codigo, l.validade IS NULL, l.validade, p.codigo
        """,
        params,
    ).fetchall()
    hoje = _hoje_iso_data()
    resultado = []
    for r in rows:
        r = dict(r)
        # Fase 65 — só exibição (selo "Vencido" na tela de Estoque); o
        # bloqueio de verdade é nas alocações FEFO, não aqui.
        r["vencido"] = r["validade"] is not None and r["validade"] < hoje
        resultado.append(r)
    return jsonify(resultado)


@bp.get("/lotes-pendentes-enderecamento")
@requires_permission("estoque", "visualizar")
def lotes_pendentes_enderecamento():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT l.*, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM lotes l JOIN itens i ON i.id = l.item_id
        WHERE l.status IN ('aprovado', 'aprovado_com_ressalva')
        ORDER BY l.id
        """
    ).fetchall()
    pendentes = []
    for row in rows:
        lote = dict(row)
        pendente = _quantidade_pendente_de_enderecamento(conn, lote["id"])
        if pendente > 0.0000001:
            lote["quantidade_pendente"] = pendente
            pendentes.append(lote)
    return jsonify(pendentes)


# ============================================================
# MOVIMENTAÇÕES
# ============================================================
@bp.post("/enderecamentos")
@requires_permission("estoque", "enderecar")
def enderecar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    lote_id = dados.get("lote_id")
    posicao_id = dados.get("posicao_id")
    quantidade = dados.get("quantidade")
    conn = get_db()

    if not lote_id or not posicao_id or not quantidade:
        raise ApiError("Informe lote_id, posicao_id e quantidade.", status=400)
    try:
        quantidade = float(quantidade)
    except (TypeError, ValueError):
        raise ApiError("quantidade deve ser numérica.", status=400)
    if quantidade <= 0:
        raise ApiError("quantidade deve ser maior que zero.", status=400)

    lote = _lote_ou_404(conn, lote_id)
    if lote["status"] not in STATUS_ENDERECAVEIS:
        raise ApiError(
            f"Só é possível endereçar um lote aprovado (status atual: '{lote['status']}').", status=403,
        )
    posicao = _posicao_ou_404(conn, posicao_id)
    if posicao["status"] != "ativa":
        raise ApiError("Esta posição de estoque está inativa.", status=400)

    pendente = _quantidade_pendente_de_enderecamento(conn, lote_id)
    if quantidade > pendente:
        raise ApiError(
            f"Quantidade solicitada ({quantidade}) maior que a pendente de endereçamento do lote "
            f"{lote['codigo_lote']} ({pendente} {lote['unidade']}, já descontando o que foi consumido em "
            "produção e o que já está endereçado em outras posições).",
            status=400,
        )

    cur = conn.execute(
        """
        INSERT INTO movimentacoes_estoque (lote_id, posicao_id, tipo, quantidade, registrado_por)
        VALUES (?, ?, 'enderecamento', ?, ?)
        """,
        (lote_id, posicao_id, quantidade, usuario_atual["id"]),
    )
    mov_id = cur.lastrowid
    audit.registrar(conn, tabela="movimentacoes_estoque", registro_id=mov_id, usuario_id=usuario_atual["id"],
                     acao="lote_enderecado", valor_novo={"lote_id": lote_id, "posicao_id": posicao_id, "quantidade": quantidade},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True, "saldo_posicao": _saldo_posicao(conn, lote_id, posicao_id)}), 201


@bp.post("/transferencias")
@requires_permission("estoque", "transferir")
def transferir():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    lote_id = dados.get("lote_id")
    posicao_origem_id = dados.get("posicao_origem_id")
    posicao_destino_id = dados.get("posicao_destino_id")
    quantidade = dados.get("quantidade")
    conn = get_db()

    if not lote_id or not posicao_origem_id or not posicao_destino_id or not quantidade:
        raise ApiError("Informe lote_id, posicao_origem_id, posicao_destino_id e quantidade.", status=400)
    if posicao_origem_id == posicao_destino_id:
        raise ApiError("A posição de origem e destino não podem ser a mesma.", status=400)
    try:
        quantidade = float(quantidade)
    except (TypeError, ValueError):
        raise ApiError("quantidade deve ser numérica.", status=400)
    if quantidade <= 0:
        raise ApiError("quantidade deve ser maior que zero.", status=400)

    _lote_ou_404(conn, lote_id)
    _posicao_ou_404(conn, posicao_origem_id)
    destino = _posicao_ou_404(conn, posicao_destino_id)
    if destino["status"] != "ativa":
        raise ApiError("A posição de destino está inativa.", status=400)

    saldo_origem = _saldo_posicao(conn, lote_id, posicao_origem_id)
    if quantidade > saldo_origem:
        raise ApiError(
            f"Quantidade solicitada ({quantidade}) maior que o saldo disponível na posição de origem ({saldo_origem}).",
            status=400,
        )

    grupo = secrets.token_hex(8)
    conn.execute(
        """
        INSERT INTO movimentacoes_estoque (lote_id, posicao_id, tipo, quantidade, transferencia_grupo, registrado_por)
        VALUES (?, ?, 'transferencia_saida', ?, ?, ?)
        """,
        (lote_id, posicao_origem_id, -quantidade, grupo, usuario_atual["id"]),
    )
    conn.execute(
        """
        INSERT INTO movimentacoes_estoque (lote_id, posicao_id, tipo, quantidade, transferencia_grupo, registrado_por)
        VALUES (?, ?, 'transferencia_entrada', ?, ?, ?)
        """,
        (lote_id, posicao_destino_id, quantidade, grupo, usuario_atual["id"]),
    )
    audit.registrar(conn, tabela="movimentacoes_estoque", registro_id=grupo, usuario_id=usuario_atual["id"],
                     acao="lote_transferido",
                     valor_novo={"lote_id": lote_id, "origem": posicao_origem_id, "destino": posicao_destino_id, "quantidade": quantidade},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({
        "ok": True,
        "saldo_origem": _saldo_posicao(conn, lote_id, posicao_origem_id),
        "saldo_destino": _saldo_posicao(conn, lote_id, posicao_destino_id),
    }), 201


def registrar_ajuste_interno(conn, lote_id, posicao_id, quantidade, motivo, usuario_atual):
    """Lógica central de um ajuste de estoque (delta positivo ou negativo
    contra o saldo de um lote numa posição), usada tanto pela rota manual
    `/ajustes` abaixo quanto pela conclusão de uma contagem de inventário
    guiada (Fase 17, `_concluir_contagem` mais abaixo) — centralizada aqui
    de propósito para as duas nunca divergirem uma da outra (mesmo motivo
    que gerou `bloquear_lote_interno` na Fase 16 e
    `_baixado_liquido`/`_contas_em_aberto` na Fase 15). Devolve
    `(saldo_posicao, movimentacao_id)` — o id da movimentação é devolvido
    explicitamente (em vez de o chamador usar `last_insert_rowid()` depois)
    porque `audit.registrar` faz outro INSERT logo em seguida, que mudaria
    esse valor se fosse lido só depois desta função retornar."""
    if quantidade == 0:
        raise ApiError("quantidade não pode ser zero.", status=400)
    if not motivo:
        raise ApiError("Informe o motivo do ajuste (ex.: divergência de inventário físico).", status=400)

    _lote_ou_404(conn, lote_id)
    _posicao_ou_404(conn, posicao_id)

    saldo_atual = _saldo_posicao(conn, lote_id, posicao_id)
    if saldo_atual + quantidade < -0.0000001:
        raise ApiError(
            f"Este ajuste deixaria o saldo negativo (saldo atual: {saldo_atual}, ajuste: {quantidade}).",
            status=400,
        )

    tipo = "ajuste_positivo" if quantidade > 0 else "ajuste_negativo"
    cur = conn.execute(
        """
        INSERT INTO movimentacoes_estoque (lote_id, posicao_id, tipo, quantidade, motivo, registrado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (lote_id, posicao_id, tipo, quantidade, motivo, usuario_atual["id"]),
    )
    mov_id = cur.lastrowid
    audit.registrar(conn, tabela="movimentacoes_estoque", registro_id=mov_id, usuario_id=usuario_atual["id"],
                     acao="estoque_ajustado", valor_novo={"lote_id": lote_id, "posicao_id": posicao_id, "quantidade": quantidade},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return _saldo_posicao(conn, lote_id, posicao_id), mov_id


@bp.post("/ajustes")
@requires_permission("estoque", "ajustar")
def ajustar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    lote_id = dados.get("lote_id")
    posicao_id = dados.get("posicao_id")
    quantidade = dados.get("quantidade")
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not lote_id or not posicao_id or quantidade in (None, ""):
        raise ApiError("Informe lote_id, posicao_id e quantidade.", status=400)
    try:
        quantidade = float(quantidade)
    except (TypeError, ValueError):
        raise ApiError("quantidade deve ser numérica.", status=400)

    saldo_posicao, _mov_id = registrar_ajuste_interno(conn, lote_id, posicao_id, quantidade, motivo, usuario_atual)
    return jsonify({"ok": True, "saldo_posicao": saldo_posicao}), 201


@bp.post("/baixas")
@requires_permission("estoque", "dar_baixa")
def dar_baixa():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    lote_id = dados.get("lote_id")
    posicao_id = dados.get("posicao_id")
    quantidade = dados.get("quantidade")
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not lote_id or not posicao_id or not quantidade:
        raise ApiError("Informe lote_id, posicao_id e quantidade.", status=400)
    if not motivo:
        raise ApiError("Informe o motivo da baixa (ex.: descarte, devolução ao fornecedor, amostra consumida).", status=400)
    try:
        quantidade = float(quantidade)
    except (TypeError, ValueError):
        raise ApiError("quantidade deve ser numérica.", status=400)
    if quantidade <= 0:
        raise ApiError("quantidade deve ser maior que zero.", status=400)

    _lote_ou_404(conn, lote_id)
    _posicao_ou_404(conn, posicao_id)

    saldo_atual = _saldo_posicao(conn, lote_id, posicao_id)
    if quantidade > saldo_atual:
        raise ApiError(f"Quantidade maior que o saldo disponível nesta posição ({saldo_atual}).", status=400)

    cur = conn.execute(
        """
        INSERT INTO movimentacoes_estoque (lote_id, posicao_id, tipo, quantidade, motivo, registrado_por)
        VALUES (?, ?, 'saida', ?, ?, ?)
        """,
        (lote_id, posicao_id, -quantidade, motivo, usuario_atual["id"]),
    )
    mov_id = cur.lastrowid
    audit.registrar(conn, tabela="movimentacoes_estoque", registro_id=mov_id, usuario_id=usuario_atual["id"],
                     acao="estoque_baixa", valor_novo={"lote_id": lote_id, "posicao_id": posicao_id, "quantidade": quantidade},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True, "saldo_posicao": _saldo_posicao(conn, lote_id, posicao_id)}), 201


# ============================================================
# FEFO — First Expire, First Out (sugestão de separação)
# ============================================================
@bp.get("/fefo")
@requires_permission("estoque", "visualizar")
def sugestao_fefo():
    conn = get_db()
    item_id = request.args.get("item_id", type=int)
    quantidade_necessaria = request.args.get("quantidade", type=float)
    if not item_id or not quantidade_necessaria:
        raise ApiError("Informe item_id e quantidade.", status=400)
    if quantidade_necessaria <= 0:
        raise ApiError("quantidade deve ser maior que zero.", status=400)

    # Fase 65 — um lote vencido nunca é sugerido para separar, mesmo com
    # saldo físico positivo e status aprovado: mesmo raciocínio de
    # `_alocar_fefo` em comercial.py e `_alocar_fefo_producao` em
    # producao.py, aplicado aqui à sugestão manual de picking.
    lotes = conn.execute(
        """
        SELECT l.id, l.codigo_lote, l.validade, l.status
        FROM lotes l
        WHERE l.item_id = ? AND l.status IN ('aprovado', 'aprovado_com_ressalva')
          AND (l.validade IS NULL OR l.validade >= ?)
        ORDER BY (l.validade IS NULL), l.validade ASC, l.id ASC
        """,
        (item_id, _hoje_iso_data()),
    ).fetchall()

    sugestao = []
    restante = quantidade_necessaria
    for row in lotes:
        if restante <= 0.0000001:
            break
        lote = dict(row)
        # Fase 12: o saldo físico já entra líquido de baixas/ajustes (é a
        # soma do próprio ledger), mas também precisa descontar o que já
        # está reservado — por uma venda confirmada (Comercial) ou por uma
        # ordem de produção liberada (Fase 12) — para não sugerir separar
        # material que outro módulo já comprometeu.
        saldo_disponivel = (
            _saldo_lote_total(conn, lote["id"])
            - _reservado_vendas_lote_total(conn, lote["id"])
            - _reservado_producao_lote(conn, lote["id"])
        )
        if saldo_disponivel <= 0.0000001:
            continue
        quantidade_sugerida = min(saldo_disponivel, restante)
        sugestao.append({
            "lote_id": lote["id"], "codigo_lote": lote["codigo_lote"], "validade": lote["validade"],
            "saldo_disponivel": saldo_disponivel, "quantidade_sugerida": quantidade_sugerida,
        })
        restante -= quantidade_sugerida

    return jsonify({
        "item_id": item_id,
        "quantidade_solicitada": quantidade_necessaria,
        "quantidade_atendida": quantidade_necessaria - restante,
        "atende_totalmente": restante <= 0.0000001,
        "lotes_sugeridos": sugestao,
    })


# ============================================================
# Fase 17 — CONTAGEM DE INVENTÁRIO CÍCLICO/GERAL (fluxo guiado)
# ============================================================
def _gerar_numero_contagem():
    ano = datetime.datetime.utcnow().year
    return f"CI-{ano}-{secrets.token_hex(4).upper()}"


def _contagem_ou_404(conn, contagem_id):
    row = conn.execute("SELECT * FROM contagens_inventario WHERE id = ?", (contagem_id,)).fetchone()
    if row is None:
        raise ApiError("Contagem de inventário não encontrada.", status=404)
    return dict(row)


def _itens_da_contagem(conn, contagem_id):
    rows = conn.execute(
        """
        SELECT ci.*, l.codigo_lote, i.codigo AS item_codigo, i.descricao AS item_descricao,
               p.codigo AS posicao_codigo, u.nome AS contado_por_nome
        FROM contagens_inventario_itens ci
        JOIN lotes l ON l.id = ci.lote_id
        JOIN itens i ON i.id = l.item_id
        JOIN posicoes_estoque p ON p.id = ci.posicao_id
        LEFT JOIN usuarios u ON u.id = ci.contado_por
        WHERE ci.contagem_id = ?
        ORDER BY p.codigo, l.codigo_lote
        """,
        (contagem_id,),
    ).fetchall()
    # Fase 34 — lido uma vez só (não por item) por eficiência. Continua
    # 0.0 (gatilho desligado) em qualquer banco onde ninguém configurou
    # isso, então nenhum custo é calculado à toa no caso mais comum.
    limiar_valor = _limiar_valor_ajuste_divergencia_grande(conn)
    saida = []
    for r in rows:
        d = dict(r)
        if d["quantidade_contada"] is not None:
            diferenca = d["quantidade_contada"] - d["saldo_sistema_no_inicio"]
            d["diferenca"] = diferenca
            d["percentual_divergencia"] = (
                abs(diferenca) / d["saldo_sistema_no_inicio"] if d["saldo_sistema_no_inicio"] > 0.0000001 else None
            )
            # Fase 34 — só calcula o valor financeiro do ajuste quando o
            # segundo gatilho está LIGADO e há de fato uma diferença a
            # avaliar (custear item por item à toa quando ninguém
            # configurou esse limiar seria trabalho e chamadas ao banco
            # desperdiçados). `custo_unitario_ajuste` vem None quando o
            # custo não é conhecido (filosofia de transparência da Fase
            # 13: nunca inventa um valor).
            if limiar_valor > 0 and abs(diferenca) > 0.0000001:
                valor_unitario, origem_custo = custo_unitario_lote(conn, d["lote_id"])
                d["custo_unitario_ajuste"] = valor_unitario
                d["origem_custo_ajuste"] = origem_custo
                d["valor_ajuste_estimado"] = abs(diferenca) * valor_unitario if valor_unitario is not None else None
            else:
                d["custo_unitario_ajuste"] = None
                d["origem_custo_ajuste"] = None
                d["valor_ajuste_estimado"] = None
        else:
            d["diferenca"] = None
            d["percentual_divergencia"] = None
            d["custo_unitario_ajuste"] = None
            d["origem_custo_ajuste"] = None
            d["valor_ajuste_estimado"] = None
        saida.append(d)
    return saida


def _contagem_detalhada(conn, contagem_id):
    contagem = _contagem_ou_404(conn, contagem_id)
    contagem["itens"] = _itens_da_contagem(conn, contagem_id)
    return contagem


@bp.get("/contagens")
@requires_permission("estoque", "visualizar")
def listar_contagens():
    conn = get_db()
    status_filtro = request.args.get("status")
    unidade_id = request.args.get("unidade_id", type=int)
    condicoes, params = [], []
    if status_filtro:
        condicoes.append("status = ?")
        params.append(status_filtro)
    if unidade_id:
        condicoes.append("unidade_id = ?")
        params.append(unidade_id)
    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = conn.execute(f"SELECT * FROM contagens_inventario {where} ORDER BY id DESC", params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/contagens/<int:contagem_id>")
@requires_permission("estoque", "visualizar")
def detalhe_contagem(contagem_id):
    conn = get_db()
    return jsonify(_contagem_detalhada(conn, contagem_id))


@bp.post("/contagens")
@requires_permission("estoque", "contagem")
def iniciar_contagem():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    unidade_id = dados.get("unidade_id")
    tipo = dados.get("tipo")
    conn = get_db()

    if not unidade_id:
        raise ApiError("Informe unidade_id.", status=400)
    if tipo not in ("ciclica", "geral"):
        raise ApiError("tipo deve ser 'ciclica' ou 'geral'.", status=400)
    if not conn.execute("SELECT id FROM unidades WHERE id = ?", (unidade_id,)).fetchone():
        raise ApiError("Unidade não encontrada.", status=404)

    numero = _gerar_numero_contagem()
    cur = conn.execute(
        "INSERT INTO contagens_inventario (numero, unidade_id, tipo, observacao, criado_por) VALUES (?, ?, ?, ?, ?)",
        (numero, unidade_id, tipo, dados.get("observacao"), usuario_atual["id"]),
    )
    contagem_id = cur.lastrowid

    if tipo == "geral":
        # Popula automaticamente com TODO par lote+posição que hoje tem
        # saldo positivo nesta unidade — "geral" significa contar tudo, o
        # oposto de "ciclica" (onde quem conduz a contagem escolhe os
        # itens um a um via `POST /contagens/{id}/itens` abaixo).
        combinacoes = conn.execute(
            """
            SELECT lote_id, posicao_id, SUM(quantidade) AS saldo
            FROM movimentacoes_estoque me
            JOIN posicoes_estoque p ON p.id = me.posicao_id
            WHERE p.unidade_id = ?
            GROUP BY lote_id, posicao_id
            HAVING SUM(quantidade) > 0.0000001
            """,
            (unidade_id,),
        ).fetchall()
        for c in combinacoes:
            conn.execute(
                """
                INSERT INTO contagens_inventario_itens
                    (contagem_id, lote_id, posicao_id, saldo_sistema_no_inicio, adicionado_por)
                VALUES (?, ?, ?, ?, ?)
                """,
                (contagem_id, c["lote_id"], c["posicao_id"], c["saldo"], usuario_atual["id"]),
            )

    audit.registrar(conn, tabela="contagens_inventario", registro_id=contagem_id, usuario_id=usuario_atual["id"],
                     acao="contagem_iniciada", valor_novo={"numero": numero, "unidade_id": unidade_id, "tipo": tipo},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contagem_detalhada(conn, contagem_id)), 201


@bp.post("/contagens/<int:contagem_id>/itens")
@requires_permission("estoque", "contagem")
def adicionar_item_contagem(contagem_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    lote_id = dados.get("lote_id")
    posicao_id = dados.get("posicao_id")
    conn = get_db()

    contagem = _contagem_ou_404(conn, contagem_id)
    if contagem["status"] != "em_andamento":
        raise ApiError(f"Esta contagem já está '{contagem['status']}' — não é possível adicionar itens.", status=400)
    if contagem["tipo"] == "geral":
        raise ApiError(
            "Contagens do tipo 'geral' já incluem todos os itens automaticamente ao serem iniciadas; "
            "use uma contagem do tipo 'ciclica' para adicionar itens individualmente.",
            status=400,
        )
    if not lote_id or not posicao_id:
        raise ApiError("Informe lote_id e posicao_id.", status=400)

    _lote_ou_404(conn, lote_id)
    _posicao_ou_404(conn, posicao_id)
    if conn.execute(
        "SELECT id FROM contagens_inventario_itens WHERE contagem_id = ? AND lote_id = ? AND posicao_id = ?",
        (contagem_id, lote_id, posicao_id),
    ).fetchone():
        raise ApiError("Este lote nesta posição já está incluído nesta contagem.", status=409)

    saldo_atual = _saldo_posicao(conn, lote_id, posicao_id)
    cur = conn.execute(
        """
        INSERT INTO contagens_inventario_itens
            (contagem_id, lote_id, posicao_id, saldo_sistema_no_inicio, adicionado_por)
        VALUES (?, ?, ?, ?, ?)
        """,
        (contagem_id, lote_id, posicao_id, saldo_atual, usuario_atual["id"]),
    )
    item_id = cur.lastrowid
    audit.registrar(conn, tabela="contagens_inventario_itens", registro_id=item_id, usuario_id=usuario_atual["id"],
                     acao="contagem_item_adicionado",
                     valor_novo={"contagem_id": contagem_id, "lote_id": lote_id, "posicao_id": posicao_id, "saldo_sistema_no_inicio": saldo_atual},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contagem_detalhada(conn, contagem_id)), 201


@bp.post("/contagens/<int:contagem_id>/itens/<int:item_id>/contar")
@requires_permission("estoque", "contagem")
def registrar_contagem_item(contagem_id, item_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    quantidade_contada = dados.get("quantidade_contada")
    conn = get_db()

    contagem = _contagem_ou_404(conn, contagem_id)
    if contagem["status"] != "em_andamento":
        raise ApiError(f"Esta contagem já está '{contagem['status']}' — não é possível registrar contagens.", status=400)

    item = conn.execute(
        "SELECT * FROM contagens_inventario_itens WHERE id = ? AND contagem_id = ?", (item_id, contagem_id),
    ).fetchone()
    if item is None:
        raise ApiError("Item não encontrado nesta contagem.", status=404)

    if quantidade_contada in (None, ""):
        raise ApiError("Informe quantidade_contada.", status=400)
    try:
        quantidade_contada = float(quantidade_contada)
    except (TypeError, ValueError):
        raise ApiError("quantidade_contada deve ser numérica.", status=400)
    if quantidade_contada < 0:
        raise ApiError("quantidade_contada não pode ser negativa.", status=400)

    conn.execute(
        """
        UPDATE contagens_inventario_itens
        SET quantidade_contada = ?, status = 'contado', contado_em = ?, contado_por = ?
        WHERE id = ?
        """,
        (quantidade_contada, _now_iso(), usuario_atual["id"], item_id),
    )
    audit.registrar(conn, tabela="contagens_inventario_itens", registro_id=item_id, usuario_id=usuario_atual["id"],
                     acao="contagem_item_contado",
                     valor_novo={"contagem_id": contagem_id, "quantidade_contada": quantidade_contada},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contagem_detalhada(conn, contagem_id))


@bp.post("/contagens/<int:contagem_id>/concluir")
@requires_permission("estoque", "ajustar")
def concluir_contagem(contagem_id):
    """Reaproveita `estoque.ajustar` (em vez de criar mais uma permissão
    nova) porque concluir uma contagem É, na prática, autorizar os
    ajustes automáticos que ela vai gerar — o mesmo poder que já é exigido
    para lançar um ajuste manual na tela Estoque.

    Fase 21: essa autorização de uma pessoa só é suficiente para
    divergências PEQUENAS (abaixo de `LIMIAR_PERCENTUAL_DIVERGENCIA_
    GRANDE`), que continuam virando ajuste na hora, exatamente como desde
    a Fase 17. Uma divergência GRANDE não é ajustada aqui — fica
    `aprovacao_status='pendente'` até um segundo usuário, com
    `estoque.aprovar_ajuste_contagem`, decidir via
    `/aprovar-ajuste`/`/rejeitar-ajuste` abaixo."""
    usuario_atual = g.usuario_atual
    conn = get_db()

    contagem = _contagem_ou_404(conn, contagem_id)
    if contagem["status"] != "em_andamento":
        raise ApiError(f"Esta contagem já está '{contagem['status']}'.", status=400)

    itens = _itens_da_contagem(conn, contagem_id)
    pendentes = [i for i in itens if i["status"] == "pendente"]
    if pendentes:
        raise ApiError(
            f"Ainda há {len(pendentes)} item(ns) pendente(s) de contagem — registre a contagem de todos "
            "os itens antes de concluir (ou cancele a contagem).",
            status=400,
        )

    ajustes_gerados = []
    pendentes_aprovacao = []
    limiar_percentual = _limiar_percentual_divergencia_grande(conn)
    limiar_valor = _limiar_valor_ajuste_divergencia_grande(conn)
    for item in itens:
        diferenca = item["quantidade_contada"] - item["saldo_sistema_no_inicio"]
        if abs(diferenca) <= 0.0000001:
            continue

        saldo_inicio = item["saldo_sistema_no_inicio"]
        percentual = (abs(diferenca) / saldo_inicio) if saldo_inicio > 0.0000001 else None
        divergencia_grande = percentual is None or percentual > limiar_percentual

        # Fase 34 — segundo gatilho, independente do percentual: se o
        # valor financeiro do ajuste (já calculado por
        # `_itens_da_contagem`, que só custeia quando o gatilho está
        # ligado) ultrapassar o limiar em R$, também vira divergência
        # grande — mesmo que o percentual esteja abaixo do limiar. E, na
        # mesma filosofia de transparência da Fase 13, não saber o custo
        # nunca deixa passar sem segunda aprovação: conta como
        # divergência grande por segurança, nunca o contrário.
        custo_indisponivel_para_valor = False
        if not divergencia_grande and limiar_valor > 0:
            if item["custo_unitario_ajuste"] is None:
                custo_indisponivel_para_valor = True
                divergencia_grande = True
            elif item["valor_ajuste_estimado"] > limiar_valor:
                divergencia_grande = True

        if divergencia_grande:
            conn.execute("UPDATE contagens_inventario_itens SET aprovacao_status = 'pendente' WHERE id = ?", (item["id"],))
            pendentes_aprovacao.append({
                "item_id": item["id"], "lote_id": item["lote_id"], "posicao_id": item["posicao_id"],
                "diferenca": diferenca, "percentual_divergencia": percentual,
                "valor_ajuste_estimado": item["valor_ajuste_estimado"],
                "custo_indisponivel_para_valor": custo_indisponivel_para_valor,
            })
        else:
            motivo = f"Ajuste automático da contagem de inventário {contagem['numero']}"
            _saldo_posicao_novo, mov_id = registrar_ajuste_interno(conn, item["lote_id"], item["posicao_id"], diferenca, motivo, usuario_atual)
            conn.execute("UPDATE contagens_inventario_itens SET ajuste_gerado_id = ? WHERE id = ?", (mov_id, item["id"]))
            ajustes_gerados.append({"item_id": item["id"], "lote_id": item["lote_id"], "posicao_id": item["posicao_id"], "diferenca": diferenca})

    conn.execute(
        "UPDATE contagens_inventario SET status = 'concluida', concluida_em = ?, concluida_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], contagem_id),
    )
    audit.registrar(conn, tabela="contagens_inventario", registro_id=contagem_id, usuario_id=usuario_atual["id"],
                     acao="contagem_concluida",
                     valor_novo={
                         "numero": contagem["numero"], "total_itens": len(itens),
                         "ajustes_gerados": len(ajustes_gerados), "pendentes_aprovacao": len(pendentes_aprovacao),
                     },
                     ip=client_ip(), dispositivo=client_device())

    # Fase 37 — avisa quem tem "estoque.aprovar_ajuste_contagem" que há
    # ajuste(s) esperando decisão, sem precisar vasculhar a tela de vez em
    # quando. Uma notificação só, resumindo a contagem inteira (não uma
    # por item) — evita alagar quem aprova quando a contagem tem muitos
    # itens divergentes. Quem concluiu não é notificado (mesma segregação
    # de função da Fase 21: quem contou/concluiu não pode ser quem
    # aprova).
    if pendentes_aprovacao:
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="estoque", acao="aprovar_ajuste_contagem",
            tipo="ajuste_contagem_pendente",
            mensagem=(
                f"A contagem de inventário {contagem['numero']} gerou "
                f"{len(pendentes_aprovacao)} ajuste(s) com divergência grande, "
                "pendente(s) de aprovação."
            ),
            excluir_usuario_id=usuario_atual["id"],
        )

    return jsonify(_contagem_detalhada(conn, contagem_id))


@bp.get("/ajustes-pendentes-aprovacao")
@requires_permission("estoque", "visualizar")
def listar_ajustes_pendentes_aprovacao():
    """Lista consolidada, de TODAS as contagens, dos itens com divergência
    grande ainda aguardando a segunda aprovação (Fase 21) — útil pra quem
    tem `estoque.aprovar_ajuste_contagem` não precisar vasculhar contagem
    por contagem procurando o que falta decidir."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT ci.id AS item_id, ci.contagem_id, c.numero AS contagem_numero, c.unidade_id,
               ci.lote_id, ci.posicao_id, ci.saldo_sistema_no_inicio, ci.quantidade_contada,
               ci.contado_por, ci.contado_em
        FROM contagens_inventario_itens ci
        JOIN contagens_inventario c ON c.id = ci.contagem_id
        WHERE ci.aprovacao_status = 'pendente'
        ORDER BY ci.contado_em
        """
    ).fetchall()
    # Fase 34 — mesma ideia de "só custeia se o gatilho estiver ligado"
    # já usada em `_itens_da_contagem`, aqui pra mostrar, de forma
    # transparente, o valor estimado do ajuste também nesta lista
    # consolidada (a decisão em si já foi tomada lá em `concluir_
    # contagem` — isso aqui é só informativo pra quem vai aprovar/rejeitar).
    limiar_valor = _limiar_valor_ajuste_divergencia_grande(conn)
    resultado = []
    for r in rows:
        d = dict(r)
        diferenca = d["quantidade_contada"] - d["saldo_sistema_no_inicio"]
        d["diferenca"] = diferenca
        d["percentual_divergencia"] = (
            abs(diferenca) / d["saldo_sistema_no_inicio"] if d["saldo_sistema_no_inicio"] > 0.0000001 else None
        )
        if limiar_valor > 0:
            valor_unitario, origem_custo = custo_unitario_lote(conn, d["lote_id"])
            d["custo_unitario_ajuste"] = valor_unitario
            d["origem_custo_ajuste"] = origem_custo
            d["valor_ajuste_estimado"] = abs(diferenca) * valor_unitario if valor_unitario is not None else None
        else:
            d["custo_unitario_ajuste"] = None
            d["origem_custo_ajuste"] = None
            d["valor_ajuste_estimado"] = None
        resultado.append(d)
    return jsonify(resultado)


def _item_contagem_pendente_ou_erro(conn, contagem_id, item_id):
    contagem = _contagem_ou_404(conn, contagem_id)
    item = conn.execute(
        "SELECT * FROM contagens_inventario_itens WHERE id = ? AND contagem_id = ?", (item_id, contagem_id),
    ).fetchone()
    if item is None:
        raise ApiError("Item não encontrado nesta contagem.", status=404)
    if item["aprovacao_status"] != "pendente":
        raise ApiError(
            f"Este item não está aguardando aprovação de ajuste (status atual: '{item['aprovacao_status']}').",
            status=400,
        )
    return contagem, item


@bp.post("/contagens/<int:contagem_id>/itens/<int:item_id>/aprovar-ajuste")
@requires_permission("estoque", "aprovar_ajuste_contagem")
def aprovar_ajuste_contagem(contagem_id, item_id):
    usuario_atual = g.usuario_atual
    conn = get_db()

    contagem, item = _item_contagem_pendente_ou_erro(conn, contagem_id, item_id)

    # Segregação de função: quem registrou a contagem física deste item não
    # pode ser quem aprova o ajuste resultante — mesmo padrão já usado em
    # `lotes.aprovar` desde a Fase 2 (quem concluiu a análise não aprova o
    # próprio lote).
    if item["contado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você registrou a contagem deste item e por isso não pode aprovar o ajuste dele — a aprovação "
            "precisa ser feita por outro usuário (segregação de função)."
        )

    diferenca = item["quantidade_contada"] - item["saldo_sistema_no_inicio"]
    motivo = f"Ajuste aprovado (divergência grande) da contagem de inventário {contagem['numero']}"
    _saldo_posicao_novo, mov_id = registrar_ajuste_interno(conn, item["lote_id"], item["posicao_id"], diferenca, motivo, usuario_atual)
    conn.execute(
        """
        UPDATE contagens_inventario_itens
        SET aprovacao_status = 'aprovado', aprovado_por = ?, aprovado_em = ?, ajuste_gerado_id = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), mov_id, item["id"]),
    )
    audit.registrar(conn, tabela="contagens_inventario_itens", registro_id=item["id"], usuario_id=usuario_atual["id"],
                     acao="ajuste_contagem_aprovado",
                     valor_novo={"contagem_id": contagem_id, "diferenca": diferenca, "movimentacao_id": mov_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contagem_detalhada(conn, contagem_id))


@bp.post("/contagens/<int:contagem_id>/itens/<int:item_id>/rejeitar-ajuste")
@requires_permission("estoque", "aprovar_ajuste_contagem")
def rejeitar_ajuste_contagem(contagem_id, item_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo_rejeicao = (dados.get("motivo") or "").strip()
    conn = get_db()

    contagem, item = _item_contagem_pendente_ou_erro(conn, contagem_id, item_id)

    if not motivo_rejeicao:
        raise ApiError("Informe o motivo da rejeição.", status=400)

    if item["contado_por"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você registrou a contagem deste item e por isso não pode decidir sobre o ajuste dele — a decisão "
            "precisa ser tomada por outro usuário (segregação de função)."
        )

    # Rejeitar NÃO gera ajuste nenhum — o saldo do sistema permanece como
    # estava. A divergência apontada pela contagem fica registrada (neste
    # item e na auditoria) para investigação, mas não é "corrigida" às
    # cegas só porque alguém contou algo muito diferente uma vez.
    conn.execute(
        """
        UPDATE contagens_inventario_itens
        SET aprovacao_status = 'rejeitado', aprovado_por = ?, aprovado_em = ?, motivo_rejeicao = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], _now_iso(), motivo_rejeicao, item["id"]),
    )
    audit.registrar(conn, tabela="contagens_inventario_itens", registro_id=item["id"], usuario_id=usuario_atual["id"],
                     acao="ajuste_contagem_rejeitado",
                     valor_novo={"contagem_id": contagem_id}, motivo=motivo_rejeicao,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contagem_detalhada(conn, contagem_id))


@bp.post("/contagens/<int:contagem_id>/cancelar")
@requires_permission("estoque", "contagem")
def cancelar_contagem(contagem_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    contagem = _contagem_ou_404(conn, contagem_id)
    if contagem["status"] != "em_andamento":
        raise ApiError(f"Esta contagem já está '{contagem['status']}'.", status=400)
    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    conn.execute(
        "UPDATE contagens_inventario SET status = 'cancelada', cancelada_em = ?, cancelada_por = ?, motivo_cancelamento = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], motivo, contagem_id),
    )
    audit.registrar(conn, tabela="contagens_inventario", registro_id=contagem_id, usuario_id=usuario_atual["id"],
                     acao="contagem_cancelada", valor_novo={"numero": contagem["numero"]}, motivo=motivo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contagem_detalhada(conn, contagem_id))


# ============================================================
# FASE 32/34 — Configuração dos limiares de divergência (editável pela tela)
# ============================================================
@bp.get("/configuracao")
@requires_permission("estoque", "visualizar")
def obter_configuracao_estoque():
    """Visualizar o valor atual é liberado pra quem já vê o módulo Estoque
    (o número em si não é sensível) — só ALTERAR exige a permissão nova
    `configurar_alcada_divergencia`."""
    conn = get_db()
    row = conn.execute("SELECT * FROM configuracoes_estoque WHERE id = 1").fetchone()
    if row is None:
        # Defensivo: nunca deveria acontecer num banco inicializado pelas
        # migrations (a Fase 32 já semeia a linha única), mas devolve o
        # padrão em vez de um 404/500 numa tela sensível como esta.
        return jsonify({
            "limiar_percentual_divergencia_grande": LIMIAR_PERCENTUAL_DIVERGENCIA_GRANDE_PADRAO,
            "limiar_valor_ajuste_divergencia_grande": LIMIAR_VALOR_AJUSTE_DIVERGENCIA_GRANDE_PADRAO,
            "atualizado_em": None, "atualizado_por": None,
        })
    return jsonify(dict(row))


@bp.put("/configuracao")
@requires_permission("estoque", "configurar_alcada_divergencia")
def atualizar_configuracao_estoque():
    """Fase 34 — o campo novo `limiar_valor_ajuste_divergencia_grande` é
    OPCIONAL nesta requisição: quem só quer mexer no percentual (o uso
    mais comum, herdado da Fase 32) continua podendo mandar só esse
    campo, sem quebrar nada — se não vier no corpo, preserva o valor já
    configurado (ou 0.0/"desligado", numa linha ainda inexistente)."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    valor = dados.get("limiar_percentual_divergencia_grande")
    if valor is None:
        raise ApiError("Informe limiar_percentual_divergencia_grande.", status=400)
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ApiError("limiar_percentual_divergencia_grande deve ser numérico.", status=400)
    if valor <= 0 or valor > 100:
        raise ApiError("limiar_percentual_divergencia_grande deve estar entre 0 (exclusive) e 100.", status=400)

    anterior = conn.execute(
        "SELECT limiar_percentual_divergencia_grande, limiar_valor_ajuste_divergencia_grande FROM configuracoes_estoque WHERE id = 1"
    ).fetchone()

    if "limiar_valor_ajuste_divergencia_grande" in dados:
        valor_reais = dados.get("limiar_valor_ajuste_divergencia_grande")
        try:
            valor_reais = float(valor_reais)
        except (TypeError, ValueError):
            raise ApiError("limiar_valor_ajuste_divergencia_grande deve ser numérico.", status=400)
        if valor_reais < 0:
            raise ApiError(
                "limiar_valor_ajuste_divergencia_grande não pode ser negativo (use 0 para desligar esse gatilho).",
                status=400,
            )
    else:
        valor_reais = anterior["limiar_valor_ajuste_divergencia_grande"] if anterior else LIMIAR_VALOR_AJUSTE_DIVERGENCIA_GRANDE_PADRAO

    conn.execute(
        """
        INSERT INTO configuracoes_estoque
            (id, limiar_percentual_divergencia_grande, limiar_valor_ajuste_divergencia_grande, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            limiar_percentual_divergencia_grande = excluded.limiar_percentual_divergencia_grande,
            limiar_valor_ajuste_divergencia_grande = excluded.limiar_valor_ajuste_divergencia_grande,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (valor, valor_reais, _now_iso(), usuario_atual["id"]),
    )
    audit.registrar(conn, tabela="configuracoes_estoque", registro_id=1, usuario_id=usuario_atual["id"],
                     acao="configuracao_estoque_atualizada",
                     valor_anterior={
                         "limiar_percentual_divergencia_grande": anterior["limiar_percentual_divergencia_grande"] if anterior else None,
                         "limiar_valor_ajuste_divergencia_grande": anterior["limiar_valor_ajuste_divergencia_grande"] if anterior else None,
                     },
                     valor_novo={"limiar_percentual_divergencia_grande": valor, "limiar_valor_ajuste_divergencia_grande": valor_reais},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM configuracoes_estoque WHERE id = 1").fetchone()
    return jsonify(dict(row))


# ============================================================
# FASE 35 — AGENDAMENTO/CADÊNCIA AUTOMÁTICA DE CONTAGENS DE INVENTÁRIO
# ============================================================
# Este backend roda num processo comum, sem um agendador de tarefas do
# sistema operacional de verdade (cron) rodando sozinho em segundo
# plano — então "automático" aqui significa "verificado e disparado na
# hora certa", não "um daemon dormindo e acordando à meia-noite". A tela
# de Estoque chama `POST /estoque/agendamentos/verificar` a cada vez que
# é aberta por qualquer usuário com `estoque.contagem`; se algum
# agendamento estiver "vencido" (dia certo, ainda não gerado hoje), a
# contagem correspondente é criada na hora — exatamente como se alguém
# tivesse clicado em "Nova contagem" manualmente, só que já rotulada com
# `origem='agendamento'` e vinculada ao agendamento que a gerou (nada
# escondido: quem abrir a contagem sabe exatamente de onde ela veio).
# Isso cobre o caso de uso real ("a contagem do dia certo aparece
# sozinha quando alguém entra no sistema"), sem inventar um processo em
# segundo plano que não existe e sem prometer uma execução no segundo
# exato configurado se ninguém abrir a tela naquele dia — limitação
# documentada no README.

# Convenção de `dia_semana`: a mesma de `date.weekday()` do Python
# (0=segunda ... 6=domingo) — escolhida por ser a convenção do próprio
# runtime que calcula "hoje", evitando um passo de tradução a cada
# verificação. A tela sempre mostra o nome do dia por extenso, nunca só
# o número, para não haver ambiguidade com sistemas que usam "0=domingo".
DIAS_SEMANA_NOMES = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def _ultimo_dia_do_mes(ano, mes):
    if mes == 12:
        proximo_mes_dia1 = datetime.date(ano + 1, 1, 1)
    else:
        proximo_mes_dia1 = datetime.date(ano, mes + 1, 1)
    return (proximo_mes_dia1 - datetime.timedelta(days=1)).day


def _agendamento_esta_vencido_hoje(agendamento, hoje):
    if agendamento["ultima_geracao_em"] == hoje.isoformat():
        return False  # já gerou hoje — nunca gera duas vezes no mesmo dia
    if agendamento["cadencia"] == "diaria":
        return True
    if agendamento["cadencia"] == "semanal":
        return hoje.weekday() == agendamento["dia_semana"]
    if agendamento["cadencia"] == "mensal":
        # Se o mês não tiver o dia configurado (ex.: 31 em abril), a
        # geração ocorre no ÚLTIMO dia daquele mês em vez de pular o mês
        # inteiro — um agendamento "todo dia 31" continua rodando 12
        # vezes por ano, não só nos meses com 31 dias.
        dia_alvo = min(agendamento["dia_mes"], _ultimo_dia_do_mes(hoje.year, hoje.month))
        return hoje.day == dia_alvo
    return False


def _agendamento_ou_404(conn, agendamento_id):
    row = conn.execute("SELECT * FROM agendamentos_contagem WHERE id = ?", (agendamento_id,)).fetchone()
    if row is None:
        raise ApiError("Agendamento de contagem não encontrado.", status=404)
    return dict(row)


def _combinacoes_com_saldo_positivo(conn, unidade_id):
    return conn.execute(
        """
        SELECT lote_id, posicao_id, SUM(quantidade) AS saldo
        FROM movimentacoes_estoque me
        JOIN posicoes_estoque p ON p.id = me.posicao_id
        WHERE p.unidade_id = ?
        GROUP BY lote_id, posicao_id
        HAVING SUM(quantidade) > 0.0000001
        """,
        (unidade_id,),
    ).fetchall()


def _gerar_contagem_a_partir_do_agendamento(conn, agendamento, usuario_id):
    """Cria uma contagem do jeito que `iniciar_contagem` (Fase 17) criaria
    manualmente, mas rotulada com a origem/agendamento — e, no caso
    'ciclica', escolhendo uma AMOSTRA ALEATÓRIA de combinações
    lote+posição em vez de exigir que alguém adicione item por item (a
    Fase 17 sempre exigiu isso manualmente; aqui, gerada por agendamento,
    o tamanho da amostra é o `percentual_itens` configurado)."""
    numero = _gerar_numero_contagem()
    cur = conn.execute(
        """
        INSERT INTO contagens_inventario
            (numero, unidade_id, tipo, observacao, criado_por, origem, agendamento_id)
        VALUES (?, ?, ?, ?, ?, 'agendamento', ?)
        """,
        (
            numero, agendamento["unidade_id"], agendamento["tipo"],
            f"Gerada automaticamente pelo agendamento #{agendamento['id']}.",
            usuario_id, agendamento["id"],
        ),
    )
    contagem_id = cur.lastrowid

    combinacoes = _combinacoes_com_saldo_positivo(conn, agendamento["unidade_id"])
    if agendamento["tipo"] == "ciclica":
        total = len(combinacoes)
        tamanho_amostra = max(1, math.ceil(total * agendamento["percentual_itens"] / 100.0)) if total else 0
        combinacoes = conn.execute(
            """
            SELECT lote_id, posicao_id, SUM(quantidade) AS saldo
            FROM movimentacoes_estoque me
            JOIN posicoes_estoque p ON p.id = me.posicao_id
            WHERE p.unidade_id = ?
            GROUP BY lote_id, posicao_id
            HAVING SUM(quantidade) > 0.0000001
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (agendamento["unidade_id"], tamanho_amostra),
        ).fetchall()

    for c in combinacoes:
        conn.execute(
            """
            INSERT INTO contagens_inventario_itens
                (contagem_id, lote_id, posicao_id, saldo_sistema_no_inicio, adicionado_por)
            VALUES (?, ?, ?, ?, ?)
            """,
            (contagem_id, c["lote_id"], c["posicao_id"], c["saldo"], usuario_id),
        )

    conn.execute(
        "UPDATE agendamentos_contagem SET ultima_geracao_em = ?, ultima_contagem_id = ? WHERE id = ?",
        (_now_iso()[:10], contagem_id, agendamento["id"]),
    )
    audit.registrar(conn, tabela="contagens_inventario", registro_id=contagem_id, usuario_id=usuario_id,
                     acao="contagem_gerada_por_agendamento",
                     valor_novo={"numero": numero, "agendamento_id": agendamento["id"], "unidade_id": agendamento["unidade_id"]},
                     ip=client_ip(), dispositivo=client_device())
    return contagem_id


def _validar_campos_agendamento(dados):
    tipo = dados.get("tipo")
    cadencia = dados.get("cadencia")

    if tipo not in ("ciclica", "geral"):
        raise ApiError("tipo deve ser 'ciclica' ou 'geral'.", status=400)
    if cadencia not in ("diaria", "semanal", "mensal"):
        raise ApiError("cadencia deve ser 'diaria', 'semanal' ou 'mensal'.", status=400)

    percentual_itens = None
    if tipo == "ciclica":
        percentual_itens = dados.get("percentual_itens")
        if percentual_itens in (None, ""):
            raise ApiError(
                "Informe percentual_itens (tamanho da amostra a ser sorteada) para agendamentos do tipo 'ciclica'.",
                status=400,
            )
        try:
            percentual_itens = float(percentual_itens)
        except (TypeError, ValueError):
            raise ApiError("percentual_itens deve ser numérico.", status=400)
        if percentual_itens <= 0 or percentual_itens > 100:
            raise ApiError("percentual_itens deve estar entre 0 (exclusive) e 100.", status=400)
    # tipo == 'geral' ignora percentual_itens: uma contagem geral sempre
    # inclui tudo — não há amostra para sortear.

    dia_semana = None
    dia_mes = None
    if cadencia == "semanal":
        dia_semana = dados.get("dia_semana")
        try:
            dia_semana = int(dia_semana)
        except (TypeError, ValueError):
            raise ApiError("Informe dia_semana (0=segunda-feira ... 6=domingo) para cadência semanal.", status=400)
        if dia_semana < 0 or dia_semana > 6:
            raise ApiError("dia_semana deve estar entre 0 (segunda-feira) e 6 (domingo).", status=400)
    elif cadencia == "mensal":
        dia_mes = dados.get("dia_mes")
        try:
            dia_mes = int(dia_mes)
        except (TypeError, ValueError):
            raise ApiError("Informe dia_mes (1 a 31) para cadência mensal.", status=400)
        if dia_mes < 1 or dia_mes > 31:
            raise ApiError("dia_mes deve estar entre 1 e 31.", status=400)

    return {
        "tipo": tipo, "percentual_itens": percentual_itens, "cadencia": cadencia,
        "dia_semana": dia_semana, "dia_mes": dia_mes, "observacao": dados.get("observacao"),
    }


@bp.get("/agendamentos")
@requires_permission("estoque", "visualizar")
def listar_agendamentos_contagem():
    """Mesma filosofia da Fase 32: VER quais agendamentos existem e quando
    a próxima contagem automática deve nascer não é sensível — é liberado
    a quem já vê o módulo Estoque. Só CRIAR/EDITAR/EXCLUIR (abaixo) exige
    a permissão nova `agendar_contagem`."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT ag.*, u.nome AS unidade_nome
        FROM agendamentos_contagem ag
        JOIN unidades u ON u.id = ag.unidade_id
        ORDER BY ag.ativo DESC, ag.id DESC
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/agendamentos")
@requires_permission("estoque", "agendar_contagem")
def criar_agendamento_contagem():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    unidade_id = dados.get("unidade_id")
    if not unidade_id or not conn.execute("SELECT id FROM unidades WHERE id = ?", (unidade_id,)).fetchone():
        raise ApiError("Unidade não encontrada.", status=404)
    campos = _validar_campos_agendamento(dados)

    cur = conn.execute(
        """
        INSERT INTO agendamentos_contagem
            (unidade_id, tipo, percentual_itens, cadencia, dia_semana, dia_mes, observacao, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (unidade_id, campos["tipo"], campos["percentual_itens"], campos["cadencia"],
         campos["dia_semana"], campos["dia_mes"], campos["observacao"], usuario_atual["id"]),
    )
    agendamento_id = cur.lastrowid
    audit.registrar(conn, tabela="agendamentos_contagem", registro_id=agendamento_id, usuario_id=usuario_atual["id"],
                     acao="agendamento_contagem_criado", valor_novo={**campos, "unidade_id": unidade_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_agendamento_ou_404(conn, agendamento_id)), 201


@bp.put("/agendamentos/<int:agendamento_id>")
@requires_permission("estoque", "agendar_contagem")
def atualizar_agendamento_contagem(agendamento_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = _agendamento_ou_404(conn, agendamento_id)
    unidade_id = dados.get("unidade_id")
    if not unidade_id or not conn.execute("SELECT id FROM unidades WHERE id = ?", (unidade_id,)).fetchone():
        raise ApiError("Unidade não encontrada.", status=404)
    campos = _validar_campos_agendamento(dados)
    ativo = 1 if dados.get("ativo", bool(anterior["ativo"])) else 0

    conn.execute(
        """
        UPDATE agendamentos_contagem SET
            unidade_id = ?, tipo = ?, percentual_itens = ?, cadencia = ?, dia_semana = ?, dia_mes = ?,
            observacao = ?, ativo = ?, atualizado_por = ?, atualizado_em = ?
        WHERE id = ?
        """,
        (unidade_id, campos["tipo"], campos["percentual_itens"], campos["cadencia"],
         campos["dia_semana"], campos["dia_mes"], campos["observacao"], ativo,
         usuario_atual["id"], _now_iso(), agendamento_id),
    )
    audit.registrar(conn, tabela="agendamentos_contagem", registro_id=agendamento_id, usuario_id=usuario_atual["id"],
                     acao="agendamento_contagem_atualizado", valor_anterior=anterior,
                     valor_novo={**campos, "unidade_id": unidade_id, "ativo": ativo},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_agendamento_ou_404(conn, agendamento_id))


@bp.delete("/agendamentos/<int:agendamento_id>")
@requires_permission("estoque", "agendar_contagem")
def excluir_agendamento_contagem(agendamento_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    anterior = _agendamento_ou_404(conn, agendamento_id)
    conn.execute("DELETE FROM agendamentos_contagem WHERE id = ?", (agendamento_id,))
    audit.registrar(conn, tabela="agendamentos_contagem", registro_id=agendamento_id, usuario_id=usuario_atual["id"],
                     acao="agendamento_contagem_excluido", valor_anterior=anterior,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.post("/agendamentos/verificar")
@requires_permission("estoque", "contagem")
def verificar_agendamentos_contagem():
    """Chamada pela tela de Estoque a cada carregamento (Fase 35) — não é
    um cron de verdade (ver comentário no topo desta seção), é uma
    verificação oportunista: "algum agendamento está vencido agora?". Se
    estiver, gera a contagem na hora, com a origem já rotulada. Gatilho
    intencionalmente aberto a quem já tem `estoque.contagem` (não exige
    `agendar_contagem`, que é só para CADASTRAR/EDITAR a regra) — do
    mesmo jeito que qualquer operador do dia a dia poderia ter clicado em
    "Nova contagem" manualmente."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    hoje = datetime.date.today()
    ativos = conn.execute("SELECT * FROM agendamentos_contagem WHERE ativo = 1").fetchall()
    geradas = []
    for row in ativos:
        agendamento = dict(row)
        if _agendamento_esta_vencido_hoje(agendamento, hoje):
            contagem_id = _gerar_contagem_a_partir_do_agendamento(conn, agendamento, usuario_atual["id"])
            geradas.append(_contagem_detalhada(conn, contagem_id))
    return jsonify({"contagens_geradas": geradas})
