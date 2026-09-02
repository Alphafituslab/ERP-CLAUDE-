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
import io
import json
import re
import secrets as secrets_lib

from flask import Blueprint, Response, g, jsonify, request

from .. import audit
from .. import backup_service
from .. import notificacoes_service
from ..context import ApiError, client_device, client_ip, get_db
from ..imagens import validar_imagem_base64
from ..pdf_marca import desenhar_cabecalho_logo
from ..permissions import requires_permission

# Fase 136 — o portal do cliente roda por trás de um túnel SSH reverso
# (máquina local → VPS), exposto publicamente pelo Caddy em
# whatts.alphafitus.com.br:9445 (path-restrito a /portal/*, ver nota
# completa em migrations/schema_fase136.sql e no Caddyfile do VPS) — esta
# é a ÚNICA origem pública que existe pra essa URL; nunca montar o link a
# partir de `request.host`/localhost, que só o computador da empresa
# consegue abrir.
URL_BASE_PORTAL_PUBLICO = "https://whatts.alphafitus.com.br:9445"
TTL_LINK_PORTAL_DIAS = 30

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
        item = conn.execute(
            "SELECT i.*, mp.nome AS nome_memorial FROM itens i LEFT JOIN memorial_produtos mp ON mp.id = i.memorial_produto_id WHERE i.id = ?",
            (p["item_id"],),
        ).fetchone()
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
    usado em `comercial.listar_clientes`) — pedido do usuário (2026-09-02):
    também busca e MOSTRA o nome cadastrado no Memorial Técnico
    (`memorial_produtos.nome`, via `itens.memorial_produto_id`) quando o
    item já estiver vinculado a um, porque é esse o nome que o
    Comercial/P&D reconhece de verdade — `itens.descricao` às vezes é só
    um nome técnico interno."""
    conn = get_db()
    busca = (request.args.get("busca") or "").strip()
    params = ["produto_acabado"]
    where_busca = ""
    if busca:
        where_busca = "AND (i.descricao LIKE ? OR i.codigo LIKE ? OR i.categoria LIKE ? OR mp.nome LIKE ?)"
        termo = f"%{busca}%"
        params += [termo, termo, termo, termo]
    rows = conn.execute(
        f"""
        SELECT i.id, i.codigo, i.descricao, i.categoria, i.imagem, i.unidade_medida, i.memorial_produto_id,
               mp.nome AS nome_memorial
        FROM itens i LEFT JOIN memorial_produtos mp ON mp.id = i.memorial_produto_id
        WHERE i.tipo = ? {where_busca} AND i.status = 'ativo' ORDER BY i.descricao LIMIT 30
        """,
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


def _nutricao_para_item(conn, item_id):
    """Extraído como função pura (sem `jsonify`) pra poder ser reaproveitada
    tanto pela rota `obter_nutricao_item` (JSON pro frontend) quanto por
    `_gerar_pdf_dossie` (embutida no PDF) — nenhuma delas duplica a lógica
    de resolver item → memorial → nutrientes."""
    item = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError("Item não encontrado.", status=404)
    item = dict(item)
    if not item.get("memorial_produto_id"):
        return {
            "vinculado_a_memorial": False,
            "mensagem": "Este item ainda não está vinculado a um Memorial Técnico aprovado. "
                        "Peça para P&D/Qualidade vincular em Itens > Editar > Memorial Técnico.",
        }
    memorial = conn.execute(
        """
        SELECT * FROM memoriais WHERE produto_id = ? AND status = 'aprovado'
        ORDER BY data_emissao DESC, id DESC LIMIT 1
        """,
        (item["memorial_produto_id"],),
    ).fetchone()
    if memorial is None:
        return {
            "vinculado_a_memorial": True,
            "memorial_aprovado_encontrado": False,
            "mensagem": "Este item está vinculado a um produto do Memorial Técnico, mas ainda não há "
                        "nenhum memorial APROVADO para ele.",
        }
    memorial = dict(memorial)
    return {
        "vinculado_a_memorial": True,
        "memorial_aprovado_encontrado": True,
        "memorial_id": memorial["id"],
        "memorial_codigo": memorial["codigo"],
        "tabela_nutricional": _extrair_nutrientes(memorial.get("calculos_nutricionais") or memorial.get("composicao_nutricional")),
        "ingredientes_ativos": memorial.get("ingredientes_ativos"),
        "excipientes": memorial.get("excipientes"),
        "lista_ingredientes": memorial.get("lista_ingredientes"),
        "advertencias": memorial.get("advertencias"),
    }


@bp.get("/formulas-disponiveis/<int:item_id>/nutricao")
@requires_permission("terceirizacao", "visualizar")
def obter_nutricao_item(item_id):
    conn = get_db()
    return jsonify(_nutricao_para_item(conn, item_id))


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


# =============================================================================
# Fase 135 (Fase B) — Aprovação interna multi-departamento + geração do
# "Dossiê de Desenvolvimento de Produto" (PDF) + mockup do produto.
# =============================================================================

DEPARTAMENTOS_APROVACAO = ("comercial", "pd", "qualidade", "regulatorio")
ROTULOS_DEPARTAMENTO = {"comercial": "Comercial", "pd": "P&D", "qualidade": "Qualidade", "regulatorio": "Regulatório"}
PERMISSAO_POR_DEPARTAMENTO = {
    "comercial": "aprovar_comercial", "pd": "aprovar_pd",
    "qualidade": "aprovar_qualidade", "regulatorio": "aprovar_regulatorio",
}


def _aprovacoes_do_projeto(conn, projeto_id):
    rows = conn.execute(
        """
        SELECT a.*, u.nome AS decidido_por_nome
        FROM terceirizacao_aprovacoes a LEFT JOIN usuarios u ON u.id = a.decidido_por
        WHERE a.projeto_id = ? ORDER BY a.departamento
        """,
        (projeto_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@bp.get("/projetos/<int:projeto_id>/aprovacoes")
@requires_permission("terceirizacao", "visualizar")
def listar_aprovacoes_projeto(projeto_id):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    return jsonify(_aprovacoes_do_projeto(conn, projeto_id))


@bp.post("/projetos/<int:projeto_id>/enviar-para-aprovacao")
@requires_permission("terceirizacao", "criar")
def enviar_para_aprovacao(projeto_id):
    """Checklist mínimo antes de abrir a rodada de aprovação — mesma ideia
    do checklist do pedido original do usuário (fórmula/embalagem/
    quantidade/briefing preenchidos). Cria (ou reabre, se já existiam de
    uma rodada anterior reprovada) as 4 linhas de aprovação, uma por
    departamento, e avisa quem tem a permissão de aprovar cada uma."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    if projeto["status"] not in ("rascunho", "aguardando_revisao"):
        raise ApiError(f"Não é possível enviar para aprovação um projeto '{projeto['status']}'.", status=400)

    faltando = []
    if not projeto["item_id"]:
        faltando.append("fórmula")
    if not projeto["pote_id"]:
        faltando.append("pote")
    if not projeto["tampa_id"]:
        faltando.append("tampa")
    if not projeto["capsula_id"]:
        faltando.append("cápsula")
    if not projeto["quantidade_por_pote"]:
        faltando.append("quantidade")
    if not conn.execute("SELECT 1 FROM terceirizacao_briefings WHERE projeto_id = ?", (projeto_id,)).fetchone():
        faltando.append("briefing")
    if faltando:
        raise ApiError(
            f"Complete antes de enviar para aprovação: {', '.join(faltando)}.",
            status=400, codigo="checklist_incompleto",
        )

    for departamento in DEPARTAMENTOS_APROVACAO:
        conn.execute(
            """
            INSERT INTO terceirizacao_aprovacoes (projeto_id, departamento, status, decidido_por, decidido_em, motivo_reprovacao)
            VALUES (?, ?, 'pendente', NULL, NULL, NULL)
            ON CONFLICT (projeto_id, departamento) DO UPDATE SET
                status = 'pendente', decidido_por = NULL, decidido_em = NULL, motivo_reprovacao = NULL
            """,
            (projeto_id, departamento),
        )
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="terceirizacao", acao=PERMISSAO_POR_DEPARTAMENTO[departamento],
            tipo="terceirizacao_aprovacao_pendente",
            mensagem=f"Projeto {projeto['numero']} aguarda o aceite de {ROTULOS_DEPARTAMENTO[departamento]}.",
        )
    conn.execute(
        "UPDATE terceirizacao_projetos SET status = 'aguardando_aprovacao', atualizado_em = ? WHERE id = ?",
        (_now_iso(), projeto_id),
    )
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="enviado_para_aprovacao", ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.post("/projetos/<int:projeto_id>/aprovacoes/<departamento>/decidir")
def decidir_aprovacao(projeto_id, departamento):
    if departamento not in DEPARTAMENTOS_APROVACAO:
        raise ApiError("Departamento inválido.", status=404)
    # Permissão verificada AQUI (não via decorator) porque a ação exigida
    # depende do `departamento` que vem na própria URL — cada departamento
    # tem sua própria permissão (ver PERMISSAO_POR_DEPARTAMENTO), então uma
    # pessoa de Qualidade não decide a linha do Comercial mesmo tendo
    # `terceirizacao.visualizar`.
    from ..context import get_current_user
    from ..permissions import usuario_tem_permissao
    usuario_atual = get_current_user()
    conn = get_db()
    if not usuario_tem_permissao(conn, usuario_atual["id"], "terceirizacao", PERMISSAO_POR_DEPARTAMENTO[departamento]):
        raise ApiError("Você não tem permissão para decidir por este departamento.", status=403, codigo="sem_permissao")

    projeto = _projeto_ou_404(conn, projeto_id)
    if projeto["status"] != "aguardando_aprovacao":
        raise ApiError(f"Este projeto não está aguardando aprovação (status atual: '{projeto['status']}').", status=400)
    linha = conn.execute(
        "SELECT * FROM terceirizacao_aprovacoes WHERE projeto_id = ? AND departamento = ?", (projeto_id, departamento)
    ).fetchone()
    if linha is None:
        raise ApiError("Linha de aprovação não encontrada — envie o projeto para aprovação primeiro.", status=404)
    if linha["status"] != "pendente":
        raise ApiError(f"O departamento {ROTULOS_DEPARTAMENTO[departamento]} já decidiu ({linha['status']}) nesta rodada.", status=409)

    dados = request.get_json(silent=True) or {}
    novo_status = dados.get("status")
    if novo_status not in ("aprovado", "reprovado"):
        raise ApiError("status deve ser 'aprovado' ou 'reprovado'.", status=400)
    motivo = (dados.get("motivo") or "").strip()
    if novo_status == "reprovado" and not motivo:
        raise ApiError("Informe o motivo da reprovação.", status=400)

    conn.execute(
        "UPDATE terceirizacao_aprovacoes SET status = ?, decidido_por = ?, decidido_em = ?, motivo_reprovacao = ? WHERE id = ?",
        (novo_status, usuario_atual["id"], _now_iso(), motivo or None, linha["id"]),
    )
    audit.registrar(conn, tabela="terceirizacao_aprovacoes", registro_id=linha["id"], usuario_id=usuario_atual["id"],
                     acao=f"aprovacao_{novo_status}", valor_novo={"departamento": departamento, "motivo": motivo},
                     ip=client_ip(), dispositivo=client_device())

    if novo_status == "reprovado":
        conn.execute(
            "UPDATE terceirizacao_projetos SET status = 'aguardando_revisao', atualizado_em = ? WHERE id = ?",
            (_now_iso(), projeto_id),
        )
        if projeto["responsavel_id"]:
            notificacoes_service.criar(
                conn, usuario_id=projeto["responsavel_id"], tipo="terceirizacao_reprovado",
                mensagem=f"Projeto {projeto['numero']} foi reprovado por {ROTULOS_DEPARTAMENTO[departamento]}: {motivo}",
            )
    else:
        todas = _aprovacoes_do_projeto(conn, projeto_id)
        if all(a["status"] == "aprovado" for a in todas):
            conn.execute(
                "UPDATE terceirizacao_projetos SET status = 'aguardando_assinatura', atualizado_em = ? WHERE id = ?",
                (_now_iso(), projeto_id),
            )
            if projeto["responsavel_id"]:
                notificacoes_service.criar(
                    conn, usuario_id=projeto["responsavel_id"], tipo="terceirizacao_aprovado",
                    mensagem=f"Projeto {projeto['numero']} foi aprovado por todos os departamentos — pronto para assinatura.",
                )
    return jsonify(_projeto_detalhado(conn, projeto_id))


# ---- Mockup do produto (Pillow) ----
#
# Composição fotográfica de verdade (pote+tampa+cápsula numa única imagem
# realista) exigiria fotos de produto já preparadas com fundo transparente
# e enquadramento consistente entre si — o catálogo de embalagem aceita
# QUALQUER foto que o administrador suba, sem essa garantia. Por isso este
# MVP monta um "cartão de especificação visual" honesto (cada peça no seu
# próprio quadro, lado a lado, com a cor/nome escritos) em vez de tentar
# sobrepor fotos incompatíveis entre si e gerar um resultado quebrado. Uma
# composição fotorrealista de verdade fica para quando houver um banco de
# imagens de embalagem preparado especificamente para isso (3D/IA, como o
# pedido original já previa como evolução futura).

def _gerar_mockup_png(projeto, cliente, item, pote, tampa, capsula):
    from PIL import Image, ImageDraw, ImageFont

    LARGURA, ALTURA = 900, 700
    COR_FUNDO = (18, 22, 20)
    COR_CARTAO = (30, 36, 33)
    COR_BORDA = (196, 165, 92)  # dourado
    COR_TEXTO = (238, 238, 230)
    COR_TEXTO_SUAVE = (150, 155, 150)

    img = Image.new("RGB", (LARGURA, ALTURA), COR_FUNDO)
    desenho = ImageDraw.Draw(img)

    try:
        fonte_titulo = ImageFont.truetype("arialbd.ttf", 34)
        fonte_subtitulo = ImageFont.truetype("arial.ttf", 20)
        fonte_rotulo = ImageFont.truetype("arialbd.ttf", 16)
        fonte_pequena = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        # Sem a fonte do Windows disponível (ex.: rodando em Linux) — cai
        # pra fonte padrão do Pillow, sempre disponível, só menos bonita.
        fonte_titulo = fonte_subtitulo = fonte_rotulo = fonte_pequena = ImageFont.load_default()

    desenho.text((40, 30), "SUA MARCA", font=fonte_subtitulo, fill=COR_TEXTO_SUAVE)
    nome_produto = (item["descricao"] if item else "Produto a definir").upper()
    desenho.text((40, 60), nome_produto, font=fonte_titulo, fill=COR_TEXTO)
    linha_quantidade = []
    if projeto["quantidade_por_pote"]:
        rotulo_unidade = "cápsulas" if projeto["unidade_quantidade"] == "capsulas" else "g"
        linha_quantidade.append(f"{projeto['quantidade_por_pote']} {rotulo_unidade}")
    desenho.text((40, 110), "SUPLEMENTO ALIMENTAR" + (" — " + " / ".join(linha_quantidade) if linha_quantidade else ""),
                 font=fonte_subtitulo, fill=COR_TEXTO_SUAVE)

    def quadro_peca(x, y, largura, altura, imagem_b64, titulo, subtitulo):
        desenho.rectangle([x, y, x + largura, y + altura], outline=COR_BORDA, width=2, fill=COR_CARTAO)
        area_imagem = altura - 70
        if imagem_b64:
            try:
                m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", imagem_b64, re.DOTALL)
                dados_img = base64.b64decode(m.group(2)) if m else base64.b64decode(imagem_b64)
                peca = Image.open(io.BytesIO(dados_img)).convert("RGBA")
                peca.thumbnail((largura - 30, area_imagem - 20))
                pos_x = x + (largura - peca.width) // 2
                pos_y = y + 15 + (area_imagem - 20 - peca.height) // 2
                img.paste(peca, (pos_x, pos_y), peca)
            except Exception:
                desenho.text((x + 15, y + area_imagem // 2), "(sem foto)", font=fonte_pequena, fill=COR_TEXTO_SUAVE)
        else:
            desenho.text((x + 15, y + area_imagem // 2), "(sem foto)", font=fonte_pequena, fill=COR_TEXTO_SUAVE)
        desenho.text((x + 12, y + area_imagem + 8), titulo, font=fonte_rotulo, fill=COR_TEXTO)
        desenho.text((x + 12, y + area_imagem + 30), subtitulo, font=fonte_pequena, fill=COR_TEXTO_SUAVE)

    largura_quadro, altura_quadro, espaco = 260, 380, 20
    y_quadros = 170
    quadro_peca(40, y_quadros, largura_quadro, altura_quadro,
                pote["imagem"] if pote else None, "POTE", pote["nome"] if pote else "—")
    quadro_peca(40 + largura_quadro + espaco, y_quadros, largura_quadro, altura_quadro,
                tampa["imagem"] if tampa else None, "TAMPA", tampa["nome"] if tampa else "—")
    quadro_peca(40 + 2 * (largura_quadro + espaco), y_quadros, largura_quadro, altura_quadro,
                capsula["imagem"] if capsula else None, "CÁPSULA", capsula["nome"] if capsula else "—")

    desenho.text((40, y_quadros + altura_quadro + 30), f"Projeto {projeto['numero']} — {cliente['razao_social']}",
                 font=fonte_pequena, fill=COR_TEXTO_SUAVE)

    saida = io.BytesIO()
    img.save(saida, format="PNG")
    return saida.getvalue()


@bp.get("/projetos/<int:projeto_id>/mockup.png")
@requires_permission("terceirizacao", "visualizar")
def obter_mockup_projeto(projeto_id):
    conn = get_db()
    projeto = _projeto_detalhado(conn, projeto_id)
    png_bytes = _gerar_mockup_png(
        projeto, projeto["cliente"], projeto.get("item"), projeto.get("pote"), projeto.get("tampa"), projeto.get("capsula")
    )
    return Response(png_bytes, mimetype="image/png")


# ---- Dossiê de Desenvolvimento de Produto (PDF) ----

def _gerar_pdf_dossie(projeto, nutricao):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    estilos = getSampleStyleSheet()
    cor_titulo = colors.HexColor("#1a3c2e")
    cor_dourado = colors.HexColor("#a8863f")
    estilo_titulo = ParagraphStyle("TituloDossie", parent=estilos["Title"], textColor=cor_titulo, alignment=TA_CENTER, fontSize=20)
    estilo_secao = ParagraphStyle("SecaoDossie", parent=estilos["Heading2"], textColor=cor_titulo, spaceBefore=14, spaceAfter=6)
    estilo_normal = estilos["Normal"]
    estilo_suave = ParagraphStyle("SuaveDossie", parent=estilos["Normal"], textColor=colors.HexColor("#666666"), fontSize=9)

    elementos = []
    elementos.append(Spacer(1, 1.5 * cm))
    elementos.append(Paragraph("ALPHAFITUS — LABORATÓRIO NUTRACÊUTICO", estilo_suave))
    elementos.append(Paragraph("DOSSIÊ DE DESENVOLVIMENTO DE PRODUTO", estilo_titulo))
    elementos.append(HRFlowable(width="100%", thickness=1, color=cor_dourado, spaceBefore=8, spaceAfter=16))

    try:
        mockup_bytes = _gerar_mockup_png(
            projeto, projeto["cliente"], projeto.get("item"), projeto.get("pote"), projeto.get("tampa"), projeto.get("capsula")
        )
        elementos.append(RLImage(io.BytesIO(mockup_bytes), width=15 * cm, height=15 * cm * 700 / 900))
        elementos.append(Spacer(1, 0.5 * cm))
    except Exception:
        pass

    tabela_identificacao = Table([
        ["Projeto", projeto["numero"]],
        ["Cliente", projeto["cliente"]["razao_social"]],
        ["CNPJ", projeto["cliente"].get("cnpj") or "—"],
        ["Versão", str(projeto["versao"])],
        ["Data", _now_iso()[:10]],
    ], colWidths=[4 * cm, 12 * cm])
    tabela_identificacao.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), cor_titulo),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos.append(tabela_identificacao)
    elementos.append(Spacer(1, 0.4 * cm))

    elementos.append(Paragraph("Produto", estilo_secao))
    item = projeto.get("item")
    elementos.append(Paragraph(
        f"<b>{item['descricao']}</b> ({item['codigo']})" if item else "<i>Fórmula ainda não definida.</i>", estilo_normal
    ))

    elementos.append(Paragraph("Embalagem", estilo_secao))
    pote, tampa, capsula = projeto.get("pote"), projeto.get("tampa"), projeto.get("capsula")
    linhas_embalagem = [["Item", "Nome", "Cor/Material"]]
    if pote:
        linhas_embalagem.append(["Pote", pote["nome"], pote.get("cor") or ""])
    if tampa:
        linhas_embalagem.append(["Tampa", tampa["nome"], tampa.get("cor") or ""])
    if capsula:
        linhas_embalagem.append(["Cápsula", capsula["nome"], f"{capsula.get('cor_cabeca', '')}/{capsula.get('cor_corpo', '')}"])
    if projeto["quantidade_por_pote"]:
        rotulo_unidade = "cápsulas" if projeto["unidade_quantidade"] == "capsulas" else "g"
        linhas_embalagem.append(["Quantidade", f"{projeto['quantidade_por_pote']} {rotulo_unidade}", ""])
    tabela_embalagem = Table(linhas_embalagem, colWidths=[3.5 * cm, 6 * cm, 6.5 * cm])
    tabela_embalagem.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), cor_titulo),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos.append(tabela_embalagem)

    elementos.append(Paragraph("Fórmula — Tabela Nutricional e Ingredientes", estilo_secao))
    if nutricao and nutricao.get("vinculado_a_memorial") and nutricao.get("memorial_aprovado_encontrado"):
        elementos.append(Paragraph(f"Do Memorial Técnico {nutricao.get('memorial_codigo')}.", estilo_suave))
        tab_nutri = nutricao.get("tabela_nutricional")
        if tab_nutri and tab_nutri.get("tipo") == "estruturado" and tab_nutri.get("linhas"):
            linhas_nutri = [["Nutriente", "Quantidade", "Unidade"]] + [
                [str(l.get("nutriente") or ""), str(l.get("quantidade") if l.get("quantidade") is not None else ""), str(l.get("unidade") or "")]
                for l in tab_nutri["linhas"]
            ]
            tabela_nutri_pdf = Table(linhas_nutri, colWidths=[8 * cm, 4 * cm, 4 * cm])
            tabela_nutri_pdf.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), cor_titulo),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ]))
            elementos.append(tabela_nutri_pdf)
        if nutricao.get("lista_ingredientes"):
            elementos.append(Spacer(1, 0.2 * cm))
            elementos.append(Paragraph(f"<b>Ingredientes:</b> {nutricao['lista_ingredientes']}", estilo_normal))
    else:
        elementos.append(Paragraph(
            "<i>Este produto ainda não tem um Memorial Técnico aprovado vinculado — tabela nutricional "
            "e ingredientes pendentes de vínculo.</i>", estilo_suave
        ))

    briefing = projeto.get("briefing")
    if briefing:
        elementos.append(Paragraph("Briefing do Projeto", estilo_secao))
        for rotulo, campo in [("Ideia do projeto", "ideia_projeto"), ("Público-alvo", "publico_alvo"),
                               ("Posicionamento", "posicionamento"), ("Sensação desejada", "sensacao_desejada")]:
            if briefing.get(campo):
                elementos.append(Paragraph(f"<b>{rotulo}:</b> {briefing[campo]}", estilo_normal))
        if briefing.get("estilo_visual"):
            estilos_lista = json.loads(briefing["estilo_visual"])
            if estilos_lista:
                elementos.append(Paragraph(f"<b>Estilo visual:</b> {', '.join(estilos_lista)}", estilo_normal))
        if briefing.get("cores_preferidas"):
            cores_lista = json.loads(briefing["cores_preferidas"])
            if cores_lista:
                elementos.append(Paragraph(f"<b>Cores preferidas:</b> {', '.join(cores_lista)}", estilo_normal))

    if projeto.get("solicitacao_alteracao_formula"):
        elementos.append(Paragraph("Solicitação de Alteração da Fórmula", estilo_secao))
        elementos.append(Paragraph(projeto["solicitacao_alteracao_formula"], estilo_normal))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2.2 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm)
    doc.build(elementos, onFirstPage=desenhar_cabecalho_logo, onLaterPages=desenhar_cabecalho_logo)
    return buffer.getvalue()


@bp.get("/projetos/<int:projeto_id>/documento.pdf")
@requires_permission("terceirizacao", "visualizar")
def obter_documento_projeto(projeto_id):
    conn = get_db()
    projeto = _projeto_detalhado(conn, projeto_id)
    nutricao = _nutricao_para_item(conn, projeto["item_id"]) if projeto.get("item_id") else None
    pdf_bytes = _gerar_pdf_dossie(projeto, nutricao)
    nome_arquivo = _nome_arquivo_seguro(f"Dossie_{projeto['numero']}.pdf")
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome_arquivo}"'},
    )


# =============================================================================
# Fase 136 (Fase C) — link seguro pro portal do cliente + envio por
# WhatsApp. Ver nota de segurança completa em app/routes/portal_terceirizacao.py
# (o lado que RECEBE o token) — aqui é só quem GERA/revoga.
# =============================================================================

def _expira_em_daqui_a_dias(dias):
    import datetime
    return (datetime.datetime.utcnow() + datetime.timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _link_ativo_do_projeto(conn, projeto_id):
    row = conn.execute(
        "SELECT * FROM terceirizacao_links_portal WHERE projeto_id = ? AND revogado = 0 ORDER BY id DESC LIMIT 1",
        (projeto_id,),
    ).fetchone()
    return dict(row) if row else None


@bp.get("/projetos/<int:projeto_id>/link-cliente")
@requires_permission("terceirizacao", "visualizar")
def obter_link_cliente(projeto_id):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    link = _link_ativo_do_projeto(conn, projeto_id)
    if link is None:
        return jsonify({"ativo": False})
    return jsonify({
        "ativo": True, "expirado": link["expira_em"] < _now_iso(),
        "expira_em": link["expira_em"], "ultimo_acesso_em": link["ultimo_acesso_em"],
        "enviado_via_whatsapp": bool(link["enviado_via_whatsapp"]),
        "url": f"{URL_BASE_PORTAL_PUBLICO}/portal/terceirizacao/{link['token']}",
    })


@bp.post("/projetos/<int:projeto_id>/link-cliente")
@requires_permission("terceirizacao", "criar")
def gerar_link_cliente(projeto_id):
    """Gera (ou renova — revoga o anterior primeiro) o link do portal.
    `enviar_whatsapp: true` no corpo manda a mensagem na hora, usando o
    telefone já cadastrado do cliente (`clientes.telefone`) — a MESMA
    configuração de Evolution API já usada pelo aviso de backup (Fase
    130), nunca uma conta separada."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    if projeto["status"] == "cancelado":
        raise ApiError("Não é possível gerar link para um projeto cancelado.", status=400)
    cliente = _cliente_ou_404(conn, projeto["cliente_id"])

    dados = request.get_json(silent=True) or {}
    enviar_whatsapp = bool(dados.get("enviar_whatsapp"))

    conn.execute("UPDATE terceirizacao_links_portal SET revogado = 1 WHERE projeto_id = ? AND revogado = 0", (projeto_id,))
    token = secrets_lib.token_urlsafe(32)
    expira_em = _expira_em_daqui_a_dias(TTL_LINK_PORTAL_DIAS)
    cur = conn.execute(
        "INSERT INTO terceirizacao_links_portal (projeto_id, token, criado_por, expira_em) VALUES (?, ?, ?, ?)",
        (projeto_id, token, usuario_atual["id"], expira_em),
    )
    url = f"{URL_BASE_PORTAL_PUBLICO}/portal/terceirizacao/{token}"

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
                    f"Olá! Preparamos um link para você personalizar o seu produto na Alphafitus.\n\n"
                    f"Acesse e preencha por aqui: {url}\n\n"
                    f"Projeto: {projeto['numero']}"
                )
                backup_service.enviar_texto_whatsapp(config, telefone, texto)
                enviado_com_sucesso = True
                conn.execute("UPDATE terceirizacao_links_portal SET enviado_via_whatsapp = 1 WHERE id = ?", (cur.lastrowid,))
            except Exception as erro:
                erro_envio = str(erro)

    # Fase 136 — gerar o link é o que "abre a porta" pro cliente; só avança
    # o status se ainda estiver no começo (rascunho). Reenviar um link
    # (projeto já em aguardando_cliente/em_preenchimento) não regride nem
    # reavança nada.
    if projeto["status"] == "rascunho":
        conn.execute("UPDATE terceirizacao_projetos SET status = 'aguardando_cliente', atualizado_em = ? WHERE id = ?", (_now_iso(), projeto_id))

    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="link_portal_gerado", valor_novo={"enviado_via_whatsapp": enviado_com_sucesso},
                     ip=client_ip(), dispositivo=client_device())

    return jsonify({
        "url": url, "expira_em": expira_em,
        "enviado_via_whatsapp": enviado_com_sucesso, "erro_envio_whatsapp": erro_envio,
    }), 201


@bp.post("/projetos/<int:projeto_id>/link-cliente/revogar")
@requires_permission("terceirizacao", "criar")
def revogar_link_cliente(projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    resultado = conn.execute("UPDATE terceirizacao_links_portal SET revogado = 1 WHERE projeto_id = ? AND revogado = 0", (projeto_id,))
    if resultado.rowcount == 0:
        raise ApiError("Não há nenhum link ativo para revogar.", status=400)
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="link_portal_revogado", ip=client_ip(), dispositivo=client_device())
    return jsonify({"ativo": False})
