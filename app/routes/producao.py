import datetime
import secrets
import sqlite3

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission
from .estoque import saldo_real_disponivel_producao
from .lotes import _gerar_codigo_lote

bp = Blueprint("producao", __name__, url_prefix="/api/v1/producao/ordens")

STATUS_QUE_PERMITEM_CONSUMO = ("liberada", "em_producao")
LOTES_CONSUMIVEIS = ("aprovado", "aprovado_com_ressalva")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hoje_iso_data():
    """Fase 65 — mesmo padrão de `_hoje_iso_data` em app/routes/compras.py:
    só a parte de data (sem hora), para comparar contra `validade` (que
    também é só data) sem fuso horário entrar no meio."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _gerar_numero_ordem():
    ano = datetime.datetime.utcnow().year
    return f"OP-{ano}-{secrets.token_hex(4).upper()}"


def _quantidade_disponivel(conn, lote_id, excluir_ordem_id=None):
    """Quantidade do lote que uma ordem de produção ainda pode consumir —
    Fase 12: deixou de olhar só para `ordem_producao_consumo` (o que já
    foi apontado) e passou a usar a disponibilidade REAL compartilhada
    com Estoque e Comercial (`saldo_real_disponivel_producao`, em
    estoque.py), que também desconta o que já foi vendido (reserva de
    venda confirmada), baixado/ajustado no estoque, e o que outras ordens
    de produção liberadas já reservaram. `excluir_ordem_id` deixa de fora
    a própria reserva da ordem que está consumindo — ela pode consumir
    até o que ELA MESMA garantiu, sem se autobloquear."""
    return saldo_real_disponivel_producao(conn, lote_id, excluir_ordem_id=excluir_ordem_id)


def _composicao_planejada(conn, ordem):
    """Composição (BOM) da fórmula desta ordem, já multiplicada pelo
    fator quantidade_planejada/rendimento_teorico — mesmo cálculo usado
    em `_ordem_detalhada` (agora extraído para cá porque a Fase 12
    também precisa dele em `liberar()`, antes de a ordem existir com todo
    o resto dos dados derivados)."""
    composicao = conn.execute(
        """
        SELECT fi.item_id, i.codigo, i.descricao, fi.quantidade AS quantidade_por_lote_teorico, fi.unidade
        FROM formula_itens fi JOIN itens i ON i.id = fi.item_id
        WHERE fi.formula_id = ? ORDER BY fi.id
        """,
        (ordem["formula_id"],),
    ).fetchall()
    rendimento = conn.execute(
        "SELECT rendimento_teorico FROM formulas WHERE id = ?", (ordem["formula_id"],)
    ).fetchone()["rendimento_teorico"]
    fator = ordem["quantidade_planejada"] / rendimento
    return [
        {**dict(c), "quantidade_planejada": round(c["quantidade_por_lote_teorico"] * fator, 6)} for c in composicao
    ]


def _alocar_fefo_producao(conn, item_id, quantidade_necessaria, excluir_ordem_id=None):
    """Aloca a quantidade necessária de um item-insumo contra os lotes
    aprovados desse item, priorizando o que vence primeiro (FEFO) — mesmo
    princípio de `_alocar_fefo` em comercial.py, mas por LOTE (não por
    posição de WMS, já que Produção nunca exigiu endereçamento para
    consumir). Devolve (alocacoes, quantidade_coberta).

    Fase 65 — mesmo raciocínio de `_alocar_fefo` em comercial.py: um lote
    com `validade` já passada nunca entra aqui, mesmo aprovado e com saldo
    físico positivo. Antes desta fase, um insumo vencido podia ser
    consumido normalmente numa ordem de produção (a ordenação por
    validade só priorizava, nunca impedia) — um bug real de conformidade."""
    lotes = conn.execute(
        """
        SELECT id, validade FROM lotes
        WHERE item_id = ? AND status IN ('aprovado', 'aprovado_com_ressalva')
          AND (validade IS NULL OR validade >= ?)
        ORDER BY (validade IS NULL), validade ASC, id ASC
        """,
        (item_id, _hoje_iso_data()),
    ).fetchall()

    alocacoes = []
    restante = quantidade_necessaria
    for lote in lotes:
        if restante <= 0.0000001:
            break
        disponivel = saldo_real_disponivel_producao(conn, lote["id"], excluir_ordem_id=excluir_ordem_id)
        if disponivel <= 0.0000001:
            continue
        quantidade = min(disponivel, restante)
        alocacoes.append({"lote_id": lote["id"], "quantidade": quantidade})
        restante -= quantidade
    return alocacoes, quantidade_necessaria - restante


def _etapas_da_ordem(conn, ordem_id):
    """Fase 50 — lista as etapas do processo cadastradas para esta ordem,
    em ordem de execução (`sequencia`). Lista vazia para qualquer ordem
    que não usa esse recurso opcional — é o caso da imensa maioria das
    ordens já existentes antes desta fase.

    Fase 75 — o LEFT JOIN com `tipos_etapa_producao` traz `unidade_valor`
    (contexto de que unidade o `valor_registrado` da etapa é, ex.: "kg"),
    e `situacao` é DERIVADA aqui mesmo (nunca gravada em coluna própria —
    ver o comentário completo em migrations/schema_fase75.sql sobre por
    que "em andamento" não é um novo valor de `status`), para o frontend
    (tanto a tela de detalhe da ordem quanto o Painel de Chão de Fábrica
    em app/routes/painel_tempo_real.py) não precisar reimplementar essa
    regra em JavaScript."""
    rows = conn.execute(
        """
        SELECT oe.*, tep.unidade_valor AS tipo_unidade_valor
        FROM ordem_producao_etapas oe
        LEFT JOIN tipos_etapa_producao tep ON tep.id = oe.tipo_etapa_id
        WHERE oe.ordem_producao_id = ?
        ORDER BY oe.sequencia
        """,
        (ordem_id,),
    ).fetchall()
    etapas = []
    for r in rows:
        etapa = dict(r)
        if etapa["status"] == "concluida":
            etapa["situacao"] = "concluida"
        elif etapa["iniciado_em"]:
            etapa["situacao"] = "em_andamento"
        else:
            etapa["situacao"] = "pendente"
        etapas.append(etapa)
    return etapas


def _etapa_ou_404(conn, ordem_id, etapa_id):
    row = conn.execute(
        "SELECT * FROM ordem_producao_etapas WHERE id = ? AND ordem_producao_id = ?", (etapa_id, ordem_id)
    ).fetchone()
    if row is None:
        raise ApiError("Etapa não encontrada nesta ordem de produção.", status=404)
    return row


def _ordem_ou_404(conn, ordem_id):
    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    return ordem


def _empresa_ou_404(conn, empresa_id):
    """Fase 52 — valida um `empresa_id` opcional informado na criação de
    uma ordem (ou no filtro do Painel Gerencial, em relatorios.py, que tem
    sua própria cópia deste helper). Reaproveitado em vez de importar
    entre módulos de rota para não criar acoplamento cruzado só por um
    SELECT de 3 linhas."""
    empresa = conn.execute("SELECT id FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if empresa is None:
        raise ApiError("Empresa não encontrada.", status=404)


def _ordem_detalhada(conn, ordem_id):
    row = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if row is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    ordem = dict(row)

    formula = conn.execute(
        "SELECT i.codigo, i.descricao FROM itens i WHERE i.id = ?", (ordem["item_produzido_id"],)
    ).fetchone()
    ordem["item_produzido_codigo"] = formula["codigo"] if formula else None
    ordem["item_produzido_descricao"] = formula["descricao"] if formula else None

    # Fase 52 — empresa_id é opcional (ver schema_fase52.sql); a maioria
    # das ordens continua sem nenhuma, então `empresa_nome` vem None nesse
    # caso, sem levantar erro.
    if ordem["empresa_id"]:
        empresa = conn.execute(
            "SELECT nome_fantasia, razao_social FROM empresas WHERE id = ?", (ordem["empresa_id"],)
        ).fetchone()
        ordem["empresa_nome"] = (empresa["nome_fantasia"] or empresa["razao_social"]) if empresa else None
    else:
        ordem["empresa_nome"] = None

    ordem["composicao_planejada"] = _composicao_planejada(conn, ordem)

    consumos = conn.execute(
        """
        SELECT opc.*, l.codigo_lote, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM ordem_producao_consumo opc
        JOIN lotes l ON l.id = opc.lote_id
        JOIN itens i ON i.id = opc.item_id
        WHERE opc.ordem_producao_id = ? ORDER BY opc.id
        """,
        (ordem_id,),
    ).fetchall()
    ordem["consumos"] = [dict(c) for c in consumos]

    # Fase 12 — reservas de material garantidas ao liberar a ordem
    # (ativas enquanto a ordem estiver 'liberada'/'em_producao'; ver
    # `_reservado_producao_lote` em estoque.py para como elas deixam de
    # contar sem precisar apagar o histórico).
    reservas = conn.execute(
        """
        SELECT opr.*, l.codigo_lote, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM ordem_producao_reservas opr
        JOIN lotes l ON l.id = opr.lote_id
        JOIN itens i ON i.id = opr.item_id
        WHERE opr.ordem_producao_id = ? ORDER BY opr.id
        """,
        (ordem_id,),
    ).fetchall()
    ordem["reservas_material"] = [dict(r) for r in reservas]

    # Fase 50 — Apontamento de perda/refugo por ETAPA do processo:
    # opcional — uma ordem sem nenhuma etapa cadastrada não muda em nada
    # (lista vazia, comportamento de conclusão idêntico ao de sempre).
    ordem["etapas"] = _etapas_da_ordem(conn, ordem_id)

    if ordem["lote_produzido_id"]:
        lote_produzido = conn.execute("SELECT * FROM lotes WHERE id = ?", (ordem["lote_produzido_id"],)).fetchone()
        ordem["lote_produzido"] = dict(lote_produzido) if lote_produzido else None
    else:
        ordem["lote_produzido"] = None

    # Fase 9 — Apontamento de perdas/refugo: indicadores derivados,
    # calculados sempre na hora a partir das colunas gravadas em
    # /concluir (nunca armazenados), só fazem sentido para ordens já
    # concluídas (quantidade_produzida preenchida).
    if ordem["quantidade_produzida"] is not None:
        total_processado = ordem["quantidade_produzida"] + (ordem["quantidade_perda"] or 0)
        ordem["percentual_perda"] = (
            round((ordem["quantidade_perda"] or 0) / total_processado * 100, 2) if total_processado > 0 else 0.0
        )
        ordem["percentual_rendimento_planejado"] = round(
            ordem["quantidade_produzida"] / ordem["quantidade_planejada"] * 100, 2
        )
    else:
        ordem["percentual_perda"] = None
        ordem["percentual_rendimento_planejado"] = None

    return ordem


@bp.get("")
@requires_permission("producao", "visualizar")
def listar():
    conn = get_db()
    status = request.args.get("status")
    if status:
        rows = conn.execute(
            """
            SELECT op.*, i.codigo AS item_produzido_codigo, i.descricao AS item_produzido_descricao
            FROM ordens_producao op JOIN itens i ON i.id = op.item_produzido_id
            WHERE op.status = ? ORDER BY op.id DESC
            """,
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT op.*, i.codigo AS item_produzido_codigo, i.descricao AS item_produzido_descricao
            FROM ordens_producao op JOIN itens i ON i.id = op.item_produzido_id
            ORDER BY op.id DESC
            """
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:ordem_id>")
@requires_permission("producao", "visualizar")
def obter(ordem_id):
    conn = get_db()
    return jsonify(_ordem_detalhada(conn, ordem_id))


@bp.post("")
@requires_permission("producao", "planejar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    formula_id = dados.get("formula_id")
    quantidade_planejada = dados.get("quantidade_planejada")
    unidade = dados.get("unidade")
    # Fase 52 — opcional, sem valor padrão (ver schema_fase52.sql): quando
    # informado, é o que permite esta ordem entrar no filtro por empresa
    # do Painel Gerencial (bloco Produção). Omitido, a ordem fica sem
    # empresa (comportamento de sempre, sem mudança nenhuma).
    empresa_id = dados.get("empresa_id")
    conn = get_db()

    if not formula_id or not quantidade_planejada or not unidade:
        raise ApiError("Informe formula_id, quantidade_planejada e unidade.", status=400)
    if empresa_id is not None:
        _empresa_ou_404(conn, empresa_id)

    formula = conn.execute("SELECT * FROM formulas WHERE id = ?", (formula_id,)).fetchone()
    if formula is None:
        raise ApiError("Fórmula não encontrada.", status=404)
    if formula["status"] != "ativa":
        raise ApiError(
            f"Só é possível abrir uma ordem de produção a partir de uma fórmula ativa (status atual: '{formula['status']}').",
            status=400,
        )

    numero = _gerar_numero_ordem()
    cur = conn.execute(
        """
        INSERT INTO ordens_producao (numero, formula_id, item_produzido_id, quantidade_planejada, unidade, empresa_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (numero, formula_id, formula["item_produzido_id"], quantidade_planejada, unidade, empresa_id, usuario_atual["id"]),
    )
    ordem_id = cur.lastrowid
    audit.registrar(conn, tabela="ordens_producao", registro_id=ordem_id, usuario_id=usuario_atual["id"],
                     acao="ordem_criada", valor_novo={"numero": numero, "formula_id": formula_id, "quantidade_planejada": quantidade_planejada},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id)), 201


@bp.post("/<int:ordem_id>/liberar")
@requires_permission("producao", "liberar")
def liberar(ordem_id):
    """Fase 12: além de mudar o status, agora RESERVA de verdade (FEFO,
    por lote) o material da composição (BOM) desta ordem — fecha a
    lacuna documentada desde a Fase 3 de duas ordens liberadas ao mesmo
    tempo competirem pelo mesmo saldo até a primeira apontar consumo. Se
    não houver saldo real disponível (já descontando o que Comercial e o
    próprio Estoque já comprometeram — ver `saldo_real_disponivel_producao`
    em estoque.py) para cobrir a BOM inteira, a liberação é recusada."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    if ordem["status"] != "planejada":
        raise ApiError(f"Só é possível liberar uma ordem com status 'planejada' (status atual: '{ordem['status']}').", status=400)
    ordem = dict(ordem)

    composicao = _composicao_planejada(conn, ordem)
    alocacoes_por_item = {}
    faltas = []
    for componente in composicao:
        alocacoes, coberto = _alocar_fefo_producao(conn, componente["item_id"], componente["quantidade_planejada"])
        if coberto + 0.0000001 < componente["quantidade_planejada"]:
            faltas.append(
                f"{componente['codigo']} — {componente['descricao']} "
                f"(precisa {componente['quantidade_planejada']} {componente['unidade']}, "
                f"disponível {round(coberto, 6)} {componente['unidade']})"
            )
        else:
            alocacoes_por_item[componente["item_id"]] = alocacoes

    if faltas:
        raise ApiError(
            "Não há saldo real disponível para reservar todo o material desta ordem ao liberar "
            "(considerando o que já foi consumido em outras ordens, vendido em pedidos confirmados, "
            "baixado/ajustado no estoque, já reservado por outra ordem liberada, ou vencido — lotes vencidos "
            "não contam mais como disponíveis, Fase 65): " + "; ".join(faltas) + ".",
            status=400,
        )

    # Fase 73: mesmo com a checagem acima dizendo "cabe", outra requisição
    # concorrente (outra ordem sendo liberada, ou um pedido de venda sendo
    # confirmado ao mesmo tempo) pode ter comprometido o mesmo lote entre a
    # leitura e esta escrita — o trigger `trg_ordem_producao_reservas_
    # bloqueia_saldo_negativo` (schema_fase73.sql) garante isso a nível de
    # banco. Como um `raise ApiError` não desfaz escritas já feitas nesta
    # requisição e ordem_producao_reservas é append-only (sem DELETE
    # possível no except), um SAVEPOINT desfaz só as reservas já inseridas
    # nesta tentativa antes de propagar o erro.
    resumo_reservas = []
    conn.execute("SAVEPOINT reserva_ordem_producao")
    try:
        for item_id, alocacoes in alocacoes_por_item.items():
            for alocacao in alocacoes:
                conn.execute(
                    """
                    INSERT INTO ordem_producao_reservas (ordem_producao_id, item_id, lote_id, quantidade, criado_por)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ordem_id, item_id, alocacao["lote_id"], alocacao["quantidade"], usuario_atual["id"]),
                )
                resumo_reservas.append({"item_id": item_id, "lote_id": alocacao["lote_id"], "quantidade": alocacao["quantidade"]})
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK TO SAVEPOINT reserva_ordem_producao")
        conn.execute("RELEASE SAVEPOINT reserva_ordem_producao")
        raise ApiError(
            "Não foi possível reservar o material desta ordem — outra liberação de ordem (ou confirmação de "
            "pedido de venda) concorrente provavelmente comprometeu o mesmo lote ao mesmo tempo, e o saldo não "
            "é mais suficiente. Nenhuma reserva foi feita para esta ordem. Consulte o saldo disponível e tente "
            "liberar de novo.",
            status=409,
        )
    conn.execute("RELEASE SAVEPOINT reserva_ordem_producao")

    conn.execute(
        "UPDATE ordens_producao SET status = 'liberada', liberado_em = ?, liberado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], ordem_id),
    )
    audit.registrar(conn, tabela="ordens_producao", registro_id=ordem_id, usuario_id=usuario_atual["id"],
                     acao="ordem_liberada", valor_anterior={"status": "planejada"},
                     valor_novo={"status": "liberada", "reservas": resumo_reservas},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id))


@bp.post("/<int:ordem_id>/consumir")
@requires_permission("producao", "apontar")
def consumir(ordem_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    lote_id = dados.get("lote_id")
    quantidade = dados.get("quantidade")
    conn = get_db()

    if not lote_id or not quantidade:
        raise ApiError("Informe lote_id e quantidade.", status=400)
    try:
        quantidade = float(quantidade)
    except (TypeError, ValueError):
        raise ApiError("quantidade deve ser numérica.", status=400)
    if quantidade <= 0:
        raise ApiError("quantidade deve ser maior que zero.", status=400)

    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    if ordem["status"] not in STATUS_QUE_PERMITEM_CONSUMO:
        raise ApiError(
            f"Só é possível apontar consumo em uma ordem 'liberada' ou 'em_producao' (status atual: '{ordem['status']}').",
            status=400,
        )

    lote = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if lote is None:
        raise ApiError("Lote não encontrado.", status=404)
    if lote["status"] not in LOTES_CONSUMIVEIS:
        raise ApiError(
            f"Só é possível consumir um lote aprovado (status atual: '{lote['status']}'). "
            "Um lote em quarentena, em análise, reprovado ou bloqueado não pode ser usado em produção.",
            status=403,
        )

    linha_bom = conn.execute(
        "SELECT * FROM formula_itens WHERE formula_id = ? AND item_id = ?", (ordem["formula_id"], lote["item_id"])
    ).fetchone()
    if linha_bom is None:
        raise ApiError(
            "O item deste lote não faz parte da composição (BOM) da fórmula desta ordem.",
            status=400,
        )

    disponivel = _quantidade_disponivel(conn, lote_id, excluir_ordem_id=ordem_id)
    if quantidade > disponivel:
        raise ApiError(
            f"Quantidade solicitada ({quantidade}) maior que a disponível no lote {lote['codigo_lote']} "
            f"({disponivel} {lote['unidade']}, considerando consumo já apontado em outras ordens, "
            "reserva ativa de venda ou de outra ordem de produção, e saída já baixada/ajustada no estoque).",
            status=400,
        )

    cur = conn.execute(
        """
        INSERT INTO ordem_producao_consumo (ordem_producao_id, lote_id, item_id, quantidade, unidade, registrado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ordem_id, lote_id, lote["item_id"], quantidade, lote["unidade"], usuario_atual["id"]),
    )
    consumo_id = cur.lastrowid

    if ordem["status"] == "liberada":
        conn.execute("UPDATE ordens_producao SET status = 'em_producao' WHERE id = ?", (ordem_id,))

    audit.registrar(conn, tabela="ordem_producao_consumo", registro_id=consumo_id, usuario_id=usuario_atual["id"],
                     acao="consumo_registrado",
                     valor_novo={"ordem_producao_id": ordem_id, "lote_id": lote_id, "quantidade": quantidade},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id)), 201


# ============================================================
# FASE 50 — Apontamento de perda/refugo por ETAPA do processo
# ============================================================
# Recurso opcional: uma ordem que nunca cadastra nenhuma etapa continua
# apontando a perda de forma agregada, direto no POST /concluir, do jeito
# de sempre (Fase 9) — nada muda para ela. Quem cadastrar ao menos uma
# etapa passa a apontar a perda (se houver) EM CADA etapa, e a perda
# agregada da ordem passa a ser calculada automaticamente como a soma das
# etapas — ver validação em `concluir()` mais abaixo.
@bp.get("/<int:ordem_id>/etapas")
@requires_permission("producao", "visualizar")
def listar_etapas(ordem_id):
    conn = get_db()
    _ordem_ou_404(conn, ordem_id)
    return jsonify(_etapas_da_ordem(conn, ordem_id))


@bp.post("/<int:ordem_id>/etapas")
@requires_permission("producao", "apontar")
def criar_etapa(ordem_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    # Fase 75 — `tipo_etapa_id` é opcional: quem escolhe um tipo do
    # catálogo (Pesagem, Mistura, etc.) ganha o nome automaticamente dele
    # se não digitar um `nome` próprio; quem não informa nada continua no
    # fluxo 100% livre da Fase 50 (nome digitado na hora, sem catálogo).
    tipo_etapa_id = dados.get("tipo_etapa_id") or None
    tipo_etapa = None
    if tipo_etapa_id is not None:
        try:
            tipo_etapa_id = int(tipo_etapa_id)
        except (TypeError, ValueError):
            raise ApiError("tipo_etapa_id deve ser um número inteiro.", status=400)
        tipo_etapa = conn.execute(
            "SELECT * FROM tipos_etapa_producao WHERE id = ? AND status = 'ativo'", (tipo_etapa_id,)
        ).fetchone()
        if tipo_etapa is None:
            raise ApiError("Tipo de etapa não encontrado ou inativo.", status=404)

    nome = (dados.get("nome") or "").strip()
    if not nome and tipo_etapa is not None:
        nome = tipo_etapa["nome"]
    if not nome:
        raise ApiError("Informe nome (ou tipo_etapa_id, para usar o nome do catálogo).", status=400)

    ordem = _ordem_ou_404(conn, ordem_id)
    if ordem["status"] not in STATUS_QUE_PERMITEM_CONSUMO:
        raise ApiError(
            "Só é possível cadastrar uma etapa em uma ordem 'liberada' ou 'em_producao' "
            f"(status atual: '{ordem['status']}').",
            status=400,
        )

    sequencia = dados.get("sequencia")
    if sequencia in (None, ""):
        proxima = conn.execute(
            "SELECT COALESCE(MAX(sequencia), 0) + 1 AS proxima FROM ordem_producao_etapas WHERE ordem_producao_id = ?",
            (ordem_id,),
        ).fetchone()["proxima"]
        sequencia = proxima
    else:
        try:
            sequencia = int(sequencia)
        except (TypeError, ValueError):
            raise ApiError("sequencia deve ser um número inteiro.", status=400)
        if sequencia <= 0:
            raise ApiError("sequencia deve ser maior que zero.", status=400)
        if conn.execute(
            "SELECT id FROM ordem_producao_etapas WHERE ordem_producao_id = ? AND sequencia = ?",
            (ordem_id, sequencia),
        ).fetchone():
            raise ApiError(f"Já existe uma etapa com sequência {sequencia} nesta ordem.", status=409)

    cur = conn.execute(
        """
        INSERT INTO ordem_producao_etapas (ordem_producao_id, sequencia, nome, tipo_etapa_id, criado_por)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ordem_id, sequencia, nome, tipo_etapa_id, usuario_atual["id"]),
    )
    etapa_id = cur.lastrowid
    audit.registrar(conn, tabela="ordem_producao_etapas", registro_id=etapa_id, usuario_id=usuario_atual["id"],
                     acao="etapa_cadastrada",
                     valor_novo={"ordem_producao_id": ordem_id, "sequencia": sequencia, "nome": nome,
                                 "tipo_etapa_id": tipo_etapa_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id)), 201


@bp.post("/<int:ordem_id>/etapas/<int:etapa_id>/iniciar")
@requires_permission("producao", "apontar")
def iniciar_etapa(ordem_id, etapa_id):
    """Fase 75 — botão "Iniciar" no tablet do setor: marca o instante em
    que o operador começou de fato a etapa (`iniciado_em`/`iniciado_por`),
    sem mexer em `status` (continua 'pendente' — "em andamento" é só
    `status = 'pendente' AND iniciado_em IS NOT NULL`, calculado na hora,
    nunca um valor novo gravado; ver o comentário completo em
    migrations/schema_fase75.sql sobre por que não é um novo CHECK). É a
    partir daqui que dá pra calcular quanto tempo uma etapa como "Mistura"
    levou de verdade: `concluido_em` menos `iniciado_em`, os dois só
    timestamps, sem duração guardada à parte para não dessincronizar."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    ordem = _ordem_ou_404(conn, ordem_id)
    if ordem["status"] not in STATUS_QUE_PERMITEM_CONSUMO:
        raise ApiError(
            "Só é possível iniciar uma etapa em uma ordem 'liberada' ou 'em_producao' "
            f"(status atual: '{ordem['status']}').",
            status=400,
        )
    etapa = _etapa_ou_404(conn, ordem_id, etapa_id)
    if etapa["status"] != "pendente":
        raise ApiError("Esta etapa já foi concluída.", status=400)
    if etapa["iniciado_em"]:
        raise ApiError("Esta etapa já foi iniciada.", status=400)

    agora = _now_iso()
    conn.execute(
        "UPDATE ordem_producao_etapas SET iniciado_em = ?, iniciado_por = ? WHERE id = ?",
        (agora, usuario_atual["id"], etapa_id),
    )
    audit.registrar(conn, tabela="ordem_producao_etapas", registro_id=etapa_id, usuario_id=usuario_atual["id"],
                     acao="etapa_iniciada",
                     valor_novo={"ordem_producao_id": ordem_id, "nome": etapa["nome"], "iniciado_em": agora},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id))


@bp.put("/<int:ordem_id>/etapas/<int:etapa_id>")
@requires_permission("producao", "apontar")
def editar_etapa(ordem_id, etapa_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    conn = get_db()

    if not nome:
        raise ApiError("Informe nome.", status=400)

    _ordem_ou_404(conn, ordem_id)
    etapa = _etapa_ou_404(conn, ordem_id, etapa_id)
    if etapa["status"] != "pendente":
        raise ApiError("Só é possível editar uma etapa ainda 'pendente' (esta já foi concluída).", status=400)

    conn.execute("UPDATE ordem_producao_etapas SET nome = ? WHERE id = ?", (nome, etapa_id))
    audit.registrar(conn, tabela="ordem_producao_etapas", registro_id=etapa_id, usuario_id=usuario_atual["id"],
                     acao="etapa_editada", valor_anterior={"nome": etapa["nome"]}, valor_novo={"nome": nome},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id))


@bp.delete("/<int:ordem_id>/etapas/<int:etapa_id>")
@requires_permission("producao", "apontar")
def excluir_etapa(ordem_id, etapa_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _ordem_ou_404(conn, ordem_id)
    etapa = _etapa_ou_404(conn, ordem_id, etapa_id)
    if etapa["status"] != "pendente":
        raise ApiError("Só é possível excluir uma etapa ainda 'pendente' (esta já foi concluída).", status=400)

    conn.execute("DELETE FROM ordem_producao_etapas WHERE id = ?", (etapa_id,))
    audit.registrar(conn, tabela="ordem_producao_etapas", registro_id=etapa_id, usuario_id=usuario_atual["id"],
                     acao="etapa_excluida",
                     valor_anterior={"ordem_producao_id": ordem_id, "sequencia": etapa["sequencia"], "nome": etapa["nome"]},
                     ip=client_ip(), dispositivo=client_device())
    return "", 204


@bp.post("/<int:ordem_id>/etapas/<int:etapa_id>/concluir")
@requires_permission("producao", "apontar")
def concluir_etapa(ordem_id, etapa_id):
    """Aponta a perda (se houver) desta etapa específica e a marca como
    'concluida' — mesma regra de sempre da Fase 9 (perda >= 0, motivo
    obrigatório só quando perda > 0), só que agora no nível da etapa, não
    da ordem inteira."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    quantidade_perda = dados.get("quantidade_perda", 0)
    motivo_perda = (dados.get("motivo_perda") or "").strip()
    conn = get_db()

    if quantidade_perda in (None, ""):
        quantidade_perda = 0
    try:
        quantidade_perda = float(quantidade_perda)
    except (TypeError, ValueError):
        raise ApiError("quantidade_perda deve ser numérica.", status=400)
    if quantidade_perda < 0:
        raise ApiError("quantidade_perda não pode ser negativa.", status=400)
    if quantidade_perda > 0 and not motivo_perda:
        raise ApiError("Informe motivo_perda quando houver quantidade_perda maior que zero.", status=400)

    # Fase 75 — valor específico da etapa (ex.: quantos kg pesou de
    # verdade na Pesagem), opcional e sem relação nenhuma com perda/refugo
    # — ver o comentário completo em migrations/schema_fase75.sql.
    valor_registrado = dados.get("valor_registrado")
    if valor_registrado in (None, ""):
        valor_registrado = None
    else:
        try:
            valor_registrado = float(valor_registrado)
        except (TypeError, ValueError):
            raise ApiError("valor_registrado deve ser numérico.", status=400)

    ordem = _ordem_ou_404(conn, ordem_id)
    if ordem["status"] not in STATUS_QUE_PERMITEM_CONSUMO:
        raise ApiError(
            "Só é possível concluir uma etapa em uma ordem 'liberada' ou 'em_producao' "
            f"(status atual: '{ordem['status']}').",
            status=400,
        )
    etapa = _etapa_ou_404(conn, ordem_id, etapa_id)
    if etapa["status"] != "pendente":
        raise ApiError("Esta etapa já foi concluída.", status=400)

    conn.execute(
        """
        UPDATE ordem_producao_etapas
        SET status = 'concluida', quantidade_perda = ?, motivo_perda = ?, valor_registrado = ?,
            concluido_em = ?, concluido_por = ?
        WHERE id = ?
        """,
        (quantidade_perda, motivo_perda or None, valor_registrado, _now_iso(), usuario_atual["id"], etapa_id),
    )
    audit.registrar(conn, tabela="ordem_producao_etapas", registro_id=etapa_id, usuario_id=usuario_atual["id"],
                     acao="etapa_concluida",
                     valor_novo={"ordem_producao_id": ordem_id, "nome": etapa["nome"],
                                 "quantidade_perda": quantidade_perda, "motivo_perda": motivo_perda or None,
                                 "valor_registrado": valor_registrado},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id))


@bp.post("/<int:ordem_id>/concluir")
@requires_permission("producao", "apontar")
def concluir(ordem_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    quantidade_produzida = dados.get("quantidade_produzida")
    # Fase 9 — Apontamento de perdas/refugo: campo opcional, com default 0
    # para não quebrar nenhum chamador que já concluía ordens do jeito
    # antigo (sem informar perda nenhuma).
    quantidade_perda = dados.get("quantidade_perda", 0)
    motivo_perda = (dados.get("motivo_perda") or "").strip()
    # Fase 30 — Custo de Mão de Obra e Overhead: mesmo padrão da Fase 9
    # (campo opcional na conclusão, sem quebrar quem já concluía ordens
    # sem informar nada). Não tenta inferir horas a partir de
    # liberado_em/concluido_em — ver comentário em migrations/schema_fase30.sql.
    horas_apontadas = dados.get("horas_apontadas")
    conn = get_db()

    if not quantidade_produzida:
        raise ApiError("Informe quantidade_produzida.", status=400)
    try:
        quantidade_produzida = float(quantidade_produzida)
    except (TypeError, ValueError):
        raise ApiError("quantidade_produzida deve ser numérica.", status=400)
    if quantidade_produzida <= 0:
        raise ApiError("quantidade_produzida deve ser maior que zero.", status=400)

    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    if ordem["status"] != "em_producao":
        raise ApiError(
            "Só é possível concluir uma ordem 'em_producao' (registre ao menos um consumo antes) "
            f"(status atual: '{ordem['status']}').",
            status=400,
        )

    # Fase 50 — quando a ordem tem ao menos uma etapa cadastrada, a perda
    # agregada passa a ser a SOMA das etapas (todas precisam estar
    # 'concluida' antes de poder concluir a ordem) — apontar
    # quantidade_perda/motivo_perda diretamente aqui deixaria de fazer
    # sentido (duas fontes de verdade para o mesmo número), por isso é
    # rejeitado explicitamente em vez de ser silenciosamente ignorado. Uma
    # ordem sem nenhuma etapa continua 100% no fluxo antigo da Fase 9.
    etapas = _etapas_da_ordem(conn, ordem_id)
    if etapas:
        if "quantidade_perda" in dados or "motivo_perda" in dados:
            raise ApiError(
                "Esta ordem tem etapas cadastradas — a perda agregada é somada automaticamente a partir "
                "das etapas concluídas. Não informe quantidade_perda/motivo_perda aqui: aponte a perda de "
                "cada etapa em POST /producao/ordens/<id>/etapas/<etapa_id>/concluir.",
                status=400,
            )
        pendentes = [e["nome"] for e in etapas if e["status"] != "concluida"]
        if pendentes:
            raise ApiError(
                f"Existem etapas ainda pendentes nesta ordem: {', '.join(pendentes)}. "
                "Conclua todas as etapas antes de concluir a ordem.",
                status=400,
            )
        quantidade_perda = sum(e["quantidade_perda"] for e in etapas)
        partes_motivo = [
            f"{e['nome']}: {e['quantidade_perda']} ({e['motivo_perda']})" if e["motivo_perda"] else f"{e['nome']}: {e['quantidade_perda']}"
            for e in etapas if e["quantidade_perda"] > 0
        ]
        motivo_perda = "Perda apurada por etapa — " + "; ".join(partes_motivo) if partes_motivo else ""
    else:
        if quantidade_perda in (None, ""):
            quantidade_perda = 0
        try:
            quantidade_perda = float(quantidade_perda)
        except (TypeError, ValueError):
            raise ApiError("quantidade_perda deve ser numérica.", status=400)
        if quantidade_perda < 0:
            raise ApiError("quantidade_perda não pode ser negativa.", status=400)
        if quantidade_perda > 0 and not motivo_perda:
            raise ApiError("Informe motivo_perda quando houver quantidade_perda maior que zero.", status=400)

    if horas_apontadas in ("",):
        horas_apontadas = None
    if horas_apontadas is not None:
        try:
            horas_apontadas = float(horas_apontadas)
        except (TypeError, ValueError):
            raise ApiError("horas_apontadas deve ser numérico.", status=400)
        if horas_apontadas < 0:
            raise ApiError("horas_apontadas não pode ser negativo.", status=400)

    # O lote produzido nasce em quarentena, exatamente como um lote
    # recebido de fornecedor (Fase 2) — precisa passar por análise e
    # aprovação antes de poder ser usado/vendido. origem='producao' e
    # ordem_producao_id fecham a genealogia "para trás": a partir deste
    # lote dá para navegar até a ordem e, dela, até cada lote consumido.
    temp_codigo = f"TEMP-{secrets.token_hex(8)}"
    cur = conn.execute(
        """
        INSERT INTO lotes (codigo_lote, item_id, quantidade, unidade, status, origem, ordem_producao_id, criado_por)
        VALUES (?, ?, ?, ?, 'quarentena', 'producao', ?, ?)
        """,
        (temp_codigo, ordem["item_produzido_id"], quantidade_produzida, dados.get("unidade") or ordem["unidade"],
         ordem_id, usuario_atual["id"]),
    )
    lote_id = cur.lastrowid
    codigo_lote = _gerar_codigo_lote(conn, lote_id)
    conn.execute("UPDATE lotes SET codigo_lote = ? WHERE id = ?", (codigo_lote, lote_id))

    conn.execute(
        """
        UPDATE ordens_producao
        SET status = 'concluida', quantidade_produzida = ?, quantidade_perda = ?, motivo_perda = ?,
            horas_apontadas = ?, lote_produzido_id = ?, concluido_em = ?, concluido_por = ?
        WHERE id = ?
        """,
        (quantidade_produzida, quantidade_perda, motivo_perda or None, horas_apontadas,
         lote_id, _now_iso(), usuario_atual["id"], ordem_id),
    )

    audit.registrar(conn, tabela="ordens_producao", registro_id=ordem_id, usuario_id=usuario_atual["id"],
                     acao="ordem_concluida",
                     valor_novo={
                         "quantidade_produzida": quantidade_produzida,
                         "quantidade_perda": quantidade_perda,
                         "motivo_perda": motivo_perda or None,
                         "horas_apontadas": horas_apontadas,
                         "lote_produzido_id": lote_id,
                     },
                     ip=client_ip(), dispositivo=client_device())
    audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                     acao="lote_produzido", valor_novo={"codigo_lote": codigo_lote, "ordem_producao_id": ordem_id, "status": "quarentena"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id))


@bp.post("/<int:ordem_id>/cancelar")
@requires_permission("producao", "planejar")
def cancelar(ordem_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)

    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    if ordem["status"] in ("concluida", "cancelada"):
        raise ApiError(f"Não é possível cancelar uma ordem com status '{ordem['status']}'.", status=400)
    if ordem["status"] == "em_producao":
        raise ApiError(
            "Esta ordem já tem consumo de material apontado (em_producao) e não pode mais ser cancelada — "
            "conclua-a normalmente para preservar a rastreabilidade do material já consumido.",
            status=400,
        )

    conn.execute(
        "UPDATE ordens_producao SET status = 'cancelada', motivo_cancelamento = ? WHERE id = ?",
        (motivo, ordem_id),
    )
    audit.registrar(conn, tabela="ordens_producao", registro_id=ordem_id, usuario_id=usuario_atual["id"],
                     acao="ordem_cancelada", valor_anterior={"status": ordem["status"]}, valor_novo={"status": "cancelada"},
                     motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify(_ordem_detalhada(conn, ordem_id))
