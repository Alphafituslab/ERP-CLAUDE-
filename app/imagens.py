"""Validação de imagens enviadas como data URI (base64) — extraído da Fase 113
(foto de perfil) quando a Fase 114 (foto de item/portfólio) precisou da MESMA
regra pela segunda vez. Guarda o data URI completo (não só o base64 puro) para
cada consumidor poder jogar direto num <img src="...">, sem reconstruir o
prefixo "data:<mime>;base64," na hora de exibir.
"""
import base64
import binascii
import re

from .context import ApiError

TIPOS_MIME_PADRAO = ("image/jpeg", "image/png", "image/webp")
TAMANHO_MAXIMO_PADRAO_BYTES = 2 * 1024 * 1024

# Fase 153 — galeria de mídia dos itens: mesma ideia da foto única acima,
# só que pra vídeo curto (pedido do usuário: "um pequeno vídeo poder
# incluir se for necessário") — limite bem maior porque vídeo, mesmo
# curto, pesa muito mais que uma foto.
TIPOS_MIME_VIDEO_PADRAO = ("video/mp4", "video/webm", "video/quicktime")
TAMANHO_MAXIMO_VIDEO_BYTES = 20 * 1024 * 1024


def _decodificar_data_uri(data_uri, tipos_permitidos, tamanho_maximo_bytes, rotulo_erro):
    m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", data_uri, re.DOTALL)
    if not m:
        raise ApiError(f"{rotulo_erro} inválido(a) — envie um arquivo válido.", status=400)
    tipo_mime, conteudo_base64 = m.group(1).lower(), m.group(2)
    if tipo_mime not in tipos_permitidos:
        raise ApiError(
            f"Tipo '{tipo_mime}' não permitido para {rotulo_erro.lower()}. "
            f"Tipos aceitos: {', '.join(tipos_permitidos)}.", status=400,
        )
    try:
        bruto = base64.b64decode(conteudo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(f"{rotulo_erro} inválido(a) — não foi possível ler o arquivo.", status=400)
    if len(bruto) == 0:
        raise ApiError(f"{rotulo_erro} enviado(a) está vazio(a).", status=400)
    if len(bruto) > tamanho_maximo_bytes:
        raise ApiError(
            f"{rotulo_erro} muito grande ({len(bruto) / (1024 * 1024):.1f} MB). "
            f"O limite é {tamanho_maximo_bytes // (1024 * 1024)} MB.",
            status=400,
        )
    return tipo_mime, len(bruto)


def validar_imagem_base64(data_uri, tipos_permitidos=TIPOS_MIME_PADRAO, tamanho_maximo_bytes=TAMANHO_MAXIMO_PADRAO_BYTES):
    """Recebe o data URI completo e devolve ele mesmo, já validado — ou
    levanta ApiError. `None`/string vazia é válido (significa "remover a
    imagem")."""
    if not data_uri:
        return None
    _decodificar_data_uri(data_uri, tipos_permitidos, tamanho_maximo_bytes, "Imagem")
    return data_uri


def validar_midia_galeria_item_base64(data_uri, tipo):
    """Fase 153 — ponto de entrada único usado por `itens.py` pra validar
    uma linha nova de `itens_midias`: despacha pra imagem ou vídeo
    conforme `tipo` e sempre devolve (tipo_mime, tamanho_bytes), as duas
    colunas que a tabela guarda separadas do `conteudo` em si."""
    if tipo == "foto":
        return _decodificar_data_uri(data_uri, TIPOS_MIME_PADRAO, TAMANHO_MAXIMO_PADRAO_BYTES, "Imagem")
    if tipo == "video":
        return _decodificar_data_uri(data_uri, TIPOS_MIME_VIDEO_PADRAO, TAMANHO_MAXIMO_VIDEO_BYTES, "Vídeo")
    raise ApiError("tipo deve ser 'foto' ou 'video'.", status=400)
