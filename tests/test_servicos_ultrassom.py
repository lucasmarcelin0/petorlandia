import sys

from extensions import db
from models import (
    Endereco,
    Specialty,
    User,
    Veterinario,
    VeterinarioAtendeCidade,
)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _make_tutor(email='tutor-ultra@example.com'):
    user = User(name='Tutor Ultra', email=email, role='adotante')
    user.set_password('secret123')
    db.session.add(user)
    db.session.flush()
    return user


def _make_ultrasound_vet(
    name='Robson Ultra',
    email='robson-ultra@example.com',
    phone='31994911955',
    cidades=('Belo Horizonte', 'Contagem', 'Brumadinho'),
):
    user = User(
        name=name,
        email=email,
        role='veterinario',
        worker='veterinario',
        phone=phone,
    )
    user.set_password('secret123')
    db.session.add(user)
    db.session.flush()

    spec = (
        Specialty.query.filter_by(nome='Ultrassonografia').first()
        or Specialty(nome='Ultrassonografia')
    )
    vet = Veterinario(
        user_id=user.id,
        crmv='CRMV-MG 26136',
        public_visible=True,
        public_profile_type='profissional',
    )
    vet.specialties = [spec]
    vet.cidades_atendidas = [
        VeterinarioAtendeCidade(cidade=c, uf='MG') for c in cidades
    ]
    db.session.add(vet)
    db.session.commit()
    return vet


def test_servicos_ultrassom_requires_login(client):
    resp = client.get('/servicos/ultrassom')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_lists_provider_in_each_covered_city(app, client):
    with app.app_context():
        tutor = _make_tutor()
        _make_ultrasound_vet()
        tutor_id = tutor.id

    _login(client, tutor_id)
    for cidade in ('Belo Horizonte', 'Contagem', 'Brumadinho'):
        resp = client.get('/servicos/ultrassom', query_string={'cidade': cidade})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'Robson Ultra' in body
        # WhatsApp link com DDI 55 prefixado pelo helper
        assert 'wa.me/5531994911955' in body


def test_excludes_provider_outside_coverage(app, client):
    with app.app_context():
        tutor = _make_tutor()
        _make_ultrasound_vet()
        tutor_id = tutor.id

    _login(client, tutor_id)
    resp = client.get('/servicos/ultrassom', query_string={'cidade': 'Uberlândia'})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Robson Ultra' not in body


def test_vet_serves_city_uses_coverage_and_address_fallback(app):
    app_module = sys.modules[app.import_name]
    with app.app_context():
        vet = _make_ultrasound_vet(email='cov@example.com')
        # cobertura explícita cobre as três cidades (case/acentos normalizados)
        assert app_module._vet_serves_city(vet, 'Contagem')
        assert app_module._vet_serves_city(vet, 'contagem')
        assert app_module._vet_serves_city(vet, 'Belo Horizonte')
        assert not app_module._vet_serves_city(vet, 'Uberlândia')

        # sem cobertura cadastrada → cai para a cidade do endereço (compat)
        u = User(
            name='Vet Endereco',
            email='vet-addr@example.com',
            role='veterinario',
            worker='veterinario',
        )
        u.set_password('secret123')
        u.endereco = Endereco(cep='30000-000', rua='Rua X', cidade='Sabará', estado='MG')
        db.session.add(u)
        db.session.flush()
        v2 = Veterinario(
            user_id=u.id,
            crmv='CRMV-MG 1',
            public_visible=True,
            public_profile_type='profissional',
        )
        db.session.add(v2)
        db.session.commit()

        assert app_module._vet_serves_city(v2, 'Sabará')
        assert not app_module._vet_serves_city(v2, 'Contagem')


def test_servicos_page_shows_ultrassom_service(app, client):
    with app.app_context():
        tutor = _make_tutor()
        _make_ultrasound_vet()
        tutor_id = tutor.id

    _login(client, tutor_id)
    resp = client.get('/servicos', query_string={'cidade': 'Brumadinho'})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Ultrassom a domicílio' in body
    assert '/servicos/ultrassom' in body
