from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from flask_login import LoginManager
from flask_session import Session

db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
login = LoginManager()
session = Session()
