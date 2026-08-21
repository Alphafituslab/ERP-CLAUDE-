# Instalador do Alphafitus OS

Gera um instalador Windows real (`.exe`, assistente Avançar/Instalar,
aparece em "Aplicativos e Recursos", desinstalador próprio) — nenhuma
máquina de destino precisa ter Python instalado; o PyInstaller empacota um
interpretador Python + todas as dependências dentro dos próprios `.exe`.

## Como gerar (nesta máquina de desenvolvimento)

Pré-requisitos (uma vez só):
```powershell
venv\Scripts\pip install pyinstaller
winget install --id JRSoftware.InnoSetup -e
```

Build completo:
```powershell
cd installer
..\venv\Scripts\pyinstaller --clean --noconfirm alphafitus.spec
"C:\Users\<usuario>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" AlphafitusOS.iss
```

O instalador final fica em `installer\saida\AlphafitusOS_Servidor_Instalar.exe`
— é esse arquivo que se distribui/copia para o computador que vai ser o
"Servidor" (ver a seção "Fase 68 — Servidor e Terminais" no README
principal para o passo a passo de uso).

## Estrutura

- `app_launcher.py` — ponto de entrada do modo "janela aberta" (equivalente
  a `_ambiente.bat` + `iniciar.bat`, mas em Python puro, sem depender de
  cmd.exe nem de Python já instalado na máquina de destino). Gera
  `config_ambiente.bat` (chave de segurança) na primeira execução, prepara
  o banco, garante o usuário administrador, e sobe o servidor waitress.
- `alphafitus.spec` — spec do PyInstaller; gera DOIS executáveis
  (`AlphafitusOS.exe` do `app_launcher.py`, `AlphafitusOS_Servico.exe` de
  `service_windows.py`) compartilhando o mesmo diretório de saída.
- `AlphafitusOS.iss` — script do Inno Setup: empacota a saída do
  PyInstaller + os `.bat` auxiliares de `payload/` num instalador só.
- `payload/*.bat` — atalhos pequenos para gerenciar o Serviço do Windows
  (instalar/iniciar/parar/status/remover, cada um se autoeleva via UAC
  quando precisa de Administrador) e `Terminal_Instalar.bat` (cria um
  atalho de navegador num outro computador, sem instalar nada pesado).
- `icone.ico` — ícone do instalador/aplicativo, convertido de
  `frontend/static/icons/icon-512.png`.

## O que NÃO vai para o Git

`dist/`, `build/` e `saida/` (saída de build, grande e 100% reproduzível a
partir do código-fonte acima) — ver `.gitignore` na raiz do projeto.

## Testado nesta máquina

Instalação silenciosa (`/VERYSILENT /DIR=...`) e desinstalação
(`unins000.exe /VERYSILENT`) validadas de ponta a ponta numa pasta de
teste isolada: o servidor sobe, responde na API, cria o usuário
administrador com senha aleatória impressa no console, e a desinstalação
remove os arquivos do programa preservando `data\` (banco de dados) e
`config_ambiente.bat` (chave de segurança), exatamente como documentado.
Não testado ainda: registro real do Serviço do Windows (exige
Administrador de verdade — `instalar_servico.bat`/`AlphafitusOS_Servico.exe
install`), e a experiência completa de dois computadores reais na mesma
rede (Servidor + Terminal).
