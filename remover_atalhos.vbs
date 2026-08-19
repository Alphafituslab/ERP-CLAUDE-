' Remove os atalhos do Alphafitus OS (Menu Iniciar e Area de
' Trabalho), tanto os da instalacao "simples" (usuario atual, criados
' por criar_atalhos.vbs) quanto os do grupo completo (todos os
' usuarios, criados por criar_atalhos_servidor.vbs quando instalado
' como Administrador).
'
' Chamado pelo desinstalador (desinstalar.bat). Ignora silenciosamente
' qualquer atalho que nao exista - a desinstalacao nunca deve travar
' por causa de um atalho que nunca chegou a ser criado.
'
' Uso: cscript //nologo remover_atalhos.vbs "<pasta de instalacao>"
' (o argumento e aceito por simetria com os outros scripts, mas nao e
' usado aqui - os atalhos sao localizados pelo nome, nao pela pasta
' de instalacao que apontam.)

Dim objShell, objFSO

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

Sub ApagarArquivoSeExistir(caminho)
    On Error Resume Next
    If objFSO.FileExists(caminho) Then
        objFSO.DeleteFile caminho, True
    End If
    On Error Goto 0
End Sub

Sub ApagarPastaSeExistir(caminho)
    On Error Resume Next
    If objFSO.FolderExists(caminho) Then
        objFSO.DeleteFolder caminho, True
    End If
    On Error Goto 0
End Sub

' Instalacao "simples" (usuario atual)
ApagarArquivoSeExistir objShell.SpecialFolders("Programs") & "\Alphafitus OS.lnk"
ApagarArquivoSeExistir objShell.SpecialFolders("Desktop") & "\Alphafitus OS.lnk"

' Instalacao completa (Administrador - grupo com todos os atalhos)
ApagarPastaSeExistir objShell.SpecialFolders("AllUsersPrograms") & "\Alphafitus OS"
ApagarArquivoSeExistir objShell.SpecialFolders("AllUsersDesktop") & "\Alphafitus OS.lnk"
