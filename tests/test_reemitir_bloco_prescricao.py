import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db
from models import Animal, BlocoPrescricao, Clinica, Prescricao, User, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def _vet(name, email, crmv, clinica):
    user = User(name=name, email=email, worker='veterinario', role='adotante')
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    db.session.add(Veterinario(user=user, crmv=crmv, clinica=clinica))
    return user


@pytest.fixture
def seed(app):
    with app.app_context():
        clinica = Clinica(nome='Clinica Reemissao')
        outra_clinica = Clinica(nome='Outra Clinica')
        db.session.add_all([clinica, outra_clinica])
        db.session.flush()

        autor = _vet('Vet Autor', 'autor@example.com', 'SP-111', clinica)
        colega = _vet('Vet Colega', 'colega@example.com', 'SP-222', clinica)
        _vet('Vet Externo', 'externo@example.com', 'SP-333', outra_clinica)

        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('x')
        animal = Animal(name='Rex', owner=tutor, clinica=clinica)
        db.session.add_all([tutor, animal])
        db.session.flush()

        bloco = BlocoPrescricao(
            animal=animal,
            clinica=clinica,
            saved_by=autor,
            instrucoes_gerais='Manter o local limpo e seco.',
        )
        db.session.add(bloco)
        db.session.flush()
        db.session.add_all([
            Prescricao(
                bloco=bloco, animal=animal, medicamento='Dipirona 1 g comprimido',
                dosagem='1/2 comprimido', frequencia='8/8h', duracao='3 dias',
            ),
            Prescricao(
                bloco=bloco, animal=animal, medicamento='Pomada de sulfadiazina de prata',
                observacoes='Aplicar camada fina de 12/12h por 10 dias.',
            ),
        ])
        db.session.commit()
        return {
            'bloco_id': bloco.id,
            'animal_id': animal.id,
            'clinica_id': clinica.id,
            'colega_id': colega.id,
        }


def _login(client, email):
    client.post('/login', data={'email': email, 'password': 'x'}, follow_redirects=True)


def _blocos_do_animal(animal_id):
    return (
        BlocoPrescricao.query
        .filter_by(animal_id=animal_id)
        .order_by(BlocoPrescricao.id)
        .all()
    )


def test_tela_de_reemissao_vem_preenchida_com_a_receita_original(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'colega@example.com')
        resp = client.get(f"/bloco_prescricao/{seed['bloco_id']}/reemitir")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Reemitir receita' in html
    assert 'Emitir nova receita' in html
    assert 'salvarReemissaoBloco' in html
    assert 'Dipirona 1 g comprimido' in html
    assert 'Pomada de sulfadiazina de prata' in html
    assert 'Manter o local limpo e seco.' in html
    # A tela de edição comum continua igual.
    assert 'Salvar alteracoes' not in html


def test_reemitir_cria_receita_nova_e_preserva_a_original(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'colega@example.com')
        resp = client.post(
            f"/bloco_prescricao/{seed['bloco_id']}/reemitir",
            json={
                'medicamentos': [
                    {'medicamento': 'Dipirona 1 g comprimido', 'dosagem': '1/2 comprimido',
                     'frequencia': '8/8h', 'duracao': '5 dias', 'observacoes': 'ignorar'},
                    {'medicamento': 'Pomada de sulfadiazina de prata', 'dosagem': '',
                     'frequencia': '', 'duracao': '', 'observacoes': 'Aplicar por mais 7 dias.'},
                ],
                'instrucoes_gerais': 'Continuar o tratamento.\r\nRetorno em 7 dias.',
            },
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    novo_id = data['bloco_id']
    assert novo_id != seed['bloco_id']
    assert data['redirect_url'] == f'/bloco_prescricao/{novo_id}/imprimir'

    with app.app_context():
        blocos = _blocos_do_animal(seed['animal_id'])
        assert [b.id for b in blocos] == [seed['bloco_id'], novo_id]

        original = db.session.get(BlocoPrescricao, seed['bloco_id'])
        assert original.instrucoes_gerais == 'Manter o local limpo e seco.'
        assert original.saved_by.email == 'autor@example.com'
        assert sorted(p.duracao or '' for p in original.prescricoes) == ['', '3 dias']

        nova = db.session.get(BlocoPrescricao, novo_id)
        assert nova.clinica_id == seed['clinica_id']
        assert nova.saved_by_id == seed['colega_id']
        assert nova.instrucoes_gerais == 'Continuar o tratamento.\nRetorno em 7 dias.'
        itens = {p.medicamento: p for p in nova.prescricoes}
        dipirona = itens['Dipirona 1 g comprimido']
        assert (dipirona.dosagem, dipirona.frequencia, dipirona.duracao) == ('1/2 comprimido', '8/8h', '5 dias')
        assert dipirona.observacoes is None
        pomada = itens['Pomada de sulfadiazina de prata']
        assert pomada.observacoes == 'Aplicar por mais 7 dias.'
        assert (pomada.dosagem, pomada.frequencia, pomada.duracao) == (None, None, None)
        assert all(p.animal_id == seed['animal_id'] for p in nova.prescricoes)


def test_reemitir_sem_ajustes_copia_a_receita_original(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'colega@example.com')
        resp = client.post(f"/bloco_prescricao/{seed['bloco_id']}/reemitir")

    assert resp.status_code == 200
    novo_id = resp.get_json()['bloco_id']
    with app.app_context():
        original = db.session.get(BlocoPrescricao, seed['bloco_id'])
        nova = db.session.get(BlocoPrescricao, novo_id)

        def resumo(bloco):
            return sorted(
                (p.medicamento, p.dosagem, p.frequencia, p.duracao, p.observacoes)
                for p in bloco.prescricoes
            )

        assert resumo(nova) == resumo(original)
        assert nova.instrucoes_gerais == original.instrucoes_gerais
        assert len(original.prescricoes) == 2


def test_reemitir_recusa_medicamento_sem_nome(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'colega@example.com')
        resp = client.post(
            f"/bloco_prescricao/{seed['bloco_id']}/reemitir",
            json={'medicamentos': [{'medicamento': '  ', 'dosagem': '1 comprimido'}], 'instrucoes_gerais': ''},
        )

    assert resp.status_code == 400
    assert resp.get_json()['success'] is False
    with app.app_context():
        assert len(_blocos_do_animal(seed['animal_id'])) == 1


def test_reemitir_recusa_receita_vazia(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'colega@example.com')
        resp = client.post(
            f"/bloco_prescricao/{seed['bloco_id']}/reemitir",
            json={'medicamentos': [], 'instrucoes_gerais': '   '},
        )

    assert resp.status_code == 400
    with app.app_context():
        assert len(_blocos_do_animal(seed['animal_id'])) == 1


def test_tutor_nao_pode_reemitir(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'tutor@example.com')
        resp_get = client.get(f"/bloco_prescricao/{seed['bloco_id']}/reemitir")
        resp_post = client.post(f"/bloco_prescricao/{seed['bloco_id']}/reemitir")

    assert resp_get.status_code in {302, 403, 404}
    assert resp_post.status_code in {403, 404}
    with app.app_context():
        assert len(_blocos_do_animal(seed['animal_id'])) == 1


def test_veterinario_de_outra_clinica_nao_pode_reemitir(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'externo@example.com')
        resp_get = client.get(f"/bloco_prescricao/{seed['bloco_id']}/reemitir")
        resp_post = client.post(f"/bloco_prescricao/{seed['bloco_id']}/reemitir")

    assert resp_get.status_code in {403, 404}
    assert resp_post.status_code in {403, 404}
    with app.app_context():
        assert len(_blocos_do_animal(seed['animal_id'])) == 1


def test_historico_mostra_botao_reemitir(app, seed):
    client = app.test_client()
    with client:
        _login(client, 'colega@example.com')
        resp = client.get(
            f"/animal/{seed['animal_id']}/historico_prescricoes?clinic_id={seed['clinica_id']}"
        )

    assert resp.status_code == 200
    html = resp.get_json()['html']
    assert f"/bloco_prescricao/{seed['bloco_id']}/reemitir" in html
    assert 'Reemitir' in html
    # Os botões existentes continuam no card.
    assert f"/bloco_prescricao/{seed['bloco_id']}/imprimir" in html
    assert f"/bloco_prescricao/{seed['bloco_id']}/editar" in html
    assert f"/bloco_prescricao/{seed['bloco_id']}/deletar" in html
