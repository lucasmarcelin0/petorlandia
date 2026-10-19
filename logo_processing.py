"""Normalize admin logos without changing photos or product uploads."""
from io import BytesIO
import warnings

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError


MAX_LOGO_PIXELS = 25_000_000
MAX_LOGO_SIDE = 1600


def prepare_logo(stream, clean_background=False):
    """Return an opaque PNG; optionally whiten neutral areas touching an edge.

    Cleaning is opt-in because a gray background can be part of a brand.
    Colored pixels and enclosed regions are never selected by the cleanup.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(stream) as source:
                if source.width * source.height > MAX_LOGO_PIXELS:
                    raise ValueError('O logotipo deve ter no máximo 25 megapixels.')
                image = ImageOps.exif_transpose(source).convert('RGBA')
        image.thumbnail((MAX_LOGO_SIDE, MAX_LOGO_SIDE), Image.Resampling.LANCZOS)
        white = Image.new('RGBA', image.size, 'white')
        white.alpha_composite(image)
        image = white.convert('RGB')
        if clean_background:
            # Work on a binary mask, so the flood cannot cross dark outlines
            # or erase white details enclosed inside the logo.
            mask = Image.new('L', image.size)
            mask.putdata([
                255 if min(pixel) >= 150 and max(pixel) - min(pixel) <= 18 else 0
                for pixel in image.getdata()
            ])
            width, height = image.size
            edges = ([(x, 0) for x in range(width)]
                     + [(x, height - 1) for x in range(width)]
                     + [(0, y) for y in range(height)]
                     + [(width - 1, y) for y in range(height)])
            for point in edges:
                if mask.getpixel(point) == 255:
                    ImageDraw.floodfill(mask, point, 128)
            selected = mask.point(lambda value: 255 if value == 128 else 0)
            image.paste('white', mask=selected)
        result = BytesIO()
        image.save(result, format='PNG')
        result.seek(0)
        return result
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError('Não foi possível ler o logotipo. Envie uma imagem válida.') from exc
