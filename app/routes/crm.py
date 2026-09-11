"""
Fase 171 — CRM: Funil de Vendas (Oportunidades).

Pedido do usuário: "CRM de vendas em tempo real, cada mudança do que está
sendo feita pelos vendedores e usuários". Ver a nota de arquitetura completa
em migrations/schema_fase171.sql — resumo: o sistema já acompanhava a venda
DEPOIS que virava `pedidos_venda` (Fase 5); isto aqui cobre o que acontece
ANTES (prospecção → contato → proposta → negociação → ganho/perdido), e a
tabela `crm_oportunidades_atividades` é ao mesmo tempo a linha do tempo de
cada oportunidade E o feed ao vivo geral (`GET /atividades-recentes`).

VISIBILIDADE — mesma régua já usada em `clientes.vendedor_responsavel_id`
(Fase 150, App de Vendas): quem só tem `oportunidades.visualizar` enxerga
exclusivamente as PRÓPRIAS oportunidades; `oportunidades.visualizar_todas`
(gestor comercial) enxerga as de todo mundo. Nunca um parâmetro de URL/corpo
decide isso — sempre resolvido a partir de quem está logado, do mesmo jeito
que a auditoria de segurança desta sessão corrigiu em `vendas_app.py`.
"""
import datetime
import secrets

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..permissions import requires_permission, usuario_tem_permissao

bp = Blueprint("crm", __name__, url_prefix="/api/v1/crm")

ETAPAS = ("novo_contato", "qualificacao", "proposta_enviada", "negociacao", "fechado_ganho", "fechado_perdido")
ETAPAS_FECHADAS = ("fechado_ganho", "fechado_perdido")
TIPOS_ATIVIDADE_MANUAL = ("nota", "ligacao", "reuniao", "email")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _gerar_numero_oportunidade():
    ano = datetime.datetime.utcnow().year
    return f"OP-{ano}-{secrets.token_hex(4).upper()}"


def _pode_ver_todas(conn, usuario_id):
    return usuario_tem_permissao(conn, usuario_id, "oportunidades", "visualizar_todas")


def _registrar_atividade(conn, oportunidade_id, tipo, descricao, usuario_id, etapa_anterior=None, etapa_nova=None):
    conn.execute(
        """
        INSERT INTO crm_oportunidades_atividades
            (oportunidade_id, tipo, descricao, etapa_anterior, etapa_nova, usuario_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (oportunidade_id, tipo, descricao, etapa_anterior, etapa_nova, usuario_id),
    )


def _oportunidade_ou_404(conn, usuario_atual, oportunidade_id):
    """Nunca revela a EXISTÊNCIA de uma oportunidade de outro vendedor pra
    quem não tem `visualizar_todas` — mesmo 404 tanto pra "não existe"
    quanto pra "existe mas não é sua", exatamente como o resto do sistema
    trata caso análogo (ver `_sessao_do_pedido_ou_erro` em vendas_app.py,
    que usa 403 porque ali a mensagem em si não vaza nada; aqui a simples
    existência de uma oportunidade sobre um prospect já é informação
    comercial sensível, por isso 404)."""
    row = conn.execute("SELECT * FROM crm_oportunidades WHERE id = ?", (oportunidade_id,)).fetchone()
    if row is None:
        raise ApiError("Oportunidade não encontrada.", status=404)
    row = dict(row)
    if row["vendedor_responsavel_id"] != usuario_atual["id"] and not _pode_ver_todas(conn, usuario_atual["id"]):
        raise ApiError("Oportunidade não encontrada.", status=404)
    return row


def _oportunidade_publica(conn, row):
    d = dict(row)
    if d.get("cliente_id"):
        cliente = conn.execute("SELECT razao_social, nome_fantasia FROM clientes WHERE id = ?", (d["cliente_id"],)).fetchone()
        d["cliente_nome"] = (cliente["nome_fantasia"] or cliente["razao_social"]) if cliente else None
    else:
        d["cliente_nome"] = None
    vendedor = conn.execute("SELECT nome FROM usuarios WHERE id = ?", (d["vendedor_responsavel_id"],)).fetchone()
    d["vendedor_nome"] = vendedor["nome"] if vendedor else None
    if d.get("pedido_venda_id"):
        pedido = conn.execute("SELECT numero FROM pedidos_venda WHERE id = ?", (d["pedido_venda_id"],)).fetchone()
        d["pedido_venda_numero"] = pedido["numero"] if pedido else None
    else:
        d["pedido_venda_numero"] = None
    return d


@bp.get("/oportunidades")
@requires_permission("oportunidades", "visualizar")
def listar_oportunidades():
    usuario_atual = g.usuario_atual
    conn = get_db()
    etapa = request.args.get("etapa")
    vendedor_id = request.args.get("vendedor_id", type=int)
    busca = (request.args.get("busca") or "").strip()

    clausulas, params = [], []
    if not _pode_ver_todas(conn, usuario_atual["id"]):
        clausulas.append("o.vendedor_responsavel_id = ?")
        params.append(usuario_atual["id"])
    elif vendedor_id:
        clausulas.append("o.vendedor_responsavel_id = ?")
        params.append(vendedor_id)
    if etapa:
        if etapa not in ETAPAS:
            raise ApiError(f"etapa deve ser uma de: {', '.join(ETAPAS)}.", status=400)
        clausulas.append("o.etapa = ?")
        params.append(etapa)
    if busca:
        clausulas.append(
            "(o.titulo LIKE ? OR o.nome_prospect LIKE ? OR o.numero LIKE ? OR "
            "EXISTS (SELECT 1 FROM clientes c WHERE c.id = o.cliente_id AND "
            "(c.razao_social LIKE ? OR c.nome_fantasia LIKE ?)))"
        )
        termo = f"%{busca}%"
        params.extend([termo, termo, termo, termo, termo])
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"SELECT o.* FROM crm_oportunidades o {where} ORDER BY o.etapa_atualizada_em DESC LIMIT 500",
        params,
    ).fetchall()
    return jsonify([_oportunidade_publica(conn, r) for r in rows])


@bp.get("/oportunidades/<int:oportunidade_id>")
@requires_permission("oportunidades", "visualizar")
def obter_oportunidade(oportunidade_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = _oportunidade_ou_404(conn, usuario_atual, oportunidade_id)
    resultado = _oportunidade_publica(conn, row)
    atividades = conn.execute(
        """
        SELECT a.*, u.nome AS usuario_nome
        FROM crm_oportunidades_atividades a
        JOIN usuarios u ON u.id = a.usuario_id
        WHERE a.oportunidade_id = ?
        ORDER BY a.criado_em DESC
        """,
        (oportunidade_id,),
    ).fetchall()
    resultado["atividades"] = [dict(a) for a in atividades]
    return jsonify(resultado)


@bp.post("/oportunidades")
@requires_permission("oportunidades", "gerenciar")
def criar_oportunidade():
    usuario_atual = g.usuario_atual
    conn = get_db()
    dados = request.get_json(silent=True) or {}

    titulo = (dados.get("titulo") or "").strip()
    cliente_id = dados.get("cliente_id")
    nome_prospect = (dados.get("nome_prospect") or "").strip()
    if not titulo:
        raise ApiError("Informe um título para a oportunidade.", status=400)
    if not cliente_id and not nome_prospect:
        raise ApiError("Informe cliente_id (cliente já cadastrado) ou nome_prospect (ainda não cadastrado).", status=400)
    if cliente_id and not conn.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone():
        raise ApiError("Cliente não encontrado.", status=404)

    # Só quem enxerga o funil inteiro pode atribuir a oportunidade a OUTRO
    # vendedor — mesma régua de "não pode conceder mais do que tem"
    # (achado de auditoria de segurança desta sessão): sem isto, qualquer
    # vendedor comum poderia criar oportunidades em nome de outro.
    vendedor_id = dados.get("vendedor_responsavel_id") or usuario_atual["id"]
    if vendedor_id != usuario_atual["id"] and not _pode_ver_todas(conn, usuario_atual["id"]):
        raise ForbiddenError("Você só pode criar oportunidades em seu próprio nome.")

    valor_estimado = dados.get("valor_estimado")
    if valor_estimado is not None:
        try:
            valor_estimado = float(valor_estimado)
        except (TypeError, ValueError):
            raise ApiError("valor_estimado deve ser numérico.", status=400)
        if valor_estimado < 0:
            raise ApiError("valor_estimado não pode ser negativo.", status=400)

    numero = _gerar_numero_oportunidade()
    cur = conn.execute(
        """
        INSERT INTO crm_oportunidades
            (numero, cliente_id, nome_prospect, contato_nome, contato_telefone, contato_email,
             titulo, valor_estimado, origem, vendedor_responsavel_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (numero, cliente_id or None, nome_prospect or None,
         (dados.get("contato_nome") or "").strip() or None, (dados.get("contato_telefone") or "").strip() or None,
         (dados.get("contato_email") or "").strip() or None, titulo, valor_estimado,
         (dados.get("origem") or "").strip() or None, vendedor_id, usuario_atual["id"]),
    )
    oportunidade_id = cur.lastrowid
    _registrar_atividade(conn, oportunidade_id, "criacao", f"Oportunidade criada: {titulo}", usuario_atual["id"])
    audit.registrar(conn, tabela="crm_oportunidades", registro_id=oportunidade_id, usuario_id=usuario_atual["id"],
                     acao="oportunidade_criada", valor_novo={"numero": numero, "titulo": titulo},
                     ip=client_ip(), dispositivo=client_device())
    conn.commit()
    return obter_oportunidade(oportunidade_id), 201


@bp.put("/oportunidades/<int:oportunidade_id>")
@requires_permission("oportunidades", "gerenciar")
def editar_oportunidade(oportunidade_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    anterior = _oportunidade_ou_404(conn, usuario_atual, oportunidade_id)
    dados = request.get_json(silent=True) or {}

    titulo = (dados.get("titulo") or anterior["titulo"] or "").strip()
    if not titulo:
        raise ApiError("Informe um título para a oportunidade.", status=400)
    valor_estimado = dados.get("valor_estimado", anterior["valor_estimado"])
    if valor_estimado is not None:
        try:
            valor_estimado = float(valor_estimado)
        except (TypeError, ValueError):
            raise ApiError("valor_estimado deve ser numérico.", status=400)
        if valor_estimado < 0:
            raise ApiError("valor_estimado não pode ser negativo.", status=400)

    conn.execute(
        """
        UPDATE crm_oportunidades SET
            titulo = ?, valor_estimado = ?, contato_nome = ?, contato_telefone = ?,
            contato_email = ?, origem = ?, atualizado_em = ?
        WHERE id = ?
        """,
        (titulo, valor_estimado,
         (dados.get("contato_nome", anterior["contato_nome"]) or "").strip() or None,
         (dados.get("contato_telefone", anterior["contato_telefone"]) or "").strip() or None,
         (dados.get("contato_email", anterior["contato_email"]) or "").strip() or None,
         (dados.get("origem", anterior["origem"]) or "").strip() or None,
         _now_iso(), oportunidade_id),
    )
    audit.registrar(conn, tabela="crm_oportunidades", registro_id=oportunidade_id, usuario_id=usuario_atual["id"],
                     acao="oportunidade_editada", valor_anterior=_oportunidade_publica(conn, anterior),
                     ip=client_ip(), dispositivo=client_device())
    conn.commit()
    return obter_oportunidade(oportunidade_id)


@bp.post("/oportunidades/<int:oportunidade_id>/mudar-etapa")
@requires_permission("oportunidades", "gerenciar")
def mudar_etapa(oportunidade_id):
    """Mesma filosofia de kanban livre (arrastar pra qualquer coluna) já
    usada em `terceirizacao_artes`/`fluxo_instancias` do sistema — sem
    máquina de estados rígida, porque negociação real vai e volta. Duas
    regras de negócio, só essas: (1) fechar como 'perdido' exige motivo
    (fica registrado pra sempre — dado real de por que se perde venda,
    não estatística inventada); (2) mover PRA FORA de uma etapa fechada
    (reabrir) limpa `fechado_em`/`motivo_perda`."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    anterior = _oportunidade_ou_404(conn, usuario_atual, oportunidade_id)
    dados = request.get_json(silent=True) or {}
    etapa_nova = dados.get("etapa")
    if etapa_nova not in ETAPAS:
        raise ApiError(f"etapa deve ser uma de: {', '.join(ETAPAS)}.", status=400)
    etapa_anterior = anterior["etapa"]
    if etapa_nova == etapa_anterior:
        return obter_oportunidade(oportunidade_id)

    motivo_perda = (dados.get("motivo_perda") or "").strip()
    if etapa_nova == "fechado_perdido" and not motivo_perda:
        raise ApiError("Informe o motivo da perda.", status=400)

    agora = _now_iso()
    fechado_em = agora if etapa_nova in ETAPAS_FECHADAS else None
    motivo_perda_final = motivo_perda if etapa_nova == "fechado_perdido" else None
    conn.execute(
        """
        UPDATE crm_oportunidades SET
            etapa = ?, etapa_atualizada_em = ?, atualizado_em = ?, fechado_em = ?, motivo_perda = ?
        WHERE id = ?
        """,
        (etapa_nova, agora, agora, fechado_em, motivo_perda_final, oportunidade_id),
    )
    descricao = f"Etapa alterada: {etapa_anterior} → {etapa_nova}"
    if motivo_perda_final:
        descricao += f" (motivo: {motivo_perda_final})"
    _registrar_atividade(conn, oportunidade_id, "mudanca_etapa", descricao, usuario_atual["id"],
                          etapa_anterior=etapa_anterior, etapa_nova=etapa_nova)
    audit.registrar(conn, tabela="crm_oportunidades", registro_id=oportunidade_id, usuario_id=usuario_atual["id"],
                     acao="oportunidade_etapa_alterada",
                     valor_anterior={"etapa": etapa_anterior}, valor_novo={"etapa": etapa_nova, "motivo_perda": motivo_perda_final},
                     ip=client_ip(), dispositivo=client_device())
    conn.commit()
    return obter_oportunidade(oportunidade_id)


@bp.post("/oportunidades/<int:oportunidade_id>/atividades")
@requires_permission("oportunidades", "gerenciar")
def registrar_atividade_manual(oportunidade_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _oportunidade_ou_404(conn, usuario_atual, oportunidade_id)
    dados = request.get_json(silent=True) or {}
    tipo = dados.get("tipo")
    descricao = (dados.get("descricao") or "").strip()
    if tipo not in TIPOS_ATIVIDADE_MANUAL:
        raise ApiError(f"tipo deve ser uma de: {', '.join(TIPOS_ATIVIDADE_MANUAL)}.", status=400)
    if not descricao:
        raise ApiError("Descreva a atividade.", status=400)
    _registrar_atividade(conn, oportunidade_id, tipo, descricao, usuario_atual["id"])
    conn.execute("UPDATE crm_oportunidades SET atualizado_em = ? WHERE id = ?", (_now_iso(), oportunidade_id))
    conn.commit()
    return obter_oportunidade(oportunidade_id)


@bp.get("/funil")
@requires_permission("oportunidades", "visualizar")
def funil():
    """Resumo por etapa (contagem + valor estimado) — alimenta o
    cabeçalho de cada coluna do kanban e a taxa de conversão. Mesma
    régua de visibilidade das outras rotas: sem `visualizar_todas`, só
    conta as próprias oportunidades."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    where, params = "", []
    if not _pode_ver_todas(conn, usuario_atual["id"]):
        where = "WHERE vendedor_responsavel_id = ?"
        params.append(usuario_atual["id"])
    rows = conn.execute(
        f"SELECT etapa, COUNT(*) AS total, COALESCE(SUM(valor_estimado), 0) AS valor_total "
        f"FROM crm_oportunidades {where} GROUP BY etapa",
        params,
    ).fetchall()
    por_etapa = {etapa: {"total": 0, "valor_total": 0.0} for etapa in ETAPAS}
    for r in rows:
        por_etapa[r["etapa"]] = {"total": r["total"], "valor_total": r["valor_total"]}
    total_fechadas = por_etapa["fechado_ganho"]["total"] + por_etapa["fechado_perdido"]["total"]
    taxa_conversao = (por_etapa["fechado_ganho"]["total"] / total_fechadas * 100) if total_fechadas else None
    return jsonify({"por_etapa": por_etapa, "taxa_conversao_percentual": taxa_conversao})


@bp.get("/atividades-recentes")
@requires_permission("oportunidades", "visualizar")
def atividades_recentes():
    """O feed ao vivo pedido: últimas atividades de TODAS as oportunidades
    visíveis ao usuário (a mesma régua de visualizar/visualizar_todas),
    mais novas primeiro. O front faz polling curto nesta rota — mesma
    filosofia de "tempo real" já usada em Painel Tempo Real (Fase 75/90):
    sem WebSocket, só consulta AO VIVO num intervalo curto."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    where = ""
    params = []
    if not _pode_ver_todas(conn, usuario_atual["id"]):
        where = "WHERE o.vendedor_responsavel_id = ?"
        params.append(usuario_atual["id"])
    rows = conn.execute(
        f"""
        SELECT a.id, a.tipo, a.descricao, a.etapa_anterior, a.etapa_nova, a.criado_em,
               u.nome AS usuario_nome, o.id AS oportunidade_id, o.numero AS oportunidade_numero, o.titulo AS oportunidade_titulo
        FROM crm_oportunidades_atividades a
        JOIN crm_oportunidades o ON o.id = a.oportunidade_id
        JOIN usuarios u ON u.id = a.usuario_id
        {where}
        ORDER BY a.id DESC LIMIT 50
        """,
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/vendedores")
@requires_permission("oportunidades", "visualizar_todas")
def listar_vendedores_com_oportunidade():
    """Pra popular o filtro "vendedor" na tela do gestor — só quem pode
    ver o funil inteiro precisa disto."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT DISTINCT u.id, u.nome FROM crm_oportunidades o
        JOIN usuarios u ON u.id = o.vendedor_responsavel_id
        ORDER BY u.nome
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])
