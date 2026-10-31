"""Melhorias da configuração inicial da clínica.

Equipe cadastrada direto pela clínica, convite (e não transferência) para
veterinário de outra clínica, checklist de ativação, horários com intervalo,
painel paginado e importação de clientes por planilha.
"""
from datetime import time
from unittest.mock import MagicMock

import pytest

from extensions import db
from models import (
    Animal,
    Breed,
    ClinicHours,
    ClinicStaff,
    Clinica,
    Species,
    User,
    Veterinario,
    VetClinicInvite,
)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _flashes(client):
    with client.session_transaction() as sess:
        return [msg for _, msg in sess.get('_flashes', [])]


@pytest.fixture
def mail_mock(monkeypatch):
    enviado = MagicMock()
    monkeypatch.setattr('app.mail.send', enviado)
    monkeypatch.setattr('blueprints.clinica.mail.send', enviado)
    return enviado


@pytest.fixture
def clinica_da_ana(app):
    owner = User(name='Dra. Ana Dona', email='ana@clinica.example.com', password_hash='x', worker='veterinario')
    clinica = Clinica(nome='Clínica da Ana', owner=owner)
    db.session.add_all([owner, clinica])
    db.session.flush()
    Veterinario(user=owner, crmv='111', clinica=clinica)
    owner.clinica_id = clinica.id
    db.session.commit()
    return {'owner_id': owner.id, 'clinica_id': clinica.id}


# ── Funcionário cadastrado pela clínica ──────────────────────────────────────

def test_cadastrar_funcionario_cria_conta_com_permissoes_da_funcao(app, client, clinica_da_ana, mail_mock):
    _login(client, clinica_da_ana['owner_id'])

    resp = client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}/colaborador",
        data={'name': 'Carla Recepção', 'email': 'Carla@Clinica.example.com', 'phone': '(16) 99123-4567', 'funcao': 'recepcao'},
    )

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('#veterinarios')
    carla = User.query.filter_by(email='carla@clinica.example.com').one()
    assert carla.worker == 'colaborador'
    assert carla.clinica_id == clinica_da_ana['clinica_id']
    staff = ClinicStaff.query.filter_by(clinic_id=clinica_da_ana['clinica_id'], user_id=carla.id).one()
    assert staff.can_manage_clients and staff.can_manage_animals and staff.can_manage_schedule
    assert not staff.can_manage_inventory and not staff.can_manage_staff
    mail_mock.assert_called_once()
    mensagem = mail_mock.call_args[0][0]
    assert 'carla@clinica.example.com' in mensagem.recipients
    assert '/primeiro-acesso' in mensagem.body


def test_cadastrar_funcionario_sem_email_enviado_mostra_o_link(app, client, clinica_da_ana, monkeypatch):
    monkeypatch.setattr('blueprints.clinica.mail.send', MagicMock(side_effect=RuntimeError('smtp fora')))
    _login(client, clinica_da_ana['owner_id'])

    client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}/colaborador",
        data={'name': 'Davi Auxiliar', 'email': 'davi@clinica.example.com', 'phone': '16991234568', 'funcao': 'auxiliar'},
    )

    assert any('/primeiro-acesso' in msg for msg in _flashes(client))
    davi = User.query.filter_by(email='davi@clinica.example.com').one()
    staff = ClinicStaff.query.filter_by(user_id=davi.id).one()
    assert staff.can_manage_animals and not staff.can_manage_clients


@pytest.mark.parametrize('dados,mensagem', [
    ({'name': 'Sem Celular', 'email': 'x@clinica.example.com', 'phone': ''}, 'obrigatórios'),
    ({'name': 'Sem DDD', 'email': 'y@clinica.example.com', 'phone': '99123-4567'}, 'DDD'),
    ({'name': 'Já existe', 'email': 'ana@clinica.example.com', 'phone': '16991230000'}, 'já está cadastrado'),
])
def test_cadastrar_funcionario_valida_dados(app, client, clinica_da_ana, mail_mock, dados, mensagem):
    _login(client, clinica_da_ana['owner_id'])
    total = User.query.count()

    client.post(f"/clinica/{clinica_da_ana['clinica_id']}/colaborador", data=dados)

    assert User.query.count() == total
    assert any(mensagem in msg for msg in _flashes(client))
    mail_mock.assert_not_called()


def test_so_o_dono_cadastra_funcionario(app, client, clinica_da_ana, mail_mock):
    intruso = User(name='Outro', email='outro@clinica.example.com', password_hash='x')
    db.session.add(intruso)
    db.session.commit()
    _login(client, intruso.id)

    resp = client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}/colaborador",
        data={'name': 'Z', 'email': 'z@clinica.example.com', 'phone': '16991239999'},
    )

    # 404 também vale: o app esconde a existência da clínica de quem é de fora.
    assert resp.status_code in (403, 404)
    assert not User.query.filter_by(email='z@clinica.example.com').first()


def test_aba_equipe_mostra_cadastro_direto(app, client, clinica_da_ana):
    _login(client, clinica_da_ana['owner_id'])

    pagina = client.get(f"/clinica/{clinica_da_ana['clinica_id']}").get_data(as_text=True)

    assert f'/clinica/{clinica_da_ana["clinica_id"]}/colaborador' in pagina
    assert 'Recepção' in pagina and 'Auxiliar / técnico(a)' in pagina
    assert 'id="add-staff-form"' in pagina


# ── Funcionário existente / veterinário de outra clínica ─────────────────────

@pytest.fixture
def vet_de_outra_clinica(app):
    outra = Clinica(nome='Outra Clínica')
    vet_user = User(name='Dr. Bruno', email='bruno@outra.example.com', password_hash='x', worker='veterinario')
    db.session.add_all([outra, vet_user])
    db.session.flush()
    vet = Veterinario(user=vet_user, crmv='222', clinica=outra)
    vet_user.clinica_id = outra.id
    db.session.add(vet)
    db.session.commit()
    return {'user_id': vet_user.id, 'vet_id': vet.id, 'clinica_id': outra.id}


def test_adicionar_vet_de_outra_clinica_como_funcionario_vira_convite(app, client, clinica_da_ana, vet_de_outra_clinica, mail_mock):
    _login(client, clinica_da_ana['owner_id'])

    client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}",
        data={'clinic_form_name': 'add_staff', 'email': 'bruno@outra.example.com', 'submit': 'Adicionar'},
    )

    assert db.session.get(Veterinario, vet_de_outra_clinica['vet_id']).clinica_id == vet_de_outra_clinica['clinica_id']
    assert not ClinicStaff.query.filter_by(clinic_id=clinica_da_ana['clinica_id'], user_id=vet_de_outra_clinica['user_id']).first()
    assert VetClinicInvite.query.filter_by(clinica_id=clinica_da_ana['clinica_id'], status='pending').count() == 1
    assert any('enviamos um convite' in msg for msg in _flashes(client))


def test_pagina_funcionarios_tambem_convida_vet_de_outra_clinica(app, client, clinica_da_ana, vet_de_outra_clinica, mail_mock):
    _login(client, clinica_da_ana['owner_id'])

    resp = client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}/funcionarios",
        data={'email': 'bruno@outra.example.com'},
        headers={'Accept': 'application/json'},
    )

    assert resp.json['success'] is False
    assert 'convite' in resp.json['message']
    assert db.session.get(Veterinario, vet_de_outra_clinica['vet_id']).clinica_id == vet_de_outra_clinica['clinica_id']
    assert VetClinicInvite.query.filter_by(clinica_id=clinica_da_ana['clinica_id']).count() == 1


def test_adicionar_conta_existente_marca_como_colaborador(app, client, clinica_da_ana):
    pessoa = User(name='Eva', email='eva@clinica.example.com', password_hash='x')
    db.session.add(pessoa)
    db.session.commit()
    _login(client, clinica_da_ana['owner_id'])

    client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}",
        data={'clinic_form_name': 'add_staff', 'email': 'eva@clinica.example.com', 'submit': 'Adicionar'},
    )

    assert db.session.get(User, pessoa.id).worker == 'colaborador'


# ── Checklist de ativação e página "Por onde começar" ────────────────────────

def test_checklist_inclui_horarios_e_equipe(app, client, clinica_da_ana):
    from services.activation import _compute

    owner = db.session.get(User, clinica_da_ana['owner_id'])
    with app.test_request_context():
        passos = {p['label']: p for p in _compute(owner)}
    assert not passos['Horários de atendimento']['done']
    assert 'abrir=horarios' in passos['Horários de atendimento']['url']
    assert passos['Equipe cadastrada']['optional']
    assert not passos['Equipe cadastrada']['done']

    db.session.add(ClinicHours(clinica_id=clinica_da_ana['clinica_id'], dia_semana='Segunda',
                               hora_abertura=time(8), hora_fechamento=time(18)))
    db.session.add(ClinicStaff(clinic_id=clinica_da_ana['clinica_id'],
                               user=User(name='F', email='f@clinica.example.com', password_hash='x')))
    db.session.commit()
    with app.test_request_context():
        passos = {p['label']: p for p in _compute(owner)}
    assert passos['Horários de atendimento']['done']
    assert passos['Equipe cadastrada']['done']


def test_dono_que_nao_e_veterinario_nao_ve_passo_de_assinatura(app):
    from services.activation import _compute

    dono = User(name='Gestora', email='gestora@clinica.example.com', password_hash='x')
    clinica = Clinica(nome='Clínica da Gestora', owner=dono)
    db.session.add_all([dono, clinica])
    db.session.commit()
    with app.test_request_context():
        labels = [p['label'] for p in _compute(dono)]
    assert 'Renovação configurada' not in labels


def test_faixa_de_ativacao_sugere_passo_obrigatorio_antes_do_opcional(app, clinica_da_ana):
    from flask import g
    from services.activation import activation_progress

    owner = db.session.get(User, clinica_da_ana['owner_id'])
    with app.test_request_context():
        g.pop('_activation_steps_cache', None)
        progresso = activation_progress(owner)
    assert progresso['next_label'] == 'definir os horários de atendimento'


def test_comecar_mostra_passos_da_clinica_para_quem_tem_clinica(app, client, clinica_da_ana):
    _login(client, clinica_da_ana['owner_id'])

    pagina = client.get('/comecar').get_data(as_text=True)

    assert 'Tudo pronto, Dra. Ana.' in pagina
    assert 'Trazer a equipe' in pagina
    assert f'/clinica/{clinica_da_ana["clinica_id"]}/importar' in pagina
    assert 'Quero cuidar do meu pet' not in pagina
    assert 'Também cuida de um pet?' in pagina


def test_comecar_sem_clinica_continua_igual(app, client):
    tutor = User(name='Tutor Novo', email='tutor@clinica.example.com', password_hash='x')
    db.session.add(tutor)
    db.session.commit()
    _login(client, tutor.id)

    pagina = client.get('/comecar').get_data(as_text=True)

    assert 'Tenho uma clínica veterinária' in pagina
    assert 'Quero cuidar do meu pet' in pagina


# ── Aba Clínica e horários ───────────────────────────────────────────────────

def test_aba_clinica_sem_bloco_repetido_e_pagamentos_recolhidos(app, client, clinica_da_ana):
    _login(client, clinica_da_ana['owner_id'])

    pagina = client.get(f"/clinica/{clinica_da_ana['clinica_id']}").get_data(as_text=True)

    assert 'clinic-hero' not in pagina
    assert pagina.count('Editar dados') == 1
    assert 'Exportar dados' in pagina
    assert '<details class="clinic-payments-section' in pagina
    assert pagina.index('Horários de Atendimento') < pagina.index('clinic-payments-section')
    assert 'class="btn-check" name="dias_semana"' in pagina
    assert f'type="hidden" name="clinica_id" value="{clinica_da_ana["clinica_id"]}"' in pagina


def test_horario_com_intervalo_e_em_ordem_da_semana(app, client, clinica_da_ana):
    _login(client, clinica_da_ana['owner_id'])
    base = {'clinic_form_name': 'clinic_hours', 'clinica_id': str(clinica_da_ana['clinica_id']), 'submit': 'Salvar'}

    client.post(f"/clinica/{clinica_da_ana['clinica_id']}", data={
        **base, 'dias_semana': ['Sábado'], 'hora_abertura': '08:00', 'hora_fechamento': '12:00',
    })
    client.post(f"/clinica/{clinica_da_ana['clinica_id']}", data={
        **base, 'dias_semana': ['Segunda'], 'hora_abertura': '08:00', 'hora_fechamento': '18:00',
        'intervalo_inicio': '12:00', 'intervalo_fim': '13:30',
    })

    segunda = ClinicHours.query.filter_by(clinica_id=clinica_da_ana['clinica_id'], dia_semana='Segunda').one()
    assert segunda.intervalo_inicio == time(12) and segunda.intervalo_fim == time(13, 30)
    pagina = client.get(f"/clinica/{clinica_da_ana['clinica_id']}").get_data(as_text=True)
    assert 'Intervalo 12:00–13:30' in pagina
    assert pagina.index('<h6 class="mb-0 fw-semibold">Segunda</h6>') < pagina.index('<h6 class="mb-0 fw-semibold">Sábado</h6>')


@pytest.mark.parametrize('extra,mensagem', [
    ({'intervalo_inicio': '12:00'}, 'início e o fim do intervalo'),
    ({'intervalo_inicio': '13:00', 'intervalo_fim': '12:00'}, 'terminar depois de começar'),
    ({'dias_semana': []}, 'pelo menos um dia'),
])
def test_horario_invalido_explica_e_nao_salva(app, client, clinica_da_ana, extra, mensagem):
    _login(client, clinica_da_ana['owner_id'])
    dados = {
        'clinic_form_name': 'clinic_hours', 'clinica_id': str(clinica_da_ana['clinica_id']), 'submit': 'Salvar',
        'dias_semana': ['Terça'], 'hora_abertura': '08:00', 'hora_fechamento': '18:00', **extra,
    }

    resp = client.post(f"/clinica/{clinica_da_ana['clinica_id']}", data=dados)

    assert resp.status_code == 302
    assert 'abrir=horarios' in resp.headers['Location']
    assert ClinicHours.query.count() == 0
    assert any(mensagem in msg for msg in _flashes(client))


# ── Painel paginado ──────────────────────────────────────────────────────────

def test_painel_carrega_so_a_primeira_pagina_de_animais_e_tutores(app, client, clinica_da_ana):
    especie = Species(name='Cachorro')
    db.session.add(especie)
    db.session.flush()
    for i in range(15):
        tutor = User(name=f'Tutor {i:02d}', email=f't{i}@clinica.example.com', password_hash='x',
                     clinica_id=clinica_da_ana['clinica_id'])
        db.session.add(tutor)
        db.session.flush()
        db.session.add(Animal(name=f'Pet {i:02d}', species_id=especie.id, user_id=tutor.id,
                              clinica_id=clinica_da_ana['clinica_id']))
    db.session.commit()
    _login(client, clinica_da_ana['owner_id'])

    pagina = client.get(f"/clinica/{clinica_da_ana['clinica_id']}").get_data(as_text=True)

    animais = sum(1 for i in range(15) if f'Pet {i:02d}' in pagina)
    tutores = sum(1 for i in range(15) if f'Tutor {i:02d}' in pagina)
    assert animais == 12
    assert tutores == 12
    assert 'data-page="2"' in pagina


# ── Importação por planilha ──────────────────────────────────────────────────

@pytest.fixture
def catalogo(app):
    cao = Species(name='Cachorro')
    gato = Species(name='Gato')
    db.session.add_all([cao, gato])
    db.session.flush()
    db.session.add(Breed(name='Labrador', species_id=cao.id))
    db.session.commit()


def _csv(linhas, sep=';'):
    cabecalho = ['tutor_nome', 'tutor_celular', 'tutor_email', 'tutor_cpf', 'animal_nome', 'especie', 'raca',
                 'sexo', 'nascimento', 'peso', 'castrado']
    texto = sep.join(cabecalho) + '\n' + '\n'.join(sep.join(l) for l in linhas) + '\n'
    return texto.encode('utf-8')


def test_ler_planilha_aceita_virgula_titulos_variados_e_latin1():
    from services.clinic_import import ler_planilha

    conteudo = 'Nome do tutor,Telefone,E-mail,Pet,Espécie\nJoão,16 99999-0000,j@x.example.com,Rex,Cão\n'.encode('cp1252')
    linhas = ler_planilha(conteudo)

    assert linhas == [{'tutor_nome': 'João', 'tutor_celular': '16 99999-0000', 'tutor_email': 'j@x.example.com',
                       'animal_nome': 'Rex', 'especie': 'Cão'}]


@pytest.mark.parametrize('conteudo,mensagem', [
    (b'', 'vazio'),
    (b'PK\x03\x04resto', 'Excel'),
    (b'animal;especie\nRex;Cachorro\n', 'nome do tutor'),
])
def test_ler_planilha_recusa_arquivo_que_nao_serve(conteudo, mensagem):
    from services.clinic_import import PlanilhaInvalida, ler_planilha

    with pytest.raises(PlanilhaInvalida, match=mensagem):
        ler_planilha(conteudo)


def test_importacao_previa_nao_grava_e_confirmacao_cria(app, client, clinica_da_ana, catalogo):
    _login(client, clinica_da_ana['owner_id'])
    planilha = _csv([
        ['Maria Souza', '(16) 99123-4567', 'maria@exemplo.example.com', '', 'Thor', 'Cachorro', 'Labrador', 'Macho', '15/03/2020', '28,5', 'sim'],
        ['Maria Souza', '(16) 99123-4567', 'maria@exemplo.example.com', '', 'Mia', 'gata', '', 'F', '2022-01-10', '4', 'não'],
        ['João Lima', '(16) 98888-1111', '', '', '', '', '', '', '', '', ''],
        ['', '', '', '', 'Sem dono', 'Cachorro', '', '', '', '', ''],
        ['Pedro', '', '', '', 'Bolinha', 'Papagaio', '', '', '', '', ''],
    ])
    from io import BytesIO

    previa = client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}/importar",
        data={'acao': 'previsualizar', 'arquivo': (BytesIO(planilha), 'clientes.csv')},
        content_type='multipart/form-data',
    )
    html = previa.get_data(as_text=True)
    assert previa.status_code == 200
    assert '2 tutor(es) novo(s)' in html
    assert '2 animal(is) novo(s)' in html
    assert '2 linha(s) com erro' in html
    assert 'espécie &#34;Papagaio&#34; não reconhecida' in html or 'espécie "Papagaio" não reconhecida' in html
    assert User.query.filter_by(email='maria@exemplo.example.com').first() is None

    import re, html as html_lib
    linhas_json = html_lib.unescape(re.search(r'<textarea name="linhas_json" hidden>(.*?)</textarea>', html, re.S).group(1))
    resp = client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}/importar",
        data={'acao': 'confirmar', 'linhas_json': linhas_json},
    )

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('#tutores')
    maria = User.query.filter_by(email='maria@exemplo.example.com').one()
    assert maria.clinica_id == clinica_da_ana['clinica_id'] and maria.is_private
    assert {a.name for a in Animal.query.filter_by(user_id=maria.id)} == {'Thor', 'Mia'}
    thor = Animal.query.filter_by(name='Thor').one()
    assert thor.breed is not None and thor.peso == 28.5 and thor.neutered is True and thor.sex == 'Macho'
    mia = Animal.query.filter_by(name='Mia').one()
    assert mia.species.name == 'Gato' and mia.neutered is False
    joao = User.query.filter_by(name='João Lima').one()
    assert joao.email_is_placeholder and joao.phone == '+5516988881111'
    assert User.query.filter_by(name='Pedro').first() is None
    assert any('Importação concluída' in msg for msg in _flashes(client))


def test_importar_de_novo_nao_duplica(app, client, clinica_da_ana, catalogo):
    from services.clinic_import import aplicar, ler_planilha

    owner = db.session.get(User, clinica_da_ana['owner_id'])
    planilha = _csv([['Maria Souza', '(16) 99123-4567', '', '', 'Thor', 'Cachorro', '', '', '', '', '']])
    with app.test_request_context():
        primeira = aplicar(ler_planilha(planilha), clinica_da_ana['clinica_id'], owner)
        segunda = aplicar(ler_planilha(planilha), clinica_da_ana['clinica_id'], owner)

    assert primeira['tutores_novos'] == 1 and primeira['animais_novos'] == 1
    assert segunda['tutores_novos'] == 0 and segunda['animais_novos'] == 0
    assert segunda['tutores_existentes'] == 1 and segunda['animais_existentes'] == 1
    assert User.query.filter_by(name='Maria Souza').count() == 1
    assert Animal.query.filter_by(name='Thor').count() == 1


def test_importacao_nao_usa_conta_de_outra_clinica(app, clinica_da_ana, catalogo):
    from services.clinic_import import ler_planilha, planejar

    db.session.add(User(name='Fora', email='fora@outra.example.com', password_hash='x'))
    db.session.commit()
    planilha = _csv([['Fora', '', 'fora@outra.example.com', '', 'Rex', 'Cachorro', '', '', '', '', '']])

    plano = planejar(ler_planilha(planilha), clinica_da_ana['clinica_id'])

    assert not plano[0].ok
    assert 'fora da clínica' in plano[0].erros[0]


def test_importacao_exige_permissao(app, client, clinica_da_ana):
    tutor = User(name='Tutor', email='tutor2@clinica.example.com', password_hash='x', clinica_id=clinica_da_ana['clinica_id'])
    db.session.add(tutor)
    db.session.commit()
    _login(client, tutor.id)

    assert client.get(f"/clinica/{clinica_da_ana['clinica_id']}/importar").status_code in (403, 404)
    assert client.get(f"/clinica/{clinica_da_ana['clinica_id']}/importar/modelo.csv").status_code in (403, 404)


def test_modelo_da_planilha_abre_no_excel(app, client, clinica_da_ana):
    _login(client, clinica_da_ana['owner_id'])

    resp = client.get(f"/clinica/{clinica_da_ana['clinica_id']}/importar/modelo.csv")

    assert resp.status_code == 200
    assert resp.mimetype == 'text/csv'
    texto = resp.get_data(as_text=True)
    assert texto.startswith('﻿tutor_nome;tutor_celular')


def test_confirmacao_rejeita_previa_adulterada(app, client, clinica_da_ana):
    _login(client, clinica_da_ana['owner_id'])

    resp = client.post(
        f"/clinica/{clinica_da_ana['clinica_id']}/importar",
        data={'acao': 'confirmar', 'linhas_json': '{"nao": "lista"}'},
    )

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/importar')
    assert any('Não foi possível ler a prévia' in msg for msg in _flashes(client))
