"""Fase 76 — Painel Executivo (visão "Power BI" da empresa).

Pedido do cliente: um painel visual, moderno e em tempo real — nos moldes de
um dashboard tipo Power BI — mostrando pedidos novos, pedidos faturados,
onde cada processo está acontecendo agora, desempenho de cada vendedor,
quais regiões estão subindo/caindo em faturamento e quais clientes não
estão sendo atendidos num período. Também expõe, por Ordem de Produção, a
linha do tempo completa do processo (emissão → ... → faturamento) com o
tempo gasto em cada etapa.

Mesma filosofia da Fase 75 (`painel_tempo_real.py`): nada fica pré-calculado
em tabela nova — tudo é montado na hora a partir das tabelas que já
existem — e a filtragem é POR SEÇÃO dentro da view, reaproveitando as
permissões operacionais que já existem (`comercial.visualizar`,
`producao.visualizar`) em vez de um cadastro novo de "setor" ou uma
permissão única de tudo-ou-nada.

Convenções de "vendido" vs "faturado" (documentando a divergência de
propósito, no mesmo espírito do comentário em `relatorios.py::_bloco_
periodo` sobre `atualizado_em` ser uma aproximação):
  - "Total Vendido" soma `pedido_venda_itens.quantidade * preco_unitario`
    de pedidos com status 'confirmado' OU 'expedido' (a venda já está
    comprometida, mesmo que a nota fiscal ainda não tenha sido emitida) —
    é um número mais amplo que o `valor_total_expedido` do Painel
    Gerencial, que conta só 'expedido'. Os dois painéis respondem
    perguntas diferentes de propósito ("o que já vendemos" vs "o que já
    saiu fisicamente"), então divergem por design, não por bug.
  - "Total Faturado" soma `notas_fiscais.valor_total` das notas com
    status 'autorizada' — é a Receita Federal quem manda aqui, não o
    status do pedido.

Datas de período usam sempre `criado_em` de cada tabela (quando o pedido/
nota foi criado) — mais simples e mais previsível para quem está olhando
"o que aconteceu em Março" do que perseguir uma data de mudança de status
por tabela, e já é dado que a Fase 52/42 mostrou ser a convenção mais fácil
de explicar num painel visual como este."""

import datetime

from flask import Blueprint, g, jsonify, request

from ..context import ApiError, get_db
from ..permissions import requires_auth, usuario_tem_permissao
from .producao import _etapas_da_ordem

bp = Blueprint("painel_executivo", __name__, url_prefix="/api/v1/painel-executivo")

STATUS_VENDA_COMPUTAVEIS = ("confirmado", "expedido")

# Mapa fixo UF -> Região (não muda, não precisa de tabela/migração — as 27
# UFs do Brasil são uma lista fechada). Um `uf` ausente (clientes cadastrados
# antes da Fase 70, ver schema_fase70.sql) cai no balde "Não informado" em
# vez de quebrar a agregação.
UF_REGIAO = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte", "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste", "PB": "Nordeste",
    "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste", "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste", "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _intervalo(ano, mes=None):
    """Devolve (inicio, fim) em ISO 8601 cobrindo o ano inteiro, ou só o
    mês informado, sempre com o fim no último instante do dia/mês (mesma
    convenção de 'T23:59:59.999999Z' usada em relatorios.py::_bloco_periodo)."""
    if mes:
        inicio = datetime.date(ano, mes, 1)
        if mes == 12:
            fim = datetime.date(ano, 12, 31)
        else:
            fim = datetime.date(ano, mes + 1, 1) - datetime.timedelta(days=1)
    else:
        inicio = datetime.date(ano, 1, 1)
        fim = datetime.date(ano, 12, 31)
    return f"{inicio.isoformat()}T00:00:00.000000Z", f"{fim.isoformat()}T23:59:59.999999Z"


def _regiao(uf):
    return UF_REGIAO.get((uf or "").upper(), "Não informado")


def _kpis(conn, inicio, fim):
    total_vendido = conn.execute(
        f"""
        SELECT COALESCE(SUM(pvi.quantidade * pvi.preco_unitario), 0) AS total
        FROM pedido_venda_itens pvi
        JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
        WHERE pv.status IN ({",".join("?" * len(STATUS_VENDA_COMPUTAVEIS))})
          AND pv.criado_em BETWEEN ? AND ?
        """,
        (*STATUS_VENDA_COMPUTAVEIS, inicio, fim),
    ).fetchone()["total"]

    total_faturado = conn.execute(
        "SELECT COALESCE(SUM(valor_total), 0) AS total FROM notas_fiscais "
        "WHERE status = 'autorizada' AND criado_em BETWEEN ? AND ?",
        (inicio, fim),
    ).fetchone()["total"]

    pedidos_novos = conn.execute(
        "SELECT COUNT(*) AS total FROM pedidos_venda WHERE criado_em BETWEEN ? AND ?", (inicio, fim)
    ).fetchone()["total"]

    notas_emitidas = conn.execute(
        "SELECT COUNT(*) AS total FROM notas_fiscais WHERE status = 'autorizada' AND criado_em BETWEEN ? AND ?",
        (inicio, fim),
    ).fetchone()["total"]

    clientes_ativos = conn.execute("SELECT COUNT(*) AS total FROM clientes WHERE status = 'ativo'").fetchone()["total"]
    clientes_com_pedido = conn.execute(
        "SELECT COUNT(DISTINCT cliente_id) AS total FROM pedidos_venda "
        "WHERE status != 'cancelado' AND criado_em BETWEEN ? AND ?",
        (inicio, fim),
    ).fetchone()["total"]
    cobertura_clientes_pct = round((clientes_com_pedido / clientes_ativos * 100), 1) if clientes_ativos else 0.0

    return {
        "total_vendido": round(total_vendido, 2),
        "total_faturado": round(total_faturado, 2),
        "pedidos_novos": pedidos_novos,
        "notas_emitidas": notas_emitidas,
        "clientes_ativos": clientes_ativos,
        "clientes_com_pedido_no_periodo": clientes_com_pedido,
        "cobertura_clientes_pct": cobertura_clientes_pct,
    }


def _vendas_por_mes(conn, ano):
    inicio, fim = _intervalo(ano)
    rows = conn.execute(
        f"""
        SELECT CAST(strftime('%m', pv.criado_em) AS INTEGER) AS mes,
               COALESCE(SUM(pvi.quantidade * pvi.preco_unitario), 0) AS total
        FROM pedidos_venda pv
        JOIN pedido_venda_itens pvi ON pvi.pedido_id = pv.id
        WHERE pv.status IN ({",".join("?" * len(STATUS_VENDA_COMPUTAVEIS))})
          AND pv.criado_em BETWEEN ? AND ?
        GROUP BY mes
        """,
        (*STATUS_VENDA_COMPUTAVEIS, inicio, fim),
    ).fetchall()
    por_mes = {r["mes"]: r["total"] for r in rows}
    return [{"mes": m, "total": round(por_mes.get(m, 0.0), 2)} for m in range(1, 13)]


def _vendedores_ranking(conn, inicio, fim, limite=10):
    rows = conn.execute(
        f"""
        SELECT u.id, u.nome,
               COALESCE(SUM(pvi.quantidade * pvi.preco_unitario), 0) AS total,
               COUNT(DISTINCT pv.id) AS total_pedidos
        FROM pedidos_venda pv
        JOIN pedido_venda_itens pvi ON pvi.pedido_id = pv.id
        JOIN usuarios u ON u.id = pv.vendedor_id
        WHERE pv.vendedor_id IS NOT NULL
          AND pv.status IN ({",".join("?" * len(STATUS_VENDA_COMPUTAVEIS))})
          AND pv.criado_em BETWEEN ? AND ?
        GROUP BY u.id
        ORDER BY total DESC
        LIMIT ?
        """,
        (*STATUS_VENDA_COMPUTAVEIS, inicio, fim, limite),
    ).fetchall()
    return [
        {"vendedor_id": r["id"], "nome": r["nome"], "total": round(r["total"], 2), "total_pedidos": r["total_pedidos"]}
        for r in rows
    ]


def _total_por_regiao(conn, inicio, fim):
    rows = conn.execute(
        f"""
        SELECT c.uf, COALESCE(SUM(pvi.quantidade * pvi.preco_unitario), 0) AS total
        FROM pedidos_venda pv
        JOIN pedido_venda_itens pvi ON pvi.pedido_id = pv.id
        JOIN clientes c ON c.id = pv.cliente_id
        WHERE pv.status IN ({",".join("?" * len(STATUS_VENDA_COMPUTAVEIS))})
          AND pv.criado_em BETWEEN ? AND ?
        GROUP BY c.uf
        """,
        (*STATUS_VENDA_COMPUTAVEIS, inicio, fim),
    ).fetchall()
    totais = {}
    for r in rows:
        regiao = _regiao(r["uf"])
        totais[regiao] = totais.get(regiao, 0.0) + r["total"]
    return totais


def _regioes_com_tendencia(conn, ano, mes):
    """Compara o período selecionado com o MESMO período do ano anterior
    (mesmo mês, se filtrado; ano inteiro anterior, senão) — a comparação
    ano-contra-ano é a que faz sentido para 'subiu ou caiu o faturamento',
    já que evita comparar Dezembro (alta sazonal) com Janeiro."""
    inicio, fim = _intervalo(ano, mes)
    inicio_ant, fim_ant = _intervalo(ano - 1, mes)
    atual = _total_por_regiao(conn, inicio, fim)
    anterior = _total_por_regiao(conn, inicio_ant, fim_ant)

    regioes = sorted(set(atual) | set(anterior))
    resultado = []
    for regiao in regioes:
        total_atual = round(atual.get(regiao, 0.0), 2)
        total_anterior = round(anterior.get(regiao, 0.0), 2)
        if total_anterior > 0:
            variacao_pct = round((total_atual - total_anterior) / total_anterior * 100, 1)
        elif total_atual > 0:
            variacao_pct = 100.0
        else:
            variacao_pct = 0.0
        resultado.append({
            "regiao": regiao,
            "total_atual": total_atual,
            "total_ano_anterior": total_anterior,
            "variacao_pct": variacao_pct,
            "tendencia": "subindo" if variacao_pct > 0 else ("caindo" if variacao_pct < 0 else "estavel"),
        })
    resultado.sort(key=lambda r: r["total_atual"], reverse=True)
    return resultado


def _funil_pedidos(conn, inicio, fim):
    """Classifica cada pedido de venda (não cancelado) do período num
    balde do funil pedido pelo cliente: novo / em produção / em
    finalização / aguardando faturamento / faturado. A prioridade abaixo
    importa — um pedido já faturado fica em 'faturado' mesmo que a OP
    vinculada ainda apareça como 'em_producao' por algum motivo raro
    (ex.: uma segunda leva do mesmo lote)."""
    rows = conn.execute(
        """
        SELECT
            pv.id, pv.status,
            EXISTS(
                SELECT 1 FROM notas_fiscais nf WHERE nf.pedido_id = pv.id AND nf.status = 'autorizada'
            ) AS tem_nf,
            EXISTS(
                SELECT 1
                FROM pedido_venda_itens pvi
                JOIN pedido_venda_reservas pvr ON pvr.pedido_item_id = pvi.id
                JOIN lotes l ON l.id = pvr.lote_id
                JOIN ordens_producao op ON op.id = l.ordem_producao_id
                WHERE pvi.pedido_id = pv.id AND op.status = 'em_producao'
            ) AS tem_op_em_producao,
            EXISTS(
                SELECT 1
                FROM pedido_venda_itens pvi
                JOIN pedido_venda_reservas pvr ON pvr.pedido_item_id = pvi.id
                JOIN lotes l ON l.id = pvr.lote_id
                JOIN ordens_producao op ON op.id = l.ordem_producao_id
                WHERE pvi.pedido_id = pv.id AND op.status = 'concluida'
            ) AS tem_op_concluida
        FROM pedidos_venda pv
        WHERE pv.status != 'cancelado' AND pv.criado_em BETWEEN ? AND ?
        """,
        (inicio, fim),
    ).fetchall()

    baldes = {"novo": 0, "em_producao": 0, "em_finalizacao": 0, "aguardando_faturamento": 0, "faturado": 0}
    for r in rows:
        if r["tem_nf"]:
            baldes["faturado"] += 1
        elif r["status"] == "expedido":
            baldes["aguardando_faturamento"] += 1
        elif r["tem_op_em_producao"]:
            baldes["em_producao"] += 1
        elif r["tem_op_concluida"]:
            baldes["em_finalizacao"] += 1
        else:
            baldes["novo"] += 1
    return baldes


def _clientes_sem_atendimento(conn, inicio, fim, limite=20):
    rows = conn.execute(
        """
        SELECT c.id, c.razao_social, c.nome_fantasia, c.uf,
               (SELECT MAX(pv.criado_em) FROM pedidos_venda pv
                WHERE pv.cliente_id = c.id AND pv.status != 'cancelado') AS ultimo_pedido_em
        FROM clientes c
        WHERE c.status = 'ativo'
        """
    ).fetchall()

    agora = _now_iso()
    sem_atendimento = []
    for r in rows:
        ultimo = r["ultimo_pedido_em"]
        if ultimo is not None and inicio <= ultimo <= fim:
            continue  # atendido dentro do próprio período — não entra na lista
        if ultimo is None:
            dias_sem_pedido = None
        else:
            try:
                dt_ultimo = datetime.datetime.strptime(ultimo[:10], "%Y-%m-%d")
                dt_agora = datetime.datetime.strptime(agora[:10], "%Y-%m-%d")
                dias_sem_pedido = (dt_agora - dt_ultimo).days
            except ValueError:
                dias_sem_pedido = None
        sem_atendimento.append({
            "cliente_id": r["id"],
            "nome": r["nome_fantasia"] or r["razao_social"],
            "uf": r["uf"],
            "ultimo_pedido_em": ultimo,
            "dias_sem_pedido": dias_sem_pedido,
        })

    sem_atendimento.sort(key=lambda c: (c["dias_sem_pedido"] is None, -(c["dias_sem_pedido"] or 0)), reverse=False)
    # nunca comprou (dias_sem_pedido None) primeiro, depois do mais tempo sem comprar para o menos tempo
    sem_atendimento.sort(key=lambda c: (c["ultimo_pedido_em"] is not None, c["ultimo_pedido_em"] or ""))
    return sem_atendimento[:limite]


def _status_ordens_producao(conn):
    rows = conn.execute(
        "SELECT status, COUNT(*) AS total FROM ordens_producao WHERE status != 'cancelada' GROUP BY status"
    ).fetchall()
    return {r["status"]: r["total"] for r in rows}


def _ordens_em_andamento(conn, limite=12):
    rows = conn.execute(
        """
        SELECT op.id, op.numero, op.status, op.criado_em, op.liberado_em,
               i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM ordens_producao op
        JOIN itens i ON i.id = op.item_produzido_id
        WHERE op.status IN ('liberada', 'em_producao')
        ORDER BY op.id DESC
        LIMIT ?
        """,
        (limite,),
    ).fetchall()
    resultado = []
    for r in rows:
        ordem = dict(r)
        etapas = _etapas_da_ordem(conn, r["id"])
        ordem["total_etapas"] = len(etapas)
        ordem["etapas_concluidas"] = len([e for e in etapas if e["situacao"] == "concluida"])
        resultado.append(ordem)
    return resultado


@bp.get("")
@requires_auth
def painel_executivo():
    usuario_atual = g.usuario_atual
    conn = get_db()

    ano = request.args.get("ano", type=int) or datetime.datetime.utcnow().year
    mes = request.args.get("mes", type=int)
    if mes is not None and not (1 <= mes <= 12):
        raise ApiError("mes deve estar entre 1 e 12.", status=400)

    inicio, fim = _intervalo(ano, mes)

    resposta = {
        "periodo": {"ano": ano, "mes": mes, "inicio": inicio, "fim": fim},
        "secoes": [],
    }

    if usuario_tem_permissao(conn, usuario_atual["id"], "comercial", "visualizar"):
        resposta["secoes"].append({
            "chave": "comercial",
            "titulo": "Vendas & Faturamento",
            "kpis": _kpis(conn, inicio, fim),
            "vendas_por_mes": _vendas_por_mes(conn, ano),
            "vendedores_ranking": _vendedores_ranking(conn, inicio, fim),
            "regioes": _regioes_com_tendencia(conn, ano, mes),
            "funil_pedidos": _funil_pedidos(conn, inicio, fim),
            "clientes_sem_atendimento": _clientes_sem_atendimento(conn, inicio, fim),
        })

    if usuario_tem_permissao(conn, usuario_atual["id"], "producao", "visualizar"):
        resposta["secoes"].append({
            "chave": "producao",
            "titulo": "Produção — Visão Geral",
            "status_ordens": _status_ordens_producao(conn),
            "ordens_em_andamento": _ordens_em_andamento(conn),
        })

    return jsonify(resposta)


# ============================================================
# Linha do tempo completa de uma Ordem de Produção
# ============================================================
# Pedido do cliente: "quero ver o caminho da OP: emissão, separação de
# matéria-prima, pesagem, mistura, liberação, análises, encapsulamento,
# envase, rotulagem, pronto para baixa, liberado faturamento — e quanto
# tempo em cada etapa". Isso atravessa 3 módulos que não têm uma tabela
# única em comum (Produção, Qualidade/Análises, Fiscal/NFe), então este
# endpoint busca em cada um e monta uma linha do tempo ordenada por data —
# não existe uma tabela nova aqui, é 100% derivado na hora, mesmo espírito
# do Painel de Chão de Fábrica (Fase 75).
#
# Duas aproximações documentadas (mesmo padrão já usado em
# relatorios.py::_bloco_periodo para o mesmo problema):
#   - "Separação de matéria-prima" não tem um botão próprio de
#     iniciar/concluir — é aproximada pelo instante do primeiro apontamento
#     de consumo de material da ordem (`ordem_producao_consumo.registrado_em`
#     mais antigo).
#   - "Liberado faturamento" não tem uma coluna própria de data em
#     `notas_fiscais` (só existe `criado_em`/`atualizado_em`) — usa-se
#     `atualizado_em` da nota autorizada como aproximação de quando ela
#     passou a valer, seguindo a mesma lógica já aplicada a `lotes.status`
#     em `_bloco_periodo`.
def _lote_produzido(conn, ordem):
    if not ordem["lote_produzido_id"]:
        return None
    return conn.execute("SELECT * FROM lotes WHERE id = ?", (ordem["lote_produzido_id"],)).fetchone()


def _eventos_analises(conn, lote_id):
    eventos = []
    analises = conn.execute(
        "SELECT id, criado_em, concluida_em, conclusao FROM analises WHERE lote_id = ? ORDER BY id", (lote_id,)
    ).fetchall()
    for a in analises:
        eventos.append({"chave": f"analise_{a['id']}_solicitada", "titulo": "Análise solicitada", "quando": a["criado_em"]})
        if a["concluida_em"]:
            titulo = "Análise concluída"
            if a["conclusao"]:
                titulo += f" ({a['conclusao']})"
            eventos.append({"chave": f"analise_{a['id']}_concluida", "titulo": titulo, "quando": a["concluida_em"]})
    return eventos


def _evento_faturamento(conn, lote_id):
    """Sobe de lote -> reserva -> item do pedido -> pedido -> nota fiscal
    autorizada (mesmo caminho de rastreabilidade "downstream" usado em
    rastreabilidade.py). Pode não haver nenhuma nota ainda (produto em
    estoque, ainda não vendido) — nesse caso não gera evento."""
    rows = conn.execute(
        """
        SELECT DISTINCT nf.id, nf.numero, nf.criado_em, nf.atualizado_em, nf.valor_total, pv.numero AS pedido_numero
        FROM pedido_venda_reservas pvr
        JOIN pedido_venda_itens pvi ON pvi.id = pvr.pedido_item_id
        JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
        JOIN notas_fiscais nf ON nf.pedido_id = pv.id
        WHERE pvr.lote_id = ? AND nf.status = 'autorizada'
        ORDER BY nf.criado_em
        """,
        (lote_id,),
    ).fetchall()
    return [
        {
            "chave": f"nf_{r['id']}",
            "titulo": f"Nota fiscal {r['numero']} autorizada (pedido {r['pedido_numero']})",
            "quando": r["atualizado_em"] or r["criado_em"],
        }
        for r in rows
    ]


@bp.get("/ordens/<int:ordem_id>/linha-do-tempo")
@requires_auth
def linha_do_tempo_ordem(ordem_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    if not usuario_tem_permissao(conn, usuario_atual["id"], "producao", "visualizar"):
        raise ApiError("Sem permissão para ver o painel de produção.", status=403)

    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)

    eventos = [{"chave": "emissao", "titulo": "Emissão da OP", "quando": ordem["criado_em"]}]

    consumo_inicial = conn.execute(
        "SELECT MIN(registrado_em) AS quando FROM ordem_producao_consumo WHERE ordem_producao_id = ?", (ordem_id,)
    ).fetchone()["quando"]
    if consumo_inicial:
        eventos.append({"chave": "separacao_materia_prima", "titulo": "Separação de matéria-prima", "quando": consumo_inicial})

    if ordem["liberado_em"]:
        eventos.append({"chave": "liberacao_op", "titulo": "Liberação da OP", "quando": ordem["liberado_em"]})

    for etapa in _etapas_da_ordem(conn, ordem_id):
        nome = etapa["nome"]
        if etapa["iniciado_em"]:
            eventos.append({"chave": f"etapa_{etapa['id']}_inicio", "titulo": f"{nome} — início", "quando": etapa["iniciado_em"]})
        if etapa["status"] == "concluida" and etapa["concluido_em"]:
            titulo = f"{nome} — concluída"
            if etapa["valor_registrado"] is not None:
                unidade = etapa["tipo_unidade_valor"] or ""
                titulo += f" ({etapa['valor_registrado']} {unidade})".rstrip()
            eventos.append({"chave": f"etapa_{etapa['id']}_fim", "titulo": titulo, "quando": etapa["concluido_em"]})

    lote = _lote_produzido(conn, ordem)
    if lote is not None:
        eventos.extend(_eventos_analises(conn, lote["id"]))

    if ordem["status"] == "concluida" and ordem["concluido_em"]:
        eventos.append({"chave": "conclusao_op", "titulo": "Pronto para baixa da OP (concluída)", "quando": ordem["concluido_em"]})

    if lote is not None:
        eventos.extend(_evento_faturamento(conn, lote["id"]))

    # Descarta eventos sem data (não deveria acontecer, mas mais seguro que
    # deixar o sort quebrar) e ordena cronologicamente — a ordem de geração
    # acima já é aproximadamente cronológica, mas o sort final é a garantia.
    eventos = [e for e in eventos if e["quando"]]
    eventos.sort(key=lambda e: e["quando"])

    anterior_quando = None
    for evento in eventos:
        if anterior_quando is None:
            evento["duracao_desde_evento_anterior_minutos"] = None
        else:
            try:
                d1 = datetime.datetime.strptime(anterior_quando[:26], "%Y-%m-%dT%H:%M:%S.%f")
                d2 = datetime.datetime.strptime(evento["quando"][:26], "%Y-%m-%dT%H:%M:%S.%f")
                evento["duracao_desde_evento_anterior_minutos"] = round((d2 - d1).total_seconds() / 60, 1)
            except ValueError:
                evento["duracao_desde_evento_anterior_minutos"] = None
        anterior_quando = evento["quando"]

    return jsonify({
        "ordem": {
            "id": ordem["id"], "numero": ordem["numero"], "status": ordem["status"],
            "quantidade_planejada": ordem["quantidade_planejada"], "unidade": ordem["unidade"],
        },
        "eventos": eventos,
    })
