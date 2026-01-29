import os
from datetime import timedelta


class Config:
    SECRET_KEY = "dev-key"  # substitua por uma variável segura em produção
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
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = 'gpt.assistente.orlandia@gmail.com'
    MAIL_PASSWORD = 'toso zrgb uuwx nzkp'  # Use a senha de app, não a senha normal da conta
    MAIL_DEFAULT_SENDER = ('PetOrlândia', 'gpt.assistente.orlandia@gmail.com')

    # Token de acesso do Mercado Pago usado na integração de pagamentos
    MERCADOPAGO_ACCESS_TOKEN = os.environ.get("MERCADOPAGO_ACCESS_TOKEN", "APP_USR-6670170005169574-071911-23502e25ef4bc98e3e2f9706cd082550-99814908")
    MERCADOPAGO_PUBLIC_KEY = os.environ.get("MERCADOPAGO_PUBLIC_KEY", "APP_USR-2b9a9bff-692b-4de8-9b90-ce9aa758ca14")
    MERCADOPAGO_WEBHOOK_SECRET = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET", "add6cb517c10e98c1decbe37a4290a41b45a9b3b1d04a5d368babd18a2969d44")

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
