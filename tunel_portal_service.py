"""
Fase 138 — Terceirização Premium: túnel do portal do cliente como Serviço
de VERDADE do Windows (não Tarefa Agendada).

Contexto (ver [[project_terceirizacao_premium]] na memória da sessão que
escreveu isto, e o plano completo em
`C:\\Users\\Oitech\\.claude\\plans\\curious-whistling-moonbeam.md`): o
portal do cliente da Terceirização Premium só é alcançável de fora porque
existe um túnel SSH reverso desta máquina até o VPS
(`whatts.alphafitus.com.br:9445`, Caddy path-restrito a `/portal/*`) — sem
esse túnel de pé, o link do cliente simplesmente não abre.

** LIMITAÇÃO CONHECIDA, NÃO RESOLVIDA (ver a memória linkada acima pro
relato completo) **: este módulo está tecnicamente correto e FUNCIONA até
certo ponto — o serviço sobe, autentica no VPS, e a porta remota fica
escutando de verdade (confirmado com `ss -tlnp` no VPS). Mas dados reais
não atravessam o túnel quando ele é mantido por este serviço (nem por uma
Tarefa Agendada, testada antes e removida pelo mesmo motivo) — só quando o
MESMO comando `ssh` é rodado interativamente (sessão de usuário de
verdade, primeiro plano). Duas causas raiz REAIS já foram encontradas e
corrigidas no caminho (path de `__file__` em módulo congelado; dono
incorreto do arquivo da chave privada rejeitado pelo OpenSSH do Windows)
— mas depois de corrigir as duas, o sintoma final (porta escuta, dados não
passam) continuou idêntico. Suspeita não confirmada: Windows Defender
tratando processos SYSTEM/não-interativos de forma diferente pra esse tipo
de tráfego. Enquanto isso não for resolvido, o túnel real de produção
continua sendo mantido manualmente (processo solto, ver a memória) — este
serviço fica no repositório pronto pra retomar a investigação, mas NÃO
está instalado/ativo em produção.

Uso (dentro do venv, num Prompt de Comando/PowerShell como Administrador):

    venv\\Scripts\\python tunel_portal_service.py install
    venv\\Scripts\\python tunel_portal_service.py start
    venv\\Scripts\\python tunel_portal_service.py stop
    venv\\Scripts\\python tunel_portal_service.py remove
"""
import os
import shutil
import subprocess
import sys


def _pasta_instalacao():
    """Fase 138 — achado real durante o teste: `__file__` de um módulo
    congelado pelo PyInstaller (com `noarchive=True`/`contents_directory=
    '.'`, ver installer/alphafitus.spec) resolve para DENTRO de
    `_internal\\`, não para a pasta real de instalação (onde
    `tunel_portal\\chave_tunel` de verdade mora, ao lado dos .exe) — isso
    fazia o `ssh.exe` ser chamado com um caminho de chave que não existe
    (`FileNotFoundError`), sempre, silenciosamente reiniciando em loop.
    `sys.executable` (o caminho do .exe em si) é a base certa quando
    congelado; só cai para `__file__` quando rodando como script .py
    puro (nunca vai acontecer no serviço real, só em teste local)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

NOME_SERVICO = "AlphafitusOSTunelPortal"
NOME_EXIBICAO = "Alphafitus OS (Tunel do Portal do Cliente - Terceirizacao)"
DESCRICAO_SERVICO = (
    "Mantem aberto o tunel SSH reverso que expoe SO o Portal do Cliente "
    "(Terceirizacao Premium) publicamente pelo VPS da Alphafitus, sem "
    "expor o resto do sistema. Sem este servico rodando, o link enviado "
    "ao cliente nao abre."
)

# Mesmos valores usados quando o túnel foi testado manualmente pela
# primeira vez (ver terceirizacao.py::URL_BASE_PORTAL_PUBLICO) — casa com
# o bloco `whatts.alphafitus.com.br:9445` do Caddy no VPS.
VPS_HOST = "46.202.151.252"
VPS_USUARIO = "portaltunnel"
PORTA_REMOTA = 18500
PORTA_LOCAL = 5000
NOME_ARQUIVO_CHAVE = "chave_tunel"  # dentro de tunel_portal/, ao lado deste arquivo/instalação
SEGUNDOS_ENTRE_TENTATIVAS = 15


def _caminho_chave(pasta_instalacao):
    return os.path.join(pasta_instalacao, "tunel_portal", NOME_ARQUIVO_CHAVE)


def _caminho_ssh():
    """Resolve o ssh.exe do PATH primeiro (mesmo binário usado quando o
    túnel foi testado manualmente com sucesso); cai pro caminho padrão do
    OpenSSH Client embutido no Windows 10/11 se não encontrar no PATH —
    nunca assume que é a MESMA máquina de desenvolvimento."""
    encontrado = shutil.which("ssh")
    if encontrado:
        return encontrado
    caminho_padrao = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe")
    if os.path.isfile(caminho_padrao):
        return caminho_padrao
    raise RuntimeError(
        "ssh.exe não encontrado (nem no PATH, nem no OpenSSH Client padrão do Windows) — "
        "instale o 'Cliente OpenSSH' em Configurações > Aplicativos > Recursos Opcionais."
    )


def montar_comando_tunel(pasta_instalacao):
    # Fase 138 — o serviço roda como LocalSystem (conta sem perfil de
    # usuário de verdade: sem HOME/USERPROFILE utilizável) — sem apontar
    # explicitamente onde gravar o known_hosts, o ssh.exe não sabia onde
    # persistir a chave do host na primeira conexão e o túnel nunca
    # chegava a conectar de verdade (ficava "Running" no SCM, mas o
    # processo ssh interno travava). Aponta pro MESMO lugar onde já fica
    # a chave privada — pasta que o serviço garantidamente consegue ler
    # e escrever.
    caminho_known_hosts = os.path.join(pasta_instalacao, "tunel_portal", "known_hosts")
    return [
        _caminho_ssh(),
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={caminho_known_hosts}",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
        "-i", _caminho_chave(pasta_instalacao),
        "-R", f"127.0.0.1:{PORTA_REMOTA}:localhost:{PORTA_LOCAL}",
        "-N",
        f"{VPS_USUARIO}@{VPS_HOST}",
    ]


if os.name == "nt":
    import sys
    import threading

    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class AlphafitusOSTunelPortalService(win32serviceutil.ServiceFramework):
        _svc_name_ = NOME_SERVICO
        _svc_display_name_ = NOME_EXIBICAO
        _svc_description_ = DESCRICAO_SERVICO

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.evento_parar = win32event.CreateEvent(None, 1, 0, None)  # manual-reset
            self.processo_atual = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.evento_parar)
            try:
                if self.processo_atual is not None and self.processo_atual.poll() is None:
                    self.processo_atual.terminate()
            except Exception:
                pass

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            self._loop_manter_tunel()

        def _loop_manter_tunel(self):
            pasta_instalacao = _pasta_instalacao()
            comando = montar_comando_tunel(pasta_instalacao)

            while win32event.WaitForSingleObject(self.evento_parar, 0) != win32event.WAIT_OBJECT_0:
                try:
                    servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, 0, ("Conectando o tunel do portal...", ""))
                    self.processo_atual = subprocess.Popen(
                        comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    # Espera o processo cair OU o serviço ser mandado parar
                    # — o que vier primeiro. `Popen.wait` é bloqueante puro
                    # (não escuta o evento de parada), então fazemos
                    # polling curto em vez disso.
                    while self.processo_atual.poll() is None:
                        if win32event.WaitForSingleObject(self.evento_parar, 2000) == win32event.WAIT_OBJECT_0:
                            self.processo_atual.terminate()
                            return
                except Exception as erro:
                    servicemanager.LogMsg(servicemanager.EVENTLOG_ERROR_TYPE, 0, (f"Erro no tunel do portal: {erro!r}", ""))

                servicemanager.LogMsg(servicemanager.EVENTLOG_WARNING_TYPE, 0, ("Tunel do portal caiu - tentando de novo...", ""))
                if win32event.WaitForSingleObject(self.evento_parar, SEGUNDOS_ENTRE_TENTATIVAS * 1000) == win32event.WAIT_OBJECT_0:
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
            "em outro sistema, gerencie o túnel SSH com o gerenciador de serviço nativo dele."
        )


if __name__ == "__main__":
    main()
