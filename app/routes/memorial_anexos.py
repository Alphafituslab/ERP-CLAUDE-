"""
Fase 27 — Anexos de arquivo do Memorial Técnico ANVISA.

A Fase 24 (fundação do módulo) deixou de propósito de fora "anexos de
arquivo (laudos, especificações, rótulos) a um memorial", citando-os como
próximo passo. Esta fase entrega isso: upload, listagem, download e
exclusão de arquivos ligados a um memorial.

O arquivo é guardado como base64 na própria coluna `dados` da tabela
`memorial_anexos` (não em disco/object storage) — mesma escolha do sistema
original (que guardava em Postgres) e consistente com o resto do
Alphafitus, que já guarda tudo num único arquivo `.db` (mais simples de
fazer backup e mover a instalação inteira sem depender de nenhum outro
caminho de disco). O limite de tamanho por arquivo é aplicado aqui na
camada de aplicação, não no banco.
"""
import base64
import binascii
import datetime
import io

import img2pdf
from flask import Blueprint, Response, g, jsonify, request
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .. import audit
from ..context import ApiError, client_device, client_ip, get_db
from ..pdf_marca import desenhar_cabecalho_logo
from ..permissions import requires_permission

bp = Blueprint("memorial_anexos", __name__, url_prefix="/api/v1/memorial")

# Mesmo limite do sistema original (documentos como laudos e
# especificações em PDF/Word podem ser grandes). Fase 49: esse limite
# virou configurável pela tela (`configuracoes_memorial.
# tamanho_maximo_anexo_mb`) — esta constante fica só como o valor padrão
# defensivo caso a linha de configuração não exista por algum motivo (a
# migration da Fase 49 já semeia a linha em todo banco novo ou
# atualizado).
MAX_ANEXO_BYTES_PADRAO = 40 * 1024 * 1024


def _tamanho_maximo_anexo_bytes(conn):
    row = conn.execute("SELECT tamanho_maximo_anexo_mb FROM configuracoes_memorial WHERE id = 1").fetchone()
    if row is None:
        return MAX_ANEXO_BYTES_PADRAO
    return row["tamanho_maximo_anexo_mb"] * 1024 * 1024


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _memorial_ou_404(conn, memorial_id):
    row = conn.execute("SELECT * FROM memoriais WHERE id = ?", (memorial_id,)).fetchone()
    if row is None:
        raise ApiError("Memorial não encontrado.", status=404)
    return row


def _anexo_metadados(row):
    d = dict(row)
    d.pop("dados", None)
    return d


def _anexo_ou_404(conn, memorial_id, anexo_id):
    row = conn.execute(
        "SELECT * FROM memorial_anexos WHERE id = ? AND memorial_id = ?", (anexo_id, memorial_id)
    ).fetchone()
    if row is None:
        raise ApiError("Anexo não encontrado.", status=404)
    return row


@bp.get("/memoriais/<int:memorial_id>/anexos")
@requires_permission("memoriais", "visualizar")
def listar_anexos(memorial_id):
    conn = get_db()
    _memorial_ou_404(conn, memorial_id)
    rows = conn.execute(
        "SELECT * FROM memorial_anexos WHERE memorial_id = ? ORDER BY criado_em", (memorial_id,)
    ).fetchall()
    return jsonify([_anexo_metadados(r) for r in rows])


@bp.post("/memoriais/<int:memorial_id>/anexos")
@requires_permission("memoriais", "editar")
def enviar_anexo(memorial_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _memorial_ou_404(conn, memorial_id)

    dados_entrada = request.get_json(silent=True) or {}
    nome_arquivo = (dados_entrada.get("nome_arquivo") or "").strip()
    if not nome_arquivo:
        raise ApiError("Informe nome_arquivo.", status=400)
    tipo_mime = (dados_entrada.get("tipo_mime") or "application/octet-stream").strip()
    conteudo_base64 = dados_entrada.get("dados") or ""
    if not conteudo_base64:
        raise ApiError("Informe o conteúdo do arquivo em base64 (campo 'dados').", status=400)
    # O front pode mandar um data URL inteiro ("data:<mime>;base64,AAAA...")
    # em vez de só o base64 — aceita os dois formatos.
    if "," in conteudo_base64 and conteudo_base64.strip().lower().startswith("data:"):
        conteudo_base64 = conteudo_base64.split(",", 1)[1]

    try:
        bruto = base64.b64decode(conteudo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("Conteúdo do arquivo não é um base64 válido.", status=400)

    if len(bruto) == 0:
        raise ApiError("O arquivo enviado está vazio.", status=400)
    limite_bytes = _tamanho_maximo_anexo_bytes(conn)
    if len(bruto) > limite_bytes:
        raise ApiError(
            f"Arquivo muito grande ({len(bruto) / (1024 * 1024):.1f} MB). "
            f"O limite por anexo é {limite_bytes // (1024 * 1024)} MB.",
            status=400,
        )

    nome = (dados_entrada.get("nome") or nome_arquivo).strip()

    cur = conn.execute(
        """
        INSERT INTO memorial_anexos
            (memorial_id, nome, nome_arquivo, tipo_mime, dados, tamanho, usuario_nome, criado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (memorial_id, nome, nome_arquivo, tipo_mime, conteudo_base64, len(bruto),
         usuario_atual["nome"], usuario_atual["id"]),
    )
    anexo_id = cur.lastrowid
    audit.registrar(
        conn, tabela="memorial_anexos", registro_id=anexo_id, usuario_id=usuario_atual["id"],
        acao="anexo_memorial_enviado",
        valor_novo={"memorial_id": memorial_id, "nome": nome, "nome_arquivo": nome_arquivo, "tamanho": len(bruto)},
        ip=client_ip(), dispositivo=client_device(),
    )
    novo = conn.execute("SELECT * FROM memorial_anexos WHERE id = ?", (anexo_id,)).fetchone()
    return jsonify(_anexo_metadados(novo)), 201


@bp.get("/memoriais/<int:memorial_id>/anexos/<int:anexo_id>/download")
@requires_permission("memoriais", "visualizar")
def baixar_anexo(memorial_id, anexo_id):
    conn = get_db()
    _memorial_ou_404(conn, memorial_id)
    anexo = _anexo_ou_404(conn, memorial_id, anexo_id)
    bruto = base64.b64decode(anexo["dados"])
    return Response(
        bruto,
        mimetype=anexo["tipo_mime"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{anexo["nome_arquivo"]}"'},
    )


@bp.delete("/memoriais/<int:memorial_id>/anexos/<int:anexo_id>")
@requires_permission("memoriais", "editar")
def excluir_anexo(memorial_id, anexo_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _memorial_ou_404(conn, memorial_id)
    anexo = _anexo_ou_404(conn, memorial_id, anexo_id)
    conn.execute("DELETE FROM memorial_anexos WHERE id = ?", (anexo_id,))
    audit.registrar(
        conn, tabela="memorial_anexos", registro_id=anexo_id, usuario_id=usuario_atual["id"],
        acao="anexo_memorial_excluido", valor_anterior=_anexo_metadados(anexo),
        ip=client_ip(), dispositivo=client_device(),
    )
    return "", 204


# ============================================================
# Fase 43 — Exportar "PDF Completo" (memorial + anexos combinados)
# ============================================================
# O sistema original tinha uma opção que baixava cada anexo, convertia
# PDF/Word para imagem/HTML e injetava tudo antes de mandar imprimir,
# gerando um único PDF com o memorial e todos os anexos juntos. A Fase 27
# entregou só a opção mais simples (imprimir o memorial em si via
# `window.print()`, mais os anexos disponíveis para baixar separadamente)
# e documentou o "PDF Completo" combinado como pendente — ver "O que
# ainda falta" no README. Esta fase entrega isso, com um limite honesto e
# deliberado: incorpora de verdade os anexos que são PDF (mescla as
# páginas) ou imagem (vira uma página nova, via `img2pdf`); um anexo de
# outro tipo (Word, Excel, texto puro, etc.) NUNCA trava a exportação —
# ele só não entra fisicamente no PDF final, e aparece listado numa
# página de apêndice ("Anexos não incorporados") explicando o motivo,
# continuando disponível para baixar separadamente como sempre. A
# alternativa (converter Word/Excel para PDF de verdade) exigiria um
# conversor de documentos de verdade (ex.: LibreOffice em modo headless)
# como dependência do sistema instalado na máquina do cliente — um passo
# a mais bem pesado (não é só `pip install`) que decidimos não exigir só
# por causa deste recurso; ver o próprio bullet desta fase no README.
#
# Os rótulos e o agrupamento por aba abaixo espelham `ABAS_MEMORIAL` em
# `frontend/static/app.js` (Fase 27) de propósito, para o PDF sair
# organizado do mesmo jeito que a tela de edição — se um campo for
# adicionado/renomeado num dos dois lugares, atualize o outro também
# (mesmo cuidado de sincronização documentado noutros pontos do sistema,
# ex. `_ROTULOS_TIPO_ITEM` em `relatorios.py`).
SECOES_MEMORIAL_PDF = (
    ("0. Identificação", (
        ("numero_certificado", "Número do Certificado"),
        ("data_emissao", "Data de Emissão"),
        ("tipo_produto", "Tipo de Produto"),
        ("tipo_pote", "Tipo de Pote"),
        ("ingredientes_ativos", "Ingredientes Ativos"),
        ("excipientes", "Excipientes"),
        ("composicao_capsula", "Composição da Cápsula"),
        ("advertencias", "Advertências"),
        ("armazenamento", "Armazenamento"),
        ("modo_uso", "Modo de Uso"),
        ("temperatura", "Temperatura do Estudo"),
        ("umidade_relativa", "Umidade Relativa do Estudo"),
        ("periodo_estudo", "Período do Estudo"),
        ("intervalos_teste", "Intervalos de Teste"),
        ("elaborado_por", "Elaborado por"),
        ("aprovado_por", "Aprovado por"),
        ("laudo_emitido_por", "Laudo emitido por"),
        ("analista_senior", "Analista Sênior"),
        ("email_rt", "Email do Responsável Técnico"),
        ("email_analista_senior", "Email do Analista Sênior"),
        ("observacao_analista", "Observação do Analista"),
    )),
    ("1. Objetivo", (("objetivo", "Objetivo"),)),
    ("2. Composição Nutricional", (
        ("composicao_nutricional", "Composição Nutricional"),
        ("lista_ingredientes", "Lista de Ingredientes"),
    )),
    ("3. Formulação", (
        ("composicao_centesimal", "Composição Centesimal"),
        ("calculo_quantidade", "Cálculo de Quantidade"),
    )),
    ("4. Metodologias", (("metodologias_aplicadas", "Metodologias Aplicadas"),)),
    ("5. Cálculos", (("calculos_nutricionais", "Cálculos Nutricionais"),)),
    ("6. Alegações", (("alegacoes", "Alegações"),)),
    ("7. Estudos", (
        ("metodos_analiticos", "Métodos Analíticos"),
        ("estabilidade_acelerada", "Estabilidade Acelerada"),
        ("ensaios_microbiologicos", "Ensaios Microbiológicos"),
        ("justificativas_tecnicas", "Justificativas Técnicas"),
        ("conclusao", "Conclusão Técnica"),
    )),
    ("8. Legislação", (
        ("legislacao_aplicavel", "Legislação Aplicável"),
        ("observacoes", "Observações"),
    )),
    ("9. Referências", (("referencias_bibliograficas", "Referências Bibliográficas"),)),
)

TIPOS_IMAGEM_SUPORTADOS = ("image/jpeg", "image/jpg", "image/png", "image/gif", "image/bmp", "image/tiff", "image/webp")


def _memorial_completo_para_pdf(conn, memorial_id):
    row = conn.execute(
        """
        SELECT m.*, p.nome AS produto_nome, e.nome_fantasia AS empresa_nome
        FROM memoriais m
        JOIN memorial_produtos p ON p.id = m.produto_id
        JOIN memorial_empresas e ON e.id = p.empresa_id
        WHERE m.id = ?
        """,
        (memorial_id,),
    ).fetchone()
    return dict(row) if row else None


def _texto_xml_seguro(valor):
    """Escapa o texto livre de um campo do memorial para o mini-XML que o
    `Paragraph` do reportlab espera, e troca quebra de linha por `<br/>`
    (senão o parágrafo inteiro vira uma linha só, ilegível)."""
    if not valor:
        return "—"
    texto = str(valor).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return texto.replace("\n", "<br/>")


def _gerar_pdf_conteudo_memorial(memorial):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("TituloMemorial", parent=estilos["Title"], fontSize=15, alignment=TA_CENTER, spaceAfter=2)
    estilo_subtitulo = ParagraphStyle(
        "SubtituloMemorial", parent=estilos["Normal"], fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor("#5a6472"), spaceAfter=16,
    )
    estilo_secao = ParagraphStyle(
        "SecaoMemorial", parent=estilos["Heading2"], fontSize=12, spaceBefore=14, spaceAfter=6,
        textColor=colors.HexColor("#1f3a5f"),
    )
    estilo_rotulo_campo = ParagraphStyle("RotuloCampoMemorial", parent=estilos["Normal"], fontSize=9.5, spaceBefore=8, spaceAfter=2, textColor=colors.HexColor("#5a6472"))
    estilo_valor_campo = ParagraphStyle("ValorCampoMemorial", parent=estilos["Normal"], fontSize=10.5, spaceAfter=2, leading=14)

    elementos = [
        Paragraph(_texto_xml_seguro(memorial["empresa_nome"]), estilo_titulo),
        Paragraph(
            f"Memorial Técnico ANVISA — {_texto_xml_seguro(memorial['produto_nome'])} "
            f"({_texto_xml_seguro(memorial['codigo'])}) — Certificado {_texto_xml_seguro(memorial['numero_certificado'])}",
            estilo_subtitulo,
        ),
    ]

    for titulo_secao, campos in SECOES_MEMORIAL_PDF:
        secao_tem_conteudo = any(memorial.get(campo) for campo, _rotulo in campos)
        if not secao_tem_conteudo:
            continue
        elementos.append(Paragraph(titulo_secao, estilo_secao))
        for campo, rotulo in campos:
            valor = memorial.get(campo)
            if not valor:
                continue
            elementos.append(Paragraph(rotulo, estilo_rotulo_campo))
            elementos.append(Paragraph(_texto_xml_seguro(valor), estilo_valor_campo))

    doc.build(elementos, onFirstPage=desenhar_cabecalho_logo, onLaterPages=desenhar_cabecalho_logo)
    return buffer.getvalue()


def _gerar_pdf_pagina_separadora(titulo, subtitulo):
    """Uma página simples só com um título — usada para marcar onde cada
    anexo incorporado começa dentro do PDF combinado, e para o apêndice
    final de anexos não incorporados."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=4 * cm)
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("TituloSeparador", parent=estilos["Title"], fontSize=16, alignment=TA_CENTER)
    estilo_subtitulo = ParagraphStyle("SubtituloSeparador", parent=estilos["Normal"], fontSize=10, alignment=TA_CENTER, textColor=colors.HexColor("#5a6472"), spaceBefore=8)
    elementos = [Paragraph(_texto_xml_seguro(titulo), estilo_titulo)]
    if subtitulo:
        elementos.append(Spacer(1, 0.3 * cm))
        elementos.append(Paragraph(subtitulo, estilo_subtitulo))
    doc.build(elementos, onFirstPage=desenhar_cabecalho_logo, onLaterPages=desenhar_cabecalho_logo)
    return buffer.getvalue()


def _anexo_para_paginas_pdf(anexo, bruto):
    """Tenta converter os bytes de um anexo em páginas de PDF prontas
    para incorporar. Devolve (lista_de_paginas_bytes_pdf, None) quando
    consegue, ou (None, motivo) quando o tipo não é suportado ou o
    arquivo está corrompido — NUNCA levanta exceção, porque um anexo
    problemático não pode derrubar a exportação inteira."""
    tipo = (anexo["tipo_mime"] or "").lower()
    nome = anexo["nome_arquivo"] or ""
    if tipo == "application/pdf" or nome.lower().endswith(".pdf"):
        try:
            leitor = PdfReader(io.BytesIO(bruto))
            if leitor.is_encrypted:
                return None, "PDF protegido por senha — não é possível incorporar automaticamente."
            return [bruto], None
        except (PdfReadError, ValueError, OSError):
            return None, "arquivo PDF corrompido ou inválido."
    if tipo in TIPOS_IMAGEM_SUPORTADOS or nome.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp")):
        try:
            pdf_da_imagem = img2pdf.convert(bruto)
            return [pdf_da_imagem], None
        except Exception:
            return None, "não foi possível converter a imagem para PDF (arquivo de imagem corrompido ou inválido)."
    return None, (
        f"tipo '{tipo or 'desconhecido'}' não é PDF nem imagem — incorporação automática exigiria um "
        "conversor de documentos (ex.: Word/Excel), fora do escopo desta entrega (ver README)."
    )


def _gerar_pdf_completo(conn, memorial_id):
    memorial = _memorial_completo_para_pdf(conn, memorial_id)
    if memorial is None:
        raise ApiError("Memorial não encontrado.", status=404)

    anexos = conn.execute(
        "SELECT * FROM memorial_anexos WHERE memorial_id = ? ORDER BY criado_em", (memorial_id,)
    ).fetchall()

    escritor = PdfWriter()

    def _anexar_bytes_pdf(pdf_bytes):
        leitor = PdfReader(io.BytesIO(pdf_bytes))
        for pagina in leitor.pages:
            escritor.add_page(pagina)

    _anexar_bytes_pdf(_gerar_pdf_conteudo_memorial(memorial))

    nao_incorporados = []
    for anexo in anexos:
        bruto = base64.b64decode(anexo["dados"])
        paginas, motivo = _anexo_para_paginas_pdf(anexo, bruto)
        if paginas is None:
            nao_incorporados.append({"nome": anexo["nome"] or anexo["nome_arquivo"], "motivo": motivo})
            continue
        _anexar_bytes_pdf(_gerar_pdf_pagina_separadora(
            f"Anexo: {anexo['nome'] or anexo['nome_arquivo']}",
            f"Enviado por {anexo['usuario_nome'] or '—'} em {anexo['criado_em']}",
        ))
        for pagina_bytes in paginas:
            _anexar_bytes_pdf(pagina_bytes)

    if nao_incorporados:
        linhas = "<br/>".join(
            f"• {_texto_xml_seguro(item['nome'])} — {item['motivo']}" for item in nao_incorporados
        )
        _anexar_bytes_pdf(_gerar_pdf_pagina_separadora(
            "Anexos não incorporados neste PDF",
            f"Continuam disponíveis para baixar separadamente pela tela de Anexos.<br/><br/>{linhas}",
        ))

    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


@bp.get("/memoriais/<int:memorial_id>/pdf-completo")
@requires_permission("memoriais", "visualizar")
def baixar_pdf_completo(memorial_id):
    """Fase 43 — mesma permissão de sempre (`memoriais.visualizar`,
    nenhuma nova) para exportar; export puro, não altera nenhum dado de
    negócio."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _memorial_ou_404(conn, memorial_id)
    pdf_bytes = _gerar_pdf_completo(conn, memorial_id)

    audit.registrar(
        conn, tabela="memoriais", registro_id=memorial_id, usuario_id=usuario_atual["id"],
        acao="memorial_pdf_completo_gerado", valor_novo={"memorial_id": memorial_id},
        ip=client_ip(), dispositivo=client_device(),
    )

    nome_arquivo = f"Memorial-Tecnico-Completo-{memorial_id}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
