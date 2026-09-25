"""
Fase 199 — Portal de aceite de convite da Agenda (sem login).

Mesma receita de segurança dos outros portais (Contrato/Orçamento): token
opaco (`agenda_participantes.token_convite`) resolvido ANTES de qualquer
outra coisa — nenhuma rota aceita participante_id vindo de fora. Diferente
dos outros portais, aqui não existe revogação/expiração — o convidado é um
usuário interno conhecido (recebeu o link direto no WhatsApp/e-mail dele) e
pode mudar de ideia depois, então aceitar/recusar por aqui funciona a
qualquer momento enquanto o compromisso não foi cancelado.
"""
from flask import Blueprint, jsonify, request

from .. import agenda_service, audit
from ..context import ApiError, client_device, client_ip, get_db

bp = Blueprint("portal_agenda_convite", __name__, url_prefix="/api/v1/portal/agenda-convite")


def _resolver_convite_ou_404(token):
    conn = get_db()
    participante = agenda_service.resolver_convite_por_token(conn, token)
    if participante is None:
        raise ApiError("Convite inválido.", status=404, codigo="convite_invalido")
    evento = conn.execute("SELECT * FROM agenda_eventos WHERE id = ?", (participante["evento_id"],)).fetchone()
    if evento is None or evento["status"] == "cancelado":
        raise ApiError("Este compromisso não está mais disponível.", status=404, codigo="compromisso_indisponivel")
    return conn, participante, dict(evento)


@bp.get("/<token>")
def obter_convite_portal(token):
    conn, participante, evento = _resolver_convite_ou_404(token)
    convidado_por = conn.execute("SELECT nome FROM usuarios WHERE id = ?", (participante["convidado_por"],)).fetchone()
    return jsonify({
        "participante_id": participante["id"],
        "status": participante["status"],
        "motivo_recusa": participante["motivo_recusa"],
        "evento": {
            "titulo": evento["titulo"],
            "descricao": evento["descricao"],
            "data_inicio": evento["data_inicio"],
            "data_fim": evento["data_fim"],
            "local_texto": evento["local_texto"],
            "cor": evento["cor"],
        },
        "convidado_por_nome": convidado_por["nome"] if convidado_por else None,
    })


@bp.post("/<token>/aceitar")
def aceitar_convite_portal(token):
    conn, participante, evento = _resolver_convite_ou_404(token)
    resultado = agenda_service._responder_convite_nucleo(conn, participante["id"], aceitar=True)
    audit.registrar(conn, tabela="agenda_participantes", registro_id=participante["id"], usuario_id=participante["convidado_por"],
                     acao="convite_aceito_pelo_portal", valor_novo=resultado, ip=client_ip(), dispositivo=client_device())
    return jsonify(resultado)


@bp.post("/<token>/recusar")
def recusar_convite_portal(token):
    conn, participante, evento = _resolver_convite_ou_404(token)
    dados = request.get_json(silent=True) or {}
    resultado = agenda_service._responder_convite_nucleo(conn, participante["id"], aceitar=False, motivo=dados.get("motivo"))
    audit.registrar(conn, tabela="agenda_participantes", registro_id=participante["id"], usuario_id=participante["convidado_por"],
                     acao="convite_recusado_pelo_portal", valor_novo=resultado, ip=client_ip(), dispositivo=client_device())
    return jsonify(resultado)
