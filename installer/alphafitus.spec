# -*- mode: python ; coding: utf-8 -*-
# Spec do PyInstaller para o instalador REAL do Alphafitus OS — empacota
# TRÊS executáveis autônomos (nenhum precisa de Python instalado na
# máquina de destino) que compartilham o mesmo diretório de saída:
#   - AlphafitusOS.exe          (installer/app_launcher_tray.py) — modo
#     PADRÃO: sem janela nenhuma, só um ícone na bandeja do Windows. É o
#     que o atalho comum "Alphafitus OS" usa.
#   - AlphafitusOS_Console.exe  (installer/app_launcher.py) — mesma coisa,
#     mas com uma janela de console visível (log em tempo real) — atalho
#     "modo diagnóstico", só para quando algo dá errado e o
#     alphafitus_log.txt não é suficiente para entender o motivo.
#   - AlphafitusOS_Servico.exe  (service_windows.py) — Serviço de verdade
#     do Windows, usado pelos atalhos "Instalar/Iniciar/Parar/Remover
#     Serviço".
#
# `contents_directory='.'` + `noarchive=True`: mantém o layout "chato"
# clássico (tudo solto ao lado do .exe, sem a subpasta `_internal/` que o
# PyInstaller 6+ usa por padrão) e os módulos Python como arquivos de
# verdade em disco (não compactados dentro de um blob) — necessário porque
# `app/db.py`/`app/__init__.py` calculam caminhos (pasta de migrations, do
# frontend) a partir de `__file__`, e isso só funciona se `__file__`
# apontar para um arquivo real no disco, não para uma entrada dentro de um
# arquivo comprimido.
import os

RAIZ_PROJETO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))

datas_comuns = [
    (os.path.join(RAIZ_PROJETO, "frontend"), "frontend"),
    (os.path.join(RAIZ_PROJETO, "migrations"), "migrations"),
    # app_launcher_tray.py carrega isto em tempo de execução (ícone da
    # bandeja) a partir da pasta de instalação — não basta ser só o ícone
    # EMBUTIDO no .exe (esse é só o ícone do ARQUIVO .exe no Explorer).
    (os.path.join(RAIZ_PROJETO, "installer", "icone.ico"), "."),
    # Fase 123 (Parte 2) — módulo WhatsApp incluso (Whatts Inbox,
    # vendorizado em whatts_bundled/): precisa ficar como pasta de
    # arquivos REAIS no disco de saída (mesmo motivo de
    # noarchive=True/contents_directory='.' no topo deste arquivo — o
    # próprio whatts_app/db.py e whatts_app/__init__.py calculam caminhos
    # a partir de `__file__`), por isso datas (não passa pelo PYZ
    # comprimido) para as três pastas relevantes.
    (os.path.join(RAIZ_PROJETO, "whatts_bundled", "whatts_app"), os.path.join("whatts_bundled", "whatts_app")),
    (os.path.join(RAIZ_PROJETO, "whatts_bundled", "frontend"), os.path.join("whatts_bundled", "frontend")),
    (os.path.join(RAIZ_PROJETO, "whatts_bundled", "migrations"), os.path.join("whatts_bundled", "migrations")),
    (os.path.join(RAIZ_PROJETO, "whatts_bundled", "whatts_seed.py"), "whatts_bundled"),
    (os.path.join(RAIZ_PROJETO, "whatts_bundled", "iniciar_whatts_bundled.py"), "whatts_bundled"),
]

hiddenimports_comuns = [
    "waitress",
    "app", "app.routes",
    "win32timezone",  # dependência oculta clássica do pywin32 em serviços
    # Fase 123 (Parte 2) — dependências de terceiros do módulo WhatsApp
    # incluso (Whatts Inbox, vendorizado em whatts_bundled/ — ver `datas`
    # acima). De propósito NÃO colocamos "whatts_app" aqui: como um
    # hiddenimport é resolvido pelo nome do pacote via `pathex` (sem
    # nenhum prefixo de pasta customizado), ele iria parar solto na RAIZ
    # da saída (dist/AlphafitusOS/whatts_app/), não dentro de
    # whatts_bundled/ como o código deste módulo espera — por isso
    # whatts_app inteiro já vai via `datas` (arquivo real, no lugar
    # certo) e só as bibliotecas de TERCEIROS que ele importa (não
    # descobertas automaticamente porque whatts_app nunca entra no grafo
    # de import estático de app_launcher_tray.py/app_launcher.py) entram
    # aqui, resolvidas normalmente a partir do site-packages do venv de
    # build — "requests"/"PyJWT" o AlphafitusOS já usa por conta própria,
    # só "pyotp" é exclusivo do Whatts.
    "pyotp", "requests",
]

hiddenimports_tray = hiddenimports_comuns + ["pystray._win32", "PIL.Image"]

# Nunca usados por este sistema (é uma API web, sem nenhuma janela local)
# — o PyInstaller às vezes puxa tkinter como dependência transitiva
# conservadora de alguma outra biblioteca (ex.: Pillow, usada só para
# gerar PDFs/imagens); excluir explicitamente economiza dezenas de MB
# sem tirar nenhuma funcionalidade real.
excludes_comuns = ["tkinter", "_tkinter"]

block_cipher = None

analise_tray = Analysis(
    [os.path.join(RAIZ_PROJETO, "installer", "app_launcher_tray.py")],
    pathex=[RAIZ_PROJETO, os.path.join(RAIZ_PROJETO, "installer")],
    binaries=[],
    datas=datas_comuns,
    hiddenimports=hiddenimports_tray,
    excludes=excludes_comuns,
    hookspath=[],
    noarchive=True,
)
pyz_tray = PYZ(analise_tray.pure, analise_tray.zipped_data, cipher=block_cipher)
exe_tray = EXE(
    pyz_tray, analise_tray.scripts, [],
    exclude_binaries=True, name="AlphafitusOS", console=False, upx=False,
    icon=os.path.join(RAIZ_PROJETO, "installer", "icone.ico"),
)

analise_launcher = Analysis(
    [os.path.join(RAIZ_PROJETO, "installer", "app_launcher.py")],
    pathex=[RAIZ_PROJETO, os.path.join(RAIZ_PROJETO, "installer")],
    binaries=[],
    datas=datas_comuns,
    hiddenimports=hiddenimports_comuns,
    excludes=excludes_comuns,
    hookspath=[],
    noarchive=True,
)
pyz_launcher = PYZ(analise_launcher.pure, analise_launcher.zipped_data, cipher=block_cipher)
exe_launcher = EXE(
    pyz_launcher, analise_launcher.scripts, [],
    exclude_binaries=True, name="AlphafitusOS_Console", console=True, upx=False,
    icon=os.path.join(RAIZ_PROJETO, "installer", "icone.ico"),
)

analise_servico = Analysis(
    [os.path.join(RAIZ_PROJETO, "service_windows.py")],
    pathex=[RAIZ_PROJETO],
    binaries=[],
    datas=datas_comuns,
    hiddenimports=hiddenimports_comuns,
    excludes=excludes_comuns,
    hookspath=[],
    noarchive=True,
)
pyz_servico = PYZ(analise_servico.pure, analise_servico.zipped_data, cipher=block_cipher)
exe_servico = EXE(
    pyz_servico, analise_servico.scripts, [],
    exclude_binaries=True, name="AlphafitusOS_Servico", console=True, upx=False,
)

# COLLECT junta os três (binários, dados, tudo) num único diretório de
# saída (dist/AlphafitusOS/) — as datas_comuns acima são deduplicadas
# automaticamente pelo PyInstaller, não viram três cópias.
COLLECT(
    exe_tray, analise_tray.binaries, analise_tray.zipfiles, analise_tray.datas,
    exe_launcher, analise_launcher.binaries, analise_launcher.zipfiles, analise_launcher.datas,
    exe_servico, analise_servico.binaries, analise_servico.zipfiles, analise_servico.datas,
    strip=False, upx=False, name="AlphafitusOS", contents_directory=".",
)
