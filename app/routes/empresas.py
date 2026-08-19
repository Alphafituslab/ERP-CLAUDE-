import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("empresas", __name__, url_prefix="/api/v1/empresas")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@bp.get("")
@requires_permission("empresas", "visualizar")
def listar():
    conn = get_db()
    rows = conn.execute("SELECT * FROM empresas ORDER BY razao_social").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@requires_permission("empresas", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    razao_social = (dados.get("razao_social") or "").strip()
    cnpj = (dados.get("cnpj") or "").strip()
    nome_fantasia = dados.get("nome_fantasia")
    conn = get_db()

    if not razao_social or not cnpj:
        raise ApiError("Informe razao_social e cnpj.", status=400)
    if conn.execute("SELECT id FROM empresas WHERE cnpj = ?", (cnpj,)).fetchone():
        raise ApiError("Já existe uma empresa com este CNPJ.", status=409)

    cur = conn.execute(
        "INSERT INTO empresas (razao_social, nome_fantasia, cnpj, criado_por) VALUES (?, ?, ?, ?)",
        (razao_social, nome_fantasia, cnpj, usuario_atual["id"]),
    )
    empresa_id = cur.lastrowid
    audit.registrar(conn, tabela="empresas", registro_id=empresa_id, usuario_id=usuario_atual["id"],
                     acao="empresa_criada", valor_novo={"razao_social": razao_social, "cnpj": cnpj},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    return jsonify(dict(row)), 201


# Fase 70 — campos de dados fiscais da empresa (exigidos para emitir NF-e,
# ver migrations/schema_fase70.sql); nenhum é obrigatório para o CADASTRO
# da empresa em si (continua bastando razao_social + cnpj), só ficam
# obrigatórios NA HORA de tentar emitir uma nota (validado em
# app/nfe_service.py::validar_pronto_para_emitir).
CAMPOS_FISCAIS_EMPRESA_EDITAVEIS = (
    "inscricao_estadual", "regime_tributario", "logradouro", "numero_endereco",
    "complemento_endereco", "bairro", "municipio", "codigo_ibge_municipio", "uf", "cep",
)
REGIMES_TRIBUTARIOS_VALIDOS = ("simples_nacional", "lucro_presumido", "lucro_real")


@bp.put("/<int:empresa_id>")
@requires_permission("empresas", "editar")
def editar(empresa_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if row is None:
        raise ApiError("Empresa não encontrada.", status=404)
    anterior = dict(row)

    nome_fantasia = dados.get("nome_fantasia", anterior["nome_fantasia"])
    status = dados.get("status", anterior["status"])
    if status not in ("ativa", "inativa"):
        raise ApiError("status deve ser 'ativa' ou 'inativa'.", status=400)

    valores = {campo: dados.get(campo, anterior[campo]) for campo in CAMPOS_FISCAIS_EMPRESA_EDITAVEIS}
    if valores["regime_tributario"] not in REGIMES_TRIBUTARIOS_VALIDOS:
        raise ApiError(f"regime_tributario deve ser um de: {', '.join(REGIMES_TRIBUTARIOS_VALIDOS)}.", status=400)

    conn.execute(
        f"""
        UPDATE empresas SET nome_fantasia = ?, status = ?, atualizado_em = ?, atualizado_por = ?,
               {', '.join(f'{c} = ?' for c in CAMPOS_FISCAIS_EMPRESA_EDITAVEIS)}
        WHERE id = ?
        """,
        (nome_fantasia, status, _now_iso(), usuario_atual["id"], *[valores[c] for c in CAMPOS_FISCAIS_EMPRESA_EDITAVEIS], empresa_id),
    )
    novo_row = conn.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    audit.registrar(conn, tabela="empresas", registro_id=empresa_id, usuario_id=usuario_atual["id"],
                     acao="empresa_editada", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo_row))


@bp.post("/<int:empresa_id>/unidades")
@requires_permission("empresas", "cadastrar")
def criar_unidade(empresa_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    tipo = dados.get("tipo") or "unidade"
    endereco = dados.get("endereco")
    conn = get_db()

    if not conn.execute("SELECT id FROM empresas WHERE id = ?", (empresa_id,)).fetchone():
        raise ApiError("Empresa não encontrada.", status=404)
    if not nome:
        raise ApiError("Informe o nome da unidade.", status=400)
    if tipo not in ("unidade", "deposito", "laboratorio"):
        raise ApiError("tipo deve ser 'unidade', 'deposito' ou 'laboratorio'.", status=400)

    cur = conn.execute(
        "INSERT INTO unidades (empresa_id, nome, tipo, endereco, criado_por) VALUES (?, ?, ?, ?, ?)",
        (empresa_id, nome, tipo, endereco, usuario_atual["id"]),
    )
    unidade_id = cur.lastrowid
    audit.registrar(conn, tabela="unidades", registro_id=unidade_id, usuario_id=usuario_atual["id"],
                     acao="unidade_criada", valor_novo={"nome": nome, "tipo": tipo, "empresa_id": empresa_id},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM unidades WHERE id = ?", (unidade_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.get("/<int:empresa_id>/unidades")
@requires_permission("empresas", "visualizar")
def listar_unidades(empresa_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM unidades WHERE empresa_id = ? ORDER BY nome", (empresa_id,)).fetchall()
    return jsonify([dict(r) for r in rows])
