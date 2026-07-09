from decimal import Decimal

from extensions import db
from models import Animal, Endereco, User, VaccineServiceItem, Veterinario


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _create_public_vet(name, email, city):
    user = User(
        name=name,
        email=email,
        password_hash='x',
        worker='veterinario',
        endereco=Endereco(cidade=city, estado='MG'),
    )
    vet = Veterinario(
        user=user,
        crmv='00000',
        public_visible=True,
        public_profile_type='profissional',
    )
    db.session.add(vet)
    return vet


def test_services_city_filter_routes_into_existing_flows(app, client):
    with app.app_context():
        tutor = User(
            name='Tutor BH',
            email='tutor-bh-services@example.com',
            password_hash='x',
            endereco=Endereco(cidade='Belo Horizonte', estado='MG'),
        )
        _create_public_vet(
            'Teresa Passos',
            'trpassostr@gmail.com',
            'Belo Horizonte',
        )
        db.session.add_all([
            tutor,
            VaccineServiceItem(
                nome='V8 Orlândia',
                especies='cao',
                preco=Decimal('70.00'),
                cidade='Orlândia',
                ativo=True,
            ),
        ])
        db.session.commit()
        tutor_id = tutor.id

    _login(client, tutor_id)
    response = client.get('/servicos', query_string={'cidade': 'Belo Horizonte'})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Serviços PetOrlândia em Belo Horizonte' in html
    assert '/veterinarios?cidade=Belo+Horizonte' in html
    assert '/servicos/exames?cidade=Belo+Horizonte' in html
    assert 'Vacinas em domicílio' in html
    assert 'Catálogo em preparação' in html
    assert 'Vacina Antirrábica (PMO)' not in html
    assert 'Ultrassom' not in html
    assert 'Raio-X' not in html
    assert 'Castração (BH)' in html
    assert 'acesso.pbh.gov.br' in html
    assert 'target="_blank"' in html


def test_bh_castration_card_hidden_for_other_cities(app, client):
    with app.app_context():
        tutor = User(
            name='Tutor Orlândia BH check',
            email='tutor-orlandia-bh-check@example.com',
            password_hash='x',
        )
        _create_public_vet(
            'Veterinária Orlândia BH check',
            'vet-orlandia-bh-check@example.com',
            'Orlândia',
        )
        db.session.add(tutor)
        db.session.commit()
        tutor_id = tutor.id

    _login(client, tutor_id)
    response = client.get('/servicos', query_string={'cidade': 'Orlândia'})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Castração (BH)' not in html


def test_orlandia_services_keep_pmo_and_paid_vaccine_flow(app, client):
    with app.app_context():
        tutor = User(
            name='Tutor Orlândia',
            email='tutor-orlandia-services@example.com',
            password_hash='x',
        )
        _create_public_vet(
            'Veterinária Orlândia',
            'vet-orlandia-services@example.com',
            'Orlândia',
        )
        db.session.add_all([
            tutor,
            VaccineServiceItem(
                nome='V8',
                especies='cao',
                preco=Decimal('70.00'),
                cidade='Orlândia',
                ativo=True,
            ),
        ])
        db.session.commit()
        tutor_id = tutor.id

    _login(client, tutor_id)
    response = client.get('/servicos', query_string={'cidade': 'Orlândia'})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Vacina Antirrábica (PMO)' in html
    assert '/servicos/vacinas?cidade=Orl%C3%A2ndia' in html
    assert 'Catálogo em preparação' not in html


def test_exam_flow_preserves_selected_city_and_filters_professionals(app, client):
    with app.app_context():
        tutor = User(
            name='Tutor',
            email='tutor-exam-city@example.com',
            password_hash='x',
            endereco=Endereco(cidade='Orlândia', estado='SP'),
        )
        db.session.add(tutor)
        db.session.flush()
        animal = Animal(name='Luna', user_id=tutor.id)
        teresa = _create_public_vet(
            'Teresa Passos',
            'trpassostr@gmail.com',
            'Belo Horizonte',
        )
        _create_public_vet(
            'Veterinária Orlândia',
            'vet-orlandia-exam@example.com',
            'Orlândia',
        )
        db.session.add(animal)
        db.session.commit()
        tutor_id = tutor.id
        animal_id = animal.id
        teresa_id = teresa.id

    _login(client, tutor_id)
    response = client.get(
        '/servicos/exames',
        query_string={'cidade': 'Belo Horizonte', 'animal_id': animal_id},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Profissionais filtrados por cidade: <strong>Belo Horizonte</strong>' in html
    assert f'<option value="{teresa_id}">' in html
    assert 'Veterinária Orlândia' not in html
    assert f'/servicos/exames?animal_id={animal_id}&amp;cidade=Belo+Horizonte' in html


def test_exam_pet_selection_keeps_city_before_a_pet_is_selected(app, client):
    with app.app_context():
        tutor = User(
            name='Tutor',
            email='tutor-exam-city-start@example.com',
            password_hash='x',
        )
        db.session.add(tutor)
        db.session.flush()
        animal = Animal(name='Luna', user_id=tutor.id)
        db.session.add(animal)
        db.session.commit()
        tutor_id = tutor.id
        animal_id = animal.id

    _login(client, tutor_id)
    response = client.get(
        '/servicos/exames',
        query_string={'cidade': 'Belo Horizonte'},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'/servicos/exames?animal_id={animal_id}&amp;cidade=Belo+Horizonte' in html
    assert '/servicos?cidade=Belo+Horizonte' in html


def test_paid_vaccine_flow_does_not_fall_back_to_another_city(app, client):
    with app.app_context():
        tutor = User(
            name='Tutor',
            email='tutor-vaccine-city@example.com',
            password_hash='x',
        )
        db.session.add_all([
            tutor,
            VaccineServiceItem(
                nome='V8 Somente Orlândia',
                especies='cao',
                preco=Decimal('70.00'),
                cidade='Orlândia',
                ativo=True,
            ),
        ])
        db.session.commit()
        tutor_id = tutor.id

    _login(client, tutor_id)
    response = client.get(
        '/servicos/vacinas',
        query_string={'cidade': 'Belo Horizonte'},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Nenhuma vacina disponível em Belo Horizonte' in html
    assert 'V8 Somente Orlândia' not in html
