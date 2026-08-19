@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Alphafitus OS - Instalar Servico do Windows
cd /d "%~dp0"

echo ================================================================
echo   Alphafitus OS - Instalar como Servico do Windows
echo ================================================================
echo.
echo Isso faz o Alphafitus OS iniciar sozinho junto com o Windows -
echo nao precisa mais abrir "Alphafitus OS" manualmente - e reiniciar
echo sozinho se o computador for reiniciado ou o servico cair.
echo.
echo Esta janela precisa ter sido aberta "Como Administrador".
echo.

call "%~dp0_ambiente.bat"
if errorlevel 1 (
    echo.
    echo Nao foi possivel preparar o ambiente. Veja as mensagens acima.
    pause
    exit /b 1
)

echo.
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

echo.
echo Registrando o servico "AlphafitusOS" no Windows...
python service_windows.py --startup=auto install
if errorlevel 1 (
    echo.
    echo ERRO ao instalar o servico. Confirme que esta janela foi
    echo aberta "Como Administrador" ^(feche e abra de novo pelo atalho,
    echo clicando com o botao direito^) e tente de novo.
    pause
    exit /b 1
)

echo.
echo Pronto! O servico foi registrado e vai iniciar sozinho com o
echo Windows a partir de agora. Use o atalho "Iniciar Servico" para
echo coloca-lo no ar agora mesmo, sem precisar reiniciar o computador.
pause
