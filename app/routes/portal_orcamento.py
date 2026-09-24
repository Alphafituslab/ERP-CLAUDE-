"""
Fase 197 — Portal de aprovação do ORÇAMENTO (sem login).

Mesma receita de segurança dos outros portais (Contrato/Terceirização):
token de ~256 bits (`orcamento_links_portal.token`) resolvido ANTES de
qualquer outra coisa — nenhuma rota aceita orcamento_id vindo de fora.

Ao APROVAR, gera de verdade um Pedido de Venda (mesma tabela que o
Comercial usa) com os itens/preços negociados no orçamento — sem exigir
CPF/assinatura eletrônica (diferente do Contrato — orçamento é uma
decisão comercial, não um documento jurídico assinado). Cliente
financeiramente reprovado ainda pode ser convertido em pedido aqui (fica
'rascunho' no Comercial); a trava de confirmar a VENDA de verdade
continua sendo a mesma de sempre (Fase 102), no Comercial.
"""
import datetime

from flask import Blueprint, Response, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, client_device, client_ip, get_db
from . import orcamentos as orc

bp = Blueprint("portal_orcamento", __name__, url_prefix="/api/v1/portal/orcamento")

STATUS_VISIVEL_PORTAL = ("enviado", "aprovado", "recusado")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _resolver_link_ou_404(token):
    """ÚNICO ponto que traduz token → orcamento_id neste blueprint inteiro."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM orcamento_links_portal WHERE token = ? AND revogado = 0", (token,)
    ).fetchone()
    if row is None:
        raise ApiError("Link inválido ou revogado.", status=404, codigo="link_invalido")
    link = dict(row)
    if link["expira_em"] < _now_iso():
        raise ApiError("Este link expirou — peça um novo ao seu contato na Alphafitus.", status=410, codigo="link_expirado")
    conn.execute("UPDATE orcamento_links_portal SET ultimo_acesso_em = ? WHERE id = ?", (_now_iso(), link["id"]))
    return conn, link


def _orcamento_visivel_ou_404(conn, orcamento_id):
    orcamento = conn.execute("SELECT * FROM orcamentos WHERE id = ?", (orcamento_id,)).fetchone()
    if orcamento is None or orcamento["status"] not in STATUS_VISIVEL_PORTAL:
        raise ApiError("Nenhum orçamento disponível neste momento.", status=404, codigo="orcamento_indisponivel")
    return dict(orcamento)


@bp.get("/<token>")
def obter_orcamento_portal(token):
    conn, link = _resolver_link_ou_404(token)
    _orcamento_visivel_ou_404(conn, link["orcamento_id"])
    return jsonify(orc.orcamento_detalhado(conn, link["orcamento_id"]))


@bp.get("/<token>/pdf")
def baixar_orcamento_pdf_portal(token):
    conn, link = _resolver_link_ou_404(token)
    _orcamento_visivel_ou_404(conn, link["orcamento_id"])
    orcamento = orc.orcamento_detalhado(conn, link["orcamento_id"])
    pdf_bytes = orc.gerar_pdf_orcamento(orcamento)
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{orcamento["numero"]}.pdf"'},
    )


@bp.post("/<token>/aprovar")
def aprovar_orcamento_portal(token):
    conn, link = _resolver_link_ou_404(token)
    orcamento_row = conn.execute("SELECT * FROM orcamentos WHERE id = ?", (link["orcamento_id"],)).fetchone()
    if orcamento_row is None or orcamento_row["status"] != "enviado":
        raise ApiError(
            "Este orçamento não está mais disponível para aprovação — já foi decidido antes, ou ainda não foi liberado pela equipe.",
            status=409, codigo="nao_aguardando_aprovacao",
        )
    orcamento = orc.orcamento_detalhado(conn, orcamento_row["id"])

    dados = request.get_json(silent=True) or {}
    nome_aprovador = (dados.get("nome") or "").strip()

    # Gera o Pedido de Venda de verdade (mesmo INSERT de
    # app/routes/comercial.py:criar_pedido — sem passar pela permissão
    # normal, porque quem está "chamando" aqui é o cliente pelo link
    # público, não um usuário logado do ERP).
    ano = datetime.datetime.utcnow().year
    total = conn.execute("SELECT COUNT(*) AS c FROM pedidos_venda WHERE numero LIKE ?", (f"PV-{ano}-%",)).fetchone()["c"]
    import secrets as secrets_lib
    numero_pedido = f"PV-{ano}-{secrets_lib.token_hex(4).upper()}"
    cur = conn.execute(
        "INSERT INTO pedidos_venda (numero, cliente_id, empresa_id, condicao_pagamento_id, canal_origem, criado_por) "
        "VALUES (?, ?, ?, ?, 'comercial', ?)",
        (numero_pedido, orcamento["cliente_id"], orcamento["empresa_id"], orcamento["condicao_pagamento_id"], link["criado_por"]),
    )
    pedido_id = cur.lastrowid
    for it in orcamento["itens"]:
        conn.execute(
            "INSERT INTO pedido_venda_itens (pedido_id, item_id, quantidade, unidade, preco_unitario) VALUES (?, ?, ?, ?, ?)",
            (pedido_id, it["item_id"], it["quantidade"], it["unidade"], it["preco_unitario"]),
        )

    agora = _now_iso()
    conn.execute(
        "UPDATE orcamentos SET status = 'aprovado', aprovado_em = ?, pedido_venda_id = ?, atualizado_em = ? WHERE id = ?",
        (agora, pedido_id, agora, orcamento["id"]),
    )

    audit.registrar(
        conn, tabela="orcamentos", registro_id=orcamento["id"], usuario_id=link["criado_por"],
        acao="orcamento_aprovado_pelo_cliente", valor_novo={"nome_aprovador": nome_aprovador, "pedido_venda_id": pedido_id},
        ip=client_ip(), dispositivo=client_device(),
    )
    mensagem = f"Orçamento {orcamento['numero']} foi APROVADO pelo cliente — Pedido de Venda {numero_pedido} criado como rascunho."
    notificacoes_service.notificar_usuarios_com_permissao(conn, modulo="orcamentos", acao="criar", tipo="orcamento_aprovado", mensagem=mensagem)

    return jsonify(orc.orcamento_detalhado(conn, orcamento["id"]))


@bp.post("/<token>/recusar")
def recusar_orcamento_portal(token):
    conn, link = _resolver_link_ou_404(token)
    orcamento_row = conn.execute("SELECT * FROM orcamentos WHERE id = ?", (link["orcamento_id"],)).fetchone()
    if orcamento_row is None or orcamento_row["status"] != "enviado":
        raise ApiError("Este orçamento não está mais disponível para decisão.", status=409, codigo="nao_aguardando_aprovacao")

    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip() or None
    agora = _now_iso()
    conn.execute(
        "UPDATE orcamentos SET status = 'recusado', recusado_em = ?, motivo_recusa = ?, atualizado_em = ? WHERE id = ?",
        (agora, motivo, agora, orcamento_row["id"]),
    )
    audit.registrar(conn, tabela="orcamentos", registro_id=orcamento_row["id"], usuario_id=link["criado_por"],
                     acao="orcamento_recusado_pelo_cliente", valor_novo={"motivo": motivo},
                     ip=client_ip(), dispositivo=client_device())
    mensagem = f"Orçamento {orcamento_row['numero']} foi RECUSADO pelo cliente" + (f" — motivo: {motivo}" if motivo else ".")
    notificacoes_service.notificar_usuarios_com_permissao(conn, modulo="orcamentos", acao="criar", tipo="orcamento_recusado", mensagem=mensagem)
    return jsonify(orc.orcamento_detalhado(conn, orcamento_row["id"]))
