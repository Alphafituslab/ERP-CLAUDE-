; Instalador real do Alphafitus OS (Fase 68 revisitada) — gera um .exe
; de verdade via Inno Setup: assistente Avancar/Instalar, aparece em
; "Aplicativos e Recursos", atalhos no Menu Iniciar, desinstalador
; proprio. Sem exigir Python/venv na maquina de destino — os executaveis
; em dist\AlphafitusOS\ (gerados por alphafitus.spec via PyInstaller) ja
; embutem um interpretador Python e todas as dependencias.
;
; PrivilegesRequiredOverridesAllowed=dialog: deixa o PROPRIO instalador
; perguntar "instalar so para mim" (sem admin) ou "para todos os
; usuarios" (com UAC) — e assim que o README (Fase 68) documenta a
; diferenca entre instalacao "de verdade" (Arquivos de Programas, pode
; virar Servico do Windows) e a instalacao simples.
#define MyAppName "Alphafitus OS"
#define MyAppVersion "78.0"
#define MyAppPublisher "Alphafitus"
#define MyAppExeName "AlphafitusOS.exe"

[Setup]
AppId={{D9D53BD0-E5E4-4360-9A9D-CFA3CC57E5E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AlphafitusOS
DefaultGroupName=Alphafitus OS
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=saida
OutputBaseFilename=AlphafitusOS_Servidor_Instalar
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "dist\AlphafitusOS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "payload\instalar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\iniciar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\parar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\status_servico.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\remover_servico.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\Terminal_Instalar.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Alphafitus OS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Alphafitus OS (modo diagnóstico, com janela)"; Filename: "{app}\AlphafitusOS_Console.exe"; WorkingDir: "{app}"
Name: "{group}\Instalar como Serviço do Windows"; Filename: "{app}\instalar_servico.bat"; WorkingDir: "{app}"
Name: "{group}\Iniciar Serviço"; Filename: "{app}\iniciar_servico.bat"; WorkingDir: "{app}"
Name: "{group}\Parar Serviço"; Filename: "{app}\parar_servico.bat"; WorkingDir: "{app}"
Name: "{group}\Status do Serviço"; Filename: "{app}\status_servico.bat"; WorkingDir: "{app}"
Name: "{group}\Remover Serviço do Windows"; Filename: "{app}\remover_servico.bat"; WorkingDir: "{app}"
Name: "{group}\Instalar um Terminal em outro computador"; Filename: "{app}\Terminal_Instalar.bat"; WorkingDir: "{app}"
Name: "{group}\Desinstalar Alphafitus OS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Alphafitus OS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar o Alphafitus OS agora"; Flags: postinstall nowait skipifsilent

; Best-effort: se o serviço do Windows tiver sido instalado antes, tenta
; removê-lo antes de apagar os arquivos (silencioso — se não houver
; privilégio de administrador, ou o serviço nunca existiu, simplesmente
; não faz nada, sem travar a desinstalação).
[UninstallRun]
Filename: "{app}\AlphafitusOS_Servico.exe"; Parameters: "remove"; Flags: runhidden skipifdoesntexist; RunOnceId: "RemoverServicoAlphafitusOS"

; De propósito, NÃO listamos `data\*` nem `config_ambiente.bat` aqui —
; o config_ambiente.bat É gerado pelo PRÓPRIO instalador (ver [Code]
; abaixo, CurStepChanged), e `data\` é gerada pelo aplicativo na primeira
; execução (banco de dados) — nenhum dos dois faz parte do que o [Files]
; instala de verdade. O desinstalador do Inno Setup só remove o que está
; no [Files] acima, então essa pasta sobrevive automaticamente à
; desinstalação — mesmo comportamento já documentado no README ("preserva
; a pasta data\ por segurança").

[Code]
var
  AdminPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  AdminPage := CreateInputQueryPage(wpSelectDir,
    'Conta do Administrador', 'Defina o login inicial do Alphafitus OS',
    'Este será o primeiro usuário do sistema, com acesso total a tudo. ' +
    'Guarde a senha em local seguro — você pode trocá-la depois, quando ' +
    'quiser, pela tela "Minha Conta" já dentro do sistema (não é ' +
    'obrigatório trocar no primeiro login).');
  AdminPage.Add('E-mail:', False);
  AdminPage.Add('Senha:', True);
  AdminPage.Add('Confirmar senha:', True);
  AdminPage.Values[0] := 'admin@alphafitus.com.br';
end;

// Política de senha PRÓPRIA desta tela do instalador — de propósito mais
// simples que app/security.py::validar_politica_senha (mínimo 12 +
// maiúscula + minúscula + número + símbolo, usada pelo resto do sistema
// sempre que alguém troca de senha depois de instalado). Aqui é só
// mínimo 8 caracteres, com maiúscula e minúscula — pensado pra ser mais
// fácil de definir/digitar na hora da instalação; nada impede o
// administrador de trocar por uma senha mais forte depois, pela tela
// "Minha Conta" (essa sim já validada pela política completa).
function SenhaValida(const Senha: String; var Motivo: String): Boolean;
var
  I: Integer;
  C: Char;
  TemMinuscula, TemMaiuscula: Boolean;
begin
  TemMinuscula := False;
  TemMaiuscula := False;
  for I := 1 to Length(Senha) do
  begin
    C := Senha[I];
    if (C >= 'a') and (C <= 'z') then TemMinuscula := True
    else if (C >= 'A') and (C <= 'Z') then TemMaiuscula := True;
  end;
  Result := True;
  Motivo := '';
  if Length(Senha) < 8 then
  begin
    Motivo := 'A senha precisa ter no mínimo 8 caracteres.';
    Result := False;
  end
  else if not TemMinuscula then
  begin
    Motivo := 'A senha precisa ter ao menos uma letra minúscula.';
    Result := False;
  end
  else if not TemMaiuscula then
  begin
    Motivo := 'A senha precisa ter ao menos uma letra maiúscula.';
    Result := False;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Motivo: String;
begin
  Result := True;
  // Instalação silenciosa (/VERYSILENT etc.) nunca mostra esta tela, mas
  // o Inno Setup ainda "clica Avançar" internamente em cada página,
  // inclusive nesta — sem este atalho, os campos ficam vazios, a
  // validação abaixo sempre falha, e a instalação inteira aborta. Em modo
  // silencioso é o comportamento certo mesmo pular a validação: o
  // CurStepChanged mais abaixo já sabe cair para trás com segurança
  // (senha aleatória, troca obrigatória no primeiro login) quando nenhuma
  // senha foi informada.
  if WizardSilent() then Exit;
  if CurPageID = AdminPage.ID then
  begin
    if Trim(AdminPage.Values[0]) = '' then
    begin
      MsgBox('Informe o e-mail do administrador.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not SenhaValida(AdminPage.Values[1], Motivo) then
    begin
      MsgBox(Motivo, mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if AdminPage.Values[1] <> AdminPage.Values[2] then
    begin
      MsgBox('As senhas informadas não são iguais.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;

function GerarChaveAleatoria(Tamanho: Integer): String;
var
  I: Integer;
  Digitos: String;
begin
  Digitos := '0123456789abcdef';
  Result := '';
  for I := 1 to Tamanho do
    Result := Result + Digitos[Random(16) + 1];
end;

// Gera config_ambiente.bat com os dados definidos na tela acima — assim,
// quando o Alphafitus OS abrir pela primeira vez, o arquivo já existe e
// nenhuma senha aleatória é gerada/mostrada (ver app_launcher.py/
// app_launcher_tray.py: só geram esse arquivo "se necessário", ou seja,
// se ainda não existir). Numa instalação SILENCIOSA (sem passar pela
// tela, ex.: /VERYSILENT), AdminPage.Values[1] fica vazio — nesse caso
// NÃO escrevemos ALPHAFITUS_ADMIN_SENHA, e o próprio seed.py cai no
// comportamento seguro de sempre (gera uma senha aleatória, mostrada no
// log, com troca obrigatória no primeiro login).
procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigFile: String;
  Linhas: TArrayOfString;
  DbPath, Email, Senha: String;
begin
  if CurStep = ssPostInstall then
  begin
    ConfigFile := ExpandConstant('{app}\config_ambiente.bat');
    DbPath := ExpandConstant('{app}\data\alphafitus.db');
    Email := Trim(AdminPage.Values[0]);
    if Email = '' then Email := 'admin@alphafitus.com.br';
    Senha := AdminPage.Values[1];

    if Senha <> '' then
    begin
      SetArrayLength(Linhas, 6);
      Linhas[5] := 'set "ALPHAFITUS_ADMIN_SENHA=' + Senha + '"';
    end
    else
      SetArrayLength(Linhas, 5);

    Linhas[0] := '@echo off';
    Linhas[1] := 'rem Gerado automaticamente pelo instalador do Alphafitus OS.';
    Linhas[2] := 'set "ALPHAFITUS_JWT_SECRET=' + GerarChaveAleatoria(64) + '"';
    Linhas[3] := 'set "ALPHAFITUS_ADMIN_EMAIL=' + Email + '"';
    Linhas[4] := 'set "ALPHAFITUS_DB_PATH=' + DbPath + '"';

    SaveStringsToFile(ConfigFile, Linhas, False);
  end;
end;
