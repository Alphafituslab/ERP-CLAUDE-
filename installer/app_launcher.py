"""
Ponto de entrada do instalador REAL (.exe, via PyInstaller + Inno Setup) —
substitui, num único executável autônomo, o que hoje é feito por
`_ambiente.bat` + `iniciar.bat`: gerar a chave de segurança na primeira
execução, preparar o banco, garantir o usuário administrador e subir o
servidor waitress. Diferente da instalação "manual" (venv, `pip install`),
este launcher não precisa de Python instalado na máquina — o PyInstaller já
empacota um interpretador Python + todas as dependências dentro do próprio
`.exe`.

O arquivo de configuração gerado (`config_ambiente.bat`) mantém o MESMO
formato de texto (`set CHAVE=valor`) que `service_windows.py` já sabe ler
(`ler_variaveis_de_config_ambiente`) — não é executado como script, é só um
arquivo de texto reaproveitando um formato já compatível com o Serviço do
Windows, para as duas formas de rodar o sistema (em primeiro plano, por
este launcher, ou como Serviço) lerem exatamente a mesma fonte de verdade.
"""
import os
import socket
import sys


def pasta_instalacao():
    """Pasta onde o .exe (ou, rodando sem empacotar, este arquivo) está —
    é ao lado dela que `config_ambiente.bat` e `data/` vivem."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def pasta_whatts_bundled_pai():
    """Fase 123 (Parte 2) — pasta-mãe de `whatts_bundled/`. NÃO é a mesma
    coisa que `pasta_instalacao()`: aquela aponta pra pasta do PRÓPRIO
    .exe (onde `config_ambiente.bat`/`data/` — arquivos do USUÁRIO —
    devem viver, ao lado do executável, editáveis/visíveis). Os módulos
    Python empacotados (como `whatts_bundled/`, via `datas` no .spec) vão
    parar dentro de `sys._MEIPASS` quando congelado pelo PyInstaller —
    que, com `contents_directory='.'` no .spec, ainda assim resolveu para
    uma subpasta `_internal/` nesta versão do PyInstaller (6.x), diferente
    da pasta do .exe. Rodando direto (sem empacotar, ex.: testes deste
    projeto), `sys._MEIPASS` não existe — cai para a pasta deste arquivo,
    onde `whatts_bundled/` já é vizinha de verdade."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", pasta_instalacao())
    # Não empacotado: este arquivo vive em installer/, whatts_bundled/ é
    # irmã da RAIZ do projeto (um nível acima de installer/).
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gerar_config_ambiente_se_necessario(pasta):
    caminho = os.path.join(pasta, "config_ambiente.bat")
    if os.path.isfile(caminho):
        return
    import secrets

    chave = secrets.token_hex(32)
    # Fase 123 — pedido do usuário: banco criptografado de verdade
    # (SQLCipher), não só um .db comum. Numa instalação NOVA (é exatamente
    # o caso coberto por esta função — só roda quando config_ambiente.bat
    # ainda não existe) o banco também ainda não existe, então esta chave
    # nasce e é usada desde a primeira escrita — nunca precisa de migração
    # como aconteceu na instalação já existente (feita à mão, uma vez).
    chave_db = secrets.token_hex(32)
    db_path = os.path.join(pasta, "data", "alphafitus.db")
    print("Gerando a chave de segurança deste computador (primeira execução)...")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("rem Gerado automaticamente pelo Alphafitus OS na primeira\n")
        f.write("rem execucao deste computador. NAO apague nem compartilhe\n")
        f.write("rem este arquivo: quem tiver a chave abaixo consegue forjar\n")
        f.write("rem sessoes de login do sistema, e quem tiver ALPHAFITUS_DB_KEY\n")
        f.write("rem consegue abrir o banco de dados inteiro.\n")
        f.write(f'set "ALPHAFITUS_JWT_SECRET={chave}"\n')
        f.write('set "ALPHAFITUS_ADMIN_EMAIL=admin@alphafitus.com.br"\n')
        f.write(f'set "ALPHAFITUS_DB_PATH={db_path}"\n')
        f.write(f'set "ALPHAFITUS_DB_KEY={chave_db}"\n')
        # Fase 123 — sincronização de senha do admin com o Whatts/
        # Protocolo/Memorial (ver app/senha_sync_service.py) é OPCIONAL e
        # específica de instalações que também têm esses sistemas
        # vendorizados rodando — por isso não entra aqui no template
        # padrão, só documentada: ALPHAFITUS_SYNC_PROTOCOLO_URL,
        # ALPHAFITUS_SYNC_PROTOCOLO_MASTER, ALPHAFITUS_SYNC_MEMORIAL_URL,
        # ALPHAFITUS_SYNC_MEMORIAL_SECRET (adicionar manualmente neste
        # arquivo, ou direto no config_ambiente.bat já existente, quando
        # essa integração for desejada).


def carregar_config_ambiente(pasta):
    # Reaproveita o mesmo parser que o Serviço do Windows já usa — nunca
    # duas implementações do mesmo formato de arquivo (ver a nota de
    # escopo em service_windows.py sobre esse mesmo raciocínio).
    import service_windows

    variaveis = service_windows.ler_variaveis_de_config_ambiente(os.path.join(pasta, "config_ambiente.bat"))
    for chave, valor in variaveis.items():
        os.environ.setdefault(chave, valor)


def detectar_ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main():
    # Sem isso, o bootloader do PyInstaller pode manter stdout em modo
    # bufferizado mesmo com uma janela de console de verdade — o mais
    # crítico de tudo (a senha do administrador gerada na primeira
    # execução) só apareceria depois de fechar o programa, tarde demais.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    pasta = pasta_instalacao()
    os.chdir(pasta)

    gerar_config_ambiente_se_necessario(pasta)
    carregar_config_ambiente(pasta)

    print("=" * 64)
    print("  Alphafitus OS - Iniciando")
    print("=" * 64)

    from app import backup_service, create_app
    from app import db as db_module

    resultado_restauracao = db_module.aplicar_restauracao_pendente_se_houver()
    if resultado_restauracao:
        print(f"Restauração de backup pendente aplicada: {resultado_restauracao}")

    print("Preparando o banco de dados (criando/atualizando o schema)...")
    db_module.init_db()

    print("Verificando o usuário administrador...")
    import seed

    seed.rodar_seed()

    app = create_app()
    backup_service.iniciar_agendador_em_background()

    ip_local = detectar_ip_local()
    print()
    print("=" * 64)
    print("  Alphafitus OS está iniciando o servidor...")
    print()
    print("  Neste computador, acesse:      http://localhost:5000")
    if ip_local:
        print("  Nos outros computadores/celulares da rede, acesse:")
        print(f"                                  http://{ip_local}:5000")
        print()
        print(f'  Use esse segundo endereço ({ip_local}) ao instalar um')
        print('  "Terminal" em outro computador (Terminal_Instalar.bat).')
    else:
        print("  Não consegui detectar automaticamente o endereço de rede")
        print("  deste computador. Rode 'ipconfig' numa outra janela para")
        print("  descobrir o endereço IPv4 e use-o nos outros computadores.")
    print()
    print("  NÃO FECHE esta janela enquanto o Alphafitus OS estiver em uso -")
    print("  fechar esta janela desliga o servidor para todo mundo.")
    print("=" * 64)
    print()

    # Fase 123 (Parte 2) — módulo WhatsApp (Whatts Inbox) incluso, num
    # segundo servidor (porta 5050) dentro deste mesmo processo — ver
    # comentário completo em app_launcher_tray.py. Isolado em try/except:
    # uma falha aqui nunca impede o AlphafitusOS de subir normalmente.
    try:
        sys.path.insert(0, os.path.join(pasta_whatts_bundled_pai(), "whatts_bundled"))
        import iniciar_whatts_bundled

        if iniciar_whatts_bundled.iniciar_em_thread(pasta):
            print("  Módulo WhatsApp (Whatts Inbox) também disponível em: http://localhost:5050")
    except Exception as erro_whatts:
        print(f"  Aviso: módulo WhatsApp (Whatts Inbox) não pôde ser iniciado ({erro_whatts}) — AlphafitusOS continua normalmente.")

    import waitress

    # Fase 111 — Arquitetura Servidor + Terminais: o padrão implícito do
    # Waitress é 4 threads, pensado pra um servidor de uso só local; agora
    # que várias estações usam este mesmo servidor pela rede o dia todo,
    # 8 dá mais folga para requisições simultâneas sem fila.
    waitress.serve(app, host="0.0.0.0", port=5000, threads=8)


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print()
        print(f"ERRO: {erro}")
        input("Pressione Enter para fechar...")
        raise
