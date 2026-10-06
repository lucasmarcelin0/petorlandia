import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db
from models import Animal, BlocoPrescricao, Clinica, Consulta, User, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def _create_veterinarian(name: str, email: str, password: str, crmv: str, clinic=None) -> User:
    vet = User(name=name, email=email, worker='veterinario', role='admin')
    vet.set_password(password)
    db.session.add(vet)
    db.session.flush()
    db.session.add(Veterinario(user=vet, crmv=crmv, clinica=clinic))
    return vet


def test_imprimir_bloco_prescricao_displays_printing_user(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        clinica = Clinica(nome='Clinica Prescricao')
        db.session.add(clinica)
        db.session.flush()

        vet1 = _create_veterinarian('Vet1', 'vet1@example.com', 'pw1', 'SP-123', clinic=clinica)
        vet2 = _create_veterinarian('Vet2', 'vet2@example.com', 'pw2', 'SP-456', clinic=clinica)

        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('pw3')
        animal = Animal(name='Jurema', owner=tutor, clinica=clinica)

        db.session.add_all([tutor, animal])
        db.session.flush()

        consulta = Consulta(animal_id=animal.id, created_by=vet1.id, status='in_progress', clinica_id=clinica.id)
        bloco = BlocoPrescricao(animal=animal, saved_by=vet1, clinica=clinica)
        db.session.add_all([consulta, bloco])
        db.session.commit()
        bloco_id = bloco.id

    client = app.test_client()
    with client:
        login_resp = client.post(
            '/login',
            data={'email': 'vet2@example.com', 'password': 'pw2'},
            follow_redirects=True,
        )
        assert login_resp.status_code == 200

        resp = client.get(f'/bloco_prescricao/{bloco_id}/imprimir')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        assert 'Impresso por:' in html
        assert 'Vet2' in html
        # Receita controlada: o CRMV ao lado de "Impresso por" só aparece
        # quando o impressor é o profissional responsável. Vet2 imprime a
        # prescrição de Vet1, então mostra apenas o nome; o CRMV do
        # responsável (Vet1) aparece na seção "Profissional Responsável".
        assert 'SP-123' in html
        assert 'Receita Digital & Medicamentos:' in html
        assert 'Mercado Pago' in html
        assert f'/r/{bloco_id}' in html
        assert 'confirme seu celular e crie sua senha' not in html

    with app.app_context():
        db.drop_all()


def test_short_prescription_url_redirect(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica Prescricao')
        db.session.add(clinica)
        db.session.flush()
        vet = _create_veterinarian('Vet1', 'vet1@example.com', 'pw1', 'SP-123', clinic=clinica)
        tutor = User(name='Isabela Abreu', email='isabela@example.com', phone='+5516999999999')
        tutor.set_password('pw3')
        animal = Animal(name='Max', owner=tutor, clinica=clinica)
        db.session.add_all([tutor, animal])
        db.session.flush()
        bloco = BlocoPrescricao(animal=animal, saved_by=vet, clinica=clinica)
        db.session.add(bloco)
        db.session.commit()
        bloco_id = bloco.id

    # O link que o tutor recebe carrega o token assinado: com ele, o link curto
    # abre a receita direto, sem senha e sem 404 — que é o objetivo do /r/.
    with app.app_context():
        from app import _first_access_token_for_user

        tutor = User.query.filter_by(email='isabela@example.com').one()
        token = _first_access_token_for_user(tutor)

    client = app.test_client()
    resp = client.get(f'/r/{bloco_id}?token={token}', follow_redirects=True)
    assert resp.status_code == 200
    assert 'Receita M' in resp.get_data(as_text=True)
    assert 'Max' in resp.get_data(as_text=True)

    with app.app_context():
        db.drop_all()


def test_short_prescription_url_nao_autentica_visitante_sem_token(app):
    """Sem o token assinado, o link curto não pode logar ninguém.

    Autenticar o tutor a partir do id numérico da URL entregaria a conta dele
    — e o prontuário do animal — a quem chutasse o número.
    """
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica Prescricao')
        db.session.add(clinica)
        db.session.flush()
        vet = _create_veterinarian('Vet1', 'vet1@example.com', 'pw1', 'SP-123', clinic=clinica)
        tutor = User(name='Isabela Abreu', email='isabela@example.com', phone='+5516999999999')
        tutor.set_password('pw3')
        animal = Animal(name='Max', owner=tutor, clinica=clinica)
        db.session.add_all([tutor, animal])
        db.session.flush()
        bloco = BlocoPrescricao(animal=animal, saved_by=vet, clinica=clinica)
        db.session.add(bloco)
        db.session.commit()
        bloco_id = bloco.id

    anonimo = app.test_client()
    corpo = anonimo.get(f'/r/{bloco_id}', follow_redirects=True).get_data(as_text=True)
    assert 'Max' not in corpo
    assert 'Isabela Abreu' not in corpo

    with anonimo.session_transaction() as sessao:
        assert '_user_id' not in sessao

    with app.app_context():
        db.drop_all()


def test_imprimir_bloco_prescricao_mostra_veterinario_que_salvou_mesmo_com_consulta_de_estagiaria(app):
    """Quando uma consulta é aberta por estagiária mas a receita é feita pelo veterinário,
    a receita impressa DEVE mostrar o veterinário responsável (com CRMV), nunca a estagiária.
    """
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica Prescricao')
        db.session.add(clinica)
        db.session.flush()

        # Veterinário supervisor
        vet = _create_veterinarian('Dr. Lucas Marcelino', 'lucas@example.com', 'pw_lucas', 'SP-65152', clinic=clinica)
        vet_profile = vet.veterinario

        # Estagiária supervisionada
        estagiaria_user = User(name='Estagiaria Laiane', email='laiane@example.com', role='estagiario', worker='estudante')
        estagiaria_user.set_password('pw_laiane')
        db.session.add(estagiaria_user)
        db.session.flush()

        estagiaria_profile = Veterinario(
            user=estagiaria_user,
            crmv=None,
            habilitacao='estagiario',
            supervisor=vet_profile,
            clinica=clinica,
        )
        db.session.add(estagiaria_profile)

        tutor = User(name='Tutor Carlos', email='carlos@example.com')
        tutor.set_password('pw_tutor')
        animal = Animal(name='Pipoca', owner=tutor, clinica=clinica)
        db.session.add_all([tutor, animal])
        db.session.flush()

        # Estagiária abriu o atendimento
        consulta = Consulta(animal_id=animal.id, created_by=estagiaria_user.id, status='in_progress', clinica_id=clinica.id)
        # Veterinário fez e salvou a prescrição
        bloco = BlocoPrescricao(animal=animal, saved_by=vet, clinica=clinica)
        db.session.add_all([consulta, bloco])
        db.session.commit()
        bloco_id = bloco.id

    client = app.test_client()
    with client:
        # Veterinário acessa a receita
        login_resp = client.post(
            '/login',
            data={'email': 'lucas@example.com', 'password': 'pw_lucas'},
            follow_redirects=True,
        )
        assert login_resp.status_code == 200

        resp = client.get(f'/bloco_prescricao/{bloco_id}/imprimir')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        # O profissional responsável deve ser o Dr. Lucas, com CRMV SP-65152
        assert 'Dr. Lucas Marcelino' in html
        assert 'SP-65152' in html
        assert 'Salvo por Dr. Lucas Marcelino' in html
        # A estagiária NÃO pode ser exibida como profissional responsável nem na assinatura
        assert 'Profissional Responsável' in html
        assert 'Estagiaria Laiane' not in html

    # Agora o tutor do animal acessa a receita
    with client:
        client.get('/logout', follow_redirects=True)
        login_resp = client.post(
            '/login',
            data={'email': 'carlos@example.com', 'password': 'pw_tutor'},
            follow_redirects=True,
        )
        assert login_resp.status_code == 200

        resp = client.get(f'/bloco_prescricao/{bloco_id}/imprimir')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        # Para o tutor, a receita DEVE mostrar o Dr. Lucas (CRMV SP-65152), e NUNCA a estagiária
        assert 'Dr. Lucas Marcelino' in html
        assert 'SP-65152' in html
        assert 'Estagiaria Laiane' not in html

    with app.app_context():
        db.drop_all()


def test_imprimir_bloco_prescricao_legado_sem_saved_by_resolve_supervisor_da_estagiaria(app):
    """Se uma receita legada não tem saved_by e a consulta foi aberta por estagiária,
    deve resolver para o supervisor com CRMV da estagiária em vez do nome dela."""
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica Prescricao')
        db.session.add(clinica)
        db.session.flush()

        vet = _create_veterinarian('Dr. Lucas Marcelino', 'lucas@example.com', 'pw_lucas', 'SP-65152', clinic=clinica)
        estagiaria_user = User(name='Estagiaria Laiane', email='laiane@example.com', role='estagiario', worker='estudante')
        estagiaria_user.set_password('pw_laiane')
        db.session.add(estagiaria_user)
        db.session.flush()

        estagiaria_profile = Veterinario(
            user=estagiaria_user,
            crmv=None,
            habilitacao='estagiario',
            supervisor=vet.veterinario,
            clinica=clinica,
        )
        db.session.add(estagiaria_profile)

        tutor = User(name='Tutor Carlos', email='carlos@example.com')
        tutor.set_password('pw_tutor')
        animal = Animal(name='Pipoca', owner=tutor, clinica=clinica)
        db.session.add_all([tutor, animal])
        db.session.flush()

        consulta = Consulta(animal_id=animal.id, created_by=estagiaria_user.id, status='in_progress', clinica_id=clinica.id)
        # saved_by é None (bloco legado)
        bloco = BlocoPrescricao(animal=animal, saved_by=None, clinica=clinica)
        db.session.add_all([consulta, bloco])
        db.session.commit()
        bloco_id = bloco.id

    client = app.test_client()
    with client:
        client.post(
            '/login',
            data={'email': 'lucas@example.com', 'password': 'pw_lucas'},
            follow_redirects=True,
        )
        resp = client.get(f'/bloco_prescricao/{bloco_id}/imprimir')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        # O profissional responsável deve ter resolvido para o supervisor (Dr. Lucas)
        assert 'Dr. Lucas Marcelino' in html
        assert 'SP-65152' in html
        assert 'Estagiaria Laiane' not in html

    with app.app_context():
        db.drop_all()
