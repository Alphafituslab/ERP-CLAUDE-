@echo off
chcp 65001 >nul
title Alphafitus OS - Status do Servico
echo ================================================================
echo   Alphafitus OS - Status do Servico do Windows
echo ================================================================
echo.
sc query AlphafitusOS
if errorlevel 1060 (
    echo.
    echo O servico ainda nao foi instalado neste computador ^(atalho
    echo "Instalar como Servico do Windows"^).
)
echo.
pause
