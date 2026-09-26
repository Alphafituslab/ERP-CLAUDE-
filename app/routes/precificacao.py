"""
Fase 212 — Precificação (cálculo de rentabilidade e custo).

Ver `app/precificacao_service.py` pra fórmula completa, a explicação do
modo "markup" x "preco_fixo" e a nota sobre o erro real encontrado e
corrigido em relação à planilha Excel original do usuário.

Permissão segue a mesma régua de `custeio.visualizar` (Fase 13) — dado
sensível de custo/margem real, por padrão só Financeiro/Diretoria/
Administrador têm acesso, mesmo a ferramenta vivendo dentro do menu
"Comercial & Vendas" (pedido explícito do usuário: é ali que ele quer
ACHAR a tela, não necessariamente quem mais vai usá-la).
"""
from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission
from .. import precificacao_service as calc
from .custeio import custo_variantes_item, custo_projetado_formula_variantes

METODOS_CUSTO_VALIDOS = ("ultimo", "media", "mais_alto")

bp = Blueprint("precificacao", __name__, url_prefix="/api/v1/precificacao")


def _cenario_ou_404(conn, cenario_id):
    row = conn.execute("SELECT * FROM precificacoes WHERE id = ?", (cenario_id,)).fetchone()
    if row is None:
        raise ApiError("Cenário de precificação não encontrado.", status=404)
    return dict(row)


def _com_resultado(cenario):
    cenario["resultado"] = calc.calcular(cenario)
    return cenario


@bp.get("/sugestao-custo/<int:item_id>")
@requires_permission("precificacao", "visualizar")
def sugestao_custo(item_id):
    """Sugere o custo de produção REAL do item (mesma fonte já usada em
    Custeio — fórmula ativa se existir, senão histórico de compra direto)
    pra pré-preencher o formulário. Nunca trava o campo: é só uma sugestão
    que o usuário pode sobrescrever, exatamente como o resto do sistema já
    faz (ex.: preço sugerido de Tabela de Preço em Novo Pedido).

    Fase 214 — pedido do usuário: em vez de só a média de compra, sempre
    devolve os 3 jeitos de olhar o histórico real (`opcoes_custo`: último
    preço pago, média ponderada, maior preço já pago) mais uma sugestão
    automática (`metodo_sugerido`/`motivo_sugestao` — ver
    `custo_variantes_item` em `custeio.py` pra regra completa: se o preço
    andou subindo, sugere média; senão, sugere o último). `?metodo=` deixa
    o usuário pedir um método específico em vez do sugerido (dropdown na
    tela) — sempre um dos 3 (`ultimo`/`media`/`mais_alto`), nunca uma
    trava."""
    conn = get_db()
    item = conn.execute("SELECT id, codigo, descricao FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError("Item não encontrado.", status=404)

    metodo_pedido = request.args.get("metodo")
    if metodo_pedido is not None and metodo_pedido not in METODOS_CUSTO_VALIDOS:
        raise ApiError(f"'metodo' inválido — use um de: {', '.join(METODOS_CUSTO_VALIDOS)}.", status=400)

    formula = conn.execute(
        "SELECT * FROM formulas WHERE item_produzido_id = ? AND status = 'ativa'", (item_id,)
    ).fetchone()
    if formula:
        info = custo_projetado_formula_variantes(conn, dict(formula))
        opcoes = info["opcoes"]
        metodo_sugerido = info["metodo_sugerido"]
        motivo_sugestao = info["motivo_sugestao"]
        origem = "formula_ativa" if opcoes else None
    else:
        variantes = custo_variantes_item(conn, item_id)
        if variantes["tem_dado"]:
            opcoes = {"ultimo": variantes["ultimo"]["valor"], "media": variantes["media"], "mais_alto": variantes["mais_alto"]}
        else:
            opcoes = None
        metodo_sugerido = variantes["sugestao_metodo"]
        motivo_sugestao = variantes["motivo_sugestao"]
        origem = "custo_medio_compra" if opcoes else None

    metodo_aplicado = metodo_pedido if (metodo_pedido and opcoes) else metodo_sugerido
    custo_sugerido = opcoes.get(metodo_aplicado) if (opcoes and metodo_aplicado) else None

    return jsonify({
        "item_id": item_id, "item_codigo": item["codigo"], "item_descricao": item["descricao"],
        "origem": origem,
        "opcoes_custo": opcoes,
        "metodo_sugerido": metodo_sugerido,
        "metodo_aplicado": metodo_aplicado,
        "motivo_sugestao": motivo_sugestao,
        "custo_sugerido": round(custo_sugerido, 4) if custo_sugerido is not None else None,
    })


@bp.post("/calcular")
@requires_permission("precificacao", "visualizar")
def calcular_previa():
    """Cálculo SEM salvar — usado pela tela pra recalcular em tempo real
    conforme o usuário digita, e também pra comparar vários cenários lado a
    lado antes de decidir qual salvar."""
    dados = request.get_json(silent=True) or {}
    cenario = calc.validar_e_normalizar(dados)
    return jsonify(_com_resultado(cenario))


@bp.get("")
@requires_permission("precificacao", "visualizar")
def listar_cenarios():
    conn = get_db()
    apenas_ativos = request.args.get("status", "ativo")
    item_id = request.args.get("item_id", type=int)
    clausulas = []
    params = []
    if apenas_ativos != "todos":
        clausulas.append("p.status = ?")
        params.append(apenas_ativos)
    if item_id:
        clausulas.append("p.item_id = ?")
        params.append(item_id)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT p.*, i.codigo AS item_codigo, i.descricao AS item_descricao, u.nome AS criado_por_nome
        FROM precificacoes p
        LEFT JOIN itens i ON i.id = p.item_id
        JOIN usuarios u ON u.id = p.criado_por_id
        {where}
        ORDER BY p.criado_em DESC
        """,
        params,
    ).fetchall()
    return jsonify([_com_resultado(dict(r)) for r in rows])


@bp.get("/<int:cenario_id>")
@requires_permission("precificacao", "visualizar")
def obter_cenario(cenario_id):
    conn = get_db()
    return jsonify(_com_resultado(_cenario_ou_404(conn, cenario_id)))


@bp.post("")
@requires_permission("precificacao", "criar")
def criar_cenario():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    item_id = dados.get("item_id")
    if item_id is not None and not conn.execute("SELECT 1 FROM itens WHERE id = ?", (item_id,)).fetchone():
        raise ApiError("Item não encontrado.", status=404)

    cenario = calc.validar_e_normalizar(dados)
    cur = conn.execute(
        """
        INSERT INTO precificacoes (
            nome, item_id, modo, custo_producao, custo_origem,
            icms_pct, pis_pct, cofins_pct, analises_pct, frete_pct, despesas_fixas_pct, comissao_pct,
            margem_liquida_desejada_pct, preco_venda_final, aliquota_irpj_csll_pct, quantidade, observacoes,
            criado_por_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cenario["nome"], item_id, cenario["modo"], cenario["custo_producao"], cenario["custo_origem"],
            cenario["icms_pct"], cenario["pis_pct"], cenario["cofins_pct"], cenario["analises_pct"],
            cenario["frete_pct"], cenario["despesas_fixas_pct"], cenario["comissao_pct"],
            cenario["margem_liquida_desejada_pct"], cenario["preco_venda_final"], cenario["aliquota_irpj_csll_pct"],
            cenario["quantidade"], cenario["observacoes"], usuario_atual["id"],
        ),
    )
    cenario_id = cur.lastrowid
    audit.registrar(conn, tabela="precificacoes", registro_id=cenario_id, usuario_id=usuario_atual["id"],
                     acao="cenario_criado", valor_novo={"nome": cenario["nome"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_com_resultado(_cenario_ou_404(conn, cenario_id))), 201


@bp.put("/<int:cenario_id>")
@requires_permission("precificacao", "criar")
def atualizar_cenario(cenario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _cenario_ou_404(conn, cenario_id)
    dados = request.get_json(silent=True) or {}

    item_id = dados.get("item_id")
    if item_id is not None and not conn.execute("SELECT 1 FROM itens WHERE id = ?", (item_id,)).fetchone():
        raise ApiError("Item não encontrado.", status=404)

    cenario = calc.validar_e_normalizar(dados)
    conn.execute(
        """
        UPDATE precificacoes SET
            nome = ?, item_id = ?, modo = ?, custo_producao = ?, custo_origem = ?,
            icms_pct = ?, pis_pct = ?, cofins_pct = ?, analises_pct = ?, frete_pct = ?,
            despesas_fixas_pct = ?, comissao_pct = ?, margem_liquida_desejada_pct = ?, preco_venda_final = ?,
            aliquota_irpj_csll_pct = ?, quantidade = ?, observacoes = ?,
            atualizado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), atualizado_por_id = ?
        WHERE id = ?
        """,
        (
            cenario["nome"], item_id, cenario["modo"], cenario["custo_producao"], cenario["custo_origem"],
            cenario["icms_pct"], cenario["pis_pct"], cenario["cofins_pct"], cenario["analises_pct"],
            cenario["frete_pct"], cenario["despesas_fixas_pct"], cenario["comissao_pct"],
            cenario["margem_liquida_desejada_pct"], cenario["preco_venda_final"], cenario["aliquota_irpj_csll_pct"],
            cenario["quantidade"], cenario["observacoes"], usuario_atual["id"], cenario_id,
        ),
    )
    audit.registrar(conn, tabela="precificacoes", registro_id=cenario_id, usuario_id=usuario_atual["id"],
                     acao="cenario_atualizado", valor_novo={"nome": cenario["nome"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_com_resultado(_cenario_ou_404(conn, cenario_id)))


@bp.delete("/<int:cenario_id>")
@requires_permission("precificacao", "excluir")
def excluir_cenario(cenario_id):
    """Soft-delete (`status = 'arquivado'`) — nunca some de verdade, pro
    histórico continuar consultável (mesmo princípio já usado em Agenda,
    Fase 208: preferir arquivar a apagar)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _cenario_ou_404(conn, cenario_id)
    conn.execute(
        "UPDATE precificacoes SET status = 'arquivado', atualizado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
        "atualizado_por_id = ? WHERE id = ?",
        (usuario_atual["id"], cenario_id),
    )
    audit.registrar(conn, tabela="precificacoes", registro_id=cenario_id, usuario_id=usuario_atual["id"],
                     acao="cenario_arquivado", valor_novo=None, ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})
