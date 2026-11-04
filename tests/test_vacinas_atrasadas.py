"""Vacinas atrasadas: painel da clínica, botão do WhatsApp e envio automático.

As três frentes usam as regras de services/vacinas_atrasadas.py; os testes
cobrem as regras de vencimento, a régua de marcos (sem repetir aviso), o
descadastro do tutor e o acesso às rotas.
"""

from datetime import date, timedelta

import pytest

from extensions import db
from models import (
    Animal,
    Clinica,
    ClinicStaff,
    LembreteVacinaBloqueio,
    LembreteVacinaEnvio,
    Notification,
    User,
    Vacina,
)
from services import vacinas_atrasadas as va

HOJE = date(2026, 11, 3)


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _user(name, email=None, phone='(16) 99123-4567', **extra):
    user = User(
        name=name,
        email=email or f'{name.lower().replace(" ", ".")}@example.test',
        password_hash='x',
        role='adotante',
        phone=phone,
        **extra,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _clinica(owner, nome='Clínica Bicho Feliz', **extra):
    clinica = Clinica(nome=nome, owner_id=owner.id, telefone='(16) 3333-4444', **extra)
    db.session.add(clinica)
    db.session.commit()
    return clinica


def _animal(tutor, clinica, name='Rex', **extra):
    animal = Animal(name=name, user_id=tutor.id, clinica_id=clinica.id if clinica else None, **extra)
    db.session.add(animal)
    db.session.commit()
    return animal


def _aplicada(animal, nome, quando, intervalo=365):
    vacina = Vacina(animal_id=animal.id, nome=nome, aplicada=True, aplicada_em=quando, intervalo_dias=intervalo)
    db.session.add(vacina)
    db.session.commit()
    return vacina


def _agendada(animal, nome, quando):
    vacina = Vacina(animal_id=animal.id, nome=nome, aplicada=False, aplicada_em=quando)
    db.session.add(vacina)
    db.session.commit()
    return vacina


@pytest.fixture()
def outbox(monkeypatch):
    sent = []

    def fake_send(recipients, subject, body):
        # Só o lembrete desta régua: o aviso de "vacina agendada" no cadastro
        # da dose (services/appointment_notifications.py) usa o mesmo envio.
        if '/lembretes-vacina/sair/' in body:
            sent.append({'to': recipients, 'subject': subject, 'body': body})
        return True

    monkeypatch.setattr('services.notifications._send_email', fake_send)
    monkeypatch.setattr('services.push.push_to_user', lambda *a, **k: 0)
    return sent


@pytest.fixture()
def cenario(app):
    dono = _user('Dra Ana', phone=None)
    tutor = _user('Maria Souza')
    clinica = _clinica(dono)
    rex = _animal(tutor, clinica)
    return {'dono': dono, 'tutor': tutor, 'clinica': clinica, 'rex': rex}


# ------------------------------------------------------------- regras


def test_reforco_vencido_aparece_e_dose_nova_do_mesmo_grupo_substitui(cenario):
    rex = cenario['rex']
    _aplicada(rex, 'V10', HOJE - timedelta(days=375))  # venceu há 10 dias
    _aplicada(rex, 'Canigen R', HOJE - timedelta(days=400))  # antirrábica antiga...
    _aplicada(rex, 'Rabisin', HOJE - timedelta(days=30))  # ...substituída pela nova

    pend = va.pendencias_da_clinica(cenario['clinica'].id, HOJE)

    assert [(p.vacina.nome, p.dias_atraso, p.origem) for p in pend] == [('V10', 10, 'reforco')]


def test_dose_agendada_vencida_e_resolvida_por_aplicacao_posterior(cenario):
    rex = cenario['rex']
    _agendada(rex, 'Giardia', HOJE - timedelta(days=5))
    # Agendada para 20 dias atrás, mas aplicada (registro novo) 18 dias atrás.
    _agendada(rex, 'Leishmune', HOJE - timedelta(days=20))
    _aplicada(rex, 'Leishmune', HOJE - timedelta(days=18))

    pend = va.pendencias_da_clinica(cenario['clinica'].id, HOJE)

    assert [(p.vacina.nome, p.origem) for p in pend] == [('Giardia', 'agendada')]


def test_segunda_dose_do_filhote_nao_some_por_causa_da_primeira(cenario):
    rex = cenario['rex']
    _aplicada(rex, 'V10', HOJE - timedelta(days=25), intervalo=21)
    _agendada(rex, 'V10', HOJE - timedelta(days=4))

    pend = va.pendencias_da_clinica(cenario['clinica'].id, HOJE)

    # Só a dose agendada; o reforço calculado da 1ª dose não duplica.
    assert [(p.origem, p.dias_atraso) for p in pend] == [('agendada', 4)]


def test_janela_do_painel_e_pacientes_fora_do_escopo(cenario):
    rex, tutor, clinica = cenario['rex'], cenario['tutor'], cenario['clinica']
    _aplicada(rex, 'V10', HOJE - timedelta(days=365 - 5))  # vence em 5 dias: entra
    _aplicada(rex, 'Giardia', HOJE - timedelta(days=365 - 20))  # vence em 20: fora
    _agendada(rex, 'Leishmune', HOJE - timedelta(days=200))  # atrasada há 200 dias

    falecido = _animal(tutor, clinica, 'Bidu', is_alive=False)
    _agendada(falecido, 'V10', HOJE - timedelta(days=3))
    outra = _clinica(cenario['dono'], 'Outra')
    _agendada(_animal(tutor, outra, 'Mia'), 'V10', HOJE - timedelta(days=3))

    padrao = va.pendencias_da_clinica(clinica.id, HOJE)
    todas = va.pendencias_da_clinica(clinica.id, HOJE, atraso_max_dias=0)

    assert [p.vacina.nome for p in padrao] == ['V10']
    assert sorted(p.vacina.nome for p in todas) == ['Leishmune', 'V10']


@pytest.mark.parametrize('dias, esperado', [
    (-10, None), (-7, -7), (-1, -7), (0, 0), (6, 0), (7, 7), (13, 7), (14, None),
    (29, None), (30, 30), (36, 30), (37, None), (400, None),
])
def test_marco_atual(dias, esperado):
    assert va.marco_atual(dias) == esperado


@pytest.mark.parametrize('phone, esperado', [
    ('(16) 99123-4567', '5516991234567'),
    ('016 3333-4444', '551633334444'),
    ('+55 16 99123-4567', '5516991234567'),
    ('1234', None),
    (None, None),
])
def test_telefone_whatsapp(phone, esperado):
    assert va.telefone_whatsapp(phone) == esperado


def test_mensagem_agrupa_animais_do_tutor(cenario):
    rex, tutor, clinica = cenario['rex'], cenario['tutor'], cenario['clinica']
    _aplicada(rex, 'V10', HOJE - timedelta(days=370))
    _agendada(_animal(tutor, clinica, 'Mel'), 'Antirrábica', HOJE + timedelta(days=2))

    grupos = va.agrupar_por_tutor(clinica.id, va.pendencias_da_clinica(clinica.id, HOJE))

    assert len(grupos) == 1
    texto = va.mensagem_whatsapp(clinica, tutor, grupos[0].pendencias)
    assert texto.startswith('Olá, Maria! Aqui é da Clínica Bicho Feliz.')
    assert 'V10 de Rex: venceu em 29/10/2026' in texto
    assert 'Antirrábica de Mel: vence em 05/11/2026' in texto
    assert va.link_whatsapp(tutor.phone, texto).startswith('https://wa.me/5516991234567?text=Ol%C3%A1')


# ------------------------------------------------------------- envio automático


def test_envio_automatico_so_para_clinica_que_ligou_e_sem_repetir(cenario, outbox):
    rex, clinica = cenario['rex'], cenario['clinica']
    _aplicada(rex, 'V10', HOJE - timedelta(days=365))  # vence hoje: marco 0

    assert va.enviar_lembretes_automaticos(HOJE)['emails'] == 0  # opção desligada
    assert outbox == []

    clinica.lembrete_vacina_automatico = True
    db.session.commit()
    resumo = va.enviar_lembretes_automaticos(HOJE)

    assert resumo == {'clinicas': 1, 'tutores': 1, 'emails': 1, 'push': 0}
    assert outbox[0]['to'] == ['maria.souza@example.test']
    assert outbox[0]['subject'] == 'Lembrete de vacina: Rex'
    assert 'V10 de Rex: vence hoje' in outbox[0]['body']
    assert 'https://wa.me/551633334444' in outbox[0]['body']
    assert '/lembretes-vacina/sair/' in outbox[0]['body']
    assert Notification.query.filter_by(kind=va.NOTIFICATION_KIND).count() == 1

    # Mesmo dia e dias seguintes do mesmo marco: nada novo.
    va.enviar_lembretes_automaticos(HOJE)
    va.enviar_lembretes_automaticos(HOJE + timedelta(days=3))
    assert len(outbox) == 1

    # Marco seguinte (7 dias de atraso): novo aviso, agora como atrasada.
    va.enviar_lembretes_automaticos(HOJE + timedelta(days=7))
    assert len(outbox) == 2
    assert outbox[1]['subject'] == 'Vacina atrasada: Rex'
    assert LembreteVacinaEnvio.query.filter_by(canal='email').count() == 2


def test_envio_automatico_um_email_por_tutor_e_ignora_atraso_antigo(cenario, outbox):
    rex, tutor, clinica = cenario['rex'], cenario['tutor'], cenario['clinica']
    clinica.lembrete_vacina_automatico = True
    db.session.commit()
    _agendada(rex, 'V10', HOJE + timedelta(days=7))
    _agendada(_animal(tutor, clinica, 'Mel'), 'Giardia', HOJE + timedelta(days=5))
    _agendada(rex, 'Leishmune', HOJE - timedelta(days=100))  # antiga: só no painel

    va.enviar_lembretes_automaticos(HOJE)

    assert len(outbox) == 1
    assert outbox[0]['subject'] == 'Lembrete de vacina: Mel e Rex'
    assert 'Leishmune' not in outbox[0]['body']


def test_envio_respeita_descadastro_e_email_placeholder(cenario, outbox):
    rex, clinica = cenario['rex'], cenario['clinica']
    clinica.lembrete_vacina_automatico = True
    sem_email = _user('Joao', email='joao@convite.petorlandia.local')
    _agendada(_animal(sem_email, clinica, 'Toto'), 'V10', HOJE)
    _agendada(rex, 'V10', HOJE)
    db.session.add(LembreteVacinaBloqueio(user_id=cenario['tutor'].id))
    db.session.commit()

    resumo = va.enviar_lembretes_automaticos(HOJE)

    assert resumo['emails'] == 0
    assert outbox == []


def test_falha_no_email_tenta_de_novo_no_dia_seguinte(cenario, monkeypatch):
    rex, clinica = cenario['rex'], cenario['clinica']
    clinica.lembrete_vacina_automatico = True
    db.session.commit()
    _agendada(rex, 'V10', HOJE)
    monkeypatch.setattr('services.push.push_to_user', lambda *a, **k: 0)
    tentativas = []
    def fake_send(to, subject, body):
        if '/lembretes-vacina/sair/' not in body:
            return True
        tentativas.append(subject)
        return len(tentativas) > 1

    monkeypatch.setattr('services.notifications._send_email', fake_send)

    va.enviar_lembretes_automaticos(HOJE)
    assert LembreteVacinaEnvio.query.count() == 0
    va.enviar_lembretes_automaticos(HOJE + timedelta(days=1))
    assert len(tentativas) == 2
    assert LembreteVacinaEnvio.query.count() == 1


def test_push_e_registrado_quando_entregue(cenario, monkeypatch, outbox):
    rex, clinica = cenario['rex'], cenario['clinica']
    clinica.lembrete_vacina_automatico = True
    db.session.commit()
    _agendada(rex, 'V10', HOJE)
    pushes = []
    monkeypatch.setattr(
        'services.push.push_to_user', lambda uid, title, body, **k: pushes.append(body) or 1,
    )

    resumo = va.enviar_lembretes_automaticos(HOJE)
    va.enviar_lembretes_automaticos(HOJE)

    assert resumo['push'] == 1
    assert pushes == ['Clínica Bicho Feliz: V10 de Rex vence hoje']


# ------------------------------------------------------------- rotas


def test_painel_lista_tutor_com_link_do_whatsapp(client, cenario):
    _aplicada(cenario['rex'], 'V10', date.today() - timedelta(days=370))
    _login(client, cenario['dono'].id)

    resp = client.get(f"/clinica/{cenario['clinica'].id}/vacinas-atrasadas")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Maria Souza' in html
    assert 'https://wa.me/5516991234567?text=' in html
    assert 'Ligar envio automático' in html


def test_painel_bloqueia_quem_nao_e_da_clinica(client, cenario):
    estranho = _user('Estranho')
    _login(client, estranho.id)

    assert client.get(f"/clinica/{cenario['clinica'].id}/vacinas-atrasadas").status_code == 404


def test_colaborador_ve_painel_mas_nao_liga_envio(client, cenario):
    colaborador = _user('Colab')
    db.session.add(ClinicStaff(clinic_id=cenario['clinica'].id, user_id=colaborador.id))
    db.session.commit()
    _login(client, colaborador.id)
    base = f"/clinica/{cenario['clinica'].id}/vacinas-atrasadas"

    resp = client.get(base)
    assert resp.status_code == 200
    assert 'Ligar envio automático' not in resp.get_data(as_text=True)
    html = {'Accept': 'text/html'}  # sem isso o app responde 404 em JSON (não vaza a clínica)
    assert client.post(f'{base}/configuracao', data={'automatico': '1'}, headers=html).status_code == 403
    assert client.post(f'{base}/enviar-agora', headers=html).status_code == 403
    assert db.session.get(Clinica, cenario['clinica'].id).lembrete_vacina_automatico is False


def test_dono_liga_envio_e_envia_agora(client, cenario, outbox):
    _agendada(cenario['rex'], 'V10', date.today())
    _login(client, cenario['dono'].id)
    base = f"/clinica/{cenario['clinica'].id}/vacinas-atrasadas"

    resp = client.post(f'{base}/configuracao', data={'automatico': '1'})
    assert resp.status_code == 302
    assert db.session.get(Clinica, cenario['clinica'].id).lembrete_vacina_automatico is True

    client.post(f'{base}/enviar-agora')
    client.post(f'{base}/enviar-agora')
    assert len(outbox) == 1


def test_registro_do_whatsapp_ignora_dose_de_outra_clinica(client, cenario):
    vacina = _aplicada(cenario['rex'], 'V10', date.today() - timedelta(days=370))
    outra = _clinica(_user('Outro Dono'), 'Outra')
    alheia = _agendada(_animal(cenario['tutor'], outra, 'Mia'), 'V10', date.today())
    _login(client, cenario['dono'].id)

    resp = client.post(
        f"/clinica/{cenario['clinica'].id}/vacinas-atrasadas/whatsapp",
        json={'tutor_id': cenario['tutor'].id, 'vacina_ids': [vacina.id, alheia.id]},
    )

    assert resp.get_json() == {'ok': True, 'registrados': 1}
    envio = LembreteVacinaEnvio.query.one()
    assert (envio.vacina_id, envio.canal, envio.origem) == (vacina.id, 'whatsapp', 'manual')
    assert envio.enviado_por_id == cenario['dono'].id


def test_descadastro_confirma_antes_e_permite_voltar(client, cenario, app):
    tutor_id = cenario['tutor'].id
    with app.test_request_context():
        token = va.token_descadastro(tutor_id)

    assert client.get(f'/lembretes-vacina/sair/{token}').status_code == 200
    assert LembreteVacinaBloqueio.query.count() == 0  # GET não descadastra

    resp = client.post(f'/lembretes-vacina/sair/{token}', data={'acao': 'sair'})
    assert 'não receberá mais' in resp.get_data(as_text=True)
    assert LembreteVacinaBloqueio.query.filter_by(user_id=tutor_id).count() == 1

    client.post(f'/lembretes-vacina/sair/{token}', data={'acao': 'voltar'})
    assert LembreteVacinaBloqueio.query.count() == 0

    assert client.get('/lembretes-vacina/sair/token-invalido').status_code == 404


# ------------------------------------------------------------- lembrete antigo


def test_lembrete_diario_antigo_nao_avisa_vacina_ja_aplicada(app, cenario, monkeypatch):
    import app as app_module

    enviados = []
    # Só os lembretes do job; o cadastro da dose agendada já dispara o próprio aviso.
    monkeypatch.setattr(
        'services.push.push_to_user',
        lambda uid, title, body, **k: body.startswith('Lembrete:') and enviados.append(body),
    )
    monkeypatch.setattr(app_module.mail, 'send', lambda msg: None)
    monkeypatch.setattr(app_module, 'enviar_mensagem_whatsapp', lambda *a: None)
    rex, tutor, clinica = cenario['rex'], cenario['tutor'], cenario['clinica']
    amanha = app_module.datetime.now(app_module.BR_TZ).date() + timedelta(days=1)
    _aplicada(rex, 'Aplicada', amanha)
    _agendada(rex, 'Agendada', amanha)
    outra = _clinica(cenario['dono'], 'Com régua', lembrete_vacina_automatico=True)
    _agendada(_animal(tutor, outra, 'Mia'), 'Da régua', amanha)

    app_module.verificar_datas_proximas()

    assert len(enviados) == 1
    assert "'Agendada'" in enviados[0]
