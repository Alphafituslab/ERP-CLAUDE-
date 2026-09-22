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
#define MyAppVersion "191.1"
#define MyAppPublisher "Alphafitus"
#define MyAppExeName "AlphafitusOS.exe"

[Setup]
AppId={{D9D53BD0-E5E4-4360-9A9D-CFA3CC57E5E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Fase 123 — o RestartManager do Windows (usado pelo Inno Setup para
; tentar fechar sozinho qualquer app "usando um dos nossos arquivos"
; antes de sobrescrevê-los) já foi visto travando a instalação por causa
; de um FALSO POSITIVO: apontou "chrome-native-host" — um processo do
; Claude Desktop (nada a ver com o AlphafitusOS; confirmado que a pasta
; de instalação do AlphafitusOS não tem nenhum arquivo chrome* — é
; correspondência genérica do RestartManager contra alguma DLL
; compartilhada, não um conflito de verdade). Desligar essa checagem
; automática evita esse falso positivo; o processo real que precisa estar
; fechado (AlphafitusOS.exe/_Servico.exe) continua sendo tratado à parte
; pelo próprio fluxo de deploy (kill explícito antes de instalar).
CloseApplications=no
; Fase 157 — pedido do usuário: o caminho de instalação NUNCA deve mudar
; sozinho, nem por escolha na hora de instalar — só desinstalando é que
; se sai dele. Antes (Fase 123) a página "Selecionar Local de Destino" do
; Inno Setup ficava habilitada (padrão do próprio Inno) e deixava
; escolher qualquer pasta; DisableDirPage=yes tira essa página do
; assistente por completo — {app} sempre resolve pro DefaultDirName
; abaixo, sem exceção, numa instalação nova. {localappdata}\Programs é o
; mesmo padrão já usado pela instalação real de produção hoje (não exige
; privilégio de administrador, ao contrário de {pf}). Numa ATUALIZAÇÃO
; (mesmo AppId já instalado antes) o Inno Setup usa sozinho o caminho já
; escolhido da vez anterior — mudar o padrão aqui só afeta instalações
; NOVAS, nunca move uma instalação existente.
DisableDirPage=yes
DefaultDirName={localappdata}\Programs\AlphafitusOS
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
; Fase 123 — VCRUNTIME140*.dll são runtimes padrão do Visual C++
; (redistribuídos pelo próprio PyInstaller, idênticos entre builds
; enquanto a versão do Python/toolchain não mudar) — nomes tão genéricos
; que QUALQUER outro processo no Windows pode ter uma cópia carregada na
; hora do deploy (já visto travando a instalação por um processo do
; Claude Desktop, sem nenhuma relação com o AlphafitusOS — confirmado por
; hash idêntico ao arquivo já instalado). Excluídos do wildcard geral e
; tratados à parte com "onlyifdoesntexist": só copiados na primeira
; instalação; numa atualização, se o arquivo já existe (99,9% das vezes,
; byte a byte igual), não tenta sobrescrever — elimina esse falso
; positivo sem nunca deixar de instalar numa máquina nova.
; Fase 123 — achado real: rodar o .exe direto de dentro de
; installer\dist\AlphafitusOS\ (comum ao testar antes de compilar o
; instalador) gera, NAQUELA MESMA pasta, um config_ambiente.bat/
; config_whatts.bat e uma pasta data\ próprios (o app não sabe que está
; sendo testado, então trata aquele diretório como se fosse a instalação
; de verdade). Se esses arquivos ficarem esquecidos ali na hora de
; compilar o instalador, o wildcard abaixo os copiava JUNTO para a
; instalação real — sobrescrevendo o config_ambiente.bat de um usuário
; já instalado com um apontando pro banco de dados ERRADO (o de teste,
; quase vazio). Foi exatamente isso que aconteceu numa entrega desta
; fase. Excluídos explicitamente — estes três só devem existir
; gerados pelo próprio app, na pasta de instalação de verdade, nunca
; vindos do pacote.
Source: "dist\AlphafitusOS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: EhServidor; Excludes: "_internal\VCRUNTIME140.dll,_internal\VCRUNTIME140_1.dll,config_ambiente.bat,config_whatts.bat,data\*,data"
Source: "dist\AlphafitusOS\_internal\VCRUNTIME140.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist; Check: EhServidor
Source: "dist\AlphafitusOS\_internal\VCRUNTIME140_1.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist; Check: EhServidor
Source: "payload\instalar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\iniciar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\parar_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\status_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\remover_servico.bat"; DestDir: "{app}"; Flags: ignoreversion; Check: EhServidor
Source: "payload\Terminal_Instalar.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\instalar_terminal.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\Recriar_Atalho_Desktop.bat"; DestDir: "{app}"; Flags: ignoreversion
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
; Fase 181 — pedido do usuário: um jeito de "resgatar" o atalho da Área de
; Trabalho sem precisar reinstalar, a partir da própria pasta de
; instalação — sem `Check: EhServidor` de propósito, aparece nos DOIS
; modos (o Servidor também pode ter um uso de Terminal na mesma máquina).
Name: "{group}\Recriar atalho na Área de Trabalho"; Filename: "{app}\Recriar_Atalho_Desktop.bat"; WorkingDir: "{app}"
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
  // instalador, antes de qualquer outra coisa.
  // Fase 175 — desde a Fase 157b o Servidor oficial é sempre o mesmo,
  // fixo na nuvem (erp.alphafitus.com.br) — não existe mais cenário de
  // "Servidor na rede local com IP variável". Pedido do usuário: Terminal
  // não pode pedir nada pra instalar, só detectar o servidor sozinho — a
  // antiga ServidorPage (pedia IP/porta) foi removida; o endereço é
  // hardcoded abaixo, em CurStepChanged.
  ModoPage: TInputOptionWizardPage;
  // Fase 177 — pedido do usuário: nunca instalar um segundo Servidor sem
  // confirmação por e-mail. CodigoServidorConfirmado só vira True depois
  // de uma verificação HTTP de verdade contra o Servidor oficial (ver
  // NextButtonClick) — o gate de segurança de fato mora em CurStepChanged
  // (ssInstall), que roda em QUALQUER modo (inclusive /VERYSILENT), então
  // não existe caminho pra instalar Servidor sem passar por essa tela.
  CodigoServidorPage: TInputQueryWizardPage;
  CodigoServidorConfirmado: Boolean;

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
    'próprio, só acessam o Alphafitus OS oficial na nuvem automaticamente, sem ' +
    'precisar de nenhum endereço ou configuração extra.',
    False, False);
  ModoPage.Add('Instalar como SERVIDOR (esta máquina terá o banco de dados oficial)');
  ModoPage.Add('Instalar como TERMINAL (conecta sozinho ao Alphafitus OS oficial na nuvem)');
  ModoPage.SelectedValueIndex := 0;

  // Fase 177 — pedido do usuário: nunca instalar um segundo Servidor sem
  // confirmação por e-mail. Só aparece no modo SERVIDOR (ver
  // ShouldSkipPage) — o código em si é pedido/enviado ao SAIR da
  // ModoPage (ver NextButtonClick), antes desta tela ser mostrada.
  CodigoServidorPage := CreateInputQueryPage(ModoPage.ID,
    'Confirmação por e-mail', 'Instalar um Servidor precisa de confirmação',
    'Só pode existir UM Servidor oficial — o que já roda na nuvem (erp.alphafitus.com.br). ' +
    'Instalar outro por engano criaria um banco de dados paralelo, sem nenhuma sincronia com o ' +
    'real. Um código de 6 dígitos foi enviado por e-mail para quem administra o sistema — confira ' +
    'a caixa de entrada e digite o código abaixo para continuar.');
  CodigoServidorPage.Add('Código recebido por e-mail:', False);

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
// de sempre, só que quase vazia).
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = AdminPage.ID) and EhTerminal() then Result := True;
  if (PageID = CodigoServidorPage.ID) and EhTerminal() then Result := True;
end;

// Fase 177 — confirmação por e-mail antes de instalar em modo SERVIDOR,
// via WinHTTP (COM embutido no Windows, nada extra pra instalar — mesmo
// objeto usado há anos em scripts de instalação pra chamadas HTTP
// simples). O JSON das duas rotas (app/routes/instalador.py) é sempre
// plano, sem aninhamento — um parser de verdade seria over-engineering
// aqui; extração por substring resolve e é fácil de auditar.
function ExtrairCampoJson(const Json, Campo: String): String;
var
  Marcador: String;
  PosInicio, PosFim: Integer;
begin
  Result := '';
  Marcador := '"' + Campo + '":"';
  PosInicio := Pos(Marcador, Json);
  if PosInicio = 0 then Exit;
  PosInicio := PosInicio + Length(Marcador);
  PosFim := PosInicio;
  while (PosFim <= Length(Json)) and (Json[PosFim] <> '"') do
    PosFim := PosFim + 1;
  Result := Copy(Json, PosInicio, PosFim - PosInicio);
end;

function ChamarApiInstalador(const Caminho, CorpoJson: String; var CodigoHttp: Integer; var RespostaTexto: String): Boolean;
var
  Http: Variant;
begin
  Result := False;
  RespostaTexto := '';
  CodigoHttp := 0;
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.Open('POST', 'https://erp.alphafitus.com.br/api/v1/instalador/' + Caminho, False);
    Http.SetRequestHeader('Content-Type', 'application/json');
    Http.SetTimeouts(5000, 5000, 10000, 10000);
    Http.Send(CorpoJson);
    CodigoHttp := Http.Status;
    RespostaTexto := Http.ResponseText;
    Result := True;
  except
    Result := False;
  end;
end;

function SolicitarCodigoInstalacaoServidor(var MensagemErro: String): Boolean;
var
  CodigoHttp: Integer;
  Resposta: String;
begin
  Result := ChamarApiInstalador('solicitar-codigo-servidor', '{}', CodigoHttp, Resposta);
  if Result and (CodigoHttp = 200) then Exit;
  Result := False;
  MensagemErro := '';
  if Resposta <> '' then MensagemErro := ExtrairCampoJson(Resposta, 'mensagem');
  if MensagemErro = '' then
    MensagemErro := 'Não consegui contatar o Servidor oficial pra pedir o código — verifique sua ' +
      'internet e tente de novo (Voltar e Avançar de novo nesta tela).';
end;

function VerificarCodigoInstalacaoServidor(const Codigo: String; var MensagemErro: String): Boolean;
var
  CodigoHttp: Integer;
  Resposta: String;
begin
  Result := ChamarApiInstalador('verificar-codigo-servidor', '{"codigo":"' + Codigo + '"}', CodigoHttp, Resposta);
  if Result and (CodigoHttp = 200) then Exit;
  Result := False;
  MensagemErro := '';
  if Resposta <> '' then MensagemErro := ExtrairCampoJson(Resposta, 'mensagem');
  if MensagemErro = '' then
    MensagemErro := 'Não consegui confirmar o código — verifique sua internet e tente de novo.';
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
  Motivo, MensagemErro: String;
begin
  Result := True;
  // Instalação silenciosa (/VERYSILENT etc.) nunca mostra esta tela, mas
  // o Inno Setup ainda "clica Avançar" internamente em cada página,
  // inclusive nesta — sem este atalho, os campos ficam vazios, a
  // validação abaixo sempre falha, e a instalação inteira aborta. Em modo
  // silencioso é o comportamento certo mesmo pular a validação: o
  // CurStepChanged mais abaixo já sabe cair para trás com segurança
  // (senha aleatória, troca obrigatória no primeiro login) quando nenhuma
  // senha foi informada. IMPORTANTE: isso NÃO abre uma brecha pro modo
  // Servidor sem confirmação por e-mail — esse gate específico mora em
  // CurStepChanged (ssInstall), que roda em QUALQUER modo, silencioso
  // incluído, e não depende de nada que aconteça aqui.
  if WizardSilent() then Exit;

  // Fase 177 — ao SAIR da ModoPage com Servidor escolhido, pede o código
  // por e-mail antes de deixar prosseguir pra tela de digitar o código.
  if (CurPageID = ModoPage.ID) and EhServidor() then
  begin
    Result := SolicitarCodigoInstalacaoServidor(MensagemErro);
    if not Result then
    begin
      MsgBox(MensagemErro, mbError, MB_OK);
      Exit;
    end;
    MsgBox(
      'Código enviado! Confira o e-mail de quem administra o sistema (chega em poucos ' +
      'segundos) e digite o código na próxima tela.',
      mbInformation, MB_OK);
  end;

  if CurPageID = CodigoServidorPage.ID then
  begin
    if Trim(CodigoServidorPage.Values[0]) = '' then
    begin
      MsgBox('Informe o código recebido por e-mail.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    Result := VerificarCodigoInstalacaoServidor(Trim(CodigoServidorPage.Values[0]), MensagemErro);
    if not Result then
    begin
      MsgBox(MensagemErro, mbError, MB_OK);
      Exit;
    end;
    CodigoServidorConfirmado := True;
  end;

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
  EnderecoServidor, ComandoPs1, Parametros: String;
  ResultCode: Integer;
begin
  // Fase 177 — o GATE de segurança de verdade (pedido do usuário: nunca
  // instalar Servidor sem confirmação por e-mail) mora aqui, não em
  // NextButtonClick — ssInstall roda em QUALQUER modo, inclusive
  // /VERYSILENT (que pula todas as telas, inclusive a de confirmação).
  // CodigoServidorConfirmado só vira True depois de uma verificação HTTP
  // de verdade contra o Servidor oficial — sem isso, não existe caminho
  // (interativo ou silencioso) que instale um Servidor sem confirmar.
  if CurStep = ssInstall then
  begin
    if EhServidor() and not CodigoServidorConfirmado then
    begin
      MsgBox(
        'Instalação cancelada: a confirmação por e-mail não foi concluída. ' +
        'Um Servidor só pode ser instalado depois de confirmar o código enviado por e-mail.',
        mbCriticalError, MB_OK);
      Abort;
    end;
  end;

  if CurStep = ssPostInstall then
  begin
    // Fase 111 — modo TERMINAL não tem config_ambiente.bat nem banco
    // próprio nenhum: em vez disso, roda o instalar_terminal.ps1 (já
    // copiado para {app} pelo [Files] acima), testando a conexão de
    // verdade e criando o atalho — tudo automático, sem precisar rodar
    // nada manualmente depois.
    // Fase 175 — pedido do usuário: Terminal não pode pedir nada pra
    // instalar, só detectar o servidor sozinho. Desde a Fase 157b existe
    // um único Servidor oficial, fixo na nuvem — não faz mais sentido
    // perguntar IP/porta numa rede local. Endereço hardcoded aqui; quem
    // realmente precisar apontar pra outro servidor (ex.: ambiente de
    // teste) ainda pode rodar Terminal_Instalar.bat manualmente depois,
    // que aceita um endereço customizado via instalar_terminal.ps1.
    if EhTerminal() then
    begin
      EnderecoServidor := 'https://erp.alphafitus.com.br';
      ComandoPs1 := ExpandConstant('{app}\instalar_terminal.ps1');
      Parametros := '-NoProfile -ExecutionPolicy Bypass -File "' + ComandoPs1 +
        '" -Servidor "' + EnderecoServidor + '"';
      Exec('powershell.exe', Parametros, '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      // Achado real (usuário relatou 2026-09-16): instalação terminava
      // "concluída" mesmo quando instalar_terminal.ps1 falhava no meio
      // do caminho (ex.: antivírus interferindo na criação do atalho) —
      // este instalador nunca checava o resultado. Agora avisa
      // explicitamente em vez de deixar a pessoa achar que deu tudo
      // certo sem nenhum atalho na tela.
      if ResultCode <> 0 then
      begin
        MsgBox(
          'A instalação em si concluiu, mas a criação do atalho na Área de Trabalho ' +
          'pode não ter funcionado (ex.: bloqueado por antivírus). Enquanto isso, você já ' +
          'pode usar o sistema abrindo o Chrome ou Edge e acessando ' + EnderecoServidor + ' ' +
          'diretamente. Pra tentar criar o atalho de novo, rode "Instalar um Terminal em outro ' +
          'computador" (atalho no Menu Iniciar do Servidor) ou o Terminal_Instalar.bat desta pasta.',
          mbInformation, MB_OK);
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
