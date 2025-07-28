from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from flask_login import LoginManager
from flask_session import Session
from flask_babel import Babel
from flask_talisman import Talisman

db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
login = LoginManager()
session = Session()
babel = Babel()
# Allow inline styles and external resources by disabling the default
# Content-Security-Policy. Production deployments can override this
# using a custom configuration if stricter policies are desired.
talisman = Talisman(content_security_policy=None)
