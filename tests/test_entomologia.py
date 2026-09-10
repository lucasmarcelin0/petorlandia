import csv
import io
import json
from pathlib import Path

import pytest
from flask import Flask
from flask_login import LoginManager

from blueprints.sfa import bp
from scripts.import_entomologia import METRICS, number, read_visits
from services.entomologia_service import DATA_DIR, load_entomologia, load_reference_maps

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def dashboard_app():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config.update(TESTING=True, SECRET_KEY='test')
    app.jinja_env.globals['csrf_token'] = lambda: 'test-csrf'
    login = LoginManager(app)
    login.user_loader(lambda _id: None)
    app.register_blueprint(bp)
    return app


def test_snapshot_reconciles_and_excludes_identifiers():
    data = load_entomologia()
    assert len(data['records']) == 2371
    assert sum(r['worked'] for r in data['records']) == 16507
    assert sum(r['positive'] or 0 for r in data['records']) == 215
    assert sum(r['positive'] is None for r in data['records']) == 1949
    assert len(data['census']['features']) == 78
    assert sum(f['properties']['population'] for f in data['census']['features']) == 38319
    allowed = {'date', 'area', 'sector', 'block', *METRICS}
    assert all(set(r) == allowed for r in data['records'])
    assert all(len(r['sector']) == 15 for r in data['records'])
    assert len(data['source']['unmatched_sectors']) == 5


def test_import_handles_cp1252_preamble_missing_zero_and_repeated_rows():
    headers = ['LOGIN','DATA','AREA','CENSITARIO','QUARTEIRÃO',*METRICS.values()]
    sample = dict.fromkeys(headers,'')
    sample.update(LOGIN='private-user', DATA='2026-02-03', AREA='1', CENSITARIO='353430205000001', **{'QUARTEIRÃO':'12','IM TRAB':'2','IM. LARVA':'0'})
    stream = io.StringIO()
    stream.write('Visita a Imóvel\nExportação\n\n')
    writer = csv.DictWriter(stream,fieldnames=headers,delimiter=';')
    writer.writeheader()
    writer.writerow(sample)
    writer.writerow(sample)
    rows, repeated = read_visits(stream.getvalue().encode('cp1252'))
    assert len(rows) == 2 and repeated == 1
    assert rows[0]['positive'] == 0
    assert rows[0]['aegypti'] is None
    assert 'private-user' not in json.dumps(rows)
    assert number(0) == 0
    assert number('2,3') == 2.3
    assert number('X') is None
    with pytest.raises(ValueError):
        number('-1')
    with pytest.raises(ValueError):
        number('NaN')


def test_page_renders_all_views_and_navigation(dashboard_app):
    response = dashboard_app.test_client().get('/sfa/entomologia')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'panel-visits' in html and 'panel-census' in html and 'panel-reference' in html
    assert html.index('>Ações</span>') < html.index('>Território e vigilância</div>') < html.index('v1.0 — SFA Flask')
    assert 'private, no-store' == response.headers['Cache-Control']
    assert response.headers['Referrer-Policy'] == 'no-referrer'


@pytest.mark.parametrize('url', ['/sfa/entomologia','/sfa/entomologia/mapas/mapa-01.jpg'])
def test_data_and_maps_require_internal_access(dashboard_app, monkeypatch, url):
    dashboard_app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0')
    monkeypatch.setenv('SFA_ADMIN_TOKEN','only-this-token')
    client = dashboard_app.test_client()
    assert client.get(url).status_code == 401
    assert client.get(url,headers={'X-SFA-Token':'wrong'}).status_code == 401
    response = client.get(url,headers={'X-SFA-Token':'only-this-token'})
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_only_manifest_maps_can_be_read(dashboard_app):
    client = dashboard_app.test_client()
    assert client.get('/sfa/entomologia/mapas/manifest.json').status_code == 404
    assert client.get('/sfa/entomologia/mapas/snapshot.json').status_code == 404
    maps = load_reference_maps()
    assert len(maps) == 14
    assert all((DATA_DIR / 'maps' / m['file']).is_file() for m in maps)
