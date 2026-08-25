"""
Fase 24 — Memorial Técnico ANVISA (Fundação).

Módulo novo, reconstruído na tecnologia do resto do sistema (Flask/SQLite/
JSON) a partir de um sistema separado (Node.js/React/Postgres, no Replit)
que o cliente já usava para gerar o Memorial Técnico exigido pela ANVISA no
registro/notificação de suplementos alimentares: um documento por produto
reunindo composição nutricional, alegações, justificativas técnicas,
métodos analíticos, plano de estudo de estabilidade acelerada, ensaios
microbiológicos, referências bibliográficas e a conclusão técnica.

Três recursos, um blueprint só (mesmo padrão de `comercial.py`):
  - `memorial_empresas` — o cliente/marca para quem o memorial é feito.
    NÃO é a mesma coisa que `empresas` (Fase 1, unidades/CNPJs da própria
    Alphafitus) — nome deliberadamente diferente para nunca colidir.
  - `memorial_produtos` — produtos de uma `memorial_empresa`.
  - `memoriais` — o documento em si, com fluxo de status (rascunho →
    em_andamento → em_revisao → concluido → aprovado, ou reprovado a
    qualquer momento), assinaturas (2 assinaturas com o memorial
    "concluido" aprovam automaticamente) e um histórico narrativo próprio.
"""
import datetime
import re

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("memorial", __name__, url_prefix="/api/v1/memorial")

STATUS_VALIDOS = ("rascunho", "em_andamento", "em_revisao", "concluido", "aprovado", "reprovado")
STATUS_LABELS = {
    "rascunho": "Rascunho",
    "em_andamento": "Em Andamento",
    "em_revisao": "Em Revisão",
    "concluido": "Concluído",
    "aprovado": "Aprovado",
    "reprovado": "Reprovado",
}

# Campos de conteúdo do memorial que podem ser criados/editados por
# `POST /memoriais` e `PUT /memoriais/<id>` — mantidos numa lista só para
# não repetir os mesmos ~35 nomes três vezes (INSERT, UPDATE e validação).
CAMPOS_MEMORIAL = (
    "objetivo", "composicao_nutricional", "lista_ingredientes", "alegacoes",
    "justificativas_tecnicas", "metodos_analiticos", "estabilidade_acelerada",
    "ensaios_microbiologicos", "calculos_nutricionais", "legislacao_aplicavel",
    "observacoes", "conclusao", "referencias_bibliograficas", "composicao_centesimal",
    "calculo_quantidade", "metodologias_aplicadas", "tipo_produto", "tipo_pote",
    "ingredientes_ativos", "excipientes", "composicao_capsula", "temperatura",
    "umidade_relativa", "periodo_estudo", "intervalos_teste", "advertencias",
    "armazenamento", "modo_uso", "elaborado_por", "aprovado_por", "laudo_emitido_por",
    "analista_senior", "email_rt", "email_analista_senior", "observacao_analista",
    "data_emissao",
)


def _numero_assinaturas_aprovacao(conn):
    """Fase 49 — quantas assinaturas um memorial 'concluido' precisa
    acumular para ser promovido automaticamente a 'aprovado'. Era o
    literal `2` fixo no Python; agora vem da linha única de configuração
    (`configuracoes_memorial`), editável pela tela de Administração. O
    valor padrão (2) preserva o comportamento de sempre caso a linha não
    exista por algum motivo (defensivo — a migration da Fase 49 já semeia
    a linha em todo banco novo ou atualizado)."""
    row = conn.execute("SELECT numero_assinaturas_aprovacao FROM configuracoes_memorial WHERE id = 1").fetchone()
    return row["numero_assinaturas_aprovacao"] if row else 2


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _registrar_historico(conn, memorial_id, acao, descricao=None, usuario=None):
    conn.execute(
        "INSERT INTO memorial_historico (memorial_id, usuario_id, usuario_nome, acao, descricao) "
        "VALUES (?, ?, ?, ?, ?)",
        (memorial_id, usuario["id"] if usuario else None,
         usuario["nome"] if usuario else "Sistema", acao, descricao),
    )


# ===========================================================================
# EMPRESAS (do Memorial Técnico)
# ===========================================================================

@bp.get("/empresas")
@requires_permission("memorial_empresas", "visualizar")
def listar_empresas():
    conn = get_db()
    rows = conn.execute("SELECT * FROM memorial_empresas ORDER BY nome_fantasia").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/empresas/<int:empresa_id>")
@requires_permission("memorial_empresas", "visualizar")
def obter_empresa(empresa_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM memorial_empresas WHERE id = ?", (empresa_id,)).fetchone()
    if row is None:
        raise ApiError("Empresa não encontrada.", status=404)
    return jsonify(dict(row))


@bp.post("/empresas")
@requires_permission("memorial_empresas", "cadastrar")
def criar_empresa():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome_fantasia = (dados.get("nome_fantasia") or "").strip()
    razao_social = (dados.get("razao_social") or "").strip()
    cnpj = (dados.get("cnpj") or "").strip()
    conn = get_db()

    if not nome_fantasia or not razao_social or not cnpj:
        raise ApiError("Informe nome_fantasia, razao_social e cnpj.", status=400)
    if conn.execute("SELECT id FROM memorial_empresas WHERE cnpj = ?", (cnpj,)).fetchone():
        raise ApiError("Já existe uma empresa com este CNPJ.", status=409)

    cur = conn.execute(
        """
        INSERT INTO memorial_empresas (nome_fantasia, razao_social, cnpj, ie, responsavel_tecnico,
                                        crf, endereco, cidade, estado, cep, telefone, email,
                                        telefone_contato, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (nome_fantasia, razao_social, cnpj, dados.get("ie"), dados.get("responsavel_tecnico"),
         dados.get("crf"), dados.get("endereco"), dados.get("cidade"), dados.get("estado"),
         dados.get("cep"), dados.get("telefone"), dados.get("email"),
         dados.get("telefone_contato"), usuario_atual["id"]),
    )
    empresa_id = cur.lastrowid
    audit.registrar(conn, tabela="memorial_empresas", registro_id=empresa_id, usuario_id=usuario_atual["id"],
                     acao="memorial_empresa_criada", valor_novo={"nome_fantasia": nome_fantasia, "cnpj": cnpj},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM memorial_empresas WHERE id = ?", (empresa_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.put("/empresas/<int:empresa_id>")
@requires_permission("memorial_empresas", "editar")
def editar_empresa(empresa_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM memorial_empresas WHERE id = ?", (empresa_id,)).fetchone()
    if row is None:
        raise ApiError("Empresa não encontrada.", status=404)
    anterior = dict(row)

    status = dados.get("status", row["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    campos = ("nome_fantasia", "razao_social", "ie", "responsavel_tecnico", "crf", "endereco",
              "cidade", "estado", "cep", "telefone", "email", "telefone_contato")
    valores = {c: dados.get(c, row[c]) for c in campos}
    if not (valores["nome_fantasia"] or "").strip() or not (valores["razao_social"] or "").strip():
        raise ApiError("nome_fantasia e razao_social não podem ficar em branco.", status=400)

    conn.execute(
        """
        UPDATE memorial_empresas
        SET nome_fantasia = ?, razao_social = ?, ie = ?, responsavel_tecnico = ?, crf = ?,
            endereco = ?, cidade = ?, estado = ?, cep = ?, telefone = ?, email = ?,
            telefone_contato = ?, status = ?, atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (valores["nome_fantasia"], valores["razao_social"], valores["ie"], valores["responsavel_tecnico"],
         valores["crf"], valores["endereco"], valores["cidade"], valores["estado"], valores["cep"],
         valores["telefone"], valores["email"], valores["telefone_contato"],
         status, _now_iso(), usuario_atual["id"], empresa_id),
    )
    novo_row = conn.execute("SELECT * FROM memorial_empresas WHERE id = ?", (empresa_id,)).fetchone()
    audit.registrar(conn, tabela="memorial_empresas", registro_id=empresa_id, usuario_id=usuario_atual["id"],
                     acao="memorial_empresa_editada", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo_row))


# ===========================================================================
# PRODUTOS (do Memorial Técnico)
# ===========================================================================

CAMPOS_PRODUTO = (
    "ingredientes_ativos", "excipientes", "embalagem", "advertencias", "modo_de_uso",
    "armazenamento", "quantidade_capsulas_totais", "peso_liquido", "tamanho_capsulas",
    "tipo_capsulas", "tipo_produto", "referencias_comerciais", "comprimento_rotulo",
    "largura_rotulo", "tamanho_pote", "tamanho_capsula", "numero_protocolo_anvisa",
    # Fase 115 — "sabor" (produtosTable.sabor no sistema original), único
    # campo de produto que faltava para paridade.
    "sabor",
)


def _empresa_ou_404(conn, empresa_id):
    row = conn.execute("SELECT * FROM memorial_empresas WHERE id = ?", (empresa_id,)).fetchone()
    if row is None:
        raise ApiError("Empresa não encontrada.", status=404)
    return dict(row)


@bp.get("/produtos")
@requires_permission("memorial_produtos", "visualizar")
def listar_produtos():
    conn = get_db()
    empresa_id = request.args.get("empresa_id")
    if empresa_id:
        rows = conn.execute(
            "SELECT * FROM memorial_produtos WHERE empresa_id = ? ORDER BY nome", (empresa_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM memorial_produtos ORDER BY nome").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/produtos/<int:produto_id>")
@requires_permission("memorial_produtos", "visualizar")
def obter_produto(produto_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM memorial_produtos WHERE id = ?", (produto_id,)).fetchone()
    if row is None:
        raise ApiError("Produto não encontrado.", status=404)
    return jsonify(dict(row))


@bp.post("/produtos")
@requires_permission("memorial_produtos", "cadastrar")
def criar_produto():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    empresa_id = dados.get("empresa_id")
    nome = (dados.get("nome") or "").strip()
    categoria = (dados.get("categoria") or "").strip()
    forma_farmaceutica = (dados.get("forma_farmaceutica") or "").strip()
    porcao_gramas = dados.get("porcao_gramas")
    quantidade_porcoes = dados.get("quantidade_porcoes")

    if not empresa_id or not nome or not categoria or not forma_farmaceutica:
        raise ApiError("Informe empresa_id, nome, categoria e forma_farmaceutica.", status=400)
    if porcao_gramas is None or quantidade_porcoes is None:
        raise ApiError("Informe porcao_gramas e quantidade_porcoes.", status=400)
    try:
        porcao_gramas = float(porcao_gramas)
        quantidade_porcoes = int(quantidade_porcoes)
    except (TypeError, ValueError):
        raise ApiError("porcao_gramas deve ser numérico e quantidade_porcoes deve ser inteiro.", status=400)
    if porcao_gramas <= 0 or quantidade_porcoes <= 0:
        raise ApiError("porcao_gramas e quantidade_porcoes devem ser maiores que zero.", status=400)
    _empresa_ou_404(conn, empresa_id)

    valores = {c: dados.get(c) for c in CAMPOS_PRODUTO}
    cur = conn.execute(
        f"""
        INSERT INTO memorial_produtos (empresa_id, nome, categoria, forma_farmaceutica, porcao_gramas,
                                        quantidade_porcoes, {", ".join(CAMPOS_PRODUTO)}, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" for _ in CAMPOS_PRODUTO)}, ?)
        """,
        (empresa_id, nome, categoria, forma_farmaceutica, porcao_gramas, quantidade_porcoes,
         *[valores[c] for c in CAMPOS_PRODUTO], usuario_atual["id"]),
    )
    produto_id = cur.lastrowid
    audit.registrar(conn, tabela="memorial_produtos", registro_id=produto_id, usuario_id=usuario_atual["id"],
                     acao="memorial_produto_criado", valor_novo={"nome": nome, "empresa_id": empresa_id},
                     ip=client_ip(), dispositivo=client_device())
    row = conn.execute("SELECT * FROM memorial_produtos WHERE id = ?", (produto_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.put("/produtos/<int:produto_id>")
@requires_permission("memorial_produtos", "editar")
def editar_produto(produto_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM memorial_produtos WHERE id = ?", (produto_id,)).fetchone()
    if row is None:
        raise ApiError("Produto não encontrado.", status=404)
    anterior = dict(row)

    status = dados.get("status", row["status"])
    if status not in ("ativo", "inativo"):
        raise ApiError("status deve ser 'ativo' ou 'inativo'.", status=400)

    nome = (dados.get("nome", row["nome"]) or "").strip()
    categoria = (dados.get("categoria", row["categoria"]) or "").strip()
    forma_farmaceutica = (dados.get("forma_farmaceutica", row["forma_farmaceutica"]) or "").strip()
    if not nome or not categoria or not forma_farmaceutica:
        raise ApiError("nome, categoria e forma_farmaceutica não podem ficar em branco.", status=400)

    porcao_gramas = dados.get("porcao_gramas", row["porcao_gramas"])
    quantidade_porcoes = dados.get("quantidade_porcoes", row["quantidade_porcoes"])
    try:
        porcao_gramas = float(porcao_gramas)
        quantidade_porcoes = int(quantidade_porcoes)
    except (TypeError, ValueError):
        raise ApiError("porcao_gramas deve ser numérico e quantidade_porcoes deve ser inteiro.", status=400)

    valores = {c: dados.get(c, row[c]) for c in CAMPOS_PRODUTO}
    conn.execute(
        f"""
        UPDATE memorial_produtos
        SET nome = ?, categoria = ?, forma_farmaceutica = ?, porcao_gramas = ?, quantidade_porcoes = ?,
            {", ".join(f"{c} = ?" for c in CAMPOS_PRODUTO)},
            status = ?, atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (nome, categoria, forma_farmaceutica, porcao_gramas, quantidade_porcoes,
         *[valores[c] for c in CAMPOS_PRODUTO], status, _now_iso(), usuario_atual["id"], produto_id),
    )
    novo_row = conn.execute("SELECT * FROM memorial_produtos WHERE id = ?", (produto_id,)).fetchone()
    audit.registrar(conn, tabela="memorial_produtos", registro_id=produto_id, usuario_id=usuario_atual["id"],
                     acao="memorial_produto_editado", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(dict(novo_row))


# ===========================================================================
# MEMORIAIS (o documento)
# ===========================================================================

_RE_SEQ = re.compile(r"/(\d+)$")


def _extrair_seq(valor):
    if not valor:
        return 0
    m = _RE_SEQ.search(valor)
    return int(m.group(1)) if m else 0


def _proximo_seq_certificado(conn):
    """Maior sequência NNN já usada, em QUALQUER memorial, olhando tanto
    `codigo` quanto `numero_certificado` (para nunca repetir um número
    mesmo que alguém tenha digitado um valor manual alto) — mesma lógica
    do sistema original que este módulo reconstrói."""
    rows = conn.execute("SELECT codigo, numero_certificado FROM memoriais").fetchall()
    maior = 0
    for row in rows:
        s1 = _extrair_seq(row["codigo"])
        s2 = _extrair_seq(row["numero_certificado"])
        maior = max(maior, s1, s2)
    return maior + 1


def _formatar_certificado(seq):
    agora = datetime.datetime.utcnow()
    return f"CERT-AF-{agora.strftime('%Y%m%d')}/{seq:03d}"


@bp.get("/memoriais/gerar-certificado")
@requires_permission("memoriais", "visualizar")
def gerar_certificado_preview():
    conn = get_db()
    seq = _proximo_seq_certificado(conn)
    return jsonify({"numero_certificado": _formatar_certificado(seq), "seq": seq})


def _produto_ou_404(conn, produto_id):
    row = conn.execute("SELECT * FROM memorial_produtos WHERE id = ?", (produto_id,)).fetchone()
    if row is None:
        raise ApiError("Produto não encontrado.", status=404)
    return dict(row)


# As mesmas 10 seções de conteúdo usadas pelo sistema original (Replit)
# para calcular o "quanto falta" de um memorial — replicado aqui campo a
# campo a partir de `lib/memorial-progresso.ts` do sistema original, só
# trocando os nomes de campo para os desta implementação (mesmo
# significado). Um valor sempre RECALCULADO na hora a partir do conteúdo
# do memorial, nunca guardado — mesmo princípio de "nunca armazenar um
# derivado" já usado em outros módulos (ex.: percentual de perda da
# Fase 9). Enquanto os editores estruturados do original (composição
# centesimal em linhas, metodologias selecionadas etc. — catálogos ainda
# não portados) não existem aqui, cada seção conta como "preenchida"
# quando o campo de texto correspondente não está vazio; a checagem fica
# mais específica automaticamente quando esses editores forem portados.
SECOES_PROGRESSO_MEMORIAL = (
    ("Objetivo", "objetivo"),
    ("Composição Centesimal", "composicao_centesimal"),
    ("Dosagem", "calculo_quantidade"),
    ("Estabilidade", "estabilidade_acelerada"),
    ("Ensaios Microbiológicos", "ensaios_microbiologicos"),
    ("Composição Nutricional", "composicao_nutricional"),
    ("Metodologias", "metodologias_aplicadas"),
    ("Legislação", "legislacao_aplicavel"),
    ("Conclusão Técnica", "conclusao"),
    ("Referências", "referencias_bibliograficas"),
)


def _progresso_memorial(memorial):
    if memorial["status"] in ("concluido", "aprovado"):
        return {"pct": 100, "faltando": [], "secoes": [{"nome": n, "ok": True} for n, _ in SECOES_PROGRESSO_MEMORIAL]}

    secoes = [{"nome": nome, "ok": bool((memorial.get(campo) or "").strip())} for nome, campo in SECOES_PROGRESSO_MEMORIAL]
    feitas = sum(1 for s in secoes if s["ok"])
    pct = round(feitas / len(secoes) * 100) if secoes else 0
    faltando = [s["nome"] for s in secoes if not s["ok"]]
    return {"pct": pct, "faltando": faltando, "secoes": secoes}


def _memorial_com_assinaturas(conn, memorial_id):
    row = conn.execute(
        """
        SELECT m.*, p.nome AS produto_nome, e.nome_fantasia AS empresa_nome
        FROM memoriais m
        JOIN memorial_produtos p ON p.id = m.produto_id
        JOIN memorial_empresas e ON e.id = p.empresa_id
        WHERE m.id = ?
        """,
        (memorial_id,),
    ).fetchone()
    if row is None:
        return None
    memorial = dict(row)
    total = conn.execute(
        "SELECT COUNT(*) AS total FROM memorial_assinaturas WHERE memorial_id = ?", (memorial_id,)
    ).fetchone()["total"]
    memorial["assinaturas_count"] = total
    memorial["assinaturas_pendentes"] = total < _numero_assinaturas_aprovacao(conn)
    memorial["progresso"] = _progresso_memorial(memorial)
    return memorial


@bp.get("/memoriais")
@requires_permission("memoriais", "visualizar")
def listar_memoriais():
    conn = get_db()
    produto_id = request.args.get("produto_id")
    status = request.args.get("status")
    clausulas, params = [], []
    if produto_id:
        clausulas.append("produto_id = ?")
        params.append(produto_id)
    if status:
        clausulas.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(f"SELECT id FROM memoriais {where} ORDER BY criado_em DESC", params).fetchall()
    memoriais = [_memorial_com_assinaturas(conn, r["id"]) for r in rows]
    return jsonify(memoriais)


@bp.post("/memoriais")
@requires_permission("memoriais", "cadastrar")
def criar_memorial():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    produto_id = dados.get("produto_id")
    data_inicio = dados.get("data_inicio")
    data_fim = dados.get("data_fim")
    if not produto_id or not data_inicio or not data_fim:
        raise ApiError("Informe produto_id, data_inicio e data_fim.", status=400)
    _produto_ou_404(conn, produto_id)

    numero_certificado = (dados.get("numero_certificado") or "").strip()
    if numero_certificado:
        existente = conn.execute(
            "SELECT id, codigo FROM memoriais WHERE numero_certificado = ?", (numero_certificado,)
        ).fetchone()
        if existente:
            raise ApiError(
                f"Já existe um memorial com o Número de Certificado \"{numero_certificado}\" "
                f"(código {existente['codigo']}). Revise o número antes de continuar.",
                status=409,
            )
    else:
        numero_certificado = _formatar_certificado(_proximo_seq_certificado(conn))
    codigo = numero_certificado

    valores = {c: dados.get(c) for c in CAMPOS_MEMORIAL}
    cur = conn.execute(
        f"""
        INSERT INTO memoriais (produto_id, codigo, numero_certificado, status, data_inicio, data_fim,
                                {", ".join(CAMPOS_MEMORIAL)}, criado_por)
        VALUES (?, ?, ?, 'rascunho', ?, ?, {", ".join("?" for _ in CAMPOS_MEMORIAL)}, ?)
        """,
        (produto_id, codigo, numero_certificado, data_inicio, data_fim,
         *[valores[c] for c in CAMPOS_MEMORIAL], usuario_atual["id"]),
    )
    memorial_id = cur.lastrowid
    _registrar_historico(conn, memorial_id, "Memorial criado", f"Código: {codigo}", usuario_atual)
    audit.registrar(conn, tabela="memoriais", registro_id=memorial_id, usuario_id=usuario_atual["id"],
                     acao="memorial_criado", valor_novo={"codigo": codigo, "produto_id": produto_id},
                     ip=client_ip(), dispositivo=client_device())
    memorial = _memorial_com_assinaturas(conn, memorial_id)
    return jsonify(memorial), 201


@bp.get("/memoriais/<int:memorial_id>")
@requires_permission("memoriais", "visualizar")
def obter_memorial(memorial_id):
    conn = get_db()
    memorial = _memorial_com_assinaturas(conn, memorial_id)
    if memorial is None:
        raise ApiError("Memorial não encontrado.", status=404)
    return jsonify(memorial)


@bp.put("/memoriais/<int:memorial_id>")
@requires_permission("memoriais", "editar")
def editar_memorial(memorial_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    if row is None:
        raise ApiError("Memorial não encontrado.", status=404)
    anterior = dict(row)

    data_inicio = dados.get("data_inicio", row["data_inicio"])
    data_fim = dados.get("data_fim", row["data_fim"])
    if not data_inicio or not data_fim:
        raise ApiError("data_inicio e data_fim não podem ficar em branco.", status=400)

    numero_certificado = row["numero_certificado"]
    codigo = row["codigo"]
    if "numero_certificado" in dados and dados["numero_certificado"]:
        novo_numero = dados["numero_certificado"].strip()
        if novo_numero and novo_numero != numero_certificado:
            existente = conn.execute(
                "SELECT id FROM memoriais WHERE numero_certificado = ? AND id != ?", (novo_numero, memorial_id)
            ).fetchone()
            if existente:
                raise ApiError("Já existe outro memorial com este Número de Certificado.", status=409)
            numero_certificado = novo_numero
            codigo = novo_numero

    valores = {c: dados.get(c, row[c]) for c in CAMPOS_MEMORIAL}
    conn.execute(
        f"""
        UPDATE memoriais
        SET data_inicio = ?, data_fim = ?, numero_certificado = ?, codigo = ?,
            {", ".join(f"{c} = ?" for c in CAMPOS_MEMORIAL)},
            atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (data_inicio, data_fim, numero_certificado, codigo,
         *[valores[c] for c in CAMPOS_MEMORIAL], _now_iso(), usuario_atual["id"], memorial_id),
    )
    _registrar_historico(conn, memorial_id, "Memorial atualizado", "Conteúdo do memorial editado e salvo", usuario_atual)
    novo_row = conn.execute("SELECT * FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    audit.registrar(conn, tabela="memoriais", registro_id=memorial_id, usuario_id=usuario_atual["id"],
                     acao="memorial_editado", valor_anterior=anterior, valor_novo=dict(novo_row),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_memorial_com_assinaturas(conn, memorial_id))


@bp.delete("/memoriais/<int:memorial_id>")
@requires_permission("memoriais", "excluir")
def excluir_memorial(memorial_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute("SELECT * FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    if row is None:
        raise ApiError("Memorial não encontrado.", status=404)
    if row["status"] != "rascunho":
        raise ApiError(
            "Só é possível excluir um memorial ainda em rascunho. "
            "Memoriais que já avançaram no fluxo fazem parte do histórico de conformidade e não podem ser apagados.",
            status=409,
        )
    conn.execute("DELETE FROM memorial_assinaturas WHERE memorial_id = ?", (memorial_id,))
    conn.execute("DELETE FROM memorial_historico WHERE memorial_id = ?", (memorial_id,))
    conn.execute("DELETE FROM memoriais WHERE id = ?", (memorial_id,))
    audit.registrar(conn, tabela="memoriais", registro_id=memorial_id, usuario_id=usuario_atual["id"],
                     acao="memorial_excluido", valor_anterior=dict(row),
                     ip=client_ip(), dispositivo=client_device())
    return "", 204


def _tentar_auto_aprovar(conn, memorial_id, usuario_atual):
    """Se o memorial estiver 'concluido' e já tiver assinaturas suficientes
    (Fase 49: configurável pela tela, padrão 2 — mesma regra do sistema
    original), promove o status para 'aprovado' automaticamente e
    registra no histórico."""
    row = conn.execute("SELECT status FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    if row is None or row["status"] != "concluido":
        return
    minimo = _numero_assinaturas_aprovacao(conn)
    total = conn.execute(
        "SELECT COUNT(*) AS total FROM memorial_assinaturas WHERE memorial_id = ?", (memorial_id,)
    ).fetchone()["total"]
    if total < minimo:
        return
    conn.execute(
        "UPDATE memoriais SET status = 'aprovado', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"] if usuario_atual else None, memorial_id),
    )
    _registrar_historico(
        conn, memorial_id, "Aprovação automática",
        f"Memorial promovido para Aprovado: status Concluído + {minimo} assinatura(s) confirmada(s).", None,
    )


@bp.post("/memoriais/<int:memorial_id>/status")
@requires_permission("memoriais", "concluir")
def alterar_status_memorial(memorial_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    if row is None:
        raise ApiError("Memorial não encontrado.", status=404)

    novo_status = dados.get("status")
    if novo_status not in STATUS_VALIDOS:
        raise ApiError(f"status deve ser um de: {', '.join(STATUS_VALIDOS)}.", status=400)

    conn.execute(
        "UPDATE memoriais SET status = ?, atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (novo_status, _now_iso(), usuario_atual["id"], memorial_id),
    )
    label = STATUS_LABELS.get(novo_status, novo_status)
    _registrar_historico(conn, memorial_id, "Status alterado", f"Status alterado para: {label}", usuario_atual)
    audit.registrar(conn, tabela="memoriais", registro_id=memorial_id, usuario_id=usuario_atual["id"],
                     acao="memorial_status_alterado", valor_anterior={"status": row["status"]},
                     valor_novo={"status": novo_status}, ip=client_ip(), dispositivo=client_device())

    _tentar_auto_aprovar(conn, memorial_id, usuario_atual)
    return jsonify(_memorial_com_assinaturas(conn, memorial_id))


# ===========================================================================
# ASSINATURAS
# ===========================================================================

@bp.get("/memoriais/<int:memorial_id>/assinaturas")
@requires_permission("memoriais", "visualizar")
def listar_assinaturas(memorial_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memorial_assinaturas WHERE memorial_id = ? ORDER BY assinado_em", (memorial_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/memoriais/<int:memorial_id>/assinaturas")
@requires_permission("memoriais", "assinar")
def assinar_memorial(memorial_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    memorial = conn.execute("SELECT id FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    if memorial is None:
        raise ApiError("Memorial não encontrado.", status=404)

    if conn.execute(
        "SELECT id FROM memorial_assinaturas WHERE memorial_id = ? AND usuario_id = ?",
        (memorial_id, usuario_atual["id"]),
    ).fetchone():
        raise ApiError("Você já assinou este memorial.", status=409)

    cargo = (dados.get("cargo") or "").strip() or "Responsável"
    partes = usuario_atual["nome"].strip().split()
    if len(partes) >= 2:
        iniciais = (partes[0][0] + partes[-1][0]).upper()
    else:
        iniciais = (partes[0][0] if partes else "?").upper()

    cur = conn.execute(
        "INSERT INTO memorial_assinaturas (memorial_id, usuario_id, nome, cargo, iniciais) VALUES (?, ?, ?, ?, ?)",
        (memorial_id, usuario_atual["id"], usuario_atual["nome"], cargo, iniciais),
    )
    assinatura_id = cur.lastrowid
    _registrar_historico(conn, memorial_id, "Assinatura registrada",
                          f"{usuario_atual['nome']} assinou como: {cargo}", usuario_atual)
    audit.registrar(conn, tabela="memorial_assinaturas", registro_id=assinatura_id, usuario_id=usuario_atual["id"],
                     acao="memorial_assinado", valor_novo={"memorial_id": memorial_id, "cargo": cargo},
                     ip=client_ip(), dispositivo=client_device())

    _tentar_auto_aprovar(conn, memorial_id, usuario_atual)
    row = conn.execute("SELECT * FROM memorial_assinaturas WHERE id = ?", (assinatura_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp.delete("/memoriais/<int:memorial_id>/assinaturas/<int:assinatura_id>")
@requires_permission("memoriais", "excluir")
def remover_assinatura(memorial_id, assinatura_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM memorial_assinaturas WHERE id = ? AND memorial_id = ?", (assinatura_id, memorial_id)
    ).fetchone()
    if row is None:
        raise ApiError("Assinatura não encontrada.", status=404)
    conn.execute("DELETE FROM memorial_assinaturas WHERE id = ?", (assinatura_id,))
    _registrar_historico(conn, memorial_id, "Assinatura removida",
                          f"Assinatura de {row['nome']} ({row['cargo']}) removida", usuario_atual)
    audit.registrar(conn, tabela="memorial_assinaturas", registro_id=assinatura_id, usuario_id=usuario_atual["id"],
                     acao="memorial_assinatura_removida", valor_anterior=dict(row),
                     ip=client_ip(), dispositivo=client_device())
    return "", 204


# ===========================================================================
# HISTÓRICO E PAINEL
# ===========================================================================

@bp.get("/memoriais/<int:memorial_id>/historico")
@requires_permission("memoriais", "visualizar")
def historico_memorial(memorial_id):
    conn = get_db()
    if conn.execute("SELECT id FROM memoriais WHERE id = ?", (memorial_id,)).fetchone() is None:
        raise ApiError("Memorial não encontrado.", status=404)
    rows = conn.execute(
        "SELECT * FROM memorial_historico WHERE memorial_id = ? ORDER BY id DESC", (memorial_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/dashboard")
@requires_permission("memoriais", "visualizar")
def dashboard():
    conn = get_db()
    total_memoriais = conn.execute("SELECT COUNT(*) AS total FROM memoriais").fetchone()["total"]
    total_produtos = conn.execute("SELECT COUNT(*) AS total FROM memorial_produtos").fetchone()["total"]
    total_empresas = conn.execute("SELECT COUNT(*) AS total FROM memorial_empresas").fetchone()["total"]

    contagem_status = {
        row["status"]: row["total"]
        for row in conn.execute("SELECT status, COUNT(*) AS total FROM memoriais GROUP BY status").fetchall()
    }
    minimo_assinaturas = _numero_assinaturas_aprovacao(conn)
    pendentes = conn.execute(
        """
        SELECT COUNT(*) AS total FROM (
            SELECT m.id, COUNT(a.id) AS assinaturas
            FROM memoriais m
            LEFT JOIN memorial_assinaturas a ON a.memorial_id = m.id
            GROUP BY m.id
            HAVING assinaturas < ?
        )
        """,
        (minimo_assinaturas,),
    ).fetchone()["total"]

    # "Progresso dos Documentos": memoriais ainda não finalizados
    # (aprovado/reprovado são estados terminais), ordenados pelos que
    # precisam de mais atenção primeiro (progresso mais baixo) — mesmo
    # critério do painel original. Limitado a 8 para o próprio painel; a
    # lista completa continua disponível em GET /memoriais.
    em_andamento_ids = conn.execute(
        "SELECT id FROM memoriais WHERE status NOT IN ('aprovado', 'reprovado') ORDER BY criado_em DESC"
    ).fetchall()
    documentos_progresso = sorted(
        (_memorial_com_assinaturas(conn, r["id"]) for r in em_andamento_ids),
        key=lambda m: m["progresso"]["pct"],
    )[:8]

    return jsonify({
        "total_memoriais": total_memoriais,
        "total_produtos": total_produtos,
        "total_empresas": total_empresas,
        "memoriais_rascunho": contagem_status.get("rascunho", 0),
        "memoriais_em_andamento": contagem_status.get("em_andamento", 0),
        "memoriais_em_revisao": contagem_status.get("em_revisao", 0),
        "memoriais_concluidos": contagem_status.get("concluido", 0),
        "memoriais_aprovados": contagem_status.get("aprovado", 0),
        "memoriais_reprovados": contagem_status.get("reprovado", 0),
        "memoriais_assinaturas_pendentes": pendentes,
        "documentos_progresso": [
            {
                "id": m["id"], "codigo": m["codigo"], "numero_certificado": m["numero_certificado"],
                "produto_nome": m["produto_nome"], "status": m["status"], "progresso": m["progresso"],
            }
            for m in documentos_progresso
        ],
    })
