import re

from app import app
from models import User

TARGET = "31998160025"

with app.app_context():
    target_digits = re.sub(r"\D", "", TARGET)
    users = User.query.filter(User.phone.isnot(None)).all()
    matches = [
        u for u in users
        if re.sub(r"\D", "", u.phone or "").endswith(target_digits[-9:])
    ]
    for u in matches:
        print(u.id, "|", u.name, "|", u.email, "|", u.phone, "|", u.role)
    print("total_matches=", len(matches))
