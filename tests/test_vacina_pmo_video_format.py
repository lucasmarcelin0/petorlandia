"""Guards do formato do "Vídeo do dia" do PMO.

O vídeo existe para ser encaminhado no WhatsApp, que recusa WebM com
"formato incompatível" e só aceita MP4/H.264. Como o trecho é JavaScript
inline no template, os guards leem o próprio template — mesmo idioma usado
em tests/test_platform_hardening.py para o service worker.
"""

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / 'templates' / 'vacina_pmo' / 'dashboard.html'


@pytest.fixture(scope='module')
def source():
    return TEMPLATE.read_text(encoding='utf-8')


def test_mp4_is_preferred_over_webm(source):
    """MP4/H.264 precisa ser tentado antes do WebM, senão o Chrome grava WebM
    (ele suporta os dois) e o arquivo volta a ser recusado pelo WhatsApp."""
    candidates = re.search(
        r'const VIDEO_FORMAT_CANDIDATES = \[(.*?)\];', source, re.S
    )
    assert candidates, 'lista de formatos do MediaRecorder nao encontrada'

    formats = re.findall(r"'([^']+)'", candidates.group(1))
    assert formats, 'lista de formatos vazia'

    mp4_indexes = [i for i, fmt in enumerate(formats) if 'mp4' in fmt]
    webm_indexes = [i for i, fmt in enumerate(formats) if 'webm' in fmt]

    assert mp4_indexes, 'nenhum formato MP4 oferecido'
    assert webm_indexes, 'WebM precisa continuar como fallback'
    assert max(mp4_indexes) < min(webm_indexes), 'MP4 tem que vir antes do WebM'
    assert any('avc1' in formats[i] for i in mp4_indexes), 'MP4 precisa pedir H.264 (avc1)'


def test_download_extension_is_derived_from_what_was_recorded(source):
    """A extensao nao pode ser literal: o MediaRecorder pode entregar um
    container diferente do pedido, e renomear .webm para .mp4 nao resolve."""
    download = re.search(r'videoDownload\.download = `([^`]+)`;', source)
    assert download, 'atribuicao do nome do arquivo nao encontrada'
    assert download.group(1).endswith('.${extension}'), (
        f'extensao fixa no nome do arquivo: {download.group(1)}'
    )

    assert re.search(r'function videoFileExtension\(', source), (
        'helper que deriva a extensao do mime gravado sumiu'
    )
    assert re.search(r'recorder\?\.mimeType', source), (
        'o container tem que sair de recorder.mimeType, nao do mime solicitado'
    )


def test_blob_uses_the_recorded_container(source):
    """O Blob precisa carregar o mime realmente gravado; um Blob marcado como
    video/webm contendo MP4 confunde o sistema operacional no download."""
    assert 'new Blob(chunks, { type: containerMime })' in source


def test_webm_fallback_warns_the_user(source):
    """Se o navegador so gerar WebM o usuario precisa saber antes de tentar
    enviar, em vez de descobrir no erro do WhatsApp."""
    assert 'WhatsApp recusa' in source


def test_video_period_selector_keeps_day_and_adds_week_and_month(source):
    scopes = re.findall(r'name="pmo-video-scope" value="(day|week|month)"', source)
    assert scopes == ["day", "week", "month"]
    assert "reference_date: selectedVideoReferenceDate()" in source
    assert "period: scope" in source


def test_video_styles_are_selectable_independently_from_the_period(source):
    styles = re.findall(
        r'name="pmo-video-style" value="(mosaic|rapid|cinematic|celebration)"',
        source,
    )
    assert styles == ["mosaic", "rapid", "cinematic", "celebration"]
    assert "generatedVideoStyle = selectedVideoStyle()" in source
    assert "if (generatedVideoStyle === 'mosaic')" in source
    assert "generatedVideoStyle === 'rapid'" in source
    assert "generatedVideoStyle === 'cinematic'" in source


def test_all_four_social_styles_keep_vertical_30_fps_rendering(source):
    assert "const VIDEO_CAPTURE_FPS = 30" in source
    assert "drawRapidPetFrame" in source
    assert "drawCinematicPetFrame" in source
    assert "drawCelebrationFrame" in source
    assert "holdAnimatedCanvasFrame" in source
    assert "RAPID_PHOTO_MIN_MS" in source
    assert "RAPID_PHOTO_MAX_MS" in source
    assert "canvas.width = 1080" in source
    assert "canvas.height = 1920" in source


def test_new_styles_have_short_bounded_storyboards(source):
    assert "const CINEMATIC_HIGHLIGHT_LIMIT = 16" in source
    assert "cinematicPhotoDuration" in source
    assert "celebrationSlideDuration" in source
    assert "mosaicSlideDuration" in source
