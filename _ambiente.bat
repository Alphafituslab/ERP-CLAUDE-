@echo off
rem ================================================================
rem Script INTERNO do Alphafitus OS - nao precisa ser aberto direto.
rem
rem Chamado por iniciar.bat e pelos atalhos de gerenciar o Servico do
rem Windows (instalar_servico.bat etc.). Garante que existe um
rem ambiente virtual Python (venv) com as dependencias do sistema
rem instaladas, e garante que a chave de seguranca (config_ambiente.bat)
rem foi gerada e esta carregada nesta janela.
rem
rem Repetir isso em varios arquivos .bat daria margem a duas copias
rem saindo dessincronizadas - por isso so existe aqui, e os outros
rem arquivos chamam "call _ambiente.bat" no comeco.
rem ================================================================

rem Prefere o "python" comum do PATH (o mesmo que roda quando voce digita
rem "python" direto no terminal), mas so aceita se a versao estiver
rem entre 3.9 e 3.13 - a faixa onde TODAS as bibliotecas do sistema ja
rem tem pacote pronto (.whl) publicado. Uma versao mais nova (ex.: 3.14,
rem ou uma 3.15 de pre-lancamento/beta) costuma ainda nao ter pacote
rem pronto de bibliotecas com codigo C (o `lxml`, usado por baixo dos
rem panos pelo `img2pdf` para montar PDFs a partir de imagens), o que
rem forca o Windows a tentar COMPILAR na hora e falhar pedindo o
rem "Microsoft Visual C++ Build Tools" - foi exatamente isso que
rem aconteceu no primeiro teste real desta instalacao, mesmo com um
rem Python "bom" tambem presente na maquina, porque o "py -3" do
rem launcher do Windows sempre escolhe a MAIOR versao registrada nele
rem (a beta), nao a mais adequada.
set "PYTHON_CMD="
set "PYTHON_OK="

where python >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"
if defined PYTHON_CMD for /f "delims=" %%r in ('%PYTHON_CMD% -c "import sys;print(1 if (3,9)<=sys.version_info[:2]<=(3,13) else 0)" 2^>nul') do set "PYTHON_OK=%%r"
if not "%PYTHON_OK%"=="1" set "PYTHON_CMD="

if not defined PYTHON_CMD (
    for %%v in (3.13 3.12 3.11 3.10 3.9) do (
        if not defined PYTHON_CMD (
            py -%%v --version >nul 2>nul
            if not errorlevel 1 set "PYTHON_CMD=py -%%v"
        )
    )
)

rem Ja existe uma copia PRIVADA do Python, baixada e instalada por este
rem mesmo script numa execucao anterior? Reaproveita, sem baixar de novo.
if not defined PYTHON_CMD (
    if exist "%~dp0python_privado\python.exe" set "PYTHON_CMD="%~dp0python_privado\python.exe""
)

rem Nenhuma versao boa encontrada nesta maquina: baixa e instala uma
rem copia PRIVADA do Python 3.12 so para o Alphafitus OS usar - fica
rem isolada dentro da propria pasta de instalacao, sem mexer no Python
rem que a pessoa ja tem nem no PATH do sistema.
if not defined PYTHON_CMD (
    echo Nao encontrei uma versao "estavel" e conhecida do Python nesta
    echo maquina - baixando uma copia PRIVADA do Python 3.12 so para o
    echo Alphafitus OS usar ^(nao mexe no Python que voce ja tem
    echo instalado^). Precisa de internet e leva um a dois minutos, so
    echo na primeira vez...
    set "PYTHON_INSTALADOR=%TEMP%\alphafitus_python_instalador.exe"
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%PYTHON_INSTALADOR%' -UseBasicParsing } catch { exit 1 }"
    if not exist "%PYTHON_INSTALADOR%" (
        echo.
        echo ERRO: nao consegui baixar o Python automaticamente ^(sem
        echo internet nesta maquina, ou algum bloqueio de rede/antivirus^).
        echo.
        echo Instale manualmente o Python 3.12 ou 3.13 em
        echo https://www.python.org/downloads/ ^(marcando "Add python.exe
        echo to PATH"^) e rode este atalho de novo.
        exit /b 1
    )
    echo Instalando o Python 3.12 ^(copia privada, so para o Alphafitus
    echo OS - nao interfere no resto do computador^)...
    "%PYTHON_INSTALADOR%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=0 TargetDir="%~dp0python_privado"
    del "%PYTHON_INSTALADOR%" >nul 2>nul
    if not exist "%~dp0python_privado\python.exe" (
        echo.
        echo ERRO ao instalar o Python automaticamente. Instale
        echo manualmente o Python 3.12 ou 3.13 em
        echo https://www.python.org/downloads/ ^(marcando "Add python.exe
        echo to PATH"^) e rode este atalho de novo.
        exit /b 1
    )
    set "PYTHON_CMD="%~dp0python_privado\python.exe""
)

if not defined PYTHON_CMD (
    echo ERRO: nao encontrei nem consegui instalar o Python nesta
    echo maquina.
    echo.
    echo Instale o Python 3 ^(https://www.python.org/downloads/^) e marque
    echo a opcao "Add python.exe to PATH" durante a instalacao. Depois,
    echo rode este atalho de novo.
    exit /b 1
)
echo Usando Python: & %PYTHON_CMD% --version

if not exist "%~dp0venv\Scripts\activate.bat" (
    echo Criando o ambiente Python pela primeira vez ^(venv^)...
    %PYTHON_CMD% -m venv "%~dp0venv"
    if errorlevel 1 (
        echo ERRO ao criar o ambiente virtual. Veja a mensagem acima.
        exit /b 1
    )
)
call "%~dp0venv\Scripts\activate.bat"

if not exist "%~dp0venv\.dependencias_instaladas" (
    echo Instalando os componentes do sistema ^(primeira vez - precisa
    echo de internet e pode levar alguns minutos^)...
    python -m pip install --upgrade pip >nul
    python -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo ERRO ao instalar as dependencias. Duas causas comuns:
        echo.
        echo   1^) Sem internet nesta maquina - verifique a conexao e
        echo      tente de novo.
        echo.
        echo   2^) A mensagem acima menciona "Microsoft Visual C++" ou
        echo      "failed building wheel" - isso normalmente acontece
        echo      quando o Python instalado nesta maquina e uma versao
        echo      muito nova/experimental ^(pre-lancamento^), que ainda
        echo      nao tem pacote pronto de alguma biblioteca, entao o
        echo      Windows tenta compilar na hora e nao consegue. A
        echo      solucao mais simples e instalar uma versao "estavel"
        echo      do Python ^(ex.: 3.12 ou 3.13^) pelo site oficial
        echo      https://www.python.org/downloads/ ^(marcando "Add
        echo      python.exe to PATH"^), apagar a pasta "venv" aqui
        echo      dentro desta instalacao, e rodar este atalho de novo -
        echo      da proxima vez o sistema vai preferir a versao
        echo      estavel automaticamente, mesmo com as duas instaladas.
        echo.
        exit /b 1
    )
    echo ok> "%~dp0venv\.dependencias_instaladas"
)

if not exist "%~dp0config_ambiente.bat" (
    echo Gerando a chave de seguranca deste computador ^(primeira vez^)...
    for /f "delims=" %%k in ('python -c "import secrets;print(secrets.token_hex(32))"') do set "NOVA_CHAVE=%%k"
    if not defined NOVA_CHAVE (
        echo ERRO ao gerar a chave de seguranca.
        exit /b 1
    )
    > "%~dp0config_ambiente.bat" (
        echo @echo off
        echo rem Gerado automaticamente pelo Alphafitus OS na primeira
        echo rem execucao deste computador. NAO apague nem compartilhe
        echo rem este arquivo: quem tiver a chave abaixo consegue forjar
        echo rem sessoes de login do sistema. Se precisar trocar o e-mail
        echo rem do administrador inicial, edite a linha abaixo ANTES da
        echo rem primeira vez que iniciar o sistema.
        echo set "ALPHAFITUS_JWT_SECRET=%NOVA_CHAVE%"
        echo set "ALPHAFITUS_ADMIN_EMAIL=admin@alphafitus.com.br"
        echo set "ALPHAFITUS_DB_PATH=%~dp0data\alphafitus.db"
    )
)
call "%~dp0config_ambiente.bat"

exit /b 0
