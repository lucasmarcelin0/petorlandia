"""Gera a imagem de compartilhamento (Open Graph) usada nas prévias de link.

A imagem é um asset estático versionado: rode este script só quando o texto ou
a marca mudarem, e faça commit do PNG resultante.

    python scripts/gen_og_image.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / 'static' / 'logo_pet.png'
OUTPUT = ROOT / 'static' / 'img' / 'og-petorlandia.png'

WIDTH, HEIGHT = 1200, 630

INK = (14, 26, 45)
INK_SOFT = (128, 146, 178)
WHITE = (255, 255, 255)
BRAND = (78, 115, 223)
ACCENT = (94, 214, 187)

TITLE = 'Sua clínica veterinária\ninteira em um lugar só'
FEATURES = 'Agenda  ·  Prontuário  ·  Vacinas  ·  Financeiro'
BADGE = '30 dias grátis — sem cartão'

FONT_CANDIDATES = {
    'bold': ['C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf',
             '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
    'regular': ['C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/arial.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
}


def load_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(
        f'Nenhuma fonte {kind} encontrada. Edite FONT_CANDIDATES em {__file__}.'
    )


def main() -> int:
    img = Image.new('RGB', (WIDTH, HEIGHT), INK)
    draw = ImageDraw.Draw(img)

    # Faixa diagonal suave no canto direito, para a arte não ficar chapada.
    draw.polygon([(WIDTH, 0), (WIDTH, HEIGHT), (WIDTH - 380, HEIGHT)], fill=(20, 36, 62))

    # Barra de acento na borda esquerda.
    draw.rectangle([0, 0, 12, HEIGHT], fill=BRAND)

    margin_x = 78
    title_font = load_font('bold', 64)
    feature_font = load_font('regular', 30)
    badge_font = load_font('bold', 28)
    brand_font = load_font('bold', 30)

    # Marca no topo. O logo tem fundo branco opaco, então recebe uma máscara de
    # cantos arredondados para virar um selo em vez de um quadrado colado.
    if LOGO.exists():
        tile = 84
        logo = Image.open(LOGO).convert('RGB').resize((tile, tile), Image.LANCZOS)
        mask = Image.new('L', (tile, tile), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile - 1, tile - 1], radius=20, fill=255)
        img.paste(logo, (margin_x, 74), mask)
        draw.text((margin_x + 108, 116), 'PetOrlândia', font=brand_font, fill=WHITE, anchor='lm')

    draw.multiline_text(
        (margin_x, 226),
        TITLE,
        font=title_font,
        fill=WHITE,
        spacing=16,
    )

    draw.text((margin_x, 404), FEATURES, font=feature_font, fill=INK_SOFT)

    # Selo da oferta. Medimos pela caixa do texto e centralizamos na vertical
    # com anchor='lm', para a pílula não virar elipse quando a fonte muda.
    badge_box = draw.textbbox((0, 0), BADGE, font=badge_font)
    badge_w = badge_box[2] - badge_box[0]
    pad_x, pad_y = 34, 24
    bx0, by0 = margin_x, 470
    badge_bottom = by0 + badge_font.size + pad_y * 2
    draw.rounded_rectangle(
        [bx0, by0, bx0 + badge_w + pad_x * 2, badge_bottom],
        radius=16,
        fill=ACCENT,
    )
    draw.text(
        (bx0 + pad_x, (by0 + badge_bottom) // 2),
        BADGE,
        font=badge_font,
        fill=INK,
        anchor='lm',
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT, 'PNG', optimize=True)
    print(f'OK: {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size // 1024} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
