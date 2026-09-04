import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..imagens import validar_imagem_base64, validar_midia_galeria_item_base64
from ..permissions import requires_permission
from .estoque import saldo_total_disponivel_item

bp = Blueprint("itens", __name__, url_prefix="/api/v1/itens")

TIPOS_VALIDOS = (
    "materia_prima", "embalagem_primaria", "embalagem_secundaria",
    "produto_intermediario", "produto_a_granel", "produto_acabado",
    "material_de_laboratorio",
)

# Fase 23 — prefixo usado para gerar automaticamente o codigo de um item
# quando ele nao e informado no cadastro. Pensado para ser o mesmo codigo
# usado depois em OPs, no ERP e no APS (por isso curto e legivel, nao um
# hash aleatorio como em outros geradores do sistema).
PREFIXOS_CODIGO = {
    "materia_prima": "MP",
    "embalagem_primaria": "EPP",
    "embalagem_secundaria": "EPS",
    "produto_intermediario": "PI",
    "produto_a_granel": "PG",
    "produto_acabado": "PA",
    "material_de_laboratorio": "LAB",
}


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _gerar_codigo_item(conn, tipo):
    """Gera um codigo sequencial e legivel para o tipo informado, no formato
    PREFIXO + 6 digitos (ex.: MP000001, PA000042, LAB000007).

    So entram na contagem os codigos que seguem EXATAMENTE esse formato —
    um codigo antigo digitado manualmente (ex.: "MP-001") nao interfere na
    sequencia nem é sobrescrito. A unicidade final e sempre garantida pela
    constraint UNIQUE da coluna "codigo" no banco; o laco abaixo e so uma
    camada extra de seguranca para o caso raro de duas requisicoes
    simultaneas gerarem o mesmo numero.
    """
    prefixo = PREFIXOS_CODIGO[tipo]
    tamanho_total = len(prefixo) + 6
    padrao_glob = prefixo + "[0-9][0-9][0-9][0-9][0-9][0-9]"
    linhas = conn.execute(
        "SELECT codigo FROM itens WHERE codigo GLOB ? AND length(codigo) = ?",
        (padrao_glob, tamanho_total),
    ).fetchall()
    maior = 0
    for linha in linhas:
        try:
            numero = int(linha["codigo"][len(prefixo):])
        except ValueError:
            continue
        if numero > maior:
            maior = numero
    proximo = maior + 1
    while True:
        candidato = f"{prefixo}{proximo:06d}"
        if not conn.execute("SELECT id FROM itens WHERE codigo = ?", (candidato,)).fetchone():
            return candidato
        proximo += 1


def _com_estoque_minimo(item):
    """Fase 87 — `itens.estoque_minimo` já existia no banco desde a Fase 2
    mas nunca era comparado contra nada. Só calcula o saldo real (query
    cara, uma por lote aprovado do item) quando o item de fato TEM um
    mínimo cadastrado — a grande maioria não tem, e não vale a pena pagar
    o custo da agregação à toa para eles."""
    if item.get("estoque_minimo") is None:
        item["estoque_atual"] = None
        item["abaixo_do_minimo"] = None
        return item
    conn = get_db()
    estoque_atual = saldo_total_disponivel_item(conn, item["id"])
    item["estoque_atual"] = estoque_atual
    item["abaixo_do_minimo"] = estoque_atual < item["estoque_minimo"]
    return item


@bp.get("")
@requires_permission("itens", "visualizar")
def listar():
    conn = get_db()
    tipo = request.args.get("tipo")
    if tipo:
        rows = conn.execute("SELECT * FROM itens WHERE tipo = ? ORDER BY codigo", (tipo,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM itens ORDER BY codigo").fetchall()
    return jsonify([_com_estoque_minimo(dict(r)) for r in rows])


@bp.get("/<int:item_id>")
@requires_permission("itens", "visualizar")
def obter(item_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ApiError("Item não encontrado.", status=404)
    return jsonify(_com_estoque_minimo(dict(row)))


@bp.post("")
@requires_permission("itens", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    codigo = (dados.get("codigo") or "").strip()
    descricao = (dados.get("descricao") or "").strip()
    tipo = dados.get("tipo")
    unidade_medida = dados.get("unidade_medida") or "kg"
    requer_analise = 1 if dados.get("requer_analise", True) else 0
    requer_fornecedor_homologado = 1 if dados.get("requer_fornecedor_homologado", False) else 0
    # Fase 77 — opcional (ver migrations/schema_fase77.sql), só usado para
    # agrupar produtos_acabados visualmente no Portfólio do App de Vendas;
    # string vazia vira NULL para não poluir o agrupamento com uma
    # categoria "em branco" diferente de "nenhuma categoria".
    categoria = (dados.get("categoria") or "").strip() or None
    conn = get_db()

    if not descricao:
        raise ApiError("Informe a descricao.", status=400)
    if tipo not in TIPOS_VALIDOS:
        raise ApiError(f"tipo deve ser um de: {', '.join(TIPOS_VALIDOS)}.", status=400)

    if codigo:
        # Codigo informado manualmente (ex.: importacao, ou usuario que
        # prefere controlar o proprio codigo) — comportamento inalterado
        # desde a Fase 2, mantido por compatibilidade.
        if conn.execute("SELECT id FROM itens WHERE codigo = ?", (codigo,)).fetchone():
            raise ApiError("Já existe um item com este código.", status=409)
    else:
        # Fase 23 — codigo nao informado: gera automaticamente a partir do
        # tipo, para ser usado de forma consistente em OPs, ERP e APS.
        codigo = _gerar_codigo_item(conn, tipo)

    cur = conn.execute(
        """
        INSERT INTO itens (codigo, descricao, tipo, unidade_medida, requer_analise,
                            requer_fornecedor_homologado, estoque_minimo, categoria, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (codigo, descricao, tipo, unidade_medida, requer_analise, requer_fornecedor_homologado,
         dados.get("estoque_minimo"), categoria, usuario_atual["id"]),
    )
    item_id = cur.lastrowid
    audit.registrar(conn, tabela="itens", registro_id=item_id, usuario_id=usuario_atual["id"],
                     acao="item_criado", valor_novo={"codigo": codigo, "descricao": descricao, "tipo": tipo},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.put("/<int:item_id>")
@requires_permission("itens", "editar")
def editar(item_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ApiError("Item não encontrado.", status=404)
    anterior = dict(row)

    descricao = dados.get("descricao", row["descricao"])
    estoque_minimo = dados.get("estoque_minimo", row["estoque_minimo"])
    status = dados.get("status", row["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    # Fase 70 — dados fiscais do item (exigidos para incluí-lo numa NF-e,
    # ver migrations/schema_fase70.sql); nenhum obrigatório para o cadastro
    # em si. `codigo_tributario_icms` fica em branco por padrão de
    # propósito — deixar vazio usa o CST/CSOSN neutro calculado a partir do
    # regime tributário da empresa emitente na hora de emitir (ver
    # app/nfe_service.py::_codigo_tributario_icms_padrao); só preencha aqui
    # se este item específico precisar de um código diferente do padrão.
    ncm = dados.get("ncm", row["ncm"])
    cfop_padrao = dados.get("cfop_padrao", row["cfop_padrao"])
    origem_mercadoria = dados.get("origem_mercadoria", row["origem_mercadoria"])
    if origem_mercadoria not in ("0", "1", "2", "3", "4", "5", "6", "7", "8"):
        raise ApiError("origem_mercadoria deve ser um código de 0 a 8 (Tabela de Origem da Mercadoria da NF-e).", status=400)
    cest = dados.get("cest", row["cest"])
    codigo_tributario_icms = dados.get("codigo_tributario_icms", row["codigo_tributario_icms"])
    categoria = dados.get("categoria", row["categoria"])
    if isinstance(categoria, str):
        categoria = categoria.strip() or None

    # Fase 114 — foto do produto, usada como imagem do card no Portfólio do
    # App de Vendas (ver migrations/schema_fase114.sql). Só valida/atualiza
    # quando "imagem" vem no corpo da requisição — sem a chave, mantém a
    # foto atual do item intacta (mesmo padrão de merge parcial do resto
    # deste endpoint).
    if "imagem" in dados:
        imagem = validar_imagem_base64(dados.get("imagem"))
    else:
        imagem = row["imagem"]

    conn.execute(
        """
        UPDATE itens SET descricao = ?, estoque_minimo = ?, status = ?, ncm = ?, cfop_padrao = ?,
               origem_mercadoria = ?, cest = ?, codigo_tributario_icms = ?, categoria = ?, imagem = ?,
               atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (descricao, estoque_minimo, status, ncm, cfop_padrao, origem_mercadoria, cest,
         codigo_tributario_icms, categoria, imagem, _now_iso(), usuario_atual["id"], item_id),
    )
    novo_row = conn.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    audit.registrar(conn, tabela="itens", registro_id=item_id, usuario_id=usuario_atual["id"],
                     acao="item_editado", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo_row))


# ============================================================
# Fase 153 — Galeria de mídia do item (múltiplas fotos + vídeo)
# ============================================================
# `itens.imagem` (Fase 114) continua existindo como a foto ÚNICA/capa de
# fallback — isto aqui é uma galeria PARALELA, pensada pro Portfólio do
# App de Vendas poder mostrar mais de uma foto (e um vídeo curto) por
# produto, pedido do usuário depois de ver a tela em mobile. Sem tabela
# de "setor" nem nada além do necessário: cada linha é uma mídia, `ordem`
# controla a sequência de exibição/qual foto vira capa.
def _item_ou_404(conn, item_id):
    if conn.execute("SELECT 1 FROM itens WHERE id = ?", (item_id,)).fetchone() is None:
        raise ApiError("Item não encontrado.", status=404)


@bp.get("/<int:item_id>/midias")
@requires_permission("itens", "visualizar")
def listar_midias(item_id):
    conn = get_db()
    _item_ou_404(conn, item_id)
    rows = conn.execute(
        "SELECT id, tipo, mime_tipo, conteudo, tamanho_bytes, ordem, criado_em FROM itens_midias WHERE item_id = ? ORDER BY ordem, id",
        (item_id,),
    ).fetchall()
    resultado = []
    for r in rows:
        midia = dict(r)
        # Foto é pequena (≤2MB, ver app/imagens.py) e a galeria normalmente
        # tem poucas — cabe embutir o conteúdo direto na listagem, mesmo
        # padrão já aceito em `itens.imagem`. Vídeo (até 20MB) fica de fora
        # daqui de propósito; quem for tocar/baixar busca ele sozinho em
        # GET /<item_id>/midias/<midia_id>.
        if midia["tipo"] == "video":
            midia["conteudo"] = None
        resultado.append(midia)
    return jsonify(resultado)


@bp.get("/<int:item_id>/midias/<int:midia_id>")
@requires_permission("itens", "visualizar")
def obter_midia(item_id, midia_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM itens_midias WHERE id = ? AND item_id = ?", (midia_id, item_id)).fetchone()
    if row is None:
        raise ApiError("Mídia não encontrada.", status=404)
    return jsonify(dict(row))


@bp.post("/<int:item_id>/midias")
@requires_permission("itens", "editar")
def adicionar_midia(item_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    _item_ou_404(conn, item_id)

    tipo = dados.get("tipo")
    tipo_mime, tamanho_bytes = validar_midia_galeria_item_base64(dados.get("conteudo"), tipo)

    proxima_ordem = conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) + 1 AS proxima FROM itens_midias WHERE item_id = ?", (item_id,)
    ).fetchone()["proxima"]
    cur = conn.execute(
        "INSERT INTO itens_midias (item_id, tipo, mime_tipo, conteudo, tamanho_bytes, ordem, criado_por) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item_id, tipo, tipo_mime, dados.get("conteudo"), tamanho_bytes, proxima_ordem, usuario_atual["id"]),
    )
    midia_id = cur.lastrowid
    audit.registrar(conn, tabela="itens_midias", registro_id=midia_id, usuario_id=usuario_atual["id"],
                     acao="midia_item_adicionada",
                     valor_novo={"item_id": item_id, "tipo": tipo, "mime_tipo": tipo_mime, "tamanho_bytes": tamanho_bytes},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute(
        "SELECT id, tipo, mime_tipo, tamanho_bytes, ordem, criado_em FROM itens_midias WHERE id = ?", (midia_id,)
    ).fetchone()
    return jsonify(dict(row)), 201


@bp.delete("/<int:item_id>/midias/<int:midia_id>")
@requires_permission("itens", "editar")
def remover_midia(item_id, midia_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute("SELECT * FROM itens_midias WHERE id = ? AND item_id = ?", (midia_id, item_id)).fetchone()
    if row is None:
        raise ApiError("Mídia não encontrada.", status=404)
    conn.execute("DELETE FROM itens_midias WHERE id = ?", (midia_id,))
    audit.registrar(conn, tabela="itens_midias", registro_id=midia_id, usuario_id=usuario_atual["id"],
                     acao="midia_item_removida", valor_anterior={"item_id": item_id, "tipo": row["tipo"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.put("/<int:item_id>/midias/ordem")
@requires_permission("itens", "editar")
def reordenar_midias(item_id):
    conn = get_db()
    _item_ou_404(conn, item_id)
    dados = request.get_json(silent=True) or {}
    ids_na_ordem = dados.get("ids") or []
    existentes = {r["id"] for r in conn.execute("SELECT id FROM itens_midias WHERE item_id = ?", (item_id,)).fetchall()}
    if set(ids_na_ordem) != existentes:
        raise ApiError("A lista de ids não bate com as mídias existentes deste item.", status=400)
    for posicao, midia_id in enumerate(ids_na_ordem):
        conn.execute("UPDATE itens_midias SET ordem = ? WHERE id = ?", (posicao, midia_id))
    return jsonify({"ok": True})
