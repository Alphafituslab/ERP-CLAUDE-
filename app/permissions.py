"""
Autorização granular por ação (não por tela), como exigido no documento de
arquitetura, seção 7. Cada rota declara exatamente qual "modulo.acao" ela
exige; a checagem é sempre feita no banco, na hora, nunca a partir de dados
guardados no token — assim uma mudança de permissão feita por um
administrador tem efeito imediato na próxima chamada do usuário afetado,
sem precisar esperar o token expirar ou pedir novo login.
"""
import functools

from flask import g

from .context import ForbiddenError, get_current_user, get_db


def usuario_tem_permissao(conn, usuario_id: int, modulo: str, acao: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM usuario_perfil up
        JOIN perfil_permissao pp ON pp.perfil_id = up.perfil_id
        JOIN permissoes p ON p.id = pp.permissao_id
        WHERE up.usuario_id = ? AND p.modulo = ? AND p.acao = ?
        LIMIT 1
        """,
        (usuario_id, modulo, acao),
    ).fetchone()
    return row is not None


def permissoes_do_usuario(conn, usuario_id: int):
    rows = conn.execute(
        """
        SELECT DISTINCT p.modulo, p.acao, p.exige_dupla_aprovacao
        FROM usuario_perfil up
        JOIN perfil_permissao pp ON pp.perfil_id = up.perfil_id
        JOIN permissoes p ON p.id = pp.permissao_id
        WHERE up.usuario_id = ?
        ORDER BY p.modulo, p.acao
        """,
        (usuario_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def requires_permission(modulo: str, acao: str):
    """Decorator de rota Flask: exige autenticação + a permissão específica
    'modulo.acao'. Em caso de falha, devolve 401 (não autenticado) ou 403
    (autenticado, mas sem permissão) — nunca deixa a rota executar."""

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(*args, **kwargs):
            usuario = get_current_user()
            conn = get_db()
            if not usuario_tem_permissao(conn, usuario["id"], modulo, acao):
                raise ForbiddenError(
                    f"Permissão necessária: {modulo}.{acao}. "
                    f"Solicite a um administrador que a conceda ao seu perfil."
                )
            g.permissao_verificada = (modulo, acao)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def requires_auth(view_func):
    """Decorator mais simples: só exige estar logado, sem permissão específica
    (usado em rotas como 'ver meu próprio perfil' ou 'minhas sessões')."""

    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        get_current_user()
        return view_func(*args, **kwargs)

    return wrapper


def bloquear_atribuicao_alem_das_proprias_permissoes(conn, usuario_solicitante_id: int, perfil_ids_alvo):
    """Regra de segregação de função (documento de arquitetura, seção 4):
    ninguém pode conceder — para SI MESMO, para um usuário já existente ou
    para um usuário RECÉM-CRIADO — um perfil cujo conjunto de permissões
    ultrapasse o que o próprio solicitante já possui NESTE EXATO MOMENTO.

    Achado de auditoria de segurança (corrigido aqui): a versão anterior
    desta função (`bloquear_autoelevacao`) só comparava o NOME do perfil
    contra a string literal "Administrador" e só entrava em ação quando
    `usuario_solicitante_id == usuario_alvo_id`. Isso deixava dois
    caminhos abertos: (1) `POST /usuarios` (criar um usuário novo) nunca
    chamava nenhuma checagem — qualquer um com `usuarios.cadastrar`
    conseguia criar uma conta nova e já anexar o perfil Administrador a
    ela na mesma chamada, já que o "alvo" nunca é o próprio solicitante
    numa criação; (2) um perfil PERSONALIZADO carregado com todas as
    permissões (via `PUT /perfis/<id>/permissoes` sobre um perfil ao qual
    o atacante ainda não pertence — permitido, e por si só inofensivo até
    alguém ser atribuído a ele) passava batido pela comparação de nome.
    Comparar o CONJUNTO DE PERMISSÕES em vez do nome do perfil, e aplicar
    a checagem em toda atribuição (não só quando o alvo é o próprio
    solicitante), fecha os dois caminhos de uma vez — inclusive qualquer
    perfil futuro que agregue poder equivalente sem se chamar
    "Administrador"."""
    if not perfil_ids_alvo:
        return
    placeholders = ",".join("?" for _ in perfil_ids_alvo)
    permissoes_dos_perfis_alvo = conn.execute(
        f"SELECT DISTINCT permissao_id FROM perfil_permissao WHERE perfil_id IN ({placeholders})",
        perfil_ids_alvo,
    ).fetchall()
    ids_permissoes_alvo = {r["permissao_id"] for r in permissoes_dos_perfis_alvo}
    if not ids_permissoes_alvo:
        return
    permissoes_do_solicitante = conn.execute(
        """
        SELECT DISTINCT pp.permissao_id FROM usuario_perfil up
        JOIN perfil_permissao pp ON pp.perfil_id = up.perfil_id
        WHERE up.usuario_id = ?
        """,
        (usuario_solicitante_id,),
    ).fetchall()
    ids_permissoes_solicitante = {r["permissao_id"] for r in permissoes_do_solicitante}
    if ids_permissoes_alvo - ids_permissoes_solicitante:
        raise ForbiddenError(
            "Você não pode atribuir um perfil com permissões que você mesmo não possui "
            "(regra de segregação de função). Peça a um administrador para fazer essa atribuição."
        )


def bloquear_autoedicao_de_permissoes_do_proprio_perfil(conn, usuario_solicitante_id: int, perfil_id: int):
    """Mesma regra de segregação de função de
    `bloquear_atribuicao_alem_das_proprias_permissoes`, mas para o OUTRO
    caminho de auto-elevação de privilégio possível no
    sistema: em vez de se conceder o perfil Administrador diretamente
    (bloqueado acima), um usuário com `perfis.editar` poderia editar as
    PERMISSÕES de um perfil PERSONALIZADO ao qual ele mesmo já pertence —
    por exemplo, adicionar `usuarios.cadastrar` ou qualquer outra
    permissão sensível a esse perfil, ganhando o poder imediatamente
    (permissões são checadas ao vivo no banco a cada requisição, nunca a
    partir do token — ver `requires_permission` acima). Achado de
    auditoria de segurança: `PUT /perfis/<id>/permissoes` tinha a mesma
    exposição que `PUT /usuarios/<id>/perfis` já resolvia, mas sem a
    guarda equivalente.

    Em vez de tentar calcular quais permissões específicas seriam um
    "aumento" (frágil — e se o usuário já tem parte delas por outro
    perfil?), a regra é simples e no mesmo espírito de todas as outras
    segregações de função já usadas no sistema (Fase 2, 21, 22, 31):
    ninguém pode ser ao mesmo tempo quem PEDE a mudança e quem se
    BENEFICIA dela — um usuário nunca pode alterar as permissões de um
    perfil ao qual ele mesmo pertence, mesmo para removê-las; peça a
    outro administrador."""
    pertence = conn.execute(
        "SELECT 1 FROM usuario_perfil WHERE usuario_id = ? AND perfil_id = ? LIMIT 1",
        (usuario_solicitante_id, perfil_id),
    ).fetchone()
    if pertence:
        raise ForbiddenError(
            "Você não pode alterar as permissões de um perfil ao qual você mesmo pertence "
            "(regra de segregação de função). Peça a outro administrador para fazer essa alteração."
        )
