from contextlib import nullcontext
from datetime import datetime, timezone
import logging
from weakref import WeakKeyDictionary

from flask import current_app, g, has_request_context, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from flask_login import LoginManager
from flask_session import Session
from flask_babel import Babel
from sqlalchemy import event, inspect

# Cache for datetime column names per model class (performance optimization)
_datetime_columns_cache: WeakKeyDictionary = WeakKeyDictionary()


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


class RequestContextFilter(logging.Filter):
    """Attach request context metadata to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if has_request_context():
            record.request_id = getattr(g, "request_id", None)
            record.path = request.path
            record.method = request.method
        else:
            record.request_id = "-"
            record.path = "-"
            record.method = "-"
        return True


def configure_logging(app) -> None:
    """Configure structured logging for the application."""
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "ts=%(asctime)s level=%(levelname)s logger=%(name)s "
        "msg=%(message)s request_id=%(request_id)s method=%(method)s path=%(path)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestContextFilter())
    handler.petorlandia_handler = True

    if not any(getattr(existing, "petorlandia_handler", False) for existing in app.logger.handlers):
        app.logger.addHandler(handler)

    app.logger.setLevel(app.config.get("LOG_LEVEL", "INFO"))
    app.logger.propagate = False


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


def _get_datetime_columns(model_class):
    """Return cached list of datetime column names for a model class."""
    if model_class in _datetime_columns_cache:
        return _datetime_columns_cache[model_class]

    try:
        mapper = inspect(model_class)
        if mapper is None:
            return ()
        datetime_cols = tuple(
            column.key
            for column in mapper.columns
            if 'DATETIME' in str(column.type).upper()
        )
        _datetime_columns_cache[model_class] = datetime_cols
        return datetime_cols
    except Exception:
        return ()


# Register event listener to ensure datetime columns always have timezone info
@event.listens_for(db.Model, "load", propagate=True)
def _receive_load(target, context):
    """Convert naive datetimes from DateTime(timezone=True) columns to UTC-aware.

    Uses cached column names per model class for better performance.
    """
    try:
        datetime_columns = _get_datetime_columns(type(target))
        if not datetime_columns:
            return

        for attr_name in datetime_columns:
            value = getattr(target, attr_name, None)
            # If naive, assume UTC and set the timezone
            if isinstance(value, datetime) and value.tzinfo is None:
                setattr(target, attr_name, value.replace(tzinfo=timezone.utc))
    except Exception:
        # Silently ignore any errors
        pass
