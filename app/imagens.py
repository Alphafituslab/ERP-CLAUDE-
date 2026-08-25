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


def validar_imagem_base64(data_uri, tipos_permitidos=TIPOS_MIME_PADRAO, tamanho_maximo_bytes=TAMANHO_MAXIMO_PADRAO_BYTES):
    """Recebe o data URI completo e devolve ele mesmo, já validado — ou
    levanta ApiError. `None`/string vazia é válido (significa "remover a
    imagem")."""
    if not data_uri:
        return None
    m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", data_uri, re.DOTALL)
    if not m:
        raise ApiError("Imagem inválida — envie um arquivo de imagem.", status=400)
    tipo_mime, conteudo_base64 = m.group(1).lower(), m.group(2)
    if tipo_mime not in tipos_permitidos:
        raise ApiError(
            f"Tipo de imagem '{tipo_mime}' não permitido. Use JPEG, PNG ou WEBP.", status=400,
        )
    try:
        bruto = base64.b64decode(conteudo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("Imagem inválida — não foi possível ler o arquivo.", status=400)
    if len(bruto) == 0:
        raise ApiError("A imagem enviada está vazia.", status=400)
    if len(bruto) > tamanho_maximo_bytes:
        raise ApiError(
            f"Imagem muito grande ({len(bruto) / (1024 * 1024):.1f} MB). "
            f"O limite é {tamanho_maximo_bytes // (1024 * 1024)} MB.",
            status=400,
        )
    return data_uri
