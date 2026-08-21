# -*- mode: python ; coding: utf-8 -*-
# Spec do PyInstaller para o instalador REAL do Alphafitus OS — empacota
# DOIS executáveis autônomos (nenhum precisa de Python instalado na
# máquina de destino) que compartilham o mesmo diretório de saída:
#   - AlphafitusOS.exe          (installer/app_launcher.py) — modo "janela
#     aberta", usado pelo atalho comum "Alphafitus OS".
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
]

hiddenimports_comuns = [
    "waitress",
    "app", "app.routes",
    "win32timezone",  # dependência oculta clássica do pywin32 em serviços
]

# Nunca usados por este sistema (é uma API web, sem nenhuma janela local)
# — o PyInstaller às vezes puxa tkinter como dependência transitiva
# conservadora de alguma outra biblioteca (ex.: Pillow, usada só para
# gerar PDFs/imagens); excluir explicitamente economiza dezenas de MB
# sem tirar nenhuma funcionalidade real.
excludes_comuns = ["tkinter", "_tkinter"]

block_cipher = None

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
    exclude_binaries=True, name="AlphafitusOS", console=True, upx=False,
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

# COLLECT junta os dois (binários, dados, tudo) num único diretório de
# saída (dist/AlphafitusOS/) — as duas datas_comuns acima são deduplicadas
# automaticamente pelo PyInstaller, não viram duas cópias.
COLLECT(
    exe_launcher, analise_launcher.binaries, analise_launcher.zipfiles, analise_launcher.datas,
    exe_servico, analise_servico.binaries, analise_servico.zipfiles, analise_servico.datas,
    strip=False, upx=False, name="AlphafitusOS", contents_directory=".",
)
