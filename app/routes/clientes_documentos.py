"""
Fase 103 — Documentos do Cliente.

Ver o cabeçalho de migrations/schema_fase103.sql para o racional completo
(por que base64-no-banco, por que a obrigatoriedade não é uma constraint de
banco, etc.). Este arquivo cobre a gestão dos documentos de um cliente já
existente pela tela DESKTOP de Comercial — a criação ATÔMICA de cliente +
documento(s) obrigatórios usada pelo App de Vendas em campo fica em
app/routes/vendas_app.py (`POST /vendas-app/clientes`), que reaproveita
`_validar_e_decodificar_documento` daqui para nunca duplicar a validação.

Diferente de `memorial_anexos.py` (Fase 27, que aceita qualquer
`tipo_mime`/tamanho declarado pelo cliente sem checar contra uma lista), aqui
exigimos que o tipo MIME esteja em `TIPOS_MIME_PERMITIDOS` — documento de
cliente (RG, CNPJ, contrato social, foto tirada pelo próprio app) não tem
motivo nenhum para ser um .exe ou .js disfarçado, e o `Content-Disposition`
do download sanitiza o nome do arquivo antes de ecoá-lo no header (o que
`memorial_anexos.py` não fazia — achado LOW da auditoria de segurança da
Fase 98, corrigido aqui na hora de escrever código novo em vez de copiar o
padrão antigo adiante).
"""
import base64
import binascii
import re

from flask import Blueprint, Response, g, jsonify, request

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission
from .comercial import _cliente_ou_404

bp = Blueprint("clientes_documentos", __name__, url_prefix="/api/v1/comercial")

TIPOS_MIME_PERMITIDOS = ("image/jpeg", "image/png", "image/webp", "application/pdf")
TAMANHO_MAXIMO_BYTES = 10 * 1024 * 1024


def _nome_arquivo_seguro(nome_arquivo):
    """Remove tudo que não seja letra/número/ponto/hífen/underscore antes de
    colocar o nome dentro do header Content-Disposition — mesmo cuidado que
    `memorial_anexos.py` (Fase 27) nunca teve: sem isso, um nome de arquivo
    contendo aspas ou quebra de linha poderia injetar campos extras no
    cabeçalho HTTP da resposta de download."""
    nome = re.sub(r'[^A-Za-z0-9._-]+', "_", nome_arquivo or "documento").strip("_") or "documento"
    return nome[:200]


def _validar_e_decodificar_documento(doc):
    """Recebe um dict no formato {nome, nome_arquivo, tipo_mime, dados} (o
    mesmo shape aceito por `memorial_anexos.py`) e devolve
    (nome, nome_arquivo, tipo_mime, conteudo_base64_limpo, tamanho_bytes) já
    validados, ou levanta ApiError. NUNCA escreve nada no banco — só
    valida/decodifica — para permitir que quem chama (aqui ou em
    vendas_app.py) valide TODOS os documentos de uma leva antes de inserir o
    primeiro, essencial para a criação atômica de cliente + documentos."""
    if not isinstance(doc, dict):
        raise ApiError("Cada documento deve ser um objeto com nome_arquivo, tipo_mime e dados.", status=400)

    nome_arquivo = (doc.get("nome_arquivo") or "").strip()
    if not nome_arquivo:
        raise ApiError("Informe nome_arquivo para cada documento.", status=400)
    tipo_mime = (doc.get("tipo_mime") or "").strip().lower()
    if tipo_mime not in TIPOS_MIME_PERMITIDOS:
        raise ApiError(
            f"Tipo de arquivo '{tipo_mime or 'desconhecido'}' não permitido para documento de cliente. "
            f"Tipos aceitos: {', '.join(TIPOS_MIME_PERMITIDOS)}.",
            status=400,
        )
    conteudo_base64 = doc.get("dados") or ""
    if not conteudo_base64:
        raise ApiError("Informe o conteúdo do documento em base64 (campo 'dados').", status=400)
    if "," in conteudo_base64 and conteudo_base64.strip().lower().startswith("data:"):
        conteudo_base64 = conteudo_base64.split(",", 1)[1]

    try:
        bruto = base64.b64decode(conteudo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(f"Conteúdo do documento '{nome_arquivo}' não é um base64 válido.", status=400)

    if len(bruto) == 0:
        raise ApiError(f"O documento '{nome_arquivo}' está vazio.", status=400)
    if len(bruto) > TAMANHO_MAXIMO_BYTES:
        raise ApiError(
            f"Documento '{nome_arquivo}' muito grande ({len(bruto) / (1024 * 1024):.1f} MB). "
            f"O limite por documento é {TAMANHO_MAXIMO_BYTES // (1024 * 1024)} MB.",
            status=400,
        )

    nome = (doc.get("nome") or nome_arquivo).strip()
    return nome, nome_arquivo, tipo_mime, conteudo_base64, len(bruto)


def _inserir_documento_cliente(conn, cliente_id, doc, usuario_id):
    """Assume que `doc` já passou por `_validar_e_decodificar_documento`
    (chamar direto sem validar antes é um bug de quem chama, não um caso a
    tratar aqui)."""
    nome, nome_arquivo, tipo_mime, conteudo_base64, tamanho = doc
    cur = conn.execute(
        """
        INSERT INTO clientes_documentos (cliente_id, nome, nome_arquivo, tipo_mime, dados, tamanho, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (cliente_id, nome, nome_arquivo, tipo_mime, conteudo_base64, tamanho, usuario_id),
    )
    return cur.lastrowid


def _documento_metadados(row):
    d = dict(row)
    d.pop("dados", None)
    return d


def _documento_ou_404(conn, cliente_id, documento_id):
    row = conn.execute(
        "SELECT * FROM clientes_documentos WHERE id = ? AND cliente_id = ?", (documento_id, cliente_id)
    ).fetchone()
    if row is None:
        raise ApiError("Documento não encontrado.", status=404)
    return row


@bp.get("/clientes/<int:cliente_id>/documentos")
@requires_permission("comercial", "visualizar")
def listar_documentos(cliente_id):
    conn = get_db()
    _cliente_ou_404(conn, cliente_id)
    rows = conn.execute(
        "SELECT * FROM clientes_documentos WHERE cliente_id = ? ORDER BY criado_em", (cliente_id,)
    ).fetchall()
    return jsonify([_documento_metadados(r) for r in rows])


@bp.post("/clientes/<int:cliente_id>/documentos")
@requires_permission("comercial", "cadastrar_cliente")
def enviar_documento(cliente_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _cliente_ou_404(conn, cliente_id)

    dados_entrada = request.get_json(silent=True) or {}
    doc_validado = _validar_e_decodificar_documento(dados_entrada)
    documento_id = _inserir_documento_cliente(conn, cliente_id, doc_validado, usuario_atual["id"])
    audit.registrar(
        conn, tabela="clientes_documentos", registro_id=documento_id, usuario_id=usuario_atual["id"],
        acao="documento_cliente_enviado",
        valor_novo={"cliente_id": cliente_id, "nome_arquivo": doc_validado[1], "tamanho": doc_validado[4]},
        ip=client_ip(), dispositivo=client_device(),
    )
    novo = conn.execute("SELECT * FROM clientes_documentos WHERE id = ?", (documento_id,)).fetchone()
    return jsonify(_documento_metadados(novo)), 201


@bp.get("/clientes/<int:cliente_id>/documentos/<int:documento_id>/download")
@requires_permission("comercial", "visualizar")
def baixar_documento(cliente_id, documento_id):
    conn = get_db()
    _cliente_ou_404(conn, cliente_id)
    documento = _documento_ou_404(conn, cliente_id, documento_id)
    bruto = base64.b64decode(documento["dados"])
    return Response(
        bruto,
        mimetype=documento["tipo_mime"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_nome_arquivo_seguro(documento["nome_arquivo"])}"'},
    )


@bp.delete("/clientes/<int:cliente_id>/documentos/<int:documento_id>")
@requires_permission("comercial", "cadastrar_cliente")
def excluir_documento(cliente_id, documento_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _cliente_ou_404(conn, cliente_id)
    documento = _documento_ou_404(conn, cliente_id, documento_id)
    conn.execute("DELETE FROM clientes_documentos WHERE id = ?", (documento_id,))
    audit.registrar(
        conn, tabela="clientes_documentos", registro_id=documento_id, usuario_id=usuario_atual["id"],
        acao="documento_cliente_excluido", valor_anterior=_documento_metadados(documento),
        ip=client_ip(), dispositivo=client_device(),
    )
    return "", 204
