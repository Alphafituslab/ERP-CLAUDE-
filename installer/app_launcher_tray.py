"""
Ponto de entrada do modo "sem janela" — mesma coisa que `app_launcher.py`
faz (gerar config na primeira execução, preparar banco, subir o servidor),
só que roda o servidor numa thread em segundo plano e mostra um ícone na
bandeja do Windows em vez de uma janela de console preta. Pensado para ser
o `AlphafitusOS.exe` padrão do instalador — "Sair" no menu do ícone é a
única forma de desligar o servidor (fechar não existe, não tem janela).

Sem console, `print()` não vai a lugar nenhum visível — por isso tudo aqui
usa `logging` gravando num arquivo (`alphafitus_log.txt`, ao lado do
.exe), e qualquer erro fatal também aparece numa caixa de mensagem do
Windows (via `ctypes`, sem precisar de nenhuma biblioteca de UI extra —
o motivo de excluir `tkinter` do build continua valendo).
"""
import ctypes
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from app_launcher import (
    carregar_config_ambiente,
    detectar_ip_local,
    gerar_config_ambiente_se_necessario,
    pasta_instalacao,
)

MB_ICONERROR = 0x10
MB_ICONINFORMATION = 0x40
MB_OK = 0x0
ERROR_ALREADY_EXISTS = 183


def mostrar_erro_windows(titulo, mensagem):
    try:
        ctypes.windll.user32.MessageBoxW(None, mensagem, titulo, MB_OK | MB_ICONERROR)
    except Exception:
        pass


def ja_esta_rodando():
    """Mutex nomeado do Windows — forma padrão de detectar 'já existe uma
    cópia rodando' sem depender de olhar a porta 5000 (que pode estar
    ocupada por outro motivo). Clicar o atalho de novo enquanto o
    Alphafitus OS já está na bandeja não deve abrir um segundo servidor
    brigando pela mesma porta — só reabre o navegador."""
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\AlphafitusOS_InstanciaUnica")
    return handle != 0 and ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS


def configurar_log(pasta):
    caminho_log = os.path.join(pasta, "alphafitus_log.txt")
    logging.basicConfig(
        filename=caminho_log,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return caminho_log


def main():
    pasta = pasta_instalacao()
    os.chdir(pasta)

    # Precisa vir ANTES de qualquer outra coisa: clicar o atalho de novo
    # com o Alphafitus OS já rodando (esquecendo que ele fica só na
    # bandeja, sem janela visível) não deve abrir um segundo processo
    # disputando a porta 5000 — só reabre o navegador na instância que já
    # está no ar.
    if ja_esta_rodando():
        webbrowser.open("http://localhost:5000")
        return

    caminho_log = configurar_log(pasta)
    logging.info("Alphafitus OS (modo bandeja) iniciando...")

    try:
        gerar_config_ambiente_se_necessario(pasta)
        carregar_config_ambiente(pasta)

        from app import backup_service, create_app
        from app import db as db_module

        resultado_restauracao = db_module.aplicar_restauracao_pendente_se_houver()
        if resultado_restauracao:
            logging.info("Restauração de backup pendente aplicada: %r", resultado_restauracao)

        db_module.init_db()

        import seed

        seed.rodar_seed(imprimir=False)

        app = create_app()
        backup_service.iniciar_agendador_em_background()

        import waitress

        ip_local = detectar_ip_local()
        logging.info("Servidor iniciando em http://0.0.0.0:5000 (rede: %s)", ip_local)

        thread_servidor = threading.Thread(
            # Fase 111 — ver comentário equivalente em app_launcher.py.
            target=lambda: waitress.serve(app, host="0.0.0.0", port=5000, threads=8),
            daemon=True,
        )
        thread_servidor.start()

        # Abre o navegador sozinho no primeiro início — sem isso, clicar o
        # atalho não parece fazer nada visível (o servidor sobe em
        # segundo plano, só o ícone aparece na bandeja), o que já
        # confundiu um usuário real achando que "não abriu".
        #
        # Antes disso era um tempo fixo de 1,5s — funcionava na maioria
        # das vezes, mas com um banco maior (ex.: depois de uma
        # importação grande) o `seed.rodar_seed()`/Waitress podem
        # demorar mais que isso pra ficar pronto, e o navegador abria
        # ANTES do servidor responder — dava erro de conexão na hora,
        # corrigindo sozinho só se o usuário recarregasse a página.
        # Agora espera de verdade o servidor responder (consulta
        # /api/v1/saude a cada 200ms, até 20s) antes de abrir — some o
        # erro sem precisar adivinhar quanto tempo esperar.
        def _abrir_quando_pronto():
            prazo_final = time.monotonic() + 20
            while time.monotonic() < prazo_final:
                try:
                    with urllib.request.urlopen("http://localhost:5000/api/v1/saude", timeout=1) as resp:
                        if resp.status == 200:
                            break
                except (urllib.error.URLError, OSError):
                    pass
                time.sleep(0.2)
            webbrowser.open("http://localhost:5000")

        threading.Thread(target=_abrir_quando_pronto, daemon=True).start()
    except Exception:
        logging.exception("Erro fatal ao iniciar")
        mostrar_erro_windows(
            "Alphafitus OS — erro ao iniciar",
            "Não foi possível iniciar o Alphafitus OS. Detalhes técnicos foram salvos em:\n"
            f"{caminho_log}\n\nMostre este arquivo para o suporte técnico.",
        )
        sys.exit(1)

    _rodar_icone_bandeja(pasta, ip_local)


def _rodar_icone_bandeja(pasta, ip_local):
    import pystray
    from PIL import Image

    caminho_icone = os.path.join(pasta, "icone.ico")
    imagem = Image.open(caminho_icone) if os.path.isfile(caminho_icone) else Image.new("RGB", (64, 64), "steelblue")

    def abrir_navegador(icon=None, item=None):
        webbrowser.open("http://localhost:5000")

    def sair(icon, item):
        logging.info("Encerrando por pedido do usuário (menu da bandeja).")
        icon.stop()
        os._exit(0)

    itens_menu = [pystray.MenuItem("Abrir Alphafitus OS", abrir_navegador, default=True)]
    if ip_local:
        itens_menu.append(
            pystray.MenuItem(f"Endereço na rede: {ip_local}:5000", None, enabled=False)
        )
    itens_menu.append(pystray.Menu.SEPARATOR)
    itens_menu.append(pystray.MenuItem("Sair (para o servidor)", sair))

    icon = pystray.Icon(
        "AlphafitusOS", imagem, "Alphafitus OS — clique para abrir", pystray.Menu(*itens_menu)
    )
    icon.run()


if __name__ == "__main__":
    main()
