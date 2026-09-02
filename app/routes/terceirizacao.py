"""
Fase 134 — Terceirização Premium (Fase A: fundação de dados).

Pedido do usuário (2026-09-01): módulo novo onde o cliente escolhe uma
fórmula já cadastrada, personaliza embalagem (pote/tampa/cápsula/
quantidade), vê a tabela nutricional/ingredientes automaticamente e
preenche um briefing. O pedido inteiro é grande (portal do cliente,
assinatura eletrônica, WhatsApp, aprovação multi-departamento) e está
sendo entregue em fases — este arquivo cobre só a Fase A (uso interno,
sem portal/assinatura ainda), ver plano completo salvo na sessão.

Reaproveita, de propósito, três padrões já existentes no resto do sistema
em vez de inventar um novo:
  - `app/imagens.py::validar_imagem_base64` para as fotos do catálogo de
    embalagem (mesmo usado por `itens.imagem`).
  - O padrão de upload de `clientes_documentos.py` (allowlist de MIME,
    tamanho máximo, nome de arquivo sanitizado) para os anexos do projeto.
  - `_gerar_numero_pedido()` de `comercial.py` como modelo de numeração —
    aqui a numeração É sequencial de verdade (TER-2026-000001) porque o
    usuário pediu explicitamente um número progressivo no documento final,
    diferente do padrão aleatório (`secrets.token_hex`) usado em Pedidos de
    Venda.
"""
import base64
import binascii
import json
import re

from flask import Blueprint, Response, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..imagens import validar_imagem_base64
from ..permissions import requires_permission

bp = Blueprint("terceirizacao", __name__, url_prefix="/api/v1/terceirizacao")

TIPOS_MIME_ARQUIVOS_PERMITIDOS = ("image/jpeg", "image/png", "image/webp", "application/pdf")
TAMANHO_MAXIMO_ARQUIVO_BYTES = 10 * 1024 * 1024
_CALC_MAGIC = "__CALCV1__"


def _now_iso():
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _nome_arquivo_seguro(nome_arquivo):
    nome = re.sub(r'[^A-Za-z0-9._-]+', "_", nome_arquivo or "arquivo").strip("_") or "arquivo"
    return nome[:200]


def _gerar_numero_projeto(conn):
    """Sequencial de verdade por ano (TER-2026-000001, TER-2026-000002...) —
    conta quantos projetos já existem no ano corrente e tenta o próximo;
    se perder uma corrida (dois projetos criados ao mesmo instante), o
    UNIQUE em `numero` estoura IntegrityError e quem chama decide retentar
    (ver `criar_projeto` abaixo)."""
    import datetime
    ano = datetime.datetime.utcnow().year
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM terceirizacao_projetos WHERE numero LIKE ?", (f"TER-{ano}-%",)
    ).fetchone()["c"]
    return f"TER-{ano}-{total + 1:06d}"


def _cliente_ou_404(conn, cliente_id):
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if row is None:
        raise ApiError("Cliente não encontrado.", status=404)
    return dict(row)


def _projeto_ou_404(conn, projeto_id):
    row = conn.execute("SELECT * FROM terceirizacao_projetos WHERE id = ?", (projeto_id,)).fetchone()
    if row is None:
        raise ApiError("Projeto de terceirização não encontrado.", status=404)
    return dict(row)


def _projeto_detalhado(conn, projeto_id):
    p = _projeto_ou_404(conn, projeto_id)
    p["cliente"] = _cliente_ou_404(conn, p["cliente_id"])
    if p["item_id"]:
        item = conn.execute("SELECT * FROM itens WHERE id = ?", (p["item_id"],)).fetchone()
        p["item"] = dict(item) if item else None
    if p["pote_id"]:
        row = conn.execute("SELECT * FROM terceirizacao_potes WHERE id = ?", (p["pote_id"],)).fetchone()
        p["pote"] = dict(row) if row else None
    if p["tampa_id"]:
        row = conn.execute("SELECT * FROM terceirizacao_tampas WHERE id = ?", (p["tampa_id"],)).fetchone()
        p["tampa"] = dict(row) if row else None
    if p["capsula_id"]:
        row = conn.execute("SELECT * FROM terceirizacao_capsulas WHERE id = ?", (p["capsula_id"],)).fetchone()
        p["capsula"] = dict(row) if row else None
    briefing = conn.execute("SELECT * FROM terceirizacao_briefings WHERE projeto_id = ?", (projeto_id,)).fetchone()
    p["briefing"] = dict(briefing) if briefing else None
    return p


# =============================================================================
# Catálogo de embalagem — pote / tampa / cápsula (nunca existiu antes desta
# fase em nenhuma tabela do sistema).
# =============================================================================

def _embalagem_crud(tabela, campos_extra):
    """Fábrica de handlers list/create/edit para os 3 catálogos (pote/tampa/
    cápsula) — os três têm exatamente o mesmo shape (código/nome/imagem/
    ativo + 2-3 campos próprios), então gerar os handlers uma vez só evita
    triplicar o mesmo CRUD com nomes trocados."""
    def listar():
        conn = get_db()
        incluir_inativos = request.args.get("incluir_inativos") == "1"
        where = "" if incluir_inativos else "WHERE ativo = 1"
        rows = conn.execute(f"SELECT * FROM {tabela} {where} ORDER BY nome").fetchall()
        return jsonify([dict(r) for r in rows])

    def criar():
        usuario_atual = g.usuario_atual
        dados = request.get_json(silent=True) or {}
        conn = get_db()
        codigo = (dados.get("codigo") or "").strip()
        nome = (dados.get("nome") or "").strip()
        if not codigo or not nome:
            raise ApiError("Informe código e nome.", status=400)
        if conn.execute(f"SELECT 1 FROM {tabela} WHERE codigo = ?", (codigo,)).fetchone():
            raise ApiError(f"Já existe um registro com o código '{codigo}'.", status=409)
        imagem = validar_imagem_base64(dados.get("imagem"))
        valores_extra = [dados.get(c) for c in campos_extra]
        colunas = ", ".join(["codigo", "nome"] + campos_extra + ["imagem", "criado_por"])
        marcadores = ", ".join(["?"] * (2 + len(campos_extra) + 2))
        cur = conn.execute(
            f"INSERT INTO {tabela} ({colunas}) VALUES ({marcadores})",
            [codigo, nome, *valores_extra, imagem, usuario_atual["id"]],
        )
        novo = conn.execute(f"SELECT * FROM {tabela} WHERE id = ?", (cur.lastrowid,)).fetchone()
        audit.registrar(conn, tabela=tabela, registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                         acao="criado", valor_novo=dict(novo), ip=client_ip(), dispositivo=client_device())
        return jsonify(dict(novo)), 201

    def editar(item_id):
        usuario_atual = g.usuario_atual
        conn = get_db()
        row = conn.execute(f"SELECT * FROM {tabela} WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ApiError("Registro não encontrado.", status=404)
        dados = request.get_json(silent=True) or {}
        nome = (dados.get("nome") or row["nome"]).strip()
        imagem = validar_imagem_base64(dados["imagem"]) if "imagem" in dados else row["imagem"]
        ativo = int(bool(dados.get("ativo", row["ativo"])))
        valores_extra = [dados.get(c, row[c]) for c in campos_extra]
        set_extra = ", ".join(f"{c} = ?" for c in campos_extra)
        conn.execute(
            f"UPDATE {tabela} SET nome = ?, {set_extra}, imagem = ?, ativo = ? WHERE id = ?",
            [nome, *valores_extra, imagem, ativo, item_id],
        )
        novo = conn.execute(f"SELECT * FROM {tabela} WHERE id = ?", (item_id,)).fetchone()
        audit.registrar(conn, tabela=tabela, registro_id=item_id, usuario_id=usuario_atual["id"],
                         acao="editado", valor_anterior=dict(row), valor_novo=dict(novo),
                         ip=client_ip(), dispositivo=client_device())
        return jsonify(dict(novo))

    return listar, criar, editar


_listar_potes, _criar_pote, _editar_pote = _embalagem_crud("terceirizacao_potes", ["cor", "material", "capacidade_ml", "capacidade_capsulas"])
_listar_tampas, _criar_tampa, _editar_tampa = _embalagem_crud("terceirizacao_tampas", ["cor", "modelo"])
_listar_capsulas, _criar_capsula, _editar_capsula = _embalagem_crud("terceirizacao_capsulas", ["cor_cabeca", "cor_corpo", "material"])

bp.get("/potes", endpoint="listar_potes")(requires_permission("terceirizacao", "visualizar")(_listar_potes))
bp.post("/potes", endpoint="criar_pote")(requires_permission("terceirizacao", "configurar_embalagem")(_criar_pote))
bp.put("/potes/<int:item_id>", endpoint="editar_pote")(requires_permission("terceirizacao", "configurar_embalagem")(_editar_pote))

bp.get("/tampas", endpoint="listar_tampas")(requires_permission("terceirizacao", "visualizar")(_listar_tampas))
bp.post("/tampas", endpoint="criar_tampa")(requires_permission("terceirizacao", "configurar_embalagem")(_criar_tampa))
bp.put("/tampas/<int:item_id>", endpoint="editar_tampa")(requires_permission("terceirizacao", "configurar_embalagem")(_editar_tampa))

bp.get("/capsulas", endpoint="listar_capsulas")(requires_permission("terceirizacao", "visualizar")(_listar_capsulas))
bp.post("/capsulas", endpoint="criar_capsula")(requires_permission("terceirizacao", "configurar_embalagem")(_criar_capsula))
bp.put("/capsulas/<int:item_id>", endpoint="editar_capsula")(requires_permission("terceirizacao", "configurar_embalagem")(_editar_capsula))


@bp.get("/potes/<int:pote_id>/tampas-compativeis")
@requires_permission("terceirizacao", "visualizar")
def listar_tampas_compativeis(pote_id):
    """Ausência de QUALQUER linha de compatibilidade pra este pote = "todas
    as tampas ativas servem" (evita ter que cadastrar compatibilidade pra
    potes genéricos antes deles funcionarem no wizard)."""
    conn = get_db()
    tem_restricao = conn.execute(
        "SELECT 1 FROM terceirizacao_compat_pote_tampa WHERE pote_id = ?", (pote_id,)
    ).fetchone()
    if not tem_restricao:
        rows = conn.execute("SELECT * FROM terceirizacao_tampas WHERE ativo = 1 ORDER BY nome").fetchall()
    else:
        rows = conn.execute(
            """
            SELECT t.* FROM terceirizacao_tampas t
            JOIN terceirizacao_compat_pote_tampa c ON c.tampa_id = t.id
            WHERE c.pote_id = ? AND t.ativo = 1 ORDER BY t.nome
            """,
            (pote_id,),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.put("/potes/<int:pote_id>/tampas-compativeis")
@requires_permission("terceirizacao", "configurar_embalagem")
def definir_tampas_compativeis(pote_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    if not conn.execute("SELECT 1 FROM terceirizacao_potes WHERE id = ?", (pote_id,)).fetchone():
        raise ApiError("Pote não encontrado.", status=404)
    dados = request.get_json(silent=True) or {}
    tampa_ids = dados.get("tampa_ids")
    if not isinstance(tampa_ids, list):
        raise ApiError("Informe tampa_ids como lista (vazia = compatível com todas).", status=400)
    conn.execute("DELETE FROM terceirizacao_compat_pote_tampa WHERE pote_id = ?", (pote_id,))
    for tampa_id in tampa_ids:
        conn.execute(
            "INSERT INTO terceirizacao_compat_pote_tampa (pote_id, tampa_id) VALUES (?, ?)", (pote_id, int(tampa_id))
        )
    audit.registrar(conn, tabela="terceirizacao_compat_pote_tampa", registro_id=pote_id, usuario_id=usuario_atual["id"],
                     acao="compatibilidade_definida", valor_novo={"pote_id": pote_id, "tampa_ids": tampa_ids},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"pote_id": pote_id, "tampa_ids": tampa_ids})


# =============================================================================
# Tabela nutricional / ingredientes — vem do Memorial Técnico ANVISA já
# existente (decisão confirmada com o usuário), via o vínculo novo
# `itens.memorial_produto_id`. Devolve só leitura — o cliente nunca edita
# a fórmula aprovada por aqui (pedido explícito do usuário); se quiser
# mudança, usa `solicitacao_alteracao_formula` no projeto.
# =============================================================================

@bp.get("/formulas-disponiveis")
@requires_permission("terceirizacao", "visualizar")
def listar_formulas_disponiveis():
    """Itens do tipo produto_acabado — o que o cliente pode escolher pra
    terceirizar. Busca por nome/código/categoria (mesmo padrão de busca já
    usado em `comercial.listar_clientes`)."""
    conn = get_db()
    busca = (request.args.get("busca") or "").strip()
    params = ["produto_acabado"]
    where_busca = ""
    if busca:
        where_busca = "AND (descricao LIKE ? OR codigo LIKE ? OR categoria LIKE ?)"
        termo = f"%{busca}%"
        params += [termo, termo, termo]
    rows = conn.execute(
        f"SELECT id, codigo, descricao, categoria, imagem, unidade_medida, memorial_produto_id "
        f"FROM itens WHERE tipo = ? {where_busca} AND status = 'ativo' ORDER BY descricao LIMIT 30",
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


def _extrair_nutrientes(valor_bruto):
    """`calculos_nutricionais`/`composicao_nutricional` de `memoriais` usam
    o prefixo mágico `__CALCV1__` + JSON quando vieram da calculadora do
    Memorial Técnico (ver app/routes/memorial_pdf_campos.py) — texto livre
    puro quando o memorial é antigo/manual. Aqui só extraímos os campos
    simples pra exibição (nutriente/quantidade/unidade) — a lógica de
    faixa de aceitação/%VD completa do PDF do Memorial não é reproduzida
    aqui de propósito (é uma prévia pro cliente, não o documento técnico
    oficial, que continua sendo emitido só pelo Memorial Técnico)."""
    if not valor_bruto:
        return None
    texto = str(valor_bruto)
    if not texto.startswith(_CALC_MAGIC):
        return {"tipo": "texto_livre", "conteudo": texto}
    try:
        dados = json.loads(texto[len(_CALC_MAGIC):])
    except (ValueError, TypeError):
        return {"tipo": "texto_livre", "conteudo": texto}
    nutrientes = dados.get("nutrientes")
    if not isinstance(nutrientes, list):
        return None
    linhas = []
    for n in nutrientes:
        if not isinstance(n, dict):
            continue
        linhas.append({
            "nutriente": n.get("nutriente"),
            "quantidade": n.get("qtdIngrediente"),
            "unidade": n.get("unidade"),
            "vd_percentual": n.get("doseMinRef"),
        })
    return {"tipo": "estruturado", "linhas": linhas}


@bp.get("/formulas-disponiveis/<int:item_id>/nutricao")
@requires_permission("terceirizacao", "visualizar")
def obter_nutricao_item(item_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError("Item não encontrado.", status=404)
    item = dict(item)
    if not item.get("memorial_produto_id"):
        return jsonify({
            "vinculado_a_memorial": False,
            "mensagem": "Este item ainda não está vinculado a um Memorial Técnico aprovado. "
                        "Peça para P&D/Qualidade vincular em Itens > Editar > Memorial Técnico.",
        })
    memorial = conn.execute(
        """
        SELECT * FROM memoriais WHERE produto_id = ? AND status = 'aprovado'
        ORDER BY data_emissao DESC, id DESC LIMIT 1
        """,
        (item["memorial_produto_id"],),
    ).fetchone()
    if memorial is None:
        return jsonify({
            "vinculado_a_memorial": True,
            "memorial_aprovado_encontrado": False,
            "mensagem": "Este item está vinculado a um produto do Memorial Técnico, mas ainda não há "
                        "nenhum memorial APROVADO para ele.",
        })
    memorial = dict(memorial)
    return jsonify({
        "vinculado_a_memorial": True,
        "memorial_aprovado_encontrado": True,
        "memorial_id": memorial["id"],
        "memorial_codigo": memorial["codigo"],
        "tabela_nutricional": _extrair_nutrientes(memorial.get("calculos_nutricionais") or memorial.get("composicao_nutricional")),
        "ingredientes_ativos": memorial.get("ingredientes_ativos"),
        "excipientes": memorial.get("excipientes"),
        "lista_ingredientes": memorial.get("lista_ingredientes"),
        "advertencias": memorial.get("advertencias"),
    })


# =============================================================================
# Projetos de terceirização
# =============================================================================

@bp.get("/projetos")
@requires_permission("terceirizacao", "visualizar")
def listar_projetos():
    conn = get_db()
    status = request.args.get("status")
    cliente_id = request.args.get("cliente_id", type=int)
    clausulas, params = [], []
    if status:
        clausulas.append("p.status = ?")
        params.append(status)
    if cliente_id:
        clausulas.append("p.cliente_id = ?")
        params.append(cliente_id)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT p.*, c.razao_social AS cliente_razao_social, i.descricao AS item_descricao,
               u.nome AS responsavel_nome
        FROM terceirizacao_projetos p
        JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN itens i ON i.id = p.item_id
        LEFT JOIN usuarios u ON u.id = p.responsavel_id
        {where} ORDER BY p.id DESC
        """,
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/projetos/<int:projeto_id>")
@requires_permission("terceirizacao", "visualizar")
def obter_projeto(projeto_id):
    conn = get_db()
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.post("/projetos")
@requires_permission("terceirizacao", "criar")
def criar_projeto():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    cliente_id = dados.get("cliente_id")
    if not cliente_id:
        raise ApiError("Informe cliente_id.", status=400)
    conn = get_db()
    cliente = _cliente_ou_404(conn, cliente_id)
    if cliente["status"] != "ativo":
        raise ApiError("Não é possível criar projeto de terceirização para um cliente inativo.", status=400)
    responsavel_id = dados.get("responsavel_id") or usuario_atual["id"]
    if not conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND status = 'ativo'", (responsavel_id,)).fetchone():
        raise ApiError("Responsável não encontrado ou inativo.", status=404)

    # Retry único em caso de corrida na numeração (ver docstring de
    # `_gerar_numero_projeto`) — volume baixo o suficiente pra não precisar
    # de mais que isso.
    for _tentativa in range(3):
        numero = _gerar_numero_projeto(conn)
        try:
            cur = conn.execute(
                "INSERT INTO terceirizacao_projetos (numero, cliente_id, responsavel_id, criado_por) VALUES (?, ?, ?, ?)",
                (numero, cliente_id, responsavel_id, usuario_atual["id"]),
            )
            break
        except Exception as erro:
            if "UNIQUE" in str(erro) and _tentativa < 2:
                continue
            raise
    projeto_id = cur.lastrowid
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="projeto_criado", valor_novo={"numero": numero, "cliente_id": cliente_id},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id)), 201


@bp.put("/projetos/<int:projeto_id>/formula")
@requires_permission("terceirizacao", "criar")
def definir_formula_projeto(projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    if projeto["status"] != "rascunho":
        raise ApiError("Só é possível alterar a fórmula enquanto o projeto está em rascunho.", status=400)
    dados = request.get_json(silent=True) or {}
    item_id = dados.get("item_id")
    if item_id is not None and not conn.execute(
        "SELECT 1 FROM itens WHERE id = ? AND tipo = 'produto_acabado'", (item_id,)
    ).fetchone():
        raise ApiError("Item não encontrado ou não é um produto acabado.", status=404)
    conn.execute(
        "UPDATE terceirizacao_projetos SET item_id = ?, atualizado_em = ? WHERE id = ?",
        (item_id, _now_iso(), projeto_id),
    )
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="formula_definida", valor_novo={"item_id": item_id}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.put("/projetos/<int:projeto_id>/embalagem")
@requires_permission("terceirizacao", "criar")
def definir_embalagem_projeto(projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    if projeto["status"] != "rascunho":
        raise ApiError("Só é possível alterar a embalagem enquanto o projeto está em rascunho.", status=400)
    dados = request.get_json(silent=True) or {}
    pote_id, tampa_id, capsula_id = dados.get("pote_id"), dados.get("tampa_id"), dados.get("capsula_id")
    quantidade = dados.get("quantidade_por_pote")
    unidade_quantidade = dados.get("unidade_quantidade")
    if unidade_quantidade is not None and unidade_quantidade not in ("capsulas", "gramas"):
        raise ApiError("unidade_quantidade deve ser 'capsulas' ou 'gramas'.", status=400)

    if pote_id and not conn.execute("SELECT 1 FROM terceirizacao_potes WHERE id = ? AND ativo = 1", (pote_id,)).fetchone():
        raise ApiError("Pote não encontrado ou inativo.", status=404)
    if tampa_id:
        if not conn.execute("SELECT 1 FROM terceirizacao_tampas WHERE id = ? AND ativo = 1", (tampa_id,)).fetchone():
            raise ApiError("Tampa não encontrada ou inativa.", status=404)
        if pote_id:
            tem_restricao = conn.execute(
                "SELECT 1 FROM terceirizacao_compat_pote_tampa WHERE pote_id = ?", (pote_id,)
            ).fetchone()
            if tem_restricao and not conn.execute(
                "SELECT 1 FROM terceirizacao_compat_pote_tampa WHERE pote_id = ? AND tampa_id = ?", (pote_id, tampa_id)
            ).fetchone():
                raise ApiError("CONFIGURAÇÃO INCOMPATÍVEL — esta tampa não é compatível com o pote escolhido.", status=409,
                                codigo="embalagem_incompativel")
    if capsula_id and not conn.execute("SELECT 1 FROM terceirizacao_capsulas WHERE id = ? AND ativo = 1", (capsula_id,)).fetchone():
        raise ApiError("Cápsula não encontrada ou inativa.", status=404)

    conn.execute(
        """
        UPDATE terceirizacao_projetos
        SET pote_id = ?, tampa_id = ?, capsula_id = ?, quantidade_por_pote = ?, unidade_quantidade = ?, atualizado_em = ?
        WHERE id = ?
        """,
        (pote_id, tampa_id, capsula_id, quantidade, unidade_quantidade, _now_iso(), projeto_id),
    )
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="embalagem_definida", valor_novo=dados, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.put("/projetos/<int:projeto_id>/solicitar-alteracao-formula")
@requires_permission("terceirizacao", "criar")
def solicitar_alteracao_formula(projeto_id):
    """Etapa 1 do pedido do usuário: cliente não edita a fórmula aprovada
    diretamente — registra um pedido de alteração pra avaliação interna."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()
    if not texto:
        raise ApiError("Descreva a alteração desejada.", status=400)
    conn.execute(
        "UPDATE terceirizacao_projetos SET solicitacao_alteracao_formula = ?, atualizado_em = ? WHERE id = ?",
        (texto, _now_iso(), projeto_id),
    )
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="alteracao_formula_solicitada", valor_novo={"texto": texto}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.post("/projetos/<int:projeto_id>/cancelar")
@requires_permission("terceirizacao", "criar")
def cancelar_projeto(projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    if projeto["status"] in ("assinado", "concluido", "cancelado"):
        raise ApiError(f"Não é possível cancelar um projeto '{projeto['status']}'.", status=400)
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    if not motivo:
        raise ApiError("Informe o motivo do cancelamento.", status=400)
    conn.execute(
        "UPDATE terceirizacao_projetos SET status = 'cancelado', motivo_cancelamento = ?, atualizado_em = ? WHERE id = ?",
        (motivo, _now_iso(), projeto_id),
    )
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="projeto_cancelado", valor_novo={"motivo": motivo}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


# =============================================================================
# Briefing
# =============================================================================

@bp.put("/projetos/<int:projeto_id>/briefing")
@requires_permission("terceirizacao", "criar")
def salvar_briefing(projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    dados = request.get_json(silent=True) or {}

    def _json_lista(valor):
        if valor is None:
            return None
        if not isinstance(valor, list):
            raise ApiError("Campo deve ser uma lista.", status=400)
        return json.dumps(valor, ensure_ascii=False)

    existente = conn.execute("SELECT id FROM terceirizacao_briefings WHERE projeto_id = ?", (projeto_id,)).fetchone()
    valores = (
        dados.get("ideia_projeto"), dados.get("publico_alvo"), dados.get("posicionamento"),
        dados.get("sensacao_desejada"), _json_lista(dados.get("estilo_visual")),
        _json_lista(dados.get("cores_preferidas")), _json_lista(dados.get("cores_evitar")),
        _json_lista(dados.get("marcas_referencia")), _now_iso(),
    )
    if existente:
        conn.execute(
            """
            UPDATE terceirizacao_briefings SET ideia_projeto = ?, publico_alvo = ?, posicionamento = ?,
                sensacao_desejada = ?, estilo_visual = ?, cores_preferidas = ?, cores_evitar = ?,
                marcas_referencia = ?, atualizado_em = ?
            WHERE projeto_id = ?
            """,
            (*valores, projeto_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO terceirizacao_briefings
                (projeto_id, ideia_projeto, publico_alvo, posicionamento, sensacao_desejada,
                 estilo_visual, cores_preferidas, cores_evitar, marcas_referencia, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (projeto_id, *valores),
        )
    audit.registrar(conn, tabela="terceirizacao_briefings", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="briefing_salvo", ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


# =============================================================================
# Arquivos/anexos do projeto — mesmo padrão de clientes_documentos.py
# =============================================================================

def _validar_e_decodificar_arquivo(doc):
    if not isinstance(doc, dict):
        raise ApiError("Cada arquivo deve ser um objeto com nome_arquivo, tipo_mime e dados.", status=400)
    nome_arquivo = (doc.get("nome_arquivo") or "").strip()
    if not nome_arquivo:
        raise ApiError("Informe nome_arquivo.", status=400)
    tipo_mime = (doc.get("tipo_mime") or "").strip().lower()
    if tipo_mime not in TIPOS_MIME_ARQUIVOS_PERMITIDOS:
        raise ApiError(
            f"Tipo de arquivo '{tipo_mime or 'desconhecido'}' não permitido. "
            f"Tipos aceitos: {', '.join(TIPOS_MIME_ARQUIVOS_PERMITIDOS)}.",
            status=400,
        )
    conteudo_base64 = doc.get("dados") or ""
    if not conteudo_base64:
        raise ApiError("Informe o conteúdo em base64 (campo 'dados').", status=400)
    if "," in conteudo_base64 and conteudo_base64.strip().lower().startswith("data:"):
        conteudo_base64 = conteudo_base64.split(",", 1)[1]
    try:
        bruto = base64.b64decode(conteudo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(f"Conteúdo de '{nome_arquivo}' não é um base64 válido.", status=400)
    if len(bruto) == 0:
        raise ApiError(f"O arquivo '{nome_arquivo}' está vazio.", status=400)
    if len(bruto) > TAMANHO_MAXIMO_ARQUIVO_BYTES:
        raise ApiError(
            f"Arquivo '{nome_arquivo}' muito grande ({len(bruto) / (1024 * 1024):.1f} MB, limite "
            f"{TAMANHO_MAXIMO_ARQUIVO_BYTES // (1024 * 1024)} MB).",
            status=400,
        )
    categoria = dados_categoria = (doc.get("categoria") or "outro").strip()
    if categoria not in ("embalagem", "rotulo", "cor", "estilo", "logotipo", "concorrente", "referencia", "documento_empresa", "outro"):
        categoria = "outro"
    visibilidade = (doc.get("visibilidade") or "compartilhado").strip()
    if visibilidade not in ("interno", "compartilhado"):
        visibilidade = "compartilhado"
    nome = (doc.get("nome") or nome_arquivo).strip()
    return nome, nome_arquivo, tipo_mime, conteudo_base64, len(bruto), categoria, visibilidade, doc.get("comentario")


def _arquivo_metadados(row):
    d = dict(row)
    d.pop("dados", None)
    return d


@bp.get("/projetos/<int:projeto_id>/arquivos")
@requires_permission("terceirizacao", "visualizar")
def listar_arquivos_projeto(projeto_id):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    rows = conn.execute(
        "SELECT * FROM terceirizacao_arquivos WHERE projeto_id = ? ORDER BY criado_em", (projeto_id,)
    ).fetchall()
    return jsonify([_arquivo_metadados(r) for r in rows])


@bp.post("/projetos/<int:projeto_id>/arquivos")
@requires_permission("terceirizacao", "criar")
def enviar_arquivo_projeto(projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    doc_validado = _validar_e_decodificar_arquivo(request.get_json(silent=True) or {})
    nome, nome_arquivo, tipo_mime, conteudo_base64, tamanho, categoria, visibilidade, comentario = doc_validado
    cur = conn.execute(
        """
        INSERT INTO terceirizacao_arquivos
            (projeto_id, nome, nome_arquivo, tipo_mime, dados, tamanho, categoria, visibilidade, comentario, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (projeto_id, nome, nome_arquivo, tipo_mime, conteudo_base64, tamanho, categoria, visibilidade, comentario, usuario_atual["id"]),
    )
    audit.registrar(conn, tabela="terceirizacao_arquivos", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="arquivo_enviado", valor_novo={"projeto_id": projeto_id, "nome_arquivo": nome_arquivo},
                     ip=client_ip(), dispositivo=client_device())
    novo = conn.execute("SELECT * FROM terceirizacao_arquivos WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(_arquivo_metadados(novo)), 201


@bp.get("/projetos/<int:projeto_id>/arquivos/<int:arquivo_id>/download")
@requires_permission("terceirizacao", "visualizar")
def baixar_arquivo_projeto(projeto_id, arquivo_id):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    arquivo = conn.execute(
        "SELECT * FROM terceirizacao_arquivos WHERE id = ? AND projeto_id = ?", (arquivo_id, projeto_id)
    ).fetchone()
    if arquivo is None:
        raise ApiError("Arquivo não encontrado.", status=404)
    bruto = base64.b64decode(arquivo["dados"])
    return Response(
        bruto, mimetype=arquivo["tipo_mime"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_nome_arquivo_seguro(arquivo["nome_arquivo"])}"'},
    )


@bp.delete("/projetos/<int:projeto_id>/arquivos/<int:arquivo_id>")
@requires_permission("terceirizacao", "criar")
def excluir_arquivo_projeto(projeto_id, arquivo_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    arquivo = conn.execute(
        "SELECT * FROM terceirizacao_arquivos WHERE id = ? AND projeto_id = ?", (arquivo_id, projeto_id)
    ).fetchone()
    if arquivo is None:
        raise ApiError("Arquivo não encontrado.", status=404)
    conn.execute("DELETE FROM terceirizacao_arquivos WHERE id = ?", (arquivo_id,))
    audit.registrar(conn, tabela="terceirizacao_arquivos", registro_id=arquivo_id, usuario_id=usuario_atual["id"],
                     acao="arquivo_excluido", valor_anterior=_arquivo_metadados(arquivo), ip=client_ip(), dispositivo=client_device())
    return "", 204
