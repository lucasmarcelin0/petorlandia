"""Links do Maps do painel da vacinação: só rua e número, ida e volta à Vigilância.

Em 26/11/2026 o link de "Rua 18, 566, Duas árvores na frente, J. D boa vista"
abria o Maps com "não encontrou": complemento e bairro digitado quebram a busca.
"""
import json
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import vacina_pmo_service

TEMPLATE = Path(__file__).resolve().parents[1] / 'templates' / 'vacina_pmo' / 'dashboard.html'

ENDERECOS = {
    'Rua 18, 566, Duas árvores na frente , J. D boa vista': 'Rua 18, 566',
    'Travessa P , 1551, Portao bege, Max defini': 'Travessa P, 1551',
    'Rua 16, 860, A, Jardim Boa Vista': 'Rua 16, 860',
    'Alameda 22 , 509, A, Resid.Paineiras': 'Alameda 22, 509',
    'Avenida H , 1461, Jardim das Flores': 'Avenida H, 1461',
    'Avenida B, 956': 'Avenida B, 956',
}

BASE = '-20.7216858,-47.8818183'


@pytest.mark.parametrize('endereco, esperado', ENDERECOS.items())
def test_servidor_busca_so_rua_e_numero(endereco, esperado):
    assert vacina_pmo_service._pmo_maps_search_address(endereco) == esperado


def test_servidor_rota_completa_volta_a_vigilancia():
    visitas = [SimpleNamespace(id=i, address=a) for i, a in enumerate(ENDERECOS)]
    url = vacina_pmo_service._pmo_build_full_google_maps_route_url((-20.72, -47.88), visitas, {})
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query['origin'] == query['destination'] == ['-20.72,-47.88']
    paradas = query['waypoints'][0].split('|')
    assert paradas == [f'{e}, Orlândia - SP' for e in ENDERECOS.values()]


def _run_js(expression):
    node = shutil.which('node')
    if not node:
        pytest.skip('node indisponivel para executar o JavaScript do template')
    source = TEMPLATE.read_text(encoding='utf-8')
    helpers = source[source.index('function cleanAddressForSearch('):source.index('function renderAddress(')]
    full_route = source[
        source.index('function buildFullGoogleMapsUrl('):source.index('function updateFullRouteMapsButton(')
    ]
    script = (
        "const normalizeText = (v) => String(v || '').replace(/\\s+/g, ' ').trim();\n"
        "const getRowCoordinates = () => null;\n"
        + helpers + full_route
        + f"\nprocess.stdout.write(JSON.stringify({expression}));"
    )
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def test_painel_link_de_cada_casa_usa_so_rua_e_numero():
    enderecos = list(ENDERECOS)
    urls = _run_js(f"{json.dumps(enderecos)}.map((address) => googleMapsUrl({{ address }}))")
    for url, esperado in zip(urls, ENDERECOS.values()):
        destino = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['destination'][0]
        assert destino == f'{esperado}, Orlândia - SP'


def test_painel_rota_completa_sai_e_volta_a_vigilancia():
    rows = [{'address': a} for a in ENDERECOS]
    url = _run_js(f"buildFullGoogleMapsUrl({json.dumps(rows)})")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query['origin'] == query['destination'] == [BASE]
    assert query['waypoints'][0].split('|') == [f'{e}, Orlândia - SP' for e in ENDERECOS.values()]


def test_rota_sai_da_vigilancia_na_rua_um_12(monkeypatch):
    # Ponto que o Maps identifica como a Vigilância (CNEFE da Rua Um, 12).
    monkeypatch.delenv('PMO_ROUTE_ORIGIN_LAT', raising=False)
    monkeypatch.delenv('PMO_ROUTE_ORIGIN_LNG', raising=False)
    lat, lng = vacina_pmo_service._pmo_route_origin_coords()
    assert abs(lat - -20.7216858) < 0.0005 and abs(lng - -47.8818183) < 0.0005


def test_rota_localiza_a_casa_pela_base_do_atlas_antes_do_google(app, monkeypatch):
    from services import vacina_pmo_mapa
    from services.entomologia_dengue_auto import AddressIndex

    casa = [-47.87581, -20.71128]           # Rua 18, 566 no CNEFE
    indice = AddressIndex({'cnefe': {'origin': {'type': 'cnefe'}, 'features': [
        {'type': 'Feature', 'id': 'c1', 'geometry': {'type': 'Point', 'coordinates': casa},
         'properties': {'street': 'Rua 18', 'house_number': '566', 'neighborhood': 'Parque Cecap'}},
    ]}})
    monkeypatch.setattr(vacina_pmo_mapa, 'indice_enderecos', lambda: indice)
    monkeypatch.setattr(vacina_pmo_service, '_PMO_ROUTE_COORDS_CACHE', {})
    monkeypatch.setattr(vacina_pmo_service, '_pmo_geocode_google', lambda address: pytest.fail('Google não deveria ser chamado'))
    with app.app_context():
        coords = vacina_pmo_service._pmo_geocode_address('Rua 18, 566, Duas árvores na frente, J. D boa vista')
    assert coords == (casa[1], casa[0])


def test_rota_segue_sem_atlas(app, monkeypatch):
    from services import vacina_pmo_mapa

    monkeypatch.setattr(vacina_pmo_mapa, 'indice_enderecos', lambda: None)
    with app.app_context():
        assert vacina_pmo_service._pmo_geocode_atlas('Rua 18, 566') is None
