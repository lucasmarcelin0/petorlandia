"""Prepare bounded raster previews of the supplied operational maps.

Build dependencies: Pillow, pypdfium2. Sources are never extracted by ZIP paths.
"""
import argparse
import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageOps


def build(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(source) as archive:
        names = sorted(n for n in archive.namelist() if Path(n).suffix.lower() in {'.pdf', '.jpg', '.jpeg', '.png'})
        for i, name in enumerate(names):
            blob = archive.read(name)
            if name.lower().endswith('.pdf'):
                import pypdfium2
                document = pypdfium2.PdfDocument(blob)
                bitmap = document[0].render(scale=1).to_pil().convert('RGB')
            else:
                with Image.open(io.BytesIO(blob)) as original:
                    bitmap = ImageOps.exif_transpose(original).convert('RGB')
            bitmap.thumbnail((3600, 3600))
            filename = f'mapa-{i+1:02d}.jpg'
            bitmap.save(destination / filename, quality=88, optimize=True)
            manifest.append({'file': filename, 'title': Path(name).stem, 'width': bitmap.width, 'height': bitmap.height})
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(manifest)} maps prepared in {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'services/data/entomologia/maps')
    args = parser.parse_args()
    build(args.source, args.output)
