"""
Cabeçalho com a logo da Alphafitus para os PDFs gerados pelo sistema
(Certificado de Análise, Relatório de Simulação de Recall, Painel
Gerencial, Memorial Técnico/"PDF Completo").

Um único ponto de verdade para isso, em vez de cada rota desenhar a logo
do jeito dela: se a logo mudar de arquivo/posição um dia, só este módulo
precisa mudar. Usa o mecanismo `onFirstPage`/`onLaterPages` do
`SimpleDocTemplate.build()` (reportlab) — desenha diretamente no canvas
de CADA página, dentro da margem superior já reservada por cada
documento (não empurra o conteúdo normal, que continua vindo 100% dos
`elementos`/flowables de cada rota).
"""
import os

LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "static", "img", "logo_alphafitus.png",
)

# Proporção real do arquivo logo_alphafitus.png (largura/altura) — usada
# para nunca desenhar a logo esticada/achatada.
_PROPORCAO_LOGO = 500 / 419

# Altura reservada para a logo dentro da margem superior de cada PDF.
# Todos os documentos que usam este cabeçalho têm `topMargin >= 1.8cm`
# (ver lotes.py, rastreabilidade.py, relatorios.py, memorial_anexos.py),
# então 1.1cm de logo + margem de respiro acima/abaixo cabe com folga
# sem encostar no título do documento, que começa exatamente em
# `topMargin` a partir do topo da página.
_ALTURA_LOGO_CM = 1.1


def desenhar_cabecalho_logo(canvas_obj, doc):
    """Callback para `SimpleDocTemplate.build(elementos, onFirstPage=...,
    onLaterPages=...)`. Desenha a logo no canto superior esquerdo de
    CADA página do documento — silenciosamente não desenha nada se o
    arquivo da logo não existir (nunca deve quebrar a geração de um PDF
    por causa disso)."""
    if not os.path.isfile(LOGO_PATH):
        return
    from reportlab.lib.units import cm

    altura = _ALTURA_LOGO_CM * cm
    largura = altura * _PROPORCAO_LOGO
    x = doc.leftMargin
    # Centraliza verticalmente a logo dentro da faixa de margem superior
    # (do topo físico da página até onde o conteúdo normal começa, em
    # `doc.topMargin`) — nunca invade a área de conteúdo abaixo dela.
    y = doc.pagesize[1] - (doc.topMargin / 2) - (altura / 2)
    canvas_obj.saveState()
    try:
        canvas_obj.drawImage(
            LOGO_PATH, x, y, width=largura, height=altura,
            preserveAspectRatio=True, mask="auto",
        )
    except Exception:
        # Mesma postura defensiva: um problema ao desenhar a logo (ex.:
        # arquivo de imagem corrompido) nunca deve impedir a emissão do
        # documento em si, que é o que realmente importa para quem pediu
        # o PDF (CoA, recall, etc.).
        pass
    canvas_obj.restoreState()


# =============================================================================
# Fase 147 — cabeçalho FORMAL (logo + razão social/CNPJ/IE/endereço/
# telefone/e-mail + linha divisória), pro Gerador de Contratos. Mais
# completo que `desenhar_cabecalho_logo` (usado pelos outros PDFs do
# sistema — CoA, recall, Memorial, Dossiê — que só precisam da logo
# pequena); um CONTRATO precisa se identificar por completo em qualquer
# página, é praxe jurídica. Dados vêm do papel timbrado real que o
# usuário mostrou (2026-09-03) — NUNCA inventados.
#
# Divergência real encontrada entre o timbre (print do usuário) e o
# corpo do modelo de contrato enviado ("Rua Agenor Martinho Lima, nº 41,
# Bairro Nossa Senhora De Fatima" vs. "Rua Cel. Marcos Rovaris, 1574,
# Primeiro de Maio" — mesmo CNPJ nos dois) — usuário confirmado em
# 2026-09-03: o endereço correto/atual é o da Rua Agenor Martinho Lima.
# Usado aqui no timbre E no corpo do contrato (contrato_modelo.py).
DADOS_EMPRESA_CONTRATO = {
    "razao_social": "Alphafitus Laboratório Nutracêutico Ltda.",
    "cnpj": "01.481.057/0001-12",
    "ie": "253385210",
    "endereco": "Rua Agenor Martinho Lima, nº 41, Bairro Nossa Senhora de Fátima, Içara/SC CEP: 88823-290",
    "telefone": "(48) 3420-1881",
    "email": "alphafitus@alphafitus.com.br",
}


def desenhar_cabecalho_formal(canvas_obj, doc):
    """Callback `onFirstPage`/`onLaterPages` — logo à esquerda, bloco de
    identificação da empresa à direita, linha dourada dividindo do
    conteúdo abaixo. Layout inspirado no papel timbrado real da
    Alphafitus (print enviado pelo usuário)."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    canvas_obj.saveState()
    try:
        altura_logo = 1.6 * cm
        largura_logo = altura_logo * _PROPORCAO_LOGO
        x_logo = doc.leftMargin
        # Âncora no TOPO FÍSICO da página (não em `doc.topMargin`) — o
        # cabeçalho inteiro (logo + 4 linhas de texto + linha dourada,
        # ~2.3cm de altura) precisa caber DENTRO da margem superior que
        # cada documento reserva; documentos que usam este cabeçalho
        # devem ter `topMargin >= 3cm` (ver contratos.py) senão o título
        # do conteúdo normal, que começa exatamente em `topMargin` a
        # partir do topo, invade o cabeçalho.
        y_topo = doc.pagesize[1] - 0.5 * cm
        y_logo = y_topo - altura_logo
        if os.path.isfile(LOGO_PATH):
            canvas_obj.drawImage(
                LOGO_PATH, x_logo, y_logo, width=largura_logo, height=altura_logo,
                preserveAspectRatio=True, mask="auto",
            )

        x_texto_direita = doc.pagesize[0] - doc.rightMargin
        d = DADOS_EMPRESA_CONTRATO
        linhas = [
            (d["razao_social"], "Helvetica-Bold", 9.5, colors.HexColor("#1a3c2e")),
            (f"CNPJ: {d['cnpj']}    IE: {d['ie']}", "Helvetica", 8, colors.HexColor("#444444")),
            (d["endereco"], "Helvetica", 8, colors.HexColor("#444444")),
            (f"Telefone: {d['telefone']}    e-mail: {d['email']}", "Helvetica", 8, colors.HexColor("#444444")),
        ]
        y = y_topo - 0.35 * cm
        for texto, fonte, tamanho, cor in linhas:
            canvas_obj.setFont(fonte, tamanho)
            canvas_obj.setFillColor(cor)
            canvas_obj.drawRightString(x_texto_direita, y, texto)
            y -= 0.38 * cm

        canvas_obj.setStrokeColor(colors.HexColor("#a8863f"))
        canvas_obj.setLineWidth(1)
        y_linha = y_logo - 0.25 * cm
        canvas_obj.line(doc.leftMargin, y_linha, doc.pagesize[0] - doc.rightMargin, y_linha)
    except Exception:
        # Mesma postura defensiva do resto deste módulo — um problema no
        # cabeçalho nunca pode impedir a emissão do contrato em si.
        pass
    canvas_obj.restoreState()
