"""Configuração inicial da clínica: cada formulário do painel faz só o seu papel.

O painel da clínica reúne equipe, convite de veterinário, dados e horários na
mesma página, e esses formulários dividem os nomes ``submit`` e ``email``.
"""
from unittest.mock import MagicMock

import pytest
from flask import url_for

from extensions import db
from models import ClinicHours, ClinicStaff, Clinica, User, Veterinario, VetClinicInvite
from template_filters import primeiro_nome


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


@pytest.fixture
def cenario(app, monkeypatch):
    """Clínica da Ana e um veterinário que já trabalha em outra clínica."""
    monkeypatch.setattr('app.mail.send', MagicMock())
    owner = User(name='Dra. Ana Dona', email='ana@clinica.example.com', password_hash='x', worker='veterinario')
    clinica = Clinica(nome='Clínica da Ana', owner=owner)
    outra = Clinica(nome='Outra Clínica')
    vet_user = User(name='Dr. Bruno', email='bruno@outra.example.com', password_hash='x', worker='veterinario')
    db.session.add_all([owner, clinica, outra, vet_user])
    db.session.flush()
    Veterinario(user=owner, crmv='111', clinica=clinica)
    vet = Veterinario(user=vet_user, crmv='222', clinica=outra)
    vet_user.clinica_id = outra.id
    owner.clinica_id = clinica.id
    db.session.add(vet)
    db.session.commit()
    return {
        'owner_id': owner.id,
        'clinica_id': clinica.id,
        'outra_id': outra.id,
        'vet_id': vet.id,
        'vet_user_id': vet_user.id,
    }


def _staff_ids(clinica_id):
    return {s.user_id for s in ClinicStaff.query.filter_by(clinic_id=clinica_id).all()}


@pytest.mark.parametrize('marcador', [True, False], ids=['com-marcador', 'pagina-antiga'])
def test_convidar_veterinario_cria_convite_sem_transferir(app, client, cenario, marcador):
    _login(client, cenario['owner_id'])
    data = {'email': 'bruno@outra.example.com', 'submit': 'Convidar'}
    if marcador:
        data['clinic_form_name'] = 'invite_vet'

    resp = client.post(f"/clinica/{cenario['clinica_id']}", data=data)

    assert resp.status_code == 302
    vet = db.session.get(Veterinario, cenario['vet_id'])
    assert vet.clinica_id == cenario['outra_id']
    assert db.session.get(User, cenario['vet_user_id']).clinica_id == cenario['outra_id']
    assert cenario['vet_user_id'] not in _staff_ids(cenario['clinica_id'])
    convite = VetClinicInvite.query.filter_by(clinica_id=cenario['clinica_id'], veterinario_id=vet.id).one()
    assert convite.status == 'pending'


@pytest.mark.parametrize('marcador', [True, False], ids=['com-marcador', 'pagina-antiga'])
def test_email_de_contato_da_clinica_nao_vira_funcionario(app, client, cenario, marcador):
    _login(client, cenario['owner_id'])
    data = {
        'nome': 'Clínica da Ana',
        'email': 'bruno@outra.example.com',
        'telefone': '(16) 3826-0000',
        'submit': 'Salvar',
    }
    if marcador:
        data['clinic_form_name'] = 'clinic_info'

    resp = client.post(f"/clinica/{cenario['clinica_id']}", data=data, follow_redirects=True)

    pagina = resp.get_data(as_text=True)
    assert 'Clínica atualizada com sucesso.' in pagina
    assert 'Usuário não encontrado' not in pagina
    clinica = db.session.get(Clinica, cenario['clinica_id'])
    assert clinica.telefone == '(16) 3826-0000'
    assert clinica.email == 'bruno@outra.example.com'
    assert cenario['vet_user_id'] not in _staff_ids(cenario['clinica_id'])
    assert db.session.get(Veterinario, cenario['vet_id']).clinica_id == cenario['outra_id']


def test_adicionar_funcionario_existente_ignora_maiusculas(app, client, cenario):
    recepcao = User(name='Carla', email='carla@clinica.example.com', password_hash='x')
    db.session.add(recepcao)
    db.session.commit()
    _login(client, cenario['owner_id'])

    resp = client.post(
        f"/clinica/{cenario['clinica_id']}",
        data={'clinic_form_name': 'add_staff', 'email': 'Carla@Clinica.example.com', 'submit': 'Adicionar'},
    )

    assert resp.status_code == 302
    assert recepcao.id in _staff_ids(cenario['clinica_id'])
    assert VetClinicInvite.query.count() == 0


def test_adicionar_funcionario_sem_conta_explica_o_que_fazer(app, client, cenario):
    _login(client, cenario['owner_id'])

    resp = client.post(
        f"/clinica/{cenario['clinica_id']}",
        data={'clinic_form_name': 'add_staff', 'email': 'ninguem@clinica.example.com', 'submit': 'Adicionar'},
        follow_redirects=True,
    )

    pagina = resp.get_data(as_text=True)
    assert 'Não encontramos uma conta com este e-mail' in pagina
    assert 'Veterinário não encontrado' not in pagina
    assert _staff_ids(cenario['clinica_id']) <= {cenario['owner_id']}
    # O e-mail digitado não pode virar o e-mail de contato da clínica.
    assert db.session.get(Clinica, cenario['clinica_id']).email is None


def test_salvar_horarios_grava_horarios_e_nao_os_dados_da_clinica(app, client, cenario):
    """O formulário de dados vem preenchido com o que já está gravado e
    validava em qualquer envio: "Salvar" nos horários regravava a clínica e
    os horários nunca eram salvos."""
    _login(client, cenario['owner_id'])

    resp = client.post(
        f"/clinica/{cenario['clinica_id']}",
        data={
            'clinic_form_name': 'clinic_hours',
            'clinica_id': str(cenario['clinica_id']),
            'dias_semana': ['Segunda', 'Terça'],
            'hora_abertura': '08:00',
            'hora_fechamento': '18:00',
            'submit': 'Salvar',
        },
    )

    assert resp.status_code == 302
    assert ClinicHours.query.filter_by(clinica_id=cenario['clinica_id']).count() == 2
    with client.session_transaction() as sess:
        mensagens = [msg for _, msg in sess.get('_flashes', [])]
    assert 'Horário salvo com sucesso.' in mensagens
    assert 'Clínica atualizada com sucesso.' not in mensagens


def test_painel_nao_expoe_veterinarios_de_outras_clinicas(app, client, cenario):
    _login(client, cenario['owner_id'])

    pagina = client.get(f"/clinica/{cenario['clinica_id']}").get_data(as_text=True)

    assert 'all-vets-list' not in pagina
    assert 'bruno@outra.example.com' not in pagina
    assert 'name="clinic_form_name" value="invite_vet"' in pagina
    assert 'name="clinic_form_name" value="add_staff"' in pagina
    assert 'name="clinic_form_name" value="clinic_info"' in pagina
    assert 'name="clinic_form_name" value="clinic_hours"' in pagina


def test_passos_da_ativacao_abrem_o_formulario_certo(app, cenario):
    from services.activation import _compute

    owner = db.session.get(User, cenario['owner_id'])
    with app.test_request_context():
        urls = {step['cta']: step['url'] for step in _compute(owner)}
        assert urls['Cadastrar paciente'] == url_for('novo_animal', panel='cadastro')
        assert urls['Criar agendamento'] == url_for('appointments') + '#section-new'


@pytest.mark.parametrize('nome,esperado', [
    ('Dra. Ana Souza', 'Dra. Ana'),
    ('Dr Bruno Lima', 'Dr. Bruno'),
    ('Maria da Silva', 'Maria'),
    ('Dra.', 'Dra.'),
    ('', ''),
    (None, ''),
])
def test_primeiro_nome_mantem_titulo_sem_ponto_duplo(nome, esperado):
    assert primeiro_nome(nome) == esperado
