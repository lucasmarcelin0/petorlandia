import os
from datetime import timedelta

from config_utils import normalize_database_uri


class Config:
    SECRET_KEY = "dev-key"  # substitua por uma variável segura em produção

    _DATABASE_PROFILE = os.environ.get("DATABASE_PROFILE", "local").strip().lower()
    _PRODUCTION_DATABASE_URI = (
        "postgresql://u82pgjdcmkbq7v:p0204cb9289674b66bfcbb9248eaf9d6a71e2dece2722fe22d6bd976c77b411e6@"
        "c2hbg00ac72j9d.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d2nnmcuqa8ljli"
    )
    _QA_DATABASE_URI = os.environ.get("QA_DATABASE_URI")
    _LOCAL_DATABASE_URI = os.environ.get(
        "LOCAL_DATABASE_URI",
        "postgresql://petorlandia:petorlandia@localhost:5432/petorlandia",
    )

    @classmethod
    def _resolve_database_uri(cls):
        explicit_uri = os.environ.get("SQLALCHEMY_DATABASE_URI")
        if explicit_uri:
            return explicit_uri

        profile = cls._DATABASE_PROFILE
        if profile in {"prod", "production"}:
            return cls._PRODUCTION_DATABASE_URI
        if profile in {"qa", "staging"}:
            return cls._QA_DATABASE_URI or cls._PRODUCTION_DATABASE_URI
        return cls._LOCAL_DATABASE_URI

    SQLALCHEMY_DATABASE_URI = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Evita erros "server closed the connection unexpectedly" ao testar conexões do pool
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    SESSION_TYPE = "filesystem"
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)

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


# Late binding ensures the helper can access the fully defined class.
Config.SQLALCHEMY_DATABASE_URI = normalize_database_uri(Config._resolve_database_uri())
