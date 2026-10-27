"""Envio incompleto não apaga o cadastro do animal ("None" no prontuário).

Quando o upload da foto cai no meio, o Werkzeug descarta o multipart em
silêncio e ``request.form`` chega vazio. Como o token CSRF vai no cabeçalho
(csrf_fetch.js), a requisição passava e ``update_animal`` gravava nome, sexo e
peso como vazios — o cabeçalho da consulta exibia "None".
"""

import importlib.util
import os
import sys
from pathlib import Path

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest  # noqa: E402

from app import app as flask_app, db  # noqa: E402
from models import Animal, User  # noqa: E402
from test_intern_start_consulta import _build_clinic, client, login  # noqa: E402,F401

JSON = {'Accept': 'application/json'}


def _preparar(monkeypatch):
    _build_clinic()
    animal = db.session.get(Animal, 1)
    animal.sex = 'Macho'
    animal.peso = 12.5
    animal.description = 'Dócil'
    db.session.commit()
    login(monkeypatch, db.session.get(User, 2))


def _recarregar():
    db.session.expire_all()
    return db.session.get(Animal, 1)


def test_upload_interrompido_nao_apaga_o_cadastro(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        boundary = 'XyZ'
        corpo = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\nRex\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="f.jpg"\r\n'
            'Content-Type: image/jpeg\r\n\r\n'
        ).encode() + b'\xff' * 5000  # corpo cortado no meio da foto

        resp = client.post(
            '/update_animal/1',
            data=corpo,
            content_type=f'multipart/form-data; boundary={boundary}',
            headers=JSON,
        )

        assert resp.status_code == 400
        payload = resp.get_json()
        assert payload['success'] is False
        # Barrado antes da rota pela proteção global (security/form_body.py).
        assert payload['error'] == 'incomplete_body'
        assert 'incompleto' in payload['message']
        animal = _recarregar()
        assert animal.name == 'Rex'
        assert animal.sex == 'Macho'
        assert animal.peso == 12.5
        assert animal.description == 'Dócil'


def test_envio_sem_campo_nome_nao_altera_nada(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post('/update_animal/1', data={'sex': 'Fêmea'}, headers=JSON)
        assert resp.status_code == 400
        animal = _recarregar()
        assert animal.name == 'Rex'
        assert animal.sex == 'Macho'


def test_nome_em_branco_e_recusado(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post('/update_animal/1', data={'name': '   ', 'sex': 'Fêmea'}, headers=JSON)
        assert resp.status_code == 400
        assert 'nome' in resp.get_json()['message'].lower()
        animal = _recarregar()
        assert animal.name == 'Rex'
        assert animal.sex == 'Macho'


def test_salvamento_normal_continua_funcionando(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post(
            '/update_animal/1',
            data={'name': '  Bidu ', 'sex': 'Fêmea', 'peso': '8', 'description': 'Nova'},
            headers=JSON,
        )
        assert resp.status_code == 200
        assert resp.get_json()['animal_name'] == 'Bidu'
        animal = _recarregar()
        assert animal.name == 'Bidu'
        assert animal.sex == 'Fêmea'
        assert animal.peso == 8.0


def test_cabecalho_da_consulta_nao_exibe_none(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        db.session.execute(db.text("UPDATE animal SET name = NULL WHERE id = 1"))
        db.session.commit()
        resp = client.get('/consulta/1', headers={'Accept': 'text/html'})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        cabecalho = html[html.index('id="animal-name"'):][:300]
        assert 'Sem nome' in cabecalho
        assert 'None' not in cabecalho


def _carregar_migracao():
    caminho = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / 'c7e1a9b3d5f2_restaurar_nome_animal_vazio.py'
    spec = importlib.util.spec_from_file_location('mig_restaurar_nome', caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_migracao_restaura_nome_pela_campanha_sem_tocar_nomes_existentes(client):
    from models import PmoVaccinationAnimal, PmoVaccinationVisit

    with flask_app.app_context():
        tutor = User(id=10, name='Rosilda', email='r@test', worker='adotante')
        tutor.set_password('x')
        sem_nome = Animal(id=10, name='Temp', user_id=10)
        com_nome = Animal(id=11, name='Luna', user_id=10)
        sem_vinculo = Animal(id=12, name='Temp', user_id=10)
        db.session.add_all([tutor, sem_nome, com_nome, sem_vinculo])
        db.session.flush()
        visita = PmoVaccinationVisit(tutor_name='Rosilda', sheet_title='aba', sheet_gid='1', password='x', spreadsheet_id='s', source_row=2)
        db.session.add(visita)
        db.session.flush()
        db.session.add_all([
            PmoVaccinationAnimal(visit=visita, position=1, name='Pretinha', species='cao', animal_id=10),
            PmoVaccinationAnimal(visit=visita, position=2, name='Outro', species='cao', animal_id=11),
        ])
        db.session.commit()
        db.session.execute(db.text("UPDATE animal SET name = NULL WHERE id IN (10, 12)"))
        db.session.commit()

        migracao = _carregar_migracao()
        with db.engine.begin() as conn:
            for tabela in ('pmo_vaccination_animal', 'pmo_castration_animal'):
                migracao._restaurar_de(conn, tabela)

        db.session.expire_all()
        assert db.session.get(Animal, 10).name == 'Pretinha'
        assert db.session.get(Animal, 11).name == 'Luna'
        assert db.session.get(Animal, 12).name is None
