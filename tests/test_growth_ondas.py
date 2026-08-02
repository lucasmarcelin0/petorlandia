"""Ondas 1 e 2 da auditoria de aquisição e monetização.

Cobre o que muda de comportamento visível: gates automáticos de oferta,
superfícies de receita abertas a visitante, parcelamento, eventos de funil,
recompensa de indicação e as réguas de recuperação.
"""

from datetime import timedelta

from extensions import db
from models import (
    Animal,
    CasaDeRacao,
    Clinica,
    GroomingPlan,
    HealthPlan,
    Order,
    OrderItem,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Product,
    ProductEvent,
    ReferralCode,
    ReferralSignup,
    User,
    Veterinario,
)
from time_utils import utcnow


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _user(name='Tutor', email=None, role='adotante', worker=None) -> User:
    user = User(
        name=name,
        email=email or f'{name.lower().replace(" ", "-")}@example.test',
        password_hash='x',
        role=role,
        worker=worker,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _abrir_loja() -> None:
    """Desliga o "em breve" manual — o gate automático segue valendo.

    A flag manual nasce ligada; sem desligá-la a loja renderiza o overlay e
    nenhum produto aparece, independentemente do catálogo.
    """
    from models.base import SiteFlag

    SiteFlag.set('loja_em_breve', False)
    db.session.commit()


def _product(name='Ração Premium', price=100.0, is_demo=False) -> Product:
    product = Product(
        name=name,
        description='Descrição do produto',
        price=price,
        stock=10,
        status='active',
        is_demo=is_demo,
    )
    db.session.add(product)
    db.session.commit()
    return product


# --------------------------------------------------------------- A6: gates


def test_loja_fica_privada_enquanto_so_houver_produto_de_teste(app):
    from services.offer_availability import store_is_public

    with app.app_context():
        _product(name='Teste produto 1', price=1.11, is_demo=True)
        assert store_is_public() is False


def test_loja_abre_sozinha_com_o_primeiro_produto_real(app):
    from services.offer_availability import store_is_public

    with app.app_context():
        _product(name='Teste produto 1', price=1.11, is_demo=True)
        assert store_is_public() is False

        _product(name='Ração Golden 15kg', price=180.0)
        assert store_is_public() is True


def test_produto_de_demo_nao_aparece_no_catalogo_publico(app, client):
    with app.app_context():
        _abrir_loja()
        demo = _product(name='Teste produto 1', price=1.11, is_demo=True)
        real = _product(name='Ração Golden 15kg', price=180.0)
        demo_id, real_id = demo.id, real.id

    response = client.get('/loja')
    assert response.status_code == 200
    body = response.data.decode()
    assert f'/produto/{real_id}' in body
    assert f'/produto/{demo_id}"' not in body


def test_admin_continua_enxergando_o_produto_de_demo(app, client):
    with app.app_context():
        _abrir_loja()
        admin = _user(name='Admin Loja', role='admin')
        demo = _product(name='Teste produto 1', price=1.11, is_demo=True)
        admin_id, demo_id = admin.id, demo.id

    _login(client, admin_id)
    body = client.get('/loja').data.decode()
    assert f'/produto/{demo_id}' in body


def test_ficha_de_produto_demo_e_404_para_visitante(app, client):
    with app.app_context():
        demo = _product(name='Teste produto 1', price=1.11, is_demo=True)
        demo_id = demo.id

    assert client.get(f'/produto/{demo_id}').status_code == 404


def test_banho_e_tosa_deixa_de_ser_em_breve_com_plano_ativo(app):
    from services.offer_availability import grooming_is_public

    with app.app_context():
        assert grooming_is_public() is False

        clinica = Clinica(nome='Clínica Parceira', status='ativa')
        db.session.add(clinica)
        db.session.commit()
        db.session.add(GroomingPlan(
            clinica_id=clinica.id,
            name='Banho mensal',
            service_type='banho',
            price=90,
            sessions_per_month=4,
            active=True,
        ))
        db.session.commit()

        assert grooming_is_public() is True


def test_plano_de_saude_abre_quando_existe_plano_cadastrado(app):
    from services.offer_availability import health_plan_is_public

    with app.app_context():
        assert health_plan_is_public() is False

        db.session.add(HealthPlan(name='Essencial', price=79.9))
        db.session.commit()

        assert health_plan_is_public() is True


# ------------------------------------------------------- A2: portas abertas


def test_ficha_de_produto_e_publica(app, client):
    with app.app_context():
        product = _product()
        product_id = product.id

    response = client.get(f'/produto/{product_id}')
    assert response.status_code == 200
    assert 'Ração Premium' in response.data.decode()


def test_visitante_nao_edita_produto(app, client):
    """Ver é público; editar não.

    O app converte 403 em 404 de propósito, para não revelar o que existe a
    quem não pode acessar — por isso a asserção é 404.
    """
    with app.app_context():
        product = _product()
        product_id = product.id

    assert client.post(f'/produto/{product_id}').status_code == 404


def test_busca_da_loja_responde_a_visitante(app, client):
    with app.app_context():
        _product()

    response = client.get('/loja/data?q=Ração')
    assert response.status_code == 200


def test_catalogo_de_vacinas_mostra_preco_sem_login(app, client):
    response = client.get('/servicos/vacinas')
    assert response.status_code == 200


def test_pedido_de_vacina_sem_conta_leva_ao_login(app, client):
    response = client.post('/servicos/vacinas', data={'item_ids': '1'})
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


# ----------------------------------------------------------- A3: sitemap


def test_sitemap_omite_a_loja_sem_catalogo_real(app, client):
    with app.app_context():
        _product(name='Teste produto 1', is_demo=True)

    body = client.get('/sitemap.xml').data.decode()
    assert '.com.br/loja</loc>' not in body
    assert '/produto/' not in body


def test_sitemap_publica_loja_e_produtos_quando_ha_catalogo(app, client):
    with app.app_context():
        _abrir_loja()
        product = _product(name='Ração Golden 15kg', price=180.0)
        product_id = product.id

    body = client.get('/sitemap.xml').data.decode()
    assert '.com.br/loja</loc>' in body
    assert f'/produto/{product_id}</loc>' in body


def test_sitemap_inclui_paginas_de_cidade(app, client):
    body = client.get('/sitemap.xml').data.decode()
    assert '/servicos' in body
    assert '/veterinarios' in body


# ------------------------------------------------------- B2: parcelamento


def test_checkout_da_loja_oferece_parcelamento(app):
    from blueprints.loja import _checkout_max_installments

    with app.app_context():
        assert _checkout_max_installments() == 6

        app.config['MERCADOPAGO_MAX_INSTALLMENTS'] = 10
        assert _checkout_max_installments() == 10

        app.config['MERCADOPAGO_MAX_INSTALLMENTS'] = 0
        assert _checkout_max_installments() == 1


# --------------------------------------------------- B1: eventos de receita


def test_adicionar_ao_carrinho_registra_evento(app, client):
    with app.app_context():
        user = _user(name='Compradora')
        product = _product()
        user_id, product_id = user.id, product.id

    _login(client, user_id)
    client.post(f'/carrinho/adicionar/{product_id}', data={'quantity': 2})

    with app.app_context():
        evento = ProductEvent.query.filter_by(event_name='add_to_cart').first()
        assert evento is not None
        assert evento.user_id == user_id
        assert evento.properties['items'] == 2


def test_webhook_registra_compra_uma_unica_vez(app, monkeypatch):
    """O Mercado Pago reenvia a mesma notificação; a compra conta uma vez."""
    import blueprints.loja as loja_module

    with app.app_context():
        user = _user(name='Pagador')
        payment = Payment(
            user_id=user.id,
            method=PaymentMethod.PIX,
            status=PaymentStatus.PENDING,
            amount=150.0,
            external_reference='pedido-teste-1',
        )
        db.session.add(payment)
        db.session.commit()

        monkeypatch.setattr(loja_module, 'verify_mp_signature', lambda *a, **k: True)
        monkeypatch.setattr(
            loja_module,
            '_fetch_mp_payment',
            lambda *a, **k: {
                'status': 'approved',
                'external_reference': 'pedido-teste-1',
                'id': '999',
            },
            raising=False,
        )

        client = app.test_client()
        for _ in range(2):
            client.post(
                '/notificacoes',
                json={'type': 'payment', 'data': {'id': '999'}},
            )

        eventos = ProductEvent.query.filter_by(
            event_name='purchase_completed'
        ).count()
        assert eventos <= 1


# ------------------------------------------- A4: indicação com recompensa


def _clinic_vet(name, email):
    user = _user(name=name, email=email, worker='veterinario')
    vet = Veterinario(user_id=user.id, crmv=f'CRMV-{user.id}')
    db.session.add(vet)
    db.session.commit()
    return user, vet


def test_indicado_ganha_dias_extras_de_avaliacao(app):
    """A indicação é registrada no cadastro, antes de a pessoa virar veterinária.

    O bônus precisa valer nessa ordem — que é a de produção.
    """
    from services.membership_conversion import REFERRED_TRIAL_BONUS_DAYS

    with app.app_context():
        indicador = _user(name='Indicador', email='indicador@example.test')
        codigo = ReferralCode.get_or_create(indicador.id)
        db.session.commit()

        indicado_user = _user(
            name='Indicada', email='indicada@example.test', worker='veterinario'
        )
        db.session.add(ReferralSignup(
            code_id=codigo.id, referred_user_id=indicado_user.id
        ))
        db.session.commit()

        vet = Veterinario(user_id=indicado_user.id, crmv='CRMV-IND')
        db.session.add(vet)
        db.session.commit()

        membership = vet.membership
        trial_days = app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
        duracao = (membership.trial_ends_at - membership.started_at).days
        assert duracao == trial_days + REFERRED_TRIAL_BONUS_DAYS


def test_quem_nao_veio_por_indicacao_mantem_avaliacao_padrao(app):
    with app.app_context():
        _user_obj, vet = _clinic_vet('Sem Indicacao', 'sem-indicacao@example.test')
        membership = vet.membership
        trial_days = app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
        assert (membership.trial_ends_at - membership.started_at).days == trial_days


def test_indicador_ganha_mes_gratis_quando_indicado_paga(app):
    from helpers import ensure_veterinarian_membership
    from services.membership_conversion import (
        REFERRAL_REWARD_DAYS,
        mark_converted,
        process_pending_conversions,
    )

    with app.app_context():
        indicador_user, indicador_vet = _clinic_vet(
            'Indicador Vet', 'indicador-vet@example.test'
        )
        indicador_membership = ensure_veterinarian_membership(indicador_vet)
        codigo = ReferralCode.get_or_create(indicador_user.id)
        db.session.commit()

        indicado_user, indicado_vet = _clinic_vet('Indicada', 'indicada@example.test')
        db.session.add(ReferralSignup(
            code_id=codigo.id, referred_user_id=indicado_user.id
        ))
        indicado_membership = ensure_veterinarian_membership(indicado_vet)
        db.session.commit()

        antes = indicador_membership.paid_until
        assert antes is None

        mark_converted(indicado_membership)
        db.session.commit()

        assert process_pending_conversions() == 1

        db.session.refresh(indicador_membership)
        assert indicador_membership.paid_until is not None
        # SQLite devolve datetime ingênuo; o helper do modelo normaliza.
        from models import VeterinarianMembership

        pago_ate = VeterinarianMembership._as_timezone_aware(
            indicador_membership.paid_until
        )
        credito = (pago_ate - utcnow()).days
        assert REFERRAL_REWARD_DAYS - 1 <= credito <= REFERRAL_REWARD_DAYS

        signup = ReferralSignup.query.one()
        assert signup.rewarded_at is not None

        # Segunda passagem não credita de novo.
        assert process_pending_conversions() == 0


def test_conversao_registra_evento_de_funil(app):
    from helpers import ensure_veterinarian_membership
    from services.membership_conversion import mark_converted, process_pending_conversions

    with app.app_context():
        _user_obj, vet = _clinic_vet('Convertida', 'convertida@example.test')
        membership = ensure_veterinarian_membership(vet)
        db.session.commit()

        mark_converted(membership)
        db.session.commit()
        process_pending_conversions()

        evento = ProductEvent.query.filter_by(event_name='trial_converted').first()
        assert evento is not None


# ------------------------------------------------ A5: faixa de ativação


def test_faixa_de_ativacao_aparece_com_passos_pendentes(app, client):
    with app.app_context():
        dono = _user(name='Dona Clinica', worker='veterinario')
        clinica = Clinica(nome='Clínica Nova', status='ativa', owner_id=dono.id)
        db.session.add(clinica)
        db.session.commit()
        dono_id = dono.id

    _login(client, dono_id)
    body = client.get('/loja').data.decode()
    assert 'activation-bar' in body
    assert 'Próximo:' in body


def test_faixa_de_ativacao_some_sem_clinica(app, client):
    with app.app_context():
        tutor = _user(name='Tutor Simples')
        tutor_id = tutor.id

    _login(client, tutor_id)
    assert 'activation-bar' not in client.get('/loja').data.decode()


# --------------------------------------------- B3: recuperação de receita


def test_winback_dispara_apenas_nos_dias_previstos(app, monkeypatch):
    import app as app_module
    from helpers import ensure_veterinarian_membership

    enviados = []
    monkeypatch.setattr(
        'services.notifications.notify_user',
        lambda user, assunto, corpo, **kw: enviados.append(assunto),
    )

    with app.app_context():
        _user_obj, vet = _clinic_vet('Nao Converteu', 'naoconverteu@example.test')
        membership = ensure_veterinarian_membership(vet)

        # Fora da régua: avaliação terminou ontem.
        membership.trial_ends_at = utcnow() - timedelta(days=1)
        db.session.commit()
        app_module.enviar_winback_pos_trial()
        assert enviados == []

        # Dentro da régua: D+3.
        membership.trial_ends_at = utcnow() - timedelta(days=3)
        db.session.commit()
        app_module.enviar_winback_pos_trial()
        assert len(enviados) == 1


def test_winback_ignora_quem_ja_converteu(app, monkeypatch):
    import app as app_module
    from helpers import ensure_veterinarian_membership
    from services.membership_conversion import mark_converted

    enviados = []
    monkeypatch.setattr(
        'services.notifications.notify_user',
        lambda user, assunto, corpo, **kw: enviados.append(assunto),
    )

    with app.app_context():
        _user_obj, vet = _clinic_vet('Converteu', 'converteu@example.test')
        membership = ensure_veterinarian_membership(vet)
        membership.trial_ends_at = utcnow() - timedelta(days=3)
        mark_converted(membership)
        db.session.commit()

        app_module.enviar_winback_pos_trial()
        assert enviados == []


def test_carrinho_abandonado_lembra_uma_vez_so(app, monkeypatch):
    import app as app_module

    enviados = []
    monkeypatch.setattr(
        'services.notifications.notify_user',
        lambda user, assunto, corpo, **kw: enviados.append(assunto),
    )

    with app.app_context():
        user = _user(name='Esquecida')
        product = _product()
        order = Order(
            user_id=user.id,
            created_at=utcnow() - timedelta(hours=30),
        )
        db.session.add(order)
        db.session.commit()
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            item_name=product.name,
            quantity=1,
            unit_price=100,
        ))
        db.session.commit()

        app_module.enviar_lembretes_carrinho_abandonado()
        assert len(enviados) == 1

        app_module.enviar_lembretes_carrinho_abandonado()
        assert len(enviados) == 1


def test_carrinho_recente_nao_recebe_lembrete(app, monkeypatch):
    import app as app_module

    enviados = []
    monkeypatch.setattr(
        'services.notifications.notify_user',
        lambda user, assunto, corpo, **kw: enviados.append(assunto),
    )

    with app.app_context():
        user = _user(name='Comprando Agora')
        product = _product()
        order = Order(user_id=user.id, created_at=utcnow() - timedelta(hours=2))
        db.session.add(order)
        db.session.commit()
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            item_name=product.name,
            quantity=1,
            unit_price=100,
        ))
        db.session.commit()

        app_module.enviar_lembretes_carrinho_abandonado()
        assert enviados == []


def test_carrinho_pago_nao_recebe_lembrete(app, monkeypatch):
    import app as app_module

    enviados = []
    monkeypatch.setattr(
        'services.notifications.notify_user',
        lambda user, assunto, corpo, **kw: enviados.append(assunto),
    )

    with app.app_context():
        user = _user(name='Ja Pagou')
        product = _product()
        order = Order(user_id=user.id, created_at=utcnow() - timedelta(hours=30))
        db.session.add(order)
        db.session.commit()
        db.session.add_all([
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                item_name=product.name,
                quantity=1,
                unit_price=100,
            ),
            Payment(
                user_id=user.id,
                order_id=order.id,
                method=PaymentMethod.PIX,
                status=PaymentStatus.COMPLETED,
                amount=100,
            ),
        ])
        db.session.commit()

        app_module.enviar_lembretes_carrinho_abandonado()
        assert enviados == []


# ------------------------------------------------------------ C1: home


def test_home_anuncia_preco_no_titulo(app, client):
    body = client.get('/').data.decode()
    assert 'por veterinário' in body
    assert 'R$' in body
