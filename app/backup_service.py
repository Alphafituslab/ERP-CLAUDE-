"""
Fase 67 — Backup Automático Agendado, Envio para Nuvem/E-mail,
Restauração.

Ver a nota de escopo completa em migrations/schema_fase67.sql. Este
módulo, no mesmo espírito de `app/audit.py` e `app/notificacoes_service.py`
(um módulo pequeno, sem blueprint próprio), concentra três
responsabilidades:

  1. `obter_configuracao` / `listar_horarios` — leitura simples.
  2. `executar_backup(conn, usuario_id, origem)` — o núcleo: gera o
     backup (reaproveitando `_gerar_backup_bytes` de app/routes/sistema.py),
     dispara nuvem e e-mail EM PARALELO (threads, não uma fila sequencial
     — é isso que "simultâneos" quer dizer), e grava o resultado de cada
     destino em `backups_executados`. Chamada tanto pela rota
     `POST /sistema/backup/executar-agora` (manual) quanto pelo
     agendador em segundo plano (agendado).
  3. `iniciar_agendador_em_background(app)` — inicia UMA thread daemon
     que acorda periodicamente, olha `backup_horarios` e dispara
     `executar_backup` quando o relógio local bate com um horário ativo.
     Chamada só por run.py, NUNCA por `app/__init__.py::create_app()` —
     se fosse criada dentro de `create_app()`, cada teste automatizado
     (que chama `create_app()" livremente, muitas vezes por execução)
     abriria uma thread nova, vazando threads e potencialmente disparando
     backups de verdade durante a bateria de testes.
"""
import datetime
import io
import threading
import time

TIMEOUT_NUVEM_SEGUNDOS = 30
INTERVALO_VERIFICACAO_SEGUNDOS = 20


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def obter_configuracao(conn):
    row = conn.execute("SELECT * FROM configuracoes_backup WHERE id = 1").fetchone()
    if row is None:
        return {
            "ativo": False, "nuvem_ativo": False, "nuvem_endpoint_url": None, "nuvem_regiao": None,
            "nuvem_bucket": None, "nuvem_access_key": None, "nuvem_secret_key": None, "nuvem_prefixo": None,
            "email_ativo": False, "email_destinatarios": None,
        }
    return dict(row)


def listar_horarios(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM backup_horarios ORDER BY hora").fetchall()]


def _enviar_para_nuvem(config, nome_arquivo, dados_backup):
    """Envia via API S3 (padrão suportado por praticamente todo provedor
    de object storage — ver decisão de escopo em migrations/schema_fase67.sql).
    `boto3` é uma dependência OPCIONAL (só quem liga o envio para nuvem
    precisa dela instalada) — por isso o import fica aqui dentro, não no
    topo do arquivo, para o resto do módulo (agendamento, e-mail) nunca
    quebrar numa instalação que ainda não rodou `pip install -r
    requirements.txt` depois de atualizar (ver iniciar.bat)."""
    try:
        import boto3
    except ImportError:
        raise RuntimeError(
            "A biblioteca 'boto3' não está instalada neste ambiente Python — necessária para o envio para "
            "nuvem. Rode 'pip install -r requirements.txt' novamente (ou reabra o iniciar.bat, que faz isso "
            "sozinho) e tente de novo."
        )
    if not config.get("nuvem_endpoint_url") or not config.get("nuvem_bucket"):
        raise ValueError("Configure ao menos nuvem_endpoint_url e nuvem_bucket antes de ativar o envio para nuvem.")

    cliente = boto3.client(
        "s3",
        endpoint_url=config["nuvem_endpoint_url"],
        region_name=config.get("nuvem_regiao") or "us-east-1",
        aws_access_key_id=config.get("nuvem_access_key") or None,
        aws_secret_access_key=config.get("nuvem_secret_key") or None,
    )
    prefixo = (config.get("nuvem_prefixo") or "").strip().strip("/")
    chave = f"{prefixo}/{nome_arquivo}" if prefixo else nome_arquivo
    cliente.put_object(Bucket=config["nuvem_bucket"], Key=chave, Body=dados_backup)
    return chave


def _enviar_para_email(config_smtp, config, nome_arquivo, dados_backup):
    """Recebe `config_smtp` JÁ CARREGADA (não uma conexão de banco) de
    propósito: esta função roda dentro de uma thread separada (ver
    `executar_backup` abaixo), e uma conexão sqlite3 só pode ser usada na
    MESMA thread em que foi criada — por isso a leitura de
    `configuracoes_email` acontece antes, na thread principal, e só o
    dicionário já pronto atravessa para a thread do envio."""
    from . import notificacoes_service

    destinatarios = [e.strip() for e in (config.get("email_destinatarios") or "").split(",") if e.strip()]
    if not destinatarios:
        raise ValueError("Nenhum destinatário configurado em email_destinatarios.")
    if not config_smtp.get("smtp_host"):
        raise ValueError(
            "Nenhum servidor SMTP configurado (Fase 37 — Configurações > E-mail) — necessário para o envio "
            "de backup por e-mail."
        )
    notificacoes_service.enviar_email_com_anexo(
        config_smtp, destinatarios,
        "[Alphafitus OS] Backup automático do sistema",
        (
            f"Backup gerado em {_now_iso()} — {len(dados_backup)} bytes.\n\n"
            "Guarde este arquivo em local seguro. Para restaurar, use a tela Administração > Backup > "
            "Restaurar, dentro do próprio Alphafitus OS."
        ),
        nome_arquivo, dados_backup,
    )
    return destinatarios


def executar_backup(conn, usuario_id, origem):
    """Núcleo reaproveitado pela rota manual e pelo agendador. Gera o
    backup uma vez só e dispara os dois destinos ATIVOS em paralelo (ver
    nota de escopo #2 em migrations/schema_fase67.sql) — um destino
    desligado nem entra na lista de threads, então nunca aparece como
    "tentado" no histórico. Sempre grava uma linha em
    `backups_executados`, mesmo se AMBOS os destinos falharem (a geração
    do backup em si é sempre bem-sucedida se chegou até aqui — só o
    ENVIO pode falhar)."""
    from . import notificacoes_service
    from .routes.sistema import _gerar_backup_bytes

    config = obter_configuracao(conn)
    conn.commit()  # mesmo motivo do commit em baixar_backup_completo (app/routes/sistema.py)
    dados_backup = _gerar_backup_bytes(conn)
    agora = _now_iso()
    nome_arquivo = f"Alphafitus-Backup-Completo-{agora.replace(':', '-')}.db"
    # Lida com a conexão AQUI, na thread principal — as threads dos dois
    # destinos abaixo nunca tocam `conn` (uma conexão sqlite3 só pode ser
    # usada na mesma thread em que foi criada).
    config_smtp = notificacoes_service.obter_configuracao_email(conn)

    resultados = {"nuvem": None, "email": None}

    def _tarefa_nuvem():
        try:
            _enviar_para_nuvem(config, nome_arquivo, dados_backup)
            resultados["nuvem"] = (True, None)
        except Exception as erro:
            resultados["nuvem"] = (False, str(erro))

    def _tarefa_email():
        try:
            _enviar_para_email(config_smtp, config, nome_arquivo, dados_backup)
            resultados["email"] = (True, None)
        except Exception as erro:
            resultados["email"] = (False, str(erro))

    threads = []
    if config.get("nuvem_ativo"):
        t = threading.Thread(target=_tarefa_nuvem, daemon=True)
        threads.append(t)
    if config.get("email_ativo"):
        t = threading.Thread(target=_tarefa_email, daemon=True)
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=TIMEOUT_NUVEM_SEGUNDOS + 30)

    nuvem_tentado = 1 if config.get("nuvem_ativo") else 0
    email_tentado = 1 if config.get("email_ativo") else 0
    nuvem_sucesso, nuvem_erro = (None, None)
    if resultados["nuvem"] is not None:
        nuvem_sucesso, nuvem_erro = resultados["nuvem"]
        nuvem_sucesso = 1 if nuvem_sucesso else 0
    email_sucesso, email_erro = (None, None)
    if resultados["email"] is not None:
        email_sucesso, email_erro = resultados["email"]
        email_sucesso = 1 if email_sucesso else 0

    cur = conn.execute(
        """
        INSERT INTO backups_executados
            (executado_em, origem, disparado_por, tamanho_bytes,
             nuvem_tentado, nuvem_sucesso, nuvem_erro, email_tentado, email_sucesso, email_erro)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (agora, origem, usuario_id, len(dados_backup),
         nuvem_tentado, nuvem_sucesso, nuvem_erro, email_tentado, email_sucesso, email_erro),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM backups_executados WHERE id = ?", (cur.lastrowid,)).fetchone())


# =======================================================================
# Agendador em segundo plano
# =======================================================================
def _rodar_ciclo(db_path, ja_executados_hoje):
    from . import db as db_module

    with db_module.get_conn(db_path) as conn:
        config = obter_configuracao(conn)
        if not config.get("ativo"):
            return
        agora_local = datetime.datetime.now()
        hoje_str = agora_local.strftime("%Y-%m-%d")
        hora_str = agora_local.strftime("%H:%M")

        # Limpa marcas de dias anteriores para o dicionário não crescer
        # para sempre num processo de servidor que fica rodando por dias.
        for chave in list(ja_executados_hoje.keys()):
            if ja_executados_hoje[chave] != hoje_str:
                del ja_executados_hoje[chave]

        horarios = listar_horarios(conn)
        for horario in horarios:
            if not horario["ativo"] or horario["hora"] != hora_str:
                continue
            if ja_executados_hoje.get(horario["id"]) == hoje_str:
                continue
            ja_executados_hoje[horario["id"]] = hoje_str
            try:
                executar_backup(conn, None, "agendado")
            except Exception:
                # Nunca deixa o agendador em si morrer por causa de uma
                # execução que falhou — tenta de novo no próximo horário.
                pass


def _loop_agendador(db_path):
    ja_executados_hoje = {}
    while True:
        try:
            _rodar_ciclo(db_path, ja_executados_hoje)
        except Exception:
            pass
        time.sleep(INTERVALO_VERIFICACAO_SEGUNDOS)


def iniciar_agendador_em_background(db_path=None):
    """Chamada só por run.py (ver docstring do módulo) — nunca por
    `create_app()`. Devolve a thread criada (daemon=True: não impede o
    processo de encerrar quando a janela principal for fechada)."""
    thread = threading.Thread(target=_loop_agendador, args=(db_path,), daemon=True, name="alphafitus-backup-agendador")
    thread.start()
    return thread
