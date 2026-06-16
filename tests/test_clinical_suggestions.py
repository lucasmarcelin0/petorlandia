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
    Medicamento,
    Prescricao,
    PrescricaoAliasMedicamento,
    ProtocoloClinico,
    ProtocoloClinicoExame,
    ProtocoloClinicoMedicamento,
    ProtocoloClinicoRetorno,
    User,
    Veterinario,
)
from services.bulario import sugerir_dose
from services.clinical_suggestions import recommend_protocols
from scripts.seed_protocolos_notas import seed as seed_protocolos_notas
from types import SimpleNamespace


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
        medicamento_canonico = Medicamento(
            id=10,
            nome='Doxiciclina',
            classificacao='Antibacteriano',
            created_by=vet_user.id,
        )
        db.session.add_all([
            clinic,
            tutor,
            vet_user,
            vet,
            animal,
            consulta,
            protocolo,
            exame,
            medicamento,
            retorno,
            medicamento_canonico,
        ])
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
    med_payload = med_apply.get_json()
    assert med_payload['success'] is True
    assert med_payload['draft_prescription']['medicamento_id'] == 10
    assert med_payload['draft_prescription']['medicamento'] == 'Doxiciclina'
    assert med_payload['draft_prescription']['use_weight_based_dose'] is False
    assert med_payload['draft_instructions'] == 'Observar frequencia da tosse e piora respiratoria.'

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
        assert BlocoPrescricao.query.count() == 0
        assert Prescricao.query.count() == 0
        assert PrescricaoAliasMedicamento.query.filter_by(
            nome_prescrito='Doxiciclina',
            medicamento_id=10,
        ).count() == 1
        consulta = Consulta.query.get(consulta_id)
        assert 'Nebulizacao e repouso' in (consulta.conduta or '')
        assert AuditoriaSugestaoClinica.query.filter_by(consulta_id=consulta_id, acao='shown').count() == 1
        assert AuditoriaSugestaoClinica.query.filter_by(consulta_id=consulta_id, acao='accepted').count() == 4


def test_sugerir_dose_resolve_indicacao_aproximada_por_semantica():
    medicamento = SimpleNamespace(
        id=1,
        nome='Meloxicam',
        classificacao='Anti-inflamatorio',
        doses=[
            SimpleNamespace(
                id=1,
                especie='Caes',
                especie_code='CAES',
                via='Oral',
                dose='0,1 mg/kg',
                dose_min=0.1,
                dose_max=0.1,
                dose_unidade='MG_KG',
                peso_min_kg=None,
                peso_max_kg=None,
                intervalo_horas=24,
                intervalo_min_horas=None,
                intervalo_max_horas=None,
                duracao_min_dias=3,
                duracao_max_dias=5,
                indicacao='Controle da dor',
                observacao=None,
                fonte='HUMANO',
                confianca='ALTA',
            ),
            SimpleNamespace(
                id=2,
                especie='Caes',
                especie_code='CAES',
                via='Oral',
                dose='0,2 mg/kg',
                dose_min=0.2,
                dose_max=0.2,
                dose_unidade='MG_KG',
                peso_min_kg=None,
                peso_max_kg=None,
                intervalo_horas=24,
                intervalo_min_horas=None,
                intervalo_max_horas=None,
                duracao_min_dias=7,
                duracao_max_dias=10,
                indicacao='Inflamacao articular',
                observacao=None,
                fonte='HUMANO',
                confianca='ALTA',
            ),
        ],
        apresentacoes=[],
    )
    animal = SimpleNamespace(
        peso=12,
        species=SimpleNamespace(name='Cachorro'),
    )

    sugestao = sugerir_dose(medicamento, animal, indicacao='Analgesia')

    assert sugestao is not None
    assert sugestao['multiplo'] is False
    assert sugestao['indicacao'] == 'Controle da dor'


def test_sugerir_dose_capstar_por_faixa_de_peso():
    medicamento = SimpleNamespace(
        id=36,
        nome='Capstar - Caes e gatos 11,4 mg, comprimido (1 un)',
        classificacao='Ectoparasiticida',
        via_administracao='Oral',
        doses=[
            SimpleNamespace(
                id=1,
                especie='Caes e Gatos',
                especie_code='AMBOS',
                via='Oral',
                dose='1 comprimido / animal (11,4 mg)',
                dose_min=1,
                dose_max=1,
                dose_unidade='COMPRIMIDOS_ANIMAL',
                peso_min_kg=None,
                peso_max_kg=11.4,
                intervalo_horas=24,
                intervalo_min_horas=24,
                intervalo_max_horas=24,
                duracao_min_dias=1,
                duracao_max_dias=1,
                indicacao='Controle de pulgas e miiase',
                observacao='Pode repetir a cada 24 horas.',
                frequencia='Dose unica',
                duracao='Dose unica',
                fonte='HUMANO',
                confianca='ALTA',
            ),
            SimpleNamespace(
                id=2,
                especie='Caes',
                especie_code='CAES',
                via='Oral',
                dose='1 comprimido / animal (57 mg)',
                dose_min=1,
                dose_max=1,
                dose_unidade='COMPRIMIDOS_ANIMAL',
                peso_min_kg=11.41,
                peso_max_kg=57.0,
                intervalo_horas=24,
                intervalo_min_horas=24,
                intervalo_max_horas=24,
                duracao_min_dias=1,
                duracao_max_dias=1,
                indicacao='Controle de pulgas e miiase',
                observacao='Pode repetir a cada 24 horas.',
                frequencia='Dose unica',
                duracao='Dose unica',
                fonte='HUMANO',
                confianca='ALTA',
            ),
        ],
        apresentacoes=[],
    )
    gato = SimpleNamespace(
        peso=4.5,
        species=SimpleNamespace(name='Gato'),
    )
    cao = SimpleNamespace(
        peso=22,
        species=SimpleNamespace(name='Cachorro'),
    )

    sugestao_gato = sugerir_dose(medicamento, gato, indicacao='Controle parasitario')
    sugestao_cao = sugerir_dose(medicamento, cao, indicacao='Controle parasitario')

    assert sugestao_gato is not None
    assert sugestao_gato['dose_exibir'] == '1 comprimido(s)'
    assert sugestao_gato['faixa_texto'] == '1 cp/animal'
    assert sugestao_cao is not None
    assert sugestao_cao['dose_exibir'] == '1 comprimido(s)'
    assert sugestao_cao['protocolo_id'] == 2


def test_sugerir_dose_sulfadiazina_topica_exibe_frequencia_correta():
    medicamento = SimpleNamespace(
        id=5928,
        nome='Sulfadiazina de Prata',
        classificacao='Dermatologico',
        via_administracao='Topica',
        doses=[
            SimpleNamespace(
                id=1,
                especie='Caes e Gatos',
                especie_code='AMBOS',
                via='Topica',
                dose='Aplicar fina camada sobre a regiao acometida',
                dose_min=1,
                dose_max=1,
                dose_unidade='CAMADA_TOPICA',
                peso_min_kg=None,
                peso_max_kg=None,
                intervalo_horas=12,
                intervalo_min_horas=8,
                intervalo_max_horas=12,
                duracao_min_dias=None,
                duracao_max_dias=None,
                indicacao='Uso topico em lesao',
                observacao='Aplicar fina camada na lesao.',
                frequencia='A cada 12 horas',
                duracao='Conforme evolucao da lesao',
                fonte='HUMANO',
                confianca='ALTA',
            ),
        ],
        apresentacoes=[],
    )
    animal = SimpleNamespace(
        peso=18,
        species=SimpleNamespace(name='Cachorro'),
    )

    sugestao = sugerir_dose(medicamento, animal, indicacao='Uso topico')

    assert sugestao is not None
    assert sugestao['dose_exibir'] == '1 camada fina'
    assert sugestao['frequencia_texto'] == 'a cada 8–12h'
    assert sugestao['via'] == 'Topica'


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


def test_bicheira_protocol_returns_requested_conduct_and_medications(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica Bicheira')
        tutor = User(id=1, name='Tutor', email='tutor-bicheira@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet-bicheira@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
            queixa_principal='Ferida com larvas e odor forte.',
        )
        protocolo = ProtocoloClinico(
            id=1,
            nome='Protocolo Inicial para Bicheira',
            suspeita_principal='bicheira',
            sinais_gatilho='Miíase cutânea, presença de larvas, ferida contaminada, odor fétido.',
            conduta_sugerida='Realizar retirada manual das larvas de moscas e limpeza criteriosa da lesão antes de definir a conduta complementar.',
            clinica_id=None,
            prioridade=2,
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, protocolo])
        db.session.flush()
        db.session.add_all([
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Cefalexina',
                justificativa='Antibioticoterapia de suporte para ferida infestada, conforme avaliação clínica.',
                frequencia_texto='a cada 12 horas',
                duracao_texto='por 10 dias',
                prioridade=1,
            ),
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Capstar',
                justificativa='Controle complementar de ectoparasitas quando clinicamente indicado.',
                frequencia_texto='Dose unica',
                duracao_texto='Dose unica',
                prioridade=2,
            ),
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Meloxicam',
                justificativa='Controle de dor e inflamação conforme avaliação clínica.',
                frequencia_texto='a cada 24 horas',
                duracao_texto='por 5 dias',
                prioridade=3,
            ),
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Pomada de sulfadiazina de prata',
                justificativa='Cuidado tópico complementar da lesão após limpeza e manejo inicial.',
                frequencia_texto='a cada 12 horas',
                duracao_texto='por 10 dias',
                prioridade=4,
            ),
        ])
        db.session.commit()
        consulta_id = consulta.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id

    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    response = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas',
        json={'suspeita_clinica': 'bicheira'},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert len(payload['suggestions']) == 1

    suggestion = payload['suggestions'][0]
    assert 'retirada manual das larvas' in suggestion['conduta_sugerida'].lower()
    assert [item['nome'] for item in suggestion['medicamentos']] == [
        'Cefalexina',
        'Capstar',
        'Meloxicam',
        'Pomada de sulfadiazina de prata',
    ]
    assert [(item['frequencia'], item['duracao']) for item in suggestion['medicamentos']] == [
        ('a cada 12 horas', 'por 10 dias'),
        ('Dose unica', 'Dose unica'),
        ('a cada 24 horas', 'por 5 dias'),
        ('a cada 12 horas', 'por 10 dias'),
    ]


def test_dermatitis_protocol_returns_requested_medications(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica Dermatologia')
        tutor = User(id=1, name='Tutor', email='tutor-dermatite@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet-dermatite@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
            queixa_principal='Muita coceira, pele vermelha e falhas no pelo.',
        )
        protocolo = ProtocoloClinico(
            id=1,
            nome='Protocolo Inicial para Dermatites',
            suspeita_principal='dermatite',
            especie='cao',
            sinais_gatilho='Prurido, coceira, eritema, alopecia, descamacao, crostas, lesoes cutaneas.',
            conduta_sugerida='Avaliar distribuicao das lesoes, intensidade do prurido e ectoparasitas.',
            alertas='Prednisona deve ser usada apenas apos avaliacao do medico-veterinario.',
            clinica_id=None,
            prioridade=3,
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, protocolo])
        db.session.flush()
        db.session.add_all([
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Shampoo de clorexidina - 0,20%, frasco (500mL)',
                justificativa='Higienizacao e apoio topico em dermatites.',
                dosagem_texto='Aplicar sobre a pelagem umedecida, massagear e deixar agir por 5 a 10 minutos; enxaguar bem e repetir o processo uma vez.',
                frequencia_texto='1 vez por semana',
                duracao_texto='3 meses',
                prioridade=1,
            ),
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g + Sulfato de Neomicina 2,5mg/g Generico C',
                justificativa='Uso topico em lesoes localizadas quando houver indicacao clinica.',
                dosagem_texto='Aplicar uma camada fina sobre a area afetada',
                frequencia_texto='2 vezes ao dia',
                duracao_texto='10 dias',
                prioridade=2,
            ),
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Simparic',
                justificativa='Controle de ectoparasitas conforme peso do animal quando indicado.',
                frequencia_texto='a cada 30 dias',
                duracao_texto='conforme protocolo',
                prioridade=3,
            ),
            ProtocoloClinicoMedicamento(
                protocolo=protocolo,
                nome_medicamento='Prednisona',
                justificativa='Controle de prurido/inflamacao quando indicado.',
                dosagem_texto='',
                frequencia_texto='',
                duracao_texto='5 dias',
                indicacao='Alergia',
                prioridade=4,
            ),
        ])
        db.session.commit()
        consulta_id = consulta.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id

    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    response = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas',
        json={'suspeita_clinica': 'dermatite alergica com coceira'},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert len(payload['suggestions']) == 1

    suggestion = payload['suggestions'][0]
    assert 'prednisona' in suggestion['alertas'].lower()
    assert [item['nome'] for item in suggestion['medicamentos']] == [
        'Shampoo de clorexidina - 0,20%, frasco (500mL)',
        'Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g + Sulfato de Neomicina 2,5mg/g Generico C',
        'Simparic',
        'Prednisona',
    ]
    assert suggestion['medicamentos'][0]['dosagem'] == 'Aplicar sobre a pelagem umedecida, massagear e deixar agir por 5 a 10 minutos; enxaguar bem e repetir o processo uma vez.'
    assert suggestion['medicamentos'][0]['frequencia'] == '1 vez por semana'
    assert suggestion['medicamentos'][0]['duracao'] == '3 meses'
    assert suggestion['medicamentos'][1]['dosagem'] == 'Aplicar uma camada fina sobre a area afetada'
    assert suggestion['medicamentos'][1]['frequencia'] == '2 vezes ao dia'
    assert suggestion['medicamentos'][1]['duracao'] == '10 dias'
    assert suggestion['medicamentos'][2]['dosagem'] in ('', None)
    assert suggestion['medicamentos'][3]['indicacao'] == 'Alergia'
    assert suggestion['medicamentos'][3]['duracao'] == '5 dias'


def test_inline_protocol_creation_creates_clinic_protocol_and_updates_suspicion_options(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica Protocolos')
        tutor = User(id=1, name='Tutor', email='tutor-protocolos@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet-protocolos@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Luna', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta])
        db.session.commit()
        consulta_id = consulta.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id

    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    response = client.post(
        f'/consulta/{consulta_id}/sugestoes_clinicas/protocolos',
        json={
            'nome': 'Protocolo Dermatologico Essencial',
            'suspeita_principal': 'dermatite',
            'especie': 'cao',
            'prioridade': 20,
            'conduta_sugerida': 'Inspecionar pele, remover irritantes e reavaliar resposta clínica.',
            'sinais_gatilho': 'prurido, eritema, descamação',
            'exames': [
                {'nome': 'Citologia cutânea', 'justificativa': 'Pesquisar infecção secundária.'},
            ],
            'medicamentos': [
                {
                    'nome_medicamento': 'Cefalexina',
                    'indicacao': 'Suporte infeccioso',
                    'frequencia_texto': 'a cada 12 horas',
                    'duracao_texto': 'por 10 dias',
                },
            ],
            'retorno': {
                'prazo_min_dias': 7,
                'tipo_retorno': 'retorno',
                'objetivo': 'Reavaliar resposta cutânea.',
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert 'dermatite' in payload['clinical_suspicion_options']

    with flask_app.app_context():
        protocolo = ProtocoloClinico.query.filter_by(
            nome='Protocolo Dermatologico Essencial',
            clinica_id=clinic_id,
        ).first()
        assert protocolo is not None
        assert protocolo.suspeita_principal == 'dermatite'
        assert len(protocolo.exames_sugeridos) == 1
        assert len(protocolo.medicamentos_sugeridos) == 1
        assert len(protocolo.retornos_sugeridos) == 1


def test_inline_protocol_can_be_loaded_and_updated(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica Edicao Protocolos')
        tutor = User(id=1, name='Tutor', email='tutor-edicao-protocolos@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet-edicao-protocolos@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Luna', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
        )
        protocolo = ProtocoloClinico(
            id=1,
            nome='Dermatite Inicial',
            suspeita_principal='dermatite',
            especie='cao',
            prioridade=10,
            conduta_sugerida='Avaliar pele e ectoparasitas.',
            sinais_gatilho='prurido, alopecia',
            orientacoes_tutor='Retornar se piorar.',
            alertas='Usar corticoide com cautela.',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        )
        protocolo.exames_sugeridos.append(
            ProtocoloClinicoExame(
                nome='Citologia cutanea',
                justificativa='Pesquisar infeccao secundaria.',
                prioridade=1,
            )
        )
        protocolo.medicamentos_sugeridos.append(
            ProtocoloClinicoMedicamento(
                nome_medicamento='Prednisona',
                indicacao='Alergia',
                duracao_texto='5 dias',
                prioridade=1,
            )
        )
        protocolo.retornos_sugeridos.append(
            ProtocoloClinicoRetorno(
                prazo_min_dias=5,
                tipo_retorno='retorno',
                objetivo='Reavaliar prurido.',
                prioridade=1,
            )
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, protocolo])
        db.session.commit()
        consulta_id = consulta.id
        protocolo_id = protocolo.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id

    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    get_response = client.get(
        f'/consulta/{consulta_id}/sugestoes_clinicas/protocolos/{protocolo_id}',
    )
    assert get_response.status_code == 200
    get_payload = get_response.get_json()
    assert get_payload['success'] is True
    assert get_payload['protocol']['nome'] == 'Dermatite Inicial'
    assert get_payload['protocol']['medicamentos'][0]['nome_medicamento'] == 'Prednisona'

    update_response = client.put(
        f'/consulta/{consulta_id}/sugestoes_clinicas/protocolos/{protocolo_id}',
        json={
            'nome': 'Dermatite Atualizada',
            'suspeita_principal': 'dermatite alergica',
            'especie': 'cao',
            'prioridade': 5,
            'conduta_sugerida': 'Avaliar pele, dieta e ectoparasitas.',
            'sinais_gatilho': 'prurido, eritema',
            'orientacoes_tutor': 'Manter acompanhamento semanal.',
            'alertas': 'Evitar automedicacao.',
            'exames': [
                {'nome': 'Citologia cutanea', 'justificativa': 'Pesquisar infeccao secundaria.'},
            ],
            'medicamentos': [
                {
                    'nome_medicamento': 'Prednisona',
                    'indicacao': 'Alergia',
                    'duracao_texto': '5 dias',
                },
                {
                    'nome_medicamento': 'Simparic',
                    'indicacao': 'Controle de ectoparasitas',
                    'frequencia_texto': 'a cada 30 dias',
                },
            ],
            'retorno': {
                'prazo_min_dias': 7,
                'tipo_retorno': 'retorno',
                'objetivo': 'Reavaliar resposta cutanea.',
            },
        },
    )
    assert update_response.status_code == 200
    update_payload = update_response.get_json()
    assert update_payload['success'] is True
    assert update_payload['protocol']['nome'] == 'Dermatite Atualizada'

    with flask_app.app_context():
        protocolo = ProtocoloClinico.query.get(protocolo_id)
        assert protocolo.nome == 'Dermatite Atualizada'
        assert protocolo.suspeita_principal == 'dermatite alergica'
        assert protocolo.prioridade == 5
        assert len(protocolo.medicamentos_sugeridos) == 2
        assert protocolo.retornos_sugeridos[0].prazo_min_dias == 7


def test_inline_global_protocol_can_be_loaded_as_clone_base(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica Base Global')
        tutor = User(id=1, name='Tutor', email='tutor-protocolo-global@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet-protocolo-global@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Luna', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
        )
        protocolo = ProtocoloClinico(
            id=1,
            nome='Dermatite Padrao',
            suspeita_principal='dermatite',
            especie='cao',
            prioridade=10,
            conduta_sugerida='Avaliar pele e prurido.',
            sinais_gatilho='prurido',
            created_by=vet_user.id,
        )
        protocolo.medicamentos_sugeridos.append(
            ProtocoloClinicoMedicamento(
                nome_medicamento='Prednisona',
                indicacao='Alergia',
                duracao_texto='5 dias',
                prioridade=1,
            )
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, protocolo])
        db.session.commit()
        consulta_id = consulta.id
        protocolo_id = protocolo.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id


    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    response = client.get(
        f'/consulta/{consulta_id}/sugestoes_clinicas/protocolos/{protocolo_id}',
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['edit_mode'] == 'clone'
    assert payload['protocol']['nome'] == 'Dermatite Padrao'
    assert payload['protocol']['clinica_id'] is None


def test_seeded_mastitis_pseudocyesis_protocol_is_created_and_searchable(app):
    with flask_app.app_context():
        result = seed_protocolos_notas(
            db.session,
            apply=True,
            only_names=['Mastite / Pseudociese em cadelas'],
        )
        assert result['created'] == ['Mastite / Pseudociese em cadelas'] or result['skipped'] == ['Mastite / Pseudociese em cadelas']

        protocolo = ProtocoloClinico.query.filter_by(
            nome='Mastite / Pseudociese em cadelas',
            clinica_id=None,
        ).first()
        assert protocolo is not None
        assert protocolo.especie == 'cao'
        assert [item.nome_exibicao for item in protocolo.medicamentos_sugeridos] == [
            'Sec Lac',
            'Cefalexina',
            'Meloxicam',
        ]
        assert protocolo.retornos_sugeridos[0].tipo_retorno == 'reavaliacao'

        suggestions = recommend_protocols(
            {
                'suspeita_clinica': 'pseudociese',
                'queixa_principal': 'cadela com leite e mamas doloridas',
                'historico_clinico': 'comportamento maternal e aumento mamario',
                'exame_fisico': 'mamas quentes e doloridas',
                'especie': 'cao',
                'clinica_id': None,
            },
            clinic_id=None,
        )

        assert suggestions
        assert suggestions[0]['nome'] == 'Mastite / Pseudociese em cadelas'
        assert [item['nome'] for item in suggestions[0]['medicamentos']] == [
            'Sec Lac',
            'Cefalexina',
            'Meloxicam',
        ]


def test_seed_protocolos_notas_idempotente_e_recomendavel(client):
    from scripts.seed_protocolos_notas import PROTOCOLS, seed
    from services.clinical_suggestions import recommend_protocols

    with flask_app.app_context():
        result = seed(db.session, apply=True)
        assert sorted(result["created"]) == sorted(p["nome"] for p in PROTOCOLS)

        # Segunda execucao nao duplica nada.
        again = seed(db.session, apply=True)
        assert again["created"] == []
        assert sorted(again["skipped"]) == sorted(p["nome"] for p in PROTOCOLS)

        # O motor de sugestao encontra o protocolo pela suspeita.
        suggestions = recommend_protocols({"suspeita_clinica": "fratura", "especie": "cao"})
        assert suggestions
        top = suggestions[0]
        assert top["nome"] == "Fratura / Trauma ortopédico"
        med_names = [m["nome"] for m in top["medicamentos"]]
        assert "Metadona" in med_names and "Meloxicam" in med_names
        assert any(e["nome"] == "Raio-X" for e in top["exames"])

        # Protocolo felino nao aparece para cao.
        feline = recommend_protocols({"suspeita_clinica": "obstrucao uretral", "especie": "cao"})
        assert all(item["nome"] != "Obstrução urinária felina" for item in feline)
        feline_ok = recommend_protocols({"suspeita_clinica": "obstrucao uretral", "especie": "gato"})
        assert feline_ok and feline_ok[0]["nome"] == "Obstrução urinária felina"
