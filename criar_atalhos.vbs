' Cria o atalho "Alphafitus OS" no Menu Iniciar e na Area de Trabalho
' do usuario atual, apontando para iniciar.bat.
'
' Chamado automaticamente pelo instalador (__main__.py) logo apos
' extrair os arquivos, so quando ele rodou SEM direitos de
' Administrador (instalacao "simples", em %LOCALAPPDATA%). Para a
' instalacao completa (Administrador), veja criar_atalhos_servidor.vbs.
'
' Uso: cscript //nologo criar_atalhos.vbs "<pasta de instalacao>"

Dim objShell, objFSO, pastaInstalacao, pastaMenuIniciar, pastaAreaTrabalho

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count < 1 Then
    WScript.Echo "Uso: criar_atalhos.vbs <pasta de instalacao>"
    WScript.Quit 1
End If

pastaInstalacao = WScript.Arguments(0)

Sub CriarAtalhoIniciar(caminhoLnk)
    Dim atalho
    Set atalho = objShell.CreateShortcut(caminhoLnk)
    atalho.TargetPath = "%ComSpec%"
    atalho.Arguments = "/k """ & pastaInstalacao & "\iniciar.bat"""
    atalho.WorkingDirectory = pastaInstalacao
    atalho.WindowStyle = 1
    atalho.Description = "Alphafitus OS"
    atalho.IconLocation = "%ComSpec%,0"
    atalho.Save
End Sub

pastaMenuIniciar = objShell.SpecialFolders("Programs")
If Not objFSO.FolderExists(pastaMenuIniciar) Then
    objFSO.CreateFolder(pastaMenuIniciar)
End If
CriarAtalhoIniciar pastaMenuIniciar & "\Alphafitus OS.lnk"

pastaAreaTrabalho = objShell.SpecialFolders("Desktop")
CriarAtalhoIniciar pastaAreaTrabalho & "\Alphafitus OS.lnk"
