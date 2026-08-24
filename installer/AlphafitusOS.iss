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
#define MyAppVersion "111.0"
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
; Fase 111 — {#MyAppExeName} só existe em instalações modo SERVIDOR (ver
; [Files] abaixo); um TERMINAL não tem esse .exe, então o ícone do
; desinstalador aponta para icone.ico (copiado em [Files] nos dois modos)
; em vez do executável, que quebraria em modo Terminal.
UninstallDisplayIcon={app}\icone.ico
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

; Fase 111 — Arquitetura Servidor + Terminais: `Check: EhServidor`/`Check: EhTerminal`
; (funções Pascal na seção [Code] abaixo) fazem cada [Files]/[Icons] só existir no modo
; certo — um TERMINAL nunca recebe o Flask/PyInstaller nem os scripts de serviço
; Windows (não tem banco de dados próprio, não faz sentido ter nenhum dos dois), só o
; instalador de atalho (instalar_terminal.ps1/.bat) + o ícone.
[Files]
Source: "dist\AlphafitusOS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: EhServidor
Source: "payload\instalar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\iniciar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\parar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\status_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\remover_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\Terminal_Instalar.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\instalar_terminal.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "icone.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Alphafitus OS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Alphafitus OS (modo diagnóstico, com janela)"; Filename: "{app}\AlphafitusOS_Console.exe"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Instalar como Serviço do Windows"; Filename: "{app}\instalar_servico.bat"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Iniciar Serviço"; Filename: "{app}\iniciar_servico.bat"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Parar Serviço"; Filename: "{app}\parar_servico.bat"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Status do Serviço"; Filename: "{app}\status_servico.bat"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Remover Serviço do Windows"; Filename: "{app}\remover_servico.bat"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Instalar um Terminal em outro computador"; Filename: "{app}\Terminal_Instalar.bat"; WorkingDir: "{app}"; Check: EhServidor
Name: "{group}\Desinstalar Alphafitus OS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Alphafitus OS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; Check: EhServidor

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar o Alphafitus OS agora"; Flags: postinstall nowait skipifsilent; Check: EhServidor

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
  // Fase 111 — Arquitetura Servidor + Terminais. ModoPage é a escolha
  // explícita pedida pelo usuário ("essa escolha precisa ficar muito
  // clara para quem estiver instalando") — a PRIMEIRA página do
  // instalador, antes de qualquer outra coisa. ServidorPage só existe
  // quando "Terminal" é escolhido: pede o endereço do Servidor já
  // instalado em outra máquina.
  ModoPage: TInputOptionWizardPage;
  ServidorPage: TInputQueryWizardPage;

function EhServidor(): Boolean;
begin
  Result := (ModoPage = nil) or (ModoPage.SelectedValueIndex = 0);
end;

function EhTerminal(): Boolean;
begin
  Result := (ModoPage <> nil) and (ModoPage.SelectedValueIndex = 1);
end;

procedure InitializeWizard;
begin
  ModoPage := CreateInputOptionPage(wpWelcome,
    'Tipo desta instalação', 'Como esta máquina vai usar o Alphafitus OS?',
    'Escolha SERVIDOR só na máquina principal, que vai guardar o banco de dados ' +
    'oficial da empresa. Escolha TERMINAL nas demais máquinas — elas não têm banco ' +
    'próprio, só acessam o sistema que roda no Servidor. Nunca instale mais de um ' +
    'Servidor: todo o resto da empresa deve apontar para o mesmo.',
    False, False);
  ModoPage.Add('Instalar como SERVIDOR (esta máquina terá o banco de dados oficial)');
  ModoPage.Add('Instalar como TERMINAL (esta máquina só acessa um Servidor já existente)');
  ModoPage.SelectedValueIndex := 0;

  ServidorPage := CreateInputQueryPage(ModoPage.ID,
    'Endereço do Servidor', 'Onde está o Alphafitus OS que já roda como Servidor?',
    'Peça esse endereço para quem instalou o Servidor — normalmente o IP da máquina ' +
    'principal na rede local (ex.: 192.168.1.10). A conexão é testada de verdade ' +
    'antes de criar o atalho; se o endereço estiver errado, nada é instalado.');
  ServidorPage.Add('Endereço/IP do servidor:', False);
  ServidorPage.Add('Porta:', False);
  ServidorPage.Values[1] := '5000';

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

// Terminal não usa a conta de administrador (não tem banco próprio) nem a
// página de pasta de instalação de verdade (usa a mesma {autopf}\AlphafitusOS
// de sempre, só que quase vazia) — e Servidor não usa a página de endereço do
// Servidor (é ELE o servidor). Cada modo pula a página que não é dele.
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = ServidorPage.ID) and EhServidor() then Result := True;
  if (PageID = AdminPage.ID) and EhTerminal() then Result := True;
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
  // Fase 111 — validação da página de endereço do Servidor (só aparece
  // no modo Terminal). A conexão em si só é testada de verdade depois,
  // pelo instalar_terminal.ps1 (ver CurStepChanged) — aqui só garante
  // que os campos não ficaram vazios/com lixo antes de prosseguir.
  if CurPageID = ServidorPage.ID then
  begin
    if Trim(ServidorPage.Values[0]) = '' then
    begin
      MsgBox('Informe o endereço/IP do servidor.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(ServidorPage.Values[1]) = '' then
    begin
      MsgBox('Informe a porta do servidor (normalmente 5000).', mbError, MB_OK);
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
  EnderecoServidor, ComandoPs1, Parametros: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // Fase 111 — modo TERMINAL não tem config_ambiente.bat nem banco
    // próprio nenhum: em vez disso, roda o instalar_terminal.ps1 (já
    // copiado para {app} pelo [Files] acima) com o endereço que a
    // pessoa informou na página ServidorPage, testando a conexão de
    // verdade e criando o atalho — mesma lógica de sempre, só que
    // automática em vez de precisar rodar o .bat manualmente depois.
    if EhTerminal() then
    begin
      EnderecoServidor := Trim(ServidorPage.Values[0]) + ':' + Trim(ServidorPage.Values[1]);
      if Trim(ServidorPage.Values[0]) <> '' then
      begin
        ComandoPs1 := ExpandConstant('{app}\instalar_terminal.ps1');
        Parametros := '-NoProfile -ExecutionPolicy Bypass -File "' + ComandoPs1 +
          '" -Servidor "' + EnderecoServidor + '"';
        Exec('powershell.exe', Parametros, '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      end;
      Exit;
    end;

    ConfigFile := ExpandConstant('{app}\config_ambiente.bat');
    // Reinstalar/atualizar por cima de uma instalação já existente (ex.:
    // uma versão nova do instalador) NUNCA deve mexer num
    // config_ambiente.bat que já existe — regenerar a chave de segurança
    // desloga todo mundo à toa, e sobrescrever apagaria a senha que a
    // pessoa definiu na instalação original. Mesmo raciocínio de "gera
    // só se necessário" que app_launcher.py/app_launcher_tray.py já usam
    // do lado do aplicativo.
    if FileExists(ConfigFile) then Exit;
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
