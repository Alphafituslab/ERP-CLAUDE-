@echo off
chcp 65001 >nul
title Alphafitus OS - Remover Servico do Windows
cd /d "%~dp0"

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo O Alphafitus OS ainda nao foi preparado nesta maquina - nao ha
    echo servico instalado para remover.
    pause
    exit /b 0
)

echo Isso remove o servico do Windows "AlphafitusOS" ^(o Alphafitus OS
echo deixa de iniciar sozinho com o computador^). Os arquivos e o banco
echo de dados NAO sao apagados - para desinstalar tudo, use
echo "desinstalar.bat" em vez deste atalho.
echo.
set /p CONFIRMA="Confirma remover o servico? (S/N): "
if /i not "%CONFIRMA%"=="S" (
    echo Cancelado.
    pause
    exit /b 0
)

echo.
echo Parando e removendo o servico "AlphafitusOS"...
python service_windows.py stop >nul 2>nul
python service_windows.py remove
if errorlevel 1 (
    echo.
    echo ERRO ao remover o servico. Confirme que esta janela foi aberta
    echo "Como Administrador" e tente de novo.
) else (
    echo.
    echo Servico removido. O Alphafitus OS nao vai mais iniciar sozinho
    echo com o Windows - use o atalho "Alphafitus OS" para abrir
    echo manualmente quando precisar, ou instale o servico de novo com
    echo "Instalar como Servico do Windows".
)
pause
