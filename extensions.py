from contextlib import nullcontext
from datetime import datetime, timezone

from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from flask_login import LoginManager
from flask_session import Session
from flask_babel import Babel
from sqlalchemy import event, inspect

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


@event.listens_for(db.session, "before_flush")
def _prevent_not_null_violations(session, _flush_context, _instances):
    """Fail fast when a new row misses ``nullable=False`` fields.

    This guards against runtime ``NOT NULL`` violations by checking new objects
    before SQL is emitted. Columns with an explicit default or server default
    are ignored so that database/populated defaults can still apply normally.
    """

    for obj in session.new:
        state = inspect(obj)
        mapper = state.mapper
        missing = []

        for column in mapper.columns:
            if column.nullable or column.primary_key:
                continue
            if column.default is not None or column.server_default is not None:
                continue
            value = getattr(obj, column.key, None)
            if value is None:
                if column.foreign_keys:
                    related = None
                    for rel in mapper.relationships:
                        if column in rel.local_columns:
                            related = getattr(obj, rel.key, None)
                            if rel.uselist:
                                related = related or None
                            break
                    if related is not None:
                        continue
                missing.append(column.key)

        if missing:
            model_name = mapper.class_.__name__
            columns = ", ".join(missing)
            raise ValueError(f"{model_name} requires values for: {columns}")


# Register event listener to ensure datetime columns always have timezone info
@event.listens_for(db.Model, "load", propagate=True)
def _receive_load(target, context):
    """Convert naive datetimes from DateTime(timezone=True) columns to UTC-aware."""
    try:
        mapper = inspect(type(target))
        if mapper is None:
            return
        
        for column in mapper.columns:
            # Check if this is a datetime column
            col_type_str = str(column.type)
            if 'DATETIME' not in col_type_str.upper():
                continue
            
            attr_name = column.key
            value = getattr(target, attr_name, None)
            
            # If naive, assume UTC and set the timezone
            if isinstance(value, datetime) and value.tzinfo is None:
                setattr(target, attr_name, value.replace(tzinfo=timezone.utc))
    except Exception:
        # Silently ignore any errors
        pass
