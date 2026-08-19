"""Fase 75 — Painel de Chão de Fábrica em Tempo Real.

Pedido do cliente: um painel que atualiza sozinho (o frontend consulta este
endpoint por polling — este stack não tem websocket, ver README.md) e que
mostra, para CADA setor, só o que é relevante para ele — não uma tela única
igual para todo mundo. Em vez de criar um cadastro novo de "Setor" (opção
descartada explicitamente pelo cliente — ver conversa da Fase 75), este
painel reaproveita os PERFIS DE ACESSO que já existem desde a Fase 1: cada
seção da resposta só aparece se o usuário logado tiver a permissão
operacional daquele módulo (`producao.visualizar`, `comercial.visualizar`,
`compras.visualizar`) — exatamente a mesma permissão que já controla se ele
vê aquela tela normal do sistema. Um usuário do perfil "Produção" (chão de
fábrica) só tem `producao.*`, então só recebe a seção `producao`; um
usuário "PCP" ou "Diretoria", com mais permissões, recebe mais seções.

Por isso este endpoint usa `requires_auth` (só exige estar logado) em vez
de uma permissão fixa feito `requires_permission("relatorios",
"visualizar")` do Painel Gerencial (relatorios.py) — aqui a filtragem é
POR SEÇÃO, dentro da própria view function, não uma permissão de tudo ou
nada guardando a rota inteira.

Não guarda nada em tabela nova: é sempre um retrato AO VIVO, montado na
hora a partir de `ordens_producao`/`ordem_producao_etapas` (Fase 50/75),
`pedidos_venda` (Fase 5) e `pedidos_compra` (Fase 58) — nenhum número é
pré-calculado nem cacheado, mesma filosofia do Painel Gerencial."""

from flask import Blueprint, g, jsonify

from ..context import get_db
from ..permissions import requires_auth, usuario_tem_permissao
from .producao import _etapas_da_ordem

bp = Blueprint("painel_tempo_real", __name__, url_prefix="/api/v1/painel-tempo-real")

# Ordens de produção "ativas" para fins deste painel: já liberadas para o
# chão de fábrica e ainda não fechadas — mesmo conjunto de status que já
# permite apontar consumo/etapa em producao.py (STATUS_QUE_PERMITEM_CONSUMO).
STATUS_PRODUCAO_ATIVOS = ("liberada", "em_producao")


def _secao_producao(conn):
    ordens = conn.execute(
        """
        SELECT op.id, op.status, op.quantidade_planejada, op.unidade, op.criado_em,
               i.codigo AS item_codigo, i.descricao AS item_descricao
        FROM ordens_producao op
        JOIN itens i ON i.id = op.item_produzido_id
        WHERE op.status IN (?, ?)
        ORDER BY op.id DESC
        """,
        STATUS_PRODUCAO_ATIVOS,
    ).fetchall()

    # Reaproveita `_etapas_da_ordem` de producao.py (mesma função usada por
    # GET /producao/ordens/<id>) em vez de duplicar a consulta + a regra de
    # `situacao` derivada aqui — uma única fonte de verdade para "o que
    # significa uma etapa estar em andamento".
    return [{**dict(ordem), "etapas": _etapas_da_ordem(conn, ordem["id"])} for ordem in ordens]


def _secao_comercial(conn):
    # Pedidos de venda ainda "em movimento" — rascunho/confirmado; expedido
    # e cancelado já são histórico, não interessam a um painel de tempo
    # real de chão de fábrica/comercial.
    rows = conn.execute(
        """
        SELECT pv.id, pv.numero, pv.status, pv.criado_em, pv.confirmado_em,
               c.razao_social AS cliente_nome
        FROM pedidos_venda pv
        JOIN clientes c ON c.id = pv.cliente_id
        WHERE pv.status IN ('rascunho', 'confirmado')
        ORDER BY pv.id DESC
        LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _secao_compras(conn):
    rows = conn.execute(
        """
        SELECT pc.id, pc.numero, pc.status, pc.criado_em, pc.enviado_em,
               f.nome AS fornecedor_nome
        FROM pedidos_compra pc
        JOIN fornecedores f ON f.id = pc.fornecedor_id
        WHERE pc.status IN ('rascunho', 'enviado', 'parcialmente_recebido')
        ORDER BY pc.id DESC
        LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


@bp.get("")
@requires_auth
def painel():
    usuario_atual = g.usuario_atual
    conn = get_db()

    resposta = {"secoes": []}

    if usuario_tem_permissao(conn, usuario_atual["id"], "producao", "visualizar"):
        resposta["secoes"].append({"chave": "producao", "titulo": "Produção — Chão de Fábrica", "ordens": _secao_producao(conn)})

    if usuario_tem_permissao(conn, usuario_atual["id"], "comercial", "visualizar"):
        resposta["secoes"].append({"chave": "comercial", "titulo": "Pedidos de Venda", "pedidos": _secao_comercial(conn)})

    if usuario_tem_permissao(conn, usuario_atual["id"], "compras", "visualizar"):
        resposta["secoes"].append({"chave": "compras", "titulo": "Pedidos de Compra", "pedidos": _secao_compras(conn)})

    return jsonify(resposta)
