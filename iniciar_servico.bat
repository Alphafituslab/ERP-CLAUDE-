@echo off
chcp 65001 >nul
title Alphafitus OS - Iniciar Servico
cd /d "%~dp0"

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo O Alphafitus OS ainda nao foi preparado nesta maquina. Use
    echo primeiro o atalho "Instalar como Servico do Windows".
    pause
    exit /b 1
)

echo Iniciando o servico "AlphafitusOS"...
python service_windows.py start
if errorlevel 1 (
    echo.
    echo ERRO ao iniciar o servico. Confira se ele ja foi instalado com
    echo o atalho "Instalar como Servico do Windows", e se esta janela
    echo foi aberta "Como Administrador".
) else (
    echo.
    echo Servico iniciado. Use "Status do Servico" para conferir, ou
    echo acesse http://localhost:5000 neste computador.
)
pause
