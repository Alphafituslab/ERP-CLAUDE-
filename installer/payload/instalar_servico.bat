@echo off
setlocal
chcp 65001 >nul
title Alphafitus OS - Instalar Servico do Windows
cd /d "%~dp0"

rem Registrar/remover um Servico do Windows sempre exige Administrador -
rem em vez de pedir para o usuario clicar com o botao direito e escolher
rem "Executar como administrador" (facil de esquecer), este atalho se
rem eleva sozinho via UAC quando necessario.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================================
echo   Alphafitus OS - Instalar como Servico do Windows
echo ================================================================
echo.
echo Isso faz o Alphafitus OS iniciar sozinho junto com o Windows -
echo nao precisa mais abrir "Alphafitus OS" manualmente - e reiniciar
echo sozinho se o computador for reiniciado ou o servico cair.
echo.

"%~dp0AlphafitusOS_Servico.exe" --startup=auto install
if errorlevel 1 (
    echo.
    echo ERRO ao instalar o servico. Veja a mensagem acima.
    pause
    exit /b 1
)

echo.
echo Pronto! O servico foi registrado e vai iniciar sozinho com o
echo Windows a partir de agora. Use o atalho "Iniciar Servico" para
echo coloca-lo no ar agora mesmo, sem precisar reiniciar o computador.
pause
