"""Tela do atlas: o JS de busca e de rota só pode usar elementos que o template realmente tem."""
import re
from pathlib import Path

from tests.test_entomologia_atualizacao import login

ROOT = Path(__file__).resolve().parents[1]


def _page(client):
    login(client)
    response = client.get('/sfa/entomologia')
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_painel_de_rota_e_scripts_estao_na_tela(client):
    html = _page(client)
    for marker in ('id="atlas-route"', 'data-atlas-panel="atlas-route"', 'sfa_atlas_route_model.js',
                   'sfa_atlas_route.js', 'sfa_atlas_search_model.js', 'sfa_atlas_route.css',
                   'sfa_atlas_nav_model.js', 'sfa_atlas_nav.js', 'sfa_atlas_nav.css',
                   'id="atlas-route-nav"', 'id="atlas-route-sim"', 'id="atlas-route-resume"', 'sfa_atlas_nav_session.js'):
        assert marker in html, marker
    # Os modelos precisam carregar antes de quem os usa.
    assert html.index('sfa_atlas_route_model.js') < html.index('sfa_atlas_nav_model.js') < html.index('sfa_atlas_nav_session.js') < html.index('sfa_atlas_nav.js') \
        < html.index('sfa_atlas_route.js') < html.index('sfa_field_map.js')
    assert html.index('sfa_atlas_search_model.js') < html.index('sfa_atlas_search.js') < html.index('sfa_field_map.js')


def test_todo_id_usado_pelo_js_existe_no_template(client):
    html = _page(client)
    for script in ('sfa_atlas_route.js', 'sfa_atlas_search.js'):
        source = (ROOT / 'static' / 'js' / script).read_text(encoding='utf-8')
        used = set(re.findall(r"\$\('([a-z0-9-]+)'\)", source))
        missing = sorted(i for i in used if f'id="{i}"' not in html)
        assert not missing, f'{script} usa ids que o template não tem: {missing}'


def test_dataset_traz_as_urls_novas(client):
    html = _page(client)
    for name in ('search_index', 'search_place', 'street_network'):
        assert f'"{name}"' in html, name
    assert '/atlas/busca/indice' in html and '/atlas/malha' in html


def test_versoes_dos_arquivos_alterados_foram_trocadas_no_template(client):
    """Os estáticos têm cache de 1 ano por versão: sem trocar o ?v= o navegador não baixa o novo."""
    html = _page(client)
    for name, version in (('sfa_atlas_search.js', '20261005-busca2'), ('sfa_atlas_search_model.js', '20261007-letra'), ('sfa_field_map.js', '20261002-rota'),
                          ('sfa_atlas_route.js', '20261004-ux'), ('sfa_atlas_route_model.js', '20261003-nav'),
                          ('sfa_atlas_nav.js', '20261006-bussola'), ('sfa_atlas_nav_model.js', '20261006-bussola'),
                          ('sfa_atlas_nav_session.js', '20261006-bussola'),
                          ('sfa_atlas_nav.css', '20261006-bussola'), ('sfa_atlas_route.css', '20261004-ux')):
        assert re.search(re.escape(name) + r'\?v=' + re.escape(version), html), name


def test_menu_lateral_do_celular_nao_e_sobrescrito_pelo_css_do_atlas():
    # Regra antiga (<=767px) deixava o menu "relative" com 180px: sobrava um vazio no topo e a gaveta aparecia cortada.
    css = (ROOT / 'static' / 'css' / 'sfa_entomologia.css').read_text(encoding='utf-8')
    assert not re.search(r'\.sfa-sidebar\s*\{[^}]*position\s*:\s*relative', css)
    assert not re.search(r'\.sfa-header\s*\{[^}]*position\s*:\s*relative', css)


def test_paineis_do_atlas_em_sanfona_estao_na_tela(client):
    html = _page(client)
    for marker in ('sfa_atlas_accordion.js', 'sfa_atlas_accordion.css', 'id="atlas-basemap-section"', 'id="atlas-areas-section"'):
        assert marker in html, marker
    assert html.index('sfa_field_map.js') < html.index('sfa_atlas_accordion.js')
    # Cada atalho aponta para um painel que existe.
    for target in re.findall(r'data-atlas-panel="([a-z0-9-]+)"', html):
        assert f'id="{target}"' in html, target


def test_css_do_menu_tem_versao_para_furar_o_cache_do_navegador(client):
    # O navegador guarda /static por 1 h; sem ?v= o celular continuava com o CSS antigo do menu.
    html = _page(client)
    assert re.search(r'sfa_entomologia\.css\?v=[\w-]+', html)
