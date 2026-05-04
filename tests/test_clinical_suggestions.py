import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

import flask_login.utils as login_utils

from app import app as flask_app, db
from models import (
    Animal,
    AuditoriaSugestaoClinica,
    BlocoPrescricao,
    Clinica,
    Consulta,
    ExameSolicitado,
    Prescricao,
    ProtocoloClinico,
    ProtocoloClinicoExame,
    ProtocoloClinicoMedicamento,
    ProtocoloClinicoRetorno,
    User,
    Veterinario,
)


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def _fake_vet(vet_user_id, vet_id, clinic_id):
    return type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet',
        'is_authenticated': True,
        'veterinario': type('V', (), {
            'id': vet_id,
            'user': type('WU', (), {'name': 'Vet'})(),
            'clinica_id': clinic_id,
        })()
    })()


def test_clinical_suggestions_can_be_loaded_and_applied(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica Segura')
        tutor = User(id=1, name='Tutor', email='tutor-sugestoes@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet-sugestoes@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
            queixa_principal='Tosse persistente',
        )
        protocolo = ProtocoloClinico(
            id=1,
            nome='Protocolo Respiratorio Inicial',
            suspeita_principal='traqueobronquite',
            especie='cao',
            conduta_sugerida='Nebulizacao e repouso com reavaliacao clinica.',
            orientacoes_tutor='Observar frequencia da tosse e piora respiratoria.',
            alertas='Antecipar retorno em caso de piora ou apatia.',
            clinica_id=clinic.id,
            created_by=vet_user.id,
            prioridade=1,
        )
        exame = ProtocoloClinicoExame(
            id=1,
            protocolo=protocolo,
            nome='Radiografia toracica',
            justificativa='Avaliar padrao pulmonar e descartar complicacoes.',
            prioridade=1,
        )
        medicamento = ProtocoloClinicoMedicamento(
            id=1,
            protocolo=protocolo,
            nome_medicamento='Doxiciclina',
            justificativa='Cobertura empirica inicial quando clinicamente indicada.',
            dosagem_texto='5 mg/kg',
            frequencia_texto='a cada 12h',
            duracao_texto='7 dias',
            observacoes='Revisar tolerancia gastrointestinal.',
            prioridade=1,
        )
        retorno = ProtocoloClinicoRetorno(
            id=1,
            protocolo=protocolo,
            prazo_min_dias=3,
            prazo_max_dias=5,
            tipo_retorno='retorno',
            objetivo='Reavaliar resposta clinica e ausculta.',
            gatilhos_antecipacao='Piora da tosse ou prostracao.',
            prioridade=1,
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, protocolo, exame, medicamento, retorno])
        db.session.commit()
        consulta_id = consulta.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id

    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    suggestions_response = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas',
        json={'suspeita_clinica': 'Traqueobronquite'},
    )
    assert suggestions_response.status_code == 200
    suggestions_payload = suggestions_response.get_json()
    assert suggestions_payload['success'] is True
    assert len(suggestions_payload['suggestions']) == 1
    assert suggestions_payload['suggestions'][0]['exames'][0]['nome'] == 'Radiografia toracica'

    exam_apply = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas/aplicar',
        json={'item_type': 'exame', 'protocol_id': 1, 'item_id': 1},
    )
    assert exam_apply.status_code == 200
    assert exam_apply.get_json()['success'] is True

    med_apply = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas/aplicar',
        json={'item_type': 'medicamento', 'protocol_id': 1, 'item_id': 1},
    )
    assert med_apply.status_code == 200
    assert med_apply.get_json()['success'] is True

    conduct_apply = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas/aplicar',
        json={'item_type': 'conduta', 'protocol_id': 1},
    )
    assert conduct_apply.status_code == 200
    conduct_payload = conduct_apply.get_json()
    assert 'Nebulizacao e repouso' in conduct_payload['conduta']

    followup_apply = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas/aplicar',
        json={'item_type': 'retorno', 'protocol_id': 1, 'item_id': 1},
    )
    assert followup_apply.status_code == 200
    followup_payload = followup_apply.get_json()
    assert followup_payload['prefill']['tipo_retorno'] == 'retorno'
    assert followup_payload['prefill']['suggested_date']

    with flask_app.app_context():
        assert ExameSolicitado.query.filter_by(nome='Radiografia toracica').count() == 1
        bloco = BlocoPrescricao.query.one()
        assert bloco.instrucoes_gerais == 'Observar frequencia da tosse e piora respiratoria.'
        prescricao = Prescricao.query.one()
        assert prescricao.medicamento == 'Doxiciclina'
        consulta = Consulta.query.get(consulta_id)
        assert 'Nebulizacao e repouso' in (consulta.conduta or '')
        assert AuditoriaSugestaoClinica.query.filter_by(consulta_id=consulta_id, acao='shown').count() == 1
        assert AuditoriaSugestaoClinica.query.filter_by(consulta_id=consulta_id, acao='accepted').count() == 4


def test_agendar_retorno_registra_auditoria_de_sugestao(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica Retorno')
        tutor = User(id=1, name='Tutor', email='tutor-retorno@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet-retorno@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(id=1, animal_id=animal.id, created_by=vet_user.id, clinica_id=clinic.id, status='finalizada')
        protocolo = ProtocoloClinico(
            id=1,
            nome='Retorno Respiratorio',
            suspeita_principal='traqueobronquite',
            especie='cao',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        )
        retorno = ProtocoloClinicoRetorno(
            id=1,
            protocolo=protocolo,
            prazo_min_dias=4,
            tipo_retorno='retorno',
            objetivo='Reavaliar resposta clinica.',
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, protocolo, retorno])
        db.session.commit()
        consulta_id = consulta.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id

    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    response = client.post(
        f'/agendar_retorno/{consulta_id}',
        data={
            'animal_id': 1,
            'veterinario_id': vet_id,
            'date': '2026-05-10',
            'time': '10:00',
            'reason': 'Reavaliar resposta clinica.',
            'suggested_protocol_id': 1,
            'suggested_return_id': 1,
        }
    )
    assert response.status_code == 302

    with flask_app.app_context():
        assert AuditoriaSugestaoClinica.query.filter_by(
            consulta_id=consulta_id,
            acao='scheduled',
            tipo_item='retorno',
        ).count() == 1
