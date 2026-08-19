"""
Fase 27 — Padronização de Rótulo do Memorial Técnico ANVISA.

A Fase 24 (fundação do módulo) deixou de propósito de fora "a página de
padronização de rótulo (rótulo formatado a partir dos dados do
memorial)", citando-a como próximo passo. Esta fase entrega isso: um
registro 1:1 por memorial com os "dizeres de rotulagem" — os campos que
vão literalmente impressos no rótulo do produto.

Permissão: verbo novo ("padronizar") no recurso `memoriais` já existente,
em vez de um recurso à parte — mesmo padrão já usado em
`producao.agendar` (Fase 25): editar a padronização é uma ação sobre um
memorial específico, e ver o memorial (`memoriais.visualizar`) já é
suficiente para ver sua padronização.
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("memorial_padronizacao", __name__, url_prefix="/api/v1/memorial")

CAMPOS_PADRONIZACAO = (
    "produto", "peso_liquido", "contem", "denominacao_legal", "lista_ingredientes",
    "alergenicos", "advertencias", "conservacao", "informacoes_consumo",
    "largura_rotulo", "comprimento_rotulo", "altura_rotulo", "cor_capsula",
    "tamanho_capsulas", "tipo_capsulas", "tamanho_pote", "simbolos_logos",
    "alegacoes", "dados_distribuidor", "observacoes_tabela",
)


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _memorial_ou_404(conn, memorial_id):
    row = conn.execute("SELECT * FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    if row is None:
        raise ApiError("Memorial não encontrado.", status=404)
    return row


@bp.get("/memoriais/<int:memorial_id>/padronizacao")
@requires_permission("memoriais", "visualizar")
def obter_padronizacao(memorial_id):
    conn = get_db()
    _memorial_ou_404(conn, memorial_id)
    row = conn.execute(
        "SELECT * FROM memorial_padronizacoes WHERE memorial_id = ?", (memorial_id,)
    ).fetchone()
    return jsonify(dict(row) if row else None)


@bp.put("/memoriais/<int:memorial_id>/padronizacao")
@requires_permission("memoriais", "padronizar")
def salvar_padronizacao(memorial_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _memorial_ou_404(conn, memorial_id)
    dados_entrada = request.get_json(silent=True) or {}

    existente = conn.execute(
        "SELECT * FROM memorial_padronizacoes WHERE memorial_id = ?", (memorial_id,)
    ).fetchone()
    valores = {
        campo: (dados_entrada.get(campo, existente[campo] if existente else None))
        for campo in CAMPOS_PADRONIZACAO
    }

    if existente:
        conn.execute(
            f"""
            UPDATE memorial_padronizacoes
            SET {", ".join(f"{c} = ?" for c in CAMPOS_PADRONIZACAO)}, atualizado_em = ?, atualizado_por = ?
            WHERE memorial_id = ?
            """,
            (*[valores[c] for c in CAMPOS_PADRONIZACAO], _now_iso(), usuario_atual["id"], memorial_id),
        )
        acao = "padronizacao_memorial_editada"
    else:
        conn.execute(
            f"""
            INSERT INTO memorial_padronizacoes
                (memorial_id, {", ".join(CAMPOS_PADRONIZACAO)}, atualizado_por)
            VALUES (?, {", ".join(["?"] * len(CAMPOS_PADRONIZACAO))}, ?)
            """,
            (memorial_id, *[valores[c] for c in CAMPOS_PADRONIZACAO], usuario_atual["id"]),
        )
        acao = "padronizacao_memorial_criada"

    audit.registrar(
        conn, tabela="memorial_padronizacoes", registro_id=memorial_id, usuario_id=usuario_atual["id"],
        acao=acao, valor_anterior=dict(existente) if existente else None, valor_novo=valores,
        ip=client_ip(), dispositivo=client_device(),
    )
    row = conn.execute("SELECT * FROM memorial_padronizacoes WHERE memorial_id = ?", (memorial_id,)).fetchone()
    return jsonify(dict(row))
