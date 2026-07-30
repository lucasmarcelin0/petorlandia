import flask_login.utils as login_utils
from flask import render_template
from types import SimpleNamespace

from extensions import db
from models import (
    Animal,
    AuditoriaSugestaoClinica,
    Clinica,
    Consulta,
    PropostaProtocoloClinico,
    ProtocoloClinico,
    User,
    Veterinario,
)


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def _fake_vet(user_id, vet_id, clinic_id):
    return type('U', (), {
        'id': user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet Revisor',
        'is_authenticated': True,
        'veterinario': type('V', (), {
            'id': vet_id,
            'user': type('WU', (), {'name': 'Vet Revisor'})(),
            'clinica_id': clinic_id,
        })(),
    })()


def _seed_consultation(app):
    with app.app_context():
        clinic = Clinica(nome='Clínica das Propostas')
        tutor = User(name='Tutor', email='tutor-proposta@test')
        tutor.set_password('x')
        vet_user = User(
            name='Vet Revisor',
            email='vet-proposta@test',
            worker='veterinario',
        )
        vet_user.set_password('x')
        db.session.add_all([clinic, tutor, vet_user])
        db.session.flush()
        vet = Veterinario(
            user_id=vet_user.id,
            crmv='12345',
            clinica_id=clinic.id,
        )
        animal = Animal(
            name='Animal Teste',
            user_id=tutor.id,
            clinica_id=clinic.id,
        )
        db.session.add_all([vet, animal])
        db.session.flush()
        consultation = Consulta(
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
        )
        db.session.add(consultation)
        db.session.commit()
        return consultation.id, clinic.id, vet_user.id, vet.id


def test_free_text_protocol_proposal_stays_pending_and_does_not_publish(
    app,
    client,
    monkeypatch,
):
    consultation_id, clinic_id, user_id, vet_id = _seed_consultation(app)
    _login(monkeypatch, _fake_vet(user_id, vet_id, clinic_id))

    response = client.post(
        f'/consulta/{consultation_id}/sugestoes_clinicas/propostas',
        json={
            'titulo': 'Abordagem inicial do prurido',
            'categoria': 'sintoma',
            'especie': 'cao',
            'conteudo_livre': (
                'Em cães com prurido recente, avaliar ectoparasitas, distribuição '
                'das lesões, citologia e necessidade de controle do desconforto.'
            ),
            'referencias': 'Diretriz clínica informada pelo autor.',
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['proposal']['status'] == 'pending_review'
    assert payload['proposal']['categoria_label'] == 'Sintoma ou sinal clínico'

    with app.app_context():
        proposal = PropostaProtocoloClinico.query.one()
        assert proposal.clinica_id == clinic_id
        assert proposal.consulta_id == consultation_id
        assert proposal.created_by == user_id
        assert proposal.status == 'pending_review'
        assert ProtocoloClinico.query.count() == 0
        audit = AuditoriaSugestaoClinica.query.filter_by(
            tipo_item='protocol_proposal',
            acao='created',
        ).one()
        assert audit.payload['proposal_id'] == proposal.id


def test_protocol_proposal_accepts_short_meaningful_free_text(
    app,
    client,
    monkeypatch,
):
    consultation_id, clinic_id, user_id, vet_id = _seed_consultation(app)
    _login(monkeypatch, _fake_vet(user_id, vet_id, clinic_id))

    response = client.post(
        f'/consulta/{consultation_id}/sugestoes_clinicas/propostas',
        json={
            'titulo': 'Prurido',
            'categoria': 'sintoma',
            'conteudo_livre': 'Avaliar.',
        },
    )

    assert response.status_code == 200
    with app.app_context():
        assert PropostaProtocoloClinico.query.one().conteudo_livre == 'Avaliar.'


def test_protocol_proposal_rejects_blank_free_text(
    app,
    client,
    monkeypatch,
):
    consultation_id, clinic_id, user_id, vet_id = _seed_consultation(app)
    _login(monkeypatch, _fake_vet(user_id, vet_id, clinic_id))

    response = client.post(
        f'/consulta/{consultation_id}/sugestoes_clinicas/propostas',
        json={
            'titulo': 'Prurido',
            'categoria': 'sintoma',
            'conteudo_livre': '   ',
        },
    )

    assert response.status_code == 400
    assert 'pelo menos 5 caracteres' in response.get_json()['message']
    with app.app_context():
        assert PropostaProtocoloClinico.query.count() == 0


def test_protocol_proposal_queue_is_scoped_to_consultation_clinic(
    app,
    client,
    monkeypatch,
):
    consultation_id, clinic_id, user_id, vet_id = _seed_consultation(app)
    with app.app_context():
        other_clinic = Clinica(nome='Outra Clínica')
        db.session.add(other_clinic)
        db.session.flush()
        db.session.add_all([
            PropostaProtocoloClinico(
                clinica_id=clinic_id,
                created_by=user_id,
                titulo='Proposta visível',
                categoria='doenca',
                conteudo_livre='Conteúdo clínico suficientemente detalhado para revisão interna.',
            ),
            PropostaProtocoloClinico(
                clinica_id=other_clinic.id,
                titulo='Proposta de outra clínica',
                categoria='doenca',
                conteudo_livre='Este conteúdo não pode aparecer para a clínica consultada.',
            ),
        ])
        db.session.commit()

    _login(monkeypatch, _fake_vet(user_id, vet_id, clinic_id))
    response = client.get(
        f'/consulta/{consultation_id}/sugestoes_clinicas/propostas',
    )

    assert response.status_code == 200
    proposals = response.get_json()['proposals']
    assert [item['titulo'] for item in proposals] == ['Proposta visível']


def test_clinical_panel_renders_free_text_proposal_experience(app):
    with app.test_request_context('/consulta/1'):
        html = render_template(
            'partials/clinical_suggestions_panel.html',
            consulta=SimpleNamespace(id=1),
            clinical_suspicion_options=[],
        )

    assert 'data-clinical-mode="proposal"' in html
    assert 'Conte sua ideia livremente' in html
    assert 'Enviar para revisão' in html
    assert 'data-proposal-url="/consulta/1/sugestoes_clinicas/propostas"' in html
    assert 'A proposta não será' in html
