@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Alphafitus OS - Instalar Terminal
cd /d "%~dp0"

echo ================================================================
echo   Alphafitus OS - Instalar Terminal (este computador so ACESSA
echo   o sistema, o Alphafitus OS de verdade roda no Servidor)
echo ================================================================
echo.
echo Nao precisa "Executar como administrador" nem ter Python
echo instalado nesta maquina - isso so cria um atalho.
echo.

set /p ENDERECO="Digite o endereco do servidor (ex.: 192.168.1.10:5000): "
if "!ENDERECO!"=="" (
    echo.
    echo Nenhum endereco informado. Cancelado.
    pause
    exit /b 1
)

echo !ENDERECO! | findstr /r "^http" >nul
if errorlevel 1 (
    set "URL=http://!ENDERECO!"
) else (
    set "URL=!ENDERECO!"
)

set "ATALHO_DESKTOP=%USERPROFILE%\Desktop\Alphafitus OS.url"
set "PASTA_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Alphafitus OS"
if not exist "%PASTA_MENU%" mkdir "%PASTA_MENU%"
set "ATALHO_MENU=%PASTA_MENU%\Alphafitus OS.url"

(
    echo [InternetShortcut]
    echo URL=!URL!
) > "%ATALHO_DESKTOP%"
(
    echo [InternetShortcut]
    echo URL=!URL!
) > "%ATALHO_MENU%"

echo.
echo Pronto! Atalho "Alphafitus OS" criado na Area de Trabalho e no
echo Menu Iniciar, apontando para !URL!
echo.
echo Se o endereco do servidor mudar no futuro, rode este mesmo
echo instalador de novo com o endereco novo - ele so atualiza o
echo atalho existente.
pause
