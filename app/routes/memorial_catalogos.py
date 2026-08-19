"""
Fase 26 — Catálogos do Memorial Técnico ANVISA.

No sistema original (Replit) existem ~10 telas de cadastro simples
("Metodologias", "Nutrientes", "Legislações", "Alegações", "Tipos de
Produto", "Advertências", "Armazenamento", "Modo de Uso", "Justificativas",
"Referências") que alimentam seletores usados ao preencher um memorial —
em vez de digitar "Vitamina C" ou uma alegação inteira toda vez, o usuário
cadastra isso uma única vez no catálogo e escolhe de uma lista depois. A
Fase 24 (fundação do módulo) deixou esses campos como texto livre de
propósito, citando explicitamente os catálogos como o próximo passo — esta
fase entrega esse próximo passo.

Decisão de implementação: em vez de 10 tabelas quase idênticas (cada uma
só variando os nomes dos campos) e 10 conjuntos de rotas copiados e
colados, os 10 catálogos moram numa única tabela (`memorial_catalogo_itens`)
com uma coluna `catalogo` (qual dos 10) e uma coluna `dados` (JSON com os
campos daquele catálogo específico) — `ordem` e `ativo` ficam como colunas
de verdade porque são comuns a todos e usados para ordenar/filtrar. A
validação de quais campos cada catálogo aceita e quais são obrigatórios
mora em `CATALOGOS_CONFIG`, abaixo — um dicionário, não 10 blocos de código
repetidos. Isso é mais fácil de manter e de auditar do que 10 tabelas
gêmeas, ao custo de a coluna `dados` não ser consultável por SQL comum
(não é um problema aqui: nenhuma tela do sistema precisa filtrar catálogo
por um desses campos internos, só listar/criar/editar/excluir itens de um
catálogo por vez, sempre already sabendo qual).

Permissão: um recurso só, `memorial_catalogos` (visualizar/cadastrar/
editar/excluir), compartilhado pelos 10 catálogos — no sistema original
também era uma permissão só ("catalogo.editar"/"catalogo.excluir") cobrindo
todos eles.
"""
import datetime
import json

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("memorial_catalogos", __name__, url_prefix="/api/v1/memorial")

# Cada entrada de "campos" descreve um campo do catálogo:
#   obrigatorio: se ausente/vazio, a API rejeita com 400.
#   tipo "bool": convertido para 0/1 (aceita bool de verdade ou string
#     "1"/"true"/"on"/"sim", já que tanto JSON quanto FormData podem mandar
#     qualquer um dos dois).
#   default: usado só na CRIAÇÃO quando o campo não é enviado.
CATALOGOS_CONFIG = {
    "metodologias": {
        "label": "Metodologias",
        "campos": {
            "categoria": {"obrigatorio": True, "rotulo": "categoria"},
            "nome": {"obrigatorio": True, "rotulo": "nome"},
            "descricao": {"rotulo": "descrição"},
            "norma": {"rotulo": "norma"},
            "referencia": {"rotulo": "referência"},
            "principio": {"rotulo": "princípio"},
            "aplicacao": {"rotulo": "aplicação"},
        },
    },
    "nutrientes": {
        "label": "Nutrientes",
        "campos": {
            "nome": {"obrigatorio": True, "rotulo": "nome"},
            "unidade": {"default": "g", "rotulo": "unidade"},
            "dose_minima": {"rotulo": "dose mínima"},
            "dose_maxima": {"rotulo": "dose máxima"},
            "unidade_dose": {"rotulo": "unidade da dose"},
            "categoria": {"rotulo": "categoria"},
            "descricao": {"rotulo": "descrição"},
        },
    },
    "legislacoes": {
        "label": "Legislações",
        "campos": {
            "codigo": {"obrigatorio": True, "rotulo": "código"},
            "titulo": {"obrigatorio": True, "rotulo": "título"},
            "categoria": {"rotulo": "categoria"},
            "ano": {"rotulo": "ano"},
            "descricao": {"rotulo": "descrição"},
        },
    },
    "alegacoes": {
        "label": "Alegações",
        "campos": {
            "ativo_nutricional": {"obrigatorio": True, "rotulo": "ativo nutricional"},
            "alegacao": {"obrigatorio": True, "rotulo": "alegação"},
            "referencia": {"rotulo": "referência"},
            "categoria": {"rotulo": "categoria"},
        },
    },
    "tipos_produto": {
        "label": "Tipos de Produto",
        "campos": {
            "nome": {"obrigatorio": True, "rotulo": "nome"},
            "tem_capsula": {"tipo": "bool", "default": False, "rotulo": "tem cápsula"},
        },
    },
    "advertencias": {
        "label": "Advertências",
        "campos": {"texto": {"obrigatorio": True, "rotulo": "texto"}},
    },
    "armazenamento": {
        "label": "Armazenamento",
        "campos": {"texto": {"obrigatorio": True, "rotulo": "texto"}},
    },
    "modo_uso": {
        "label": "Modo de Uso",
        "campos": {
            "descricao": {"obrigatorio": True, "rotulo": "descrição"},
            "tipo": {"default": "capsula", "rotulo": "tipo"},
        },
    },
    "justificativas": {
        "label": "Justificativas",
        "campos": {
            "titulo": {"obrigatorio": True, "rotulo": "título"},
            "texto": {"obrigatorio": True, "rotulo": "texto"},
        },
    },
    "referencias": {
        "label": "Referências",
        "campos": {
            "substancia": {"obrigatorio": True, "rotulo": "substância"},
            "referencia": {"obrigatorio": True, "rotulo": "referência"},
            "descricao": {"rotulo": "descrição"},
            "tipo": {"rotulo": "tipo"},
            "auto_incluir": {"tipo": "bool", "default": False, "rotulo": "incluir automaticamente"},
        },
    },
}


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _para_bool(valor):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in ("1", "true", "on", "sim")
    return bool(valor)


def _catalogo_ou_404(catalogo):
    config = CATALOGOS_CONFIG.get(catalogo)
    if config is None:
        raise ApiError(
            f"Catálogo '{catalogo}' não existe. Catálogos disponíveis: {', '.join(CATALOGOS_CONFIG)}.",
            status=404,
        )
    return config


def _item_dict(row):
    d = dict(row)
    extra = json.loads(d.pop("dados") or "{}")
    d["ativo"] = bool(d["ativo"])
    d.update(extra)
    return d


def _item_ou_404(conn, catalogo, item_id):
    row = conn.execute(
        "SELECT * FROM memorial_catalogo_itens WHERE id = ? AND catalogo = ?", (item_id, catalogo)
    ).fetchone()
    if row is None:
        raise ApiError("Item de catálogo não encontrado.", status=404)
    return row


def _validar_e_montar_campos(config, entrada, atual=None):
    """Monta o dict que vai para a coluna `dados`, aplicando (nesta ordem,
    para cada campo do catálogo): valor enviado -> valor já existente
    (edição) -> default (criação) -> None. Campos obrigatórios vazios
    rejeitam com 400 antes de gravar qualquer coisa."""
    atual = atual or {}
    resultado = {}
    for nome_campo, regras in config["campos"].items():
        if nome_campo in entrada:
            valor = entrada[nome_campo]
        elif nome_campo in atual:
            valor = atual[nome_campo]
        else:
            valor = regras.get("default")

        if regras.get("tipo") == "bool":
            valor = _para_bool(valor)
        else:
            valor = valor.strip() if isinstance(valor, str) else valor
            if regras.get("obrigatorio") and not valor:
                raise ApiError(f"Informe {regras.get('rotulo', nome_campo)}.", status=400)
        resultado[nome_campo] = valor
    return resultado


# ---------------------------------------------------------------------------
# Metadados (lista de catálogos e seus campos, para a tela genérica)
# ---------------------------------------------------------------------------

@bp.get("/catalogos")
@requires_permission("memorial_catalogos", "visualizar")
def listar_catalogos_disponiveis():
    return jsonify(
        [
            {"chave": chave, "label": config["label"], "campos": config["campos"]}
            for chave, config in CATALOGOS_CONFIG.items()
        ]
    )


# ---------------------------------------------------------------------------
# Itens de um catálogo
# ---------------------------------------------------------------------------

@bp.get("/catalogos/<catalogo>")
@requires_permission("memorial_catalogos", "visualizar")
def listar_itens_catalogo(catalogo):
    _catalogo_ou_404(catalogo)
    conn = get_db()
    query = "SELECT * FROM memorial_catalogo_itens WHERE catalogo = ?"
    params = [catalogo]
    if request.args.get("incluir_inativos") != "1":
        query += " AND ativo = 1"
    query += " ORDER BY ordem, id"
    rows = conn.execute(query, params).fetchall()
    return jsonify([_item_dict(r) for r in rows])


@bp.get("/catalogos/<catalogo>/<int:item_id>")
@requires_permission("memorial_catalogos", "visualizar")
def obter_item_catalogo(catalogo, item_id):
    _catalogo_ou_404(catalogo)
    conn = get_db()
    return jsonify(_item_dict(_item_ou_404(conn, catalogo, item_id)))


@bp.post("/catalogos/<catalogo>")
@requires_permission("memorial_catalogos", "cadastrar")
def criar_item_catalogo(catalogo):
    usuario_atual = g.usuario_atual
    config = _catalogo_ou_404(catalogo)
    entrada = request.get_json(silent=True) or {}
    campos = _validar_e_montar_campos(config, entrada)

    try:
        ordem = int(entrada.get("ordem", 0) or 0)
    except (TypeError, ValueError):
        raise ApiError("ordem deve ser um número inteiro.", status=400)

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO memorial_catalogo_itens (catalogo, ordem, dados, criado_por, atualizado_por) VALUES (?, ?, ?, ?, ?)",
        (catalogo, ordem, json.dumps(campos, ensure_ascii=False), usuario_atual["id"], usuario_atual["id"]),
    )
    item_id = cur.lastrowid
    audit.registrar(
        conn, tabela="memorial_catalogo_itens", registro_id=item_id, usuario_id=usuario_atual["id"],
        acao="catalogo_item_criado", valor_novo={"catalogo": catalogo, "ordem": ordem, **campos},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_item_dict(_item_ou_404(conn, catalogo, item_id))), 201


@bp.put("/catalogos/<catalogo>/<int:item_id>")
@requires_permission("memorial_catalogos", "editar")
def editar_item_catalogo(catalogo, item_id):
    usuario_atual = g.usuario_atual
    config = _catalogo_ou_404(catalogo)
    conn = get_db()
    item = _item_ou_404(conn, catalogo, item_id)
    atual = _item_dict(item)
    entrada = request.get_json(silent=True) or {}
    campos = _validar_e_montar_campos(config, entrada, atual=atual)

    try:
        ordem = int(entrada.get("ordem", atual.get("ordem", 0)) or 0)
    except (TypeError, ValueError):
        raise ApiError("ordem deve ser um número inteiro.", status=400)
    ativo = _para_bool(entrada.get("ativo", atual.get("ativo", True)))

    conn.execute(
        """
        UPDATE memorial_catalogo_itens
        SET ordem = ?, ativo = ?, dados = ?, atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (ordem, 1 if ativo else 0, json.dumps(campos, ensure_ascii=False), _now_iso(), usuario_atual["id"], item_id),
    )
    audit.registrar(
        conn, tabela="memorial_catalogo_itens", registro_id=item_id, usuario_id=usuario_atual["id"],
        acao="catalogo_item_editado", valor_anterior=atual,
        valor_novo={"catalogo": catalogo, "ordem": ordem, "ativo": ativo, **campos},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_item_dict(_item_ou_404(conn, catalogo, item_id)))


@bp.delete("/catalogos/<catalogo>/<int:item_id>")
@requires_permission("memorial_catalogos", "excluir")
def excluir_item_catalogo(catalogo, item_id):
    usuario_atual = g.usuario_atual
    _catalogo_ou_404(catalogo)
    conn = get_db()
    item = _item_ou_404(conn, catalogo, item_id)
    valor_anterior = _item_dict(item)
    conn.execute("DELETE FROM memorial_catalogo_itens WHERE id = ?", (item_id,))
    audit.registrar(
        conn, tabela="memorial_catalogo_itens", registro_id=item_id, usuario_id=usuario_atual["id"],
        acao="catalogo_item_excluido", valor_anterior=valor_anterior,
        ip=client_ip(), dispositivo=client_device(),
    )
    return "", 204
