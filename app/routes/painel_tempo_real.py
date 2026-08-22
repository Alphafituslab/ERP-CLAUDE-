"""Fase 75 (original) / Fase 90 (redesenho) — Painel Tempo Real em formato Kanban/pipeline.

Pedido do cliente: em vez de 3 listas soltas e sem relação entre si (o formato original desta
tela), um painel único que mostra um pedido/matéria-prima atravessando de verdade as etapas do
negócio — do PCP solicitando compra de matéria-prima até a coleta pela transportadora — com o
lado de Compras/CQ e o lado de Produção/Comercial sincronizados na MESMA tela.

PRINCÍPIO DE ARQUITETURA (não violar sem reler a nota completa em
migrations/schema_fase81.sql): a maior parte do pipeline JÁ tem uma coluna de status de verdade
em alguma tabela existente (`pedidos_venda.status`, `ordens_producao.status` +
`ordem_producao_etapas`, `pedidos_compra.status`, `sugestoes_compra_mrp.status`,
`lotes.status`, `pedidos_venda_confirmacoes_pendentes.status`) — cada coluna abaixo é uma
query pequena e AO VIVO contra essas tabelas, nunca um snapshot persistido (mesma filosofia
desde a Fase 75: "não guarda nada em tabela nova"). Só a coluna "Separação" usa o Catálogo de
Fluxo Configurável (Fase 81), porque é a única etapa deste conjunto sem nenhuma coluna própria.

PERMISSÕES: cada coluna é gated pela MESMA permissão que já controla a tela normal daquele
módulo (`producao.visualizar`, `comercial.visualizar`, `compras.visualizar`, `lotes.visualizar`,
`itens.visualizar`) — nunca uma permissão nova "ver o painel inteiro". Um perfil estreito (ex.:
"Produção", só com `producao.*`) continua vendo só as colunas que já fazem sentido pra ele, em
vez de um painel vazio ou de ganhar visibilidade sobre módulos que não tem permissão nenhuma.

Sem WebSocket — o frontend continua fazendo polling (Fase 75), mesma decisão de sempre."""

from flask import Blueprint, g, jsonify

from ..context import get_db
from ..permissions import requires_auth, usuario_tem_permissao
from .estoque import saldo_total_disponivel_item
from .producao import _etapas_da_ordem

bp = Blueprint("painel_tempo_real", __name__, url_prefix="/api/v1/painel-tempo-real")


def _col_aprovacao_financeira(conn):
    rows = conn.execute(
        """
        SELECT p.id AS pendente_id, p.valor_pedido, p.motivo_solicitacao, p.solicitado_em,
               pv.id AS pedido_venda_id, pv.numero, c.razao_social AS cliente_nome
        FROM pedidos_venda_confirmacoes_pendentes p
        JOIN pedidos_venda pv ON pv.id = p.pedido_venda_id
        JOIN clientes c ON c.id = pv.cliente_id
        WHERE p.status = 'pendente'
        ORDER BY p.id DESC LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _col_separacao(conn):
    # LEFT JOIN de propósito: a etapa "Separação" (Fase 81) só é
    # materializada em `fluxo_instancias` na primeira vez que alguém abre
    # o detalhe daquele pedido — um pedido confirmado que ninguém ainda
    # visitou não tem linha nenhuma lá, mas ainda precisa aparecer aqui
    # como "pendente" (`COALESCE`), senão o painel ficaria incompleto até
    # alguém abrir a tela manualmente pelo menos uma vez.
    rows = conn.execute(
        """
        SELECT * FROM (
            SELECT pv.id AS pedido_venda_id, pv.numero, pv.confirmado_em, c.razao_social AS cliente_nome,
                   COALESCE(fi.status, 'pendente') AS status_separacao
            FROM pedidos_venda pv
            JOIN clientes c ON c.id = pv.cliente_id
            LEFT JOIN tipos_etapa_fluxo tef ON tef.entidade_tipo = 'pedido_venda' AND tef.codigo = 'separacao' AND tef.status = 'ativo'
            LEFT JOIN fluxo_instancias fi ON fi.tipo_etapa_fluxo_id = tef.id AND fi.entidade_id = pv.id
            WHERE pv.status = 'confirmado'
        ) sub
        WHERE status_separacao != 'concluida'
        ORDER BY pedido_venda_id DESC LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _col_sugestoes_compra(conn):
    rows = conn.execute(
        """
        SELECT s.id, s.quantidade_sugerida, s.gerada_em, i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM sugestoes_compra_mrp s JOIN itens i ON i.id = s.item_id
        WHERE s.status = 'pendente'
        ORDER BY s.id DESC LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _col_pedidos_compra(conn):
    rows = conn.execute(
        """
        SELECT pc.id, pc.numero, pc.status, pc.criado_em, pc.enviado_em,
               f.nome AS fornecedor_nome
        FROM pedidos_compra pc
        JOIN fornecedores f ON f.id = pc.fornecedor_id
        WHERE pc.status IN ('rascunho', 'enviado', 'parcialmente_recebido')
        ORDER BY pc.id DESC LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _col_lotes_quarentena(conn):
    rows = conn.execute(
        """
        SELECT l.id, l.codigo_lote, l.status, l.criado_em, l.origem,
               i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM lotes l JOIN itens i ON i.id = l.item_id
        WHERE l.status IN ('quarentena', 'em_analise', 'aguardando_aprovacao')
        ORDER BY l.id DESC LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _col_producao_etapas(conn):
    # Mostra toda etapa ainda não concluída de uma ordem liberada/em
    # produção — tanto a que já está em andamento (`iniciado_em`
    # preenchido, pode ser concluída) quanto a próxima da fila (ainda nem
    # iniciada, ordenada por `sequencia`) — de propósito, para o tablet
    # do chão de fábrica continuar podendo iniciar a PRÓXIMA etapa direto
    # por aqui, sem precisar abrir o detalhe da ordem (mesma capacidade
    # que o painel original, Fase 75, já dava). "Em andamento" continua
    # sendo a mesma regra derivada de sempre: status 'pendente' no banco +
    # `iniciado_em` preenchido, nunca um valor novo de status (ver a nota
    # completa em migrations/schema_fase75.sql).
    rows = conn.execute(
        """
        SELECT oe.id AS etapa_id, oe.nome, oe.sequencia, oe.iniciado_em, oe.valor_registrado,
               op.id AS ordem_producao_id, op.numero, i.codigo AS item_codigo, i.descricao AS item_descricao,
               ct.nome AS centro_trabalho_nome, tep.unidade_valor AS tipo_unidade_valor
        FROM ordem_producao_etapas oe
        JOIN ordens_producao op ON op.id = oe.ordem_producao_id
        JOIN itens i ON i.id = op.item_produzido_id
        LEFT JOIN centros_trabalho ct ON ct.id = oe.centro_trabalho_id
        LEFT JOIN tipos_etapa_producao tep ON tep.id = oe.tipo_etapa_id
        WHERE oe.status = 'pendente' AND op.status IN ('liberada', 'em_producao')
        ORDER BY (oe.iniciado_em IS NULL), oe.iniciado_em DESC, oe.sequencia
        LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _col_estoque_minimo(conn):
    # Fase 87 — mesmo helper usado em GET /itens e no MRP; aqui só filtra
    # para os que estão de fato abaixo, em vez de devolver o catálogo
    # inteiro com um booleano por linha.
    itens_com_minimo = conn.execute(
        "SELECT id, codigo, descricao, unidade_medida, estoque_minimo FROM itens WHERE estoque_minimo IS NOT NULL AND status = 'ativo'"
    ).fetchall()
    resultado = []
    for item in itens_com_minimo:
        item = dict(item)
        estoque_atual = saldo_total_disponivel_item(conn, item["id"])
        if estoque_atual < item["estoque_minimo"]:
            resultado.append({**item, "estoque_atual": estoque_atual})
    resultado.sort(key=lambda i: i["estoque_atual"] - i["estoque_minimo"])
    return resultado[:50]


def _col_expedicao_coleta(conn):
    rows = conn.execute(
        """
        SELECT pv.id AS pedido_venda_id, pv.numero, pv.expedido_em, c.razao_social AS cliente_nome
        FROM pedidos_venda pv JOIN clientes c ON c.id = pv.cliente_id
        WHERE pv.status = 'expedido'
          AND NOT EXISTS (
              SELECT 1 FROM pedido_venda_coletas pvc
              WHERE pvc.pedido_venda_id = pv.id AND pvc.status = 'coletada'
          )
        ORDER BY pv.id DESC LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


# (chave, título, função da coluna, (módulo, ação) da permissão que já
# controla a tela normal daquele módulo)
COLUNAS = (
    ("aprovacao_financeira", "Aguardando Aprovação Financeira", _col_aprovacao_financeira, ("comercial", "visualizar")),
    ("separacao", "Separação", _col_separacao, ("comercial", "visualizar")),
    ("solicitacao_compra", "PCP → Compras (Sugestões)", _col_sugestoes_compra, ("producao", "visualizar")),
    ("compras_em_andamento", "Compras — Enviado / Recebendo", _col_pedidos_compra, ("compras", "visualizar")),
    ("quarentena_cq", "Quarentena / Aguardando CQ", _col_lotes_quarentena, ("lotes", "visualizar")),
    ("producao_etapas", "Produção — Etapas em Andamento", _col_producao_etapas, ("producao", "visualizar")),
    ("estoque_minimo", "Abaixo do Estoque Mínimo", _col_estoque_minimo, ("itens", "visualizar")),
    ("expedicao_coleta", "Expedido / Aguardando Coleta", _col_expedicao_coleta, ("comercial", "visualizar")),
)


@bp.get("")
@requires_auth
def painel():
    usuario_atual = g.usuario_atual
    conn = get_db()

    colunas_resultado = []
    for chave, titulo, funcao_coluna, (modulo, acao) in COLUNAS:
        if not usuario_tem_permissao(conn, usuario_atual["id"], modulo, acao):
            continue
        itens = funcao_coluna(conn)
        colunas_resultado.append({"chave": chave, "titulo": titulo, "itens": itens, "contagem": len(itens)})

    return jsonify({"colunas": colunas_resultado})
