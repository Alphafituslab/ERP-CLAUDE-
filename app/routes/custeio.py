"""
Fase 13 — Custeio de Produção: custo real de uma ordem de produção e a
fatia desse custo atribuível à perda/refugo (Fase 9), calculados a partir
do CUSTO MÉDIO REAL DE COMPRA de cada insumo (decidido com o usuário antes
de implementar, entre as opções "custo padrão cadastrado no item" x
"custo médio real das compras" x "os dois combinados" — a resposta foi
"custo médio real das compras").

Toda a matemática aqui é 100% DERIVADA em tempo real — nenhuma tabela
nova de "custo calculado" é criada (mesmo princípio de "nunca guardar um
número que poderia dessincronizar" já usado em saldo de estoque, reservas
e status de conta financeira desde as Fases 4/5/6):

  1. `custo_medio_item()`: para cada item, a média ponderada por
     quantidade de `lotes.custo_unitario` (Fase 13, novo campo OPCIONAL
     informado no recebimento) entre todos os lotes já recebidos desse
     item que tiveram custo informado. Lotes sem custo informado NÃO
     entram na média (nem como zero — isso subestimaria o custo real, nem
     são ignorados silenciosamente — o resultado sinaliza quando a
     informação está incompleta).
  2. `custo_lote()`: o custo de um lote específico é o `custo_unitario`
     dele mesmo, se informado; senão cai para a média do item (acima);
     senão fica indisponível.
  3. `custo_ordem_producao()`: soma, por insumo, `quantidade consumida
     (ordem_producao_consumo, Fase 3) × custo_lote(lote consumido)` — é o
     custo REAL desta ordem específica, insumo a insumo (matéria-prima,
     rótulo, tampa, sílica etc., contanto que estejam na composição da
     fórmula — o cadastro já suporta isso desde a Fase 3, sem mudança de
     schema). Depois que a ordem está CONCLUÍDA (Fase 9 grava
     `quantidade_produzida`/`quantidade_perda`), a mesma função também
     devolve a fatia desse custo atribuível à perda: cada insumo tem seu
     custo total dividido proporcionalmente ao `percentual_perda` já
     calculado pela Fase 9 — é uma alocação simples e deliberadamente
     transparente (não tenta adivinhar EM QUE ETAPA do processo a perda
     aconteceu; se a perda ocorre antes de embalar, por exemplo, o custo
     real de rótulo/tampa perdido pode ser menor do que esta alocação
     proporcional sugere — documentado no README). A Fase 50 (Perda por
     Etapa) reparte esse MESMO `custo_total_perda` entre as etapas
     cadastradas na ordem (`ordem_producao_etapas`), proporcionalmente à
     quantidade de perda que cada uma apontou — ver `_perda_por_etapa()` e
     a chave `perdas.por_etapa` do resultado. Continua sem saber em que
     etapa cada INSUMO específico entra (a composição/BOM não tem esse
     vínculo), então dentro de cada etapa o custo ainda vem do mesmo
     rateio proporcional entre insumos de sempre — só a fatia ENTRE
     etapas é nova.
  4. `custo_projetado_formula()`: para a tela agregada "Custo do Produto"
     (consulta por fórmula, sem depender de nenhuma ordem específica), o
     mesmo cálculo de custo médio é aplicado à composição da fórmula
     (BOM) normalizada por unidade de rendimento — um custo PADRÃO
     projetado, útil para precificar antes mesmo de produzir.

Permissão nova: `custeio.visualizar` — dado financeiro sensível (preço
pago a fornecedor), deliberadamente INDEPENDENTE de `producao.visualizar`
(que já é dado operacional, sem preço). Só Financeiro/Diretoria/
Administrador têm por padrão — mesma filosofia de segregação já usada
para `financeiro.visualizar` (Fase 6) e `relatorios.visualizar` (Fase 7):
quem vê o chão de fábrica não necessariamente vê quanto a empresa paga
pelos insumos.
"""
from flask import Blueprint, jsonify, request

from ..context import ApiError, get_db
from ..permissions import requires_permission

bp = Blueprint("custeio", __name__, url_prefix="/api/v1/custeio")


def custo_medio_item(conn, item_id):
    """Média ponderada por quantidade de `lotes.custo_unitario` entre
    todos os lotes já recebidos deste item que têm custo informado
    (qualquer status — o dinheiro já foi gasto na compra, independente do
    lote ter sido aprovado, reprovado ou bloqueado depois). Devolve None
    se nenhum lote do item tem custo informado."""
    row = conn.execute(
        """
        SELECT SUM(quantidade * custo_unitario) AS custo_total, SUM(quantidade) AS quantidade_total
        FROM lotes WHERE item_id = ? AND custo_unitario IS NOT NULL
        """,
        (item_id,),
    ).fetchone()
    if not row or not row["quantidade_total"]:
        return None
    return row["custo_total"] / row["quantidade_total"]


def custo_lote(conn, lote_id):
    """Devolve (valor_unitario, origem) para um lote específico.
    origem é 'lote' (custo informado neste lote), 'media_item' (caiu para
    a média do item) ou 'indisponivel' (nenhum dos dois existe)."""
    lote = conn.execute("SELECT item_id, custo_unitario FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if lote is None:
        return None, "indisponivel"
    if lote["custo_unitario"] is not None:
        return lote["custo_unitario"], "lote"
    media = custo_medio_item(conn, lote["item_id"])
    if media is not None:
        return media, "media_item"
    return None, "indisponivel"


def custo_mao_de_obra_overhead(conn, ordem):
    """Fase 30: custo de mão de obra + overhead de uma ordem, a partir das
    taxas por HORA cadastradas no centro de trabalho (Fase 25) onde a
    ordem foi agendada, multiplicadas pelas horas apontadas na conclusão
    (Fase 9-style, campo opcional). Assim como o custo de material (Fase
    13), NUNCA inventa um número: se qualquer uma das três informações
    necessárias falta (horas apontadas, agendamento num centro, taxa
    cadastrada naquele centro), devolve `disponivel: False` com um motivo
    explicando qual delas — mesma transparência já usada para custo de
    material sem preço informado."""
    if ordem["horas_apontadas"] is None:
        return {
            "disponivel": False, "motivo_indisponivel": "Ordem concluída sem apontar horas trabalhadas.",
            "horas_apontadas": None, "centro_trabalho_id": None, "centro_trabalho_nome": None,
            "custo_hora_mao_de_obra": None, "custo_hora_overhead": None,
            "custo_mao_de_obra": None, "custo_overhead": None, "custo_total": None,
        }

    agendamento = conn.execute(
        """
        SELECT opa.centro_trabalho_id, ct.nome AS centro_trabalho_nome,
               ct.custo_hora_mao_de_obra, ct.custo_hora_overhead
        FROM ordem_producao_agendamentos opa JOIN centros_trabalho ct ON ct.id = opa.centro_trabalho_id
        WHERE opa.ordem_producao_id = ?
        """,
        (ordem["id"],),
    ).fetchone()
    if agendamento is None:
        return {
            "disponivel": False,
            "motivo_indisponivel": "Ordem sem agendamento em nenhum centro de trabalho (APS, Fase 25) — sem saber qual centro produziu, não há taxa de custo/hora para aplicar.",
            "horas_apontadas": ordem["horas_apontadas"], "centro_trabalho_id": None, "centro_trabalho_nome": None,
            "custo_hora_mao_de_obra": None, "custo_hora_overhead": None,
            "custo_mao_de_obra": None, "custo_overhead": None, "custo_total": None,
        }

    custo_hora_mdo = agendamento["custo_hora_mao_de_obra"]
    custo_hora_oh = agendamento["custo_hora_overhead"]
    if custo_hora_mdo is None and custo_hora_oh is None:
        return {
            "disponivel": False,
            "motivo_indisponivel": f"O centro de trabalho '{agendamento['centro_trabalho_nome']}' não tem taxa de custo/hora cadastrada (Centros de Trabalho (APS) → Editar).",
            "horas_apontadas": ordem["horas_apontadas"],
            "centro_trabalho_id": agendamento["centro_trabalho_id"], "centro_trabalho_nome": agendamento["centro_trabalho_nome"],
            "custo_hora_mao_de_obra": None, "custo_hora_overhead": None,
            "custo_mao_de_obra": None, "custo_overhead": None, "custo_total": None,
        }

    horas = ordem["horas_apontadas"]
    custo_mdo = round(horas * custo_hora_mdo, 6) if custo_hora_mdo is not None else None
    custo_oh = round(horas * custo_hora_oh, 6) if custo_hora_oh is not None else None
    return {
        "disponivel": True, "motivo_indisponivel": None,
        "horas_apontadas": horas,
        "centro_trabalho_id": agendamento["centro_trabalho_id"], "centro_trabalho_nome": agendamento["centro_trabalho_nome"],
        "custo_hora_mao_de_obra": custo_hora_mdo, "custo_hora_overhead": custo_hora_oh,
        "custo_mao_de_obra": custo_mdo, "custo_overhead": custo_oh,
        "custo_total": round((custo_mdo or 0) + (custo_oh or 0), 6),
    }


def _perda_por_etapa(conn, ordem_id, custo_total_perda):
    """Fase 50 — reparte `custo_total_perda` (já calculado com o rateio
    proporcional de sempre entre insumos) entre as etapas cadastradas para
    esta ordem, proporcionalmente à quantidade de perda que cada etapa
    apontou. Lista vazia para qualquer ordem que não usa etapas (a imensa
    maioria) — o campo "por_etapa" nesse caso é só um array vazio, nunca
    None, para não obrigar quem já lê `perdas.itens`/`custo_total_perda`
    a tratar mais um caso especial."""
    etapas = conn.execute(
        "SELECT id, sequencia, nome, quantidade_perda, motivo_perda FROM ordem_producao_etapas "
        "WHERE ordem_producao_id = ? ORDER BY sequencia",
        (ordem_id,),
    ).fetchall()
    if not etapas:
        return []
    quantidade_perda_total_etapas = sum(e["quantidade_perda"] for e in etapas)
    resultado = []
    for e in etapas:
        proporcao = (e["quantidade_perda"] / quantidade_perda_total_etapas) if quantidade_perda_total_etapas > 0 else 0.0
        resultado.append({
            "etapa_id": e["id"], "sequencia": e["sequencia"], "nome": e["nome"],
            "quantidade_perda": e["quantidade_perda"], "motivo_perda": e["motivo_perda"],
            "percentual_da_perda_total": round(proporcao * 100, 4),
            "custo_perda_estimado": round(custo_total_perda * proporcao, 6),
        })
    return resultado


def custo_ordem_producao(conn, ordem_id):
    ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (ordem_id,)).fetchone()
    if ordem is None:
        raise ApiError("Ordem de produção não encontrada.", status=404)
    ordem = dict(ordem)

    consumos = conn.execute(
        """
        SELECT opc.item_id, opc.lote_id, opc.quantidade, i.codigo, i.descricao, i.unidade_medida
        FROM ordem_producao_consumo opc JOIN itens i ON i.id = opc.item_id
        WHERE opc.ordem_producao_id = ? ORDER BY opc.id
        """,
        (ordem_id,),
    ).fetchall()

    por_item = {}
    custo_incompleto = False
    itens_sem_custo = []
    for c in consumos:
        item_id = c["item_id"]
        valor_unit, origem = custo_lote(conn, c["lote_id"])
        entry = por_item.setdefault(item_id, {
            "item_id": item_id, "codigo": c["codigo"], "descricao": c["descricao"],
            "quantidade_consumida": 0.0, "unidade": c["unidade_medida"],
            "custo_total": 0.0, "origens": set(), "tem_custo_indisponivel": False,
        })
        entry["quantidade_consumida"] += c["quantidade"]
        if valor_unit is None:
            entry["tem_custo_indisponivel"] = True
            custo_incompleto = True
            if c["codigo"] not in itens_sem_custo:
                itens_sem_custo.append(c["codigo"])
        else:
            entry["custo_total"] += c["quantidade"] * valor_unit
            entry["origens"].add(origem)

    itens_lista = []
    custo_total_producao = 0.0
    for entry in por_item.values():
        if entry["tem_custo_indisponivel"] and not entry["origens"]:
            origem_final = "indisponivel"
        elif entry["tem_custo_indisponivel"]:
            origem_final = "parcial"
        elif entry["origens"] == {"lote"}:
            origem_final = "lote"
        elif entry["origens"] == {"media_item"}:
            origem_final = "media_item"
        else:
            origem_final = "misto"
        itens_lista.append({
            "item_id": entry["item_id"], "codigo": entry["codigo"], "descricao": entry["descricao"],
            "quantidade_consumida": round(entry["quantidade_consumida"], 6),
            "unidade": entry["unidade"],
            "custo_total": round(entry["custo_total"], 6),
            "origem_custo": origem_final,
        })
        custo_total_producao += entry["custo_total"]

    itens_lista.sort(key=lambda x: x["codigo"])

    # Fase 30 — Custo de Mão de Obra e Overhead: um bloco à parte, que
    # NÃO altera `custo_total_producao` acima (esse continua sendo só
    # material, exatamente como a Fase 13 sempre calculou — telas e
    # integrações já existentes continuam recebendo o mesmo número de
    # sempre). `custo_total_producao_com_mao_de_obra` é o novo total
    # "completo", que soma material + mão de obra + overhead quando
    # disponível (senão repete o valor de material, já que não há o que
    # somar).
    mao_de_obra_overhead = custo_mao_de_obra_overhead(conn, ordem)
    resultado = {
        "ordem_id": ordem_id,
        "ordem_numero": ordem["numero"],
        "ordem_status": ordem["status"],
        "itens": itens_lista,
        "custo_total_producao": round(custo_total_producao, 6),
        "custo_incompleto": custo_incompleto,
        "itens_sem_custo_disponivel": itens_sem_custo,
        "mao_de_obra_overhead": mao_de_obra_overhead,
        "custo_total_producao_com_mao_de_obra": round(
            custo_total_producao + (mao_de_obra_overhead["custo_total"] or 0), 6
        ),
    }

    # Aba "custo com as perdas" — só existe depois que a Fase 9 já
    # calculou quantidade_produzida/quantidade_perda na conclusão da
    # ordem; antes disso não há como saber o percentual de perda.
    if ordem["quantidade_produzida"] is not None:
        total_processado = ordem["quantidade_produzida"] + (ordem["quantidade_perda"] or 0)
        percentual_perda = (ordem["quantidade_perda"] or 0) / total_processado if total_processado > 0 else 0.0
        itens_perda = []
        custo_total_perda = 0.0
        for item in itens_lista:
            custo_perda_item = round(item["custo_total"] * percentual_perda, 6)
            itens_perda.append({
                "item_id": item["item_id"], "codigo": item["codigo"], "descricao": item["descricao"],
                "custo_total_item": item["custo_total"],
                "custo_perda": custo_perda_item,
                "custo_producao_boa": round(item["custo_total"] - custo_perda_item, 6),
            })
            custo_total_perda += custo_perda_item
        resultado["perdas"] = {
            "percentual_perda": round(percentual_perda * 100, 4),
            "itens": itens_perda,
            "custo_total_perda": round(custo_total_perda, 6),
            "custo_total_producao_boa": round(custo_total_producao - custo_total_perda, 6),
            # Fase 50 — quando a ordem tem etapas cadastradas (ver
            # `ordem_producao_etapas`), reparte o MESMO `custo_total_perda`
            # acima entre as etapas, proporcionalmente à quantidade de
            # perda que cada uma apontou — ex.: se a etapa "Embalagem"
            # apontou 1.5kg de perda e "Pesagem" apontou 0.5kg (total 2kg,
            # o mesmo total que já compõe `percentual_perda` acima),
            # "Embalagem" fica com 75% de `custo_total_perda`. Isto NÃO é
            # o mesmo que ratear por insumo realmente consumido até cada
            # etapa (a composição/BOM não sabe em que etapa cada insumo
            # entra — ver README) — dentro de cada etapa o custo continua
            # vindo do mesmo rateio proporcional entre insumos de sempre,
            # só a fatia ENTRE etapas é nova. Ainda assim, é uma alocação
            # bem mais fiel do que assumir que a perda inteira caiu num
            # ponto só do processo.
            "por_etapa": _perda_por_etapa(conn, ordem_id, custo_total_perda),
        }
    else:
        resultado["perdas"] = None

    return resultado


def custo_projetado_formula(conn, formula):
    itens = conn.execute(
        """
        SELECT fi.item_id, fi.quantidade, i.codigo, i.descricao, i.unidade_medida
        FROM formula_itens fi JOIN itens i ON i.id = fi.item_id
        WHERE fi.formula_id = ? ORDER BY i.codigo
        """,
        (formula["id"],),
    ).fetchall()
    rendimento = formula["rendimento_teorico"] or 0
    itens_lista = []
    custo_total_por_unidade = 0.0
    incompleto = False
    for it in itens:
        qtd_por_unidade = (it["quantidade"] / rendimento) if rendimento else 0.0
        media = custo_medio_item(conn, it["item_id"])
        if media is None:
            incompleto = True
            custo_item = None
        else:
            custo_item = round(qtd_por_unidade * media, 6)
            custo_total_por_unidade += custo_item
        itens_lista.append({
            "item_id": it["item_id"], "codigo": it["codigo"], "descricao": it["descricao"],
            "quantidade_por_unidade": round(qtd_por_unidade, 6),
            "unidade": it["unidade_medida"],
            "custo_medio_unitario": round(media, 6) if media is not None else None,
            "custo_por_unidade": custo_item,
        })
    return {
        "itens": itens_lista,
        "custo_total_por_unidade": round(custo_total_por_unidade, 6),
        "unidade_rendimento": formula["unidade_rendimento"],
        "custo_incompleto": incompleto,
    }


@bp.get("/ordens/<int:ordem_id>")
@requires_permission("custeio", "visualizar")
def obter_custo_ordem(ordem_id):
    conn = get_db()
    return jsonify(custo_ordem_producao(conn, ordem_id))


@bp.get("/produtos")
@requires_permission("custeio", "visualizar")
def listar_custo_produtos():
    """Aba 1 (por produto): custo padrão projetado de cada fórmula ATIVA,
    calculado a partir do custo médio de compra atual dos insumos da BOM
    — não depende de nenhuma ordem já ter sido produzida."""
    conn = get_db()
    formulas = conn.execute(
        """
        SELECT f.*, i.codigo AS item_produzido_codigo, i.descricao AS item_produzido_descricao
        FROM formulas f JOIN itens i ON i.id = f.item_produzido_id
        WHERE f.status = 'ativa' ORDER BY i.codigo
        """
    ).fetchall()
    resultado = []
    for f in formulas:
        formula = dict(f)
        resultado.append({
            "formula_id": formula["id"],
            "versao": formula["versao"],
            "item_produzido_id": formula["item_produzido_id"],
            "item_produzido_codigo": formula["item_produzido_codigo"],
            "item_produzido_descricao": formula["item_produzido_descricao"],
            "custo_projetado": custo_projetado_formula(conn, formula),
        })
    return jsonify(resultado)


@bp.get("/produtos/<int:formula_id>")
@requires_permission("custeio", "visualizar")
def obter_custo_produto(formula_id):
    """Aba 1: custo padrão projetado da fórmula (igual ao item da lista
    acima). Aba 2: histórico de custo de perda das últimas ordens
    CONCLUÍDAS desta fórmula (deliberadamente não resume num único número
    "esperado" — mostra os casos reais, cada ordem com seu próprio
    percentual de perda e custo, para não sugerir uma precisão que os
    dados não têm)."""
    conn = get_db()
    formula = conn.execute(
        """
        SELECT f.*, i.codigo AS item_produzido_codigo, i.descricao AS item_produzido_descricao
        FROM formulas f JOIN itens i ON i.id = f.item_produzido_id
        WHERE f.id = ?
        """,
        (formula_id,),
    ).fetchone()
    if formula is None:
        raise ApiError("Fórmula não encontrada.", status=404)
    formula = dict(formula)

    limite = request.args.get("limite", default=20, type=int)
    ordens = conn.execute(
        """
        SELECT id, numero, quantidade_planejada, quantidade_produzida, quantidade_perda, criado_em
        FROM ordens_producao
        WHERE formula_id = ? AND status = 'concluida'
        ORDER BY id DESC LIMIT ?
        """,
        (formula_id, limite),
    ).fetchall()

    historico_perdas = []
    for o in ordens:
        custo = custo_ordem_producao(conn, o["id"])
        historico_perdas.append({
            "ordem_id": o["id"],
            "ordem_numero": o["numero"],
            "quantidade_produzida": o["quantidade_produzida"],
            "quantidade_perda": o["quantidade_perda"],
            "custo_total_producao": custo["custo_total_producao"],
            "custo_incompleto": custo["custo_incompleto"],
            "perdas": custo["perdas"],
        })

    return jsonify({
        "formula_id": formula["id"],
        "versao": formula["versao"],
        "item_produzido_id": formula["item_produzido_id"],
        "item_produzido_codigo": formula["item_produzido_codigo"],
        "item_produzido_descricao": formula["item_produzido_descricao"],
        "custo_projetado": custo_projetado_formula(conn, formula),
        "historico_perdas": historico_perdas,
    })


# ============================================================
# Fase 20 — DRE Simplificado (Demonstrativo de Resultado)
# ============================================================
# Junta duas coisas que já existem, cada uma desde uma fase diferente, num
# relatório novo: a receita de pedidos EXPEDIDOS (Fase 5/6 —
# quantidade × preco_unitario) e o CMV — Custo das Mercadorias Vendidas —
# calculado a partir do custo REAL de produção (Fase 13) do lote
# efetivamente reservado/expedido para cada item do pedido
# (`pedido_venda_reservas`, Fase 5). 100% derivado a cada chamada, nenhuma
# tabela nova: mesmo princípio de todo o resto do sistema. Reaproveita
# `custo_lote()`/`custo_ordem_producao()` já validados pela Fase 13 —
# nenhuma lógica de custo duplicada, só uma nova forma de somar o que já
# está lá.
#
# Permissão: reaproveita `custeio.visualizar` (não `relatorios.visualizar`)
# de propósito — um DRE expõe margem, que é derivada do custo real de
# compra dos insumos (o mesmo dado sensível que já justificou
# `custeio.visualizar` ser independente de `producao.visualizar` desde a
# Fase 13); o perfil Financeiro já tem `custeio.visualizar` mas NÃO tem
# `relatorios.visualizar`, então exigir esta última deixaria o perfil que
# mais precisa de um DRE sem conseguir vê-lo.
def _custo_unitario_lote_vendido(conn, lote_id):
    """Custo unitário de um lote vendido, para o CMV do DRE. O caso normal
    de um pedido de venda é um produto ACABADO fabricado por uma ordem de
    produção — nesse caso o custo real é `custo_ordem_producao()` (Fase
    13) dividido pela quantidade produzida daquela ordem, não o
    `custo_unitario`/`custo_lote()` (que é para lotes RECEBIDOS de
    fornecedor, e nunca é preenchido para um lote produzido — ver
    `producao.py`). Cai para `custo_lote()` só no caso raro de um produto
    acabado ter sido recebido diretamente (não fabricado) via
    `/lotes/recebimento`. Devolve (valor_unitario, origem) — origem é
    'ordem_producao', 'lote'/'media_item' (via `custo_lote`) ou
    'indisponivel'."""
    ordem = conn.execute(
        "SELECT id, quantidade_produzida FROM ordens_producao WHERE lote_produzido_id = ?", (lote_id,)
    ).fetchone()
    if ordem is not None and ordem["quantidade_produzida"]:
        custo_ordem = custo_ordem_producao(conn, ordem["id"])
        if not custo_ordem["custo_incompleto"]:
            return custo_ordem["custo_total_producao"] / ordem["quantidade_produzida"], "ordem_producao"
        return None, "indisponivel"
    return custo_lote(conn, lote_id)


def custo_unitario_lote(conn, lote_id):
    """Fase 34 — versão pública de `_custo_unitario_lote_vendido`, exata
    mesma lógica (cobre lote produzido por uma ordem E lote recebido de
    fornecedor), só sem a suposição de que o lote necessariamente foi
    vendido — o nome "vendido" da função original vem do contexto em que
    ela nasceu (CMV do DRE, Fase 20), mas o cálculo em si serve para
    saber o custo unitário de QUALQUER lote, vendido ou não. Reaproveitada
    pela Fase 34 (alçada por valor do ajuste de contagem de estoque) para
    estimar o valor financeiro de uma divergência de inventário. Devolve
    (valor_unitario, origem), mesma semântica de `custo_lote()`."""
    return _custo_unitario_lote_vendido(conn, lote_id)


def _despesas_operacionais_periodo(conn, data_inicio=None, data_fim=None):
    """Fase 41 — soma as contas a pagar lançadas como `categoria =
    'despesa_operacional'` (ver `financeiro.criar_conta_pagar`) dentro do
    período. Usa `criado_em` (quando a despesa foi LANÇADA no sistema),
    não `vencimento` (quando ela vence pra pagamento) nem uma baixa —
    mesmo regime de competência já usado do lado da receita (que reconhece
    no momento da EXPEDIÇÃO do pedido, não no recebimento do dinheiro):
    reconhece a despesa quando ela é registrada, independente de já ter
    sido paga. Contas canceladas nunca entram — uma despesa cancelada
    nunca aconteceu de verdade."""
    clausulas = ["cp.categoria = 'despesa_operacional'", "cp.status != 'cancelado'"]
    params = []
    if data_inicio:
        clausulas.append("cp.criado_em >= ?")
        params.append(data_inicio)
    if data_fim:
        clausulas.append("cp.criado_em <= ?")
        params.append(f"{data_fim}T23:59:59.999999Z")
    where = " AND ".join(clausulas)
    rows = conn.execute(
        f"""
        SELECT cp.id, cp.numero, cp.descricao, cp.valor_total, cp.criado_em, f.nome AS fornecedor_nome
        FROM contas_pagar cp
        JOIN fornecedores f ON f.id = cp.fornecedor_id
        WHERE {where}
        ORDER BY cp.criado_em
        """,
        params,
    ).fetchall()
    detalhe = [
        {
            "conta_id": r["id"], "numero": r["numero"], "descricao": r["descricao"],
            "fornecedor_nome": r["fornecedor_nome"], "valor": round(r["valor_total"], 2), "criado_em": r["criado_em"],
        }
        for r in rows
    ]
    total = round(sum(r["valor_total"] for r in rows), 2)
    return total, detalhe


def _dre_simplificado(conn, data_inicio=None, data_fim=None):
    clausulas = ["pv.status = 'expedido'"]
    params = []
    if data_inicio:
        clausulas.append("pv.expedido_em >= ?")
        params.append(data_inicio)
    if data_fim:
        clausulas.append("pv.expedido_em <= ?")
        params.append(f"{data_fim}T23:59:59.999999Z")
    where = " AND ".join(clausulas)

    pedidos = conn.execute(
        f"SELECT pv.id, pv.numero, pv.expedido_em FROM pedidos_venda pv WHERE {where} ORDER BY pv.expedido_em",
        params,
    ).fetchall()

    receita_bruta = 0.0
    cmv = 0.0
    custo_incompleto = False
    lotes_sem_custo = set()
    pedidos_detalhe = []

    for pedido in pedidos:
        itens = conn.execute(
            "SELECT id, quantidade, preco_unitario FROM pedido_venda_itens WHERE pedido_id = ?", (pedido["id"],)
        ).fetchall()
        receita_pedido = 0.0
        cmv_pedido = 0.0
        pedido_incompleto = False
        for item in itens:
            receita_pedido += item["quantidade"] * item["preco_unitario"]
            reservas = conn.execute(
                "SELECT lote_id, quantidade FROM pedido_venda_reservas WHERE pedido_item_id = ?", (item["id"],)
            ).fetchall()
            for reserva in reservas:
                valor_unit, _origem = _custo_unitario_lote_vendido(conn, reserva["lote_id"])
                if valor_unit is None:
                    pedido_incompleto = True
                    custo_incompleto = True
                    lote_row = conn.execute("SELECT codigo_lote FROM lotes WHERE id = ?", (reserva["lote_id"],)).fetchone()
                    if lote_row:
                        lotes_sem_custo.add(lote_row["codigo_lote"])
                else:
                    cmv_pedido += reserva["quantidade"] * valor_unit
        receita_bruta += receita_pedido
        cmv += cmv_pedido
        pedidos_detalhe.append({
            "pedido_id": pedido["id"], "numero": pedido["numero"], "expedido_em": pedido["expedido_em"],
            "receita": round(receita_pedido, 2), "cmv": round(cmv_pedido, 2),
            "lucro_bruto": round(receita_pedido - cmv_pedido, 2),
            "custo_incompleto": pedido_incompleto,
        })

    lucro_bruto = receita_bruta - cmv
    margem_bruta_pct = round((lucro_bruto / receita_bruta) * 100, 2) if receita_bruta > 0 else None

    # Fase 41 — as duas peças que faltavam para chegar em Lucro Líquido.
    despesas_operacionais, despesas_operacionais_detalhe = _despesas_operacionais_periodo(conn, data_inicio, data_fim)
    config_row = conn.execute(
        "SELECT percentual_imposto_venda, percentual_pis, percentual_cofins, percentual_icms, percentual_iss "
        "FROM configuracoes_financeiro WHERE id = 1"
    ).fetchone()
    percentual_imposto_venda = config_row["percentual_imposto_venda"] if config_row else 0.0
    # Fase 56 — quatro alíquotas detalhadas, cada uma também aplicada
    # sobre a Receita Bruta e somada à alíquota genérica acima (nunca em
    # substituição a ela — ver a nota completa em
    # `migrations/schema_fase56.sql`). Uma instalação que nunca configurar
    # nenhuma delas (todas ficam 0 por padrão) tem exatamente o mesmo
    # `impostos_sobre_vendas` de antes desta fase.
    percentual_pis = config_row["percentual_pis"] if config_row else 0.0
    percentual_cofins = config_row["percentual_cofins"] if config_row else 0.0
    percentual_icms = config_row["percentual_icms"] if config_row else 0.0
    percentual_iss = config_row["percentual_iss"] if config_row else 0.0

    imposto_generico = round(receita_bruta * (percentual_imposto_venda / 100), 2)
    imposto_pis = round(receita_bruta * (percentual_pis / 100), 2)
    imposto_cofins = round(receita_bruta * (percentual_cofins / 100), 2)
    imposto_icms = round(receita_bruta * (percentual_icms / 100), 2)
    imposto_iss = round(receita_bruta * (percentual_iss / 100), 2)
    impostos_sobre_vendas = round(imposto_generico + imposto_pis + imposto_cofins + imposto_icms + imposto_iss, 2)
    lucro_liquido = round(lucro_bruto - despesas_operacionais - impostos_sobre_vendas, 2)
    margem_liquida_pct = round((lucro_liquido / receita_bruta) * 100, 2) if receita_bruta > 0 else None

    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "receita_bruta": round(receita_bruta, 2),
        "cmv": round(cmv, 2),
        "lucro_bruto": round(lucro_bruto, 2),
        "margem_bruta_pct": margem_bruta_pct,
        "despesas_operacionais": despesas_operacionais,
        "despesas_operacionais_detalhe": despesas_operacionais_detalhe,
        "percentual_imposto_venda": percentual_imposto_venda,
        "impostos_sobre_vendas": impostos_sobre_vendas,
        # Fase 56 — quebra dos impostos por tributo, para a tela mostrar
        # cada linha separadamente quando configurado (e a soma sempre
        # bate com `impostos_sobre_vendas` acima).
        "impostos_detalhe": {
            "imposto_generico": {"percentual": percentual_imposto_venda, "valor": imposto_generico},
            "pis": {"percentual": percentual_pis, "valor": imposto_pis},
            "cofins": {"percentual": percentual_cofins, "valor": imposto_cofins},
            "icms": {"percentual": percentual_icms, "valor": imposto_icms},
            "iss": {"percentual": percentual_iss, "valor": imposto_iss},
        },
        "lucro_liquido": lucro_liquido,
        "margem_liquida_pct": margem_liquida_pct,
        "custo_incompleto": custo_incompleto,
        "lotes_sem_custo_disponivel": sorted(lotes_sem_custo),
        "total_pedidos": len(pedidos_detalhe),
        "pedidos": pedidos_detalhe,
    }


@bp.get("/dre")
@requires_permission("custeio", "visualizar")
def dre_simplificado():
    """`data_inicio`/`data_fim` (AAAA-MM-DD, opcionais) filtram por
    `pedidos_venda.expedido_em` — sem eles, o DRE cobre todo o histórico
    de pedidos já expedidos."""
    conn = get_db()
    data_inicio = request.args.get("data_inicio") or None
    data_fim = request.args.get("data_fim") or None
    return jsonify(_dre_simplificado(conn, data_inicio, data_fim))
