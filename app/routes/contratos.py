"""
Fase 147 — Gerador de Contratos.

Pedido original do usuário (2026-09-03): gerar o "Contrato de
Industrialização de Produtos Nutracêuticos por Encomenda" puxando
automaticamente os dados da Alphafitus (cabeçalho) e do cliente/
produtos. Assinatura eletrônica reaproveita o MESMO mecanismo já
construído pra Terceirização (Fase 140): link do portal sem login,
captura de nome/CPF/e-mail/IP/navegador, hash SHA-256 do PDF final,
snapshot congelado por versão.

Revisão no mesmo dia, ainda antes de ir pra produção — o desenho
original amarrava contrato 1:1 a um projeto do Monte sua linha. O
usuário pediu pra mudar: "PRECISO QUE TENHA O CONTRATO INDIVIDUAL e se
desejar linkar ele com o Monte sua linha ter a opção depois... esse
contrato deve ficar linkado ao cadastro do CLIENTE, e pode ser feito
mais de um contrato". Por isso:
  - Todo contrato pertence a um CLIENTE (`cliente_id`, obrigatório) —
    um cliente pode ter vários contratos.
  - O vínculo com um projeto do Monte sua linha é OPCIONAL
    (`projeto_id`, pode ser nulo) — pode ser definido na criação ou
    depois (`vincular_projeto`/`desvincular_projeto`), e só existe pra
    puxar produtos/condição comercial automaticamente; nunca é
    obrigatório pro contrato funcionar.
  - Assinatura usa o link PRÓPRIO do contrato (`contrato_links_portal`,
    ver migrations/schema_fase147.sql) — não depende de existir um
    projeto/link de Terceirização por trás.
  - Depois de assinado, o PDF é salvo automaticamente no cadastro do
    cliente (`clientes_documentos`) — "esse contrato já fica salvo no
    cadastro do cliente após assinatura", pedido original do usuário.
"""
import base64
import datetime
import io
import json
import re
import secrets as secrets_lib

from flask import Blueprint, Response, g, jsonify, request

from .. import audit
from .. import backup_service
from ..context import ApiError, client_device, client_ip, get_db
from ..contrato_modelo import TEXTO_PADRAO_CONTRATO
from ..pdf_marca import desenhar_cabecalho_formal
from ..permissions import requires_permission
from . import terceirizacao as tc  # reaproveita _projeto_detalhado/_cliente_ou_404 — nunca duplica a query

bp = Blueprint("contratos", __name__, url_prefix="/api/v1/contratos")

MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}
STATUS_EDITAVEL = ("rascunho",)

# Mesmo esquema de URL pública do portal de Terceirização (Fase 136) —
# ver nota completa em terceirizacao.py sobre o túnel SSH reverso/Caddy;
# nunca montar a partir de `request.host`, que só funciona na máquina local.
URL_BASE_PORTAL_PUBLICO = "https://whatts.alphafitus.com.br:9445"
TTL_LINK_PORTAL_DIAS = 30


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _expira_em_daqui_a_dias(dias):
    return (datetime.datetime.utcnow() + datetime.timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _gerar_numero_contrato(conn):
    """Sequencial por ano (CT-2026-000001, CT-2026-000002...) — mesmo
    esquema de `terceirizacao._gerar_numero_projeto`; quem chama faz o
    retry em caso de corrida (UNIQUE em `numero`)."""
    ano = datetime.datetime.utcnow().year
    total = conn.execute("SELECT COUNT(*) AS c FROM contratos WHERE numero LIKE ?", (f"CT-{ano}-%",)).fetchone()["c"]
    return f"CT-{ano}-{total + 1:06d}"


def _contrato_ou_404(conn, contrato_id):
    row = conn.execute("SELECT * FROM contratos WHERE id = ?", (contrato_id,)).fetchone()
    if row is None:
        raise ApiError("Contrato não encontrado.", status=404)
    return dict(row)


def _contrato_para_json(conn, contrato):
    d = dict(contrato)
    d["itens_anexo_json"] = json.loads(d["itens_anexo_json"]) if d.get("itens_anexo_json") else []
    if d.get("projeto_id"):
        projeto = conn.execute("SELECT id, numero, status FROM terceirizacao_projetos WHERE id = ?", (d["projeto_id"],)).fetchone()
        d["projeto"] = dict(projeto) if projeto else None
    else:
        d["projeto"] = None
    return d


def _condicao_comercial_textos(briefing):
    """Deriva os três blocos de texto do Anexo I a partir do briefing do
    projeto vinculado (bloco "Condição comercial" da ficha cadastral,
    Fase 139) — só serve de PONTO DE PARTIDA; fica editável no contrato."""
    briefing = briefing or {}
    partes_pagamento = []
    if briefing.get("forma_pagamento"):
        partes_pagamento.append(briefing["forma_pagamento"])
    if briefing.get("valor_unitario"):
        partes_pagamento.append(f"Valor unitário: R$ {briefing['valor_unitario']:.2f}")
    if briefing.get("valor_total"):
        partes_pagamento.append(f"Valor total: R$ {briefing['valor_total']:.2f}")
    condicao_pagamento = " — ".join(partes_pagamento) or None
    prazo_producao = briefing.get("prazo_pagamento") or None
    partes_obs = []
    if briefing.get("notificacao_observacao"):
        partes_obs.append(briefing["notificacao_observacao"])
    if briefing.get("excedente_rotulos"):
        partes_obs.append(f"Excedente de rótulos: {briefing['excedente_rotulos']}")
    observacoes = "\n".join(partes_obs) or None
    return condicao_pagamento, prazo_producao, observacoes


@bp.get("")
@requires_permission("terceirizacao", "visualizar")
def listar_contratos():
    conn = get_db()
    filtros, params = [], []
    if request.args.get("cliente_id"):
        filtros.append("cliente_id = ?")
        params.append(request.args["cliente_id"])
    if request.args.get("projeto_id"):
        filtros.append("projeto_id = ?")
        params.append(request.args["projeto_id"])
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    rows = conn.execute(f"SELECT * FROM contratos {where} ORDER BY criado_em DESC", params).fetchall()
    return jsonify([_contrato_para_json(conn, dict(r)) for r in rows])


@bp.get("/<int:contrato_id>")
@requires_permission("terceirizacao", "visualizar")
def obter_contrato(contrato_id):
    conn = get_db()
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id)))


@bp.post("")
@requires_permission("terceirizacao", "criar")
def criar_contrato():
    """Cria um contrato novo pra um cliente — `projeto_id` é OPCIONAL:
    se informado, pré-preenche cláusulas/condição comercial/Anexo I a
    partir daquele projeto do Monte sua linha (precisa pertencer ao
    mesmo cliente); se omitido, o contrato nasce avulso, com o modelo
    padrão e campos em branco, editáveis na hora."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    dados = request.get_json(silent=True) or {}
    cliente_id = dados.get("cliente_id")
    if not cliente_id:
        raise ApiError("Informe cliente_id.", status=400)
    cliente = tc._cliente_ou_404(conn, cliente_id)

    projeto_id = dados.get("projeto_id")
    representante_nome = representante_cpf = None
    condicao_pagamento = prazo_producao = observacoes = None
    itens_ids = []
    if projeto_id:
        projeto = tc._projeto_detalhado(conn, projeto_id)
        if projeto["cliente_id"] != int(cliente_id):
            raise ApiError("Este projeto não pertence ao cliente informado.", status=400)
        briefing = projeto.get("briefing") or {}
        condicao_pagamento, prazo_producao, observacoes = _condicao_comercial_textos(briefing)
        itens_ids = [it["id"] for it in projeto["itens"]]
        representante_nome, representante_cpf = briefing.get("assinante_nome"), briefing.get("assinante_cpf")

    for _tentativa in range(3):
        numero = _gerar_numero_contrato(conn)
        try:
            cur = conn.execute(
                """
                INSERT INTO contratos
                    (numero, cliente_id, projeto_id, texto_clausulas, representante_nome, representante_cpf,
                     incluir_anexo_produtos, itens_anexo_json, condicao_pagamento_texto,
                     prazo_producao_texto, observacoes_gerais, criado_por)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    numero, cliente_id, projeto_id or None, TEXTO_PADRAO_CONTRATO,
                    representante_nome, representante_cpf,
                    json.dumps(itens_ids), condicao_pagamento, prazo_producao, observacoes,
                    usuario_atual["id"],
                ),
            )
            break
        except Exception as erro:
            if "UNIQUE" in str(erro) and _tentativa < 2:
                continue
            raise
    contrato_id = cur.lastrowid
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="contrato_criado", valor_novo={"numero": numero, "cliente_id": cliente_id, "projeto_id": projeto_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id))), 201


@bp.put("/<int:contrato_id>")
@requires_permission("terceirizacao", "criar")
def editar_contrato(contrato_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    if contrato["status"] not in STATUS_EDITAVEL:
        raise ApiError(
            "Este contrato não está mais em rascunho — só é possível editar antes de enviar para assinatura.",
            status=409,
        )
    dados = request.get_json(silent=True) or {}
    campos = {
        "texto_clausulas": dados.get("texto_clausulas", contrato["texto_clausulas"]),
        "representante_nome": dados.get("representante_nome", contrato["representante_nome"]),
        "representante_cpf": dados.get("representante_cpf", contrato["representante_cpf"]),
        "incluir_anexo_produtos": int(bool(dados.get("incluir_anexo_produtos", contrato["incluir_anexo_produtos"]))),
        "condicao_pagamento_texto": dados.get("condicao_pagamento_texto", contrato["condicao_pagamento_texto"]),
        "prazo_producao_texto": dados.get("prazo_producao_texto", contrato["prazo_producao_texto"]),
        "observacoes_gerais": dados.get("observacoes_gerais", contrato["observacoes_gerais"]),
    }
    if not (campos["texto_clausulas"] or "").strip():
        raise ApiError("O texto do contrato não pode ficar vazio.", status=400)
    if "itens_anexo_json" in dados:
        if not isinstance(dados["itens_anexo_json"], list):
            raise ApiError("itens_anexo_json deve ser uma lista de ids de item do projeto.", status=400)
        campos["itens_anexo_json"] = json.dumps(dados["itens_anexo_json"])
    else:
        campos["itens_anexo_json"] = contrato["itens_anexo_json"]

    conn.execute(
        """
        UPDATE contratos SET texto_clausulas = ?, representante_nome = ?, representante_cpf = ?,
               incluir_anexo_produtos = ?, itens_anexo_json = ?, condicao_pagamento_texto = ?,
               prazo_producao_texto = ?, observacoes_gerais = ?, atualizado_em = ?
        WHERE id = ?
        """,
        (
            campos["texto_clausulas"], campos["representante_nome"], campos["representante_cpf"],
            campos["incluir_anexo_produtos"], campos["itens_anexo_json"], campos["condicao_pagamento_texto"],
            campos["prazo_producao_texto"], campos["observacoes_gerais"], _now_iso(), contrato_id,
        ),
    )
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="contrato_editado", valor_anterior=contrato, valor_novo=campos,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id)))


@bp.post("/<int:contrato_id>/vincular-projeto")
@requires_permission("terceirizacao", "criar")
def vincular_projeto(contrato_id):
    """Liga (ou troca) o projeto do Monte sua linha deste contrato —
    "se desejar linkar ele com o monte sua linha ter a opção depois"
    (pedido do usuário). Só preenche automaticamente os campos de
    condição comercial/Anexo I que ainda estiverem VAZIOS — nunca
    sobrescreve o que já foi editado manualmente no contrato."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    if contrato["status"] not in STATUS_EDITAVEL:
        raise ApiError("Só é possível vincular um projeto enquanto o contrato está em rascunho.", status=409)
    dados = request.get_json(silent=True) or {}
    projeto_id = dados.get("projeto_id")
    if not projeto_id:
        raise ApiError("Informe projeto_id.", status=400)
    projeto = tc._projeto_detalhado(conn, projeto_id)
    if projeto["cliente_id"] != contrato["cliente_id"]:
        raise ApiError("Este projeto não pertence ao mesmo cliente deste contrato.", status=400)

    briefing = projeto.get("briefing") or {}
    condicao_pagamento, prazo_producao, observacoes = _condicao_comercial_textos(briefing)
    atualizacoes = {"projeto_id": projeto_id}
    if not contrato["representante_nome"] and briefing.get("assinante_nome"):
        atualizacoes["representante_nome"] = briefing["assinante_nome"]
    if not contrato["representante_cpf"] and briefing.get("assinante_cpf"):
        atualizacoes["representante_cpf"] = briefing["assinante_cpf"]
    if not contrato["condicao_pagamento_texto"] and condicao_pagamento:
        atualizacoes["condicao_pagamento_texto"] = condicao_pagamento
    if not contrato["prazo_producao_texto"] and prazo_producao:
        atualizacoes["prazo_producao_texto"] = prazo_producao
    if not contrato["observacoes_gerais"] and observacoes:
        atualizacoes["observacoes_gerais"] = observacoes
    if not contrato["itens_anexo_json"] or contrato["itens_anexo_json"] == "[]":
        atualizacoes["itens_anexo_json"] = json.dumps([it["id"] for it in projeto["itens"]])

    set_sql = ", ".join(f"{c} = ?" for c in atualizacoes)
    conn.execute(f"UPDATE contratos SET {set_sql}, atualizado_em = ? WHERE id = ?",
                 [*atualizacoes.values(), _now_iso(), contrato_id])
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="projeto_vinculado", valor_novo={"projeto_id": projeto_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id)))


@bp.post("/<int:contrato_id>/desvincular-projeto")
@requires_permission("terceirizacao", "criar")
def desvincular_projeto(contrato_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    if contrato["status"] not in STATUS_EDITAVEL:
        raise ApiError("Só é possível desvincular um projeto enquanto o contrato está em rascunho.", status=409)
    conn.execute("UPDATE contratos SET projeto_id = NULL, atualizado_em = ? WHERE id = ?", (_now_iso(), contrato_id))
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="projeto_desvinculado", ip=client_ip(), dispositivo=client_device())
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id)))


@bp.post("/<int:contrato_id>/enviar-para-assinatura")
@requires_permission("terceirizacao", "criar")
def enviar_para_assinatura(contrato_id):
    """Trava a edição interna e libera o contrato pro cliente assinar
    pelo link do portal (gerado separadamente em .../link)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    if contrato["status"] != "rascunho":
        raise ApiError("Este contrato já foi enviado para assinatura ou já está assinado.", status=409)
    conn.execute(
        "UPDATE contratos SET status = 'aguardando_assinatura', atualizado_em = ? WHERE id = ?",
        (_now_iso(), contrato_id),
    )
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="enviado_para_assinatura", valor_novo={"numero": contrato["numero"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id)))


@bp.post("/<int:contrato_id>/cancelar")
@requires_permission("terceirizacao", "criar")
def cancelar_contrato(contrato_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    if contrato["status"] == "assinado":
        raise ApiError("Um contrato já assinado não pode ser cancelado — abra uma nova versão em vez disso.", status=409)
    conn.execute("UPDATE contratos SET status = 'cancelado', atualizado_em = ? WHERE id = ?", (_now_iso(), contrato_id))
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="contrato_cancelado", valor_novo={"numero": contrato["numero"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id)))


@bp.post("/<int:contrato_id>/nova-versao")
@requires_permission("terceirizacao", "criar")
def nova_versao_contrato(contrato_id):
    """Depois de assinado, o contrato vira somente-leitura — pra alterar
    qualquer coisa é preciso abrir uma V2 explicitamente (mesmo padrão
    de `terceirizacao.iniciar_nova_versao`). A versão assinada anterior
    (texto + PDF + hash, em `contrato_versoes`) nunca é tocada."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    if contrato["status"] != "assinado":
        raise ApiError("Só é possível abrir uma nova versão de um contrato já assinado.", status=400)
    nova_versao = contrato["versao"] + 1
    conn.execute(
        "UPDATE contratos SET versao = ?, status = 'rascunho', atualizado_em = ? WHERE id = ?",
        (nova_versao, _now_iso(), contrato_id),
    )
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="nova_versao_iniciada", valor_novo={"versao": nova_versao},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_contrato_para_json(conn, _contrato_ou_404(conn, contrato_id)))


@bp.get("/<int:contrato_id>/versoes")
@requires_permission("terceirizacao", "visualizar")
def listar_versoes_contrato(contrato_id):
    conn = get_db()
    _contrato_ou_404(conn, contrato_id)
    rows = conn.execute(
        "SELECT id, versao, hash_pdf_sha256, assinante_nome, assinante_email, assinante_cpf, assinado_em "
        "FROM contrato_versoes WHERE contrato_id = ? ORDER BY versao DESC",
        (contrato_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:contrato_id>/versoes/<int:versao>/documento.pdf")
@requires_permission("terceirizacao", "visualizar")
def baixar_versao_assinada(contrato_id, versao):
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    linha = conn.execute(
        "SELECT * FROM contrato_versoes WHERE contrato_id = ? AND versao = ?", (contrato_id, versao)
    ).fetchone()
    if linha is None:
        raise ApiError("Versão assinada não encontrada.", status=404)
    pdf_bytes = base64.b64decode(linha["pdf_dados"])
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{contrato['numero']}_v{versao}_assinado.pdf\""},
    )


@bp.get("/<int:contrato_id>/pdf")
@requires_permission("terceirizacao", "visualizar")
def pre_visualizar_pdf(contrato_id):
    """PDF de CONFERÊNCIA (rascunho ou aguardando assinatura) — nunca é o
    documento assinado; esse só existe depois de `assinar_contrato_portal`
    gerar e congelar o PDF exato em `contrato_versoes`."""
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    cliente = tc._cliente_ou_404(conn, contrato["cliente_id"])
    projeto = tc._projeto_detalhado(conn, contrato["projeto_id"]) if contrato["projeto_id"] else None
    pdf_bytes = gerar_pdf_contrato(contrato, cliente, projeto)
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{contrato['numero']}_rascunho.pdf\""},
    )


# =============================================================================
# Link do portal (próprio do contrato — ver nota no topo do arquivo sobre
# por que não reaproveita mais `terceirizacao_links_portal`).
# =============================================================================

def _link_ativo_do_contrato(conn, contrato_id):
    row = conn.execute(
        "SELECT * FROM contrato_links_portal WHERE contrato_id = ? AND revogado = 0 ORDER BY id DESC LIMIT 1",
        (contrato_id,),
    ).fetchone()
    return dict(row) if row else None


@bp.get("/<int:contrato_id>/link")
@requires_permission("terceirizacao", "visualizar")
def obter_link_contrato(contrato_id):
    conn = get_db()
    _contrato_ou_404(conn, contrato_id)
    link = _link_ativo_do_contrato(conn, contrato_id)
    if link is None:
        return jsonify({"ativo": False})
    return jsonify({
        "ativo": True, "expirado": link["expira_em"] < _now_iso(),
        "expira_em": link["expira_em"], "ultimo_acesso_em": link["ultimo_acesso_em"],
        "enviado_via_whatsapp": bool(link["enviado_via_whatsapp"]),
        "url": f"{URL_BASE_PORTAL_PUBLICO}/portal/contrato/{link['token']}",
    })


@bp.post("/<int:contrato_id>/link")
@requires_permission("terceirizacao", "criar")
def gerar_link_contrato(contrato_id):
    """Gera (ou renova — revoga o anterior primeiro) o link de assinatura
    deste contrato. `enviar_whatsapp: true` manda a mensagem na hora,
    usando o telefone já cadastrado do cliente (`clientes.telefone`) —
    mesma configuração de Evolution API já usada no resto do sistema."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    contrato = _contrato_ou_404(conn, contrato_id)
    if contrato["status"] == "cancelado":
        raise ApiError("Não é possível gerar link para um contrato cancelado.", status=400)
    cliente = tc._cliente_ou_404(conn, contrato["cliente_id"])

    dados = request.get_json(silent=True) or {}
    enviar_whatsapp = bool(dados.get("enviar_whatsapp"))

    conn.execute("UPDATE contrato_links_portal SET revogado = 1 WHERE contrato_id = ? AND revogado = 0", (contrato_id,))
    token = secrets_lib.token_urlsafe(32)
    expira_em = _expira_em_daqui_a_dias(TTL_LINK_PORTAL_DIAS)
    cur = conn.execute(
        "INSERT INTO contrato_links_portal (contrato_id, token, criado_por, expira_em) VALUES (?, ?, ?, ?)",
        (contrato_id, token, usuario_atual["id"], expira_em),
    )
    url = f"{URL_BASE_PORTAL_PUBLICO}/portal/contrato/{token}"

    enviado_com_sucesso = False
    erro_envio = None
    if enviar_whatsapp:
        telefone = (cliente.get("telefone") or "").strip()
        if not telefone:
            erro_envio = "Este cliente não tem telefone cadastrado (Comercial > editar cliente)."
        else:
            try:
                config = backup_service.obter_configuracao(conn)
                texto = (
                    f"Olá! Segue o link para leitura e assinatura eletrônica do contrato {contrato['numero']} "
                    f"com a Alphafitus.\n\nAcesse por aqui: {url}"
                )
                backup_service.enviar_texto_whatsapp(config, telefone, texto)
                enviado_com_sucesso = True
                conn.execute("UPDATE contrato_links_portal SET enviado_via_whatsapp = 1 WHERE id = ?", (cur.lastrowid,))
            except Exception as erro:
                erro_envio = str(erro)

    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="link_portal_gerado", valor_novo={"enviado_via_whatsapp": enviado_com_sucesso},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({
        "url": url, "expira_em": expira_em,
        "enviado_via_whatsapp": enviado_com_sucesso, "erro_envio_whatsapp": erro_envio,
    }), 201


@bp.post("/<int:contrato_id>/link/revogar")
@requires_permission("terceirizacao", "criar")
def revogar_link_contrato(contrato_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _contrato_ou_404(conn, contrato_id)
    resultado = conn.execute("UPDATE contrato_links_portal SET revogado = 1 WHERE contrato_id = ? AND revogado = 0", (contrato_id,))
    if resultado.rowcount == 0:
        raise ApiError("Não há nenhum link ativo para revogar.", status=400)
    audit.registrar(conn, tabela="contratos", registro_id=contrato_id, usuario_id=usuario_atual["id"],
                     acao="link_portal_revogado", ip=client_ip(), dispositivo=client_device())
    return jsonify({"ativo": False})


# =============================================================================
# Montagem do texto e do PDF — reaproveitado pelo portal do contrato na
# hora de assinar (mesmo PDF exato que vira o hash SHA-256, ver
# `portal_contrato.assinar_contrato_portal`).
# =============================================================================

def _bloco_contratante(cliente, contrato):
    """Monta o parágrafo "CONTRATANTE: ..." com os dados reais do
    cliente/representante — nunca digitado à mão (pedido do usuário: "já
    puxe os dados... do cliente do próprio erp")."""
    documento = (
        f"inscrita no CNPJ sob o n° {cliente['cnpj']}" if cliente.get("cnpj")
        else (f"inscrito(a) no CPF sob n° {cliente['cpf']}" if cliente.get("cpf") else "sem documento cadastrado")
    )
    endereco = cliente.get("endereco") or "endereço não informado no cadastro"
    representante = contrato.get("representante_nome") or "(representante não informado)"
    cpf_representante = contrato.get("representante_cpf")
    trecho_representante = f", inscrito(a) no CPF sob n° {cpf_representante}" if cpf_representante else ""
    return (
        f"CONTRATANTE: {cliente['razao_social']}, {documento}, estabelecida à {endereco}, "
        f"neste ato devidamente representado(a) pelo(a) Sr(a). {representante}{trecho_representante}."
    )


def _resolver_texto_contrato(texto, cliente, contrato):
    agora = datetime.datetime.utcnow()
    data_extenso = f"{agora.day} de {MESES_PT[agora.month]} de {agora.year}"
    return (
        texto
        .replace("{{CONTRATANTE_BLOCO}}", _bloco_contratante(cliente, contrato))
        .replace("{{DATA_CONTRATO}}", data_extenso)
        .replace("{{REPRESENTANTE_CONTRATANTE}}", contrato.get("representante_nome") or "")
    )


def gerar_pdf_contrato(contrato, cliente, projeto=None):
    """Gera o PDF do contrato (rascunho OU final, mesma função — o que
    muda é só o texto/estado no momento da chamada). `projeto` é OPCIONAL
    (dict de `tc._projeto_detalhado`, ou None pra contrato avulso) — só é
    usado pra montar a tabela de produtos do Anexo I quando existir."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    cor_titulo = colors.HexColor("#1a3c2e")
    cor_dourado = colors.HexColor("#a8863f")
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("TituloContrato", parent=estilos["Title"], textColor=cor_titulo, alignment=TA_CENTER, fontSize=15, spaceAfter=14)
    estilo_secao = ParagraphStyle("SecaoContrato", parent=estilos["Heading3"], textColor=cor_titulo, spaceBefore=12, spaceAfter=4, fontSize=11)
    estilo_normal = ParagraphStyle("NormalContrato", parent=estilos["Normal"], alignment=TA_JUSTIFY, spaceAfter=8, fontSize=9.5, leading=13)
    estilo_suave = ParagraphStyle("SuaveContrato", parent=estilos["Normal"], textColor=colors.HexColor("#666666"), fontSize=8.5)

    texto_resolvido = _resolver_texto_contrato(contrato["texto_clausulas"], cliente, contrato)
    elementos = [Spacer(1, 0.6 * cm)]
    for bloco in texto_resolvido.split("\n\n"):
        bloco = bloco.strip()
        if not bloco:
            continue
        if bloco.startswith("# "):
            elementos.append(Paragraph(escape(bloco[2:].strip()), estilo_titulo))
            elementos.append(HRFlowable(width="100%", thickness=1, color=cor_dourado, spaceAfter=10))
        elif bloco.startswith("## "):
            elementos.append(Paragraph(escape(bloco[3:].strip()), estilo_secao))
        else:
            # Dentro de um mesmo bloco, uma quebra de linha simples vira
            # <br/> (parágrafos de verdade continuam separados por linha
            # em branco, que é o que já separa os `bloco` aqui).
            texto_html = escape(bloco).replace("\n", "<br/>")
            elementos.append(Paragraph(texto_html, estilo_normal))

    tem_condicoes_texto = any([contrato.get("condicao_pagamento_texto"), contrato.get("prazo_producao_texto"), contrato.get("observacoes_gerais")])
    if contrato["incluir_anexo_produtos"] and (projeto or tem_condicoes_texto):
        ids_incluidos = set(json.loads(contrato["itens_anexo_json"])) if contrato.get("itens_anexo_json") else None
        itens_anexo = [it for it in projeto["itens"] if ids_incluidos is None or it["id"] in ids_incluidos] if projeto else []
        elementos.append(PageBreak())
        elementos.append(Paragraph("ANEXO I — PRODUTOS E CONDIÇÕES COMERCIAIS", estilo_titulo))
        elementos.append(HRFlowable(width="100%", thickness=1, color=cor_dourado, spaceAfter=12))
        if itens_anexo:
            estilo_cabecalho_tabela = ParagraphStyle("CabecalhoAnexo", parent=estilo_normal, textColor=colors.white, fontName="Helvetica-Bold", fontSize=9, spaceAfter=0)
            estilo_celula_tabela = ParagraphStyle("CelulaAnexo", parent=estilo_normal, alignment=TA_JUSTIFY, fontSize=8.5, leading=11, spaceAfter=0)
            linhas = [[Paragraph(t, estilo_cabecalho_tabela) for t in ("Produto", "Embalagem", "Quantidade")]]
            for it in itens_anexo:
                nome_produto = escape((it["item"]["nome_memorial"] or it["item"]["descricao"]) if it.get("item") else "—")
                # Uma linha por peça, com um rótulo curto ("Pote:"/"Tampa:"/
                # "Cápsula:") em vez de concatenar o nome cadastrado direto
                # atrás da palavra — evita repetição visual quando quem
                # cadastra a embalagem já inclui o tipo no próprio nome.
                partes_embalagem = []
                if it.get("pote"):
                    partes_embalagem.append(f"<b>Pote:</b> {escape(it['pote']['nome'])} ({escape(it['pote'].get('cor') or '—')})")
                if it.get("tampa"):
                    partes_embalagem.append(f"<b>Tampa:</b> {escape(it['tampa']['nome'])} ({escape(it['tampa'].get('cor') or '—')})")
                if it.get("capsula"):
                    partes_embalagem.append(f"<b>Cápsula:</b> {escape(it['capsula']['nome'])}")
                embalagem = "<br/>".join(partes_embalagem) or "—"
                if it.get("quantidade_por_pote"):
                    rotulo_unidade = "cápsulas" if it.get("unidade_quantidade") == "capsulas" else "g"
                    quantidade = f"{it['quantidade_por_pote']} {rotulo_unidade}"
                else:
                    quantidade = "—"
                linhas.append([
                    Paragraph(nome_produto, estilo_celula_tabela),
                    Paragraph(embalagem, estilo_celula_tabela),
                    Paragraph(escape(quantidade), estilo_celula_tabela),
                ])
            tabela = Table(linhas, colWidths=[5 * cm, 6.5 * cm, 3 * cm], repeatRows=1)
            tabela.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), cor_titulo),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f5ef")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            elementos.append(tabela)
        else:
            elementos.append(Paragraph("<i>Nenhum produto vinculado a este contrato.</i>", estilo_suave))

        elementos.append(Spacer(1, 0.5 * cm))
        for rotulo, valor in [
            ("Condição de Pagamento", contrato.get("condicao_pagamento_texto")),
            ("Prazo de Produção", contrato.get("prazo_producao_texto")),
            ("Observações Gerais", contrato.get("observacoes_gerais")),
        ]:
            if valor:
                elementos.append(Paragraph(f"<b>{escape(rotulo)}:</b> {escape(valor).replace(chr(10), '<br/>')}", estilo_normal))

    buffer = io.BytesIO()
    # topMargin folgado de propósito — `desenhar_cabecalho_formal` ocupa
    # ~2.3cm de altura (logo + 4 linhas de texto + linha dourada) a
    # partir do topo físico da página; 3.4cm dá respiro real antes do
    # título do contrato começar (ver nota em pdf_marca.py).
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=3.4 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm)
    doc.build(elementos, onFirstPage=desenhar_cabecalho_formal, onLaterPages=desenhar_cabecalho_formal)
    return buffer.getvalue()
