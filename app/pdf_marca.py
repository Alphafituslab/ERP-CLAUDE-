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
