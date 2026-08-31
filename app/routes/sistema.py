"""
Fase 47 — Memorial Técnico ANVISA: Administração — Backups do Sistema.

Terceiro pedaço da seção "Administração" replicada dentro do Memorial
Técnico (depois de Usuários Online na Fase 44 e Snapshots & Restauração na
Fase 46) — mas, diferente dos outros dois, este é DELIBERADAMENTE
diferente de escopo: um "Backup do Sistema" é uma cópia do BANCO DE DADOS
INTEIRO (todas as tabelas de todos os módulos — usuários, produção,
estoque, financeiro etc.), não só das tabelas do Memorial Técnico. Por
isso a permissão exigida é `sistema.backup_completo` (módulo genérico
"sistema", mesma filosofia da Fase 37 — `sistema.configurar_email`: uma
decisão de infraestrutura do sistema como um todo, não de um módulo de
negócio específico) — NUNCA `memoriais.*`, que daria a entender
(erroneamente) que ter acesso ao Memorial Técnico dá acesso a um backup de
todo o sistema.

Como o arquivo é SQLite puro (sem servidor de banco separado, sem
`pg_dump`), o "backup" é gerado com a própria API de backup nativa do
`sqlite3` do Python (`Connection.backup()`), que faz uma cópia consistente
do banco enquanto ele está em uso — sem precisar parar o servidor nem
bloquear outras requisições (ela usa o mecanismo de página do SQLite, o
mesmo usado pelo comando `.backup` do `sqlite3` CLI e pela ferramenta
`sqlite3_backup_init` da biblioteca C).

Restauração deste backup NÃO tem uma rota própria, de propósito — e essa
ausência é uma decisão de segurança, não uma lacuna esquecida: diferente
do Snapshot da Fase 46 (JSON das tabelas do módulo, restaurado dentro de
um SAVEPOINT, tudo ou nada, sem nunca precisar tocar no arquivo em si),
substituir o ARQUIVO `.db` inteiro enquanto o servidor Flask está rodando
— com outras requisições podendo estar com uma conexão sqlite3 aberta
naquele exato instante — arriscaria corromper o banco ou deixar conexões
antigas apontando para um arquivo que não existe mais. A forma segura de
restaurar um backup deste tipo é um procedimento manual, com o serviço
parado (ver "Restaurando um Backup do Sistema" no README) — não uma ação
de um clique dentro do sistema rodando.
"""
import datetime
import io
import os
import tempfile

# Fase 123 — mesmo motivo/mesma técnica do alias em app/db.py: o banco
# agora é SQLCipher, então toda conexão sqlite3 aberta por fora de
# `db_module._connect()` (como a de destino do backup abaixo) também
# precisa ser desta biblioteca, com a MESMA chave — senão o arquivo de
# backup gerado sairia sem criptografia nenhuma, anulando o propósito.
from sqlcipher3 import dbapi2 as sqlite3  # noqa: F811 (troca intencional do sqlite3 padrão)

from flask import Blueprint, Response, g, jsonify, request

from .. import audit
from .. import backup_service
from .. import db as db_module
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("sistema", __name__, url_prefix="/api/v1/sistema")


def _gerar_backup_bytes(conn_origem: sqlite3.Connection) -> bytes:
    """Usa a API de backup nativa do sqlite3 (Connection.backup()) para
    gerar uma cópia consistente do banco INTEIRO num arquivo temporário, lê
    os bytes e apaga o temporário — nunca devolve o arquivo original em si
    (que continua sendo escrito por outras requisições), sempre uma cópia
    ponto-no-tempo."""
    descritor, caminho_tmp = tempfile.mkstemp(suffix=".db", prefix="alphafitus_backup_")
    os.close(descritor)
    try:
        conn_destino = sqlite3.connect(caminho_tmp)
        # Fase 123 — mesma chave da conexão de origem, ANTES do backup()
        # de verdade: SQLCipher criptografa/descriptografa página a
        # página, embaixo da API nativa de backup do sqlite — sem a
        # chave aqui, o arquivo de destino sairia sem criptografia.
        conn_destino.execute(f"PRAGMA key = '{db_module._obter_chave_criptografia()}'")
        try:
            conn_origem.backup(conn_destino)
        finally:
            conn_destino.close()
        with open(caminho_tmp, "rb") as arquivo:
            return arquivo.read()
    finally:
        os.remove(caminho_tmp)


@bp.get("/backup")
@requires_permission("sistema", "backup_completo")
def baixar_backup_completo():
    """Baixa uma cópia de backup do banco de dados INTEIRO (todos os
    módulos) — nunca altera nenhum dado de negócio, é só uma leitura (a
    API de backup do sqlite3 nunca escreve na conexão de origem)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    # `conn.backup()` trava indefinidamente (fica repetindo a tentativa
    # sem nunca desistir) se a conexão de ORIGEM tiver uma transação de
    # escrita aberta e não confirmada no momento da chamada — e é comum
    # ela ter uma: `get_current_user()` (app/context.py) já fez um UPDATE
    # em `usuarios.ultimo_acesso_em` mais cedo nesta mesma requisição (Fase
    # 44) sem comitar ainda (o commit de verdade só acontece no
    # `teardown_appcontext`, depois que esta função retornar). Um commit
    # explícito aqui resolve isso — e como consequência boa, o backup já
    # sai incluindo esse próprio acesso, não uma versão um instante atrasada.
    conn.commit()
    dados_backup = _gerar_backup_bytes(conn)

    audit.registrar(
        conn, tabela="sistema_backup", registro_id=None, usuario_id=usuario_atual["id"],
        acao="backup_sistema_exportado", valor_novo={"tamanho_bytes": len(dados_backup)},
        ip=client_ip(), dispositivo=client_device(),
    )

    agora = datetime.datetime.utcnow().strftime("%Y-%m-%d_%Hh%Mmin")
    nome_arquivo = f"Alphafitus-Backup-Completo-{agora}.db"
    return Response(
        dados_backup,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


# =======================================================================
# FASE 67 — Backup Automático Agendado, Envio para Nuvem/E-mail,
# Restauração
# =======================================================================
# Ver a nota de escopo completa em migrations/schema_fase67.sql. O núcleo
# de negócio (gerar + enviar para os dois destinos em paralelo + gravar
# histórico) mora em app/backup_service.py — este arquivo só expõe rotas
# HTTP finas em cima dele.

def _config_backup_publica(config):
    """Mesmo padrão de `_config_publica` para SMTP (app/routes/notificacoes.py,
    Fase 37): nunca devolve a chave secreta salva — só um booleano
    avisando se já existe uma configurada."""
    d = dict(config)
    d["nuvem_chave_configurada"] = bool(d.get("nuvem_secret_key"))
    d.pop("nuvem_secret_key", None)
    d["ativo"] = bool(d.get("ativo"))
    d["nuvem_ativo"] = bool(d.get("nuvem_ativo"))
    d["email_ativo"] = bool(d.get("email_ativo"))
    return d


@bp.get("/backup/configuracao")
@requires_permission("sistema", "configurar_backup")
def obter_configuracao_backup():
    conn = get_db()
    return jsonify(_config_backup_publica(backup_service.obter_configuracao(conn)))


@bp.put("/backup/configuracao")
@requires_permission("sistema", "configurar_backup")
def atualizar_configuracao_backup():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = backup_service.obter_configuracao(conn)

    ativo = 1 if dados.get("ativo") else 0
    nuvem_ativo = 1 if dados.get("nuvem_ativo") else 0
    email_ativo = 1 if dados.get("email_ativo") else 0
    nuvem_endpoint_url = (dados.get("nuvem_endpoint_url") or "").strip() or None
    nuvem_regiao = (dados.get("nuvem_regiao") or "").strip() or None
    nuvem_bucket = (dados.get("nuvem_bucket") or "").strip() or None
    nuvem_access_key = (dados.get("nuvem_access_key") or "").strip() or None
    nuvem_prefixo = (dados.get("nuvem_prefixo") or "").strip() or None
    email_destinatarios = (dados.get("email_destinatarios") or "").strip() or None

    # Chave secreta: campo vazio/omitido MANTÉM a chave já salva — mesmo
    # padrão de smtp_senha (Fase 37) e nuvem_secret_key nunca é devolvida
    # pela API para poder ser reenviada sem querer.
    nova_chave = dados.get("nuvem_secret_key")
    nuvem_secret_key = anterior.get("nuvem_secret_key") if not nova_chave else nova_chave

    if nuvem_ativo and (not nuvem_endpoint_url or not nuvem_bucket):
        raise ApiError("Para ativar o envio para nuvem, informe ao menos nuvem_endpoint_url e nuvem_bucket.", status=400)
    if email_ativo and not email_destinatarios:
        raise ApiError("Para ativar o envio por e-mail, informe ao menos um destinatário em email_destinatarios.", status=400)
    if ativo and not nuvem_ativo and not email_ativo:
        raise ApiError("Ative ao menos um destino (nuvem ou e-mail) antes de ligar o backup automático.", status=400)

    conn.execute(
        """
        INSERT INTO configuracoes_backup
            (id, ativo, nuvem_ativo, nuvem_endpoint_url, nuvem_regiao, nuvem_bucket, nuvem_access_key,
             nuvem_secret_key, nuvem_prefixo, email_ativo, email_destinatarios, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            ativo = excluded.ativo,
            nuvem_ativo = excluded.nuvem_ativo,
            nuvem_endpoint_url = excluded.nuvem_endpoint_url,
            nuvem_regiao = excluded.nuvem_regiao,
            nuvem_bucket = excluded.nuvem_bucket,
            nuvem_access_key = excluded.nuvem_access_key,
            nuvem_secret_key = excluded.nuvem_secret_key,
            nuvem_prefixo = excluded.nuvem_prefixo,
            email_ativo = excluded.email_ativo,
            email_destinatarios = excluded.email_destinatarios,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (ativo, nuvem_ativo, nuvem_endpoint_url, nuvem_regiao, nuvem_bucket, nuvem_access_key,
         nuvem_secret_key, nuvem_prefixo, email_ativo, email_destinatarios, _now_iso_completo(), usuario_atual["id"]),
    )
    audit.registrar(
        conn, tabela="configuracoes_backup", registro_id=1, usuario_id=usuario_atual["id"],
        acao="configuracao_backup_atualizada",
        valor_anterior={"ativo": bool(anterior.get("ativo")), "nuvem_ativo": bool(anterior.get("nuvem_ativo")), "email_ativo": bool(anterior.get("email_ativo"))},
        valor_novo={"ativo": bool(ativo), "nuvem_ativo": bool(nuvem_ativo), "email_ativo": bool(email_ativo)},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_config_backup_publica(backup_service.obter_configuracao(conn)))


def _now_iso_completo():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@bp.get("/backup/horarios")
@requires_permission("sistema", "configurar_backup")
def listar_horarios_backup():
    conn = get_db()
    horarios = backup_service.listar_horarios(conn)
    for h in horarios:
        h["ativo"] = bool(h["ativo"])
    return jsonify(horarios)


@bp.post("/backup/horarios")
@requires_permission("sistema", "configurar_backup")
def criar_horario_backup():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    hora = (dados.get("hora") or "").strip()
    conn = get_db()

    import re
    if not re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", hora or ""):
        raise ApiError("Informe hora no formato HH:MM (24 horas), ex.: 08:00.", status=400)
    partes_hora = int(hora.split(":")[0])
    if partes_hora > 23:
        raise ApiError("Hora inválida — o valor antes dos dois-pontos deve ir de 00 a 23.", status=400)

    existente = conn.execute("SELECT id FROM backup_horarios WHERE hora = ?", (hora,)).fetchone()
    if existente:
        raise ApiError(f"Já existe um horário de backup cadastrado às {hora}.", status=400)

    cur = conn.execute("INSERT INTO backup_horarios (hora, ativo) VALUES (?, 1)", (hora,))
    conn.commit()
    audit.registrar(
        conn, tabela="backup_horarios", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
        acao="backup_horario_criado", valor_novo={"hora": hora},
        ip=client_ip(), dispositivo=client_device(),
    )
    horarios = backup_service.listar_horarios(conn)
    for h in horarios:
        h["ativo"] = bool(h["ativo"])
    return jsonify(horarios), 201


@bp.delete("/backup/horarios/<int:horario_id>")
@requires_permission("sistema", "configurar_backup")
def excluir_horario_backup(horario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    horario = conn.execute("SELECT * FROM backup_horarios WHERE id = ?", (horario_id,)).fetchone()
    if horario is None:
        raise ApiError("Horário de backup não encontrado.", status=404)
    conn.execute("DELETE FROM backup_horarios WHERE id = ?", (horario_id,))
    conn.commit()
    audit.registrar(
        conn, tabela="backup_horarios", registro_id=horario_id, usuario_id=usuario_atual["id"],
        acao="backup_horario_excluido", valor_anterior={"hora": horario["hora"]},
        ip=client_ip(), dispositivo=client_device(),
    )
    horarios = backup_service.listar_horarios(conn)
    for h in horarios:
        h["ativo"] = bool(h["ativo"])
    return jsonify(horarios)


@bp.get("/backup/historico")
@requires_permission("sistema", "backup_completo")
def listar_historico_backup():
    conn = get_db()
    linhas = conn.execute("SELECT * FROM backups_executados ORDER BY id DESC LIMIT 200").fetchall()
    resultado = []
    for linha in linhas:
        d = dict(linha)
        for campo in ("nuvem_tentado", "email_tentado"):
            d[campo] = bool(d[campo])
        for campo in ("nuvem_sucesso", "email_sucesso"):
            d[campo] = bool(d[campo]) if d[campo] is not None else None
        resultado.append(d)
    return jsonify(resultado)


@bp.post("/backup/executar-agora")
@requires_permission("sistema", "backup_completo")
def executar_backup_agora():
    """Dispara um backup manual imediatamente, pelo mesmo núcleo usado
    pelo agendador (`backup_service.executar_backup`) — mesmos destinos
    configurados em `configuracoes_backup`, mesmo registro em
    `backups_executados` (com `origem = 'manual'` e `disparado_por`
    preenchido, diferente do agendado)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    resultado = backup_service.executar_backup(conn, usuario_atual["id"], "manual")
    for campo in ("nuvem_tentado", "email_tentado"):
        resultado[campo] = bool(resultado[campo])
    for campo in ("nuvem_sucesso", "email_sucesso"):
        resultado[campo] = bool(resultado[campo]) if resultado[campo] is not None else None
    return jsonify(resultado), 201


# ---- Restauração (ver a nota de escopo completa em migrations/schema_fase67.sql) ----

TAMANHO_MAXIMO_RESTAURACAO_BYTES = 500 * 1024 * 1024  # 500 MB — generoso para um SQLite de uma empresa só.


def _validar_arquivo_backup(caminho):
    """Confere que o arquivo enviado é mesmo um banco SQLite do Alphafitus
    OS (tem a tabela de controle `_migrations` E a tabela `usuarios`) —
    barra na hora, antes de deixar qualquer coisa pendente para o próximo
    início, em vez de descobrir só depois de já ter reiniciado o
    sistema."""
    try:
        conn_teste = sqlite3.connect(caminho)
        # Fase 123 — um backup de verdade, gerado por este sistema depois
        # da criptografia, só abre com a chave certa; sem ela, a consulta
        # abaixo cai no `except sqlite3.Error` e já devolve a mensagem
        # certa ("não é um banco de dados SQLite válido").
        conn_teste.execute(f"PRAGMA key = '{db_module._obter_chave_criptografia()}'")
        try:
            tabelas = {
                r[0] for r in conn_teste.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            conn_teste.close()
    except sqlite3.Error as erro:
        raise ApiError(f"O arquivo enviado não é um banco de dados SQLite válido: {erro}", status=400)

    if "_migrations" not in tabelas or "usuarios" not in tabelas:
        raise ApiError(
            "O arquivo enviado não parece ser um backup do Alphafitus OS (faltam tabelas essenciais).",
            status=400,
        )


@bp.post("/backup/restaurar")
@requires_permission("sistema", "restaurar_backup")
def restaurar_backup():
    """Recebe o arquivo de backup e o deixa PRONTO para a próxima vez que
    o sistema for iniciado (ver `db.aplicar_restauracao_pendente_se_houver`,
    chamada por run.py) — NUNCA troca o banco com o servidor já
    respondendo requisições. Devolve `restauracao_pendente: true` para a
    tela mostrar um aviso bem visível até o próximo reinício."""
    usuario_atual = g.usuario_atual
    if "arquivo" not in request.files:
        raise ApiError("Envie o arquivo de backup no campo 'arquivo'.", status=400)
    arquivo = request.files["arquivo"]
    if not arquivo.filename:
        raise ApiError("Nenhum arquivo selecionado.", status=400)

    conn = get_db()
    descritor, caminho_tmp = tempfile.mkstemp(suffix=".db", prefix="alphafitus_restaurar_")
    os.close(descritor)
    try:
        arquivo.save(caminho_tmp)
        if os.path.getsize(caminho_tmp) > TAMANHO_MAXIMO_RESTAURACAO_BYTES:
            raise ApiError("Arquivo maior que o limite permitido para restauração (500 MB).", status=400)
        _validar_arquivo_backup(caminho_tmp)

        caminho_pendente = db_module.caminho_restauracao_pendente()
        import shutil
        shutil.copy2(caminho_tmp, caminho_pendente)
    finally:
        if os.path.exists(caminho_tmp):
            os.remove(caminho_tmp)

    audit.registrar(
        conn, tabela="sistema_backup", registro_id=None, usuario_id=usuario_atual["id"],
        acao="restauracao_de_backup_agendada", valor_novo={"nome_arquivo_original": arquivo.filename},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify({
        "restauracao_pendente": True,
        "mensagem": (
            "Backup recebido e validado. A restauração será concluída na PRÓXIMA VEZ que o Alphafitus OS "
            "for iniciado (feche e abra o sistema de novo para concluir)."
        ),
    }), 202


@bp.get("/backup/restauracao-pendente")
@requires_permission("sistema", "restaurar_backup")
def obter_restauracao_pendente():
    existe = os.path.exists(db_module.caminho_restauracao_pendente())
    return jsonify({"restauracao_pendente": existe})


@bp.delete("/backup/restauracao-pendente")
@requires_permission("sistema", "restaurar_backup")
def cancelar_restauracao_pendente():
    """Desiste de uma restauração já enviada, antes do próximo reinício
    aplicá-la — ex.: a pessoa percebeu que enviou o arquivo errado."""
    usuario_atual = g.usuario_atual
    caminho_pendente = db_module.caminho_restauracao_pendente()
    if not os.path.exists(caminho_pendente):
        raise ApiError("Não há nenhuma restauração pendente para cancelar.", status=400)
    os.remove(caminho_pendente)
    conn = get_db()
    audit.registrar(
        conn, tabela="sistema_backup", registro_id=None, usuario_id=usuario_atual["id"],
        acao="restauracao_de_backup_cancelada", ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify({"restauracao_pendente": False})
