from flask_migrate import Migrate, upgrade, migrate, init
from petorlandia.app import app, db

import os

with app.app_context():
    if not os.path.exists('migrations'):
        init()
    migrate(message="Atualizando banco de dados via models.py")
    upgrade()
