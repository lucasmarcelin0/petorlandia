# test.py
from app import app, db
from models import DeliveryRequest, PickupLocation

with app.app_context():                           # <-- garante o contexto
    pickup = PickupLocation.query.filter_by(ativo=True).first()
    if not pickup:
        print("⚠️  Nenhum PickupLocation ativo no banco.")
    else:
        n = (DeliveryRequest.query
             .filter(DeliveryRequest.pickup_id.is_(None))
             .update({DeliveryRequest.pickup_id: pickup.id},
                     synchronize_session=False))
        db.session.commit()
        print(f"{n} entregas antigas atualizadas.")
