@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Alphafitus OS - Servidor
cd /d "%~dp0"

echo ================================================================
echo   Alphafitus OS - Iniciando
echo ================================================================
echo.

call "%~dp0_ambiente.bat"
if errorlevel 1 (
    echo.
    echo Nao foi possivel preparar o ambiente. Veja as mensagens acima.
    echo.
    pause
    exit /b 1
)

echo.
rem Chama init_db() explicitamente, em vez de confiar no "cria sozinho
rem se nao existir" do run.py/seed.py: como este script sempre define
rem ALPHAFITUS_DB_PATH em config_ambiente.bat (util para o Servico do
rem Windows - ver service_windows.py), o proprio seed.py.__main__ nunca
rem cria o schema sozinho (so faz isso quando essa variavel NAO esta
rem definida, assumindo que quem define o caminho na mao ja cuidou do
rem banco por conta propria) - sem este passo, "seed.py" falhava com
rem "no such table" na primeira execucao.
echo Preparando o banco de dados ^(criando/atualizando o schema^)...
python -c "from app import db as db_module; db_module.init_db()"
if errorlevel 1 (
    echo.
    echo ERRO ao preparar o schema do banco de dados. Veja a mensagem acima.
    pause
    exit /b 1
)

echo Verificando o usuario administrador...
python seed.py
if errorlevel 1 (
    echo.
    echo ERRO ao preparar o usuario administrador. Veja a mensagem acima.
    pause
    exit /b 1
)

set "MEU_IP="
for /f "delims=" %%i in ('python -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(0.5);s.connect(('8.8.8.8',80));print(s.getsockname()[0])" 2^>nul') do set "MEU_IP=%%i"

echo.
echo ================================================================
echo   Alphafitus OS esta iniciando o servidor...
echo.
if defined MEU_IP (
    echo   Neste computador, acesse:      http://localhost:5000
    echo   Nos outros computadores/celulares da rede, acesse:
    echo                                   http://!MEU_IP!:5000
    echo.
    echo   Use esse segundo endereco ^(!MEU_IP!^) ao instalar um
    echo   "Terminal" em outro computador ^(Terminal_Instalar.bat^).
) else (
    echo   Acesse neste computador:       http://localhost:5000
    echo   Nao consegui detectar automaticamente o endereco de rede
    echo   deste computador. Rode "ipconfig" numa outra janela para
    echo   descobrir o endereco IPv4 e use-o nos outros computadores.
)
echo.
echo   NAO FECHE esta janela enquanto o Alphafitus OS estiver em uso -
echo   fechar esta janela desliga o servidor para todo mundo.
echo ================================================================
echo.

waitress-serve --host=0.0.0.0 --port=5000 run:app

echo.
echo O servidor foi encerrado.
pause
