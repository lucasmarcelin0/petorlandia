"""Gera a imagem de compartilhamento das páginas públicas do tutor.

A carteirinha de vacinação é enviada por WhatsApp para o tutor. A prévia
dessas páginas não pode usar a arte de venda da landing (og-petorlandia.png):
quem recebe é o dono do animal, não um cliente em potencial.

O ícone do pastor-gato tem cantos transparentes, e o WhatsApp pinta
transparência de preto na prévia. Por isso achatamos sobre fundo branco — os
cantos já são brancos com alfa 0, então o resultado é idêntico ao original,
só que opaco.

A imagem é um asset estático versionado: rode este script só quando o ícone
mudar, e faça commit do PNG resultante.

    python scripts/gen_og_carteirinha.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'static' / 'pastorgato-512.png'
OUTPUT = ROOT / 'static' / 'img' / 'og-carteirinha.png'

# Quadrada de propósito: com 1:1 o WhatsApp usa o cartão de miniatura pequena,
# que é como essa prévia sempre apareceu, em vez da faixa larga da landing.
SIZE = 600
MARGIN = 36
BACKGROUND = (255, 255, 255)


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f'Ícone de origem não encontrado: {SOURCE}')

    icon = Image.open(SOURCE).convert('RGBA')
    inner = SIZE - MARGIN * 2
    icon = icon.resize((inner, inner), Image.LANCZOS)

    canvas = Image.new('RGB', (SIZE, SIZE), BACKGROUND)
    # A própria imagem serve de máscara: preserva o antialiasing das bordas
    # arredondadas em vez de recortá-las em degrau.
    canvas.paste(icon, (MARGIN, MARGIN), icon)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT, 'PNG', optimize=True)
    print(f'OK: {OUTPUT.relative_to(ROOT)} ({SIZE}x{SIZE}, {OUTPUT.stat().st_size // 1024} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
