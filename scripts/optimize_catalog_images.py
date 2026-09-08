"""Build responsive WebP siblings for bundled catalog images; keep originals."""
from pathlib import Path

from PIL import Image, ImageOps


def main():
    catalog = Path(__file__).resolve().parents[1] / 'static' / 'img' / 'produtos'
    before = after = count = 0
    for source in sorted(catalog.glob('*.png')):
        with Image.open(source) as original:
            original = ImageOps.exif_transpose(original).convert('RGBA')
            for width in (480, 960):
                target = source.with_name(f'{source.stem}-{width}.webp')
                if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
                    scaled = original.copy()
                    scaled.thumbnail((width, width), Image.Resampling.LANCZOS)
                    scaled.save(target, 'WEBP', quality=84, method=6)
                if width == 960:
                    before += source.stat().st_size
                    after += target.stat().st_size
            count += 1
    print(f'{count} images; original={before} bytes; desktop_webp={after} bytes; saved={before-after} bytes')


if __name__ == '__main__':
    main()
