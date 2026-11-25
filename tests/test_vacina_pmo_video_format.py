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
        r'name="pmo-video-style" value="(mosaic|rapid|cinematic|celebration|polaroid|badge|pop|runway)"',
        source,
    )
    assert styles == [
        "mosaic",
        "rapid",
        "cinematic",
        "celebration",
        "polaroid",
        "badge",
        "pop",
        "runway",
    ]
    assert "generatedVideoStyle = selectedVideoStyle()" in source
    assert "if (generatedVideoStyle === 'mosaic')" in source
    assert "generatedVideoStyle === 'rapid'" in source
    assert "generatedVideoStyle === 'cinematic'" in source
    assert "generatedVideoStyle === 'celebration'" in source
    assert "generatedVideoStyle === 'polaroid'" in source
    assert "generatedVideoStyle === 'badge'" in source
    assert "generatedVideoStyle === 'pop'" in source


def test_all_eight_social_styles_keep_vertical_30_fps_rendering(source):
    assert "const VIDEO_CAPTURE_FPS = 30" in source
    assert "drawRapidPetFrame" in source
    assert "drawCinematicPetFrame" in source
    assert "drawCelebrationFrame" in source
    assert "drawPolaroidFrame" in source
    assert "drawBadgePetFrame" in source
    assert "drawPopPetFrame" in source
    assert "drawRunwayPetFrame" in source
    assert "holdAnimatedCanvasFrame" in source
    assert "RAPID_PHOTO_MIN_MS" in source
    assert "RAPID_PHOTO_MAX_MS" in source
    assert "canvas.width = 1080" in source
    assert "canvas.height = 1920" in source


def test_new_styles_have_short_bounded_storyboards(source):
    assert "const CINEMATIC_HIGHLIGHT_LIMIT = 16" in source
    assert "const RUNWAY_HIGHLIGHT_LIMIT = 16" in source
    assert "cinematicPhotoDuration" in source
    assert "celebrationSlideDuration" in source
    assert "mosaicSlideDuration" in source
    assert "polaroidSlideDuration" in source
    assert "badgeCardDuration" in source
    assert "popPetDuration" in source
    assert "runwayPhotoDuration" in source


def test_mp4_header_duration_is_fixed_before_download(source):
    """O Chrome grava MP4 fragmentado com a duração do cabeçalho zerada; o
    WhatsApp lê esse campo e mostra o vídeo como se tivesse 1 segundo."""
    assert 'function fixFragmentedMp4Duration(' in source
    assert 'const blob = await finalizeRecordedVideo(chunks, containerMime);' in source
    finalize = re.search(
        r'async function finalizeRecordedVideo\(chunks, containerMime\) \{(.*?)\n  \}\n',
        source,
        re.S,
    )
    assert finalize, 'finalizeRecordedVideo nao encontrada'
    body = finalize.group(1)
    # Qualquer falha no ajuste precisa cair no arquivo original, nunca em erro.
    assert 'catch (error)' in body
    assert 'return original;' in body


# --- teste funcional: roda a função real do template no Node --------------

def _box(kind, payload):
    import struct
    return struct.pack('>I', 8 + len(payload)) + kind + payload


def _full(kind, version, flags, payload):
    import struct
    return _box(kind, struct.pack('>I', (version << 24) | flags) + payload)


def _fragmented_mp4(sample_durations_per_fragment, media_timescale=30000):
    """MP4 fragmentado mínimo no formato do Chrome: moov com duração zerada,
    mvex/trex sem mehd e um moof+mdat por trecho com duração por amostra."""
    import struct
    mvhd = _full(b'mvhd', 1, 0, struct.pack('>QQIQ', 0, 0, 1000, 0) + b'\0' * 80)
    tkhd = _full(b'tkhd', 1, 3, struct.pack('>QQIIQ', 0, 0, 1, 0, 0) + b'\0' * 52)
    mdhd = _full(b'mdhd', 1, 0, struct.pack('>QQIQ', 0, 0, media_timescale, 1745) + b'\x55\xc4\0\0')
    trak = _box(b'trak', tkhd + _box(b'mdia', mdhd))
    trex = _full(b'trex', 0, 0, struct.pack('>IIIII', 1, 1, 0, 0, 0))
    moov = _box(b'moov', mvhd + trak + _box(b'mvex', trex))
    fragments = b''
    for seq, durations in enumerate(sample_durations_per_fragment, start=1):
        tfhd = _full(b'tfhd', 0, 0x020020, struct.pack('>II', 1, 0x01010000))
        entries = b''.join(struct.pack('>II', d, 100) for d in durations)
        trun = _full(b'trun', 1, 0x000301, struct.pack('>Ii', len(durations), 0) + entries)
        moof = _box(b'moof', _full(b'mfhd', 0, 0, struct.pack('>I', seq)) + _box(b'traf', tfhd + trun))
        fragments += moof + _box(b'mdat', b'\0' * (100 * len(durations)))
    return _box(b'ftyp', b'isom\0\0\0\0isomavc1') + moov + fragments


def _read_header_durations(data):
    import struct
    found = {}

    def walk(offset, end):
        while offset + 8 <= end:
            size, kind = struct.unpack('>I4s', data[offset:offset + 8])
            body = offset + 8
            if kind in (b'mvhd', b'mdhd'):
                found[kind.decode()] = struct.unpack('>IQ', data[body + 20:body + 32])
            elif kind == b'tkhd':
                found['tkhd'] = struct.unpack('>Q', data[body + 28:body + 36])[0]
            elif kind == b'mehd':
                found['mehd'] = struct.unpack('>Q', data[body + 4:body + 12])[0]
            if kind in (b'moov', b'trak', b'mdia', b'mvex'):
                walk(body, offset + size)
            offset += size

    walk(0, len(data))
    return found


def _run_fix(source, data, tmp_path):
    import shutil
    import subprocess

    node = shutil.which('node')
    if not node:
        pytest.skip('node indisponivel para executar o JavaScript do template')
    start = source.index('function fixFragmentedMp4Duration(')
    end = source.index('async function finalizeRecordedVideo(')
    (tmp_path / 'fix.js').write_text(source[start:end], encoding='utf-8')
    (tmp_path / 'in.mp4').write_bytes(data)
    runner = (
        "const fs = require('fs');"
        "const fn = new Function(fs.readFileSync(process.argv[1], 'utf8') + '; return fixFragmentedMp4Duration;')();"
        "const input = fs.readFileSync(process.argv[2]);"
        "const out = fn(input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength));"
        "if (out) fs.writeFileSync(process.argv[3], Buffer.from(out));"
        "process.stdout.write(out ? 'fixed' : 'null');"
    )
    result = subprocess.run(
        [node, '-e', runner, str(tmp_path / 'fix.js'), str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4')],
        capture_output=True, text=True, timeout=60, check=True,
    )
    if result.stdout == 'null':
        return None
    return (tmp_path / 'out.mp4').read_bytes()


def test_fragmented_mp4_gets_real_duration_in_header(source, tmp_path):
    # 3 trechos a 30 fps (1000/30000 s por quadro): 15 + 15 + 10 quadros = 40
    # quadros = 1,333 s; o cabeçalho original dizia 0 s.
    original = _fragmented_mp4([[1000] * 15, [1000] * 15, [1000] * 10])
    fixed = _run_fix(source, original, tmp_path)
    assert fixed is not None

    durations = _read_header_durations(fixed)
    assert durations['mdhd'] == (30000, 40000)
    assert durations['mvhd'] == (1000, 1333)
    assert durations['tkhd'] == 1333
    assert durations['mehd'] == 1333

    # Só o mehd (20 bytes) é inserido; os fragmentos de vídeo ficam intactos.
    assert len(fixed) == len(original) + 20
    first_moof = original.index(b'moof') - 4
    assert fixed[first_moof + 20:] == original[first_moof:]


def test_regular_mp4_is_left_untouched(source, tmp_path):
    """MP4 sem fragmentos já tem a duração certa: a função não deve mexer."""
    import struct
    mvhd = _full(b'mvhd', 1, 0, struct.pack('>QQIQ', 0, 0, 1000, 5000) + b'\0' * 80)
    regular = _box(b'ftyp', b'isom\0\0\0\0isom') + _box(b'moov', mvhd) + _box(b'mdat', b'\0' * 64)
    assert _run_fix(source, regular, tmp_path) is None
