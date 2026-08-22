import datetime
import io
import secrets

from flask import Blueprint, Response, g, jsonify, request
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .. import audit
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..pdf_marca import desenhar_cabecalho_logo
from ..permissions import requires_permission
from .compras import dar_baixa_recebimento_no_pedido, validar_pedido_para_recebimento

bp = Blueprint("lotes", __name__, url_prefix="/api/v1/lotes")

STATUS_ATIVOS_PARA_USO = ("aprovado", "aprovado_com_ressalva")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hoje_iso_data():
    """Fase 65 — mesmo padrão de `_hoje_iso_data` em app/routes/compras.py:
    só a parte de data (sem hora), para comparar contra `validade` (que
    também é só data) sem fuso horário entrar no meio."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _gerar_codigo_lote(conn, lote_id):
    ano = datetime.datetime.utcnow().year
    return f"L{ano}-{lote_id:06d}"


def _lote_ou_404(conn, lote_id):
    row = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if row is None:
        raise ApiError("Lote não encontrado.", status=404)
    lote = dict(row)
    # Fase 52 — empresa_id é opcional (ver schema_fase52.sql); a maioria
    # dos lotes continua sem nenhuma.
    if lote["empresa_id"]:
        empresa = conn.execute(
            "SELECT nome_fantasia, razao_social FROM empresas WHERE id = ?", (lote["empresa_id"],)
        ).fetchone()
        lote["empresa_nome"] = (empresa["nome_fantasia"] or empresa["razao_social"]) if empresa else None
    else:
        lote["empresa_nome"] = None
    # Fase 65 — só para exibição (a Qualidade/PCP já veem isso na hora sem
    # precisar comparar a data de validade de cabeça); NÃO é usado para
    # bloquear nada aqui — o bloqueio de verdade é nas alocações FEFO
    # (`_alocar_fefo` em comercial.py, `_alocar_fefo_producao` em
    # producao.py, `sugestao_fefo` em estoque.py), que simplesmente param
    # de considerar o lote "disponível" quando vencido.
    lote["vencido"] = lote["validade"] is not None and lote["validade"] < _hoje_iso_data()
    return lote


def _empresa_ou_404(conn, empresa_id):
    """Fase 52 — mesma validação de app/routes/producao.py, duplicada de
    propósito para não criar acoplamento entre módulos de rota só por um
    SELECT de 3 linhas."""
    empresa = conn.execute("SELECT id FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if empresa is None:
        raise ApiError("Empresa não encontrada.", status=404)


def _analise_concluida_pendente_de_aprovacao(conn, lote_id):
    row = conn.execute(
        "SELECT * FROM analises WHERE lote_id = ? AND status = 'concluida' ORDER BY id DESC LIMIT 1",
        (lote_id,),
    ).fetchone()
    return dict(row) if row else None


@bp.get("")
@requires_permission("lotes", "visualizar")
def listar():
    conn = get_db()
    status = request.args.get("status")
    item_id = request.args.get("item_id", type=int)
    clausulas, params = [], []
    if status:
        clausulas.append("l.status = ?")
        params.append(status)
    if item_id:
        clausulas.append("l.item_id = ?")
        params.append(item_id)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT l.*, i.codigo AS item_codigo, i.descricao AS item_descricao, f.nome AS fornecedor_nome
        FROM lotes l
        JOIN itens i ON i.id = l.item_id
        LEFT JOIN fornecedores f ON f.id = l.fornecedor_id
        {where}
        ORDER BY l.id DESC
        """,
        params,
    ).fetchall()
    hoje = _hoje_iso_data()
    resultado = []
    for r in rows:
        r = dict(r)
        r["vencido"] = r["validade"] is not None and r["validade"] < hoje  # Fase 65 — só exibição.
        resultado.append(r)
    return jsonify(resultado)


@bp.get("/<int:lote_id>")
@requires_permission("lotes", "visualizar")
def obter(lote_id):
    conn = get_db()
    lote = _lote_ou_404(conn, lote_id)
    analises = conn.execute("SELECT * FROM analises WHERE lote_id = ? ORDER BY id", (lote_id,)).fetchall()
    lote["analises"] = []
    for a in analises:
        a = dict(a)
        resultados = conn.execute("SELECT * FROM resultados_analise WHERE analise_id = ? ORDER BY id", (a["id"],)).fetchall()
        a["resultados"] = [dict(r) for r in resultados]
        lote["analises"].append(a)
    coa = conn.execute("SELECT * FROM certificados_analise WHERE lote_id = ? ORDER BY id DESC LIMIT 1", (lote_id,)).fetchone()
    lote["certificado_analise"] = dict(coa) if coa else None
    return jsonify(lote)


@bp.post("/recebimento")
@requires_permission("lotes", "receber")
def receber():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    item_id = dados.get("item_id")
    fornecedor_id = dados.get("fornecedor_id")
    quantidade = dados.get("quantidade")
    unidade = dados.get("unidade")
    # Fase 52 — opcional, sem valor padrão (ver schema_fase52.sql): quando
    # informado, é o que permite este lote entrar no filtro por empresa do
    # Painel Gerencial (blocos Qualidade e Estoque). Omitido, o lote fica
    # sem empresa (comportamento de sempre, sem mudança nenhuma).
    empresa_id = dados.get("empresa_id")
    # Fase 58 — opcional, sem valor padrão: vínculo ESTRUTURADO com um
    # Pedido de Compra formal (ver app/routes/compras.py), diferente da
    # coluna `pedido_compra` (texto livre) que já existia desde a Fase 2 e
    # continua funcionando exatamente igual, com ou sem este campo novo.
    pedido_compra_id = dados.get("pedido_compra_id")

    if not item_id or not quantidade or not unidade:
        raise ApiError("Informe item_id, quantidade e unidade.", status=400)
    if empresa_id is not None:
        _empresa_ou_404(conn, empresa_id)

    pedido_compra_para_baixa = None
    if pedido_compra_id:
        # Valida ANTES de criar o lote — se o pedido não existir, estiver
        # no status errado, ou o item não pertencer a ele, nada é criado
        # (mesmo princípio de "falhar antes de qualquer INSERT" já usado
        # na validação de fornecedor homologado, abaixo).
        pedido_compra_para_baixa = validar_pedido_para_recebimento(conn, pedido_compra_id, item_id)
        # Fornecedor do recebimento não informado: assume o do pedido
        # (mesmo fornecedor que vai receber o material, evita redigitar).
        if not fornecedor_id:
            fornecedor_id = pedido_compra_para_baixa["fornecedor_id"]
        elif int(fornecedor_id) != pedido_compra_para_baixa["fornecedor_id"]:
            raise ApiError(
                "O fornecedor informado é diferente do fornecedor deste pedido de compra.", status=400
            )

    # Fase 13 — custo_unitario é OPCIONAL: quando informado, é o preço
    # pago por este lote especificamente (mesma unidade de `unidade`),
    # usado pelo motor de custeio (app/routes/custeio.py) para calcular o
    # custo médio real de compra do item e, a partir daí, o custo de cada
    # ordem de produção que consumir este lote. Não exige nenhuma
    # permissão nova — quem já pode registrar o recebimento (lotes.receber)
    # já pode informar o custo dele.
    custo_unitario = dados.get("custo_unitario")
    if custo_unitario is not None and custo_unitario != "":
        try:
            custo_unitario = float(custo_unitario)
        except (TypeError, ValueError):
            raise ApiError("custo_unitario deve ser numérico.", status=400)
        if custo_unitario < 0:
            raise ApiError("custo_unitario não pode ser negativo.", status=400)
    else:
        custo_unitario = None

    item = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError("Item não encontrado.", status=404)
    item = dict(item)

    if fornecedor_id:
        fornecedor = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone()
        if fornecedor is None:
            raise ApiError("Fornecedor não encontrado.", status=404)
        fornecedor = dict(fornecedor)
        if item["requer_fornecedor_homologado"]:
            homologado = conn.execute(
                "SELECT 1 FROM item_fornecedor_aprovado WHERE item_id = ? AND fornecedor_id = ?",
                (item_id, fornecedor_id),
            ).fetchone()
            if not homologado:
                raise ApiError(
                    "Este item exige fornecedor homologado, e o fornecedor informado não está homologado "
                    "para ele. Homologue-o antes (POST /fornecedores/<id>/itens) ou registre uma autorização "
                    "especial fora deste fluxo.",
                    status=403,
                )
        if fornecedor["status"] in ("bloqueado", "reprovado"):
            raise ApiError(f"Fornecedor está com status '{fornecedor['status']}' e não pode fornecer material.", status=403)

    status_inicial = "quarentena"

    temp_codigo = f"TEMP-{secrets.token_hex(8)}"
    cur = conn.execute(
        """
        INSERT INTO lotes (codigo_lote, item_id, fornecedor_id, lote_fornecedor, fabricacao, validade,
                            quantidade, unidade, status, nota_fiscal, pedido_compra, pedido_compra_id,
                            custo_unitario, empresa_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (temp_codigo, item_id, fornecedor_id, dados.get("lote_fornecedor"), dados.get("fabricacao"),
         dados.get("validade"), quantidade, unidade, status_inicial, dados.get("nota_fiscal"),
         dados.get("pedido_compra"), pedido_compra_id, custo_unitario, empresa_id, usuario_atual["id"]),
    )
    lote_id = cur.lastrowid
    codigo_lote = _gerar_codigo_lote(conn, lote_id)
    conn.execute("UPDATE lotes SET codigo_lote = ? WHERE id = ?", (codigo_lote, lote_id))

    audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                     acao="lote_recebido", valor_novo={"codigo_lote": codigo_lote, "item_id": item_id,
                                                        "quantidade": quantidade, "status": status_inicial,
                                                        "custo_unitario": custo_unitario},
                     ip=client_ip(), dispositivo=client_device())

    # Fase 58 — só agora, com o lote já criado (e o `lote_id` para o
    # registro de auditoria), abate a quantidade recebida contra a linha
    # do pedido e recalcula o status dele.
    if pedido_compra_id:
        dar_baixa_recebimento_no_pedido(conn, pedido_compra_id, item_id, quantidade, usuario_atual, lote_id)

    lote = _lote_ou_404(conn, lote_id)
    return jsonify(lote), 201


def bloquear_lote_interno(conn, lote_id, motivo, usuario_atual, pular_se_ja_bloqueado=False):
    """Lógica central de bloqueio de um lote, usada tanto pela rota de
    bloqueio individual abaixo quanto pelo bloqueio em massa a partir de
    uma simulação de recall (Fase 16, `rastreabilidade.py`) — centralizada
    aqui de propósito para as duas nunca divergirem uma da outra (mesmo
    motivo que gerou `_baixado_liquido`/`_contas_em_aberto` na Fase 15).

    Devolve o lote atualizado, ou `None` se `pular_se_ja_bloqueado=True` e
    o lote já estava bloqueado (usado pelo bloqueio em massa, onde alguns
    lotes afetados já podem estar bloqueados de uma investigação
    anterior — isso não deve interromper nem falhar o restante do lote)."""
    lote = _lote_ou_404(conn, lote_id)
    if lote["status"] == "bloqueado":
        if pular_se_ja_bloqueado:
            return None
        raise ApiError("Este lote já está bloqueado.", status=400)

    conn.execute(
        "UPDATE lotes SET status = 'bloqueado', status_antes_bloqueio = ?, motivo_bloqueio = ?, "
        "atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (lote["status"], motivo, _now_iso(), usuario_atual["id"], lote_id),
    )
    audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                     acao="lote_bloqueado", valor_anterior={"status": lote["status"]},
                     valor_novo={"status": "bloqueado"}, motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return _lote_ou_404(conn, lote_id)


@bp.post("/<int:lote_id>/bloquear")
@requires_permission("lotes", "bloquear")
def bloquear(lote_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo do bloqueio.", status=400)
    lote = bloquear_lote_interno(conn, lote_id, motivo, usuario_atual)
    return jsonify(lote)


@bp.post("/<int:lote_id>/desbloquear")
@requires_permission("lotes", "bloquear")
def desbloquear(lote_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    lote = _lote_ou_404(conn, lote_id)
    if lote["status"] != "bloqueado":
        raise ApiError("Este lote não está bloqueado.", status=400)

    status_restaurado = lote["status_antes_bloqueio"] or "quarentena"
    conn.execute(
        "UPDATE lotes SET status = ?, status_antes_bloqueio = NULL, motivo_bloqueio = NULL, "
        "atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (status_restaurado, _now_iso(), usuario_atual["id"], lote_id),
    )
    audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                     acao="lote_desbloqueado", valor_anterior={"status": "bloqueado"},
                     valor_novo={"status": status_restaurado}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_lote_ou_404(conn, lote_id))


# ============================================================
# FASE 85 — Configuração de Qualidade (singleton, mesmo padrão de
# configuracoes_fiscais_sped da Fase 79)
# ============================================================
@bp.get("/configuracao-qualidade")
@requires_permission("qualidade", "configurar")
def obter_configuracao_qualidade():
    conn = get_db()
    row = conn.execute("SELECT * FROM configuracoes_qualidade WHERE id = 1").fetchone()
    return jsonify(dict(row))


@bp.put("/configuracao-qualidade")
@requires_permission("qualidade", "configurar")
def atualizar_configuracao_qualidade():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = dict(conn.execute("SELECT * FROM configuracoes_qualidade WHERE id = 1").fetchone())
    exigir = bool(dados.get("exigir_nota_fiscal_entrada_para_aprovar_lote"))

    conn.execute(
        "UPDATE configuracoes_qualidade SET exigir_nota_fiscal_entrada_para_aprovar_lote = ?, atualizado_em = ?, atualizado_por = ? WHERE id = 1",
        (1 if exigir else 0, _now_iso(), usuario_atual["id"]),
    )
    novo = dict(conn.execute("SELECT * FROM configuracoes_qualidade WHERE id = 1").fetchone())
    audit.registrar(conn, tabela="configuracoes_qualidade", registro_id=1, usuario_id=usuario_atual["id"],
                     acao="configuracao_qualidade_atualizada", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(novo)


@bp.post("/<int:lote_id>/aprovar")
@requires_permission("lotes", "aprovar")
def aprovar(lote_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    lote = _lote_ou_404(conn, lote_id)
    if lote["status"] != "aguardando_aprovacao":
        raise ApiError(
            f"Só é possível aprovar um lote com status 'aguardando_aprovacao' (status atual: '{lote['status']}').",
            status=400,
        )

    analise = _analise_concluida_pendente_de_aprovacao(conn, lote_id)
    if analise is None:
        raise ApiError("Não há análise concluída para este lote.", status=400)

    # Fase 85 — se configurado (Administração > Configurações de
    # Qualidade), um lote RECEBIDO de fornecedor só pode ser aprovado
    # depois de vinculado a uma Nota Fiscal de Entrada já lançada (Fase
    # 78). Só se aplica a `origem == 'recebimento'` — um lote produzido
    # internamente (`origem == 'producao'`) nunca teve nem terá uma NF-e
    # de entrada, então nunca é bloqueado por esta checagem.
    config_qualidade = conn.execute(
        "SELECT exigir_nota_fiscal_entrada_para_aprovar_lote FROM configuracoes_qualidade WHERE id = 1"
    ).fetchone()
    if (
        config_qualidade
        and config_qualidade["exigir_nota_fiscal_entrada_para_aprovar_lote"]
        and lote["origem"] == "recebimento"
        and lote["nota_fiscal_entrada_id"] is None
    ):
        raise ApiError(
            "Este lote ainda não está vinculado a uma Nota Fiscal de Entrada lançada — a liberação está "
            "configurada para exigir esse vínculo antes da aprovação do CQ (vincule pela tela de Notas Fiscais "
            "de Entrada, ou desligue essa exigência em Administração > Configurações de Qualidade).",
            status=400,
        )

    # Segregação de função: quem registrou/concluiu a análise não pode ser
    # quem aprova a liberação do mesmo lote (mesmo padrão da Fase 1).
    if analise["analista_id"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você concluiu a análise deste lote e por isso não pode aprová-lo — a aprovação precisa ser "
            "feita por outro usuário do time de qualidade (segregação de função)."
        )

    aprovar_com_ressalva = bool(dados.get("aprovar_com_ressalva"))
    justificativa = dados.get("justificativa")

    if analise["conclusao"] == "nao_conforme" and not aprovar_com_ressalva:
        raise ApiError(
            "A análise concluiu 'não conforme'. Para aprovar mesmo assim, envie "
            "aprovar_com_ressalva=true e uma justificativa, ou use /reprovar.",
            status=400,
        )
    if aprovar_com_ressalva and not justificativa:
        raise ApiError("Informe a justificativa para aprovar com ressalva.", status=400)

    novo_status = "aprovado_com_ressalva" if aprovar_com_ressalva else "aprovado"
    conn.execute(
        "UPDATE lotes SET status = ?, atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (novo_status, _now_iso(), usuario_atual["id"], lote_id),
    )

    numero_unico = f"CoA-{lote['codigo_lote']}-{secrets.token_hex(3).upper()}"
    cur = conn.execute(
        "INSERT INTO certificados_analise (lote_id, numero_unico, conclusao, aprovado_por) VALUES (?, ?, ?, ?)",
        (lote_id, numero_unico, analise["conclusao"], usuario_atual["id"]),
    )
    coa_id = cur.lastrowid

    audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                     acao="lote_aprovado", valor_anterior={"status": "aguardando_aprovacao"},
                     valor_novo={"status": novo_status}, motivo=justificativa,
                     ip=client_ip(), dispositivo=client_device())
    audit.registrar(conn, tabela="certificados_analise", registro_id=coa_id, usuario_id=usuario_atual["id"],
                     acao="coa_emitido", valor_novo={"numero_unico": numero_unico, "lote_id": lote_id},
                     ip=client_ip(), dispositivo=client_device())

    lote_atualizado = _lote_ou_404(conn, lote_id)
    coa_row = conn.execute("SELECT * FROM certificados_analise WHERE id = ?", (coa_id,)).fetchone()
    lote_atualizado["certificado_analise"] = dict(coa_row) if coa_row else None
    return jsonify(lote_atualizado)


@bp.post("/<int:lote_id>/reprovar")
@requires_permission("lotes", "reprovar")
def reprovar(lote_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    conn = get_db()

    if not motivo:
        raise ApiError("Informe o motivo da reprovação.", status=400)

    lote = _lote_ou_404(conn, lote_id)
    if lote["status"] != "aguardando_aprovacao":
        raise ApiError(
            f"Só é possível reprovar um lote com status 'aguardando_aprovacao' (status atual: '{lote['status']}').",
            status=400,
        )

    analise = _analise_concluida_pendente_de_aprovacao(conn, lote_id)
    if analise and analise["analista_id"] == usuario_atual["id"]:
        raise ForbiddenError(
            "Você concluiu a análise deste lote e por isso não pode reprová-lo — a decisão precisa ser "
            "tomada por outro usuário do time de qualidade (segregação de função)."
        )

    conn.execute(
        "UPDATE lotes SET status = 'reprovado', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], lote_id),
    )
    audit.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=usuario_atual["id"],
                     acao="lote_reprovado", valor_anterior={"status": "aguardando_aprovacao"},
                     valor_novo={"status": "reprovado"}, motivo=motivo, ip=client_ip(), dispositivo=client_device())
    return jsonify(_lote_ou_404(conn, lote_id))


@bp.get("/<int:lote_id>/rastreabilidade")
@requires_permission("lotes", "visualizar")
def rastreabilidade(lote_id):
    conn = get_db()
    lote = _lote_ou_404(conn, lote_id)
    item = conn.execute("SELECT * FROM itens WHERE id = ?", (lote["item_id"],)).fetchone()
    fornecedor = None
    if lote["fornecedor_id"]:
        fornecedor = conn.execute("SELECT * FROM fornecedores WHERE id = ?", (lote["fornecedor_id"],)).fetchone()
    analises = conn.execute("SELECT * FROM analises WHERE lote_id = ? ORDER BY id", (lote_id,)).fetchall()
    analises_resultado = []
    for a in analises:
        a = dict(a)
        resultados = conn.execute("SELECT * FROM resultados_analise WHERE analise_id = ? ORDER BY id", (a["id"],)).fetchall()
        a["resultados"] = [dict(r) for r in resultados]
        analises_resultado.append(a)
    coas = conn.execute("SELECT * FROM certificados_analise WHERE lote_id = ? ORDER BY id", (lote_id,)).fetchall()
    auditoria_lote = conn.execute(
        "SELECT * FROM auditoria WHERE tabela = 'lotes' AND registro_id = ? ORDER BY id", (str(lote_id),)
    ).fetchall()

    # ---- Genealogia "para trás": de que lotes este lote foi produzido? ----
    # Só existe quando o lote nasceu de uma ordem de produção (Fase 3) — um
    # lote recebido de fornecedor não tem genealogia de origem além do
    # próprio fornecedor.
    genealogia_origem = None
    if lote.get("origem") == "producao" and lote.get("ordem_producao_id"):
        ordem = conn.execute("SELECT * FROM ordens_producao WHERE id = ?", (lote["ordem_producao_id"],)).fetchone()
        if ordem:
            consumos = conn.execute(
                """
                SELECT opc.*, l.codigo_lote, l.fornecedor_id, i.codigo AS item_codigo, i.descricao AS item_descricao
                FROM ordem_producao_consumo opc
                JOIN lotes l ON l.id = opc.lote_id
                JOIN itens i ON i.id = opc.item_id
                WHERE opc.ordem_producao_id = ? ORDER BY opc.id
                """,
                (lote["ordem_producao_id"],),
            ).fetchall()
            genealogia_origem = {"ordem_producao": dict(ordem), "lotes_consumidos": [dict(c) for c in consumos]}

    # ---- Genealogia "para frente": em que ordens de produção este lote
    # foi consumido, e que lote(s) essas ordens produziram? ----
    consumido_em = conn.execute(
        """
        SELECT opc.*, op.numero AS ordem_numero, op.status AS ordem_status, op.lote_produzido_id
        FROM ordem_producao_consumo opc
        JOIN ordens_producao op ON op.id = opc.ordem_producao_id
        WHERE opc.lote_id = ? ORDER BY opc.id
        """,
        (lote_id,),
    ).fetchall()
    genealogia_destino = []
    for c in consumido_em:
        c = dict(c)
        if c["lote_produzido_id"]:
            lote_gerado = conn.execute(
                "SELECT id, codigo_lote, status FROM lotes WHERE id = ?", (c["lote_produzido_id"],)
            ).fetchone()
            c["lote_gerado"] = dict(lote_gerado) if lote_gerado else None
        else:
            c["lote_gerado"] = None
        genealogia_destino.append(c)

    return jsonify({
        "lote": lote,
        "item": dict(item) if item else None,
        "fornecedor": dict(fornecedor) if fornecedor else None,
        "analises": analises_resultado,
        "certificados_analise": [dict(c) for c in coas],
        "historico_status": [dict(a) for a in auditoria_lote],
        "genealogia_origem": genealogia_origem,
        "genealogia_destino": genealogia_destino,
    })


# ===========================================================================
# Fase 10 — Certificado de Análise (CoA) em PDF
#
# Até aqui (Fase 2) o CoA já existia como um registro estruturado no banco
# (tabela certificados_analise) e era exibido na tela — mas não existia
# nenhum jeito de gerar um DOCUMENTO de verdade para enviar a um cliente ou
# anexar a uma nota fiscal, que é o formato que o mercado espera de um CoA.
# Esta rota é 100% um EXPORT: não grava nada em nenhuma tabela de negócio
# (só um evento de auditoria, para saber quem gerou o PDF e quando — útil
# em caso de auditoria externa querer saber se o CoA de um lote específico
# já foi baixado antes). Não existe permissão nova: gerar o PDF de um CoA
# que a pessoa já pode VER na tela (lotes.visualizar) não deveria exigir
# nada além disso — é a mesma informação, só formatada como PDF em vez de
# JSON.
# ===========================================================================

def _montar_dados_coa(conn, lote_id):
    """Reúne tudo que o PDF do CoA precisa: lote, item, origem (fornecedor
    OU ordem de produção — nunca as duas), o certificado de análise mais
    recente e a análise concluída que embasou a aprovação, com seus
    ensaios/resultados. Devolve None se o lote ainda não tem CoA emitido
    (nunca foi aprovado)."""
    lote = _lote_ou_404(conn, lote_id)

    coa = conn.execute(
        "SELECT * FROM certificados_analise WHERE lote_id = ? ORDER BY id DESC LIMIT 1", (lote_id,)
    ).fetchone()
    if coa is None:
        return None
    coa = dict(coa)

    item = conn.execute("SELECT * FROM itens WHERE id = ?", (lote["item_id"],)).fetchone()
    item = dict(item) if item else None

    fornecedor = None
    ordem_producao = None
    if lote.get("origem") == "producao" and lote.get("ordem_producao_id"):
        ordem = conn.execute(
            "SELECT numero, quantidade_planejada, quantidade_produzida FROM ordens_producao WHERE id = ?",
            (lote["ordem_producao_id"],),
        ).fetchone()
        ordem_producao = dict(ordem) if ordem else None
    elif lote.get("fornecedor_id"):
        forn = conn.execute("SELECT nome, cnpj FROM fornecedores WHERE id = ?", (lote["fornecedor_id"],)).fetchone()
        fornecedor = dict(forn) if forn else None

    analise = conn.execute(
        "SELECT * FROM analises WHERE lote_id = ? AND status = 'concluida' ORDER BY id DESC LIMIT 1", (lote_id,)
    ).fetchone()
    resultados = []
    if analise:
        resultados = conn.execute(
            "SELECT * FROM resultados_analise WHERE analise_id = ? ORDER BY id", (analise["id"],)
        ).fetchall()
        resultados = [dict(r) for r in resultados]

    aprovado_por_nome = None
    if coa.get("aprovado_por"):
        u = conn.execute("SELECT nome FROM usuarios WHERE id = ?", (coa["aprovado_por"],)).fetchone()
        aprovado_por_nome = u["nome"] if u else None

    return {
        "lote": lote,
        "item": item,
        "fornecedor": fornecedor,
        "ordem_producao": ordem_producao,
        "coa": coa,
        "resultados": resultados,
        "aprovado_por_nome": aprovado_por_nome,
    }


def _gerar_pdf_coa(dados):
    """Monta o PDF do CoA com reportlab (platypus) a partir dos dados já
    reunidos por `_montar_dados_coa`. Devolve os bytes do PDF pronto."""
    lote = dados["lote"]
    item = dados["item"]
    coa = dados["coa"]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        "TituloCoA", parent=estilos["Title"], fontSize=16, alignment=TA_CENTER, spaceAfter=2,
    )
    estilo_subtitulo = ParagraphStyle(
        "SubtituloCoA", parent=estilos["Normal"], fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor("#5a6472"), spaceAfter=16,
    )
    estilo_rotulo_secao = ParagraphStyle(
        "RotuloSecao", parent=estilos["Heading3"], fontSize=11, spaceBefore=12, spaceAfter=6,
        textColor=colors.HexColor("#1f3a5f"),
    )

    elementos = [
        Paragraph("Alphafitus Laboratório Nutracêutico Ltda.", estilo_titulo),
        Paragraph("Certificado de Análise (CoA)", estilo_subtitulo),
    ]

    dados_gerais = [
        ["Número do certificado", coa["numero_unico"]],
        ["Lote", lote["codigo_lote"]],
        ["Item", f"{item['codigo']} — {item['descricao']}" if item else "—"],
        ["Quantidade", f"{lote['quantidade']} {lote['unidade']}"],
    ]
    if dados["fornecedor"]:
        dados_gerais.append(["Fornecedor", f"{dados['fornecedor']['nome']} ({dados['fornecedor'].get('cnpj') or 's/ CNPJ'})"])
    if dados["ordem_producao"]:
        dados_gerais.append(["Ordem de produção", dados["ordem_producao"]["numero"]])
    dados_gerais.append(["Conclusão", "CONFORME" if coa["conclusao"] == "conforme" else "NÃO CONFORME (aprovado com ressalva)"])
    dados_gerais.append(["Status do lote", lote["status"].replace("_", " ").upper()])
    dados_gerais.append(["Aprovado por", dados["aprovado_por_nome"] or "—"])
    dados_gerais.append(["Emitido em", coa["emitido_em"]])

    tabela_geral = Table(dados_gerais, colWidths=[5 * cm, 11 * cm])
    tabela_geral.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#5a6472")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
    ]))
    elementos.append(tabela_geral)

    elementos.append(Paragraph("Resultados dos ensaios", estilo_rotulo_secao))
    if dados["resultados"]:
        cabecalho = ["Ensaio", "Especificação", "Resultado", "Unidade", "Conclusão"]
        linhas = [cabecalho]
        for r in dados["resultados"]:
            espec_min = r["especificacao_min"]
            espec_max = r["especificacao_max"]
            if espec_min is not None and espec_max is not None:
                especificacao = f"{espec_min} a {espec_max}"
            elif espec_max is not None:
                especificacao = f"≤ {espec_max}"
            elif espec_min is not None:
                especificacao = f"≥ {espec_min}"
            else:
                especificacao = "—"
            linhas.append([
                r["ensaio"],
                especificacao,
                str(r["resultado"]) if r["resultado"] is not None else "—",
                r["unidade"] or "—",
                "Conforme" if r["conclusao"] == "conforme" else ("Não conforme" if r["conclusao"] == "nao_conforme" else "—"),
            ])
        tabela_ensaios = Table(linhas, colWidths=[4.5 * cm, 3.5 * cm, 3 * cm, 2.5 * cm, 2.5 * cm])
        tabela_ensaios.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e6ea")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elementos.append(tabela_ensaios)
    else:
        elementos.append(Paragraph("Nenhum ensaio registrado para a análise que embasou esta aprovação.", estilos["Normal"]))

    elementos.append(Spacer(1, 24))
    elementos.append(Paragraph(
        "Este certificado é gerado automaticamente a partir dos registros eletrônicos do Alphafitus OS "
        "(análises, resultados e aprovação de lote), com trilha de auditoria imutável de cada etapa. "
        "A autenticidade dos dados pode ser conferida no sistema pelo número do certificado acima.",
        ParagraphStyle("Rodape", parent=estilos["Normal"], fontSize=8, textColor=colors.HexColor("#5a6472")),
    ))

    doc.build(elementos, onFirstPage=desenhar_cabecalho_logo, onLaterPages=desenhar_cabecalho_logo)
    return buffer.getvalue()


@bp.get("/<int:lote_id>/certificado-analise/pdf")
@requires_permission("lotes", "visualizar")
def certificado_analise_pdf(lote_id):
    usuario_atual = g.usuario_atual
    conn = get_db()

    dados = _montar_dados_coa(conn, lote_id)
    if dados is None:
        raise ApiError(
            "Este lote ainda não tem Certificado de Análise emitido (só lotes aprovados têm CoA).",
            status=400,
        )

    pdf_bytes = _gerar_pdf_coa(dados)

    audit.registrar(conn, tabela="certificados_analise", registro_id=dados["coa"]["id"], usuario_id=usuario_atual["id"],
                     acao="coa_pdf_gerado", valor_novo={"numero_unico": dados["coa"]["numero_unico"]},
                     ip=client_ip(), dispositivo=client_device())

    nome_arquivo = f"CoA-{dados['lote']['codigo_lote']}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
