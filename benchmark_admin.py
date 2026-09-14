import time
from app_factory import create_app
from models import db, User, DeliveryRequest, Order

app = create_app()
app.config['SERVER_NAME'] = 'localhost'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

with app.app_context():
    db.create_all()

    # Create dummy users
    admin = User(name='Admin', email='admin@test.com', role='admin')
    admin.set_password('123')
    db.session.add(admin)

    # Create dummy users for requested_by
    users = []
    for i in range(20):
        u = User(name=f'User {i}', email=f'user{i}@test.com', role='tutor')
        u.set_password('123')
        db.session.add(u)
        users.append(u)
    db.session.commit()

    # Create dummy orders
    orders = []
    for i in range(20):
        o = Order(user_id=users[i].id)
        db.session.add(o)
        orders.append(o)
    db.session.commit()

    # Create dummy delivery requests
    for i in range(20):
        dr = DeliveryRequest(order_id=orders[i].id, requested_by_id=users[i].id)
        db.session.add(dr)
    db.session.commit()

    from sqlalchemy.orm import joinedload

    def benchmark_unoptimized():
        start = time.time()
        for dr in DeliveryRequest.query.order_by(DeliveryRequest.requested_at.desc()).limit(10):
            solicitante = dr.requested_by.name if dr.requested_by else '—'
        end = time.time()
        return end - start

    def benchmark_optimized():
        start = time.time()
        for dr in DeliveryRequest.query.options(joinedload(DeliveryRequest.requested_by)).order_by(DeliveryRequest.requested_at.desc()).limit(10):
            solicitante = dr.requested_by.name if dr.requested_by else '—'
        end = time.time()
        return end - start

    # Clear caches
    db.session.expunge_all()

    # Run multiple times to get average
    unopt_time = 0
    opt_time = 0
    runs = 100
    for _ in range(runs):
        db.session.expunge_all()
        unopt_time += benchmark_unoptimized()
        db.session.expunge_all()
        opt_time += benchmark_optimized()

    print(f"Average time per run (Unoptimized): {unopt_time/runs:.6f} seconds")
    print(f"Average time per run (Optimized):   {opt_time/runs:.6f} seconds")
    if opt_time < unopt_time:
        print(f"Improvement: {((unopt_time - opt_time) / unopt_time) * 100:.2f}% faster")
