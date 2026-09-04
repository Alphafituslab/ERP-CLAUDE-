"""
Fase 147 — Portal de assinatura do CONTRATO (sem login).

Diferente do portal de Terceirização (`portal_terceirizacao.py`, amarrado a
um projeto), este é o portal PRÓPRIO de cada contrato — funciona com ou sem
projeto do Monte sua linha vinculado, porque o contrato agora pertence ao
CLIENTE, não ao projeto (ver nota completa em `app/routes/contratos.py`).

Mesma receita de segurança do portal de Terceirização (Fase 136): token de
~256 bits (`contrato_links_portal.token`), resolvido ANTES de qualquer outra
coisa — nenhuma rota aceita `contrato_id` vindo de fora (URL, corpo, query).
"""
import base64
import datetime
import hashlib
import json
import re

from flask import Blueprint, Response, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, client_device, client_ip, get_db
from . import contratos as ctr
from . import terceirizacao as tc  # reaproveita _cliente_ou_404/_projeto_detalhado

bp = Blueprint("portal_contrato", __name__, url_prefix="/api/v1/portal/contrato")

STATUS_VISIVEL_PORTAL = ("aguardando_assinatura", "assinado")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _resolver_link_ou_404(token):
    """ÚNICO ponto que traduz token → contrato_id neste blueprint inteiro —
    mesmo desenho de `portal_terceirizacao._resolver_link_ou_404`, nunca
    aceita contrato_id de nenhuma outra fonte."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM contrato_links_portal WHERE token = ? AND revogado = 0", (token,)
    ).fetchone()
    if row is None:
        raise ApiError("Link inválido ou revogado.", status=404, codigo="link_invalido")
    link = dict(row)
    if link["expira_em"] < _now_iso():
        raise ApiError("Este link expirou — peça um novo link ao seu contato na Alphafitus.", status=410, codigo="link_expirado")
    conn.execute("UPDATE contrato_links_portal SET ultimo_acesso_em = ? WHERE id = ?", (_now_iso(), link["id"]))
    return conn, link


def _contrato_visivel_ou_404(conn, contrato_id):
    contrato = conn.execute("SELECT * FROM contratos WHERE id = ?", (contrato_id,)).fetchone()
    if contrato is None or contrato["status"] not in STATUS_VISIVEL_PORTAL:
        raise ApiError("Nenhum contrato disponível para assinatura neste momento.", status=404, codigo="contrato_indisponivel")
    return dict(contrato)


def _contrato_do_portal(conn, contrato):
    cliente = tc._cliente_ou_404(conn, contrato["cliente_id"])
    texto_resolvido = ctr._resolver_texto_contrato(contrato["texto_clausulas"], cliente, contrato)
    assinatura = conn.execute(
        "SELECT assinante_nome, assinante_email, assinado_em, hash_pdf_sha256 FROM contrato_versoes WHERE contrato_id = ? AND versao = ?",
        (contrato["id"], contrato["versao"]),
    ).fetchone()
    return {
        "numero": contrato["numero"],
        "status": contrato["status"],
        "versao": contrato["versao"],
        "cliente_razao_social": cliente["razao_social"],
        "texto_resolvido": texto_resolvido,
        "incluir_anexo_produtos": bool(contrato["incluir_anexo_produtos"]),
        "condicao_pagamento_texto": contrato["condicao_pagamento_texto"],
        "prazo_producao_texto": contrato["prazo_producao_texto"],
        "observacoes_gerais": contrato["observacoes_gerais"],
        "assinatura_eletronica": dict(assinatura) if assinatura else None,
    }


@bp.get("/<token>")
def obter_contrato_portal(token):
    conn, link = _resolver_link_ou_404(token)
    contrato = _contrato_visivel_ou_404(conn, link["contrato_id"])
    return jsonify(_contrato_do_portal(conn, contrato))


@bp.get("/<token>/pdf")
def baixar_contrato_pdf_portal(token):
    """PDF pra leitura antes de assinar — mesmo conteúdo que vira o
    documento oficial, só que ainda sem o hash/assinatura (esses só
    existem depois de `assinar_contrato_portal` gerar o PDF definitivo)."""
    conn, link = _resolver_link_ou_404(token)
    contrato = _contrato_visivel_ou_404(conn, link["contrato_id"])
    cliente = tc._cliente_ou_404(conn, contrato["cliente_id"])
    projeto = tc._projeto_detalhado(conn, contrato["projeto_id"]) if contrato["projeto_id"] else None
    pdf_bytes = ctr.gerar_pdf_contrato(contrato, cliente, projeto)
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{contrato['numero']}.pdf\""},
    )


@bp.post("/<token>/assinar")
def assinar_contrato_portal(token):
    """A assinatura eletrônica DE VERDADE — mesmo desenho de
    `portal_terceirizacao.assinar_portal`: captura nome/CPF/e-mail/IP/
    navegador, gera o PDF final NA HORA, calcula o hash SHA-256, grava
    tudo como um snapshot permanente em `contrato_versoes` e trava o
    contrato pra somente-leitura até uma nova versão ser aberta (só uso
    interno). Depois de assinado, salva uma cópia no cadastro do CLIENTE
    — "esse contrato já fica salvo no cadastro do cliente após
    assinatura", pedido explícito do usuário — usando `contrato.cliente_id`
    direto, sem precisar de nenhum projeto vinculado."""
    conn, link = _resolver_link_ou_404(token)
    contrato_row = conn.execute("SELECT * FROM contratos WHERE id = ?", (link["contrato_id"],)).fetchone()
    if contrato_row is None or contrato_row["status"] != "aguardando_assinatura":
        raise ApiError(
            "Este contrato não está aguardando assinatura no momento — "
            "ou ainda não foi liberado pela equipe, ou já foi assinado.",
            status=409, codigo="nao_aguardando_assinatura",
        )
    contrato = dict(contrato_row)

    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip()
    cpf = re.sub(r"\D", "", dados.get("cpf") or "")
    if not nome:
        raise ApiError("Informe seu nome para assinar.", status=400)
    if len(cpf) != 11:
        raise ApiError("Informe um CPF válido (11 dígitos) para assinar.", status=400)

    cliente = tc._cliente_ou_404(conn, contrato["cliente_id"])
    projeto = tc._projeto_detalhado(conn, contrato["projeto_id"]) if contrato["projeto_id"] else None
    pdf_bytes = ctr.gerar_pdf_contrato(contrato, cliente, projeto)
    hash_pdf = hashlib.sha256(pdf_bytes).hexdigest()
    agora = _now_iso()
    navegador = (request.headers.get("User-Agent") or "")[:500]
    versao_atual = contrato["versao"]

    snapshot = {"contrato": contrato, "cliente": cliente, "projeto": projeto}
    conn.execute(
        """
        INSERT INTO contrato_versoes
            (contrato_id, versao, snapshot_json, hash_pdf_sha256, pdf_dados, pdf_tamanho,
             assinante_nome, assinante_email, assinante_cpf, assinante_ip, assinante_navegador, assinado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contrato["id"], versao_atual, json.dumps(snapshot, ensure_ascii=False, default=str),
            hash_pdf, base64.b64encode(pdf_bytes).decode(), len(pdf_bytes),
            nome, email or None, cpf, client_ip(), navegador, agora,
        ),
    )
    conn.execute("UPDATE contratos SET status = 'assinado', atualizado_em = ? WHERE id = ?", (agora, contrato["id"]))

    # Mesmo padrão de "salva no cadastro do cliente pra auditoria" do
    # resto do sistema — nunca deixa a assinatura em si falhar por causa
    # disso.
    try:
        conn.execute(
            "INSERT INTO clientes_documentos (cliente_id, nome, nome_arquivo, tipo_mime, dados, tamanho, criado_por) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                contrato["cliente_id"], f"Contrato {contrato['numero']} — assinado eletronicamente (v{versao_atual})",
                f"Contrato_{contrato['numero']}_v{versao_atual}_assinado.pdf", "application/pdf",
                base64.b64encode(pdf_bytes).decode(), len(pdf_bytes), link["criado_por"],
            ),
        )
    except Exception:
        pass

    audit.registrar(
        conn, tabela="contratos", registro_id=contrato["id"], usuario_id=link["criado_por"],
        acao="assinado_eletronicamente", valor_novo={"versao": versao_atual, "hash_pdf_sha256": hash_pdf, "nome": nome},
        ip=client_ip(), dispositivo=client_device(),
    )
    mensagem = f"Contrato {contrato['numero']} (cliente {cliente['razao_social']}) foi assinado eletronicamente por {nome} — hash {hash_pdf[:12]}…"
    notificacoes_service.notificar_usuarios_com_permissao(conn, modulo="terceirizacao", acao="criar", tipo="contrato_assinado", mensagem=mensagem)

    contrato_atualizado = conn.execute("SELECT * FROM contratos WHERE id = ?", (contrato["id"],)).fetchone()
    return jsonify(_contrato_do_portal(conn, dict(contrato_atualizado)))
