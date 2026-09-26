from datetime import datetime, timezone

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.health_plan import _serialize_usage_timestamp
from time_utils import BR_TZ


def test_usage_timestamp_serialization_produces_utc_iso_and_localized_dt():
    naive_local = datetime(2025, 12, 22, 15, 30)

    utc_iso, localized = _serialize_usage_timestamp(naive_local)

    # API/JS should receive explicit timezone info (UTC with Z suffix)
    assert utc_iso.endswith("Z")
    parsed_utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    assert parsed_utc.tzinfo == timezone.utc
    # Local -> UTC adds 3h during standard time in Sao Paulo
    assert parsed_utc.hour == 18

    # Server-side formatting keeps the local Sao Paulo clock time
    assert localized.tzinfo == BR_TZ
    assert localized.hour == naive_local.hour


def test_coverage_limit_counts_prior_items_in_same_consulta(app):
    from decimal import Decimal

    from extensions import db
    from models import (
        Animal,
        Consulta,
        HealthCoverage,
        HealthPlan,
        HealthSubscription,
        OrcamentoItem,
        User,
    )
    from services.health_plan import evaluate_consulta_coverages

    with app.app_context():
        tutor = User(name='Tutor', email='coverage-limit@example.com', password_hash='x')
        vet = User(name='Veterinário', email='vet-coverage-limit@example.com', password_hash='x')
        db.session.add_all([tutor, vet])
        db.session.flush()
        animal = Animal(name='Rex', user_id=tutor.id, modo='pessoal')
        plan = HealthPlan(name='Plano', price=100)
        db.session.add_all([animal, plan])
        db.session.flush()
        subscription = HealthSubscription(
            animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True
        )
        coverage = HealthCoverage(
            plan_id=plan.id,
            procedure_code='consulta',
            name='Consulta',
            monetary_limit=Decimal('100.00'),
            limit_period='lifetime',
        )
        db.session.add_all([subscription, coverage])
        db.session.flush()
        consulta = Consulta(
            animal_id=animal.id,
            created_by=vet.id,
            health_subscription_id=subscription.id,
        )
        db.session.add(consulta)
        db.session.flush()
        for description in ('Primeiro', 'Segundo'):
            db.session.add(
                OrcamentoItem(
                    consulta_id=consulta.id,
                    descricao=description,
                    valor=Decimal('60.00'),
                    clinica_id=1,
                    coverage=coverage,
                )
            )
        db.session.flush()

        result = evaluate_consulta_coverages(consulta)

        assert result['status'] == 'denied'
        assert [item.coverage_status for item in consulta.orcamento_items] == [
            'approved', 'limit_exceeded'
        ]
