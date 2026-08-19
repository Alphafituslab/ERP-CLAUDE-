@echo off
chcp 65001 >nul
title Alphafitus OS - Parar Servico
cd /d "%~dp0"

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo O Alphafitus OS ainda nao foi preparado nesta maquina. Use
    echo primeiro o atalho "Instalar como Servico do Windows".
    pause
    exit /b 1
)

echo ATENCAO: parar o servico derruba o acesso de todo mundo que
echo estiver usando o Alphafitus OS por essa maquina agora.
echo.
set /p CONFIRMA="Confirma parar o servico? (S/N): "
if /i not "%CONFIRMA%"=="S" (
    echo Cancelado.
    pause
    exit /b 0
)

echo.
echo Parando o servico "AlphafitusOS"...
python service_windows.py stop
if errorlevel 1 (
    echo.
    echo ERRO ao parar o servico. Confira se esta janela foi aberta
    echo "Como Administrador".
) else (
    echo.
    echo Servico parado. Use "Iniciar Servico" para coloca-lo no ar
    echo de novo quando precisar.
)
pause
