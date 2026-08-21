"""
Fase 68 — Servidor & Terminais: roda o Alphafitus OS como um SERVIÇO DE
VERDADE do Windows (Painel de Controle > Serviços) — inicia sozinho
quando o Windows liga, mesmo sem ninguém logar, sem nenhuma janela
aberta, e reinicia sozinho se o processo cair (o Windows já faz isso
para qualquer serviço configurado com "recuperação automática").

Por que um módulo separado, e não só "rodar run.py escondido": um
serviço do Windows de verdade precisa responder ao protocolo de controle
de serviços do Windows (SCM — Service Control Manager: avisar "estou
iniciando", "estou rodando", aceitar o pedido de "pare agora" etc.) — um
processo comum rodando escondido (ex.: via um atalho "minimizado") NÃO é
um serviço, não sobrevive a logoff, não reinicia sozinho se cair, e o
Windows não sabe geri-lo. Fazer isso direito exige a biblioteca `pywin32`
(pacote Python que dá acesso às APIs do Windows) — só existe no Windows
(nunca no Linux/Mac, e por isso nunca instalada neste ambiente de
desenvolvimento em nuvem) e só é necessária na máquina escolhida como
"servidor" (ver requirements.txt: `pywin32 ; sys_platform == "win32"`).

Por isso os imports de pywin32 ficam DENTRO de um `if os.name == "nt":`
— assim este arquivo continua podendo ser IMPORTADO (para os testes
automatizados da função `ler_variaveis_de_config_ambiente`, que não
depende de nada do Windows) em qualquer sistema operacional; só
INSTANCIAR/RODAR o serviço de verdade exige estar no Windows com o
pywin32 instalado.

Uso (dentro do venv, num Prompt de Comando/PowerShell como
Administrador — registrar ou remover um serviço do Windows sempre exige
direitos de administrador):

    venv\\Scripts\\python service_windows.py install
    venv\\Scripts\\python service_windows.py start
    venv\\Scripts\\python service_windows.py stop
    venv\\Scripts\\python service_windows.py remove

(Os scripts instalar_servico.bat / iniciar_servico.bat / parar_servico.bat
/ remover_servico.bat, ao lado deste arquivo, são atalhos amigáveis para
esses mesmos comandos — cuidam de ativar o venv sozinhos.)
"""
import os

NOME_SERVICO = "AlphafitusOS"
NOME_EXIBICAO = "Alphafitus OS (Servidor)"
DESCRICAO_SERVICO = (
    "Mantem o Alphafitus OS rodando em segundo plano e disponivel na rede, "
    "iniciando sozinho junto com o Windows. Para configurar backups, "
    "usuarios e demais opcoes, acesse pelo navegador em "
    "http://localhost:5000 (ou pelo endereco desta maquina, a partir de "
    "outros computadores da rede)."
)

# Porta e host usados pelo servidor — mesmos valores do waitress-serve
# chamado por iniciar.bat (ver a nota de escopo sobre 0.0.0.0 em
# iniciar.bat e no README, seção "Fase 68 — Servidor e Terminais").
HOST_PADRAO = "0.0.0.0"
PORTA_PADRAO = 5000


def ler_variaveis_de_config_ambiente(caminho_config_ambiente_bat):
    """Lê `config_ambiente.bat` (gerado por iniciar.bat na primeira
    execução, com linhas `set VAR=valor`) SEM depender de rodar o
    `cmd.exe` de verdade — um parser simples de texto, de propósito,
    porque um serviço do Windows não passa por um shell de batch (roda
    o próprio `python.exe` diretamente), então precisa carregar essas
    variáveis (ALPHAFITUS_JWT_SECRET, ALPHAFITUS_DB_PATH,
    ALPHAFITUS_ADMIN_EMAIL) de outro jeito antes de importar `run.py`.

    Ser um parser puro (sem nenhum import do Windows) é proposital —
    assim dá para testar esta função em qualquer sistema operacional,
    sem precisar de um Windows de verdade para verificar que o formato
    `set CHAVE=valor` é interpretado corretamente."""
    variaveis = {}
    if not os.path.isfile(caminho_config_ambiente_bat):
        return variaveis
    with open(caminho_config_ambiente_bat, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha.lower().startswith("set "):
                continue
            resto = linha[4:]
            if "=" not in resto:
                continue
            chave, _, valor = resto.partition("=")
            # `_ambiente.bat`/o instalador geram linhas no formato
            # `set "CHAVE=valor"` (aspas envolvendo o par inteiro, sintaxe
            # padrão do cmd.exe para lidar com valores com espaço/caracteres
            # especiais) — sem este strip, a aspa de abertura ficava colada
            # no início da CHAVE e a de fechamento no fim do VALOR,
            # nunca batendo com o nome real da variável de ambiente
            # (bug real: o Serviço do Windows sempre caía nos valores
            # padrão do código, silenciosamente, em vez de ler o que
            # `set "ALPHAFITUS_JWT_SECRET=..."` realmente gravou).
            chave = chave.strip().strip('"')
            valor = valor.strip().strip('"')
            if chave:
                variaveis[chave] = valor
    return variaveis


def preparar_ambiente(pasta_instalacao):
    """Carrega as variáveis de `config_ambiente.bat` no `os.environ` do
    processo do serviço, sem sobrescrever alguma que já tenha sido
    definida por fora (decisão deliberada, só deste caminho — dá para
    um administrador sobrepor uma variável só para o Serviço do Windows,
    via as propriedades do serviço ou uma variável de ambiente do
    sistema, sem precisar editar o arquivo). Devolve o dicionário lido
    (útil para os testes conferirem o que foi carregado)."""
    caminho = os.path.join(pasta_instalacao, "config_ambiente.bat")
    variaveis = ler_variaveis_de_config_ambiente(caminho)
    for chave, valor in variaveis.items():
        os.environ.setdefault(chave, valor)
    return variaveis


if os.name == "nt":
    import socket
    import sys
    import threading

    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class AlphafitusOSService(win32serviceutil.ServiceFramework):
        _svc_name_ = NOME_SERVICO
        _svc_display_name_ = NOME_EXIBICAO
        _svc_description_ = DESCRICAO_SERVICO

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.evento_parar = win32event.CreateEvent(None, 0, 0, None)
            self.servidor = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            # Sinaliza a thread do servidor para encerrar (ver
            # `_rodar_servidor` abaixo) e desperta o `WaitForSingleObject`
            # de `SvcDoRun`, que é quem realmente devolve o controle ao
            # SCM (Service Control Manager) — nota de escopo: este é um
            # encerramento "melhor esforço" (fecha o socket de escuta e
            # deixa o processo do serviço terminar), no mesmo espírito
            # de fechar a janela do iniciar.bat/apertar Ctrl+C hoje — não
            # é um risco NOVO introduzido pelo serviço, é o mesmo
            # comportamento de sempre, só que agora também acionável
            # pelo Painel de Controle > Serviços.
            try:
                if self.servidor is not None:
                    self.servidor.close()
            except Exception:
                pass
            win32event.SetEvent(self.evento_parar)

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            self._rodar_servidor()

        def _rodar_servidor(self):
            pasta_instalacao = os.path.dirname(os.path.abspath(__file__))
            os.chdir(pasta_instalacao)
            preparar_ambiente(pasta_instalacao)

            # Mesma restauração pendente que run.py trata hoje — o
            # serviço passa pelo mesmo caminho, porque ele TAMBÉM é uma
            # forma de "iniciar o Alphafitus OS" (ver run.py e a nota de
            # escopo em migrations/schema_fase67.sql).
            from app import backup_service, create_app
            from app import db as db_module

            resultado_restauracao = db_module.aplicar_restauracao_pendente_se_houver()
            if resultado_restauracao:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE, 0,
                    ("Restauracao de backup pendente aplicada: %r" % (resultado_restauracao,), ""),
                )
            db_module.init_db()

            app = create_app()
            backup_service.iniciar_agendador_em_background()

            import waitress
            from waitress.server import create_server

            host = os.environ.get("ALPHAFITUS_HOST", HOST_PADRAO)
            porta = int(os.environ.get("ALPHAFITUS_PORTA", PORTA_PADRAO))
            self.servidor = create_server(app, host=host, port=porta)

            # `server.run()` é bloqueante (é o próprio laço de eventos do
            # waitress) — roda numa thread separada para o thread
            # principal do serviço poder ficar livre esperando o sinal
            # de parada do SCM em `win32event.WaitForSingleObject` logo
            # abaixo, exatamente como o exemplo oficial de serviço do
            # pywin32 recomenda.
            thread_servidor = threading.Thread(target=self.servidor.run, daemon=True)
            thread_servidor.start()

            win32event.WaitForSingleObject(self.evento_parar, win32event.INFINITE)

    def main():
        if len(sys.argv) == 1:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(AlphafitusOSService)
            servicemanager.StartServiceCtrlDispatcher()
        else:
            win32serviceutil.HandleCommandLine(AlphafitusOSService)

else:
    def main():
        raise RuntimeError(
            "service_windows.py só funciona no Windows (usa a biblioteca pywin32, "
            "que só existe lá) — em outro sistema operacional, rode 'python run.py' "
            "diretamente, ou use um gerenciador de serviço nativo do seu sistema "
            "(systemd no Linux, launchd no macOS)."
        )


if __name__ == "__main__":
    main()
