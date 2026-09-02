"""
Fase 136 — Terceirização Premium (Fase C: portal do cliente, sem login).

Primeiro (e único, até aqui) ponto do sistema com acesso EXTERNO sem
autenticação normal — todo o resto do Alphafitus OS exige login (JWT) ou é
administrativo (OAuth). Por isso as regras aqui são mais rígidas que o
resto do sistema:

  1. NENHUMA rota aceita `projeto_id` vindo de fora (URL, corpo, query).
     Tudo é resolvido a partir do TOKEN — `_resolver_link_ou_404` é o único
     lugar que lê a tabela `terceirizacao_links_portal` e devolve o
     `projeto_id` verdadeiro. Isso elimina IDOR por definição: não existe
     nenhum parâmetro pra manipular.
  2. Token = `secrets.token_urlsafe(32)` (~256 bits) — inviável de
     adivinhar por força bruta; não precisa de rate limit adicional pra
     isso (mesma decisão já usada pro refresh token do login normal,
     `app/security.py::gerar_refresh_token`, mesmo tamanho).
  3. Nunca expõe nada de OUTRO cliente/projeto — `_projeto_do_portal`
     devolve só os campos que o cliente tem motivo de ver (nunca a lista
     de usuários internos, nunca dados de outro projeto do mesmo cliente
     sem ser este).
  4. Arquivos: só `visibilidade = 'compartilhado'` — um arquivo marcado
     `interno` pela equipe NUNCA aparece aqui, em nenhuma rota.
  5. Mutação só é aceita enquanto o projeto está "aberto" pro cliente
     (`aguardando_cliente`/`em_preenchimento`) — depois de concluído
     (`aguardando_revisao` em diante), o portal vira somente-leitura.
"""
import base64
import binascii
import datetime
import json
import re
import secrets

from flask import Blueprint, Response, jsonify, request

from .. import audit
from .. import notificacoes_service
from ..context import ApiError, client_device, client_ip, get_db
from ..imagens import validar_imagem_base64
from . import terceirizacao as tc  # reaproveita _gerar_mockup_png, _gerar_pdf_dossie, _nutricao_para_item etc.

bp = Blueprint("portal_terceirizacao", __name__, url_prefix="/api/v1/portal/terceirizacao")

TTL_LINK_DIAS = 30
STATUS_ABERTOS_PARA_CLIENTE = ("aguardando_cliente", "em_preenchimento")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _resolver_link_ou_404(token):
    """ÚNICO ponto que traduz token → projeto_id neste blueprint inteiro.
    Nunca aceita projeto_id de nenhuma outra fonte — ver nota de segurança
    no topo do arquivo."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM terceirizacao_links_portal WHERE token = ? AND revogado = 0", (token,)
    ).fetchone()
    if row is None:
        raise ApiError("Link inválido ou revogado.", status=404, codigo="link_invalido")
    link = dict(row)
    if link["expira_em"] < _now_iso():
        raise ApiError("Este link expirou — peça um novo link ao seu contato na Alphafitus.", status=410, codigo="link_expirado")
    conn.execute("UPDATE terceirizacao_links_portal SET ultimo_acesso_em = ? WHERE id = ?", (_now_iso(), link["id"]))
    return conn, link


def _projeto_do_portal(conn, projeto_id):
    """Versão do projeto pro OLHO DO CLIENTE — reaproveita `_projeto_
    detalhado` do módulo interno (mesmos dados de fórmula/embalagem/
    briefing que a tela interna já monta) e remove só o que não faz
    sentido pro cliente ver (quem criou, responsável interno)."""
    p = tc._projeto_detalhado(conn, projeto_id)
    p.pop("criado_por", None)
    p.pop("responsavel_id", None)
    nutricao = tc._nutricao_para_item(conn, p["item_id"]) if p.get("item_id") else None
    arquivos = conn.execute(
        "SELECT id, nome, categoria, tamanho, criado_em FROM terceirizacao_arquivos WHERE projeto_id = ? AND visibilidade = 'compartilhado' ORDER BY criado_em DESC",
        (projeto_id,),
    ).fetchall()
    return {
        "numero": p["numero"], "status": p["status"], "versao": p["versao"],
        "editavel": p["status"] in STATUS_ABERTOS_PARA_CLIENTE,
        "cliente": {"razao_social": p["cliente"]["razao_social"], "cnpj": p["cliente"].get("cnpj")},
        "item": p.get("item"), "nutricao": nutricao,
        "pote_id": p["pote_id"], "tampa_id": p["tampa_id"], "capsula_id": p["capsula_id"],
        "quantidade_por_pote": p["quantidade_por_pote"], "unidade_quantidade": p["unidade_quantidade"],
        "briefing": p.get("briefing"),
        "solicitacao_alteracao_formula": p.get("solicitacao_alteracao_formula"),
        "arquivos": [dict(a) for a in arquivos],
    }


def _exigir_editavel(conn, projeto_id):
    projeto = conn.execute("SELECT status FROM terceirizacao_projetos WHERE id = ?", (projeto_id,)).fetchone()
    if projeto["status"] not in STATUS_ABERTOS_PARA_CLIENTE:
        raise ApiError(
            "Este projeto já foi enviado para a Alphafitus e não pode mais ser alterado por aqui — "
            "entre em contato com seu vendedor se precisar mudar algo.",
            status=409, codigo="projeto_nao_editavel",
        )
    # Fase 136 — primeira mutação vinda do portal marca "o cliente já
    # começou a preencher" (distinto de "ainda não abriu o link"), pra
    # equipe interna ver esse sinal na lista de projetos.
    if projeto["status"] == "aguardando_cliente":
        conn.execute("UPDATE terceirizacao_projetos SET status = 'em_preenchimento', atualizado_em = ? WHERE id = ?", (_now_iso(), projeto_id))


@bp.get("/<token>")
def obter_projeto_portal(token):
    conn, link = _resolver_link_ou_404(token)
    return jsonify(_projeto_do_portal(conn, link["projeto_id"]))


@bp.get("/<token>/embalagem-disponivel")
def obter_embalagem_disponivel_portal(token):
    """Catálogo de opções pro cliente escolher — mesmo dado que a tela
    interna usa (`/terceirizacao/potes`/`tampas`/`capsulas`), só que sem
    exigir a permissão `terceirizacao.visualizar` (o cliente não tem
    login nenhum)."""
    conn, link = _resolver_link_ou_404(token)
    potes = conn.execute("SELECT * FROM terceirizacao_potes WHERE ativo = 1 ORDER BY nome").fetchall()
    capsulas = conn.execute("SELECT * FROM terceirizacao_capsulas WHERE ativo = 1 ORDER BY nome").fetchall()
    projeto = conn.execute("SELECT pote_id FROM terceirizacao_projetos WHERE id = ?", (link["projeto_id"],)).fetchone()
    if projeto["pote_id"]:
        tem_restricao = conn.execute("SELECT 1 FROM terceirizacao_compat_pote_tampa WHERE pote_id = ?", (projeto["pote_id"],)).fetchone()
        if tem_restricao:
            tampas = conn.execute(
                """SELECT t.* FROM terceirizacao_tampas t JOIN terceirizacao_compat_pote_tampa c ON c.tampa_id = t.id
                   WHERE c.pote_id = ? AND t.ativo = 1 ORDER BY t.nome""",
                (projeto["pote_id"],),
            ).fetchall()
        else:
            tampas = conn.execute("SELECT * FROM terceirizacao_tampas WHERE ativo = 1 ORDER BY nome").fetchall()
    else:
        tampas = []
    return jsonify({
        "potes": [dict(r) for r in potes], "tampas": [dict(r) for r in tampas], "capsulas": [dict(r) for r in capsulas],
    })


@bp.put("/<token>/embalagem")
def definir_embalagem_portal(token):
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    _exigir_editavel(conn, projeto_id)
    dados = request.get_json(silent=True) or {}
    pote_id, tampa_id, capsula_id = dados.get("pote_id"), dados.get("tampa_id"), dados.get("capsula_id")
    for campo, valor, tabela in (("pote_id", pote_id, "terceirizacao_potes"), ("tampa_id", tampa_id, "terceirizacao_tampas"), ("capsula_id", capsula_id, "terceirizacao_capsulas")):
        if valor is not None and not conn.execute(f"SELECT 1 FROM {tabela} WHERE id = ? AND ativo = 1", (valor,)).fetchone():
            raise ApiError(f"{campo} inválido.", status=400)
    if pote_id and tampa_id:
        tem_restricao = conn.execute("SELECT 1 FROM terceirizacao_compat_pote_tampa WHERE pote_id = ?", (pote_id,)).fetchone()
        if tem_restricao and not conn.execute(
            "SELECT 1 FROM terceirizacao_compat_pote_tampa WHERE pote_id = ? AND tampa_id = ?", (pote_id, tampa_id)
        ).fetchone():
            raise ApiError("Esta tampa não é compatível com o pote escolhido.", status=400, codigo="embalagem_incompativel")
    quantidade = dados.get("quantidade_por_pote")
    unidade = dados.get("unidade_quantidade")
    if unidade is not None and unidade not in ("capsulas", "gramas"):
        raise ApiError("unidade_quantidade deve ser 'capsulas' ou 'gramas'.", status=400)
    conn.execute(
        "UPDATE terceirizacao_projetos SET pote_id = ?, tampa_id = ?, capsula_id = ?, quantidade_por_pote = ?, unidade_quantidade = ?, atualizado_em = ? WHERE id = ?",
        (pote_id, tampa_id, capsula_id, quantidade, unidade, _now_iso(), projeto_id),
    )
    return jsonify(_projeto_do_portal(conn, projeto_id))


@bp.put("/<token>/briefing")
def definir_briefing_portal(token):
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    _exigir_editavel(conn, projeto_id)
    dados = request.get_json(silent=True) or {}
    campos_texto = ["ideia_projeto", "publico_alvo", "posicionamento", "sensacao_desejada"]
    valores_texto = [dados.get(c) for c in campos_texto]
    estilo_visual = json.dumps(dados.get("estilo_visual") or [])
    cores_preferidas = json.dumps(dados.get("cores_preferidas") or [])
    cores_evitar = json.dumps(dados.get("cores_evitar") or [])
    marcas_referencia = json.dumps(dados.get("marcas_referencia") or [])
    conn.execute(
        """
        INSERT INTO terceirizacao_briefings (projeto_id, ideia_projeto, publico_alvo, posicionamento, sensacao_desejada,
                                              estilo_visual, cores_preferidas, cores_evitar, marcas_referencia, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (projeto_id) DO UPDATE SET
            ideia_projeto = excluded.ideia_projeto, publico_alvo = excluded.publico_alvo,
            posicionamento = excluded.posicionamento, sensacao_desejada = excluded.sensacao_desejada,
            estilo_visual = excluded.estilo_visual, cores_preferidas = excluded.cores_preferidas,
            cores_evitar = excluded.cores_evitar, marcas_referencia = excluded.marcas_referencia,
            atualizado_em = excluded.atualizado_em
        """,
        (projeto_id, *valores_texto, estilo_visual, cores_preferidas, cores_evitar, marcas_referencia, _now_iso()),
    )
    return jsonify(_projeto_do_portal(conn, projeto_id))


@bp.put("/<token>/solicitar-alteracao-formula")
def solicitar_alteracao_formula_portal(token):
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    _exigir_editavel(conn, projeto_id)
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()
    if not texto:
        raise ApiError("Descreva a alteração desejada.", status=400)
    conn.execute("UPDATE terceirizacao_projetos SET solicitacao_alteracao_formula = ?, atualizado_em = ? WHERE id = ?", (texto, _now_iso(), projeto_id))
    return jsonify(_projeto_do_portal(conn, projeto_id))


# ---- Arquivos (reaproveita o padrão de validação de clientes_documentos.py) ----

TIPOS_MIME_PERMITIDOS_PORTAL = ("image/jpeg", "image/png", "image/webp", "application/pdf")
TAMANHO_MAXIMO_BYTES_PORTAL = 10 * 1024 * 1024


def _validar_e_decodificar_arquivo_portal(dados):
    nome_arquivo = (dados.get("nome_arquivo") or "").strip()
    tipo_mime = (dados.get("tipo_mime") or "").strip()
    bruto = dados.get("dados") or ""
    if not nome_arquivo or not tipo_mime or not bruto:
        raise ApiError("Informe nome_arquivo, tipo_mime e dados.", status=400)
    if tipo_mime not in TIPOS_MIME_PERMITIDOS_PORTAL:
        raise ApiError(f"Tipo de arquivo não permitido: {tipo_mime}. Envie JPG, PNG, WEBP ou PDF.", status=400)
    m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", bruto, re.DOTALL)
    conteudo_b64 = m.group(2) if m else bruto
    try:
        decodificado = base64.b64decode(conteudo_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("Conteúdo do arquivo inválido (base64 malformado).", status=400)
    if not decodificado:
        raise ApiError("Arquivo vazio.", status=400)
    if len(decodificado) > TAMANHO_MAXIMO_BYTES_PORTAL:
        raise ApiError(f"Arquivo maior que o limite permitido ({TAMANHO_MAXIMO_BYTES_PORTAL // (1024*1024)} MB).", status=400)
    return nome_arquivo, tipo_mime, conteudo_b64, len(decodificado)


@bp.post("/<token>/arquivos")
def enviar_arquivo_portal(token):
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    _exigir_editavel(conn, projeto_id)
    dados = request.get_json(silent=True) or {}
    nome_arquivo, tipo_mime, conteudo_b64, tamanho = _validar_e_decodificar_arquivo_portal(dados)
    categoria = dados.get("categoria") or "referencia"
    if categoria not in ("embalagem", "rotulo", "cor", "estilo", "logotipo", "concorrente", "referencia", "documento_empresa", "outro"):
        categoria = "outro"
    conn.execute(
        """
        INSERT INTO terceirizacao_arquivos (projeto_id, nome, nome_arquivo, tipo_mime, dados, tamanho, categoria, visibilidade, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'compartilhado', ?)
        """,
        # Fase 136 — cliente nunca tem `criado_por` (usuário interno); usa
        # o `criado_por` do próprio link (quem gerou o convite) como
        # responsável de auditoria pelo upload — nunca NULL, sempre
        # rastreável a uma pessoa real do lado da Alphafitus.
        (projeto_id, nome_arquivo, nome_arquivo, tipo_mime, conteudo_b64, tamanho, categoria, link["criado_por"]),
    )
    return jsonify(_projeto_do_portal(conn, projeto_id)), 201


@bp.get("/<token>/arquivos/<int:arquivo_id>/download")
def baixar_arquivo_portal(token, arquivo_id):
    conn, link = _resolver_link_ou_404(token)
    arquivo = conn.execute(
        "SELECT * FROM terceirizacao_arquivos WHERE id = ? AND projeto_id = ? AND visibilidade = 'compartilhado'",
        (arquivo_id, link["projeto_id"]),
    ).fetchone()
    if arquivo is None:
        raise ApiError("Arquivo não encontrado.", status=404)
    bruto = base64.b64decode(arquivo["dados"])
    return Response(bruto, mimetype=arquivo["tipo_mime"] or "application/octet-stream")


@bp.get("/<token>/mockup.png")
def mockup_portal(token):
    conn, link = _resolver_link_ou_404(token)
    projeto = tc._projeto_detalhado(conn, link["projeto_id"])
    png_bytes = tc._gerar_mockup_png(projeto, projeto["cliente"], projeto.get("item"), projeto.get("pote"), projeto.get("tampa"), projeto.get("capsula"))
    return Response(png_bytes, mimetype="image/png")


@bp.post("/<token>/concluir")
def concluir_portal(token):
    """"Ao devolver o preenchimento, avisa o usuário responsável" (pedido
    do usuário) — o backend já sabe, na hora, que o cliente terminou:
    não precisa de webhook de WhatsApp nenhum pra descobrir isso (ver
    nota no topo do arquivo)."""
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    projeto = conn.execute("SELECT * FROM terceirizacao_projetos WHERE id = ?", (projeto_id,)).fetchone()
    if projeto["status"] not in STATUS_ABERTOS_PARA_CLIENTE:
        raise ApiError("Este projeto já foi concluído anteriormente.", status=409, codigo="ja_concluido")
    conn.execute(
        "UPDATE terceirizacao_projetos SET status = 'aguardando_revisao', atualizado_em = ? WHERE id = ?",
        (_now_iso(), projeto_id),
    )
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=link["criado_por"],
                     acao="cliente_concluiu_preenchimento_via_portal", ip=client_ip(), dispositivo=client_device())
    if projeto["responsavel_id"]:
        notificacoes_service.criar(
            conn, usuario_id=projeto["responsavel_id"], tipo="terceirizacao_cliente_concluiu",
            mensagem=f"O cliente concluiu o preenchimento do projeto {projeto['numero']} — pronto para revisão interna.",
        )
    else:
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="terceirizacao", acao="criar", tipo="terceirizacao_cliente_concluiu",
            mensagem=f"O cliente concluiu o preenchimento do projeto {projeto['numero']} — pronto para revisão interna.",
        )
    return jsonify(_projeto_do_portal(conn, projeto_id))
