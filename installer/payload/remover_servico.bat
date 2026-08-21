@echo off
setlocal
chcp 65001 >nul
title Alphafitus OS - Remover Servico do Windows
cd /d "%~dp0"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================================
echo   Alphafitus OS - Remover Servico do Windows
echo ================================================================
echo.
echo Isso NAO desinstala o Alphafitus OS - so volta a exigir abrir
echo manualmente pelo atalho comum "Alphafitus OS", em vez de iniciar
echo sozinho com o Windows.
echo.

"%~dp0AlphafitusOS_Servico.exe" stop >nul 2>&1
"%~dp0AlphafitusOS_Servico.exe" remove
if errorlevel 1 (
    echo.
    echo ERRO ao remover o servico. Veja a mensagem acima.
    pause
    exit /b 1
)

echo.
echo Servico removido.
pause
