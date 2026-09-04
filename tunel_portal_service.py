"""
Fase 152 — Terceirização Premium/Contratos: acesso externo ao portal do
cliente REESCRITO de túnel SSH reverso para um relay HTTP de conexão de
SAÍDA (substitui por completo a Fase 138).

Contexto (ver [[project_terceirizacao_premium]] na memória da sessão que
escreveu a Fase 138, e a investigação da Fase 152 na mesma memória): o
desenho anterior (`ssh -R`, um túnel reverso pro VPS) funcionava
perfeitamente quando rodado interativamente, mas os dados nunca
atravessavam quando o MESMO comando rodava dentro de um Serviço do
Windows/Tarefa Agendada (contexto SYSTEM) — a porta remota ficava
escutando de verdade, mas a retransmissão de dados travava. Um teste
isolado (Tarefa Agendada rodando como SYSTEM, só um `curl 127.0.0.1:5000`
sem SSH nenhum no meio) confirmou que loopback puro FUNCIONA normalmente
em contexto SYSTEM — o problema era específico do mecanismo de
retransmissão do SSH sob esse contexto, não de rede em geral.

Por isso a Fase 152 abandona SSH por completo. Arquitetura nova:

  1. Esta máquina NUNCA aceita conexão nenhuma de fora — só faz chamadas
     de SAÍDA (long-polling HTTPS) para um pequeno relay novo no VPS
     (`portal_relay_vps.py`, ver esse arquivo pro lado de lá).
  2. O relay recebe as requisições reais dos visitantes do portal (em
     `whatts.alphafitus.com.br:9445/portal/...`, mesmo Caddy de sempre,
     só trocando a porta de destino) e as deixa "penduradas" numa fila.
  3. Este serviço pergunta repetidamente ao relay "tem pedido pendente?"
     (`GET /agente/proximo`); quando chega um, faz a chamada real contra
     `http://127.0.0.1:5000` (o próprio AlphafitusOS local) e devolve o
     resultado (`POST /agente/resposta/<id>`), que acorda o visitante
     que estava esperando.

Nenhuma chave privada, nenhum ACL de arquivo, nenhum `ssh.exe` — só um
segredo compartilhado (Bearer token) em `config_ambiente.bat`, o mesmo
mecanismo já usado para `ALPHAFITUS_JWT_SECRET` e outros segredos deste
projeto. Isso elimina de vez a lacuna real que a Fase 138 nunca
conseguiu fechar.

Uso (dentro do venv, num Prompt de Comando/PowerShell como Administrador):

    venv\\Scripts\\python tunel_portal_service.py install
    venv\\Scripts\\python tunel_portal_service.py start
    venv\\Scripts\\python tunel_portal_service.py stop
    venv\\Scripts\\python tunel_portal_service.py remove
"""
import base64
import os
import sys
import time


def _pasta_instalacao():
    """Mesmo achado real da Fase 138: `__file__` de um módulo congelado
    pelo PyInstaller resolve para DENTRO de `_internal\\`, não para a
    pasta real de instalação (onde `config_ambiente.bat` de verdade
    mora, ao lado dos .exe) — `sys.executable` é a base certa quando
    congelado; só cai para `__file__` rodando como script .py puro."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


NOME_SERVICO = "AlphafitusOSTunelPortal"
NOME_EXIBICAO = "Alphafitus OS (Portal do Cliente - Terceirizacao/Contratos)"
DESCRICAO_SERVICO = (
    "Mantem o Portal do Cliente (Terceirizacao Premium/Contratos) acessivel "
    "de fora, via chamadas de saida para o relay do VPS da Alphafitus (Fase "
    "152 - substitui o antigo tunel SSH). Sem este servico rodando, o link "
    "enviado ao cliente nao abre."
)

PORTA_LOCAL = 5000
TIMEOUT_LONGPOLL_SEGUNDOS = 35  # um pouco acima do timeout do relay (ver portal_relay_vps.py)
SEGUNDOS_ESPERA_APOS_ERRO = 5


def _variaveis_relay(pasta_instalacao):
    """Carrega ALPHAFITUS_PORTAL_RELAY_URL/SEGREDO de config_ambiente.bat
    — mesmo parser puro (`ler_variaveis_de_config_ambiente`) que
    `service_windows.py` já usa pro serviço principal, reaproveitado
    aqui em vez de duplicar a lógica de leitura do arquivo."""
    sys.path.insert(0, pasta_instalacao)
    from service_windows import ler_variaveis_de_config_ambiente
    caminho = os.path.join(pasta_instalacao, "config_ambiente.bat")
    variaveis = ler_variaveis_de_config_ambiente(caminho)
    url = os.environ.get("ALPHAFITUS_PORTAL_RELAY_URL") or variaveis.get("ALPHAFITUS_PORTAL_RELAY_URL")
    segredo = os.environ.get("ALPHAFITUS_PORTAL_RELAY_SEGREDO") or variaveis.get("ALPHAFITUS_PORTAL_RELAY_SEGREDO")
    return url, segredo


def _processar_pedido(sessao, url_relay, headers_auth, pedido, log):
    """Executa a requisição real contra o AlphafitusOS local e devolve o
    resultado pro relay — qualquer falha na chamada local vira uma
    resposta 502 pro visitante (nunca deixa o pedido pendurado pra
    sempre no relay, que tem seu próprio timeout como rede de segurança)."""
    corpo = base64.b64decode(pedido["corpo_b64"])
    headers_locais = {k: v for k, v in pedido["headers"].items() if k.lower() not in ("host", "content-length")}
    try:
        resposta_local = sessao.request(
            pedido["metodo"], f"http://127.0.0.1:{PORTA_LOCAL}{pedido['path']}",
            headers=headers_locais, data=corpo, timeout=60, allow_redirects=False,
        )
        payload = {
            "status_code": resposta_local.status_code,
            "headers": {k: v for k, v in resposta_local.headers.items()},
            "corpo_b64": base64.b64encode(resposta_local.content).decode("ascii"),
        }
    except Exception as erro:
        log(f"Falha ao chamar o AlphafitusOS local para o pedido {pedido['id']}: {erro!r}")
        payload = {
            "status_code": 502,
            "headers": {"Content-Type": "text/plain; charset=utf-8"},
            "corpo_b64": base64.b64encode(f"Erro ao processar localmente: {erro}".encode("utf-8")).decode("ascii"),
        }
    try:
        sessao.post(f"{url_relay}/agente/resposta/{pedido['id']}", headers=headers_auth, json=payload, timeout=15)
    except Exception as erro:
        log(f"Falha ao devolver a resposta do pedido {pedido['id']} ao relay: {erro!r}")


def loop_agente(deve_parar, log):
    """Loop principal: pergunta ao relay se tem pedido, processa, repete.
    `deve_parar()` é chamado entre iterações para permitir parada
    responsiva (mesmo espírito do polling curto que a Fase 138 já usava
    pra não bloquear `SvcStop` — só que aqui não tem processo filho pra
    matar, é tudo síncrono dentro deste laço)."""
    import requests

    pasta_instalacao = _pasta_instalacao()
    url_relay, segredo = _variaveis_relay(pasta_instalacao)
    if not url_relay or not segredo:
        log("ALPHAFITUS_PORTAL_RELAY_URL/ALPHAFITUS_PORTAL_RELAY_SEGREDO não configurados em config_ambiente.bat — nada a fazer.")
        return
    url_relay = url_relay.rstrip("/")
    headers_auth = {"Authorization": f"Bearer {segredo}"}
    sessao = requests.Session()

    log(f"Conectando ao relay do portal em {url_relay}...")
    while not deve_parar():
        try:
            resp = sessao.get(f"{url_relay}/agente/proximo", headers=headers_auth, timeout=TIMEOUT_LONGPOLL_SEGUNDOS)
            if resp.status_code == 204:
                continue  # sem pedido pendente agora — o long-poll do relay já esperou, tenta de novo na hora
            if resp.status_code == 401:
                log("Relay recusou o segredo (401) — confira ALPHAFITUS_PORTAL_RELAY_SEGREDO.")
                time.sleep(30)
                continue
            if resp.status_code != 200:
                time.sleep(SEGUNDOS_ESPERA_APOS_ERRO)
                continue
            _processar_pedido(sessao, url_relay, headers_auth, resp.json(), log)
        except requests.RequestException as erro:
            log(f"Relay indisponível ({erro!r}) — tentando de novo em {SEGUNDOS_ESPERA_APOS_ERRO}s...")
            time.sleep(SEGUNDOS_ESPERA_APOS_ERRO)


if os.name == "nt":
    import win32event
    import win32service
    import win32serviceutil
    import servicemanager

    class AlphafitusOSTunelPortalService(win32serviceutil.ServiceFramework):
        _svc_name_ = NOME_SERVICO
        _svc_display_name_ = NOME_EXIBICAO
        _svc_description_ = DESCRICAO_SERVICO

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.evento_parar = win32event.CreateEvent(None, 1, 0, None)  # manual-reset

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.evento_parar)

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)

            def deve_parar():
                return win32event.WaitForSingleObject(self.evento_parar, 0) == win32event.WAIT_OBJECT_0

            def log(mensagem):
                servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, 0, (mensagem, ""))

            while not deve_parar():
                try:
                    loop_agente(deve_parar, log)
                except Exception as erro:
                    servicemanager.LogMsg(servicemanager.EVENTLOG_ERROR_TYPE, 0, (f"Erro fatal no loop do agente: {erro!r}", ""))
                if win32event.WaitForSingleObject(self.evento_parar, SEGUNDOS_ESPERA_APOS_ERRO * 1000) == win32event.WAIT_OBJECT_0:
                    return

    def main():
        if len(sys.argv) == 1:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(AlphafitusOSTunelPortalService)
            servicemanager.StartServiceCtrlDispatcher()
        else:
            win32serviceutil.HandleCommandLine(AlphafitusOSTunelPortalService)

else:
    def main():
        raise RuntimeError(
            "tunel_portal_service.py só funciona no Windows (usa pywin32) — "
            "em outro sistema, rode loop_agente() diretamente dentro do gerenciador de serviço nativo dele."
        )


if __name__ == "__main__":
    main()
