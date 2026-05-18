import os

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

from extensions import db
from models import CasaDeRacao, GroomingPlan, User


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def test_feed_store_owner_can_create_grooming_plan(app, client, monkeypatch):
    with app.app_context():
        owner = User(name="Lojista", email="lojista-planos@example.com")
        owner.set_password("x")
        db.session.add(owner)
        db.session.flush()
        casa = CasaDeRacao(nome="Racoes e Banho", owner_id=owner.id, status="ativa")
        db.session.add(casa)
        db.session.commit()
        _login(monkeypatch, owner)

        resp = client.post(
            f"/casa-de-racao/{casa.id}/planos/tosa",
            data={
                "name": "Banho Mensal",
                "description": "Quatro banhos por mes",
                "service_type": "banho",
                "price": "89.90",
                "sessions_per_month": "4",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        plan = GroomingPlan.query.filter_by(casa_de_racao_id=casa.id).one()
        assert plan.name == "Banho Mensal"
        assert plan.clinica_id is None
        assert plan.provider_name == casa.nome
