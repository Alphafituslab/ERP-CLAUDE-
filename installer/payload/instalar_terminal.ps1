# ============================================================
#  Alphafitus OS - Terminal
#
#  Fase 111 (Arquitetura Servidor + Terminais) - versao evoluida do
#  antigo Terminal_Instalar.bat: agora TESTA a conexao com o servidor
#  antes de criar o atalho (em vez de criar sempre, mesmo com endereco
#  errado), e abre o sistema em modo "aplicativo" (janela limpa, sem
#  barra de enderecos) em vez de um atalho de internet comum -
#  exatamente o mesmo padrao ja usado e testado em producao pelo
#  instalador do Whatts Inbox.
#
#  Este computador NAO instala Flask nem banco de dados - so cria um
#  atalho que abre o navegador apontado para o SERVIDOR de verdade.
#  Pode ser chamado com -Servidor "http://192.168.1.10:5000" (usado
#  pelo instalador principal, modo Terminal) ou sem parametro nenhum
#  (pede o endereco interativamente, mesmo jeito que sempre foi).
# ============================================================
param(
    [string]$Servidor = ''
)

$ErrorActionPreference = 'Stop'
$NOME_ATALHO = 'Alphafitus OS'

function Escrever($texto, $cor = 'White') { Write-Host $texto -ForegroundColor $cor }

Escrever ''
Escrever '  ============================================' Cyan
Escrever '   Alphafitus OS - Terminal' Cyan
Escrever '  ============================================' Cyan
Escrever ''
Escrever '  Este computador so ACESSA o sistema - o Alphafitus OS de' White
Escrever '  verdade (com o banco de dados) roda no SERVIDOR.' White
Escrever ''

if ([string]::IsNullOrWhiteSpace($Servidor)) {
    $Servidor = Read-Host '  Endereco do servidor (ex.: 192.168.1.10:5000)'
}
$Servidor = $Servidor.Trim()
if ([string]::IsNullOrWhiteSpace($Servidor)) {
    Escrever '  [X] Nenhum endereco informado. Cancelado.' Red
    Read-Host '  Pressione Enter para fechar'
    exit 1
}
if ($Servidor -notmatch '^https?://') { $Servidor = "http://$Servidor" }
$Servidor = $Servidor.TrimEnd('/')

# --- 1. Testar conexao com o servidor -------------------------
Escrever "  [1/3] Testando conexao com $Servidor ..." White
$conectou = $false
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $resposta = Invoke-WebRequest -Uri "$Servidor/api/v1/saude" -UseBasicParsing -TimeoutSec 8
    if ($resposta.StatusCode -eq 200 -and $resposta.Content -match '"status"\s*:\s*"ok"') {
        $conectou = $true
        Escrever '        Servidor localizado' Green
        Escrever '        Banco de dados disponivel' Green
        Escrever '        Comunicacao estabelecida' Green
    }
} catch {
    # segue com $conectou = $false
}
if (-not $conectou) {
    Escrever '  [X] Nao consegui conectar nesse endereco.' Red
    Escrever '      Confira se o Alphafitus OS esta rodando no servidor,' Red
    Escrever '      se o endereco/porta estao corretos e se este' Red
    Escrever '      computador esta na mesma rede.' Red
    Escrever ''
    Escrever '      O atalho NAO foi criado - rode este instalador de' Yellow
    Escrever '      novo depois de confirmar o endereco certo.' Yellow
    Read-Host '  Pressione Enter para fechar'
    exit 1
}

# --- 2. Achar um navegador que suporte modo aplicativo -------
$candidatos = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$navegador = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $navegador) {
    Escrever '  [X] Nao encontrei Chrome nem Edge neste computador.' Red
    Escrever '      Instale o Google Chrome e rode este instalador de novo.' Red
    Read-Host '  Pressione Enter para fechar'
    exit 1
}
Escrever "  [2/3] Navegador encontrado: $(Split-Path $navegador -Leaf)" Green

# --- 3. Criar o atalho na area de trabalho -------------------
$areaTrabalho = [Environment]::GetFolderPath('Desktop')
$caminhoAtalho = Join-Path $areaTrabalho "$NOME_ATALHO.lnk"

$shell = New-Object -ComObject WScript.Shell
$atalho = $shell.CreateShortcut($caminhoAtalho)
$atalho.TargetPath  = $navegador
$atalho.Arguments   = "--app=$Servidor"
$atalho.Description = "Alphafitus OS (terminal) - $Servidor"
$atalho.Save()

Escrever '  [3/3] Atalho criado na area de trabalho' Green

# --- 4. Pasta fixa de backup + atalho pra ela -----------------
# Fase 180 - pedido do usuario: todo backup baixado deste Terminal (botao
# "Salvar backup" ou "Baixar Backup Completo") deve cair sempre no MESMO
# lugar. O navegador (API File System Access) exige que a pessoa escolha
# essa pasta manualmente na primeira vez - nao tem como um script pre-
# autorizar isso -, entao aqui so preparamos o terreno: cria a pasta
# (se ainda nao existir) e um atalho na Area de Trabalho pra abri-la
# facil, ja que uma pagina web tambem nao pode mandar o Windows abrir o
# Explorer sozinha.
$PASTA_BACKUP_FIXA = 'C:\Alphafitus\Backups'
try {
    if (-not (Test-Path $PASTA_BACKUP_FIXA)) {
        New-Item -ItemType Directory -Path $PASTA_BACKUP_FIXA -Force | Out-Null
    }
    $caminhoAtalhoPasta = Join-Path $areaTrabalho 'Backups do Alphafitus.lnk'
    $atalhoPasta = $shell.CreateShortcut($caminhoAtalhoPasta)
    $atalhoPasta.TargetPath = $PASTA_BACKUP_FIXA
    $atalhoPasta.Save()
    Escrever "  [4/4] Pasta de backup pronta: $PASTA_BACKUP_FIXA" Green
} catch {
    # Nao critico - o Terminal funciona normalmente sem isso, so nao tera
    # a pasta pre-criada; a pessoa ainda pode escolher/criar uma na hora
    # de usar "Salvar backup".
    Escrever "  [!] Nao consegui preparar a pasta de backup automaticamente." Yellow
}

Escrever ''
Escrever '  ============================================' Cyan
Escrever '   Pronto!' Green
Escrever ''
Escrever "   Procure o atalho '$NOME_ATALHO' na sua area de" White
Escrever '   trabalho e clique duas vezes.' White
Escrever ''
Escrever '   Ao usar "Salvar backup" dentro do sistema pela primeira vez,' White
Escrever "   escolha a pasta $PASTA_BACKUP_FIXA (ja criada, com atalho" White
Escrever '   "Backups do Alphafitus" na Area de Trabalho) - so precisa' White
Escrever '   escolher uma vez, o sistema lembra depois disso.' White
Escrever ''
Escrever '   Se o endereco do servidor mudar no futuro, rode este' DarkGray
Escrever '   instalador de novo com o endereco novo.' DarkGray
Escrever '  ============================================' Cyan
Escrever ''
if (-not $Servidor) { Read-Host '  Pressione Enter para fechar' }
