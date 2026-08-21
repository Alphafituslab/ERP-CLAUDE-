@echo off
setlocal
chcp 65001 >nul
title Alphafitus OS - Parar Servico
cd /d "%~dp0"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

"%~dp0AlphafitusOS_Servico.exe" stop
if errorlevel 1 (
    echo.
    echo ERRO ao parar o servico. Veja a mensagem acima.
    pause
    exit /b 1
)
echo Servico parado.
pause
