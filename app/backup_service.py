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
import os
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
            "local_ativo": False, "local_pasta": None,
            "drive_ativo": False, "drive_client_id": None, "drive_client_secret": None,
            "drive_refresh_token": None, "drive_pasta_id": None,
            "whatsapp_ativo": False, "whatsapp_numero_destino": None,
            "whatsapp_evolution_url": None, "whatsapp_evolution_apikey": None, "whatsapp_instancia_nome": None,
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


def _salvar_local(config, nome_arquivo, dados_backup):
    """Mais simples dos quatro destinos — sem dependência nenhuma, só
    escreve o arquivo. `local_pasta` pode ser um HD externo ou pasta de
    rede; se não existir na hora (ex.: pendrive desconectado durante o
    backup agendado de madrugada), a exceção sobe normal e fica
    registrada em `backups_executados.local_erro`, sem derrubar os
    outros destinos (mesmo padrão de nuvem/e-mail)."""
    pasta = (config.get("local_pasta") or "").strip()
    if not pasta:
        raise ValueError("Configure local_pasta antes de ativar o destino Local.")
    os.makedirs(pasta, exist_ok=True)
    caminho_completo = os.path.join(pasta, nome_arquivo)
    with open(caminho_completo, "wb") as f:
        f.write(dados_backup)
    return caminho_completo


def _requests_backup():
    try:
        import requests
        return requests
    except ImportError:
        raise RuntimeError(
            "A biblioteca 'requests' não está instalada neste ambiente Python — necessária para o envio ao "
            "Google Drive e o aviso por WhatsApp. Rode 'pip install -r requirements.txt' novamente."
        )


def _obter_access_token_drive(config):
    """Troca o refresh_token (obtido uma única vez pelo fluxo de
    autorização — ver app/routes/sistema.py) por um access_token novo,
    válido por ~1h — feito a cada backup porque o access_token não é
    guardado (só o refresh_token, que não expira até o usuário revogar
    o acesso)."""
    requests = _requests_backup()
    if not config.get("drive_client_id") or not config.get("drive_client_secret") or not config.get("drive_refresh_token"):
        raise ValueError(
            "Google Drive ainda não foi autorizado — vá em Administração > Backup, preencha o Client ID/Secret "
            "e clique em 'Conectar Google Drive'."
        )
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": config["drive_client_id"],
            "client_secret": config["drive_client_secret"],
            "refresh_token": config["drive_refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=TIMEOUT_NUVEM_SEGUNDOS,
    )
    if not resp.ok:
        raise RuntimeError(f"Falha ao renovar o acesso ao Google Drive (HTTP {resp.status_code}): {resp.text[:300]}")
    return resp.json()["access_token"]


def _enviar_para_drive(config, nome_arquivo, dados_backup):
    """Upload direto pela API REST do Drive v3 (multipart simples — sem
    a biblioteca oficial google-api-python-client, pesada demais para
    esta única chamada; mesmo raciocínio de app/nfe_service.py e
    app/boleto_service.py, que também falam REST puro em vez de SDK)."""
    requests = _requests_backup()
    access_token = _obter_access_token_drive(config)

    metadados = {"name": nome_arquivo}
    if config.get("drive_pasta_id"):
        metadados["parents"] = [config["drive_pasta_id"]]

    import json as _json
    fronteira = "alphafitus-backup-boundary"
    corpo = (
        f"--{fronteira}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{_json.dumps(metadados)}\r\n"
        f"--{fronteira}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + dados_backup + f"\r\n--{fronteira}--".encode("utf-8")

    resp = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={fronteira}",
        },
        data=corpo,
        timeout=TIMEOUT_NUVEM_SEGUNDOS * 4,  # arquivo grande, dá mais tempo que os outros destinos
    )
    if not resp.ok:
        raise RuntimeError(f"Falha ao enviar para o Google Drive (HTTP {resp.status_code}): {resp.text[:300]}")
    return resp.json().get("id")


def _enviar_aviso_whatsapp(config, nome_arquivo, tamanho_bytes, resultados_outros_destinos):
    """Só um AVISO de texto — decisão explícita do usuário (2026-09-01):
    o arquivo de backup (~110MB hoje, só cresce) fica perto/acima do
    limite de anexo do WhatsApp; mandar só avisar que rodou é o que
    realmente funciona sempre. Fala direto com a Evolution API (mesma
    que já atende o Whatts Inbox de produção) — não precisa da conta de
    ninguém no Alphafitus, só da apikey da própria Evolution."""
    requests = _requests_backup()
    numero = (config.get("whatsapp_numero_destino") or "").strip()
    if not numero:
        raise ValueError("Configure whatsapp_numero_destino antes de ativar o aviso por WhatsApp.")
    if not config.get("whatsapp_evolution_url") or not config.get("whatsapp_evolution_apikey"):
        raise ValueError("Configure a URL e a chave de API do WhatsApp (Evolution API) antes de ativar este destino.")

    partes_status = []
    for nome_destino, rotulo in (("nuvem", "Nuvem"), ("email", "E-mail"), ("drive", "Google Drive"), ("local", "Local")):
        resultado = resultados_outros_destinos.get(nome_destino)
        if resultado is None:
            continue
        sucesso, _erro = resultado
        partes_status.append(f"{rotulo}: {'✅' if sucesso else '❌'}")
    resumo_destinos = " | ".join(partes_status) if partes_status else "(nenhum outro destino ativo)"

    texto = (
        f"🔒 *Alphafitus OS — Backup automático*\n"
        f"Arquivo: {nome_arquivo}\n"
        f"Tamanho: {tamanho_bytes / (1024 * 1024):.1f} MB\n"
        f"{resumo_destinos}"
    )
    digitos = "".join(c for c in numero if c.isdigit())
    resp = requests.post(
        f"{config['whatsapp_evolution_url']}/message/sendText/{config.get('whatsapp_instancia_nome') or 'whatts'}",
        json={"number": digitos, "text": texto},
        headers={"apikey": config["whatsapp_evolution_apikey"], "Content-Type": "application/json"},
        timeout=TIMEOUT_NUVEM_SEGUNDOS,
    )
    if not resp.ok:
        raise RuntimeError(f"Falha ao enviar aviso por WhatsApp (HTTP {resp.status_code}): {resp.text[:300]}")
    return True


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

    resultados = {"nuvem": None, "email": None, "local": None, "drive": None}

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

    def _tarefa_local():
        try:
            _salvar_local(config, nome_arquivo, dados_backup)
            resultados["local"] = (True, None)
        except Exception as erro:
            resultados["local"] = (False, str(erro))

    def _tarefa_drive():
        try:
            _enviar_para_drive(config, nome_arquivo, dados_backup)
            resultados["drive"] = (True, None)
        except Exception as erro:
            resultados["drive"] = (False, str(erro))

    threads = []
    if config.get("nuvem_ativo"):
        threads.append(threading.Thread(target=_tarefa_nuvem, daemon=True))
    if config.get("email_ativo"):
        threads.append(threading.Thread(target=_tarefa_email, daemon=True))
    if config.get("local_ativo"):
        threads.append(threading.Thread(target=_tarefa_local, daemon=True))
    if config.get("drive_ativo"):
        threads.append(threading.Thread(target=_tarefa_drive, daemon=True))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=TIMEOUT_NUVEM_SEGUNDOS * 4 + 30)  # drive pode demorar mais (arquivo grande)

    def _extrair(chave):
        tentado = 1 if config.get(f"{chave}_ativo") else 0
        sucesso, erro = (None, None)
        if resultados[chave] is not None:
            sucesso, erro = resultados[chave]
            sucesso = 1 if sucesso else 0
        return tentado, sucesso, erro

    nuvem_tentado, nuvem_sucesso, nuvem_erro = _extrair("nuvem")
    email_tentado, email_sucesso, email_erro = _extrair("email")
    local_tentado, local_sucesso, local_erro = _extrair("local")
    drive_tentado, drive_sucesso, drive_erro = _extrair("drive")

    # WhatsApp roda DEPOIS dos outros (não em paralelo com eles) — o
    # aviso precisa saber como os outros destinos foram pra montar o
    # resumo; sem essa ordem, o aviso chegaria sem essa informação.
    whatsapp_tentado = whatsapp_sucesso = None
    whatsapp_erro = None
    if config.get("whatsapp_ativo"):
        whatsapp_tentado = 1
        try:
            _enviar_aviso_whatsapp(config, nome_arquivo, len(dados_backup), resultados)
            whatsapp_sucesso = 1
        except Exception as erro:
            whatsapp_sucesso = 0
            whatsapp_erro = str(erro)

    cur = conn.execute(
        """
        INSERT INTO backups_executados
            (executado_em, origem, disparado_por, tamanho_bytes,
             nuvem_tentado, nuvem_sucesso, nuvem_erro, email_tentado, email_sucesso, email_erro,
             local_tentado, local_sucesso, local_erro, drive_tentado, drive_sucesso, drive_erro,
             whatsapp_tentado, whatsapp_sucesso, whatsapp_erro)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (agora, origem, usuario_id, len(dados_backup),
         nuvem_tentado, nuvem_sucesso, nuvem_erro, email_tentado, email_sucesso, email_erro,
         local_tentado, local_sucesso, local_erro, drive_tentado, drive_sucesso, drive_erro,
         whatsapp_tentado, whatsapp_sucesso, whatsapp_erro),
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
