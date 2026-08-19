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


PERFIL_ADMINISTRADOR = "Administrador"


def bloquear_autoelevacao(conn, usuario_solicitante_id: int, usuario_alvo_id: int, perfil_ids_alvo):
    """Regra de segregação de função (documento de arquitetura, seção 4):
    ninguém pode conceder a SI MESMO um perfil administrativo. Esta é a
    implementação de referência do padrão de dupla aprovação que as Fases
    2-3 vão reaplicar em aprovação de lote, fórmula, CoA etc. — nenhum
    usuário pode ser ao mesmo tempo solicitante e aprovador de uma mudança
    que amplia seu próprio poder no sistema. Um administrador ainda pode
    conceder o perfil Administrador a OUTRO usuário normalmente."""
    if not perfil_ids_alvo or usuario_solicitante_id != usuario_alvo_id:
        return
    placeholders = ",".join("?" for _ in perfil_ids_alvo)
    rows = conn.execute(
        f"SELECT id, nome FROM perfis WHERE id IN ({placeholders}) AND nome = ?",
        (*perfil_ids_alvo, PERFIL_ADMINISTRADOR),
    ).fetchall()
    if rows:
        raise ForbiddenError(
            "Um usuário não pode conceder a si mesmo o perfil Administrador "
            "(regra de segregação de função). Peça a outro administrador para fazer essa alteração."
        )


def bloquear_autoedicao_de_permissoes_do_proprio_perfil(conn, usuario_solicitante_id: int, perfil_id: int):
    """Mesma regra de segregação de função de `bloquear_autoelevacao`, mas
    para o OUTRO caminho de auto-elevação de privilégio possível no
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
