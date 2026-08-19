@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Alphafitus OS - Desinstalar
cd /d "%~dp0"

echo ================================================================
echo   Alphafitus OS - Desinstalador
echo ================================================================
echo.
echo Esta acao vai remover o Alphafitus OS deste computador:
echo   - para o Servico do Windows, se estiver instalado
echo   - remove os atalhos do Menu Iniciar e da Area de Trabalho
echo   - remove a entrada em "Aplicativos e Recursos"
echo   - apaga a pasta de instalacao (incluindo o banco de dados
echo     local, se ele estiver guardado aqui)
echo.
echo IMPORTANTE: se este computador e o SERVIDOR usado por outras
echo maquinas da rede, desinstalar aqui derruba o acesso de todo
echo mundo. Se ainda nao tiver um backup recente, faca um pela tela
echo "Sistema > Backup" do Alphafitus OS antes de continuar.
echo.
set /p CONFIRMA="Tem certeza que deseja desinstalar? (digite SIM para confirmar): "
if /i not "%CONFIRMA%"=="SIM" (
    echo.
    echo Cancelado. Nada foi removido.
    pause
    exit /b 0
)

echo.
echo Parando e removendo o Servico do Windows (se existir)...
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
    python "%~dp0service_windows.py" stop >nul 2>nul
    python "%~dp0service_windows.py" remove >nul 2>nul
) else (
    sc stop AlphafitusOS >nul 2>nul
    sc delete AlphafitusOS >nul 2>nul
)

echo Removendo os atalhos do Menu Iniciar e da Area de Trabalho...
if exist "%~dp0remover_atalhos.vbs" (
    cscript.exe //nologo "%~dp0remover_atalhos.vbs" "%~dp0"
)

echo Removendo o registro em "Aplicativos e Recursos"...
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\AlphafitusOS" /f >nul 2>nul

echo.
echo Pronto. Os arquivos do sistema serao apagados assim que esta
echo janela fechar.
echo.
echo Se voce quer GUARDAR o banco de dados atual antes de apagar tudo,
echo copie agora a pasta "data" desta instalacao para outro lugar, e
echo so depois pressione uma tecla para continuar.
pause

rem A propria pasta de instalacao nao pode se autoapagar enquanto
rem este .bat ainda esta rodando de dentro dela - por isso agenda a
rem remocao num processo separado e desacoplado (start /b), que
rem espera alguns segundos (tempo deste script terminar e o cmd
rem fechar) antes de apagar a pasta inteira.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & rmdir /s /q "%~dp0""
exit
