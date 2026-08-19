"""
Fase 46 — Memorial Técnico ANVISA: Administração — Snapshots (Exportar/
Restaurar). (Fase 49 acrescentou a este mesmo blueprint o último pedaço da
Administração — "Configurações" — ver a seção FASE 49 mais abaixo neste
arquivo.)

Continuação da seção "Administração" do sistema original que a Fase 24
deixou de propósito de fora (ver migrations/schema_fase44.sql) e que a
Fase 44 começou a repor com "Usuários Online". Esta fase entrega o
segundo pedaço: "Snapshots & Restauração" — o sistema original guardava
isso em Postgres com `pg_dump`; aqui, como cada tabela do módulo já é
lida/escrita como um dict Python comum (nenhuma coluna binária de verdade
— até o conteúdo de um anexo já é texto em base64, ver
`memorial_anexos.dados`), um "snapshot" é simplesmente um arquivo JSON com
o conteúdo INTEIRO das tabelas do módulo, baixável e "restaurável" depois
— DB-agnóstico por natureza, então funciona igual se um dia o sistema for
migrado de SQLite para PostgreSQL (ver README, seção "Migrando para
PostgreSQL").

Reaproveita permissões que já existem, nenhuma nova:
  - `memoriais.visualizar` para EXPORTAR (é só uma leitura maior, no fundo
    a mesma capacidade de ver os dados do módulo).
  - `memoriais.excluir` para RESTAURAR — restaurar um snapshot SUBSTITUI
    por completo o conteúdo atual das tabelas do módulo (quem cadastrou
    depois do snapshot perde o que cadastrou), então a permissão exigida é
    a mais destrutiva que já existe no módulo, de propósito.

Segurança do "tudo ou nada": como o restante do sistema já documenta em
`app/context.py` (`close_db`), uma `ApiError` levantada no meio de uma rota
AINDA FAZ COMMIT do que já foi escrito até ali — então esta rota nunca
pode contar com "levantar erro no meio" para desfazer um DELETE que já
rodou. Em vez disso, a restauração roda inteira dentro de um SAVEPOINT
próprio: qualquer erro durante o apagar+inserir (violação de chave
estrangeira, de unicidade, de CHECK, JSON malformado) desfaz o SAVEPOINT
antes de levantar a ApiError — ou seja, o próprio banco garante que uma
restauração que falhar no meio não deixa o módulo pela metade.
"""
import datetime
import sqlite3

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("memorial_administracao", __name__, url_prefix="/api/v1/memorial/administracao")

# Ordem de INSERÇÃO da restauração (pais antes de filhos, por causa das
# foreign keys — `PRAGMA foreign_keys = ON` está ligado em toda conexão,
# ver app/db.py). A ordem de EXCLUSÃO usa exatamente o inverso desta
# lista. `memorial_catalogo_itens` não depende de nenhuma das outras
# (só de `usuarios`), então sua posição relativa às demais não importa.
_TABELAS_SNAPSHOT = (
    "memorial_empresas",
    "memorial_produtos",
    "memoriais",
    "memorial_assinaturas",
    "memorial_historico",
    "memorial_anexos",
    "memorial_padronizacoes",
    "memorial_catalogo_itens",
)

VERSAO_SNAPSHOT = 1


def _colunas_validas_por_tabela(conn):
    """Devolve {nome_tabela: {conjunto de nomes de coluna reais}} lendo o
    schema de verdade via PRAGMA table_info — usado por
    `_restaurar_snapshot` para NUNCA interpolar um nome de coluna vindo do
    arquivo JSON enviado pelo usuário sem antes confirmar que é uma coluna
    que realmente existe na tabela. Sem isso, uma chave de dicionário
    maliciosa no JSON (ex.: `"nome) SELECT senha_hash FROM usuarios --"`)
    vira SQL injetado direto no INSERT, já que o nome da coluna é
    interpolado por f-string (só o VALOR de cada campo é parametrizado com
    `?` — o NOME da coluna não pode ser, o SQLite não aceita `?` no lugar
    de identificador). Descoberto em auditoria de segurança; ver também os
    testes em `tests/test_fase46.py`."""
    colunas_por_tabela = {}
    for nome_tabela in _TABELAS_SNAPSHOT:
        linhas = conn.execute(f"PRAGMA table_info({nome_tabela})").fetchall()
        colunas_por_tabela[nome_tabela] = {linha["name"] for linha in linhas}
    return colunas_por_tabela


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _montar_snapshot(conn):
    tabelas = {}
    for nome_tabela in _TABELAS_SNAPSHOT:
        rows = conn.execute(f"SELECT * FROM {nome_tabela}").fetchall()
        tabelas[nome_tabela] = [dict(r) for r in rows]
    return {"versao": VERSAO_SNAPSHOT, "gerado_em": _now_iso(), "tabelas": tabelas}


def _validar_formato_snapshot(payload, conn):
    if not isinstance(payload, dict):
        raise ApiError("Arquivo de snapshot inválido: esperado um objeto JSON.", status=400)
    tabelas = payload.get("tabelas")
    if not isinstance(tabelas, dict):
        raise ApiError('Arquivo de snapshot inválido: campo "tabelas" ausente ou não é um objeto.', status=400)
    faltando = [t for t in _TABELAS_SNAPSHOT if t not in tabelas]
    if faltando:
        raise ApiError(
            f"Arquivo de snapshot inválido: faltam as tabelas {', '.join(faltando)} — "
            "parece ser de uma versão diferente do sistema.",
            status=400,
        )
    colunas_validas = _colunas_validas_por_tabela(conn)
    for nome_tabela in _TABELAS_SNAPSHOT:
        linhas = tabelas[nome_tabela]
        if not isinstance(linhas, list):
            raise ApiError(f'Arquivo de snapshot inválido: "{nome_tabela}" deveria ser uma lista.', status=400)
        for linha in linhas:
            if not isinstance(linha, dict) or not linha:
                raise ApiError(f'Arquivo de snapshot inválido: um registro de "{nome_tabela}" não é um objeto válido.', status=400)
            # Segurança: os NOMES das colunas de cada registro são
            # interpolados diretamente no SQL do INSERT em
            # `_restaurar_snapshot` (SQLite não aceita `?` no lugar de um
            # identificador de coluna, só no lugar de um valor) — por
            # isso, ao contrário dos valores, os nomes precisam ser
            # validados aqui contra o schema real da tabela ANTES de
            # qualquer DELETE rodar, recusando qualquer chave que não seja
            # uma coluna de verdade dessa tabela.
            colunas_desconhecidas = set(linha.keys()) - colunas_validas[nome_tabela]
            if colunas_desconhecidas:
                raise ApiError(
                    f'Arquivo de snapshot inválido: "{nome_tabela}" tem campo(s) '
                    f"desconhecido(s) {sorted(colunas_desconhecidas)} — não correspondem a "
                    "nenhuma coluna real dessa tabela.",
                    status=400,
                )
    return tabelas


def _restaurar_snapshot(conn, tabelas):
    """Apaga e reinsere o conteúdo das tabelas do módulo dentro de um
    SAVEPOINT — ver docstring do módulo sobre por que isso é obrigatório
    neste sistema. Devolve a contagem de linhas restauradas por tabela."""
    conn.execute("SAVEPOINT restaurar_snapshot_memorial")
    try:
        for nome_tabela in reversed(_TABELAS_SNAPSHOT):
            conn.execute(f"DELETE FROM {nome_tabela}")

        contagens = {}
        for nome_tabela in _TABELAS_SNAPSHOT:
            linhas = tabelas[nome_tabela]
            for linha in linhas:
                colunas = list(linha.keys())
                marcadores = ", ".join("?" for _ in colunas)
                conn.execute(
                    f"INSERT INTO {nome_tabela} ({', '.join(colunas)}) VALUES ({marcadores})",
                    [linha[c] for c in colunas],
                )
            contagens[nome_tabela] = len(linhas)
    except sqlite3.Error as erro:
        conn.execute("ROLLBACK TO restaurar_snapshot_memorial")
        conn.execute("RELEASE restaurar_snapshot_memorial")
        raise ApiError(
            f"Não foi possível restaurar o snapshot — nenhuma alteração foi feita ({erro}).",
            status=400,
        )
    else:
        conn.execute("RELEASE restaurar_snapshot_memorial")
        return contagens


@bp.get("/snapshot")
@requires_permission("memoriais", "visualizar")
def baixar_snapshot():
    """Exporta o conteúdo INTEIRO das tabelas do Memorial Técnico (empresas,
    produtos, memoriais, assinaturas, histórico, anexos, padronizações e os
    10 catálogos) como um único arquivo JSON para download — o "backup"
    deste módulo. Export puro: nunca altera nenhum dado."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    snapshot = _montar_snapshot(conn)

    audit.registrar(
        conn, tabela="memorial_snapshot", registro_id=None, usuario_id=usuario_atual["id"],
        acao="memorial_snapshot_exportado",
        valor_novo={nome: len(linhas) for nome, linhas in snapshot["tabelas"].items()},
        ip=client_ip(), dispositivo=client_device(),
    )

    data_arquivo = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    nome_arquivo = f"Memorial-Tecnico-Snapshot-{data_arquivo}.json"
    resposta = jsonify(snapshot)
    resposta.headers["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return resposta


@bp.post("/snapshot/restaurar")
@requires_permission("memoriais", "excluir")
def restaurar_snapshot():
    """Restaura um snapshot exportado por `GET /snapshot` — SUBSTITUI por
    completo o conteúdo atual das tabelas do módulo pelo conteúdo do
    arquivo enviado. Ação destrutiva e irreversível (exceto se você tiver
    guardado um snapshot de ANTES de restaurar) — por isso exige a
    permissão mais forte que já existe no módulo, `memoriais.excluir`, e o
    frontend pede confirmação explícita antes de chamar esta rota."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    payload = request.get_json(silent=True)
    tabelas = _validar_formato_snapshot(payload, conn)

    contagens_antes = {
        nome_tabela: conn.execute(f"SELECT COUNT(*) AS total FROM {nome_tabela}").fetchone()["total"]
        for nome_tabela in _TABELAS_SNAPSHOT
    }
    contagens_depois = _restaurar_snapshot(conn, tabelas)

    audit.registrar(
        conn, tabela="memorial_snapshot", registro_id=None, usuario_id=usuario_atual["id"],
        acao="memorial_snapshot_restaurado",
        valor_anterior=contagens_antes, valor_novo=contagens_depois,
        ip=client_ip(), dispositivo=client_device(),
    )

    return jsonify({"ok": True, "restaurado_em": _now_iso(), "contagens": contagens_depois})


# ============================================================
# FASE 49 — Configurações (quarto e último pedaço da Administração)
# ============================================================
# As duas únicas regras hoje fixas no Python, específicas do módulo
# Memorial Técnico (ver migrations/schema_fase49.sql para o raciocínio
# completo de por que só estas duas): quantas assinaturas aprovam um
# memorial automaticamente, e o tamanho máximo de um anexo. Mesmo padrão
# GET-mais-fraco/PUT-mais-forte já usado em `estoque.py`
# (`configurar_alcada_divergencia`): ver o valor atual não é sensível
# (liberado para quem já visualiza o módulo); só ALTERAR exige a
# permissão nova `memoriais.configurar`.
_CONFIGURACAO_PADRAO = {
    "numero_assinaturas_aprovacao": 2,
    "tamanho_maximo_anexo_mb": 40,
    "atualizado_em": None,
    "atualizado_por": None,
}


@bp.get("/configuracao")
@requires_permission("memoriais", "visualizar")
def obter_configuracao_memorial():
    conn = get_db()
    row = conn.execute("SELECT * FROM configuracoes_memorial WHERE id = 1").fetchone()
    if row is None:
        # Defensivo: nunca deveria acontecer num banco inicializado pelas
        # migrations (a Fase 49 já semeia a linha única), mas devolve o
        # padrão em vez de um 404/500 numa tela sensível como esta.
        return jsonify(dict(_CONFIGURACAO_PADRAO))
    return jsonify(dict(row))


@bp.put("/configuracao")
@requires_permission("memoriais", "configurar")
def atualizar_configuracao_memorial():
    """Os dois campos são independentes e OPCIONAIS nesta requisição — quem
    só quer mexer em um deles continua podendo mandar só esse campo, sem
    afetar o outro (mesmo comportamento já usado em `estoque.py` desde a
    Fase 34)."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    if "numero_assinaturas_aprovacao" not in dados and "tamanho_maximo_anexo_mb" not in dados:
        raise ApiError(
            "Informe numero_assinaturas_aprovacao e/ou tamanho_maximo_anexo_mb.", status=400
        )

    conn = get_db()
    anterior = conn.execute(
        "SELECT numero_assinaturas_aprovacao, tamanho_maximo_anexo_mb FROM configuracoes_memorial WHERE id = 1"
    ).fetchone()
    valor_anterior_assinaturas = anterior["numero_assinaturas_aprovacao"] if anterior else _CONFIGURACAO_PADRAO["numero_assinaturas_aprovacao"]
    valor_anterior_anexo_mb = anterior["tamanho_maximo_anexo_mb"] if anterior else _CONFIGURACAO_PADRAO["tamanho_maximo_anexo_mb"]

    if "numero_assinaturas_aprovacao" in dados:
        numero_assinaturas = dados.get("numero_assinaturas_aprovacao")
        try:
            numero_assinaturas = int(numero_assinaturas)
        except (TypeError, ValueError):
            raise ApiError("numero_assinaturas_aprovacao deve ser um número inteiro.", status=400)
        if numero_assinaturas <= 0:
            raise ApiError("numero_assinaturas_aprovacao deve ser maior que zero.", status=400)
    else:
        numero_assinaturas = valor_anterior_assinaturas

    if "tamanho_maximo_anexo_mb" in dados:
        tamanho_anexo_mb = dados.get("tamanho_maximo_anexo_mb")
        try:
            tamanho_anexo_mb = int(tamanho_anexo_mb)
        except (TypeError, ValueError):
            raise ApiError("tamanho_maximo_anexo_mb deve ser um número inteiro.", status=400)
        if tamanho_anexo_mb <= 0:
            raise ApiError("tamanho_maximo_anexo_mb deve ser maior que zero.", status=400)
    else:
        tamanho_anexo_mb = valor_anterior_anexo_mb

    conn.execute(
        """
        INSERT INTO configuracoes_memorial
            (id, numero_assinaturas_aprovacao, tamanho_maximo_anexo_mb, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            numero_assinaturas_aprovacao = excluded.numero_assinaturas_aprovacao,
            tamanho_maximo_anexo_mb = excluded.tamanho_maximo_anexo_mb,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (numero_assinaturas, tamanho_anexo_mb, _now_iso(), usuario_atual["id"]),
    )
    audit.registrar(
        conn, tabela="configuracoes_memorial", registro_id=1, usuario_id=usuario_atual["id"],
        acao="configuracao_memorial_atualizada",
        valor_anterior={
            "numero_assinaturas_aprovacao": valor_anterior_assinaturas,
            "tamanho_maximo_anexo_mb": valor_anterior_anexo_mb,
        },
        valor_novo={
            "numero_assinaturas_aprovacao": numero_assinaturas,
            "tamanho_maximo_anexo_mb": tamanho_anexo_mb,
        },
        ip=client_ip(), dispositivo=client_device(),
    )
    row = conn.execute("SELECT * FROM configuracoes_memorial WHERE id = 1").fetchone()
    return jsonify(dict(row))
