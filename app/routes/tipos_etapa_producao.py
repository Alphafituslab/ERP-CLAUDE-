"""Fase 75 — catálogo de Tipos de Etapa de Produção.

Cadastro reaproveitável (Pesagem, Mistura, Granulação, etc. — ver o
comentário completo em migrations/schema_fase75.sql) usado por
`app/routes/producao.py` para vincular cada etapa concreta de uma ordem
(`ordem_producao_etapas.tipo_etapa_id`) a um tipo do catálogo, e por
`app/routes/painel_tempo_real.py` para exibir o nome/unidade no painel de
chão de fábrica.

Leitura (`GET`) exige só `producao.visualizar` — o mesmo que já enxerga
qualquer outra tela do módulo. Escrita (`POST`/`PUT`) exige a permissão
nova `producao.configurar_etapas`, dada por padrão só ao perfil "PCP" (ver
seed.py) — é uma decisão de configuração do processo produtivo, não uma
ação do dia a dia do chão de fábrica.

Sem DELETE: um tipo de etapa pode já estar referenciado em etapas
concretas de ordens antigas/em andamento (`ordem_producao_etapas.
tipo_etapa_id`), então excluir de verdade quebraria esse histórico. Em vez
disso, PUT permite marcar `status = 'inativo'` — some das opções ao
cadastrar uma etapa NOVA, mas etapas já vinculadas ao tipo continuam
funcionando normalmente."""

from flask import g, jsonify, request
from flask import Blueprint

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("tipos_etapa_producao", __name__, url_prefix="/api/v1/producao/tipos-etapa")


def _tipo_ou_404(conn, tipo_id):
    row = conn.execute("SELECT * FROM tipos_etapa_producao WHERE id = ?", (tipo_id,)).fetchone()
    if row is None:
        raise ApiError("Tipo de etapa não encontrado.", status=404)
    return row


@bp.get("")
@requires_permission("producao", "visualizar")
def listar():
    conn = get_db()
    apenas_ativos = request.args.get("apenas_ativos") == "1"
    if apenas_ativos:
        rows = conn.execute(
            "SELECT * FROM tipos_etapa_producao WHERE status = 'ativo' ORDER BY ordem_padrao, nome"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tipos_etapa_producao ORDER BY ordem_padrao, nome").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@requires_permission("producao", "configurar_etapas")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ApiError("Informe nome.", status=400)

    conn = get_db()
    if conn.execute("SELECT id FROM tipos_etapa_producao WHERE nome = ?", (nome,)).fetchone():
        raise ApiError(f"Já existe um tipo de etapa chamado '{nome}'.", status=409)

    unidade_valor = (dados.get("unidade_valor") or "").strip() or None

    ordem_padrao = dados.get("ordem_padrao")
    if ordem_padrao in (None, ""):
        proxima = conn.execute(
            "SELECT COALESCE(MAX(ordem_padrao), 0) + 1 AS proxima FROM tipos_etapa_producao"
        ).fetchone()["proxima"]
        ordem_padrao = proxima
    else:
        try:
            ordem_padrao = int(ordem_padrao)
        except (TypeError, ValueError):
            raise ApiError("ordem_padrao deve ser um número inteiro.", status=400)

    cur = conn.execute(
        "INSERT INTO tipos_etapa_producao (nome, unidade_valor, ordem_padrao, criado_por) VALUES (?, ?, ?, ?)",
        (nome, unidade_valor, ordem_padrao, usuario_atual["id"]),
    )
    tipo_id = cur.lastrowid
    audit.registrar(conn, tabela="tipos_etapa_producao", registro_id=tipo_id, usuario_id=usuario_atual["id"],
                     acao="tipo_etapa_criado",
                     valor_novo={"nome": nome, "unidade_valor": unidade_valor, "ordem_padrao": ordem_padrao},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(_tipo_ou_404(conn, tipo_id))), 201


@bp.put("/<int:tipo_id>")
@requires_permission("producao", "configurar_etapas")
def editar(tipo_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    tipo = _tipo_ou_404(conn, tipo_id)
    dados = request.get_json(silent=True) or {}

    nome = dados.get("nome", tipo["nome"])
    if not (nome or "").strip():
        raise ApiError("nome não pode ficar vazio.", status=400)
    nome = nome.strip()
    outro = conn.execute(
        "SELECT id FROM tipos_etapa_producao WHERE nome = ? AND id != ?", (nome, tipo_id)
    ).fetchone()
    if outro:
        raise ApiError(f"Já existe um tipo de etapa chamado '{nome}'.", status=409)

    unidade_valor = dados.get("unidade_valor", tipo["unidade_valor"])
    unidade_valor = (unidade_valor or "").strip() or None

    ordem_padrao = dados.get("ordem_padrao", tipo["ordem_padrao"])
    try:
        ordem_padrao = int(ordem_padrao)
    except (TypeError, ValueError):
        raise ApiError("ordem_padrao deve ser um número inteiro.", status=400)

    status = dados.get("status", tipo["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    conn.execute(
        "UPDATE tipos_etapa_producao SET nome = ?, unidade_valor = ?, ordem_padrao = ?, status = ? WHERE id = ?",
        (nome, unidade_valor, ordem_padrao, status, tipo_id),
    )
    audit.registrar(conn, tabela="tipos_etapa_producao", registro_id=tipo_id, usuario_id=usuario_atual["id"],
                     acao="tipo_etapa_editado", valor_anterior=dict(tipo),
                     valor_novo={"nome": nome, "unidade_valor": unidade_valor, "ordem_padrao": ordem_padrao, "status": status},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(_tipo_ou_404(conn, tipo_id)))
