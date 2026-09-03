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
import hashlib
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
    arquivos = conn.execute(
        "SELECT id, nome, categoria, tamanho, criado_em FROM terceirizacao_arquivos WHERE projeto_id = ? AND visibilidade = 'compartilhado' ORDER BY criado_em DESC",
        (projeto_id,),
    ).fetchall()
    return {
        "numero": p["numero"], "status": p["status"], "versao": p["versao"],
        "editavel": p["status"] in STATUS_ABERTOS_PARA_CLIENTE,
        "cliente": {"razao_social": p["cliente"]["razao_social"], "cnpj": p["cliente"].get("cnpj")},
        # Fase 146 — vários itens, cada um com fórmula/embalagem/
        # nutrição próprios (antes era um item só, direto nestes campos).
        "itens": p["itens"],
        "briefing": p.get("briefing"),
        "arquivos": [dict(a) for a in arquivos],
        "assinatura_cliente_nome": p.get("assinatura_cliente_nome"),
        "assinatura_cliente_em": p.get("assinatura_cliente_em"),
        # Fase 140 — assinatura eletrônica de verdade desta versão (se já
        # foi assinada); None enquanto `status` ainda não chegou em
        # 'assinado' pela primeira vez nesta versão.
        "assinatura_eletronica": _assinatura_eletronica_atual(conn, projeto_id, p["versao"]),
        # Fase 145 (Fase E) — arte do rótulo/embalagem (histórico
        # completo de versões, o cliente decide sobre a mais recente) e
        # comentários (só os marcados 'compartilhado' — um 'interno' da
        # equipe nunca chega até aqui, nem por engano).
        "artes": [
            {k: v for k, v in dict(a).items() if k != "dados"}
            for a in conn.execute(
                "SELECT * FROM terceirizacao_artes WHERE projeto_id = ? ORDER BY versao DESC", (projeto_id,)
            ).fetchall()
        ],
        "comentarios": [
            dict(c) for c in conn.execute(
                "SELECT * FROM terceirizacao_comentarios WHERE projeto_id = ? AND visibilidade = 'compartilhado' ORDER BY criado_em",
                (projeto_id,),
            ).fetchall()
        ],
    }


def _assinatura_eletronica_atual(conn, projeto_id, versao):
    linha = conn.execute(
        "SELECT assinante_nome, assinante_email, assinado_em, hash_pdf_sha256 "
        "FROM terceirizacao_versoes WHERE projeto_id = ? AND versao = ?",
        (projeto_id, versao),
    ).fetchone()
    return dict(linha) if linha else None


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
    login nenhum). Fase 146 — `?pote_id=` filtra as tampas compatíveis
    do item que o cliente está editando no momento (cada item tem sua
    própria embalagem agora, não dá mais pra pré-filtrar por "o" pote do
    projeto)."""
    conn, link = _resolver_link_ou_404(token)
    potes = conn.execute("SELECT * FROM terceirizacao_potes WHERE ativo = 1 ORDER BY nome").fetchall()
    capsulas = conn.execute("SELECT * FROM terceirizacao_capsulas WHERE ativo = 1 ORDER BY nome").fetchall()
    pote_id = request.args.get("pote_id", type=int)
    if pote_id:
        tem_restricao = conn.execute("SELECT 1 FROM terceirizacao_compat_pote_tampa WHERE pote_id = ?", (pote_id,)).fetchone()
        if tem_restricao:
            tampas = conn.execute(
                """SELECT t.* FROM terceirizacao_tampas t JOIN terceirizacao_compat_pote_tampa c ON c.tampa_id = t.id
                   WHERE c.pote_id = ? AND t.ativo = 1 ORDER BY t.nome""",
                (pote_id,),
            ).fetchall()
        else:
            tampas = conn.execute("SELECT * FROM terceirizacao_tampas WHERE ativo = 1 ORDER BY nome").fetchall()
    else:
        tampas = conn.execute("SELECT * FROM terceirizacao_tampas WHERE ativo = 1 ORDER BY nome").fetchall()
    return jsonify({
        "potes": [dict(r) for r in potes], "tampas": [dict(r) for r in tampas], "capsulas": [dict(r) for r in capsulas],
    })


@bp.put("/<token>/itens/<int:item_projeto_id>/embalagem")
def definir_embalagem_item_portal(token, item_projeto_id):
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    _exigir_editavel(conn, projeto_id)
    if not conn.execute(
        "SELECT 1 FROM terceirizacao_projeto_itens WHERE id = ? AND projeto_id = ?", (item_projeto_id, projeto_id)
    ).fetchone():
        raise ApiError("Item não encontrado neste projeto.", status=404)
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
        "UPDATE terceirizacao_projeto_itens SET pote_id = ?, tampa_id = ?, capsula_id = ?, quantidade_por_pote = ?, unidade_quantidade = ? WHERE id = ?",
        (pote_id, tampa_id, capsula_id, quantidade, unidade, item_projeto_id),
    )
    conn.execute("UPDATE terceirizacao_projetos SET atualizado_em = ? WHERE id = ?", (_now_iso(), projeto_id))
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


@bp.get("/<token>/itens/<int:item_projeto_id>/mockup.png")
def mockup_item_portal(token, item_projeto_id):
    conn, link = _resolver_link_ou_404(token)
    projeto = tc._projeto_detalhado(conn, link["projeto_id"])
    item = next((i for i in projeto["itens"] if i["id"] == item_projeto_id), None)
    if item is None:
        raise ApiError("Item não encontrado neste projeto.", status=404)
    png_bytes = tc._gerar_mockup_png(
        projeto, projeto["cliente"], item.get("item"), item.get("pote"), item.get("tampa"), item.get("capsula"),
        item.get("quantidade_por_pote"), item.get("unidade_quantidade"),
    )
    return Response(png_bytes, mimetype="image/png")


@bp.put("/<token>/itens/<int:item_projeto_id>/mockup-3d")
def salvar_mockup_3d_item_portal(token, item_projeto_id):
    """Fase 146 — mesma captura da tela interna (Fase 144), só que
    disparada do lado do cliente quando ele abre a visualização 3D no
    portal."""
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    if not conn.execute(
        "SELECT 1 FROM terceirizacao_projeto_itens WHERE id = ? AND projeto_id = ?", (item_projeto_id, projeto_id)
    ).fetchone():
        raise ApiError("Item não encontrado neste projeto.", status=404)
    dados = request.get_json(silent=True) or {}
    imagem = validar_imagem_base64(dados.get("imagem"), tipos_permitidos=("image/png",), tamanho_maximo_bytes=6 * 1024 * 1024)
    if not imagem:
        raise ApiError("Envie a imagem capturada.", status=400)
    conn.execute("UPDATE terceirizacao_projeto_itens SET mockup_3d_imagem = ? WHERE id = ?", (imagem, item_projeto_id))
    return jsonify({"ok": True})


@bp.get("/<token>/documento.pdf")
def documento_portal(token):
    """Pedido do usuário (2026-09-02) — o cliente precisa poder ver uma
    prévia de como ficou o documento ANTES de confirmar/concluir, do
    mesmo jeito que o usuário interno já podia. Mesmo gerador
    (`tc._gerar_pdf_dossie`) usado pela tela interna — é uma prévia, não
    o documento final assinado (esse continua sendo emitido só depois
    da Fase D, quando existir de verdade)."""
    conn, link = _resolver_link_ou_404(token)
    projeto = tc._projeto_detalhado(conn, link["projeto_id"])
    pdf_bytes = tc._gerar_pdf_dossie(projeto)
    return Response(pdf_bytes, mimetype="application/pdf", headers={"Content-Disposition": "inline"})


@bp.post("/<token>/concluir")
def concluir_portal(token):
    """"Ao devolver o preenchimento, avisa o usuário responsável" (pedido
    do usuário) — o backend já sabe, na hora, que o cliente terminou:
    não precisa de webhook de WhatsApp nenhum pra descobrir isso (ver
    nota no topo do arquivo).

    Pedido do usuário (2026-09-02): "assim que o cliente disser que está
    tudo ok, deve abrir um campo para assinatura" — captura uma
    confirmação LEVE (nome + e-mail digitados + IP + data/hora), NÃO a
    assinatura eletrônica de verdade da Fase D (sem hash, sem
    congelamento de versão — ver nota no schema_fase137.sql). Depois de
    capturada, o PDF do momento é salvo no cadastro do cliente
    (`clientes_documentos`, mesma tabela já usada pra outros anexos do
    cliente) — "documento deve ser salvo no cadastro do próprio
    cliente... para possível auditoria"."""
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    projeto = conn.execute("SELECT * FROM terceirizacao_projetos WHERE id = ?", (projeto_id,)).fetchone()
    if projeto["status"] not in STATUS_ABERTOS_PARA_CLIENTE:
        raise ApiError("Este projeto já foi concluído anteriormente.", status=409, codigo="ja_concluido")

    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip()
    if not nome:
        raise ApiError("Informe seu nome para confirmar.", status=400)

    agora = _now_iso()
    conn.execute(
        """
        UPDATE terceirizacao_projetos SET status = 'aguardando_revisao', atualizado_em = ?,
               assinatura_cliente_nome = ?, assinatura_cliente_email = ?, assinatura_cliente_em = ?, assinatura_cliente_ip = ?
        WHERE id = ?
        """,
        (agora, nome, email or None, agora, client_ip(), projeto_id),
    )

    # Salva uma cópia do documento no cadastro do cliente, pra auditoria —
    # nunca deixa a confirmação em si falhar por causa disso (o cliente já
    # confirmou; um problema ao gerar/salvar o PDF é registrado, não
    # propagado como erro pra quem está do outro lado do link).
    try:
        projeto_detalhado = tc._projeto_detalhado(conn, projeto_id)
        pdf_bytes = tc._gerar_pdf_dossie(projeto_detalhado)
        nome_arquivo = f"Terceirizacao_{projeto['numero']}_confirmado_pelo_cliente.pdf"
        conn.execute(
            "INSERT INTO clientes_documentos (cliente_id, nome, nome_arquivo, tipo_mime, dados, tamanho, criado_por) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                projeto["cliente_id"], f"Terceirização {projeto['numero']} — especificação confirmada pelo cliente",
                nome_arquivo, "application/pdf", base64.b64encode(pdf_bytes).decode(), len(pdf_bytes), link["criado_por"],
            ),
        )
    except Exception:
        pass

    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=link["criado_por"],
                     acao="cliente_concluiu_preenchimento_via_portal", valor_novo={"assinatura_cliente_nome": nome},
                     ip=client_ip(), dispositivo=client_device())
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


@bp.post("/<token>/assinar")
def assinar_portal(token):
    """Fase 140 (Fase D do plano) — a assinatura eletrônica DE VERDADE,
    diferente da confirmação leve de `concluir_portal` acima (que
    acontece bem antes no fluxo, só pra avisar a equipe que o cliente
    terminou de preencher). Esta só fica disponível quando o projeto
    chega em 'aguardando_assinatura' — depois que TODOS os departamentos
    já aprovaram internamente (ver decidir_aprovacao em terceirizacao.py)
    — e captura CPF além de nome/e-mail, IP e navegador, gera o PDF final
    NA HORA, calcula o hash SHA-256 dele, e grava tudo (dados + PDF +
    hash) como um snapshot permanente em terceirizacao_versoes — depois
    disso o projeto vira somente-leitura até alguém abrir uma nova versão
    de propósito (POST /projetos/<id>/nova-versao, só uso interno)."""
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    projeto = conn.execute("SELECT * FROM terceirizacao_projetos WHERE id = ?", (projeto_id,)).fetchone()
    if projeto["status"] != "aguardando_assinatura":
        raise ApiError(
            "Este projeto não está aguardando assinatura no momento — "
            "ou ainda não passou pela aprovação interna, ou já foi assinado.",
            status=409, codigo="nao_aguardando_assinatura",
        )

    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip()
    cpf = re.sub(r"\D", "", dados.get("cpf") or "")
    if not nome:
        raise ApiError("Informe seu nome para assinar.", status=400)
    if len(cpf) != 11:
        raise ApiError("Informe um CPF válido (11 dígitos) para assinar.", status=400)

    projeto_detalhado = tc._projeto_detalhado(conn, projeto_id)
    pdf_bytes = tc._gerar_pdf_dossie(projeto_detalhado)
    hash_pdf = hashlib.sha256(pdf_bytes).hexdigest()
    agora = _now_iso()
    navegador = (request.headers.get("User-Agent") or "")[:500]
    versao_atual = projeto["versao"]

    snapshot = {"projeto": projeto_detalhado, "nutricao": nutricao}
    conn.execute(
        """
        INSERT INTO terceirizacao_versoes
            (projeto_id, versao, snapshot_json, hash_pdf_sha256, pdf_dados, pdf_tamanho,
             assinante_nome, assinante_email, assinante_cpf, assinante_ip, assinante_navegador, assinado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            projeto_id, versao_atual, json.dumps(snapshot, ensure_ascii=False, default=str),
            hash_pdf, base64.b64encode(pdf_bytes).decode(), len(pdf_bytes),
            nome, email or None, cpf, client_ip(), navegador, agora,
        ),
    )
    conn.execute("UPDATE terceirizacao_projetos SET status = 'assinado', atualizado_em = ? WHERE id = ?", (agora, projeto_id))

    # Mesmo padrão de "salva no cadastro do cliente pra auditoria" que
    # concluir_portal já usa — nunca deixa a assinatura em si falhar por
    # causa disso.
    try:
        conn.execute(
            "INSERT INTO clientes_documentos (cliente_id, nome, nome_arquivo, tipo_mime, dados, tamanho, criado_por) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                projeto["cliente_id"], f"Terceirização {projeto['numero']} — assinado eletronicamente (v{versao_atual})",
                f"Terceirizacao_{projeto['numero']}_v{versao_atual}_assinado.pdf", "application/pdf",
                base64.b64encode(pdf_bytes).decode(), len(pdf_bytes), link["criado_por"],
            ),
        )
    except Exception:
        pass

    audit.registrar(
        conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=link["criado_por"],
        acao="assinado_eletronicamente", valor_novo={"versao": versao_atual, "hash_pdf_sha256": hash_pdf, "nome": nome},
        ip=client_ip(), dispositivo=client_device(),
    )
    if projeto["responsavel_id"]:
        notificacoes_service.criar(
            conn, usuario_id=projeto["responsavel_id"], tipo="terceirizacao_assinado",
            mensagem=f"Projeto {projeto['numero']} foi assinado eletronicamente por {nome} — hash {hash_pdf[:12]}…",
        )
    else:
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="terceirizacao", acao="criar", tipo="terceirizacao_assinado",
            mensagem=f"Projeto {projeto['numero']} foi assinado eletronicamente por {nome}.",
        )
    return jsonify(_projeto_do_portal(conn, projeto_id))


@bp.get("/<token>/artes/<int:versao>/arquivo")
def baixar_arte_portal(token, versao):
    conn, link = _resolver_link_ou_404(token)
    arte = conn.execute(
        "SELECT * FROM terceirizacao_artes WHERE projeto_id = ? AND versao = ?", (link["projeto_id"], versao)
    ).fetchone()
    if arte is None:
        raise ApiError("Versão de arte não encontrada.", status=404)
    try:
        bruto = base64.b64decode(arte["dados"], validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("Arquivo corrompido.", status=500)
    return Response(bruto, mimetype=arte["tipo_mime"],
                     headers={"Content-Disposition": f"inline; filename=\"{arte['nome_arquivo']}\""})


@bp.post("/<token>/artes/<int:versao>/decidir")
def decidir_arte_portal(token, versao):
    """Fase 145 (Fase E) — o cliente aprova a arte do rótulo ou pede
    alteração, direto pelo link — sem depender de login. Grava nas
    MESMAS colunas que a decisão interna (ver decidir_arte_projeto em
    terceirizacao.py), só com `decidido_por_nome` vindo do que o cliente
    digitou aqui em vez de `g.usuario_atual`. Disponível em QUALQUER
    status do projeto — arte é frequentemente ajustada depois da
    aprovação/assinatura da fórmula em si, não faz sentido travar isso
    ao congelamento da Fase D."""
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    arte = conn.execute(
        "SELECT * FROM terceirizacao_artes WHERE projeto_id = ? AND versao = ?", (projeto_id, versao)
    ).fetchone()
    if arte is None:
        raise ApiError("Versão de arte não encontrada.", status=404)
    if arte["status"] != "aguardando_aprovacao":
        raise ApiError("Esta versão já foi decidida anteriormente.", status=409, codigo="arte_ja_decidida")

    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    novo_status = dados.get("status")
    if not nome:
        raise ApiError("Informe seu nome.", status=400)
    if novo_status not in ("aprovado", "alteracao_solicitada"):
        raise ApiError("status deve ser 'aprovado' ou 'alteracao_solicitada'.", status=400)
    solicitacao_texto = (dados.get("solicitacao_texto") or "").strip()
    if novo_status == "alteracao_solicitada" and not solicitacao_texto:
        raise ApiError("Descreva o que precisa mudar.", status=400)

    conn.execute(
        """
        UPDATE terceirizacao_artes SET status = ?, solicitacao_texto = ?,
               decidido_por_nome = ?, decidido_em = ? WHERE id = ?
        """,
        (novo_status, solicitacao_texto or None, nome, _now_iso(), arte["id"]),
    )
    audit.registrar(conn, tabela="terceirizacao_artes", registro_id=arte["id"], usuario_id=link["criado_por"],
                     acao=f"cliente_arte_{novo_status}", valor_novo={"versao": versao, "nome": nome},
                     ip=client_ip(), dispositivo=client_device())
    projeto = conn.execute("SELECT numero, responsavel_id FROM terceirizacao_projetos WHERE id = ?", (projeto_id,)).fetchone()
    mensagem = (
        f"Cliente aprovou a arte V{versao} do projeto {projeto['numero']}." if novo_status == "aprovado"
        else f"Cliente pediu alteração na arte V{versao} do projeto {projeto['numero']}: {solicitacao_texto}"
    )
    if projeto["responsavel_id"]:
        notificacoes_service.criar(conn, usuario_id=projeto["responsavel_id"], tipo="terceirizacao_arte_decidida", mensagem=mensagem)
    else:
        notificacoes_service.notificar_usuarios_com_permissao(conn, modulo="terceirizacao", acao="criar", tipo="terceirizacao_arte_decidida", mensagem=mensagem)
    return jsonify(_projeto_do_portal(conn, projeto_id))


@bp.post("/<token>/comentarios")
def criar_comentario_portal(token):
    """Comentário do cliente pelo portal — sempre 'compartilhado' (o
    cliente não tem como criar um comentário 'interno', essa opção nem
    existe do lado dele)."""
    conn, link = _resolver_link_ou_404(token)
    projeto_id = link["projeto_id"]
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    texto = (dados.get("texto") or "").strip()
    if not nome:
        raise ApiError("Informe seu nome.", status=400)
    if not texto:
        raise ApiError("Escreva o comentário.", status=400)
    conn.execute(
        "INSERT INTO terceirizacao_comentarios (projeto_id, texto, visibilidade, autor_nome, autor_usuario_id) VALUES (?, ?, 'compartilhado', ?, NULL)",
        (projeto_id, texto, nome),
    )
    audit.registrar(conn, tabela="terceirizacao_comentarios", registro_id=projeto_id, usuario_id=link["criado_por"],
                     acao="cliente_comentou", valor_novo={"nome": nome}, ip=client_ip(), dispositivo=client_device())
    projeto = conn.execute("SELECT numero, responsavel_id FROM terceirizacao_projetos WHERE id = ?", (projeto_id,)).fetchone()
    mensagem = f"Novo comentário do cliente no projeto {projeto['numero']}: {texto[:120]}"
    if projeto["responsavel_id"]:
        notificacoes_service.criar(conn, usuario_id=projeto["responsavel_id"], tipo="terceirizacao_comentario", mensagem=mensagem)
    else:
        notificacoes_service.notificar_usuarios_com_permissao(conn, modulo="terceirizacao", acao="criar", tipo="terceirizacao_comentario", mensagem=mensagem)
    return jsonify(_projeto_do_portal(conn, projeto_id))
