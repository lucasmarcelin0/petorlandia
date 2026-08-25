"""Os vazamentos do funil que o diagnóstico apontou, agora com rede.

Cada teste aqui prende um comportamento que antes não existia: quem paga sem
ter CRMV, o lead que recebe resposta, o marco de ativação que vira evento, a
atribuição que sobrevive ao clique de CTA e a intenção de compra que atravessa
o muro de login.
"""

from datetime import timedelta

import pytest

from extensions import db
from models import (
    Animal,
    Clinica,
    Order,
    Product,
    ProductEvent,
    User,
    VeterinarianMembership,
    WaitlistLead,
)
from time_utils import utcnow


def _login(client, user_id: int, *, keep_session=False) -> None:
    with client.session_transaction() as session:
        if not keep_session:
            session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _user(name='Responsável', email=None, role='adotante') -> User:
    user = User(
        name=name,
        email=email or f'{name.lower().replace(" ", "-")}@example.test',
        password_hash='x',
        role=role,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _clinica(owner, nome='Clínica Teste') -> Clinica:
    clinica = Clinica(nome=nome, owner_id=owner.id, status='ativa')
    db.session.add(clinica)
    db.session.commit()
    return clinica


# ------------------------------------------------- assinatura ancorada na clínica


def test_responsavel_sem_crmv_ganha_avaliacao_ao_criar_clinica(app, client):
    """O dono que não é veterinário existia comercialmente como ninguém.

    Tinha clínica ativa, usava o produto e nunca entrava na régua: sem
    avaliação, sem lembrete de fim de teste, sem win-back.
    """

    with app.app_context():
        owner = _user(name='Dona Sem CRMV', email='dona@example.test')
        owner_id = owner.id

        _login(client, owner_id)
        response = client.post(
            '/minha-clinica',
            data={'nome': 'Clínica da Dona', 'sou_veterinario': ''},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)

        membership = VeterinarianMembership.query.filter_by(
            owner_user_id=owner_id
        ).one()
        assert membership.veterinario_id is None
        assert membership.is_trial_active()
        assert membership.user.id == owner_id


def test_responsavel_sem_crmv_abre_a_propria_pagina_de_assinatura(app, client):
    """Antes: 403 na página onde ele configuraria o pagamento."""

    with app.app_context():
        owner = _user(name='Responsável Financeiro', email='financeiro@example.test')
        clinica = _clinica(owner)
        from helpers import ensure_clinic_membership

        ensure_clinic_membership(clinica, owner)
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get('/veterinario/assinatura')

    assert response.status_code == 200


def test_lembrete_de_fim_de_avaliacao_alcanca_responsavel_sem_crmv(app, monkeypatch):
    import app as app_module

    enviados = []
    monkeypatch.setattr(
        'services.notifications.notify_user',
        lambda user, assunto, corpo, **kw: enviados.append((user.id, assunto)),
    )

    with app.app_context():
        owner = _user(name='Responsável Avisado', email='avisado@example.test')
        clinica = _clinica(owner)
        from helpers import ensure_clinic_membership

        membership = ensure_clinic_membership(clinica, owner)
        # Último dia da avaliação: é um dos offsets da régua.
        membership.trial_ends_at = utcnow()
        db.session.commit()
        owner_id = owner.id

        app_module.enviar_lembretes_fim_trial()

        assert [user_id for user_id, _ in enviados] == [owner_id]


def test_virar_veterinario_nao_cria_segunda_assinatura(app):
    """A avaliação em curso muda de âncora; não recomeça nem duplica."""

    with app.app_context():
        owner = _user(name='Vira Vet', email='viravet@example.test')
        clinica = _clinica(owner)
        from helpers import ensure_clinic_membership, grant_veterinarian_role

        membership = ensure_clinic_membership(clinica, owner)
        trial_original = membership.trial_ends_at

        vet_profile = grant_veterinarian_role(owner, crmv='12345', clinica=clinica)
        db.session.commit()

        assert VeterinarianMembership.query.count() == 1
        adotada = VeterinarianMembership.query.one()
        assert adotada.veterinario_id == vet_profile.id
        assert adotada.owner_user_id == owner.id
        assert adotada.trial_ends_at == trial_original


# ------------------------------------------------------------ eventos de ativação


def test_criar_clinica_emite_marco_de_ativacao(app, client):
    with app.app_context():
        owner = _user(name='Marco Clinica', email='marco@example.test')
        owner_id = owner.id

    _login(client, owner_id)
    client.post(
        '/minha-clinica',
        data={'nome': 'Clínica com Marco', 'sou_veterinario': ''},
    )

    with app.app_context():
        assert ProductEvent.query.filter_by(event_name='clinic_created').count() == 1


def test_primeiro_paciente_emite_evento_uma_unica_vez(app):
    with app.app_context():
        owner = _user(name='Dona da Clinica', email='donaclinica@example.test')
        clinica = _clinica(owner)
        from services.activation import note_first_patient

        primeiro = Animal(name='Rex', user_id=owner.id, clinica_id=clinica.id)
        db.session.add(primeiro)
        db.session.commit()
        note_first_patient(clinica.id)

        segundo = Animal(name='Mia', user_id=owner.id, clinica_id=clinica.id)
        db.session.add(segundo)
        db.session.commit()
        note_first_patient(clinica.id)

        assert ProductEvent.query.filter_by(
            event_name='first_patient_created'
        ).count() == 1


def test_painel_mostra_o_funil_de_ativacao(app, client):
    with app.app_context():
        admin = _user(name='Admin Funil', email='adminfunil@example.test', role='admin')
        db.session.add_all([
            ProductEvent(
                event_name='signup_completed', anonymous_id='a1', session_id='s1',
                source_path='/register',
            ),
            ProductEvent(
                event_name='clinic_created', anonymous_id='a1', session_id='s1',
                source_path='/minha-clinica',
            ),
        ])
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    body = client.get('/admin/analytics-produto?days=7').data.decode()

    assert 'Ativação da clínica' in body
    assert 'Clínicas criadas' in body
    assert 'Primeiro agendamento' in body


def test_funil_conta_pessoas_e_nao_visitas(app, client):
    """Duas visitas da mesma pessoa não diluem a conversão de cadastro."""

    with app.app_context():
        admin = _user(name='Admin Pessoas', email='adminpessoas@example.test', role='admin')
        db.session.add_all([
            ProductEvent(
                event_name='landing_viewed', anonymous_id='a1', session_id='s1',
                source_path='/',
            ),
            ProductEvent(
                event_name='landing_viewed', anonymous_id='a1', session_id='s2',
                source_path='/',
            ),
            ProductEvent(
                event_name='signup_completed', anonymous_id='a1', session_id='s2',
                source_path='/register',
            ),
        ])
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    body = client.get('/admin/analytics-produto?days=7').data.decode()

    # Uma pessoa, um cadastro: 100%. Contando eventos daria 50%.
    assert '100.0%' in body
    assert '50.0%' not in body


# ------------------------------------------------------------------- atribuição


def test_clique_de_cta_preserva_a_campanha_de_origem(app, client):
    """``source='cta'`` apagava a campanha e virava origem de tráfego."""

    client.get('/?utm_source=parceiro&utm_medium=indicacao&utm_campaign=lancamento')
    client.post('/eventos/cta', json={'name': 'cta_home_clinic', 'path': '/precos'})

    with app.app_context():
        evento = ProductEvent.query.filter_by(event_name='cta_home_clinic').one()
        assert evento.utm_source == 'parceiro'
        assert evento.utm_campaign == 'lancamento'
        assert evento.properties['surface'] == 'cta'


# ------------------------------------------------------------ lista de espera


def test_pedido_de_demo_avisa_a_equipe_e_responde_ao_lead(app, client, monkeypatch):
    avisos = []
    confirmacoes = []
    monkeypatch.setattr(
        'services.notifications.notify_admins',
        lambda texto, **kw: avisos.append(texto),
    )
    monkeypatch.setattr(
        'services.notifications.notify_contact',
        lambda email, assunto, corpo: confirmacoes.append((email, assunto)),
    )

    response = client.post(
        '/lista-de-espera',
        json={'feature': 'demo_clinica', 'contact': 'clinica@example.test', 'city': 'Orlândia'},
    )

    assert response.status_code == 200
    assert len(avisos) == 1
    assert 'demonstração' in avisos[0].lower()
    assert confirmacoes == [('clinica@example.test', 'Sua demonstração da PetOrlândia')]

    with app.app_context():
        lead = WaitlistLead.query.one()
        assert lead.status == 'novo'
        assert lead.notified_at is not None


def test_lead_repetido_nao_avisa_a_equipe_de_novo(app, client, monkeypatch):
    avisos = []
    monkeypatch.setattr(
        'services.notifications.notify_admins',
        lambda texto, **kw: avisos.append(texto),
    )
    monkeypatch.setattr(
        'services.notifications.notify_contact',
        lambda email, assunto, corpo: None,
    )

    payload = {'feature': 'loja', 'contact': 'tutor@example.test'}
    client.post('/lista-de-espera', json=payload)
    client.post('/lista-de-espera', json=payload)

    assert len(avisos) == 1


# ---------------------------------------------------------------- boas-vindas


def test_cadastro_proprio_recebe_e_mail_de_boas_vindas(app, client, monkeypatch):
    enviados = []
    monkeypatch.setattr(
        'services.notifications.notify_user',
        lambda user, assunto, corpo, **kw: enviados.append((user.email, assunto, corpo)),
    )

    response = client.post(
        '/register',
        data={
            'name': 'Nova Tutora',
            'email': 'nova.tutora@example.com',
            'password': 'senhaforte123',
        },
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    assert len(enviados) == 1
    email, assunto, corpo = enviados[0]
    assert email == 'nova.tutora@example.com'
    assert 'Bem-vindo' in assunto
    # A mensagem entrega o próximo passo, não um recibo.
    assert '/minha-clinica' in corpo
    assert '/comecar' in corpo


# ------------------------------------------------------- intenção de compra


def _produto_publicado(name='Ração Premium', price=100.0) -> Product:
    from models.base import SiteFlag

    SiteFlag.set('loja_em_breve', False)
    product = Product(
        name=name,
        description='Descrição',
        price=price,
        stock=10,
        status='active',
    )
    db.session.add(product)
    db.session.commit()
    return product


def test_visitante_mantem_a_intencao_de_compra_atraves_do_login(app, client):
    with app.app_context():
        product = _produto_publicado()
        product_id = product.id
        comprador = _user(name='Comprador Novo', email='comprador@example.com')
        comprador.set_password('senhaforte123')
        db.session.commit()
        comprador_id = comprador.id

    intent = client.get(f'/produto/{product_id}/quero-comprar?quantity=3')
    assert intent.status_code in (302, 303)
    assert '/login' in intent.headers['Location']

    with client.session_transaction() as session:
        assert session['pending_cart_item'] == {
            'product_id': product_id,
            'quantity': 3,
        }

    # Login de verdade, pelo formulário: é o caminho em que a sessão do
    # visitante (e a intenção guardada nela) precisa sobreviver.
    entrada = client.post(
        '/login',
        data={'login': 'comprador@example.com', 'password': 'senhaforte123'},
        follow_redirects=False,
    )
    assert entrada.status_code in (302, 303)
    aplicado = client.get('/carrinho/retomar-intencao')

    assert aplicado.status_code in (302, 303)
    assert '/carrinho' in aplicado.headers['Location']

    with app.app_context():
        order = Order.query.filter_by(user_id=comprador_id).one()
        assert [(item.product_id, item.quantity) for item in order.items] == [
            (product_id, 3)
        ]


def test_quem_ja_tem_conta_vai_direto_ao_carrinho(app, client):
    with app.app_context():
        product = _produto_publicado(name='Shampoo')
        product_id = product.id
        comprador = _user(name='Comprador Logado', email='logado@example.test')
        comprador_id = comprador.id

    _login(client, comprador_id)
    response = client.get(f'/produto/{product_id}/quero-comprar?quantity=2')

    assert response.status_code in (302, 303)
    assert '/carrinho' in response.headers['Location']

    with app.app_context():
        order = Order.query.filter_by(user_id=comprador_id).one()
        assert order.items[0].quantity == 2


# ------------------------------------------------------------------- backfill


def test_backfill_cria_assinatura_so_para_quem_nao_tem(app):
    """Clínicas antigas só entram na cobrança por decisão explícita."""

    from click.testing import CliRunner

    from cli import backfill_clinic_memberships

    with app.app_context():
        sem_assinatura = _user(name='Antiga Dona', email='antiga@example.test')
        _clinica(sem_assinatura, nome='Clínica Antiga')

        ja_coberta = _user(name='Dona Coberta', email='coberta@example.test')
        clinica_coberta = _clinica(ja_coberta, nome='Clínica Coberta')
        from helpers import ensure_clinic_membership

        ensure_clinic_membership(clinica_coberta, ja_coberta)

        runner = CliRunner()

        previa = runner.invoke(backfill_clinic_memberships, [], obj={})
        assert previa.exit_code == 0
        assert '1 clinica(s)' in previa.output
        assert VeterinarianMembership.query.count() == 1

        aplicado = runner.invoke(backfill_clinic_memberships, ['--apply'], obj={})
        assert aplicado.exit_code == 0
        assert VeterinarianMembership.query.count() == 2
        nova = VeterinarianMembership.query.filter_by(
            owner_user_id=sem_assinatura.id
        ).one()
        assert nova.is_trial_active()
