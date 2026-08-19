"""Guards das imagens de prévia de link (Open Graph).

As prévias aparecem no WhatsApp quando um link é compartilhado com o tutor.
Dois erros são invisíveis em desenvolvimento e só aparecem no celular de quem
recebe: dimensão declarada diferente da real (o WhatsApp corta ou descarta a
prévia) e PNG com transparência (a área transparente vira preta).
"""

import re
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates'
STATIC = ROOT / 'static'

DEFAULT_OG = ('img/og-petorlandia.png', 1200, 630)


def _declared_og_images():
    """Cada template que sobrescreve a imagem de prévia, com as dimensoes que
    declara. Varre todos os templates para que uma pagina nova entre no guard
    sozinha, sem ninguem lembrar de atualizar esta lista."""
    found = []
    for template in TEMPLATES.rglob('*.html'):
        source = template.read_text(encoding='utf-8')
        image = re.search(r"{%\s*set\s+og_image\s*=\s*'([^']+)'\s*%}", source)
        if not image:
            continue
        width = re.search(r"{%\s*set\s+og_image_width\s*=\s*(\d+)\s*%}", source)
        height = re.search(r"{%\s*set\s+og_image_height\s*=\s*(\d+)\s*%}", source)
        found.append((
            template.relative_to(ROOT).as_posix(),
            image.group(1),
            int(width.group(1)) if width else None,
            int(height.group(1)) if height else None,
        ))
    return found


ALL_OG_IMAGES = _declared_og_images()


def test_at_least_one_template_overrides_the_marketing_art():
    """Se este guard ficar sem casos, a varredura quebrou e os testes abaixo
    passariam vazios."""
    assert ALL_OG_IMAGES, 'nenhum template define og_image; a varredura falhou'


@pytest.mark.parametrize('template,filename,width,height', ALL_OG_IMAGES)
def test_declared_og_dimensions_match_the_real_file(template, filename, width, height):
    path = STATIC / filename
    assert path.exists(), f'{template} aponta para {filename}, que nao existe'

    with Image.open(path) as img:
        real = img.size

    assert (width, height) == real, (
        f'{template} declara {width}x{height} mas {filename} e {real[0]}x{real[1]}'
    )


@pytest.mark.parametrize('template,filename,width,height', ALL_OG_IMAGES)
def test_og_images_are_opaque(template, filename, width, height):
    """O WhatsApp pinta transparencia de preto na previa."""
    path = STATIC / filename
    with Image.open(path) as img:
        assert img.mode not in ('RGBA', 'LA', 'P'), (
            f'{filename} ({img.mode}) pode ter transparencia; achate o fundo'
        )


def test_default_og_image_still_matches_its_declared_size():
    """O layout usa 1200x630 como padrao quando a pagina nao sobrescreve."""
    filename, width, height = DEFAULT_OG
    with Image.open(STATIC / filename) as img:
        assert img.size == (width, height)

    layout = (TEMPLATES / 'layout.html').read_text(encoding='utf-8')
    assert f"else {width} %}}" in layout
    assert f"else {height} %}}" in layout


def test_tutor_pages_do_not_share_the_sales_art():
    """As paginas publicas do PMO sao enviadas ao tutor; a arte de venda da
    landing nao pode aparecer nessa previa."""
    tutor_pages = {
        'templates/vacina_pmo/public_certificate.html',
        'templates/vacina_pmo/public_pet_card.html',
    }
    overridden = {template for template, _, _, _ in ALL_OG_IMAGES}
    assert tutor_pages <= overridden, (
        f'sem override de og_image: {sorted(tutor_pages - overridden)}'
    )

    for template, filename, _, _ in ALL_OG_IMAGES:
        if template in tutor_pages:
            assert filename != DEFAULT_OG[0]


def test_public_certificate_renders_the_tutor_og_image(app, client):
    """Guard de ponta a ponta: o `{% set %}` no filho precisa mesmo chegar ao
    <head> do layout. So o HTML renderizado prova isso."""
    from extensions import db
    from models.pmo import PmoVaccinationVisit

    visit = PmoVaccinationVisit(
        spreadsheet_id='sheet-og',
        sheet_gid='0',
        sheet_title='11/08/2026',
        source_row=2,
        tutor_name='Antonio Carlos do Amaral',
        password='1234',
        public_token='token-og-preview',
    )
    db.session.add(visit)
    db.session.commit()

    response = client.get('/vacina-pmo/c/token-og-preview')
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    og_image = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    assert og_image, 'pagina publica sem og:image'
    assert og_image.group(1).endswith('/static/img/og-carteirinha.png'), og_image.group(1)
    assert 'og-petorlandia.png' not in og_image.group(1)

    assert '<meta property="og:image:width" content="600">' in html
    assert '<meta property="og:image:height" content="600">' in html
    assert '<meta name="twitter:card" content="summary">' in html
