import io
import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db
from models import (
    AdministracaoRegistro,
    Animal,
    BlocoPrescricao,
    Clinica,
    Consulta,
    FotoTratamento,
    ItemTratamento,
    Prescricao,
    TratamentoAcompanhamento,
    User,
    Veterinario,
)
from services.tratamento import (
    parse_duracao_dias,
    parse_intervalo_horas,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def _create_veterinarian(name, email, password, crmv, clinic=None):
    vet = User(name=name, email=email, worker='veterinario', role='admin')
    vet.set_password(password)
    db.session.add(vet)
    db.session.flush()
    db.session.add(Veterinario(user=vet, crmv=crmv, clinica=clinic))
    return vet


def _setup_bloco(app):
    """Clinica + vet + tutor + animal + bloco com 3 prescrições variadas."""
    with app.app_context():
        db.drop_all()
        db.create_all()

        clinica = Clinica(nome='Clinica Tratamento')
        db.session.add(clinica)
        db.session.flush()

        vet = _create_veterinarian('Vet', 'vet@example.com', 'pw1', 'SP-111', clinic=clinica)

        tutor = User(name='Tutor', email='tutor@example.com', phone='11999998888')
        tutor.set_password('pw2')
        estranho = User(name='Estranho', email='estranho@example.com')
        estranho.set_password('pw3')
        animal = Animal(name='Rex', owner=tutor, clinica=clinica)
        db.session.add_all([tutor, estranho, animal])
        db.session.flush()

        consulta = Consulta(
            animal_id=animal.id, created_by=vet.id,
            status='in_progress', clinica_id=clinica.id,
        )
        bloco = BlocoPrescricao(animal=animal, saved_by=vet, clinica=clinica)
        db.session.add_all([consulta, bloco])
        db.session.flush()

        prescricoes = [
            Prescricao(
                animal_id=animal.id, bloco_id=bloco.id,
                medicamento='Amoxicilina 250mg',
                dosagem='1 comprimido', frequencia='BID', duracao='7 dias',
            ),
            Prescricao(
                animal_id=animal.id, bloco_id=bloco.id,
                medicamento='Shampoo clorexidina',
                dosagem='banho', frequencia='conforme orientação', duracao='até melhorar',
            ),
            Prescricao(
                animal_id=animal.id, bloco_id=bloco.id,
                medicamento='Prednisolona',
                dosagem='5 mg/kg', frequencia='a cada 24 horas', duracao='2 semanas',
            ),
        ]
        db.session.add_all(prescricoes)
        db.session.commit()
        return bloco.id, animal.id


def _login(client, email, password):
    resp = client.post(
        '/login',
        data={'email': email, 'password': password},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return resp


def test_parse_intervalo_horas():
    assert parse_intervalo_horas('SID') == 24
    assert parse_intervalo_horas('bid') == 12
    assert parse_intervalo_horas('TID') == 8
    assert parse_intervalo_horas('a cada 12 horas') == 12
    assert parse_intervalo_horas('de 8 em 8 horas') == 8
    assert parse_intervalo_horas('12/12h') == 12
    assert parse_intervalo_horas('2x ao dia') == 12
    assert parse_intervalo_horas('3 vezes por dia') == 8
    assert parse_intervalo_horas('1x por semana') == 168
    assert parse_intervalo_horas('uma vez ao dia') == 24
    assert parse_intervalo_horas('a cada 2 dias') == 48
    assert parse_intervalo_horas('conforme necessário') is None
    assert parse_intervalo_horas('') is None
    assert parse_intervalo_horas(None) is None


def test_parse_duracao_dias():
    assert parse_duracao_dias('7 dias') == 7
    assert parse_duracao_dias('por 10 dias') == 10
    assert parse_duracao_dias('2 semanas') == 14
    assert parse_duracao_dias('1 mês') == 30
    assert parse_duracao_dias('dose única') == 1
    assert parse_duracao_dias('até melhorar') is None
    assert parse_duracao_dias(None) is None


def test_ativar_acompanhamento_cria_itens_e_agenda(app):
    bloco_id, _ = _setup_bloco(app)
    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw1')
        resp = client.post(f'/bloco_prescricao/{bloco_id}/acompanhamento')
        assert resp.status_code == 302

    with app.app_context():
        acomp = TratamentoAcompanhamento.query.filter_by(bloco_id=bloco_id).one()
        assert acomp.status == 'ativo'
        assert len(acomp.itens) == 3

        por_med = {i.prescricao.medicamento: i for i in acomp.itens}
        amoxi = por_med['Amoxicilina 250mg']
        assert amoxi.modo == 'agendado'
        assert amoxi.intervalo_horas == 12
        assert amoxi.duracao_dias == 7
        assert len(amoxi.registros) == 14  # 7 dias BID

        shampoo = por_med['Shampoo clorexidina']
        assert shampoo.modo == 'livre'
        assert len(shampoo.registros) == 0

        pred = por_med['Prednisolona']
        assert pred.modo == 'agendado'
        assert pred.intervalo_horas == 24
        assert len(pred.registros) == 14  # 14 dias SID

    # Idempotente: segundo POST não duplica
    with client:
        _login(client, 'vet@example.com', 'pw1')
        client.post(f'/bloco_prescricao/{bloco_id}/acompanhamento')
    with app.app_context():
        assert TratamentoAcompanhamento.query.filter_by(bloco_id=bloco_id).count() == 1
        tratamento_id = TratamentoAcompanhamento.query.filter_by(bloco_id=bloco_id).one().id

    # Vet vê a página com a área do veterinário e o link de WhatsApp do tutor
    with client:
        _login(client, 'vet@example.com', 'pw1')
        resp = client.get(f'/tratamento/{tratamento_id}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Área do veterinário' in html
        assert 'wa.me/5511999998888' in html
    with app.app_context():
        db.drop_all()


def test_tutor_nao_pode_ativar(app):
    bloco_id, _ = _setup_bloco(app)
    client = app.test_client()
    with client:
        _login(client, 'tutor@example.com', 'pw2')
        client.post(f'/bloco_prescricao/{bloco_id}/acompanhamento')
    with app.app_context():
        assert TratamentoAcompanhamento.query.filter_by(bloco_id=bloco_id).count() == 0
        db.drop_all()


def _ativar(app, bloco_id):
    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw1')
        client.post(f'/bloco_prescricao/{bloco_id}/acompanhamento')
    with app.app_context():
        return TratamentoAcompanhamento.query.filter_by(bloco_id=bloco_id).one().id


def test_tutor_acessa_pagina_e_marca_acoes(app):
    bloco_id, _ = _setup_bloco(app)
    tratamento_id = _ativar(app, bloco_id)

    with app.app_context():
        acomp = db.session.get(TratamentoAcompanhamento, tratamento_id)
        amoxi = next(i for i in acomp.itens if i.modo == 'agendado')
        shampoo = next(i for i in acomp.itens if i.modo == 'livre')
        registro = amoxi.registros[0]
        amoxi_id, shampoo_id, registro_id = amoxi.id, shampoo.id, registro.id

    client = app.test_client()
    with client:
        _login(client, 'tutor@example.com', 'pw2')

        resp = client.get(f'/tratamento/{tratamento_id}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Amoxicilina 250mg' in html
        assert 'Shampoo clorexidina' in html

        # marca compra
        resp = client.post(f'/tratamento/item/{amoxi_id}/comprado')
        assert resp.status_code == 302

        # marca dose agendada como feita
        resp = client.post(
            f'/tratamento/registro/{registro_id}/marcar',
            data={'status': 'feita'},
        )
        assert resp.status_code == 302

        # registra aplicação livre
        resp = client.post(
            f'/tratamento/item/{shampoo_id}/registrar',
            data={'observacao': 'banho dado'},
        )
        assert resp.status_code == 302

    with app.app_context():
        item = db.session.get(ItemTratamento, amoxi_id)
        assert item.comprado_em is not None
        registro = db.session.get(AdministracaoRegistro, registro_id)
        assert registro.status == 'feita'
        assert registro.realizada_em is not None
        avulso = AdministracaoRegistro.query.filter_by(item_id=shampoo_id).one()
        assert avulso.status == 'feita'
        assert avulso.observacao == 'banho dado'
        db.drop_all()


def test_estranho_recebe_404(app):
    bloco_id, _ = _setup_bloco(app)
    tratamento_id = _ativar(app, bloco_id)

    client = app.test_client()
    with client:
        _login(client, 'estranho@example.com', 'pw3')
        resp = client.get(f'/tratamento/{tratamento_id}')
        assert resp.status_code == 404
    with app.app_context():
        db.drop_all()


def test_upload_foto(app, monkeypatch):
    bloco_id, _ = _setup_bloco(app)
    tratamento_id = _ativar(app, bloco_id)

    import app as app_module
    monkeypatch.setattr(
        app_module, 'upload_to_s3',
        lambda file, filename, folder='uploads': f'https://s3.example/{folder}/{filename}',
    )

    client = app.test_client()
    with client:
        _login(client, 'tutor@example.com', 'pw2')
        resp = client.post(
            f'/tratamento/{tratamento_id}/foto',
            data={
                'foto': (io.BytesIO(b'fake-image-bytes'), 'evolucao.jpg'),
                'observacao': 'dia 1',
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 302

    with app.app_context():
        foto = FotoTratamento.query.filter_by(acompanhamento_id=tratamento_id).one()
        assert foto.url.startswith('https://s3.example/tratamentos/')
        assert foto.observacao == 'dia 1'
        db.drop_all()


def test_imprimir_mostra_botao_e_link(app):
    bloco_id, _ = _setup_bloco(app)

    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw1')
        resp = client.get(f'/bloco_prescricao/{bloco_id}/imprimir')
        assert resp.status_code == 200
        assert 'Ativar acompanhamento' in resp.get_data(as_text=True)

    tratamento_id = _ativar(app, bloco_id)
    with client:
        _login(client, 'vet@example.com', 'pw1')
        resp = client.get(f'/bloco_prescricao/{bloco_id}/imprimir')
        html = resp.get_data(as_text=True)
        assert f'/tratamento/{tratamento_id}' in html
        assert 'Acompanhamento' in html
    with app.app_context():
        db.drop_all()
