"""Anexo do laudo integral (arquivo unico) a blocos de exames."""
import os
from io import BytesIO

os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')

import app as app_module
from app import app as flask_app, db
from models import BlocoExames, ExameSolicitado
from tests.test_ajax_improvements import client, create_basic_clinic_data, login  # noqa: F401


def _fake_upload(monkeypatch, url='/static/uploads/laudos_exames/laudo.pdf'):
    chamadas = []

    def _upload(file, filename, folder='uploads', **kwargs):
        chamadas.append((filename, folder))
        return url

    monkeypatch.setattr(app_module, 'upload_to_s3', _upload)
    return chamadas


def test_anexar_laudo_unico_vale_para_todo_o_bloco(client, monkeypatch):
    chamadas = _fake_upload(monkeypatch)
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        bloco = BlocoExames(id=10, animal_id=animal.id)
        db.session.add_all([
            bloco,
            ExameSolicitado(id=11, bloco=bloco, nome='Hemograma'),
            ExameSolicitado(id=12, bloco=bloco, nome='Creatinina'),
            ExameSolicitado(id=13, bloco=bloco, nome='Ureia', status='cancelado'),
        ])
        db.session.commit()
        vet_id = vet_user.id
    login(monkeypatch, vet_id)

    resp = client.post(
        '/bloco_exames/10/laudo',
        data={'laudo': (BytesIO(b'%PDF-1.4 laudo'), 'Barbinha laudo.pdf'), 'data_realizacao': '2026-11-26'},
        headers={'Accept': 'application/json'},
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data['success'] is True
    html = data['html']
    assert 'Laudo completo' in html
    visao = html.split('id="exames-view-10"', 1)[1].split('id="exames-pedido-10"', 1)[0]
    assert visao.count('Barbinha_laudo.pdf') == 1
    assert chamadas and chamadas[0][1] == 'laudos_exames'
    with flask_app.app_context():
        exames = {e.id: e for e in ExameSolicitado.query.all()}
        assert {e.laudo_url for e in exames.values()} == {'/static/uploads/laudos_exames/laudo.pdf'}
        assert exames[11].status == 'concluido'
        assert exames[12].status == 'concluido'
        assert exames[13].status == 'cancelado'
        assert exames[11].performed_at.date().isoformat() == '2026-11-26'
        assert db.session.get(BlocoExames, 10).laudo_unico is not None


def test_registrar_exame_recebido_somente_com_arquivo(client, monkeypatch):
    _fake_upload(monkeypatch)
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        animal_id = animal.id
        vet_id = vet_user.id
    login(monkeypatch, vet_id)

    resp = client.post(
        f'/animal/{animal_id}/bloco_exames/laudo',
        data={
            'laudo': (BytesIO(b'%PDF-1.4 laudo'), 'bioquimica.pdf'),
            'nomes': 'Hemograma, Creatinina; Ureia',
            'observacoes': 'Laboratorio Biocenter',
        },
        headers={'Accept': 'application/json'},
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()['success'] is True
    with flask_app.app_context():
        bloco = BlocoExames.query.filter_by(animal_id=animal_id).one()
        assert bloco.observacoes_gerais == 'Laboratorio Biocenter'
        assert [e.nome for e in bloco.exames] == ['Hemograma', 'Creatinina', 'Ureia']
        assert all(e.status == 'concluido' and e.performed_at and not e.resultado for e in bloco.exames)
        assert bloco.laudo_unico.laudo_filename == 'bioquimica.pdf'


def test_exame_recebido_sem_nomes_usa_nome_padrao(client, monkeypatch):
    _fake_upload(monkeypatch)
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        animal_id = animal.id
        vet_id = vet_user.id
    login(monkeypatch, vet_id)

    resp = client.post(
        f'/animal/{animal_id}/bloco_exames/laudo',
        data={'laudo': (BytesIO(b'img'), 'laudo.jpg')},
        headers={'Accept': 'application/json'},
    )

    assert resp.status_code == 200
    with flask_app.app_context():
        bloco = BlocoExames.query.filter_by(animal_id=animal_id).one()
        assert [e.nome for e in bloco.exames] == ['Laudo de exame']


def test_laudo_rejeita_extensao_nao_permitida(client, monkeypatch):
    chamadas = _fake_upload(monkeypatch)
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        animal_id = animal.id
        vet_id = vet_user.id
    login(monkeypatch, vet_id)

    resp = client.post(
        f'/animal/{animal_id}/bloco_exames/laudo',
        data={'laudo': (BytesIO(b'MZ'), 'virus.exe')},
        headers={'Accept': 'application/json'},
    )

    assert resp.status_code == 400
    assert chamadas == []
    with flask_app.app_context():
        assert BlocoExames.query.count() == 0


def test_tutor_nao_pode_anexar_laudo(client, monkeypatch):
    chamadas = _fake_upload(monkeypatch)
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        bloco = BlocoExames(id=20, animal_id=animal.id)
        db.session.add_all([bloco, ExameSolicitado(id=21, bloco=bloco, nome='Hemograma')])
        db.session.commit()
        tutor_id = tutor.id
    login(monkeypatch, tutor_id)

    resp = client.post(
        '/bloco_exames/20/laudo',
        data={'laudo': (BytesIO(b'%PDF'), 'laudo.pdf')},
        headers={'Accept': 'application/json'},
    )

    assert resp.status_code in (403, 404)
    assert chamadas == []
    with flask_app.app_context():
        assert db.session.get(ExameSolicitado, 21).laudo_url is None


def test_laudos_diferentes_por_exame_continuam_individuais(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        bloco = BlocoExames(id=30, animal_id=animal.id)
        db.session.add_all([
            bloco,
            ExameSolicitado(id=31, bloco=bloco, nome='Raio-X', laudo_url='/a.pdf', laudo_filename='a.pdf'),
            ExameSolicitado(id=32, bloco=bloco, nome='Ultrassom', laudo_url='/b.pdf', laudo_filename='b.pdf'),
        ])
        db.session.commit()
        assert bloco.laudo_unico is None
        animal_id = animal.id
        vet_id = vet_user.id
    login(monkeypatch, vet_id)

    resp = client.get(f'/animal/{animal_id}/historico_exames')
    assert resp.status_code == 200
    html = resp.get_json()['html']
    assert 'a.pdf' in html and 'b.pdf' in html
    assert 'Laudo completo' not in html
