import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit, backup_service, security, senha_sync_service
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..imagens import validar_imagem_base64
from ..permissions import (
    bloquear_atribuicao_alem_das_proprias_permissoes,
    bloquear_excecao_alem_das_proprias_permissoes,
    requires_permission,
)

bp = Blueprint("usuarios", __name__, url_prefix="/api/v1/usuarios")

# Fase 44 — "Usuários Online" (Administração do Memorial Técnico): janela
# de tolerância para considerar alguém "online agora". `ultimo_acesso_em`
# (app/context.py) é atualizado a cada requisição autenticada — 5 minutos
# cobre alguém que está de fato navegando pelo sistema (mesmo com telas
# que não fazem chamada nenhuma por um tempo) sem contar como "online"
# quem só logou de manhã e não voltou a usar o sistema.
ONLINE_JANELA_MINUTOS = 5


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _limite_online():
    return (datetime.datetime.utcnow() - datetime.timedelta(minutes=ONLINE_JANELA_MINUTOS)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _publico(usuario_row):
    d = dict(usuario_row)
    d.pop("senha_hash", None)
    d.pop("dois_fatores_secret", None)
    return d


def _perfis_do_usuario(conn, usuario_id):
    rows = conn.execute(
        "SELECT pf.id, pf.nome FROM usuario_perfil up JOIN perfis pf ON pf.id = up.perfil_id WHERE up.usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@bp.get("")
@requires_permission("usuarios", "visualizar")
def listar():
    # Fase 187 — pedido do usuário: ver direto na lista de Usuários (não só
    # na tela separada "Usuários Online") quem está online agora e há
    # quanto tempo — mesma janela de 5 min já usada em `usuarios_online()`.
    conn = get_db()
    limite = _limite_online()
    rows = conn.execute("SELECT * FROM usuarios ORDER BY nome").fetchall()
    resultado = []
    for r in rows:
        u = _publico(r)
        u["perfis"] = _perfis_do_usuario(conn, u["id"])
        u["online"] = bool(u["ultimo_acesso_em"]) and u["ultimo_acesso_em"] >= limite
        resultado.append(u)
    return jsonify(resultado)


@bp.get("/<int:usuario_id>")
@requires_permission("usuarios", "visualizar")
def obter(usuario_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    u = _publico(row)
    u["perfis"] = _perfis_do_usuario(conn, usuario_id)
    # Fase 191c — pedido do usuário: "Editar" precisa vir com a Função já
    # preenchida (vive em funcionarios.funcao, não em usuarios).
    funcionario_row = conn.execute(
        "SELECT funcao FROM funcionarios WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()
    u["funcao"] = funcionario_row["funcao"] if funcionario_row else None
    return jsonify(u)


@bp.post("")
@requires_permission("usuarios", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip().lower()
    senha = dados.get("senha") or ""
    perfil_ids = dados.get("perfil_ids") or []
    # Pedido do usuário (2026-09-16): poder já colocar a foto no ato do
    # cadastro, em vez de só o próprio usuário conseguir subir depois
    # (Fase 113, "Minha Conta") — mesma validação, mesmo formato (data
    # URI base64), reaproveitados sem duplicar a lógica de decodificação.
    foto_perfil = validar_imagem_base64(dados.get("foto_perfil"))
    # Pedido do usuário (2026-09-16): poder já cadastrar o celular (WhatsApp)
    # no ato da criação, pra habilitar "Enviar por WhatsApp" no login/senha
    # provisória mostrada logo em seguida — sem precisar esperar a pessoa
    # cadastrar o próprio celular depois em "Minha Conta" (Fase 158).
    celular = (dados.get("celular") or "").strip() or None
    # Fase 191 — pedido do usuário: dar pra escolher a Função já na criação
    # do usuário (antes só dava pra completar depois em Funcionários).
    funcao = (dados.get("funcao") or "").strip() or None
    conn = get_db()

    if not nome or not email or not senha:
        raise ApiError("Informe nome, email e senha.", status=400)
    if not security.email_valido(email):
        raise ApiError("Informe um e-mail válido.", status=400)

    problemas = security.validar_politica_senha(senha)
    if problemas:
        raise ApiError("Senha não atende à política de segurança: " + " ".join(problemas), status=400)

    existente = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
    if existente:
        raise ApiError("Já existe um usuário com este email.", status=409)

    # Achado de auditoria de segurança: sem esta checagem, qualquer um com
    # só `usuarios.cadastrar` (uma permissão de "cadastrar gente nova", não
    # de "administrar o sistema") conseguia criar uma conta nova e já
    # anexar o perfil Administrador (ou qualquer outro) a ela na mesma
    # chamada — mesma regra de segregação de função que `PUT /usuarios/
    # <id>/perfis` já aplicava para um usuário EXISTENTE, agora também
    # aqui, na criação.
    bloquear_atribuicao_alem_das_proprias_permissoes(conn, usuario_atual["id"], perfil_ids)

    senha_hash = security.hash_password(senha)
    cur = conn.execute(
        """
        INSERT INTO usuarios (nome, email, senha_hash, senha_deve_trocar, criado_por, foto_perfil, celular)
        VALUES (?, ?, ?, 1, ?, ?, ?)
        """,
        (nome, email, senha_hash, usuario_atual["id"], foto_perfil, celular),
    )
    novo_id = cur.lastrowid

    for perfil_id in perfil_ids:
        conn.execute(
            "INSERT INTO usuario_perfil (usuario_id, perfil_id, atribuido_por) VALUES (?, ?, ?)",
            (novo_id, perfil_id, usuario_atual["id"]),
        )

    audit.registrar(conn, tabela="usuarios", registro_id=novo_id, usuario_id=usuario_atual["id"],
                     acao="usuario_criado", valor_novo={"nome": nome, "email": email, "perfil_ids": perfil_ids},
                     ip=client_ip(), dispositivo=client_device())

    # Fase 188b — pedido do usuário: todo Usuário (login) criado no ERP já
    # deve aparecer automaticamente em Funcionários, vinculado e marcado
    # como "usuário do sistema" — sem precisar cadastrar a mesma pessoa duas
    # vezes à mão. Função/setor/salário ficam em branco pra completar
    # depois em Funcionários; nome/email/celular vêm de graça daqui.
    #
    # Fase 188c — quando quem está chamando é o PRÓPRIO formulário de
    # Funcionários marcando "é usuário do sistema" num funcionário que já
    # existe (editar), esse funcionário já vai ser atualizado com o
    # `usuario_id` novo logo em seguida (ver PUT /funcionarios/<id>) — criar
    # um funcionário automático aqui duplicaria a pessoa. `pular_criacao_
    # funcionario` deixa esse caso pular a criação automática.
    funcionario_id = None
    if not dados.get("pular_criacao_funcionario"):
        cur_f = conn.execute(
            "INSERT INTO funcionarios (nome, email, telefone, funcao, usuario_id, criado_por) VALUES (?, ?, ?, ?, ?, ?)",
            (nome, email, celular, funcao, novo_id, usuario_atual["id"]),
        )
        funcionario_id = cur_f.lastrowid

    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (novo_id,)).fetchone()
    u = _publico(row)
    u["perfis"] = _perfis_do_usuario(conn, novo_id)
    u["funcionario_id"] = funcionario_id
    return jsonify(u), 201


@bp.put("/<int:usuario_id>")
@requires_permission("usuarios", "editar")
def editar(usuario_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    anterior = _publico(row)

    nome = dados.get("nome", row["nome"])
    email = (dados.get("email", row["email"]) or "").strip().lower()
    if not security.email_valido(email):
        raise ApiError("Informe um e-mail válido.", status=400)

    # Pedido do usuário (2026-09-16): a tela de Editar (administrador
    # mexendo no cadastro de OUTRO usuário) também precisa poder colocar/
    # trocar a foto, não só a de criação (Fase 182) e o autosserviço
    # (Fase 113). "foto_perfil" só é tocado se a chave vier no corpo — do
    # contrário mantém a foto atual (não força reenviar em todo PUT que
    # só quer mudar nome/email).
    if "foto_perfil" in dados:
        foto_perfil = validar_imagem_base64(dados.get("foto_perfil"))
    else:
        foto_perfil = row["foto_perfil"]

    # Fase 191c — pedido do usuário: "Editar" ganhou os mesmos campos de
    # "Criar" (Celular, Função) — só toca no que veio na requisição, pra
    # não apagar o que já estava lá num PUT que só mexe em outra coisa.
    celular = dados.get("celular", row["celular"])

    conn.execute(
        "UPDATE usuarios SET nome = ?, email = ?, celular = ?, foto_perfil = ?, atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (nome, email, celular, foto_perfil, _now_iso(), usuario_atual["id"], usuario_id),
    )
    if "funcao" in dados:
        conn.execute(
            "UPDATE funcionarios SET funcao = ? WHERE usuario_id = ?",
            (dados.get("funcao"), usuario_id),
        )

    novo_row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    novo = _publico(novo_row)
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="usuario_editado", valor_anterior=anterior, valor_novo=novo,
                     ip=client_ip(), dispositivo=client_device())
    novo["perfis"] = _perfis_do_usuario(conn, usuario_id)
    return jsonify(novo)


@bp.post("/<int:usuario_id>/resetar-senha")
@requires_permission("usuarios", "editar")
def resetar_senha(usuario_id):
    """Pedido do usuário (2026-09-16): "se o usuário perder o acesso,
    poder ver a senha que ele colocou e reenviar, ou resetar pra um
    padrão". Ver a senha original NÃO é possível por desenho — ela é
    guardada só como hash de mão única (`security.hash_password`), o
    mesmo motivo pelo qual nenhum sistema sério devolve senha em texto
    puro (se fosse possível, qualquer vazamento do banco exporia a
    senha de todo mundo). O equivalente seguro, que cobre a mesma
    necessidade prática, é o que esta rota faz: gera uma senha
    PROVISÓRIA nova, mostra ela UMA VEZ (só nesta resposta — não fica
    salva em nenhum lugar recuperável depois) pra quem administra
    usuários repassar à pessoa, e força a troca no próximo login (mesma
    tela usada quando o usuário é criado, ver `senha_deve_trocar` em
    /auth/login)."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)

    senha_provisoria = security.gerar_senha_forte()
    conn.execute(
        """
        UPDATE usuarios
        SET senha_hash = ?, senha_deve_trocar = 1, tentativas_login_falhas = 0, bloqueado_ate = NULL
        WHERE id = ?
        """,
        (security.hash_password(senha_provisoria), usuario_id),
    )
    # Mesmo motivo do endurecimento da Fase 169 em /auth/trocar-senha: uma
    # sessão aberta com a senha antiga (ex.: de quem perdeu o acesso e teve
    # a conta comprometida) não pode continuar válida depois do reset.
    conn.execute(
        "UPDATE sessoes SET revogado = 1, revogado_em = ? WHERE usuario_id = ? AND revogado = 0",
        (datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"), usuario_id),
    )
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="senha_resetada_por_administrador", ip=client_ip(), dispositivo=client_device())

    # Fase 188d — pedido do usuário: a senha provisória gerada aqui também
    # já sincroniza com Protocolo/Memorial/HPLC (best effort — quem não tem
    # conta lá simplesmente não recebe nada, ver senha_sync_service), pra
    # já dar acesso imediato caso a pessoa precise entrar direto num
    # desses sistemas antes mesmo de completar a troca obrigatória no ERP.
    senha_sync_service.sincronizar_senha_em_todos_sistemas(usuario_id, row["email"], senha_provisoria)
    return jsonify({"ok": True, "senha_provisoria": senha_provisoria, "email": row["email"]})


@bp.post("/<int:usuario_id>/enviar-credenciais-whatsapp")
@requires_permission("usuarios", "editar")
def enviar_credenciais_whatsapp(usuario_id):
    """Fase 186 — pedido do usuário: ao criar um usuário ou resetar a senha
    dele, se a pessoa já tiver celular (WhatsApp) cadastrado, poder mandar
    login + senha provisória direto pra ela por lá, em vez de precisar
    copiar/colar manualmente em outra conversa. Reaproveita o MESMO canal
    já usado em `/auth/recuperar-senha` (Fase 158) — a mesma Evolution API
    configurada em Sistema > Backups, sem integração nova nenhuma. O texto
    (email/senha) só existe nesta chamada: como a senha provisória nunca é
    salva em lugar recuperável nenhum, é o FRONTEND (que acabou de recebê-la
    da resposta de criar/resetar) quem manda ela de volta aqui pra ser
    repassada — nunca lida do banco."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    senha_provisoria = dados.get("senha_provisoria") or ""
    if not senha_provisoria:
        raise ApiError("Informe a senha provisória a enviar.", status=400)
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    row = dict(row)
    # O número usado é sempre o já cadastrado na conta — nunca um número
    # informado na hora por quem está enviando, pra garantir que a senha só
    # vai pro WhatsApp que a própria pessoa já associou ao email dela.
    if not row.get("celular"):
        raise ApiError("Este usuário não tem celular (WhatsApp) cadastrado.", status=400)

    texto = (
        "Alphafitus OS — acesso ao sistema\n\n"
        f"Login: {row['email']}\n"
        f"Senha provisória: {senha_provisoria}\n\n"
        "Use essa senha só na primeira vez — o sistema vai pedir pra você escolher a senha definitiva."
    )
    config_whats = backup_service.obter_configuracao(conn)
    try:
        backup_service.enviar_texto_whatsapp(config_whats, row["celular"], texto)
    except Exception as erro:
        raise ApiError(f"Falha ao enviar por WhatsApp: {erro}", status=502)

    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="credenciais_enviadas_por_whatsapp", ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.put("/<int:usuario_id>/perfis")
@requires_permission("usuarios", "editar")
def definir_perfis(usuario_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    perfil_ids = dados.get("perfil_ids")
    conn = get_db()

    if perfil_ids is None or not isinstance(perfil_ids, list):
        raise ApiError("Informe perfil_ids como lista.", status=400)

    alvo = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if alvo is None:
        raise ApiError("Usuário não encontrado.", status=404)

    bloquear_atribuicao_alem_das_proprias_permissoes(conn, usuario_atual["id"], perfil_ids)

    anteriores = _perfis_do_usuario(conn, usuario_id)
    conn.execute("DELETE FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,))
    for perfil_id in perfil_ids:
        conn.execute(
            "INSERT INTO usuario_perfil (usuario_id, perfil_id, atribuido_por) VALUES (?, ?, ?)",
            (usuario_id, perfil_id, usuario_atual["id"]),
        )
    novos = _perfis_do_usuario(conn, usuario_id)

    audit.registrar(conn, tabela="usuario_perfil", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="perfis_do_usuario_alterados", valor_anterior=anteriores, valor_novo=novos,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"usuario_id": usuario_id, "perfis": novos})


def _excecoes_do_usuario(conn, usuario_id):
    rows = conn.execute(
        "SELECT permissao_id, tipo FROM usuario_permissao_excecao WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@bp.get("/<int:usuario_id>/excecoes-permissao")
@requires_permission("usuarios", "editar")
def listar_excecoes_permissao(usuario_id):
    conn = get_db()
    if conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone() is None:
        raise ApiError("Usuário não encontrado.", status=404)
    return jsonify(_excecoes_do_usuario(conn, usuario_id))


@bp.put("/<int:usuario_id>/excecoes-permissao")
@requires_permission("usuarios", "editar")
def definir_excecoes_permissao(usuario_id):
    """Fase 184 — pedido do usuário: "dentro de um único [perfil], como
    exemplo Qualidade, tem vários abas dentro que gostaria que usuários
    possam ou não acessar". Guarda só o DESVIO em relação ao que os perfis
    da pessoa já dariam (ver schema_fase184.sql) — 'conceder' dá uma
    permissão a mais que nenhum perfil dela dá, 'negar' tira uma que algum
    perfil dela dá. Substitui a lista inteira (mesmo padrão de
    `definir_perfis` acima), não faz merge incremental."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    excecoes = dados.get("excecoes")
    conn = get_db()

    if excecoes is None or not isinstance(excecoes, list):
        raise ApiError("Informe 'excecoes' como lista de {permissao_id, tipo}.", status=400)
    ids_vistos = set()
    for e in excecoes:
        if (
            not isinstance(e, dict)
            or e.get("tipo") not in ("conceder", "negar")
            or not isinstance(e.get("permissao_id"), int)
        ):
            raise ApiError("Cada exceção precisa de 'permissao_id' (número) e 'tipo' ('conceder' ou 'negar').", status=400)
        if e["permissao_id"] in ids_vistos:
            raise ApiError(f"Permissão {e['permissao_id']} repetida na lista de exceções.", status=400)
        ids_vistos.add(e["permissao_id"])

    alvo = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if alvo is None:
        raise ApiError("Usuário não encontrado.", status=404)

    # Mesma lógica de segregação de função de `definir_perfis`: ninguém
    # pode alterar as PRÓPRIAS exceções (removeria um 'negar' que outro
    # administrador colocou como restrição, ou adicionaria um 'conceder'
    # pra si mesmo por essa via em vez da de perfil).
    if usuario_id == usuario_atual["id"]:
        raise ForbiddenError(
            "Você não pode alterar suas próprias exceções de permissão "
            "(regra de segregação de função). Peça a outro administrador para fazer essa alteração."
        )

    ids_permissoes_validas = {r["id"] for r in conn.execute("SELECT id FROM permissoes").fetchall()}
    for permissao_id in ids_vistos:
        if permissao_id not in ids_permissoes_validas:
            raise ApiError(f"Permissão {permissao_id} não existe.", status=400)

    bloquear_excecao_alem_das_proprias_permissoes(conn, usuario_atual["id"], excecoes)

    anteriores = _excecoes_do_usuario(conn, usuario_id)
    conn.execute("DELETE FROM usuario_permissao_excecao WHERE usuario_id = ?", (usuario_id,))
    for e in excecoes:
        conn.execute(
            """
            INSERT INTO usuario_permissao_excecao (usuario_id, permissao_id, tipo, criado_em, criado_por)
            VALUES (?, ?, ?, ?, ?)
            """,
            (usuario_id, e["permissao_id"], e["tipo"], _now_iso(), usuario_atual["id"]),
        )
    novas = _excecoes_do_usuario(conn, usuario_id)

    audit.registrar(conn, tabela="usuario_permissao_excecao", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="excecoes_de_permissao_alteradas", valor_anterior=anteriores, valor_novo=novas,
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"usuario_id": usuario_id, "excecoes": novas})


@bp.post("/<int:usuario_id>/inativar")
@requires_permission("usuarios", "inativar")
def inativar(usuario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    if usuario_id == usuario_atual["id"]:
        raise ApiError("Você não pode inativar a própria conta.", status=400)
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    conn.execute(
        "UPDATE usuarios SET status = 'inativo', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], usuario_id),
    )
    # Fase 169 (endurecimento) — inativar agora derruba na hora tudo que
    # aquele usuário tinha ativo: sessões (refresh tokens) e dispositivos
    # confiáveis de 2FA. Antes, o único freio era o `get_current_user`
    # rejeitar cada request pelo `status` — mas o refresh continuava
    # rotacionando token, o dispositivo confiável seguia válido por 24h, e
    # se a conta fosse REATIVADA tudo isso ressuscitava. Mesma coisa que já
    # é feita ao trocar/redefinir senha.
    conn.execute(
        "UPDATE sessoes SET revogado = 1, revogado_em = ?, revogado_por = ? WHERE usuario_id = ? AND revogado = 0",
        (_now_iso(), usuario_atual["id"], usuario_id),
    )
    conn.execute(
        "UPDATE dispositivos_confiaveis_2fa SET revogado = 1 WHERE usuario_id = ? AND revogado = 0",
        (usuario_id,),
    )
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="usuario_inativado", valor_anterior={"status": row["status"]}, valor_novo={"status": "inativo"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.post("/<int:usuario_id>/reativar")
@requires_permission("usuarios", "inativar")
def reativar(usuario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        raise ApiError("Usuário não encontrado.", status=404)
    conn.execute(
        "UPDATE usuarios SET status = 'ativo', tentativas_login_falhas = 0, bloqueado_ate = NULL, "
        "atualizado_em = ?, atualizado_por = ? WHERE id = ?",
        (_now_iso(), usuario_atual["id"], usuario_id),
    )
    audit.registrar(conn, tabela="usuarios", registro_id=usuario_id, usuario_id=usuario_atual["id"],
                     acao="usuario_reativado", valor_anterior={"status": row["status"]}, valor_novo={"status": "ativo"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.get("/online")
@requires_permission("usuarios", "visualizar")
def usuarios_online():
    """Fase 44 — "Usuários Online" (item da Administração do Memorial
    Técnico que o cliente pediu para replicar, ver schema_fase44.sql).
    Reaproveita a mesma permissão `usuarios.visualizar` de sempre — ver
    quem está online é uma extensão natural de ver a lista de usuários,
    não uma capacidade nova. Devolve TODOS os usuários ativos, cada um já
    com `online` calculado a partir de `ultimo_acesso_em` — o front decide
    como destacar/ordenar; banco vazio ou sem ninguém navegando agora
    simplesmente devolve todo mundo com `online: false`, sem quebrar."""
    conn = get_db()
    limite = _limite_online()
    rows = conn.execute("SELECT * FROM usuarios WHERE status = 'ativo' ORDER BY nome").fetchall()
    resultado = []
    for r in rows:
        u = _publico(r)
        u["perfis"] = _perfis_do_usuario(conn, u["id"])
        u["online"] = bool(u["ultimo_acesso_em"]) and u["ultimo_acesso_em"] >= limite
        resultado.append(u)
    resultado.sort(key=lambda u: (not u["online"], u["nome"]))
    return jsonify({"janela_minutos": ONLINE_JANELA_MINUTOS, "usuarios": resultado})
