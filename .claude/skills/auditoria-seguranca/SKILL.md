---
name: auditoria-seguranca
description: Auditoria de segurança adversarial do backend do Alphafitus OS (Flask + sqlite3 puro, sem ORM). Use sempre que o usuário pedir para verificar falhas de segurança, vulnerabilidades, auditoria de segurança, "checar com força" a segurança do sistema, ou revisar a segurança depois de mudanças em autenticação, permissões, 2FA, ou qualquer rota nova — mesmo que ele não use a palavra "auditoria" literalmente (ex.: "isso está seguro?", "alguém consegue burlar essa aprovação?", "essa rota vaza dado de outro usuário?").
---

# Auditoria de Segurança — Alphafitus OS

Isto NÃO é uma revisão de diff nem uma lista genérica de OWASP — é uma auditoria adversarial
do código de verdade, específica para como este sistema é construído. Toda descoberta precisa
vir de ler/gropar o arquivo real, com file:line e um cenário de exploração concreto (o request
que um atacante manda, o que ele ganha com isso). Nunca reporte "boa prática" genérica sem um
jeito real de explorar — isso só enche o relatório de ruído que ninguém vai agir em cima.

Contexto de arquitetura que já vale a pena saber antes de começar (evita reler tudo do zero):

- Flask + sqlite3 puro (sem ORM), uma conexão por request via `get_db()`. Rotas em
  `app/routes/*.py`, um blueprint por módulo (comercial, financeiro, fiscal, estoque, producao,
  usuarios, auth, solicitacoes_material, etc.).
- Auth: JWT access+refresh (`app/security.py`, `app/context.py::get_current_user`). Permissão
  via `@requires_permission("modulo","acao")`/`@requires_auth` (`app/permissions.py`), checada
  AO VIVO contra `usuario_perfil`/`perfil_permissao`/`permissoes` — nunca cacheada no token.
- 2FA: TOTP (`app/security.py::gerar_totp_secret`/`verificar_totp`) + "dispositivo confiável"
  (tabela `dispositivos_confiaveis_2fa`, `app/routes/auth.py::_criar_dispositivo_confiavel_2fa`/
  `_dispositivo_confiavel_2fa_valido`) — mexe em token opaco com expiração de 24h, sempre vale
  reconferir geração/expiração/revogação quando essa área for tocada de novo.
- Segregação de função: padrão repetido em vários módulos é
  `if x["solicitado_por"] == usuario_atual["id"]: raise ForbiddenError(...)`.
- NF-e: integração com provedor externo (Focus NFe), token de API guardado em config no banco.
- Upload de arquivo: `app/routes/memorial_anexos.py` (Memorial Técnico).
- Trilha de auditoria (`app/audit.py`) é para ser só-inserção.

## Metodologia (nesta ordem)

Para cada item abaixo, USE Grep/Read nos arquivos de verdade — não recite de memória. Onde
achar um padrão suspeito, abra o arquivo inteiro da rota para confirmar se é explorável ou se
já está mitigado por outra checagem antes/depois.

1. **Injeção SQL** — grep todo `app/routes/*.py` por f-string/`.format()`/`%` que monta texto de
   SQL (`conn.execute(f"...")`, `.format(` perto de `SELECT/UPDATE/DELETE/INSERT`). Para cada
   ocorrência, decida: o texto interpolado vem de uma lista fixa no próprio código (nome de
   coluna, cláusula WHERE montada a partir de um whitelist), ou vem de
   `request.args`/`request.get_json()`/parâmetro de rota direto no TEXTO da query (não como
   parâmetro `?`)? Só o segundo caso é achado real.

2. **Controle de acesso quebrado / IDOR** — rotas com `<int:id>` que buscam um recurso: elas
   confirmam que aquele recurso pertence/deveria ser visível para quem pediu, ou só checam uma
   permissão de módulo genérica e servem qualquer id pedido? Amostre pelo menos 15-20 rotas
   espalhadas por módulos diferentes, não só um.

3. **Autenticação/sessão** — `app/security.py` e `app/routes/auth.py`: existe algum segredo JWT
   com fallback hardcoded (falha aberto se `ALPHAFITUS_JWT_SECRET` não estiver definida)?
   Algoritmo de hash de senha é forte (nunca sha256/md5 puro)? Refresh token é rotacionado/
   guardado com hash? O bloqueio por tentativas (`tentativas_login_falhas`) tem algum jeito de
   ser burlado? O token de dispositivo confiável (`dispositivos_confiaveis_2fa`) checa
   usuario_id, `revogado`, e `expira_em` todos ao mesmo tempo, ou algum caminho pula uma dessas
   checagens?

4. **Segregação de função** — grep todo o padrão `solicitado_por.*==.*usuario_atual\["id"\]` (e
   variações). Para cada resultado, existe um SEGUNDO jeito de chegar na mesma mudança de estado
   (outra rota, outro branch) que não tem a mesma checagem?

5. **Upload de arquivo** — `memorial_anexos.py`: o nome do arquivo enviado pelo usuário é usado
   direto em algum caminho de disco (risco de path traversal)? Existe validação de
   extensão/MIME/tamanho, ou é só confiar no que o navegador mandou?

6. **Vazamento de segredo** — todo dict de `usuarios` que chega em `jsonify()` remove
   `dois_fatores_secret`/`senha_hash` (grep por `.pop("dois_fatores_secret"`/`.pop("senha_hash"`
   e confirme que TODA rota que devolve um usuário passa por ali, não só a mais óbvia)? A rota
   de configuração fiscal/NF-e devolve o token do provedor de volta num GET, ou só aceita
   escrever e nunca ecoa?

7. **Mass assignment** — rotas PUT/PATCH que montam um UPDATE a partir de
   `request.get_json()`: elas pegam campo por campo explicitamente, ou fazem algo tipo
   `**dados` que deixaria a pessoa mandar um campo sensível (status, permissão, id de outro
   registro) que não deveria poder setar sozinha?

8. **CORS/CSRF** — confirme que autenticação é só Bearer token no header `Authorization` (não
   cookie) — nesse caso CSRF clássico não se aplica; só vale a pena reportar se achar algum
   lugar usando cookie de sessão em paralelo.

9. **Rate limiting** — além do bloqueio por conta (`tentativas_login_falhas`), existe algum
   limite entre contas DIFERENTES em `/auth/login` ou `/auth/2fa/verificar`? Testar login em
   paralelo contra muitas contas diferentes seria livre?

10. **Config/dependências** — `requirements.txt` tem alguma versão flagrantemente desatualizada
    (checagem rápida, não é pra virar uma pesquisa de CVE)? Existe `debug=True`/`app.debug` em
    algum lugar que rodaria em produção?

## Formato do relatório

Lista ordenada por severidade (crítico → alto → médio → baixo). Cada item:

```
[SEVERIDADE] arquivo.py:linha — resumo de uma frase
Cenário: o que um atacante manda e o que ele ganha
```

Itens conferidos e OK (sem achado) podem ser citados em uma linha cada no final, sob um
cabeçalho "Conferido, sem achado" — não precisa de parágrafo por item. Nunca preencha o
relatório com sugestões de "boa prática" sem exploração concreta associada.
