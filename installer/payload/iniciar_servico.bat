@echo off
setlocal
chcp 65001 >nul
title Alphafitus OS - Iniciar Servico
cd /d "%~dp0"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

"%~dp0AlphafitusOS_Servico.exe" start
if errorlevel 1 (
    echo.
    echo ERRO ao iniciar o servico. Ele precisa estar instalado primeiro
    echo ^(atalho "Instalar como Servico do Windows"^).
    pause
    exit /b 1
)
echo Servico iniciado.
pause
