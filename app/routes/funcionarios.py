"""
Fase 188 — pedido do usuário: "onde eu cadastro os funcionários da empresa
(produção, laboratório, vendas), pra saber função, cargo, salário e poder
falar com eles" — cadastro próprio, separado de Usuários (login no
sistema): nem todo funcionário de produção precisa de acesso ao ERP.
`usuario_id` liga opcionalmente as duas pontas quando a mesma pessoa tem
os dois cadastros (ver migrations/schema_fase188.sql).

Salário é sensível de propósito: `funcionarios.visualizar` mostra o
cadastro inteiro MENOS o salário; só quem também tem
`funcionarios.ver_salario` recebe o campo `salario` de verdade — os dois
por padrão só vêm com o perfil Administrador (ver seed.py), quem
administra o sistema decide quem mais pode ver.
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit, security
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission, usuario_tem_permissao

bp = Blueprint("funcionarios", __name__, url_prefix="/api/v1/funcionarios")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _publico(row, ve_salario):
    d = dict(row)
    if not ve_salario:
        d.pop("salario", None)
    return d


def _funcionario_ou_404(conn, funcionario_id):
    row = conn.execute("SELECT * FROM funcionarios WHERE id = ?", (funcionario_id,)).fetchone()
    if row is None:
        raise ApiError("Funcionário não encontrado.", status=404)
    return row


@bp.get("")
@requires_permission("funcionarios", "visualizar")
def listar():
    conn = get_db()
    ve_salario = usuario_tem_permissao(conn, g.usuario_atual["id"], "funcionarios", "ver_salario")
    incluir_inativos = request.args.get("incluir_inativos") == "1"
    where = "" if incluir_inativos else "WHERE status = 'ativo'"
    rows = conn.execute(f"SELECT * FROM funcionarios {where} ORDER BY nome").fetchall()
    return jsonify([_publico(r, ve_salario) for r in rows])


@bp.get("/<int:funcionario_id>")
@requires_permission("funcionarios", "visualizar")
def obter(funcionario_id):
    conn = get_db()
    ve_salario = usuario_tem_permissao(conn, g.usuario_atual["id"], "funcionarios", "ver_salario")
    row = _funcionario_ou_404(conn, funcionario_id)
    return jsonify(_publico(row, ve_salario))


def _validar_e_normalizar(dados, anterior=None):
    nome = (dados.get("nome") or (anterior["nome"] if anterior else "")).strip()
    if not nome:
        raise ApiError("Informe o nome do funcionário.", status=400)
    # Pedido do usuário: email sempre obrigatório — é a chave usada pra
    # casar este funcionário com o chat interno do Whatts Inbox na hora de
    # enviar login/senha nova (ver módulo de envio, ainda pendente).
    email = (dados.get("email") or (anterior["email"] if anterior else "")).strip().lower()
    if not email or not security.email_valido(email):
        raise ApiError("Informe um e-mail válido do funcionário.", status=400)
    salario = dados.get("salario", anterior["salario"] if anterior else None)
    if salario == "":
        salario = None
    if salario is not None:
        try:
            salario = float(salario)
        except (TypeError, ValueError):
            raise ApiError("Salário inválido.", status=400)
        if salario < 0:
            raise ApiError("Salário não pode ser negativo.", status=400)
    campo = lambda chave: (dados.get(chave, anterior[chave] if anterior else None) or "").strip() or None
    return {
        "nome": nome,
        "setor": campo("setor"),
        "funcao": campo("funcao"),
        "registro_profissional": campo("registro_profissional"),
        "cpf": campo("cpf"),
        "telefone": campo("telefone"),
        "email": email,
        "endereco": campo("endereco"),
        "salario": salario,
        "data_admissao": campo("data_admissao"),
        "observacoes": campo("observacoes"),
        "usuario_id": dados.get("usuario_id", anterior["usuario_id"] if anterior else None) or None,
    }


@bp.post("")
@requires_permission("funcionarios", "cadastrar")
def criar():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    if dados.get("usuario_id"):
        if conn.execute("SELECT id FROM usuarios WHERE id = ?", (dados["usuario_id"],)).fetchone() is None:
            raise ApiError("Usuário (login) informado não existe.", status=400)

    valores = _validar_e_normalizar(dados)
    cur = conn.execute(
        """
        INSERT INTO funcionarios (nome, setor, funcao, registro_profissional, cpf, telefone, email, endereco,
                                   salario, data_admissao, observacoes, usuario_id, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (valores["nome"], valores["setor"], valores["funcao"], valores["registro_profissional"], valores["cpf"],
         valores["telefone"], valores["email"], valores["endereco"], valores["salario"],
         valores["data_admissao"], valores["observacoes"], valores["usuario_id"], usuario_atual["id"]),
    )
    funcionario_id = cur.lastrowid
    audit.registrar(conn, tabela="funcionarios", registro_id=funcionario_id, usuario_id=usuario_atual["id"],
                     acao="funcionario_criado", valor_novo={"nome": valores["nome"], "funcao": valores["funcao"]},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_publico(_funcionario_ou_404(conn, funcionario_id), True)), 201


@bp.put("/<int:funcionario_id>")
@requires_permission("funcionarios", "editar")
def editar(funcionario_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    anterior = _funcionario_ou_404(conn, funcionario_id)
    if dados.get("usuario_id"):
        if conn.execute("SELECT id FROM usuarios WHERE id = ?", (dados["usuario_id"],)).fetchone() is None:
            raise ApiError("Usuário (login) informado não existe.", status=400)

    ve_salario = usuario_tem_permissao(conn, usuario_atual["id"], "funcionarios", "ver_salario")
    valores = _validar_e_normalizar(dados, anterior)
    # Quem não tem `ver_salario` também não pode ALTERAR o salário — sem essa
    # trava, bastaria ter `funcionarios.editar` pra escrever um valor mesmo
    # sem nunca poder consultar o que já estava lá (e um PUT que omite o
    # campo já cai no valor anterior via `_validar_e_normalizar`, então só
    # bloqueia quem está de fato tentando MUDAR o número).
    if not ve_salario and valores["salario"] != anterior["salario"]:
        raise ApiError("Você não tem permissão para alterar o salário deste funcionário.", status=403)

    conn.execute(
        """
        UPDATE funcionarios SET nome = ?, setor = ?, funcao = ?, registro_profissional = ?, cpf = ?, telefone = ?,
               email = ?, endereco = ?, salario = ?, data_admissao = ?, observacoes = ?, usuario_id = ?,
               atualizado_em = ?, atualizado_por = ?
        WHERE id = ?
        """,
        (valores["nome"], valores["setor"], valores["funcao"], valores["registro_profissional"], valores["cpf"],
         valores["telefone"], valores["email"], valores["endereco"], valores["salario"],
         valores["data_admissao"], valores["observacoes"], valores["usuario_id"],
         _now_iso(), usuario_atual["id"], funcionario_id),
    )
    novo = _funcionario_ou_404(conn, funcionario_id)
    audit.registrar(conn, tabela="funcionarios", registro_id=funcionario_id, usuario_id=usuario_atual["id"],
                     acao="funcionario_editado", valor_anterior=_publico(anterior, True), valor_novo=_publico(novo, True),
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_publico(novo, ve_salario))


@bp.post("/<int:funcionario_id>/inativar")
@requires_permission("funcionarios", "inativar")
def inativar(funcionario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = _funcionario_ou_404(conn, funcionario_id)
    conn.execute("UPDATE funcionarios SET status = 'inativo', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
                 (_now_iso(), usuario_atual["id"], funcionario_id))
    audit.registrar(conn, tabela="funcionarios", registro_id=funcionario_id, usuario_id=usuario_atual["id"],
                     acao="funcionario_inativado", valor_anterior={"status": row["status"]}, valor_novo={"status": "inativo"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})


@bp.post("/<int:funcionario_id>/reativar")
@requires_permission("funcionarios", "inativar")
def reativar(funcionario_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    row = _funcionario_ou_404(conn, funcionario_id)
    conn.execute("UPDATE funcionarios SET status = 'ativo', atualizado_em = ?, atualizado_por = ? WHERE id = ?",
                 (_now_iso(), usuario_atual["id"], funcionario_id))
    audit.registrar(conn, tabela="funcionarios", registro_id=funcionario_id, usuario_id=usuario_atual["id"],
                     acao="funcionario_reativado", valor_anterior={"status": row["status"]}, valor_novo={"status": "ativo"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"ok": True})
