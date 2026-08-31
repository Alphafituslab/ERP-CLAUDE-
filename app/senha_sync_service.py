"""
Fase 123 — pedido do usuário: "preciso que a senha ao logar o sistema
seja a mesma em todas as abas: memorial, protocolo, whatts, login do
sistema... sempre que alterar uma altera todas".

Os quatro sistemas guardam a conta do administrador em bancos de dados
TOTALMENTE separados, cada um com seu próprio esquema de hash (PBKDF2
aqui e no Whatts, bcrypt no Protocolo e no Memorial) — não existe (nem
seria seguro inventar) uma forma de "copiar o hash" de um pro outro.
Por isso a sincronização SEMPRE passa pelo mecanismo de troca de senha
que cada sistema já expõe:

  - Whatts Inbox: roda no mesmo processo/máquina (bundled) — escrita
    local direta, usando a MESMA função de hash que o próprio Whatts já
    usa (nenhuma criptografia nova inventada aqui).
  - Protocolo de Estabilidade: já tinha, de fábrica, um endpoint
    `POST /api/auth/reset-password` protegido pela senha mestra
    (MASTER_PASSWORD) — reaproveitado tal como é, sem mexer no código
    dele.
  - Memorial Técnico: não tinha um equivalente livre (só sincronizava a
    própria senha mestra no boot) — adicionamos `POST
    /api/auth/sync-password`, protegido por um segredo PRÓPRIO
    (SYNC_PASSWORD_SECRET, deliberadamente diferente do
    BACKUP_MASTER_PASSWORD, pra não misturar o escopo de acesso a
    backup com o de troca de senha).

Cada chamada é independente e "best effort": uma falha num destino
(rede fora do ar, sistema não configurado nesta instalação) NUNCA desfaz
nem bloqueia a troca de senha local nem os outros destinos — a rota que
chama esta função já concluiu a troca local ANTES de chamar isto.

Só dispara para o e-mail administrador vinculado (configurável via
ALPHAFITUS_SYNC_EMAIL, senão assume admin@alphafitus.com.br) — nunca
para usuários comuns, que não têm conta correspondente nos outros três
sistemas.
"""
import logging
import os
import sqlite3
import sys

logger = logging.getLogger(__name__)

EMAIL_ADMIN_SINCRONIZADO = os.environ.get("ALPHAFITUS_SYNC_EMAIL", "admin@alphafitus.com.br")
TIMEOUT_SEGUNDOS = 10


# ---------------------------------------------------------------------
# Localização do Whatts bundled — versões próprias (não importadas de
# installer/app_launcher.py) de propósito: app/ não deve depender de
# installer/, só o contrário. Mesma lógica de resolução frozen/dev.
# ---------------------------------------------------------------------
def _pasta_instalacao():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pasta_whatts_bundled_pai():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", _pasta_instalacao())
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sincronizar_whatts_local(nova_senha):
    caminho_db = os.path.join(_pasta_instalacao(), "data", "whatts.db")
    if not os.path.isfile(caminho_db):
        return None, "Módulo WhatsApp não está em uso nesta instalação (banco não encontrado)."
    try:
        caminho_pacote = os.path.join(_pasta_whatts_bundled_pai(), "whatts_bundled")
        if caminho_pacote not in sys.path:
            sys.path.insert(0, caminho_pacote)
        from whatts_app import security as whatts_security  # import tardio, só quando necessário

        conn = sqlite3.connect(caminho_db)
        try:
            novo_hash = whatts_security.hash_password(nova_senha)
            cur = conn.execute(
                "UPDATE usuarios SET senha_hash = ? WHERE email = ?",
                (novo_hash, EMAIL_ADMIN_SINCRONIZADO),
            )
            conn.commit()
            if cur.rowcount == 0:
                return False, "Usuário administrador não encontrado no banco do Whatts."
            return True, None
        finally:
            conn.close()
    except Exception as erro:
        logger.exception("Falha ao sincronizar senha no Whatts Inbox")
        return False, str(erro)


def _chamar_endpoint_sincronizacao(url_base, caminho, payload):
    import requests

    resp = requests.post(f"{url_base.rstrip('/')}{caminho}", json=payload, timeout=TIMEOUT_SEGUNDOS)
    if resp.status_code == 200:
        return True, None
    try:
        return False, resp.json().get("error", f"HTTP {resp.status_code}")
    except Exception:
        return False, f"HTTP {resp.status_code}"


def _sincronizar_protocolo(nova_senha):
    url = os.environ.get("ALPHAFITUS_SYNC_PROTOCOLO_URL")
    senha_mestra = os.environ.get("ALPHAFITUS_SYNC_PROTOCOLO_MASTER")
    usuario = os.environ.get("ALPHAFITUS_SYNC_PROTOCOLO_USUARIO", "admin")
    if not url or not senha_mestra:
        return None, "Sincronização com o Protocolo de Estabilidade não configurada nesta instalação."
    try:
        return _chamar_endpoint_sincronizacao(
            url, "/api/auth/reset-password",
            {"masterPassword": senha_mestra, "username": usuario, "newPassword": nova_senha},
        )
    except Exception as erro:
        logger.exception("Falha ao sincronizar senha no Protocolo de Estabilidade")
        return False, str(erro)


def _sincronizar_memorial(nova_senha):
    url = os.environ.get("ALPHAFITUS_SYNC_MEMORIAL_URL")
    segredo = os.environ.get("ALPHAFITUS_SYNC_MEMORIAL_SECRET")
    usuario = os.environ.get("ALPHAFITUS_SYNC_MEMORIAL_USUARIO", "Clayton")
    if not url or not segredo:
        return None, "Sincronização com o Memorial Técnico não configurada nesta instalação."
    try:
        return _chamar_endpoint_sincronizacao(
            url, "/api/auth/sync-password",
            {"syncSecret": segredo, "usuarioLogin": usuario, "novaSenha": nova_senha},
        )
    except Exception as erro:
        logger.exception("Falha ao sincronizar senha no Memorial Técnico")
        return False, str(erro)


def _sincronizar_whatts_email_local(email_atual, email_novo):
    caminho_db = os.path.join(_pasta_instalacao(), "data", "whatts.db")
    if not os.path.isfile(caminho_db):
        return None, "Módulo WhatsApp não está em uso nesta instalação (banco não encontrado)."
    try:
        conn = sqlite3.connect(caminho_db)
        try:
            conflito = conn.execute("SELECT id FROM usuarios WHERE email = ? AND email != ?", (email_novo, email_atual)).fetchone()
            if conflito:
                return False, "Já existe outro usuário com este e-mail no Whatts."
            cur = conn.execute(
                "UPDATE usuarios SET email = ? WHERE email = ?",
                (email_novo, email_atual),
            )
            conn.commit()
            if cur.rowcount == 0:
                return False, "Usuário administrador não encontrado no banco do Whatts."
            return True, None
        finally:
            conn.close()
    except Exception as erro:
        logger.exception("Falha ao sincronizar e-mail no Whatts Inbox")
        return False, str(erro)


def _persistir_variavel_config_ambiente(chave, valor):
    """Depois de um sync de e-mail bem-sucedido, o "usuário atual" de
    cada destino muda — se isso ficasse só em `os.environ` (memória do
    processo), a PRÓXIMA sincronização (mesmo dias depois, depois de
    reiniciar o Alphafitus OS) voltaria a procurar pelo login ANTIGO
    (`config_ambiente.bat` é relido do zero a cada início) e falharia com
    "usuário não encontrado". Por isso, além do `os.environ[...] = ...`
    (efeito imediato, sem precisar reiniciar), regrava a mesma linha no
    arquivo de configuração — mesmo arquivo/formato que
    `gerar_config_ambiente_se_necessario` já escreve
    (`installer/app_launcher.py`), só que aqui é uma edição pontual de
    UMA linha, nunca reescrevendo o arquivo inteiro. Falha em persistir
    (arquivo ausente/sem permissão) não derruba a sincronização em si —
    só fica registrado no log; o valor em memória já está certo até o
    próximo reinício."""
    caminho = os.path.join(_pasta_instalacao(), "config_ambiente.bat")
    try:
        if not os.path.isfile(caminho):
            return
        with open(caminho, "r", encoding="utf-8") as f:
            linhas = f.readlines()
        prefixo = f'set "{chave}='
        encontrada = False
        for i, linha in enumerate(linhas):
            if linha.strip().startswith(prefixo):
                linhas[i] = f'set "{chave}={valor}"\n'
                encontrada = True
                break
        if not encontrada:
            linhas.append(f'set "{chave}={valor}"\n')
        with open(caminho, "w", encoding="utf-8") as f:
            f.writelines(linhas)
    except Exception:
        logger.exception("Falha ao persistir %s em config_ambiente.bat (valor em memória continua correto)", chave)


def _sincronizar_protocolo_username(email_novo):
    url = os.environ.get("ALPHAFITUS_SYNC_PROTOCOLO_URL")
    senha_mestra = os.environ.get("ALPHAFITUS_SYNC_PROTOCOLO_MASTER")
    usuario_atual = os.environ.get("ALPHAFITUS_SYNC_PROTOCOLO_USUARIO", "admin")
    if not url or not senha_mestra:
        return None, "Sincronização com o Protocolo de Estabilidade não configurada nesta instalação."
    try:
        ok, msg = _chamar_endpoint_sincronizacao(
            url, "/api/auth/sync-username",
            {"masterPassword": senha_mestra, "currentUsername": usuario_atual, "newUsername": email_novo},
        )
        if ok:
            # A partir daqui, o login desse sistema passa a ser o e-mail novo
            # — próxima sincronização (de senha ou de e-mail) precisa usar
            # esse valor, não mais o antigo. Persistido em disco também
            # (ver _persistir_variavel_config_ambiente), não só em memória.
            os.environ["ALPHAFITUS_SYNC_PROTOCOLO_USUARIO"] = email_novo
            _persistir_variavel_config_ambiente("ALPHAFITUS_SYNC_PROTOCOLO_USUARIO", email_novo)
        return ok, msg
    except Exception as erro:
        logger.exception("Falha ao sincronizar login no Protocolo de Estabilidade")
        return False, str(erro)


def _sincronizar_memorial_username(email_novo):
    url = os.environ.get("ALPHAFITUS_SYNC_MEMORIAL_URL")
    segredo = os.environ.get("ALPHAFITUS_SYNC_MEMORIAL_SECRET")
    usuario_atual = os.environ.get("ALPHAFITUS_SYNC_MEMORIAL_USUARIO", "Clayton")
    if not url or not segredo:
        return None, "Sincronização com o Memorial Técnico não configurada nesta instalação."
    try:
        ok, msg = _chamar_endpoint_sincronizacao(
            url, "/api/auth/sync-username",
            {"syncSecret": segredo, "currentUsuarioLogin": usuario_atual, "novoUsuarioLogin": email_novo},
        )
        if ok:
            os.environ["ALPHAFITUS_SYNC_MEMORIAL_USUARIO"] = email_novo
            _persistir_variavel_config_ambiente("ALPHAFITUS_SYNC_MEMORIAL_USUARIO", email_novo)
        return ok, msg
    except Exception as erro:
        logger.exception("Falha ao sincronizar login no Memorial Técnico")
        return False, str(erro)


ID_USUARIO_ADMIN_SINCRONIZADO = 1


def sincronizar_email_em_todos_sistemas(usuario_id, email_atual, email_novo):
    """Espelha `sincronizar_senha_em_todos_sistemas`, mas pro LOGIN
    (usuário/e-mail) em vez da senha — pedido do usuário: "se trocar
    email fica igual em tudo". Os três destinos passam a usar o e-mail
    NOVO como próprio identificador de login (Whatts: campo email;
    Protocolo: username; Memorial: usuarioLogin) — não é só um "e-mail de
    contato", é literalmente o que cada um vai pedir na tela de login daí
    em diante. As variáveis de ambiente que guardam qual é o "usuário
    atual" em cada destino são atualizadas em memória após um sucesso,
    pra uma sincronização seguinte (de senha ou de e-mail de novo) já
    mirar no valor certo sem precisar reiniciar o processo — mas isso é
    só um cache: `config_ambiente.bat` continua com o valor ANTIGO até
    alguém editar à mão (ver README/memória do projeto)."""
    global EMAIL_ADMIN_SINCRONIZADO
    e_admin_vinculado = usuario_id == ID_USUARIO_ADMIN_SINCRONIZADO or (
        (email_atual or "").strip().lower() == EMAIL_ADMIN_SINCRONIZADO.lower()
    )
    if not e_admin_vinculado:
        return None

    resultado = {
        "whatts": _sincronizar_whatts_email_local(email_atual, email_novo),
        "protocolo": _sincronizar_protocolo_username(email_novo),
        "memorial": _sincronizar_memorial_username(email_novo),
    }
    if usuario_id == ID_USUARIO_ADMIN_SINCRONIZADO:
        EMAIL_ADMIN_SINCRONIZADO = email_novo
    return resultado


def sincronizar_senha_em_todos_sistemas(usuario_id, email_usuario, nova_senha):
    """Devolve None se o usuário não é a identidade administrativa
    vinculada (nada a sincronizar). Senão, devolve um dict
    {"whatts"/"protocolo"/"memorial": (True|False|None, mensagem)} —
    True=sincronizado, False=tentou e falhou, None=não configurado
    nesta instalação. Nunca levanta exceção.

    Checa pelo ID (âncora estável, id=1 é sempre o primeiro
    administrador criado — ver seed.py) em vez de só pelo e-mail: o
    usuário pode trocar o próprio e-mail (ver rota trocar-email) sem
    perder a sincronização de senha."""
    e_admin_vinculado = (
        usuario_id == ID_USUARIO_ADMIN_SINCRONIZADO
        or (email_usuario or "").strip().lower() == EMAIL_ADMIN_SINCRONIZADO.lower()
    )
    if not e_admin_vinculado:
        return None

    return {
        "whatts": _sincronizar_whatts_local(nova_senha),
        "protocolo": _sincronizar_protocolo(nova_senha),
        "memorial": _sincronizar_memorial(nova_senha),
    }
