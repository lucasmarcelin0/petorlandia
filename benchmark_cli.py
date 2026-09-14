from app_factory import create_app
from extensions import db
from models.usuarios import User
from models.loja import Payment, PaymentMethod, PaymentStatus
from models.saude import HealthSubscription, HealthPlan
import time

app = create_app()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
app.config['TESTING'] = True

with app.app_context():
    # Setup test data
    db.create_all()
    user1 = User(name="Test User 1", email="test_bm_1234@example.com")
    user1.set_password("password")
    user2 = User(name="Test User 2", email="test_bm_2234@example.com")
    user2.set_password("password")
    db.session.add(user1)
    db.session.add(user2)
    db.session.commit()

    plan = HealthPlan(name="Plan 1", description="Test", price=10.0)
    db.session.add(plan)
    db.session.commit()

    # Add payments and subscriptions
    for i in range(100):
        p = Payment(user_id=user1.id, method=PaymentMethod.PIX, status=PaymentStatus.COMPLETED)
        db.session.add(p)
        db.session.commit()
        for j in range(20):
            # For this test, just assign animal_id 1 since it's integer field
            s = HealthSubscription(payment_id=p.id, animal_id=1, plan_id=plan.id, user_id=user1.id)
            db.session.add(s)
        db.session.commit()

    print("Data created")

    # Clear identity map so we start fresh
    db.session.expunge_all()

    # Benchmark original
    start = time.time()
    users = User.query.all()
    for user in users:
        for payment in Payment.query.filter_by(user_id=user.id).all():
            for subscription in list(payment.subscriptions):
                subscription.payment = None
            db.session.delete(payment)
    end = time.time()
    db.session.rollback()

    print(f"Original Time: {end - start:.4f}s")

    # Clear identity map again
    db.session.expunge_all()

    # Let's try with joinedload
    from sqlalchemy.orm import joinedload

    start = time.time()
    users = User.query.all()
    for user in users:
        for payment in Payment.query.filter_by(user_id=user.id).options(joinedload(Payment.subscriptions)).all():
            for subscription in list(payment.subscriptions):
                subscription.payment = None
            db.session.delete(payment)
    end = time.time()
    db.session.rollback()

    print(f"Optimized Time: {end - start:.4f}s")
