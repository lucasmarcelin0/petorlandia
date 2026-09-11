# -*- coding: utf-8 -*-
"""Normaliza a foto que chega do campo antes de guardar.

O aparelho manda o que o sistema dele produz: iPhone no modo "Alta eficiencia"
entrega HEIC, e a conversao feita no navegador falha em silencio sempre que o
browser nao sabe decodificar o formato (o `catch` do dashboard devolve o
arquivo original). Antes desta camada o servidor respondia 415, a fila local
tentava reenviar o mesmo arquivo para sempre e o vacinador so via o selo
vermelho, sem motivo nenhum na tela.

A regra aqui e uma so: se da para ler a imagem, ela entra. O que nao for JPEG,
PNG ou WebP e convertido para JPEG, porque a foto ainda vai ser exibida na
carteirinha do tutor e no painel -- e nenhum navegador exibe HEIC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Formatos que o navegador exibe direto: passam sem reencodar (sem perda de
# qualidade e sem gastar CPU do dyno com o caso comum).
DIRECT_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}

# Lado maior da foto convertida. Igual ao limite que o dashboard usa quando
# consegue converter no proprio aparelho, para a foto nao mudar de tamanho
# dependendo de quem fez a conversao.
CONVERSION_MAX_SIDE = 1600
CONVERSION_QUALITY = 86

# Acima disto, mesmo um JPEG valido e reencodado. A foto do animal e exibida
# num quadrado de 40 px na lista, num modal de ~400 px e na carteirinha: um
# arquivo de 12 MP so custa dado movel do vacinador na subida, espaco no S3 e
# tempo de carregamento de quem abre a lista depois. O cliente ja reduz quando
# consegue; isto cobre quem nao conseguiu (navegador antigo, HEIC no Android).
RECOMPRESS_ABOVE_BYTES = 1_200_000

_heif_registered: bool | None = None


class PhotoIntakeError(ValueError):
    """Erro de foto com mensagem pronta para o vacinador ler na tela."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message


class InvalidPhoto(PhotoIntakeError):
    status_code = 400


class UnsupportedPhotoFormat(PhotoIntakeError):
    status_code = 415


@dataclass
class NormalizedPhoto:
    """Foto pronta para subir: stream no inicio, tipo e extensao coerentes."""

    stream: BytesIO
    content_type: str
    extension: str
    source_format: str
    converted: bool


class _UploadStream(BytesIO):
    """BytesIO com ``content_type`` -- e o que ``upload_to_s3`` le do arquivo.

    Sem isso o objeto do S3 herdaria o ``Content-Type`` que o navegador
    declarou (as vezes ``image/heic`` para um JPEG ja convertido), e o
    ``<img>`` do tutor receberia um tipo que ele nao sabe exibir.
    """

    def __init__(self, data: bytes, content_type: str):
        super().__init__(data)
        self.content_type = content_type


def ensure_heif_support() -> bool:
    """Registra o decodificador HEIF/HEIC no Pillow. Idempotente.

    Retorna ``False`` quando ``pillow-heif`` nao esta instalado -- ambiente de
    desenvolvimento sem a dependencia continua funcionando para os demais
    formatos em vez de quebrar o import do modulo.
    """
    global _heif_registered
    if _heif_registered is not None:
        return _heif_registered
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        _heif_registered = True
    except Exception:  # pragma: no cover - depende do ambiente
        logger.warning("pillow-heif indisponivel: fotos HEIC serao recusadas")
        _heif_registered = False
    return _heif_registered


def _achatar_para_rgb(image: Image.Image) -> Image.Image:
    """Converte para RGB preservando o que estava transparente como branco.

    Um `convert("RGB")` direto num PNG com alfa pinta o transparente de preto.
    """
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        fundo = Image.new("RGB", image.size, (255, 255, 255))
        com_alfa = image.convert("RGBA")
        fundo.paste(com_alfa, mask=com_alfa.split()[-1])
        return fundo
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _precisa_reduzir(data: bytes, source_format: str) -> bool:
    """A foto ja esta no tamanho que o site usa, ou vale reencodar?"""
    if len(data) > RECOMPRESS_ABOVE_BYTES:
        return True
    try:
        with Image.open(BytesIO(data)) as image:
            maior_lado = max(image.size)
    except Exception:
        return False
    return maior_lado > CONVERSION_MAX_SIDE


def _swap_extension(filename: str, extension: str) -> str:
    """Troca a extensao do arquivo pela do formato que sera realmente gravado."""
    base = (filename or "foto").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return f"{base or 'foto'}{extension}"


def normalize_photo_upload(data: bytes) -> NormalizedPhoto:
    """Valida a foto e devolve um stream que o navegador consegue exibir.

    Levanta ``InvalidPhoto`` quando o arquivo nao e imagem e
    ``UnsupportedPhotoFormat`` quando e imagem de um formato que este servidor
    nao consegue decodificar (tipicamente HEIC sem ``pillow-heif`` instalado).
    """
    ensure_heif_support()

    if not data:
        raise InvalidPhoto("A foto enviada está vazia.")

    try:
        with Image.open(BytesIO(data)) as probe:
            probe.verify()
            source_format = (probe.format or "").upper()
    except Exception:
        raise InvalidPhoto("O arquivo selecionado não é uma foto válida.")

    if source_format in DIRECT_FORMATS and not _precisa_reduzir(data, source_format):
        content_type, extension = DIRECT_FORMATS[source_format]
        return NormalizedPhoto(
            stream=_UploadStream(data, content_type),
            content_type=content_type,
            extension=extension,
            source_format=source_format,
            converted=False,
        )

    try:
        with Image.open(BytesIO(data)) as image:
            # `exif_transpose` antes de qualquer coisa: a foto do celular vem
            # com a rotacao so na EXIF, e o JPEG convertido perde esse dado.
            image = ImageOps.exif_transpose(image)
            image = _achatar_para_rgb(image)
            image.thumbnail((CONVERSION_MAX_SIDE, CONVERSION_MAX_SIDE))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=CONVERSION_QUALITY, optimize=True)
    except Exception:
        if source_format in DIRECT_FORMATS:
            # Reduzir e otimizacao, nao requisito: se falhar, a foto original
            # (que o navegador ja sabe exibir) continua valendo.
            content_type, extension = DIRECT_FORMATS[source_format]
            logger.warning("Falha ao reduzir foto %s; guardando original", source_format)
            return NormalizedPhoto(
                stream=_UploadStream(data, content_type),
                content_type=content_type,
                extension=extension,
                source_format=source_format,
                converted=False,
            )
        raise UnsupportedPhotoFormat(
            "Não conseguimos converter esta foto. Tire a foto de novo pela "
            "câmera do app ou use uma imagem JPG, PNG ou WebP."
        )

    # Reencodar nem sempre compensa (foto ja enxuta, PNG de traco): fica com o
    # menor dos dois, para nunca devolver ao S3 algo maior do que chegou.
    if source_format in DIRECT_FORMATS and buffer.tell() >= len(data):
        content_type, extension = DIRECT_FORMATS[source_format]
        return NormalizedPhoto(
            stream=_UploadStream(data, content_type),
            content_type=content_type,
            extension=extension,
            source_format=source_format,
            converted=False,
        )

    return NormalizedPhoto(
        stream=_UploadStream(buffer.getvalue(), "image/jpeg"),
        content_type="image/jpeg",
        extension=".jpg",
        source_format=source_format or "DESCONHECIDO",
        converted=True,
    )


def normalized_filename(original_name: str, photo: NormalizedPhoto) -> str:
    """Nome do arquivo com a extensao do formato realmente gravado."""
    return _swap_extension(original_name, photo.extension)
