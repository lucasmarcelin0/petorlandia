from routes.app import app, db
from models import Payment

with app.app_context():
    pagamentos = Payment.query.filter(Payment.amount == None).all()
    for p in pagamentos:
        if p.order:
            p.amount = p.order.total_value()
        else:
            p.amount = 0
    db.session.commit()
