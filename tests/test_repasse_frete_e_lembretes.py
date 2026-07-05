import os
import sys
from datetime import timedelta
from decimal import Decimal

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import (
    app as flask_app,
    db,
    enviar_lembretes_recebimento,
    enviar_lembretes_tratamento,
)
from time_utils import now_in_brazil
from models import (
    Animal,
    BlocoPrescricao,
    Clinica,
    DeliveryRequest,
    Notification,
    Order,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Prescricao,
    TratamentoAcompanhamento,
    User,
    Veterinario,
)
from services.repasses import classificar_entrega, frete_da_entrega


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def _user(name, email, password='pw', **kwargs):
    user = User(name=name, email=email, **kwargs)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, email, password='pw'):
    resp = client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)
    assert resp.status_code == 200


def _setup_loja(app):
    """Clinica vendedora (frete 12), comprador, entregador e admin."""
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Loja Frete', modo_entrega='plataforma', valor_frete=Decimal('12.00'))
        db.session.add(clinica)
        db.session.flush()
        comprador = _user('Comprador', 'comprador@example.com')
        entregador = _user('Entregador', 'entregador@example.com', worker='delivery')
        admin = _user('Admin', 'admin@example.com', role='admin')
        db.session.commit()
        return clinica.id, comprador.id, entregador.id, admin.id


def _pedido_com_entrega(clinica_id, comprador_id, entregador_id, status='em_andamento'):
    order = Order(user_id=comprador_id)
    db.session.add(order)
    db.session.flush()
    dr = DeliveryRequest(
        order_id=order.id,
        requested_by_id=comprador_id,
        worker_id=entregador_id,
        clinica_id=clinica_id,
        tipo_entrega='plataforma',
        status=status,
        accepted_at=now_in_brazil(),
    )
    if status == 'concluida':
        dr.completed_at = now_in_brazil()
    db.session.add(dr)
    db.session.flush()
    return order, dr


def test_complete_delivery_congela_frete_e_notifica(app):
    clinica_id, comprador_id, entregador_id, _ = _setup_loja(app)
    with app.app_context():
        _, dr = _pedido_com_entrega(clinica_id, comprador_id, entregador_id)
        db.session.commit()
        dr_id = dr.id

    client = app.test_client()
    with client:
        _login(client, 'entregador@example.com')
        resp = client.post(f'/delivery_requests/{dr_id}/complete')
        assert resp.status_code in (200, 302)

    with app.app_context():
        dr = db.session.get(DeliveryRequest, dr_id)
        assert dr.status == 'concluida'
        assert dr.frete_valor == Decimal('12.00')
        aviso = Notification.query.filter_by(user_id=comprador_id, kind='order_receipt').first()
        assert aviso is not None
        assert 'Confirme' in aviso.message or 'confirme' in aviso.message
        db.drop_all()


def test_classificacao_e_pagamento_semanal(app):
    clinica_id, comprador_id, entregador_id, _ = _setup_loja(app)
    with app.app_context():
        order_ok, dr_ok = _pedido_com_entrega(clinica_id, comprador_id, entregador_id, status='concluida')
        order_pend, dr_pend = _pedido_com_entrega(clinica_id, comprador_id, entregador_id, status='concluida')
        order_ok.received_at = now_in_brazil()  # tutor confirmou só o primeiro
        db.session.commit()
        assert classificar_entrega(dr_ok) == 'liberado'
        assert classificar_entrega(dr_pend) == 'aguardando'
        assert frete_da_entrega(dr_pend) == Decimal('12.00')
        dr_ok_id, dr_pend_id = dr_ok.id, dr_pend.id

    client = app.test_client()
    with client:
        _login(client, 'admin@example.com')
        resp = client.get('/admin/repasses-frete')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Liberado' in html
        assert 'Aguardando confirma' in html

        resp = client.post(f'/admin/repasses-frete/pagar/{entregador_id}')
        assert resp.status_code == 302

    with app.app_context():
        dr_ok = db.session.get(DeliveryRequest, dr_ok_id)
        dr_pend = db.session.get(DeliveryRequest, dr_pend_id)
        assert dr_ok.frete_pago_em is not None       # confirmado → pago
        assert dr_pend.frete_pago_em is None         # sem confirmação → retido
        db.drop_all()


def test_repasses_requer_admin(app):
    clinica_id, comprador_id, entregador_id, _ = _setup_loja(app)
    client = app.test_client()
    with client:
        _login(client, 'comprador@example.com')
        assert client.get('/admin/repasses-frete').status_code in (403, 404)
    with app.app_context():
        db.drop_all()


def test_lembrete_recebimento_job(app):
    clinica_id, comprador_id, entregador_id, _ = _setup_loja(app)
    with app.app_context():
        order, _ = _pedido_com_entrega(clinica_id, comprador_id, entregador_id, status='concluida')
        pagamento = Payment(
            order_id=order.id,
            user_id=comprador_id,
            method=PaymentMethod.PIX,
            status=PaymentStatus.COMPLETED,
            amount=Decimal('50.00'),
            created_at=now_in_brazil() - timedelta(days=3),
        )
        db.session.add(pagamento)
        db.session.commit()
        order_id = order.id

    enviar_lembretes_recebimento()

    with app.app_context():
        order = db.session.get(Order, order_id)
        assert order.receipt_reminder_at is not None
        lembretes = Notification.query.filter_by(user_id=comprador_id, kind='order_receipt').count()
        assert lembretes == 1

    # Rodar de novo no mesmo dia não duplica o lembrete
    enviar_lembretes_recebimento()
    with app.app_context():
        assert Notification.query.filter_by(user_id=comprador_id, kind='order_receipt').count() == 1
        # Depois de confirmar, não lembra mais
        order = db.session.get(Order, order_id)
        order.received_at = now_in_brazil()
        order.receipt_reminder_at = now_in_brazil() - timedelta(days=10)
        db.session.commit()
    enviar_lembretes_recebimento()
    with app.app_context():
        assert Notification.query.filter_by(user_id=comprador_id, kind='order_receipt').count() == 1
        db.drop_all()


def test_lembrete_tratamento_job(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica Lembrete')
        db.session.add(clinica)
        db.session.flush()
        vet = _user('Vet', 'vet@example.com', worker='veterinario', role='admin')
        db.session.add(Veterinario(user=vet, crmv='SP-1', clinica=clinica))
        tutor = _user('Tutor', 'tutor@example.com')
        animal = Animal(name='Mel', owner=tutor, clinica=clinica)
        db.session.add(animal)
        db.session.flush()
        bloco = BlocoPrescricao(animal=animal, saved_by=vet, clinica=clinica)
        db.session.add(bloco)
        db.session.flush()
        db.session.add(Prescricao(
            animal_id=animal.id, bloco_id=bloco.id,
            medicamento='Antibiotico', frequencia='BID', duracao='7 dias',
        ))
        db.session.commit()

        from services.tratamento import criar_acompanhamento
        # Início ontem → doses de ontem pendentes = atrasadas hoje
        acompanhamento = criar_acompanhamento(bloco, vet, now_in_brazil() - timedelta(days=1))
        db.session.commit()
        tutor_id = tutor.id
        acomp_id = acompanhamento.id

    enviar_lembretes_tratamento()

    with app.app_context():
        aviso = Notification.query.filter_by(user_id=tutor_id, kind='treatment_reminder').first()
        assert aviso is not None
        assert 'Mel' in aviso.message
        assert f'/tratamento/{acomp_id}' in aviso.message

        # Tratamento concluído não gera lembrete
        Notification.query.delete()
        acomp = db.session.get(TratamentoAcompanhamento, acomp_id)
        acomp.status = 'concluido'
        db.session.commit()
    enviar_lembretes_tratamento()
    with app.app_context():
        assert Notification.query.filter_by(user_id=tutor_id, kind='treatment_reminder').count() == 0
        db.drop_all()
