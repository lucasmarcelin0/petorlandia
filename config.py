import os

SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///petorlandia.db")

# Corrigir Heroku PostgreSQL URL (caso necessário)
if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
