# ───────────────────────────  app.py  ───────────────────────────
import os, sys, pathlib, importlib, logging, uuid, re, secrets, hashlib, base64
import time as _stdlib_time
import subprocess
import requests
from collections import defaultdict, Counter
import math
from types import SimpleNamespace
from io import BytesIO, StringIO
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from functools import wraps
from urllib.parse import quote_plus, urlparse, parse_qs, urlencode
from typing import Iterable, Optional, Set, Dict

# Tests and factory imports may load this module through either name. Keep both
# aliases pointed at the same module so runtime monkeypatches and configuration
# changes do not split across two copies.
sys.modules["app"] = sys.modules[__name__]
sys.modules["petorlandia_app"] = sys.modules[__name__]



from datetime import datetime, timezone, date, timedelta, time
from dateutil.relativedelta import relativedelta
from PIL import Image, ImageOps


from apscheduler.schedulers.background import BackgroundScheduler
import click
from dotenv import load_dotenv
from flask import (
    Flask,
    g,
    session,
    send_from_directory,
    send_file,
    abort,
    request,
    jsonify,
    flash,
    render_template,
    redirect,
    url_for,
    current_app,
    has_request_context,
    make_response,
)
from flask_wtf.csrf import CSRFError, generate_csrf
from flask.cli import with_appcontext
from flask_cors import CORS
from flask_socketio import SocketIO, disconnect, emit, join_room, leave_room
# Twilio não é usado hoje (WhatsApp é via links wa.me); import lazy dentro de
# _send_share_sms/enviar_mensagem_whatsapp para não pagar o custo no boot.
# O placeholder mantém o atributo no módulo para monkeypatch de testes.
Client = None  # resolvido em runtime: twilio.rest.Client
from itsdangerous import URLSafeTimedSerializer
from jinja2 import TemplateNotFound
from authlib.jose import JsonWebKey, jwt
import json
import csv
import unicodedata
try:
    from document_utils import format_cnpj as format_cnpj_value, only_digits
except ImportError:
    from .document_utils import format_cnpj as format_cnpj_value, only_digits
from sqlalchemy import func, or_, exists, and_, case, true, false, inspect, text, cast, Text
from sqlalchemy.exc import IntegrityError, NoSuchTableError, OperationalError, ProgrammingError
from sqlalchemy.orm import joinedload, selectinload, aliased, defer, load_only

# ----------------------------------------------------------------
# 1)  Alias único para “models”
# ----------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    models_pkg = importlib.import_module("models")
except ModuleNotFoundError:
    models_pkg = importlib.import_module("petorlandia.models")
sys.modules["models"] = models_pkg
sys.modules.setdefault("petorlandia.models", models_pkg)


def _alias_model_modules(source_prefix: str, target_prefix: str) -> None:
    for module_name, module in list(sys.modules.items()):
        if module_name.startswith(f"{source_prefix}."):
            alias = module_name.replace(source_prefix, target_prefix, 1)
            sys.modules.setdefault(alias, module)


if models_pkg.__name__ == "models":
    _alias_model_modules("models", "petorlandia.models")
else:
    _alias_model_modules("petorlandia.models", "models")

# 📌 Expose every model name (CamelCase) globally
globals().update({
    name: obj
    for name, obj in models_pkg.__dict__.items()
    if name[:1].isupper()          # naive check: classes start with capital
})

from models import (
    AccountingAccount,
    DataShareAccess,
    DataSharePartyType,
    DataShareRequest,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalCertificate,
    FiscalEvent,
    PlantonistaEscala,
    PlantaoModelo,
    NfseIssue,
    NfseXml,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthAccessToken,
    OAuthConsent,
    OAuthJwkKey,
    OAuthRefreshToken,
    ProductVariant,
    StorePaymentAccount,
    User,
    Veterinario,
    clinica_has_column,
    get_clinica_field,
)
from models import CasaDeRacao, CasaDeRacaoHorario, CasaDeRacaoOnboardingInvite, PartnerInvite  # noqa: E402
from models import get_active_product_categories  # noqa: E402
from services.nfse_queue import (
    ensure_nfse_issue_for_consulta,
    get_nfse_cancel_rules,
    process_nfse_issue,
    process_nfse_queue,
    queue_nfse_issue,
    request_nfse_cancel,
    request_nfse_substitution,
    should_emit_async,
    validate_nfse_cancel_request,
)
from services.nfse_service import _normalize_municipio
from services.fiscal.certificate import parse_pfx
from services.fiscal.nfse_service import (
    NFSE_NACIONAL_MUNICIPIO_IBGE,
    NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY,
    VETERINARY_NFSE_SERVICE_DEFAULTS,
    build_nfse_payload_from_appointment,
    cancel_nfse_document,
    create_manual_nfse_document,
    create_nfse_draft_from_orcamento,
    create_nfse_document,
    queue_emit_nfse,
)
from services.billing.close_appointment import close_appointment
from services.appointments import (
    ReturnAppointmentDTO,
    finalize_consulta_flow,
    schedule_return_appointment,
)
from services.clinical_suggestions import (
    build_followup_prefill,
    log_suggestion_event,
    recommend_protocols,
)
from services.payments import (
    PaymentItemDTO,
    PaymentPreferenceDTO,
    apply_payment_to_bloco,
    apply_payment_to_orcamento,
    create_payment_preference,
)
from services.mercadopago_oauth import (
    MercadoPagoOAuthError,
    build_authorization_start,
    exchange_code_for_credentials,
    renew_due_store_accounts,
)
from security.crypto import (
    MissingMasterKeyError,
    decrypt_text_for_clinic,
    encrypt_bytes,
    encrypt_text,
)
from repositories import AppointmentRepository, ClinicRepository
_config_utils_module_name = (
    f"{__package__}.config_utils" if __package__ else "config_utils"
)
normalize_database_uri = importlib.import_module(
    _config_utils_module_name
).normalize_database_uri

# ----------------------------------------------------------------
# 2)  Flask app + config
# ----------------------------------------------------------------
load_dotenv()

app = Flask(
    __name__,
    instance_path=str(PROJECT_ROOT / "instance"),
    instance_relative_config=True,
)
app.config.from_object("config.Config")
app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_uri(
    app.config.get("SQLALCHEMY_DATABASE_URI")
)
# Add pool settings for PostgreSQL (not supported by SQLite)
_resolved_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
if _resolved_uri and ("postgresql" in _resolved_uri or "postgres" in _resolved_uri):
    engine_opts = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})
    engine_opts.setdefault("pool_size", 5)
    engine_opts.setdefault("max_overflow", 10)
    connect_args = dict(engine_opts.get("connect_args", {}))
    connect_args.setdefault("connect_timeout", 10)
    engine_opts["connect_args"] = connect_args
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts
elif _resolved_uri and _resolved_uri.startswith("sqlite"):
    engine_opts = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}))
    connect_args = dict(engine_opts.get("connect_args", {}))
    connect_args.pop("connect_timeout", None)
    if connect_args:
        engine_opts["connect_args"] = connect_args
    else:
        engine_opts.pop("connect_args", None)
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts
app.config.setdefault("FRONTEND_URL", "http://127.0.0.1:5000")
app.config.update(SESSION_PERMANENT=True, SESSION_TYPE="filesystem")
CORS(app, resources={
    r"/surpresa*": {"origins": "*"},
    r"/socket.io/*": {"origins": "*"},
    # OAuth 2.0 / OpenID Connect endpoints must be accessible from any origin
    # so that external clients (Claude, ChatGPT, etc.) can perform dynamic
    # client registration (RFC 7591) and token exchange (RFC 6749).
    r"/.well-known/*": {
        "origins": "*",
        "methods": ["GET", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
    },
    r"/oauth/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
    },
    # MCP server endpoint — Claude and ChatGPT connect here after OAuth
    r"/mcp": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Mcp-Session-Id", "MCP-Protocol-Version"],
        "expose_headers": ["WWW-Authenticate", "Mcp-Session-Id"],
    },
})
async_mode = os.getenv("SOCKETIO_ASYNC_MODE", "eventlet").strip().lower() or None
if async_mode == "eventlet":
    if sys.platform.startswith("win") and sys.version_info >= (3, 13):
        async_mode = "threading"
    else:
        try:
            import eventlet  # noqa: F401  # pragma: no cover - optional dependency
        except Exception:  # pragma: no cover - fallback when eventlet is unavailable/incompatible
            async_mode = "threading"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)

# ----------------------------------------------------------------
# 3)  Extensões
# ----------------------------------------------------------------

from extensions import (
    db,
    migrate,
    mail,
    login,
    session as session_ext,
    babel,
    csrf,
    configure_logging,
)
from flask_login import login_user, logout_user, current_user, login_required
from flask_mail import Message as MailMessage
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from werkzeug.routing import BuildError
from werkzeug.exceptions import HTTPException, NotFound
from time_utils import BR_TZ, coerce_to_brazil_tz, normalize_to_utc, now_in_brazil, utcnow
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

db.init_app(app)
migrate.init_app(app, db, compare_type=True)
mail.init_app(app)
login.init_app(app)
session_ext.init_app(app)
babel.init_app(app)
csrf.init_app(app)
app.config.setdefault("BABEL_DEFAULT_LOCALE", "pt_BR")
configure_logging(app)


# Hooks de request e error handlers globais vivem em request_hooks.py.
from request_hooks import register_request_hooks

register_request_hooks(app)


# ----------------------------------------------------------------
# 3a)  Runtime safety checks for legacy databases
# ----------------------------------------------------------------

_inventory_threshold_columns_checked = False
_inventory_movement_table_checked = False
_inventory_movement_columns_checked = False
_clinic_notifications_table_checked = False
_plantao_modelos_table_checked = False
_professional_services_table_checked = False


PLATFORM_SERVICE_FEE_RATE = Decimal("0.10")
PLATFORM_SERVICE_ROUNDING_STEP = Decimal("5")


def public_price_from_professional_price(value) -> Decimal | None:
    """Add platform fee and round up to the next R$ 5 multiple."""
    if value is None:
        return None
    amount = Decimal(str(value))
    if amount < 0:
        return None
    gross = amount * (Decimal("1") + PLATFORM_SERVICE_FEE_RATE)
    return (
        (gross / PLATFORM_SERVICE_ROUNDING_STEP).to_integral_value(rounding=ROUND_CEILING)
        * PLATFORM_SERVICE_ROUNDING_STEP
    ).quantize(Decimal("0.01"))


def _ensure_professional_services_table() -> None:
    """Create professional_service defensively when migrations were skipped."""
    global _professional_services_table_checked
    if _professional_services_table_checked:
        return

    try:
        inspector = inspect(db.engine)
    except Exception:
        return

    if not inspector.has_table("professional_service"):
        try:
            ProfessionalService.__table__.create(bind=db.engine, checkfirst=True)
        except ProgrammingError:
            pass

    _professional_services_table_checked = True


def _seed_robson_professional_services_if_needed() -> None:
    """Seed Robson's first two services for the initial production evaluation."""
    _ensure_professional_services_table()
    try:
        robson = (
            Veterinario.query
            .join(User, Veterinario.user_id == User.id)
            .filter(func.lower(User.name).like('%robson%'))
            .order_by(
                case(
                    (func.lower(User.name).like('%santos%'), 0),
                    (func.lower(User.name).like('%oliveira%'), 1),
                    else_=2,
                ),
                Veterinario.id,
            )
            .first()
        )
        if not robson:
            return
        existing = ProfessionalService.query.filter_by(veterinario_id=robson.id).first()
        if existing:
            return
        db.session.add_all([
            ProfessionalService(
                veterinario_id=robson.id,
                service_type='ultrassom',
                title='Ultrassonografia veterinária',
                description='Exame ultrassonográfico para clínicas e tutores, com laudo digital pela plataforma.',
                audience='both',
                mode='clinica_ou_domicilio',
                duration_minutes=60,
                business_start=time(9, 0),
                business_end=time(19, 0),
                tutor_price=Decimal('260.00'),
                clinic_business_price=Decimal('170.00'),
                clinic_after_hours_price=Decimal('270.00'),
                active=True,
            ),
            ProfessionalService(
                veterinario_id=robson.id,
                service_type='consulta',
                title='Consulta veterinária domiciliar',
                description='Consulta veterinária em domicílio para tutores.',
                audience='tutor',
                mode='domicilio',
                duration_minutes=60,
                business_start=time(9, 0),
                business_end=time(19, 0),
                tutor_price=Decimal('160.00'),
                active=True,
            ),
        ])
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha ao semear serviços profissionais do Robson')


def _ensure_inventory_threshold_columns() -> None:
    """Add inventory threshold columns when the migration wasn't applied.

    Some self-hosted deployments might skip Alembic migrations, which means
    new columns such as ``categoria``/``min_quantity``/``max_quantity`` are
    missing and the ``ClinicInventoryItem`` queries fail immediately.  We
    opportunistically add those columns the first time the clinic inventory is
    accessed so the UI keeps working even on older databases.  This is
    intentionally defensive and becomes a no-op once the Alembic migration
    runs.
    """

    global _inventory_threshold_columns_checked
    if _inventory_threshold_columns_checked:
        return

    try:
        inspector = inspect(db.engine)
        existing_columns = {
            column["name"] for column in inspector.get_columns("clinic_inventory_item")
        }
    except Exception:  # pragma: no cover - only triggered on engine init failures
        return

    statements = []
    if "categoria" not in existing_columns:
        statements.append(
            "ALTER TABLE clinic_inventory_item ADD COLUMN categoria VARCHAR(120)"
        )
    if "min_quantity" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_item ADD COLUMN min_quantity INTEGER")
    if "max_quantity" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_item ADD COLUMN max_quantity INTEGER")

    if statements:
        for statement in statements:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text(statement))
            except ProgrammingError:
                # Another worker may have created the column first; ignore it.
                continue

    _inventory_threshold_columns_checked = True


def _ensure_inventory_movement_table() -> None:
    """Create ``clinic_inventory_movement`` defensively when missing.

    Some self-hosted deployments occasionally skip Alembic migrations.  When
    that happens we opportunistically create the clinic inventory movement
    table the first time the inventory UI is accessed so the application keeps
    working.  Once the table exists the function becomes a cheap no-op.
    """

    global _inventory_movement_table_checked
    if _inventory_movement_table_checked:
        return

    try:
        inspector = inspect(db.engine)
    except Exception:  # pragma: no cover - engine init failures
        return

    if inspector.has_table("clinic_inventory_movement"):
        _inventory_movement_table_checked = True
        return

    try:
        ClinicInventoryMovement.__table__.create(bind=db.engine, checkfirst=True)
    except ProgrammingError:
        # Another worker may have created the table already; nothing else to do.
        pass
    finally:
        _inventory_movement_table_checked = True


def _ensure_inventory_movement_columns() -> None:
    """Add missing inventory movement columns when migrations are skipped."""

    global _inventory_movement_columns_checked
    if _inventory_movement_columns_checked:
        return

    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("clinic_inventory_movement"):
            return
        existing_columns = {
            column["name"] for column in inspector.get_columns("clinic_inventory_movement")
        }
    except Exception:  # pragma: no cover - engine init failures
        return

    statements = []
    if "clinica_id" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_movement ADD COLUMN clinica_id INTEGER")
    if "item_id" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_movement ADD COLUMN item_id INTEGER")
    if "quantity_change" not in existing_columns:
        statements.append(
            "ALTER TABLE clinic_inventory_movement ADD COLUMN quantity_change INTEGER"
        )
    if "quantity_before" not in existing_columns:
        statements.append(
            "ALTER TABLE clinic_inventory_movement ADD COLUMN quantity_before INTEGER"
        )
    if "quantity_after" not in existing_columns:
        statements.append(
            "ALTER TABLE clinic_inventory_movement ADD COLUMN quantity_after INTEGER"
        )
    if "tipo" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_movement ADD COLUMN tipo VARCHAR(20)")
    if "motivo" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_movement ADD COLUMN motivo VARCHAR(200)")
    if "responsavel_id" not in existing_columns:
        statements.append(
            "ALTER TABLE clinic_inventory_movement ADD COLUMN responsavel_id INTEGER"
        )
    if "created_at" not in existing_columns:
        statements.append(
            "ALTER TABLE clinic_inventory_movement ADD COLUMN created_at TIMESTAMP WITH TIME ZONE"
        )

    if statements:
        for statement in statements:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text(statement))
            except ProgrammingError:
                continue

    _inventory_movement_columns_checked = True


def _ensure_clinic_notifications_table() -> bool:
    """Create ``clinic_notifications`` defensively when missing."""

    global _clinic_notifications_table_checked
    if _clinic_notifications_table_checked:
        return True

    try:
        inspector = inspect(db.engine)
    except Exception:  # pragma: no cover - engine initialization failures
        return False

    if inspector.has_table("clinic_notifications"):
        _clinic_notifications_table_checked = True
        return True

    try:
        ClinicNotification.__table__.create(bind=db.engine, checkfirst=True)
    except ProgrammingError:
        # Another worker may have created the table already; ignore and re-check.
        pass

    try:
        exists = inspect(db.engine).has_table("clinic_notifications")
    except Exception:  # pragma: no cover - engine initialization failures
        exists = False

    _clinic_notifications_table_checked = exists
    return exists


def _ensure_plantao_modelos_table() -> bool:
    """Create ``plantao_modelos`` defensively when the migration is missing."""

    global _plantao_modelos_table_checked
    if _plantao_modelos_table_checked:
        return True

    try:
        inspector = inspect(db.engine)
    except Exception:  # pragma: no cover - engine initialization failures
        return False

    if inspector.has_table("plantao_modelos"):
        _plantao_modelos_table_checked = True
        return True

    try:
        PlantaoModelo.__table__.create(bind=db.engine, checkfirst=True)
    except ProgrammingError:
        # Another worker may have created the table already; ignore and re-check.
        pass

    try:
        exists = inspect(db.engine).has_table("plantao_modelos")
    except Exception:  # pragma: no cover - engine initialization failures
        exists = False

    _plantao_modelos_table_checked = exists
    return exists

# ----------------------------------------------------------------
# 4)  AWS S3 helper (lazy)
# ----------------------------------------------------------------
import boto3

AWS_ID, AWS_SECRET = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")
BUCKET = os.getenv("S3_BUCKET_NAME")

def _s3():
    return boto3.client("s3", aws_access_key_id=AWS_ID, aws_secret_access_key=AWS_SECRET)


def _runtime_module_attr(name, default):
    seen = set()
    for module_name in ("app", "petorlandia_app", __name__):
        module = sys.modules.get(module_name)
        if module is None or id(module) in seen:
            continue
        seen.add(id(module))
        namespace = getattr(module, "__dict__", {})
        if name in namespace:
            return namespace[name]
    return default


def upload_to_s3(file, filename, folder="uploads") -> str | None:
    """Compress and upload a file to S3.

    Falls back to saving the file locally under ``static/uploads`` if the
    S3 bucket is not configured or the upload fails for any reason.  Returns
    the public URL of the uploaded file or ``None`` on failure.
    """
    try:
        fileobj = file
        content_type = file.content_type
        filename = secure_filename(filename)
        bucket = _runtime_module_attr("BUCKET", BUCKET)
        project_root = pathlib.Path(_runtime_module_attr("PROJECT_ROOT", PROJECT_ROOT))
        s3_factory = _runtime_module_attr("_s3", _s3)

        # Detecta imagem pelo content_type OU tentando abrir com o PIL. Não dá para
        # confiar só no content_type: fotos de celular, colagens (Ctrl+V) e alguns
        # navegadores mobile enviam content_type vazio ou "application/octet-stream".
        # Se a orientação EXIF não for normalizada aqui, a foto fica de lado no site.
        is_image = bool(content_type and content_type.startswith("image"))
        if not is_image:
            try:
                file.stream.seek(0)
                probe = Image.open(file.stream)
                probe.verify()
                is_image = True
            except Exception:
                is_image = False
            finally:
                file.stream.seek(0)

        if is_image:
            file.stream.seek(0)
            image = Image.open(file.stream)
            image = ImageOps.exif_transpose(image)  # baixa o EXIF: pixels já saem na orientação certa
            image = image.convert("RGB")
            image.thumbnail((1280, 1280))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", optimize=True, quality=85)
            buffer.seek(0)
            fileobj = buffer
            content_type = "image/jpeg"
            name, ext = os.path.splitext(filename)
            if ext.lower() not in {".jpg", ".jpeg"}:
                filename = f"{name}.jpg"

        filename = secure_filename(filename)
        key = f"{folder}/{filename}"

        # Keep a copy of the data so that we can retry if S3 upload fails
        fileobj.seek(0)
        data = fileobj.read()
        buffer = BytesIO(data)

        if bucket:
            try:
                buffer.seek(0)
                s3_factory().upload_fileobj(
                    buffer,
                    bucket,
                    key,
                    ExtraArgs={"ContentType": content_type},
                )
                return f"https://{bucket}.s3.amazonaws.com/{key}"
            except Exception as exc:  # noqa: BLE001
                app.logger.exception("S3 upload failed: %s", exc)
                buffer.seek(0)

        # Local fallback when S3 is not configured or fails
        local_path = project_root / "static" / "uploads" / key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as fp:
            fp.write(buffer.read())

        return f"/static/uploads/{key}"
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Upload failed: %s", exc)
        return None


def bake_image_rotation(image_url: str, degrees, folder: str = "uploads") -> str:
    """Grava a rotação nos pixels da imagem e regrava no S3.

    A rotação do cropper é aplicada por CSS na exibição, mas `transform: rotate()`
    combinado com `object-fit: cover` renderiza diferente conforme o formato do
    container (o editor é quadrado; os cards são retangulares), então a foto
    aparece deitada fora do editor. Gravando a rotação na própria imagem (e zerando
    a rotação CSS) ela fica igual em qualquer lugar.

    `degrees` segue o sentido do CSS (horário). Retorna a nova URL, ou a original
    em caso de falha (degrada sem quebrar o salvamento).
    """
    try:
        degrees = int(round(float(degrees or 0))) % 360
        if degrees == 0 or not image_url:
            return image_url
        if image_url.startswith("/"):
            src = pathlib.Path(_runtime_module_attr("PROJECT_ROOT", PROJECT_ROOT)) / image_url.lstrip("/")
            source_image = Image.open(src)
        else:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            source_image = Image.open(BytesIO(response.content))
        source_image = ImageOps.exif_transpose(source_image).convert("RGB")
        # CSS gira no sentido horário; PIL.rotate gira anti-horário -> negar.
        rotated = source_image.rotate(-degrees, expand=True)
        buffer = BytesIO()
        rotated.save(buffer, format="JPEG", optimize=True, quality=90)
        buffer.seek(0)
        baked = FileStorage(
            stream=buffer,
            filename=f"{uuid.uuid4().hex}_rot.jpg",
            content_type="image/jpeg",
        )
        new_url = upload_to_s3(baked, baked.filename, folder=folder)
        return new_url or image_url
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Falha ao gravar rotação na imagem: %s", exc)
        return image_url

# ------------------------ Background S3 upload -------------------------
executor = ThreadPoolExecutor(max_workers=2)

def upload_profile_photo_async(user_id, data, content_type, filename):
    """Upload profile photo in a background thread and update the user."""
    def _task():
        file_storage = FileStorage(stream=BytesIO(data), filename=filename, content_type=content_type)
        image_url = upload_to_s3(file_storage, filename, folder="tutors")
        if image_url:
            with app.app_context():
                user = User.query.get(user_id)
                if user:
                    user.profile_photo = image_url
                    db.session.commit()

    executor.submit(_task)

# ----------------------------------------------------------------
# Nim game with Socket.IO
# ----------------------------------------------------------------
NIM_TEMPLATE_ROWS = [
    [True, True, True],
    [True, True, True],
    [True, True, True],
    [True, True],
    [True, True],
]


def _nim_default_rows() -> list[list[bool]]:
    return [row.copy() for row in NIM_TEMPLATE_ROWS]


def _nim_default_state() -> dict:
    return {
        "rows": _nim_default_rows(),
        "turn": 1,
        "starting_player": 1,
        "winner": None,
        "players": {1: "Jogador 1", 2: "Jogador 2"},
        "has_played": False,
        "active_row": None,
        "bg_gradient": None,
        "stick_color": None,
        "player_emojis": ["🐾", "🐾"],
        "turn_origin_rows": _nim_default_rows(),
        "last_turn": None,
        "alternate_rows": [False] * len(NIM_TEMPLATE_ROWS),
    }


nim_rooms = defaultdict(_nim_default_state)
nim_session_rooms: Dict[str, str] = {}
nim_session_players: Dict[str, int] = {}
nim_room_members: Dict[str, set[str]] = defaultdict(set)
nim_room_players: Dict[str, dict[int, str]] = defaultdict(dict)

EASTER_EGG_STATIC_DIR = PROJECT_ROOT / "static" / "easter_egg"


def _nim_payload(room: str) -> dict:
    state = nim_rooms[room]
    return {
        "rows": [row.copy() for row in state["rows"]],
        "turn": state["turn"],
        "starting_player": state.get("starting_player", 1),
        "winner": state["winner"],
        "players": dict(state.get("players", {})),
        "has_played": bool(state.get("has_played", False)),
        "active_row": state.get("active_row"),
        "bg_gradient": state.get("bg_gradient"),
        "stick_color": state.get("stick_color"),
        "player_emojis": list(state.get("player_emojis", [])),
        "last_turn": state.get("last_turn"),
        "alternate_rows": list(state.get("alternate_rows", [])),
        "turn_origin_rows": [row.copy() for row in state.get("turn_origin_rows", _nim_default_rows())],
    }


def _nim_copy_rows(rows: Iterable[Iterable[bool]]) -> list[list[bool]]:
    copied: list[list[bool]] = []
    for index, template_row in enumerate(NIM_TEMPLATE_ROWS):
        try:
            row = rows[index]
        except (TypeError, IndexError):
            copied.append(template_row.copy())
            continue
        if not isinstance(row, (list, tuple)):
            copied.append(template_row.copy())
            continue
        copied.append([bool(value) for value in row[: len(template_row)]])
    return copied


def _nim_enforce_rules(current_state: dict, proposed_state: dict) -> dict | None:
    """Validate the proposed state according to the house rules."""

    proposed_rows = _nim_copy_rows(proposed_state.get("rows", []))
    current_rows = _nim_copy_rows(current_state.get("rows", _nim_default_rows()))

    current_start = current_state.get("starting_player", 1)
    try:
        current_start_int = int(current_start)
    except (TypeError, ValueError):
        current_start_int = 1
    if current_start_int not in (1, 2):
        current_start_int = 1

    proposed_state["starting_player"] = current_start_int

    origin_candidate = current_state.get("turn_origin_rows")
    if (
        not isinstance(origin_candidate, list)
        or len(origin_candidate) != len(NIM_TEMPLATE_ROWS)
    ):
        baseline_rows = _nim_copy_rows(current_rows)
    else:
        baseline_rows = _nim_copy_rows(origin_candidate)

    default_rows = _nim_default_rows()

    proposed_turn = proposed_state.get("turn")
    try:
        proposed_turn_int = int(proposed_turn)
    except (TypeError, ValueError):
        proposed_turn_int = None
    if proposed_turn_int not in (1, 2):
        proposed_turn_int = None

    has_played_flag = proposed_state.get("has_played")
    has_played_bool = bool(has_played_flag)

    winner_flag = proposed_state.get("winner")
    is_reset = (
        proposed_rows == default_rows
        and (winner_flag is None or winner_flag == "")
        and not has_played_bool
        and proposed_turn_int in (1, 2)
    )

    restorations_from_current: list[tuple[int, int]] = []
    for row_index, (current_row, next_row) in enumerate(zip(current_rows, proposed_rows)):
        for stick_index, (current_value, next_value) in enumerate(zip(current_row, next_row)):
            if not current_value and next_value:
                restorations_from_current.append((row_index, stick_index))

    if restorations_from_current and not is_reset:
        return None

    removed_by_row_turn: list[int] = [0] * len(NIM_TEMPLATE_ROWS)

    for row_index, (baseline_row, next_row) in enumerate(zip(baseline_rows, proposed_rows)):
        for stick_index, (baseline_value, next_value) in enumerate(zip(baseline_row, next_row)):
            if baseline_value and not next_value:
                removed_by_row_turn[row_index] += 1

    total_removed_turn = sum(removed_by_row_turn)
    rows_with_removals = [
        index for index, count in enumerate(removed_by_row_turn) if count > 0
    ]

    current_turn = current_state.get("turn")
    try:
        current_turn_int = int(current_turn)
    except (TypeError, ValueError):
        current_turn_int = 1
    if current_turn_int not in (1, 2):
        current_turn_int = 1

    next_turn = proposed_state.get("turn")
    try:
        next_turn_int = int(next_turn)
    except (TypeError, ValueError):
        next_turn_int = current_turn_int
    if next_turn_int not in (1, 2):
        next_turn_int = current_turn_int

    proposed_state["turn"] = next_turn_int
    turn_changed = current_turn_int != next_turn_int

    current_alternates = current_state.get("alternate_rows")
    if not isinstance(current_alternates, (list, tuple)):
        normalized_alternates = [False] * len(NIM_TEMPLATE_ROWS)
    else:
        normalized_alternates = [
            bool(current_alternates[index]) if index < len(current_alternates) else False
            for index in range(len(NIM_TEMPLATE_ROWS))
        ]

    if is_reset:
        next_start = 2 if current_start_int == 1 else 1
        proposed_state["rows"] = proposed_rows
        proposed_state["has_played"] = False
        proposed_state["turn"] = next_start
        proposed_state["winner"] = None
        proposed_state["alternate_rows"] = [False] * len(NIM_TEMPLATE_ROWS)
        proposed_state["starting_player"] = next_start
        return proposed_state

    if total_removed_turn > 3:
        return None

    if len(rows_with_removals) > 1:
        return None

    if turn_changed and total_removed_turn == 0:
        return None

    for row_index, removed_count in enumerate(removed_by_row_turn):
        if normalized_alternates[row_index] and removed_count > 1:
            return None

    # Update alternate row metadata based on the resulting board.
    next_alternates = normalized_alternates.copy()
    for row_index, row in enumerate(proposed_rows):
        remaining = sum(1 for stick in row if stick)
        if remaining <= 1:
            next_alternates[row_index] = False
            continue

        if len(row) == 3:
            left, middle, right = row
            if left and right and not middle:
                next_alternates[row_index] = True

    proposed_state["rows"] = proposed_rows
    proposed_state["alternate_rows"] = next_alternates

    if turn_changed:
        proposed_state["has_played"] = False
    else:
        proposed_state["has_played"] = total_removed_turn > 0

    # Winner is only valid when the board is empty. With the misère rule, the
    # winner corresponds to the opponent of the player who removed the last
    # stick, so any inconsistent winner flag is cleared here.
    all_taken = all(not any(row) for row in proposed_rows)
    if not all_taken:
        proposed_state["winner"] = None
    else:
        if turn_changed:
            proposed_state["winner"] = next_turn_int
        else:
            proposed_state["winner"] = 1 if next_turn_int == 2 else 2

    proposed_state["starting_player"] = current_start_int
    return proposed_state


def _nim_player_name(state: dict, index: int) -> str:
    players = state.get("players")
    if isinstance(players, dict):
        for key in (index, str(index)):
            value = players.get(key)
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
    return f"Jogador {index}"


def _nim_build_turn_summary(
    previous_state: dict, next_state: dict, baseline_rows: list[list[bool]]
) -> dict | None:
    prev_turn = previous_state.get("turn", 1)
    next_turn = next_state.get("turn", prev_turn)
    prev_winner = previous_state.get("winner")
    next_winner = next_state.get("winner")

    removed_segments: list[dict[str, int]] = []
    total_removed = 0
    total_restored = 0

    for index, (start_row, end_row) in enumerate(
        zip(baseline_rows, next_state.get("rows", []))
    ):
        removed = 0
        restored = 0
        for start_value, end_value in zip(start_row, end_row):
            start_bool = bool(start_value)
            end_bool = bool(end_value)
            if start_bool and not end_bool:
                removed += 1
            elif not start_bool and end_bool:
                restored += 1
        if removed:
            removed_segments.append({"row": index + 1, "count": removed})
            total_removed += removed
        total_restored += restored

    previous_player_name = _nim_player_name(next_state, prev_turn)
    next_player_name = _nim_player_name(next_state, next_turn)

    message_parts = []
    for segment in removed_segments:
        count = segment["count"]
        row_label = segment["row"]
        noun = "palito" if count == 1 else "palitos"
        message_parts.append(f"{count} {noun} da linha {row_label}")

    if not message_parts:
        removed_text = ""
    elif len(message_parts) == 1:
        removed_text = message_parts[0]
    else:
        removed_text = ", ".join(message_parts[:-1]) + " e " + message_parts[-1]

    if next_winner in (1, 2) and next_winner == prev_turn:
        if removed_text:
            message = (
                f"{previous_player_name} removeu {removed_text} e venceu a partida!"
            )
        else:
            message = f"{previous_player_name} venceu a partida!"
    elif next_winner in (1, 2):
        winner_name = _nim_player_name(next_state, next_winner)
        if removed_text:
            message = (
                f"{previous_player_name} removeu {removed_text} e ficou sem jogadas. "
                f"{winner_name} venceu a partida!"
            )
        else:
            message = f"{winner_name} venceu a partida!"
    elif total_removed:
        if removed_text:
            message = (
                f"{previous_player_name} removeu {removed_text}. "
                f"Agora é a vez de {next_player_name}."
            )
        else:
            message = f"{previous_player_name} passou a vez."
    elif total_restored:
        message = f"{previous_player_name} reiniciou o tabuleiro."
    elif prev_winner and not next_winner:
        message = "Uma nova partida foi iniciada."
    else:
        message = f"{previous_player_name} passou a vez."

    return {
        "player": int(prev_turn) if isinstance(prev_turn, int) else prev_turn,
        "player_name": previous_player_name,
        "next_player": int(next_turn) if isinstance(next_turn, int) else next_turn,
        "next_player_name": next_player_name,
        "removed": removed_segments,
        "total_removed": total_removed,
        "restored": total_restored,
        "winner": int(next_winner)
        if isinstance(next_winner, int) and next_winner in (1, 2)
        else None,
        "message": message,
    }


def _nim_turn_metadata(previous_state: dict, next_state: dict) -> tuple[dict | None, list[list[bool]]]:
    baseline = previous_state.get("turn_origin_rows")
    if not isinstance(baseline, list) or len(baseline) != len(NIM_TEMPLATE_ROWS):
        baseline_rows = _nim_default_rows()
    else:
        baseline_rows = _nim_copy_rows(baseline)

    prev_turn = previous_state.get("turn")
    next_turn = next_state.get("turn")
    prev_winner = previous_state.get("winner")
    next_winner = next_state.get("winner")

    turn_changed = prev_turn != next_turn
    winner_declared = (next_winner and next_winner != prev_winner)
    winner_cleared = prev_winner and not next_winner

    last_turn_summary = previous_state.get("last_turn")
    next_origin_rows = baseline_rows

    if winner_cleared:
        last_turn_summary = None
        next_origin_rows = _nim_copy_rows(next_state.get("rows", _nim_default_rows()))
    elif turn_changed or winner_declared:
        summary = _nim_build_turn_summary(previous_state, next_state, baseline_rows)
        last_turn_summary = summary
        next_origin_rows = _nim_copy_rows(next_state.get("rows", _nim_default_rows()))

    return last_turn_summary, next_origin_rows


def _normalize_nim_payload(payload: dict | None, current_state: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None

    rows = payload.get("rows")
    if not isinstance(rows, (list, tuple)) or len(rows) != len(NIM_TEMPLATE_ROWS):
        return None

    normalized_rows: list[list[bool]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != len(NIM_TEMPLATE_ROWS[index]):
            return None
        normalized_rows.append([bool(value) for value in row])

    turn = payload.get("turn", current_state["turn"])
    try:
        turn_int = int(turn)
    except (TypeError, ValueError):
        turn_int = current_state["turn"]
    if turn_int not in (1, 2):
        turn_int = 1

    winner_value = payload.get("winner")
    if winner_value in (None, "", "null"):
        winner_int = None
    else:
        try:
            winner_int = int(winner_value)
        except (TypeError, ValueError):
            winner_int = None
        if winner_int not in (1, 2):
            winner_int = None

    has_played_raw = payload.get("has_played")
    if has_played_raw is None:
        has_played_raw = current_state.get("has_played", False)
    if isinstance(has_played_raw, str):
        has_played_raw = has_played_raw.strip().lower()
        if has_played_raw in {"1", "true", "yes", "on"}:
            has_played = True
        elif has_played_raw in {"0", "false", "no", "off", ""}:
            has_played = False
        else:
            has_played = current_state.get("has_played", False)
    else:
        has_played = bool(has_played_raw)

    has_active_row_key = "active_row" in payload or "activeRow" in payload
    active_row_value = payload.get("active_row")
    if active_row_value is None and "active_row" not in payload:
        active_row_value = payload.get("activeRow")
    if active_row_value is None and not has_active_row_key:
        active_row_value = current_state.get("active_row")
    try:
        active_row_int = int(active_row_value)
    except (TypeError, ValueError):
        active_row_int = None
    if active_row_int is not None and not (
        0 <= active_row_int < len(NIM_TEMPLATE_ROWS)
    ):
        active_row_int = None

    bg_gradient_value = payload.get("bg_gradient")
    if bg_gradient_value is None:
        bg_gradient_value = payload.get("bgGradient")
    if bg_gradient_value is None:
        bg_gradient = current_state.get("bg_gradient")
    else:
        bg_gradient_text = str(bg_gradient_value).strip()
        bg_gradient = bg_gradient_text[:200] if bg_gradient_text else current_state.get("bg_gradient")

    stick_color_value = payload.get("stick_color")
    if stick_color_value is None:
        stick_color_value = payload.get("stickColor")
    if stick_color_value is None:
        stick_color = current_state.get("stick_color")
    else:
        stick_color_text = str(stick_color_value).strip()
        stick_color = stick_color_text[:50] if stick_color_text else current_state.get("stick_color")

    player_emojis_value = payload.get("player_emojis")
    if player_emojis_value is None:
        player_emojis_value = payload.get("playerEmojis")
    if isinstance(player_emojis_value, (list, tuple)):
        normalized_emojis: list[str] = []
        for index in range(2):
            try:
                raw = player_emojis_value[index]
            except IndexError:
                raw = ""
            text = str(raw).strip()
            normalized_emojis.append(text[:8] if text else "🐾")
        player_emojis = normalized_emojis
    else:
        current_emojis = current_state.get("player_emojis")
        if isinstance(current_emojis, (list, tuple)):
            player_emojis = [str(value)[:8] for value in current_emojis[:2]]
            if len(player_emojis) < 2:
                player_emojis.extend(["🐾"] * (2 - len(player_emojis)))
        else:
            player_emojis = ["🐾", "🐾"]

    starting_player_value = payload.get("starting_player")
    if starting_player_value is None:
        starting_player_value = payload.get("startingPlayer")
    if starting_player_value is None:
        starting_player = current_state.get("starting_player", 1)
    else:
        try:
            starting_player = int(starting_player_value)
        except (TypeError, ValueError):
            starting_player = current_state.get("starting_player", 1)
        if starting_player not in (1, 2):
            starting_player = current_state.get("starting_player", 1) or 1

    return {
        "rows": normalized_rows,
        "turn": turn_int,
        "winner": winner_int,
        "players": _normalize_nim_players(payload.get("players"), current_state.get("players", {})),
        "has_played": has_played,
        "active_row": active_row_int,
        "bg_gradient": bg_gradient,
        "stick_color": stick_color,
        "player_emojis": player_emojis,
        "starting_player": starting_player,
    }


def _normalize_nim_players(players: dict | None, current_players: dict | None) -> dict:
    defaults = {1: "Jogador 1", 2: "Jogador 2"}
    normalized: dict[int, str] = {}

    if not isinstance(current_players, dict):
        current_players = {}

    if not isinstance(players, dict):
        players = {}

    for player_index in (1, 2):
        fallback = current_players.get(player_index) or defaults[player_index]
        value = (
            players.get(player_index)
            or players.get(str(player_index))
            or fallback
        )
        text = str(value).strip()
        text = " ".join(text.split())
        if not text:
            text = defaults[player_index]
        normalized[player_index] = text[:40]

    return normalized








def _nim_room_from_request() -> str:
    room = (
        request.args.get("room", "")
        or request.args.get("sala", "")
        or ""
    ).strip()
    if not room:
        return "lobby"
    sanitized = "".join(ch for ch in room if ch.isalnum() or ch in {"_", "-"})
    return sanitized[:32].upper() or "lobby"


@socketio.on("connect")
def nim_connect():  # pragma: no cover - exercised via browser
    room = _nim_room_from_request()
    members = nim_room_members[room]
    if len(members) >= 2:
        emit(
            "room_full",
            {
                "message": "Sala cheia. Somente dois jogadores podem participar desta partida.",
                "room": room,
            },
        )
        disconnect()
        return

    nim_session_rooms[request.sid] = room
    players_map = nim_room_players[room]

    # Clear out any stale seat assignments that might linger if a client
    # disconnected without triggering ``nim_disconnect`` (for example when the
    # server restarted).
    for seat, occupant in list(players_map.items()):
        if occupant not in members:
            players_map.pop(seat, None)

    assigned_seat = None
    for candidate in (1, 2):
        occupant = players_map.get(candidate)
        if not occupant:
            assigned_seat = candidate
            break

    if assigned_seat is None:
        # Should not happen because the room is limited to two players, but
        # default to seat ``1`` to avoid leaving the session without a slot.
        assigned_seat = 1

    players_map[assigned_seat] = request.sid
    nim_session_players[request.sid] = assigned_seat
    members.add(request.sid)
    join_room(room)
    emit("update_state", _nim_payload(room))


@socketio.on("move")
def nim_move(data):  # pragma: no cover - exercised via browser
    room = nim_session_rooms.get(request.sid)
    if not room:
        room = _nim_room_from_request()
        nim_session_rooms[request.sid] = room
    current_state = nim_rooms[room]
    player_seat = nim_session_players.get(request.sid)
    normalized = _normalize_nim_payload(data, current_state)
    if not normalized:
        emit("update_state", _nim_payload(room))
        return

    current_turn = current_state.get("turn")
    try:
        current_turn_int = int(current_turn)
    except (TypeError, ValueError):
        current_turn_int = 1
    if current_turn_int not in (1, 2):
        current_turn_int = 1

    board_changed = (
        normalized.get("rows") != current_state.get("rows")
        or normalized.get("turn") != current_turn_int
        or normalized.get("winner") != current_state.get("winner")
        or normalized.get("has_played") != current_state.get("has_played")
        or normalized.get("active_row") != current_state.get("active_row")
    )

    if board_changed and player_seat != current_turn_int:
        emit("update_state", _nim_payload(room))
        return

    enforced = _nim_enforce_rules(current_state, normalized)
    if not enforced:
        emit("update_state", _nim_payload(room))
        return

    last_turn_summary, next_origin_rows = _nim_turn_metadata(current_state, enforced)
    enforced["turn_origin_rows"] = next_origin_rows
    enforced["last_turn"] = last_turn_summary

    nim_rooms[room] = enforced
    emit("update_state", _nim_payload(room), room=room)


@socketio.on("disconnect")
def nim_disconnect():  # pragma: no cover - exercised via browser
    room = nim_session_rooms.pop(request.sid, None)
    seat = nim_session_players.pop(request.sid, None)
    if room:
        members = nim_room_members.get(room)
        if members and request.sid in members:
            members.discard(request.sid)
            if not members:
                nim_room_members.pop(room, None)
        players = nim_room_players.get(room)
        if players and seat in players and players.get(seat) == request.sid:
            players.pop(seat, None)
            if not players:
                nim_room_players.pop(room, None)
        leave_room(room)


def local_date_range_to_utc(start_dt, end_dt):
    """Convert local date/datetime boundaries to UTC-aware values."""

    def _convert(value):
        if value is None:
            return None
        return normalize_to_utc(value)

    return _convert(start_dt), _convert(end_dt)


# Filters e helpers de formatação vivem em template_filters.py; os nomes são
# reimportados aqui porque várias views deste módulo ainda os utilizam.
from template_filters import (
    register_template_filters,
    date_now,
    datetime_brazil,
    format_datetime_brazil,
    isoformat_with_tz,
    format_timedelta,
    digits_only,
    whatsapp_chat_url,
    normalize_email,
    normalize_phone,
    format_cnpj,
    currency_br,
    payment_status_label,
    PAYER_TYPE_LABELS,
    payer_type_label,
    default_payer_type_for_consulta,
    species_display,
    animal_size_label,
    animal_size_token,
    _resolve_species_name,
    _normalize_species_token,
    _resolve_species_visual,
    _resolve_size_data,
    _SPECIES_VISUAL_TOKENS,
)

register_template_filters(app)

def find_users_by_phone(phone: str | None, *, exclude_user_id: int | None = None) -> list[User]:
    """Return users whose stored phone matches the normalized phone value."""
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return []

    matches = []
    candidates = User.query.filter(User.phone.isnot(None), User.phone != "").all()
    for candidate in candidates:
        if exclude_user_id is not None and candidate.id == exclude_user_id:
            continue
        if normalize_phone(candidate.phone) == normalized_phone:
            matches.append(candidate)
    return matches


def find_user_by_login_identifier(identifier: str | None) -> tuple[User | None, str | None]:
    """Resolve a login identifier as email or phone."""
    normalized_email = normalize_email(identifier)
    if normalized_email and "@" in normalized_email:
        return User.query.filter(func.lower(User.email) == normalized_email).first(), None

    phone_matches = find_users_by_phone(identifier)
    if len(phone_matches) > 1:
        return None, "Há mais de uma conta com este celular. Entre com seu e-mail por enquanto."
    if phone_matches:
        return phone_matches[0], None
    return None, None


# ----------------------------------------------------------------
# 6)  Forms e helpers
# ----------------------------------------------------------------
from forms import (
    AddToCartForm,
    AnimalForm,
    APPOINTMENT_KIND_CHOICES,
    AppointmentDeleteForm,
    AppointmentForm,
    AppointmentRequestForm,
    AppointmentRequestResponseForm,
    CartAddressForm,
    ChangePasswordForm,
    ClinicAddSpecialistForm,
    ClinicAddStaffForm,
    ClinicForm,
    ClinicHoursForm,
    ClinicInviteCancelForm,
    ClinicInviteResendForm,
    ClinicInviteResponseForm,
    ClinicInviteVeterinarianForm,
    ClinicStaffPermissionForm,
    DeleteAccountForm,
    DeliveryDemotionForm,
    DeliveryPromotionForm,
    ParceiroPromotionForm,
    ParceiroDemotionForm,
    DeliveryRequestForm,
    EditProfileForm,
    ClinicProductForm,
    ClinicProductEditForm,
    CasaDeRacaoForm,
    CasaDeRacaoProductForm,
    CasaDeRacaoProductEditForm,
    GroomingPlanForm,
    GroomingSubscribeForm,
    HealthPlanForm,
    InventoryItemForm,
    LoginForm,
    MessageForm,
    OrcamentoForm,
    OrderItemForm,
    PJPaymentForm,
    PlantonistaEscalaForm,
    ProductPhotoForm,
    ProductUpdateForm,
    ProfessionalServiceForm,
    RegistrationForm,
    FirstAccessPasswordForm,
    FirstAccessPhoneForm,
    ResetPasswordForm,
    ResetPasswordRequestForm,
    SubscribePlanForm,
    ConsultaPlanAuthorizationForm,
    VetScheduleForm,
    VetSpecialtyForm,
    VetProfileForm,
    VeterinarianMembershipCheckoutForm,
    VeterinarianMembershipCancelTrialForm,
    VeterinarianMembershipRequestNewTrialForm,
    VeterinarianProfileForm,
    VeterinarianPromotionForm,
)
from helpers import (
    _user_can_access_accounting,
    _user_is_clinic_owner,
    appointments_to_events,
    calcular_idade,
    clinicas_do_usuario,
    consulta_to_event,
    ensure_veterinarian_membership,
    exam_to_event,
    get_appointment_duration,
    get_available_times,
    get_weekly_schedule,
    has_professional_access,
    grant_veterinarian_role,
    is_parceiro,
    parceiro_required,
    group_appointments_by_day,
    group_vet_schedules_by_day,
    has_conflict_for_slot,
    has_schedule_conflict,
    has_veterinarian_profile,
    is_slot_available,
    is_veterinarian,
    parse_data_nascimento,
    to_timezone_aware,
    unique_items_by_id,
    vaccine_to_event,
    veterinarian_required,
    geocode_address,
    reverse_geocode_city,
)
from services import (
    build_usage_history,
    coverage_badge,
    coverage_label,
    evaluate_consulta_coverages,
    find_active_share,
    generate_financial_snapshot,
    get_calendar_access_scope,
    insurer_token_valid,
    log_data_share_event,
    summarize_plan_metrics,
    update_financial_snapshots_daily,
)
from services.geocode_queue import AddressGeocodeQueue
from authz import (
    can_manage_budget,
    can_view_budget,
    can_view_clinic,
)
from services.finance import (
    build_accounting_dashboard,
    build_cash_flow_report,
    build_dre_report,
    build_veterinarian_revenue_report,
    classify_transactions_for_month,
    determine_pj_payment_subcategory,
    export_accountant_xlsx,
    import_bank_statement,
    REQUIRED_PJ_PAYMENT_COLUMNS,
    register_account,
    run_transactions_history_backfill,
)
from services.animal_search import search_animals


address_geocode_queue = AddressGeocodeQueue(app)


def current_user_clinic_id():
    """Return the clinic ID associated with the current user, if any."""
    if not current_user.is_authenticated:
        return None
    if has_veterinarian_profile(current_user):
        return getattr(current_user.veterinario, 'clinica_id', None)
    return current_user.clinica_id


def _normalize_public_text(value):
    normalized = (value or '').strip().lower()
    if not normalized:
        return ''
    normalized = unicodedata.normalize('NFKD', normalized)
    normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', normalized)


def _vet_public_city(vet):
    end = getattr(getattr(vet, 'user', None), 'endereco', None)
    return (end.cidade or '').strip() if end and end.cidade else None


def _vet_coverage_city_keys(vet):
    """Conjunto de cidades (normalizadas) que o veterinário atende.

    Usa ``cidades_atendidas`` quando houver; senão cai para a cidade do
    endereço (preserva o comportamento dos profissionais já cadastrados).
    """
    keys = {
        _normalize_public_text(c.cidade)
        for c in (getattr(vet, 'cidades_atendidas', None) or [])
        if c and c.cidade
    }
    keys.discard('')
    if keys:
        return keys
    fallback = _normalize_public_text(_vet_public_city(vet))
    return {fallback} if fallback else set()


def _vet_serves_city(vet, city):
    """True se o veterinário atende a cidade (cobertura cadastrada ou endereço)."""
    city_key = _normalize_public_text(city)
    if not city_key:
        return False
    return city_key in _vet_coverage_city_keys(vet)


def _vet_all_public_cities(vet):
    """Cidades de exibição do veterinário (cobertura ou, na falta, o endereço)."""
    cidades = [
        (c.cidade or '').strip()
        for c in (getattr(vet, 'cidades_atendidas', None) or [])
        if c and (c.cidade or '').strip()
    ]
    if cidades:
        seen = set()
        unique = []
        for nome in cidades:
            key = _normalize_public_text(nome)
            if key not in seen:
                seen.add(key)
                unique.append(nome)
        return unique
    cidade = _vet_public_city(vet)
    return [cidade] if cidade else []


def _is_ultrasound_vet(vet):
    """True se o profissional oferece ultrassonografia / diagnóstico por imagem."""
    return any(
        'ultrass' in _normalize_public_text(s.nome)
        or 'imagem' in _normalize_public_text(s.nome)
        for s in (getattr(vet, 'specialties', None) or [])
    )


def _parse_coverage_cities(raw):
    """Texto livre (linhas/vírgulas, 'Cidade' ou 'Cidade/UF') → lista de (cidade, uf)."""
    if not raw:
        return []
    out = []
    seen = set()
    for part in re.split(r'[\n,;]+', raw):
        part = part.strip()
        if not part:
            continue
        uf = None
        if '/' in part:
            cidade, _, uf_raw = part.rpartition('/')
            cidade, uf_raw = cidade.strip(), uf_raw.strip().upper()
            if len(uf_raw) == 2:
                uf = uf_raw
            else:
                cidade = part.strip()
        else:
            cidade = part
        if not cidade:
            continue
        key = _normalize_public_text(cidade)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((cidade, uf))
    return out


def _set_vet_coverage_cities(vet, raw):
    """Substitui as cidades atendidas do veterinário pelo conteúdo do textarea."""
    from models import VeterinarioAtendeCidade

    vet.cidades_atendidas = [
        VeterinarioAtendeCidade(cidade=cidade, uf=uf)
        for cidade, uf in _parse_coverage_cities(raw)
    ]


def _format_vet_coverage_cities(vet):
    """Serializa as cidades atendidas para preencher o textarea (uma por linha)."""
    return '\n'.join(
        f'{c.cidade}/{c.uf}' if c.uf else c.cidade
        for c in (getattr(vet, 'cidades_atendidas', None) or [])
    )


def _populate_professional_service_form(form, service=None):
    if service:
        form.service_id.data = str(service.id)
        form.title.data = service.title
        form.service_type.data = service.service_type
        form.description.data = service.description
        form.audience.data = service.audience
        form.mode.data = service.mode
        form.duration_minutes.data = service.duration_minutes
        form.business_start.data = service.business_start
        form.business_end.data = service.business_end
        form.tutor_price.data = service.tutor_price
        form.clinic_business_price.data = service.clinic_business_price
        form.clinic_after_hours_price.data = service.clinic_after_hours_price
        form.active.data = service.active


def _apply_professional_service_form(service, form):
    service.title = (form.title.data or '').strip()
    service.service_type = form.service_type.data or 'consulta'
    service.description = (form.description.data or '').strip() or None
    service.audience = form.audience.data or 'tutor'
    service.mode = form.mode.data or None
    service.duration_minutes = form.duration_minutes.data or None
    service.business_start = form.business_start.data
    service.business_end = form.business_end.data
    service.tutor_price = form.tutor_price.data
    service.clinic_business_price = form.clinic_business_price.data
    service.clinic_after_hours_price = form.clinic_after_hours_price.data
    service.active = bool(form.active.data)


def _vet_public_name_key(vet):
    return _normalize_public_text(getattr(getattr(vet, 'user', None), 'name', None))


def _public_city_key(city):
    key = _normalize_public_text(city)
    if 'belo horizonte' in key:
        return 'belo horizonte'
    if 'contagem' in key:
        return 'contagem'
    if 'orlandia' in key:
        return 'orlandia'
    return key


def _is_bh_public_city(city):
    return _public_city_key(city) == 'belo horizonte'


def _is_bh_or_contagem_public_city(city):
    return _public_city_key(city) in {'belo horizonte', 'contagem'}


def _is_robson_santos_public_profile(vet):
    name_key = _vet_public_name_key(vet)
    return (
        'robson' in name_key
        and (
            'santos' in name_key
            or 'oliveira' in name_key
            or _is_ultrasound_vet(vet)
        )
    )


def _is_bh_consulta_extra_public_profile(vet):
    name_key = _vet_public_name_key(vet)
    return any(name in name_key for name in {'tereza', 'teresa', 'amanda'})


def _vet_matches_public_city(vet, city, *, kind='consulta'):
    if not city:
        return True
    city_key = _public_city_key(city)
    if _vet_serves_city(vet, city):
        return True
    if any(_public_city_key(vet_city) == city_key for vet_city in _vet_all_public_cities(vet)):
        return True
    if _is_robson_santos_public_profile(vet) and city_key in {'belo horizonte', 'contagem'}:
        return True
    if kind == 'consulta' and city_key == 'belo horizonte' and _is_bh_consulta_extra_public_profile(vet):
        return True
    return False


def _vet_public_service_notes(vet, selected_city=None):
    notes = []
    if selected_city and _is_robson_santos_public_profile(vet) and _is_bh_or_contagem_public_city(selected_city):
        notes.append({
            'icon': 'fa-solid fa-stethoscope',
            'label': 'Consultas em Belo Horizonte e Contagem',
        })
        notes.append({
            'icon': 'fa-solid fa-wave-square',
            'label': 'Exame ultrassonografico',
        })
    if selected_city and _is_bh_public_city(selected_city) and _is_bh_consulta_extra_public_profile(vet):
        notes.append({
            'icon': 'fa-solid fa-calendar-check',
            'label': 'Consultas em Belo Horizonte',
        })
    return notes


def _is_public_veterinarian(vet):
    profile_type = _normalize_public_text(getattr(vet, 'public_profile_type', None) or 'profissional')
    membership = getattr(vet, 'membership', None)
    return (
        bool(getattr(vet, 'public_visible', True))
        and profile_type == 'profissional'
        and bool(membership and membership.is_active())
    )


def _public_veterinarians_query():
    return (
        Veterinario.query
        .join(User, Veterinario.user_id == User.id)
        .join(VeterinarianMembership, VeterinarianMembership.veterinario_id == Veterinario.id)
        .options(
            db.joinedload(Veterinario.user).joinedload(User.endereco),
            db.joinedload(Veterinario.membership),
            db.selectinload(Veterinario.specialties),
            db.selectinload(Veterinario.cidades_atendidas),
        )
        .filter(Veterinario.public_visible.is_(True))
        .filter(Veterinario.public_profile_type == 'profissional')
        .filter(VeterinarianMembership.is_active_flag.is_(True))
        .order_by(User.name)
    )


def _current_professional_service_audience():
    if current_user.is_authenticated and _user_is_clinic_owner(current_user):
        return 'clinic'
    return 'tutor'


def _service_visible_for_audience(service, audience):
    target = (getattr(service, 'audience', None) or 'tutor').strip().lower()
    return target == 'both' or target == audience


def _professional_service_query(*, audience=None, service_type=None, city=None, active_only=True):
    _seed_robson_professional_services_if_needed()
    query = (
        ProfessionalService.query
        .join(Veterinario, ProfessionalService.veterinario_id == Veterinario.id)
        .join(User, Veterinario.user_id == User.id)
        .join(VeterinarianMembership, VeterinarianMembership.veterinario_id == Veterinario.id)
        .options(
            db.joinedload(ProfessionalService.veterinario).joinedload(Veterinario.user).joinedload(User.endereco),
            db.joinedload(ProfessionalService.veterinario).joinedload(Veterinario.membership),
            db.joinedload(ProfessionalService.veterinario).selectinload(Veterinario.specialties),
            db.joinedload(ProfessionalService.veterinario).selectinload(Veterinario.cidades_atendidas),
        )
        .filter(Veterinario.public_visible.is_(True))
        .filter(Veterinario.public_profile_type == 'profissional')
        .filter(VeterinarianMembership.is_active_flag.is_(True))
        .order_by(User.name, ProfessionalService.service_type, ProfessionalService.title)
    )
    if active_only:
        query = query.filter(ProfessionalService.active.is_(True))
    if service_type:
        if isinstance(service_type, (list, tuple, set)):
            query = query.filter(ProfessionalService.service_type.in_(list(service_type)))
        else:
            query = query.filter(ProfessionalService.service_type == service_type)
    services = query.all()
    if audience:
        services = [service for service in services if _service_visible_for_audience(service, audience)]
    if city:
        services = [
            service for service in services
            if _vet_matches_public_city(
                service.veterinario,
                city,
                kind='exame' if service.service_type in {'ultrassom', 'exame'} else 'consulta',
            )
        ]
    return services


def _service_public_price_options(service, audience):
    options = []
    if audience == 'clinic':
        if service.clinic_business_price is not None:
            options.append({
                'label': 'Horário comercial',
                'professional': service.clinic_business_price,
                'public': public_price_from_professional_price(service.clinic_business_price),
            })
        if service.clinic_after_hours_price is not None:
            options.append({
                'label': 'Fora do comercial',
                'professional': service.clinic_after_hours_price,
                'public': public_price_from_professional_price(service.clinic_after_hours_price),
            })
    else:
        if service.tutor_price is not None:
            options.append({
                'label': 'Preço ao tutor',
                'professional': service.tutor_price,
                'public': public_price_from_professional_price(service.tutor_price),
            })
    return options


def _service_lowest_public_price(services, audience):
    prices = [
        option['public']
        for service in services
        for option in _service_public_price_options(service, audience)
        if option.get('public') is not None
    ]
    return min(prices) if prices else None


def _format_reais(value):
    if value is None:
        return None
    amount = Decimal(str(value)).quantize(Decimal('0.01'))
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# Helpers fiscais migraram para blueprints/fiscal.py


































def _collect_clinic_ids(viewer=None, clinic_scope=None):
    """Return a set with clinic IDs derived from the viewer and scope hints."""
    clinic_ids = set()

    if clinic_scope:
        if isinstance(clinic_scope, (list, tuple, set)):
            clinic_ids.update(cid for cid in clinic_scope if cid)
        else:
            if clinic_scope:
                clinic_ids.add(clinic_scope)

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer:
        viewer_clinic = getattr(viewer, 'clinica_id', None)
        if viewer_clinic:
            clinic_ids.add(viewer_clinic)

        vet_profile = getattr(viewer, 'veterinario', None)
        if vet_profile:
            primary = getattr(vet_profile, 'clinica_id', None)
            if primary:
                clinic_ids.add(primary)
            for clinic in getattr(vet_profile, 'clinicas', []) or []:
                clinic_id = getattr(clinic, 'id', None)
                if clinic_id:
                    clinic_ids.add(clinic_id)

    return clinic_ids


def _viewer_parties(viewer=None, clinic_scope=None):
    parties = []

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    for clinic_id in clinic_ids:
        if clinic_id:
            parties.append((DataSharePartyType.clinic, clinic_id))

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer:
        worker = getattr(viewer, 'worker', None)
        viewer_id = getattr(viewer, 'id', None)
        if viewer_id and is_veterinarian(viewer):
            parties.append((DataSharePartyType.veterinarian, viewer_id))
        elif worker == 'seguradora' and viewer_id:
            parties.append((DataSharePartyType.insurer, viewer_id))

    unique = []
    seen = set()
    for party in parties:
        if not party or party[1] is None:
            continue
        key = (party[0].value if isinstance(party[0], DataSharePartyType) else party[0], party[1])
        if key in seen:
            continue
        seen.add(key)
        unique.append(party)
    return unique


def _shared_user_clause(viewer=None, clinic_scope=None):
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    if not parties:
        return None

    now = utcnow()
    query = (
        db.session.query(DataShareAccess.user_id)
        .filter(DataShareAccess.user_id.isnot(None))
        .filter(DataShareAccess.revoked_at.is_(None))
        .filter(or_(DataShareAccess.expires_at.is_(None), DataShareAccess.expires_at > now))
    )
    party_clauses = [
        and_(
            DataShareAccess.granted_to_type == party_type,
            DataShareAccess.granted_to_id == party_id,
        )
        for party_type, party_id in parties
    ]
    if not party_clauses:
        return None
    query = query.filter(or_(*party_clauses))
    return User.id.in_(query.subquery())


def _user_visibility_clause(viewer=None, clinic_scope=None):
    """Return a SQLAlchemy clause enforcing user privacy for listings."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer and getattr(viewer, 'role', None) == 'admin':
        return true()

    if viewer and has_professional_access(viewer):
        return true()

    clauses = []

    if viewer:
        viewer_id = getattr(viewer, 'id', None)
        if viewer_id:
            clauses.append(User.id == viewer_id)
            clauses.append(User.added_by_id == viewer_id)

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    if clinic_ids:
        clauses.append(User.clinica_id.in_(list(clinic_ids)))

    shared_clause = _shared_user_clause(viewer=viewer, clinic_scope=clinic_scope)
    if shared_clause is not None:
        clauses.append(shared_clause)

    if not clauses:
        return false()

    return or_(*clauses)


def _can_view_user(user, viewer=None, clinic_scope=None):
    """Return ``True`` if the viewer can see the given user respecting privacy."""
    if user is None:
        return False

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer is None:
        return False

    viewer_id = getattr(viewer, 'id', None)
    if viewer_id and user.id == viewer_id:
        return True

    if viewer_id and user.added_by_id == viewer_id:
        return True

    shared_access = _resolve_shared_access_for_user(user, viewer=viewer, clinic_scope=clinic_scope)
    if getattr(viewer, 'role', None) == 'admin':
        return True

    if shared_access:
        return True

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    if has_professional_access(viewer):
        return bool(user.clinica_id and user.clinica_id in clinic_ids)

    return bool(user.clinica_id and user.clinica_id in clinic_ids)


def _resolve_shared_access_for_user(user, viewer=None, clinic_scope=None):
    if not user:
        return None
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    return find_active_share(parties, user_id=getattr(user, 'id', None))


def _resolve_shared_access_for_animal(animal, viewer=None, clinic_scope=None):
    if not animal:
        return None
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    user_id = getattr(animal, 'user_id', None)
    animal_id = getattr(animal, 'id', None)
    return find_active_share(parties, user_id=user_id, animal_id=animal_id)


def _resolve_shared_access_for_consulta(consulta, viewer=None, clinic_scope=None):
    if not consulta:
        return None
    if getattr(consulta, 'animal', None):
        return _resolve_shared_access_for_animal(consulta.animal, viewer=viewer, clinic_scope=clinic_scope)
    return None


def _log_data_share(access, *, event_type, resource_type, resource_id=None, actor=None):
    if not access:
        return None
    return log_data_share_event(
        access,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor,
    )


def _default_share_duration(days=None):
    value = days or current_app.config.get('DATA_SHARE_DEFAULT_DAYS', 30)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 30
    return max(value, 1)


def _serialize_share_request(req):
    clinic_name = getattr(req.clinic, 'nome', None)
    requester_name = getattr(req.requester, 'name', None)
    status = req.status
    if status == 'pending' and req.expires_at and req.expires_at <= utcnow():
        status = 'expired'
    return {
        'id': req.id,
        'token': req.token,
        'message': req.message,
        'status': status,
        'expires_at': req.expires_at.isoformat() if req.expires_at else None,
        'created_at': req.created_at.isoformat() if req.created_at else None,
        'clinic': clinic_name,
        'requester': requester_name,
        'animal': getattr(req.animal, 'name', None),
    }


def _serialize_share_access(access):
    clinic_name = getattr(access.source_clinic, 'nome', None)
    return {
        'id': access.id,
        'clinic': clinic_name,
        'expires_at': access.expires_at.isoformat() if access.expires_at else None,
        'expires_label': access.expires_at.strftime('%d/%m/%Y') if access.expires_at else None,
        'grant_reason': access.grant_reason,
    }


def _send_share_email(subject, recipients, body):
    if not recipients:
        return False
    try:
        msg = MailMessage(subject=subject, recipients=recipients, body=body)
        mail.send(msg)
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning('Falha ao enviar email de compartilhamento: %s', exc)
        return False


def _send_share_sms(phone, body):
    if not phone or not body:
        return False
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_SMS_FROM')
    if not all([account_sid, auth_token, from_number]):
        return False
    number = formatar_telefone(phone)
    try:
        client_cls = Client
        if client_cls is None:
            from twilio.rest import Client as client_cls
        client = client_cls(account_sid, auth_token)
        client.messages.create(body=body, from_=from_number, to=number)
        return True
    except Exception as exc:  # pragma: no cover - avoid test flakes
        current_app.logger.warning('Falha ao enviar SMS: %s', exc)
        return False


def _share_request_link(token):
    try:
        return url_for('tutor_sharing_dashboard', token=token, _external=True)
    except Exception:  # pragma: no cover - fallback when outside request
        return None


def _notify_tutor_share_request(share_request):
    tutor = share_request.tutor
    clinic_name = getattr(share_request.clinic, 'nome', 'uma clínica parceira')
    link = _share_request_link(share_request.token)
    lines = [
        f'Olá {tutor.name or "tutor"},',
        '',
        f'A clínica {clinic_name} está solicitando acesso aos dados do seu tutorado.',
    ]
    if share_request.animal:
        lines.append(f'Animal: {share_request.animal.name}.')
    if share_request.message:
        lines.extend(['', f'Mensagem da clínica:', share_request.message])
    if link:
        lines.extend(['', 'Para revisar o pedido, acesse o link seguro:', link])
    subject = 'Novo pedido de compartilhamento de dados - PetOrlândia'
    _send_share_email(subject, [tutor.email] if tutor.email else [], '\n'.join(lines))
    if tutor.phone:
        sms_body = f'PetOrlândia: {clinic_name} pediu acesso aos seus dados. Confirme em {link}' if link else (
            f'PetOrlândia: {clinic_name} pediu acesso aos seus dados.'
        )
        _send_share_sms(tutor.phone, sms_body)


def _notify_clinic_share_decision(share_request, approved):
    requester = share_request.requester
    if not requester:
        return
    clinic_name = getattr(share_request.clinic, 'nome', 'sua clínica')
    if approved:
        subject = 'Compartilhamento aprovado - PetOrlândia'
        status_line = 'foi aprovado'
    else:
        subject = 'Compartilhamento negado - PetOrlândia'
        status_line = 'foi negado'
    lines = [
        f'Olá {requester.name or "time"},',
        '',
        f'O pedido de compartilhamento com {share_request.tutor.name} {status_line}.',
        f'Clínica: {clinic_name}',
    ]
    if share_request.animal:
        lines.append(f'Animal: {share_request.animal.name}')
    if share_request.denial_reason and not approved:
        lines.extend(['', f'Motivo informado: {share_request.denial_reason}'])
    _send_share_email(subject, [requester.email] if requester.email else [], '\n'.join(lines))
    if requester.phone:
        sms_body = f'PetOrlândia: pedido com {share_request.tutor.name} {status_line}.'
        _send_share_sms(requester.phone, sms_body)


def _serialize_tutor_share_payload(user):
    now = utcnow()
    pending = (
        DataShareRequest.query.filter_by(tutor_id=user.id)
        .order_by(DataShareRequest.created_at.desc())
        .all()
    )
    active_access = (
        DataShareAccess.query.filter_by(user_id=user.id)
        .filter(DataShareAccess.revoked_at.is_(None))
        .filter(or_(DataShareAccess.expires_at.is_(None), DataShareAccess.expires_at > now))
        .order_by(DataShareAccess.created_at.desc())
        .all()
    )
    return {
        'pending_requests': [_serialize_share_request(req) for req in pending if req.is_pending()],
        'active_shares': [_serialize_share_access(access) for access in active_access if access.is_active],
    }


def _serialize_clinic_share_payload(user):
    requests = (
        DataShareRequest.query.filter_by(requested_by_id=user.id)
        .order_by(DataShareRequest.created_at.desc())
        .limit(25)
        .all()
    )
    clinic_ids = list(_collect_clinic_ids(viewer=user))
    active = []
    if clinic_ids:
        active = (
            DataShareAccess.query
            .filter(DataShareAccess.granted_to_type == DataSharePartyType.clinic)
            .filter(DataShareAccess.granted_to_id.in_(clinic_ids))
            .filter(DataShareAccess.revoked_at.is_(None))
            .filter(or_(DataShareAccess.expires_at.is_(None), DataShareAccess.expires_at > utcnow()))
            .order_by(DataShareAccess.created_at.desc())
            .limit(25)
            .all()
        )
    return {
        'pending_requests': [_serialize_share_request(req) for req in requests if req.is_pending()],
        'active_shares': [_serialize_share_access(access) for access in active],
    }


def _is_tutor_portal_user(user=None):
    user = user or (current_user if current_user.is_authenticated else None)
    if not user:
        return False
    worker = (getattr(user, 'worker', None) or '').lower()
    return worker not in {'veterinario', 'colaborador', 'admin'}


def get_user_or_404(user_id, *, viewer=None, clinic_scope=None):
    """Load a user enforcing privacy-aware visibility."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    user = User.query.get_or_404(user_id)
    shared_access = _resolve_shared_access_for_user(user, viewer=viewer, clinic_scope=clinic_scope)
    if not shared_access and not _can_view_user(user, viewer=viewer, clinic_scope=clinic_scope):
        abort(404)

    if shared_access:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='user',
            resource_id=user.id,
            actor=viewer,
        )
    return user


def ensure_clinic_access(clinica_id):
    """Abort with 404 if the current user cannot view the given clinic."""
    if not clinica_id or not current_user.is_authenticated:
        abort(404)
    if not can_view_clinic(current_user, clinica_id):
        abort(404)


def _viewer_operational_clinic_ids(viewer):
    """Return clinic IDs where the viewer can operate as staff/owner."""

    clinic_ids = []
    if not viewer:
        return clinic_ids

    if _user_is_clinic_owner(viewer):
        for clinic in getattr(viewer, 'clinicas', []) or []:
            clinic_id = getattr(clinic, 'id', None)
            if clinic_id and clinic_id not in clinic_ids:
                clinic_ids.append(clinic_id)

    worker_role = (getattr(viewer, 'worker', None) or '').lower()
    if worker_role == 'colaborador':
        viewer_clinic = getattr(viewer, 'clinica_id', None)
        if viewer_clinic and viewer_clinic not in clinic_ids:
            clinic_ids.append(viewer_clinic)

    vet_profile = getattr(viewer, 'veterinario', None)
    for clinic_id in _veterinarian_accessible_clinic_ids(vet_profile):
        if clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    for role in getattr(viewer, 'clinic_roles', []) or []:
        clinic_id = getattr(role, 'clinic_id', None)
        if clinic_id and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_animal_or_404(animal_id, *, viewer=None, clinic_scope=None):
    """Return animal if accessible to current user, otherwise 404."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    animal = Animal.query.get_or_404(animal_id)
    admin_access = bool(viewer and getattr(viewer, 'role', None) == 'admin')
    owner_access = bool(viewer and animal.user_id == viewer.id)
    added_by_access = bool(viewer and animal.added_by_id and animal.added_by_id == viewer.id)
    shared_access = _resolve_shared_access_for_animal(animal, viewer=viewer, clinic_scope=clinic_scope)
    if not admin_access and not shared_access and not owner_access and not added_by_access:
        ensure_clinic_access(animal.clinica_id)
    elif shared_access:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='animal',
            resource_id=animal.id,
            actor=viewer,
        )

    tutor_id = getattr(animal, "user_id", None)
    if tutor_id and animal.clinica_id:
        visibility_clause = _user_visibility_clause(viewer=viewer, clinic_scope=clinic_scope)
        tutor_visible = (
            db.session.query(User.id)
            .filter(User.id == tutor_id)
            .filter(visibility_clause)
            .first()
        )
        if not tutor_visible and not (shared_access or owner_access or added_by_access):
            abort(404)

    return animal


def get_consulta_or_404(consulta_id, *, viewer=None, clinic_scope=None):
    """Return consulta if accessible to current user, otherwise 404."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    consulta = Consulta.query.get_or_404(consulta_id)
    shared_access = _resolve_shared_access_for_consulta(consulta, viewer=viewer, clinic_scope=clinic_scope)
    if not shared_access:
        ensure_clinic_access(consulta.clinica_id)
    else:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='consulta',
            resource_id=consulta.id,
            actor=viewer,
        )
    return consulta


def _filter_records_by_clinic(records, clinic_id):
    """Return a list limited to the given clinic id.

    If clinic_id is None, returns an empty list to prevent data leakage
    between clinics.
    """

    if not records:
        return []

    if not clinic_id:
        # No clinic context - return empty to prevent showing other clinics' data
        return []

    items = list(records)
    return [item for item in items if getattr(item, 'clinica_id', None) == clinic_id]


def _clinic_orcamento_blocks(animal, clinic_id):
    return _filter_records_by_clinic(getattr(animal, 'blocos_orcamento', []) or [], clinic_id)


def _clinic_prescricao_blocks(animal, clinic_id):
    return _filter_records_by_clinic(getattr(animal, 'blocos_prescricao', []) or [], clinic_id)


def _render_orcamento_history(animal, clinic_id):
    blocos = _clinic_orcamento_blocks(animal, clinic_id)
    return render_template(
        'partials/historico_orcamentos.html',
        animal=animal,
        blocos_orcamento=blocos,
        clinic_scope_id=clinic_id,
    )


def _render_prescricao_history(animal, clinic_id):
    blocos = _clinic_prescricao_blocks(animal, clinic_id)
    return render_template(
        'partials/historico_prescricoes.html',
        animal=animal,
        blocos_prescricao=blocos,
        clinic_scope_id=clinic_id,
    )




MISSING_VET_PROFILE_MESSAGE = (
    "Para visualizar os convites de clínica, finalize seu cadastro de "
    "veterinário informando o CRMV e demais dados profissionais."
)


def _render_missing_vet_profile(form=None, profile_form=None):
    """Render the clinic invite page guiding the vet to complete the profile."""
    if form is None:
        form = ClinicInviteResponseForm()
    if profile_form is None:
        profile_form = VeterinarianProfileForm()
    return render_template(
        "clinica/clinic_invites.html",
        invites=[],
        form=form,
        missing_vet_profile=True,
        missing_vet_profile_message=MISSING_VET_PROFILE_MESSAGE,
        vet_profile_form=profile_form,
    )


def _build_vet_invites_context(response_form=None, vet_profile_form=None):
    """Return context data for clinic invites within the messages page."""
    show_clinic_invites = getattr(current_user, "worker", None) == "veterinario"

    if not show_clinic_invites:
        return {
            "show_clinic_invites": False,
            "clinic_invites": [],
            "clinic_invite_form": None,
            "vet_profile_form": None,
            "missing_vet_profile": False,
            "missing_vet_profile_message": MISSING_VET_PROFILE_MESSAGE,
        }

    if response_form is None:
        response_form = ClinicInviteResponseForm()

    vet_profile = getattr(current_user, "veterinario", None)
    invites = []
    missing_vet_profile = False

    if vet_profile is None:
        missing_vet_profile = True
        if vet_profile_form is None:
            vet_profile_form = VeterinarianProfileForm()
    else:
        invites = (
            VetClinicInvite.query.options(
                joinedload(VetClinicInvite.clinica).joinedload(Clinica.owner)
            )
            .filter_by(
                veterinario_id=vet_profile.id,
                status="pending",
            )
            .order_by(VetClinicInvite.created_at.desc())
            .all()
        )

    return {
        "show_clinic_invites": True,
        "clinic_invites": invites,
        "clinic_invite_form": response_form,
        "vet_profile_form": vet_profile_form,
        "missing_vet_profile": missing_vet_profile,
        "missing_vet_profile_message": MISSING_VET_PROFILE_MESSAGE,
    }


def _get_inbox_messages():
    """Return received messages with sender information for current user."""
    if not current_user.is_authenticated:
        return []

    mensagens = (
        Message.query.options(
            # sent_messages is lazy='select' by default now (see models/base.py);
            # the mensagens.html template reads msg.sender.sent_messages per row
            # to compute per-conversation unread counts, so eager-load it here
            # in batch instead of paying that tax on every User load site-wide.
            selectinload(Message.sender).selectinload(User.sent_messages),
            selectinload(Message.animal),
        )
        .filter_by(receiver_id=current_user.id)
        .order_by(Message.timestamp.desc().nullslast())
        .all()
    )

    return [mensagem for mensagem in mensagens if mensagem.sender is not None]


def _notify_admin_message(receiver, sender, message_content, conversation_url=None):
    """Send an email notification when an administrator sends a message.

    This keeps tutors and veterinarians informed even when they are
    outside da plataforma, addressing the reported communication gap where
    admin replies were silently stored without any alert.
    """

    if not receiver or not sender:
        return

    sender_role = (getattr(sender, "role", "") or "").lower()
    if sender_role != "admin":
        return

    email = (getattr(receiver, "email", "") or "").strip()
    if not email:
        return

    first_name_source = (getattr(receiver, "name", "") or "").strip()
    if first_name_source:
        first_name = first_name_source.split()[0]
    else:
        first_name = email.split("@")[0]

    if conversation_url is None:
        try:
            relative_url = url_for("conversa_admin")
            base_url = request.url_root.rstrip("/") if has_request_context() else ""
            conversation_url = f"{base_url}{relative_url}" if base_url else relative_url
        except Exception:  # pragma: no cover - defensive fallback
            conversation_url = None

    preview = (message_content or "").strip()
    if len(preview) > 280:
        preview = f"{preview[:277]}..."

    lines = [
        f"Olá {first_name},",
        "",
        "Você recebeu uma nova mensagem do administrador do PetOrlândia.",
    ]
    if preview:
        lines.extend(["", preview])
    if conversation_url:
        lines.extend([
            "",
            "Acesse suas mensagens para responder:",
            conversation_url,
        ])
    lines.extend(["", "Abraços,", "Equipe PetOrlândia"])

    body = "\n".join(lines)

    try:
        mail_msg = MailMessage(
            subject="Nova mensagem do administrador no PetOrlândia",
            recipients=[email],
            body=body,
        )
        mail.send(mail_msg)
    except Exception as exc:  # pragma: no cover - only log the failure
        current_app.logger.warning(
            "Falha ao enviar notificação de mensagem para %s: %s", email, exc
        )

    try:
        db.session.add(
            Notification(
                user_id=receiver.id,
                message=body,
                channel="email",
                kind="admin_message",
            )
        )
    except Exception as exc:  # pragma: no cover - logging only
        current_app.logger.warning(
            "Não foi possível registrar a notificação de mensagem: %s", exc
        )


def _render_messages_page(mensagens=None, **extra_context):
    """Render the messages page with optional overrides for clinic invites."""
    if mensagens is None:
        mensagens = _get_inbox_messages()

    context_overrides = extra_context.copy()
    response_form = context_overrides.pop("clinic_invite_form", None)
    vet_profile_form = context_overrides.pop("vet_profile_form", None)

    clinic_invite_context = _build_vet_invites_context(
        response_form=response_form,
        vet_profile_form=vet_profile_form,
    )
    clinic_invite_context.update(context_overrides)
    clinic_invite_context["mensagens"] = mensagens

    return render_template("mensagens/mensagens.html", **clinic_invite_context)


def _serialize_message_threads(mensagens):
    """Aggregate messages into conversation threads for the authenticated user."""
    threads = {}

    for mensagem in mensagens:
        last_timestamp = mensagem.timestamp or datetime.min

        conversation_partner_id = (
            mensagem.receiver_id
            if mensagem.sender_id == current_user.id
            else mensagem.sender_id
        )
        conversation_partner = (
            mensagem.receiver
            if mensagem.sender_id == current_user.id
            else mensagem.sender
        )

        key = (conversation_partner_id, mensagem.animal_id or None)

        thread = threads.get(key)
        if thread is None or last_timestamp > thread["last_message_dt"]:
            if mensagem.animal is not None:
                conversation_url = url_for(
                    "conversa",
                    animal_id=mensagem.animal_id,
                    user_id=conversation_partner_id,
                )
                animal_payload = {
                    "id": mensagem.animal_id,
                    "name": mensagem.animal.name,
                }
            else:
                conversation_url = url_for(
                    "conversa_admin", user_id=conversation_partner_id
                )
                animal_payload = None

            partner_name = getattr(conversation_partner, "name", None) or "Usuário"
            partner_initial = (
                partner_name.strip()[:1].upper() if partner_name.strip() else "?"
            )

            thread = {
                "id": f"{conversation_partner_id}-{mensagem.animal_id or 'admin'}",
                "sender": {
                    "id": conversation_partner_id,
                    "name": partner_name,
                    "profile_photo": getattr(conversation_partner, "profile_photo", None),
                    "initials": partner_initial,
                },
                "animal": animal_payload,
                "last_message_dt": last_timestamp,
                "last_message_at": last_timestamp.isoformat(),
                "unread_count": 0,
                "conversation_url": conversation_url,
            }
            threads[key] = thread
        else:
            if last_timestamp > thread["last_message_dt"]:
                thread["last_message_dt"] = last_timestamp
                thread["last_message_at"] = last_timestamp.isoformat()

        if not mensagem.lida:
            threads[key]["unread_count"] += 1

    sorted_threads = sorted(
        threads.values(), key=lambda thread: thread["last_message_dt"], reverse=True
    )

    for thread in sorted_threads:
        thread.pop("last_message_dt", None)

    return sorted_threads


def _user_initials_from_name(full_name: Optional[str]) -> str:
    """Return a compact set of initials for display-only contexts.

    The function gracefully handles single-word names, multi-word names and
    missing values while ensuring the returned value is always uppercase.
    """

    if not full_name:
        return "?"

    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "?"

    if len(parts) == 1:
        return parts[0][:2].upper()

    return (parts[0][0] + parts[-1][0]).upper()


def _build_user_avatar_map(users: Iterable["User"]) -> Dict[int, Dict[str, str]]:
    """Prepare avatar payloads (photo + initials) keyed by user id."""

    avatar_map: Dict[int, Dict[str, str]] = {}
    for user in users:
        if not user or getattr(user, "id", None) is None:
            continue

        if user.id in avatar_map:
            continue

        avatar_map[user.id] = {
            "photo": getattr(user, "profile_photo", None),
            "initials": _user_initials_from_name(getattr(user, "name", None)),
        }

    return avatar_map


def _ensure_veterinarian_profile(form=None):
    """Return veterinarian profile or render guidance message when missing."""
    if not has_veterinarian_profile(current_user):
        abort(403)

    vet_profile = current_user.veterinario
    if vet_profile is None:
        return None, _render_missing_vet_profile(form=form)

    membership = ensure_veterinarian_membership(vet_profile)
    if membership and not membership.is_active():
        flash('Sua assinatura de veterinário está inativa. Regularize para continuar.', 'warning')
        return None, redirect(url_for('veterinarian_membership'))

    return vet_profile, None


def _get_veterinarian_membership_price() -> Decimal:
    """Return the configured membership price for veterinarians."""

    return VeterinarianSettings.membership_price_amount()


def _format_brl_price(value) -> str | None:
    if value is None:
        return None
    try:
        amount = Decimal(value).quantize(Decimal('0.01'))
    except Exception:  # noqa: BLE001
        return None
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _public_pricing_config() -> dict:
    trial_days = int(current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30) or 30)
    show_price = bool(current_app.config.get('EXIBIR_PRECO_NO_CONVITE_CLINICA', True))
    price = None
    formatted_price = None
    try:
        price = _get_veterinarian_membership_price()
        formatted_price = _format_brl_price(price)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("Falha ao carregar pricing publico: %s", exc)
        show_price = False

    return {
        'trial_dias_clinica': trial_days,
        'preco_mensal_clinica': float(price) if price is not None else None,
        'preco_formatado': formatted_price,
        'moeda': 'BRL',
        'exibir_preco_no_convite_clinica': bool(show_price and formatted_price),
        'fonte': 'site_public_pricing',
    }


def _resolve_membership_from_payment(payment):
    external = getattr(payment, 'external_reference', '') or ''
    match = re.match(r'vet-membership-(\d+)', external)
    if not match:
        return None
    membership_id = int(match.group(1))
    return VeterinarianMembership.query.get(membership_id)


def _sync_veterinarian_membership_payment(payment):
    membership = _resolve_membership_from_payment(payment)
    if not membership:
        return

    membership.last_payment_id = payment.id
    if payment.status == PaymentStatus.COMPLETED:
        cycle_days = current_app.config.get('VETERINARIAN_MEMBERSHIP_BILLING_DAYS', 30)
        now = utcnow()
        start_from = membership.paid_until if membership.paid_until and membership.paid_until > now else now
        membership.paid_until = start_from + timedelta(days=cycle_days)
        membership.ensure_trial_dates(current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30))
    db.session.add(membership)


_HEALTH_ONBOARDING_RE = re.compile(r"health-onboarding-(\d+)")


def _resolve_health_onboarding(external_reference: str):
    match = _HEALTH_ONBOARDING_RE.match(external_reference or "")
    if not match:
        return None
    onboarding_id = int(match.group(1))
    return HealthPlanOnboarding.query.get(onboarding_id)


def _sync_health_subscription_from_onboarding(onboarding, payment_status, payment=None):
    if not onboarding or payment_status != PaymentStatus.COMPLETED:
        return

    if not onboarding.animal or onboarding.animal.user_id != onboarding.user_id:
        current_app.logger.warning(
            "Onboarding %s ignorado: tutor não corresponde ao animal.",
            getattr(onboarding, "id", None),
        )
        return

    if payment and payment.user_id != onboarding.user_id:
        current_app.logger.warning(
            "Pagamento não pertence ao tutor do onboarding %s.",
            getattr(onboarding, "id", None),
        )
        return

    now = utcnow()
    subscription = (
        HealthSubscription.query
        .filter_by(
            animal_id=onboarding.animal_id,
            plan_id=onboarding.plan_id,
            user_id=onboarding.user_id,
        )
        .order_by(HealthSubscription.start_date.desc())
        .first()
    )

    if subscription:
        if not subscription.start_date:
            subscription.start_date = now
    else:
        subscription = HealthSubscription(
            animal_id=onboarding.animal_id,
            plan_id=onboarding.plan_id,
            user_id=onboarding.user_id,
            start_date=now,
        )
        db.session.add(subscription)

    subscription.guardian_document = onboarding.guardian_document
    subscription.animal_document = onboarding.animal_document
    subscription.contract_reference = onboarding.contract_reference
    subscription.consent_ip = onboarding.consent_ip
    subscription.consent_signed_at = onboarding.consent_signed_at
    subscription.plan_id = onboarding.plan_id
    subscription.active = True

    if payment:
        subscription.payment = payment

    onboarding.status = "paid"
    db.session.add(onboarding)


# ----------------------------------------------------------------
# CEP lookup API
# ----------------------------------------------------------------















# ----------------------------------------------------------------
# 7)  Login & serializer
# ----------------------------------------------------------------
from models import User   # noqa: E402  (import depois de alias)

@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


from flask_login import user_logged_in  # noqa: E402


@user_logged_in.connect_via(app)
def _registrar_ultimo_login(sender, user, **extra):
    # Cobre todos os pontos de login (formulário, OAuth, primeiro acesso).
    try:
        user.last_login = datetime.now(BR_TZ)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Falha ao registrar last_login do usuário %s', getattr(user, 'id', '?'))


login.login_view = "login_view"
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

def _ensure_registration_flow_schema() -> None:
    """Garante colunas/tabelas dos fluxos de cadastro de parceiros.

    Precisa rodar no startup (e não por request) porque a coluna
    ``clinica.status`` participa de todo SELECT do modelo Clinica.
    """
    from models import PartnerInvite

    try:
        columns = {column['name'] for column in inspect(db.engine).get_columns('clinica')}
        if 'status' not in columns:
            db.session.execute(text(
                "ALTER TABLE clinica ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ativa'"
            ))
        if 'created_at' not in columns:
            db.session.execute(text('ALTER TABLE clinica ADD COLUMN created_at TIMESTAMP'))
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        app.logger.warning('Falha ao garantir colunas de status da clínica: %s', exc)
    try:
        PartnerInvite.__table__.create(db.engine, checkfirst=True)
    except Exception as exc:  # noqa: BLE001
        app.logger.warning('Falha ao garantir tabela partner_invite: %s', exc)


# ----------------------------------------------------------------
# 8)  Admin & blueprints
# ----------------------------------------------------------------
with app.app_context():
    from admin import init_admin, _is_admin  # import interno evita loop
    init_admin(app)
    _ensure_registration_flow_schema()
    # outras blueprints ->  from views import bp as views_bp ; app.register_blueprint(views_bp)

# (rotas podem ser definidas em módulos separados e registrados via blueprint)
# ────────────────────────────── fim ─────────────────────────────

# Context processors e cache de badges vivem em context_processors.py.
from context_processors import (
    register_context_processors,
    _get_cached_context,
    _set_cached_context,
    _invalidate_cached_context,
    _invalidate_admin_unread_cache,
    _invalidate_admin_action_cache,
)

register_context_processors(app)








s = URLSafeTimedSerializer(app.config['SECRET_KEY'])






_FIRST_ACCESS_EMAIL_DOMAINS = (
    '@petorlandia.local',
    '@cadastro.petorlandia.local',
    '@convite.petorlandia.local',
)
_FIRST_ACCESS_TOKEN_MAX_AGE = 60 * 60 * 24 * 60


def _is_provisional_first_access_user(user: User | None) -> bool:
    email = normalize_email(getattr(user, 'email', None)) or ''
    return bool(user and email.endswith(_FIRST_ACCESS_EMAIL_DOMAINS))


def _first_access_invite_from_token(token: str | None):
    token = (token or '').strip()
    if not token:
        return None
    _ensure_external_onboarding_invite_table()
    invite = ExternalOnboardingInvite.query.filter_by(token=token).first()
    if not invite or invite.invite_type != 'tutor':
        return None
    if invite.expires_at and invite.expires_at < datetime.now(BR_TZ):
        return None
    return invite


def _first_access_token_for_user(user: User) -> str:
    return s.dumps({'user_id': user.id}, salt='first-access-salt')


def _first_access_user_from_signed_token(token: str | None):
    token = (token or '').strip()
    if not token:
        return None
    try:
        payload = s.loads(token, salt='first-access-salt', max_age=_FIRST_ACCESS_TOKEN_MAX_AGE)
    except Exception:
        return None
    user_id = payload.get('user_id') if isinstance(payload, dict) else payload
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def _first_access_url_for_user(user: User, *, next_url: str | None = None, _external: bool = False) -> str:
    kwargs = {
        'token': _first_access_token_for_user(user),
        '_external': _external,
    }
    if next_url:
        kwargs['next'] = next_url
    return url_for('first_access', **kwargs)


def _first_access_user_allowed(user: User | None, invite=None, token_user: User | None = None) -> bool:
    if not user:
        return False
    if token_user:
        return token_user.id == user.id
    if _is_provisional_first_access_user(user):
        return True
    return bool(invite and invite.tutor_id == user.id)


def _first_access_next_url(invite=None) -> str:
    raw_next = request.values.get('next') or session.get('first_access_next')
    if raw_next:
        return _sanitize_login_next_url(raw_next)
    if invite and getattr(invite, 'animal_id', None):
        return url_for('ficha_animal', animal_id=invite.animal_id)
    return url_for('index')







#admin configuration




# Rota principal




















def _format_pmo_certificate_date(value):
    return value.strftime('%d/%m/%Y') if value else 'A confirmar'


def _pmo_protocol_label(visit):
    reference = getattr(visit, 'updated_at', None) or getattr(visit, 'synced_at', None) or date.today()
    if isinstance(reference, datetime):
        year = reference.year
    else:
        year = getattr(reference, 'year', date.today().year)
    return f"PMO-{year}-{getattr(visit, 'id', 0):04d}"


def _pmo_status_labels():
    return {
        'pendente': 'Vacinação pendente',
        'vacinado': 'Vacinado',
        'ausente': 'Morador ausente',
        'remarcar': 'Remarcar visita',
        'recusou': 'Vacina recusada',
        'parcial': 'Parcialmente vacinado',
    }


def _pmo_status_context(status):
    labels = _pmo_status_labels()
    messages = {
        'vacinado': 'Dose registrada. Guarde este comprovante e acompanhe a data do reforco anual.',
        'pendente': 'A equipe ainda vai confirmar ou realizar a visita. Mantenha o telefone atualizado.',
        'ausente': 'A equipe esteve no endereco, mas nao encontrou o morador. Aguarde contato para nova orientacao.',
        'remarcar': 'Ha uma solicitacao de remarcacao. A equipe devera combinar uma nova tentativa.',
        'recusou': 'A vacina foi marcada como recusada. Em caso de duvida, procure a equipe da campanha.',
        'parcial': 'Parte dos animais foi vacinada. Confira a situacao individual de cada pet.',
    }
    normalized = status or 'pendente'
    return {
        'key': normalized,
        'label': labels.get(normalized, normalized.capitalize()),
        'message': messages.get(normalized, 'Acompanhe o status da campanha por este link.'),
    }


def _pmo_booster_countdown_label(next_booster_date):
    if not next_booster_date:
        return ""
    days_remaining = (next_booster_date - date.today()).days
    if days_remaining > 1:
        return f"Faltam {days_remaining} dias para o reforco anual."
    if days_remaining == 1:
        return "Falta 1 dia para o reforco anual."
    if days_remaining == 0:
        return "O reforco anual esta indicado a partir de hoje."
    if days_remaining == -1:
        return "O reforco anual venceu ha 1 dia."
    return f"O reforco anual venceu ha {abs(days_remaining)} dias."


def _is_pmo_rabies_vaccine(vaccine):
    name = (getattr(vaccine, 'nome', '') or '').lower()
    kind = (getattr(vaccine, 'tipo', '') or '').lower()
    text = f"{name} {kind}"
    return any(term in text for term in ('antirrab', 'anti-rab', 'raiva', 'rabic'))


def _pmo_animal_booster_guidance(animals):
    animal_ids = [animal.id for animal in animals if getattr(animal, 'id', None)]
    if not animal_ids:
        return {}

    vaccines = (
        Vacina.query
        .filter(Vacina.animal_id.in_(animal_ids), Vacina.aplicada.is_(True), Vacina.aplicada_em.isnot(None))
        .order_by(Vacina.aplicada_em.desc(), Vacina.criada_em.desc())
        .all()
    )
    latest_by_animal = {}
    for vaccine in vaccines:
        if vaccine.animal_id in latest_by_animal or not _is_pmo_rabies_vaccine(vaccine):
            continue
        latest_by_animal[vaccine.animal_id] = vaccine

    guidance = {}
    for animal in animals:
        vaccine = latest_by_animal.get(animal.id)
        if not vaccine:
            guidance[animal.id] = {
                'status': 'unknown',
                'message': 'Sem registro de vacina antirrabica aplicada no PetOrlandia.',
                'countdown': '',
                'last_date': None,
                'next_date': None,
            }
            continue
        next_booster_date = vaccine.proxima_dose or (vaccine.aplicada_em + relativedelta(years=1))
        days_remaining = (next_booster_date - date.today()).days
        if days_remaining > 0:
            message = (
                f"{animal.name or 'Este pet'} ja recebeu vacina antirrabica ha menos de 1 ano. "
                "Normalmente nao e necessario vacinar novamente antes do reforco anual."
            )
            status = 'protected'
        elif days_remaining == 0:
            message = f"O reforco anual de {animal.name or 'este pet'} esta indicado a partir de hoje."
            status = 'due'
        else:
            message = f"O reforco anual de {animal.name or 'este pet'} esta vencido."
            status = 'overdue'
        guidance[animal.id] = {
            'status': status,
            'message': message,
            'countdown': _pmo_booster_countdown_label(next_booster_date),
            'last_date': vaccine.aplicada_em,
            'next_date': next_booster_date,
        }
    return guidance


def _wrap_pmo_pdf_text(text, max_chars):
    words = str(text or '').split()
    lines = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:max_chars]
    if current:
        lines.append(current)
    return lines


def _pmo_pdf_text(value):
    text = str(value or '')
    replacements = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
        'é': 'e', 'ê': 'e', 'É': 'E', 'Ê': 'E',
        'í': 'i', 'Í': 'I',
        'ó': 'o', 'õ': 'o', 'ô': 'o', 'Ó': 'O', 'Õ': 'O', 'Ô': 'O',
        'ú': 'u', 'Ú': 'U',
        'ç': 'c', 'Ç': 'C',
        '–': '-', '—': '-', '“': '"', '”': '"', '’': "'",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.encode('latin-1', 'ignore').decode('latin-1')


def _pmo_pdf_escape(value):
    text = _pmo_pdf_text(value)
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _build_simple_pmo_pdf(lines):
    objects = []

    def add_object(payload):
        objects.append(payload)
        return len(objects)

    content = '\n'.join(lines).encode('latin-1', 'ignore')
    catalog_id = add_object('<< /Type /Catalog /Pages 2 0 R >>')
    pages_id = add_object('<< /Type /Pages /Kids [3 0 R] /Count 1 >>')
    page_id = add_object('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>')
    font_regular_id = add_object('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    font_bold_id = add_object('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>')
    content_id = add_object(f'<< /Length {len(content)} >>\nstream\n{content.decode("latin-1")}\nendstream')

    assert (catalog_id, pages_id, page_id, font_regular_id, font_bold_id, content_id) == (1, 2, 3, 4, 5, 6)

    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f'{index} 0 obj\n{payload}\nendobj\n'.encode('latin-1', 'ignore'))
    xref_offset = len(pdf)
    pdf.extend(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode('ascii'))
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    pdf.extend(
        (
            f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'
            f'startxref\n{xref_offset}\n%%EOF\n'
        ).encode('ascii')
    )
    return bytes(pdf)


def _export_vacina_pmo_pet_certificate_pdf(
    *,
    visit,
    pmo_animal,
    campaign_vaccine,
    effective_status,
    next_booster_date,
):
    vaccine_name = campaign_vaccine.nome if campaign_vaccine else 'Vacina Antirrabica'
    vaccine_lot = campaign_vaccine.lote if campaign_vaccine and campaign_vaccine.lote else 'Registro municipal'
    vaccine_maker = campaign_vaccine.fabricante if campaign_vaccine and campaign_vaccine.fabricante else 'Campanha PMO'
    applied_at = campaign_vaccine.aplicada_em if campaign_vaccine and campaign_vaccine.aplicada_em else visit.vaccine_date
    species = 'Cao' if pmo_animal.species == 'cao' else 'Gato'
    statement = (
        f'Certificamos que o animal {pmo_animal.name}, sob responsabilidade de {visit.tutor_name}, '
        f'consta como {effective_status} na campanha municipal de vacinacao antirrabica. '
        'Este documento pode ser apresentado como comprovante para guarda pessoal do tutor.'
    )

    lines = [
        'q 0.929 0.957 1 rg 0 638 595 204 re f Q',
        'q 0.906 0.973 0.961 rg 421 662 104 104 re f Q',
        'q 0.078 0.129 0.239 rg BT /F2 23 Tf 52 760 Td (Certificado de Vacinacao Antirrabica) Tj ET Q',
        'q 0.365 0.408 0.478 rg BT /F1 11 Tf 52 738 Td (Campanha municipal de vacinacao - Prefeitura de Orlandia) Tj ET Q',
        'q 0.031 0.498 0.357 rg 52 682 146 30 re f Q',
        f'q 1 1 1 rg BT /F2 10 Tf 87 692 Td ({"VACINADO" if effective_status == "vacinado" else _pmo_pdf_escape(effective_status.upper())}) Tj ET Q',
        'q 1 1 1 rg 52 510 491 126 re f Q',
        'q 0.859 0.890 0.933 RG 52 510 491 126 re S Q',
        f'q 0.078 0.129 0.239 rg BT /F2 18 Tf 76 598 Td ({_pmo_pdf_escape(pmo_animal.name)}) Tj ET Q',
        f'q 0.365 0.408 0.478 rg BT /F1 10 Tf 76 578 Td ({_pmo_pdf_escape(f"{species} registrado para {visit.tutor_name}")}) Tj ET Q',
    ]

    field_rows = [
        [('Data da aplicacao', _format_pmo_certificate_date(applied_at)), ('Vacina', vaccine_name), ('Fabricante', vaccine_maker)],
        [('Lote', vaccine_lot), ('Proximo reforco', _format_pmo_certificate_date(next_booster_date)), ('Endereco', visit.address or 'Nao informado')],
    ]
    x_positions = [76, 250, 392]
    y_positions = [552, 519]
    for row_index, row in enumerate(field_rows):
        for col_index, (label, value) in enumerate(row):
            x = x_positions[col_index]
            y = y_positions[row_index]
            lines.append(f'q 0.365 0.408 0.478 rg BT /F2 7.8 Tf {x} {y} Td ({_pmo_pdf_escape(label.upper())}) Tj ET Q')
            for line_index, text_line in enumerate(_wrap_pmo_pdf_text(value, 24)):
                lines.append(f'q 0.078 0.129 0.239 rg BT /F2 9.2 Tf {x} {y - 13 - (line_index * 10)} Td ({_pmo_pdf_escape(text_line)}) Tj ET Q')

    lines.extend([
        'q 0.078 0.129 0.239 rg BT /F2 13 Tf 52 466 Td (Declaracao) Tj ET Q',
        'q 0.859 0.890 0.933 RG 136 470 m 543 470 l S Q',
        'q 0.984 0.992 1 rg 52 356 491 82 re f Q',
        'q 0.859 0.890 0.933 RG 52 356 491 82 re S Q',
    ])
    statement_y = 414
    for line_index, text_line in enumerate(_wrap_pmo_pdf_text(statement, 86)):
        lines.append(f'q 0.078 0.129 0.239 rg BT /F1 10.5 Tf 76 {statement_y - (line_index * 15)} Td ({_pmo_pdf_escape(text_line)}) Tj ET Q')

    issued_at_text = _pmo_pdf_escape(f"Emitido em {date.today().strftime('%d/%m/%Y')}")
    lines.extend([
        'q 0.859 0.890 0.933 RG 70 258 m 250 258 l S Q',
        'q 0.859 0.890 0.933 RG 345 258 m 525 258 l S Q',
        'q 0.365 0.408 0.478 rg BT /F1 9 Tf 100 242 Td (Responsavel pela campanha) Tj ET Q',
        'q 0.365 0.408 0.478 rg BT /F1 9 Tf 391 242 Td (Tutor responsavel) Tj ET Q',
        'q 0.059 0.404 1 rg 52 60 491 34 re f Q',
        'q 1 1 1 rg BT /F2 8.5 Tf 70 73 Td (PetOrlandia - Carteirinha digital da campanha PMO) Tj ET Q',
        f'q 1 1 1 rg BT /F1 8.5 Tf 416 73 Td ({issued_at_text}) Tj ET Q',
    ])

    pdf_bytes = _build_simple_pmo_pdf(lines)
    buffer = BytesIO(pdf_bytes)

    safe_name = re.sub(r'[^A-Za-z0-9_-]+', '-', pmo_animal.name or 'pet').strip('-') or 'pet'
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'certificado-vacina-antirrabica-{safe_name}.pdf',
    )










import threading as _pmo_threading
_pmo_status_sync_lock = _pmo_threading.Lock()




_pmo_doses_compile_lock = _pmo_threading.Lock()








































# _user_is_clinic_owner / _user_can_access_accounting migraram para helpers.py

def _ensure_accounting_access():
    """Abort with 403 when the current user lacks accounting permissions."""

    if not _user_can_access_accounting():
        abort(403)


def _accounting_accessible_clinics():
    """Return (clinics, clinic_ids) accessible for the accounting module."""

    clinics = []
    clinic_repo = ClinicRepository()
    if _is_admin():
        clinics = clinic_repo.list_all_ordered()
        return clinics, {clinic.id for clinic in clinics if clinic.id}

    accessible_ids = set()
    if current_user.is_authenticated:
        accessible_ids.update(_collect_clinic_ids(viewer=current_user))
        for clinic in getattr(current_user, 'clinicas', []) or []:
            if clinic and clinic.id:
                accessible_ids.add(clinic.id)
                clinics.append(clinic)

    existing_ids = {clinic.id for clinic in clinics if clinic.id}
    missing_ids = [cid for cid in accessible_ids if cid and cid not in existing_ids]
    if missing_ids:
        clinics.extend(clinic_repo.list_by_ids(missing_ids))

    clinics.sort(key=lambda clinic: (clinic.nome or '').lower())
    return clinics, {clinic.id for clinic in clinics if clinic.id}


def _select_accounting_clinic(clinics, accessible_ids, requested_clinic_id=None):
    """Return the clinic to use in accounting views.

    Preference order:
    1. Explicit request (if accessible)
    2. The user's own clinic (if accessible)
    3. First available clinic
    """

    def _find_clinic(clinic_id):
        return next((clinic for clinic in clinics if clinic.id == clinic_id), None)

    if requested_clinic_id and requested_clinic_id in accessible_ids:
        return _find_clinic(requested_clinic_id)

    preferred_clinic_id = getattr(current_user, 'clinica_id', None)
    if preferred_clinic_id and preferred_clinic_id in accessible_ids:
        preferred_clinic = _find_clinic(preferred_clinic_id)
        if preferred_clinic:
            return preferred_clinic

    return clinics[0] if clinics else None


def _parse_month_parameter(month_value):
    base_date = date.today().replace(day=1)
    if not month_value:
        return base_date
    try:
        year_str, month_str = month_value.split('-', 1)
        parsed_date = date(int(year_str), int(month_str), 1)
    except (ValueError, TypeError):
        return base_date
    return parsed_date


def _format_month_parameter(reference_date):
    if reference_date is None:
        reference_date = date.today()
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()
    return reference_date.replace(day=1).strftime('%Y-%m')


def _sync_pj_payment_classification(payment):
    """Create or update the classified transaction entry for a PJ payment."""

    if not payment or not payment.id:
        return

    reference_date = payment.data_pagamento or payment.data_servico or date.today()
    entry_datetime = datetime.combine(reference_date, time.min)
    month_reference = reference_date.replace(day=1)

    classification = ClassifiedTransaction.query.filter_by(
        origin='pj_payment', raw_id=str(payment.id)
    ).first()
    if classification is None:
        classification = ClassifiedTransaction(
            origin='pj_payment',
            raw_id=str(payment.id),
        )

    description = f"Pagamento PJ - {payment.prestador_nome}"[:255]
    classification.clinic_id = payment.clinic_id
    classification.category = 'pagamento_pj'
    classification.subcategory = determine_pj_payment_subcategory(
        getattr(payment, 'tipo_prestador', None)
    )
    classification.description = description
    classification.value = payment.valor
    classification.date = entry_datetime
    classification.month = month_reference
    db.session.add(classification)


_PAYMENT_STATUS_ALIASES = {
    'pendente': 'pending',
    'pending': 'pending',
    'in_process': 'pending',
    'in_mediation': 'pending',
    'aguardando': 'pending',
    'pago': 'paid',
    'paid': 'paid',
    'success': 'paid',
    'approved': 'paid',
    'authorized': 'paid',
    'completed': 'paid',
    'falha': 'failed',
    'falhou': 'failed',
    'erro': 'failed',
    'failed': 'failed',
    'cancelado': 'failed',
    'cancelled': 'failed',
    'canceled': 'failed',
    'rejected': 'failed',
    'refunded': 'failed',
    'expired': 'failed',
    'charged_back': 'failed',
    'rascunho': 'draft',
    'draft': 'draft',
}


def _normalize_payment_status(raw_status: Optional[str]) -> str:
    normalized = (raw_status or '').strip().lower()
    return _PAYMENT_STATUS_ALIASES.get(normalized, normalized)


def _normalize_external_payment_status(raw_status: Optional[str]) -> str:
    normalized = _normalize_payment_status(raw_status)
    if normalized in {'pending', 'paid', 'failed'}:
        return normalized
    return 'pending'


def _sync_orcamento_payment_classification(record):
    """Create/update classified transactions for Orcamento or Bloco payments."""

    if record is None or not getattr(record, 'id', None):
        return

    clinic_id = getattr(record, 'clinica_id', None)
    if not clinic_id:
        return

    status = _normalize_payment_status(getattr(record, 'payment_status', None))
    raw_prefix = 'bloco_orcamento' if isinstance(record, BlocoOrcamento) else 'orcamento'
    raw_id = f"{raw_prefix}:{record.id}"
    origin = 'orcamento_payment'

    def _delete_entry():
        (
            ClassifiedTransaction.query.filter_by(origin=origin, raw_id=raw_id)
            .delete(synchronize_session=False)
        )

    if status in {'', 'draft', 'failed'}:
        _delete_entry()
        return

    if status not in {'pending', 'paid'}:
        return

    if isinstance(record, BlocoOrcamento):
        gross_value = record.total_liquido
        created_at = getattr(record, 'data_criacao', None)
        base_description = (record.tutor_notes or '').strip()
        subcategory = 'bloco_orcamento'
    else:
        gross_value = record.total
        created_at = getattr(record, 'created_at', None)
        base_description = (record.descricao or '').strip()
        subcategory = 'orcamento'

    try:
        value = Decimal(gross_value)
    except (InvalidOperation, TypeError):
        value = Decimal('0.00')

    reference_dt = None
    if status == 'paid':
        reference_dt = getattr(record, 'paid_at', None)
    if reference_dt is None:
        reference_dt = created_at
    if reference_dt is None:
        reference_dt = utcnow()
    elif isinstance(reference_dt, date) and not isinstance(reference_dt, datetime):
        reference_dt = datetime.combine(reference_dt, time.min)
    elif isinstance(reference_dt, datetime) and reference_dt.tzinfo:
        reference_dt = reference_dt.astimezone(timezone.utc).replace(tzinfo=None)

    if isinstance(value, (int, float)):
        value = Decimal(str(value))
    if not isinstance(value, Decimal):
        value = Decimal('0.00')

    category = 'receita_servico' if status == 'paid' else 'recebivel_orcamento'
    base_label = 'Bloco de orçamento' if isinstance(record, BlocoOrcamento) else 'Orçamento'
    description = f"{base_label} #{record.id}"
    if base_description:
        description = f"{description} - {base_description}"
    description = description[:255]

    classification = ClassifiedTransaction.query.filter_by(
        origin=origin, raw_id=raw_id
    ).first()
    if classification is None:
        classification = ClassifiedTransaction(origin=origin, raw_id=raw_id)

    classification.clinic_id = clinic_id
    classification.date = reference_dt
    classification.month = reference_dt.date().replace(day=1)
    classification.description = description
    classification.value = value
    classification.category = category
    classification.subcategory = subcategory
    db.session.add(classification)


def _delete_pj_payment_classification(payment_id):
    if not payment_id:
        return
    ClassifiedTransaction.query.filter_by(origin='pj_payment', raw_id=str(payment_id)).delete()


# Comandos CLI vivem em cli.py.
from cli import register_cli_commands

register_cli_commands(app)






def _decimal_json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _decimal_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimal_json(item) for item in value]
    return value


def _selected_accounting_context():
    clinics, accessible_ids = _accounting_accessible_clinics()
    selected_clinic = _select_accounting_clinic(
        clinics,
        accessible_ids,
        requested_clinic_id=request.args.get('clinica_id', type=int),
    )
    selected_month = _parse_month_parameter(request.args.get('mes'))
    return clinics, selected_clinic, selected_month
















def _describe_pj_payments_schema_error(exc: ProgrammingError) -> Optional[tuple[str, str]]:
    """Return log and user friendly messages for pj_payments schema issues."""

    original_message = str(getattr(exc, "orig", exc))
    normalized = original_message.lower()
    if "pj_payments" not in normalized:
        return None

    if "column" in normalized and (
        "does not exist" in normalized or "undefinedcolumn" in normalized
    ):
        column_name = None
        column_match = re.search(
            r"column\s+([\w\.\"]+)\s+(?:of\s+relation\s+[\w\"]+\s+)?does\s+not\s+exist",
            original_message,
            re.IGNORECASE,
        )
        if column_match:
            identifier = column_match.group(1).strip('"')
            column_name = identifier.split('.')[-1]
        if not column_name:
            column_name = sorted(REQUIRED_PJ_PAYMENT_COLUMNS)[0]
        return (
            "Coluna %s ausente na tabela pj_payments. Execute as migrações do banco para habilitar o módulo." % column_name,
            "O módulo de pagamentos PJ ainda não está disponível porque a coluna %s da tabela pj_payments não existe. Execute as migrações do banco para adicioná-la." % column_name,
        )

    if (
        "does not exist" in normalized
        or "undefinedtable" in normalized
        or "no such table" in normalized
    ):
        return (
            "Tabela pj_payments ausente. Execute as migrações do banco para habilitar o módulo.",
            "O módulo de pagamentos PJ ainda não está disponível porque a tabela pj_payments não existe. Execute as migrações do banco para criá-la.",
        )

    return None


REQUIRED_PLANTONISTA_COLUMNS = {
    'id',
    'clinic_id',
    'medico_nome',
    'turno',
    'inicio',
    'fim',
    'valor_previsto',
    'status',
    'nota_fiscal_recebida',
    'retencao_validada',
    'pj_payment_id',
}


def _describe_plantonista_schema_error(exc: ProgrammingError) -> Optional[tuple[str, str]]:
    """Return log and user friendly messages for plantonista schema issues."""

    original_message = str(getattr(exc, "orig", exc))
    normalized = original_message.lower()
    if "plantonista_escalas" not in normalized:
        return None

    if "column" in normalized and (
        "does not exist" in normalized or "undefinedcolumn" in normalized
    ):
        column_name = None
        column_match = re.search(
            r"column\s+([\w\.\"]+)\s+(?:of\s+relation\s+[\w\"]+\s+)?does\s+not\s+exist",
            original_message,
            re.IGNORECASE,
        )
        if column_match:
            identifier = column_match.group(1).strip('"')
            column_name = identifier.split('.')[-1]
        if not column_name:
            column_name = sorted(REQUIRED_PLANTONISTA_COLUMNS)[0]
        return (
            "Coluna %s ausente na tabela plantonista_escalas. Execute as migrações do banco para habilitar o módulo." % column_name,
            "O módulo de plantonistas ainda não está disponível porque a coluna %s da tabela plantonista_escalas não existe. Execute as migrações do banco para adicioná-la." % column_name,
        )

    if (
        "does not exist" in normalized
        or "undefinedtable" in normalized
        or "no such table" in normalized
    ):
        return (
            "Tabela plantonista_escalas ausente. Execute as migrações do banco para habilitar o módulo.",
            "O módulo de plantonistas ainda não está disponível porque a tabela plantonista_escalas não existe. Execute as migrações do banco para criá-la.",
        )

    return None


def _plantonista_schema_issue() -> Optional[tuple[str, str]]:
    """Return cached schema issues for the ``plantonista_escalas`` table, if any."""

    if not has_request_context():
        return None
    cached = getattr(g, '_plantonista_schema_issue', None)
    if cached is not None:
        return cached

    issue: Optional[tuple[str, str]] = None
    try:
        inspector = inspect(db.engine)
        columns = {column["name"] for column in inspector.get_columns('plantonista_escalas')}
    except NoSuchTableError:
        issue = (
            "Tabela plantonista_escalas ausente. Execute as migrações do banco para habilitar o módulo.",
            "O módulo de plantonistas ainda não está disponível porque a tabela plantonista_escalas não existe. Execute as migrações do banco para criá-la.",
        )
    except (ProgrammingError, OperationalError) as exc:
        described = _describe_plantonista_schema_error(exc)
        if described:
            issue = described
        else:
            current_app.logger.warning(
                "Falha ao inspecionar a tabela plantonista_escalas: %s", exc, exc_info=exc
            )
            issue = (
                "Não foi possível verificar o esquema da tabela plantonista_escalas.",
                "Não foi possível verificar se o módulo de plantonistas está habilitado. Verifique as migrações do banco.",
            )
    else:
        missing_columns = REQUIRED_PLANTONISTA_COLUMNS - columns
        if missing_columns:
            missing_label = ', '.join(sorted(missing_columns))
            issue = (
                "Colunas ausentes na tabela plantonista_escalas (%s). Execute as migrações do banco para habilitar o módulo." % missing_label,
                "O módulo de plantonistas ainda não está disponível porque as colunas %s da tabela plantonista_escalas não existem. Execute as migrações do banco para adicioná-las." % missing_label,
            )

    g._plantonista_schema_issue = issue
    return issue


def _pj_payments_schema_issue() -> Optional[tuple[str, str]]:
    """Return cached schema issues for the ``pj_payments`` table, if any."""

    if not has_request_context():
        return None
    cached = getattr(g, '_pj_payments_schema_issue', None)
    if cached is not None:
        return cached

    issue: Optional[tuple[str, str]] = None
    try:
        inspector = inspect(db.engine)
        columns = {column["name"] for column in inspector.get_columns('pj_payments')}
    except NoSuchTableError:
        issue = (
            "Tabela pj_payments ausente. Execute as migrações do banco para habilitar o módulo.",
            "O módulo de pagamentos PJ ainda não está disponível porque a tabela pj_payments não existe. Execute as migrações do banco para criá-la.",
        )
    except (ProgrammingError, OperationalError) as exc:
        described = _describe_pj_payments_schema_error(exc)
        if described:
            issue = described
        else:
            current_app.logger.warning(
                "Falha ao inspecionar a tabela pj_payments: %s", exc, exc_info=exc
            )
            issue = (
                "Não foi possível verificar o esquema da tabela pj_payments.",
                "Não foi possível verificar se o módulo de pagamentos PJ está habilitado. Verifique as migrações do banco.",
            )
    else:
        missing_columns = REQUIRED_PJ_PAYMENT_COLUMNS - columns
        if missing_columns:
            missing_column = sorted(missing_columns)[0]
            issue = (
                "Coluna %s ausente na tabela pj_payments. Execute as migrações do banco para habilitar o módulo." % missing_column,
                "O módulo de pagamentos PJ ainda não está disponível porque a coluna %s da tabela pj_payments não existe. Execute as migrações do banco para adicioná-la." % missing_column,
            )

    g._pj_payments_schema_issue = issue
    if issue:
        current_app.logger.warning(issue[0])
    return issue




def _populate_plantonista_form_choices(form, clinics):
    form.clinic_id.choices = [
        (clinic.id, clinic.nome or f'Clínica #{clinic.id}') for clinic in clinics
    ]
    medico_choices = [(0, 'Sem vínculo direto')]
    medicos = (
        Veterinario.query.join(User)
        .order_by(User.name.asc())
        .all()
    )
    for medico in medicos:
        label = medico.user.name if medico.user else f'Veterinário #{medico.id}'
        medico_choices.append((medico.id, label))
    form.medico_id.choices = medico_choices


def _serialize_plantao_modelo(modelo: PlantaoModelo) -> dict:
    hora_inicio = None
    if modelo.hora_inicio:
        hora_inicio = modelo.hora_inicio.strftime('%H:%M')
    return {
        'id': modelo.id,
        'clinic_id': modelo.clinic_id,
        'nome': modelo.nome,
        'duracao_horas': float(modelo.duracao_horas or 0),
        'hora_inicio': hora_inicio,
        'medico_id': modelo.medico_id,
        'medico_nome': modelo.medico_nome,
        'medico_cnpj': modelo.medico_cnpj,
        'owner_tipo': 'medico' if modelo.medico_id else 'clinica',
    }


def _configure_modelo_choices(form, modelos: list[PlantaoModelo], clinic_id: int | None):
    form.plantao_modelo_id.choices = [(0, 'Sem modelo salvo')]
    for modelo in modelos:
        clinic_label = getattr(getattr(modelo, 'clinic', None), 'nome', '') or ''
        label_suffix = f" ({clinic_label})" if clinic_label else ''
        label = f"{modelo.nome} — {modelo.duracao_horas}h{label_suffix}"
        form.plantao_modelo_id.choices.append((modelo.id, label))


def _build_modelo_from_form(form):
    if not form.salvar_modelo.data:
        return None

    if not form.hora_inicio.data or not form.hora_fim.data:
        flash('Defina hora de início e término para salvar como modelo.', 'warning')
        return None

    start = datetime.combine(date.today(), form.hora_inicio.data)
    end = datetime.combine(date.today(), form.hora_fim.data)
    if end <= start:
        end += timedelta(days=1)
    duracao = _compute_plantao_horas(start, end)
    if not duracao:
        flash('Não foi possível calcular a duração do modelo de plantão.', 'warning')
        return None

    nome_modelo = (form.modelo_nome.data or form.turno.data or '').strip()
    if not nome_modelo:
        flash('Informe um nome para o modelo de plantão.', 'warning')
        return None

    medico_id = form.medico_id.data or None
    if medico_id == 0:
        medico_id = None

    medico_nome = (form.medico_nome.data or '').strip() or None
    medico_cnpj = (form.medico_cnpj.data or '').strip() or None

    return PlantaoModelo(
        clinic_id=form.clinic_id.data,
        nome=nome_modelo,
        hora_inicio=form.hora_inicio.data,
        duracao_horas=duracao,
        medico_id=medico_id,
        medico_nome=medico_nome,
        medico_cnpj=medico_cnpj,
    )


def _load_plantao_modelos(clinic_ids: Iterable[int]):
    if not clinic_ids:
        return []
    if not _ensure_plantao_modelos_table():
        return []
    return (
        PlantaoModelo.query.options(
            selectinload(PlantaoModelo.medico).joinedload(Veterinario.user),
            selectinload(PlantaoModelo.clinic),
        )
        .filter(PlantaoModelo.clinic_id.in_(clinic_ids))
        .order_by(PlantaoModelo.nome.asc())
        .all()
    )


def _apply_modelo_to_form(form, modelo: PlantaoModelo):
    if not form or not modelo:
        return

    form.plantao_modelo_id.data = modelo.id
    form.turno.data = modelo.nome

    if modelo.hora_inicio:
        form.hora_inicio.data = modelo.hora_inicio
        try:
            start_dt = datetime.combine(date.today(), modelo.hora_inicio)
            end_dt = start_dt + timedelta(hours=float(modelo.duracao_horas or 0))
            form.hora_fim.data = end_dt.time()
        except Exception:
            pass

    if modelo.medico_id:
        form.medico_id.data = modelo.medico_id
    if modelo.medico_nome:
        form.medico_nome.data = modelo.medico_nome
    if modelo.medico_cnpj:
        form.medico_cnpj.data = modelo.medico_cnpj


def _format_plantao_option(escala):
    if not escala:
        return 'Plantão'
    medico = (escala.medico_nome or 'Plantonista').strip()
    turno = (escala.turno or '').strip()
    inicio = escala.inicio.strftime('%d/%m %H:%M') if escala.inicio else 'Sem início'
    fim = escala.fim.strftime('%d/%m %H:%M') if escala.fim else 'Sem fim'
    clinic_label = getattr(getattr(escala, 'clinic', None), 'nome', None)
    parts = [medico]
    if turno:
        parts.append(turno)
    parts.append(f'{inicio} → {fim}')
    if clinic_label:
        parts.append(clinic_label)
    return ' • '.join(parts)


def _compute_plantao_horas(inicio, fim):
    if not inicio or not fim:
        return None
    total_seconds = (fim - inicio).total_seconds()
    if total_seconds <= 0:
        return None
    try:
        horas = Decimal(str(total_seconds)) / Decimal('3600')
        return horas.quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError):
        return None


def _configure_pj_payment_form(form, clinics, accessible_ids):
    form.clinic_id.choices = [
        (clinic.id, clinic.nome or f'Clínica #{clinic.id}') for clinic in clinics
    ]

    allowed_ids = sorted({cid for cid in accessible_ids if cid})

    if not allowed_ids:
        form.plantao_vinculado.query_factory = lambda: PlantonistaEscala.query.filter(false())
    else:
        def _plantao_query():
            return (
                PlantonistaEscala.query.options(selectinload(PlantonistaEscala.clinic))
                .filter(PlantonistaEscala.clinic_id.in_(allowed_ids))
                .order_by(PlantonistaEscala.inicio.desc())
            )

        form.plantao_vinculado.query_factory = _plantao_query

    form.plantao_vinculado.get_label = _format_plantao_option


def _get_primary_payment_plantao(payment):
    if not payment:
        return None
    for escala in getattr(payment, 'plantao_escalas', []) or []:
        if escala:
            return escala
    return None


def _apply_plantao_details_from_form(escala, form):
    if not escala or not form:
        return
    if form.plantao_inicio.data:
        escala.inicio = form.plantao_inicio.data
    if form.plantao_fim.data:
        escala.fim = form.plantao_fim.data
    escala.plantao_horas = _compute_plantao_horas(escala.inicio, escala.fim)
    horas = form.horas_previstas.data
    valor_hora = form.valor_por_hora.data
    if horas is not None and valor_hora is not None:
        try:
            escala.valor_previsto = (Decimal(valor_hora) * Decimal(horas)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            pass


def _sync_payment_plantao_link(payment, target_scale, form):
    current_scale = _get_primary_payment_plantao(payment)
    if current_scale and current_scale is not target_scale:
        current_scale.pj_payment = None

    if target_scale:
        target_scale.pj_payment = payment
        _apply_plantao_details_from_form(target_scale, form)
        if payment:
            payment.tipo_prestador = 'plantonista'
            if target_scale.plantao_horas is not None:
                payment.plantao_horas = target_scale.plantao_horas
        return target_scale

    if current_scale and current_scale is target_scale:
        _apply_plantao_details_from_form(current_scale, form)
        if payment and current_scale.plantao_horas is not None:
            payment.plantao_horas = current_scale.plantao_horas
        return current_scale

    return None


def _prefill_plantao_fields_on_form(form, escala):
    if not form or not escala:
        return
    form.plantao_vinculado.data = escala
    if escala.inicio:
        form.plantao_inicio.data = escala.inicio
    if escala.fim:
        form.plantao_fim.data = escala.fim
    horas = escala.horas_previstas
    if horas and horas > 0:
        form.horas_previstas.data = horas
        if escala.valor_previsto:
            try:
                form.valor_por_hora.data = (Decimal(escala.valor_previsto) / horas).quantize(Decimal('0.01'))
            except (InvalidOperation, TypeError):
                pass























def _nfse_required_fields_by_municipio() -> dict[str, list[str]]:
    return {
        "orlandia": [
            "inscricao_municipal",
            "regime_tributario",
            "cnae",
            "codigo_servico",
            "aliquota_iss",
            "nfse_username",
            "nfse_password",
        ],
        "belo_horizonte": [
            "inscricao_municipal",
            "regime_tributario",
            "cnae",
            "codigo_servico",
            "aliquota_iss",
        ],
        "contagem": [
            "regime_tributario",
            "cnae",
            "codigo_servico",
        ],
    }


def _nfse_field_labels() -> dict[str, str]:
    return {
        "inscricao_municipal": "Inscrição municipal",
        "regime_tributario": "Regime tributário",
        "cnae": "CNAE",
        "codigo_servico": "Código de serviço",
        "aliquota_iss": "Alíquota ISS",
        "nfse_username": "Usuário NFS-e",
        "nfse_password": "Senha NFS-e",
        "nfse_cert_path": "Certificado NFS-e",
        "nfse_cert_password": "Senha do certificado",
    }


def _nfse_missing_fields(clinic: Clinica) -> tuple[list[str], str]:
    municipio_key = (get_clinica_field(clinic, "municipio_nfse", "") or "").strip().lower()
    required_fields = _nfse_required_fields_by_municipio().get(municipio_key, [])
    labels = _nfse_field_labels()
    missing_fields = []
    for field in required_fields:
        current_value = get_clinica_field(clinic, field, "")
        if current_value in (None, "", []):
            missing_fields.append(labels.get(field, field))
    return missing_fields, municipio_key


def _nfse_certificate_status(clinic: Clinica, municipio_key: str) -> tuple[bool, str]:
    required_fields = _nfse_required_fields_by_municipio().get(municipio_key, [])
    certificate_required = (
        municipio_key in NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY
        or "nfse_cert_path" in required_fields
        or "nfse_cert_password" in required_fields
    )
    if not certificate_required:
        return True, "Não exigido para este município."

    certificate = (
        FiscalCertificate.query.join(FiscalEmitter, FiscalCertificate.emitter_id == FiscalEmitter.id)
        .filter(FiscalEmitter.clinic_id == clinic.id)
        .order_by(FiscalCertificate.created_at.desc())
        .first()
    )
    if certificate and certificate.valid_to:
        is_valid = certificate.valid_to >= datetime.now(timezone.utc)
        if is_valid:
            return True, f"Válido até {certificate.valid_to.strftime('%d/%m/%Y')}."
        return False, f"Vencido em {certificate.valid_to.strftime('%d/%m/%Y')}."
    if clinic.nfse_cert_path and clinic.nfse_cert_password:
        return True, "Certificado configurado."
    return False, "Certificado não informado."


def _nfse_betha_status(clinic: Clinica, municipio_key: str) -> tuple[bool, str]:
    if municipio_key in NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY:
        return True, "Municipio integrado pela API da NFS-e Nacional com DPS assinada por certificado A1."
    if municipio_key != "orlandia":
        return True, "Não se aplica ao município."
    if get_clinica_field(clinic, "fiscal_ready", False):
        return True, "Teste de comunicação concluído."
    return False, "Teste de comunicação pendente."


def _build_orcamento_nfse_snapshot(
    orcamento: Orcamento,
    clinic: Clinica,
    issue: NfseIssue | None = None,
    pdf_available: bool = False,
) -> dict:
    consulta = orcamento.consulta
    particular_items = [
        item for item in (orcamento.items or [])
        if getattr(item, "effective_payer_type", "particular") == "particular"
    ]
    particular_total = sum((item.valor or Decimal("0.00") for item in particular_items), Decimal("0.00"))
    config_url = url_for("contabilidade_nfse", clinica_id=orcamento.clinica_id, orcamento_id=orcamento.id)
    preview_url = url_for("contabilidade_nfse_preview", orcamento_id=orcamento.id)
    wizard_url = url_for("fiscal_onboarding_step", step=1)
    issue_list_url = url_for("contabilidade_nfse", clinica_id=orcamento.clinica_id, orcamento_id=orcamento.id)
    key_configured = bool((os.getenv("FISCAL_MASTER_KEY") or "").strip())

    base_snapshot = {
        "applicable": False,
        "kind": "unavailable",
        "label": "Não disponível",
        "detail": "A NFS-e fica disponível para orçamentos ligados a uma consulta.",
        "badge": "secondary",
        "icon": "fa-file-circle-minus",
        "preview_url": preview_url,
        "config_url": config_url,
        "wizard_url": wizard_url,
        "issue_list_url": issue_list_url,
        "download_pdf_url": None,
        "issue_id": getattr(issue, "id", None),
        "numero_nfse": getattr(issue, "numero_nfse", None),
        "particular_total": particular_total,
        "has_particular_items": bool(particular_items),
        "can_emit": False,
    }

    if not consulta:
        return base_snapshot

    if not particular_items:
        base_snapshot.update(
            {
                "kind": "not_applicable",
                "label": "Sem itens particulares",
                "detail": "A nota fiscal só é necessária quando há cobrança particular neste orçamento.",
                "icon": "fa-circle-info",
            }
        )
        return base_snapshot

    missing_fields, municipio_key = _nfse_missing_fields(clinic)
    certificate_ok, certificate_msg = _nfse_certificate_status(clinic, municipio_key)
    betha_ok, betha_msg = _nfse_betha_status(clinic, municipio_key)
    blocking_messages = []
    if not key_configured:
        blocking_messages.append("Configure a chave fiscal do ambiente.")
    if missing_fields:
        blocking_messages.append("Preencha o cadastro fiscal obrigatório.")
    if not certificate_ok:
        blocking_messages.append(certificate_msg)
    if not betha_ok:
        blocking_messages.append(betha_msg)

    base_snapshot["applicable"] = True
    base_snapshot["can_emit"] = key_configured and not missing_fields and certificate_ok and betha_ok

    issue_status_labels = {
        "fila": ("Na fila", "warning", "fa-clock"),
        "processando": ("Processando", "info", "fa-arrows-rotate"),
        "pendente": ("Pendente", "warning", "fa-hourglass-half"),
        "autorizado": ("Emitida", "success", "fa-file-circle-check"),
        "erro": ("Com erro", "danger", "fa-triangle-exclamation"),
        "cancelada": ("Cancelada", "dark", "fa-ban"),
        "cancelamento_solicitado": ("Cancelamento solicitado", "secondary", "fa-rotate-left"),
        "substituicao_solicitada": ("Substituição solicitada", "secondary", "fa-file-pen"),
    }

    if issue:
        raw_status = (issue.status or "").strip().lower()
        label, badge, icon = issue_status_labels.get(
            raw_status,
            ((raw_status or "Em acompanhamento").replace("_", " ").title(), "secondary", "fa-file-lines"),
        )
        detail = label
        kind = "processing"
        if raw_status == "autorizado":
            kind = "emitted"
            detail = (
                f"NFS-e {issue.numero_nfse} autorizada."
                if issue.numero_nfse
                else "NFS-e autorizada e pronta para consulta."
            )
        elif raw_status in {"erro", "cancelada"}:
            kind = "issue"
            detail = issue.erro_mensagem or detail
        elif raw_status in {"cancelamento_solicitado", "substituicao_solicitada"}:
            kind = "processing"
            detail = "A nota está em tratamento fiscal."
        elif raw_status in {"fila", "processando", "pendente"}:
            detail = "A emissão foi iniciada e segue em acompanhamento."

        base_snapshot.update(
            {
                "kind": kind,
                "label": label,
                "detail": detail,
                "badge": badge,
                "icon": icon,
                "issue_id": issue.id,
                "numero_nfse": issue.numero_nfse,
                "download_pdf_url": (
                    url_for("contabilidade_nfse_download", issue_id=issue.id, kind="pdf")
                    if pdf_available
                    else None
                ),
            }
        )
        return base_snapshot

    if not key_configured:
        base_snapshot.update(
            {
                "kind": "config",
                "label": "Chave fiscal pendente",
                "detail": "O ambiente ainda não está pronto para armazenar credenciais fiscais.",
                "badge": "danger",
                "icon": "fa-key",
            }
        )
        return base_snapshot

    if missing_fields or not certificate_ok or not betha_ok:
        detail = blocking_messages[0] if blocking_messages else "Revise a configuração fiscal."
        base_snapshot.update(
            {
                "kind": "config",
                "label": "Configuração pendente",
                "detail": detail,
                "badge": "warning",
                "icon": "fa-gear",
            }
        )
        return base_snapshot

    base_snapshot.update(
        {
            "kind": "ready",
            "label": "Pronta para emitir",
            "detail": "Cadastro, certificado e comunicação fiscal estão em dia.",
            "badge": "success",
            "icon": "fa-file-circle-check",
            "can_emit": True,
        }
    )
    return base_snapshot










def _build_nfse_orcamento_payload(orcamento: Orcamento) -> dict:
    consulta = orcamento.consulta
    animal = consulta.animal if consulta else None
    tomador = animal.owner if animal else None
    items = [
        {
            "id": item.id,
            "descricao": item.descricao,
            "valor": float(item.valor or 0),
            "payer_type": item.effective_payer_type,
            "servico_id": item.servico_id,
            "procedure_code": item.procedure_code,
        }
        for item in orcamento.items
    ]

    particular_items = [
        i for i in items if i["payer_type"] == "particular"
    ]
    particular_total = sum(i["valor"] for i in particular_items)

    desc_lines = [i["descricao"] for i in particular_items if i["descricao"]]
    discriminacao = "; ".join(desc_lines) if desc_lines else (orcamento.descricao or "")

    endereco_payload = (
        {
            "cep": tomador.endereco.cep,
            "logradouro": tomador.endereco.rua,
            "numero": tomador.endereco.numero,
            "complemento": tomador.endereco.complemento,
            "bairro": tomador.endereco.bairro,
            "cidade": tomador.endereco.cidade,
            "estado": tomador.endereco.estado,
        }
        if tomador and tomador.endereco
        else None
    )

    return {
        "id": orcamento.id,
        "consulta_id": orcamento.consulta_id,
        "descricao": orcamento.descricao,
        "valor_total": float(orcamento.total or 0),
        "valor_particular": particular_total,
        "discriminacao": discriminacao,
        "itens": items,
        "paciente": (
            {
                "id": animal.id,
                "nome": animal.name,
                "especie": animal.species,
                "raca": animal.breed,
            }
            if animal
            else None
        ),
        "tomador": (
            {
                "id": tomador.id,
                "nome": tomador.name,
                "cpf_cnpj": tomador.cpf,
                "email": tomador.email,
                "telefone": tomador.phone,
                "endereco": endereco_payload,
                "endereco_texto": tomador.address,
            }
            if tomador
            else None
        ),
    }


def _build_nfse_emissor_payload(clinica: Clinica) -> dict:
    def _to_float(value):
        return float(value) if value is not None else None

    return {
        "id": clinica.id,
        "nome": clinica.nome,
        "cnpj": clinica.cnpj,
        "email": clinica.email,
        "telefone": clinica.telefone,
        "endereco": clinica.endereco,
        "inscricao_municipal": get_clinica_field(clinica, "inscricao_municipal", None),
        "inscricao_estadual": get_clinica_field(clinica, "inscricao_estadual", None),
        "regime_tributario": get_clinica_field(clinica, "regime_tributario", None),
        "cnae": get_clinica_field(clinica, "cnae", None),
        "codigo_servico": get_clinica_field(clinica, "codigo_servico", None),
        "aliquota_iss": _to_float(get_clinica_field(clinica, "aliquota_iss", None)),
        "aliquota_pis": _to_float(get_clinica_field(clinica, "aliquota_pis", None)),
        "aliquota_cofins": _to_float(get_clinica_field(clinica, "aliquota_cofins", None)),
        "aliquota_csll": _to_float(get_clinica_field(clinica, "aliquota_csll", None)),
        "aliquota_ir": _to_float(get_clinica_field(clinica, "aliquota_ir", None)),
        "municipio_nfse": get_clinica_field(clinica, "municipio_nfse", None),
        "fiscal_ready": clinica.fiscal_ready_status,
    }




















def _geocode_endereco(endereco: Endereco | None):
    """Atualiza latitude/longitude do endereço com base nos campos atuais."""

    if not endereco:
        return None

    coords = geocode_address(
        cep=endereco.cep,
        rua=endereco.rua,
        numero=endereco.numero,
        bairro=endereco.bairro,
        cidade=endereco.cidade,
        estado=endereco.estado,
    )

    if coords:
        endereco.latitude, endereco.longitude = coords
    else:
        endereco.latitude = None
        endereco.longitude = None

    return coords


def _update_coordinates_from_request(endereco: Endereco | None):
    """Aplica latitude/longitude enviados pelo formulário, se válidos."""

    if not endereco:
        return False

    payload = request.get_json(silent=True) or {}

    raw_lat = (request.form.get('latitude') or payload.get('latitude') or '').strip()
    raw_lon = (request.form.get('longitude') or payload.get('longitude') or '').strip()

    if not raw_lat and not raw_lon:
        return False

    try:
        endereco.latitude = float(str(raw_lat).replace(',', '.'))
        endereco.longitude = float(str(raw_lon).replace(',', '.'))
        return True
    except ValueError:
        endereco.latitude = None
        endereco.longitude = None
        return False






def _normalizar_unidade_idade(unidade):
    if not unidade:
        return 'anos'
    texto = unicodedata.normalize('NFKD', str(unidade))
    texto = texto.encode('ASCII', 'ignore').decode('ASCII').strip().lower()
    if texto.startswith('mes'):
        return 'meses'
    if texto.startswith('ano'):
        return 'anos'
    return 'anos'


def _formatar_idade(numero, unidade):
    if numero is None:
        return ''
    unidade_norm = _normalizar_unidade_idade(unidade)
    if unidade_norm == 'meses':
        sufixo = 'mês' if numero == 1 else 'meses'
    else:
        sufixo = 'ano' if numero == 1 else 'anos'
    return f"{numero} {sufixo}"


def _extrair_idade(unidade_texto):
    if not unidade_texto:
        return None, None
    partes = str(unidade_texto).split()
    numero = None
    try:
        numero = int(partes[0])
    except (ValueError, IndexError):
        numero = None
    unidade = None
    if len(partes) > 1:
        unidade = _normalizar_unidade_idade(partes[1])
    return numero, unidade


def _preencher_idade_form(form, animal=None):
    if not hasattr(form, 'age') or not hasattr(form, 'age_unit'):
        return
    if form.is_submitted():
        return

    numero = None
    unidade = None

    if animal and animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            numero = delta.years
            unidade = 'anos'
        else:
            numero = delta.months
            unidade = 'meses'
    elif animal and animal.age:
        numero, unidade = _extrair_idade(animal.age)
    elif form.age.data:
        numero, unidade = _extrair_idade(form.age.data)

    if numero is not None:
        form.age.data = str(numero)
    if unidade:
        form.age_unit.data = unidade
    elif not form.age_unit.data:
        form.age_unit.data = 'anos'




def _sanitize_login_next_url(next_url):
    next_url = next_url or url_for('index')
    parsed_next = urlparse(next_url)
    if parsed_next.netloc or (parsed_next.scheme and parsed_next.scheme not in ('http', 'https')):
        return url_for('index')
    if re.fullmatch(r'/vacina-pmo/c/[^/]+/pet/\d+/?', parsed_next.path or ''):
        return url_for('index')
    return next_url




# Helpers OAuth migraram para services/oauth_provider.py
from services.oauth_provider import (  # noqa: E402,F401
    _oauth_access_token_can_self_heal_mcp_scope,
    _oauth_access_token_requires_mcp_reauthorization,
    _oauth_allowed_scopes,
    _oauth_default_mcp_scope,
    _oauth_extract_bearer_token,
    _oauth_get_signing_keys,
    _oauth_issuer,
    _oauth_log_event,
    _oauth_order_scopes,
    _oauth_revoke_refresh_family,
    _oauth_rotate_signing_key,
    _oauth_scope_needs_mcp_recovery,
    _oauth_scope_tokens,
)


def _integration_error(code: str, message: str, status_code: int, **details):
    payload = {
        'error': {
            'code': code,
            'message': message,
        }
    }
    if details:
        payload['error']['details'] = details
    return jsonify(payload), status_code


def _integration_ok(data, status_code: int = 200):
    return jsonify({'data': data}), status_code


def _integration_user_clinic_id(user: User) -> int | None:
    if has_veterinarian_profile(user):
        veterinario = getattr(user, 'veterinario', None)
        membership = ensure_veterinarian_membership(veterinario)
        clinic_id = getattr(veterinario, 'clinica_id', None) or getattr(user, 'clinica_id', None)
        if clinic_id:
            return clinic_id
        return getattr(getattr(membership, 'veterinario', None), 'clinica_id', None) if membership else None
    return getattr(user, 'clinica_id', None)


def _integration_empty_query(model):
    return model.query.filter(model.id.is_(None))


def _integration_accessible_animals_query(user: User, clinic_id: int | None = None):
    query = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
            joinedload(Animal.clinica),
        )
        .filter(Animal.removido_em.is_(None))
    )

    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        if clinic_id:
            query = query.filter(Animal.clinica_id == clinic_id)
        return query

    if has_professional_access(user):
        professional_clinic_id = _integration_user_clinic_id(user)
        if not professional_clinic_id:
            return _integration_empty_query(Animal)
        return query.filter(Animal.clinica_id == professional_clinic_id)

    return query.filter(Animal.user_id == user.id)


def _integration_accessible_appointments_query(user: User, clinic_id: int | None = None):
    query = (
        Appointment.query
        .options(
            joinedload(Appointment.animal).joinedload(Animal.owner),
            joinedload(Appointment.veterinario).joinedload(Veterinario.user),
            joinedload(Appointment.clinica),
            joinedload(Appointment.consulta),
        )
    )

    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        if clinic_id:
            query = query.filter(Appointment.clinica_id == clinic_id)
        return query

    if has_veterinarian_profile(user):
        veterinario = getattr(user, 'veterinario', None)
        if not veterinario:
            return _integration_empty_query(Appointment)
        return query.filter(Appointment.veterinario_id == veterinario.id)

    if getattr(user, 'worker', None) == 'colaborador':
        professional_clinic_id = _integration_user_clinic_id(user)
        if not professional_clinic_id:
            return _integration_empty_query(Appointment)
        return query.filter(Appointment.clinica_id == professional_clinic_id)

    return query.filter(Appointment.tutor_id == user.id)


def _integration_accessible_exam_appointments_query(user: User, clinic_id: int | None = None):
    query = (
        ExamAppointment.query
        .join(Animal, ExamAppointment.animal_id == Animal.id)
        .options(
            joinedload(ExamAppointment.animal).joinedload(Animal.owner),
            joinedload(ExamAppointment.specialist).joinedload(Veterinario.user),
        )
        .filter(Animal.removido_em.is_(None))
    )

    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        if clinic_id:
            query = query.filter(Animal.clinica_id == clinic_id)
        return query

    if has_professional_access(user):
        professional_clinic_id = _integration_user_clinic_id(user)
        if not professional_clinic_id:
            return _integration_empty_query(ExamAppointment)
        return query.filter(Animal.clinica_id == professional_clinic_id)

    return query.filter(Animal.user_id == user.id)


def _integration_accessible_consultas_query(user: User, clinic_id: int | None = None):
    query = (
        Consulta.query
        .join(Animal, Consulta.animal_id == Animal.id)
        .options(
            joinedload(Consulta.animal).joinedload(Animal.owner),
            joinedload(Consulta.clinica),
            joinedload(Consulta.veterinario),
        )
        .filter(Animal.removido_em.is_(None))
    )

    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        if clinic_id:
            query = query.filter(Consulta.clinica_id == clinic_id)
        return query

    if has_professional_access(user):
        professional_clinic_id = _integration_user_clinic_id(user)
        if not professional_clinic_id:
            return _integration_empty_query(Consulta)
        return query.filter(Consulta.clinica_id == professional_clinic_id)

    return query.filter(Animal.user_id == user.id)


def _integration_accessible_prescription_blocks_query(user: User, clinic_id: int | None = None):
    query = (
        BlocoPrescricao.query
        .join(Animal, BlocoPrescricao.animal_id == Animal.id)
        .options(
            joinedload(BlocoPrescricao.animal).joinedload(Animal.owner),
            joinedload(BlocoPrescricao.prescricoes),
            joinedload(BlocoPrescricao.clinica),
        )
        .filter(Animal.removido_em.is_(None))
    )

    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        if clinic_id:
            query = query.filter(BlocoPrescricao.clinica_id == clinic_id)
        return query

    if has_professional_access(user):
        professional_clinic_id = _integration_user_clinic_id(user)
        if not professional_clinic_id:
            return _integration_empty_query(BlocoPrescricao)
        return query.filter(BlocoPrescricao.clinica_id == professional_clinic_id)

    return query.filter(Animal.user_id == user.id)


def _integration_accessible_exam_requests_query(user: User, clinic_id: int | None = None):
    query = (
        ExameSolicitado.query
        .join(BlocoExames, ExameSolicitado.bloco_id == BlocoExames.id)
        .join(Animal, BlocoExames.animal_id == Animal.id)
        .options(
            joinedload(ExameSolicitado.bloco).joinedload(BlocoExames.animal).joinedload(Animal.owner),
        )
        .filter(Animal.removido_em.is_(None))
    )

    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        if clinic_id:
            query = query.filter(Animal.clinica_id == clinic_id)
        return query

    if has_professional_access(user):
        professional_clinic_id = _integration_user_clinic_id(user)
        if not professional_clinic_id:
            return _integration_empty_query(ExameSolicitado)
        return query.filter(Animal.clinica_id == professional_clinic_id)

    return query.filter(Animal.user_id == user.id)


def _integration_accessible_vaccines_query(user: User, clinic_id: int | None = None):
    query = (
        Vacina.query
        .join(Animal, Vacina.animal_id == Animal.id)
        .options(
            joinedload(Vacina.animal).joinedload(Animal.owner),
        )
        .filter(Animal.removido_em.is_(None))
    )

    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        if clinic_id:
            query = query.filter(Animal.clinica_id == clinic_id)
        return query

    if has_professional_access(user):
        professional_clinic_id = _integration_user_clinic_id(user)
        if not professional_clinic_id:
            return _integration_empty_query(Vacina)
        return query.filter(Animal.clinica_id == professional_clinic_id)

    return query.filter(Animal.user_id == user.id)


def _integration_find_accessible_animal(
    user: User,
    *,
    animal_id: int | None = None,
    animal_name: str | None = None,
    clinic_id: int | None = None,
):
    query = _integration_accessible_animals_query(user, clinic_id=clinic_id)
    if animal_id is not None:
        return query.filter(Animal.id == animal_id).first()

    normalized_name = (animal_name or '').strip().lower()
    if normalized_name:
        return (
            query
            .filter(func.lower(Animal.name) == normalized_name)
            .order_by(Animal.date_added.desc(), Animal.id.desc())
            .first()
        )

    return None


def _integration_format_datetime(value):
    if not value:
        return None
    localized = value
    if getattr(value, 'tzinfo', None) is None:
        localized = value.replace(tzinfo=timezone.utc)
    return localized.astimezone(BR_TZ).isoformat()


def _integration_collect_animal_pendencies(animal: Animal):
    now = utcnow()
    today = datetime.now(BR_TZ).date()

    overdue_vaccines = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
        .filter(Vacina.aplicada_em.isnot(None))
        .filter(Vacina.aplicada_em < today)
        .order_by(Vacina.aplicada_em.asc())
        .all()
    )
    upcoming_vaccines = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
        .filter(Vacina.aplicada_em.isnot(None))
        .filter(Vacina.aplicada_em >= today)
        .order_by(Vacina.aplicada_em.asc())
        .all()
    )
    upcoming_returns = (
        Appointment.query.filter_by(animal_id=animal.id)
        .filter(Appointment.consulta_id.isnot(None))
        .filter(Appointment.status.in_(['scheduled', 'accepted']))
        .filter(Appointment.scheduled_at >= now)
        .order_by(Appointment.scheduled_at.asc())
        .all()
    )
    pending_exam_appointments = (
        ExamAppointment.query.filter_by(animal_id=animal.id)
        .filter(ExamAppointment.status.in_(['pending', 'confirmed']))
        .order_by(ExamAppointment.scheduled_at.asc())
        .all()
    )
    pending_exam_requests = (
        ExameSolicitado.query
        .join(BlocoExames, ExameSolicitado.bloco_id == BlocoExames.id)
        .filter(BlocoExames.animal_id == animal.id)
        .filter(
            or_(
                func.lower(func.coalesce(ExameSolicitado.status, '')) == 'pendente',
                and_(
                    ExameSolicitado.resultado.is_(None),
                    func.lower(func.coalesce(ExameSolicitado.status, '')) != 'concluido',
                ),
            )
        )
        .order_by(ExameSolicitado.id.desc())
        .all()
    )

    return {
        'vacinas_atrasadas': overdue_vaccines,
        'proximas_vacinas': upcoming_vaccines,
        'retornos_agendados': upcoming_returns,
        'exames_agendados': pending_exam_appointments,
        'exames_pendentes': pending_exam_requests,
    }


def _integration_prescription_items(block: BlocoPrescricao):
    items = []
    for item in (block.prescricoes or []):
        items.append({
            'medicamento': item.medicamento,
            'dosagem': item.dosagem,
            'frequencia': item.frequencia,
            'duracao': item.duracao,
            'observacoes': item.observacoes,
        })
    return items


def _integration_build_clinical_summary(user: User, animal: Animal):
    latest_consulta = (
        _integration_accessible_consultas_query(user)
        .filter(Consulta.animal_id == animal.id)
        .order_by(Consulta.finalizada_em.desc().nullslast(), Consulta.created_at.desc())
        .first()
    )
    recent_consultas = (
        _integration_accessible_consultas_query(user)
        .filter(Consulta.animal_id == animal.id)
        .order_by(Consulta.finalizada_em.desc().nullslast(), Consulta.created_at.desc())
        .limit(3)
        .all()
    )
    latest_prescription = (
        _integration_accessible_prescription_blocks_query(user)
        .filter(BlocoPrescricao.animal_id == animal.id)
        .order_by(BlocoPrescricao.data_criacao.desc())
        .first()
    )
    recent_exam_requests = (
        _integration_accessible_exam_requests_query(user)
        .filter(BlocoExames.animal_id == animal.id)
        .order_by(ExameSolicitado.id.desc())
        .limit(5)
        .all()
    )
    pendencias = _integration_collect_animal_pendencies(animal)

    return {
        'animal': {
            'id': animal.id,
            'nome': animal.name,
            'especie': animal.species.name if animal.species else None,
            'raca': animal.breed.name if animal.breed else None,
            'sexo': animal.sex,
            'idade': animal.age_display,
            'peso_kg': animal.peso,
            'clinica_id': animal.clinica_id,
            'clinica_nome': animal.clinica.nome if animal.clinica else None,
        },
        'tutor': {
            'id': animal.owner.id if getattr(animal, 'owner', None) else None,
            'nome': animal.owner.name if getattr(animal, 'owner', None) else None,
            'email': animal.owner.email if getattr(animal, 'owner', None) else None,
            'telefone': animal.owner.phone if getattr(animal, 'owner', None) else None,
        },
        'ultima_consulta': (
            {
                'id': latest_consulta.id,
                'status': latest_consulta.status,
                'finalizada_em': _integration_format_datetime(
                    latest_consulta.finalizada_em or latest_consulta.created_at
                ),
                'queixa_principal': latest_consulta.queixa_principal,
                'historico_clinico': latest_consulta.historico_clinico,
                'exame_fisico': latest_consulta.exame_fisico,
                'conduta': latest_consulta.conduta,
                'exames_solicitados': latest_consulta.exames_solicitados,
                'retorno_de_id': latest_consulta.retorno_de_id,
            }
            if latest_consulta else None
        ),
        'consultas_recentes': [
            {
                'id': consulta.id,
                'status': consulta.status,
                'finalizada_em': _integration_format_datetime(consulta.finalizada_em or consulta.created_at),
                'queixa_principal': consulta.queixa_principal,
                'conduta': consulta.conduta,
                'exames_solicitados': consulta.exames_solicitados,
            }
            for consulta in recent_consultas
        ],
        'prescricao_mais_recente': (
            {
                'id': latest_prescription.id,
                'emitida_em': _integration_format_datetime(latest_prescription.data_criacao),
                'instrucoes_gerais': latest_prescription.instrucoes_gerais,
                'itens': _integration_prescription_items(latest_prescription),
            }
            if latest_prescription else None
        ),
        'exames_recentes': [
            {
                'id': exam.id,
                'nome': exam.nome,
                'status': exam.status,
                'justificativa': exam.justificativa,
                'resultado': exam.resultado,
            }
            for exam in recent_exam_requests
        ],
        'pendencias': {
            'vacinas_atrasadas': [
                {
                    'id': vaccine.id,
                    'nome': vaccine.nome,
                    'tipo': vaccine.tipo,
                    'data_prevista': vaccine.aplicada_em.isoformat() if vaccine.aplicada_em else None,
                }
                for vaccine in pendencias['vacinas_atrasadas']
            ],
            'proximas_vacinas': [
                {
                    'id': vaccine.id,
                    'nome': vaccine.nome,
                    'tipo': vaccine.tipo,
                    'data_prevista': vaccine.aplicada_em.isoformat() if vaccine.aplicada_em else None,
                }
                for vaccine in pendencias['proximas_vacinas'][:5]
            ],
            'retornos_agendados': [
                {
                    'id': appointment.id,
                    'data': _integration_format_datetime(appointment.scheduled_at),
                    'status': appointment.status,
                    'observacoes': appointment.notes,
                }
                for appointment in pendencias['retornos_agendados'][:5]
            ],
            'exames_agendados': [
                {
                    'id': exam.id,
                    'data': _integration_format_datetime(exam.scheduled_at),
                    'status': exam.status,
                    'especialista': (
                        exam.specialist.user.name
                        if getattr(getattr(exam, 'specialist', None), 'user', None) else None
                    ),
                }
                for exam in pendencias['exames_agendados'][:5]
            ],
            'exames_pendentes': [
                {
                    'id': exam.id,
                    'nome': exam.nome,
                    'status': exam.status,
                    'justificativa': exam.justificativa,
                }
                for exam in pendencias['exames_pendentes'][:5]
            ],
        },
    }


def _integration_build_today_agenda(user: User, target_date: date | None = None):
    target_date = target_date or datetime.now(BR_TZ).date()
    appointments = (
        _integration_accessible_appointments_query(user)
        .order_by(Appointment.scheduled_at.asc())
        .limit(500)
        .all()
    )

    today_items = []
    for appointment in appointments:
        if not appointment.scheduled_at:
            continue
        if appointment.scheduled_at.astimezone(BR_TZ).date() != target_date:
            continue
        animal = appointment.animal
        pendencias = _integration_collect_animal_pendencies(animal) if animal else {}
        today_items.append({
            'appointment_id': appointment.id,
            'data_hora': _integration_format_datetime(appointment.scheduled_at),
            'status': appointment.status,
            'tipo': appointment.kind,
            'animal': {
                'id': animal.id if animal else None,
                'nome': animal.name if animal else None,
                'tutor_nome': animal.owner.name if animal and getattr(animal, 'owner', None) else None,
            },
            'observacoes': appointment.notes,
            'pendencias_clinicas': {
                'vacinas_atrasadas': len(pendencias.get('vacinas_atrasadas', [])),
                'retornos_agendados': len(pendencias.get('retornos_agendados', [])),
                'exames_pendentes': len(pendencias.get('exames_pendentes', [])),
            },
        })

    return {
        'data': target_date.isoformat(),
        'total_agendamentos': len(today_items),
        'agendamentos': today_items,
    }


def _integration_build_clinical_pendencies(user: User, clinic_id: int | None = None):
    now = utcnow()
    today = datetime.now(BR_TZ).date()

    overdue_vaccines = (
        _integration_accessible_vaccines_query(user, clinic_id=clinic_id)
        .filter(Vacina.aplicada.is_(False))
        .filter(Vacina.aplicada_em.isnot(None))
        .filter(Vacina.aplicada_em < today)
        .order_by(Vacina.aplicada_em.asc())
        .limit(100)
        .all()
    )
    upcoming_returns = (
        _integration_accessible_appointments_query(user, clinic_id=clinic_id)
        .filter(Appointment.consulta_id.isnot(None))
        .filter(Appointment.status.in_(['scheduled', 'accepted']))
        .filter(Appointment.scheduled_at >= now)
        .order_by(Appointment.scheduled_at.asc())
        .limit(100)
        .all()
    )
    pending_exam_appointments = (
        _integration_accessible_exam_appointments_query(user, clinic_id=clinic_id)
        .filter(ExamAppointment.status.in_(['pending', 'confirmed']))
        .order_by(ExamAppointment.scheduled_at.asc())
        .limit(100)
        .all()
    )
    pending_exam_requests = (
        _integration_accessible_exam_requests_query(user, clinic_id=clinic_id)
        .filter(
            or_(
                func.lower(func.coalesce(ExameSolicitado.status, '')) == 'pendente',
                and_(
                    ExameSolicitado.resultado.is_(None),
                    func.lower(func.coalesce(ExameSolicitado.status, '')) != 'concluido',
                ),
            )
        )
        .order_by(ExameSolicitado.id.desc())
        .limit(100)
        .all()
    )

    return {
        'resumo': {
            'vacinas_atrasadas': len(overdue_vaccines),
            'retornos_pendentes': len(upcoming_returns),
            'agendamentos_de_exame_pendentes': len(pending_exam_appointments),
            'solicitacoes_de_exame_pendentes': len(pending_exam_requests),
        },
        'vacinas_atrasadas': [
            {
                'id': vaccine.id,
                'animal_id': vaccine.animal_id,
                'animal_nome': vaccine.animal.name if vaccine.animal else None,
                'tutor_nome': vaccine.animal.owner.name if vaccine.animal and getattr(vaccine.animal, 'owner', None) else None,
                'nome': vaccine.nome,
                'tipo': vaccine.tipo,
                'data_prevista': vaccine.aplicada_em.isoformat() if vaccine.aplicada_em else None,
            }
            for vaccine in overdue_vaccines
        ],
        'retornos_pendentes': [
            {
                'id': appointment.id,
                'animal_id': appointment.animal_id,
                'animal_nome': appointment.animal.name if appointment.animal else None,
                'tutor_nome': appointment.animal.owner.name if appointment.animal and getattr(appointment.animal, 'owner', None) else None,
                'data_hora': _integration_format_datetime(appointment.scheduled_at),
                'status': appointment.status,
            }
            for appointment in upcoming_returns
        ],
        'exames_agendados_pendentes': [
            {
                'id': exam.id,
                'animal_id': exam.animal_id,
                'animal_nome': exam.animal.name if exam.animal else None,
                'tutor_nome': exam.animal.owner.name if exam.animal and getattr(exam.animal, 'owner', None) else None,
                'data_hora': _integration_format_datetime(exam.scheduled_at),
                'status': exam.status,
            }
            for exam in pending_exam_appointments
        ],
        'exames_solicitados_pendentes': [
            {
                'id': exam.id,
                'animal_id': exam.bloco.animal_id if exam.bloco else None,
                'animal_nome': exam.bloco.animal.name if exam.bloco and exam.bloco.animal else None,
                'tutor_nome': (
                    exam.bloco.animal.owner.name
                    if exam.bloco and exam.bloco.animal and getattr(exam.bloco.animal, 'owner', None) else None
                ),
                'nome': exam.nome,
                'status': exam.status,
                'justificativa': exam.justificativa,
            }
            for exam in pending_exam_requests
        ],
    }


def _integration_generate_tutor_guidance(user: User, animal: Animal, consulta_id: int | None = None):
    consultas_query = _integration_accessible_consultas_query(user).filter(Consulta.animal_id == animal.id)
    if consulta_id:
        consultas_query = consultas_query.filter(Consulta.id == consulta_id)
    consulta = consultas_query.order_by(Consulta.finalizada_em.desc().nullslast(), Consulta.created_at.desc()).first()
    prescricao = (
        _integration_accessible_prescription_blocks_query(user)
        .filter(BlocoPrescricao.animal_id == animal.id)
        .order_by(BlocoPrescricao.data_criacao.desc())
        .first()
    )
    pendencias = _integration_collect_animal_pendencies(animal)

    medicamentos = []
    if prescricao:
        for item in prescricao.prescricoes or []:
            parts = [item.medicamento]
            if item.dosagem:
                parts.append(f"dosagem {item.dosagem}")
            if item.frequencia:
                parts.append(f"frequência {item.frequencia}")
            if item.duracao:
                parts.append(f"duração {item.duracao}")
            medicamentos.append(', '.join(parts))

    text_parts = [
        f"Olá! Seguem as orientações do atendimento de {animal.name}.",
    ]
    if consulta and consulta.queixa_principal:
        text_parts.append(f"Motivo principal do atendimento: {consulta.queixa_principal}.")
    if consulta and consulta.conduta:
        text_parts.append(f"Conduta registrada: {consulta.conduta}.")
    if medicamentos:
        text_parts.append("Medicamentos/orientações de uso: " + '; '.join(medicamentos) + ".")
    if prescricao and prescricao.instrucoes_gerais:
        text_parts.append(f"Cuidados gerais: {prescricao.instrucoes_gerais}.")
    if consulta and consulta.exames_solicitados:
        text_parts.append(f"Exames solicitados: {consulta.exames_solicitados}.")
    if pendencias['retornos_agendados']:
        next_return = pendencias['retornos_agendados'][0]
        text_parts.append(
            "Retorno agendado para "
            f"{next_return.scheduled_at.astimezone(BR_TZ).strftime('%d/%m/%Y às %H:%M')}."
        )
    if pendencias['proximas_vacinas']:
        next_vaccine = pendencias['proximas_vacinas'][0]
        if next_vaccine.aplicada_em:
            text_parts.append(
                f"Próxima vacina prevista: {next_vaccine.nome} em {next_vaccine.aplicada_em.strftime('%d/%m/%Y')}."
            )
    text_parts.append("Texto gerado a partir do prontuário. Revise antes de enviar ao tutor.")

    return {
        'animal': {
            'id': animal.id,
            'nome': animal.name,
        },
        'consulta_id': consulta.id if consulta else None,
        'prescricao_id': prescricao.id if prescricao else None,
        'medicacoes': medicamentos,
        'orientacoes_gerais': prescricao.instrucoes_gerais if prescricao else None,
        'rascunho': ' '.join(text_parts),
    }


def _integration_build_handoff(user: User, animal: Animal, consulta_id: int | None = None):
    consultas_query = _integration_accessible_consultas_query(user).filter(Consulta.animal_id == animal.id)
    if consulta_id:
        consultas_query = consultas_query.filter(Consulta.id == consulta_id)
    consultas = consultas_query.order_by(Consulta.finalizada_em.desc().nullslast(), Consulta.created_at.desc()).limit(3).all()
    latest_consulta = consultas[0] if consultas else None
    prescricao = (
        _integration_accessible_prescription_blocks_query(user)
        .filter(BlocoPrescricao.animal_id == animal.id)
        .order_by(BlocoPrescricao.data_criacao.desc())
        .first()
    )
    pendencias = _integration_collect_animal_pendencies(animal)

    next_steps = []
    if latest_consulta and latest_consulta.conduta:
        next_steps.append(latest_consulta.conduta)
    if latest_consulta and latest_consulta.exames_solicitados:
        next_steps.append(f"Acompanhar exames solicitados: {latest_consulta.exames_solicitados}")
    if pendencias['retornos_agendados']:
        appointment = pendencias['retornos_agendados'][0]
        next_steps.append(
            "Retorno marcado em "
            f"{appointment.scheduled_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')}"
        )
    if pendencias['vacinas_atrasadas']:
        next_steps.append(
            f"Há {len(pendencias['vacinas_atrasadas'])} vacina(s) atrasada(s) para revisar."
        )

    handoff_lines = [
        f"Handoff clínico do paciente {animal.name}.",
    ]
    if latest_consulta and latest_consulta.queixa_principal:
        handoff_lines.append(f"Queixa principal: {latest_consulta.queixa_principal}.")
    if latest_consulta and latest_consulta.exame_fisico:
        handoff_lines.append(f"Exame físico: {latest_consulta.exame_fisico}.")
    if latest_consulta and latest_consulta.conduta:
        handoff_lines.append(f"Conduta: {latest_consulta.conduta}.")
    if prescricao and prescricao.instrucoes_gerais:
        handoff_lines.append(f"Orientações gerais ativas: {prescricao.instrucoes_gerais}.")
    if next_steps:
        handoff_lines.append("Próximos passos: " + ' | '.join(next_steps) + ".")

    return {
        'animal': {
            'id': animal.id,
            'nome': animal.name,
            'especie': animal.species.name if animal.species else None,
            'tutor_nome': animal.owner.name if getattr(animal, 'owner', None) else None,
        },
        'caso_atual': (
            {
                'consulta_id': latest_consulta.id,
                'queixa_principal': latest_consulta.queixa_principal,
                'historico_clinico': latest_consulta.historico_clinico,
                'exame_fisico': latest_consulta.exame_fisico,
                'conduta': latest_consulta.conduta,
            }
            if latest_consulta else None
        ),
        'ultimos_atendimentos': [
            {
                'id': consulta.id,
                'data': _integration_format_datetime(consulta.finalizada_em or consulta.created_at),
                'queixa_principal': consulta.queixa_principal,
                'conduta': consulta.conduta,
            }
            for consulta in consultas
        ],
        'prescricoes_ativas': (
            {
                'bloco_id': prescricao.id,
                'emitida_em': _integration_format_datetime(prescricao.data_criacao),
                'instrucoes_gerais': prescricao.instrucoes_gerais,
                'itens': _integration_prescription_items(prescricao),
            }
            if prescricao else None
        ),
        'pendencias': {
            'exames_pendentes': [
                {
                    'id': exam.id,
                    'nome': exam.nome,
                    'status': exam.status,
                }
                for exam in pendencias['exames_pendentes']
            ],
            'retornos_agendados': [
                {
                    'id': appointment.id,
                    'data': _integration_format_datetime(appointment.scheduled_at),
                    'status': appointment.status,
                }
                for appointment in pendencias['retornos_agendados']
            ],
            'vacinas_atrasadas': [
                {
                    'id': vaccine.id,
                    'nome': vaccine.nome,
                    'data_prevista': vaccine.aplicada_em.isoformat() if vaccine.aplicada_em else None,
                }
                for vaccine in pendencias['vacinas_atrasadas']
            ],
        },
        'proximos_passos': next_steps,
        'handoff_texto': ' '.join(handoff_lines),
    }


def _integration_normalize_lookup_token(value: str | None) -> str:
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    without_accents = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', '', without_accents.lower())


def _integration_parse_freeform_messages(payload: dict):
    raw_text = str(payload.get('texto') or '').strip()
    raw_messages = payload.get('mensagens') or []
    parsed_messages = []

    whatsapp_pattern = re.compile(
        r'^\[(?P<hora>[^,\]]+),\s*(?P<data>[^\]]+)\]\s*(?P<autor>[^:]+):\s*(?P<conteudo>.*)$'
    )

    def _append_message(content, *, author=None, timestamp=None):
        content_text = str(content or '')
        parsed_messages.append({
            'autor': (author or '').strip() or None,
            'timestamp': (timestamp or '').strip() or None,
            'conteudo': content_text.strip(),
            'conteudo_original': content_text,
        })

    if isinstance(raw_messages, list):
        for item in raw_messages:
            if isinstance(item, dict):
                _append_message(
                    item.get('conteudo') or item.get('content') or item.get('texto'),
                    author=item.get('autor') or item.get('author') or item.get('sender'),
                    timestamp=item.get('timestamp') or item.get('quando') or item.get('time'),
                )
            else:
                line = str(item or '')
                match = whatsapp_pattern.match(line.strip())
                if match:
                    _append_message(
                        match.group('conteudo'),
                        author=match.group('autor'),
                        timestamp=f"{match.group('data')} {match.group('hora')}",
                    )
                else:
                    _append_message(line)

    if raw_text:
        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = whatsapp_pattern.match(stripped)
            if match:
                _append_message(
                    match.group('conteudo'),
                    author=match.group('autor'),
                    timestamp=f"{match.group('data')} {match.group('hora')}",
                )
            else:
                _append_message(stripped)

    return parsed_messages


def _integration_extract_freeform_intake(payload: dict):
    messages = _integration_parse_freeform_messages(payload)
    if not messages:
        raise ValueError('Informe texto livre ou uma lista de mensagens para interpretação.')

    url_pattern = re.compile(r'https?://\S+')
    phone_pattern = re.compile(r'(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?(?:9?\d{4})[-\s]?\d{4}')
    date_pattern = re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b')
    time_pattern = re.compile(r'\b\d{1,2}:\d{2}\b')

    map_links = []
    other_links = []
    phones = []
    dates_found = []
    times_found = []
    name_candidates = []
    empty_messages = 0

    for message in messages:
        content = (message.get('conteudo') or '').strip()
        if not content:
            empty_messages += 1
            continue

        for found_url in url_pattern.findall(content):
            if 'maps.app.goo.gl' in found_url or 'google.com/maps' in found_url or 'goo.gl/maps' in found_url:
                if found_url not in map_links:
                    map_links.append(found_url)
            elif found_url not in other_links:
                other_links.append(found_url)

        for found_phone in phone_pattern.findall(content):
            normalized_phone = re.sub(r'\D+', '', found_phone)
            if normalized_phone and normalized_phone not in phones:
                phones.append(normalized_phone)

        for found_date in date_pattern.findall(content):
            if found_date not in dates_found:
                dates_found.append(found_date)

        for found_time in time_pattern.findall(content):
            if found_time not in times_found:
                times_found.append(found_time)

        cleaned = re.sub(url_pattern, '', content).strip(' -–,:;')
        if (
            cleaned
            and len(cleaned.split()) <= 3
            and re.fullmatch(r"[A-Za-zÀ-ÿ' ]+", cleaned)
            and len(cleaned) >= 3
        ):
            candidate = cleaned.strip()
            if candidate not in name_candidates:
                name_candidates.append(candidate)

    tutor_name = name_candidates[0] if name_candidates else None
    phone = phones[0] if phones else None
    suggested_action = 'cadastrar_tutor_e_pets'
    if dates_found or times_found:
        suggested_action = 'agendar_consulta'

    tutor_draft = {
        'nome': tutor_name,
        'telefone': phone,
        'endereco_referencia': map_links[0] if map_links else None,
    }

    agendamento_draft = None
    if dates_found or times_found:
        agendamento_draft = {
            'data_candidata': dates_found[0] if dates_found else None,
            'hora_candidata': times_found[0] if times_found else None,
        }

    missing_fields = []
    if not tutor_draft['nome']:
        missing_fields.append('nome_do_tutor')
    if not tutor_draft['telefone']:
        missing_fields.append('telefone_do_tutor')
    if not tutor_draft['endereco_referencia']:
        missing_fields.append('endereco_ou_localizacao')
    missing_fields.extend([
        'nome_do_pet',
        'especie_do_pet',
        'motivo_clinico_ou_objetivo_do_atendimento',
    ])
    if agendamento_draft and not agendamento_draft['data_candidata']:
        missing_fields.append('data_do_agendamento')
    if agendamento_draft and not agendamento_draft['hora_candidata']:
        missing_fields.append('hora_do_agendamento')

    summary_parts = []
    if tutor_draft['nome']:
        summary_parts.append(f"Possível tutor identificado: {tutor_draft['nome']}.")
    if tutor_draft['endereco_referencia']:
        summary_parts.append('Foi identificado um link de localização/mapa.')
    if empty_messages:
        summary_parts.append(f'Há {empty_messages} mensagem(ns) vazia(s) ou sem conteúdo útil.')
    summary_parts.append(
        'Ainda faltam dados clínicos e do pet para converter a conversa em cadastro ou atendimento operacional.'
    )

    return {
        'mensagens_processadas': len(messages),
        'mensagens_vazias': empty_messages,
        'dados_extraidos': {
            'nomes_candidatos': name_candidates,
            'telefones': phones,
            'links_mapa': map_links,
            'outros_links': other_links,
            'datas_identificadas': dates_found,
            'horarios_identificados': times_found,
        },
        'rascunho_operacional': {
            'tutor': tutor_draft,
            'pets': [],
            'agendamento': agendamento_draft,
            'consulta': None,
        },
        'acao_sugerida': suggested_action,
        'campos_a_confirmar': list(dict.fromkeys(missing_fields)),
        'resumo_interpretado': ' '.join(summary_parts),
    }


def _integration_parse_flexible_date(value: str | None):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    match = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', raw)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _integration_infer_assistant_action(user: User, payload: dict):
    intake = _integration_extract_freeform_intake(payload)
    messages = _integration_parse_freeform_messages(payload)
    full_text = '\n'.join((message.get('conteudo_original') or '') for message in messages)
    normalized_text = _integration_normalize_lookup_token(full_text)

    def _extract_label(patterns):
        for pattern in patterns:
            match = re.search(pattern, full_text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" .,:;-")
        return None

    tutor_name = (
        _extract_label([
            r'(?:tutor|respons[aá]vel|cliente)\s*[:\-]\s*([A-Za-zÀ-ÿ\' ]{3,80})',
            r'cadastrar\s+tutor\s+([A-Za-zÀ-ÿ\' ]{3,80})',
        ])
        or intake['rascunho_operacional']['tutor'].get('nome')
    )
    pet_name = _extract_label([
        r'(?:pet|animal|paciente)\s*[:\-]\s*([A-Za-zÀ-ÿ\' ]{2,80})',
        r'(?:pet|animal|paciente)\s+([A-Za-zÀ-ÿ\' ]{2,80}?)(?=\s+em\b|[.,;]|$)',
        r'cadel[ao]\s+([A-Za-zÀ-ÿ\' ]{2,80})',
        r'gat[oa]\s+([A-Za-zÀ-ÿ\' ]{2,80})',
    ])
    phone = (
        _extract_label([r'(?:telefone|fone|whatsapp)\s*[:\-]\s*([\d\+\-\(\) ]{8,30})'])
        or intake['rascunho_operacional']['tutor'].get('telefone')
    )
    address = (
        _extract_label([r'(?:endere[cç]o|local)\s*[:\-]\s*([^.\n]{5,160})'])
        or intake['rascunho_operacional']['tutor'].get('endereco_referencia')
    )
    reason = _extract_label([
        r'(?:motivo|queixa|objetivo)\s*[:\-]\s*([^.\n]{3,200})',
        r'agendar\s+consulta\s+.*?para\s+([^\n]{3,120})',
    ])
    observacao_clinica = _extract_label([
        r'(?:observa[cç][aã]o\s+cl[ií]nica|observa[cç][aã]o)\s*[:\-]\s*([^.\n]{3,200})',
    ])
    diagnostico = _extract_label([
        r'(?:diagn[oó]stico|hip[oó]tese)\s*[:\-]\s*([^.\n]{3,200})',
    ])
    conduta = _extract_label([
        r'conduta\s*[:\-]\s*([^.\n]{3,200})',
    ])
    clinic_name = _extract_label([
        r'(?:cl[ií]nica(?:\s+requisitante)?|requisitante)\s*[:\-]\s*([^.\n]{2,120})',
    ])
    exam_type = _extract_label([
        r'(?:exame|tipo\s+de\s+exame)\s*[:\-]\s*([^.\n]{3,120})',
    ])
    crmv = _extract_label([
        r'(?:crmv(?:[-\s]?[A-Za-z]{2})?)\s*[:\-]?\s*([A-Za-z]{0,2}\s*\d{2,8})',
    ])

    species = None
    labeled_species = _extract_label([r'esp[eé]cie\s*[:\-]\s*([A-Za-zÀ-ÿ ]{2,40})'])
    normalized_species = _integration_normalize_lookup_token(labeled_species) if labeled_species else ''
    if normalized_species in {'cao', 'cachorro', 'canino'} or any(
        token in normalized_text for token in ('cachorro', 'cao', 'canino', 'cadela')
    ):
        species = 'cao'
    elif normalized_species in {'gato', 'gata', 'felino'} or any(
        token in normalized_text for token in ('gato', 'gata', 'felino')
    ):
        species = 'gato'

    parsed_date = None
    for found_date in intake['dados_extraidos']['datas_identificadas']:
        parsed_date = _integration_parse_flexible_date(found_date)
        if parsed_date:
            break
    parsed_time = None
    for found_time in intake['dados_extraidos']['horarios_identificados']:
        try:
            parsed_time = _integration_parse_time_arg(found_time)
            break
        except ValueError:
            continue

    intent_scores = {
        'cadastrar_tutor_e_pets': 0,
        'agendar_consulta': 0,
        'registrar_consulta_clinica': 0,
        'criar_exame_imagem': 0,
    }
    if any(token in normalized_text for token in ('ultrassom', 'ultrassonografia', 'laudo', 'pdf', 'imagem', 'clinicarequisitante', 'requisitante')):
        intent_scores['criar_exame_imagem'] += 6
    if any(token in normalized_text for token in ('anexar', 'liberar', 'convite', 'primeiroacesso')):
        intent_scores['criar_exame_imagem'] += 2
    if exam_type:
        intent_scores['criar_exame_imagem'] += 2
    if clinic_name:
        intent_scores['criar_exame_imagem'] += 1
    if any(token in normalized_text for token in ('cadastrar', 'cadastro', 'novotutor', 'novopet')):
        intent_scores['cadastrar_tutor_e_pets'] += 3
    if tutor_name:
        intent_scores['cadastrar_tutor_e_pets'] += 1
    if pet_name:
        intent_scores['cadastrar_tutor_e_pets'] += 1

    if any(token in normalized_text for token in ('agendar', 'agenda', 'marcar', 'retorno')):
        intent_scores['agendar_consulta'] += 3
    if parsed_date:
        intent_scores['agendar_consulta'] += 2
    if parsed_time:
        intent_scores['agendar_consulta'] += 1

    if any(token in normalized_text for token in ('consulta', 'diagnostico', 'conduta', 'queixa', 'examefisico')):
        intent_scores['registrar_consulta_clinica'] += 2
    if diagnostico:
        intent_scores['registrar_consulta_clinica'] += 2
    if conduta or reason:
        intent_scores['registrar_consulta_clinica'] += 1

    suggested_action = max(intent_scores, key=intent_scores.get)
    if all(score == 0 for score in intent_scores.values()):
        suggested_action = intake['acao_sugerida']

    suggested_arguments = {}
    missing_fields = []

    if suggested_action == 'cadastrar_tutor_e_pets':
        tutor_payload = {
            'nome': tutor_name,
            'telefone': phone,
            'endereco': address,
        }
        pet_payload = {'nome': pet_name, 'especie': species}
        suggested_arguments = {
            'tutor': {key: value for key, value in tutor_payload.items() if value},
            'pets': [{key: value for key, value in pet_payload.items() if value}] if pet_name else [],
            'observacao_clinica': observacao_clinica or reason,
        }
        if not tutor_name:
            missing_fields.append('nome_do_tutor')
        if not pet_name:
            missing_fields.append('nome_do_pet')
    elif suggested_action == 'agendar_consulta':
        suggested_arguments = {
            'nome_animal': pet_name,
            'data': parsed_date.isoformat() if parsed_date else None,
            'hora': parsed_time.isoformat(timespec='minutes') if parsed_time else None,
            'tipo': 'retorno' if 'retorno' in normalized_text else 'consulta',
            'motivo': reason or observacao_clinica,
        }
        if not pet_name:
            missing_fields.append('nome_do_pet_ja_cadastrado')
        if not parsed_date:
            missing_fields.append('data_do_agendamento')
        if not parsed_time:
            missing_fields.append('hora_do_agendamento')
    elif suggested_action == 'registrar_consulta_clinica':
        suggested_arguments = {
            'nome_animal': pet_name,
            'queixa_principal': reason,
            'diagnostico': diagnostico,
            'conduta': conduta,
        }
        if not pet_name:
            missing_fields.append('nome_do_pet_ja_cadastrado')
        if not any(suggested_arguments.get(key) for key in ('queixa_principal', 'diagnostico', 'conduta')):
            missing_fields.append('dados_clinicos_da_consulta')
    elif suggested_action == 'criar_exame_imagem':
        suggested_arguments = {
            'nome_animal': pet_name,
            'nome_tutor': tutor_name,
            'nome_clinica': clinic_name,
            'tipo_exame': exam_type or ('Ultrassonografia Abdominal' if 'ultrassonografia' in normalized_text or 'ultrassom' in normalized_text else None),
            'data_exame': parsed_date.isoformat() if parsed_date else None,
            'profissional_crmv': crmv,
            'descricao': reason or observacao_clinica,
        }
        if not pet_name:
            missing_fields.append('nome_do_animal')
        if not tutor_name:
            missing_fields.append('nome_do_tutor')
        if not clinic_name:
            missing_fields.append('nome_da_clinica_requisitante')
        if not suggested_arguments.get('tipo_exame'):
            missing_fields.append('tipo_exame')
        if not parsed_date:
            missing_fields.append('data_exame')

    return {
        'intake': intake,
        'acao_sugerida': suggested_action,
        'argumentos_sugeridos': suggested_arguments,
        'campos_a_confirmar': list(dict.fromkeys(missing_fields)),
    }


def _integration_execute_assistant_action(user: User, planning: dict):
    action = planning['acao_sugerida']
    arguments = dict(planning.get('argumentos_sugeridos') or {})

    if action == 'cadastrar_tutor_e_pets':
        if not has_veterinarian_profile(user):
            raise PermissionError('Somente contas veterinárias podem cadastrar tutor e pets via assistente.')
        tutor_data = arguments.get('tutor') or {}
        pets_data = arguments.get('pets') or []
        if not tutor_data or not pets_data:
            raise ValueError('Ainda faltam dados para cadastrar tutor e pet.')
        result = _integration_create_or_reuse_tutor_and_pets(
            user,
            tutor_data,
            pets_data,
            observacao_clinica=arguments.get('observacao_clinica'),
            disponibilidade=arguments.get('disponibilidade'),
        )
        return {'acao_executada': action, 'resultado': result}

    if action == 'agendar_consulta':
        animal = _mcp_find_animal_for_tool(user, arguments)
        if not animal:
            raise ValueError('Não foi possível identificar um animal já cadastrado para agendamento.')
        appointment = _integration_schedule_consulta(user, animal, arguments)
        return {
            'acao_executada': action,
            'resultado': {
                'appointment_id': appointment.id,
                'animal_id': appointment.animal_id,
                'tipo': appointment.kind,
                'status': appointment.status,
                'scheduled_at': _integration_format_datetime(appointment.scheduled_at),
            },
        }

    if action == 'registrar_consulta_clinica':
        if not has_veterinarian_profile(user):
            raise PermissionError('Somente contas veterinárias podem registrar consulta via assistente.')
        animal = _mcp_find_animal_for_tool(user, arguments)
        if not animal:
            raise ValueError('Não foi possível identificar um animal já cadastrado para registrar a consulta.')
        consulta = _integration_upsert_consulta(user, animal, arguments)
        return {
            'acao_executada': action,
            'resultado': {
                'consulta_id': consulta.id,
                'animal_id': consulta.animal_id,
                'status': consulta.status,
                'queixa_principal': consulta.queixa_principal,
                'conduta': consulta.conduta,
            },
        }

    if action == 'criar_exame_imagem':
        if not has_veterinarian_profile(user):
            raise PermissionError('Somente contas veterinarias podem criar exame de imagem via assistente.')
        return {
            'acao_executada': action,
            'resultado': _integration_create_exame_imagem(user, arguments),
        }

    raise ValueError('A ação sugerida ainda não pode ser executada automaticamente.')


def _integration_parse_date_arg(value):
    if value in (None, ''):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value).strip())


def _integration_parse_time_arg(value):
    if value in (None, ''):
        return None
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value).strip())


def _integration_parse_datetime_arg(date_value, time_value):
    parsed_date = _integration_parse_date_arg(date_value)
    parsed_time = _integration_parse_time_arg(time_value)
    if not parsed_date or not parsed_time:
        raise ValueError('Data e hora são obrigatórias.')
    return datetime.combine(parsed_date, parsed_time)


def _integration_generate_provisional_email(name: str) -> str:
    token = _integration_normalize_lookup_token(name)[:40] or 'tutor'
    base = f'{token}@cadastro.petorlandia.local'
    if not User.query.filter_by(email=base).first():
        return base

    suffix = 2
    while True:
        candidate = f'{token}.{suffix}@cadastro.petorlandia.local'
        if not User.query.filter_by(email=candidate).first():
            return candidate
        suffix += 1


def _integration_resolve_species(species_name: str | None):
    if not species_name:
        return None
    token = _integration_normalize_lookup_token(species_name)
    aliases = {
        'cao': {'cao', 'cachorro', 'canino'},
        'gato': {'gato', 'gata', 'felino'},
    }
    canonical_names = {
        'cao': 'Cachorro',
        'gato': 'Gato',
    }
    species_rows = Species.query.order_by(Species.name).all()
    for species in species_rows:
        species_token = _integration_normalize_lookup_token(species.name)
        if token == species_token:
            return species
        for alias_group in aliases.values():
            if token in alias_group and species_token in alias_group:
                return species
    for canonical_token, alias_group in aliases.items():
        if token in alias_group:
            created_species = Species(name=canonical_names[canonical_token])
            db.session.add(created_species)
            db.session.flush()
            return created_species
    return None


def _integration_resolve_breed(species, breed_name: str | None):
    if not species or not breed_name:
        return None
    token = _integration_normalize_lookup_token(breed_name)
    breed_rows = Breed.query.filter_by(species_id=species.id).order_by(Breed.name).all()
    for breed in breed_rows:
        if _integration_normalize_lookup_token(breed.name) == token:
            return breed
    return None


def _integration_require_professional_writer(user: User, *, require_veterinarian: bool = False):
    if require_veterinarian:
        return has_veterinarian_profile(user)
    return has_professional_access(user)


def _integration_find_existing_tutor(clinic_id: int | None, tutor_data: dict):
    email = (tutor_data.get('email') or '').strip().lower()
    phone = (tutor_data.get('telefone') or tutor_data.get('phone') or '').strip()
    cpf = (tutor_data.get('cpf') or '').strip()
    name = (tutor_data.get('nome') or tutor_data.get('name') or '').strip()

    if email:
        found = User.query.filter(func.lower(User.email) == email).first()
        if found:
            return found
    if cpf:
        found = User.query.filter_by(cpf=cpf).first()
        if found:
            return found
    if clinic_id and name:
        query = User.query.filter(
            User.clinica_id == clinic_id,
            func.lower(User.name) == name.lower(),
            User.role == 'adotante',
        )
        if phone:
            query = query.filter(User.phone == phone)
        found = query.first()
        if found:
            return found
    return None


def _integration_find_existing_pet(tutor_id: int, pet_data: dict):
    pet_name = (pet_data.get('nome') or pet_data.get('name') or '').strip()
    if not pet_name:
        return None
    query = Animal.query.filter(
        Animal.user_id == tutor_id,
        Animal.removido_em.is_(None),
        func.lower(Animal.name) == pet_name.lower(),
    )

    microchip = (pet_data.get('microchip_number') or '').strip()
    if microchip:
        found = query.filter(Animal.microchip_number == microchip).first()
        if found:
            return found
    return query.first()


def _integration_create_initial_consulta(animal: Animal, user: User, observacao_clinica: str | None = None, disponibilidade: str | None = None):
    consulta = Consulta(
        animal_id=animal.id,
        created_by=user.id,
        clinica_id=_integration_user_clinic_id(user) or getattr(animal, 'clinica_id', None),
        status='in_progress',
        queixa_principal=(observacao_clinica or '').strip() or None,
        historico_clinico=(
            f"Disponibilidade informada: {disponibilidade.strip()}"
            if (disponibilidade or '').strip() else None
        ),
    )
    db.session.add(consulta)
    db.session.flush()
    return consulta


def _integration_create_or_reuse_tutor_and_pets(user: User, tutor_data: dict, pets_data: list[dict], observacao_clinica: str | None = None, disponibilidade: str | None = None):
    clinic_id = _integration_user_clinic_id(user)
    tutor = _integration_find_existing_tutor(clinic_id, tutor_data)
    tutor_already_exists = tutor is not None
    provisional_email = False

    if tutor is None:
        tutor_email = (tutor_data.get('email') or '').strip().lower()
        if not tutor_email:
            tutor_email = _integration_generate_provisional_email(tutor_data.get('nome') or tutor_data.get('name') or 'tutor')
            provisional_email = True
        tutor = User(
            name=(tutor_data.get('nome') or tutor_data.get('name') or '').strip() or 'Tutor sem nome',
            email=tutor_email,
            phone=(tutor_data.get('telefone') or tutor_data.get('phone') or '').strip() or None,
            address=(tutor_data.get('endereco') or tutor_data.get('address') or '').strip() or None,
            cpf=(tutor_data.get('cpf') or '').strip() or None,
            rg=(tutor_data.get('rg') or '').strip() or None,
            role='adotante',
            clinica_id=clinic_id,
            added_by=current_user if has_request_context() and current_user.is_authenticated else user,
            is_private=True,
        )
        date_of_birth = tutor_data.get('date_of_birth')
        if date_of_birth:
            tutor.date_of_birth = _integration_parse_date_arg(date_of_birth)
        tutor.set_password('123456789')
        db.session.add(tutor)
        db.session.flush()

    pets_result = []
    consultas_criadas = 0
    pets_created = 0
    pets_reused = 0

    for pet_data in pets_data:
        existing_pet = _integration_find_existing_pet(tutor.id, pet_data)
        if existing_pet:
            pets_reused += 1
            pets_result.append({
                'id': existing_pet.id,
                'nome': existing_pet.name,
                'ja_existia': True,
            })
            continue

        species = _integration_resolve_species(pet_data.get('especie') or pet_data.get('species'))
        breed = _integration_resolve_breed(species, pet_data.get('raca') or pet_data.get('breed'))
        dob = _integration_parse_date_arg(pet_data.get('date_of_birth'))
        age_number = pet_data.get('idade_numero')
        age_text = (pet_data.get('idade') or pet_data.get('age') or '').strip()
        age_unit = pet_data.get('age_unit') or 'anos'
        if not dob and age_text:
            match = re.search(r'(\d+)', age_text)
            if match:
                age_number = int(match.group(1))
            if age_number is not None:
                normalized_unit = _normalizar_unidade_idade(age_unit if pet_data.get('age_unit') else age_text)
                if normalized_unit == 'meses':
                    dob = date.today() - relativedelta(months=int(age_number))
                else:
                    dob = date.today() - relativedelta(years=int(age_number))

        age_formatted = None
        if age_number is not None:
            age_formatted = _formatar_idade(int(age_number), age_unit)
        elif age_text:
            age_formatted = age_text

        peso = pet_data.get('peso') or pet_data.get('peso_kg')
        try:
            peso_float = float(peso) if peso not in (None, '') else None
        except (TypeError, ValueError):
            peso_float = None

        pet = Animal(
            name=(pet_data.get('nome') or pet_data.get('name') or '').strip() or 'Pet sem nome',
            species_id=species.id if species else None,
            breed_id=breed.id if breed else None,
            sex=(pet_data.get('sexo') or pet_data.get('sex') or '').strip() or None,
            date_of_birth=dob,
            age=age_formatted,
            microchip_number=(pet_data.get('microchip_number') or '').strip() or None,
            peso=peso_float,
            health_plan=(pet_data.get('health_plan') or '').strip() or None,
            description=(pet_data.get('descricao') or pet_data.get('description') or '').strip() or None,
            user_id=tutor.id,
            added_by_id=user.id,
            clinica_id=clinic_id,
            status='disponível',
            image=None,
            is_alive=True,
            modo='adotado',
        )
        db.session.add(pet)
        db.session.flush()
        pets_created += 1

        _integration_create_initial_consulta(
            pet,
            user,
            observacao_clinica=observacao_clinica,
            disponibilidade=disponibilidade,
        )
        consultas_criadas += 1
        pets_result.append({
            'id': pet.id,
            'nome': pet.name,
            'ja_existia': False,
        })

    db.session.commit()

    return {
        'tutor': {
            'id': tutor.id,
            'nome': tutor.name,
            'email': tutor.email,
            'ja_existia': tutor_already_exists,
            'email_provisorio': provisional_email,
        },
        'pets': pets_result,
        'resumo': {
            'pets_criados': pets_created,
            'pets_reaproveitados': pets_reused,
            'consultas_iniciais_criadas': consultas_criadas,
        },
    }


def _integration_upsert_consulta(user: User, animal: Animal, payload: dict):
    clinic_id = _integration_user_clinic_id(user) or animal.clinica_id
    consulta_id = payload.get('consulta_id')
    consulta = None
    if consulta_id is not None:
        try:
            consulta_id = int(consulta_id)
        except (TypeError, ValueError):
            raise ValueError('consulta_id inválido.')
        consulta = (
            _integration_accessible_consultas_query(user, clinic_id=clinic_id)
            .filter(Consulta.id == consulta_id, Consulta.animal_id == animal.id)
            .first()
        )
    if consulta is None:
        consulta = (
            _integration_accessible_consultas_query(user, clinic_id=clinic_id)
            .filter(Consulta.animal_id == animal.id, Consulta.status == 'in_progress')
            .order_by(Consulta.created_at.desc())
            .first()
        )
    if consulta is None:
        consulta = Consulta(
            animal_id=animal.id,
            created_by=user.id,
            clinica_id=clinic_id,
            status='in_progress',
        )
        db.session.add(consulta)
        db.session.flush()

    diagnostico = (payload.get('diagnostico') or '').strip()
    conduta = (payload.get('conduta') or '').strip()
    if diagnostico:
        conduta = f"Diagnóstico: {diagnostico}\n{conduta}".strip()

    consulta.queixa_principal = (payload.get('queixa_principal') or consulta.queixa_principal or '').strip() or None
    consulta.historico_clinico = (payload.get('historico_clinico') or consulta.historico_clinico or '').strip() or None
    consulta.exame_fisico = (payload.get('exame_fisico') or consulta.exame_fisico or '').strip() or None
    consulta.suspeita_clinica = (
        payload.get('suspeita_clinica')
        or diagnostico
        or consulta.suspeita_clinica
        or ''
    ).strip() or None
    consulta.conduta = conduta or consulta.conduta
    consulta.exames_solicitados = (payload.get('exames_solicitados') or consulta.exames_solicitados or '').strip() or None
    consulta.prescricao = (payload.get('prescricao') or consulta.prescricao or '').strip() or None

    finalizada = bool(payload.get('finalizar'))
    if finalizada:
        consulta.status = 'finalizada'
        consulta.finalizada_em = utcnow()
        if consulta.appointment and consulta.appointment.status != 'completed':
            consulta.appointment.status = 'completed'

    db.session.add(consulta)
    db.session.commit()
    return consulta


def _integration_create_exam_block(user: User, animal: Animal, payload: dict):
    exames_data = payload.get('exames') or []
    if not exames_data:
        raise ValueError('Informe pelo menos um exame.')

    bloco = BlocoExames(
        animal_id=animal.id,
        observacoes_gerais=(payload.get('observacoes_gerais') or '').strip() or None,
    )
    db.session.add(bloco)
    db.session.flush()

    for exam in exames_data:
        performed_at = exam.get('performed_at')
        parsed_performed_at = None
        if performed_at:
            parsed_performed_at = datetime.fromisoformat(str(performed_at))
        db.session.add(
            ExameSolicitado(
                bloco_id=bloco.id,
                nome=(exam.get('nome') or '').strip(),
                justificativa=(exam.get('justificativa') or '').strip() or None,
                status=(exam.get('status') or 'pendente').strip() or 'pendente',
                resultado=(exam.get('resultado') or '').strip() or None,
                performed_at=parsed_performed_at,
            )
        )

    db.session.commit()
    return bloco


def _integration_find_or_create_external_clinic(user: User, clinic_data: dict):
    clinic_name = (clinic_data.get('nome') or clinic_data.get('name') or '').strip()
    if not clinic_name:
        raise ValueError('Informe o nome da clinica solicitante.')

    email = (clinic_data.get('email') or '').strip().lower() or None
    phone = (clinic_data.get('telefone') or clinic_data.get('phone') or '').strip() or None
    cnpj = (clinic_data.get('cnpj') or '').strip() or None

    query = Clinica.query.filter(func.lower(Clinica.nome) == clinic_name.lower())
    if cnpj:
        existing = query.filter(Clinica.cnpj == cnpj).first()
        if existing:
            return existing, False
    existing = query.first()
    if existing:
        updated = False
        if email and not existing.email:
            existing.email = email
            updated = True
        if phone and not existing.telefone:
            existing.telefone = phone
            updated = True
        if updated:
            db.session.add(existing)
            db.session.flush()
        return existing, False

    clinic = Clinica(
        nome=clinic_name,
        email=email,
        telefone=phone,
        cnpj=cnpj,
        endereco=(clinic_data.get('endereco') or clinic_data.get('address') or '').strip() or None,
    )
    db.session.add(clinic)
    db.session.flush()

    return clinic, True


def _integration_ensure_clinic_admin_user(clinic: Clinica, *, email: str | None = None, phone: str | None = None, name: str | None = None):
    email = (email or clinic.email or '').strip().lower()
    phone = (phone or clinic.telefone or '').strip() or None
    if clinic.owner_id:
        owner = db.session.get(User, clinic.owner_id)
        if owner:
            if phone and not owner.phone:
                owner.phone = phone
                db.session.add(owner)
            return owner, False

    owner = User.query.filter(func.lower(User.email) == email).first() if email else None
    created = False
    if not owner and email:
        owner = User(
            name=(name or clinic.nome or 'Administrador da clinica').strip(),
            email=email,
            phone=phone,
            role='adotante',
            worker='colaborador',
            clinica_id=clinic.id,
        )
        owner.set_password(secrets.token_urlsafe(16))
        db.session.add(owner)
        db.session.flush()
        created = True
    if owner:
        if not owner.clinica_id:
            owner.clinica_id = clinic.id
        if phone and not owner.phone:
            owner.phone = phone
        clinic.owner_id = owner.id
        db.session.add_all([owner, clinic])
        db.session.flush()
    return owner, created


def _integration_find_or_create_tutor_for_clinic(user: User, clinic: Clinica, tutor_data: dict):
    tutor = _integration_find_existing_tutor(clinic.id, tutor_data)
    created = False
    provisional_email = False
    if tutor:
        return tutor, created, provisional_email

    tutor_email = (tutor_data.get('email') or '').strip().lower()
    if not tutor_email:
        tutor_email = _integration_generate_provisional_email(tutor_data.get('nome') or tutor_data.get('name') or 'tutor')
        provisional_email = True

    tutor = User(
        name=(tutor_data.get('nome') or tutor_data.get('name') or '').strip() or 'Tutor sem nome',
        email=tutor_email,
        phone=(tutor_data.get('telefone') or tutor_data.get('phone') or '').strip() or None,
        address=(tutor_data.get('endereco') or tutor_data.get('address') or '').strip() or None,
        cpf=(tutor_data.get('cpf') or '').strip() or None,
        role='adotante',
        clinica_id=clinic.id,
        added_by=user,
        is_private=True,
    )
    tutor.set_password(secrets.token_urlsafe(16))
    db.session.add(tutor)
    db.session.flush()
    return tutor, True, provisional_email


def _integration_find_or_create_pet_for_tutor(user: User, clinic: Clinica, tutor: User, pet_data: dict):
    pet = _integration_find_existing_pet(tutor.id, pet_data)
    if pet:
        if not pet.clinica_id:
            pet.clinica_id = clinic.id
            db.session.add(pet)
            db.session.flush()
        return pet, False

    species = _integration_resolve_species(pet_data.get('especie') or pet_data.get('species'))
    breed = _integration_resolve_breed(species, pet_data.get('raca') or pet_data.get('breed'))
    pet = Animal(
        name=(pet_data.get('nome') or pet_data.get('name') or '').strip() or 'Pet sem nome',
        species_id=species.id if species else None,
        breed_id=breed.id if breed else None,
        sex=(pet_data.get('sexo') or pet_data.get('sex') or '').strip() or None,
        age=(pet_data.get('idade') or pet_data.get('age') or '').strip() or None,
        user_id=tutor.id,
        added_by_id=user.id,
        clinica_id=clinic.id,
        status='disponível',
        modo='adotado',
        is_alive=True,
    )
    db.session.add(pet)
    db.session.flush()
    return pet, True


def _integration_import_mobile_exam_report(user: User, payload: dict):
    clinic_data = payload.get('clinica') or {}
    tutor_data = payload.get('tutor') or {}
    animal_data = payload.get('animal') or payload.get('pet') or {}
    exam_data = payload.get('exame') or {}

    if not tutor_data:
        raise ValueError('Informe os dados do tutor/responsavel extraidos do laudo.')
    if not animal_data:
        raise ValueError('Informe os dados do animal extraidos do laudo.')

    clinic, clinic_created = _integration_find_or_create_external_clinic(user, clinic_data)
    tutor, tutor_created, tutor_provisional_email = _integration_find_or_create_tutor_for_clinic(user, clinic, tutor_data)
    animal, animal_created = _integration_find_or_create_pet_for_tutor(user, clinic, tutor, animal_data)

    laudo_url = (payload.get('laudo_url') or '').strip()
    laudo_filename = (payload.get('laudo_filename') or payload.get('nome_arquivo') or '').strip() or None
    laudo_file_ref = _mcp_extract_file_reference(payload, 'laudo_arquivo', 'arquivo_laudo', 'laudo_file')
    laudo_file_status = 'sem_arquivo'
    if laudo_file_ref:
        laudo_url, uploaded_filename = _integration_download_and_store_laudo_file(laudo_file_ref)
        laudo_filename = uploaded_filename or laudo_filename
        laudo_file_status = 'arquivo_salvo'
    elif laudo_url and _is_local_chatgpt_file_path(laudo_url):
        # ChatGPT can surface attachments as local sandbox paths (for example /mnt/data/*.pdf).
        # Those paths are not reachable by PetOrlandia's server; keep the structured import
        # working from the extracted text/data and explicitly avoid persisting the bad path.
        laudo_url = None
        laudo_filename = laudo_filename or os.path.basename(payload.get('laudo_url') or '') or None
        laudo_file_status = 'caminho_local_ignorado'
    elif laudo_url:
        parsed_laudo_url = urlparse(laudo_url)
        if parsed_laudo_url.scheme not in {'http', 'https'} or not parsed_laudo_url.netloc:
            raise ValueError('laudo_url deve ser uma URL http/https publica. Para anexos do ChatGPT, use laudo_arquivo ou cole o texto integral.')
        laudo_file_status = 'url_registrada'

    existing_exam = _integration_find_existing_exam_for_laudo(payload, animal)
    if existing_exam and existing_exam.bloco and existing_exam.bloco.animal:
        animal = existing_exam.bloco.animal
        tutor = animal.owner or tutor
        clinic = animal.clinica or clinic
    report_text = (payload.get('laudo_texto') or payload.get('texto_laudo') or '').strip()
    conclusion = (exam_data.get('conclusao') or payload.get('conclusao') or '').strip()
    findings = (exam_data.get('achados') or payload.get('achados') or '').strip()
    result_parts = [part for part in [conclusion, findings, report_text] if part]
    result_text = '\n\n'.join(result_parts) or None

    performed_at = None
    performed_at_raw = exam_data.get('data') or payload.get('data_exame')
    if performed_at_raw:
        parsed_date = _integration_parse_flexible_date(str(performed_at_raw))
        if not parsed_date:
            raise ValueError('Data do exame invalida. Use YYYY-MM-DD ou DD/MM/YYYY.')
        performed_at = datetime.combine(parsed_date, time(12, 0), tzinfo=BR_TZ)

    if existing_exam:
        exam = existing_exam
        bloco = exam.bloco
        if laudo_url:
            uploaded_at = datetime.now(BR_TZ)
            exam.laudo_url = laudo_url
            exam.laudo_filename = laudo_filename
            exam.laudo_uploaded_at = uploaded_at
            db.session.execute(
                text(
                    'UPDATE exame_solicitado '
                    'SET laudo_url = :laudo_url, laudo_filename = :laudo_filename, laudo_uploaded_at = :laudo_uploaded_at '
                    'WHERE id = :exam_id'
                ),
                {
                    'laudo_url': laudo_url,
                    'laudo_filename': laudo_filename,
                    'laudo_uploaded_at': uploaded_at,
                    'exam_id': exam.id,
                },
            )
            _integration_add_exam_document(user, animal, laudo_url, laudo_filename, exam.nome)
        elif laudo_filename and not exam.laudo_filename:
            exam.laudo_filename = laudo_filename
            db.session.execute(
                text('UPDATE exame_solicitado SET laudo_filename = :laudo_filename WHERE id = :exam_id'),
                {'laudo_filename': laudo_filename, 'exam_id': exam.id},
            )
        if payload.get('mensagem_clinica'):
            exam.laudo_message = (payload.get('mensagem_clinica') or '').strip() or exam.laudo_message
        db.session.add(exam)
        db.session.flush()
        laudo_import_mode = 'anexo_em_exame_existente'
    else:
        bloco = BlocoExames(
            animal_id=animal.id,
            observacoes_gerais=(payload.get('observacoes_gerais') or 'Laudo importado via conector ChatGPT.').strip(),
        )
        db.session.add(bloco)
        db.session.flush()

        exam = ExameSolicitado(
            bloco_id=bloco.id,
            nome=(exam_data.get('nome') or exam_data.get('tipo') or 'Ultrassonografia').strip(),
            justificativa=(exam_data.get('justificativa') or '').strip() or None,
            status='concluido',
            resultado=result_text,
            performed_at=performed_at or datetime.now(BR_TZ),
            laudo_url=laudo_url or None,
            laudo_filename=laudo_filename,
            laudo_uploaded_at=datetime.now(BR_TZ) if laudo_url else None,
            laudo_message=(payload.get('mensagem_clinica') or '').strip() or None,
        )
        db.session.add(exam)
        db.session.flush()
        _integration_add_exam_document(user, animal, laudo_url, laudo_filename, exam.nome)
        laudo_import_mode = 'exame_criado'

    animal_name = animal.name or 'paciente'
    clinic_message = (
        (payload.get('mensagem_clinica') or '').strip()
        or f'Laudo de {exam.nome} do paciente {animal_name} importado pelo ultrassonografista volante.'
    )
    notification_message = (
        f'{clinic_message}\n\n'
        f'Paciente: {animal_name}\n'
        f'Tutor: {tutor.name}\n'
        f'Exame: {exam.nome}'
    )

    if _ensure_clinic_notifications_table():
        db.session.add(
            ClinicNotification(
                clinic_id=clinic.id,
                title='Novo laudo recebido pelo PetOrlândia',
                message=notification_message,
                type='success',
                month=datetime.now(BR_TZ).date().replace(day=1),
            )
        )

    if clinic.owner_id:
        db.session.add(
            Notification(
                user_id=clinic.owner_id,
                message=notification_message,
                channel='app',
                kind='exam_report',
            )
        )

    clinic_id = clinic.id
    clinic_name = clinic.nome
    clinic_owner_id = clinic.owner_id
    clinic_phone = clinic.telefone
    tutor_id = tutor.id
    tutor_name = tutor.name
    tutor_phone = tutor.phone
    animal_id = animal.id
    animal_name = animal.name
    exam_id = exam.id
    exam_name = exam.nome
    exam_status = exam.status
    exam_performed_at = exam.performed_at
    exam_laudo_url = exam.laudo_url
    exam_laudo_filename = exam.laudo_filename
    bloco_id = bloco.id
    clinic_invite = _create_external_onboarding_invite(
        'clinic',
        user,
        clinic=clinic,
        tutor=tutor,
        animal=animal,
        exam=exam,
        message=f'{clinic_message}\n\nAcesse para ver o laudo e conhecer o PetOrlandia.',
    )
    tutor_invite = _create_external_onboarding_invite(
        'tutor',
        user,
        clinic=clinic,
        tutor=tutor,
        animal=animal,
        exam=exam,
        message=f'O laudo de {exam.nome} do paciente {animal_name} foi recebido pelo PetOrlandia.',
    )
    clinic_invite_url = _external_onboarding_url(clinic_invite)
    tutor_invite_url = _first_access_invite_url(tutor_invite)
    db.session.commit()

    clinic_url = None
    animal_url = None
    if has_request_context():
        clinic_url = url_for('clinic_detail', clinica_id=clinic_id, _external=True)
        animal_url = url_for('ficha_animal', animal_id=animal_id, _external=True)

    laudo_public_url = _integration_absolute_public_url(exam_laudo_url)
    clinic_share_url = clinic_invite_url or laudo_public_url
    tutor_share_url = tutor_invite_url or laudo_public_url

    clinic_share_message = (
        (payload.get('mensagem_clinica') or '').strip()
        or f'Laudo de {exam_name} do paciente {animal_name} disponivel no PetOrlandia.'
    )
    if clinic_share_url and clinic_share_url not in clinic_share_message:
        clinic_share_message = f'{clinic_share_message}\n\nAcesse: {clinic_share_url}'

    tutor_share_message = (
        (payload.get('mensagem_tutor') or '').strip()
        or f'O laudo de {exam_name} do paciente {animal_name} esta disponivel para consulta.'
    )
    if tutor_share_url and tutor_share_url not in tutor_share_message:
        tutor_share_message = f'{tutor_share_message}\n\nAcesse: {tutor_share_url}'

    return {
        'clinica': {
            'id': clinic_id,
            'nome': clinic_name,
            'criada_agora': clinic_created,
            'tem_dono_cadastrado': bool(clinic_owner_id),
            'url': clinic_url,
        },
        'tutor': {
            'id': tutor_id,
            'nome': tutor_name,
            'criado_agora': tutor_created,
            'email_provisorio': tutor_provisional_email,
        },
        'animal': {
            'id': animal_id,
            'nome': animal_name,
            'criado_agora': animal_created,
            'url': animal_url,
        },
        'exame': {
            'bloco_id': bloco_id,
            'exame_id': exam_id,
            'nome': exam_name,
            'status': exam_status,
            'data_realizacao': exam_performed_at.astimezone(BR_TZ).date().isoformat() if exam_performed_at else None,
            'laudo_url': exam_laudo_url,
            'laudo_filename': exam_laudo_filename,
            'arquivo_status': laudo_file_status,
            'modo_importacao': laudo_import_mode,
        },
        'links_primeiro_acesso': {
            'clinica': clinic_invite_url,
            'tutor': tutor_invite_url,
        },
        'links': {
            'laudo': laudo_public_url,
            'clinica': clinic_invite_url,
            'tutor': tutor_invite_url,
        },
        'comunicacao': {
            'clinica': {
                'url': clinic_share_url,
                'mensagem': clinic_share_message,
                'whatsapp_url': _web_whatsapp_url(clinic_phone, clinic_share_message),
            },
            'tutor': {
                'url': tutor_share_url,
                'mensagem': tutor_share_message,
                'whatsapp_url': _web_whatsapp_url(tutor_phone, tutor_share_message),
            },
        },
        'proxima_acao_recomendada': (
            'Enviar os links prontos para clinica e tutor.'
            if not clinic_owner_id else
            'Avisar o dono da clinica para abrir a notificacao no PetOrlandia.'
        ),
        'mensagem_sugerida_para_clinica': clinic_share_message,
        'mensagem_sugerida_para_tutor': tutor_share_message,
    }


def _integration_suggest_report_template(user: User, payload: dict):
    exam_type = (payload.get('tipo_exame') or payload.get('exame') or '').strip()
    if not exam_type:
        raise ValueError('Informe o tipo de exame.')
    limit = max(1, min(int(payload.get('limite_exemplos') or 3), 5))
    normalized_type = _integration_normalize_match_text(exam_type)
    species_filter = _integration_normalize_match_text(payload.get('especie') or '')

    query = (
        ExameSolicitado.query
        .join(BlocoExames, ExameSolicitado.bloco_id == BlocoExames.id)
        .join(Animal, BlocoExames.animal_id == Animal.id)
        .filter(ExameSolicitado.resultado.isnot(None))
        .order_by(ExameSolicitado.performed_at.desc().nullslast(), ExameSolicitado.id.desc())
        .limit(50)
    )

    examples = []
    for exam in query.all():
        if normalized_type not in _integration_normalize_match_text(exam.nome):
            continue
        animal = exam.bloco.animal if exam.bloco else None
        animal_species = getattr(animal, 'species', '') if animal else ''
        species_name = getattr(animal_species, 'name', animal_species)
        if species_filter and animal and species_filter not in _integration_normalize_match_text(species_name):
            continue
        result = (exam.resultado or '').strip()
        examples.append({
            'exame_id': exam.id,
            'nome': exam.nome,
            'paciente': getattr(animal, 'name', None),
            'data_realizacao': exam.performed_at.astimezone(BR_TZ).date().isoformat() if exam.performed_at else None,
            'trecho_modelo': result[:1200],
        })
        if len(examples) >= limit:
            break

    achados = (payload.get('achados') or '').strip()
    sections = [
        'Identificacao do paciente e dados do exame',
        'Tecnica e limitacoes do metodo',
        'Descricao por sistemas/orgaos avaliados',
        'Impressao diagnostica',
        'Recomendacoes e correlacao clinica',
    ]
    draft = (
        f'{exam_type}\n\n'
        'Paciente: [nome]\nTutor: [nome]\nData: [data]\n\n'
        'Achados:\n'
        f'{achados or "[descrever achados atuais por orgao/sistema]"}\n\n'
        'Impressao diagnostica:\n'
        '[resumir os achados principais sem extrapolar alem do exame]\n\n'
        'Recomendacoes:\n'
        '[sugerir correlacao clinica, exames complementares ou acompanhamento quando aplicavel]'
    )
    return {
        'tipo_exame': exam_type,
        'estrutura_sugerida': sections,
        'rascunho_base': draft,
        'exemplos_encontrados': examples,
        'orientacao': (
            'Use os exemplos apenas como padrao de estrutura e linguagem. '
            'Adapte todos os achados ao paciente atual e mantenha a impressao diagnostica compatível com o exame.'
        ),
    }


def _integration_schedule_consulta(user: User, animal: Animal, payload: dict):
    if not has_veterinarian_profile(user):
        raise PermissionError('Somente contas veterinárias podem agendar consultas via ChatGPT.')

    veterinario = getattr(user, 'veterinario', None)
    vet_id = payload.get('veterinario_id') or (veterinario.id if veterinario else None)
    if not vet_id:
        raise ValueError('veterinario_id é obrigatório.')
    try:
        vet_id = int(vet_id)
    except (TypeError, ValueError):
        raise ValueError('veterinario_id inválido.')

    scheduled_at_local = _integration_parse_datetime_arg(payload.get('data'), payload.get('hora'))
    appointment_kind = (payload.get('tipo') or 'consulta').strip() or 'consulta'
    if not is_slot_available(vet_id, scheduled_at_local, kind=appointment_kind):
        raise ValueError('Horário indisponível para o veterinário selecionado.')

    duration = get_appointment_duration(appointment_kind)
    if has_conflict_for_slot(vet_id, scheduled_at_local, duration):
        raise ValueError('Horário indisponível para o veterinário selecionado.')

    appointment = Appointment(
        animal_id=animal.id,
        tutor_id=animal.user_id,
        veterinario_id=vet_id,
        scheduled_at=normalize_to_utc(scheduled_at_local),
        status='accepted' if veterinario and veterinario.id == vet_id else 'scheduled',
        kind=appointment_kind,
        notes=(payload.get('motivo') or payload.get('reason') or '').strip() or None,
        created_by=user.id,
        created_at=utcnow(),
        clinica_id=_integration_user_clinic_id(user) or animal.clinica_id,
    )
    db.session.add(appointment)
    db.session.commit()
    return appointment


def integration_bearer_required(*required_scopes: str):
    required_scope_set = {scope for scope in required_scopes if scope}

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            access_token = _oauth_extract_bearer_token()
            if not access_token:
                return _integration_error(
                    'missing_bearer_token',
                    'Missing bearer access token.',
                    401,
                )

            token = OAuthAccessToken.query.filter_by(access_token=access_token).first()
            if not token or not token.is_active:
                return _integration_error(
                    'invalid_access_token',
                    'Access token is invalid or expired.',
                    401,
                )

            token_scope_set = {item.strip() for item in (token.scope or '').split() if item.strip()}
            missing_scopes = sorted(required_scope_set.difference(token_scope_set))
            if missing_scopes:
                if _oauth_access_token_can_self_heal_mcp_scope(token):
                    healed_scope = _oauth_default_mcp_scope()
                    token.scope = healed_scope
                    refresh = (
                        db.session.get(OAuthRefreshToken, token.refresh_token_id)
                        if token.refresh_token_id
                        else None
                    )
                    if refresh is not None and _oauth_scope_needs_mcp_recovery(refresh.scope):
                        refresh.scope = healed_scope
                        db.session.add(refresh)
                    db.session.add(token)
                    db.session.commit()
                    _oauth_log_event('oauth_mcp_legacy_access_scope_upgraded', client_id=token.client_id, user_id=token.user_id)
                    token_scope_set = _oauth_scope_tokens(healed_scope)
                    missing_scopes = sorted(required_scope_set.difference(token_scope_set))

                if missing_scopes and _oauth_access_token_requires_mcp_reauthorization(token):
                    refresh = (
                        db.session.get(OAuthRefreshToken, token.refresh_token_id)
                        if token.refresh_token_id
                        else None
                    )
                    if refresh is not None:
                        _oauth_revoke_refresh_family(refresh)
                    elif token.revoked_at is None:
                        token.revoked_at = utcnow()
                        db.session.add(token)
                    db.session.commit()
                    _oauth_log_event('oauth_mcp_reauthorization_required', client_id=token.client_id, user_id=token.user_id)
                    return _integration_error(
                        'reauthorization_required',
                        'Este token foi emitido antes dos escopos clinicos atuais. Reconecte o PetOrlandia no ChatGPT para autorizar pets:read, exams:write e os demais escopos clinicos.',
                        401,
                        required_scopes=sorted(required_scope_set),
                        granted_scopes=sorted(token_scope_set),
                        missing_scopes=missing_scopes,
                    )
                if missing_scopes:
                    return _integration_error(
                        'insufficient_scope',
                        'Access token does not grant the required scope.',
                        403,
                        required_scopes=sorted(required_scope_set),
                        granted_scopes=sorted(token_scope_set),
                        missing_scopes=missing_scopes,
                    )

            auth_user = db.session.get(User, token.user_id)
            if not auth_user:
                return _integration_error(
                    'invalid_token_subject',
                    'Token subject is not available anymore.',
                    401,
                )

            role = (getattr(auth_user, 'role', '') or '').lower()
            g.integration_auth = {
                'sub': str(token.user_id),
                'user_id': token.user_id,
                'client_id': token.client_id,
                'scopes': sorted(token_scope_set),
                'role': role,
                'worker': getattr(auth_user, 'worker', None),
            }
            g.integration_token = token
            g.integration_current_user = auth_user
            return view(*args, **kwargs)

        return wrapped

    return decorator




















LAUDO_VOLANTE_WIDGET_URI = 'ui://petorlandia/laudo-volante-v2.html'
MAX_MCP_LAUDO_FILE_BYTES = 25 * 1024 * 1024



def _is_local_chatgpt_file_path(value: str) -> bool:
    raw = (value or '').strip()
    if not raw:
        return False
    lowered = raw.lower()
    return (
        lowered.startswith('/mnt/data/')
        or lowered.startswith('/tmp/')
        or lowered.startswith('file:')
        or re.match(r'^[a-z]:\\', raw, flags=re.IGNORECASE) is not None
    )


def _mcp_extract_file_reference(payload: dict, *field_names: str) -> dict | None:
    for field_name in field_names:
        value = payload.get(field_name)
        if isinstance(value, dict) and value.get('download_url') and value.get('file_id'):
            return value
    return None




def _integration_extract_pdf_file_reference(payload: dict) -> dict | None:
    file_ref = _mcp_extract_file_reference(payload, 'arquivo_pdf', 'laudo_arquivo', 'arquivo_laudo', 'attachment_id')
    if file_ref:
        return file_ref

    attachment_id = payload.get('attachment_id')
    download_url = (payload.get('download_url') or payload.get('url') or '').strip()
    if isinstance(attachment_id, str) and attachment_id.strip().lower().startswith('https://') and not download_url:
        download_url = attachment_id.strip()
    if attachment_id and download_url:
        return {
            'file_id': str(attachment_id),
            'download_url': download_url,
            'mime_type': payload.get('mime_type') or 'application/pdf',
            'file_name': payload.get('file_name') or payload.get('filename') or 'laudo.pdf',
            'size': payload.get('size'),
        }
    return None


def _integration_download_and_store_laudo_file(file_ref: dict) -> tuple[str | None, str | None]:
    download_url = (file_ref.get('download_url') or '').strip()
    parsed = urlparse(download_url)
    if parsed.scheme != 'https' or not parsed.netloc:
        raise ValueError('Arquivo do laudo recebeu download_url invalido. Se necessario, cole o texto integral do laudo.')

    original_name = (file_ref.get('file_name') or file_ref.get('filename') or 'laudo-chatgpt.pdf').strip()
    safe_name = secure_filename(original_name) or 'laudo-chatgpt.pdf'
    try:
        response = requests.get(download_url, timeout=20, stream=True)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError('Nao foi possivel baixar o arquivo autorizado pelo ChatGPT. Cole o texto integral do laudo e tente novamente.') from exc

    content = BytesIO()
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_MCP_LAUDO_FILE_BYTES:
            raise ValueError('Arquivo do laudo excede 25 MB. Cole o texto integral do laudo ou envie um arquivo menor.')
        content.write(chunk)
    content.seek(0)

    storage = FileStorage(
        stream=content,
        filename=safe_name,
        content_type=(file_ref.get('mime_type') or 'application/octet-stream'),
    )
    stored_url = upload_to_s3(storage, f"{uuid.uuid4().hex}_{safe_name}", folder='laudos_exames')
    if not stored_url:
        raise ValueError('Nao foi possivel salvar o arquivo do laudo. Cole o texto integral e tente novamente.')
    return stored_url, safe_name


def _ensure_external_onboarding_invite_table() -> bool:
    try:
        ExternalOnboardingInvite.__table__.create(db.engine, checkfirst=True)
        columns = {column['name'] for column in inspect(db.engine).get_columns('external_onboarding_invite')}
        if 'exame_imagem_id' not in columns:
            db.session.execute(text('ALTER TABLE external_onboarding_invite ADD COLUMN exame_imagem_id INTEGER'))
            db.session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Falha ao garantir tabela de convites externos: %s", exc)
        return False


def _integration_add_exam_document(user: User, animal: Animal, laudo_url: str | None, laudo_filename: str | None, exam_name: str):
    if not laudo_url:
        return None
    filename = laudo_filename or os.path.basename(urlparse(laudo_url).path) or 'laudo.pdf'
    existing = AnimalDocumento.query.filter_by(animal_id=animal.id, file_url=laudo_url).first()
    if existing:
        return existing
    documento = AnimalDocumento(
        animal_id=animal.id,
        veterinario_id=user.id,
        filename=filename,
        file_url=laudo_url,
        descricao=f'Laudo anexado ao exame: {exam_name}',
    )
    db.session.add(documento)
    return documento


def _integration_exam_image_status(status: str | None) -> str:
    normalized = (status or '').strip().lower()
    allowed = {'rascunho', 'finalizado', 'liberado_para_clinica', 'liberado_para_tutor'}
    return normalized if normalized in allowed else 'rascunho'


def _integration_ensure_exam_image_table():
    try:
        ExameImagem.__table__.create(db.engine, checkfirst=True)
        ExameImagemPdfAccessLog.__table__.create(db.engine, checkfirst=True)
        return True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Falha ao garantir tabela de exames de imagem: %s", exc)
        return False


def _integration_find_or_create_exame_image_entities(user: User, payload: dict):
    raw_clinic_id = payload.get('clinica_id') or payload.get('clinica_requisitante_id')
    if raw_clinic_id:
        clinic = db.session.get(Clinica, int(raw_clinic_id))
        clinic_created = False
        if not clinic:
            raise ValueError('Clinica requisitante nao encontrada.')
    elif payload.get('nome_clinica'):
        clinic, clinic_created = _integration_find_or_create_external_clinic(user, {
            'nome': payload.get('nome_clinica'),
            'email': payload.get('email_clinica') or payload.get('email'),
            'telefone': payload.get('telefone_clinica') or payload.get('telefone'),
            'cnpj': payload.get('cnpj'),
        })
    else:
        clinic_id = _integration_user_clinic_id(user)
        clinic = db.session.get(Clinica, clinic_id) if clinic_id else None
        clinic_created = False
    if not clinic:
        raise ValueError('Informe clinica_id ou nome_clinica para vincular o exame.')

    raw_tutor_id = payload.get('tutor_id')
    if raw_tutor_id:
        tutor = db.session.get(User, int(raw_tutor_id))
        tutor_created = False
        tutor_provisional_email = False
        if not tutor:
            raise ValueError('Tutor nao encontrado.')
    elif payload.get('nome_tutor'):
        tutor, tutor_created, tutor_provisional_email = _integration_find_or_create_tutor_for_clinic(
            user,
            clinic,
            {
                'nome': payload.get('nome_tutor'),
                'email': payload.get('email_tutor'),
                'telefone': payload.get('telefone_tutor'),
                'cpf': payload.get('cpf_tutor'),
            },
        )
    else:
        raise ValueError('Informe tutor_id ou nome_tutor.')

    raw_animal_id = payload.get('animal_id')
    if raw_animal_id:
        animal = db.session.get(Animal, int(raw_animal_id))
        if not animal:
            raise ValueError('Animal nao encontrado.')
        if animal.user_id != tutor.id:
            raise ValueError('Animal informado nao pertence ao tutor indicado.')
        if not animal.clinica_id:
            animal.clinica_id = clinic.id
            db.session.add(animal)
    elif payload.get('nome_animal'):
        animal, _animal_created = _integration_find_or_create_pet_for_tutor(
            user,
            clinic,
            tutor,
            {
                'nome': payload.get('nome_animal'),
                'especie': payload.get('especie'),
                'raca': payload.get('raca'),
                'sexo': payload.get('sexo'),
                'idade': payload.get('idade'),
            },
        )
    else:
        raise ValueError('Informe animal_id ou nome_animal.')

    return clinic, clinic_created, tutor, tutor_created, tutor_provisional_email, animal


def _integration_create_exame_imagem(user: User, payload: dict):
    if not _integration_ensure_exam_image_table():
        raise ValueError('Nao foi possivel preparar a tabela de exames de imagem.')
    tipo_exame = (payload.get('tipo_exame') or payload.get('tipo') or '').strip()
    if not tipo_exame:
        raise ValueError('Informe tipo_exame.')
    exam_date = _integration_parse_flexible_date(str(payload.get('data_exame') or '')) if payload.get('data_exame') else None
    if not exam_date:
        raise ValueError('Informe data_exame valida em YYYY-MM-DD ou DD/MM/YYYY.')
    clinic, clinic_created, tutor, tutor_created, tutor_provisional_email, animal = _integration_find_or_create_exame_image_entities(user, payload)
    status = 'finalizado' if payload.get('finalizar') is True else _integration_exam_image_status(payload.get('status'))
    exame = ExameImagem(
        animal_id=animal.id,
        tutor_id=tutor.id,
        clinica_requisitante_id=clinic.id,
        profissional_id=user.id,
        tipo_exame=tipo_exame,
        data_exame=exam_date,
        titulo=(payload.get('titulo') or tipo_exame).strip(),
        descricao=(payload.get('descricao') or '').strip() or None,
        impressao_diagnostica=(payload.get('impressao_diagnostica') or '').strip() or None,
        profissional_nome=(payload.get('profissional_nome') or user.name or '').strip() or None,
        profissional_crmv=(payload.get('profissional_crmv') or '').strip() or None,
        status=status,
    )
    db.session.add(exame)
    db.session.flush()
    db.session.commit()
    return {
        'exame': _integration_serialize_exame_imagem(exame, user),
        'clinica': {'id': clinic.id, 'nome': clinic.nome, 'criada_agora': clinic_created},
        'tutor': {'id': tutor.id, 'nome': tutor.name, 'criado_agora': tutor_created, 'email_provisorio': tutor_provisional_email},
        'animal': {'id': animal.id, 'nome': animal.name},
    }


def _integration_store_exame_pdf(user: User, exame: ExameImagem, file_ref: dict):
    if not file_ref:
        if _integration_reconcile_exam_documents(exame.animal, [exame]) or exame.arquivo_pdf_url:
            db.session.add(exame)
            db.session.commit()
            return _integration_serialize_exame_imagem(exame, user)
        raise ValueError('Informe attachment_id/arquivo_pdf como anexo autorizado do ChatGPT com download_url temporaria.')
    mime_type = (file_ref.get('mime_type') or '').strip().lower()
    original_name = (file_ref.get('file_name') or file_ref.get('filename') or 'laudo.pdf').strip()
    if mime_type and mime_type != 'application/pdf':
        raise ValueError('Apenas arquivos PDF sao aceitos neste fluxo.')
    if not original_name.lower().endswith('.pdf'):
        raise ValueError('O arquivo do laudo deve ter extensao .pdf.')
    stored_url, safe_name = _integration_download_and_store_laudo_file(file_ref)
    documento = _integration_add_exam_document(user, exame.animal, stored_url, safe_name, exame.tipo_exame)
    if documento:
        db.session.flush()
        exame.documento_id = documento.id
    exame.arquivo_pdf_url = stored_url
    exame.arquivo_pdf_filename = safe_name
    exame.arquivo_pdf_content_type = 'application/pdf'
    exame.arquivo_pdf_size = file_ref.get('size') if isinstance(file_ref.get('size'), int) else None
    db.session.add(exame)
    db.session.commit()
    return _integration_serialize_exame_imagem(exame, user)


def _integration_user_can_access_exame_imagem(user: User, exame: ExameImagem) -> bool:
    role = (getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        return True
    if has_veterinarian_profile(user) and exame.profissional_id == user.id:
        return True
    if exame.tutor_id == user.id:
        return bool(exame.liberado_para_tutor)
    clinic_id = _integration_user_clinic_id(user)
    if clinic_id and exame.clinica_requisitante_id == clinic_id:
        return bool(exame.liberado_para_clinica)
    return False


def _integration_absolute_public_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme and parsed.netloc:
        return raw_url
    if has_request_context() and raw_url.startswith('/'):
        return f"{request.url_root.rstrip('/')}{raw_url}"
    return raw_url


def _integration_invite_is_active(invite) -> bool:
    expires_at = getattr(invite, 'expires_at', None)
    if not expires_at:
        return True
    now = datetime.now(BR_TZ)
    if getattr(expires_at, 'tzinfo', None) is None:
        now = now.replace(tzinfo=None)
    return expires_at >= now


def _integration_latest_external_invite_for_exame(exame: ExameImagem, invite_type: str):
    if not exame or not has_request_context():
        return None
    filters = [ExternalOnboardingInvite.exame_imagem_id == exame.id]
    if getattr(exame, 'exame_solicitado_id', None):
        filters.append(ExternalOnboardingInvite.exame_id == exame.exame_solicitado_id)
    try:
        invites = (
            ExternalOnboardingInvite.query
            .filter(ExternalOnboardingInvite.invite_type == invite_type, or_(*filters))
            .order_by(ExternalOnboardingInvite.created_at.desc(), ExternalOnboardingInvite.id.desc())
            .limit(10)
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.debug("Convite externo indisponivel para exame %s: %s", getattr(exame, 'id', None), exc)
        return None
    for invite in invites:
        if _integration_invite_is_active(invite):
            return invite
    return None


def _integration_exame_imagem_portal_urls(exame: ExameImagem, user: User | None = None):
    if not exame:
        return {'clinic_portal_url': None, 'tutor_portal_url': None, 'portal_url': None, 'portal_tipo': None}
    role = (getattr(user, 'role', '') or '').lower() if user else ''
    is_internal_operator = user is None or role == 'admin' or has_veterinarian_profile(user)
    clinic_id = _integration_user_clinic_id(user) if user else None
    can_use_clinic_portal = bool(is_internal_operator or (clinic_id and exame.clinica_requisitante_id == clinic_id))
    can_use_tutor_portal = bool(is_internal_operator or (getattr(user, 'id', None) == exame.tutor_id))

    clinic_portal_url = None
    tutor_portal_url = None
    if can_use_clinic_portal and exame.liberado_para_clinica:
        clinic_invite = _integration_latest_external_invite_for_exame(exame, 'clinic')
        clinic_portal_url = _external_onboarding_url(clinic_invite) if clinic_invite else None
    if can_use_tutor_portal and exame.liberado_para_tutor:
        tutor_invite = _integration_latest_external_invite_for_exame(exame, 'tutor')
        tutor_portal_url = _external_onboarding_url(tutor_invite) if tutor_invite else None

    if getattr(user, 'id', None) == exame.tutor_id and tutor_portal_url:
        return {'clinic_portal_url': clinic_portal_url, 'tutor_portal_url': tutor_portal_url, 'portal_url': tutor_portal_url, 'portal_tipo': 'tutor'}
    if clinic_id and exame.clinica_requisitante_id == clinic_id and clinic_portal_url:
        return {'clinic_portal_url': clinic_portal_url, 'tutor_portal_url': tutor_portal_url, 'portal_url': clinic_portal_url, 'portal_tipo': 'clinica'}
    if clinic_portal_url:
        return {'clinic_portal_url': clinic_portal_url, 'tutor_portal_url': tutor_portal_url, 'portal_url': clinic_portal_url, 'portal_tipo': 'clinica'}
    if tutor_portal_url:
        return {'clinic_portal_url': clinic_portal_url, 'tutor_portal_url': tutor_portal_url, 'portal_url': tutor_portal_url, 'portal_tipo': 'tutor'}
    return {'clinic_portal_url': clinic_portal_url, 'tutor_portal_url': tutor_portal_url, 'portal_url': None, 'portal_tipo': None}


def _integration_exame_imagem_access_links(exame: ExameImagem, user: User | None = None, *, include_internal_links: bool = True):
    can_pdf = bool(exame and exame.arquivo_pdf_url and (user is None or _integration_user_can_access_exame_imagem(user, exame)))
    empty = {
        'pdf_disponivel': can_pdf,
        'download_url': None,
        'portal_url': None,
        'portal_tipo': None,
        'clinic_portal_url': None,
        'tutor_portal_url': None,
        'shareable_url': None,
        'shareable_url_type': None,
        'orientacao_compartilhamento': None,
    }
    if include_internal_links:
        empty.update({'api_document_url': None, 'api_document_requires_bearer': False})
    if not can_pdf:
        return empty

    portal_urls = _integration_exame_imagem_portal_urls(exame, user)
    download_url = _integration_absolute_public_url(exame.arquivo_pdf_url)
    portal_url = portal_urls.get('portal_url')
    portal_tipo = portal_urls.get('portal_tipo')
    shareable_url = portal_url or download_url
    shareable_url_type = f"{portal_tipo}_portal" if portal_url and portal_tipo else ('download' if download_url else None)
    links = {
        'pdf_disponivel': True,
        'download_url': download_url,
        **portal_urls,
        'shareable_url': shareable_url,
        'shareable_url_type': shareable_url_type,
        'orientacao_compartilhamento': 'Compartilhe shareable_url ou portal_url com clinica/tutor. Nao compartilhe api_document_url; ele exige bearer token.',
    }
    if include_internal_links:
        api_document_url = url_for('api_integrations_get_clinical_document', exame_id=exame.id, _external=True) if has_request_context() else None
        links.update({'api_document_url': api_document_url, 'api_document_requires_bearer': bool(api_document_url)})
    return links


def _integration_exame_imagem_pdf_summary(exame: ExameImagem, user: User | None = None, *, include_internal_links: bool = True):
    links = _integration_exame_imagem_access_links(exame, user, include_internal_links=include_internal_links)
    if not links.get('pdf_disponivel'):
        return None
    summary = {
        'exame_id': exame.id,
        'documento_id': exame.documento_id,
        'filename': exame.arquivo_pdf_filename,
        'url': links.get('shareable_url'),
        'url_tipo': links.get('shareable_url_type'),
        'download_url': links.get('download_url'),
        'portal_url': links.get('portal_url'),
        'portal_tipo': links.get('portal_tipo'),
        'shareable_url': links.get('shareable_url'),
        'shareable_url_type': links.get('shareable_url_type'),
        'orientacao_compartilhamento': links.get('orientacao_compartilhamento'),
    }
    if include_internal_links:
        summary.update({
            'api_document_url': links.get('api_document_url'),
            'api_document_requires_bearer': links.get('api_document_requires_bearer'),
        })
    return summary


def _integration_exame_imagem_document_payload(exame: ExameImagem, user: User | None = None, *, include_internal_links: bool = True):
    links = _integration_exame_imagem_access_links(exame, user, include_internal_links=include_internal_links)
    payload = {
        'documento': _integration_serialize_exame_imagem(exame, user, include_internal_links=include_internal_links),
        'url_temporaria': exame.arquivo_pdf_url,
        'download_url': links.get('download_url'),
        'portal_url': links.get('portal_url'),
        'portal_tipo': links.get('portal_tipo'),
        'shareable_url': links.get('shareable_url'),
        'shareable_url_type': links.get('shareable_url_type'),
        'orientacao_compartilhamento': links.get('orientacao_compartilhamento'),
    }
    if include_internal_links:
        payload.update({
            'api_document_url': links.get('api_document_url'),
            'api_document_requires_bearer': links.get('api_document_requires_bearer'),
        })
    return payload


def _integration_serialize_exame_imagem(exame: ExameImagem, user: User | None = None, *, include_internal_links: bool = True):
    access_links = _integration_exame_imagem_access_links(exame, user, include_internal_links=include_internal_links)
    payload = {
        'id': exame.id,
        'documento_id': exame.documento_id,
        'animal_id': exame.animal_id,
        'tutor_id': exame.tutor_id,
        'clinica_requisitante_id': exame.clinica_requisitante_id,
        'tipo_registro': 'exame',
        'tipo_exame': exame.tipo_exame,
        'data_exame': exame.data_exame.isoformat() if exame.data_exame else None,
        'titulo': exame.titulo,
        'descricao': exame.descricao,
        'impressao_diagnostica': exame.impressao_diagnostica,
        'profissional_nome': exame.profissional_nome,
        'profissional_crmv': exame.profissional_crmv,
        'status': exame.status,
        'liberado_para_clinica': bool(exame.liberado_para_clinica),
        'liberado_para_tutor': bool(exame.liberado_para_tutor),
        'data_liberacao_clinica': _integration_format_datetime(exame.data_liberacao_clinica),
        'data_liberacao_tutor': _integration_format_datetime(exame.data_liberacao_tutor),
        'arquivo_pdf_filename': exame.arquivo_pdf_filename,
        'pdf_disponivel': access_links.get('pdf_disponivel'),
        'pdf_url': access_links.get('shareable_url'),
        'download_url': access_links.get('download_url'),
        'portal_url': access_links.get('portal_url'),
        'portal_tipo': access_links.get('portal_tipo'),
        'clinic_portal_url': access_links.get('clinic_portal_url'),
        'tutor_portal_url': access_links.get('tutor_portal_url'),
        'shareable_url': access_links.get('shareable_url'),
        'shareable_url_type': access_links.get('shareable_url_type'),
        'orientacao_compartilhamento': access_links.get('orientacao_compartilhamento'),
        'created_at': _integration_format_datetime(exame.created_at),
        'updated_at': _integration_format_datetime(exame.updated_at),
    }
    if include_internal_links:
        payload.update({
            'api_document_url': access_links.get('api_document_url'),
            'api_document_requires_bearer': access_links.get('api_document_requires_bearer'),
        })
    return payload


def _integration_document_matches_exam(documento: AnimalDocumento, exame: ExameImagem) -> bool:
    haystack = _integration_normalize_match_text(
        ' '.join([
            documento.filename or '',
            documento.descricao or '',
        ])
    )
    candidates = [
        exame.tipo_exame,
        exame.titulo,
        getattr(exame.exame_solicitado, 'nome', None),
    ]
    for candidate in candidates:
        normalized = _integration_normalize_match_text(candidate)
        if normalized and normalized in haystack:
            return True
    return False


def _integration_link_document_to_exam(exame: ExameImagem, documento: AnimalDocumento):
    changed = False
    if not exame.documento_id:
        exame.documento_id = documento.id
        changed = True
    if not exame.arquivo_pdf_url:
        exame.arquivo_pdf_url = documento.file_url
        changed = True
    if not exame.arquivo_pdf_filename:
        exame.arquivo_pdf_filename = documento.filename
        changed = True
    if not exame.arquivo_pdf_content_type and (documento.filename or '').lower().endswith('.pdf'):
        exame.arquivo_pdf_content_type = 'application/pdf'
        changed = True
    if changed:
        db.session.add(exame)
    return changed


def _integration_reconcile_exam_documents(animal: Animal, exames: list[ExameImagem]) -> bool:
    if not animal or not exames:
        return False
    unlinked = [exame for exame in exames if not exame.documento_id or not exame.arquivo_pdf_url]
    if not unlinked:
        return False

    docs = (
        AnimalDocumento.query
        .filter_by(animal_id=animal.id)
        .order_by(AnimalDocumento.uploaded_at.desc(), AnimalDocumento.id.desc())
        .all()
    )
    if not docs:
        return False

    changed = False
    for exame in unlinked:
        document = None
        if exame.documento_id:
            document = next((doc for doc in docs if doc.id == exame.documento_id), None)
        if not document:
            document = next((doc for doc in docs if _integration_document_matches_exam(doc, exame)), None)
        if not document and len(docs) == 1 and len(exames) == 1:
            document = docs[0]
        if document:
            changed = _integration_link_document_to_exam(exame, document) or changed
    if changed:
        db.session.flush()
    return changed


def _integration_find_exame_by_documento(documento: AnimalDocumento, user: User):
    exame = ExameImagem.query.filter_by(documento_id=documento.id).first()
    if exame:
        return exame
    exames = _integration_list_exame_imagem_history(user, documento.animal)
    _integration_reconcile_exam_documents(documento.animal, exames)
    return ExameImagem.query.filter_by(documento_id=documento.id).first()


def _integration_release_exame_imagem(user: User, payload: dict, *, target: str):
    if not _integration_ensure_exam_image_table():
        raise ValueError('Nao foi possivel preparar a tabela de exames de imagem.')
    exame = db.session.get(ExameImagem, int(payload.get('exame_id') or 0))
    if not exame:
        raise ValueError('Exame de imagem nao encontrado.')
    clinic_id = _integration_user_clinic_id(user)
    if target == 'clinica':
        if not (getattr(user, 'role', '') == 'admin' or exame.profissional_id == user.id):
            raise PermissionError('Somente o ultrassonografista criador ou admin pode liberar para a clinica.')
        if payload.get('clinica_id') and int(payload.get('clinica_id')) != exame.clinica_requisitante_id:
            raise ValueError('clinica_id nao corresponde a clinica requisitante do exame.')
        exame.liberado_para_clinica = True
        exame.data_liberacao_clinica = datetime.now(BR_TZ)
        exame.status = 'liberado_para_clinica'
    else:
        allowed_clinic = clinic_id and clinic_id == exame.clinica_requisitante_id and exame.liberado_para_clinica
        if not (getattr(user, 'role', '') == 'admin' or allowed_clinic or exame.profissional_id == user.id):
            raise PermissionError('Somente a clinica vinculada, o ultrassonografista criador ou admin pode liberar para o tutor.')
        if payload.get('tutor_id') and int(payload.get('tutor_id')) != exame.tutor_id:
            raise ValueError('tutor_id nao corresponde ao tutor do exame.')
        exame.liberado_para_tutor = True
        exame.data_liberacao_tutor = datetime.now(BR_TZ)
        exame.status = 'liberado_para_tutor'
    exame.usuario_que_liberou_id = user.id
    db.session.add(exame)
    db.session.commit()
    return _integration_serialize_exame_imagem(exame, user)


def _integration_list_exame_imagem_history(user: User, animal: Animal):
    if not _integration_ensure_exam_image_table():
        return []
    query = ExameImagem.query.filter_by(animal_id=animal.id)
    role = (getattr(user, 'role', '') or '').lower()
    clinic_id = _integration_user_clinic_id(user)
    if role == 'admin':
        pass
    elif has_veterinarian_profile(user):
        query = query.filter(ExameImagem.profissional_id == user.id)
    elif animal.user_id == user.id:
        query = query.filter(ExameImagem.tutor_id == user.id, ExameImagem.liberado_para_tutor.is_(True))
    elif clinic_id:
        query = query.filter(ExameImagem.clinica_requisitante_id == clinic_id, ExameImagem.liberado_para_clinica.is_(True))
    else:
        query = query.filter(db.text('0=1'))
    return query.order_by(ExameImagem.data_exame.desc().nullslast(), ExameImagem.created_at.desc()).all()


def _integration_normalize_match_text(value) -> str:
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', text.lower()).strip()


def _integration_find_existing_exam_for_laudo(payload: dict, animal: Animal | None = None):
    exam_data = payload.get('exame') or {}
    raw_exam_id = payload.get('exame_id') or exam_data.get('id') or exam_data.get('exame_id')
    if raw_exam_id:
        try:
            exam = db.session.get(ExameSolicitado, int(raw_exam_id))
        except (TypeError, ValueError):
            exam = None
        if exam:
            return exam

    raw_bloco_id = payload.get('bloco_id') or exam_data.get('bloco_id')
    if raw_bloco_id:
        try:
            bloco = db.session.get(BlocoExames, int(raw_bloco_id))
        except (TypeError, ValueError):
            bloco = None
        if bloco and (animal is None or bloco.animal_id == animal.id):
            exam_name = (exam_data.get('nome') or exam_data.get('tipo') or '').strip()
            if exam_name:
                normalized_name = _integration_normalize_match_text(exam_name)
                for exam in bloco.exames or []:
                    if _integration_normalize_match_text(exam.nome) == normalized_name:
                        return exam
            return (bloco.exames or [None])[0]
    exam_name = (exam_data.get('nome') or exam_data.get('tipo') or '').strip()
    if animal and exam_name:
        normalized_name = _integration_normalize_match_text(exam_name)
        exams = (
            ExameSolicitado.query
            .join(BlocoExames, ExameSolicitado.bloco_id == BlocoExames.id)
            .filter(BlocoExames.animal_id == animal.id)
            .order_by(ExameSolicitado.performed_at.desc().nullslast(), ExameSolicitado.id.desc())
            .limit(20)
            .all()
        )
        for exam in exams:
            if _integration_normalize_match_text(exam.nome) == normalized_name:
                return exam
    return None


def _create_external_onboarding_invite(invite_type: str, user: User, *, clinic=None, tutor=None, animal=None, exam=None, exam_image=None, message: str | None = None):
    if not _ensure_external_onboarding_invite_table():
        return None
    if isinstance(exam, ExameImagem) and exam_image is None:
        exam_image = exam
        exam = exam.exame_solicitado
    invite = ExternalOnboardingInvite(
        token=secrets.token_urlsafe(24),
        invite_type=invite_type,
        clinica_id=getattr(clinic, 'id', None),
        tutor_id=getattr(tutor, 'id', None),
        animal_id=getattr(animal, 'id', None),
        exame_id=getattr(exam, 'id', None),
        exame_imagem_id=getattr(exam_image, 'id', None),
        created_by_id=getattr(user, 'id', None),
        referrer_vet_id=getattr(getattr(user, 'veterinario', None), 'id', None),
        message=message,
        expires_at=datetime.now(BR_TZ) + timedelta(days=30),
    )
    db.session.add(invite)
    return invite


def _external_onboarding_url(invite):
    if not invite or not has_request_context():
        return None
    if getattr(invite, 'invite_type', None) == 'clinic':
        return url_for('external_clinic_first_access_invite', token=invite.token, _external=True)
    return url_for('external_onboarding_invite', token=invite.token, _external=True)


def _first_access_invite_url(invite):
    if not invite or not has_request_context():
        return None
    if getattr(invite, 'invite_type', None) == 'clinic':
        return url_for('external_clinic_first_access_invite', token=invite.token, _external=True)
    return url_for('first_access', token=invite.token, _external=True)


def _external_invite_exame_imagem(invite):
    if not invite:
        return None
    if getattr(invite, 'exame_imagem_id', None):
        return db.session.get(ExameImagem, invite.exame_imagem_id)
    if not getattr(invite, 'exame_id', None):
        return None
    return ExameImagem.query.filter_by(exame_solicitado_id=invite.exame_id).first()


def _external_invite_document_url(invite, exame_imagem=None):
    exame_imagem = exame_imagem or _external_invite_exame_imagem(invite)
    if exame_imagem and exame_imagem.arquivo_pdf_url:
        return exame_imagem.arquivo_pdf_url
    if invite and invite.exame and invite.exame.laudo_url:
        return invite.exame.laudo_url
    return None


def _invite_missing_fields(invite, exame_imagem=None):
    missing = []
    effective_exame_id = getattr(exame_imagem, 'id', None) or getattr(invite, 'exame_id', None)
    if not getattr(invite, 'tutor_id', None):
        missing.append('tutor_id')
    if not getattr(invite, 'animal_id', None):
        missing.append('animal_id')
    if not effective_exame_id:
        missing.append('exame_id')
    if invite and invite.invite_type == 'clinic' and not getattr(invite, 'clinica_id', None):
        missing.append('clinica_id')
    if not _external_invite_document_url(invite, exame_imagem):
        missing.append('laudo_url')
    return missing


def _invite_payload(invite, *, pricing=None):
    exame_imagem = _external_invite_exame_imagem(invite)
    if exame_imagem:
        _integration_reconcile_exam_documents(exame_imagem.animal, [exame_imagem])
    document_url = _external_invite_document_url(invite, exame_imagem)
    missing = _invite_missing_fields(invite, exame_imagem)
    effective_exame_id = getattr(exame_imagem, 'id', None) or getattr(invite, 'exame_id', None)
    documento_id = getattr(exame_imagem, 'documento_id', None)
    base = {
        'url': _external_onboarding_url(invite),
        'expires_at': _integration_format_datetime(invite.expires_at) if invite else None,
        'dados_faltantes': missing,
        'documento_id': documento_id,
    }
    if invite and invite.invite_type == 'clinic':
        pricing = pricing or _public_pricing_config()
        payload = {
            **base,
            'tipo_convite': 'trial_clinica_exame',
            'trial_dias': pricing.get('trial_dias_clinica'),
            'pricing_source': pricing.get('fonte'),
            'permite_visualizar_exame': True,
            'clinica_id': invite.clinica_id,
            'exame_id': effective_exame_id,
        }
        if pricing.get('exibir_preco_no_convite_clinica') and pricing.get('preco_formatado'):
            payload['preco_formatado'] = pricing.get('preco_formatado')
        return payload
    return {
        **base,
        'tipo_convite': 'acesso_tutor_laudo',
        'tutor_paga': False,
        'permite_visualizar_laudo': True,
        'tutor_id': getattr(invite, 'tutor_id', None),
        'animal_id': getattr(invite, 'animal_id', None),
        'exame_id': effective_exame_id,
    }


def _web_exame_imagem_operator_required():
    role = (getattr(current_user, 'role', '') or '').lower()
    if role == 'admin' or has_veterinarian_profile(current_user):
        return None
    abort(403)


def _web_user_can_manage_exame_imagem(user: User, exame: ExameImagem) -> bool:
    role = (getattr(user, 'role', '') or '').lower()
    return bool(role == 'admin' or getattr(exame, 'profissional_id', None) == getattr(user, 'id', None))


def _integration_store_exame_pdf_upload(user: User, exame: ExameImagem, file_storage):
    if not file_storage or not getattr(file_storage, 'filename', ''):
        return _integration_serialize_exame_imagem(exame, user)

    original_name = secure_filename(file_storage.filename or 'laudo.pdf') or 'laudo.pdf'
    if not original_name.lower().endswith('.pdf'):
        raise ValueError('O arquivo do laudo deve ser um PDF.')

    file_size = None
    stream = getattr(file_storage, 'stream', None)
    if stream:
        try:
            position = stream.tell()
            stream.seek(0, os.SEEK_END)
            file_size = stream.tell()
            stream.seek(position)
        except (OSError, ValueError):
            file_size = None

    stored_url = upload_to_s3(file_storage, f"{uuid.uuid4().hex}_{original_name}", folder='laudos_exames')
    if not stored_url:
        raise ValueError('Nao foi possivel salvar o PDF do laudo.')

    documento = _integration_add_exam_document(user, exame.animal, stored_url, original_name, exame.tipo_exame)
    if documento:
        db.session.flush()
        exame.documento_id = documento.id
    exame.arquivo_pdf_url = stored_url
    exame.arquivo_pdf_filename = original_name
    exame.arquivo_pdf_content_type = 'application/pdf'
    exame.arquivo_pdf_size = file_size
    exame.status = 'finalizado'
    db.session.add(exame)
    db.session.commit()
    return _integration_serialize_exame_imagem(exame, user)


def _web_exame_imagem_ensure_invite(user: User, exame: ExameImagem, invite_type: str, form=None):
    invite = _integration_latest_external_invite_for_exame(exame, invite_type)
    if invite:
        return invite

    form = form or {}
    if invite_type == 'clinic':
        clinic = exame.clinica_requisitante
        _integration_ensure_clinic_admin_user(
            clinic,
            email=form.get('email_clinica'),
            phone=form.get('telefone_clinica'),
            name=form.get('nome_responsavel_clinica') or getattr(clinic, 'nome', None),
        )
        message = (
            f'Laudo do paciente {getattr(exame.animal, "name", "paciente")} '
            f'disponivel para {getattr(clinic, "nome", "a clinica requisitante")}.'
        )
        invite = _create_external_onboarding_invite(
            'clinic',
            user,
            clinic=clinic,
            tutor=exame.tutor,
            animal=exame.animal,
            exam=exame.exame_solicitado,
            exam_image=exame,
            message=message,
        )
    else:
        clinic = exame.clinica_requisitante
        message = (
            f'Seu exame foi disponibilizado pela equipe da '
            f'{getattr(clinic, "nome", "clinica requisitante")}.'
        )
        invite = _create_external_onboarding_invite(
            'tutor',
            user,
            clinic=clinic,
            tutor=exame.tutor,
            animal=exame.animal,
            exam=exame.exame_solicitado,
            exam_image=exame,
            message=message,
        )

    db.session.flush()
    return invite


def _web_exame_imagem_notify(exame: ExameImagem, invite, target: str):
    url = _external_onboarding_url(invite)
    if not url:
        return
    animal_name = getattr(getattr(exame, 'animal', None), 'name', None) or 'paciente'
    clinic_name = getattr(getattr(exame, 'clinica_requisitante', None), 'nome', None) or 'clinica requisitante'
    if target == 'clinic':
        owner_id = getattr(getattr(exame, 'clinica_requisitante', None), 'owner_id', None)
        if owner_id:
            db.session.add(Notification(
                user_id=owner_id,
                message=f'Laudo de {animal_name} disponivel para {clinic_name}.',
                channel='app',
                kind='exam_report',
            ))
    elif getattr(exame, 'tutor_id', None):
        db.session.add(Notification(
            user_id=exame.tutor_id,
            message=f'Seu exame foi disponibilizado pela equipe da {clinic_name}.',
            channel='app',
            kind='exam_report',
        ))


def _web_whatsapp_url(phone: str | None, message: str) -> str | None:
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if not digits:
        return None
    if not digits.startswith('55'):
        digits = f'55{digits}'
    return f'https://wa.me/{digits}?text={quote_plus(message)}'


def _web_exame_imagem_card(exame: ExameImagem, highlight_id: int | None = None):
    clinic_invite = _integration_latest_external_invite_for_exame(exame, 'clinic')
    tutor_invite = _integration_latest_external_invite_for_exame(exame, 'tutor')
    clinic_url = _external_onboarding_url(clinic_invite) if clinic_invite else None
    tutor_url = _external_onboarding_url(tutor_invite) if tutor_invite else None
    pdf_url = _integration_absolute_public_url(exame.arquivo_pdf_url)
    animal_name = getattr(getattr(exame, 'animal', None), 'name', None) or 'Paciente'
    clinic_name = getattr(getattr(exame, 'clinica_requisitante', None), 'nome', None) or 'Clinica requisitante'
    clinic_message = (
        f'Laudo de {animal_name} disponivel para {clinic_name}. '
        f'Acesse: {clinic_url}'
    ) if clinic_url else ''
    tutor_message = (
        f'Seu exame foi disponibilizado pela equipe da {clinic_name}. '
        f'Acesse: {tutor_url}'
    ) if tutor_url else ''
    return {
        'exame': exame,
        'highlight': bool(highlight_id and exame.id == highlight_id),
        'pdf_url': pdf_url,
        'clinic_url': clinic_url,
        'tutor_url': tutor_url,
        'clinic_whatsapp_url': _web_whatsapp_url(
            getattr(getattr(exame, 'clinica_requisitante', None), 'telefone', None),
            clinic_message,
        ),
        'tutor_whatsapp_url': _web_whatsapp_url(
            getattr(getattr(exame, 'tutor', None), 'phone', None),
            tutor_message,
        ),
    }


def _web_exame_imagem_scoped_query():
    query = ExameImagem.query.options(
        joinedload(ExameImagem.animal),
        joinedload(ExameImagem.tutor),
        joinedload(ExameImagem.clinica_requisitante),
    )
    if (getattr(current_user, 'role', '') or '').lower() != 'admin':
        query = query.filter(ExameImagem.profissional_id == current_user.id)
    return query


def _web_exame_imagem_filter_state():
    data_inicio_raw = (request.args.get('inicio') or '').strip()
    data_fim_raw = (request.args.get('fim') or '').strip()
    data_inicio = _integration_parse_flexible_date(data_inicio_raw)
    data_fim = _integration_parse_flexible_date(data_fim_raw)
    return {
        'clinica_id': request.args.get('clinica_id', type=int),
        'tutor_id': request.args.get('tutor_id', type=int),
        'animal_id': request.args.get('animal_id', type=int),
        'inicio': data_inicio.isoformat() if data_inicio else data_inicio_raw,
        'fim': data_fim.isoformat() if data_fim else data_fim_raw,
        'inicio_data': data_inicio,
        'fim_data': data_fim,
    }


def _web_exame_imagem_apply_filters(query, filters: dict):
    if filters.get('clinica_id'):
        query = query.filter(ExameImagem.clinica_requisitante_id == filters['clinica_id'])
    if filters.get('tutor_id'):
        query = query.filter(ExameImagem.tutor_id == filters['tutor_id'])
    if filters.get('animal_id'):
        query = query.filter(ExameImagem.animal_id == filters['animal_id'])
    if filters.get('inicio_data'):
        query = query.filter(ExameImagem.data_exame >= filters['inicio_data'])
    if filters.get('fim_data'):
        query = query.filter(ExameImagem.data_exame <= filters['fim_data'])
    return query


def _web_exame_imagem_unique_options(exames: list[ExameImagem], relation_name: str, label_attr: str):
    options = {}
    for exame in exames:
        entity = getattr(exame, relation_name, None)
        entity_id = getattr(entity, 'id', None)
        if not entity or not entity_id or entity_id in options:
            continue
        label = getattr(entity, label_attr, None) or f'#{entity_id}'
        options[entity_id] = {'id': entity_id, 'label': label}
    return sorted(options.values(), key=lambda item: _integration_normalize_match_text(item['label']))


def _web_exame_imagem_history_context(highlight_id: int | None = None):
    scoped_query = _web_exame_imagem_scoped_query()
    filters = _web_exame_imagem_filter_state()
    all_exames = scoped_query.order_by(ExameImagem.created_at.desc(), ExameImagem.id.desc()).all()
    filtered_query = _web_exame_imagem_apply_filters(_web_exame_imagem_scoped_query(), filters)
    filtered_total = filtered_query.order_by(None).count()
    pdf_total = filtered_query.filter(ExameImagem.arquivo_pdf_url.isnot(None)).order_by(None).count()
    filtered_exames = (
        filtered_query
        .order_by(ExameImagem.data_exame.desc().nullslast(), ExameImagem.created_at.desc(), ExameImagem.id.desc())
        .limit(200)
        .all()
    )

    return {
        'filters': filters,
        'filter_options': {
            'clinicas': _web_exame_imagem_unique_options(all_exames, 'clinica_requisitante', 'nome'),
            'tutores': _web_exame_imagem_unique_options(all_exames, 'tutor', 'name'),
            'animais': _web_exame_imagem_unique_options(all_exames, 'animal', 'name'),
        },
        'stats': {
            'total': len(all_exames),
            'filtered_total': filtered_total,
            'pdf_total': pdf_total,
            'limit': 200,
        },
        'cards': [_web_exame_imagem_card(exame, highlight_id) for exame in filtered_exames],
    }

def _web_render_exames_imagem(highlight_id: int | None = None):
    vet_profile = getattr(current_user, 'veterinario', None)
    history = _web_exame_imagem_history_context(highlight_id)
    return render_template(
        'exames_imagem/painel.html',
        exam_cards=history['cards'],
        history_filters=history['filters'],
        history_filter_options=history['filter_options'],
        history_stats=history['stats'],
        today=date.today().isoformat(),
        profissional_nome=getattr(current_user, 'name', '') or '',
        profissional_crmv=getattr(vet_profile, 'crmv', '') or '',
        highlight_id=highlight_id,
    )

































def _build_animals_pmo_dates(animals):
    animal_ids = [animal.id for animal in animals if animal.id]
    if not animal_ids:
        return {}

    pmo_animals = (
        PmoVaccinationAnimal.query
        .options(
            joinedload(PmoVaccinationAnimal.visit),
            joinedload(PmoVaccinationAnimal.vaccine),
        )
        .filter(PmoVaccinationAnimal.animal_id.in_(animal_ids))
        .all()
    )

    pmo_dates = {}
    for pmo_animal in pmo_animals:
        visit = pmo_animal.visit
        if not visit:
            continue

        info = pmo_dates.setdefault(
            pmo_animal.animal_id,
            {
                'requested_date': None,
                'vaccinated_date': None,
            },
        )

        requested_date = getattr(visit, 'requested_date', None)
        if requested_date and (
            info['requested_date'] is None or requested_date < info['requested_date']
        ):
            info['requested_date'] = requested_date

        vaccinated_date = None
        if pmo_animal.vaccine and pmo_animal.vaccine.aplicada_em:
            applied_at = pmo_animal.vaccine.aplicada_em
            vaccinated_date = applied_at.date() if hasattr(applied_at, 'date') else applied_at
        elif pmo_animal.status == 'vacinado':
            vaccinated_date = visit.vaccine_date

        if vaccinated_date and (
            info['vaccinated_date'] is None or vaccinated_date > info['vaccinated_date']
        ):
            info['vaccinated_date'] = vaccinated_date

    return pmo_dates




















































# Função local de formatação, caso ainda não tenha no projeto
def formatar_telefone(telefone: str) -> str:
    telefone = ''.join(filter(str.isdigit, telefone))  # Remove qualquer coisa que não seja número
    if telefone.startswith('55'):
        return f"+{telefone}"
    elif telefone.startswith('0'):
        return f"+55{telefone[1:]}"
    elif len(telefone) == 11:
        return f"+55{telefone}"
    else:
        return f"+55{telefone}"


APPOINTMENT_STATUS_LABELS = {
    'scheduled': 'A fazer',
    'accepted': 'Aceita',
    'completed': 'Realizada',
    'canceled': 'Cancelada',
}

APPOINTMENT_KIND_LABELS = {
    'consulta': 'Consulta',
    'retorno': 'Retorno',
    'exame': 'Exame',
    'banho_tosa': 'Banho e Tosa',
    'vacina': 'Vacina',
    'general': 'Geral',
}

ORCAMENTO_STATUS_LABELS = {
    'draft': 'Rascunho',
    'sent': 'Enviado',
    'approved': 'Aprovado',
    'rejected': 'Rejeitado',
    'canceled': 'Cancelado',
}

ORCAMENTO_STATUS_STYLES = {
    'draft': 'secondary',
    'sent': 'info',
    'approved': 'success',
    'rejected': 'danger',
    'canceled': 'dark',
}

ORCAMENTO_PAYMENT_STATUS_LABELS = {
    'not_generated': 'Sem link',
    'pending': 'Pendente',
    'paid': 'Pago',
    'failed': 'Falhou',
}

ORCAMENTO_PAYMENT_STATUS_STYLES = {
    'not_generated': 'secondary',
    'pending': 'warning',
    'paid': 'success',
    'failed': 'danger',
}

ACCOUNTING_BUDGET_STATUS_SUMMARY = {
    'sem_link': {'label': 'Sem link'},
    'pendente': {'label': 'Pendentes'},
    'pago': {'label': 'Pagos'},
    'cancelado': {'label': 'Cancelados'},
}

PLANTONISTA_STATUS_STYLES = {
    'agendado': 'badge bg-info text-dark',
    'confirmado': 'badge bg-primary',
    'realizado': 'badge bg-success',
    'cancelado': 'badge bg-secondary',
}


def registrar_feedback_solicitacao(user, texto, kind, *, enviar_email=True):
    """Registra o feedback de uma solicitação para o usuário.

    Adiciona um ``Notification`` (fica no histórico do usuário e visível no
    admin) e, quando possível, envia o mesmo texto por e-mail. Nunca levanta
    exceção — o fluxo da solicitação não pode quebrar por falha de aviso.
    A sessão NÃO é commitada aqui; o chamador controla a transação.
    """
    from models import Notification

    try:
        db.session.add(Notification(
            user_id=user.id, message=texto, channel='sistema', kind=kind,
        ))
    except Exception:
        current_app.logger.exception('Falha ao registrar Notification (%s)', kind)

    if enviar_email and getattr(user, 'email', None) and app.config.get('MAIL_DEFAULT_SENDER'):
        try:
            mail.send(MailMessage(
                subject='PetOrlândia — confirmação da sua solicitação',
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[user.email],
                body=texto,
            ))
        except Exception:
            current_app.logger.exception('Falha ao enviar e-mail de confirmação (%s)', kind)


def avisar_admin_nova_solicitacao(assunto, corpo):
    """Envia e-mail ao admin (ADMIN_NOTIFY_EMAIL) sobre uma nova solicitação.

    Nunca levanta exceção; sem ADMIN_NOTIFY_EMAIL configurado, não faz nada.
    """
    destino = app.config.get('ADMIN_NOTIFY_EMAIL')
    if not destino or not app.config.get('MAIL_DEFAULT_SENDER'):
        return
    try:
        mail.send(MailMessage(
            subject=f'[PetOrlândia] {assunto}',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[destino],
            body=corpo,
        ))
    except Exception:
        current_app.logger.exception('Falha ao avisar admin sobre solicitação')


def enviar_mensagem_whatsapp(texto: str, numero: str) -> None:
    """Envia uma mensagem de WhatsApp usando a API do Twilio."""

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM")

    if not all([account_sid, auth_token, from_number]):
        raise RuntimeError("Credenciais do Twilio não configuradas")

    client_cls = Client
    if client_cls is None:
        from twilio.rest import Client as client_cls
    client = client_cls(account_sid, auth_token)
    client.messages.create(body=texto, from_=from_number, to=numero)


def verificar_datas_proximas() -> None:
    from models import Appointment, ExameSolicitado, Vacina, Notification

    with app.app_context():
        agora = datetime.now(BR_TZ)
        limite = agora + timedelta(days=1)

        consultas = (
            Appointment.query
            .filter(Appointment.scheduled_at >= agora, Appointment.scheduled_at <= limite)
            .all()
        )
        for appt in consultas:
            tutor = appt.tutor
            texto = (
                f"Lembrete: consulta de {appt.animal.name} em "
                f"{appt.scheduled_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')}"
            )
            from services.push import push_to_user
            push_to_user(tutor.id, 'PetOrlândia 🐾', texto, url='/', tag='lembrete')
            if tutor.email:
                msg = MailMessage(
                    subject="Lembrete de consulta - PetOrlândia",
                    sender=app.config['MAIL_DEFAULT_SENDER'],
                    recipients=[tutor.email],
                    body=texto,
                )
                mail.send(msg)
                db.session.add(Notification(user_id=tutor.id, message=texto, channel='email', kind='appointment'))
            if tutor.phone:
                numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
                try:
                    enviar_mensagem_whatsapp(texto, numero)
                    db.session.add(Notification(user_id=tutor.id, message=texto, channel='whatsapp', kind='appointment'))
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        exames = (
            ExameSolicitado.query
            .filter(
                ExameSolicitado.status == 'pendente',
                ExameSolicitado.performed_at.isnot(None),
                ExameSolicitado.performed_at >= agora,
                ExameSolicitado.performed_at <= limite,
            )
            .all()
        )
        for ex in exames:
            tutor = ex.bloco.animal.owner
            texto = (
                f"Lembrete: exame '{ex.nome}' de {ex.bloco.animal.name} em "
                f"{ex.performed_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')}"
            )
            from services.push import push_to_user
            push_to_user(tutor.id, 'PetOrlândia 🐾', texto, url='/', tag='lembrete')
            if tutor.email:
                msg = MailMessage(
                    subject="Lembrete de exame - PetOrlândia",
                    sender=app.config['MAIL_DEFAULT_SENDER'],
                    recipients=[tutor.email],
                    body=texto,
                )
                mail.send(msg)
                db.session.add(Notification(user_id=tutor.id, message=texto, channel='email', kind='exam'))
            if tutor.phone:
                numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
                try:
                    enviar_mensagem_whatsapp(texto, numero)
                    db.session.add(Notification(user_id=tutor.id, message=texto, channel='whatsapp', kind='exam'))
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        vacinas = (
            Vacina.query
            .filter(Vacina.aplicada_em >= agora.date(), Vacina.aplicada_em <= limite.date())
            .all()
        )
        for vac in vacinas:
            tutor = vac.animal.owner
            texto = (
                f"Lembrete: vacina '{vac.nome}' de {vac.animal.name} em "
                f"{vac.aplicada_em.strftime('%d/%m/%Y')}"
            )
            from services.push import push_to_user
            push_to_user(tutor.id, 'PetOrlândia 🐾', texto, url='/', tag='lembrete')
            if tutor.email:
                msg = MailMessage(
                    subject="Lembrete de vacina - PetOrlândia",
                    sender=app.config['MAIL_DEFAULT_SENDER'],
                    recipients=[tutor.email],
                    body=texto,
                )
                mail.send(msg)
                db.session.add(Notification(user_id=tutor.id, message=texto, channel='email', kind='vaccine'))
            if tutor.phone:
                numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
                try:
                    enviar_mensagem_whatsapp(texto, numero)
                    db.session.add(Notification(user_id=tutor.id, message=texto, channel='whatsapp', kind='vaccine'))
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        db.session.commit()


def _notification_base_url() -> str:
    """Base para links em e-mails enviados fora de request context (jobs)."""
    return os.environ.get('FRONTEND_URL', 'https://www.petorlandia.com.br').rstrip('/')


def _concluir_entrega_efeitos(delivery) -> None:
    """Efeitos da conclusão de uma entrega: congela o frete a repassar e
    pede ao tutor a confirmação de recebimento (libera repasses)."""
    from services.notifications import notify_user
    from services.repasses import congelar_frete

    congelar_frete(delivery)
    order = delivery.order
    tutor = getattr(order, 'user', None)
    if not tutor:
        return
    base_url = _notification_base_url()
    notify_user(
        tutor,
        'Seu pedido chegou? Confirme o recebimento — PetOrlândia',
        (
            f'Olá {tutor.name}! A entrega do pedido #{order.id} foi concluída.\n\n'
            'Se está tudo certo, confirme o recebimento em Minhas atividades → Compras:\n'
            f'{base_url}/minhas_compras\n\n'
            'A confirmação garante a segurança da sua compra e libera o repasse '
            'aos parceiros da entrega.'
        ),
        kind='order_receipt',
    )


def enviar_lembretes_recebimento() -> None:
    """Job diário: lembra tutores de confirmar pedidos pagos ainda não confirmados.

    Regras anti-spam: espera 2 dias após o pagamento (tempo de chegar),
    relembra no máximo a cada 3 dias e ignora pedidos com mais de 60 dias.
    """
    from services.notifications import notify_user

    with app.app_context():
        agora = now_in_brazil()
        espera_entrega = agora - timedelta(days=2)
        corte_antigo = agora - timedelta(days=60)
        relembrar_apos = agora - timedelta(days=3)
        pedidos = (
            Order.query
            .join(Payment, Payment.order_id == Order.id)
            .filter(
                Payment.status == PaymentStatus.COMPLETED,
                Order.received_at.is_(None),
                Payment.created_at <= espera_entrega,
                Payment.created_at >= corte_antigo,
                or_(
                    Order.receipt_reminder_at.is_(None),
                    Order.receipt_reminder_at <= relembrar_apos,
                ),
            )
            .all()
        )
        base_url = _notification_base_url()
        for pedido in pedidos:
            tutor = pedido.user
            if not tutor:
                continue
            notify_user(
                tutor,
                'Recebeu seu pedido? Confirme para nós — PetOrlândia',
                (
                    f'Olá {tutor.name}! Você já recebeu o pedido #{pedido.id}?\n\n'
                    'Confirme o recebimento em Minhas atividades → Compras:\n'
                    f'{base_url}/minhas_compras\n\n'
                    'Se ainda não chegou ou houve algum problema, responda este '
                    'e-mail para ajudarmos.'
                ),
                kind='order_receipt',
            )
            pedido.receipt_reminder_at = agora
        db.session.commit()


def enviar_lembretes_tratamento() -> None:
    """Job diário: resumo das doses de hoje/atrasadas dos tratamentos ativos.

    Um e-mail por acompanhamento ativo com pendências no dia — traz o tutor de
    volta à página do tratamento para marcar as doses e enviar a foto diária.
    """
    from services.notifications import notify_user

    with app.app_context():
        agora = now_in_brazil()
        hoje = agora.date()
        base_url = _notification_base_url()
        acompanhamentos = (
            TratamentoAcompanhamento.query
            .filter(TratamentoAcompanhamento.status == 'ativo')
            .all()
        )
        for acompanhamento in acompanhamentos:
            animal = acompanhamento.animal
            tutor = animal.owner if animal else None
            if not tutor:
                continue
            doses_hoje = 0
            doses_atrasadas = 0
            for item in acompanhamento.itens:
                for registro in item.registros:
                    if registro.status != 'pendente' or registro.prevista_para is None:
                        continue
                    prevista = coerce_to_brazil_tz(registro.prevista_para)
                    if prevista.date() < hoje:
                        doses_atrasadas += 1
                    elif prevista.date() == hoje:
                        doses_hoje += 1
            if not doses_hoje and not doses_atrasadas:
                continue
            partes = []
            if doses_hoje:
                partes.append(f'{doses_hoje} dose(s) para dar hoje')
            if doses_atrasadas:
                partes.append(f'{doses_atrasadas} dose(s) atrasada(s)')
            resumo = ' e '.join(partes)
            notify_user(
                tutor,
                f'Tratamento de {animal.name}: {resumo} — PetOrlândia',
                (
                    f'Olá {tutor.name}! O tratamento de {animal.name} tem {resumo}.\n\n'
                    'Marque as doses dadas e aproveite para enviar a foto de hoje '
                    'da evolução:\n'
                    f'{base_url}/tratamento/{acompanhamento.id}\n\n'
                    'Registrar direitinho ajuda o veterinário a avaliar o '
                    'tratamento e ajustar o que for preciso.'
                ),
                kind='treatment_reminder',
            )
        db.session.commit()


def _run_financial_snapshot_job() -> None:
    """Daily hook executed by APScheduler to refresh monthly snapshots."""

    with app.app_context():
        update_financial_snapshots_daily()


def _run_mercadopago_oauth_renewal_job() -> None:
    """Daily hook executed by APScheduler to renew seller OAuth tokens."""

    with app.app_context():
        result = renew_due_store_accounts(db, StorePaymentAccount)
        if result.checked:
            current_app.logger.info(
                "Mercado Pago OAuth renewal checked=%s renewed=%s failed=%s",
                result.checked,
                result.renewed,
                result.failed,
            )


if not app.config.get("TESTING"):
    scheduler = BackgroundScheduler(timezone=str(BR_TZ))
    scheduler.add_job(verificar_datas_proximas, 'cron', hour=8)
    scheduler.add_job(enviar_lembretes_tratamento, 'cron', hour=9)
    scheduler.add_job(enviar_lembretes_recebimento, 'cron', hour=10)
    scheduler.add_job(_run_financial_snapshot_job, 'cron', hour=2, minute=30)
    scheduler.add_job(_run_mercadopago_oauth_renewal_job, 'cron', hour=3, minute=15)
    scheduler.start()













# ── Admin: toggle de site flags (em breve) ────────────────






































def _animal_species_name(animal) -> str | None:
    if getattr(animal, 'species', None) and getattr(animal.species, 'name', None):
        return animal.species.name
    if getattr(animal, 'breed', None) and getattr(animal.breed, 'species', None):
        return getattr(animal.breed.species, 'name', None)
    return None


def _append_consulta_text(existing_text: str | None, new_text: str | None) -> str:
    current = (existing_text or '').strip()
    incoming = (new_text or '').strip()
    if not incoming:
        return current
    if not current:
        return incoming
    if incoming in current:
        return current
    return f"{current}\n\n{incoming}".strip()


def _build_clinical_suggestion_context(consulta, payload: dict | None = None) -> dict:
    payload = payload or {}
    animal = consulta.animal
    return {
        'suspeita_clinica': (payload.get('suspeita_clinica') or consulta.suspeita_clinica or '').strip() or None,
        'queixa_principal': (payload.get('queixa_principal') or consulta.queixa_principal or '').strip() or None,
        'historico_clinico': (payload.get('historico_clinico') or consulta.historico_clinico or '').strip() or None,
        'exame_fisico': (payload.get('exame_fisico') or consulta.exame_fisico or '').strip() or None,
        'especie': _animal_species_name(animal),
        'peso': getattr(animal, 'peso', None),
        'sexo': getattr(animal, 'sex', None),
        'data_base': date.today(),
    }


def _find_protocol_item(protocol, item_type: str, item_id: int | None):
    mapping = {
        'exame': getattr(protocol, 'exames_sugeridos', []) or [],
        'medicamento': getattr(protocol, 'medicamentos_sugeridos', []) or [],
        'retorno': getattr(protocol, 'retornos_sugeridos', []) or [],
    }
    if item_type == 'conduta':
        return protocol if getattr(protocol, 'conduta_sugerida', None) else None
    items = mapping.get(item_type, [])
    if not item_id:
        return None
    return next((item for item in items if item.id == item_id), None)


def _clean_protocol_text(value: str | None) -> str | None:
    text = (value or '').strip()
    return text or None


def _protocol_priority(value, default: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _serialize_clinical_protocol(protocol: ProtocoloClinico) -> dict:
    return {
        'id': protocol.id,
        'nome': protocol.nome,
        'suspeita_principal': protocol.suspeita_principal,
        'especie': protocol.especie,
        'prioridade': protocol.prioridade,
        'sinais_gatilho': protocol.sinais_gatilho,
        'conduta_sugerida': protocol.conduta_sugerida,
        'orientacoes_tutor': protocol.orientacoes_tutor,
        'alertas': protocol.alertas,
        'exames': [
            {
                'id': item.id,
                'nome': item.nome,
                'justificativa': item.justificativa,
            }
            for item in (protocol.exames_sugeridos or [])
        ],
        'medicamentos': [
            {
                'id': item.id,
                'nome_medicamento': item.nome_medicamento or item.nome_exibicao,
                'justificativa': item.justificativa,
                'dosagem_texto': item.dosagem_texto,
                'frequencia_texto': item.frequencia_texto,
                'duracao_texto': item.duracao_texto,
                'observacoes': item.observacoes,
                'indicacao': item.indicacao,
            }
            for item in (protocol.medicamentos_sugeridos or [])
        ],
        'retorno': (
            {
                'id': protocol.retornos_sugeridos[0].id,
                'prazo_min_dias': protocol.retornos_sugeridos[0].prazo_min_dias,
                'prazo_max_dias': protocol.retornos_sugeridos[0].prazo_max_dias,
                'tipo_retorno': protocol.retornos_sugeridos[0].tipo_retorno,
                'objetivo': protocol.retornos_sugeridos[0].objetivo,
                'gatilhos_antecipacao': protocol.retornos_sugeridos[0].gatilhos_antecipacao,
            }
            if (protocol.retornos_sugeridos or []) else {}
        ),
        'clinica_id': protocol.clinica_id,
    }


def _apply_protocol_payload(protocol: ProtocoloClinico, payload: dict, consulta) -> ProtocoloClinico:
    nome = _clean_protocol_text(payload.get('nome'))
    suspeita = _clean_protocol_text(payload.get('suspeita_principal'))
    if not nome or not suspeita:
        raise ValueError('Informe pelo menos nome do protocolo e suspeita principal.')

    protocol.nome = nome
    protocol.suspeita_principal = suspeita
    protocol.especie = _clean_protocol_text(payload.get('especie'))
    protocol.sinais_gatilho = _clean_protocol_text(payload.get('sinais_gatilho'))
    protocol.conduta_sugerida = _clean_protocol_text(payload.get('conduta_sugerida'))
    protocol.orientacoes_tutor = _clean_protocol_text(payload.get('orientacoes_tutor'))
    protocol.alertas = _clean_protocol_text(payload.get('alertas'))
    protocol.prioridade = _protocol_priority(payload.get('prioridade'), default=100)
    protocol.ativo = True
    if not getattr(protocol, 'clinica_id', None):
        protocol.clinica_id = consulta.clinica_id
    if not getattr(protocol, 'created_by', None):
        protocol.created_by = getattr(current_user, 'id', None)

    protocol.exames_sugeridos[:] = []
    protocol.medicamentos_sugeridos[:] = []
    protocol.retornos_sugeridos[:] = []

    for index, exame in enumerate(payload.get('exames') or [], start=1):
        nome_exame = _clean_protocol_text((exame or {}).get('nome'))
        if not nome_exame:
            continue
        protocol.exames_sugeridos.append(
            ProtocoloClinicoExame(
                nome=nome_exame,
                justificativa=_clean_protocol_text((exame or {}).get('justificativa')),
                prioridade=index,
            )
        )

    for index, medicamento in enumerate(payload.get('medicamentos') or [], start=1):
        nome_medicamento = _clean_protocol_text((medicamento or {}).get('nome_medicamento'))
        if not nome_medicamento:
            continue
        protocol.medicamentos_sugeridos.append(
            ProtocoloClinicoMedicamento(
                nome_medicamento=nome_medicamento,
                justificativa=_clean_protocol_text((medicamento or {}).get('justificativa')),
                dosagem_texto=_clean_protocol_text((medicamento or {}).get('dosagem_texto')),
                frequencia_texto=_clean_protocol_text((medicamento or {}).get('frequencia_texto')),
                duracao_texto=_clean_protocol_text((medicamento or {}).get('duracao_texto')),
                observacoes=_clean_protocol_text((medicamento or {}).get('observacoes')),
                indicacao=_clean_protocol_text((medicamento or {}).get('indicacao')),
                prioridade=index,
            )
        )

    retorno = payload.get('retorno') or {}
    prazo_min = retorno.get('prazo_min_dias')
    prazo_max = retorno.get('prazo_max_dias')
    objetivo = _clean_protocol_text(retorno.get('objetivo'))
    gatilhos = _clean_protocol_text(retorno.get('gatilhos_antecipacao'))
    tipo_retorno = _clean_protocol_text(retorno.get('tipo_retorno')) or 'retorno'
    try:
        prazo_min = int(prazo_min) if prazo_min not in (None, '') else None
    except (TypeError, ValueError):
        prazo_min = None
    try:
        prazo_max = int(prazo_max) if prazo_max not in (None, '') else None
    except (TypeError, ValueError):
        prazo_max = None
    if objetivo or gatilhos or prazo_min is not None or prazo_max is not None:
        protocol.retornos_sugeridos.append(
            ProtocoloClinicoRetorno(
                prazo_min_dias=prazo_min,
                prazo_max_dias=prazo_max,
                tipo_retorno=tipo_retorno,
                objetivo=objetivo,
                gatilhos_antecipacao=gatilhos,
                prioridade=1,
            )
        )

    return protocol


def _normalize_protocol_medication_name(value: str | None) -> str:
    text = unicodedata.normalize('NFKD', (value or '').strip().lower())
    return ''.join(char for char in text if not unicodedata.combining(char))


def _protocol_prefers_weight_based_dose(item) -> bool:
    name = _normalize_protocol_medication_name(getattr(item, 'nome_exibicao', None))
    if name in {'sec lac', 'cefalexina', 'meloxicam'}:
        return True
    return False


def _protocol_preferred_dose_mode(item) -> str:
    name = _normalize_protocol_medication_name(getattr(item, 'nome_exibicao', None))
    indication = _normalize_protocol_medication_name(getattr(item, 'indicacao', None))
    if name == 'prednisona' and indication == 'alergia':
        return 'min'
    if name == 'cefalexina':
        return 'media'
    if name == 'meloxicam':
        return 'min'
    return ''


def _build_protocol_from_payload(payload: dict, consulta) -> ProtocoloClinico:
    protocolo = ProtocoloClinico(
        versao=1,
        ativo=True,
        clinica_id=consulta.clinica_id,
        created_by=getattr(current_user, 'id', None),
    )
    return _apply_protocol_payload(protocolo, payload, consulta)







































TUTOR_SEARCH_LIMIT = 50














def _user_can_manage_clinic(clinica):
    """Return True when the current user can manage the given clinic."""
    if not current_user.is_authenticated:
        return False
    if _is_admin():
        return True
    if current_user.id == clinica.owner_id:
        return True
    if current_user.id == clinica.registered_by_id:
        return True
    if is_veterinarian(current_user) and current_user.veterinario.clinica_id == clinica.id:
        return True
    return False


# ── Casa de Ração ─────────────────────────────────────────────────────────────

def _casa_loja_access(casa_id):
    """Retorna a CasaDeRacao ou aborta 403 se o usuário não for dono/admin/parceiro."""
    casa = CasaDeRacao.query.get_or_404(casa_id)
    if not (
        _is_admin()
        or current_user.id == casa.owner_id
        or current_user.id == casa.registered_by_id
    ):
        abort(403)
    return casa




def _casa_de_racao_product_onboarding_target(casa):
    if casa.status == 'pendente' and not _is_admin():
        return url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#produtos'
    return url_for('casa_de_racao_produtos', casa_id=casa.id)


def _variant_name_from_parts(name=None, dosage=None, package_quantity=None, weight_volume=None):
    explicit = (name or '').strip()
    if explicit:
        return explicit[:160]
    parts = [p.strip() for p in (dosage or '', package_quantity or '', weight_volume or '') if p and p.strip()]
    return ' · '.join(parts)[:160] if parts else 'Padrão'


def _sync_product_legacy_price_stock(product):
    """Mantém Product.price/stock compatível com código legado."""
    active = [v for v in (product.variants or []) if v.status == 'active']
    if not active:
        return
    primary = sorted(active, key=lambda v: (v.position or 0, v.id or 0))[0]
    product.price = float(primary.price or 0)
    product.stock = sum(int(v.stock or 0) for v in active)


def _create_initial_variant(product, form):
    variant = ProductVariant(
        product=product,
        name=_variant_name_from_parts(
            form.variant_name.data,
            form.dosage.data,
            form.package_quantity.data,
            form.weight_volume.data,
        ),
        dosage=(form.dosage.data or '').strip() or None,
        package_quantity=(form.package_quantity.data or '').strip() or None,
        weight_volume=(form.weight_volume.data or '').strip() or None,
        sku=(form.sku.data or '').strip() or None,
        price=float(form.price.data or 0),
        stock=form.stock.data or 0,
        status='active',
        position=0,
    )
    db.session.add(variant)
    return variant


def _sync_variants_from_request(product):
    """Sincroniza linhas dinâmicas de variação do formulário de edição."""
    ids = request.form.getlist('variant_id[]')
    names = request.form.getlist('variant_name[]')
    dosages = request.form.getlist('variant_dosage[]')
    packages = request.form.getlist('variant_package[]')
    weights = request.form.getlist('variant_weight[]')
    skus = request.form.getlist('variant_sku[]')
    prices = request.form.getlist('variant_price[]')
    stocks = request.form.getlist('variant_stock[]')
    statuses = set(request.form.getlist('variant_active[]'))

    existing = {str(v.id): v for v in product.variants}
    seen_ids = set()

    total = max(len(names), len(prices), len(stocks), len(ids))
    for idx in range(total):
        raw_price = (prices[idx] if idx < len(prices) else '').strip().replace(',', '.')
        if not raw_price:
            continue
        try:
            price = float(raw_price)
        except ValueError:
            continue
        if price <= 0:
            continue
        raw_stock = (stocks[idx] if idx < len(stocks) else '').strip()
        try:
            stock = max(0, int(raw_stock or 0))
        except ValueError:
            stock = 0

        variant_id = (ids[idx] if idx < len(ids) else '').strip()
        variant = existing.get(variant_id)
        if not variant:
            variant = ProductVariant(product=product)
            db.session.add(variant)
        elif variant_id:
            seen_ids.add(variant_id)

        name = names[idx] if idx < len(names) else ''
        dosage = dosages[idx] if idx < len(dosages) else ''
        package_quantity = packages[idx] if idx < len(packages) else ''
        weight_volume = weights[idx] if idx < len(weights) else ''
        sku = skus[idx] if idx < len(skus) else ''

        variant.name = _variant_name_from_parts(name, dosage, package_quantity, weight_volume)
        variant.dosage = dosage.strip() or None
        variant.package_quantity = package_quantity.strip() or None
        variant.weight_volume = weight_volume.strip() or None
        variant.sku = sku.strip() or None
        variant.price = price
        variant.stock = stock
        variant.position = idx
        variant.status = 'active' if str(idx) in statuses else 'inactive'

    for variant_id, variant in existing.items():
        if variant_id not in seen_ids and not any((ids[i] if i < len(ids) else '') == variant_id for i in range(total)):
            variant.status = 'inactive'

    if not any(v.status == 'active' for v in product.variants):
        first = product.variants[0] if product.variants else None
        if first:
            first.status = 'active'

    _sync_product_legacy_price_stock(product)




def _onboarding_decimal(raw_value):
    value = str(raw_value or '').strip().replace('R$', '').replace(' ', '')
    if not value:
        return None
    if ',' in value:
        value = value.replace('.', '').replace(',', '.')
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _onboarding_money_display(value):
    if value is None:
        return ''
    amount = Decimal(value).quantize(Decimal('0.01'))
    return f"{amount:.2f}".replace('.', ',')


def _onboarding_seller_percent():
    fee_percent = Decimal(str(current_app.config.get('MERCADOPAGO_MARKETPLACE_FEE_PERCENT') or 0))
    seller_percent = Decimal('100') - fee_percent
    return fee_percent, seller_percent


def _onboarding_payout_from_final(price):
    """Repasse estimado a partir de um preço de vitrine desejado (÷ 1,10).

    O preço de vitrine real será ``_onboarding_final_from_payout`` do valor
    retornado (pode arredondar para cima até o múltiplo de R$ 5).
    """
    if price is None:
        return None
    return (Decimal(price) / Decimal('1.10')).quantize(Decimal('0.01'))


def _onboarding_final_from_payout(payout):
    """Preço de vitrine: repasse + 10%, arredondado ao próximo múltiplo de R$5.

    Mesma regra de ``Product.preco_publico`` — o lojista recebe o valor
    integral que definiu; a taxa fica embutida no preço exibido.
    """
    if payout is None:
        return None
    amount = Decimal(payout)
    if amount <= 0:
        return None
    return public_price_from_professional_price(amount)


def _onboarding_prefill_email(user_email):
    email = normalize_email(user_email) or ''
    return '' if email.endswith('@convite.petorlandia.local') else email


def _onboarding_product_form_state(produtos):
    state = []
    configured_count = 0
    fee_percent, seller_percent = _onboarding_seller_percent()
    for product in produtos:
        is_configured = bool((product.price or 0) > 0 and (product.stock or 0) >= 0 and product.status == 'active')
        if is_configured:
            configured_count += 1
        # product.price = valor que o lojista recebe; vitrine = preço público.
        payout = Decimal(str(product.price or 0)) if is_configured else None
        final_price = _onboarding_final_from_payout(payout) if is_configured else None
        state.append({
            'product': product,
            'price_value': _onboarding_money_display(final_price),
            'payout_value': _onboarding_money_display(payout),
            'stock_value': '' if not is_configured else str(product.stock),
            'configured': is_configured,
            'pricing_mode': 'payout',
        })
    return state, configured_count, fee_percent, seller_percent
























# ── Área do Parceiro (onboarding de estabelecimentos) ──────────────────────────























# ── Parcerias: pendências de aprovação + convites unificados ────────────────



# _partner_invite_url/_partner_invite_whatsapp_url migraram para blueprints/admin.py




















def _optional_decimal_from_form(field_name):
    raw_value = (request.form.get(field_name) or '').strip().replace(',', '.')
    if not raw_value:
        return None
    try:
        return float(Decimal(raw_value))
    except Exception:
        return None










# ── Fim Casa de Ração ──────────────────────────────────────────────────────────


def _send_clinic_invite_email(clinica, veterinarian_user, inviter):
    """Send the invite email for a clinic invitation."""
    if not veterinarian_user:
        current_app.logger.warning(
            'Convite para clínica %s ignorado: veterinário sem usuário associado.',
            clinica.id,
        )
        return False

    acceptance_url = url_for('clinic_invites', _external=True)
    inviter_name = getattr(inviter, 'name', None) or 'Um membro da clínica'
    recipient_name = getattr(veterinarian_user, 'name', None) or 'veterinário(a)'
    subject = f"Convite para ingressar na clínica {clinica.nome}"
    body = (
        f"Olá {recipient_name},\n\n"
        f"{inviter_name} convidou você para ingressar na clínica {clinica.nome} na PetOrlândia.\n"
        f"Acesse {acceptance_url} para aceitar ou recusar o convite e concluir o processo.\n\n"
        "Se tiver dúvidas, responda a este e-mail ou entre em contato com a clínica.\n\n"
        "Equipe PetOrlândia"
    )
    msg = MailMessage(
        subject=subject,
        sender=app.config['MAIL_DEFAULT_SENDER'],
        recipients=[veterinarian_user.email],
        body=body,
    )
    try:
        mail.send(msg)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception('Falha ao enviar e-mail de convite da clínica: %s', exc)
        return False
    return True


def _resolve_clinic_logo_path(clinica):
    """Return an absolute filesystem path for the clinic logo if it exists."""
    if not clinica or not clinica.logotipo:
        return None

    logo_path = clinica.logotipo
    if logo_path.startswith('http'):
        return None

    if logo_path.startswith('/'):
        candidate = os.path.join(current_app.root_path, logo_path.lstrip('/'))
    else:
        uploads_dir = os.path.join(
            current_app.static_folder,
            'uploads',
            'clinicas',
        )
        candidate = os.path.join(uploads_dir, logo_path)

    return candidate if os.path.isfile(candidate) else None


def _rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*rgb)


def _hex_to_rgb(value):
    value = value.lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    return tuple(int(value[i:i + 2], 16) for i in range(0, 6, 2))


def _relative_brightness(rgb):
    r, g, b = rgb
    return (r * 299 + g * 587 + b * 114) / 1000


def _is_light_color(rgb):
    return _relative_brightness(rgb) >= 155


def _color_distance(rgb_a, rgb_b):
    return sum((a - b) ** 2 for a, b in zip(rgb_a, rgb_b)) ** 0.5


def _simplify_color(rgb):
    return tuple((channel // 16) * 16 for channel in rgb)


def _extract_clinic_logo_palette(clinica):
    logo_path = _resolve_clinic_logo_path(clinica)
    if not logo_path:
        return {}

    try:
        with Image.open(logo_path) as img:
            img = img.convert('RGBA')
            img.thumbnail((220, 220))
            pixels = [
                tuple(pixel[:3])
                for pixel in img.getdata()
                if (len(pixel) == 4 and pixel[3] > 50) or len(pixel) == 3
            ]
    except Exception as exc:
        current_app.logger.debug(
            'Não foi possível extrair cores do logo da clínica %s: %s',
            clinica.id,
            exc,
        )
        return {}

    if not pixels:
        return {}

    counter = Counter(_simplify_color(pixel) for pixel in pixels)
    if not counter:
        return {}

    primary = counter.most_common(1)[0][0]
    secondary = primary
    for color, _ in counter.most_common(5):
        if _color_distance(primary, color) > 60:
            secondary = color
            break

    if secondary == primary and len(counter) > 1:
        secondary = counter.most_common(2)[1][0]

    return {
        'primary_color': _rgb_to_hex(primary),
        'secondary_color': _rgb_to_hex(secondary),
    }


def _clinic_initials(clinica):
    if not clinica or not clinica.nome:
        return 'CL'
    parts = [part for part in re.split(r'\s+', clinica.nome.strip()) if part]
    if not parts:
        return 'CL'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _extract_city_from_address(address):
    if not address:
        return ''
    segments = [seg.strip() for seg in re.split(r'[-–,]', address) if seg.strip()]
    if not segments:
        return ''
    candidate = segments[-1]
    if len(candidate.split()) > 6:
        return ''
    return candidate


def _build_clinic_subtitle(clinica):
    if not clinica:
        return 'Parceira PetOrlândia'

    custom_slogans = current_app.config.get('CLINIC_SLOGANS', {}) or {}
    for key in (clinica.id, str(clinica.id), clinica.nome):
        if key in custom_slogans:
            return custom_slogans[key]

    city = _extract_city_from_address(clinica.endereco)
    if city:
        return f'Referência veterinária em {city}'
    if clinica.telefone:
        return f'Fale com a equipe pelo {clinica.telefone}'
    if clinica.email:
        return f'Contato direto: {clinica.email}'
    return 'Parceira PetOrlândia'


def _build_clinic_theme(clinica):
    theme = {
        'primary_color': '#6f6df4',
        'secondary_color': '#46c4d3',
    }

    presets = current_app.config.get('CLINIC_COLOR_PRESETS', {}) or {}
    keys = [
        clinica.id if clinica else None,
        str(clinica.id) if clinica else None,
        clinica.nome if clinica else None,
        'default',
    ]
    for key in keys:
        if key in presets:
            theme.update(presets[key])
            break

    theme.update(_extract_clinic_logo_palette(clinica))

    primary_rgb = _hex_to_rgb(theme['primary_color'])
    text_color = theme.get('text_color')
    if not text_color:
        text_color = '#0f172a' if _is_light_color(primary_rgb) else '#f8fafc'
    theme['text_color'] = text_color

    text_rgb = _hex_to_rgb(text_color)
    text_is_light = _is_light_color(text_rgb)

    if text_is_light:
        theme.setdefault('subtitle_color', 'rgba(248, 250, 252, 0.82)')
        theme.setdefault('eyebrow_color', 'rgba(248, 250, 252, 0.7)')
        theme.setdefault('chip_bg_color', 'rgba(255, 255, 255, 0.2)')
        theme.setdefault('chip_border_color', 'rgba(255, 255, 255, 0.35)')
        theme.setdefault('chip_text_color', '#ffffff')
        theme.setdefault('logo_frame_bg', '#ffffff')
        theme.setdefault('logo_frame_shadow', 'rgba(0, 0, 0, 0.15)')
        theme.setdefault('avatar_text_color', '#ffffff')
    else:
        theme.setdefault('subtitle_color', 'rgba(15, 23, 42, 0.82)')
        theme.setdefault('eyebrow_color', 'rgba(15, 23, 42, 0.65)')
        theme.setdefault('chip_bg_color', 'rgba(15, 23, 42, 0.08)')
        theme.setdefault('chip_border_color', 'rgba(15, 23, 42, 0.18)')
        theme.setdefault('chip_text_color', '#0f172a')
        theme.setdefault('logo_frame_bg', '#f8fafc')
        theme.setdefault('logo_frame_shadow', 'rgba(15, 23, 42, 0.12)')
        theme.setdefault('avatar_text_color', '#0f172a')

    theme.setdefault(
        'avatar_bg',
        f'linear-gradient(135deg, {theme["primary_color"]}, {theme["secondary_color"]})',
    )
    theme.setdefault('logo_frame_border', 'rgba(255, 255, 255, 0.4)')

    return theme


















def _clinic_loja_access(clinica_id):
    """Retorna (clinica, is_owner). Aborta 403 se sem permissão."""
    clinica = Clinica.query.get_or_404(clinica_id)
    is_owner = current_user.id == clinica.owner_id
    staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_perm = staff.can_manage_inventory if staff else False
    if not (_is_admin() or is_owner or has_perm):
        abort(403)
    return clinica, is_owner










# ---------------------------------------------------------------------------
# Planos de Banho e Tosa
# ---------------------------------------------------------------------------



















def _orcamento_services_for_clinic(clinica_id):
    return (
        ServicoClinica.query
        .filter(
            or_(
                ServicoClinica.clinica_id == clinica_id,
                ServicoClinica.clinica_id.is_(None),
            )
        )
        .order_by(ServicoClinica.descricao)
        .all()
    )


def _format_decimal_for_form(value):
    if value in (None, ''):
        return ''
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        return f"{amount.quantize(Decimal('0.01')):.2f}"
    except (ArithmeticError, InvalidOperation, ValueError):
        return str(value)


def _parse_currency_decimal(value):
    text_value = str(value or '').strip()
    if not text_value:
        return None
    normalized = text_value.replace('R$', '').replace(' ', '')
    if ',' in normalized:
        normalized = normalized.replace('.', '').replace(',', '.')
    try:
        amount = Decimal(normalized)
    except (ArithmeticError, InvalidOperation, ValueError) as exc:
        raise ValueError('Valor inválido.') from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError('Valor inválido.')
    return amount.quantize(Decimal('0.01'))


def _orcamento_submitted_item_fields_present():
    return any(
        key in request.form
        for key in (
            'item_servico_id[]',
            'item_servico_id',
            'item_descricao[]',
            'item_descricao',
            'item_valor[]',
            'item_valor',
        )
    )


def _orcamento_form_item_rows_from_request():
    def _getlist(field_name):
        values = request.form.getlist(f'{field_name}[]')
        if values:
            return values
        return request.form.getlist(field_name)

    service_ids = _getlist('item_servico_id')
    descriptions = _getlist('item_descricao')
    values = _getlist('item_valor')
    payer_types = _getlist('item_payer_type')
    procedure_codes = _getlist('item_procedure_code')
    row_count = max(
        len(service_ids),
        len(descriptions),
        len(values),
        len(payer_types),
        len(procedure_codes),
    )

    def _value_at(items, index, default=''):
        return items[index] if index < len(items) else default

    rows = []
    for index in range(row_count):
        rows.append({
            'servico_id': _value_at(service_ids, index),
            'descricao': _value_at(descriptions, index),
            'valor': _value_at(values, index),
            'payer_type': _value_at(payer_types, index, 'particular') or 'particular',
            'procedure_code': _value_at(procedure_codes, index),
        })
    return rows


def _orcamento_form_item_rows_from_model(orcamento):
    rows = []
    for item in getattr(orcamento, 'items', []) or []:
        rows.append({
            'servico_id': str(item.servico_id or ''),
            'descricao': item.descricao or '',
            'valor': _format_decimal_for_form(item.valor),
            'payer_type': item.payer_type or 'particular',
            'procedure_code': item.procedure_code or '',
            'locked': bool(item.bloco_id),
        })
    return rows


def _extract_orcamento_item_payloads(clinica_id):
    rows = _orcamento_form_item_rows_from_request()
    payloads = []
    errors = []
    for index, row in enumerate(rows, start=1):
        raw_service_id = str(row.get('servico_id') or '').strip()
        raw_description = str(row.get('descricao') or '').strip()
        raw_value = str(row.get('valor') or '').strip()
        raw_code = str(row.get('procedure_code') or '').strip()

        if not any([raw_service_id, raw_description, raw_value, raw_code]):
            continue

        service = None
        service_id = _coerce_int(raw_service_id) if raw_service_id else None
        if raw_service_id and service_id is None:
            errors.append(f'Item {index}: selecione um serviço válido.')
            continue
        if service_id:
            service = ServicoClinica.query.get(service_id)
            if not service:
                errors.append(f'Item {index}: serviço não encontrado.')
                continue
            if service.clinica_id and service.clinica_id != clinica_id:
                errors.append(f'Item {index}: serviço indisponível para esta clínica.')
                continue

        description = raw_description or (service.descricao if service else '')
        procedure_code = raw_code or (service.procedure_code if service else None)
        if not description:
            errors.append(f'Item {index}: informe a descrição.')
            continue

        try:
            amount = _parse_currency_decimal(raw_value) if raw_value else None
        except ValueError:
            errors.append(f'Item {index}: informe um valor válido.')
            continue
        if amount is None and service:
            amount = _parse_currency_decimal(service.valor)
        if amount is None:
            errors.append(f'Item {index}: informe o valor.')
            continue

        payer_type = row.get('payer_type') or 'particular'
        if payer_type not in PAYER_TYPE_LABELS:
            payer_type = 'particular'

        payloads.append({
            'descricao': description[:120],
            'valor': amount,
            'servico_id': service.id if service else None,
            'procedure_code': procedure_code,
            'payer_type': payer_type,
        })
    return payloads, rows, errors


def _render_orcamento_form(form, clinica, *, orcamento=None, item_rows=None, selected_status=None, errors=None):
    if item_rows is None:
        item_rows = _orcamento_form_item_rows_from_model(orcamento) if orcamento else []
    locked_items = [row for row in item_rows if row.get('locked')]
    can_edit_items = not locked_items
    return render_template(
        'orcamentos/orcamento_form.html',
        form=form,
        clinica=clinica,
        orcamento=orcamento,
        servicos=_orcamento_services_for_clinic(clinica.id),
        item_rows=item_rows,
        can_edit_items=can_edit_items,
        selected_status=selected_status or (getattr(orcamento, 'status', None) or 'draft'),
        orcamento_status_labels=ORCAMENTO_STATUS_LABELS,
        item_errors=errors or [],
    )








































def _appointment_request_within_vet_schedule(veterinario_id, scheduled_date, scheduled_time):
    weekday_names = {
        0: {"segunda", "segunda feira"},
        1: {"terca", "terca feira"},
        2: {"quarta", "quarta feira"},
        3: {"quinta", "quinta feira"},
        4: {"sexta", "sexta feira"},
        5: {"sabado"},
        6: {"domingo"},
    }
    allowed_names = weekday_names.get(scheduled_date.weekday(), set())
    horarios = VetSchedule.query.filter_by(veterinario_id=veterinario_id).all()
    for horario in horarios:
        dia = unicodedata.normalize("NFKD", (horario.dia_semana or "").lower())
        dia = "".join(ch for ch in dia if not unicodedata.combining(ch))
        dia = re.sub(r"[^a-z]+", " ", dia).strip()
        if dia not in allowed_names:
            continue
        if not (horario.hora_inicio <= scheduled_time < horario.hora_fim):
            continue
        if (
            horario.intervalo_inicio
            and horario.intervalo_fim
            and horario.intervalo_inicio <= scheduled_time < horario.intervalo_fim
        ):
            continue
        return True
    return False




def _veterinarian_activity_kind_label(kind):
    labels = {
        'appointment': 'Agendamento',
        'consulta': 'Consulta',
        'prescription': 'Prescrição',
        'exam_request': 'Exame solicitado',
        'vaccine': 'Vacina',
        'document': 'Documento',
    }
    return labels.get(kind, 'Atividade')


def _veterinarian_activity_status_label(raw_status):
    if not raw_status:
        return '—'

    labels = {
        'scheduled': 'Agendado',
        'agendado': 'Agendado',
        'confirmed': 'Confirmado',
        'confirmado': 'Confirmado',
        'completed': 'Concluído',
        'concluido': 'Concluído',
        'finalizada': 'Finalizada',
        'in_progress': 'Em andamento',
        'pending': 'Pendente',
        'pendente': 'Pendente',
        'cancelled': 'Cancelado',
        'cancelado': 'Cancelado',
        'aplicada': 'Aplicada',
        'uploaded': 'Anexado',
    }
    normalized = str(raw_status).strip().lower()
    return labels.get(normalized, str(raw_status).replace('_', ' ').title())


def _veterinarian_activity_timestamp_local(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=BR_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=BR_TZ)
    return value.astimezone(BR_TZ)


def _veterinarian_activity_in_range(value, start_date, end_date):
    local_value = _veterinarian_activity_timestamp_local(value)
    if local_value is None:
        return False
    return start_date <= local_value.date() <= end_date


def _consulta_activity_timestamp(consulta):
    if getattr(consulta, 'finalizada_em', None):
        return consulta.finalizada_em
    if getattr(consulta, 'created_at', None):
        return consulta.created_at
    appointment = getattr(consulta, 'appointment', None)
    if appointment and getattr(appointment, 'scheduled_at', None):
        return appointment.scheduled_at
    return None


def _clinical_suspicion_options(clinic_id: int | None = None) -> list[str]:
    query = (
        db.session.query(ProtocoloClinico.suspeita_principal)
        .filter(ProtocoloClinico.ativo.is_(True))
        .filter(ProtocoloClinico.suspeita_principal.isnot(None))
    )
    if clinic_id:
        query = query.filter(
            or_(ProtocoloClinico.clinica_id.is_(None), ProtocoloClinico.clinica_id == clinic_id)
        )
    else:
        query = query.filter(ProtocoloClinico.clinica_id.is_(None))

    rows = query.distinct().order_by(ProtocoloClinico.suspeita_principal.asc()).all()
    return [value.strip() for (value,) in rows if (value or '').strip()]


def _can_view_veterinarian_activity_report(veterinario):
    if not current_user.is_authenticated:
        return False
    if getattr(current_user, 'role', None) == 'admin':
        return True
    current_vet = getattr(current_user, 'veterinario', None)
    return bool(current_vet and current_vet.id == veterinario.id)


def _build_veterinarian_activity_report(veterinario, start_date, end_date):
    activities = []
    vet_user_id = getattr(veterinario, 'user_id', None)

    appointments = (
        Appointment.query.options(
            joinedload(Appointment.animal).joinedload(Animal.owner),
            joinedload(Appointment.clinica),
        )
        .filter(Appointment.veterinario_id == veterinario.id)
        .all()
    )
    for appointment in appointments:
        if not _veterinarian_activity_in_range(appointment.scheduled_at, start_date, end_date):
            continue
        activities.append(
            {
                'kind': 'appointment',
                'timestamp': _veterinarian_activity_timestamp_local(appointment.scheduled_at),
                'status': _veterinarian_activity_status_label(appointment.status),
                'animal_name': getattr(getattr(appointment, 'animal', None), 'name', '—'),
                'tutor_name': getattr(getattr(getattr(appointment, 'animal', None), 'owner', None), 'name', '—'),
                'clinic_name': getattr(getattr(appointment, 'clinica', None), 'nome', None)
                or getattr(getattr(veterinario, 'clinica', None), 'nome', '—'),
                'detail': appointment.notes or f"Tipo: {(appointment.kind or 'consulta').replace('_', ' ').title()}",
                'record_id': appointment.id,
                'detail_url': url_for('appointments', view_as='veterinario', veterinario_id=veterinario.id),
            }
        )

    consultas = (
        Consulta.query.options(
            joinedload(Consulta.animal).joinedload(Animal.owner),
            joinedload(Consulta.clinica),
            joinedload(Consulta.appointment),
        )
        .filter(Consulta.created_by == vet_user_id)
        .all()
    )
    consultas_by_id = {}
    consultas_by_animal_day = defaultdict(list)
    for consulta in consultas:
        timestamp = _consulta_activity_timestamp(consulta)
        if not _veterinarian_activity_in_range(timestamp, start_date, end_date):
            continue
        consultas_by_id[consulta.id] = consulta
        local_timestamp = _veterinarian_activity_timestamp_local(timestamp)
        consultas_by_animal_day[(consulta.animal_id, local_timestamp.date())].append(consulta)
        detail_parts = [
            consulta.queixa_principal,
            consulta.conduta,
            consulta.exames_solicitados,
        ]
        activities.append(
            {
                'kind': 'consulta',
                'timestamp': local_timestamp,
                'status': _veterinarian_activity_status_label(consulta.status),
                'animal_name': getattr(getattr(consulta, 'animal', None), 'name', '—'),
                'tutor_name': getattr(getattr(getattr(consulta, 'animal', None), 'owner', None), 'name', '—'),
                'clinic_name': getattr(getattr(consulta, 'clinica', None), 'nome', None)
                or getattr(getattr(veterinario, 'clinica', None), 'nome', '—'),
                'detail': ' | '.join(part.strip() for part in detail_parts if part) or 'Atendimento clínico registrado.',
                'record_id': consulta.id,
                'detail_url': url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id),
            }
        )

    prescricoes = (
        BlocoPrescricao.query.options(
            joinedload(BlocoPrescricao.animal).joinedload(Animal.owner),
            joinedload(BlocoPrescricao.clinica),
            joinedload(BlocoPrescricao.prescricoes),
        )
        .filter(BlocoPrescricao.saved_by_id == vet_user_id)
        .all()
    )
    for bloco in prescricoes:
        if not _veterinarian_activity_in_range(bloco.data_criacao, start_date, end_date):
            continue
        medicamentos = [prescricao.medicamento for prescricao in (bloco.prescricoes or []) if prescricao.medicamento]
        detail = ', '.join(medicamentos[:4])
        if len(medicamentos) > 4:
            detail = f"{detail} e mais {len(medicamentos) - 4}"
        activities.append(
            {
                'kind': 'prescription',
                'timestamp': _veterinarian_activity_timestamp_local(bloco.data_criacao),
                'status': _veterinarian_activity_status_label('completed'),
                'animal_name': getattr(getattr(bloco, 'animal', None), 'name', '—'),
                'tutor_name': getattr(getattr(getattr(bloco, 'animal', None), 'owner', None), 'name', '—'),
                'clinic_name': getattr(getattr(bloco, 'clinica', None), 'nome', None)
                or getattr(getattr(veterinario, 'clinica', None), 'nome', '—'),
                'detail': detail or bloco.instrucoes_gerais or 'Prescrição registrada no prontuário.',
                'record_id': bloco.id,
                'detail_url': url_for('ficha_animal', animal_id=bloco.animal_id),
            }
        )

    consulta_animal_ids = {consulta.animal_id for consulta in consultas_by_id.values()}
    if consulta_animal_ids:
        exam_blocks = (
            BlocoExames.query.options(
                joinedload(BlocoExames.animal).joinedload(Animal.owner),
                joinedload(BlocoExames.exames),
            )
            .filter(BlocoExames.animal_id.in_(consulta_animal_ids))
            .all()
        )
        for bloco in exam_blocks:
            if not _veterinarian_activity_in_range(bloco.data_criacao, start_date, end_date):
                continue
            local_timestamp = _veterinarian_activity_timestamp_local(bloco.data_criacao)
            related_consulta = None
            if getattr(bloco, 'consulta_id', None):
                related_consulta = consultas_by_id.get(bloco.consulta_id)
            if related_consulta is None:
                same_day_consultas = consultas_by_animal_day.get((bloco.animal_id, local_timestamp.date()), [])
                if same_day_consultas:
                    related_consulta = same_day_consultas[0]
            if related_consulta is None:
                continue
            for exame in bloco.exames or []:
                activities.append(
                    {
                        'kind': 'exam_request',
                        'timestamp': local_timestamp,
                        'status': _veterinarian_activity_status_label(exame.status),
                        'animal_name': getattr(getattr(bloco, 'animal', None), 'name', '—'),
                        'tutor_name': getattr(getattr(getattr(bloco, 'animal', None), 'owner', None), 'name', '—'),
                        'clinic_name': getattr(getattr(related_consulta, 'clinica', None), 'nome', None)
                        or getattr(getattr(veterinario, 'clinica', None), 'nome', '—'),
                        'detail': exame.nome if not exame.justificativa else f"{exame.nome} | {exame.justificativa}",
                        'record_id': exame.id,
                        'detail_url': url_for('consulta_direct', animal_id=related_consulta.animal_id, c=related_consulta.id),
                    }
                )

    vacinas = (
        Vacina.query.options(joinedload(Vacina.animal).joinedload(Animal.owner))
        .filter(or_(Vacina.aplicada_por == vet_user_id, Vacina.created_by == vet_user_id))
        .all()
    )
    for vacina in vacinas:
        vacina_timestamp = vacina.aplicada_em or vacina.criada_em
        if not _veterinarian_activity_in_range(vacina_timestamp, start_date, end_date):
            continue
        status = 'aplicada' if vacina.aplicada else 'pending'
        activities.append(
            {
                'kind': 'vaccine',
                'timestamp': _veterinarian_activity_timestamp_local(vacina_timestamp),
                'status': _veterinarian_activity_status_label(status),
                'animal_name': getattr(getattr(vacina, 'animal', None), 'name', '—'),
                'tutor_name': getattr(getattr(getattr(vacina, 'animal', None), 'owner', None), 'name', '—'),
                'clinic_name': getattr(getattr(veterinario, 'clinica', None), 'nome', '—'),
                'detail': vacina.nome or 'Vacina registrada.',
                'record_id': vacina.id,
                'detail_url': url_for('ficha_animal', animal_id=vacina.animal_id),
            }
        )

    documentos = (
        AnimalDocumento.query.options(joinedload(AnimalDocumento.animal).joinedload(Animal.owner))
        .filter(AnimalDocumento.veterinario_id == vet_user_id)
        .all()
    )
    for documento in documentos:
        if not _veterinarian_activity_in_range(documento.uploaded_at, start_date, end_date):
            continue
        activities.append(
            {
                'kind': 'document',
                'timestamp': _veterinarian_activity_timestamp_local(documento.uploaded_at),
                'status': _veterinarian_activity_status_label('uploaded'),
                'animal_name': getattr(getattr(documento, 'animal', None), 'name', '—'),
                'tutor_name': getattr(getattr(getattr(documento, 'animal', None), 'owner', None), 'name', '—'),
                'clinic_name': getattr(getattr(veterinario, 'clinica', None), 'nome', '—'),
                'detail': documento.descricao or documento.filename,
                'record_id': documento.id,
                'detail_url': documento.file_url,
            }
        )

    activities.sort(
        key=lambda item: item.get('timestamp') or datetime.min.replace(tzinfo=BR_TZ),
        reverse=True,
    )

    unique_animals = {
        item['animal_name']
        for item in activities
        if item.get('animal_name') and item.get('animal_name') != '—'
    }
    summary = {
        'total': len(activities),
        'appointments': sum(1 for item in activities if item['kind'] == 'appointment'),
        'consultas': sum(1 for item in activities if item['kind'] == 'consulta'),
        'prescriptions': sum(1 for item in activities if item['kind'] == 'prescription'),
        'exam_requests': sum(1 for item in activities if item['kind'] == 'exam_request'),
        'vaccines': sum(1 for item in activities if item['kind'] == 'vaccine'),
        'documents': sum(1 for item in activities if item['kind'] == 'document'),
        'animals': len(unique_animals),
        'days_with_activity': len(
            {
                item['timestamp'].date()
                for item in activities
                if item.get('timestamp') is not None
            }
        ),
    }

    return activities, summary


def _export_veterinarian_activity_csv(veterinario, activities, start_date, end_date):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Veterinario',
        'CRMV',
        'Periodo inicial',
        'Periodo final',
        'Data',
        'Tipo',
        'Status',
        'Animal',
        'Tutor',
        'Clinica',
        'Detalhes',
        'Registro ID',
        'Link',
    ])
    for item in activities:
        writer.writerow([
            getattr(getattr(veterinario, 'user', None), 'name', ''),
            getattr(veterinario, 'crmv', ''),
            start_date.isoformat(),
            end_date.isoformat(),
            item['timestamp'].strftime('%Y-%m-%d %H:%M') if item.get('timestamp') else '',
            _veterinarian_activity_kind_label(item['kind']),
            item.get('status', ''),
            item.get('animal_name', ''),
            item.get('tutor_name', ''),
            item.get('clinic_name', ''),
            item.get('detail', ''),
            item.get('record_id', ''),
            item.get('detail_url', ''),
        ])
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = (
        f'attachment; filename=veterinario-{veterinario.id}-atividades-{start_date.isoformat()}-{end_date.isoformat()}.csv'
    )
    return response


def _export_veterinarian_activity_pdf(veterinario, activities, summary, start_date, end_date):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40

    header_lines = [
        'Relatório de atividades do veterinário',
        f"Profissional: {getattr(getattr(veterinario, 'user', None), 'name', '—')} | CRMV: {getattr(veterinario, 'crmv', '—')}",
        f"Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}",
        (
            f"Total: {summary['total']} | Consultas: {summary['consultas']} | "
            f"Agendamentos: {summary['appointments']} | Prescrições: {summary['prescriptions']}"
        ),
        (
            f"Exames: {summary['exam_requests']} | Vacinas: {summary['vaccines']} | "
            f"Documentos: {summary['documents']} | Animais: {summary['animals']}"
        ),
    ]

    for text_line in header_lines:
        pdf.drawString(36, y, text_line[:120])
        y -= 16
    y -= 8

    for item in activities:
        lines = [
            (
                f"{item['timestamp'].strftime('%d/%m/%Y %H:%M') if item.get('timestamp') else '—'} | "
                f"{_veterinarian_activity_kind_label(item['kind'])} | {item.get('status', '—')}"
            ),
            (
                f"Animal: {item.get('animal_name', '—')} | Tutor: {item.get('tutor_name', '—')} | "
                f"Clínica: {item.get('clinic_name', '—')}"
            ),
            f"Detalhes: {(item.get('detail') or '—')[:110]}",
        ]
        for line in lines:
            if y < 40:
                pdf.showPage()
                y = height - 40
            pdf.drawString(36, y, line[:120])
            y -= 14
        y -= 8

    pdf.save()
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'veterinario-{veterinario.id}-atividades-{start_date.isoformat()}-{end_date.isoformat()}.pdf',
    )


def _user_is_clinic_professional(veterinario_id=None):
    """True quando o usuário logado é profissional (admin/vet/colaborador).

    Apenas profissionais enxergam a página de gestão do veterinário (com agenda
    e dados internos). Tutores e visitantes recebem o perfil público.
    """
    if not current_user.is_authenticated:
        return False
    if current_user.role == 'admin':
        return True
    if getattr(current_user, 'worker', None) in ('veterinario', 'colaborador'):
        return True
    own_vet = getattr(current_user, 'veterinario', None)
    if own_vet is not None and veterinario_id is not None and getattr(own_vet, 'id', None) == veterinario_id:
        return True
    try:
        if is_veterinarian(current_user):
            return True
    except Exception:
        # Falha ao avaliar perfil → trata como não-profissional (perfil público, fail-safe).
        pass
    return False


def _render_vet_public_profile(veterinario):
    """Perfil público do veterinário, voltado ao tutor — sem expor a agenda."""
    from models import Animal

    form = AppointmentRequestForm()
    animals = []
    if current_user.is_authenticated:
        animals = (
            Animal.query
            .filter(Animal.user_id == current_user.id, Animal.removido_em.is_(None))
            .order_by(Animal.name)
            .all()
        )
    form.animal_id.choices = [(a.id, a.name) for a in animals]

    end = getattr(veterinario.user, 'endereco', None)
    cidade = end.cidade.strip() if end and end.cidade else None
    audience = _current_professional_service_audience()
    services = [
        service for service in _professional_service_query(
            audience=audience,
            active_only=True,
        )
        if service.veterinario_id == veterinario.id
    ]

    return render_template(
        'veterinarios/vet_public.html',
        veterinario=veterinario,
        form=form,
        animals=animals,
        cidade=cidade,
        services=services,
        audience=audience,
        price_options=_service_public_price_options,
        format_reais=_format_reais,
    )
















def _resolve_record_panel(args, listing_params=(), default='create'):
    raw_panel = (args.get('panel') or '').strip().lower()
    create_values = {'create', 'form', 'new', 'novo', 'cadastro'}
    list_values = {'list', 'listing', 'records', 'cadastrados', 'listagem'}

    if raw_panel in create_values:
        return 'create'
    if raw_panel in list_values:
        return 'list'
    if any(param in args for param in listing_params):
        return 'list'
    return default






def _can_request_share(user):
    worker = (getattr(user, 'worker', None) or '').lower()
    if worker in {'veterinario', 'colaborador'}:
        return True
    return getattr(user, 'role', None) == 'admin'


def _share_request_target_animals(tutor_id, animal_id):
    animal = None
    if animal_id:
        animal = Animal.query.get_or_404(animal_id)
        if animal.user_id != tutor_id:
            raise ValueError('Animal não pertence ao tutor informado.')
    return animal




def _share_request_or_404(request_id):
    share_request = DataShareRequest.query.get_or_404(request_id)
    if share_request.tutor_id != current_user.id:
        abort(404)
    return share_request


def _ensure_pending(share_request):
    if not share_request.is_pending():
        abort(400, description='Pedido já foi processado ou expirou.')


def _activate_share_request(share_request, expires_in_days=None):
    now = utcnow()
    expires_at = share_request.expires_at
    if expires_in_days:
        expires_at = now + timedelta(days=_default_share_duration(expires_in_days))
    elif not expires_at or expires_at <= now:
        expires_at = now + timedelta(days=_default_share_duration(None))
    tutor = share_request.tutor
    party = (DataSharePartyType.clinic, share_request.clinic_id)
    access = find_active_share([party], user_id=share_request.tutor_id, animal_id=share_request.animal_id)
    if access:
        access.expires_at = expires_at
        access.grant_reason = share_request.message or access.grant_reason
        access.granted_by = current_user.id
        access.granted_via = 'share_request'
    else:
        access = DataShareAccess(
            user_id=share_request.tutor_id,
            animal_id=share_request.animal_id,
            source_clinic_id=getattr(tutor, 'clinica_id', None),
            granted_to_type=DataSharePartyType.clinic,
            granted_to_id=share_request.clinic_id,
            granted_by=current_user.id,
            grant_reason=share_request.message,
            granted_via='share_request',
            expires_at=expires_at,
        )
        db.session.add(access)
    share_request.status = 'approved'
    share_request.approved_at = now
    share_request.approved_by_id = current_user.id
    share_request.denied_at = None
    share_request.denial_reason = None
    db.session.add(share_request)
    db.session.flush()
    log_data_share_event(
        access,
        event_type='share_granted',
        resource_type='user',
        resource_id=share_request.tutor_id,
        actor=current_user,
        notes=f'Pedido #{share_request.id}',
    )
    if share_request.animal_id:
        log_data_share_event(
            access,
            event_type='share_granted',
            resource_type='animal',
            resource_id=share_request.animal_id,
            actor=current_user,
            notes=f'Pedido #{share_request.id}',
        )
    return access























# ——— FICHA DO TUTOR (dados + lista de animais) ————————————
from sqlalchemy.orm import joinedload



























def _normalize_racao_brand_key(value):
    text = " ".join((value or "").strip().lower().split())
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _canonicalize_racao_brand(value):
    text = (value or "").strip()
    corrections = {
        "especial dog": "Special Dog",
        "especialdog": "Special Dog",
        "especial cat": "Special Cat",
        "especialcat": "Special Cat",
    }
    return corrections.get(_normalize_racao_brand_key(text), text)








from sqlalchemy.orm import aliased
from sqlalchemy import desc, and_, or_

from collections import defaultdict



def _build_delivery_research_message(tutor_name, animal_name):
    tutor_name = (tutor_name or "tutor").strip()
    if isinstance(animal_name, (list, tuple)):
        animal_names = [str(item).strip() for item in animal_name if str(item).strip()]
    else:
        animal_names = [str(animal_name).strip()] if str(animal_name or "").strip() else []

    if not animal_names:
        pet_intro = "do seu pet"
        pet_question = "seu pet"
        pet_subject = "ele"
    elif len(animal_names) == 1:
        pet_intro = f"do {animal_names[0]}"
        pet_question = animal_names[0]
        pet_subject = animal_names[0]
    elif len(animal_names) == 2:
        joined_names = f"{animal_names[0]} e {animal_names[1]}"
        pet_intro = f"dos pets {joined_names}"
        pet_question = "eles"
        pet_subject = joined_names
    else:
        joined_names = ", ".join(animal_names[:-1]) + f" e {animal_names[-1]}"
        pet_intro = f"dos pets {joined_names}"
        pet_question = "eles"
        pet_subject = joined_names

    return (
        f"Oi, {tutor_name}! Tudo bem?\n\n"
        f"Aqui \u00e9 o Lucas Marcelino, m\u00e9dico veterin\u00e1rio. Vi aqui o cadastro {pet_intro} e estou organizando "
        "em Orl\u00e2ndia um servi\u00e7o de entrega r\u00e1pida de ra\u00e7\u00e3o, direto na casa do tutor, para facilitar "
        "o dia a dia e evitar faltar ra\u00e7\u00e3o.\n\n"
        "Queria validar rapidinho com voc\u00ea:\n\n"
        "Se tivesse ra\u00e7\u00e3o com pre\u00e7o igual ou melhor que os sites, com entrega r\u00e1pida, voc\u00ea compraria?\n\n"
        "1 - Sim\n"
        "2 - Talvez\n"
        "3 - N\u00e3o\n\n"
        "Se puder, me ajuda com mais algumas informa\u00e7\u00f5es:\n\n"
        f"- Qual ra\u00e7\u00e3o {pet_question} usa hoje?\n"
        "- Qual o tamanho do saco?\n"
        "- Quanto voc\u00ea costuma pagar nesse saco?\n"
        "Se n\u00e3o souber o valor exato, pode ser uma faixa:\n"
        "at\u00e9 R$50 / R$50-100 / R$100-150 / R$150-200 / R$200-250 / acima de R$250\n\n"
        "- Onde voc\u00ea costuma comprar?\n"
        "(pet shop, agropecu\u00e1ria, internet ou outro)\n\n"
        f"- E normalmente esse saco de ra\u00e7\u00e3o de {pet_subject} dura quanto tempo?\n\n"
        "Se fizer sentido, posso te avisar quando come\u00e7armos com condi\u00e7\u00f5es especiais."
    )


def _build_whatsapp_research_url(phone, message):
    phone_digits = digits_only(formatar_telefone(phone or ""))
    if not phone_digits:
        return None
    return f"https://api.whatsapp.com/send?phone={phone_digits}&text={urlencode({'text': message})[5:]}"


def _latest_racao_for_animal(animal):
    racoes = sorted(
        getattr(animal, "racoes", []) or [],
        key=lambda item: item.data_cadastro.timestamp() if item.data_cadastro else float("-inf"),
        reverse=True,
    )
    return racoes[0] if racoes else None


def _delivery_research_contact_table_available():
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("delivery_research_contact"):
            return False
        columns = {
            column.get("name")
            for column in inspector.get_columns("delivery_research_contact")
        }
        required = {
            "id",
            "tutor_id",
            "sent",
            "sent_at",
            "sent_by_id",
            "replied",
            "replied_at",
            "replied_by_id",
            "recorded",
            "recorded_at",
            "recorded_by_id",
            "do_not_send",
            "do_not_send_at",
            "do_not_send_by_id",
            "interest_answer",
            "current_food",
            "bag_size",
            "price_paid",
            "purchase_channel",
            "duration_estimate",
            "response_notes",
            "response_collected_at",
            "created_at",
            "updated_at",
        }
        return required.issubset(columns)
    except (ProgrammingError, OperationalError, NoSuchTableError):
        return False


def _delivery_research_stage(status):
    if status and getattr(status, "do_not_send", False):
        return "do_not_send"
    if status and getattr(status, "recorded", False):
        return "recorded"
    if status and getattr(status, "replied", False):
        return "replied"
    if status and getattr(status, "sent", False):
        return "sent"
    return "pending"


def _delivery_research_stage_label(stage):
    labels = {
        "pending": "Falta enviar",
        "sent": "Ja enviei",
        "replied": "Ja responderam",
        "recorded": "Ja cadastrei",
        "do_not_send": "Nao enviar agora",
    }
    return labels.get(stage, "Falta enviar")


def _delivery_research_interest_label(value):
    labels = {
        "1": "Sim",
        "2": "Talvez",
        "3": "Nao",
    }
    return labels.get((value or "").strip(), value or "Nao informado")


def _parse_delivery_research_price(value):
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.lower().replace("r$", "").replace(" ", "")
    normalized = normalized.replace(".", "").replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _split_delivery_research_food_label(value):
    raw = (value or "").strip()
    if not raw:
        return (None, None)
    if " - " in raw:
        marca, linha = raw.split(" - ", 1)
        return (_canonicalize_racao_brand(marca) or raw, linha.strip() or None)
    return (_canonicalize_racao_brand(raw), None)


def _delivery_research_food_label_for_type(tipo_racao):
    if not tipo_racao:
        return None
    marca = (tipo_racao.marca or "").strip()
    linha = (tipo_racao.linha or "").strip()
    if marca and linha:
        return f"{marca} - {linha}"
    return marca or linha or None


def _find_tipo_racao_for_delivery_research_label(value):
    marca, linha = _split_delivery_research_food_label(value)
    if not marca:
        return None
    return TipoRacao.query.filter_by(marca=marca, linha=linha).first()


def _sync_delivery_research_answers_to_racoes(tutor, contact, selected_animal_ids):
    if not contact or not contact.current_food:
        return 0

    selected_ids = {int(item) for item in selected_animal_ids if str(item).isdigit()}
    animais = [
        animal for animal in (tutor.animals or [])
        if not getattr(animal, "removido_em", None) and (not selected_ids or animal.id in selected_ids)
    ]
    if not animais:
        return 0

    tipo_racao = _find_tipo_racao_for_delivery_research_label(contact.current_food)
    if tipo_racao is None:
        marca, linha = _split_delivery_research_food_label(contact.current_food)
        if not marca:
            return 0

        tipo_racao = TipoRacao(
            marca=marca,
            linha=linha,
            created_by=current_user.id,
        )
        db.session.add(tipo_racao)
        db.session.flush()
        try:
            list_rations.cache_clear()
        except Exception:
            pass
    elif not getattr(tipo_racao, "id", None):
        return 0

    preco_pago = _parse_delivery_research_price(contact.price_paid)
    bag_size = contact.bag_size or None
    collected_at = contact.response_collected_at or utcnow()
    observacoes = [
        "Pesquisa de tutores",
        f"Coletado em {collected_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')}" if collected_at else None,
        f"Canal de compra: {contact.purchase_channel}" if contact.purchase_channel else None,
        f"Duracao estimada: {contact.duration_estimate}" if contact.duration_estimate else None,
        f"Interesse: {_delivery_research_interest_label(contact.interest_answer)}" if contact.interest_answer else None,
        f"Observacoes: {contact.response_notes}" if contact.response_notes else None,
    ]
    observacoes_racao = "\n".join(item for item in observacoes if item)

    synced = 0
    for animal in animais:
        latest_racao = _latest_racao_for_animal(animal)
        should_update_latest = (
            latest_racao is not None
            and latest_racao.tipo_racao_id == tipo_racao.id
            and (latest_racao.tamanho_embalagem or None) == bag_size
            and (latest_racao.preco_pago or None) == preco_pago
            and latest_racao.created_by == current_user.id
            and (latest_racao.observacoes_racao or "").startswith("Pesquisa de tutores")
        )

        if should_update_latest:
            latest_racao.observacoes_racao = observacoes_racao
            latest_racao.data_cadastro = collected_at
            synced += 1
            continue

        db.session.add(
            Racao(
                animal_id=animal.id,
                tipo_racao_id=tipo_racao.id,
                observacoes_racao=observacoes_racao,
                preco_pago=preco_pago,
                tamanho_embalagem=bag_size,
                created_by=current_user.id,
                data_cadastro=collected_at,
            )
        )
        synced += 1

    return synced


def _build_delivery_research_contact_map():
    return {
        item["tutor"].id: item
        for item in _build_delivery_research_contacts()
    }


def _get_or_create_delivery_research_contact(tutor_id):
    status = DeliveryResearchContact.query.filter_by(tutor_id=tutor_id).first()
    if status is not None:
        return status

    status = DeliveryResearchContact(tutor_id=tutor_id)
    db.session.add(status)
    return status


def _commit_delivery_research_contact_changes(tutor_id):
    try:
        db.session.commit()
        return DeliveryResearchContact.query.filter_by(tutor_id=tutor_id).first()
    except IntegrityError:
        db.session.rollback()
        return DeliveryResearchContact.query.filter_by(tutor_id=tutor_id).first()


def _run_whatsapp_batch_selenium(batch_items, warmup_only=False):
    if not batch_items and not warmup_only:
        return {"results": []}

    script_path = PROJECT_ROOT / "scripts" / "send_whatsapp_batch_selenium.py"
    if not script_path.exists():
        raise RuntimeError("Script de envio em lote nao encontrado.")

    temp_root = PROJECT_ROOT / "instance" / "whatsapp_batch"
    temp_root.mkdir(parents=True, exist_ok=True)
    batch_dir = temp_root / uuid.uuid4().hex
    batch_dir.mkdir(parents=True, exist_ok=True)

    input_path = batch_dir / "input.json"
    output_path = batch_dir / "output.json"

    try:
        input_path.write_text(json.dumps({"items": batch_items}, ensure_ascii=False), encoding="utf-8")

        command = [
            r"C:\edb\languagepack\v3\Python-3.10\python.exe",
            str(script_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
        if warmup_only:
            command.append("--warmup-only")

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=1800,
        )

        if not output_path.exists():
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or "Falha no envio em lote.").strip())
            raise RuntimeError("O script de envio nao gerou arquivo de resultado.")

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if completed.returncode != 0:
            payload["process_error"] = (completed.stderr or completed.stdout or "Falha no envio em lote.").strip()
        return payload
    finally:
        for temp_file in (input_path, output_path):
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass
        try:
            batch_dir.rmdir()
        except OSError:
            pass


def _build_delivery_research_contacts():
    status_available = _delivery_research_contact_table_available()

    query = (
        User.query
        .join(Animal, Animal.user_id == User.id)
        .options(
            selectinload(User.animals)
            .selectinload(Animal.racoes)
            .joinedload(Racao.tipo_racao),
        )
        .distinct()
        .order_by(User.name.asc(), User.id.asc())
    )

    if status_available:
        query = query.options(joinedload(User.delivery_research_contact))

    tutors = query.all()

    contatos = []
    for tutor in tutors:
        animais = sorted(
            [animal for animal in (tutor.animals or []) if not getattr(animal, "removido_em", None)],
            key=lambda item: ((item.name or "").lower(), item.id),
        )
        nomes_animais = [animal.name for animal in animais if animal.name]
        mensagem = _build_delivery_research_message(tutor.name, nomes_animais)
        latest_racoes = []
        for animal in animais:
            racao = _latest_racao_for_animal(animal)
            if racao:
                latest_racoes.append(
                    {
                        "animal_id": animal.id,
                        "animal_nome": animal.name or "Pet sem nome",
                        "racao": racao,
                    }
                )

        status_envio = getattr(tutor, "delivery_research_contact", None) if status_available else None
        stage = _delivery_research_stage(status_envio)
        current_food_option = None
        current_food_manual = ""
        if status_envio and status_envio.current_food:
            current_food_option = _find_tipo_racao_for_delivery_research_label(status_envio.current_food)
            if current_food_option is None:
                current_food_manual = status_envio.current_food

        contatos.append(
            {
                "tutor": tutor,
                "animais": animais,
                "nomes_animais": nomes_animais,
                "mensagem": mensagem,
                "whatsapp_url": _build_whatsapp_research_url(getattr(tutor, "phone", None), mensagem),
                "status_envio": status_envio,
                "status_disponivel": status_available,
                "stage": stage,
                "stage_label": _delivery_research_stage_label(stage),
                "interest_label": _delivery_research_interest_label(getattr(status_envio, "interest_answer", None)) if status_envio else "Nao informado",
                "current_food_option_id": current_food_option.id if current_food_option else None,
                "current_food_manual": current_food_manual,
                "response_collected_label": (
                    status_envio.response_collected_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')
                    if status_envio and getattr(status_envio, "response_collected_at", None)
                    else None
                ),
                "do_not_send_label": (
                    status_envio.do_not_send_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')
                    if status_envio and getattr(status_envio, "do_not_send_at", None)
                    else None
                ),
                "racoes_recentes": latest_racoes,
            }
        )

    return contatos


























from datetime import datetime












from flask import request, jsonify










_MEDICATION_SEARCH_CACHE = {}
_MEDICATION_SEARCH_CACHE_TTL = 180
_MEDICATION_SEARCH_CACHE_MAX = 256


def _clear_medication_search_cache():
    _MEDICATION_SEARCH_CACHE.clear()


def _get_medication_search_cache(cache_key):
    entry = _MEDICATION_SEARCH_CACHE.get(cache_key)
    if not entry:
        return None
    payload, ts = entry
    if _stdlib_time.monotonic() - ts > _MEDICATION_SEARCH_CACHE_TTL:
        _MEDICATION_SEARCH_CACHE.pop(cache_key, None)
        return None
    return payload


def _set_medication_search_cache(cache_key, payload):
    if len(_MEDICATION_SEARCH_CACHE) >= _MEDICATION_SEARCH_CACHE_MAX:
        oldest_key = min(
            _MEDICATION_SEARCH_CACHE,
            key=lambda key: _MEDICATION_SEARCH_CACHE[key][1],
        )
        _MEDICATION_SEARCH_CACHE.pop(oldest_key, None)
    _MEDICATION_SEARCH_CACHE[cache_key] = (payload, _stdlib_time.monotonic())
    return payload























def _normalizar_instrucoes_prescricao(texto):
    if not texto:
        return ''
    if not isinstance(texto, str):
        texto = str(texto)
    return texto.replace('\r\n', '\n').replace('\r', '\n').strip()










def _current_user_owns_animal(animal) -> bool:
    return bool(
        current_user.is_authenticated
        and animal
        and getattr(animal, 'user_id', None) == current_user.id
    )






def _tratamento_acompanhamento_or_404(tratamento_id):
    """Carrega o acompanhamento validando acesso: tutor dono ou equipe da clínica."""
    acompanhamento = TratamentoAcompanhamento.query.get_or_404(tratamento_id)
    if _current_user_owns_animal(acompanhamento.animal):
        return acompanhamento, True
    ensure_clinic_access(acompanhamento.bloco.clinica_id if acompanhamento.bloco else None)
    return acompanhamento, False


















































# app.py  – dentro da rota /novo_animal






















































#Delivery routes
 




from sqlalchemy.orm import selectinload

def _delivery_context_for_current_user():
    """Return sections context and counts for the current user."""
    base = (DeliveryRequest.query
            .filter_by(archived=False)
            .order_by(DeliveryRequest.requested_at.asc())   # FIFO
            .options(
                selectinload(DeliveryRequest.order)          # evita N+1
                .selectinload(Order.user)
            ))

    # -------------------------------------------------------- ENTREGADOR
    if current_user.worker == "delivery":
        # Entregadores só veem entregas da plataforma (não as do próprio vendedor)
        base = base.filter(DeliveryRequest.tipo_entrega == 'plataforma')

        # total (para o badge)
        available_total = base.filter_by(status="pendente").count()

        # só as 3 primeiras pendentes
        available = (base.filter_by(status="pendente")
                          .limit(3)
                          .all())

        doing    = (base.filter_by(worker_id=current_user.id,
                                   status="em_andamento")
                         .order_by(DeliveryRequest.accepted_at.desc())
                         .all())

        done     = (base.filter_by(worker_id=current_user.id,
                                   status="concluida")
                         .order_by(DeliveryRequest.completed_at.desc())
                         .all())

        canceled = (base.filter_by(worker_id=current_user.id,
                                   status="cancelada")
                         .order_by(DeliveryRequest.canceled_at.desc())
                         .all())
    # -------------------------------------------------------- CLIENTE
    else:
        base = base.filter_by(requested_by_id=current_user.id)

        available_total = 0
        available = []                                          # não exibe

        doing    = base.filter_by(status="em_andamento").all()
        done     = base.filter_by(status="concluida").all()
        canceled = base.filter_by(status="cancelada").all()

    context = dict(
        available=available,
        doing=doing,
        done=done,
        canceled=canceled,
        available_total=available_total,
    )

    counts = {
        "available_total": available_total,
        "doing": len(doing),
        "done": len(done),
        "canceled": len(canceled),
    }

    return context, counts


def _delivery_sections_payload():
    context, counts = _delivery_context_for_current_user()
    html = render_template("entregas/_delivery_sections.html", **context)
    return html, counts, context







# --- Compatibilidade admin ---------------------------------

# --- Compatibilidade entregador ----------------------------





def _wants_json_response():
    accept = (request.headers.get('Accept') or '').lower()
    xrw = (request.headers.get('X-Requested-With') or '').lower()
    return 'application/json' in accept or xrw == 'xmlhttprequest'


def _delivery_error_response(message, category='danger', status=400):
    payload = {
        'message': message,
        'category': category,
        'redirect': None,
    }
    try:
        html, counts, _ = _delivery_sections_payload()
        payload.setdefault('html', html)
        payload.setdefault('counts', counts)
    except Exception as exc:  # pragma: no cover - fallback only
        current_app.logger.exception('Erro ao montar payload de entrega', exc_info=exc)
    return jsonify(payload), status












# routes_delivery.py  (ou app.py)
from sqlalchemy.orm import joinedload




# routes_delivery.py  (ou app.py)

def _build_tutor_map_data():
    tutors = (
        User.query.join(Endereco, Endereco.id == User.endereco_id)
        .options(joinedload(User.endereco))
        .filter(and_(Endereco.latitude.isnot(None), Endereco.longitude.isnot(None)))
        .order_by(User.name)
        .all()
    )

    raw_markers = []
    for tutor in tutors:
        endereco = tutor.endereco
        if not endereco:
            continue

        raw_markers.append({
            'id': tutor.id,
            'name': tutor.name,
            'lat': endereco.latitude,
            'lng': endereco.longitude,
            'address': endereco.full,
            'profile_url': url_for('ficha_tutor', tutor_id=tutor.id),
            'photo': getattr(tutor, 'profile_photo', None),
            'initials': _user_initials_from_name(getattr(tutor, 'name', None)),
            'gender': getattr(tutor, 'gender', None),
        })

    markers = []
    grouped_by_coord = defaultdict(list)
    for marker in raw_markers:
        grouped_by_coord[(marker['lat'], marker['lng'])].append(marker)

    for (lat, lng), group in grouped_by_coord.items():
        if len(group) == 1:
            markers.append(group[0])
            continue

        angle_step = (2 * math.pi) / len(group)
        # Pequeno deslocamento (~20 m) para evitar sobreposição visual dos marcadores
        offset = 0.0002
        for idx, marker in enumerate(group):
            angle = angle_step * idx
            lat_adjust = math.sin(angle) * offset
            lng_adjust = (math.cos(angle) * offset) / max(0.0001, math.cos(math.radians(lat)))

            markers.append({
                **marker,
                'lat': lat + lat_adjust,
                'lng': lng + lng_adjust,
            })

    default_center = [-20.7202, -47.8852]
    if markers:
        avg_lat = sum(marker['lat'] for marker in markers) / len(markers)
        avg_lng = sum(marker['lng'] for marker in markers) / len(markers)
        map_center = [avg_lat, avg_lng]
    else:
        map_center = default_center

    return {
        'markers': markers,
        'default_center': map_center,
        'total_tutores': len(tutors),
        'total_animais': Animal.query.filter(Animal.removido_em.is_(None)).count(),
    }


def _build_missing_tutor_geocodes():
    missing_tutors = (
        User.query.join(Endereco, Endereco.id == User.endereco_id)
        .options(joinedload(User.endereco))
        .filter(or_(Endereco.latitude.is_(None), Endereco.longitude.is_(None)))
        .order_by(User.name)
        .all()
    )

    return [
        {
            'id': tutor.id,
            'name': tutor.name,
            'address': tutor.endereco.full if tutor.endereco else '',
            'profile_url': url_for('ficha_tutor', tutor_id=tutor.id),
        }
        for tutor in missing_tutors
    ]




























def _export_data_share_logs_csv(logs):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID',
        'Data',
        'Evento',
        'Recurso',
        'Recurso ID',
        'Tutor ID',
        'Animal ID',
        'Clínica Origem',
        'Destinatário',
        'Destinatário ID',
        'Ator',
        'IP',
        'Endpoint',
    ])
    for log in logs:
        access = getattr(log, 'access', None)
        writer.writerow([
            log.id,
            log.occurred_at.isoformat() if log.occurred_at else '',
            log.event_type,
            log.resource_type,
            log.resource_id or '',
            access.user_id if access else '',
            access.animal_id if access else '',
            access.source_clinic_id if access else '',
            access.granted_to_type.value if access and access.granted_to_type else '',
            access.granted_to_id if access else '',
            log.actor_id or '',
            log.request_ip or '',
            log.request_path or '',
        ])
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=data-share-logs.csv'
    return response


def _export_data_share_logs_pdf(logs):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40
    for log in logs:
        access = getattr(log, 'access', None)
        lines = [
            f"{log.occurred_at:%Y-%m-%d %H:%M:%S} – {log.event_type} {log.resource_type} #{log.resource_id or '-'}",
            f"Tutor #{access.user_id if access else '-'} | Animal #{access.animal_id if access else '-'} | Clínica #{access.source_clinic_id if access else '-'}",
            f"Destinatário {access.granted_to_type.value if access and access.granted_to_type else '-'} #{access.granted_to_id if access else '-'} | Ator #{log.actor_id or '-'}",
            f"IP {log.request_ip or '-'} | {log.request_path or ''}",
        ]
        for text in lines:
            if y < 40:
                pdf.showPage()
                y = height - 40
            pdf.drawString(36, y, text[:130])
            y -= 16
        y -= 8
    pdf.save()
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='data-share-logs.pdf',
    )





# ========================================================
#  PAGAMENTO – Mercado Pago (Checkout Pro PIX) - CORRECTED
# ========================================================

import hmac, hashlib, mercadopago
from decimal   import Decimal
from functools import cache
from datetime  import datetime, timedelta

from flask import (
    render_template, redirect, url_for, flash, session,
    request, jsonify, abort, current_app
)
from flask_login import login_required, current_user

from forms import AddToCartForm, CheckoutForm, CartAddressForm  # Added CheckoutForm for CSRF

# ─────────────────────────────────────────────────────────
#  SDK (lazy – lê token do config)
# ─────────────────────────────────────────────────────────
@cache
def mp_sdk(access_token=None):
    return mercadopago.SDK(access_token or current_app.config["MERCADOPAGO_ACCESS_TOKEN"])


def _connected_mercadopago_account_for_order(order):
    seller_keys = {
        (item.product.clinica_id, item.product.casa_de_racao_id)
        for item in (order.items or [])
        if item.product and (item.product.clinica_id or item.product.casa_de_racao_id)
    }
    if len(seller_keys) != 1:
        return None
    clinica_id, casa_id = next(iter(seller_keys))

    account = (
        StorePaymentAccount.query
        .filter_by(
            clinica_id=clinica_id,
            casa_de_racao_id=casa_id,
            provider='mercado_pago',
            status='connected',
        )
        .first()
    )
    if account and account.is_connected:
        return account
    return None


def _mp_auto_return_enabled(back_urls: dict) -> bool:
    """Return True when Mercado Pago auto_return can safely be enabled."""
    success_url = (back_urls or {}).get('success')
    if not success_url:
        return False
    return urlparse(success_url).scheme == 'https'


class PaymentPreferenceError(RuntimeError):
    """Exception raised when Mercado Pago preference creation fails."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _mercadopago_notification_url() -> str:
    """Return the webhook URL used by Mercado Pago notifications."""

    configured = (current_app.config.get('MERCADOPAGO_NOTIFICATION_URL') or '').strip()
    if configured:
        return configured

    if not has_request_context():
        raise RuntimeError(
            'MERCADOPAGO_NOTIFICATION_URL não configurado e url_for fora do request context.',
        )

    preferred_scheme = current_app.config.get('PREFERRED_URL_SCHEME')
    forwarded_proto = (request.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip()
    url_kwargs = {'_external': True}
    if preferred_scheme:
        url_kwargs['_scheme'] = preferred_scheme
    elif forwarded_proto in {'http', 'https'}:
        url_kwargs['_scheme'] = forwarded_proto
    elif request.is_secure:
        url_kwargs['_scheme'] = 'https'
    else:
        url_kwargs['_scheme'] = 'https'

    return url_for('notificacoes_mercado_pago', **url_kwargs)


def _criar_preferencia_pagamento(items, external_reference: str, back_url: str):
    """Create a Mercado Pago payment preference for the given items."""

    if not items:
        raise PaymentPreferenceError('Nenhum item no orçamento.', status_code=400)

    normalized_items = []
    for item in items:
        normalized_items.append({
            'id': str(item.get('id')),
            'title': item.get('title'),
            'quantity': int(item.get('quantity', 1) or 1),
            'unit_price': float(item.get('unit_price', 0)),
        })

    back_urls = {key: back_url for key in ('success', 'failure', 'pending')}
    preference_data = {
        'items': normalized_items,
        'external_reference': external_reference,
        'notification_url': _mercadopago_notification_url(),
        'statement_descriptor': current_app.config.get('MERCADOPAGO_STATEMENT_DESCRIPTOR'),
        'back_urls': back_urls,
    }
    if _mp_auto_return_enabled(back_urls):
        preference_data['auto_return'] = 'approved'

    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception('Erro de conexão com Mercado Pago: %s', exc)
        raise PaymentPreferenceError('Falha ao conectar com Mercado Pago.', status_code=502) from exc

    if resp.get('status') != 201:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        raise PaymentPreferenceError('Erro ao iniciar pagamento.', status_code=502)

    pref = resp.get('response') or {}
    payment_url = pref.get('init_point')
    if not payment_url:
        raise PaymentPreferenceError('Retorno de pagamento inválido.', status_code=502)

    return {
        'payment_url': payment_url,
        'preference': pref,
        'payment_reference': str(pref.get('id') or pref.get('external_reference') or external_reference),
    }


# Caches for frequently requested lists
@cache
def list_species():
    """Return a lightweight list of species as dictionaries."""
    return [
        {"id": sp.id, "name": sp.name}
        for sp in Species.query.order_by(Species.name).all()
    ]


@cache
def list_breeds():
    """Return a lightweight, display-deduplicated list of breeds.

    O banco pode conter aliases importados (ex.: ``SRD``, ``Sem Raça
    Definida``, ``SRD (Sem Raça Definida)``). Para o usuário, isso deve
    aparecer uma vez só no dropdown.
    """
    import unicodedata

    def _breed_display_key(name):
        raw = (name or "").strip()
        normalized = unicodedata.normalize("NFKD", raw)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        token = " ".join(normalized.lower().replace("-", " ").split())
        if token in {
            "srd",
            "sem raca definida",
            "srd sem raca definida",
            "vira lata",
            "viralata",
            "mestico",
        }:
            return "srd"
        return token

    rows = Breed.query.order_by(Breed.name, Breed.id).all()
    seen = set()
    result = []
    for br in rows:
        key = _breed_display_key(br.name)
        if key in seen:
            continue
        seen.add(key)
        result.append({"id": br.id, "name": "SRD" if key == "srd" else br.name, "species_id": br.species_id})
    return result


def _normalize_clinic_ids(clinic_scope):
    """Return a sanitized list of clinic IDs from ``clinic_scope``."""

    if not clinic_scope:
        return []
    if isinstance(clinic_scope, (list, tuple, set)):
        return [cid for cid in clinic_scope if cid]
    return [clinic_scope] if clinic_scope else []


def _is_specialist_veterinarian(vet_profile):
    """Return ``True`` if the veterinarian acts only as a specialist."""

    if not vet_profile:
        return False

    primary = getattr(vet_profile, 'clinica_id', None)
    associated = getattr(vet_profile, 'clinicas', None) or []
    return primary is None and bool(associated)


def _veterinarian_accessible_clinic_ids(vet_profile):
    """Return clinic IDs a veterinarian can operate in."""

    if not vet_profile:
        return []

    clinic_ids = []
    primary = getattr(vet_profile, 'clinica_id', None)
    if primary:
        clinic_ids.append(primary)

    for clinic in getattr(vet_profile, 'clinicas', []) or []:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    # Clinics the vet's user owns (owner_id == user.id) may not appear in the
    # two sets above when the Veterinario record predates the Clinica or when
    # the staff link was never set.
    for clinic in getattr(getattr(vet_profile, 'user', None), 'clinicas', []) or []:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _viewer_accessible_clinic_ids(viewer):
    """Return clinic IDs accessible to ``viewer`` preserving priority order."""

    clinic_ids = []
    if not viewer:
        return clinic_ids

    viewer_clinic = getattr(viewer, 'clinica_id', None)
    if viewer_clinic and viewer_clinic not in clinic_ids:
        clinic_ids.append(viewer_clinic)

    vet_profile = getattr(viewer, 'veterinario', None)
    for clinic_id in _veterinarian_accessible_clinic_ids(vet_profile):
        if clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _normalize_role_scope(scope_value, *, allow_global):
    """Normalize list/dashboard scope defensively by role capabilities."""

    normalized = (scope_value or '').strip().lower()
    if normalized not in {'all', 'mine'}:
        return 'all' if allow_global else 'mine'
    if normalized == 'all' and not allow_global:
        return 'mine'
    return normalized


def _get_recent_animais(
    scope,
    page,
    clinic_id=None,
    user_id=None,
    require_appointments=False,
    veterinario_id=None,
    search=None,
    sort_option=None,
):
    """Return recent animals and pagination metadata for dashboards."""

    from models import Species, Breed

    viewer = current_user if current_user.is_authenticated else None
    is_admin = bool(viewer and getattr(viewer, 'role', None) == 'admin')
    resolved_scope = _normalize_role_scope(scope, allow_global=is_admin)
    effective_user_id = user_id or (getattr(current_user, 'id', None))
    clinic_ids = _normalize_clinic_ids(clinic_id)

    if resolved_scope == 'mine' and not effective_user_id:
        resolved_scope = 'all'

    base_query = Animal.query.filter(Animal.removido_em.is_(None))

    search_value = (search or '').strip().lower()
    sort_value = (sort_option or 'date_desc').strip().lower() or 'date_desc'
    per_page = 9

    species_alias = aliased(Species)
    breed_alias = aliased(Breed)

    def apply_search_filters(query):
        if not search_value:
            return query
        term = f"%{search_value}%"
        return (
            query.outerjoin(species_alias, Animal.species)
            .outerjoin(breed_alias, Animal.breed)
            .filter(
                or_(
                    func.lower(func.coalesce(Animal.name, '')).like(term),
                    func.lower(func.coalesce(Animal.description, '')).like(term),
                    func.lower(func.coalesce(species_alias.name, '')).like(term),
                    func.lower(func.coalesce(breed_alias.name, '')).like(term),
                    func.lower(func.coalesce(Animal.modo, '')).like(term),
                )
            )
        )

    def apply_sorting(query, last_reference=None):
        query = query.order_by(None)

        name_column = func.lower(func.coalesce(Animal.name, ''))
        age_expr = case(
            (Animal.date_of_birth != None, Animal.date_of_birth),
            else_=Animal.date_added,
        )

        if sort_value == 'name_asc':
            return query.order_by(name_column.asc(), Animal.id.asc())
        if sort_value == 'name_desc':
            return query.order_by(name_column.desc(), Animal.id.asc())
        if sort_value == 'date_asc':
            if last_reference is not None:
                return query.order_by(last_reference.asc(), Animal.id.asc())
            return query.order_by(Animal.date_added.asc(), Animal.id.asc())
        if sort_value == 'date_desc':
            if last_reference is not None:
                return query.order_by(last_reference.desc(), Animal.id.desc())
            return query.order_by(Animal.date_added.desc(), Animal.id.desc())
        if sort_value == 'age_asc':
            return query.order_by(age_expr.desc(), Animal.date_added.desc(), Animal.id.desc())
        if sort_value == 'age_desc':
            return query.order_by(age_expr.asc(), Animal.date_added.desc(), Animal.id.desc())

        # Fallback to recent first when sort option is unknown
        if last_reference is not None:
            return query.order_by(last_reference.desc(), Animal.id.desc())
        return query.order_by(Animal.date_added.desc(), Animal.id.desc())

    last_reference = None

    if resolved_scope == 'mine' and effective_user_id:
        query = base_query
        if clinic_ids and not require_appointments:
            query = query.filter(Animal.clinica_id.in_(clinic_ids))

        if require_appointments and clinic_ids:
            appointment_exists = (
                db.session.query(Appointment.id)
                .filter(
                    Appointment.animal_id == Animal.id,
                    Appointment.clinica_id.in_(clinic_ids),
                )
            )
            if veterinario_id:
                appointment_exists = appointment_exists.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            query = query.filter(appointment_exists.exists())

        consultas_exist = (
            db.session.query(Consulta.id)
            .filter(
                Consulta.animal_id == Animal.id,
                Consulta.created_by == effective_user_id,
            )
        )

        query = query.filter(
            or_(
                Animal.added_by_id == effective_user_id,
                consultas_exist.exists(),
            )
        )
    elif clinic_ids:
        if require_appointments:
            last_appt_query = (
                db.session.query(
                    Appointment.animal_id,
                    func.max(Appointment.scheduled_at).label('last_at'),
                )
                .filter(Appointment.clinica_id.in_(clinic_ids))
            )
            if veterinario_id:
                last_appt_query = last_appt_query.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            last_appt = last_appt_query.group_by(Appointment.animal_id).subquery()
            query = base_query.join(last_appt, Animal.id == last_appt.c.animal_id)
            last_reference = last_appt.c.last_at
        else:
            last_appt = (
                db.session.query(
                    Appointment.animal_id,
                    func.max(Appointment.scheduled_at).label('last_at'),
                )
                .filter(Appointment.clinica_id.in_(clinic_ids))
                .group_by(Appointment.animal_id)
                .subquery()
            )
            query = (
                base_query.outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
                .filter(Animal.clinica_id.in_(clinic_ids))
            )
            last_reference = func.coalesce(last_appt.c.last_at, Animal.date_added)
    else:
        query = base_query
        if effective_user_id and not is_admin:
            query = query.filter(Animal.added_by_id == effective_user_id)

    query = apply_search_filters(query)
    if search_value:
        query = query.group_by(Animal.id)
        # Wrap last_reference in max() so it's valid with GROUP BY
        if last_reference is not None:
            last_reference = func.max(last_reference)
    query = apply_sorting(query, last_reference)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return pagination.items, pagination, resolved_scope


def _get_recent_tutores(
    scope,
    page,
    clinic_id=None,
    user_id=None,
    require_appointments=False,
    veterinario_id=None,
    search=None,
    sort_option=None,
):
    """Return recent tutors and pagination metadata for dashboards."""

    viewer = current_user if current_user.is_authenticated else None
    is_admin = bool(viewer and getattr(viewer, 'role', None) == 'admin')
    resolved_scope = _normalize_role_scope(scope, allow_global=is_admin)
    effective_user_id = user_id or getattr(current_user, 'id', None)
    clinic_ids = _normalize_clinic_ids(clinic_id)

    if resolved_scope == 'mine' and not effective_user_id:
        resolved_scope = 'all'

    search_value = (search or '').strip().lower()
    sort_value = (sort_option or 'name_asc').strip().lower() or 'name_asc'
    per_page = 9

    def apply_search_filters(query):
        if not search_value:
            return query
        term = f"%{search_value}%"
        return query.filter(
            or_(
                func.lower(func.coalesce(User.name, '')).like(term),
                func.lower(func.coalesce(User.email, '')).like(term),
                func.lower(func.coalesce(User.cpf, '')).like(term),
                func.lower(func.coalesce(User.phone, '')).like(term),
            )
        )

    def apply_sorting(query):
        query = query.order_by(None)
        name_column = func.lower(func.coalesce(User.name, ''))
        age_expr = case(
            (User.date_of_birth != None, User.date_of_birth),
            else_=User.created_at,
        )

        if sort_value == 'name_desc':
            return query.order_by(name_column.desc(), User.id.asc())
        if sort_value == 'date_desc':
            return query.order_by(User.created_at.desc(), User.id.desc())
        if sort_value == 'date_asc':
            return query.order_by(User.created_at.asc(), User.id.asc())
        if sort_value == 'age_desc':
            return query.order_by(age_expr.asc(), User.created_at.desc(), User.id.desc())
        if sort_value == 'age_asc':
            return query.order_by(age_expr.desc(), User.created_at.desc(), User.id.desc())

        return query.order_by(name_column.asc(), User.id.asc())

    if resolved_scope == 'mine' and effective_user_id:
        base_query = (
            User.query.filter(User.created_at != None)
            .filter(_user_visibility_clause(clinic_scope=clinic_ids))
        )
        if clinic_ids and not require_appointments:
            base_query = base_query.filter(User.clinica_id.in_(clinic_ids))

        if require_appointments and clinic_ids:
            appointment_exists = (
                db.session.query(Appointment.id)
                .filter(
                    Appointment.tutor_id == User.id,
                    Appointment.clinica_id.in_(clinic_ids),
                )
            )
            if veterinario_id:
                appointment_exists = appointment_exists.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            base_query = base_query.filter(appointment_exists.exists())

        consultas_exist = (
            db.session.query(Consulta.id)
            .join(Animal, Consulta.animal_id == Animal.id)
            .filter(
                Consulta.created_by == effective_user_id,
                Animal.user_id == User.id,
            )
        )

        query = base_query.filter(
            or_(
                User.added_by_id == effective_user_id,
                consultas_exist.exists(),
            )
        )
    elif clinic_ids:
        query = (
            User.query.filter(User.created_at != None)
            .filter(_user_visibility_clause(clinic_scope=clinic_ids))
        )
        if require_appointments:
            appointment_exists = (
                db.session.query(Appointment.id)
                .filter(
                    Appointment.tutor_id == User.id,
                    Appointment.clinica_id.in_(clinic_ids),
                )
            )
            if veterinario_id:
                appointment_exists = appointment_exists.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            query = query.filter(appointment_exists.exists())
        else:
            query = query.filter(User.clinica_id.in_(clinic_ids))
    else:
        query = User.query.filter(User.created_at != None)
        if effective_user_id and not is_admin:
            query = query.filter(User.added_by_id == effective_user_id)

    query = apply_search_filters(query)
    query = apply_sorting(query)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return pagination.items, pagination, resolved_scope


@cache
def list_rations():
    """Return cached ration options without keeping ORM instances alive."""
    return [
        SimpleNamespace(
            id=tipo.id,
            marca=tipo.marca,
            linha=tipo.linha,
            recomendacao=tipo.recomendacao,
        )
        for tipo in TipoRacao.query.order_by(TipoRacao.marca.asc()).all()
    ]


# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────
PENDING_TIMEOUT = timedelta(minutes=20)

def _limpa_pendencia(payment):
    """
    Se o pagamento pendente ainda for válido (PENDING, não expirado e
    com init_point), devolve‑o. Caso contrário zera a chave na sessão.
    """
    if not payment:
        session.pop("last_pending_payment", None)
        return None

    expirou   = (utcnow() - payment.created_at) > PENDING_TIMEOUT
    sem_link  = not getattr(payment, "init_point", None)

    if payment.status != PaymentStatus.PENDING or expirou or sem_link:
        session.pop("last_pending_payment", None)
        return None
    return payment


def _mp_item_payload(it):
    """Return a Mercado Pago item dict with description."""
    if it.product:
        description = it.product.description or it.product.name
        return {
            "id": str(it.product.id),
            "title": it.product.name,
            "description": description,
            "category_id": "others",
            "quantity": int(it.quantity),
            "unit_price": float(it.product.price),
        }
    # Fallback in case product record was removed
    return {
        "id": str(it.id),
        "title": it.item_name,
        "description": it.item_name,
        "category_id": "others",
        "quantity": int(it.quantity),
        "unit_price": float(it.unit_price or 0),
    }


def _money_decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return Decimal("0.00")


def _reprice_order_items(order):
    """Sincroniza itens de carrinho aberto com o preço público atual.

    Carrinhos criados antes de uma mudança de precificação (ex.: taxa
    embutida) carregam ``unit_price`` antigo; aqui todo carrinho é
    "reaberto" com o preço vigente antes de exibir ou cobrar.
    """
    if not order or not getattr(order, "items", None):
        return False
    changed = False
    for item in order.items:
        product = item.product
        if not product:
            continue
        current = product.preco_publico
        if current is None:
            continue
        if item.unit_price is None or _money_decimal(item.unit_price) != current:
            item.unit_price = current
            changed = True
    if changed:
        db.session.commit()
    return changed


def _order_vendor_shipping(order):
    """Return per-store shipping lines for a cart/order."""
    if not order or not getattr(order, 'items', None):
        return {
            "stores": [],
            "products_total": Decimal("0.00"),
            "seller_products_total": Decimal("0.00"),
            "shipping_total": Decimal("0.00"),
            "platform_freight_total": Decimal("0.00"),
            "grand_total": Decimal("0.00"),
        }

    grouped = {}
    products_total = Decimal("0.00")
    # Soma dos preços do lojista (repasse); a diferença para products_total
    # (preço público, taxa embutida) é a margem da plataforma.
    seller_products_total = Decimal("0.00")
    for item in order.items:
        product = item.product
        unit_price = _money_decimal(item.unit_price if item.unit_price is not None else (product.preco_publico if product else 0))
        line_total = unit_price * int(item.quantity or 0)
        products_total += line_total
        seller_unit = _money_decimal(product.price if product else 0)
        seller_products_total += seller_unit * int(item.quantity or 0)
        casa_id = product.casa_de_racao_id if product and product.casa_de_racao_id else None
        clinica_id = product.clinica_id if product and product.clinica_id else None
        if not casa_id and not clinica_id:
            continue
        seller_key = (clinica_id, casa_id)
        provider = product.casa_de_racao if casa_id else product.clinica
        entry = grouped.setdefault(
            seller_key,
            {
                "provider": provider,
                "kind": "casa_de_racao" if casa_id else "clinica",
                "seller_id": casa_id or clinica_id,
                "items": [],
                "subtotal": Decimal("0.00"),
            },
        )
        entry["items"].append(item)
        entry["subtotal"] += line_total

    stores = []
    shipping_total = Decimal("0.00")
    # Frete de entregas feitas por parceiro PetOrlândia ('plataforma'):
    # fica retido pela plataforma para repassar ao entregador, não ao lojista.
    platform_freight_total = Decimal("0.00")
    for seller_key, entry in grouped.items():
        provider = entry["provider"]
        freight = _money_decimal(getattr(provider, "valor_frete", 0))
        minimum = _money_decimal(getattr(provider, "pedido_minimo_entrega", 0))
        meets_minimum = not minimum or entry["subtotal"] >= minimum
        modo_entrega = getattr(provider, "modo_entrega", None) or "plataforma"
        shipping_total += freight
        if modo_entrega != "propria":
            platform_freight_total += freight
        stores.append({
            "seller_key": f"{entry['kind']}-{entry['seller_id']}",
            "seller_id": entry["seller_id"],
            "kind": entry["kind"],
            "name": provider.nome if provider else "Estabelecimento",
            "subtotal": entry["subtotal"],
            "freight": freight,
            "modo_entrega": modo_entrega,
            "minimum": minimum,
            "meets_minimum": meets_minimum,
            "prazo_min": getattr(provider, "prazo_entrega_min", None),
            "prazo_max": getattr(provider, "prazo_entrega_max", None),
        })

    return {
        "stores": stores,
        "products_total": products_total,
        "seller_products_total": seller_products_total,
        "shipping_total": shipping_total,
        "platform_freight_total": platform_freight_total,
        "grand_total": products_total + shipping_total,
    }


def _order_checkout_total(order) -> Decimal:
    return _order_vendor_shipping(order)["grand_total"]


def _shipping_items_for_preference(order):
    shipping = _order_vendor_shipping(order)
    items = []
    for store in shipping["stores"]:
        if store["freight"] <= 0:
            continue
        items.append({
            "id": f"frete-{store['seller_key']}",
            "title": f"Frete - {store['name']}",
            "description": f"Entrega da loja {store['name']}",
            "category_id": "services",
            "quantity": 1,
            "unit_price": float(store["freight"]),
        })
    return items


# Helper to fetch the current order from session and verify ownership
def _get_current_order():
    order_id = session.get("current_order")
    if not order_id:
        return None

    order = Order.query.get(order_id)

    # Se o pedido não existe mais ou pertence a outro usuário, limpa a sessão
    # para evitar erros e devolve None, permitindo que um novo pedido seja
    # criado para o usuário atual.
    if not order or order.user_id != current_user.id:
        session.pop("current_order", None)
        return None

    # Se o pedido já possui um pagamento concluído não deve ser reutilizado
    if order.payment and order.payment.status == PaymentStatus.COMPLETED:
        session.pop("current_order", None)
        return None

    return order


def _setup_checkout_form(form, preserve_selected=True):
    """Preenche o CheckoutForm com os endereços do usuário."""
    default_address = None
    if current_user.endereco and current_user.endereco.full:
        default_address = current_user.endereco.full

    form.address_id.choices = []
    if default_address:
        form.address_id.choices.append((0, default_address))
    for addr in current_user.saved_addresses:
        form.address_id.choices.append((addr.id, addr.address))
    form.address_id.choices.append((-1, 'Novo endereço'))

    if preserve_selected and form.address_id.data is not None:
        selected = form.address_id.data
    else:
        selected = session.get("last_address_id")

    available = [c[0] for c in form.address_id.choices]
    try:
        selected = int(selected)
    except (TypeError, ValueError):
        selected = None
    if selected not in available:
        selected = None
    if selected is not None:
        form.address_id.data = selected
    elif available:
        form.address_id.data = available[0]

    return default_address



from flask import session, render_template, request, jsonify
from flask_login import login_required


def _build_loja_query(search_term: str, filtro: str, vendedor: str = '', categoria: str = ''):
    from sqlalchemy import and_
    query = (
        Product.query
        .filter(Product.status == 'active')
        .outerjoin(CasaDeRacao, Product.casa_de_racao_id == CasaDeRacao.id)
        .filter(
            or_(
                Product.casa_de_racao_id == None,   # produto de clínica
                CasaDeRacao.status == 'ativa',       # produto de casa aprovada
            )
        )
    )

    if search_term:
        like = f"%{search_term}%"
        query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

    if vendedor.startswith('c_'):
        try:
            cid = int(vendedor[2:])
            query = query.filter(Product.clinica_id == cid)
        except ValueError:
            pass
    elif vendedor.startswith('r_'):
        try:
            rid = int(vendedor[2:])
            query = query.filter(Product.casa_de_racao_id == rid)
        except ValueError:
            pass

    if categoria:
        query = query.filter(Product.category == categoria)

    if filtro == "lowStock":
        query = query.filter(Product.stock < 5)
    elif filtro == "new":
        query = query.order_by(Product.id.desc())
    elif filtro == "priceLow":
        query = query.order_by(Product.price.asc())
    elif filtro == "priceHigh":
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.name)

    return query


def _get_vendedores_ativos():
    """Retorna lista de dicts {key, nome, logo_url} de todos os vendedores com produtos ativos."""
    from models import Clinica as ClinicaModel
    vendedores = []
    clinicas = (
        ClinicaModel.query
        .join(Product, Product.clinica_id == ClinicaModel.id)
        .filter(Product.status == 'active')
        .distinct()
        .order_by(ClinicaModel.nome)
        .all()
    )
    for c in clinicas:
        vendedores.append({'key': f'c_{c.id}', 'nome': c.nome, 'logo_url': c.logo_url})

    casas = (
        CasaDeRacao.query
        .join(Product, Product.casa_de_racao_id == CasaDeRacao.id)
        .filter(Product.status == 'active', CasaDeRacao.status == 'ativa')
        .distinct()
        .order_by(CasaDeRacao.nome)
        .all()
    )
    for r in casas:
        vendedores.append({'key': f'r_{r.id}', 'nome': r.nome, 'logo_url': r.logo_url})

    return vendedores




# Rótulos e catálogo de serviços recomendáveis pelo admin (mensagem WhatsApp).
SERVICE_RECOMMENDATION_CATALOG = {
    'vacinas': 'Vacinas (agendamento)',
    'pmo': 'Vacina antirrábica gratuita (PMO)',
    'consultas': 'Consulta com veterinário',
    'exames': 'Exames e ultrassonografia',
}


def _service_recommendation_link(service_key, city):
    """Return the internal target URL for a recommendable service, or None."""
    if service_key == 'vacinas':
        return url_for('servicos_vacinas', cidade=city) if city else url_for('servicos_vacinas')
    if service_key == 'pmo':
        return url_for('vacina_pmo_solicitar')
    if service_key == 'consultas':
        return url_for('veterinarios', cidade=city) if city else url_for('veterinarios')
    if service_key == 'exames':
        return url_for('servicos_ultrassom')
    return None


def _build_service_recommendation(tutor, animais, services, city, free_text):
    """Build the WhatsApp recommendation message + wa.me URL for a tutor.

    Each service link is wrapped in a personalized first-access URL so a
    logged-out tutor sets a password once and is redirected (``next``) to the
    service page. Must run server-side because the token is signed.
    """
    nome = (getattr(tutor, 'name', None) or 'tutor').split()[0]
    nomes_animais = [a.name for a in (animais or []) if getattr(a, 'name', None)]
    if not nomes_animais:
        pets = 'seu pet'
    elif len(nomes_animais) == 1:
        pets = nomes_animais[0]
    else:
        pets = ', '.join(nomes_animais[:-1]) + f' e {nomes_animais[-1]}'

    linhas = [
        f'Oi, {nome}! Tudo bem? Aqui é o Lucas Marcelino, médico veterinário.',
        f'Separei alguns serviços da PetOrlândia para {pets}:',
        '',
    ]
    for key in services:
        target = _service_recommendation_link(key, city)
        if not target:
            continue
        link = _first_access_url_for_user(tutor, next_url=target, _external=True)
        linhas.append(f'• {SERVICE_RECOMMENDATION_CATALOG[key]}: {link}')

    if free_text and free_text.strip():
        linhas.append('')
        linhas.append(free_text.strip())

    linhas.append('')
    linhas.append('No primeiro acesso é só definir uma senha e você já cai direto na página. 🐾')
    message = '\n'.join(linhas)
    whatsapp_url = whatsapp_chat_url(getattr(tutor, 'phone', None), message)
    return {
        'message': message,
        'whatsapp_url': whatsapp_url,
        'phone_ok': bool(whatsapp_url),
    }








# ──────────────────── Serviço de Vacinas Pagas ────────────────────

def _vacserv_refund_payment(payment) -> bool:
    """Reembolso total via API do Mercado Pago. True se aprovado."""
    if not payment or not payment.mercado_pago_id:
        return False
    resp = mp_sdk().refund().create(payment.mercado_pago_id)
    return resp.get('status') in (200, 201)


















def _vacinas_parceiro_serializer():
    from itsdangerous import URLSafeSerializer
    return URLSafeSerializer(app.config['SECRET_KEY'], salt='vacinas-parceiro')


def vacinas_parceiro_token(vet_id: int) -> str:
    return _vacinas_parceiro_serializer().dumps(int(vet_id))














# --------------------------------------------------------
#  ADICIONAR AO CARRINHO
# --------------------------------------------------------


# --------------------------------------------------------
#  ATUALIZAR QUANTIDADE DO ITEM DO CARRINHO
# --------------------------------------------------------




# --------------------------------------------------------
#  VER CARRINHO
# --------------------------------------------------------
from forms import CheckoutForm, EditAddressForm






















#inicio pagamento


# --------------------------------------------------------
#  CHECKOUT (CSRF PROTECTED)
# --------------------------------------------------------
# ──────────────────────────────────────────────────────────────────────────────
# 1)  /checkout  –  cria Preference + Payment “pending”
# ──────────────────────────────────────────────────────────────────────────────
import json, logging, os
from flask import current_app, redirect, url_for, flash, session
from flask_login import login_required, current_user







import re
import hmac
import hashlib
from flask import current_app, request, jsonify
from sqlalchemy.exc import SQLAlchemyError

# Regular expression for parsing X-Signature header
_SIG_RE = re.compile(r"(?i)(?:ts=(\d+),\s*)?v1=([a-f0-9]{64})")

def _parse_mp_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def verify_mp_signature(req, secret: str) -> bool:
    """
    Verify the signature of a Mercado Pago webhook notification.
    
    Args:
        req: Flask request object
        secret: Webhook secret key from Mercado Pago
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not secret:
        current_app.logger.warning(
            "Webhook sem chave – verificacao impossivel"
        )
        return False

    x_signature = req.headers.get("X-Signature", "")
    m = _SIG_RE.search(x_signature)
    if not m:
        current_app.logger.warning("X-Signature mal-formado: %s", x_signature)
        return False

    ts, sig_mp = m.groups()
    if not ts or not sig_mp:
        current_app.logger.warning("Missing ts or v1 in X-Signature")
        return False

    x_request_id = req.headers.get("x-request-id", "")
    if not x_request_id:
        current_app.logger.warning("Missing x-request-id header")
        return False

    # Determine ID based on notification type
    topic = req.args.get("topic")
    type_ = req.args.get("type")
    if topic == "payment" or type_ == "payment":
        data_id = req.args.get("data.id", "")
    elif topic == "merchant_order":
        data_id = req.args.get("id", "")
    else:
        current_app.logger.warning("Unknown notification type")
        return False

    if not data_id:
        current_app.logger.warning("Missing ID in query parameters")
        return False

    # Construct manifest
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"

    # Compute HMAC-SHA256
    calc = hmac.new(
        secret.strip().encode(),
        manifest.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calc, sig_mp):
        current_app.logger.warning("Invalid signature: calc=%s recv=%s", calc, sig_mp)
        return False
    return True























































# ——— 3) Página de status final —————————————————————————————————————————
# --------------------------------------------------------
# 3)  /payment_status/<payment_id>   – página pós‑pagamento
#      (versão sem QR‑Code)
# --------------------------------------------------------
from flask import render_template, request, jsonify

def _refresh_mp_status(payment: Payment) -> None:
    if payment.status != PaymentStatus.PENDING:
        return
    resp = mp_sdk().payment().get(payment.mercado_pago_id or payment.transaction_id)
    if resp.get("status") != 200:
        current_app.logger.warning("MP lookup falhou: %s", resp)
        return
    mp = resp["response"]
    mapping = {
        "approved":   PaymentStatus.COMPLETED,
        "authorized": PaymentStatus.COMPLETED,
        "pending":    PaymentStatus.PENDING,
        "in_process": PaymentStatus.PENDING,
        "in_mediation": PaymentStatus.PENDING,
        "rejected":   PaymentStatus.FAILED,
        "cancelled":  PaymentStatus.FAILED,
        "refunded":   PaymentStatus.FAILED,
        "expired":    PaymentStatus.FAILED,
    }
    new_status = mapping.get(mp["status"], PaymentStatus.PENDING)
    if new_status != payment.status:
        payment.status = new_status
        if payment.external_reference and payment.external_reference.startswith('vet-membership-'):
            _sync_veterinarian_membership_payment(payment)
        if payment.external_reference and payment.external_reference.startswith('health-onboarding-'):
            onboarding = _resolve_health_onboarding(payment.external_reference)
            _sync_health_subscription_from_onboarding(onboarding, payment.status, payment)
        db.session.commit()











#fim pagamento


from sqlalchemy.orm import joinedload




























































def _serialize_calendar_pet(pet):
    """Serialize ``Animal`` data for the experimental calendar widgets."""

    def _extract_name(value):
        if not value:
            return ""
        if hasattr(value, "name"):
            return value.name or ""
        return str(value)

    owner_name = ""
    owner = getattr(pet, "owner", None)
    if owner and getattr(owner, "name", None):
        owner_name = owner.name

    return {
        "id": pet.id,
        "name": pet.name,
        "species": _extract_name(getattr(pet, "species", "")),
        "breed": _extract_name(getattr(pet, "breed", "")),
        "date_added": pet.date_added.isoformat() if pet.date_added else None,
        "image": getattr(pet, "image", None),
        "tutor_name": owner_name,
        "age_display": pet.age_display if hasattr(pet, "age_display") else None,
        "clinica_id": getattr(pet, "clinica_id", None),
    }


















def _integration_request_json():
    payload = request.get_json(silent=True)
    if payload is None:
        return None, _integration_error(
            'invalid_json',
            'Request body must be valid JSON.',
            400,
        )
    if not isinstance(payload, dict):
        return None, _integration_error(
            'invalid_json',
            'Request body must be a JSON object.',
            400,
        )
    return payload, None


def _integration_confirmation_error(payload: dict):
    confirmed = str(payload.get('confirmar_gravacao') or '').strip().lower()
    if confirmed in {'sim', 's', 'yes', 'true', '1'}:
        return None
    return _integration_error(
        'confirmation_required',
        'Esta acao grava dados no PetOrlandia e exige confirmar_gravacao="sim".',
        409,
        required_field='confirmar_gravacao',
        required_value='sim',
    )


def _integration_professional_error(auth_user: User, *, veterinarian_only: bool = False):
    if veterinarian_only:
        allowed = has_veterinarian_profile(auth_user)
        message = 'Somente contas veterinarias podem executar esta acao.'
    else:
        allowed = has_professional_access(auth_user)
        message = 'Somente contas profissionais podem executar esta acao.'
    if allowed:
        return None
    return _integration_error('professional_account_required', message, 403)












































def _parse_calendar_boundary(value):
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        if "T" not in raw:
            return datetime.combine(date.fromisoformat(raw), time.min, tzinfo=BR_TZ)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BR_TZ)
        return parsed
    except (TypeError, ValueError):
        return None


def _calendar_window_from_request():
    start = _parse_calendar_boundary(request.args.get("start"))
    end = _parse_calendar_boundary(request.args.get("end"))

    if start and end and end <= start:
        end = None

    start_local = coerce_to_brazil_tz(start) if start else None
    end_local = coerce_to_brazil_tz(end) if end else None

    return {
        "start_utc": normalize_to_utc(start) if start else None,
        "end_utc": normalize_to_utc(end) if end else None,
        "start_date": start_local.date() if start_local else None,
        "end_date": end_local.date() if end_local else None,
    }


def _apply_calendar_datetime_window(query, column, window):
    if not window:
        return query
    if window.get("start_utc") is not None:
        query = query.filter(column >= window["start_utc"])
    if window.get("end_utc") is not None:
        query = query.filter(column < window["end_utc"])
    return query


def _apply_calendar_date_window(query, column, window):
    if not window:
        return query
    if window.get("start_date") is not None:
        query = query.filter(column >= window["start_date"])
    if window.get("end_date") is not None:
        query = query.filter(column < window["end_date"])
    return query



























































# Bulário de Medicamentos migrou para blueprints/bulario.py.
# Reexport para compatibilidade com testes/monkeypatch via módulo app.
from blueprints.bulario import (  # noqa: E402,F401
    _salvar_doses_do_form,
    bulario,
    bulario_buscar_api,
    bulario_curadoria,
    bulario_curadoria_sincronizar,
    bulario_curadoria_status,
    bulario_detalhe,
    bulario_editar,
    bulario_excluir,
    bulario_novo,
    bulario_sugerir_dose_api,
)




from blueprint_utils import register_domain_blueprints

_fiscal_onboarding_path = pathlib.Path(__file__).resolve().parent / "app" / "routes" / "fiscal_onboarding.py"
if _fiscal_onboarding_path.exists():
    _spec = importlib.util.spec_from_file_location("fiscal_onboarding_routes", _fiscal_onboarding_path)
    _fiscal_onboarding_routes = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_fiscal_onboarding_routes)
    fiscal_onboarding_start = _fiscal_onboarding_routes.fiscal_onboarding_start
    fiscal_onboarding_step = _fiscal_onboarding_routes.fiscal_onboarding_step

_fiscal_exports_path = pathlib.Path(__file__).resolve().parent / "app" / "routes" / "fiscal_exports.py"
if _fiscal_exports_path.exists():
    _spec = importlib.util.spec_from_file_location("fiscal_exports_routes", _fiscal_exports_path)
    _fiscal_exports_routes = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_fiscal_exports_routes)
    fiscal_exports_xmls = _fiscal_exports_routes.fiscal_exports_xmls

register_domain_blueprints(app)

# Views migradas para blueprints (reexport para compatibilidade de monkeypatch).
from blueprints.mensagens import (  # noqa: E402,F401
    _resolve_animal_conversation,
    aceitar_interesse,
    api_conversa_admin_message,
    api_conversa_message,
    api_message_threads,
    chat_messages,
    chat_view,
    conversa,
    conversa_admin,
    enviar_mensagem,
    mensagens,
    mensagens_admin,
    mensagens_admin_marcar_lidas,
)
from blueprints.planos import (  # noqa: E402,F401
    clinic_grooming_assinantes,
    clinic_grooming_plano_editar,
    clinic_grooming_plano_toggle,
    clinic_grooming_planos,
    contratar_plano,
    grooming_assinar,
    grooming_cancelar,
    grooming_minhas_assinaturas,
    grooming_planos_publicos,
    plano_saude_overview,
    planosaude_animal,
    validar_plano_consulta,
)
from blueprints.mcp import (  # noqa: E402,F401
    MCP_FILE_REFERENCE_OR_STRING_SCHEMA,
    MCP_FILE_REFERENCE_SCHEMA,
    _mcp_find_animal_for_tool,
    mcp_protected_resource_metadata,
    mcp_server,
)
from blueprints.auth import (  # noqa: E402,F401
    change_password,
    delete_account,
    first_access,
    first_access_password,
    login_view,
    logout,
    profile,
    register,
    reset_password,
    reset_password_request,
)
from blueprints.site import (  # noqa: E402,F401
    admin_pagar_repasses_frete,
    admin_repasses_frete,
    api_geo_cidade,
    cancelar_solicitacao,
    chatgpt_onboarding,
    index,
    minhas_solicitacoes,
    openai_apps_challenge,
    painel_dashboard,
    parceiro_vacinas_precos,
    privacy,
    professional_services_manage,
    responder_solicitacao,
    secret_game,
    secret_game_partituras,
    secret_game_static,
    service_worker,
    servicos,
    servicos_exames,
    servicos_recomendar,
    servicos_ultrassom,
    servicos_vacinas,
    servicos_vacinas_admin,
    servicos_vacinas_admin_acao,
    servicos_vacinas_admin_item,
    servicos_vacinas_cancelar,
    servicos_vacinas_cidade_por_local,
    servicos_vacinas_pedido,
    servicos_vacinas_reagendar,
    solicitacoes_recebidas,
    solicitar_agendamento,
    support,
    terms,
    update_vet_profile,
    veterinarian_cancel_trial,
    veterinarian_membership,
    veterinarian_membership_checkout,
    veterinarian_request_new_trial,
)
from blueprints.vacina_pmo import (  # noqa: E402,F401
    castracao_pmo_solicitar,
    vacina_pmo,
    vacina_pmo_agenda,
    vacina_pmo_animal_name,
    vacina_pmo_animal_photo,
    vacina_pmo_animal_photo_src,
    vacina_pmo_animal_status,
    vacina_pmo_avaliacoes,
    vacina_pmo_cobertura_ativa,
    vacina_pmo_criar_dia,
    vacina_pmo_doses_compilar,
    vacina_pmo_doses_webhook,
    vacina_pmo_imprimir,
    vacina_pmo_painel,
    vacina_pmo_public,
    vacina_pmo_public_pet,
    vacina_pmo_route_optimize,
    vacina_pmo_route_preview,
    vacina_pmo_route_undo,
    vacina_pmo_sheets,
    vacina_pmo_solicitar,
    vacina_pmo_state,
    vacina_pmo_status_webhook,
    vacina_pmo_sync,
    vacina_pmo_visit_attended_by,
    vacina_pmo_visit_losses,
    vacina_pmo_visit_note,
)
from blueprints.consulta import (  # noqa: E402,F401
    acompanhamento_tratamento,
    adicionar_orcamento_item,
    agendar_retorno,
    alterar_exame,
    alterar_exame_modelo,
    alterar_medicamento,
    alterar_status_tratamento,
    aplicar_sugestao_clinica,
    appointment_close,
    ativar_acompanhamento_tratamento,
    atualizar_bloco_exames,
    atualizar_bloco_orcamento,
    atualizar_bloco_prescricao,
    atualizar_protocolo_clinico_inline,
    atualizar_realizacao_exames,
    buscar_apresentacoes,
    buscar_exames,
    buscar_medicamentos,
    calcular_plano_sugestao_clinica,
    consulta_direct,
    criar_apresentacao_medicamento,
    criar_exame_modelo,
    criar_medicamento,
    criar_prescricao,
    criar_protocolo_clinico_inline,
    criar_servico_clinica,
    deletar_bloco_exames,
    deletar_bloco_orcamento,
    deletar_bloco_prescricao,
    deletar_consulta,
    deletar_orcamento_item,
    deletar_prescricao,
    detalhe_medicamento_busca,
    editar_bloco_exames,
    editar_bloco_orcamento,
    editar_bloco_prescricao,
    enviar_assinatura_bloco_prescricao,
    enviar_foto_tratamento,
    finalizar_consulta,
    finalizar_consulta_e_fechar,
    gerar_link_pagamento_orcamento,
    historico_consultas_partial,
    historico_exames_partial,
    historico_orcamentos_partial,
    historico_prescricoes_partial,
    imprimir_bloco_exames,
    imprimir_bloco_orcamento,
    imprimir_bloco_prescricao,
    imprimir_consulta,
    imprimir_orcamento,
    imprimir_orcamento_padrao,
    iniciar_retorno,
    listar_medicamentos_favoritos,
    marcar_administracao_tratamento,
    marcar_item_tratamento_comprado,
    medicamentos_frequentes,
    novo_atendimento,
    obter_protocolo_clinico_inline,
    obter_sugestoes_clinicas,
    pagar_consulta_orcamento,
    pagar_orcamento,
    recarregar_historico_prescricoes_ajax,
    registrar_aplicacao_tratamento,
    registrar_feedback_sugestao_clinica,
    salvar_bloco_exames,
    salvar_bloco_orcamento,
    salvar_bloco_prescricao,
    salvar_prescricoes_lote,
    toggle_medicamento_favorito,
    update_consulta,
)
from blueprints.pacientes import (  # noqa: E402,F401
    add_animal,
    adotar_animal,
    alterar_racao,
    alterar_tipo_racao,
    alterar_vacina,
    alterar_vacina_modelo,
    api_atualizar_peso_animal,
    api_tipos_racao,
    arquivar_animal,
    buscar_animais,
    buscar_racoes,
    buscar_tutores,
    buscar_vacinas,
    consulta_qr,
    criar_tipo_racao,
    criar_tutor_ajax,
    criar_vacina_modelo,
    deletar_animal,
    deletar_tutor,
    delete_document,
    detalhes_racao,
    editar_animal,
    editar_ficha_animal,
    exames_imagem_compartilhar,
    exames_imagem_painel,
    ficha_animal,
    ficha_tutor,
    generate_qr,
    gerar_termo,
    historico_animal,
    imprimir_vacinas,
    list_animals,
    marcar_como_falecido,
    meus_animais,
    novo_animal,
    obter_tutor,
    relatorio_racoes,
    reverter_falecimento,
    salvar_racao,
    salvar_vacinas,
    termo_animal,
    termo_interesse,
    termo_transferencia,
    tipos_racao,
    tutor_detail,
    tutor_sharing_dashboard,
    tutores,
    update_animal,
    update_tutor,
    upload_document,
)
from blueprints.clinica import (  # noqa: E402,F401
    atualizar_status_orcamento,
    cancel_clinic_invite,
    clinic_dashboard,
    clinic_detail,
    clinic_invites,
    clinic_loja_produtos,
    clinic_mercadopago_direct_save,
    clinic_mercadopago_oauth_disconnect,
    clinic_mercadopago_oauth_start,
    clinic_produto_editar,
    clinic_produto_toggle,
    clinic_staff,
    clinic_staff_permissions,
    clinic_stock,
    clinicas,
    create_clinic_veterinario,
    dashboard_orcamentos,
    delete_clinic_hour,
    delete_vet_schedule_clinic,
    editar_orcamento,
    enviar_orcamento,
    external_clinic_first_access_invite,
    external_onboarding_invite,
    minha_clinica,
    novo_orcamento,
    orcamentos,
    parceiro_clinica_landing,
    publish_inventory_to_loja,
    remove_funcionario,
    remove_specialist,
    remove_veterinario,
    resend_clinic_invite,
    respond_clinic_invite,
    update_inventory_item,
)
from blueprints.api import (  # noqa: E402,F401
    api_cep_lookup,
    api_clinic_appointments,
    api_clinic_pets,
    api_criar_sinistro,
    api_delivery_counts,
    api_forward_geocode,
    api_historico_uso,
    api_integrations_appointments,
    api_integrations_attach_exame_imagem_pdf,
    api_integrations_clinical_pendencies,
    api_integrations_clinical_summary,
    api_integrations_create_appointment,
    api_integrations_create_exam_block,
    api_integrations_create_exame_imagem,
    api_integrations_create_or_update_consultation,
    api_integrations_create_return_appointment,
    api_integrations_create_tutor_and_pets,
    api_integrations_find_or_create_requesting_clinic,
    api_integrations_find_or_create_tutor_animal_for_exam,
    api_integrations_generate_clinic_first_access_invite,
    api_integrations_generate_tutor_access_invite,
    api_integrations_get_clinical_document,
    api_integrations_handoff,
    api_integrations_interpret_intake,
    api_integrations_list_animal_medical_history,
    api_integrations_me,
    api_integrations_openapi,
    api_integrations_operational_assistant,
    api_integrations_pets,
    api_integrations_release_exame_to_clinic,
    api_integrations_release_exame_to_tutor,
    api_integrations_today_agenda,
    api_integrations_tutor_guidance,
    api_minhas_compras,
    api_my_appointments,
    api_my_pets,
    api_payment_status,
    api_public_pricing,
    api_reschedule_appointment,
    api_reverse_geocode,
    api_specialist_available_times,
    api_specialist_weekly_schedule,
    api_specialists,
    api_specialties,
    api_status_autorizacao,
    api_status_sinistro,
    api_user_appointments,
    api_vet_appointments,
    approve_share_request,
    confirm_share_request,
    deny_share_request,
    share_request_detail,
    shares_api,
)
from blueprints.agendamentos import (  # noqa: E402,F401
    animal_exam_appointments,
    appointment_confirmation,
    appointment_emit_nfse,
    appointments,
    appointments_calendar,
    bulk_delete_vet_schedule,
    delete_appointment,
    delete_exam_appointment,
    delete_vet_schedule,
    edit_appointment,
    edit_vet_schedule_slot,
    edit_vet_specialties,
    manage_appointments,
    pending_appointments,
    schedule_exam,
    update_appointment_status,
    update_exam_appointment,
    update_exam_appointment_requester,
    update_exam_appointment_status,
    vet_detail,
    veterinarian_activity_report,
    veterinarios,
)
from blueprints.loja import (  # noqa: E402,F401
    accept_delivery,
    adicionar_carrinho,
    admin_archive_delivery,
    admin_data_share_logs,
    admin_delete_delivery,
    admin_delivery_detail,
    admin_geocode_addresses,
    admin_geocode_status,
    admin_set_delivery_status,
    admin_tutor_map,
    admin_tutor_markers_api,
    admin_unarchive_delivery,
    aumentar_item_carrinho,
    buyer_cancel_delivery,
    cancel_delivery,
    carrinho_salvar_endereco,
    checkout,
    checkout_confirm,
    complete_delivery,
    confirmar_recebimento_pedido,
    create_order,
    delivery_archive,
    delivery_archive_user,
    delivery_detail,
    delivery_overview,
    diminuir_item_carrinho,
    edit_order_address,
    legacy_pagamento,
    list_delivery_requests,
    loja,
    loja_data,
    minhas_compras,
    notificacoes_mercado_pago,
    payment_status,
    pedido_detail,
    pesquisa_racoes_tutores,
    produto_detail,
    request_delivery,
    save_pesquisa_racoes_tutor_answers,
    send_selected_pesquisa_racoes_tutores,
    toggle_pesquisa_racoes_tutor,
    update_pesquisa_racoes_tutor_status,
    ver_carrinho,
    warmup_pesquisa_racoes_whatsapp,
    worker_delivery_detail,
)
from blueprints.casa_de_racao import (  # noqa: E402,F401
    admin_aprovar_casa_de_racao,
    admin_casas_de_racao,
    admin_suspender_casa_de_racao,
    casa_de_racao_animais,
    casa_de_racao_animal_racoes,
    casa_de_racao_dashboard,
    casa_de_racao_entregas,
    casa_de_racao_grooming_plano_toggle,
    casa_de_racao_grooming_planos,
    casa_de_racao_horario_delete,
    casa_de_racao_onboarding,
    casa_de_racao_produtos,
    casa_de_racao_tutores,
    casa_de_racao_vendas,
    casa_entrega_atualizar_status,
    casa_produto_editar,
    casa_produto_toggle,
    mercadopago_direct_save,
    mercadopago_oauth_callback,
    mercadopago_oauth_disconnect,
    mercadopago_oauth_start,
    minha_casa_de_racao,
    parceiro_loja_landing,
    parceiro_loja_produtos_landing,
)
from blueprints.financeiro import (  # noqa: E402,F401
    api_contabilidade_dashboard,
    api_contabilidade_veterinarios,
    contabilidade_conciliacao_importar,
    contabilidade_contas,
    contabilidade_dre,
    contabilidade_exportar_xlsx,
    contabilidade_financeiro,
    contabilidade_fluxo_caixa,
    contabilidade_home,
    contabilidade_nfse,
    contabilidade_nfse_cancelar,
    contabilidade_nfse_configurar,
    contabilidade_nfse_consolidado,
    contabilidade_nfse_contexto,
    contabilidade_nfse_download,
    contabilidade_nfse_emitir,
    contabilidade_nfse_orcamento,
    contabilidade_nfse_preview,
    contabilidade_nfse_processar_fila,
    contabilidade_nfse_reprocessar,
    contabilidade_nfse_substituir,
    contabilidade_obrigacoes,
    contabilidade_pagamentos,
    contabilidade_pagamentos_delete,
    contabilidade_pagamentos_editar,
    contabilidade_pagamentos_marcar_pago,
    contabilidade_plantao_confirmar,
    contabilidade_plantao_gerar_pagamento,
    contabilidade_plantonistas_editar,
    contabilidade_plantonistas_novo,
    contabilidade_plantonistas_quick_create,
)
from blueprints.fiscal import (  # noqa: E402,F401
    fiscal_certificate_upload,
    fiscal_document_cancel,
    fiscal_document_detail,
    fiscal_document_emit,
    fiscal_document_status,
    fiscal_documents,
    fiscal_nfse_manual,
    fiscal_settings,
)
from blueprints.parceiro import (  # noqa: E402,F401
    parceiro_dashboard,
    parceiro_novo_estabelecimento,
    parceiro_novo_usuario,
    partner_invite_onboarding,
)
from blueprints.oauth import (  # noqa: E402,F401
    jwks,
    oauth_authorize,
    oauth_dynamic_client_registration,
    oauth_introspect,
    oauth_revoke,
    oauth_token,
    oauth_userinfo,
    openid_configuration,
)
from blueprints.admin import (  # noqa: E402,F401
    admin_aprovar_clinica,
    admin_criar_convite,
    admin_notification_mark_read,
    admin_notification_resolve,
    admin_notifications,
    admin_parcerias,
    admin_promote_delivery,
    admin_promote_parceiro,
    admin_promote_veterinarian,
    admin_rejeitar_clinica,
    admin_remove_delivery,
    admin_remove_parceiro,
    admin_toggle_site_flag,
    planos_dashboard,
)

if __name__ == "__main__":
    # Usa a porta 8080 se existir no ambiente (como no Docker), senão usa 5000
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
