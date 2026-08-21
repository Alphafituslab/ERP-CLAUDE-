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
; são gerados pelo próprio aplicativo na primeira execução (banco de
; dados e chave de segurança), não fazem parte do que o instalador
; colocou. O desinstalador do Inno Setup só remove o que está no [Files]
; acima, então essa pasta sobrevive automaticamente à desinstalação —
; mesmo comportamento já documentado no README ("preserva a pasta data\
; por segurança").
