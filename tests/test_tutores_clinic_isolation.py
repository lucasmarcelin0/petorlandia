"""Isolamento de tutores entre clínicas na aba "Tutores cadastrados".

O bug que originou estes testes era de front-end (a busca guardada no
localStorage repunha o termo de uma sessão anterior e a lista renderizada pelo
servidor piscava antes de ser corrigida). Mas o que ninguém guardava era a
premissa por baixo: a listagem só pode devolver tutor da própria clínica, e os
dois caminhos de render — HTML da página e JSON do refetch — precisam concordar.
Se algum dia divergirem, é aqui que quebra.
"""

from bs4 import BeautifulSoup

from extensions import db
from models import Clinica, User, Veterinario


def _make_clinic_with_vet(nome, vet_email, tutor_name, tutor_email):
    """Cria uma clínica com um veterinário e um tutor vinculado a ela."""
    clinic = Clinica(nome=nome)
    db.session.add(clinic)
    db.session.flush()

    vet_user = User(name=f'Vet {nome}', email=vet_email, worker='veterinario')
    vet_user.set_password('senha123')
    vet_user.clinica_id = clinic.id
    db.session.add(vet_user)
    db.session.flush()

    vet = Veterinario(user_id=vet_user.id, crmv=f'CRMV-{clinic.id}', clinica_id=clinic.id)
    db.session.add(vet)

    tutor = User(name=tutor_name, email=tutor_email)
    tutor.set_password('senha123')
    tutor.clinica_id = clinic.id
    db.session.add(tutor)
    db.session.flush()

    return clinic.id, vet_user.id, tutor.id, tutor_name


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _card_names(html):
    soup = BeautifulSoup(html, 'html.parser')
    return {
        card.get('data-name', '')
        for card in soup.select('#tutor-cards [data-tutor-id]')
    }


def _setup_two_clinics(app):
    with app.app_context():
        own = _make_clinic_with_vet(
            'Clinica Alfa', 'vet-alfa@test.com', 'Caroline Alfa', 'caroline-alfa@test.com'
        )
        other = _make_clinic_with_vet(
            'Clinica Beta', 'vet-beta@test.com', 'Caroline Beta', 'caroline-beta@test.com'
        )
        db.session.commit()
        return {
            'vet_id': own[1],
            'own_tutor': own[3],
            'other_tutor': other[3],
        }


def test_listing_hides_tutors_from_other_clinics(client, app):
    data = _setup_two_clinics(app)
    _login(client, data['vet_id'])

    response = client.get('/tutores?panel=list')
    assert response.status_code == 200

    names = _card_names(response.get_data(as_text=True))
    assert data['own_tutor'].lower() in names
    assert data['other_tutor'].lower() not in names


def test_search_cannot_reach_another_clinic_tutor(client, app):
    """Um termo que casa com as duas clínicas só pode devolver a própria.

    As duas tutoras se chamam "Caroline"; buscar por esse prefixo prova que a
    busca funciona (a de casa aparece) e que o filtro de clínica continua de pé
    (a de fora não). Sem a primeira asserção o teste passaria com lista vazia.
    """
    data = _setup_two_clinics(app)
    _login(client, data['vet_id'])

    response = client.get('/tutores?panel=list&tutor_search=Caroline')
    assert response.status_code == 200

    names = _card_names(response.get_data(as_text=True))
    assert data['own_tutor'].lower() in names
    assert data['other_tutor'].lower() not in names

    # E pelo nome exato de quem é de fora: nada.
    exact = client.get(f"/tutores?panel=list&tutor_search={data['other_tutor']}")
    assert data['other_tutor'].lower() not in _card_names(exact.get_data(as_text=True))


def test_json_refetch_matches_the_rendered_page(client, app):
    """O refetch do painel usa o mesmo escopo do HTML inicial.

    Era exatamente essa divergência que fazia a lista piscar: se um caminho
    passar a enxergar mais que o outro, o vazamento aparece só por um instante
    na tela — o tipo de falha que ninguém consegue reproduzir depois.
    """
    data = _setup_two_clinics(app)
    _login(client, data['vet_id'])

    page = client.get('/tutores?panel=list')
    refetch = client.get(
        '/tutores?panel=list',
        headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
    )

    assert refetch.status_code == 200
    payload = refetch.get_json()
    assert payload and 'html' in payload

    assert _card_names(page.get_data(as_text=True)) == _card_names(payload['html'])
