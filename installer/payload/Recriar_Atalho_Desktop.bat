@echo off
rem ============================================================
rem  Alphafitus OS - Recriar atalho na Area de Trabalho
rem
rem  Fase 181 - pedido do usuario: poder "resgatar" o icone sem precisar
rem  reinstalar nada, a partir da propria pasta de instalacao (visivel
rem  aqui no Menu Iniciar caso o atalho da Area de Trabalho tenha sido
rem  apagado ou nunca criado - ex.: por um antivirus bloqueando a
rem  criacao durante a instalacao original).
rem
rem  Roda de novo so a parte que cria o atalho (e a pasta fixa de
rem  backup), direto pro Servidor oficial - sem perguntar nada, mesmo
rem  principio de zero-configuracao do instalador principal.
rem ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_terminal.ps1" -Servidor "https://erp.alphafitus.com.br"
