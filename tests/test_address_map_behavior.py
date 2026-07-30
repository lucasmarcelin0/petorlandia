from pathlib import Path


def test_reverse_geocoding_preserves_the_selected_coordinates():
    template = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "partials"
        / "endereco_form.html"
    ).read_text(encoding="utf-8")

    current_location_section = template.split(
        "function preencherComLocalizacao(trigger)", 1
    )[1].split("function preencherComLocalizacaoDoMapa(trigger)", 1)[0]
    map_location_section = template.split(
        "function preencherComLocalizacaoDoMapa(trigger)", 1
    )[1].split("// Validação melhorada", 1)[0]

    assert "preferCepLookup: false" in current_location_section
    assert "applyCoordinates(latitude, longitude);" in current_location_section
    assert "preferCepLookup: false" in map_location_section
    assert "coordinateManager?.setCoordinates(coords.lat, coords.lon);" in map_location_section
    assert "preferCepLookup: true" not in map_location_section
