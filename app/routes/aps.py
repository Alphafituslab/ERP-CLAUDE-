"""
Fase 25 — APS (Advanced Planning and Scheduling): sequenciamento com
capacidade finita, por cima do PCP básico que já existia desde a Fase 3.

A Fase 3 já respondia "o que produzir e com que fórmula" (ordens de
produção) e "o material está disponível" (Fase 12, reserva real). O que
faltava — e é o núcleo de um APS de verdade — é "QUANDO, fisicamente,
cada ordem vai rodar, e em qual recurso", sem deixar agendar mais do que
o recurso aguenta ao mesmo tempo (capacidade finita). Esta fase entrega
essa fundação: cadastro de centros de trabalho (linhas, máquinas, salas)
com uma capacidade paralela, e o agendamento de uma ordem de produção
existente num centro de trabalho dentro de uma janela de tempo — com o
sistema recusando o agendamento se ele estourar a capacidade do centro
naquele intervalo.

Este módulo não substitui nem altera nada do PCP/MES da Fase 3: uma
ordem pode ser criada, liberada, ter consumo apontado e ser concluída
com ou sem agendamento algum — agendar é uma camada adicional, opcional,
por cima do que já existe.
"""
import datetime
import json

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission
from .compras import criar_pedido_compra_interno
from .estoque import saldo_total_disponivel_item
from .producao import _composicao_planejada

bp = Blueprint("aps", __name__, url_prefix="/api/v1/aps")

STATUS_AGENDAVEIS = ("planejada", "liberada", "em_producao")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_datetime_planejamento(valor, campo):
    """Aceita qualquer string ISO 8601 razoável vinda do formulário
    (`datetime-local` do navegador manda "AAAA-MM-DDTHH:MM", sem segundos
    nem fuso) e devolve sempre no mesmo formato normalizado
    "AAAA-MM-DDTHH:MM:SS", para que a comparação de sobreposição de
    agenda (feita como comparação de string, já que ambas as pontas usam
    o mesmo formato fixo) funcione de forma confiável."""
    if not valor or not isinstance(valor, str):
        raise ApiError(f"Informe {campo} num formato de data/hora válido.", status=400)
    texto = valor.strip()
    if texto.endswith("Z"):
        texto = texto[:-1]
    try:
        dt = datetime.datetime.fromisoformat(texto)
    except ValueError:
        raise ApiError(f"{campo} não é uma data/hora válida (esperado AAAA-MM-DDTHH:MM).", status=400)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _centro_trabalho_dict(row):
    return dict(row)


def _validar_taxa_hora_opcional(valor, campo):
    """Fase 30: `custo_hora_mao_de_obra`/`custo_hora_overhead` são
    OPCIONAIS (None = não informada — o centro continua funcionando
    normalmente para agendamento, só não entra no custeio da Fase 13).
    Quando informado, precisa ser um número >= 0."""
    if valor in (None, ""):
        return None
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ApiError(f"{campo} deve ser numérico.", status=400)
    if valor < 0:
        raise ApiError(f"{campo} não pode ser negativo.", status=400)
    return valor


def _centro_ou_404(conn, centro_trabalho_id):
    centro = conn.execute("SELECT * FROM centros_trabalho WHERE id = ?", (centro_trabalho_id,)).fetchone()
    if centro is None:
        raise ApiError("Centro de trabalho não encontrado.", status=404)
    return centro


def _ordem_ou_404(conn, ordem_id):
    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    return ordem


def _checar_capacidade(conn, centro_trabalho_id, inicio, fim, excluir_agendamento_id=None):
    """Conta quantos agendamentos já existentes nesse centro de trabalho
    se SOBREPÕEM ao intervalo [inicio, fim) pedido — duas janelas se
    sobrepõem quando uma começa antes da outra terminar e termina depois
    da outra começar (a checagem clássica de intervalo). Se a contagem já
    bate a capacidade paralela do centro, o agendamento é recusado — essa
    é a diferença entre um calendário comum e capacidade FINITA de
    verdade."""
    centro = _centro_ou_404(conn, centro_trabalho_id)
    if centro["status"] != "ativo":
        raise ApiError(
            f"O centro de trabalho '{centro['nome']}' está inativo e não pode receber novos agendamentos.",
            status=400,
        )

    query = """
        SELECT opa.*, op.numero AS ordem_numero
        FROM ordem_producao_agendamentos opa
        JOIN ordens_producao op ON op.id = opa.ordem_producao_id
        WHERE opa.centro_trabalho_id = ?
          AND opa.inicio_planejado < ? AND opa.fim_planejado > ?
    """
    params = [centro_trabalho_id, fim, inicio]
    if excluir_agendamento_id is not None:
        query += " AND opa.id != ?"
        params.append(excluir_agendamento_id)
    sobrepostos = conn.execute(query, params).fetchall()

    if len(sobrepostos) >= centro["capacidade_paralela"]:
        conflitos = ", ".join(f"{s['ordem_numero']} ({s['inicio_planejado']} a {s['fim_planejado']})" for s in sobrepostos)
        raise ApiError(
            f"Capacidade do centro de trabalho '{centro['nome']}' esgotada nesse período "
            f"(capacidade paralela: {centro['capacidade_paralela']}, já ocupada por: {conflitos}).",
            status=409,
            codigo="capacidade_esgotada",
        )
    return centro


# ---------------------------------------------------------------------------
# Centros de trabalho
# ---------------------------------------------------------------------------

@bp.get("/centros-trabalho")
@requires_permission("centros_trabalho", "visualizar")
def listar_centros_trabalho():
    conn = get_db()
    rows = conn.execute("SELECT * FROM centros_trabalho ORDER BY nome").fetchall()
    return jsonify([_centro_trabalho_dict(r) for r in rows])


@bp.get("/centros-trabalho/<int:centro_trabalho_id>")
@requires_permission("centros_trabalho", "visualizar")
def obter_centro_trabalho(centro_trabalho_id):
    conn = get_db()
    return jsonify(_centro_trabalho_dict(_centro_ou_404(conn, centro_trabalho_id)))


@bp.post("/centros-trabalho")
@requires_permission("centros_trabalho", "cadastrar")
def criar_centro_trabalho():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ApiError("Informe o nome do centro de trabalho.", status=400)

    capacidade_paralela = dados.get("capacidade_paralela", 1)
    try:
        capacidade_paralela = int(capacidade_paralela)
    except (TypeError, ValueError):
        raise ApiError("capacidade_paralela deve ser um número inteiro.", status=400)
    if capacidade_paralela < 1:
        raise ApiError("capacidade_paralela deve ser pelo menos 1.", status=400)

    # Fase 30: taxas de custo por hora, opcionais.
    custo_hora_mao_de_obra = _validar_taxa_hora_opcional(dados.get("custo_hora_mao_de_obra"), "custo_hora_mao_de_obra")
    custo_hora_overhead = _validar_taxa_hora_opcional(dados.get("custo_hora_overhead"), "custo_hora_overhead")

    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO centros_trabalho
            (nome, descricao, capacidade_paralela, custo_hora_mao_de_obra, custo_hora_overhead, criado_por, atualizado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (nome, (dados.get("descricao") or "").strip() or None, capacidade_paralela,
         custo_hora_mao_de_obra, custo_hora_overhead, usuario_atual["id"], usuario_atual["id"]),
    )
    centro_id = cur.lastrowid
    audit.registrar(conn, tabela="centros_trabalho", registro_id=centro_id, usuario_id=usuario_atual["id"],
                     acao="centro_trabalho_criado",
                     valor_novo={
                         "nome": nome, "capacidade_paralela": capacidade_paralela,
                         "custo_hora_mao_de_obra": custo_hora_mao_de_obra, "custo_hora_overhead": custo_hora_overhead,
                     },
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_centro_trabalho_dict(_centro_ou_404(conn, centro_id))), 201


@bp.put("/centros-trabalho/<int:centro_trabalho_id>")
@requires_permission("centros_trabalho", "editar")
def editar_centro_trabalho(centro_trabalho_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    centro = _centro_ou_404(conn, centro_trabalho_id)
    dados = request.get_json(silent=True) or {}

    nome = dados.get("nome", centro["nome"])
    if not (nome or "").strip():
        raise ApiError("nome não pode ficar vazio.", status=400)

    capacidade_paralela = dados.get("capacidade_paralela", centro["capacidade_paralela"])
    try:
        capacidade_paralela = int(capacidade_paralela)
    except (TypeError, ValueError):
        raise ApiError("capacidade_paralela deve ser um número inteiro.", status=400)
    if capacidade_paralela < 1:
        raise ApiError("capacidade_paralela deve ser pelo menos 1.", status=400)

    status = dados.get("status", centro["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    # Fase 30: taxas de custo por hora, opcionais — "não enviado" preserva
    # o valor atual (mesmo padrão de PUT parcial já usado pelos demais
    # campos deste endpoint); "enviado como vazio/null" limpa a taxa.
    if "custo_hora_mao_de_obra" in dados:
        custo_hora_mao_de_obra = _validar_taxa_hora_opcional(dados.get("custo_hora_mao_de_obra"), "custo_hora_mao_de_obra")
    else:
        custo_hora_mao_de_obra = centro["custo_hora_mao_de_obra"]
    if "custo_hora_overhead" in dados:
        custo_hora_overhead = _validar_taxa_hora_opcional(dados.get("custo_hora_overhead"), "custo_hora_overhead")
    else:
        custo_hora_overhead = centro["custo_hora_overhead"]

    conn.execute(
        """
        UPDATE centros_trabalho
        SET nome = ?, descricao = ?, capacidade_paralela = ?, status = ?,
            custo_hora_mao_de_obra = ?, custo_hora_overhead = ?,
            atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (nome.strip(), (dados.get("descricao", centro["descricao"]) or "").strip() or None,
         capacidade_paralela, status, custo_hora_mao_de_obra, custo_hora_overhead,
         _now_iso(), usuario_atual["id"], centro_trabalho_id),
    )
    audit.registrar(conn, tabela="centros_trabalho", registro_id=centro_trabalho_id, usuario_id=usuario_atual["id"],
                     acao="centro_trabalho_editado",
                     valor_anterior=dict(centro),
                     valor_novo={
                         "nome": nome.strip(), "capacidade_paralela": capacidade_paralela, "status": status,
                         "custo_hora_mao_de_obra": custo_hora_mao_de_obra, "custo_hora_overhead": custo_hora_overhead,
                     },
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_centro_trabalho_dict(_centro_ou_404(conn, centro_trabalho_id)))


# ---------------------------------------------------------------------------
# Agenda / agendamento de ordens de produção
# ---------------------------------------------------------------------------

def _agendamento_dict(row):
    return dict(row)


def _listar_agenda(conn, centro_trabalho_id=None, inicio=None, fim=None):
    query = """
        SELECT opa.*, op.numero AS ordem_numero, op.status AS ordem_status,
               op.quantidade_planejada, op.unidade,
               i.codigo AS item_codigo, i.descricao AS item_descricao,
               ct.nome AS centro_trabalho_nome
        FROM ordem_producao_agendamentos opa
        JOIN ordens_producao op ON op.id = opa.ordem_producao_id
        JOIN itens i ON i.id = op.item_produzido_id
        JOIN centros_trabalho ct ON ct.id = opa.centro_trabalho_id
        WHERE 1 = 1
    """
    params = []
    if centro_trabalho_id:
        query += " AND opa.centro_trabalho_id = ?"
        params.append(centro_trabalho_id)
    if inicio:
        query += " AND opa.fim_planejado > ?"
        params.append(inicio)
    if fim:
        query += " AND opa.inicio_planejado < ?"
        params.append(fim)
    query += " ORDER BY opa.inicio_planejado"
    return [_agendamento_dict(r) for r in conn.execute(query, params).fetchall()]


@bp.get("/agenda")
@requires_permission("aps", "visualizar")
def listar_agenda():
    conn = get_db()
    centro_trabalho_id = request.args.get("centro_trabalho_id", type=int)
    inicio = request.args.get("inicio")
    fim = request.args.get("fim")
    return jsonify(_listar_agenda(conn, centro_trabalho_id=centro_trabalho_id, inicio=inicio, fim=fim))


@bp.get("/ordens/<int:ordem_id>/agendamento")
@requires_permission("aps", "visualizar")
def obter_agendamento(ordem_id):
    conn = get_db()
    _ordem_ou_404(conn, ordem_id)
    row = conn.execute(
        """
        SELECT opa.*, ct.nome AS centro_trabalho_nome
        FROM ordem_producao_agendamentos opa
        JOIN centros_trabalho ct ON ct.id = opa.centro_trabalho_id
        WHERE opa.ordem_producao_id = ?
        """,
        (ordem_id,),
    ).fetchone()
    return jsonify(_agendamento_dict(row) if row else None)


@bp.post("/ordens/<int:ordem_id>/agendar")
@requires_permission("aps", "agendar")
def agendar_ordem(ordem_id):
    """Cria ou atualiza (reagenda) o agendamento de uma ordem de produção
    num centro de trabalho — é sempre um upsert num único registro por
    ordem, nunca acumula linhas antigas (ver nota na migração sobre por
    que este não é um ledger append-only)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    ordem = _ordem_ou_404(conn, ordem_id)
    if ordem["status"] not in STATUS_AGENDAVEIS:
        raise ApiError(
            f"Só é possível agendar uma ordem 'planejada', 'liberada' ou 'em_producao' "
            f"(status atual: '{ordem['status']}').",
            status=400,
        )

    dados = request.get_json(silent=True) or {}
    centro_trabalho_id = dados.get("centro_trabalho_id")
    if not centro_trabalho_id:
        raise ApiError("Informe centro_trabalho_id.", status=400)
    inicio = _parse_datetime_planejamento(dados.get("inicio_planejado"), "inicio_planejado")
    fim = _parse_datetime_planejamento(dados.get("fim_planejado"), "fim_planejado")
    if fim <= inicio:
        raise ApiError("fim_planejado deve ser depois de inicio_planejado.", status=400)

    existente = conn.execute(
        "SELECT * FROM ordem_producao_agendamentos WHERE ordem_producao_id = ?", (ordem_id,)
    ).fetchone()
    excluir_id = existente["id"] if existente else None

    _checar_capacidade(conn, centro_trabalho_id, inicio, fim, excluir_agendamento_id=excluir_id)

    if existente:
        conn.execute(
            """
            UPDATE ordem_producao_agendamentos
            SET centro_trabalho_id = ?, inicio_planejado = ?, fim_planejado = ?,
                atualizado_em = ?, atualizado_por = ?
            WHERE id = ?
            """,
            (centro_trabalho_id, inicio, fim, _now_iso(), usuario_atual["id"], existente["id"]),
        )
        acao = "ordem_reagendada"
        agendamento_id = existente["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO ordem_producao_agendamentos
                (ordem_producao_id, centro_trabalho_id, inicio_planejado, fim_planejado, criado_por, atualizado_por)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ordem_id, centro_trabalho_id, inicio, fim, usuario_atual["id"], usuario_atual["id"]),
        )
        acao = "ordem_agendada"
        agendamento_id = cur.lastrowid

    audit.registrar(conn, tabela="ordem_producao_agendamentos", registro_id=agendamento_id, usuario_id=usuario_atual["id"],
                     acao=acao,
                     valor_novo={"ordem_producao_id": ordem_id, "centro_trabalho_id": centro_trabalho_id,
                                 "inicio_planejado": inicio, "fim_planejado": fim},
                     ip=client_ip(), dispositivo=client_device())

    row = conn.execute(
        """
        SELECT opa.*, ct.nome AS centro_trabalho_nome
        FROM ordem_producao_agendamentos opa
        JOIN centros_trabalho ct ON ct.id = opa.centro_trabalho_id
        WHERE opa.id = ?
        """,
        (agendamento_id,),
    ).fetchone()
    return jsonify(_agendamento_dict(row)), 201 if acao == "ordem_agendada" else 200


@bp.delete("/ordens/<int:ordem_id>/agendar")
@requires_permission("aps", "agendar")
def desagendar_ordem(ordem_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _ordem_ou_404(conn, ordem_id)
    existente = conn.execute(
        "SELECT * FROM ordem_producao_agendamentos WHERE ordem_producao_id = ?", (ordem_id,)
    ).fetchone()
    if existente is None:
        raise ApiError("Esta ordem não tem agendamento para remover.", status=404)

    conn.execute("DELETE FROM ordem_producao_agendamentos WHERE id = ?", (existente["id"],))
    audit.registrar(conn, tabela="ordem_producao_agendamentos", registro_id=existente["id"], usuario_id=usuario_atual["id"],
                     acao="ordem_desagendada", valor_anterior=dict(existente),
                     ip=client_ip(), dispositivo=client_device())
    return "", 204


# ============================================================
# FASE 39 — MRP (Cálculo de Necessidade de Materiais)
# ============================================================
# A Fase 25 já garantia, ao LIBERAR uma ordem, que havia saldo real
# disponível para reservar a BOM inteira (senão recusa com 400) — mas
# isso só é descoberto ordem por ordem, no momento de liberar. Quem faz
# PCP/Compras precisa da pergunta inversa, ANTES disso: "somando a
# necessidade de todas as ordens ainda planejadas (não liberadas), o que
# vai faltar comprar?" — sobretudo quando duas ordens planejadas
# competem pelo mesmo insumo, e nenhuma das duas isolada mostraria o
# problema.
#
# Deliberadamente considera só ordens em status 'planejada': uma ordem
# 'liberada'/'em_producao' já RESERVOU de verdade seu material (Fase 12)
# — esse consumo futuro já está descontado do saldo disponível por
# `saldo_real_disponivel_producao`, então somar a composição delas de
# novo aqui contaria a mesma necessidade duas vezes. O que falta comprar
# é sempre em relação ao que ainda não foi garantido.
# FASE 57 — data mais próxima em que alguma das ordens (planejadas, que
# motivaram a necessidade deste item) precisa fisicamente rodar, segundo
# o agendamento do APS (Fase 25/28) — ou None se nenhuma das ordens
# relacionadas está agendada ainda. Deliberadamente NÃO tenta adivinhar
# uma data para ordem sem agendamento algum: "quando" a produção vai
# rodar é uma decisão do PCP (tela de Agenda Visual), não algo que o MRP
# deveria inventar.
def _data_necessidade_mais_proxima(conn, ordem_ids):
    if not ordem_ids:
        return None
    linhas = conn.execute(
        f"""
        SELECT MIN(inicio_planejado) AS data
        FROM ordem_producao_agendamentos
        WHERE ordem_producao_id IN ({','.join('?' for _ in ordem_ids)})
        """,
        ordem_ids,
    ).fetchone()
    return linhas["data"] if linhas else None


# FASE 57 — "até quando comprar" para não atrasar a ordem mais urgente:
# data de necessidade (acima) MENOS o lead time (em dias) do fornecedor
# sugerido. Só calcula quando as DUAS informações existem — nenhuma
# ordem relacionada tem agendamento, OU o fornecedor sugerido não tem
# lead_time_dias configurado, e o resultado é None (nenhuma data
# inventada a partir de informação que não existe).
def _data_limite_compra(data_necessidade_iso, lead_time_dias):
    if not data_necessidade_iso or lead_time_dias is None:
        return None
    data_necessidade = datetime.datetime.strptime(data_necessidade_iso[:10], "%Y-%m-%d").date()
    return (data_necessidade - datetime.timedelta(days=lead_time_dias)).isoformat()


def _calcular_mrp(conn):
    ordens_planejadas = conn.execute(
        "SELECT * FROM ordens_producao WHERE status = 'planejada' ORDER BY id"
    ).fetchall()

    por_item = {}
    for ordem_row in ordens_planejadas:
        ordem = dict(ordem_row)
        for componente in _composicao_planejada(conn, ordem):
            entrada = por_item.setdefault(componente["item_id"], {
                "item_id": componente["item_id"],
                "codigo": componente["codigo"],
                "descricao": componente["descricao"],
                "unidade": componente["unidade"],
                "necessidade_total": 0.0,
                "ordens": [],
            })
            entrada["necessidade_total"] = round(entrada["necessidade_total"] + componente["quantidade_planejada"], 6)
            entrada["ordens"].append({
                "ordem_producao_id": ordem["id"],
                "numero": ordem["numero"],
                "quantidade_necessaria": componente["quantidade_planejada"],
            })

    resultado = []
    for entrada in por_item.values():
        # Fase 87 — mesma agregação extraída para app/routes/estoque.py::
        # saldo_total_disponivel_item, reaproveitada aqui em vez de
        # duplicar a query lote a lote (agora também usada pelo alerta de
        # estoque mínimo em Itens).
        disponivel = saldo_total_disponivel_item(conn, entrada["item_id"])
        falta = round(max(0.0, entrada["necessidade_total"] - disponivel), 6)

        fornecedores = conn.execute(
            """
            SELECT f.id, f.nome, f.cnpj, f.lead_time_dias
            FROM item_fornecedor_aprovado ifa JOIN fornecedores f ON f.id = ifa.fornecedor_id
            WHERE ifa.item_id = ? AND f.status IN ('aprovado', 'aprovado_com_ressalva')
            ORDER BY f.nome
            """,
            (entrada["item_id"],),
        ).fetchall()
        fornecedores = [dict(f) for f in fornecedores]

        # Fase 57 — mesmo fornecedor "sugerido" (o primeiro homologado) já
        # usado pela Fase 54 ao gerar a sugestão de compra automática.
        fornecedor_sugerido = fornecedores[0] if fornecedores else None
        data_necessidade = _data_necessidade_mais_proxima(conn, [o["ordem_producao_id"] for o in entrada["ordens"]])
        data_limite_compra = _data_limite_compra(
            data_necessidade, fornecedor_sugerido["lead_time_dias"] if fornecedor_sugerido else None
        )

        resultado.append({
            **entrada,
            "disponivel": disponivel,
            "falta": falta,
            "fornecedores_homologados": fornecedores,
            "data_necessidade_mais_proxima": data_necessidade,
            "data_limite_compra": data_limite_compra,
        })

    resultado.sort(key=lambda r: (-r["falta"], r["codigo"] or ""))
    return resultado


@bp.get("/mrp")
@requires_permission("aps", "visualizar")
def obter_mrp():
    conn = get_db()
    itens = _calcular_mrp(conn)
    return jsonify({
        "gerado_em": _now_iso(),
        "total_itens": len(itens),
        "total_itens_em_falta": len([i for i in itens if i["falta"] > 0]),
        "itens": itens,
    })


# ============================================================
# FASE 54 — MRP: Sugestão Automática de Compra
# ============================================================
# Deliberadamente uma entidade PRÓPRIA, separada de `contas_pagar` — ver
# a nota completa no topo de migrations/schema_fase54.sql. Resumindo: uma
# sugestão de compra é uma PREVISÃO derivada do MRP (sem preço nem data de
# vencimento reais ainda), enquanto uma conta a pagar é uma obrigação
# financeira de verdade — misturar as duas contaminaria o Financeiro e o
# Fluxo de Caixa Projetado com números inventados.
def _sugestao_compra_detalhada(conn, row):
    d = dict(row)
    d["ordens_relacionadas"] = json.loads(d["ordens_relacionadas"])
    item = conn.execute("SELECT codigo, descricao, unidade_medida FROM itens WHERE id = ?", (d["item_id"],)).fetchone()
    d["item_codigo"] = item["codigo"] if item else None
    d["item_descricao"] = item["descricao"] if item else None
    d["item_unidade"] = item["unidade_medida"] if item else None
    if d["fornecedor_sugerido_id"]:
        fornecedor = conn.execute("SELECT nome, cnpj FROM fornecedores WHERE id = ?", (d["fornecedor_sugerido_id"],)).fetchone()
        d["fornecedor_sugerido_nome"] = fornecedor["nome"] if fornecedor else None
    else:
        d["fornecedor_sugerido_nome"] = None
    return d


def _sugestao_compra_ou_404(conn, sugestao_id):
    row = conn.execute("SELECT * FROM sugestoes_compra_mrp WHERE id = ?", (sugestao_id,)).fetchone()
    if row is None:
        raise ApiError("Sugestão de compra não encontrada.", status=404)
    return row


@bp.post("/mrp/gerar-sugestoes-compra")
@requires_permission("aps", "gerar_sugestao_compra")
def gerar_sugestoes_compra():
    """Recalcula o MRP (mesma função de `GET /mrp`, nunca dessincroniza) e
    cria uma sugestão `pendente` para cada item com falta > 0 — SALVO os
    que já têm uma sugestão `pendente` em aberto, para clicar no botão
    duas vezes seguidas não empilhar sugestões duplicadas do mesmo item
    (mesmo espírito de "não permite segunda solicitação pendente" da Fase
    22). Um item cuja sugestão anterior já foi decidida (atendida ou
    descartada) pode ganhar uma sugestão nova — a necessidade pode ter
    voltado a existir."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    itens_mrp = _calcular_mrp(conn)
    itens_em_falta = [i for i in itens_mrp if i["falta"] > 0]

    ja_pendentes = {
        row["item_id"]
        for row in conn.execute("SELECT DISTINCT item_id FROM sugestoes_compra_mrp WHERE status = 'pendente'").fetchall()
    }

    criadas = []
    puladas = []
    for item in itens_em_falta:
        if item["item_id"] in ja_pendentes:
            puladas.append({"item_id": item["item_id"], "codigo": item["codigo"], "motivo": "Já existe uma sugestão pendente para este item."})
            continue
        fornecedores = item.get("fornecedores_homologados") or []
        fornecedor_sugerido_id = fornecedores[0]["id"] if fornecedores else None
        cursor = conn.execute(
            """
            INSERT INTO sugestoes_compra_mrp
                (item_id, quantidade_sugerida, fornecedor_sugerido_id, ordens_relacionadas, gerada_por, data_limite_compra)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["item_id"], item["falta"], fornecedor_sugerido_id, json.dumps(item["ordens"]),
                usuario_atual["id"], item.get("data_limite_compra"),
            ),
        )
        conn.commit()
        sugestao_id = cursor.lastrowid
        audit.registrar(
            conn, tabela="sugestoes_compra_mrp", registro_id=sugestao_id, usuario_id=usuario_atual["id"],
            acao="sugestao_compra_gerada",
            valor_novo={"item_id": item["item_id"], "codigo": item["codigo"], "quantidade_sugerida": item["falta"]},
            ip=client_ip(), dispositivo=client_device(),
        )
        row = conn.execute("SELECT * FROM sugestoes_compra_mrp WHERE id = ?", (sugestao_id,)).fetchone()
        criadas.append(_sugestao_compra_detalhada(conn, row))

    return jsonify({"total_criadas": len(criadas), "criadas": criadas, "total_puladas": len(puladas), "puladas": puladas}), 201


@bp.get("/sugestoes-compra")
@requires_permission("aps", "visualizar")
def listar_sugestoes_compra():
    conn = get_db()
    status_filtro = request.args.get("status")
    if status_filtro:
        if status_filtro not in ("pendente", "atendida", "descartada"):
            raise ApiError("status deve ser 'pendente', 'atendida' ou 'descartada'.", status=400)
        rows = conn.execute(
            "SELECT * FROM sugestoes_compra_mrp WHERE status = ? ORDER BY id DESC", (status_filtro,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sugestoes_compra_mrp ORDER BY id DESC").fetchall()
    return jsonify([_sugestao_compra_detalhada(conn, r) for r in rows])


@bp.post("/sugestoes-compra/<int:sugestao_id>/atender")
@requires_permission("aps", "decidir_sugestao_compra")
def atender_sugestao_compra(sugestao_id):
    """Marca a sugestão como atendida — Compras já providenciou a compra
    (dentro ou fora do sistema). `conta_pagar_id` é OPCIONAL: se a conta a
    pagar já foi lançada pela tela de Financeiro (Fase 6), linkar aqui dá
    rastreabilidade completa; se ainda não foi (ex.: compra fechada mas
    nota fiscal só chega depois), a sugestão pode ser atendida sem link
    nenhum por ora."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    sugestao = _sugestao_compra_ou_404(conn, sugestao_id)
    if sugestao["status"] != "pendente":
        raise ApiError(f"Esta sugestão já foi decidida (status atual: '{sugestao['status']}').", status=400)

    conta_pagar_id = dados.get("conta_pagar_id")
    if conta_pagar_id:
        conta = conn.execute("SELECT id FROM contas_pagar WHERE id = ?", (conta_pagar_id,)).fetchone()
        if conta is None:
            raise ApiError("conta_pagar_id informado não corresponde a nenhuma conta a pagar.", status=404)

    conn.execute(
        """
        UPDATE sugestoes_compra_mrp
        SET status = 'atendida', decidida_em = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
            decidida_por = ?, conta_pagar_id = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], conta_pagar_id, sugestao_id),
    )
    conn.commit()
    audit.registrar(
        conn, tabela="sugestoes_compra_mrp", registro_id=sugestao_id, usuario_id=usuario_atual["id"],
        acao="sugestao_compra_atendida", valor_novo={"conta_pagar_id": conta_pagar_id},
        ip=client_ip(), dispositivo=client_device(),
    )
    row = conn.execute("SELECT * FROM sugestoes_compra_mrp WHERE id = ?", (sugestao_id,)).fetchone()
    return jsonify(_sugestao_compra_detalhada(conn, row))


# ============================================================
# FASE 58 — gerar um Pedido de Compra formal a partir da sugestão
# ============================================================
# Segunda forma de "atender" uma sugestão pendente (a primeira,
# `POST .../atender` acima, linkando só um `conta_pagar_id`, continua
# existindo sem nenhuma mudança — para compras fechadas fora deste fluxo
# novo). Aqui, gerar o pedido JÁ conta como a decisão: a sugestão vira
# "atendida" automaticamente, com o pedido novo linkado em
# `pedido_compra_id` — não faz sentido pedir para Compras clicar em dois
# botões separados ("gerar pedido" e depois "atender") para a mesma
# decisão.
@bp.post("/sugestoes-compra/<int:sugestao_id>/gerar-pedido-compra")
@requires_permission("compras", "criar_pedido")
def gerar_pedido_compra_a_partir_da_sugestao(sugestao_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    sugestao = _sugestao_compra_ou_404(conn, sugestao_id)
    if sugestao["status"] != "pendente":
        raise ApiError(f"Esta sugestão já foi decidida (status atual: '{sugestao['status']}').", status=400)

    # fornecedor_id é OPCIONAL no corpo da requisição: por padrão usa o
    # fornecedor sugerido pelo próprio MRP (Fase 54) — mas Compras pode
    # escolher outro fornecedor homologado na hora de gerar o pedido,
    # sem precisar editar a sugestão em si.
    fornecedor_id = dados.get("fornecedor_id") or sugestao["fornecedor_sugerido_id"]
    if not fornecedor_id:
        raise ApiError(
            "Esta sugestão não tem fornecedor sugerido (nenhum fornecedor homologado para o item) — "
            "informe fornecedor_id explicitamente.",
            status=400,
        )

    item = conn.execute("SELECT unidade_medida FROM itens WHERE id = ?", (sugestao["item_id"],)).fetchone()
    item_payload = [{
        "item_id": sugestao["item_id"],
        "quantidade_pedida": sugestao["quantidade_sugerida"],
        "unidade": item["unidade_medida"] if item else "un",
        "preco_unitario": dados.get("preco_unitario"),
        "sugestao_compra_mrp_id": sugestao_id,
    }]

    pedido_id = criar_pedido_compra_interno(
        conn, usuario_atual, fornecedor_id, item_payload, observacoes=dados.get("observacoes")
    )

    conn.execute(
        """
        UPDATE sugestoes_compra_mrp
        SET status = 'atendida', decidida_em = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
            decidida_por = ?, pedido_compra_id = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], pedido_id, sugestao_id),
    )
    conn.commit()
    audit.registrar(
        conn, tabela="sugestoes_compra_mrp", registro_id=sugestao_id, usuario_id=usuario_atual["id"],
        acao="sugestao_compra_atendida_via_pedido", valor_novo={"pedido_compra_id": pedido_id},
        ip=client_ip(), dispositivo=client_device(),
    )

    from .compras import _pedido_detalhado
    return jsonify(_pedido_detalhado(conn, pedido_id)), 201


@bp.post("/sugestoes-compra/<int:sugestao_id>/descartar")
@requires_permission("aps", "decidir_sugestao_compra")
def descartar_sugestao_compra(sugestao_id):
    """Marca a sugestão como descartada — Compras avaliou e decidiu não
    comprar por ora (ex.: ordem planejada será cancelada, insumo será
    substituído). Exige motivo, mesmo padrão de toda ação que encerra uma
    pendência sem executar a ação original neste sistema."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do descarte.", status=400)

    sugestao = _sugestao_compra_ou_404(conn, sugestao_id)
    if sugestao["status"] != "pendente":
        raise ApiError(f"Esta sugestão já foi decidida (status atual: '{sugestao['status']}').", status=400)

    conn.execute(
        """
        UPDATE sugestoes_compra_mrp
        SET status = 'descartada', decidida_em = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
            decidida_por = ?, motivo_descarte = ?
        WHERE id = ?
        """,
        (usuario_atual["id"], motivo, sugestao_id),
    )
    conn.commit()
    audit.registrar(
        conn, tabela="sugestoes_compra_mrp", registro_id=sugestao_id, usuario_id=usuario_atual["id"],
        acao="sugestao_compra_descartada", motivo=motivo,
        ip=client_ip(), dispositivo=client_device(),
    )
    row = conn.execute("SELECT * FROM sugestoes_compra_mrp WHERE id = ?", (sugestao_id,)).fetchone()
    return jsonify(_sugestao_compra_detalhada(conn, row))
