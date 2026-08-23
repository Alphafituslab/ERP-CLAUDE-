"""
Fase 81 — Catálogo de Fluxo Configurável: funções compartilhadas usadas tanto por
`app/routes/fluxo.py` (rotas de cadastro/apontamento manual) quanto por qualquer rota REAL de
outro módulo que precise marcar uma etapa `origem='sistema'` automaticamente no momento exato
de uma transição de negócio (ex.: confirmar coleta pela transportadora, Fase 86).

Ver a nota de escopo completa em migrations/schema_fase81.sql — este catálogo cobre só o que
HOJE não tem uma coluna de status própria em nenhuma tabela existente.
"""
import datetime
import sqlite3

from .context import ApiError

ENTIDADES_VALIDAS = ("pedido_venda", "ordem_producao", "pedido_compra", "lote")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def listar_tipos_etapa(conn, entidade_tipo=None, incluir_inativos=False):
    clausulas, params = [], []
    if entidade_tipo:
        clausulas.append("t.entidade_tipo = ?")
        params.append(entidade_tipo)
    if not incluir_inativos:
        clausulas.append("t.status = 'ativo'")
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    rows = conn.execute(
        f"""
        SELECT t.*, p.nome AS perfil_nome FROM tipos_etapa_fluxo t
        LEFT JOIN perfis p ON p.id = t.perfil_id
        {where} ORDER BY t.entidade_tipo, t.ordem_padrao, t.id
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def etapas_da_entidade(conn, entidade_tipo, entidade_id, usuario_id):
    """Materializa (lazy) uma linha 'pendente' em fluxo_instancias para cada tipo ATIVO deste
    entidade_tipo que a entidade ainda não tenha, e devolve as etapas já materializadas que o
    USUÁRIO ATUAL pode ver — Fase 100: uma etapa com `perfil_id` definido só aparece para quem
    pertence àquele perfil (setor); uma etapa sem perfil (a maioria, incluindo tudo cadastrado
    antes desta fase) continua visível para qualquer um com `fluxo.apontar`, sem mudança de
    comportamento. A MATERIALIZAÇÃO acontece para TODAS as etapas ativas, independente do
    filtro — é assim que a etapa já existe pronta para quando alguém do setor certo abrir a
    tela, sem precisar de nenhum backfill."""
    if entidade_tipo not in ENTIDADES_VALIDAS:
        raise ApiError(f"entidade_tipo deve ser um de: {', '.join(ENTIDADES_VALIDAS)}.", status=400)

    tipos = listar_tipos_etapa(conn, entidade_tipo=entidade_tipo)
    for tipo in tipos:
        try:
            conn.execute(
                "INSERT INTO fluxo_instancias (tipo_etapa_fluxo_id, entidade_id) VALUES (?, ?)",
                (tipo["id"], entidade_id),
            )
        except sqlite3.IntegrityError:
            # Já materializada (por esta mesma chamada antes, ou por uma corrida com outra
            # requisição concorrente abrindo a mesma tela ao mesmo tempo) — não é um erro.
            pass

    rows = conn.execute(
        """
        SELECT fi.*, t.codigo, t.nome, t.ordem_padrao, t.origem, t.perfil_id, p.nome AS perfil_nome
        FROM fluxo_instancias fi
        JOIN tipos_etapa_fluxo t ON t.id = fi.tipo_etapa_fluxo_id
        LEFT JOIN perfis p ON p.id = t.perfil_id
        WHERE t.entidade_tipo = ? AND fi.entidade_id = ?
          AND (t.perfil_id IS NULL OR t.perfil_id IN (SELECT perfil_id FROM usuario_perfil WHERE usuario_id = ?))
        ORDER BY t.ordem_padrao, t.id
        """,
        (entidade_tipo, entidade_id, usuario_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _instancia_ou_404(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id):
    row = conn.execute(
        """
        SELECT fi.*, t.codigo, t.nome, t.entidade_tipo, t.origem
        FROM fluxo_instancias fi JOIN tipos_etapa_fluxo t ON t.id = fi.tipo_etapa_fluxo_id
        WHERE fi.tipo_etapa_fluxo_id = ? AND fi.entidade_id = ? AND t.entidade_tipo = ?
        """,
        (tipo_etapa_fluxo_id, entidade_id, entidade_tipo),
    ).fetchone()
    if row is None:
        raise ApiError("Etapa de fluxo não encontrada para esta entidade.", status=404)
    return dict(row)


def iniciar_etapa(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id, usuario_id):
    instancia = _instancia_ou_404(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id)
    if instancia["origem"] == "sistema":
        raise ApiError(
            "Esta etapa é marcada automaticamente por uma ação real do sistema — não pode ser iniciada manualmente.",
            status=400,
        )
    if instancia["status"] != "pendente":
        raise ApiError(f"Esta etapa já está '{instancia['status']}' — não é possível iniciar de novo.", status=400)
    conn.execute(
        "UPDATE fluxo_instancias SET status = 'em_andamento', iniciado_em = ?, iniciado_por = ? WHERE id = ?",
        (_now_iso(), usuario_id, instancia["id"]),
    )
    return _instancia_ou_404(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id)


def concluir_etapa(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id, usuario_id, observacao=None):
    instancia = _instancia_ou_404(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id)
    if instancia["origem"] == "sistema":
        raise ApiError(
            "Esta etapa é marcada automaticamente por uma ação real do sistema — não pode ser concluída manualmente.",
            status=400,
        )
    if instancia["status"] == "concluida":
        raise ApiError("Esta etapa já está concluída.", status=400)
    conn.execute(
        "UPDATE fluxo_instancias SET status = 'concluida', concluido_em = ?, concluido_por = ?, observacao = ? WHERE id = ?",
        (_now_iso(), usuario_id, observacao, instancia["id"]),
    )
    return _instancia_ou_404(conn, entidade_tipo, entidade_id, tipo_etapa_fluxo_id)


def marcar_concluida(conn, entidade_tipo, entidade_id, codigo, usuario_id, observacao=None):
    """Chamado por uma rota REAL de outro módulo (ex.: confirmar coleta pela transportadora,
    Fase 86) no momento exato de uma transição de negócio, para uma etapa origem='sistema'.
    Materializa a instância se ainda não existir (mesma lógica preguiçosa de
    `etapas_da_entidade`) e já a marca concluída de uma vez — quem chama isso já SABE que o
    evento aconteceu de verdade, não precisa passar por iniciar() antes."""
    tipo = conn.execute(
        "SELECT * FROM tipos_etapa_fluxo WHERE entidade_tipo = ? AND codigo = ?",
        (entidade_tipo, codigo),
    ).fetchone()
    if tipo is None:
        # Etapa 'sistema' esperada pelo código mas ainda não cadastrada no catálogo (ex.:
        # instalação antiga sem a migração que a semeou) — não deve derrubar a rota que
        # chamou isso só por causa de uma etapa decorativa do painel.
        return None
    try:
        conn.execute(
            "INSERT INTO fluxo_instancias (tipo_etapa_fluxo_id, entidade_id) VALUES (?, ?)",
            (tipo["id"], entidade_id),
        )
    except sqlite3.IntegrityError:
        pass
    conn.execute(
        "UPDATE fluxo_instancias SET status = 'concluida', concluido_em = ?, concluido_por = ?, observacao = COALESCE(?, observacao) "
        "WHERE tipo_etapa_fluxo_id = ? AND entidade_id = ?",
        (_now_iso(), usuario_id, observacao, tipo["id"], entidade_id),
    )
    return _instancia_ou_404(conn, entidade_tipo, entidade_id, tipo["id"])
