' Cria o GRUPO completo de atalhos "Alphafitus OS" no Menu Iniciar de
' TODOS os usuarios da maquina, incluindo os atalhos de gerenciar o
' Servico do Windows, alem de um atalho principal na Area de
' Trabalho de todos os usuarios.
'
' Chamado automaticamente pelo instalador (__main__.py) logo apos
' extrair os arquivos, so quando ele rodou COM direitos de
' Administrador (instalacao completa, em %ProgramFiles%). Para a
' instalacao simples (sem Administrador), veja criar_atalhos.vbs.
'
' Uso: cscript //nologo criar_atalhos_servidor.vbs "<pasta de instalacao>"

Dim objShell, objFSO, pastaInstalacao, pastaGrupo

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count < 1 Then
    WScript.Echo "Uso: criar_atalhos_servidor.vbs <pasta de instalacao>"
    WScript.Quit 1
End If

pastaInstalacao = WScript.Arguments(0)
pastaGrupo = objShell.SpecialFolders("AllUsersPrograms") & "\Alphafitus OS"

If Not objFSO.FolderExists(pastaGrupo) Then
    objFSO.CreateFolder(pastaGrupo)
End If

Sub CriarAtalho(pastaDestino, nomeExibicao, chaveCmd, arquivoBat)
    Dim caminhoLnk, atalho
    caminhoLnk = pastaDestino & "\" & nomeExibicao & ".lnk"
    Set atalho = objShell.CreateShortcut(caminhoLnk)
    atalho.TargetPath = "%ComSpec%"
    atalho.Arguments = "/" & chaveCmd & " """ & pastaInstalacao & "\" & arquivoBat & """"
    atalho.WorkingDirectory = pastaInstalacao
    atalho.WindowStyle = 1
    atalho.Description = nomeExibicao
    atalho.IconLocation = "%ComSpec%,0"
    atalho.Save
End Sub

' O atalho principal fica aberto (/k) porque e o console do servidor
' rodando - precisa continuar visivel enquanto o sistema estiver em
' uso. Os atalhos de gerenciar o servico so mostram um resultado e
' fecham a janela sozinhos no fim do .bat correspondente, mas usamos
' /k tambem neles para o usuario conseguir ler a mensagem antes que
' a janela suma.
CriarAtalho pastaGrupo, "Alphafitus OS", "k", "iniciar.bat"
CriarAtalho pastaGrupo, "Instalar como Servico do Windows", "k", "instalar_servico.bat"
CriarAtalho pastaGrupo, "Iniciar Servico", "k", "iniciar_servico.bat"
CriarAtalho pastaGrupo, "Parar Servico", "k", "parar_servico.bat"
CriarAtalho pastaGrupo, "Status do Servico", "k", "status_servico.bat"
CriarAtalho pastaGrupo, "Remover Servico do Windows", "k", "remover_servico.bat"

Dim pastaAreaTrabalho
pastaAreaTrabalho = objShell.SpecialFolders("AllUsersDesktop")
CriarAtalho pastaAreaTrabalho, "Alphafitus OS", "k", "iniciar.bat"
