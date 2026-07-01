import sys

from extensions import db
from models import Animal, Endereco, Specialty, User, Veterinario, VeterinarioAtendeCidade


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _make_tutor(email='tutor-geo@example.com', cidade=None):
    user = User(name='Tutor Geo', email=email, role='adotante')
    user.set_password('secret123')
    if cidade:
        user.endereco = Endereco(cep='30000-000', rua='Rua A', cidade=cidade, estado='MG')
    db.session.add(user)
    db.session.commit()
    return user


def _make_vet(name, email, city=None, coverage=(), specialty=None):
    user = User(name=name, email=email, role='veterinario', worker='veterinario')
    user.set_password('secret123')
    if city:
        user.endereco = Endereco(cep='30000-000', rua='Rua V', cidade=city, estado='MG')
    db.session.add(user)
    db.session.flush()
    vet = Veterinario(
        user_id=user.id,
        crmv='CRMV-MG 1',
        public_visible=True,
        public_profile_type='profissional',
    )
    if specialty:
        spec = Specialty.query.filter_by(nome=specialty).first() or Specialty(nome=specialty)
        vet.specialties = [spec]
    vet.cidades_atendidas = [VeterinarioAtendeCidade(cidade=c, uf='MG') for c in coverage]
    db.session.add(vet)
    db.session.commit()
    return vet


def test_api_geo_cidade_requires_login(client):
    resp = client.get('/api/geo/cidade', query_string={'lat': '-19.9', 'lon': '-44.0'})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_api_geo_cidade_returns_city(app, client, monkeypatch):
    app_module = sys.modules[app.import_name]
    monkeypatch.setattr(app_module, 'reverse_geocode_city', lambda lat, lon: 'Contagem')
    with app.app_context():
        tutor = _make_tutor()
        tutor_id = tutor.id
    _login(client, tutor_id)
    resp = client.get('/api/geo/cidade', query_string={'lat': '-19.9', 'lon': '-44.0'})
    assert resp.status_code == 200
    assert resp.get_json()['cidade'] == 'Contagem'


def test_api_geo_cidade_404_when_unknown(app, client, monkeypatch):
    app_module = sys.modules[app.import_name]
    monkeypatch.setattr(app_module, 'reverse_geocode_city', lambda lat, lon: None)
    with app.app_context():
        tutor = _make_tutor(email='tutor-geo2@example.com')
        tutor_id = tutor.id
    _login(client, tutor_id)
    resp = client.get('/api/geo/cidade', query_string={'lat': '0', 'lon': '0'})
    assert resp.status_code == 404
    assert resp.get_json()['cidade'] is None


def test_exames_all_cities_shows_all_specialists(app, client):
    with app.app_context():
        tutor = _make_tutor()
        animal = Animal(name='Rex', user_id=tutor.id)
        db.session.add(animal)
        _make_vet('Vet Alfa', 'vet-alfa-geo@example.com', city='Belo Horizonte')
        _make_vet('Vet Beta', 'vet-beta-geo@example.com', city='Contagem')
        db.session.commit()
        tutor_id, animal_id = tutor.id, animal.id

    _login(client, tutor_id)
    # cidade presente porém vazia = "Todas as cidades" → mostra todos
    resp = client.get('/servicos/exames', query_string={'animal_id': animal_id, 'cidade': ''})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Todas as cidades' in body            # seletor renderizado
    assert 'Vet Alfa' in body
    assert 'Vet Beta' in body


def test_exames_city_filter_limits_specialists(app, client):
    with app.app_context():
        tutor = _make_tutor(email='tutor-geo3@example.com')
        animal = Animal(name='Rex', user_id=tutor.id)
        db.session.add(animal)
        _make_vet('Vet Alfa', 'vet-alfa-geo3@example.com', city='Belo Horizonte')
        _make_vet('Vet Beta', 'vet-beta-geo3@example.com', city='Contagem')
        db.session.commit()
        tutor_id, animal_id = tutor.id, animal.id

    _login(client, tutor_id)
    resp = client.get('/servicos/exames', query_string={'animal_id': animal_id, 'cidade': 'Contagem'})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Vet Beta' in body
    assert 'Vet Alfa' not in body


def test_servicos_auto_locate_on_without_registered_city(app, client):
    with app.app_context():
        tutor = _make_tutor(email='sem-cidade@example.com')
        tutor_id = tutor.id
    _login(client, tutor_id)
    body = client.get('/servicos').get_data(as_text=True)
    assert 'service-locate-btn' in body
    assert 'data-auto-locate="1"' in body


def test_servicos_auto_locate_off_with_registered_city(app, client):
    with app.app_context():
        tutor = _make_tutor(email='com-cidade@example.com', cidade='Belo Horizonte')
        tutor_id = tutor.id
    _login(client, tutor_id)
    body = client.get('/servicos').get_data(as_text=True)
    assert 'data-auto-locate="0"' in body
