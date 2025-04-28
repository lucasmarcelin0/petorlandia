from app import app, db
from models import *

with app.app_context():
    db.create_all()
    print("Tabelas criadas no petorlandia.db com sucesso!")
