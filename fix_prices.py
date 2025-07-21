from app import app
from models import db, OrderItem, Product

with app.app_context():
    items = OrderItem.query.filter_by(unit_price=None).all()
    for it in items:
        prod = Product.query.get(it.product_id)
        if prod and prod.price is not None:
            it.unit_price = prod.price
    db.session.commit()
    print(f"Corrigidos {len(items)} itens.")

