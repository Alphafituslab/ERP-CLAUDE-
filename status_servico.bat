@echo off
chcp 65001 >nul
title Alphafitus OS - Status do Servico
cd /d "%~dp0"

echo Consultando o status do servico "AlphafitusOS" no Windows...
echo.
sc query AlphafitusOS
if errorlevel 1060 (
    echo.
    echo O servico ainda nao foi instalado nesta maquina. Use o atalho
    echo "Instalar como Servico do Windows" primeiro.
)
echo.
pause
