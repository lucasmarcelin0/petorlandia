import os
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent


def _env_optional(name: str) -> Optional[str]:
    return os.environ.get(name) or None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_secret_key(project_root: Optional[Path] = None) -> str:
    env_secret = os.environ.get("SECRET_KEY")
    if env_secret:
        return env_secret

    root = project_root or PROJECT_ROOT
    secret_file = root / "config" / "secret_key"

    try:
        secret = secret_file.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        secret = secret_file.read_text(encoding="utf-8-sig").strip()
    except OSError:
        secret = ""

    if secret:
        return secret

    secret = secrets.token_hex(32)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secret, encoding="utf-8")
    except OSError:
        pass
    return secret


class Config:
    SECRET_KEY = _load_secret_key()
    # Lido exclusivamente da variável de ambiente (setada no Heroku em produção).
    # Sem ela (dev/local/CI), cai para um SQLite local — nunca uma credencial de
    # produção embutida no código.
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("SQLALCHEMY_DATABASE_URI")
    ) or (
        f"sqlite:///{(PROJECT_ROOT / 'petorlandia_dev.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Evita erros "server closed the connection unexpectedly" ao testar conexões do pool
    # Note: pool_size/max_overflow are added dynamically in app.py for PostgreSQL only
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    SESSION_TYPE = os.environ.get("SESSION_TYPE", "filesystem")
    SESSION_PERMANENT = True
    # Long-lived sessions increase the blast radius of a stolen cookie.
    PERMANENT_SESSION_LIFETIME = timedelta(
        days=int(os.environ.get("PERMANENT_SESSION_LIFETIME_DAYS", "30"))
    )
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    WTF_CSRF_TIME_LIMIT = int(os.environ.get("WTF_CSRF_TIME_LIMIT", "3600"))
    FORCE_HTTPS = _env_bool("FORCE_HTTPS", True)
    SECURITY_HEADERS_ENABLED = _env_bool("SECURITY_HEADERS_ENABLED", True)
    ALLOW_LOCAL_UPLOAD_FALLBACK = _env_bool("ALLOW_LOCAL_UPLOAD_FALLBACK", False)
    MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    CORS_ALLOWED_ORIGINS = tuple(
        origin.strip()
        for origin in os.environ.get(
            "CORS_ALLOWED_ORIGINS",
            "https://chatgpt.com,https://chat.openai.com,https://www.petorlandia.com.br,https://petorlandia.com.br",
        ).split(",")
        if origin.strip()
    )
    RATELIMIT_ENABLED = _env_bool("RATELIMIT_ENABLED", True)
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    OAUTH_AUTHORIZATION_CODE_EXPIRES_IN = int(os.environ.get("OAUTH_AUTHORIZATION_CODE_EXPIRES_IN", "300"))
    OAUTH_ACCESS_TOKEN_EXPIRES_IN = int(os.environ.get("OAUTH_ACCESS_TOKEN_EXPIRES_IN", "900"))
    OAUTH_REFRESH_TOKEN_EXPIRES_IN = int(os.environ.get("OAUTH_REFRESH_TOKEN_EXPIRES_IN", "2592000"))
    # Keep OAuth issuer/resource identifiers independent from the request Host
    # header. Production uses the verified public origin; tunnels and local
    # environments can opt in to their own origin with OAUTH_ISSUER.
    OAUTH_ISSUER = (
        os.environ.get("OAUTH_ISSUER") or "https://www.petorlandia.com.br"
    ).rstrip("/")
    OAUTH_ALLOWED_SCOPES = os.environ.get(
        "OAUTH_ALLOWED_SCOPES",
        (
            "openid profile email pets:read pets:write appointments:read appointments:write "
            "tutors:read tutors:write consultations:read consultations:write "
            "prescriptions:read exams:read exams:write vaccines:read "
            "clinical_summary:read handoff:read tutor_guidance:generate"
        ),
    )

    # Performance: cache static files longer outside debug. Versioned URLs can
    # be cached aggressively by browsers/proxies without slowing deploy fixes.
    _STATIC_CACHE_DEFAULT = "3600" if _env_bool("FLASK_DEBUG", False) else "604800"
    SEND_FILE_MAX_AGE_DEFAULT = int(os.environ.get("SEND_FILE_MAX_AGE_DEFAULT", _STATIC_CACHE_DEFAULT))
    SEND_FILE_VERSIONED_MAX_AGE = int(os.environ.get("SEND_FILE_VERSIONED_MAX_AGE", "31536000"))

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
    SUPPORT_EMAIL = _env_optional("SUPPORT_EMAIL") or _mail_sender_email
    SUPPORT_PHONE = _env_optional("SUPPORT_PHONE")
    MAIL_DEFAULT_SENDER = (
        (os.environ.get("MAIL_DEFAULT_SENDER_NAME", "PetOrlândia"), _mail_sender_email)
        if _mail_sender_email
        else None
    )

    # Google Analytics 4 (medição de visitantes). Sem o ID definido, nenhum
    # script de analytics é carregado nas páginas.
    GA_MEASUREMENT_ID = _env_optional("GA_MEASUREMENT_ID")

    # E-mail que recebe o aviso de novas solicitações (pedidos pagos,
    # agendamentos). Sem valor definido, nenhum aviso é enviado.
    ADMIN_NOTIFY_EMAIL = _env_optional("ADMIN_NOTIFY_EMAIL")

    # Web Push (VAPID). Sem as chaves o push fica desativado silenciosamente.
    VAPID_PUBLIC_KEY = _env_optional("VAPID_PUBLIC_KEY")
    VAPID_PRIVATE_KEY = _env_optional("VAPID_PRIVATE_KEY")
    VAPID_CLAIM_EMAIL = _env_optional("VAPID_CLAIM_EMAIL")

    # Token de acesso do Mercado Pago usado na integração de pagamentos
    MERCADOPAGO_ACCESS_TOKEN = _env_optional("MERCADOPAGO_ACCESS_TOKEN")
    MERCADOPAGO_PUBLIC_KEY = _env_optional("MERCADOPAGO_PUBLIC_KEY")
    MERCADOPAGO_WEBHOOK_SECRET = _env_optional("MERCADOPAGO_WEBHOOK_SECRET")
    MERCADOPAGO_CLIENT_ID = _env_optional("MERCADOPAGO_CLIENT_ID")
    MERCADOPAGO_CLIENT_SECRET = _env_optional("MERCADOPAGO_CLIENT_SECRET")
    MERCADOPAGO_OAUTH_REDIRECT_URI = _env_optional("MERCADOPAGO_OAUTH_REDIRECT_URI")
    MERCADOPAGO_OAUTH_USE_PKCE = _env_bool("MERCADOPAGO_OAUTH_USE_PKCE", True)
    MERCADOPAGO_MARKETPLACE_FEE_PERCENT = float(
        os.environ.get("MERCADOPAGO_MARKETPLACE_FEE_PERCENT", "0")
    )

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

    # Missing integration credentials disable the endpoint instead of
    # authorizing every caller.
    INSURER_PORTAL_TOKEN = _env_optional("INSURER_PORTAL_TOKEN")

    NFSE_ASYNC_MUNICIPIOS = [
        item.strip()
        for item in os.environ.get("NFSE_ASYNC_MUNICIPIOS", "orlandia,belo horizonte,contagem").split(",")
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
        "contagem": {
            "deadline_days": int(os.environ.get("NFSE_CANCEL_DEADLINE_CONTAGEM", "30")),
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

    NFSE_NACIONAL_API = {
        "environment": os.environ.get("NFSE_NACIONAL_ENV", "producao_restrita"),
        "base_url": os.environ.get(
            "NFSE_NACIONAL_BASE_URL",
            "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
        ),
        "production_base_url": os.environ.get(
            "NFSE_NACIONAL_PRODUCTION_BASE_URL",
            "https://sefin.nfse.gov.br/SefinNacional",
        ),
        "timeout": int(os.environ.get("NFSE_NACIONAL_TIMEOUT", "30")),
        "nfse_path": os.environ.get("NFSE_NACIONAL_NFSE_PATH", "/nfse"),
        "dps_path": os.environ.get("NFSE_NACIONAL_DPS_PATH", "/dps/{id}"),
        "eventos_path": os.environ.get(
            "NFSE_NACIONAL_EVENTOS_PATH",
            "/nfse/{chave_acesso}/eventos",
        ),
    }

    NFSE_NACIONAL_XML = {
        "ambiente": os.environ.get("NFSE_NACIONAL_AMBIENTE", "2"),
        "versao": os.environ.get("NFSE_NACIONAL_VERSAO", "1.01"),
        "ver_aplic": os.environ.get("NFSE_NACIONAL_VER_APLIC", "Petorlandia-1.0"),
        "signature_algorithm": os.environ.get(
            "NFSE_NACIONAL_SIGNATURE_ALGORITHM",
            "rsa-sha1",
        ),
        "digest_algorithm": os.environ.get("NFSE_NACIONAL_DIGEST_ALGORITHM", "sha1"),
    }
