"""
Fase 69 — Painel Gerencial: Série Histórica / Tendência.

Ver a nota de escopo completa em migrations/schema_fase69.sql. Resumo:
o Painel Gerencial (Fase 7 em diante) sempre foi 100% recalculado a cada
chamada, sem guardar nada — bom para "situação atual", impossível para
"como esse número estava há 30 dias". Este módulo grava, pela primeira
vez, um HISTÓRICO desses números.

Por que a captura acontece "ao visualizar" e não por um agendador em
segundo plano (como o Backup Automático da Fase 67): um agendador
precisaria do servidor ligado exatamente no horário configurado para não
perder um dia — bom para backup (o servidor de produção fica ligado o
tempo todo, é o próprio propósito dele), mas um requisito a mais para uma
funcionalidade só de leitura/relatório, que já é naturalmente visitada
todo dia por quem usa um "painel GERENCIAL" de verdade. Em vez de somar
essa dependência, a captura vira um efeito colateral barato de
`GET /relatorios/dashboard` (a mesma rota que a tela já chama toda vez
que é aberta) — sem thread nova, sem depender do servidor estar de pé
numa hora específica. Trade-off aceito e documentado: se ninguém abrir o
Painel Gerencial num dia inteiro (com aquele filtro de empresa
específico), aquele dia fica sem snapshot.
"""
import datetime
import json

DIAS_PADRAO = 30
DIAS_MAXIMO = 365


def _hoje_iso_data():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _agora_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _serializar_blocos(dashboard_dict):
    """Extrai só os cinco blocos de "situação atual" do dict que
    `_montar_dashboard` já produziu — nunca recalcula nada aqui, para
    nunca haver dois números divergentes entre a tela "agora" e a série
    histórica (mesmo motivo pelo qual `_baixado_liquido` foi centralizada
    na Fase 15). Nunca inclui o bloco "periodo" (Fase 42) — ver a nota em
    schema_fase69.sql."""
    blocos = {
        "producao": dashboard_dict["producao"],
        "qualidade": dashboard_dict["qualidade"],
        "estoque": dashboard_dict["estoque"],
        "comercial": dashboard_dict["comercial"],
        "financeiro": dashboard_dict["financeiro"],
    }
    return json.dumps(blocos, sort_keys=True, ensure_ascii=False)


def capturar_ou_atualizar_snapshot_do_dia(conn, dashboard_dict, empresa_id=None):
    """Chamada a cada `GET /relatorios/dashboard` (ver
    app/routes/relatorios.py) — grava/atualiza a linha de HOJE (UTC) para
    esta `empresa_id` (ou o "grupo todo", quando None). Só grava de novo
    se o conteúdo realmente mudou desde a última gravação de hoje (evita
    crescer o banco à toa a cada view idêntica de quem só está olhando a
    tela, sem nada ter mudado nos bastidores)."""
    hoje = _hoje_iso_data()
    dados_json = _serializar_blocos(dashboard_dict)

    if empresa_id:
        linha_existente = conn.execute(
            "SELECT id, dados_json FROM painel_snapshots WHERE data_referencia = ? AND empresa_id = ?",
            (hoje, empresa_id),
        ).fetchone()
    else:
        linha_existente = conn.execute(
            "SELECT id, dados_json FROM painel_snapshots WHERE data_referencia = ? AND empresa_id IS NULL",
            (hoje,),
        ).fetchone()

    if linha_existente is None:
        conn.execute(
            "INSERT INTO painel_snapshots (data_referencia, empresa_id, capturado_em, dados_json) VALUES (?, ?, ?, ?)",
            (hoje, empresa_id, _agora_iso(), dados_json),
        )
        conn.commit()
    elif linha_existente["dados_json"] != dados_json:
        conn.execute(
            "UPDATE painel_snapshots SET dados_json = ?, capturado_em = ? WHERE id = ?",
            (dados_json, _agora_iso(), linha_existente["id"]),
        )
        conn.commit()


def listar_tendencia(conn, dias=DIAS_PADRAO, empresa_id=None):
    """Devolve a lista de snapshots dos últimos `dias` dias (incluindo
    hoje), do mais antigo para o mais recente, para esta `empresa_id` (ou
    "grupo todo" quando None) — cada item já vem com os cinco blocos
    desserializados, prontos para o front montar os gráficos."""
    dias = max(1, min(int(dias), DIAS_MAXIMO))
    data_limite = (datetime.datetime.utcnow() - datetime.timedelta(days=dias - 1)).strftime("%Y-%m-%d")

    if empresa_id:
        linhas = conn.execute(
            """
            SELECT data_referencia, capturado_em, dados_json FROM painel_snapshots
            WHERE data_referencia >= ? AND empresa_id = ?
            ORDER BY data_referencia ASC
            """,
            (data_limite, empresa_id),
        ).fetchall()
    else:
        linhas = conn.execute(
            """
            SELECT data_referencia, capturado_em, dados_json FROM painel_snapshots
            WHERE data_referencia >= ? AND empresa_id IS NULL
            ORDER BY data_referencia ASC
            """,
            (data_limite,),
        ).fetchall()

    resultado = []
    for linha in linhas:
        item = {"data_referencia": linha["data_referencia"], "capturado_em": linha["capturado_em"]}
        item.update(json.loads(linha["dados_json"]))
        resultado.append(item)
    return resultado
