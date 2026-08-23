"""
Fase 81 — Catálogo de Fluxo Configurável: rotas HTTP finas em cima de app/fluxo_service.py
(mesmo padrão de app/routes/boletos.py em cima de app/boleto_service.py). Ver a nota de
escopo completa em migrations/schema_fase81.sql.
"""
from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import fluxo_service
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("fluxo", __name__, url_prefix="/api/v1/fluxo")


# ============================================================
# CATÁLOGO (cadastro de tipos de etapa)
# ============================================================
@bp.get("/tipos-etapa")
@requires_permission("fluxo", "apontar")
def listar_tipos_etapa():
    conn = get_db()
    entidade_tipo = request.args.get("entidade_tipo")
    incluir_inativos = request.args.get("incluir_inativos") == "1"
    return jsonify(fluxo_service.listar_tipos_etapa(conn, entidade_tipo, incluir_inativos))


def _validar_perfil_id(conn, perfil_id):
    if perfil_id is None:
        return None
    if not conn.execute("SELECT 1 FROM perfis WHERE id = ?", (perfil_id,)).fetchone():
        raise ApiError("Perfil (setor) não encontrado.", status=404)
    return perfil_id


@bp.get("/perfis-disponiveis")
@requires_permission("fluxo", "configurar")
def listar_perfis_disponiveis():
    """Fase 100 — lista mínima (id/nome) para popular o seletor de "setor
    responsável" ao cadastrar/editar um tipo de etapa. Deliberadamente uma
    rota própria, em vez de exigir `perfis.visualizar` (que devolveria
    também as permissões de cada perfil, informação mais ampla do que
    quem cadastra uma etapa de fluxo precisa ver) — mesmo perfil que já
    tem `fluxo.configurar` (hoje só PCP/Administrador) já basta."""
    conn = get_db()
    rows = conn.execute("SELECT id, nome FROM perfis ORDER BY nome").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/tipos-etapa")
@requires_permission("fluxo", "configurar")
def criar_tipo_etapa():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    entidade_tipo = dados.get("entidade_tipo")
    if entidade_tipo not in fluxo_service.ENTIDADES_VALIDAS:
        raise ApiError(f"entidade_tipo deve ser um de: {', '.join(fluxo_service.ENTIDADES_VALIDAS)}.", status=400)
    codigo = (dados.get("codigo") or "").strip()
    nome = (dados.get("nome") or "").strip()
    if not codigo or not nome:
        raise ApiError("Informe codigo e nome.", status=400)
    perfil_id = _validar_perfil_id(conn, dados.get("perfil_id"))

    if conn.execute(
        "SELECT id FROM tipos_etapa_fluxo WHERE entidade_tipo = ? AND codigo = ?", (entidade_tipo, codigo)
    ).fetchone():
        raise ApiError("Já existe um tipo de etapa com este código para esta entidade.", status=409)

    cur = conn.execute(
        "INSERT INTO tipos_etapa_fluxo (entidade_tipo, codigo, nome, ordem_padrao, origem, perfil_id, criado_por) "
        "VALUES (?, ?, ?, ?, 'manual', ?, ?)",
        (entidade_tipo, codigo, nome, dados.get("ordem_padrao") or 0, perfil_id, usuario_atual["id"]),
    )
    tipo_id = cur.lastrowid
    audit.registrar(conn, tabela="tipos_etapa_fluxo", registro_id=tipo_id, usuario_id=usuario_atual["id"],
                     acao="tipo_etapa_fluxo_criado",
                     valor_novo={"entidade_tipo": entidade_tipo, "codigo": codigo, "nome": nome, "perfil_id": perfil_id},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM tipos_etapa_fluxo WHERE id = ?", (tipo_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.put("/tipos-etapa/<int:tipo_id>")
@requires_permission("fluxo", "configurar")
def editar_tipo_etapa(tipo_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = conn.execute("SELECT * FROM tipos_etapa_fluxo WHERE id = ?", (tipo_id,)).fetchone()
    if anterior is None:
        raise ApiError("Tipo de etapa não encontrado.", status=404)
    anterior = dict(anterior)

    nome = dados.get("nome", anterior["nome"])
    ordem_padrao = dados.get("ordem_padrao", anterior["ordem_padrao"])
    status = dados.get("status", anterior["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)
    perfil_id = _validar_perfil_id(conn, dados.get("perfil_id", anterior["perfil_id"]))

    conn.execute(
        "UPDATE tipos_etapa_fluxo SET nome = ?, ordem_padrao = ?, status = ?, perfil_id = ? WHERE id = ?",
        (nome, ordem_padrao, status, perfil_id, tipo_id),
    )
    novo = conn.execute("SELECT * FROM tipos_etapa_fluxo WHERE id = ?", (tipo_id,)).fetchone()
    audit.registrar(conn, tabela="tipos_etapa_fluxo", registro_id=tipo_id, usuario_id=usuario_atual["id"],
                     acao="tipo_etapa_fluxo_editado", valor_anterior=anterior, valor_novo=dict(novo),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo))


# ============================================================
# ETAPAS DE UMA ENTIDADE CONCRETA
# ============================================================
@bp.get("/<entidade_tipo>/<int:entidade_id>/etapas")
@requires_permission("fluxo", "apontar")
def listar_etapas_entidade(entidade_tipo, entidade_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    return jsonify(fluxo_service.etapas_da_entidade(conn, entidade_tipo, entidade_id, usuario_atual["id"]))


@bp.post("/<entidade_tipo>/<int:entidade_id>/etapas/<int:tipo_etapa_fluxo_id>/iniciar")
@requires_permission("fluxo", "apontar")
def iniciar_etapa_entidade(entidade_tipo, entidade_id, tipo_etapa_fluxo_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    resultado = fluxo_service.iniciar_etapa(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id, usuario_atual["id"])
    audit.registrar(conn, tabela="fluxo_instancias", registro_id=resultado["id"], usuario_id=usuario_atual["id"],
                     acao="fluxo_etapa_iniciada", valor_novo={"entidade_tipo": entidade_tipo, "entidade_id": entidade_id, "codigo": resultado["codigo"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(resultado)


@bp.post("/<entidade_tipo>/<int:entidade_id>/etapas/<int:tipo_etapa_fluxo_id>/concluir")
@requires_permission("fluxo", "apontar")
def concluir_etapa_entidade(entidade_tipo, entidade_id, tipo_etapa_fluxo_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    resultado = fluxo_service.concluir_etapa(
        conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id, usuario_atual["id"], dados.get("observacao")
    )
    audit.registrar(conn, tabela="fluxo_instancias", registro_id=resultado["id"], usuario_id=usuario_atual["id"],
                     acao="fluxo_etapa_concluida", valor_novo={"entidade_tipo": entidade_tipo, "entidade_id": entidade_id, "codigo": resultado["codigo"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(resultado)
