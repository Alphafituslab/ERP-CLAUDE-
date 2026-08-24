@echo off
rem ============================================================
rem  Alphafitus OS - Terminal (atalho para instalar_terminal.ps1)
rem
rem  Fase 111 - a logica de verdade (testar conexao, achar
rem  Chrome/Edge, criar o atalho) mora em instalar_terminal.ps1,
rem  ao lado deste arquivo - os dois precisam viajar juntos se
rem  forem copiados para outro computador (ex.: por USB ou rede).
rem  Este .bat so existe porque dar duplo-clique num .bat e mais
rem  familiar para quem nao mexe com PowerShell no dia a dia.
rem ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_terminal.ps1"
