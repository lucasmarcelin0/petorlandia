from contextlib import nullcontext

from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from flask_login import LoginManager
from flask_session import Session
from flask_babel import Babel

class TestingAwareSQLAlchemy(SQLAlchemy):
    """SQLAlchemy helper that drops tables before ``create_all`` in tests."""

    def create_all(self, bind="__all__", app=None, **_kwargs):  # type: ignore[override]
        app_obj = app or current_app
        ctx = app.app_context() if app is not None else nullcontext()
        with ctx:
            if app_obj and app_obj.config.get("TESTING"):
                uri = str(app_obj.config.get("SQLALCHEMY_DATABASE_URI", ""))
                if uri.startswith("sqlite"):
                    super().drop_all(bind_key=bind)
            return super().create_all(bind_key=bind)


db = TestingAwareSQLAlchemy()
migrate = Migrate()
mail = Mail()
login = LoginManager()
session = Session()
babel = Babel()
