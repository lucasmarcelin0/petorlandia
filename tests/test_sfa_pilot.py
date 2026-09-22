import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from werkzeug.datastructures import MultiDict
from extensions import db
from models.sfa import (SfaPilotParticipant, SfaPilotResponse, SfaPaciente,
                        SfaRespostaT0, SfaRespostaT7, SfaRespostaT30, SfaInstrumentReview)
from services import sfa_pilot as service


@pytest.fixture
def pilot(app, monkeypatch):
    monkeypatch.setattr(service, 'hoje_local', lambda: date(2025, 1, 6))
    with app.app_context():
        p = service.create_pilot('Piloto fictício QA', date(2025, 1, 2),
            {'pilot_ns1_resultado': 'Negativo', 'pilot_sintomas': ['Febre'], 'name': 'Never retained'}, 'test-pilot-key')
        return p.id, p.token


def test_pilot_registration_is_independent_and_visible(app, client, pilot):
    pid, token = pilot
    with app.app_context():
        p = db.session.get(SfaPilotParticipant, pid)
        assert service.create_pilot('ignored duplicate', None, {}, 'test-pilot-key').id == pid
        assert 'name' not in json.loads(p.context_json)
        assert service.pilot_calendar(p)['first_interview'] is None
        assert len(token) >= 40
        for model in (SfaPaciente, SfaRespostaT0, SfaRespostaT7, SfaRespostaT30):
            assert model.query.count() == 0
    assert b'Piloto fict' in client.get('/sfa/').data
    response = client.get(f'/sfa/pilotos/{pid}')
    assert response.status_code == 200
    assert f'/sfa/piloto/{token}/t0'.encode() in response.data
    assert b'09/01/2025' in response.data
    assert b'01/02/2025' in response.data
    assert b'NS1 negativo isolado' in response.data


@pytest.mark.parametrize('kind', ['t0', 't7', 't30'])
def test_pilot_blank_forms_are_private_and_render(client, pilot, kind):
    _, token = pilot
    r = client.get(f'/sfa/piloto/{token}/{kind}')
    assert r.status_code == 200
    assert r.headers['Cache-Control'] == 'no-store'
    assert r.headers['Referrer-Policy'] == 'no-referrer'
    assert b'aceite_tcle' not in r.data
    assert b'Enviar somente sugest' in r.data
    assert 'primeira entrevista'.encode() in r.data
    if kind == 't0':
        assert b'work_activity' in r.data and b'work_city' in r.data
        assert b'work_address' in r.data and b'work_days' in r.data
        assert b'value="Negativo" checked' in r.data
    assert client.get('/sfa/piloto/not-a-valid-token/t0').status_code == 404


def test_feedback_never_becomes_baseline_or_saves_clinical_answers(app, client, pilot):
    pid, token = pilot
    r = client.post(f'/sfa/piloto/{token}/t7', data={'action': 'feedback', 'pilot_suggestion': 'Pergunta confusa', 'answer__classificacao_melhora': 'Recuperado(a)'})
    assert r.status_code == 200
    with app.app_context():
        assert SfaPilotResponse.query.count() == 0
        payload = json.loads(SfaInstrumentReview.query.one().payload_json)
        assert payload['pilot']['participant_id'] == pid
        assert 'Recuperado' not in json.dumps(payload)
        assert service.pilot_calendar(db.session.get(SfaPilotParticipant, pid))['first_interview'] is None
    assert b'Pergunta confusa' in client.get(f'/sfa/pilotos/{pid}').data


def test_linked_timing_real_interview_and_no_duplicate(app, client, pilot, monkeypatch):
    pid, token = pilot
    assert client.post(f'/sfa/piloto/{token}/t7', data={'action':'answer'}).status_code == 409
    data = MultiDict([('action','answer'), ('answer__data_inicio_sintomas','2025-01-02'),
        ('answer__outras_pessoas_com_sintomas','Sim'), ('answer__outra_exposicao_suspeita','Local QA'),
        ('work_activity','Trabalho'),('work_name','Oficina fictícia'),('work_city','Município QA'),
        ('work_neighborhood','Bairro QA'),('work_address','Referência QA'),('work_days','5'),('work_hours','8'),
        ('work_activity','Estudo'),('work_name','Escola fictícia'),('work_city','Outro município'),
        ('work_neighborhood',''),('work_address',''),('work_days','2'),('work_hours','3'),
        ('pilot_minutes','6')])
    assert client.post(f'/sfa/piloto/{token}/t0',data=data).status_code == 200
    assert client.post(f'/sfa/piloto/{token}/t0',data=data).status_code == 200
    with app.app_context():
        r=SfaPilotResponse.query.one(); payload=json.loads(r.payload_json)
        assert r.interview_date == date(2025,1,6)
        assert payload['pilot']['illness_days']==4
        assert len(payload['pilot']['workplaces'])==2
        assert service.pilot_calendar(db.session.get(SfaPilotParticipant,pid))['stages'][1]['target']==date(2025,1,9)
    assert client.post(f'/sfa/piloto/{token}/t7',data={'action':'answer'}).status_code==409
    monkeypatch.setattr(service,'hoje_local',lambda:date(2025,1,9))
    response=client.get(f'/sfa/piloto/{token}/t7')
    assert b'answer__fonte_ainda_ativa' in response.data
    assert client.post(f'/sfa/piloto/{token}/t7',data={'action':'answer','answer__classificacao_melhora':'Melhorando'}).status_code==200
    monkeypatch.setattr(service,'hoje_local',lambda:date(2025,2,1))
    assert client.post(f'/sfa/piloto/{token}/t30',data={'action':'answer'}).status_code==200
    with app.app_context():
        rows=SfaPilotResponse.query.all()
        assert len(rows)==3
        last=next(r for r in rows if r.stage=='t30')
        assert json.loads(last.payload_json)['pilot']['interval_from']=='2025-01-09'
        assert SfaPaciente.query.count()==0
    assert 'Oficina fictícia'.encode() in client.get(f'/sfa/pilotos/{pid}').data


def test_late_t0_does_not_reset_targets_and_no_t7_fallback(app, client, pilot, monkeypatch):
    pid, token=pilot
    monkeypatch.setattr(service,'hoje_local',lambda:date(2025,1,12))
    assert client.post(f'/sfa/piloto/{token}/t0',data={'action':'answer'}).status_code==200
    with app.app_context():
        c=service.pilot_calendar(db.session.get(SfaPilotParticipant,pid))
        assert c['first_interview']==date(2025,1,12)
        assert c['stages'][1]['target']==date(2025,1,9)
        assert any('após o D7' in f for f in c['flags'])
    monkeypatch.setattr(service,'hoje_local',lambda:date(2025,2,1))
    assert client.post(f'/sfa/piloto/{token}/t30',data={'action':'answer'}).status_code==200
    with app.app_context():
        r=SfaPilotResponse.query.filter_by(stage='t30').one()
        assert json.loads(r.payload_json)['pilot']['interval_from']=='2025-01-12'


def test_admin_and_csrf_boundaries(app, client, pilot, monkeypatch):
    pid, token=pilot
    monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0')
    app.config['TESTING']=False
    assert client.get('/sfa/pilotos').status_code in (302,401,403)
    assert client.get(f'/sfa/pilotos/{pid}').status_code in (302,401,403)
    assert client.get(f'/sfa/piloto/{token}').status_code==200
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post(f'/sfa/piloto/{token}/t0',data={'action':'answer'}).status_code==400


def test_validation_keeps_inputs_and_rolls_back(app, client, pilot):
    _,token=pilot
    r=client.post(f'/sfa/piloto/{token}/t0',data={'action':'answer','pilot_minutes':'nan','answer__pilot_municipio':'Cidade QA'})
    assert r.status_code==400 and b'Cidade QA' in r.data
    with app.app_context():
        assert SfaPilotResponse.query.count()==0


def test_pilot_schema_does_not_modify_municipal_schema(app):
    from services.sfa_service import carregar_t0_form_schema
    original=carregar_t0_form_schema(); before=json.dumps(original,sort_keys=True)
    result=service.pilot_schema('t0',original)
    assert json.dumps(original,sort_keys=True)==before
    assert all(f['key']!='aceite_tcle' for s in result['sections'] for f in s['fields'])


def test_pilot_migration_is_isolated():
    path=Path('migrations/versions/e4b8d5f2a411_sfa_usability_pilot.py')
    spec=importlib.util.spec_from_file_location('pilot_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=sa.create_engine('sqlite://')
    with engine.begin() as conn:
        module.op=Operations(MigrationContext.configure(conn));module.upgrade()
        assert set(sa.inspect(conn).get_table_names())=={'sfa_pilot_participant','sfa_pilot_response'}
        conn.execute(sa.text("INSERT INTO sfa_pilot_participant (id,label,token,creation_key,context_json,created_at) VALUES (1,'QA','token','key','{}','2025-01-01')"))
        with pytest.raises(RuntimeError):module.downgrade()
