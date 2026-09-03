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

# Fase 143 — teto de `listar_formulas_disponiveis` (busca por texto E a
# lista geral sem filtro nenhum). 30 fazia sentido só pra busca por
# texto (onde sobra); com a lista SEM FILTRO (Fase 141) e restrita a só
# Memorial aprovado (Fase 142), 30 cortava antes de mostrar tudo — hoje
# (2026-09-02) existem 84 produtos com Memorial aprovado; 150 dá folga
# real sem virar uma lista sem fim se o catálogo aprovado crescer muito.
LIMITE_FORMULAS_DISPONIVEIS = 150
TAMANHO_MAXIMO_ARQUIVO_BYTES = 10 * 1024 * 1024


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


def _item_projeto_hidratado(conn, linha):
    """Fase 146 — um item da lista `terceirizacao_projeto_itens`, com
    fórmula/pote/tampa/cápsula/nutrição já resolvidos (mesmo padrão que
    `_projeto_detalhado` fazia pro projeto inteiro antes de virar
    multi-item)."""
    d = dict(linha)
    if d["item_id"]:
        item = conn.execute(
            "SELECT i.*, mp.nome AS nome_memorial FROM itens i LEFT JOIN memorial_produtos mp ON mp.id = i.memorial_produto_id WHERE i.id = ?",
            (d["item_id"],),
        ).fetchone()
        d["item"] = dict(item) if item else None
        d["nutricao"] = _nutricao_para_item(conn, d["item_id"])
    else:
        d["item"] = None
        d["nutricao"] = None
    if d["pote_id"]:
        row = conn.execute("SELECT * FROM terceirizacao_potes WHERE id = ?", (d["pote_id"],)).fetchone()
        d["pote"] = dict(row) if row else None
    if d["tampa_id"]:
        row = conn.execute("SELECT * FROM terceirizacao_tampas WHERE id = ?", (d["tampa_id"],)).fetchone()
        d["tampa"] = dict(row) if row else None
    if d["capsula_id"]:
        row = conn.execute("SELECT * FROM terceirizacao_capsulas WHERE id = ?", (d["capsula_id"],)).fetchone()
        d["capsula"] = dict(row) if row else None
    return d


def _itens_do_projeto(conn, projeto_id):
    linhas = conn.execute(
        "SELECT * FROM terceirizacao_projeto_itens WHERE projeto_id = ? ORDER BY ordem, id", (projeto_id,)
    ).fetchall()
    return [_item_projeto_hidratado(conn, l) for l in linhas]


def _item_projeto_ou_404(conn, projeto_id, item_projeto_id):
    row = conn.execute(
        "SELECT * FROM terceirizacao_projeto_itens WHERE id = ? AND projeto_id = ?", (item_projeto_id, projeto_id)
    ).fetchone()
    if row is None:
        raise ApiError("Item não encontrado neste projeto.", status=404)
    return dict(row)


def _projeto_detalhado(conn, projeto_id):
    p = _projeto_ou_404(conn, projeto_id)
    p["cliente"] = _cliente_ou_404(conn, p["cliente_id"])
    # Fase 146 — um projeto agora pode ter VÁRIOS itens (fórmula +
    # embalagem própria cada), não mais um só. As colunas antigas
    # (item_id/pote_id/tampa_id/capsula_id/quantidade_por_pote/
    # unidade_quantidade/mockup_3d_imagem) direto em
    # terceirizacao_projetos continuam no banco (nunca apagadas — dado
    # de projetos criados antes desta fase, migrado pra cá também), mas
    # o código novo só lê/escreve em `itens`.
    p["itens"] = _itens_do_projeto(conn, projeto_id)
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
    """Busca por nome/código/categoria (mesmo padrão de busca já usado em
    `comercial.listar_clientes`), combinando DUAS fontes de produtos do
    Memorial Técnico — nunca produtos "soltos" do catálogo geral.

    Fase 142 — pedido explícito do usuário (2026-09-02): "Monte sua
    linha" é terceirização de fórmula já registrada na ANVISA — só faz
    sentido vender ao cliente uma fórmula com Memorial Técnico APROVADO
    de verdade, nunca um item qualquer do catálogo geral (a maioria dos
    milhares de itens cadastrados nunca passou pelo Memorial Técnico).
    Antes desta fase a busca misturava os dois; agora só aparece aqui
    quem tem `EXISTS (... memoriais WHERE status='aprovado')` — item já
    vinculado a um memorial aprovado, ou produto do Memorial ainda sem
    item vinculado (que ganha o item na hora, ver PUT .../formula), mas
    SEMPRE com aprovação de verdade por trás.
      1. `itens` já cadastrados E vinculados a um memorial aprovado.
      2. `memorial_produtos` com memorial aprovado que AINDA não têm
         nenhum `item` vinculado — aparecem com `origem: "memorial"`."""
    conn = get_db()
    busca = (request.args.get("busca") or "").strip()
    params_itens = ["produto_acabado"]
    where_busca_itens = ""
    if busca:
        where_busca_itens = "AND (i.descricao LIKE ? OR i.codigo LIKE ? OR i.categoria LIKE ? OR mp.nome LIKE ?)"
        termo = f"%{busca}%"
        params_itens += [termo, termo, termo, termo]
    rows_itens = conn.execute(
        f"""
        SELECT i.id, i.codigo, i.descricao, i.categoria, i.imagem, i.unidade_medida, i.memorial_produto_id,
               mp.nome AS nome_memorial, 'item' AS origem
        FROM itens i JOIN memorial_produtos mp ON mp.id = i.memorial_produto_id
        WHERE i.tipo = ? {where_busca_itens} AND i.status = 'ativo'
          AND EXISTS (SELECT 1 FROM memoriais m WHERE m.produto_id = mp.id AND m.status = 'aprovado')
        ORDER BY i.descricao LIMIT {LIMITE_FORMULAS_DISPONIVEIS}
        """,
        params_itens,
    ).fetchall()
    resultado = [dict(r) for r in rows_itens]

    # Fase 141 — pedido do usuário: a caixa de busca também precisa
    # mostrar algo SEM precisar digitar nada (clicar e já ver uma lista
    # pra escolher, não só buscar por texto). Com `busca` vazio, o "LIKE
    # '%%'" de sempre já cobre 100% das linhas, então nem precisa de um
    # WHERE condicional — só remove a exigência de `busca` não-vazio que
    # antes escondia os produtos do Memorial ainda sem item vinculado.
    # Fase 143 — pedido do usuário: o limite de 30 (pensado originalmente
    # pra busca por texto, onde sobra) estava cortando a lista SEM FILTRO
    # antes de mostrar tudo — hoje (2026-09-02) só existem 84 produtos com
    # Memorial aprovado, então 150 dá folga real sem virar uma lista
    # infinita se o catálogo aprovado crescer bastante.
    vagas_restantes = max(0, LIMITE_FORMULAS_DISPONIVEIS - len(resultado))
    if vagas_restantes:
        termo = f"%{busca}%"
        rows_memorial = conn.execute(
            """
            SELECT mp.id AS memorial_produto_id, mp.nome AS nome_memorial, mp.categoria
            FROM memorial_produtos mp
            WHERE mp.status = 'ativo' AND mp.nome LIKE ?
              AND NOT EXISTS (SELECT 1 FROM itens i2 WHERE i2.memorial_produto_id = mp.id)
              AND EXISTS (SELECT 1 FROM memoriais m WHERE m.produto_id = mp.id AND m.status = 'aprovado')
            ORDER BY mp.nome LIMIT ?
            """,
            (termo, vagas_restantes),
        ).fetchall()
        for r in rows_memorial:
            resultado.append({
                "id": None, "codigo": None, "descricao": None, "categoria": r["categoria"],
                "imagem": None, "unidade_medida": None, "memorial_produto_id": r["memorial_produto_id"],
                "nome_memorial": r["nome_memorial"], "origem": "memorial",
            })
    return jsonify(resultado)


def _extrair_nutrientes(valor_bruto):
    """`memoriais.composicao_nutricional` — a TABELA DE INFORMAÇÃO
    NUTRICIONAL de verdade, a mesma que sai impressa no rótulo/PDF do
    Memorial Técnico (achado real, 2026-09-02: a primeira versão desta
    função lia o campo errado — `calculos_nutricionais`, que é a
    calculadora de FAIXA DE ACEITAÇÃO/dose de referência usada por P&D,
    um dado completamente diferente, não a tabela nutricional que o
    cliente precisa ver). Estrutura real replicada FIELMENTE de
    `app/routes/memorial_pdf_campos.py::_formatar_tabela_nutricional_
    padrao` (não inventada): `{"tipoTabela": "padrao", "dadosPadrao":
    {"porcoesPorEmbalagem", "porcaoGramas", "descricaoPorcao", "linhas":
    [{"nome", "quantidade", "vd", "ativo"}], "rodapeVD"}}`. A variante
    "alimento" (declaração por 100g) segue formato ainda não confirmado
    no próprio Memorial Técnico (comentário do arquivo original) — aqui
    também não arrisca inventar colunas, só devolve os campos brutos que
    existirem, igual ao PDF já faz."""
    if not valor_bruto:
        return None
    texto = str(valor_bruto)
    try:
        dados = json.loads(texto)
    except (ValueError, TypeError):
        return {"tipo": "texto_livre", "conteudo": texto}
    if not isinstance(dados, dict):
        return {"tipo": "texto_livre", "conteudo": texto}

    def _sub_json(bruto):
        # Achado real, 2026-09-02: `dadosPadrao`/`dadosAlimento` NÃO vêm
        # como objeto aninhado — vêm como uma STRING contendo JSON (JSON
        # dentro de JSON, "JSON-em-string" no comentário original de
        # memorial_pdf_campos.py::formatar_composicao_nutricional, que
        # tem exatamente este mesmo `_sub_json`). Sem este segundo
        # `json.loads`, `isinstance(padrao, dict)` dá falso pra TODO
        # memorial e a tabela nunca aparece — foi isso que aconteceu na
        # primeira versão desta função.
        if isinstance(bruto, dict):
            return bruto
        if isinstance(bruto, str):
            try:
                sub = json.loads(bruto)
            except (ValueError, TypeError):
                return None
            return sub if isinstance(sub, dict) else None
        return None

    tipo_tabela = dados.get("tipoTabela")
    if tipo_tabela == "padrao":
        padrao = _sub_json(dados.get("dadosPadrao"))
        if not isinstance(padrao, dict):
            return None
        linhas_ativas = [l for l in (padrao.get("linhas") or []) if isinstance(l, dict) and l.get("ativo", True)]
        return {
            "tipo": "estruturado",
            "porcoes_por_embalagem": padrao.get("porcoesPorEmbalagem"),
            "porcao_gramas": padrao.get("porcaoGramas"),
            "descricao_porcao": padrao.get("descricaoPorcao"),
            "rodape_vd": padrao.get("rodapeVD"),
            "linhas": [
                {"nutriente": l.get("nome"), "quantidade": l.get("quantidade"), "vd": l.get("vd")}
                for l in linhas_ativas
            ],
        }
    if tipo_tabela == "alimento":
        alimento = _sub_json(dados.get("dadosAlimento"))
        if not isinstance(alimento, dict):
            return None
        linhas_dados = [l for l in (alimento.get("linhas") or []) if isinstance(l, dict)]
        return {
            "tipo": "estruturado_alimento",
            "grupo_etario": alimento.get("grupoEtario"),
            "porcoes_por_embalagem": alimento.get("porcoesPorEmbalagem"),
            "porcao_gramas": alimento.get("porcaoGramas"),
            "descricao_porcao": alimento.get("descricaoPorcao"),
            "rodape_vd": alimento.get("rodapeVD"),
            "linhas": [{"nutriente": l.get("nome"), "quantidade": l.get("quantidade"), "vd": l.get("vd")} for l in linhas_dados],
        }
    return {"tipo": "texto_livre", "conteudo": texto}


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
        "tabela_nutricional": _extrair_nutrientes(memorial.get("composicao_nutricional")),
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
    # Fase 146 — a lista mostra o nome do primeiro item + quantos itens o
    # projeto tem no total (não dá mais pra mostrar "o" item, pode ter
    # vários) — subquery correlacionada em vez de JOIN porque cada
    # projeto pode ter 0, 1 ou N linhas em terceirizacao_projeto_itens.
    rows = conn.execute(
        f"""
        SELECT p.*, c.razao_social AS cliente_razao_social, u.nome AS responsavel_nome,
               (SELECT COUNT(*) FROM terceirizacao_projeto_itens pi WHERE pi.projeto_id = p.id) AS total_itens,
               (
                   SELECT i.descricao FROM terceirizacao_projeto_itens pi
                   LEFT JOIN itens i ON i.id = pi.item_id
                   WHERE pi.projeto_id = p.id ORDER BY pi.ordem, pi.id LIMIT 1
               ) AS item_descricao
        FROM terceirizacao_projetos p
        JOIN clientes c ON c.id = p.cliente_id
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


def _item_id_para_memorial_produto(conn, usuario_id, memorial_produto_id):
    """Pedido do usuário (2026-09-02) — achado real: 91 produtos reais do
    Memorial Técnico já existem no próprio AlphafitusOS (85 memoriais,
    dados reais), mas NENHUM tinha `itens.memorial_produto_id` preenchido
    — a busca de fórmula, que só olha `itens`, nunca achava nada. Em vez
    de exigir um cadastro manual prévio em Itens pra cada um dos 91 antes
    de poder usar, cria o `item` na hora, na primeira vez que alguém
    escolhe aquele produto do Memorial — depois disso já fica vinculado
    de verdade e a busca passa a achar direto por `itens` também."""
    existente = conn.execute("SELECT id FROM itens WHERE memorial_produto_id = ?", (memorial_produto_id,)).fetchone()
    if existente:
        return existente["id"]
    produto = conn.execute("SELECT * FROM memorial_produtos WHERE id = ?", (memorial_produto_id,)).fetchone()
    if produto is None:
        raise ApiError("Produto do Memorial Técnico não encontrado.", status=404)
    codigo = f"MEM-{memorial_produto_id}"
    cur = conn.execute(
        "INSERT INTO itens (codigo, descricao, tipo, unidade_medida, memorial_produto_id, criado_por) VALUES (?, ?, 'produto_acabado', 'UN', ?, ?)",
        (codigo, produto["nome"], memorial_produto_id, usuario_id),
    )
    audit.registrar(conn, tabela="itens", registro_id=cur.lastrowid, usuario_id=usuario_id,
                     acao="criado_automaticamente_a_partir_do_memorial_tecnico",
                     valor_novo={"memorial_produto_id": memorial_produto_id, "nome": produto["nome"]},
                     ip=client_ip(), dispositivo=client_device())
    return cur.lastrowid


def _exigir_projeto_rascunho(projeto, acao):
    if projeto["status"] != "rascunho":
        raise ApiError(f"Só é possível {acao} enquanto o projeto está em rascunho.", status=400)


def _validar_embalagem(conn, pote_id, tampa_id, capsula_id):
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


# =============================================================================
# Fase 146 — itens do projeto (cada um com fórmula + embalagem própria).
# Antes desta fase um projeto tinha UM item_id/pote_id/tampa_id/capsula_id
# direto em terceirizacao_projetos; pedido do usuário (2026-09-03): o
# mesmo projeto/contrato pode incluir mais de um produto (ex.: Colágeno
# num pote, Creatina noutro tipo de embalagem), decisão confirmada com o
# usuário: cada item tem embalagem própria (não uma única pro projeto
# inteiro). As colunas antigas continuam no banco (nunca apagadas), só
# não são mais lidas/escritas pelo código novo.
# =============================================================================

@bp.post("/projetos/<int:projeto_id>/itens")
@requires_permission("terceirizacao", "criar")
def adicionar_item_projeto(projeto_id):
    """Cria uma linha nova (fórmula ainda sem embalagem/quantidade — isso
    se define depois, via PUT .../embalagem) — mesma ideia de "adicionar
    mais um produto ao pedido"."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    _exigir_projeto_rascunho(projeto, "adicionar um item")
    dados = request.get_json(silent=True) or {}
    item_id = dados.get("item_id")
    memorial_produto_id = dados.get("memorial_produto_id")
    if memorial_produto_id is not None:
        item_id = _item_id_para_memorial_produto(conn, usuario_atual["id"], memorial_produto_id)
    elif item_id is not None and not conn.execute(
        "SELECT 1 FROM itens WHERE id = ? AND tipo = 'produto_acabado'", (item_id,)
    ).fetchone():
        raise ApiError("Item não encontrado ou não é um produto acabado.", status=404)
    else:
        raise ApiError("Informe item_id ou memorial_produto_id.", status=400)
    proxima_ordem = (conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) + 1 AS o FROM terceirizacao_projeto_itens WHERE projeto_id = ?", (projeto_id,)
    ).fetchone()["o"])
    cur = conn.execute(
        "INSERT INTO terceirizacao_projeto_itens (projeto_id, item_id, ordem) VALUES (?, ?, ?)",
        (projeto_id, item_id, proxima_ordem),
    )
    conn.execute("UPDATE terceirizacao_projetos SET atualizado_em = ? WHERE id = ?", (_now_iso(), projeto_id))
    audit.registrar(conn, tabela="terceirizacao_projeto_itens", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="item_adicionado", valor_novo={"item_id": item_id}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id)), 201


@bp.put("/projetos/<int:projeto_id>/itens/<int:item_projeto_id>/formula")
@requires_permission("terceirizacao", "criar")
def definir_formula_item(projeto_id, item_projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    _exigir_projeto_rascunho(projeto, "alterar a fórmula")
    _item_projeto_ou_404(conn, projeto_id, item_projeto_id)
    dados = request.get_json(silent=True) or {}
    item_id = dados.get("item_id")
    memorial_produto_id = dados.get("memorial_produto_id")
    if memorial_produto_id is not None:
        item_id = _item_id_para_memorial_produto(conn, usuario_atual["id"], memorial_produto_id)
    elif item_id is not None and not conn.execute(
        "SELECT 1 FROM itens WHERE id = ? AND tipo = 'produto_acabado'", (item_id,)
    ).fetchone():
        raise ApiError("Item não encontrado ou não é um produto acabado.", status=404)
    conn.execute("UPDATE terceirizacao_projeto_itens SET item_id = ? WHERE id = ?", (item_id, item_projeto_id))
    conn.execute("UPDATE terceirizacao_projetos SET atualizado_em = ? WHERE id = ?", (_now_iso(), projeto_id))
    audit.registrar(conn, tabela="terceirizacao_projeto_itens", registro_id=item_projeto_id, usuario_id=usuario_atual["id"],
                     acao="formula_definida", valor_novo={"item_id": item_id}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.put("/projetos/<int:projeto_id>/itens/<int:item_projeto_id>/embalagem")
@requires_permission("terceirizacao", "criar")
def definir_embalagem_item(projeto_id, item_projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    _exigir_projeto_rascunho(projeto, "alterar a embalagem")
    _item_projeto_ou_404(conn, projeto_id, item_projeto_id)
    dados = request.get_json(silent=True) or {}
    pote_id, tampa_id, capsula_id = dados.get("pote_id"), dados.get("tampa_id"), dados.get("capsula_id")
    quantidade = dados.get("quantidade_por_pote")
    unidade_quantidade = dados.get("unidade_quantidade")
    if unidade_quantidade is not None and unidade_quantidade not in ("capsulas", "gramas"):
        raise ApiError("unidade_quantidade deve ser 'capsulas' ou 'gramas'.", status=400)
    _validar_embalagem(conn, pote_id, tampa_id, capsula_id)
    conn.execute(
        """
        UPDATE terceirizacao_projeto_itens
        SET pote_id = ?, tampa_id = ?, capsula_id = ?, quantidade_por_pote = ?, unidade_quantidade = ?
        WHERE id = ?
        """,
        (pote_id, tampa_id, capsula_id, quantidade, unidade_quantidade, item_projeto_id),
    )
    conn.execute("UPDATE terceirizacao_projetos SET atualizado_em = ? WHERE id = ?", (_now_iso(), projeto_id))
    audit.registrar(conn, tabela="terceirizacao_projeto_itens", registro_id=item_projeto_id, usuario_id=usuario_atual["id"],
                     acao="embalagem_definida", valor_novo=dados, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.delete("/projetos/<int:projeto_id>/itens/<int:item_projeto_id>")
@requires_permission("terceirizacao", "criar")
def excluir_item_projeto(projeto_id, item_projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    _exigir_projeto_rascunho(projeto, "remover um item")
    item = _item_projeto_ou_404(conn, projeto_id, item_projeto_id)
    conn.execute("DELETE FROM terceirizacao_projeto_itens WHERE id = ?", (item_projeto_id,))
    conn.execute("UPDATE terceirizacao_projetos SET atualizado_em = ? WHERE id = ?", (_now_iso(), projeto_id))
    audit.registrar(conn, tabela="terceirizacao_projeto_itens", registro_id=item_projeto_id, usuario_id=usuario_atual["id"],
                     acao="item_removido", valor_anterior=item, ip=client_ip(), dispositivo=client_device())
    return jsonify(_projeto_detalhado(conn, projeto_id))


@bp.put("/projetos/<int:projeto_id>/itens/<int:item_projeto_id>/solicitar-alteracao-formula")
@requires_permission("terceirizacao", "criar")
def solicitar_alteracao_formula_item(projeto_id, item_projeto_id):
    """Etapa 1 do pedido do usuário: cliente não edita a fórmula aprovada
    diretamente — registra um pedido de alteração pra avaliação interna,
    agora POR ITEM (cada produto do projeto pode ter seu próprio pedido
    de alteração, independente dos outros)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    _item_projeto_ou_404(conn, projeto_id, item_projeto_id)
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()
    if not texto:
        raise ApiError("Descreva a alteração desejada.", status=400)
    conn.execute("UPDATE terceirizacao_projeto_itens SET solicitacao_alteracao_formula = ? WHERE id = ?", (texto, item_projeto_id))
    audit.registrar(conn, tabela="terceirizacao_projeto_itens", registro_id=item_projeto_id, usuario_id=usuario_atual["id"],
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
    projeto = _projeto_ou_404(conn, projeto_id)
    # Fase 140 — mesmo congelamento que definir_formula_projeto/
    # definir_embalagem_projeto já aplicam (só faltava aqui): uma vez que
    # o projeto saiu de rascunho — enviado pra revisão/aprovação/
    # assinatura — os cartões de briefing (inclusive quem assina e
    # condição comercial, adicionados na Fase 139) também precisam parar
    # de aceitar edição silenciosa. Sem isso a "assinatura eletrônica" da
    # Fase D não significa nada: dado assinado podia mudar por baixo.
    if projeto["status"] != "rascunho":
        raise ApiError("Só é possível alterar o briefing enquanto o projeto está em rascunho.", status=400)
    dados = request.get_json(silent=True) or {}

    def _json_lista(valor):
        if valor is None:
            return None
        if not isinstance(valor, list):
            raise ApiError("Campo deve ser uma lista.", status=400)
        return json.dumps(valor, ensure_ascii=False)

    # Fase 139 — campos de "quem assina" + "condição comercial" +
    # cartucho/pouch, da ficha cadastral real que o usuário enviou. Ver
    # nota completa em migrations/schema_fase139.sql — dados fiscais da
    # EMPRESA ficam no cadastro do cliente (CAMPOS_FISCAIS_CLIENTE_
    # EDITAVEIS em comercial.py), só o que pode mudar a cada contrato
    # fica aqui no briefing.
    def _numero_opcional(valor, nome_campo):
        if valor in (None, ""):
            return None
        try:
            return float(valor)
        except (TypeError, ValueError):
            raise ApiError(f"{nome_campo} deve ser numérico.", status=400)

    # Fase 139 — a tela agora tem VÁRIOS cartões com salvamento próprio
    # (briefing criativo, "quem assina", condição comercial) todos
    # gravando neste mesmo endpoint — sem isso, salvar um cartão apagaria
    # o que o outro cartão tinha acabado de gravar. Mesmo padrão de
    # merge-com-o-anterior que `editar_cliente` já usa em comercial.py:
    # campo ausente no corpo da requisição = mantém o valor que já tinha,
    # nunca vira NULL sozinho.
    anterior = conn.execute("SELECT * FROM terceirizacao_briefings WHERE projeto_id = ?", (projeto_id,)).fetchone()
    anterior = dict(anterior) if anterior else {}

    def _texto(campo):
        return dados.get(campo, anterior.get(campo))

    def _lista_json(campo):
        if campo not in dados:
            return anterior.get(campo)
        return _json_lista(dados.get(campo))

    def _numero(campo):
        if campo not in dados:
            return anterior.get(campo)
        return _numero_opcional(dados.get(campo), campo)

    existente = conn.execute("SELECT id FROM terceirizacao_briefings WHERE projeto_id = ?", (projeto_id,)).fetchone()
    valores = (
        _texto("ideia_projeto"), _texto("publico_alvo"), _texto("posicionamento"),
        _texto("sensacao_desejada"), _lista_json("estilo_visual"),
        _lista_json("cores_preferidas"), _lista_json("cores_evitar"),
        _lista_json("marcas_referencia"),
        _texto("assinante_nome"), _texto("assinante_cpf"), _texto("assinante_data_nascimento"),
        _texto("assinante_telefone_whats"), _texto("assinante_endereco"),
        _texto("assinante_cidade_domicilio"), _texto("assinante_email"),
        _texto("embalagem_secundaria"),
        _texto("forma_pagamento"), _texto("prazo_pagamento"),
        _numero("valor_unitario"), _numero("valor_total"),
        _texto("notificacao_observacao"), _texto("excedente_rotulos"),
        _now_iso(),
    )
    if existente:
        conn.execute(
            """
            UPDATE terceirizacao_briefings SET ideia_projeto = ?, publico_alvo = ?, posicionamento = ?,
                sensacao_desejada = ?, estilo_visual = ?, cores_preferidas = ?, cores_evitar = ?,
                marcas_referencia = ?,
                assinante_nome = ?, assinante_cpf = ?, assinante_data_nascimento = ?,
                assinante_telefone_whats = ?, assinante_endereco = ?, assinante_cidade_domicilio = ?,
                assinante_email = ?, embalagem_secundaria = ?,
                forma_pagamento = ?, prazo_pagamento = ?, valor_unitario = ?, valor_total = ?,
                notificacao_observacao = ?, excedente_rotulos = ?, atualizado_em = ?
            WHERE projeto_id = ?
            """,
            (*valores, projeto_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO terceirizacao_briefings
                (projeto_id, ideia_projeto, publico_alvo, posicionamento, sensacao_desejada,
                 estilo_visual, cores_preferidas, cores_evitar, marcas_referencia,
                 assinante_nome, assinante_cpf, assinante_data_nascimento,
                 assinante_telefone_whats, assinante_endereco, assinante_cidade_domicilio,
                 assinante_email, embalagem_secundaria,
                 forma_pagamento, prazo_pagamento, valor_unitario, valor_total,
                 notificacao_observacao, excedente_rotulos, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    if categoria not in (
        "embalagem", "rotulo", "cor", "estilo", "logotipo", "concorrente", "referencia",
        "documento_empresa", "foto_produto_final", "outro",
    ):
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
# Fase 145 (Fase E) — Aprovação de arte (V1/V2/V3) + comentários internos
# vs compartilhados. Diferente do congelamento de versão da Fase D (que
# trava o PROJETO inteiro depois de assinado) — aqui é só o arquivo de
# ARTE que tem ciclo de versão e aprovação próprios, podendo acontecer
# várias vezes mesmo com o projeto já assinado (rótulo é frequentemente
# ajustado depois da aprovação da fórmula/embalagem em si).
# =============================================================================

def _arte_metadados(row):
    d = dict(row)
    d.pop("dados", None)
    return d


@bp.get("/projetos/<int:projeto_id>/artes")
@requires_permission("terceirizacao", "visualizar")
def listar_artes_projeto(projeto_id):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    rows = conn.execute(
        "SELECT * FROM terceirizacao_artes WHERE projeto_id = ? ORDER BY versao DESC", (projeto_id,)
    ).fetchall()
    return jsonify([_arte_metadados(r) for r in rows])


@bp.post("/projetos/<int:projeto_id>/artes")
@requires_permission("terceirizacao", "criar")
def enviar_arte_projeto(projeto_id):
    """Envia uma nova versão de arte (V1 na primeira vez, V2/V3/... nas
    seguintes — número sempre sequencial, nunca reaproveitado). Enviar
    uma nova versão NÃO decide nada sobre a anterior — cada uma guarda
    seu próprio status pra sempre; a lista mostra o histórico completo,
    não só a mais recente."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    dados = request.get_json(silent=True) or {}
    # Reaproveita a mesma validação/decodificação de terceirizacao_arquivos
    # (allowlist de MIME, limite de tamanho, base64 válido) — categoria/
    # visibilidade não existem em terceirizacao_artes, passadas só pra
    # satisfazer a assinatura da função, descartadas com `_`.
    nome_arquivo, tipo_mime, conteudo_base64, tamanho, _cat, _vis, _com = _validar_e_decodificar_arquivo({
        **dados, "categoria": "outro", "visibilidade": "compartilhado",
    })[1:]
    ultima_versao = conn.execute(
        "SELECT MAX(versao) v FROM terceirizacao_artes WHERE projeto_id = ?", (projeto_id,)
    ).fetchone()["v"] or 0
    nova_versao = ultima_versao + 1
    cur = conn.execute(
        """
        INSERT INTO terceirizacao_artes
            (projeto_id, versao, nome_arquivo, tipo_mime, dados, tamanho, observacoes, enviado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (projeto_id, nova_versao, nome_arquivo, tipo_mime, conteudo_base64, tamanho, dados.get("observacoes"), usuario_atual["id"]),
    )
    audit.registrar(conn, tabela="terceirizacao_artes", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="arte_enviada", valor_novo={"versao": nova_versao}, ip=client_ip(), dispositivo=client_device())
    if projeto_ja_tem_link_cliente_ativo(conn, projeto_id):
        notificacoes_service.notificar_usuarios_com_permissao(
            conn, modulo="terceirizacao", acao="criar", tipo="terceirizacao_arte_enviada",
            mensagem=f"Nova arte V{nova_versao} enviada — projeto {projeto_id}.",
        )
    return jsonify(_arte_metadados(conn.execute("SELECT * FROM terceirizacao_artes WHERE id = ?", (cur.lastrowid,)).fetchone())), 201


@bp.get("/projetos/<int:projeto_id>/artes/<int:versao>/arquivo")
@requires_permission("terceirizacao", "visualizar")
def baixar_arte_projeto(projeto_id, versao):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    arte = conn.execute(
        "SELECT * FROM terceirizacao_artes WHERE projeto_id = ? AND versao = ?", (projeto_id, versao)
    ).fetchone()
    if arte is None:
        raise ApiError("Versão de arte não encontrada.", status=404)
    try:
        bruto = base64.b64decode(arte["dados"], validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("Arquivo corrompido.", status=500)
    return Response(bruto, mimetype=arte["tipo_mime"],
                     headers={"Content-Disposition": f"inline; filename=\"{arte['nome_arquivo']}\""})


@bp.post("/projetos/<int:projeto_id>/artes/<int:versao>/decidir")
@requires_permission("terceirizacao", "criar")
def decidir_arte_projeto(projeto_id, versao):
    """Decisão INTERNA (equipe) sobre uma versão de arte — o cliente
    decide pela rota equivalente no portal (`portal_terceirizacao.py`),
    que grava exatamente nas mesmas colunas, só com `decidido_por_nome`
    vindo do nome digitado pelo cliente em vez de `g.usuario_atual`."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    arte = conn.execute(
        "SELECT * FROM terceirizacao_artes WHERE projeto_id = ? AND versao = ?", (projeto_id, versao)
    ).fetchone()
    if arte is None:
        raise ApiError("Versão de arte não encontrada.", status=404)
    dados = request.get_json(silent=True) or {}
    novo_status = dados.get("status")
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
        (novo_status, solicitacao_texto or None, usuario_atual["nome"], _now_iso(), arte["id"]),
    )
    audit.registrar(conn, tabela="terceirizacao_artes", registro_id=arte["id"], usuario_id=usuario_atual["id"],
                     acao=f"arte_{novo_status}", valor_novo={"versao": versao}, ip=client_ip(), dispositivo=client_device())
    return jsonify(_arte_metadados(conn.execute("SELECT * FROM terceirizacao_artes WHERE id = ?", (arte["id"],)).fetchone()))


# ---- Comentários (interno vs compartilhado com o cliente) ----

@bp.get("/projetos/<int:projeto_id>/comentarios")
@requires_permission("terceirizacao", "visualizar")
def listar_comentarios_projeto(projeto_id):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    rows = conn.execute(
        "SELECT * FROM terceirizacao_comentarios WHERE projeto_id = ? ORDER BY criado_em", (projeto_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/projetos/<int:projeto_id>/comentarios")
@requires_permission("terceirizacao", "criar")
def criar_comentario_projeto(projeto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()
    if not texto:
        raise ApiError("Escreva o comentário.", status=400)
    visibilidade = dados.get("visibilidade") if dados.get("visibilidade") in ("interno", "compartilhado") else "interno"
    cur = conn.execute(
        "INSERT INTO terceirizacao_comentarios (projeto_id, texto, visibilidade, autor_nome, autor_usuario_id) VALUES (?, ?, ?, ?, ?)",
        (projeto_id, texto, visibilidade, usuario_atual["nome"], usuario_atual["id"]),
    )
    return jsonify(dict(conn.execute("SELECT * FROM terceirizacao_comentarios WHERE id = ?", (cur.lastrowid,)).fetchone())), 201


def projeto_ja_tem_link_cliente_ativo(conn, projeto_id):
    return bool(_link_ativo_do_projeto(conn, projeto_id))


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

    # Fase 146 — o checklist agora vale por ITEM (cada produto do projeto
    # precisa da própria fórmula/embalagem/quantidade completas), mais a
    # exigência de ter pelo menos 1 item e o briefing (esse continua
    # único, por projeto).
    itens = conn.execute("SELECT * FROM terceirizacao_projeto_itens WHERE projeto_id = ?", (projeto_id,)).fetchall()
    faltando = []
    if not itens:
        faltando.append("pelo menos 1 item (fórmula)")
    for idx, item in enumerate(itens, start=1):
        campos_item = []
        if not item["item_id"]:
            campos_item.append("fórmula")
        if not item["pote_id"]:
            campos_item.append("pote")
        if not item["tampa_id"]:
            campos_item.append("tampa")
        if not item["capsula_id"]:
            campos_item.append("cápsula")
        if not item["quantidade_por_pote"]:
            campos_item.append("quantidade")
        if campos_item:
            faltando.append(f"item {idx}: {', '.join(campos_item)}")
    if not conn.execute("SELECT 1 FROM terceirizacao_briefings WHERE projeto_id = ?", (projeto_id,)).fetchone():
        faltando.append("briefing")
    if faltando:
        raise ApiError(
            f"Complete antes de enviar para aprovação: {'; '.join(faltando)}.",
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


# =============================================================================
# Fase 140 (Fase D do plano) — versões assinadas + congelamento
# =============================================================================

def _versao_resumo(row):
    d = dict(row)
    d.pop("snapshot_json", None)
    d.pop("pdf_dados", None)
    return d


@bp.get("/projetos/<int:projeto_id>/versoes")
@requires_permission("terceirizacao", "visualizar")
def listar_versoes_projeto(projeto_id):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    linhas = conn.execute(
        "SELECT * FROM terceirizacao_versoes WHERE projeto_id = ? ORDER BY versao DESC", (projeto_id,)
    ).fetchall()
    return jsonify([_versao_resumo(r) for r in linhas])


def _versao_ou_404(conn, projeto_id, versao):
    row = conn.execute(
        "SELECT * FROM terceirizacao_versoes WHERE projeto_id = ? AND versao = ?", (projeto_id, versao)
    ).fetchone()
    if row is None:
        raise ApiError("Versão assinada não encontrada.", status=404)
    return dict(row)


@bp.get("/projetos/<int:projeto_id>/versoes/<int:versao>")
@requires_permission("terceirizacao", "visualizar")
def obter_versao_projeto(projeto_id, versao):
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    linha = _versao_ou_404(conn, projeto_id, versao)
    linha["snapshot"] = json.loads(linha.pop("snapshot_json"))
    linha.pop("pdf_dados", None)
    return jsonify(linha)


@bp.get("/projetos/<int:projeto_id>/versoes/<int:versao>/documento.pdf")
@requires_permission("terceirizacao", "visualizar")
def baixar_documento_versao(projeto_id, versao):
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    linha = _versao_ou_404(conn, projeto_id, versao)
    try:
        pdf_bytes = base64.b64decode(linha["pdf_dados"], validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("PDF da versão assinada corrompido.", status=500)
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"Terceirizacao_{projeto['numero']}_v{versao}_assinado.pdf\""},
    )


@bp.post("/projetos/<int:projeto_id>/nova-versao")
@requires_permission("terceirizacao", "criar")
def iniciar_nova_versao(projeto_id):
    """Depois de assinado, o projeto vira somente-leitura (ver checagens
    de status == 'rascunho' em definir_formula_projeto/definir_embalagem_
    projeto/salvar_briefing) — pra mudar qualquer coisa depois disso é
    preciso abrir explicitamente uma V2 nova. A versão assinada anterior
    (dados + PDF + hash) continua intacta pra sempre em
    terceirizacao_versoes — nunca é sobrescrita, só uma nova é criada na
    hora de assinar de novo."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    projeto = _projeto_ou_404(conn, projeto_id)
    if projeto["status"] != "assinado":
        raise ApiError("Só é possível abrir uma nova versão de um projeto já assinado.", status=400)
    nova_versao = projeto["versao"] + 1
    conn.execute(
        "UPDATE terceirizacao_projetos SET versao = ?, status = 'rascunho', atualizado_em = ? WHERE id = ?",
        (nova_versao, _now_iso(), projeto_id),
    )
    audit.registrar(conn, tabela="terceirizacao_projetos", registro_id=projeto_id, usuario_id=usuario_atual["id"],
                     acao="nova_versao_iniciada", valor_novo={"versao": nova_versao}, ip=client_ip(), dispositivo=client_device())
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

def _gerar_mockup_png(projeto, cliente, item, pote, tampa, capsula, quantidade_por_pote=None, unidade_quantidade=None):
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
    if quantidade_por_pote:
        rotulo_unidade = "cápsulas" if unidade_quantidade == "capsulas" else "g"
        linha_quantidade.append(f"{quantidade_por_pote} {rotulo_unidade}")
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


@bp.get("/projetos/<int:projeto_id>/itens/<int:item_projeto_id>/mockup.png")
@requires_permission("terceirizacao", "visualizar")
def obter_mockup_item(projeto_id, item_projeto_id):
    conn = get_db()
    projeto = _projeto_detalhado(conn, projeto_id)
    item = next((i for i in projeto["itens"] if i["id"] == item_projeto_id), None)
    if item is None:
        raise ApiError("Item não encontrado neste projeto.", status=404)
    png_bytes = _gerar_mockup_png(
        projeto, projeto["cliente"], item.get("item"), item.get("pote"), item.get("tampa"), item.get("capsula"),
        item.get("quantidade_por_pote"), item.get("unidade_quantidade"),
    )
    return Response(png_bytes, mimetype="image/png")


@bp.put("/projetos/<int:projeto_id>/itens/<int:item_projeto_id>/mockup-3d")
@requires_permission("terceirizacao", "visualizar")
def salvar_mockup_3d_item(projeto_id, item_projeto_id):
    """Fase 144 (agora por ITEM desde a Fase 146) — o servidor não sabe
    renderizar 3D; quem monta a cena (Three.js, ver renderTerceirizacaoDetalhe
    em app.js) é o navegador — esta rota só recebe a imagem PNG já
    capturada de lá (`canvas.toDataURL()`) e guarda, pra reaproveitar
    tanto na tela quanto no PDF do Dossiê sem precisar renderizar de novo
    toda vez. Permissão 'visualizar' (não 'criar') de propósito —
    qualquer um que já pode ver o projeto pode deixar a cena carregada e
    capturar a imagem, isso não é uma mudança de dado do projeto em si,
    só um retrato dele."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _projeto_ou_404(conn, projeto_id)
    _item_projeto_ou_404(conn, projeto_id, item_projeto_id)
    dados = request.get_json(silent=True) or {}
    imagem = validar_imagem_base64(dados.get("imagem"), tipos_permitidos=("image/png",), tamanho_maximo_bytes=6 * 1024 * 1024)
    if not imagem:
        raise ApiError("Envie a imagem capturada.", status=400)
    conn.execute("UPDATE terceirizacao_projeto_itens SET mockup_3d_imagem = ? WHERE id = ?", (imagem, item_projeto_id))
    audit.registrar(conn, tabela="terceirizacao_projeto_itens", registro_id=item_projeto_id, usuario_id=usuario_atual["id"],
                     acao="mockup_3d_capturado", ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


# ---- Dossiê de Desenvolvimento de Produto (PDF) ----

def _secao_item_pdf(elementos, indice, total, item, estilo_secao, estilo_normal, estilo_suave, cor_titulo):
    """Fase 146 — um bloco completo (imagem/embalagem/fórmula/nutrição)
    POR ITEM do projeto — chamado uma vez pra cada produto, em vez de
    uma vez só pro projeto inteiro."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Image as RLImage, PageBreak, Paragraph, Spacer, Table, TableStyle

    if total > 1:
        elementos.append(Paragraph(f"Item {indice} de {total}", estilo_secao))

    # Imagem — 3D capturado se existir, senão o cartão 2D de sempre;
    # nunca deixa o item sem nenhuma imagem.
    try:
        imagem_3d = item.get("mockup_3d_imagem")
        if imagem_3d:
            from PIL import Image as PILImage
            m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", imagem_3d, re.DOTALL)
            dados_img = base64.b64decode(m.group(2)) if m else base64.b64decode(imagem_3d)
            imagem_pil = PILImage.open(io.BytesIO(dados_img))
            proporcao = imagem_pil.height / imagem_pil.width
            largura_pdf = 11 * cm
            elementos.append(RLImage(io.BytesIO(dados_img), width=largura_pdf, height=largura_pdf * proporcao))
        elif item.get("pote") or item.get("tampa") or item.get("capsula"):
            mockup_bytes = _gerar_mockup_png(
                {"numero": ""}, {"razao_social": ""}, item.get("item"), item.get("pote"), item.get("tampa"), item.get("capsula"),
                item.get("quantidade_por_pote"), item.get("unidade_quantidade"),
            )
            elementos.append(RLImage(io.BytesIO(mockup_bytes), width=13 * cm, height=13 * cm * 700 / 900))
        elementos.append(Spacer(1, 0.4 * cm))
    except Exception:
        pass

    elementos.append(Paragraph("Produto", estilo_secao))
    prod = item.get("item")
    elementos.append(Paragraph(
        f"<b>{prod['descricao']}</b> ({prod['codigo']})" if prod else "<i>Fórmula ainda não definida.</i>", estilo_normal
    ))

    elementos.append(Paragraph("Embalagem", estilo_secao))
    pote, tampa, capsula = item.get("pote"), item.get("tampa"), item.get("capsula")
    linhas_embalagem = [["Item", "Nome", "Cor/Material"]]
    if pote:
        linhas_embalagem.append(["Pote", pote["nome"], pote.get("cor") or ""])
    if tampa:
        linhas_embalagem.append(["Tampa", tampa["nome"], tampa.get("cor") or ""])
    if capsula:
        linhas_embalagem.append(["Cápsula", capsula["nome"], f"{capsula.get('cor_cabeca', '')}/{capsula.get('cor_corpo', '')}"])
    if item.get("quantidade_por_pote"):
        rotulo_unidade = "cápsulas" if item.get("unidade_quantidade") == "capsulas" else "g"
        linhas_embalagem.append(["Quantidade", f"{item['quantidade_por_pote']} {rotulo_unidade}", ""])
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
    nutricao = item.get("nutricao")
    if nutricao and nutricao.get("vinculado_a_memorial") and nutricao.get("memorial_aprovado_encontrado"):
        elementos.append(Paragraph(f"Do Memorial Técnico {nutricao.get('memorial_codigo')}.", estilo_suave))
        tab_nutri = nutricao.get("tabela_nutricional")
        if tab_nutri and tab_nutri.get("tipo") in ("estruturado", "estruturado_alimento") and tab_nutri.get("linhas"):
            resumo_porcao = []
            if tab_nutri.get("porcoes_por_embalagem"):
                resumo_porcao.append(f"Porções por embalagem: {tab_nutri['porcoes_por_embalagem']}")
            if tab_nutri.get("porcao_gramas") or tab_nutri.get("descricao_porcao"):
                rotulo = f"Porção: {tab_nutri['porcao_gramas']} g" if tab_nutri.get("porcao_gramas") else "Porção"
                if tab_nutri.get("descricao_porcao"):
                    rotulo += f" ({tab_nutri['descricao_porcao']})"
                resumo_porcao.append(rotulo)
            if resumo_porcao:
                elementos.append(Paragraph(" — ".join(resumo_porcao), estilo_suave))
            coluna_qtd = f"{tab_nutri['porcao_gramas']} g" if tab_nutri.get("porcao_gramas") else "Quantidade"
            linhas_nutri = [["", coluna_qtd, "%VD*"]] + [
                [str(l.get("nutriente") or ""), str(l.get("quantidade") if l.get("quantidade") is not None else "0"), str(l.get("vd") or "**")]
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
            if tab_nutri.get("rodape_vd"):
                elementos.append(Paragraph(tab_nutri["rodape_vd"], estilo_suave))
        elif tab_nutri and tab_nutri.get("tipo") == "texto_livre":
            elementos.append(Paragraph(tab_nutri.get("conteudo") or "", estilo_normal))
        if nutricao.get("lista_ingredientes"):
            elementos.append(Spacer(1, 0.2 * cm))
            elementos.append(Paragraph(f"<b>Lista de Ingredientes:</b> {nutricao['lista_ingredientes']}", estilo_normal))
    else:
        elementos.append(Paragraph(
            "<i>Este produto ainda não tem um Memorial Técnico aprovado vinculado — tabela nutricional "
            "e ingredientes pendentes de vínculo.</i>", estilo_suave
        ))

    if item.get("solicitacao_alteracao_formula"):
        elementos.append(Paragraph("Solicitação de Alteração da Fórmula", estilo_secao))
        elementos.append(Paragraph(item["solicitacao_alteracao_formula"], estilo_normal))

    if indice < total:
        elementos.append(PageBreak())


def _gerar_pdf_dossie(projeto):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

    tabela_identificacao = Table([
        ["Projeto", projeto["numero"]],
        ["Cliente", projeto["cliente"]["razao_social"]],
        ["CNPJ", projeto["cliente"].get("cnpj") or "—"],
        ["Versão", str(projeto["versao"])],
        ["Data", _now_iso()[:10]],
        ["Itens neste projeto", str(len(projeto["itens"]))],
    ], colWidths=[4 * cm, 12 * cm])
    tabela_identificacao.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), cor_titulo),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos.append(tabela_identificacao)
    elementos.append(Spacer(1, 0.4 * cm))

    # Fase 146 — um bloco (imagem + embalagem + fórmula + nutrição) por
    # ITEM do projeto, em vez de um bloco só pro projeto inteiro; cada
    # item além do primeiro começa em página nova, pra não misturar
    # tabelas nutricionais de produtos diferentes na mesma página.
    total_itens = len(projeto["itens"])
    if total_itens == 0:
        elementos.append(Paragraph("<i>Nenhum item adicionado a este projeto ainda.</i>", estilo_suave))
    for indice, item in enumerate(projeto["itens"], start=1):
        _secao_item_pdf(elementos, indice, total_itens, item, estilo_secao, estilo_normal, estilo_suave, cor_titulo)

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

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2.2 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm)
    doc.build(elementos, onFirstPage=desenhar_cabecalho_logo, onLaterPages=desenhar_cabecalho_logo)
    return buffer.getvalue()


@bp.get("/projetos/<int:projeto_id>/documento.pdf")
@requires_permission("terceirizacao", "visualizar")
def obter_documento_projeto(projeto_id):
    conn = get_db()
    projeto = _projeto_detalhado(conn, projeto_id)
    pdf_bytes = _gerar_pdf_dossie(projeto)
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
