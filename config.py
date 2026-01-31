import os
from typing import Optional
from datetime import timedelta


def _env_optional(name: str) -> Optional[str]:
    return os.environ.get(name) or None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://u82pgjdcmkbq7v:p0204cb9289674b66bfcbb9248eaf9d6a71e2dece2722fe22d6bd976c77b411e6@c2hbg00ac72j9d.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d2nnmcuqa8ljli",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Evita erros "server closed the connection unexpectedly" ao testar conexões do pool
    # Note: pool_size/max_overflow are added dynamically in app.py for PostgreSQL only
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    SESSION_TYPE = "filesystem"
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
    WTF_CSRF_TIME_LIMIT = None  # CSRF token valid for entire session lifetime

    # Performance: cache static files for 1 hour (overridden by env var for dev)
    SEND_FILE_MAX_AGE_DEFAULT = int(os.environ.get("SEND_FILE_MAX_AGE_DEFAULT", "3600"))

    # Performance: disable template auto-reload unless in debug mode
    TEMPLATES_AUTO_RELOAD = os.environ.get("TEMPLATES_AUTO_RELOAD", "").lower() in ("1", "true", "yes")

    # Configurações do Flask-Mail (Gmail)
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = _env_optional("MAIL_USERNAME")
    MAIL_PASSWORD = _env_optional("MAIL_PASSWORD")
    _mail_sender_email = _env_optional("MAIL_DEFAULT_SENDER_EMAIL")
    MAIL_DEFAULT_SENDER = (
        (os.environ.get("MAIL_DEFAULT_SENDER_NAME", "PetOrlândia"), _mail_sender_email)
        if _mail_sender_email
        else None
    )

    # Token de acesso do Mercado Pago usado na integração de pagamentos
    MERCADOPAGO_ACCESS_TOKEN = _env_optional("MERCADOPAGO_ACCESS_TOKEN")
    MERCADOPAGO_PUBLIC_KEY = _env_optional("MERCADOPAGO_PUBLIC_KEY")
    MERCADOPAGO_WEBHOOK_SECRET = _env_optional("MERCADOPAGO_WEBHOOK_SECRET")

    # Opções adicionais de integração com o Mercado Pago
    MERCADOPAGO_STATEMENT_DESCRIPTOR = os.environ.get("MERCADOPAGO_STATEMENT_DESCRIPTOR", "PETORLANDIA")
    MERCADOPAGO_BINARY_MODE = bool(int(os.environ.get("MERCADOPAGO_BINARY_MODE", "0")))
    MERCADOPAGO_NOTIFICATION_URL = os.environ.get("MERCADOPAGO_NOTIFICATION_URL")

    # URLs gerados com ``url_for(..., _external=True)`` agora usam HTTPS por padrão,
    # garantindo que endpoints como o webhook do Mercado Pago sejam aceitos.
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "https")

    # Habilita validação de plano de saúde para agendamentos
    REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT = bool(
        int(os.environ.get("REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT", "0"))
    )

    # Endereço de retirada padrão (usado se não houver PickupLocation no banco)
    DEFAULT_PICKUP_ADDRESS = os.environ.get("DEFAULT_PICKUP_ADDRESS", "Rua Nove, 990")

    # Política padrão de retorno em dias para consultas
    DEFAULT_RETURN_DAYS = int(os.environ.get("DEFAULT_RETURN_DAYS", "7"))

    # Prazo padrão (em horas) para confirmação de solicitações de exame
    EXAM_CONFIRM_DEFAULT_HOURS = int(
        os.environ.get("EXAM_CONFIRM_DEFAULT_HOURS", "2")
    )

    VETERINARIAN_TRIAL_DAYS = int(os.environ.get("VETERINARIAN_TRIAL_DAYS", "30"))
    VETERINARIAN_MEMBERSHIP_PRICE = float(
        os.environ.get("VETERINARIAN_MEMBERSHIP_PRICE", "60.00")
    )
    VETERINARIAN_MEMBERSHIP_BILLING_DAYS = int(
        os.environ.get("VETERINARIAN_MEMBERSHIP_BILLING_DAYS", "30")
    )

    INSURER_PORTAL_TOKEN = os.environ.get("INSURER_PORTAL_TOKEN", "petorlandia-insurer")

    NFSE_ASYNC_MUNICIPIOS = [
        item.strip()
        for item in os.environ.get("NFSE_ASYNC_MUNICIPIOS", "orlandia,belo horizonte").split(",")
        if item.strip()
    ]

    # Regras de cancelamento/substituição por município (ajuste conforme regras oficiais).
    NFSE_CANCEL_RULES = {
        "orlandia": {
            "deadline_days": int(os.environ.get("NFSE_CANCEL_DEADLINE_ORLANDIA", "30")),
            "require_reason": True,
            "allowed_reasons": [],
        },
        "belo_horizonte": {
            "deadline_days": int(os.environ.get("NFSE_CANCEL_DEADLINE_BELO_HORIZONTE", "30")),
            "require_reason": True,
            "allowed_reasons": [],
        },
    }

    NFSE_BETHA_WSDL = {
        "recepcionar_lote_rps": os.environ.get("NFSE_BETHA_WSDL_RECEPCIONAR_LOTE_RPS", ""),
        "consultar_situacao_lote_rps": os.environ.get(
            "NFSE_BETHA_WSDL_CONSULTAR_SITUACAO_LOTE_RPS", ""
        ),
        "consultar_nfse_por_rps": os.environ.get("NFSE_BETHA_WSDL_CONSULTAR_NFSE_POR_RPS", ""),
        "cancelar_nfse": os.environ.get("NFSE_BETHA_WSDL_CANCELAR_NFSE", ""),
    }
