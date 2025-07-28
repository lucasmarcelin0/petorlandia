import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI")

    # Ensure SSL is used when connecting to PostgreSQL if no sslmode is provided
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
        if "sslmode=" not in SQLALCHEMY_DATABASE_URI:
            separator = "&" if "?" in SQLALCHEMY_DATABASE_URI else "?"
            SQLALCHEMY_DATABASE_URI += f"{separator}sslmode=require"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_TYPE = "filesystem"
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
    SESSION_COOKIE_SECURE = bool(int(os.environ.get("SESSION_COOKIE_SECURE", "1")))
    SESSION_COOKIE_HTTPONLY = bool(int(os.environ.get("SESSION_COOKIE_HTTPONLY", "1")))

    # Flask-Mail settings
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = bool(int(os.environ.get("MAIL_USE_TLS", "1")))
    MAIL_USE_SSL = bool(int(os.environ.get("MAIL_USE_SSL", "0")))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = (
        os.environ.get("MAIL_DEFAULT_SENDER_NAME", "PetOrlândia"),
        os.environ.get("MAIL_DEFAULT_SENDER_EMAIL", "noreply@example.com"),
    )

    # Mercado Pago credentials
    MERCADOPAGO_ACCESS_TOKEN = os.environ.get("MERCADOPAGO_ACCESS_TOKEN")
    MERCADOPAGO_PUBLIC_KEY = os.environ.get("MERCADOPAGO_PUBLIC_KEY")
    MERCADOPAGO_WEBHOOK_SECRET = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET")

    MERCADOPAGO_STATEMENT_DESCRIPTOR = os.environ.get(
        "MERCADOPAGO_STATEMENT_DESCRIPTOR", "PETORLANDIA"
    )
    MERCADOPAGO_BINARY_MODE = bool(int(os.environ.get("MERCADOPAGO_BINARY_MODE", "0")))

    # Default pickup address
    DEFAULT_PICKUP_ADDRESS = os.environ.get("DEFAULT_PICKUP_ADDRESS", "Rua Nove, 990")
