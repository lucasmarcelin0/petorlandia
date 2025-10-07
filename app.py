# ───────────────────────────  app.py  ───────────────────────────
import os, sys, pathlib, importlib, logging, uuid, re
from collections import defaultdict
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from urllib.parse import urlparse, parse_qs



from datetime import datetime, timezone, date, timedelta, time
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
from PIL import Image


from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import (
    Flask,
    session,
    send_from_directory,
    abort,
    request,
    jsonify,
    flash,
    render_template,
    redirect,
    url_for,
    current_app,
)
from twilio.rest import Client
from itsdangerous import URLSafeTimedSerializer
from jinja2 import TemplateNotFound
import json
import unicodedata
from sqlalchemy import func, or_, exists, and_, case
from sqlalchemy.orm import joinedload

# ----------------------------------------------------------------
# 1)  Alias único para “models”
# ----------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    models_pkg = importlib.import_module("petorlandia.models")
except ModuleNotFoundError:
    models_pkg = importlib.import_module("models")
sys.modules["models"] = models_pkg

# 📌 Expose every model name (CamelCase) globally
globals().update({
    name: obj
    for name, obj in models_pkg.__dict__.items()
    if name[:1].isupper()          # naive check: classes start with capital
})

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
app.config.setdefault("FRONTEND_URL", "http://127.0.0.1:5000")
app.config.update(SESSION_PERMANENT=True, SESSION_TYPE="filesystem")

# ----------------------------------------------------------------
# 3)  Extensões
# ----------------------------------------------------------------

@app.template_filter('date_now')
def date_now(format_string='%Y-%m-%d'):
    return datetime.now(BR_TZ).strftime(format_string)
# já existe no topo, logo depois das extensões:
from extensions import db, migrate, mail, login, session as session_ext, babel
from flask_login import login_user, logout_user, current_user, login_required
from flask_mail import Message as MailMessage      #  ←  adicione esta linha
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage

db.init_app(app)
migrate.init_app(app, db, compare_type=True)
mail.init_app(app)
login.init_app(app)
session_ext.init_app(app)
babel.init_app(app)
app.config.setdefault("BABEL_DEFAULT_LOCALE", "pt_BR")

# ----------------------------------------------------------------
# 4)  AWS S3 helper (lazy)
# ----------------------------------------------------------------
import boto3

AWS_ID, AWS_SECRET = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")
BUCKET = os.getenv("S3_BUCKET_NAME")

def _s3():
    return boto3.client("s3", aws_access_key_id=AWS_ID, aws_secret_access_key=AWS_SECRET)

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

        if content_type and content_type.startswith("image"):
            image = Image.open(file.stream)
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

        if BUCKET:
            try:
                buffer.seek(0)
                _s3().upload_fileobj(
                    buffer,
                    BUCKET,
                    key,
                    ExtraArgs={"ContentType": content_type},
                )
                return f"https://{BUCKET}.s3.amazonaws.com/{key}"
            except Exception as exc:  # noqa: BLE001
                app.logger.exception("S3 upload failed: %s", exc)
                buffer.seek(0)

        # Local fallback when S3 is not configured or fails
        local_path = PROJECT_ROOT / "static" / "uploads" / key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as fp:
            fp.write(buffer.read())

        return f"/static/uploads/{key}"
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Upload failed: %s", exc)
        return None

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
# 5)  Filtros Jinja para data BR
# ----------------------------------------------------------------

BR_TZ = ZoneInfo("America/Sao_Paulo")


def local_date_range_to_utc(start_dt, end_dt):
    """Convert local date/datetime boundaries to naive UTC datetimes."""

    def _convert(value):
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, time.min)
        if value.tzinfo is None:
            value = value.replace(tzinfo=BR_TZ)
        else:
            value = value.astimezone(BR_TZ)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return _convert(start_dt), _convert(end_dt)


@app.template_filter("datetime_brazil")
def datetime_brazil(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:

            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M")
    return value

@app.template_filter("format_datetime_brazil")
def format_datetime_brazil(value, fmt="%d/%m/%Y %H:%M"):
    if value is None:
        return ""

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(BR_TZ)
        return value.strftime(fmt)

    if isinstance(value, date):
        return value.strftime(fmt)

    return value


@app.template_filter("format_timedelta")
def format_timedelta(value):
    """Format a ``timedelta`` as ``'Xh Ym'``."""
    total_seconds = int(value.total_seconds())
    if total_seconds <= 0:
        return "0h 0m"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"

@app.template_filter("digits_only")
def digits_only(value):
    """Return only the digits from a string."""
    return "".join(filter(str.isdigit, value)) if value else ""


@app.template_filter("payment_status_label")
def payment_status_label(value):
    """Translate payment status codes to Portuguese labels."""
    mapping = {
        "pending": "Pendente",
        "success": "Aprovado",
        "completed": "Aprovado",
        "approved": "Aprovado",
        "failure": "Falha no pagamento",
        "failed": "Falha no pagamento",
    }
    return mapping.get(value.lower(), value) if value else ""

# ----------------------------------------------------------------
# 6)  Forms e helpers
# ----------------------------------------------------------------
from forms import (
    MessageForm, RegistrationForm, LoginForm, AnimalForm, EditProfileForm,
    ResetPasswordRequestForm, ResetPasswordForm, OrderItemForm,
    DeliveryRequestForm, AddToCartForm, SubscribePlanForm,
    ProductUpdateForm, ProductPhotoForm, ChangePasswordForm,
    DeleteAccountForm, ClinicForm, ClinicHoursForm,
    ClinicInviteVeterinarianForm, ClinicInviteCancelForm, ClinicInviteResendForm, ClinicInviteResponseForm,
    VeterinarianProfileForm,
    ClinicAddStaffForm, ClinicAddSpecialistForm, ClinicStaffPermissionForm, VetScheduleForm, VetSpecialtyForm, AppointmentForm, AppointmentDeleteForm,
    InventoryItemForm, OrcamentoForm
)
from helpers import (
    calcular_idade,
    parse_data_nascimento,
    is_slot_available,
    clinicas_do_usuario,
    has_schedule_conflict,
    group_appointments_by_day,
    group_vet_schedules_by_day,
    appointments_to_events,
    exam_to_event,
    vaccine_to_event,
    consulta_to_event,
    unique_items_by_id,
    to_timezone_aware,
    get_available_times,
    get_weekly_schedule,
    get_appointment_duration,
    has_conflict_for_slot,
)


def current_user_clinic_id():
    """Return the clinic ID associated with the current user, if any."""
    if not current_user.is_authenticated:
        return None
    if current_user.worker == 'veterinario' and getattr(current_user, 'veterinario', None):
        return current_user.veterinario.clinica_id
    return current_user.clinica_id


def ensure_clinic_access(clinica_id):
    """Abort with 404 if the current user cannot access the given clinic."""
    if not clinica_id:
        return
    if not current_user.is_authenticated:
        abort(404)
    if current_user.is_authenticated and current_user.role == 'admin':
        return
    if current_user_clinic_id() != clinica_id:
        abort(404)


def get_animal_or_404(animal_id):
    """Return animal if accessible to current user, otherwise 404."""
    animal = Animal.query.get_or_404(animal_id)
    return animal


def get_consulta_or_404(consulta_id):
    """Return consulta if accessible to current user, otherwise 404."""
    consulta = Consulta.query.get_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    return consulta


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


def _render_messages_page(mensagens=None, **extra_context):
    """Render the messages page with optional overrides for clinic invites."""
    if mensagens is None:
        mensagens = [
            m for m in current_user.received_messages if m.sender is not None
        ]

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


def _ensure_veterinarian_profile(form=None):
    """Return veterinarian profile or render guidance message when missing."""
    worker = getattr(current_user, "worker", None)
    if worker != "veterinario":
        abort(403)

    vet_profile = getattr(current_user, "veterinario", None)
    if vet_profile is None:
        return None, _render_missing_vet_profile(form=form)

    return vet_profile, None

# ----------------------------------------------------------------
# 7)  Login & serializer
# ----------------------------------------------------------------
from models import User   # noqa: E402  (import depois de alias)

@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

login.login_view = "login_view"
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

# ----------------------------------------------------------------
# 8)  Admin & blueprints
# ----------------------------------------------------------------
with app.app_context():
    from admin import init_admin, _is_admin  # import interno evita loop
    init_admin(app)
    # outras blueprints ->  from views import bp as views_bp ; app.register_blueprint(views_bp)

# (rotas podem ser definidas em módulos separados e registrados via blueprint)
# ────────────────────────────── fim ─────────────────────────────
@app.context_processor
def inject_unread_count():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
            unread = (
                Message.query
                .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
                .count()
            )
        else:
            unread = (
                Message.query
                .filter_by(receiver_id=current_user.id, lida=False)
                .count()
            )
    else:
        unread = 0
    return dict(unread_messages=unread)


@app.context_processor
def inject_pending_exam_count():
    if (
        current_user.is_authenticated
        and getattr(current_user, 'worker', None) == 'veterinario'
        and getattr(current_user, 'veterinario', None)
    ):
        from models import ExamAppointment
        pending = ExamAppointment.query.filter_by(
            specialist_id=current_user.veterinario.id, status='pending'
        ).count()
        seen = session.get('exam_pending_seen_count', 0)
        pending = max(pending - seen, 0)
    else:
        pending = 0
    return dict(pending_exam_count=pending)


@app.context_processor
def inject_pending_appointment_count():
    """Expose count of upcoming appointments requiring vet action."""
    if (
        current_user.is_authenticated
        and getattr(current_user, "worker", None) == "veterinario"
        and getattr(current_user, "veterinario", None)
    ):
        from models import Appointment

        now = datetime.utcnow()
        pending = Appointment.query.filter(
            Appointment.veterinario_id == current_user.veterinario.id,
            Appointment.status == "scheduled",
            Appointment.scheduled_at >= now + timedelta(hours=2),
        ).count()
        seen = session.get('appointment_pending_seen_count', 0)
        pending = max(pending - seen, 0)
    else:
        pending = 0
    return dict(pending_appointment_count=pending)


def _clinic_pending_appointments_query(veterinario):
    """Return query for scheduled clinic appointments excluding the given vet."""
    if not veterinario or not getattr(veterinario, "clinica_id", None):
        return None

    from models import Appointment

    return Appointment.query.filter(
        Appointment.clinica_id == veterinario.clinica_id,
        Appointment.status == "scheduled",
        Appointment.veterinario_id != veterinario.id,
    )


@app.context_processor
def inject_clinic_pending_appointment_count():
    """Expose count of scheduled appointments in the clinic excluding the current vet."""
    if (
        current_user.is_authenticated
        and getattr(current_user, "worker", None) == "veterinario"
    ):
        pending_query = _clinic_pending_appointments_query(
            getattr(current_user, "veterinario", None)
        )
        pending = pending_query.count() if pending_query is not None else 0
        seen = session.get("clinic_pending_seen_count", 0)
        pending = max(pending - seen, 0)
    else:
        pending = 0
    return dict(clinic_pending_appointment_count=pending)


@app.context_processor
def inject_clinic_invite_count():
    if (
        current_user.is_authenticated
        and getattr(current_user, 'worker', None) == 'veterinario'
        and getattr(current_user, 'veterinario', None)
    ):
        from models import VetClinicInvite

        pending = VetClinicInvite.query.filter_by(
            veterinario_id=current_user.veterinario.id, status='pending'
        ).count()
    else:
        pending = 0
    return dict(pending_clinic_invites=pending)


s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

@app.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = s.dumps(user.email, salt='password-reset-salt')
            base_url = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:5000')
            link = f"{base_url}{url_for('reset_password', token=token)}"

            msg = MailMessage(
                subject='Redefinir sua senha - PetOrlândia',
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[user.email],
                body=f'Clique no link para redefinir sua senha: {link}',
                html=f""" 
                    <!DOCTYPE html>
                    <html lang="pt-BR">
                    <head><meta charset="UTF-8"><title>Redefinição de Senha</title></head>
                    <body style="font-family: Arial; padding: 20px;">
                        <h2>🐾 PetOrlândia</h2>
                        <p>Recebemos uma solicitação para redefinir sua senha.</p>
                        <p><a href="{link}" style="background:#0d6efd;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;">Redefinir Senha</a></p>
                        <p>Se você não solicitou, ignore este e-mail.</p>
                        <hr><small>PetOrlândia • Cuidando com amor dos seus melhores amigos</small>
                    </body>
                    </html>
                """
            )
            mail.send(msg)
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('login_view')})
            flash('Um e-mail foi enviado com instruções para redefinir sua senha.', 'info')
            return redirect(url_for('login_view'))
        if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
            return jsonify({'success': False, 'errors': {'email': ['E-mail não encontrado.']}}), 400
        flash('E-mail não encontrado.', 'danger')
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400
    return render_template('auth/reset_password_request.html', form=form)



@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)  # 1 hour
    except:
        flash('O link de redefinição expirou ou é inválido.', 'danger')
        return redirect(url_for('reset_password_request'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(form.password.data)  # Your User model must have set_password method
            db.session.commit()
            flash('Sua senha foi redefinida. Você já pode entrar!', 'success')
            return redirect(url_for('login_view'))
    return render_template('auth/reset_password.html', form=form)



#admin configuration

@app.route('/painel')
@login_required
def painel_dashboard():
    cards = [
        {"icon": "👤", "title": "Usuários", "description": f"Total: {User.query.count()}"},
        {"icon": "🐶", "title": "Animais", "description": f"Total: {Animal.query.count()}"},
        {"icon": "🏥", "title": "Clínicas", "description": f"Total: {Clinica.query.count()}"},
        {"icon": "💉", "title": "Vacinas", "description": f"Hoje: {VacinaModelo.query.count()}"},
        {"icon": "📋", "title": "Consultas", "description": f"Pendentes: {Consulta.query.filter_by(status='pendente').count()}"},
        {"icon": "💊", "title": "Prescrições", "description": f"Semana: {Prescricao.query.count()}"},
    ]
    return render_template('admin/admin_dashboard.html', cards=cards)



# Rota principal


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/service-worker.js')
def service_worker():
    return send_from_directory(app.static_folder, 'service-worker.js')


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()

    if form.validate_on_submit():
        # Verifica se o e-mail já está em uso
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': False, 'errors': {'email': ['Email já está em uso.']}}), 400
            flash('Email já está em uso.', 'danger')
            return render_template('auth/register.html', form=form, endereco=None)

        # Cria o endereço
        endereco = Endereco(
            cep=request.form.get('cep'),
            rua=request.form.get('rua'),
            numero=request.form.get('numero'),
            complemento=request.form.get('complemento'),
            bairro=request.form.get('bairro'),
            cidade=request.form.get('cidade'),
            estado=request.form.get('estado')
        )

        # Upload da foto de perfil para o S3
        photo_url = None
        if form.profile_photo.data:
            file = form.profile_photo.data
            filename = secure_filename(file.filename)
            photo_url = upload_to_s3(file, filename, folder="users")


        # Cria o usuário com a URL da imagem no S3
        user = User(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            profile_photo=photo_url,
            endereco=endereco
        )
        user.set_password(form.password.data)

        # Salva no banco
        db.session.add(endereco)
        db.session.add(user)
        db.session.commit()

        if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
            return jsonify({'success': True, 'redirect': url_for('index')})
        flash('Usuário registrado com sucesso!', 'success')
        return redirect(url_for('index'))

    if request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400

    return render_template('auth/register.html', form=form, endereco=None)




@app.route('/add-animal', methods=['GET', 'POST'])
@login_required
def add_animal():
    form = AnimalForm()

    # Listas para o template
    try:
        species_list = list_species()
    except Exception:
        species_list = []
    try:
        breed_list = list_breeds()
    except Exception:
        breed_list = []

    # Debug da requisição
    print("📥 Método da requisição:", request.method)
    print("📋 Dados recebidos:", request.form)

    if form.validate_on_submit():
        print("✅ Formulário validado com sucesso.")

        image_url = None
        if form.image.data:
            file = form.image.data
            original_filename = secure_filename(file.filename)
            filename = f"{uuid.uuid4().hex}_{original_filename}"
            print("🖼️ Upload de imagem iniciado:", filename)
            image_url = upload_to_s3(file, filename, folder="animals")
            print("✅ Upload concluído. URL:", image_url)

        # IDs das listas
        species_id = request.form.get("species_id", type=int)
        breed_id = request.form.get("breed_id", type=int)
        print("🔍 Species ID:", species_id)
        print("🔍 Breed ID:", breed_id)

        dob = form.date_of_birth.data
        if not dob and form.age.data:
            try:
                age_years = int(form.age.data)
                dob = date.today() - relativedelta(years=age_years)
            except ValueError:
                dob = None

        # Criação do animal
        animal = Animal(
            name=form.name.data,
            species_id=species_id,
            breed_id=breed_id,
            age=form.age.data,
            date_of_birth=dob,
            sex=form.sex.data,
            description=form.description.data,
            image=image_url,
            photo_rotation=form.photo_rotation.data,
            photo_zoom=form.photo_zoom.data,
            photo_offset_x=form.photo_offset_x.data,
            photo_offset_y=form.photo_offset_y.data,
            modo=form.modo.data,
            price=form.price.data if form.modo.data == 'venda' else None,
            status='disponível',
            owner=current_user,
            is_alive=True
        )

        db.session.add(animal)
        try:
            db.session.commit()
            print("✅ Animal salvo com ID:", animal.id)
            flash('Animal cadastrado com sucesso!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            print("❌ Erro ao salvar no banco:", str(e))
            flash('Erro ao salvar o animal.', 'danger')

    else:
        print("⚠️ Formulário inválido.")
        print("🧾 Erros do formulário:", form.errors)

    return render_template(
        'animais/add_animal.html',
        form=form,
        species_list=species_list,
        breed_list=breed_list
    )


@app.route('/login', methods=['GET', 'POST'])
def login_view():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            if form.remember.data:
                session.permanent = True
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('index')})
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        else:
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': False, 'errors': {'email': ['Email ou senha inválidos.']}}), 400
            flash('Email ou senha inválidos.', 'danger')
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400
    return render_template('auth/login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu com sucesso!', 'success')
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Garante que current_user.endereco exista para pré-preenchimento
    form = EditProfileForm(obj=current_user)
    delete_form = DeleteAccountForm()

    if form.validate_on_submit():
        if not current_user.endereco:
            current_user.endereco = Endereco()


    form = EditProfileForm(obj=current_user)

    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.email = form.email.data
        current_user.phone = form.phone.data
        current_user.photo_rotation = form.photo_rotation.data
        current_user.photo_zoom = form.photo_zoom.data
        current_user.photo_offset_x = form.photo_offset_x.data
        current_user.photo_offset_y = form.photo_offset_y.data

        # Atualiza ou cria endereço
        endereco = current_user.endereco
        endereco.cep = request.form.get("cep")
        endereco.rua = request.form.get("rua")
        endereco.numero = request.form.get("numero")
        endereco.complemento = request.form.get("complemento")
        endereco.bairro = request.form.get("bairro")
        endereco.cidade = request.form.get("cidade")
        endereco.estado = request.form.get("estado")

        db.session.add(endereco)

        # Upload de imagem para S3 (se houver nova)
        if (
            form.profile_photo.data and
            hasattr(form.profile_photo.data, 'filename') and
            form.profile_photo.data.filename != ''
        ):
            file = form.profile_photo.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            current_user.profile_photo = upload_to_s3(file, filename, folder="profile_photos")

        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    # Transações recentes
    transactions = Transaction.query.filter(
        (Transaction.from_user_id == current_user.id) | (Transaction.to_user_id == current_user.id)
    ).order_by(Transaction.date.desc()).limit(10).all()

    return render_template(
        'auth/profile.html',
        user=current_user,
        form=form,
        delete_form=delete_form,
        transactions=transactions
    )


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': False, 'errors': {'current_password': ['Senha atual incorreta.']}}), 400
            flash('Senha atual incorreta.', 'danger')
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('profile')})
            flash('Senha atualizada com sucesso!', 'success')
            return redirect(url_for('profile'))
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400
    return render_template('auth/change_password.html', form=form)


@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if form.validate_on_submit():
        # Capture the actual user object before logging out because
        # `current_user` becomes `AnonymousUserMixin` after logout.
        user = current_user._get_current_object()

        # Remove mensagens associadas ao usuário antes de excluí-lo
        for msg in list(user.sent_messages) + list(user.received_messages):
            db.session.delete(msg)

        # Remove pagamentos vinculados ao usuário antes de excluí-lo
        for payment in list(user.payments):
            # Desassocia assinaturas que usam este pagamento
            for sub in list(payment.subscriptions):
                sub.payment = None
            db.session.delete(payment)

        logout_user()
        db.session.delete(user)
        db.session.commit()
        flash('Sua conta foi excluída.', 'success')
        return redirect(url_for('index'))
    flash('Operação inválida.', 'danger')
    return redirect(url_for('profile'))




@app.route('/animals')
def list_animals():
    page = request.args.get('page', 1, type=int)
    per_page = 9
    modo = request.args.get('modo')
    species_id = request.args.get('species_id', type=int)
    breed_id = request.args.get('breed_id', type=int)
    sex = request.args.get('sex')
    age = request.args.get('age')
    show_all = _is_admin() and request.args.get('show_all') == '1'

    # Base query: ignora animais removidos
    query = Animal.query.filter(Animal.removido_em == None)

    # Filtro por modo
    if modo and modo.lower() != 'todos':
        query = query.filter_by(modo=modo)
    else:
        # Evita mostrar adotados para usuários não autorizados, exceto quando o admin opta por ver todos
        if not show_all and (not current_user.is_authenticated or current_user.worker not in ['veterinario', 'colaborador']):
            query = query.filter(Animal.modo != 'adotado')

    if species_id:
        query = query.filter_by(species_id=species_id)
    if breed_id:
        query = query.filter_by(breed_id=breed_id)
    if sex:
        query = query.filter_by(sex=sex)
    if age:
        query = query.filter(Animal.age.ilike(f"{age}%"))

    # Veterinários só podem ver animais perdidos, à venda ou para adoção,
    # ou então animais cadastrados pela própria clínica
    if current_user.is_authenticated and current_user.worker == 'veterinario' and not show_all:
        allowed = ['perdido', 'venda', 'doação']
        if current_user.clinica_id:
            query = query.filter(
                or_(
                    Animal.modo.in_(allowed),
                    Animal.clinica_id == current_user.clinica_id
                )
            )
        else:
            query = query.filter(Animal.modo.in_(allowed))

    # Ordenação e paginação
    query = query.order_by(Animal.date_added.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    animals = pagination.items

    try:
        species_list = list_species()
    except Exception:
        species_list = []
    try:
        breed_list = list_breeds()
    except Exception:
        breed_list = []

    return render_template(
        'animais/animals.html',
        animals=animals,
        page=page,
        total_pages=pagination.pages,
        modo=modo,
        species_list=species_list,
        breed_list=breed_list,
        species_id=species_id,
        breed_id=breed_id,
        sex=sex,
        age=age,
        is_admin=_is_admin(),
        show_all=show_all
    )




@app.route('/animal/<int:animal_id>/adotar', methods=['POST'])
@login_required
def adotar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.status != 'disponível':
        flash('Este animal já foi adotado ou vendido.', 'danger')
        return redirect(url_for('list_animals'))

    animal.status = 'adotado'  # ou 'vendido', se for o caso
    animal.user_id = current_user.id  # <- transfere a posse do animal
    db.session.commit()
    flash(f'Você adotou {animal.name} com sucesso!', 'success')
    return redirect(url_for('list_animals'))


@app.route('/animal/<int:animal_id>/editar', methods=['GET', 'POST'])
@app.route('/editar_animal/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def editar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.user_id != current_user.id:
        flash('Você não tem permissão para editar este animal.', 'danger')
        return redirect(url_for('profile'))

    form = AnimalForm(obj=animal)

    species_list = list_species()
    breed_list = list_breeds()




    if form.validate_on_submit():
        animal.name = form.name.data
        animal.age = form.age.data
        animal.sex = form.sex.data
        animal.description = form.description.data
        animal.modo = form.modo.data
        animal.price = form.price.data if form.modo.data == 'venda' else None

        # Data de nascimento calculada a partir da idade se necessário
        dob = form.date_of_birth.data
        if not dob and form.age.data:
            try:
                age_years = int(form.age.data)
                dob = date.today() - relativedelta(years=age_years)
            except ValueError:
                dob = None
        animal.date_of_birth = dob

        # Relacionamentos
        species_id = request.form.get('species_id')
        breed_id = request.form.get('breed_id')
        if species_id:
            animal.species_id = int(species_id)
        if breed_id:
            animal.breed_id = int(breed_id)

        # Upload da nova imagem, se fornecida
        if form.image.data and getattr(form.image.data, 'filename', ''):
            file = form.image.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            image_url = upload_to_s3(file, filename, folder="animals")
            if image_url:
                animal.image = image_url

        db.session.commit()
        flash('Animal atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    return render_template('animais/editar_animal.html',
                           form=form,
                           animal=animal,
                           species_list=species_list,
                           breed_list=breed_list)


@app.route('/mensagem/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def enviar_mensagem(animal_id):
    animal = get_animal_or_404(animal_id)
    form = MessageForm()

    if animal.user_id == current_user.id:
        flash("Você não pode enviar mensagem para si mesmo.", "warning")
        return redirect(url_for('list_animals'))

    if form.validate_on_submit():
        msg = Message(
            sender_id=current_user.id,
            receiver_id=animal.user_id,
            animal_id=animal.id,
            content=form.content.data
        )
        db.session.add(msg)
        db.session.commit()
        flash('Mensagem enviada com sucesso!', 'success')
        return redirect(url_for('list_animals'))

    return render_template('mensagens/enviar_mensagem.html', form=form, animal=animal)


@app.route('/mensagem/<int:message_id>/aceitar', methods=['POST'])
@login_required
def aceitar_interesse(message_id):
    mensagem = Message.query.get_or_404(message_id)

    if mensagem.animal.owner.id != current_user.id:
        flash("Você não tem permissão para aceitar esse interesse.", "danger")
        return redirect(url_for('conversa', animal_id=mensagem.animal.id, user_id=mensagem.sender_id))

    animal = mensagem.animal
    animal.status = 'adotado'
    animal.user_id = mensagem.sender_id
    db.session.commit()

    flash(f"Você aceitou a adoção de {animal.name} por {mensagem.sender.name}.", "success")
    return redirect(url_for('conversa', animal_id=animal.id, user_id=mensagem.sender_id))


@app.route('/mensagens')
@login_required
def mensagens():
    return _render_messages_page()


@app.route('/chat/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def chat_messages(animal_id):
    """API simples para listar e criar mensagens relacionadas a um animal."""
    get_animal_or_404(animal_id)
    if request.method == 'GET':
        mensagens = (
            Message.query
            .filter_by(animal_id=animal_id)
            .order_by(Message.timestamp)
            .all()
        )
        return jsonify([
            {
                'id': m.id,
                'sender_id': m.sender_id,
                'receiver_id': m.receiver_id,
                'animal_id': m.animal_id,
                'clinica_id': m.clinica_id,
                'content': m.content,
                'timestamp': m.timestamp.isoformat(),
            }
            for m in mensagens
        ])

    data = request.get_json() or {}
    nova_msg = Message(
        sender_id=data.get('sender_id', current_user.id),
        receiver_id=data['receiver_id'],
        animal_id=animal_id,
        clinica_id=data.get('clinica_id'),
        content=data['content'],
    )
    db.session.add(nova_msg)
    db.session.commit()
    return (
        jsonify(
            {
                'id': nova_msg.id,
                'sender_id': nova_msg.sender_id,
                'receiver_id': nova_msg.receiver_id,
                'animal_id': nova_msg.animal_id,
                'clinica_id': nova_msg.clinica_id,
                'content': nova_msg.content,
                'timestamp': nova_msg.timestamp.isoformat(),
            }
        ),
        201,
    )


@app.route('/chat/<int:animal_id>/view')
@login_required
def chat_view(animal_id):
    animal = get_animal_or_404(animal_id)
    return render_template('chat/conversa.html', animal=animal)


@app.route('/conversa/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def conversa(animal_id, user_id):
    animal = get_animal_or_404(animal_id)
    outro_usuario = User.query.get_or_404(user_id)
    interesse_existente = Interest.query.filter_by(
        user_id=outro_usuario.id, animal_id=animal.id).first()

    form = MessageForm()

    # Busca todas as mensagens entre current_user e outro_usuario sobre o animal
    mensagens = Message.query.filter(
        Message.animal_id == animal.id,
        ((Message.sender_id == current_user.id) & (Message.receiver_id == outro_usuario.id)) |
        ((Message.sender_id == outro_usuario.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()

    # Enviando nova mensagem
    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=outro_usuario.id,
            animal_id=animal.id,
            content=form.content.data,
            lida=False

        )
        db.session.add(nova_msg)
        db.session.commit()
        return redirect(url_for('conversa', animal_id=animal.id, user_id=outro_usuario.id))

    updated = False
    for m in mensagens:
        if m.receiver_id == current_user.id and not m.lida:
            m.lida = True
            updated = True
    if updated:
        db.session.commit()

    return render_template(
        'mensagens/conversa.html',
        mensagens=mensagens,
        form=form,
        animal=animal,
        outro_usuario=outro_usuario,
        interesse_existente=interesse_existente
    )


@app.route('/api/conversa/<int:animal_id>/<int:user_id>', methods=['POST'])
@login_required
def api_conversa_message(animal_id, user_id):
    """Recebe uma nova mensagem da conversa e retorna o HTML renderizado."""
    form = MessageForm()
    get_animal_or_404(animal_id)
    outro_usuario = User.query.get_or_404(user_id)
    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=outro_usuario.id,
            animal_id=animal_id,
            content=form.content.data,
            lida=False
        )
        db.session.add(nova_msg)
        db.session.commit()
        return render_template('components/message.html', msg=nova_msg)
    return '', 400


@app.route('/conversa_admin', methods=['GET', 'POST'])
@app.route('/conversa_admin/<int:user_id>', methods=['GET', 'POST'])
@login_required
def conversa_admin(user_id=None):
    """Permite conversar diretamente com o administrador.

    - Usuários comuns acessam ``/conversa_admin`` para falar com o admin.
    - O administrador acessa ``/conversa_admin/<user_id>`` para responder
      mensagens de um usuário específico.
    """

    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        flash('Administrador não encontrado.', 'danger')
        return redirect(url_for('mensagens'))

    form = MessageForm()

    if current_user.is_authenticated and current_user.role == 'admin':
        if user_id is None:
            flash('Selecione um usuário para conversar.', 'warning')
            return redirect(url_for('mensagens_admin'))
        interlocutor = User.query.get_or_404(user_id)
        admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
        participant_id = interlocutor.id
    else:
        interlocutor = admin_user
        admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
        participant_id = current_user.id

    mensagens = (
        Message.query
        .filter(
            ((Message.sender_id.in_(admin_ids)) & (Message.receiver_id == participant_id)) |
            ((Message.sender_id == participant_id) & (Message.receiver_id.in_(admin_ids)))
        )
        .order_by(Message.timestamp)
        .all()
    )

    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=interlocutor.id,
            content=form.content.data,
            lida=False
        )
        db.session.add(nova_msg)
        db.session.commit()
        if current_user.role == 'admin':
            return redirect(url_for('conversa_admin', user_id=interlocutor.id))
        return redirect(url_for('conversa_admin'))

    for m in mensagens:
        if current_user.role == 'admin':
            if m.receiver_id in admin_ids and not m.lida:
                m.lida = True
        else:
            if m.receiver_id == current_user.id and not m.lida:
                m.lida = True
    db.session.commit()

    return render_template(
        'mensagens/conversa_admin.html',
        mensagens=mensagens,
        form=form,
        admin=interlocutor
    )


@app.route('/api/conversa_admin', methods=['POST'])
@app.route('/api/conversa_admin/<int:user_id>', methods=['POST'])
@login_required
def api_conversa_admin_message(user_id=None):
    """Recebe nova mensagem na conversa com o admin e retorna HTML."""
    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        abort(404)

    if current_user.role == 'admin':
        if user_id is None:
            return '', 400
        interlocutor = User.query.get_or_404(user_id)
    else:
        interlocutor = admin_user

    form = MessageForm()
    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=interlocutor.id,
            content=form.content.data,
            lida=False,
        )
        db.session.add(nova_msg)
        db.session.commit()
        return render_template('components/message.html', msg=nova_msg)
    return '', 400


@app.route('/mensagens_admin')
@login_required
def mensagens_admin():
    """Lista as conversas iniciadas pelos usuários com o administrador."""
    if current_user.role != 'admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('index'))

    admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]

    all_msgs = (
        Message.query
        .filter((Message.sender_id.in_(admin_ids)) | (Message.receiver_id.in_(admin_ids)))
        .order_by(Message.timestamp.desc())
        .all()
    )

    # usuários que enviaram alguma mensagem geral para qualquer admin
    users_contacted_admin = {
        m.sender_id for m in all_msgs
        if m.receiver_id in admin_ids and m.animal_id is None
    }

    latest_animais = {}
    latest_geral = {}
    for m in all_msgs:
        other_id = m.sender_id if m.sender_id not in admin_ids else m.receiver_id
        if m.animal_id:
            if other_id not in latest_animais:
                latest_animais[other_id] = m
        else:
            if other_id in users_contacted_admin and other_id not in latest_geral:
                latest_geral[other_id] = m

    mensagens_animais = list(latest_animais.values())
    mensagens_gerais = list(latest_geral.values())

    unread = (
        db.session.query(Message.sender_id, db.func.count())
        .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
        .group_by(Message.sender_id)
        .all()
    )
    unread_counts = {u[0]: u[1] for u in unread}

    return render_template(
        'mensagens/mensagens_admin.html',
        mensagens_animais=mensagens_animais,
        mensagens_gerais=mensagens_gerais,
        unread_counts=unread_counts
    )


@app.context_processor
def inject_unread_count():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
            unread = (
                Message.query
                .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
                .count()
            )
        else:
            unread = (
                Message.query
                .filter_by(receiver_id=current_user.id, lida=False)
                .count()
            )
        return dict(unread_messages=unread)
    return dict(unread_messages=0)


@app.context_processor
def inject_mp_public_key():
    """Disponibiliza a chave pública do Mercado Pago para os templates."""
    return dict(MERCADOPAGO_PUBLIC_KEY=current_app.config.get("MERCADOPAGO_PUBLIC_KEY"))


@app.context_processor
def inject_default_pickup_address():
    """Exposes DEFAULT_PICKUP_ADDRESS config to templates."""
    return dict(DEFAULT_PICKUP_ADDRESS=current_app.config.get("DEFAULT_PICKUP_ADDRESS"))


@app.route('/animal/<int:animal_id>/deletar', methods=['POST'])
@login_required
def deletar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if not (
        current_user.role == 'admin'
        or animal.user_id == current_user.id
        or animal.added_by_id == current_user.id
    ):
        message = 'Você não tem permissão para excluir este animal.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='danger'), 403
        flash(message, 'danger')
        abort(403)

    if animal.removido_em:
        message = 'Animal já foi removido anteriormente.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='warning'), 400
        flash(message, 'warning')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    animal.removido_em = datetime.utcnow()
    db.session.commit()
    message = 'Animal marcado como removido. Histórico preservado.'
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message=message, category='success', deleted=True)
    flash(message, 'success')
    return redirect(request.referrer or url_for('list_animals'))


@app.route('/termo/interesse/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_interesse(animal_id, user_id):
    animal = get_animal_or_404(animal_id)
    interessado = User.query.get_or_404(user_id)

    if request.method == 'POST':
        # Verifica se já existe um interesse registrado
        interesse_existente = Interest.query.filter_by(
            user_id=interessado.id, animal_id=animal.id).first()

        if not interesse_existente:
            # Cria novo interesse
            novo_interesse = Interest(user_id=interessado.id, animal_id=animal.id)
            db.session.add(novo_interesse)

            # Cria mensagem automática
            mensagem = Message(
                sender_id=current_user.id,
                receiver_id=animal.user_id,
                animal_id=animal.id,
                content=f"Tenho interesse em {'comprar' if animal.modo == 'venda' else 'adotar'} o animal {animal.name}.",
                lida=False
            )
            db.session.add(mensagem)
            db.session.commit()

            flash('Você demonstrou interesse. Aguardando aprovação do tutor.', 'info')
        else:
            flash('Você já demonstrou interesse anteriormente.', 'warning')

        return redirect(url_for('conversa', animal_id=animal.id, user_id=animal.user_id))

    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    return render_template('termos/termo_interesse.html', animal=animal, interessado=interessado, data_atual=data_atual)


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


def enviar_mensagem_whatsapp(texto: str, numero: str) -> None:
    """Envia uma mensagem de WhatsApp usando a API do Twilio."""

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM")

    if not all([account_sid, auth_token, from_number]):
        raise RuntimeError("Credenciais do Twilio não configuradas")

    client = Client(account_sid, auth_token)
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


if not app.config.get("TESTING"):
    scheduler = BackgroundScheduler(timezone=str(BR_TZ))
    scheduler.add_job(verificar_datas_proximas, 'cron', hour=8)
    scheduler.start()


@app.route('/termo/transferencia/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_transferencia(animal_id, user_id):
    animal = get_animal_or_404(animal_id)
    novo_dono = User.query.get_or_404(user_id)

    if animal.owner.id != current_user.id:
        flash("Você não tem permissão para transferir esse animal.", "danger")
        return redirect(url_for('profile'))

    if request.method == 'POST':
        try:
            # Transfere a tutoria
            animal.user_id = novo_dono.id
            animal.status = 'indisponível'
            animal.modo = 'adotado'

            # Cria a transação
            transacao = Transaction(
                animal_id=animal.id,
                from_user_id=current_user.id,
                to_user_id=novo_dono.id,
                type='adoção' if animal.modo == 'doação' else 'venda',
                status='concluída',
                date=datetime.utcnow()
            )
            db.session.add(transacao)

            # Envia uma mensagem interna para o novo tutor
            msg = Message(
                sender_id=current_user.id,
                receiver_id=novo_dono.id,
                animal_id=animal.id,
                content=f"Parabéns! Você agora é o tutor de {animal.name}. 🐾",
                lida=False
            )
            db.session.add(msg)

            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao transferir tutoria")
            flash('Ocorreu um erro ao transferir a tutoria.', 'danger')
        else:
            flash(f'Tutoria de {animal.name} transferida para {novo_dono.name}.', 'success')

            # WhatsApp para o novo tutor
            if novo_dono.phone:
                numero_formatado = f"whatsapp:{formatar_telefone(novo_dono.phone)}"
                texto_wpp = f"Parabéns, {novo_dono.name}! Agora você é o tutor de {animal.name} pelo PetOrlândia. 🐶🐱"

                try:
                    enviar_mensagem_whatsapp(texto_wpp, numero_formatado)
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        return redirect(url_for('profile'))

    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    return render_template('termos/termo_transferencia.html', animal=animal, novo_dono=novo_dono)

@app.route('/animal/<int:animal_id>/termo/<string:tipo>')
@login_required
def termo_animal(animal_id, tipo):
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    clinica = current_user.veterinario.clinica if current_user.veterinario else None
    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    templates = {
        'internacao': 'termos/termo_internacao.html',
        'eutanasia': 'termos/termo_eutanasia.html',
        'procedimentos': 'termos/termo_procedimentos.html',
        'exames': 'termos/termo_exames.html',
        'imagem': 'termos/termo_imagem.html',
        'medicacao': 'termos/termo_medicacao.html',
        'planos': 'termos/termo_planos.html',
        'adocao': 'termos/termo_adocao.html',
    }
    template = templates.get(tipo)
    if not template:
        abort(404)
    return render_template(template, animal=animal, tutor=tutor, clinica=clinica, data_atual=data_atual)




@app.route('/termo/<int:animal_id>/<tipo>')
@login_required
def gerar_termo(animal_id, tipo):
    """Gera um termo específico para um animal."""
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    veterinario = current_user.veterinario
    template_name = f'termos/{tipo}.html'
    try:
        return render_template(
            template_name,
            animal=animal,
            tutor=tutor,
            veterinario=veterinario,
            tipo=tipo,
        )
    except TemplateNotFound:
        abort(404)


@app.route("/plano-saude")
@login_required
def plano_saude_overview():
    # animais ativos do tutor
    animais_do_usuario = (
        Animal.query
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .all()
    )

    # assinaturas de plano de saúde do tutor → dict {animal_id: sub}
    from models import HealthSubscription
    subs = (
        HealthSubscription.query
        .filter_by(user_id=current_user.id, active=True)
        .all()
    )
    subscriptions = {s.animal_id: s for s in subs}

    return render_template(
        "planos/plano_saude_overview.html",
        animais=animais_do_usuario,
        subscriptions=subscriptions,   # ← agora o template encontra
        user=current_user,
    )

from forms import SubscribePlanForm   # coloque o import lá no topo

@app.route("/animal/<int:animal_id>/planosaude", methods=["GET", "POST"])
@login_required
def planosaude_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.owner != current_user:
        flash("Você não tem permissão para acessar esse animal.", "danger")
        return redirect(url_for("profile"))

    form = SubscribePlanForm()
    from models import HealthPlan, HealthSubscription
    plans = HealthPlan.query.all()
    form.plan_id.choices = [
        (p.id, f"{p.name} - R$ {p.price:.2f}") for p in plans
    ]
    plans_data = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": p.price,
        }
        for p in plans
    ]
    subscription = (
        HealthSubscription.query
        .filter_by(animal_id=animal.id, user_id=current_user.id, active=True)
        .first()
    )

    if form.validate_on_submit():
        # TODO: processar contratação do plano aqui…
        flash("Plano de saúde contratado!", "success")
        return redirect(url_for("planosaude_animal", animal_id=animal_id))

    return render_template(
        "animais/planosaude_animal.html",
        animal=animal,
        form=form,        # {{ form.hidden_tag() }} agora existe
        subscription=subscription,
        plans=plans_data,
    )



@app.route("/plano-saude/<int:animal_id>/contratar", methods=["POST"])
@login_required
def contratar_plano(animal_id):
    """Inicia a assinatura de um plano de saúde via Mercado Pago."""
    animal = get_animal_or_404(animal_id)

    if animal.owner != current_user:
        flash("Você não tem permissão para contratar este plano.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    form = SubscribePlanForm()
    from models import HealthPlan
    plans = HealthPlan.query.all()
    form.plan_id.choices = [
        (p.id, f"{p.name} - R$ {p.price:.2f}") for p in plans
    ]
    if not form.validate_on_submit():
        flash("Selecione um plano válido.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    plan = HealthPlan.query.get_or_404(form.plan_id.data)

    preapproval_data = {
        "reason": f"{plan.name} - {animal.name}",
        "back_url": url_for("planosaude_animal", animal_id=animal.id, _external=True),
        "payer_email": current_user.email,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(plan.price),
            "currency_id": "BRL",
        },
    }

    try:
        resp = mp_sdk().preapproval().create(preapproval_data)
    except Exception:  # pragma: no cover - network failures
        app.logger.exception("Erro de conexão com Mercado Pago")
        flash("Falha ao conectar com Mercado Pago.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    if resp.get("status") not in {200, 201}:
        app.logger.error("MP error (HTTP %s): %s", resp.get("status"), resp)
        flash("Erro ao iniciar assinatura.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    init_point = (resp.get("response", {}).get("init_point") or
                  resp.get("response", {}).get("sandbox_init_point"))
    if not init_point:
        flash("Erro ao iniciar assinatura.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    return redirect(init_point)








@app.route('/animal/<int:animal_id>/ficha')
@login_required
def ficha_animal(animal_id):
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner

    consultas_query = Consulta.query.filter_by(
        animal_id=animal.id,
        status='finalizada',
    )
    if (
        current_user.role != 'admin'
        and current_user.worker in ['veterinario', 'colaborador']
    ):
        consultas_query = consultas_query.filter_by(
            clinica_id=current_user_clinic_id()
        )
    consultas = consultas_query.order_by(Consulta.created_at.desc()).all()

    blocos_prescricao = BlocoPrescricao.query.filter_by(animal_id=animal.id).all()
    blocos_exames = BlocoExames.query.filter_by(animal_id=animal.id).all()

    vacinas_aplicadas = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=True)
        .order_by(Vacina.aplicada_em.desc())
        .all()
    )
    vacinas_agendadas = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
        .filter(Vacina.aplicada_em >= date.today())
        .order_by(Vacina.aplicada_em)
        .all()
    )
    doses_atrasadas = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
        .filter(Vacina.aplicada_em < date.today())
        .order_by(Vacina.aplicada_em)
        .all()
    )

    now = datetime.utcnow()
    retornos = (
        Appointment.query.filter_by(animal_id=animal.id)
        .filter(Appointment.scheduled_at >= now)
        .filter(Appointment.status.in_(["scheduled", "accepted"]))
        .filter(Appointment.consulta_id.isnot(None))
        .order_by(Appointment.scheduled_at)
        .all()
    )
    exames_agendados = (
        ExamAppointment.query.filter_by(animal_id=animal.id)
        .filter(ExamAppointment.scheduled_at >= now)
        .filter(ExamAppointment.status.in_(["pending", "confirmed"]))
        .order_by(ExamAppointment.scheduled_at)
        .all()
    )

    return render_template(
        'animais/ficha_animal.html',
        animal=animal,
        tutor=tutor,
        consultas=consultas,
        blocos_prescricao=blocos_prescricao,
        blocos_exames=blocos_exames,
        vacinas_aplicadas=vacinas_aplicadas,
        vacinas_agendadas=vacinas_agendadas,
        doses_atrasadas=doses_atrasadas,
        retornos=retornos,
        exames_agendados=exames_agendados,
    )
@app.route('/animal/<int:animal_id>/documentos', methods=['POST'])
@login_required
def upload_document(animal_id):
    animal = get_animal_or_404(animal_id)
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem enviar documentos.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    file = request.files.get('documento')
    if not file or file.filename == '':
        flash('Nenhum arquivo enviado.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    descricao = (request.form.get('descricao') or '').strip().lower()
    tipo_termo = (request.form.get('tipo') or descricao)
    filename_base = secure_filename(file.filename)
    ext = os.path.splitext(filename_base)[1]
    if tipo_termo in ['termo_interesse', 'termo_transferencia']:
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{tipo_termo}_{animal.id}_{timestamp}{ext}"
    else:
        filename = f"{uuid.uuid4().hex}_{filename_base}"

    file_url = upload_to_s3(file, filename, folder='documentos')
    if not file_url:
        flash('Falha ao enviar arquivo.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    documento = AnimalDocumento(
        animal_id=animal.id,
        veterinario_id=current_user.id,
        filename=filename,
        file_url=file_url,
        descricao=descricao
    )
    db.session.add(documento)
    db.session.commit()

    flash('Documento enviado com sucesso!', 'success')
    return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))


@app.route('/animal/<int:animal_id>/documentos/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(animal_id, doc_id):
    documento = AnimalDocumento.query.filter_by(id=doc_id, animal_id=animal_id).first_or_404()

    if not (
        current_user.role == 'admin'
        or (
            current_user.worker == 'veterinario'
            and current_user.id == documento.veterinario_id
        )
    ):
        flash('Você não tem permissão para excluir este documento.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal_id))

    prefix = f"https://{BUCKET}.s3.amazonaws.com/"
    if documento.file_url and documento.file_url.startswith(prefix):
        key = documento.file_url[len(prefix):]
        try:
            _s3().delete_object(Bucket=BUCKET, Key=key)
        except Exception as exc:  # noqa: BLE001
            app.logger.exception('Falha ao remover arquivo do S3: %s', exc)

    db.session.delete(documento)
    db.session.commit()

    flash('Documento excluído com sucesso!', 'success')
    return redirect(request.referrer or url_for('ficha_animal', animal_id=animal_id))






@app.route('/animal/<int:animal_id>/editar_ficha', methods=['GET', 'POST'])
@login_required
def editar_ficha_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    # Dados fictícios para fins de edição simples (substituir por formulário real depois)
    if request.method == 'POST':
        nova_vacina = request.form.get("vacina")
        nova_consulta = request.form.get("consulta")
        novo_medicamento = request.form.get("medicamento")

        print(f"Vacina adicionada: {nova_vacina}")
        print(f"Consulta adicionada: {nova_consulta}")
        print(f"Medicação adicionada: {novo_medicamento}")

        flash("Informacões adicionadas com sucesso (simulação).", "success")
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    return render_template("editar_ficha.html", animal=animal)


@app.route('/generate_qr/<int:animal_id>')
@login_required
def generate_qr(animal_id):
    animal = get_animal_or_404(animal_id)
    if current_user.id != animal.user_id:
        flash('Você não tem permissão para gerar o QR code deste animal.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal_id))

    # Gera token
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(minutes=10)  # por exemplo, 10 minutos

    qr_token = ConsultaToken(
        token=token,
        animal_id=animal.id,
        tutor_id=current_user.id,
        expires_at=expires
    )
    db.session.add(qr_token)
    db.session.commit()

    consulta_url = url_for('consulta_qr', token=token, _external=True)
    img = qrcode.make(consulta_url)

    buffer = BytesIO()
    img.save(buffer)
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')




@app.route('/consulta_qr', methods=['GET'])
@login_required
def consulta_qr():
    animal_id = request.args.get('animal_id', type=int)
    token = request.args.get('token')  # se estiver usando QR com token

    # Aqui você já deve ter carregado o animal
    animal = get_animal_or_404(animal_id)
    clinica_id = current_user_clinic_id()

    # Idade e unidade (anos/meses)
    idade = ''
    idade_unidade = ''
    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            idade = delta.years
            idade_unidade = 'ano' if delta.years == 1 else 'anos'
        else:
            idade = delta.months
            idade_unidade = 'mês' if delta.months == 1 else 'meses'
    elif animal.age:
        partes = str(animal.age).split()
        try:
            idade = int(partes[0])
        except (ValueError, IndexError):
            idade = ''
        if len(partes) > 1:
            idade_unidade = partes[1]


    # Lógica adicional
    tutor = animal.owner
    consulta = (
        Consulta.query
        .filter_by(animal_id=animal.id, clinica_id=clinica_id)
        .order_by(Consulta.id.desc())
        .first()
    )
    tutor_form = EditProfileForm(obj=tutor)

    servicos = []
    if clinica_id:
        servicos = (
            ServicoClinica.query
            .filter_by(clinica_id=clinica_id)
            .order_by(ServicoClinica.descricao)
            .all()
        )

    return render_template(
        'consulta_qr.html',
        tutor=tutor,
        animal=animal,
        consulta=consulta,
        animal_idade=idade,
        animal_idade_unidade=idade_unidade,
        tutor_form=tutor_form,
        servicos=servicos,
    )








@app.route('/consulta/<int:animal_id>')
@login_required
def consulta_direct(animal_id):
    if current_user.worker not in ['veterinario', 'colaborador']:
        abort(403)

    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    clinica_id = current_user_clinic_id()

    appointment_id = request.args.get('appointment_id', type=int)
    appointment = None
    if appointment_id:
        appointment = Appointment.query.get_or_404(appointment_id)
        if appointment.animal_id != animal.id:
            abort(404)
        appointment_clinic_id = appointment.clinica_id or (
            appointment.veterinario.clinica_id if appointment.veterinario else None
        )
        if not appointment_clinic_id and getattr(appointment, 'animal', None):
            appointment_clinic_id = appointment.animal.clinica_id
        if appointment_clinic_id:
            ensure_clinic_access(appointment_clinic_id)
            if clinica_id and appointment_clinic_id != clinica_id:
                abort(404)
            if not clinica_id:
                clinica_id = appointment_clinic_id

    edit_id = request.args.get('c', type=int)
    edit_mode = False

    consulta = None
    if current_user.worker == 'veterinario':
        consulta_created = False
        appointment_updated = False

        if edit_id:
            consulta = get_consulta_or_404(edit_id)
            edit_mode = True
        else:
            if appointment and appointment.consulta_id:
                consulta_vinculada = get_consulta_or_404(appointment.consulta_id)
                if consulta_vinculada.status != 'finalizada':
                    consulta = consulta_vinculada

            if not consulta:
                consulta = (
                    Consulta.query
                    .filter_by(animal_id=animal.id, status='in_progress', clinica_id=clinica_id)
                    .first()
                )

            if not consulta:
                consulta = Consulta(
                    animal_id=animal.id,
                    created_by=current_user.id,
                    clinica_id=clinica_id,
                    status='in_progress'
                )
                db.session.add(consulta)
                consulta_created = True

        if appointment and consulta:
            if appointment.consulta_id != consulta.id:
                appointment.consulta = consulta
                appointment_updated = True

            vet_profile = getattr(current_user, 'veterinario', None)
            if (
                vet_profile
                and appointment.veterinario_id == getattr(vet_profile, 'id', None)
                and appointment.status not in {'completed', 'canceled'}
                and appointment.status != 'accepted'
            ):
                appointment.status = 'accepted'
                appointment_updated = True

        if consulta_created or appointment_updated:
            db.session.commit()
    else:
        consulta = None

    historico = []
    if current_user.worker == 'veterinario':
        historico = (
            Consulta.query
            .filter_by(animal_id=animal.id, status='finalizada', clinica_id=clinica_id)
            .order_by(Consulta.created_at.desc())
            .limit(10)
            .all()
        )

    tipos_racao = list_rations()
    marcas_existentes = sorted(set([t.marca for t in tipos_racao if t.marca]))
    linhas_existentes = sorted(set([t.linha for t in tipos_racao if t.linha]))

    # 🆕 Carregar listas de espécies e raças para o formulário
    species_list = list_species()
    breed_list = list_breeds()

    form = AnimalForm(obj=animal)
    tutor_form = EditProfileForm(obj=tutor)

    appointment_form = None
    if consulta:
        from models import Veterinario

        appointment_form = AppointmentForm()
        appointment_form.animal_id.choices = [(animal.id, animal.name)]
        appointment_form.animal_id.data = animal.id
        vet_obj = None
        if consulta.veterinario and getattr(consulta.veterinario, "veterinario", None):
            vet_obj = consulta.veterinario.veterinario
        if vet_obj:
            vets = (
                Veterinario.query.filter_by(
                    clinica_id=current_user_clinic_id()
                ).all()
            )
            appointment_form.veterinario_id.choices = [
                (v.id, v.user.name) for v in vets
            ]
            appointment_form.veterinario_id.data = vet_obj.id

    # Idade e unidade (anos/meses)
    idade = ''
    idade_unidade = ''
    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            idade = delta.years
            idade_unidade = 'ano' if delta.years == 1 else 'anos'
        else:
            idade = delta.months
            idade_unidade = 'mês' if delta.months == 1 else 'meses'
    elif animal.age:
        partes = str(animal.age).split()
        try:
            idade = int(partes[0])
        except (ValueError, IndexError):
            idade = ''
        if len(partes) > 1:
            idade_unidade = partes[1]

    servicos = []
    if clinica_id:
        servicos = (
            ServicoClinica.query
            .filter_by(clinica_id=clinica_id)
            .order_by(ServicoClinica.descricao)
            .all()
        )

    return render_template(
        'consulta_qr.html',
        animal=animal,
        tutor=tutor,
        consulta=consulta,
        historico_consultas=historico,
        edit_mode=edit_mode,
        worker=current_user.worker,
        tipos_racao=tipos_racao,
        marcas_existentes=marcas_existentes,
        linhas_existentes=linhas_existentes,
        species_list=species_list,
        breed_list=breed_list,
        form=form,
        tutor_form=tutor_form,
        animal_idade=idade,
        animal_idade_unidade=idade_unidade,
        servicos=servicos,
        appointment_form=appointment_form,
    )



@app.route('/finalizar_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def finalizar_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem finalizar consultas.', 'danger')
        return redirect(url_for('index'))

    consulta.status = 'finalizada'
    consulta.finalizada_em = datetime.utcnow()
    appointment = consulta.appointment
    if appointment and appointment.status != 'completed':
        appointment.status = 'completed'

    # Mensagem de resumo para o tutor
    resumo = (
        f"Consulta do {consulta.animal.name} finalizada.\n"
        f"Queixa: {consulta.queixa_principal or 'N/A'}\n"
        f"Conduta: {consulta.conduta or 'N/A'}\n"
        f"Prescrição: {consulta.prescricao or 'N/A'}"
    )
    msg = Message(
        sender_id=current_user.id,
        receiver_id=consulta.animal.owner.id,
        animal_id=consulta.animal_id,
        content=resumo,
    )
    db.session.add(msg)

    if appointment:
        db.session.commit()
        flash('Consulta finalizada e retorno já agendado.', 'success')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    # Prepara formulário de retorno com dados padrão
    form = AppointmentForm()
    form.animal_id.choices = [(consulta.animal.id, consulta.animal.name)]
    form.animal_id.data = consulta.animal.id
    from models import Veterinario

    vets = (
        Veterinario.query.filter_by(
            clinica_id=current_user_clinic_id()
        ).all()
    )
    form.veterinario_id.choices = [(v.id, v.user.name) for v in vets]
    form.veterinario_id.data = consulta.veterinario.veterinario.id

    dias_retorno = current_app.config.get('DEFAULT_RETURN_DAYS', 7)
    data_recomendada = (datetime.now(BR_TZ) + timedelta(days=dias_retorno)).date()
    form.date.data = data_recomendada
    form.time.data = time(10, 0)

    db.session.commit()
    flash('Consulta finalizada e registrada no histórico! Agende o retorno.', 'success')
    return render_template('agendamentos/confirmar_retorno.html', consulta=consulta, form=form)


@app.route('/agendar_retorno/<int:consulta_id>', methods=['POST'])
@login_required
def agendar_retorno(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        abort(403)
    from models import Veterinario

    form = AppointmentForm()
    form.animal_id.choices = [(consulta.animal.id, consulta.animal.name)]
    vets = (
        Veterinario.query.filter_by(
            clinica_id=current_user_clinic_id()
        ).all()
    )
    form.veterinario_id.choices = [(v.id, v.user.name) for v in vets]
    if form.validate_on_submit():
        scheduled_at_local = datetime.combine(form.date.data, form.time.data)
        vet_id = form.veterinario_id.data
        if not is_slot_available(vet_id, scheduled_at_local, kind='retorno'):
            flash('Horário indisponível para o veterinário selecionado.', 'danger')
        else:
            scheduled_at = (
                scheduled_at_local
                .replace(tzinfo=BR_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            duration = get_appointment_duration('retorno')
            if has_conflict_for_slot(vet_id, scheduled_at_local, duration):
                flash('Horário indisponível para o veterinário selecionado.', 'danger')
            else:
                current_vet = getattr(current_user, 'veterinario', None)
                same_user = current_vet and current_vet.id == vet_id
                appt = Appointment(
                    consulta_id=consulta.id,
                    animal_id=consulta.animal_id,
                    tutor_id=consulta.animal.owner.id,
                    veterinario_id=vet_id,
                    scheduled_at=scheduled_at,
                    notes=form.reason.data,
                    kind='retorno',
                    status='accepted' if same_user else 'scheduled',
                    created_by=current_user.id,
                    created_at=datetime.utcnow(),
                )
                db.session.add(appt)
                db.session.commit()
                flash('Retorno agendado com sucesso.', 'success')
    else:
        flash('Erro ao agendar retorno.', 'danger')
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/retorno/<int:appointment_id>/start', methods=['POST'])
@login_required
def iniciar_retorno(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    if current_user.worker != 'veterinario':
        abort(403)
    consulta = Consulta(
        animal_id=appt.animal_id,
        created_by=current_user.id,
        clinica_id=appt.clinica_id or current_user_clinic_id(),
        status='in_progress',
        retorno_de_id=appt.consulta_id,
    )
    db.session.add(consulta)
    appt.status = 'completed'
    db.session.commit()
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/consulta/<int:consulta_id>/deletar', methods=['POST'])
@login_required
def deletar_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal_id = consulta.animal_id
    if current_user.worker != 'veterinario':
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir consultas.'), 403
        flash('Apenas veterinários podem excluir consultas.', 'danger')
        return redirect(url_for('index'))

    db.session.delete(consulta)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = render_template(
            'partials/historico_consultas.html',
            animal=animal,
            historico_consultas=animal.consultas
        )
        return jsonify(success=True, html=historico_html)

    flash('Consulta excluída!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/imprimir_consulta/<int:consulta_id>')
@login_required
def imprimir_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal = consulta.animal
    tutor = animal.owner
    veterinario = consulta.veterinario
    clinica = consulta.clinica or (
        veterinario.veterinario.clinica if veterinario and veterinario.veterinario else None
    )

    return render_template(
        'orcamentos/imprimir_consulta.html',
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
    )




@app.route('/buscar_tutores', methods=['GET'])
def buscar_tutores():
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify([])

    query = f"%{query}%"

    # Filtra por campos individualmente e junta os resultados (sem usar or_)
    nome_matches = User.query.filter(User.name.ilike(query)).all()
    email_matches = User.query.filter(User.email.ilike(query)).all()
    cpf_matches = User.query.filter(User.cpf.ilike(query)).all()
    rg_matches = User.query.filter(User.rg.ilike(query)).all()
    phone_matches = User.query.filter(User.phone.ilike(query)).all()

    # Junta os resultados e remove duplicados (por ID)
    todos = {user.id: user for user in (
        nome_matches + email_matches + cpf_matches + rg_matches + phone_matches
    )}.values()

    resultados = [
        {
            'id': tutor.id,
            'name': tutor.name,
            'email': tutor.email,
            'specialties': ', '.join(s.nome for s in tutor.veterinario.specialties) if getattr(tutor, 'veterinario', None) else ''
        }
        for tutor in todos
    ]

    return jsonify(resultados)


@app.route('/clinicas')
def clinicas():
    clinicas = clinicas_do_usuario().all()
    return render_template('clinica/clinicas.html', clinicas=clinicas)


@app.route('/minha-clinica', methods=['GET', 'POST'])
@login_required
def minha_clinica():
    clinicas = clinicas_do_usuario().all()
    if not clinicas:
        form = ClinicForm()
        if form.validate_on_submit():
            clinica = Clinica(
                nome=form.nome.data,
                cnpj=form.cnpj.data,
                endereco=form.endereco.data,
                telefone=form.telefone.data,
                email=form.email.data,
                owner_id=current_user.id,
            )
            file = form.logotipo.data
            if file and getattr(file, "filename", ""):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                image_url = upload_to_s3(file, filename, folder="clinicas")
                if image_url:
                    clinica.logotipo = image_url
                    clinica.photo_rotation = form.photo_rotation.data
                    clinica.photo_zoom = form.photo_zoom.data
                    clinica.photo_offset_x = form.photo_offset_x.data
                    clinica.photo_offset_y = form.photo_offset_y.data
            db.session.add(clinica)
            db.session.commit()
            if current_user.veterinario:
                current_user.veterinario.clinica_id = clinica.id
            current_user.clinica_id = clinica.id
            db.session.commit()
            return redirect(url_for('clinic_detail', clinica_id=clinica.id))
        return render_template('clinica/create_clinic.html', form=form)

    if _is_admin() and current_user.clinica_id:
        return redirect(url_for('clinic_detail', clinica_id=current_user.clinica_id))
    if len(clinicas) == 1:
        return redirect(url_for('clinic_detail', clinica_id=clinicas[0].id))
    overview = []
    for c in clinicas:
        staff = c.veterinarios
        upcoming = (
            Appointment.query.filter_by(clinica_id=c.id)
            .filter(Appointment.scheduled_at >= datetime.utcnow())
            .order_by(Appointment.scheduled_at)
            .limit(5)
            .all()
        )
        overview.append({'clinic': c, 'staff': staff, 'appointments': upcoming})
    return render_template('clinica/multi_clinic_dashboard.html', clinics=overview)


def _user_can_manage_clinic(clinica):
    """Return True when the current user can manage the given clinic."""
    if not current_user.is_authenticated:
        return False
    if _is_admin():
        return True
    if current_user.id == clinica.owner_id:
        return True
    if (
        current_user.worker == 'veterinario'
        and getattr(current_user, 'veterinario', None)
        and current_user.veterinario.clinica_id == clinica.id
    ):
        return True
    return False


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


@app.route('/clinica/<int:clinica_id>', methods=['GET', 'POST'])
@login_required
def clinic_detail(clinica_id):
    if _is_admin():
        clinica = Clinica.query.get_or_404(clinica_id)
    else:
        # Para usuários não administradores, garantimos que a clínica
        # consultada pertence ao conjunto de clínicas acessíveis ao
        # usuário atual. O uso de ``filter`` com ``Clinica.id`` evita
        # possíveis ambiguidades de ``filter_by`` e assegura que o
        # ``clinica_id`` da URL seja respeitado corretamente.
        clinica = (
            clinicas_do_usuario()
            .filter(Clinica.id == clinica_id)
            .first_or_404()
        )
    from models import VetClinicInvite

    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_inventory_perm = staff.can_manage_inventory if staff else False
    show_inventory = _is_admin() or is_owner or has_inventory_perm
    inventory_form = InventoryItemForm() if show_inventory else None
    inventory_items = []
    if show_inventory:
        inventory_items = (
            ClinicInventoryItem.query
            .filter_by(clinica_id=clinica.id)
            .order_by(ClinicInventoryItem.name)
            .all()
        )
    hours_form = ClinicHoursForm()
    clinic_form = ClinicForm(obj=clinica)
    invite_form = ClinicInviteVeterinarianForm()
    invite_cancel_form = ClinicInviteCancelForm(prefix='cancel_invite')
    invite_resend_form = ClinicInviteResendForm(prefix='resend_invite')
    staff_form = ClinicAddStaffForm()
    specialist_form = ClinicAddSpecialistForm(prefix='specialist')
    if request.method == 'GET':
        hours_form.clinica_id.data = clinica.id
    pode_editar = _user_can_manage_clinic(clinica)
    if staff_form.submit.data and staff_form.validate_on_submit():
        if not (_is_admin() or current_user.id == clinica.owner_id):
            abort(403)
        user = User.query.filter_by(email=staff_form.email.data).first()
        if not user:
            flash('Usuário não encontrado', 'danger')
        else:
            staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=user.id).first()
            if staff:
                flash('Funcionário já está na clínica', 'warning')
            else:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=user.id)
                db.session.add(staff)
                user.clinica_id = clinica.id
                if getattr(user, 'veterinario', None):
                    user.veterinario.clinica_id = clinica.id
                    db.session.add(user.veterinario)
                db.session.add(user)
                db.session.commit()
                flash('Funcionário adicionado. Defina as permissões.', 'success')
                return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if specialist_form.submit.data and specialist_form.validate_on_submit():
        if not (_is_admin() or current_user.id == clinica.owner_id):
            abort(403)
        email = specialist_form.email.data.strip().lower()
        user = (
            User.query
            .filter(func.lower(User.email) == email)
            .first()
        )
        vet_profile = getattr(user, 'veterinario', None) if user else None
        if not vet_profile:
            flash('Especialista não encontrado.', 'danger')
        elif vet_profile in clinica.veterinarios_associados or vet_profile.clinica_id == clinica.id:
            flash('Especialista já associado à clínica.', 'warning')
        else:
            clinica.veterinarios_associados.append(vet_profile)
            staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=user.id).first()
            if not staff:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=user.id)
                db.session.add(staff)
            db.session.commit()
            flash('Especialista associado com sucesso. Defina as permissões.', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#especialistas')

    if clinic_form.submit.data and clinic_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        original_logo = clinica.logotipo
        clinic_form.populate_obj(clinica)
        file = clinic_form.logotipo.data
        if file and getattr(file, 'filename', ''):
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            image_url = upload_to_s3(file, filename, folder="clinicas")
            if image_url:
                clinica.logotipo = image_url
        else:
            clinica.logotipo = original_logo
        db.session.commit()
        flash('Clínica atualizada com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    if invite_form.submit.data and invite_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        email = invite_form.email.data.strip().lower()
        user = (
            User.query
            .filter(func.lower(User.email) == email)
            .first()
        )
        if not user or getattr(user, 'worker', '') != 'veterinario' or not getattr(user, 'veterinario', None):
            flash('Veterinário não encontrado.', 'danger')
        else:
            existing = VetClinicInvite.query.filter_by(
                clinica_id=clinica.id,
                veterinario_id=user.veterinario.id,
                status='pending',
            ).first()
            if user.veterinario.clinica_id == clinica.id:
                flash('Veterinário já associado à clínica.', 'warning')
            elif existing:
                flash('Convite já enviado.', 'warning')
            else:
                invite = VetClinicInvite(
                    clinica_id=clinica.id,
                    veterinario_id=user.veterinario.id,
                )
                db.session.add(invite)
                db.session.commit()
                if _send_clinic_invite_email(clinica, user, current_user):
                    flash('Convite enviado.', 'success')
                else:
                    flash(
                        'Convite criado, mas houve um problema ao enviar o e-mail para o veterinário.',
                        'warning',
                    )
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')
    if hours_form.submit.data and hours_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        for dia in hours_form.dias_semana.data:
            existentes = ClinicHours.query.filter_by(
                clinica_id=hours_form.clinica_id.data, dia_semana=dia
            ).all()
            if existentes:
                existentes[0].hora_abertura = hours_form.hora_abertura.data
                existentes[0].hora_fechamento = hours_form.hora_fechamento.data
                for extra in existentes[1:]:
                    db.session.delete(extra)
            else:
                db.session.add(
                    ClinicHours(
                        clinica_id=hours_form.clinica_id.data,
                        dia_semana=dia,
                        hora_abertura=hours_form.hora_abertura.data,
                        hora_fechamento=hours_form.hora_fechamento.data,
                    )
                )
        db.session.commit()
        flash('Horário salvo com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    horarios = ClinicHours.query.filter_by(clinica_id=clinica_id).all()
    veterinarios = Veterinario.query.filter_by(clinica_id=clinica_id).all()
    associated_vets = list(clinica.veterinarios_associados)
    veterinarios_ids = {v.id for v in veterinarios}
    specialists = [
        v for v in associated_vets if v.id not in veterinarios_ids
    ]
    specialists.sort(key=lambda vet: (vet.user.name or '').lower())
    all_veterinarios = Veterinario.query.all()
    staff_members = ClinicStaff.query.filter(
        ClinicStaff.clinic_id == clinica.id,
        ClinicStaff.user.has(User.veterinario == None),
    ).all()

    clinic_invites = (
        VetClinicInvite.query
        .filter_by(clinica_id=clinica.id)
        .order_by(VetClinicInvite.created_at.desc())
        .all()
    )
    invites_by_status = defaultdict(list)
    for invite in clinic_invites:
        invites_by_status[invite.status].append(invite)
    invites_by_status = dict(invites_by_status)
    invite_status_order = ['pending', 'declined', 'accepted', 'cancelled']

    staff_permission_forms = {}
    for s in staff_members:
        form = ClinicStaffPermissionForm(prefix=f"perm_{s.user.id}", obj=s)
        staff_permission_forms[s.user.id] = form

    vets_for_forms = unique_items_by_id(veterinarios + specialists)

    vet_permission_forms = {}
    for v in vets_for_forms:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=v.user.id).first()
        if not staff:
            staff = ClinicStaff(clinic_id=clinica.id, user_id=v.user.id)
        form = ClinicStaffPermissionForm(prefix=f"vet_perm_{v.user.id}", obj=staff)
        vet_permission_forms[v.user.id] = form

    for s in staff_members:
        form = staff_permission_forms[s.user.id]
        if form.submit.data and form.validate_on_submit():
            if not (_is_admin() or current_user.id == clinica.owner_id):
                abort(403)
            form.populate_obj(s)
            s.user_id = s.user.id
            db.session.add(s)
            db.session.commit()
            flash('Permissões atualizadas', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    for v in vets_for_forms:
        form = vet_permission_forms[v.user.id]
        if form.submit.data and form.validate_on_submit():
            if not (_is_admin() or current_user.id == clinica.owner_id):
                abort(403)
            staff = ClinicStaff.query.filter_by(
                clinic_id=clinica.id, user_id=v.user.id
            ).first()
            if not staff:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=v.user.id)
            form.populate_obj(staff)
            staff.user_id = v.user.id
            db.session.add(staff)
            db.session.commit()
            flash('Permissões atualizadas', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    vet_schedule_forms = {}
    for v in vets_for_forms:
        form = VetScheduleForm(prefix=f"schedule_{v.id}")
        form.veterinario_id.choices = [(v.id, v.user.name)]
        if request.method == 'GET':
            form.veterinario_id.data = v.id
        vet_schedule_forms[v.id] = form

    for v in vets_for_forms:
        form = vet_schedule_forms[v.id]
        if form.submit.data and form.validate_on_submit():
            if not pode_editar:
                abort(403)
            for dia in form.dias_semana.data:
                db.session.add(
                    VetSchedule(
                        veterinario_id=form.veterinario_id.data,
                        dia_semana=dia,
                        hora_inicio=form.hora_inicio.data,
                        hora_fim=form.hora_fim.data,
                        intervalo_inicio=form.intervalo_inicio.data,
                        intervalo_fim=form.intervalo_fim.data,
                    )
                )
            db.session.commit()
            flash('Horário do funcionário salvo com sucesso.', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    animais_adicionados = (
        Animal.query
        .filter_by(clinica_id=clinica_id)
        .filter(Animal.removido_em == None)
        .all()
    )
    tutores_adicionados = (
        User.query
        .filter_by(clinica_id=clinica_id)
        .filter(or_(User.worker != 'veterinario', User.worker == None))
        .all()
    )

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    start_dt = None
    end_dt = None
    if start_str:
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        except ValueError:
            start_dt = None
    if end_str:
        try:
            end_dt = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            end_dt = None

    start_dt_utc, end_dt_utc = local_date_range_to_utc(start_dt, end_dt)

    appointments_query = Appointment.query.filter_by(clinica_id=clinica_id)
    if start_dt_utc:
        appointments_query = appointments_query.filter(Appointment.scheduled_at >= start_dt_utc)
    if end_dt_utc:
        appointments_query = appointments_query.filter(Appointment.scheduled_at < end_dt_utc)

    appointments = appointments_query.order_by(Appointment.scheduled_at).all()
    appointments_grouped = group_appointments_by_day(appointments)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template(
            "partials/appointments_table.html",
            appointments_grouped=appointments_grouped,
        )

    grouped_vet_schedules = {
        v.id: group_vet_schedules_by_day(v.horarios)
        for v in vets_for_forms
    }

    orcamentos = Orcamento.query.filter_by(clinica_id=clinica_id).all()
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    next7_str = (today + timedelta(days=7)).strftime('%Y-%m-%d')
    now_dt = datetime.utcnow()

    return render_template(
        'clinica/clinic_detail.html',
        clinica=clinica,
        horarios=horarios,
        form=hours_form,
        clinic_form=clinic_form,
        invite_form=invite_form,
        invite_cancel_form=invite_cancel_form,
        invite_resend_form=invite_resend_form,
        veterinarios=veterinarios,
        all_veterinarios=all_veterinarios,
        vet_schedule_forms=vet_schedule_forms,
        staff_members=staff_members,
        staff_form=staff_form,
        specialists=specialists,
        specialist_form=specialist_form,
        staff_permission_forms=staff_permission_forms,
        vet_permission_forms=vet_permission_forms,
        appointments=appointments,
        appointments_grouped=appointments_grouped,
        grouped_vet_schedules=grouped_vet_schedules,
        orcamentos=orcamentos,
        pode_editar=pode_editar,
        animais_adicionados=animais_adicionados,
        tutores_adicionados=tutores_adicionados,
        pagination=None,
        start=start_str,
        end=end_str,
        today_str=today_str,
        next7_str=next7_str,
        now=now_dt,
        inventory_items=inventory_items,
        inventory_form=inventory_form,
        show_inventory=show_inventory,
        invites_by_status=invites_by_status,
        invite_status_order=invite_status_order,
    )


@app.route('/clinica/<int:clinica_id>/convites/<int:invite_id>/cancel', methods=['POST'])
@login_required
def cancel_clinic_invite(clinica_id, invite_id):
    """Cancel a pending clinic invite."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.clinica_id != clinica.id:
        abort(404)

    form = ClinicInviteCancelForm()
    if not form.validate_on_submit():
        abort(400)

    if invite.status != 'pending':
        flash('Somente convites pendentes podem ser cancelados.', 'warning')
    else:
        invite.status = 'cancelled'
        db.session.commit()
        flash('Convite cancelado.', 'success')

    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@app.route('/clinica/<int:clinica_id>/convites/<int:invite_id>/resend', methods=['POST'])
@login_required
def resend_clinic_invite(clinica_id, invite_id):
    """Resend a declined clinic invite."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.clinica_id != clinica.id:
        abort(404)

    form = ClinicInviteResendForm()
    if not form.validate_on_submit():
        abort(400)

    if invite.status != 'declined':
        flash('Apenas convites recusados podem ser reenviados.', 'warning')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    invite.status = 'pending'
    invite.created_at = datetime.utcnow()
    db.session.commit()

    vet_user = invite.veterinario.user if invite.veterinario else None
    if _send_clinic_invite_email(clinica, vet_user, current_user):
        flash('Convite reenviado.', 'success')
    else:
        flash('Convite reativado, mas houve um problema ao reenviar o e-mail.', 'warning')

    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@app.route('/clinica/<int:clinica_id>/veterinario', methods=['POST'])
@login_required
def create_clinic_veterinario(clinica_id):
    """Create a new veterinarian linked to a clinic."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    crmv = request.form.get('crmv', '').strip()

    if not name or not email or not crmv:
        flash('Nome, e-mail e CRMV são obrigatórios.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if User.query.filter_by(email=email).first():
        flash('E-mail já cadastrado.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if Veterinario.query.filter_by(crmv=crmv).first():
        flash('CRMV já cadastrado.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    password = uuid.uuid4().hex[:8]
    user = User(name=name, email=email, worker='veterinario')
    user.set_password(password)
    user.clinica_id = clinica.id
    db.session.add(user)

    veterinario = Veterinario(user=user, crmv=crmv, clinica=clinica)
    db.session.add(veterinario)

    db.session.add(ClinicStaff(clinic_id=clinica.id, user=user))
    db.session.commit()

    flash('Veterinário cadastrado com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@app.route('/convites/clinica', methods=['GET', 'POST'])
@login_required
def clinic_invites():
    """List pending clinic invitations for the logged veterinarian."""
    from models import Veterinario

    if getattr(current_user, "worker", None) != "veterinario":
        abort(403)

    response_form = ClinicInviteResponseForm()
    profile_form = VeterinarianProfileForm()

    vet_profile = getattr(current_user, "veterinario", None)
    anchor_redirect = redirect(url_for('mensagens', _anchor='convites-clinica'))

    if request.method == 'GET':
        return anchor_redirect

    if vet_profile is None:
        if profile_form.validate_on_submit():
            crmv = profile_form.crmv.data
            existing = (
                Veterinario.query.filter(
                    func.lower(Veterinario.crmv) == crmv.lower(),
                    Veterinario.user_id != current_user.id,
                ).first()
            )
            if existing:
                profile_form.crmv.errors.append('Este CRMV já está cadastrado.')
            else:
                vet = Veterinario(user=current_user, crmv=crmv)
                phone = profile_form.phone.data
                if phone:
                    current_user.phone = phone
                db.session.add(vet)
                db.session.commit()
                flash('Cadastro de veterinário concluído com sucesso!', 'success')
                return anchor_redirect
        return _render_messages_page(
            clinic_invite_form=response_form,
            vet_profile_form=profile_form,
            missing_vet_profile=True,
        )

    return anchor_redirect


@app.route('/convites/<int:invite_id>/<string:action>', methods=['POST'])
@login_required
def respond_clinic_invite(invite_id, action):
    """Accept or decline a clinic invitation."""
    from models import VetClinicInvite

    vet_profile, response = _ensure_veterinarian_profile()
    if response is not None:
        return response

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.veterinario_id != vet_profile.id:
        abort(403)
    if action == 'accept':
        invite.status = 'accepted'
        vet = invite.veterinario
        vet.clinica_id = invite.clinica_id
        if vet.user:
            vet.user.clinica_id = invite.clinica_id
            staff = ClinicStaff.query.filter_by(
                clinic_id=invite.clinica_id, user_id=vet.user.id
            ).first()
            if not staff:
                db.session.add(ClinicStaff(clinic_id=invite.clinica_id, user_id=vet.user.id))
        flash('Convite aceito.', 'success')
    else:
        invite.status = 'declined'
        flash('Convite recusado.', 'info')
    db.session.commit()
    return redirect(url_for('clinic_invites'))


@app.route('/clinica/<int:clinica_id>/estoque', methods=['GET', 'POST'])
@login_required
def clinic_stock(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_perm = staff.can_manage_inventory if staff else False
    if not (_is_admin() or is_owner or has_perm):
        abort(403)

    inventory_form = InventoryItemForm()
    if inventory_form.validate_on_submit():
        item = ClinicInventoryItem(
            clinica_id=clinica.id,
            name=inventory_form.name.data,
            quantity=inventory_form.quantity.data,
            unit=inventory_form.unit.data,
        )
        db.session.add(item)
        db.session.commit()
        flash('Item adicionado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')

    inventory_items = (
        ClinicInventoryItem.query
        .filter_by(clinica_id=clinica.id)
        .order_by(ClinicInventoryItem.name)
        .all()
    )
    return render_template(
        'clinica/clinic_stock.html',
        clinica=clinica,
        inventory_items=inventory_items,
        inventory_form=inventory_form,
    )


@app.route('/estoque/item/<int:item_id>/atualizar', methods=['POST'])
@login_required
def update_inventory_item(item_id):
    item = ClinicInventoryItem.query.get_or_404(item_id)
    clinica = item.clinica
    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_perm = staff.can_manage_inventory if staff else False
    if not (_is_admin() or is_owner or has_perm):
        abort(403)
    try:
        qty = int(request.form.get('quantity', item.quantity))
    except (TypeError, ValueError):
        qty = item.quantity
    item.quantity = max(0, qty)
    db.session.commit()
    message = 'Quantidade atualizada.'
    flash(message, 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(success=True, message=message, category='success', quantity=item.quantity)
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')


@app.route('/clinica/<int:clinica_id>/novo_orcamento', methods=['GET', 'POST'])
@login_required
def novo_orcamento(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if current_user.clinica_id != clinica_id and not _is_admin():
        abort(403)
    form = OrcamentoForm()
    if form.validate_on_submit():
        o = Orcamento(clinica_id=clinica_id, descricao=form.descricao.data)
        db.session.add(o)
        db.session.commit()
        flash('Orçamento criado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica_id) + '#orcamento')
    return render_template('orcamentos/orcamento_form.html', form=form, clinica=clinica)


@app.route('/orcamento/<int:orcamento_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    if current_user.clinica_id != orcamento.clinica_id and not _is_admin():
        abort(403)
    form = OrcamentoForm(obj=orcamento)
    if form.validate_on_submit():
        orcamento.descricao = form.descricao.data
        db.session.commit()
        flash('Orçamento atualizado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=orcamento.clinica_id) + '#orcamento')
    return render_template('orcamentos/orcamento_form.html', form=form, clinica=orcamento.clinica)


@app.route('/clinica/<int:clinica_id>/orcamentos')
@login_required
def orcamentos(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if current_user.clinica_id != clinica_id and not _is_admin():
        abort(403)
    lista = Orcamento.query.filter_by(clinica_id=clinica_id).all()
    return render_template('orcamentos/orcamentos.html', clinica=clinica, orcamentos=lista)


@app.route('/dashboard/orcamentos')
@login_required
def dashboard_orcamentos():
    from collections import defaultdict
    from models import Consulta, Orcamento, Payment, PaymentStatus

    consultas = Consulta.query.filter(Consulta.orcamento_items.any()).all()
    dados_consultas = []
    for consulta in consultas:
        pagamento = Payment.query.filter_by(
            external_reference=f'consulta-{consulta.id}',
            status=PaymentStatus.COMPLETED,
        ).first()
        dados_consultas.append(
            {
                'cliente': consulta.animal.owner.name if consulta.animal and consulta.animal.owner else 'N/A',
                'animal': consulta.animal.name if consulta.animal else 'N/A',
                'total': float(consulta.total_orcamento),
                'status': 'Pago' if pagamento else 'Pendente',
            }
        )

    total_por_cliente = defaultdict(lambda: {'total': 0, 'pagos': 0, 'pendentes': 0})
    total_por_animal = defaultdict(lambda: {'total': 0, 'pagos': 0, 'pendentes': 0})
    for d in dados_consultas:
        tc = total_por_cliente[d['cliente']]
        tc['total'] += d['total']
        if d['status'] == 'Pago':
            tc['pagos'] += d['total']
        else:
            tc['pendentes'] += d['total']
        ta = total_por_animal[d['animal']]
        ta['total'] += d['total']
        if d['status'] == 'Pago':
            ta['pagos'] += d['total']
        else:
            ta['pendentes'] += d['total']

    orcamentos = Orcamento.query.all()
    dados_orcamentos = [
        {'descricao': o.descricao, 'total': float(o.total)} for o in orcamentos
    ]

    return render_template(
        'orcamentos/dashboard_orcamentos.html',
        consultas=dados_consultas,
        clientes=total_por_cliente,
        animais=total_por_animal,
        orcamentos=dados_orcamentos,
    )


@app.route('/clinica/<int:clinica_id>/dashboard')
@login_required
def clinic_dashboard(clinica_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id == clinic.owner_id:
        staff = ClinicStaff(
            clinic_id=clinic.id,
            user_id=current_user.id,
            can_manage_clients=True,
            can_manage_animals=True,
            can_manage_staff=True,
            can_manage_schedule=True,
            can_manage_inventory=True,
        )
    else:
        staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=current_user.id).first()
        if not staff:
            abort(403)
    return render_template('clinica/clinic_dashboard.html', clinic=clinic, staff=staff)


@app.route('/clinica/<int:clinica_id>/funcionarios', methods=['GET', 'POST'])
@login_required
def clinic_staff(clinica_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id != clinic.owner_id:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Sem permissão'), 403
        abort(403)
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if not user:
            if request.accept_mimetypes.accept_json:
                return jsonify(success=False, message='Usuário não encontrado'), 404
            flash('Usuário não encontrado', 'danger')
        else:
            staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=user.id).first()
            if staff:
                if request.accept_mimetypes.accept_json:
                    return jsonify(success=False, message='Funcionário já está na clínica'), 400
                flash('Funcionário já está na clínica', 'warning')
            else:
                staff = ClinicStaff(clinic_id=clinic.id, user_id=user.id)
                db.session.add(staff)
                user.clinica_id = clinic.id
                if user.worker == 'veterinario' and getattr(user, 'veterinario', None):
                    user.veterinario.clinica_id = clinic.id
                    db.session.add(user.veterinario)
                db.session.add(user)
                db.session.commit()
                if request.accept_mimetypes.accept_json:
                    staff_members = ClinicStaff.query.filter_by(clinic_id=clinic.id).all()
                    html = render_template('partials/clinic_staff_rows.html', clinic=clinic, staff_members=staff_members)
                    return jsonify(success=True, html=html, message='Funcionário adicionado', category='success')
                flash('Funcionário adicionado. Defina as permissões.', 'success')
                return redirect(url_for('clinic_staff_permissions', clinica_id=clinic.id, user_id=user.id))
    staff_members = ClinicStaff.query.filter_by(clinic_id=clinic.id).all()
    if request.accept_mimetypes.accept_json:
        html = render_template('partials/clinic_staff_rows.html', clinic=clinic, staff_members=staff_members)
        return jsonify(success=True, html=html)
    return render_template('clinica/clinic_staff_list.html', clinic=clinic, staff_members=staff_members)


@app.route('/clinica/<int:clinica_id>/funcionario/<int:user_id>/permissoes', methods=['GET', 'POST'])
@login_required
def clinic_staff_permissions(clinica_id, user_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id != clinic.owner_id:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Sem permissão'), 403
        abort(403)
    user = User.query.get(user_id)
    if not user:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Usuário não encontrado'), 404
        abort(404)
    staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=user_id).first()
    if not staff:
        staff = ClinicStaff(clinic_id=clinic.id, user_id=user_id)
    form = ClinicStaffPermissionForm(obj=staff)
    if form.validate_on_submit():
        form.populate_obj(staff)
        staff.user_id = user_id
        db.session.add(staff)
        user.clinica_id = clinic.id
        db.session.add(user)
        db.session.commit()
        if request.accept_mimetypes.accept_json:
            html = render_template('partials/clinic_staff_permissions_form.html', form=form, clinic=clinic)
            return jsonify(success=True, html=html, message='Permissões atualizadas', category='success')
        flash('Permissões atualizadas', 'success')
        return redirect(url_for('clinic_dashboard', clinica_id=clinic.id))
    if request.accept_mimetypes.accept_json:
        html = render_template('partials/clinic_staff_permissions_form.html', form=form, clinic=clinic)
        return jsonify(success=True, html=html)
    return render_template('clinica/clinic_staff_permissions.html', form=form, clinic=clinic)


@app.route('/clinica/<int:clinica_id>/funcionario/<int:user_id>/remove', methods=['POST'])
@login_required
def remove_funcionario(clinica_id, user_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    staff = ClinicStaff.query.filter_by(clinic_id=clinica_id, user_id=user_id).first_or_404()
    db.session.delete(staff)
    user = User.query.get(user_id)
    if user and user.clinica_id == clinica_id:
        user.clinica_id = None
        if user.worker == 'veterinario' and getattr(user, 'veterinario', None):
            user.veterinario.clinica_id = None
            db.session.add(user.veterinario)
        db.session.add(user)
    db.session.commit()
    flash('Funcionário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/clinica/<int:clinica_id>/horario/<int:horario_id>/delete', methods=['POST'])
@login_required
def delete_clinic_hour(clinica_id, horario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    pode_editar = _is_admin() or (
        current_user.worker == 'veterinario'
        and getattr(current_user, 'veterinario', None)
        and current_user.veterinario.clinica_id == clinica_id
    ) or current_user.id == clinica.owner_id
    if not pode_editar:
        abort(403)
    horario = ClinicHours.query.filter_by(id=horario_id, clinica_id=clinica_id).first_or_404()
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/remove', methods=['POST'])
@login_required
def remove_veterinario(clinica_id, veterinario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    vet = Veterinario.query.filter_by(id=veterinario_id, clinica_id=clinica_id).first_or_404()
    vet.clinica_id = None
    if vet.user:
        # Remove clinic association and staff permissions for this user
        vet.user.clinica_id = None
        ClinicStaff.query.filter_by(
            clinic_id=clinica_id, user_id=vet.user.id
        ).delete()
    db.session.commit()
    flash('Funcionário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/clinica/<int:clinica_id>/especialista/<int:veterinario_id>/remove', methods=['POST'])
@login_required
def remove_specialist(clinica_id, veterinario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    vet = Veterinario.query.get_or_404(veterinario_id)
    if vet not in clinica.veterinarios_associados:
        abort(404)
    clinica.veterinarios_associados.remove(vet)
    staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=vet.user_id).first()
    if staff and vet.clinica_id != clinica.id:
        db.session.delete(staff)
    db.session.commit()
    flash('Especialista removido da clínica.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id) + '#especialistas')


@app.route(
    '/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/schedule/<int:horario_id>/delete',
    methods=['POST'],
)
@login_required
def delete_vet_schedule_clinic(clinica_id, veterinario_id, horario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    horario = VetSchedule.query.get_or_404(horario_id)
    vet = horario.veterinario
    if vet.id != veterinario_id:
        abort(404)
    if vet.clinica_id != clinica_id and vet not in clinica.veterinarios_associados:
        abort(404)
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/veterinarios')
def veterinarios():
    veterinarios = Veterinario.query.all()
    return render_template('veterinarios/veterinarios.html', veterinarios=veterinarios)


@app.route('/veterinario/<int:veterinario_id>')
def vet_detail(veterinario_id):
    from models import Animal, User  # import local para evitar ciclos

    veterinario = Veterinario.query.get_or_404(veterinario_id)
    horarios = (
        VetSchedule.query.filter_by(veterinario_id=veterinario_id)
        .order_by(VetSchedule.dia_semana, VetSchedule.hora_inicio)
        .all()
    )

    schedule_form = VetScheduleForm(prefix='schedule')
    appointment_form = AppointmentForm(is_veterinario=True, prefix='appointment')
    admin_default_selection_value = ''

    if current_user.is_authenticated and current_user.role == 'admin':
        agenda_veterinarios = (
            Veterinario.query.join(User).order_by(User.name).all()
        )
        agenda_colaboradores = (
            User.query.filter(User.worker == 'colaborador')
            .order_by(User.name)
            .all()
        )
        vet_choices = [(v.id, v.user.name) for v in agenda_veterinarios]
        admin_selected_view = 'veterinario'
        admin_selected_veterinario_id = veterinario.id
        admin_selected_colaborador_id = None
        default_vet = getattr(current_user, 'veterinario', None)
        if default_vet and getattr(default_vet, 'id', None):
            admin_default_selection_value = f'veterinario:{default_vet.id}'
        else:
            admin_default_selection_value = f'veterinario:{veterinario.id}'
    else:
        agenda_veterinarios = []
        agenda_colaboradores = []
        vet_choices = [(veterinario.id, veterinario.user.name)]
        admin_selected_view = None
        admin_selected_veterinario_id = None
        admin_selected_colaborador_id = None

    schedule_form.veterinario_id.choices = vet_choices
    schedule_form.veterinario_id.data = veterinario.id

    appointment_form.veterinario_id.choices = [
        (veterinario.id, veterinario.user.name)
    ]
    appointment_form.veterinario_id.data = veterinario.id

    if veterinario.clinica_id:
        animals = (
            Animal.query.filter_by(clinica_id=veterinario.clinica_id)
            .order_by(Animal.name)
            .all()
        )
    else:
        animals = Animal.query.order_by(Animal.name).all()
    appointment_form.animal_id.choices = [(a.id, a.name) for a in animals]

    weekday_order = {
        'Segunda': 0,
        'Terça': 1,
        'Quarta': 2,
        'Quinta': 3,
        'Sexta': 4,
        'Sábado': 5,
        'Domingo': 6,
    }
    horarios.sort(key=lambda h: weekday_order.get(h.dia_semana, 7))
    horarios_grouped = []
    for horario in horarios:
        if not horarios_grouped or horarios_grouped[-1]['dia'] != horario.dia_semana:
            horarios_grouped.append({'dia': horario.dia_semana, 'itens': []})
        horarios_grouped[-1]['itens'].append(horario)

    calendar_redirect_url = url_for(
        'appointments', view_as='veterinario', veterinario_id=veterinario.id
    )
    calendar_summary_vets = []
    calendar_summary_clinic_ids = []

    def build_calendar_summary_entry(vet, *, label=None, is_specialist=None):
        """Return a serializable mapping with vet summary metadata."""
        if not vet:
            return None
        vet_id = getattr(vet, 'id', None)
        if not vet_id:
            return None
        vet_user = getattr(vet, 'user', None)
        vet_name = getattr(vet_user, 'name', None)
        specialty_list = getattr(vet, 'specialty_list', None)
        entry = {
            'id': vet_id,
            'name': label if label is not None else vet_name,
            'full_name': vet_name,
            'specialty_list': specialty_list,
        }
        if label is not None:
            entry['label'] = label
        if is_specialist is None:
            is_specialist = bool(specialty_list)
        entry['is_specialist'] = bool(is_specialist)
        return entry

    def add_summary_vet(vet, *, label=None, is_specialist=None):
        if not vet:
            return
        vet_id = getattr(vet, 'id', None)
        if not vet_id:
            return
        if any(entry.get('id') == vet_id for entry in calendar_summary_vets):
            return
        entry = build_calendar_summary_entry(vet, label=label, is_specialist=is_specialist)
        if entry:
            calendar_summary_vets.append(entry)

    add_summary_vet(veterinario)

    clinic_ids = set()

    primary_clinic_id = getattr(veterinario, 'clinica_id', None)
    if primary_clinic_id:
        clinic_ids.add(primary_clinic_id)

    related_clinics = []
    main_clinic = getattr(veterinario, 'clinica', None)
    if main_clinic is not None:
        related_clinics.append(main_clinic)
    associated_clinics = getattr(veterinario, 'clinicas', None) or []
    related_clinics.extend(clinic for clinic in associated_clinics if clinic)

    for clinic in related_clinics:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id:
            clinic_ids.add(clinic_id)
        for colleague in getattr(clinic, 'veterinarios', []) or []:
            add_summary_vet(colleague)
        for colleague in getattr(clinic, 'veterinarios_associados', []) or []:
            add_summary_vet(colleague, is_specialist=True)

    if clinic_ids and len(calendar_summary_vets) == 1:
        colleagues = (
            Veterinario.query.filter(Veterinario.clinica_id.in_(clinic_ids)).all()
        )
        for colleague in colleagues:
            add_summary_vet(colleague)

    calendar_summary_clinic_ids = list(clinic_ids)

    return render_template(
        'veterinarios/vet_detail.html',
        veterinario=veterinario,
        horarios=horarios,
        horarios_grouped=horarios_grouped,
        calendar_redirect_url=calendar_redirect_url,
        schedule_form=schedule_form,
        appointment_form=appointment_form,
        agenda_veterinarios=agenda_veterinarios,
        agenda_colaboradores=agenda_colaboradores,
        admin_selected_view=admin_selected_view,
        admin_selected_veterinario_id=admin_selected_veterinario_id,
        admin_selected_colaborador_id=admin_selected_colaborador_id,
        admin_default_selection_value=admin_default_selection_value,
        calendar_summary_vets=calendar_summary_vets,
        calendar_summary_clinic_ids=calendar_summary_clinic_ids,
    )




@app.route('/admin/veterinario/<int:veterinario_id>/especialidades', methods=['GET', 'POST'])
@login_required
def edit_vet_specialties(veterinario_id):
    # Apenas o próprio veterinário ou um administrador pode alterar especialidades
    is_owner = (
        current_user.worker == 'veterinario'
        and current_user.veterinario
        and current_user.veterinario.id == veterinario_id
    )
    if not (_is_admin() or is_owner):
        flash('Apenas o próprio veterinário ou um administrador pode acessar esta página.', 'danger')
        return redirect(url_for('index'))

    veterinario = Veterinario.query.get_or_404(veterinario_id)
    form = VetSpecialtyForm()
    form.specialties.choices = [
        (s.id, s.nome) for s in Specialty.query.order_by(Specialty.nome).all()
    ]
    if form.validate_on_submit():
        veterinario.specialties = Specialty.query.filter(
            Specialty.id.in_(form.specialties.data)
        ).all()
        db.session.commit()
        flash('Especialidades atualizadas com sucesso.', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=veterinario.user_id))
    form.specialties.data = [s.id for s in veterinario.specialties]
    return render_template('agendamentos/edit_vet_specialties.html', form=form, veterinario=veterinario)


@app.route('/tutor/<int:tutor_id>')
@login_required
def obter_tutor(tutor_id):
    tutor = User.query.get_or_404(tutor_id)
    return jsonify({
        'id': tutor.id,
        'name': tutor.name,
        'phone': tutor.phone,
        'address': tutor.address,
        'cpf': tutor.cpf,
        'rg': tutor.rg,
        'email': tutor.email,
        'date_of_birth': tutor.date_of_birth.strftime('%Y-%m-%d') if tutor.date_of_birth else ''
    })


@app.route('/tutor/<int:tutor_id>')
@login_required
def tutor_detail(tutor_id):
    tutor   = User.query.get_or_404(tutor_id)
    animais = tutor.animais.order_by(Animal.name).all()
    return render_template('animais/tutor_detail.html', tutor=tutor, animais=animais)


@app.route('/tutores', methods=['GET', 'POST'])
@login_required
def tutores():
    # Restrição de acesso
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    def fetch_tutores(scope, page):
        clinic_id = current_user_clinic_id()
        if scope == 'mine':
            query = User.query.filter(User.created_at != None)
            if clinic_id:
                query = query.filter(User.clinica_id == clinic_id)
            consultas_exist = (
                db.session.query(Consulta.id)
                .join(Animal, Consulta.animal_id == Animal.id)
                .filter(
                    Consulta.created_by == current_user.id,
                    Animal.user_id == User.id,
                )
            )
            pagination = (
                query.filter(
                    or_(
                        User.added_by_id == current_user.id,
                        consultas_exist.exists(),
                    )
                )
                .order_by(User.created_at.desc())
                .paginate(page=page, per_page=9)
            )
            return pagination.items, pagination
        elif clinic_id:
            last_appt = (
                db.session.query(
                    Appointment.tutor_id,
                    func.max(Appointment.scheduled_at).label('last_at')
                )
                .filter(Appointment.clinica_id == clinic_id)
                .group_by(Appointment.tutor_id)
                .subquery()
            )

            pagination = (
                User.query
                .outerjoin(last_appt, User.id == last_appt.c.tutor_id)
                .filter(
                    or_(
                        User.clinica_id == clinic_id,
                        last_appt.c.last_at != None
                    )
                )
                .order_by(func.coalesce(last_appt.c.last_at, User.created_at).desc())
                .paginate(page=page, per_page=9)
            )
            return pagination.items, pagination
        else:
            return [], None

    # Criação de novo tutor
    if request.method == 'POST':
        name = request.form.get('tutor_name') or request.form.get('name')
        email = request.form.get('tutor_email') or request.form.get('email')

        if not name or not email:
            flash('Nome e e‑mail são obrigatórios.', 'warning')
            return redirect(url_for('tutores'))

        if User.query.filter_by(email=email).first():
            flash('Já existe um tutor com esse e‑mail.', 'warning')
            return redirect(url_for('tutores'))

        novo = User(
            name=name.strip(),
            email=email.strip(),
            role='adotante',  # padrão inicial
            clinica_id=current_user_clinic_id(),
            added_by=current_user
        )
        novo.set_password('123456789')  # ⚠️ Sugestão: depois trocar por um token de convite

        # Campos opcionais
        novo.phone = (request.form.get('tutor_phone') or request.form.get('phone') or '').strip() or None
        novo.cpf = (request.form.get('tutor_cpf') or request.form.get('cpf') or '').strip() or None
        novo.rg = (request.form.get('tutor_rg') or request.form.get('rg') or '').strip() or None
        novo.address = None

        # Data de nascimento
        date_str = request.form.get('tutor_date_of_birth') or request.form.get('date_of_birth')
        if date_str:
            try:
                novo.date_of_birth = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
            except ValueError:
                flash('Data de nascimento inválida. Use o formato AAAA-MM-DD.', 'danger')
                return redirect(url_for('tutores'))

        # Endereço
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')

        if cep and rua and cidade and estado:
            endereco = Endereco(
                cep=cep,
                rua=rua,
                numero=numero,
                complemento=complemento,
                bairro=bairro,
                cidade=cidade,
                estado=estado
            )
            db.session.add(endereco)
            db.session.flush()
            novo.endereco_id = endereco.id

        # Foto
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            novo.profile_photo = f"/static/uploads/{filename}"

        db.session.add(novo)
        db.session.commit()

        if request.accept_mimetypes.accept_json:
            scope = request.args.get('scope', 'all')
            page = request.args.get('page', 1, type=int)
            tutores_adicionados, pagination = fetch_tutores(scope, page)
            html = render_template(
                'partials/tutores_adicionados.html',
                tutores_adicionados=tutores_adicionados,
                pagination=pagination,
                scope=scope
            )
            return jsonify(message='Tutor criado com sucesso!', category='success', html=html)

        flash('Tutor criado com sucesso!', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=novo.id))

    # — GET com paginação —
    page = request.args.get('page', 1, type=int)
    scope = request.args.get('scope', 'all')
    tutores_adicionados, pagination = fetch_tutores(scope, page)

    return render_template(
        'animais/tutores.html',
        tutores_adicionados=tutores_adicionados,
        pagination=pagination,
        scope=scope
    )



@app.route('/deletar_tutor/<int:tutor_id>', methods=['POST'])
@login_required
def deletar_tutor(tutor_id):
    tutor = User.query.get_or_404(tutor_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir tutores.', 'danger')
        return redirect(url_for('index'))

    if current_user.role != 'admin' and tutor.added_by_id != current_user.id:
        message = 'Você não tem permissão para excluir este tutor.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='danger'), 403
        flash(message, 'danger')
        abort(403)

    try:
        with db.session.no_autoflush:
            for animal in tutor.animals:
                # Deletar blocos de prescrição manualmente
                for bloco in animal.blocos_prescricao:
                    db.session.delete(bloco)

                # Você pode incluir aqui: exames, vacinas, etc., se necessário

                db.session.delete(animal)

        db.session.delete(tutor)
        db.session.commit()
        flash('Tutor e todos os seus dados foram excluídos com sucesso.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir tutor: {str(e)}', 'danger')

    return redirect(url_for('tutores'))




@app.route('/buscar_animais')
@login_required
def buscar_animais():
    termo = request.args.get('q', '').lower()
    animais = Animal.query.filter(
        (Animal.name.ilike(f"%{termo}%")) |
        (Animal.species.ilike(f"%{termo}%")) |
        (Animal.breed.ilike(f"%{termo}%")) |
        (Animal.microchip_number.ilike(f"%{termo}%"))
    ).all()

    return jsonify([{
        'id': a.id,
        'name': a.name,
        'species': a.species,
        'breed': a.breed,
        'sex': a.sex,
        'date_of_birth': a.date_of_birth.strftime('%Y-%m-%d') if a.date_of_birth else '',
        'microchip_number': a.microchip_number,
        'peso': a.peso,
        'health_plan': a.health_plan,
        'neutered': int(a.neutered) if a.neutered is not None else '',
    } for a in animais])





@app.route('/update_tutor/<int:user_id>', methods=['POST'])
@login_required
def update_tutor(user_id):
    user = User.query.get_or_404(user_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    # 🔐 Permissão: veterinários ou colaboradores
    if current_user.worker not in ['veterinario', 'colaborador']:
        message = 'Apenas veterinários ou colaboradores podem editar dados do tutor.'
        flash(message, 'danger')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        return redirect(request.referrer or url_for('index'))

    # 📋 Campos básicos (exceto CPF)
    for field in ['name', 'email', 'phone', 'rg']:
        value = request.form.get(field)
        if value:
            setattr(user, field, value)

    # CPF precisa ser único
    cpf_val = request.form.get('cpf')
    if cpf_val:
        cpf_val = cpf_val.strip()
        if cpf_val != (user.cpf or ''):
            existing = User.query.filter(User.cpf == cpf_val, User.id != user.id).first()
            if existing:
                message = 'CPF já cadastrado para outro tutor.'
                flash(message, 'danger')
                if wants_json:
                    return jsonify(success=False, message=message, category='danger'), 400
                return redirect(request.referrer or url_for('index'))
        user.cpf = cpf_val

    # 📅 Data de nascimento
    date_str = request.form.get('date_of_birth')
    if date_str:
        try:
            user.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            message = 'Data de nascimento inválida. Use o formato correto.'
            flash(message, 'danger')
            if wants_json:
                return jsonify(success=False, message=message, category='danger'), 400
            return redirect(request.referrer or url_for('index'))

    # 📸 Foto de perfil
    photo = request.files.get('profile_photo')
    if photo and photo.filename:
        filename = f"{uuid.uuid4().hex}_{secure_filename(photo.filename)}"
        # Upload sincronamente para garantir a atualização imediata
        image_url = upload_to_s3(photo, filename, folder="tutors")
        if image_url:
            user.profile_photo = image_url

    # Controles de corte da foto
    try:
        user.photo_rotation = int(request.form.get('photo_rotation', user.photo_rotation or 0))
    except ValueError:
        pass
    try:
        user.photo_zoom = float(request.form.get('photo_zoom', user.photo_zoom or 1.0))
    except ValueError:
        pass
    try:
        user.photo_offset_x = float(request.form.get('photo_offset_x', user.photo_offset_x or 0))
    except ValueError:
        pass
    try:
        user.photo_offset_y = float(request.form.get('photo_offset_y', user.photo_offset_y or 0))
    except ValueError:
        pass

    # 📍 Endereço
    addr_fields = {
        k: request.form.get(k) or None
        for k in ['cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado']
    }
    required_fields = ['cep', 'rua', 'cidade', 'estado']

    if all(addr_fields.get(f) for f in required_fields):
        endereco = user.endereco or Endereco()
        for k, v in addr_fields.items():
            setattr(endereco, k, v)
        if not user.endereco_id:
            db.session.add(endereco)
            db.session.flush()
            user.endereco_id = endereco.id
    elif any(addr_fields.values()):
        message = 'Por favor, informe CEP, rua, cidade e estado.'
        flash(message, 'warning')
        if wants_json:
            return jsonify(success=False, message=message, category='warning'), 400
        return redirect(request.referrer or url_for('index'))

    # 💾 Commit final
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERRO ao salvar tutor: {e}")
        message = f'Ocorreu um erro ao salvar: {str(e)}'
        flash(message, 'danger')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 500
        return redirect(request.referrer or url_for('index'))

    message = 'Dados do tutor atualizados com sucesso!'
    flash(message, 'success')
    if wants_json:
        return jsonify(success=True, message=message, tutor_name=user.name, category='success')
    return redirect(request.referrer or url_for('index'))



# ——— FICHA DO TUTOR (dados + lista de animais) ————————————
from sqlalchemy.orm import joinedload

@app.route('/ficha_tutor/<int:tutor_id>')
@login_required
def ficha_tutor(tutor_id):
    # Restrição de acesso
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    # Dados do tutor
    tutor = User.query.get_or_404(tutor_id)

    # Lista de animais do tutor (com species e breed carregados)
    animais = Animal.query.options(
        joinedload(Animal.species),
        joinedload(Animal.breed)
    ).filter_by(user_id=tutor.id).order_by(Animal.name).all()

    # Ano atual
    current_year = datetime.now(BR_TZ).year

    # Formulários para usar o photo_cropper no template
    tutor_form = EditProfileForm(obj=tutor)
    animal_forms = {a.id: AnimalForm(obj=a) for a in animais}
    new_animal_form = AnimalForm()

    # Busca todas as espécies e raças
    species_list = list_species()
    breeds = Breed.query.options(joinedload(Breed.species)).all()

    # Mapeia raças por species_id (como string, para uso seguro no JS)
    breed_map = {}
    for breed in breeds:
        sp_id = str(breed.species.id)
        breed_map.setdefault(sp_id, []).append({
            'id': breed.id,
            'name': breed.name
        })

    return render_template(
        'animais/tutor_detail.html',
        tutor=tutor,
        endereco=tutor.endereco,  # Passa explicitamente o endereço
        animais=animais,
        current_year=current_year,
        species_list=species_list,
        breed_map=breed_map,
        tutor_form=tutor_form,
        animal_forms=animal_forms,
        new_animal_form=new_animal_form
    )






@app.route('/update_animal/<int:animal_id>', methods=['POST'])
@login_required
def update_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    if current_user.worker != 'veterinario':
        message = 'Apenas veterinários podem editar dados do animal.'
        flash(message, 'danger')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        return redirect(request.referrer or url_for('index'))

    # Campos básicos
    animal.name = request.form.get('name')
    animal.sex = request.form.get('sex')
    animal.description = request.form.get('description') or ''
    animal.microchip_number = request.form.get('microchip_number')
    animal.health_plan = request.form.get('health_plan')
    animal.neutered = request.form.get('neutered') == '1'

    # Espécie (relacional)
    species_id = request.form.get('species_id')
    if species_id:
        try:
            animal.species_id = int(species_id)
        except ValueError:
            flash('ID de espécie inválido.', 'warning')

    # Raça (relacional)
    breed_id = request.form.get('breed_id')
    if breed_id:
        try:
            animal.breed_id = int(breed_id)
        except ValueError:
            flash('ID de raça inválido.', 'warning')

    # Peso
    peso_valor = request.form.get('peso')
    if peso_valor:
        try:
            animal.peso = float(peso_valor)
        except ValueError:
            flash('Peso inválido. Deve ser um número.', 'warning')
    else:
        animal.peso = None

    # Data de nascimento ou idade
    dob_str = request.form.get('date_of_birth')
    age_input = request.form.get('age')
    if dob_str:
        try:
            animal.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Data de nascimento inválida.', 'warning')
    elif age_input:
        try:
            age_years = int(age_input)
            animal.date_of_birth = date.today() - relativedelta(years=age_years)
        except ValueError:
            flash('Idade inválida. Deve ser um número inteiro.', 'warning')

    animal.age = None

    # Upload de imagem
    if 'image' in request.files and request.files['image'].filename != '':
        image_file = request.files['image']
        original_filename = secure_filename(image_file.filename)
        filename = f"{uuid.uuid4().hex}_{original_filename}"
        image_url = upload_to_s3(image_file, filename, folder="animals")
        animal.image = image_url

    try:
        animal.photo_rotation = int(request.form.get('photo_rotation', animal.photo_rotation or 0))
    except ValueError:
        pass
    try:
        animal.photo_zoom = float(request.form.get('photo_zoom', animal.photo_zoom or 1.0))
    except ValueError:
        pass
    try:
        animal.photo_offset_x = float(request.form.get('photo_offset_x', animal.photo_offset_x or 0))
    except ValueError:
        pass
    try:
        animal.photo_offset_y = float(request.form.get('photo_offset_y', animal.photo_offset_y or 0))
    except ValueError:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        message = f'Ocorreu um erro ao salvar: {str(e)}'
        flash(message, 'danger')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 500
        return redirect(request.referrer or url_for('index'))

    message = 'Dados do animal atualizados com sucesso!'
    flash(message, 'success')
    if wants_json:
        return jsonify(success=True, message=message, animal_name=animal.name, category='success')
    return redirect(request.referrer or url_for('index'))




@app.route('/update_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def update_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    if current_user.worker != 'veterinario':
        message = 'Apenas veterinários podem editar a consulta.'
        flash(message, 'danger')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        return redirect(url_for('index'))

    # Atualiza os campos
    consulta.queixa_principal = request.form.get('queixa_principal')
    consulta.historico_clinico = request.form.get('historico_clinico')
    consulta.exame_fisico = request.form.get('exame_fisico')
    consulta.conduta = request.form.get('conduta')

    # Se estiver editando uma consulta antiga
    if request.args.get('edit') == '1':
        db.session.commit()
        message = 'Consulta atualizada com sucesso!'
        flash(message, 'success')

    else:
        # Salva, finaliza e cria nova automaticamente
        consulta.status = 'finalizada'
        consulta.finalizada_em = datetime.utcnow()
        appointment = consulta.appointment
        if appointment and appointment.status != 'completed':
            appointment.status = 'completed'
        db.session.commit()

        nova = Consulta(
            animal_id=consulta.animal_id,
            created_by=current_user.id,
            clinica_id=consulta.clinica_id,
            status='in_progress'
        )
        db.session.add(nova)
        db.session.commit()

        message = 'Consulta salva e movida para o histórico!'
        flash(message, 'success')

    if wants_json:
        historico = (
            Consulta.query
            .filter_by(
                animal_id=consulta.animal_id,
                status='finalizada',
                clinica_id=consulta.clinica_id,
            )
            .order_by(Consulta.created_at.desc())
            .all()
        )
        html = render_template(
            'partials/historico_consultas.html',
            animal=consulta.animal,
            historico_consultas=historico,
        )
        appointments_html = None
        if consulta.appointment and consulta.clinica_id:
            clinic_appointments = (
                Appointment.query
                .filter_by(clinica_id=consulta.clinica_id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            appointments_grouped = group_appointments_by_day(clinic_appointments)
            appointments_html = render_template(
                'partials/appointments_table.html',
                appointments_grouped=appointments_grouped,
            )
        return jsonify(
            success=True,
            message=message,
            category='success',
            html=html,
            appointments_html=appointments_html,
        )

    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/animal/<int:animal_id>/racoes', methods=['POST'])
@login_required
def salvar_racao(animal_id):
    animal = get_animal_or_404(animal_id)

    # Verifica se o usuário pode editar esse animal
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    data = request.get_json(silent=True) or {}

    try:
        # ✅ SUPORTE AO FORMATO NOVO: tipo_racao_id direto
        if 'tipo_racao_id' in data:
            tipo_racao_id = data.get('tipo_racao_id')
            recomendacao_custom = data.get('recomendacao_custom')
            observacoes_racao = data.get('observacoes_racao')

            # Garante que tipo_racao existe
            tipo_racao = TipoRacao.query.get(tipo_racao_id)
            if not tipo_racao:
                return jsonify({'success': False, 'error': 'Tipo de ração não encontrado.'}), 404

            nova_racao = Racao(
                animal_id=animal.id,
                tipo_racao_id=tipo_racao.id,
                recomendacao_custom=recomendacao_custom,
                observacoes_racao=observacoes_racao,
                preco_pago=data.get('preco_pago'),  # ✅ CORRIGIDO
                tamanho_embalagem=data.get('tamanho_embalagem'),  # ✅ CORRIGIDO
                created_by=current_user.id
            )
            db.session.add(nova_racao)

        # ✅ SUPORTE AO FORMATO ANTIGO: lista de racoes com marca/linha
        elif 'racoes' in data:
            racoes_data = data.get('racoes', [])
            for r in racoes_data:
                marca = r.get('marca_racao', '').strip()
                linha_val = r.get('linha_racao')
                linha = linha_val.strip() if linha_val else None

                if not marca:
                    continue  # ignora se não houver marca

                tipo_racao = TipoRacao.query.filter_by(marca=marca, linha=linha).first()

                if not tipo_racao:
                    tipo_racao = TipoRacao(
                        marca=marca,
                        linha=linha,
                        created_by=current_user.id,
                    )
                    db.session.add(tipo_racao)
                    db.session.flush()  # garante que o ID estará disponível

                nova_racao = Racao(
                    animal_id=animal.id,
                    tipo_racao_id=tipo_racao.id,
                    recomendacao_custom=r.get('recomendacao_custom'),
                    observacoes_racao=r.get('observacoes_racao'),
                    created_by=current_user.id
                )
                db.session.add(nova_racao)

        else:
            return jsonify({'success': False, 'error': 'Formato de dados inválido.'}), 400

        db.session.commit()
        # Limpa o cache caso um novo tipo tenha sido criado acima
        try:
            list_rations.cache_clear()
        except Exception:
            pass

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao salvar ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao salvar ração.'}), 500


@app.route('/tipo_racao', methods=['POST'])
@login_required
def criar_tipo_racao():
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    data = request.get_json(silent=True) or {}
    marca = data.get('marca', '').strip()
    linha = data.get('linha', '').strip()
    recomendacao = data.get('recomendacao')
    peso_pacote_kg = data.get('peso_pacote_kg')  # Novo campo
    observacoes = data.get('observacoes', '').strip()

    if not marca:
        return jsonify({'success': False, 'error': 'Marca é obrigatória.'}), 400

    try:
        # Evita duplicidade
        existente = TipoRacao.query.filter_by(marca=marca, linha=linha).first()
        if existente:
            return jsonify({'success': False, 'error': 'Esta ração já existe.'}), 409

        nova_racao = TipoRacao(
            marca=marca,
            linha=linha if linha else None,
            recomendacao=recomendacao,
            peso_pacote_kg=peso_pacote_kg or 15.0,  # valor padrão se não enviado
            observacoes=observacoes if observacoes else None,
            created_by=current_user.id,
        )
        db.session.add(nova_racao)
        db.session.commit()
        # Limpa o cache para que novas rações apareçam imediatamente
        try:
            list_rations.cache_clear()
        except Exception:
            pass

        return jsonify({'success': True, 'id': nova_racao.id})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao cadastrar tipo de ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao cadastrar tipo de ração.'}), 500


@app.route('/tipo_racao/<int:tipo_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_tipo_racao(tipo_id):
    tipo = TipoRacao.query.get_or_404(tipo_id)
    if tipo.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        db.session.delete(tipo)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    marca_val = data.get('marca', tipo.marca)
    if marca_val is not None:
        marca_val = marca_val.strip()
    tipo.marca = marca_val
    linha_val = data.get('linha', tipo.linha)
    if linha_val is not None:
        linha_val = linha_val.strip()
    tipo.linha = linha_val or None
    tipo.recomendacao = data.get('recomendacao', tipo.recomendacao)
    tipo.peso_pacote_kg = data.get('peso_pacote_kg', tipo.peso_pacote_kg)
    tipo.observacoes = data.get('observacoes', tipo.observacoes)
    db.session.commit()
    return jsonify({'success': True})




@app.route('/tipos_racao')
def tipos_racao():
    termos = request.args.get('q', '')
    resultados = TipoRacao.query.filter(
        (TipoRacao.marca + ' - ' + (TipoRacao.linha or '')).ilike(f'%{termos}%')
    ).limit(15).all()

    return jsonify([
        f"{r.marca} - {r.linha}" if r.linha else r.marca
        for r in resultados
    ])


@app.route('/buscar_racoes')
def buscar_racoes():
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])

    resultados = (
        TipoRacao.query
        .filter(
            (TipoRacao.marca.ilike(f'%{q}%')) |
            (TipoRacao.linha.ilike(f'%{q}%'))
        )
        .order_by(TipoRacao.marca)
        .limit(15)
        .all()
    )

    return jsonify([
        {
            'id': r.id,
            'marca': r.marca,
            'linha': r.linha,
            'recomendacao': r.recomendacao,
            'peso_pacote_kg': r.peso_pacote_kg,
            'observacoes': r.observacoes,
        }
        for r in resultados
    ])


@app.route('/racao/<int:racao_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_racao(racao_id):
    racao = Racao.query.get_or_404(racao_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if racao.created_by and racao.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            db.session.delete(racao)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            print(f"Erro ao excluir ração: {e}")
            return jsonify({'success': False, 'error': 'Erro técnico ao excluir ração.'}), 500

    data = request.get_json(silent=True) or {}
    racao.recomendacao_custom = data.get('recomendacao_custom') or None
    racao.observacoes_racao = data.get('observacoes_racao') or ''
    racao.preco_pago = data.get('preco_pago') or None
    racao.tamanho_embalagem = data.get('tamanho_embalagem') or None

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Erro ao editar ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao editar ração.'}), 500






from sqlalchemy.orm import aliased
from sqlalchemy import desc

from collections import defaultdict

@app.route("/relatorio/racoes")
@login_required
def relatorio_racoes():
    subquery = (
        db.session.query(
            Racao.animal_id,
            func.max(Racao.data_cadastro).label("ultima_data")
        )
        .group_by(Racao.animal_id)
        .subquery()
    )

    RacaoAlias = aliased(Racao)

    racoes_recentes = (
        db.session.query(RacaoAlias)
        .join(subquery, (RacaoAlias.animal_id == subquery.c.animal_id) & 
                         (RacaoAlias.data_cadastro == subquery.c.ultima_data))
        .all()
    )

    # Agrupar por tipo_racao
    racoes_por_tipo = defaultdict(list)
    for r in racoes_recentes:
        racoes_por_tipo[r.tipo_racao].append(r)

    return render_template("loja/relatorio_racoes.html", racoes_por_tipo=racoes_por_tipo)


@app.route("/historico_animal/<int:animal_id>")
@login_required
def historico_animal(animal_id):
    animal = get_animal_or_404(animal_id)
    racoes = Racao.query.filter_by(animal_id=animal.id).order_by(Racao.data_cadastro.desc()).all()
    return render_template("historico_racoes.html", animal=animal, racoes=racoes)



@app.route('/relatorio/racoes/<int:tipo_id>')
@login_required
def detalhes_racao(tipo_id):
    tipo = TipoRacao.query.get_or_404(tipo_id)
    racoes = tipo.usos  # usa o backref 'usos'
    return render_template('loja/detalhes_racao.html', tipo=tipo, racoes=racoes)





@app.route('/buscar_vacinas')
def buscar_vacinas():
    termo = request.args.get('q', '').strip().lower()

    if not termo or len(termo) < 2:
        return jsonify([])

    try:
        resultados = VacinaModelo.query.filter(
            VacinaModelo.nome.ilike(f"%{termo}%")
        ).all()

        return jsonify([
            {
                'id': v.id,
                'nome': v.nome,
                'tipo': v.tipo or '',
                'fabricante': v.fabricante or '',
                'doses_totais': v.doses_totais,
                'intervalo_dias': v.intervalo_dias,
                'frequencia': v.frequencia or '',
            }
            for v in resultados
        ])
    except Exception as e:
        print(f"Erro ao buscar vacinas: {e}")
        return jsonify([])  # Não quebra o front se der erro

@app.route('/vacina_modelo', methods=['POST'])
@login_required
def criar_vacina_modelo():
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    tipo = (data.get('tipo') or '').strip()
    fabricante = (data.get('fabricante') or '').strip() or None
    doses_totais = data.get('doses_totais')
    intervalo_dias = data.get('intervalo_dias')
    frequencia = (data.get('frequencia') or '').strip() or None
    if not nome or not tipo:
        return jsonify({'success': False, 'message': 'Nome e tipo são obrigatórios.'}), 400
    try:
        existente = VacinaModelo.query.filter(func.lower(VacinaModelo.nome) == nome.lower()).first()
        if existente:
            return jsonify({'success': False, 'message': 'Vacina já cadastrada.'}), 400
        vacina = VacinaModelo(
            nome=nome,
            tipo=tipo,
            fabricante=fabricante,
            doses_totais=doses_totais,
            intervalo_dias=intervalo_dias,
            frequencia=frequencia,
            created_by=current_user.id,
        )
        db.session.add(vacina)
        db.session.commit()
        return jsonify({
            'success': True,
            'vacina': {
                'id': vacina.id,
                'nome': vacina.nome,
                'tipo': vacina.tipo,
                'fabricante': vacina.fabricante,
                'doses_totais': vacina.doses_totais,
                'intervalo_dias': vacina.intervalo_dias,
                'frequencia': vacina.frequencia,
            },
        })
    except Exception as e:
        db.session.rollback()
        print('Erro ao salvar vacina modelo:', e)
        return jsonify({'success': False, 'message': 'Erro ao salvar vacina.'}), 500


@app.route('/vacina_modelo/<int:vacina_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_vacina_modelo(vacina_id):
    vacina = VacinaModelo.query.get_or_404(vacina_id)
    if vacina.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'message': 'Permissão negada'}), 403

    if request.method == 'DELETE':
        db.session.delete(vacina)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    nome_val = data.get('nome', vacina.nome)
    if nome_val is not None:
        nome_val = nome_val.strip()
    vacina.nome = nome_val
    tipo_val = data.get('tipo', vacina.tipo)
    if tipo_val is not None:
        tipo_val = tipo_val.strip()
    vacina.tipo = tipo_val or None
    vacina.fabricante = (data.get('fabricante', vacina.fabricante) or '').strip() or None
    vacina.doses_totais = data.get('doses_totais', vacina.doses_totais)
    vacina.intervalo_dias = data.get('intervalo_dias', vacina.intervalo_dias)
    vacina.frequencia = (data.get('frequencia', vacina.frequencia) or '').strip() or None
    db.session.commit()
    return jsonify({'success': True})

from datetime import datetime

@app.route("/animal/<int:animal_id>/vacinas", methods=["POST"])
def salvar_vacinas(animal_id):
    data = request.get_json(silent=True) or {}

    if not data or "vacinas" not in data:
        return jsonify({"success": False, "error": "Dados incompletos"}), 400

    try:
        for v in data["vacinas"]:
            aplicada_em_str = v.get("aplicada_em")
            if aplicada_em_str:
                try:
                    aplicada_em = datetime.strptime(aplicada_em_str, "%Y-%m-%d").date()
                except ValueError:
                    aplicada_em = None
            else:
                aplicada_em = None

            vacina = Vacina(
                animal_id=animal_id,
                nome=v.get("nome"),
                tipo=v.get("tipo"),
                fabricante=v.get("fabricante"),
                doses_totais=v.get("doses_totais"),
                intervalo_dias=v.get("intervalo_dias"),
                frequencia=v.get("frequencia"),
                aplicada=v.get("aplicada", False),
                aplicada_em=aplicada_em,
                observacoes=v.get("observacoes"),
                created_by=current_user.id if current_user.is_authenticated else None,
            )
            db.session.add(vacina)

        db.session.commit()
        animal = get_animal_or_404(animal_id)
        historico_html = render_template(
            'partials/historico_vacinas.html',
            animal=animal
        )
        return jsonify({"success": True, "html": historico_html})

    except Exception as e:
        print("Erro ao salvar vacinas:", e)
        return jsonify({"success": False, "error": "Erro técnico ao salvar vacinas"}), 500




@app.route("/animal/<int:animal_id>/vacinas/imprimir")
def imprimir_vacinas(animal_id):
    animal = get_animal_or_404(animal_id)
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else None
    if not veterinario and current_user.is_authenticated and getattr(current_user, "worker", None) == "veterinario":
        veterinario = current_user
    clinica = consulta.clinica if consulta and consulta.clinica else None
    if not clinica and veterinario and getattr(veterinario, "veterinario", None):
        vet = veterinario.veterinario
        if vet.clinica:
            clinica = vet.clinica
    if not clinica:
        clinica = getattr(animal, "clinica", None)
    if not clinica:
        clinica_id = request.args.get("clinica_id", type=int)
        if clinica_id:
            clinica = Clinica.query.get_or_404(clinica_id)
    if not clinica:
        abort(400, description="É necessário informar uma clínica.")
    return render_template("orcamentos/imprimir_vacinas.html", animal=animal, clinica=clinica, veterinario=veterinario)


@app.route('/vacina/<int:vacina_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_vacina(vacina_id):
    vacina = Vacina.query.get_or_404(vacina_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if vacina.created_by and vacina.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            animal_id = vacina.animal_id
            db.session.delete(vacina)
            db.session.commit()
            return jsonify({'success': True, 'animal_id': animal_id})
        except Exception as e:
            db.session.rollback()
            print('Erro ao excluir vacina:', e)
            return jsonify({'success': False, 'error': 'Erro ao excluir vacina.'}), 500

    data = request.get_json(silent=True) or {}
    vacina.nome = data.get('nome', vacina.nome)
    vacina.tipo = data.get('tipo', vacina.tipo)
    vacina.fabricante = data.get('fabricante', vacina.fabricante)
    vacina.doses_totais = data.get('doses_totais', vacina.doses_totais)
    vacina.intervalo_dias = data.get('intervalo_dias', vacina.intervalo_dias)
    vacina.frequencia = data.get('frequencia', vacina.frequencia)
    vacina.observacoes = data.get('observacoes', vacina.observacoes)
    vacina.aplicada = data.get('aplicada', vacina.aplicada)

    aplicada_em_str = data.get('aplicada_em')
    if aplicada_em_str is not None:
        if aplicada_em_str:
            try:
                vacina.aplicada_em = datetime.strptime(aplicada_em_str, '%Y-%m-%d').date()
            except ValueError:
                vacina.aplicada_em = None
        else:
            vacina.aplicada_em = None

    nova_vacina = None
    if vacina.aplicada:
        base_date = vacina.aplicada_em or date.today()
        proxima_data = None
        if vacina.intervalo_dias:
            proxima_data = base_date + timedelta(days=vacina.intervalo_dias)
        elif vacina.frequencia:
            def _norm(txt):
                return ''.join(
                    c for c in unicodedata.normalize('NFD', txt.lower())
                    if unicodedata.category(c) != 'Mn'
                )

            freq_map = {
                'diario': 1,
                'diaria': 1,
                'semanal': 7,
                'quinzenal': 15,
                'mensal': 30,
                'bimestral': 60,
                'trimestral': 91,
                'quadrimestral': 120,
                'semestral': 182,
                'anual': 365,
                'bienal': 730,
            }
            dias = freq_map.get(_norm(vacina.frequencia))
            if dias:
                proxima_data = base_date + timedelta(days=dias)

        if proxima_data:
            nova_vacina = Vacina(
                animal_id=vacina.animal_id,
                nome=vacina.nome,
                tipo=vacina.tipo,
                fabricante=vacina.fabricante,
                doses_totais=vacina.doses_totais,
                intervalo_dias=vacina.intervalo_dias,
                frequencia=vacina.frequencia,
                observacoes=vacina.observacoes,
                aplicada=False,
                aplicada_em=proxima_data,
                created_by=vacina.created_by,
            )

    try:
        if nova_vacina:
            db.session.add(nova_vacina)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print('Erro ao editar vacina:', e)
        return jsonify({'success': False, 'error': 'Erro ao editar vacina.'}), 500



@app.route('/consulta/<int:consulta_id>/prescricao', methods=['POST'])
@login_required
def criar_prescricao(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem adicionar prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    medicamento = request.form.get('medicamento')
    dosagem = request.form.get('dosagem')
    frequencia = request.form.get('frequencia')
    duracao = request.form.get('duracao')
    observacoes = request.form.get('observacoes')

    # Se houver campos estruturados (dose, frequência ou duração),
    # ignoramos o campo de texto livre para evitar salvar ambos
    if dosagem or frequencia or duracao:
        observacoes = None
    # Caso contrário, se apenas o texto livre foi preenchido, os
    # campos estruturados não devem ser persistidos
    elif observacoes:
        dosagem = frequencia = duracao = None

    if not medicamento:
        flash('É necessário informar o nome do medicamento.', 'warning')
        return redirect(request.referrer)

    nova_prescricao = Prescricao(
        consulta_id=consulta.id,
        medicamento=medicamento,
        dosagem=dosagem,
        frequencia=frequencia,
        duracao=duracao,
        observacoes=observacoes
    )

    db.session.add(nova_prescricao)
    db.session.commit()

    flash('Prescrição adicionada com sucesso!', 'success')
    # criar_prescricao
    return redirect(url_for('consulta_qr', animal_id=Consulta.query.get(consulta_id).animal_id))


from flask import request, jsonify


@app.route('/prescricao/<int:prescricao_id>/deletar', methods=['POST'])
@login_required
def deletar_prescricao(prescricao_id):
    prescricao = Prescricao.query.get_or_404(prescricao_id)
    consulta_id = prescricao.consulta_id

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    db.session.delete(prescricao)
    db.session.commit()
    flash('Prescrição removida com sucesso!', 'info')
    return redirect(url_for('consulta_qr', animal_id=consulta.animal_id))


@app.route('/importar_medicamentos')
def importar_medicamentos():
    import pandas as pd


    try:
        df = pd.read_csv("medicamentos_pet_orlandia.csv")

        for _, row in df.iterrows():
            medicamento = Medicamento(
                classificacao=row["classificacao"],
                nome=row["nome"],
                principio_ativo=row["principio_ativo"],
                via_administracao=row["via_administracao"],
                dosagem_recomendada=row["dosagem_recomendada"],
                duracao_tratamento=row["duracao_tratamento"],
                observacoes=row["observacoes"],
                bula=row["link_bula"]
            )
            db.session.add(medicamento)

        db.session.commit()
        return "✅ Medicamentos importados com sucesso!"

    except Exception as e:
        return f"❌ Erro: {e}"


@app.route("/medicamento", methods=["POST"])
@login_required
def criar_medicamento():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()

    if not nome:
        return jsonify({"success": False, "message": "Nome é obrigatório"}), 400

    try:
        novo = Medicamento(
            nome=nome,
            principio_ativo=(data.get("principio_ativo") or "").strip() or None,
            classificacao=(data.get("classificacao") or "").strip() or None,
            via_administracao=(data.get("via_administracao") or "").strip() or None,
            dosagem_recomendada=(data.get("dosagem_recomendada") or "").strip() or None,
            frequencia=(data.get("frequencia") or "").strip() or None,
            duracao_tratamento=(data.get("duracao_tratamento") or "").strip() or None,
            observacoes=(data.get("observacoes") or "").strip() or None,
            bula=(data.get("bula") or "").strip() or None,
            created_by=current_user.id,
        )
        db.session.add(novo)
        db.session.commit()
        return jsonify({
            "success": True,
            "id": novo.id,
            "nome": novo.nome,
            "classificacao": novo.classificacao,
            "principio_ativo": novo.principio_ativo,
            "via_administracao": novo.via_administracao,
            "dosagem_recomendada": novo.dosagem_recomendada,
            "frequencia": novo.frequencia,
            "duracao_tratamento": novo.duracao_tratamento,
            "observacoes": novo.observacoes,
            "bula": novo.bula,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/medicamento/<int:med_id>", methods=["PUT", "DELETE"])
@login_required
def alterar_medicamento(med_id):
    medicamento = Medicamento.query.get_or_404(med_id)
    if medicamento.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({"success": False, "message": "Permissão negada"}), 403

    if request.method == "DELETE":
        db.session.delete(medicamento)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    campos = {
        "nome": "nome",
        "principio_ativo": "principio_ativo",
        "classificacao": "classificacao",
        "via_administracao": "via_administracao",
        "dosagem_recomendada": "dosagem_recomendada",
        "frequencia": "frequencia",
        "duracao_tratamento": "duracao_tratamento",
        "observacoes": "observacoes",
        "bula": "bula",
    }
    for key, attr in campos.items():
        if key in data:
            val = (data.get(key) or "").strip()
            setattr(medicamento, attr, val or None)

    db.session.commit()
    return jsonify({"success": True})


@app.route("/apresentacao_medicamento", methods=["POST"])
def criar_apresentacao_medicamento():
    data = request.get_json(silent=True) or {}
    medicamento_id = data.get("medicamento_id")
    forma = (data.get("forma") or "").strip()
    concentracao = (data.get("concentracao") or "").strip()

    if not medicamento_id or not forma or not concentracao:
        return jsonify({"success": False, "message": "Dados obrigatórios ausentes"}), 400

    try:
        apresentacao = ApresentacaoMedicamento(
            medicamento_id=int(medicamento_id),
            forma=forma,
            concentracao=concentracao,
        )
        db.session.add(apresentacao)
        db.session.commit()
        return jsonify({"success": True, "id": apresentacao.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/buscar_medicamentos")
def buscar_medicamentos():
    q = (request.args.get("q") or "").strip()

    # evita erro de None.lower()
    if len(q) < 2:
        return jsonify([])

    # busca por nome OU princípio ativo
    resultados = (
        Medicamento.query
        .filter(
            (Medicamento.nome.ilike(f"%{q}%")) |
            (Medicamento.principio_ativo.ilike(f"%{q}%"))
        )
        .order_by(Medicamento.nome)
        .limit(15)                     # devolve no máximo 15
        .all()
    )

    return jsonify([
        {
            "id": m.id,  # ✅ ESSENCIAL PARA O FUNCIONAMENTO
            "nome": m.nome,
            "classificacao": m.classificacao,
            "principio_ativo": m.principio_ativo,
            "via_administracao": m.via_administracao,
            "dosagem_recomendada": m.dosagem_recomendada,
            "frequencia": m.frequencia,
            "duracao_tratamento": m.duracao_tratamento,
            "observacoes": m.observacoes,
            "bula": m.bula,
        }
        for m in resultados
    ])



@app.route("/buscar_apresentacoes")
def buscar_apresentacoes():
    try:
        medicamento_id = request.args.get("medicamento_id")
        q = (request.args.get("q") or "").strip()

        if not medicamento_id or not medicamento_id.isdigit():
            return jsonify([])

        # Log for debugging
        print(f"Searching for presentations of medicamento_id={medicamento_id}, query='{q}'")

        apresentacoes = (
            ApresentacaoMedicamento.query
            .filter(
                ApresentacaoMedicamento.medicamento_id == int(medicamento_id),
                (ApresentacaoMedicamento.forma.ilike(f"%{q}%")) |
                (ApresentacaoMedicamento.concentracao.ilike(f"%{q}%"))
            )
            .all()
        )

        return jsonify([
            {"forma": a.forma, "concentracao": a.concentracao}
            for a in apresentacoes
        ])

    except Exception as e:
        print(f"[ERROR] /buscar_apresentacoes: {str(e)}")
        return jsonify({"error": str(e)}), 500



@app.route('/consulta/<int:consulta_id>/prescricao/lote', methods=['POST'])
@login_required
def salvar_prescricoes_lote(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    data = request.get_json(silent=True) or {}
    novas_prescricoes = data.get('prescricoes', [])

    for item in novas_prescricoes:
        nova = Prescricao(
            animal_id=consulta.animal_id,
            medicamento=item.get('nome'),
            dosagem=item.get('dosagem'),
            frequencia=item.get('frequencia'),
            duracao=item.get('duracao'),
            observacoes=item.get('observacoes')
        )
        db.session.add(nova)

    db.session.commit()

    historico_html = render_template('partials/historico_prescricoes.html', consulta=consulta)
    return jsonify({'status': 'ok', 'historico_html': historico_html})


@app.route('/consulta/<int:consulta_id>/bloco_prescricao', methods=['POST'])
@login_required
def salvar_bloco_prescricao(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem prescrever.'}), 403

    dados = request.get_json(silent=True) or {}
    lista_prescricoes = dados.get('prescricoes')
    instrucoes = dados.get('instrucoes_gerais')  # 🟢 AQUI você precisa pegar o campo

    if not lista_prescricoes:
        return jsonify({'success': False, 'message': 'Nenhuma prescrição recebida.'}), 400

    # ⬇️ Aqui é onde a instrução geral precisa ser usada
    bloco = BlocoPrescricao(animal_id=consulta.animal_id, instrucoes_gerais=instrucoes)
    db.session.add(bloco)
    db.session.flush()  # Garante o ID do bloco

    for item in lista_prescricoes:
        dosagem = item.get('dosagem')
        frequencia = item.get('frequencia')
        duracao = item.get('duracao')
        observacoes = item.get('observacoes')

        # Se qualquer campo estruturado estiver presente, descartamos o texto livre
        if dosagem or frequencia or duracao:
            observacoes = None
        # Caso contrário, usamos apenas o texto livre e ignoramos os outros
        elif observacoes:
            dosagem = frequencia = duracao = None

        nova = Prescricao(
            animal_id=consulta.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=dosagem,
            frequencia=frequencia,
            duracao=duracao,
            observacoes=observacoes
        )
        db.session.add(nova)

    db.session.commit()
    historico_html = render_template(
        'partials/historico_prescricoes.html',
        animal=consulta.animal
    )
    return jsonify({
        'success': True,
        'message': 'Prescrições salvas com sucesso!',
        'html': historico_html
    })


@app.route('/bloco_prescricao/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    if current_user.worker != 'veterinario':
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir prescrições.'), 403
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    db.session.delete(bloco)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = render_template('partials/historico_prescricoes.html',
                                         animal=animal)
        return jsonify(success=True, html=historico_html)

    flash('Bloco de prescrição excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/bloco_prescricao/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar prescrições.', 'danger')
        return redirect(url_for('index'))

    return render_template('orcamentos/editar_bloco.html', bloco=bloco)


@app.route('/bloco_prescricao/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403

    data = request.get_json(silent=True) or {}
    novos_medicamentos = data.get('medicamentos', [])
    instrucoes = data.get('instrucoes_gerais')

    # Limpa os medicamentos atuais do bloco
    for p in bloco.prescricoes:
        db.session.delete(p)

    # Adiciona os novos medicamentos ao bloco
    for item in novos_medicamentos:
        dosagem = item.get('dosagem')
        frequencia = item.get('frequencia')
        duracao = item.get('duracao')
        observacoes = item.get('observacoes')

        # Se qualquer campo estruturado estiver presente, descartamos o texto livre
        if dosagem or frequencia or duracao:
            observacoes = None
        # Caso contrário, usamos apenas o texto livre e ignoramos os outros
        elif observacoes:
            dosagem = frequencia = duracao = None

        nova = Prescricao(
            animal_id=bloco.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=dosagem,
            frequencia=frequencia,
            duracao=duracao,
            observacoes=observacoes
        )
        db.session.add(nova)

    bloco.instrucoes_gerais = instrucoes
    db.session.commit()
    return jsonify({'success': True})


@app.route('/bloco_prescricao/<int:bloco_id>/imprimir')
@login_required
def imprimir_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem imprimir prescrições.', 'danger')
        return redirect(url_for('index'))

    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else current_user
    clinica = consulta.clinica if consulta and consulta.clinica else (
        veterinario.veterinario.clinica if veterinario and getattr(veterinario, "veterinario", None) else None
    )

    return render_template(
        'orcamentos/imprimir_bloco.html',
        bloco=bloco,
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
    )


@app.route('/animal/<int:animal_id>/bloco_exames', methods=['POST'])
@login_required
def salvar_bloco_exames(animal_id):
    data = request.get_json(silent=True) or {}
    exames_data = data.get('exames', [])
    observacoes_gerais = data.get('observacoes_gerais', '')

    bloco = BlocoExames(animal_id=animal_id, observacoes_gerais=observacoes_gerais)
    db.session.add(bloco)
    db.session.flush()  # Garante que bloco.id esteja disponível

    for exame in exames_data:
        exame_modelo = ExameSolicitado(
            bloco_id=bloco.id,
            nome=exame.get('nome'),
            justificativa=exame.get('justificativa'),
            status=exame.get('status', 'pendente'),
            resultado=exame.get('resultado'),
            performed_at=datetime.fromisoformat(exame['performed_at']) if exame.get('performed_at') else None,
        )
        db.session.add(exame_modelo)

    db.session.commit()
    animal = get_animal_or_404(animal_id)
    historico_html = render_template(
        'partials/historico_exames.html',
        animal=animal
    )
    return jsonify({'success': True, 'html': historico_html})



@app.route('/buscar_exames')
@login_required
def buscar_exames():
    q = request.args.get('q', '').lower()
    exames = ExameModelo.query.filter(ExameModelo.nome.ilike(f'%{q}%')).all()
    return jsonify([
        {'id': e.id, 'nome': e.nome, 'justificativa': e.justificativa}
        for e in exames
    ])


@app.route('/exame_modelo', methods=['POST'])
@login_required
def criar_exame_modelo():
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    justificativa = (data.get('justificativa') or '').strip() or None
    if not nome:
        return jsonify({'error': 'Nome é obrigatório'}), 400
    exame = ExameModelo(nome=nome, justificativa=justificativa, created_by=current_user.id)
    db.session.add(exame)
    db.session.commit()
    return jsonify({'id': exame.id, 'nome': exame.nome, 'justificativa': exame.justificativa})


@app.route('/exame_modelo/<int:exame_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_exame_modelo(exame_id):
    exame = ExameModelo.query.get_or_404(exame_id)
    if exame.created_by != current_user.id:
        return jsonify({'success': False, 'message': 'Permissão negada'}), 403

    if request.method == 'DELETE':
        db.session.delete(exame)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or exame.nome).strip()
    justificativa = data.get('justificativa', exame.justificativa)
    exame.nome = nome
    exame.justificativa = justificativa
    db.session.commit()
    return jsonify({'success': True})


@app.route('/imprimir_bloco_exames/<int:bloco_id>')
@login_required
def imprimir_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else None
    if not veterinario and current_user.is_authenticated and getattr(current_user, 'worker', None) == 'veterinario':
        veterinario = current_user
    clinica = consulta.clinica if consulta and consulta.clinica else None
    if not clinica and veterinario and getattr(veterinario, 'veterinario', None):
        vet = veterinario.veterinario
        if vet.clinica:
            clinica = vet.clinica
    if not clinica:
        clinica = getattr(animal, 'clinica', None)
    if not clinica:
        clinica_id = request.args.get('clinica_id', type=int)
        if clinica_id:
            clinica = Clinica.query.get_or_404(clinica_id)
    if not clinica:
        abort(400, description="É necessário informar uma clínica.")

    return render_template('orcamentos/imprimir_exames.html', bloco=bloco, animal=animal, tutor=tutor, clinica=clinica, veterinario=veterinario)


@app.route('/bloco_exames/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    if current_user.worker != 'veterinario':
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir blocos de exames.'), 403
        flash('Apenas veterinários podem excluir blocos de exames.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    db.session.delete(bloco)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = render_template('partials/historico_exames.html',
                                         animal=animal)
        return jsonify(success=True, html=historico_html)

    flash('Bloco de exames excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))



@app.route('/bloco_exames/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar exames.'}), 403
    return render_template('orcamentos/editar_bloco_exames.html', bloco=bloco)





@app.route('/exame/<int:exame_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_exame(exame_id):
    exame = ExameSolicitado.query.get_or_404(exame_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            db.session.delete(exame)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            print('Erro ao excluir exame:', e)
            return jsonify({'success': False, 'error': 'Erro ao excluir exame.'}), 500

    data = request.get_json(silent=True) or {}
    exame.nome = data.get('nome', exame.nome)
    exame.justificativa = data.get('justificativa', exame.justificativa)
    exame.status = data.get('status', exame.status)
    exame.resultado = data.get('resultado', exame.resultado)
    performed_at = data.get('performed_at')
    if performed_at:
        try:
            exame.performed_at = datetime.fromisoformat(performed_at)
        except ValueError:
            pass

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print('Erro ao editar exame:', e)
        return jsonify({'success': False, 'error': 'Erro ao editar exame.'}), 500






@app.route('/bloco_exames/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    dados = request.get_json(silent=True) or {}

    bloco.observacoes_gerais = dados.get('observacoes_gerais', '')

    # ---------- mapeia exames já existentes ----------
    existentes = {e.id: e for e in bloco.exames}
    enviados_ids = set()

    for ex_json in dados.get('exames', []):
        ex_id = ex_json.get('id')
        nome  = ex_json.get('nome', '').strip()
        just  = ex_json.get('justificativa', '').strip()
        status = ex_json.get('status', 'pendente')
        resultado = ex_json.get('resultado')
        performed_at_str = ex_json.get('performed_at')
        performed_at = datetime.fromisoformat(performed_at_str) if performed_at_str else None

        if not nome:                 # pulamos entradas vazias
            continue

        if ex_id and ex_id in existentes:
            # --- atualizar exame já salvo ---
            exame = existentes[ex_id]
            exame.nome = nome
            exame.justificativa = just
            exame.status = status
            exame.resultado = resultado
            exame.performed_at = performed_at
            enviados_ids.add(ex_id)
        else:
            # --- criar exame novo ---
            novo = ExameSolicitado(
                bloco=bloco,
                nome=nome,
                justificativa=just,
                status=status,
                resultado=resultado,
                performed_at=performed_at,
            )
            db.session.add(novo)

    # ---------- remover os que ficaram de fora ----------
    for ex in bloco.exames:
        if ex.id not in enviados_ids and ex.id in existentes:
            db.session.delete(ex)

    db.session.commit()

    historico_html = render_template(
        'partials/historico_exames.html',
        animal=bloco.animal
    )
    return jsonify(success=True, html=historico_html)



@app.route('/novo_atendimento')
@login_required
def novo_atendimento():
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    tutor_form = EditProfileForm()
    return render_template('agendamentos/novo_atendimento.html', tutor_form=tutor_form)


@app.route('/criar_tutor_ajax', methods=['POST'])
@login_required
def criar_tutor_ajax():
    name = request.form.get('name')
    email = request.form.get('email')

    if not name or not email:
        return jsonify({'success': False, 'message': 'Nome e e-mail são obrigatórios.'})

    tutor_existente = User.query.filter_by(email=email).first()
    if tutor_existente:
        return jsonify({'success': False, 'message': 'Já existe um tutor com este e-mail.'})

    novo_tutor = User(
        name=name,
        phone=request.form.get('phone'),
        address=request.form.get('address'),
        cpf=request.form.get('cpf'),
        rg=request.form.get('rg'),
        email=email,
        role='adotante',
        clinica_id=current_user.clinica_id

    )

    date_str = request.form.get('date_of_birth')
    if date_str:
        try:
            novo_tutor.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Data de nascimento inválida.'})

    novo_tutor.set_password('123456789')  # Senha padrão

    db.session.add(novo_tutor)
    db.session.commit()

    return jsonify({'success': True, 'tutor_id': novo_tutor.id})


# app.py  – dentro da rota /novo_animal
@app.route('/novo_animal', methods=['GET', 'POST'])
@login_required
def novo_animal():
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem cadastrar animais.', 'danger')
        return redirect(url_for('index'))

    def fetch_animais(scope, page):
        clinic_id = current_user_clinic_id()
        if scope == 'mine':
            query = Animal.query.filter(Animal.removido_em == None)
            if clinic_id:
                query = query.filter(Animal.clinica_id == clinic_id)
            consultas_exist = (
                db.session.query(Consulta.id)
                .filter(
                    Consulta.animal_id == Animal.id,
                    Consulta.created_by == current_user.id,
                )
            )
            pagination = (
                query.filter(
                    or_(
                        Animal.added_by_id == current_user.id,
                        consultas_exist.exists(),
                    )
                )
                .order_by(Animal.date_added.desc())
                .paginate(page=page, per_page=9)
            )
        elif clinic_id:
            last_appt = (
                db.session.query(
                    Appointment.animal_id,
                    func.max(Appointment.scheduled_at).label('last_at')
                )
                .filter(Appointment.clinica_id == clinic_id)
                .group_by(Appointment.animal_id)
                .subquery()
            )

            pagination = (
                Animal.query
                .outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
                .filter(Animal.removido_em == None)
                .filter(
                    or_(
                        Animal.clinica_id == clinic_id,
                        last_appt.c.last_at != None
                    )
                )
                .order_by(func.coalesce(last_appt.c.last_at, Animal.date_added).desc())
                .paginate(page=page, per_page=9)
            )
        else:
            pagination = (
                Animal.query
                .filter_by(added_by_id=current_user.id)
                .filter(Animal.removido_em == None)
                .order_by(Animal.date_added.desc())
                .paginate(page=page, per_page=9)
            )
        return pagination.items, pagination

    if request.method == 'POST':
        tutor_id = request.form.get('tutor_id', type=int)
        tutor = User.query.get_or_404(tutor_id)

        dob_str = request.form.get('date_of_birth')
        dob = None
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Data de nascimento inválida. Use AAAA‑MM‑DD.', 'warning')
                return redirect(url_for('ficha_tutor', tutor_id=tutor.id))
        else:
            age_input = request.form.get('age')
            if age_input:
                try:
                    age_years = int(age_input)
                    dob = date.today() - relativedelta(years=age_years)
                except ValueError:
                    flash('Idade inválida. Deve ser um número inteiro.', 'warning')
                    return redirect(url_for('ficha_tutor', tutor_id=tutor.id))

        peso_str = request.form.get('peso')
        peso = float(peso_str) if peso_str else None

        neutered_val = request.form.get('neutered')
        neutered = True if neutered_val == '1' else False if neutered_val == '0' else None

        image_path = None
        if 'image' in request.files and request.files['image'].filename != '':
            image_file = request.files['image']
            filename = secure_filename(image_file.filename)
            image_path = upload_to_s3(image_file, filename)

        # IDs para espécie e raça
        species_id = request.form.get('species_id', type=int)
        breed_id = request.form.get('breed_id', type=int)

        # Carrega os objetos Species e Breed (opcional)
        species_obj = Species.query.get(species_id) if species_id else None
        breed_obj = Breed.query.get(breed_id) if breed_id else None

        # Criação do animal
        animal = Animal(
            name=request.form.get('name'),
            species_id=species_id,
            breed_id=breed_id,
            sex=request.form.get('sex'),
            date_of_birth=dob,
            microchip_number=request.form.get('microchip_number'),
            peso=peso,
            health_plan=request.form.get('health_plan'),
            neutered=neutered,
            user_id=tutor.id,
            added_by_id=current_user.id,
            clinica_id=current_user_clinic_id(),
            status='disponível',
            image=image_path,
            is_alive=True,
            modo='adotado',
        )
        db.session.add(animal)
        db.session.commit()

        # Criação da consulta
        consulta = Consulta(
            animal_id=animal.id,
            created_by=current_user.id,
            clinica_id=current_user_clinic_id(),
            status='in_progress'
        )
        db.session.add(consulta)
        db.session.commit()

        # Retorna conteúdo em JSON apenas quando o cliente realmente
        # priorizar "application/json" ou quando for uma requisição AJAX.
        prefers_json = (
            request.accept_mimetypes['application/json'] >
            request.accept_mimetypes['text/html']
        )
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if prefers_json or is_ajax:
            scope = request.args.get('scope', 'all')
            page = request.args.get('page', 1, type=int)
            animais_adicionados, pagination = fetch_animais(scope, page)
            html = render_template(
                'partials/animais_adicionados.html',
                animais_adicionados=animais_adicionados,
                pagination=pagination,
                scope=scope
            )
            return jsonify(
                message='Animal cadastrado com sucesso!',
                category='success',
                html=html
            )

        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('consulta_direct', animal_id=animal.id))

    # GET: lista de animais adicionados para exibição
    page = request.args.get('page', 1, type=int)
    scope = request.args.get('scope', 'all')
    animais_adicionados, pagination = fetch_animais(scope, page)

    # Lista de espécies e raças para os <select> do formulário
    species_list = list_species()
    breed_list = list_breeds()

    return render_template(
        'animais/novo_animal.html',
        animais_adicionados=animais_adicionados,
        pagination=pagination,
        species_list=species_list,
        breed_list=breed_list,
        scope=scope
    )





@app.route('/animal/<int:animal_id>/marcar_falecido', methods=['POST'])
@login_required
def marcar_como_falecido(animal_id):
    animal = get_animal_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem realizar essa ação.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    data = request.form.get('falecimento_em')

    try:
        animal.falecido_em = datetime.strptime(data, '%Y-%m-%dT%H:%M') if data else datetime.utcnow()
        animal.is_alive = False
        db.session.commit()
        flash(f'{animal.name} foi marcado como falecido.', 'success')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(
                message=f'{animal.name} foi marcado como falecido.',
                category='success',
                redirect=url_for('ficha_animal', animal_id=animal.id)
            )
    except Exception as e:
        flash(f'Erro ao marcar como falecido: {str(e)}', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=f'Erro ao marcar como falecido: {str(e)}', category='danger'), 400

    return redirect(url_for('ficha_animal', animal_id=animal.id))




@app.route('/animal/<int:animal_id>/reverter_falecimento', methods=['POST'])
@login_required
def reverter_falecimento(animal_id):
    if current_user.worker != 'veterinario':
        abort(403)

    animal = get_animal_or_404(animal_id)
    animal.is_alive = True
    animal.falecido_em = None
    db.session.commit()
    flash('Falecimento revertido com sucesso.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(
            message='Falecimento revertido com sucesso.',
            category='success',
            redirect=url_for('ficha_animal', animal_id=animal.id)
        )
    return redirect(url_for('ficha_animal', animal_id=animal.id))





@app.route('/animal/<int:animal_id>/arquivar', methods=['POST'])
@login_required
def arquivar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir animais definitivamente.', 'danger')
        return redirect(request.referrer or url_for('index'))

    try:
        db.session.delete(animal)
        db.session.commit()
        flash(f'Animal {animal.name} excluído permanentemente.', 'success')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(
                message=f'Animal {animal.name} excluído permanentemente.',
                category='success',
                redirect=url_for('ficha_tutor', tutor_id=animal.user_id)
            )
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {str(e)}', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=f'Erro ao excluir: {str(e)}', category='danger'), 400

    return redirect(url_for('ficha_tutor', tutor_id=animal.user_id))
























@app.route('/orders/new', methods=['GET', 'POST'])
@login_required
def create_order():
    if current_user.worker != 'delivery':
        abort(403)

    order_id = session.get('current_order')
    if order_id:
        order = Order.query.get_or_404(order_id)
    else:
        order = Order(user_id=current_user.id)
        db.session.add(order)
        db.session.commit()
        session['current_order'] = order.id

    form = OrderItemForm()
    delivery_form = DeliveryRequestForm()

    if form.validate_on_submit():
        item = OrderItem(order_id=order.id,
                         item_name=form.item_name.data,
                         quantity=form.quantity.data)
        db.session.add(item)
        db.session.commit()
        flash('Item adicionado ao pedido.', 'success')
        return redirect(url_for('create_order'))

    total_quantity = sum(i.quantity for i in order.items)
    return render_template(
        'loja/create_order.html',
        form=form,
        delivery_form=delivery_form,
        order=order,
        total_quantity=total_quantity,
    )


















#Delivery routes
 


@app.route('/orders/<int:order_id>/request_delivery', methods=['POST'])
@login_required
def request_delivery(order_id):
    if current_user.worker != 'delivery':      # só entregadores podem solicitar
        abort(403)

    order = Order.query.get_or_404(order_id)

    # ─── 1. escolher um ponto de retirada ────────────────────────────────
    # Hoje: pega o primeiro ponto ATIVO
    pickup = (
        PickupLocation.query
        .filter_by(ativo=True)
        .first()
    )

    if pickup is None:
        default_addr = current_app.config.get("DEFAULT_PICKUP_ADDRESS")
        if default_addr:
            flash(f'Usando endereço de retirada padrão: {default_addr}', 'info')
        else:
            flash('Nenhum ponto de retirada cadastrado/ativo.', 'danger')
            return redirect(url_for('list_delivery_requests'))

    # ─── 2. criar a DeliveryRequest já com o pickup_id ───────────────────
    req = DeliveryRequest(
        order_id        = order.id,
        requested_by_id = current_user.id,
        status          = 'pendente',
        pickup          = pickup         # 🔑 chave aqui!
    )

    db.session.add(req)
    db.session.commit()

    session.pop('current_order', None)
    flash('Solicitação de entrega gerada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Solicitação de entrega gerada.', category='success')
    return redirect(url_for('list_delivery_requests'))


from sqlalchemy.orm import selectinload

@app.route("/delivery_requests")
@login_required
def list_delivery_requests():
    """
    •  Entregador → até 3 pendentes (mais antigas primeiro) + as dele
    •  Cliente    → só pedidos que ele criou
    """
    base = (DeliveryRequest.query
            .filter_by(archived=False)
            .order_by(DeliveryRequest.requested_at.asc())   # FIFO
            .options(
                selectinload(DeliveryRequest.order)          # evita N+1
                .selectinload(Order.user)
            ))

    # -------------------------------------------------------- ENTREGADOR
    if current_user.worker == "delivery":
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

    return render_template(
        "entregas/delivery_requests.html",
        available=available,
        doing=doing,
        done=done,
        canceled=canceled,
        available_total=available_total   # novo badge
    )


@app.route("/api/delivery_counts")
@login_required
def api_delivery_counts():
    """Return delivery counts for the current user."""
    base = DeliveryRequest.query.filter_by(archived=False)
    if current_user.worker == "delivery":
        available_total = base.filter_by(status="pendente").count()
        doing = base.filter_by(worker_id=current_user.id,
                              status="em_andamento").count()
        done = base.filter_by(worker_id=current_user.id,
                             status="concluida").count()
        canceled = base.filter_by(worker_id=current_user.id,
                                 status="cancelada").count()
    else:
        base = base.filter_by(requested_by_id=current_user.id)
        available_total = 0
        doing = base.filter_by(status="em_andamento").count()
        done = base.filter_by(status="concluida").count()
        canceled = base.filter_by(status="cancelada").count()

    return jsonify(
        available_total=available_total,
        doing=doing,
        done=done,
        canceled=canceled,
    )



# --- Compatibilidade admin ---------------------------------
@app.route("/admin/delivery/<int:req_id>")
@login_required
def admin_delivery_detail(req_id):
    # se quiser, mantenha restrição de admin aqui
    if not _is_admin():
        abort(403)
    return redirect(url_for("delivery_detail", req_id=req_id))

# --- Compatibilidade entregador ----------------------------
@app.route("/worker/delivery/<int:req_id>")
@login_required
def worker_delivery_detail(req_id):
    # garante que o usuário é entregador e dono da entrega
    if current_user.worker != "delivery":
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id and req.worker_id != current_user.id:
        abort(403)
    return redirect(url_for("delivery_detail", req_id=req_id))





@app.route('/delivery_requests/<int:req_id>/accept', methods=['POST'])
@login_required
def accept_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.status != 'pendente':
        flash('Solicitação não disponível.', 'warning')
        return redirect(url_for('list_delivery_requests'))
    req.status = 'em_andamento'
    req.worker_id = current_user.id
    req.accepted_at = datetime.utcnow()
    db.session.commit()
    flash('Entrega aceita.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(
            message='Entrega aceita.',
            category='success',
            redirect=url_for('worker_delivery_detail', req_id=req.id)
        )
    # ⬇️ redireciona direto ao detalhe unificado
    return redirect(url_for('delivery_detail', req_id=req.id))




@app.route('/delivery_requests/<int:req_id>/complete', methods=['POST'])
@login_required
def complete_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id != current_user.id:
        abort(403)
    req.status = 'concluida'
    req.completed_at = datetime.utcnow()
    db.session.commit()
    flash('Entrega concluída.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega concluída.', category='success')
    return redirect(url_for('list_delivery_requests'))


@app.route('/delivery_requests/<int:req_id>/cancel', methods=['POST'])
@login_required
def cancel_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id != current_user.id:
        abort(403)
    req.status = 'cancelada'
    req.canceled_at = datetime.utcnow()
    req.canceled_by_id = current_user.id
    db.session.commit()
    flash('Entrega cancelada.', 'info')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega cancelada.', category='info')
    return redirect(url_for('list_delivery_requests'))


@app.route('/delivery_requests/<int:req_id>/buyer_cancel', methods=['POST'])
@login_required
def buyer_cancel_delivery(req_id):
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.requested_by_id != current_user.id:
        abort(403)
    if req.status in ['concluida', 'cancelada']:
        flash('Não é possível cancelar.', 'warning')
        return redirect(url_for('loja'))
    req.status = 'cancelada'
    req.canceled_at = datetime.utcnow()
    req.canceled_by_id = current_user.id
    db.session.commit()
    flash('Solicitação cancelada.', 'info')
    return redirect(url_for('loja'))


# routes_delivery.py  (ou app.py)
from sqlalchemy.orm import joinedload


@app.route("/delivery/<int:req_id>")
@login_required
def delivery_detail(req_id):
    """Detalhe da entrega para admin, entregador ou comprador."""
    req = (
        DeliveryRequest.query
        .options(
            joinedload(DeliveryRequest.pickup).joinedload(PickupLocation.endereco),
            joinedload(DeliveryRequest.order).joinedload(Order.user),
            joinedload(DeliveryRequest.worker),
        )
        .get_or_404(req_id)
    )

    order = req.order
    buyer = order.user
    items = order.items
    total = sum(i.quantity * i.product.price for i in items if i.product)

    if _is_admin():
        role = "admin"
    elif current_user.worker == "delivery":
        if req.worker_id and req.worker_id != current_user.id:
            abort(403)
        role = "worker"
    elif current_user.id == buyer.id:
        role = "buyer"
    else:
        abort(403)

    return render_template(
        "entregas/delivery_detail.html",
        req=req,
        order=order,
        items=items,
        buyer=buyer,
        delivery_worker=req.worker,
        total=total,
        role=role,
    )


# routes_delivery.py  (ou app.py)

@app.route("/admin/delivery_overview")
@login_required
def delivery_overview():
    if not _is_admin():
        abort(403)

    # eager‑loading: DeliveryRequest ➜ Order ➜ User + Items + Product
    base_q = (
        DeliveryRequest.query.filter_by(archived=False)
        .options(
            joinedload(DeliveryRequest.order)
                .joinedload(Order.user),                       # comprador
            joinedload(DeliveryRequest.order)
                .joinedload(Order.items)
                .joinedload(OrderItem.product)                 # itens + produtos
        )
        .order_by(DeliveryRequest.id.desc())
    )

    per_page = 10
    open_page = request.args.get('open_page', 1, type=int)
    progress_page = request.args.get('progress_page', 1, type=int)
    completed_page = request.args.get('completed_page', 1, type=int)
    canceled_page = request.args.get('canceled_page', 1, type=int)

    open_pagination = (
        base_q.filter_by(status="pendente")
              .paginate(page=open_page, per_page=per_page, error_out=False)
    )
    progress_pagination = (
        base_q.filter_by(status="em_andamento")
              .paginate(page=progress_page, per_page=per_page, error_out=False)
    )
    completed_pagination = (
        base_q.filter_by(status="concluida")
              .paginate(page=completed_page, per_page=per_page, error_out=False)
    )
    canceled_pagination = (
        base_q.filter_by(status="cancelada")
              .paginate(page=canceled_page, per_page=per_page, error_out=False)
    )

    open_requests = open_pagination.items
    in_progress   = progress_pagination.items
    completed     = completed_pagination.items
    canceled      = canceled_pagination.items

    # produtos para o bloco de estoque
    products = Product.query.order_by(Product.name).all()

    return render_template(
        "admin/delivery_overview.html",
        products      = products,
        open_requests = open_requests,
        in_progress   = in_progress,
        completed     = completed,
        canceled      = canceled,
        open_pagination = open_pagination,
        progress_pagination = progress_pagination,
        completed_pagination = completed_pagination,
        canceled_pagination = canceled_pagination,
        open_page = open_page,
        progress_page = progress_page,
        completed_page = completed_page,
        canceled_page = canceled_page,
    )


@app.route('/admin/delivery_requests/<int:req_id>/status/<status>', methods=['POST'])
@login_required
def admin_set_delivery_status(req_id, status):
    if not _is_admin():
        abort(403)

    allowed = ['pendente', 'em_andamento', 'concluida', 'cancelada']
    if status not in allowed:
        abort(400)

    req = DeliveryRequest.query.get_or_404(req_id)
    now = datetime.utcnow()
    req.status = status

    if status == 'pendente':
        req.worker_id = None
        req.accepted_at = None
        req.canceled_at = None
        req.canceled_by_id = None
        req.completed_at = None
    elif status == 'em_andamento':
        if not req.accepted_at:
            req.accepted_at = now

        req.canceled_at = None
        req.canceled_by_id = None
        req.completed_at = None
    elif status == 'concluida':
        if not req.completed_at:
            req.completed_at = now
        if not req.accepted_at:
            req.accepted_at = now
        req.canceled_at = None
        req.canceled_by_id = None

    elif status == 'cancelada':
        req.canceled_at = now
        req.canceled_by_id = current_user.id
        req.completed_at = None

    db.session.commit()
    flash('Status atualizado.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Status atualizado.', category='success', status=status)
    return redirect(url_for('delivery_overview'))


@app.route('/admin/delivery_requests/<int:req_id>/delete', methods=['POST'])
@login_required
def admin_delete_delivery(req_id):
    if not _is_admin():
        abort(403)

    req = DeliveryRequest.query.get_or_404(req_id)
    db.session.delete(req)
    db.session.commit()
    flash('Entrega excluída.', 'info')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega excluída.', category='info', deleted=True)
    return redirect(url_for('delivery_overview'))


@app.route('/admin/delivery_requests/<int:req_id>/archive', methods=['POST'])
@login_required
def admin_archive_delivery(req_id):
    if not _is_admin():
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    req.archived = True
    db.session.commit()
    flash('Entrega arquivada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega arquivada.', category='success', archived=True)
    return redirect(url_for('delivery_overview'))


@app.route('/admin/delivery_requests/<int:req_id>/unarchive', methods=['POST'])
@login_required
def admin_unarchive_delivery(req_id):
    if not _is_admin():
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    req.archived = False
    db.session.commit()
    flash('Entrega desarquivada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega desarquivada.', category='success', archived=False)
    return redirect(url_for('delivery_archive'))


@app.route('/admin/delivery_archive')
@login_required
def delivery_archive():
    if not _is_admin():
        abort(403)

    reqs = (
        DeliveryRequest.query.filter_by(archived=True)
        .options(
            joinedload(DeliveryRequest.order)
                .joinedload(Order.user),
            joinedload(DeliveryRequest.order)
                .joinedload(Order.items)
                .joinedload(OrderItem.product)
        )
        .order_by(DeliveryRequest.id.desc())
        .all()
    )

    return render_template('admin/delivery_archive_admin.html', requests=reqs)


@app.route('/delivery_archive')
@login_required
def delivery_archive_user():
    base = (
        DeliveryRequest.query.filter_by(archived=True)
        .options(
            joinedload(DeliveryRequest.order).joinedload(Order.user)
        )
        .order_by(DeliveryRequest.id.desc())
    )
    if current_user.worker == "delivery":
        reqs = base.filter_by(worker_id=current_user.id).all()
    else:
        reqs = base.filter_by(requested_by_id=current_user.id).all()
    return render_template('entregas/delivery_archive.html', requests=reqs)



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
def mp_sdk():
    return mercadopago.SDK(current_app.config["MERCADOPAGO_ACCESS_TOKEN"])


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
    """Return a lightweight list of breeds as dictionaries."""
    return [
        {"id": br.id, "name": br.name, "species_id": br.species_id}
        for br in Breed.query.order_by(Breed.name).all()
    ]


@cache
def list_rations():
    return TipoRacao.query.order_by(TipoRacao.marca.asc()).all()


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

    expirou   = (datetime.utcnow() - payment.created_at) > PENDING_TIMEOUT
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

# Helper to fetch the current order from session and verify ownership
def _get_current_order():
    order_id = session.get("current_order")
    if not order_id:
        return None
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        session.pop("current_order", None)
        abort(403)
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


def _build_loja_query(search_term: str, filtro: str):
    query = Product.query
    if search_term:
        like = f"%{search_term}%"
        query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

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


@app.route("/loja")
@login_required
def loja():
    pagamento_pendente = None
    payment_id = session.get("last_pending_payment")
    if payment_id:
        payment = Payment.query.get(payment_id)
        if payment and payment.status.name == "PENDING":
            pagamento_pendente = payment

    search_term = request.args.get("q", "").strip()
    filtro = request.args.get("filter", "all")
    page = request.args.get("page", 1, type=int)
    per_page = 12

    query = _build_loja_query(search_term, filtro)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    produtos = pagination.items
    form = AddToCartForm()

    # Verifica se há pedidos anteriores
    has_orders = Order.query.filter_by(user_id=current_user.id).first() is not None

    return render_template(
        "loja/loja.html",
        products=produtos,
        pagination=pagination,
        pagamento_pendente=pagamento_pendente,
        form=form,
        has_orders=has_orders,
        selected_filter=filtro,
        search_term=search_term,
    )


@app.route("/loja/data")
@login_required
def loja_data():
    search_term = request.args.get("q", "").strip()
    filtro = request.args.get("filter", "all")
    page = request.args.get("page", 1, type=int)
    per_page = 12

    query = _build_loja_query(search_term, filtro)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    produtos = pagination.items
    form = AddToCartForm()

    if request.args.get("format") == "json":
        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "image_url": p.image_url,
            }
            for p in produtos
        ]
        return jsonify(
            products=products_data,
            page=pagination.page,
            total_pages=pagination.pages,
            has_next=pagination.has_next,
            has_prev=pagination.has_prev,
        )

    html = render_template(
        "partials/_product_grid.html",
        products=produtos,
        pagination=pagination,
        form=form,
        selected_filter=filtro,
        search_term=search_term,
    )
    return html


@app.route('/produto/<int:product_id>', methods=['GET', 'POST'])
@login_required
def produto_detail(product_id):
    """Exibe detalhes do produto e permite edições para administradores."""
    product = Product.query.options(db.joinedload(Product.extra_photos)).get_or_404(product_id)

    update_form = ProductUpdateForm(obj=product, prefix='upd')
    photo_form = ProductPhotoForm(prefix='photo')
    form = AddToCartForm()

    if _is_admin():
        if update_form.validate_on_submit() and update_form.submit.data:
            product.name = update_form.name.data
            product.description = update_form.description.data
            product.price = float(update_form.price.data or 0)
            product.stock = update_form.stock.data
            product.mp_category_id = (update_form.mp_category_id.data or "others").strip()
            if update_form.image_upload.data:
                file = update_form.image_upload.data
                filename = secure_filename(file.filename)
                image_url = upload_to_s3(file, filename, folder='products')
                if image_url:
                    product.image_url = image_url
            db.session.commit()
            flash('Produto atualizado.', 'success')
            return redirect(url_for('produto_detail', product_id=product.id))

        if photo_form.validate_on_submit() and photo_form.submit.data:
            file = photo_form.image.data
            filename = secure_filename(file.filename)
            image_url = upload_to_s3(file, filename, folder='products')
            if image_url:
                db.session.add(ProductPhoto(product_id=product.id, image_url=image_url))
                db.session.commit()
                flash('Foto adicionada.', 'success')
            return redirect(url_for('produto_detail', product_id=product.id))

    return render_template(
        'loja/product_detail.html',
        product=product,
        update_form=update_form,
        photo_form=photo_form,
        form=form,
        is_admin=_is_admin(),
    )




# --------------------------------------------------------
#  ADICIONAR AO CARRINHO
# --------------------------------------------------------
@app.route("/carrinho/adicionar/<int:product_id>", methods=["POST"])
@login_required
def adicionar_carrinho(product_id):
    product = Product.query.get_or_404(product_id)
    form = AddToCartForm()
    if not form.validate_on_submit():
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(success=False, error='invalid form'), 400
        return redirect(url_for("loja"))

    order = _get_current_order()
    if not order:
        order = Order(user_id=current_user.id)
        db.session.add(order)
        db.session.commit()
        session["current_order"] = order.id

    qty = form.quantity.data or 1

    # Verifica se o produto já está no carrinho para somar as quantidades
    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    if item:
        item.quantity += qty
    else:
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            item_name=product.name,
            unit_price=Decimal(str(product.price or 0)),
            quantity=qty,
        )
        db.session.add(item)

    db.session.commit()
    flash("Produto adicionado ao carrinho.", "success")
    if 'application/json' in request.headers.get('Accept', ''):
        total_value = order.total_value()
        total_qty = sum(i.quantity for i in order.items)
        return jsonify(
            message="Produto adicionado ao carrinho.",
            category="success",
            item_id=item.id,
            item_quantity=item.quantity,
            order_total=total_value,
            order_total_formatted=f"R$ {total_value:.2f}",
            order_quantity=total_qty,
        )
    return redirect(url_for("loja"))


# --------------------------------------------------------
#  ATUALIZAR QUANTIDADE DO ITEM DO CARRINHO
# --------------------------------------------------------
@app.route("/carrinho/increase/<int:item_id>", methods=["POST"])
@login_required
def aumentar_item_carrinho(item_id):
    """Incrementa a quantidade de um item no carrinho."""
    order = _get_current_order()
    item = OrderItem.query.get_or_404(item_id)
    if item.order_id != order.id:
        abort(404)
    item.quantity += 1
    db.session.commit()
    flash("Quantidade atualizada", "success")
    if 'application/json' in request.headers.get('Accept', ''):
        total_value = order.total_value()
        total_qty = sum(i.quantity for i in order.items)
        return jsonify(
            message="Quantidade atualizada",
            category="success",
            item_id=item.id,
            item_quantity=item.quantity,
            order_total=total_value,
            order_total_formatted=f"R$ {total_value:.2f}",
            order_quantity=total_qty,
        )
    return redirect(url_for("ver_carrinho"))


@app.route("/carrinho/decrease/<int:item_id>", methods=["POST"])
@login_required
def diminuir_item_carrinho(item_id):
    """Diminui a quantidade de um item; remove se chegar a zero."""
    order = _get_current_order()
    item = OrderItem.query.get_or_404(item_id)
    if item.order_id != order.id:
        abort(404)
    item.quantity -= 1
    if item.quantity <= 0:
        db.session.delete(item)
        db.session.commit()
        message = "Produto removido"
        category = "info"
        item_qty = 0
    else:
        db.session.commit()
        message = "Quantidade atualizada"
        category = "success"
        item_qty = item.quantity
    flash(message, category)
    if 'application/json' in request.headers.get('Accept', ''):
        total_value = order.total_value()
        total_qty = sum(i.quantity for i in order.items)
        payload = {
            "message": message,
            "category": category,
            "item_id": item.id,
            "item_quantity": item_qty,
            "order_total": total_value,
            "order_total_formatted": f"R$ {total_value:.2f}",
            "order_quantity": total_qty,
        }
        if total_qty == 0:
            payload["redirect"] = url_for("ver_carrinho")
        return jsonify(**payload)
    return redirect(url_for("ver_carrinho"))


# --------------------------------------------------------
#  VER CARRINHO
# --------------------------------------------------------
from forms import CheckoutForm, EditAddressForm

@app.route("/carrinho", methods=["GET", "POST"])
@login_required
def ver_carrinho():
    # 1) Cria o form
    form = CheckoutForm()
    addr_form = CartAddressForm()
    default_address = _setup_checkout_form(form)

    # 2) Verifica se há um pagamento pendente
    pagamento_pendente = None
    payment_id = session.get('last_pending_payment')
    if payment_id:
        pagamento = Payment.query.get(payment_id)
        if pagamento and pagamento.status == PaymentStatus.PENDING:
            pagamento_pendente = pagamento

    # 3) Busca o pedido atual
    order = _get_current_order()

    # 4) Renderiza o carrinho passando o form
    return render_template(
        'loja/carrinho.html',
        form=form,
        order=order,
        pagamento_pendente=pagamento_pendente,
        default_address=default_address,
        saved_addresses=current_user.saved_addresses,
        addr_form=addr_form
    )


@app.route('/carrinho/salvar_endereco', methods=['POST'])
@login_required
def carrinho_salvar_endereco():
    """Salva um novo endereço informado no carrinho."""
    form = CartAddressForm()
    if not form.validate_on_submit():
        flash('Preencha os campos obrigatórios do endereço.', 'warning')
        return redirect(url_for('ver_carrinho'))

    tmp_addr = Endereco(
        cep=form.cep.data,
        rua=form.rua.data,
        numero=form.numero.data,
        complemento=form.complemento.data,
        bairro=form.bairro.data,
        cidade=form.cidade.data,
        estado=form.estado.data,
    )
    address_text = tmp_addr.full
    sa = SavedAddress(user_id=current_user.id, address=address_text)
    db.session.add(sa)
    db.session.commit()
    session['last_address_id'] = sa.id
    flash('Endereço salvo com sucesso.', 'success')

    return redirect(url_for('ver_carrinho'))


@app.route("/checkout/confirm", methods=["POST"])
@login_required
def checkout_confirm():
    """Mostra um resumo antes de redirecionar ao pagamento externo."""
    form = CheckoutForm()
    _setup_checkout_form(form, preserve_selected=True)
    if not form.validate_on_submit():
        return redirect(url_for("ver_carrinho"))

    order = _get_current_order()
    if not order or not order.items:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("ver_carrinho"))

    # Determine the address text based on the chosen option
    selected_address = None
    if form.address_id.data is not None and form.address_id.data >= 0:
        if form.address_id.data == 0 and current_user.endereco and current_user.endereco.full:
            selected_address = current_user.endereco.full
        else:
            sa = SavedAddress.query.filter_by(
                id=form.address_id.data,
                user_id=current_user.id
            ).first()
            if sa:
                selected_address = sa.address

    if not selected_address and form.shipping_address.data:
        selected_address = form.shipping_address.data

    if not selected_address and current_user.endereco and current_user.endereco.full:
        selected_address = current_user.endereco.full

    return render_template(
        "loja/checkout_confirm.html",
        form=form,
        order=order,
        selected_address=selected_address,
    )

















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

@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    current_app.logger.setLevel(logging.DEBUG)

    form = CheckoutForm()
    _setup_checkout_form(form, preserve_selected=True)
    if not form.validate_on_submit():
        return redirect(url_for("ver_carrinho"))

    # 1️⃣ pedido atual do carrinho
    order = _get_current_order()
    if not order or not order.items:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("ver_carrinho"))

    address_text = None
    if form.address_id.data is not None and form.address_id.data >= 0:
        if form.address_id.data == 0 and current_user.endereco and current_user.endereco.full:
            address_text = current_user.endereco.full
        else:
            sa = SavedAddress.query.filter_by(id=form.address_id.data, user_id=current_user.id).first()
            if sa:
                address_text = sa.address
        session["last_address_id"] = form.address_id.data
    elif form.address_id.data == -1:
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')
        if any([cep, rua, cidade, estado]):
            tmp_addr = Endereco(
                cep=cep,
                rua=rua,
                numero=numero,
                complemento=complemento,
                bairro=bairro,
                cidade=cidade,
                estado=estado
            )
            address_text = tmp_addr.full
            sa = SavedAddress(user_id=current_user.id, address=address_text)
            db.session.add(sa)
            db.session.flush()
            session["last_address_id"] = sa.id
    if not address_text and form.shipping_address.data:
        address_text = form.shipping_address.data
        sa = SavedAddress(user_id=current_user.id, address=address_text)
        db.session.add(sa)
        db.session.flush()
        session["last_address_id"] = sa.id
    if not address_text and current_user.endereco and current_user.endereco.full:
        address_text = current_user.endereco.full
        session["last_address_id"] = 0 if address_text else None

    order.shipping_address = address_text
    db.session.add(order)
    db.session.commit()

    # 2️⃣ grava Payment PENDING
    payment = Payment(
        user_id=current_user.id,
        order_id=order.id,
        method=PaymentMethod.PIX,          # ou outro enum que prefira
        status=PaymentStatus.PENDING,
    )
    payment.amount = Decimal(str(order.total_value()))
    db.session.add(payment)
    db.session.flush()                     # gera payment.id sem fechar a transação
    payment.external_reference = str(payment.id)
    db.session.commit()

    # 3️⃣ itens do Preference
    # O Mercado Pago recomenda enviar um código no campo
    # ``items.id`` para agilizar a verificação antifraude.

    items = [
        {
            "id":          str(it.product.id),
            "title":       it.product.name,
            "description": it.product.description or it.product.name,
            "category_id": it.product.mp_category_id or "others",
            "quantity":    int(it.quantity),
            "unit_price":  float(it.product.price),
        }
        for it in order.items
    ]


    # 4️⃣ payload Preference

    # Separa o nome em partes para extrair primeiro e último nome
    name = (current_user.name or "").strip()
    parts = name.split()
    if parts:
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else first_name
    else:
        # Quando o usuário não tem um nome salvo, usa o prefixo do e‑mail
        first_name = current_user.email.split("@")[0]
        last_name = first_name
    payer_info = {
        "first_name": first_name,
        "last_name": last_name,

        "email": current_user.email,
    }
    if current_user.phone:
        digits = re.sub(r"\D", "", current_user.phone)
        if digits.startswith("55") and len(digits) > 11:
            digits = digits[2:]
        if len(digits) >= 10:
            payer_info["phone"] = {
                "area_code": digits[:2],
                "number": digits[2:],
            }
        else:
            payer_info["phone"] = {"number": digits}
    if current_user.cpf:
        payer_info["identification"] = {
            "type": "CPF",
            "number": re.sub(r"\D", "", current_user.cpf),
        }
    if order.shipping_address:
        payer_info["address"] = {"street_name": order.shipping_address}
        m = re.search(r"CEP\s*(\d{5}-?\d{3})", order.shipping_address)
        if m:
            payer_info["address"]["zip_code"] = m.group(1)

    preference_data = {
        "items": items,
        "external_reference": payment.external_reference,
        "notification_url":   url_for("notificacoes_mercado_pago", _external=True),
        "payment_methods":    {"installments": 1},
        "statement_descriptor": current_app.config.get("MERCADOPAGO_STATEMENT_DESCRIPTOR"),
        "binary_mode": current_app.config.get("MERCADOPAGO_BINARY_MODE", False),
        "back_urls": {
            s: url_for("payment_status", payment_id=payment.id, _external=True)
            for s in ("success", "failure", "pending")
        },
        "auto_return": "approved",
        "payer": payer_info,
    }
    current_app.logger.debug("MP Preference Payload:\n%s",
                             json.dumps(preference_data, indent=2, ensure_ascii=False))

    # 5️⃣ cria Preference no Mercado Pago
    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception:
        current_app.logger.exception("Erro de conexão com Mercado Pago")
        flash("Falha ao conectar com Mercado Pago.", "danger")
        return redirect(url_for("ver_carrinho"))

    if resp.get("status") != 201:
        current_app.logger.error("MP error (HTTP %s): %s", resp["status"], resp)
        flash("Erro ao iniciar pagamento.", "danger")
        return redirect(url_for("ver_carrinho"))

    pref = resp["response"]
    payment.transaction_id = str(pref["id"])       # preference_id
    payment.init_point     = pref["init_point"]
    db.session.commit()

    session["last_pending_payment"] = payment.id
    return redirect(pref["init_point"])






import re
import hmac
import hashlib
from flask import current_app, request, jsonify
from sqlalchemy.exc import SQLAlchemyError

# Regular expression for parsing X-Signature header
_SIG_RE = re.compile(r"(?i)(?:ts=(\d+),\s*)?v1=([a-f0-9]{64})")

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

@app.route("/notificacoes", methods=["POST", "GET"])
def notificacoes_mercado_pago():
    if request.method == "GET":
        return jsonify(status="pong"), 200

    secret = current_app.config.get("MERCADOPAGO_WEBHOOK_SECRET", "")
    if not verify_mp_signature(request, secret):
        return jsonify(error="invalid signature"), 400

    # Check notification type
    notification_type = request.args.get("type") or request.args.get("topic")
    if notification_type != "payment":
        current_app.logger.info("Ignoring non-payment notification: %s", notification_type)
        return jsonify(status="ignored"), 200

    # Extract mp_id
    data = request.get_json(silent=True) or {}
    mp_id = (data.get("data", {}).get("id") or  # v1
             data.get("resource", "").split("/")[-1])  # v2

    if not mp_id:
        return jsonify(status="ignored"), 200

    # Query payment
    resp = mp_sdk().payment().get(mp_id)
    if resp.get("status") == 404:
        with db.session.begin():
            p = PendingWebhook.query.filter_by(mp_id=mp_id).first()
            if not p:
                db.session.add(PendingWebhook(mp_id=mp_id))
        return jsonify(status="retry_later"), 202
    if resp.get("status") != 200:
        return jsonify(error="api error"), 500

    # Process payment info
    info = resp["response"]
    status = info["status"]
    extref = info.get("external_reference")
    if not extref:
        return jsonify(status="ignored"), 200

    # Update database
    status_map = {
        "approved": PaymentStatus.COMPLETED,
        "authorized": PaymentStatus.COMPLETED,
        "pending": PaymentStatus.PENDING,
        "in_process": PaymentStatus.PENDING,
        "in_mediation": PaymentStatus.PENDING,
        "rejected": PaymentStatus.FAILED,
        "cancelled": PaymentStatus.FAILED,
        "refunded": PaymentStatus.FAILED,
        "expired": PaymentStatus.FAILED,
    }

    try:
        with db.session.begin():
            pay = Payment.query.filter_by(external_reference=extref).first()
            if not pay:
                current_app.logger.warning("Payment %s not found for external_reference %s", mp_id, extref)
                return jsonify(error="payment not found"), 404

            pay.status = status_map.get(status, PaymentStatus.PENDING)
            pay.mercado_pago_id = mp_id

            if pay.status == PaymentStatus.COMPLETED and pay.order_id:
                if not DeliveryRequest.query.filter_by(order_id=pay.order_id).first():
                    db.session.add(DeliveryRequest(
                        order_id=pay.order_id,
                        requested_by_id=pay.user_id,
                        status="pendente",
                    ))

    except SQLAlchemyError as e:
        current_app.logger.exception("DB error: %s", e)
        return jsonify(error="db failure"), 500

    return jsonify(status="updated"), 200






















































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
        db.session.commit()


@app.route("/pagamento/<status>")
def legacy_pagamento(status):
    extref = request.args.get("external_reference")
    payment = None

    if extref and extref.isdigit():
        payment = Payment.query.get(int(extref))

    if not payment:
        mp_id = (request.args.get("collection_id") or
                 request.args.get("payment_id"))
        if mp_id:
            payment = Payment.query.filter(
                (Payment.mercado_pago_id == mp_id) |
                (Payment.transaction_id == mp_id)
            ).first()

    if not payment:
        pref_id = request.args.get("preference_id")
        if pref_id:
            payment = Payment.query.filter_by(transaction_id=pref_id).first()

    mp_status = (request.args.get("status") or
                 request.args.get("collection_status") or
                 status)

    if not payment:
        if mp_status in {"success", "completed", "approved", "sucesso"}:
            return render_template("auth/sucesso.html")
        abort(404)

    return redirect(url_for("payment_status", payment_id=payment.id, status=mp_status))


@app.route("/order/<int:order_id>/edit_address", methods=["GET", "POST"])
@login_required
def edit_order_address(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        abort(403)

    form = EditAddressForm(obj=order)
    if form.validate_on_submit():
        order.shipping_address = form.shipping_address.data
        db.session.commit()
        flash("Endereço atualizado.", "success")
        if order.payment:
            return redirect(url_for("payment_status", payment_id=order.payment.id))
        return redirect(url_for("loja"))

    payment_id = order.payment.id if order.payment else None
    return render_template("loja/edit_address.html", form=form, payment_id=payment_id)


@app.route("/payment_status/<int:payment_id>")
def payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if current_user.is_authenticated and payment.user_id != current_user.id:
        abort(403)

    result  = request.args.get("status") or payment.status.name.lower()

    form = CheckoutForm()

    delivery_req = (DeliveryRequest.query
                    .filter_by(order_id=payment.order_id)
                    .first())

    # endpoint a usar
    endpoint = "delivery_detail"  # agora é um só

    # Limpa o pedido da sessão quando o pagamento foi concluído
    if result in {"success", "completed", "approved"}:
        session.pop("current_order", None)

    order = payment.order if (
        current_user.is_authenticated and payment.user_id == current_user.id
    ) else None

    delivery_estimate = None
    if order and order.created_at:
        delivery_estimate = order.created_at + timedelta(days=5)

    cancel_url = (
        url_for('buyer_cancel_delivery', req_id=delivery_req.id)
        if delivery_req and delivery_req.status not in ['cancelada', 'concluida']
        else None
    )
    edit_address_url = url_for('edit_order_address', order_id=payment.order_id) if order else None

    return render_template(
        "loja/payment_status.html",
        payment          = payment,
        result           = result,
        req_id           = delivery_req.id if delivery_req else None,
        req_endpoint     = endpoint,
        order            = order,
        form             = form,
        delivery_estimate= delivery_estimate,
        cancel_url       = cancel_url,
        edit_address_url = edit_address_url,
    )


@app.route("/api/payment_status/<int:payment_id>")
def api_payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if current_user.is_authenticated and payment.user_id != current_user.id:
        abort(403)
    return jsonify(status=payment.status.name)



#fim pagamento


from sqlalchemy.orm import joinedload


@app.route("/minhas-compras")
@login_required
def minhas_compras():
    page = request.args.get("page", 1, type=int)
    per_page = 20

    pagination = (Order.query
                  .join(Order.payment)
                  .options(joinedload(Order.payment))
                  .filter(Order.user_id == current_user.id,
                          Payment.status == PaymentStatus.COMPLETED)
                  .order_by(Order.created_at.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))

    return render_template(
        "loja/minhas_compras.html",
        orders=pagination.items,
        pagination=pagination,
        PaymentStatus=PaymentStatus,
    )



@app.route("/api/minhas-compras")
@login_required
def api_minhas_compras():
    orders = (Order.query
              .options(joinedload(Order.payment))
              .filter_by(user_id=current_user.id)
              .order_by(Order.created_at.desc())
              .all())
    data = [
        {
            "id": o.id,
            "data": o.created_at.isoformat(),
            "valor": float((getattr(o.payment, "amount", None) if o.payment else None) or o.total_value()),
            "status": (o.payment.status.value if o.payment else "Pendente"),
        }
        for o in orders
    ]
    return jsonify(data)


@app.route("/pedido/<int:order_id>")
@login_required
def pedido_detail(order_id):
    order = (Order.query
             .options(
                 joinedload(Order.items).joinedload(OrderItem.product),
                 joinedload(Order.user),
                 joinedload(Order.payment),
                 joinedload(Order.delivery_requests).joinedload(DeliveryRequest.pickup).joinedload(PickupLocation.endereco),
                 joinedload(Order.delivery_requests).joinedload(DeliveryRequest.worker)
             )
             .get_or_404(order_id))

    if not _is_admin() and order.user_id != current_user.id:
        abort(403)

    req = order.delivery_requests[0] if order.delivery_requests else None
    items = order.items
    buyer = order.user
    delivery_worker = req.worker if req else None
    total = sum(i.quantity * i.product.price for i in items if i.product)

    if _is_admin():
        role = "admin"
    elif current_user.worker == "delivery":
        if req and req.worker_id and req.worker_id != current_user.id:
            abort(403)
        role = "worker"
    elif current_user.id == buyer.id:
        role = "buyer"
    else:
        abort(403)

    form = CheckoutForm()
    edit_address_url = url_for("edit_order_address", order_id=order.id)
    cancel_url = (
        url_for("buyer_cancel_delivery", req_id=req.id)
        if req and req.status not in ['cancelada', 'concluida']
        else None
    )

    return render_template(
        "entregas/delivery_detail.html",
        req=req,
        order=order,
        items=items,
        buyer=buyer,
        delivery_worker=delivery_worker,
        total=total,
        role=role,
        form=form,
        edit_address_url=edit_address_url,
        cancel_url=cancel_url,
    )

























@app.route('/appointments/<int:appointment_id>/confirmation')
@login_required
def appointment_confirmation(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.tutor_id != current_user.id:
        abort(403)
    return render_template('agendamentos/appointment_confirmation.html', appointment=appointment)


@app.route('/appointments', methods=['GET', 'POST'])
@login_required
def appointments():
    from models import ExamAppointment, Veterinario, Clinica, User

    view_as = request.args.get('view_as')
    worker = current_user.worker

    def _redirect_to_current_appointments():
        query_args = request.args.to_dict(flat=False)
        if query_args:
            return redirect(url_for('appointments', **query_args))
        return redirect(url_for('appointments'))
    if view_as:
        allowed_views = {'veterinario', 'colaborador', 'tutor'}
        if current_user.role == 'admin' and view_as in allowed_views:
            worker = view_as
        elif current_user.role != 'admin':
            # Non-admin users can only request the view matching their own role.
            user_view = worker if worker in allowed_views else 'tutor'
            if view_as not in allowed_views or view_as != user_view:
                flash('Você não tem permissão para acessar essa visão de agenda.', 'warning')
                return redirect(url_for('appointments'))

    agenda_users = []
    agenda_veterinarios = []
    agenda_colaboradores = []
    admin_selected_veterinario_id = None
    admin_selected_colaborador_id = None
    admin_default_selection_value = ''
    selected_colaborador = None
    calendar_summary_vets = []
    calendar_summary_clinic_ids = []
    calendar_redirect_url = None

    if current_user.role == 'admin':
        agenda_users = User.query.order_by(User.name).all()
        agenda_veterinarios = (
            Veterinario.query.join(User).order_by(User.name).all()
        )
        agenda_colaboradores = (
            User.query.filter(User.worker == 'colaborador')
            .order_by(User.name)
            .all()
        )
        default_vet = getattr(current_user, 'veterinario', None)
        if default_vet and getattr(default_vet, 'id', None):
            admin_default_selection_value = f'veterinario:{default_vet.id}'

    admin_selected_view = (
        worker
        if current_user.role == 'admin' and worker in {'veterinario', 'colaborador'}
        else None
    )

    if request.method == 'POST' and worker not in ['veterinario', 'colaborador', 'admin']:
        abort(403)
    if worker == 'veterinario':
        if current_user.role == 'admin':
            veterinario_id_arg = request.args.get(
                'veterinario_id', type=int
            )
            if veterinario_id_arg:
                veterinario = next(
                    (v for v in agenda_veterinarios if v.id == veterinario_id_arg),
                    None,
                )
                if not veterinario:
                    veterinario = Veterinario.query.get_or_404(
                        veterinario_id_arg
                    )
            elif agenda_veterinarios:
                veterinario = agenda_veterinarios[0]
            else:
                abort(404)
            admin_selected_veterinario_id = veterinario.id
        else:
            veterinario = current_user.veterinario
        if not veterinario:
            abort(404)
        vet_user_id = getattr(veterinario, "user_id", None)
        clinic_ids = []
        if getattr(veterinario, "clinica_id", None):
            clinic_ids.append(veterinario.clinica_id)
        for clinica in getattr(veterinario, "clinicas", []) or []:
            clinica_id = getattr(clinica, "id", None)
            if clinica_id and clinica_id not in clinic_ids:
                clinic_ids.append(clinica_id)
        calendar_summary_clinic_ids = clinic_ids
        if getattr(veterinario, "id", None) is not None:
            calendar_summary_vets = [
                {
                    'id': veterinario.id,
                    'name': veterinario.user.name
                    if getattr(veterinario, "user", None)
                    else None,
                    'full_name': getattr(getattr(veterinario, 'user', None), 'name', None),
                    'specialty_list': getattr(veterinario, 'specialty_list', None),
                    'is_specialist': bool(getattr(veterinario, 'specialty_list', None)),
                }
            ]
        include_colleagues = bool(clinic_ids)
        if include_colleagues:
            if current_user.role == 'admin' and agenda_veterinarios:
                colleagues_source = [
                    v
                    for v in agenda_veterinarios
                    if getattr(v, 'clinica_id', None) in clinic_ids
                ]
            else:
                colleagues_source = (
                    Veterinario.query.filter(
                        Veterinario.clinica_id.in_(clinic_ids)
                    ).all()
                    if clinic_ids
                    else []
                )
            known_ids = {entry['id'] for entry in calendar_summary_vets}
            for colleague in colleagues_source:
                colleague_id = getattr(colleague, 'id', None)
                if not colleague_id or colleague_id in known_ids:
                    continue
                calendar_summary_vets.append(
                    {
                        'id': colleague_id,
                        'name': colleague.user.name
                        if getattr(colleague, 'user', None)
                        else None,
                        'full_name': getattr(getattr(colleague, 'user', None), 'name', None),
                        'specialty_list': getattr(colleague, 'specialty_list', None),
                        'is_specialist': bool(getattr(colleague, 'specialty_list', None)),
                    }
                )
                known_ids.add(colleague_id)
        calendar_redirect_url = url_for(
            'appointments', view_as='veterinario', veterinario_id=veterinario.id
        )
        query_args = request.args.to_dict()
        if current_user.role == 'admin':
            query_args['view_as'] = 'veterinario'
            query_args['veterinario_id'] = veterinario.id
        appointments_url = url_for('appointments', **query_args)
        schedule_form = VetScheduleForm(prefix='schedule')
        appointment_form = AppointmentForm(is_veterinario=True, prefix='appointment')
        if _is_admin():
            vets_for_choices = agenda_veterinarios or Veterinario.query.all()
        else:
            vets_for_choices = [veterinario]
        schedule_form.veterinario_id.choices = [
            (v.id, v.user.name) for v in vets_for_choices
        ]
        clinic_vets = []
        if clinic_ids:
            clinic_vets = (
                Veterinario.query.filter(
                    Veterinario.clinica_id.in_(clinic_ids)
                ).all()
            )
        associated_clinics = (
            Clinica.query.filter(Clinica.id.in_(clinic_ids)).all()
            if clinic_ids
            else []
        )
        specialists = []
        for clinica in associated_clinics:
            specialists.extend(
                vet
                for vet in (getattr(clinica, 'veterinarios_associados', []) or [])
                if getattr(vet, 'id', None) is not None
            )
        combined_vets = unique_items_by_id(clinic_vets + specialists + [veterinario])

        def _vet_sort_key(vet):
            name = getattr(getattr(vet, 'user', None), 'name', '') or ''
            return name.lower()

        combined_vets = sorted(
            (
                vet
                for vet in combined_vets
                if getattr(vet, 'id', None) is not None
            ),
            key=_vet_sort_key,
        )

        clinic_vet_ids = {
            getattr(vet, 'id', None) for vet in clinic_vets if getattr(vet, 'id', None)
        }
        specialist_ids = {
            getattr(vet, 'id', None)
            for vet in specialists
            if getattr(vet, 'id', None)
        }

        def _vet_label(vet):
            base_name = getattr(getattr(vet, 'user', None), 'name', None)
            label = base_name or f"Profissional #{getattr(vet, 'id', '—')}"
            vet_id = getattr(vet, 'id', None)
            if vet_id in specialist_ids and vet_id not in clinic_vet_ids:
                return f"{label} (Especialista)"
            return label

        appointment_form.veterinario_id.choices = [
            (vet.id, _vet_label(vet)) for vet in combined_vets
        ]
        calendar_summary_vets = [
            {
                'id': vet.id,
                'name': _vet_label(vet),
                'label': _vet_label(vet),
                'full_name': getattr(getattr(vet, 'user', None), 'name', None),
                'specialty_list': getattr(vet, 'specialty_list', None),
                'is_specialist': getattr(vet, 'id', None) in specialist_ids
                and getattr(vet, 'id', None) not in clinic_vet_ids,
            }
            for vet in combined_vets
        ]
        if request.method == 'GET':
            schedule_form.veterinario_id.data = veterinario.id
            appointment_form.veterinario_id.data = veterinario.id
        if schedule_form.submit.data and not _is_admin():
            raw_vet_id = request.form.get(schedule_form.veterinario_id.name)
            if raw_vet_id is None:
                abort(403)
            try:
                submitted_vet_id = int(raw_vet_id)
            except (TypeError, ValueError):
                abort(403)
            if submitted_vet_id != veterinario.id:
                abort(403)

        if schedule_form.submit.data and schedule_form.validate_on_submit():
            if not _is_admin() and schedule_form.veterinario_id.data != veterinario.id:
                abort(403)

            vet_id = schedule_form.veterinario_id.data
            for dia in schedule_form.dias_semana.data:
                if has_schedule_conflict(
                    vet_id,
                    dia,
                    schedule_form.hora_inicio.data,
                    schedule_form.hora_fim.data,
                ):
                    flash(f'Conflito de horário em {dia}.', 'danger')
                    return redirect(appointments_url)
            added = False
            for dia in schedule_form.dias_semana.data:
                if has_schedule_conflict(
                    schedule_form.veterinario_id.data,
                    dia,
                    schedule_form.hora_inicio.data,
                    schedule_form.hora_fim.data,
                ):
                    flash(f'Horário em {dia} conflita com um existente.', 'danger')
                    continue
                horario = VetSchedule(
                    veterinario_id=vet_id,
                    dia_semana=dia,
                    hora_inicio=schedule_form.hora_inicio.data,
                    hora_fim=schedule_form.hora_fim.data,
                    intervalo_inicio=schedule_form.intervalo_inicio.data,
                    intervalo_fim=schedule_form.intervalo_fim.data,
                )
                db.session.add(horario)
                added = True
            if added:
                db.session.commit()
                flash('Horário salvo com sucesso.', 'success')
            else:
                flash('Nenhum novo horário foi salvo.', 'info')
            return redirect(appointments_url)
        if appointment_form.validate_on_submit():
            scheduled_at_local = datetime.combine(
                appointment_form.date.data, appointment_form.time.data
            )
            if not is_slot_available(
                appointment_form.veterinario_id.data,
                scheduled_at_local,
                kind=appointment_form.kind.data,
            ):
                flash(
                    'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                    'danger'
                )
            else:
                animal = get_animal_or_404(appointment_form.animal_id.data)
                tutor_id = animal.user_id
                requires_plan = current_app.config.get(
                    'REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT', False
                )
                if requires_plan and not Appointment.has_active_subscription(
                    animal.id, tutor_id
                ):
                    flash(
                        'O animal não possui uma assinatura de plano de saúde ativa.',
                        'danger',
                    )
                else:
                    scheduled_at = (
                        scheduled_at_local
                        .replace(tzinfo=BR_TZ)
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                    current_vet = getattr(current_user, 'veterinario', None)
                    selected_vet_id = appointment_form.veterinario_id.data
                    same_user = current_vet and current_vet.id == selected_vet_id
                    selected_vet = next(
                        (
                            vet
                            for vet in combined_vets
                            if getattr(vet, 'id', None) == selected_vet_id
                        ),
                        None,
                    )
                    if not selected_vet and selected_vet_id:
                        selected_vet = Veterinario.query.get(selected_vet_id)
                    selected_clinic_id = (
                        getattr(selected_vet, 'clinica_id', None)
                        if selected_vet
                        else None
                    )
                    appt = Appointment(
                        animal_id=animal.id,
                        tutor_id=tutor_id,
                        veterinario_id=selected_vet_id,
                        scheduled_at=scheduled_at,
                        clinica_id=selected_clinic_id or animal.clinica_id,
                        notes=appointment_form.reason.data,
                        kind=appointment_form.kind.data,
                        status='accepted' if same_user else 'scheduled',
                        created_by=current_user.id,
                        created_at=datetime.utcnow(),
                    )
                    db.session.add(appt)
                    db.session.commit()
                    flash('Agendamento criado com sucesso.', 'success')
            return redirect(appointments_url)
        horarios = VetSchedule.query.filter_by(
            veterinario_id=veterinario.id
        ).all()
        weekday_order = {
            'Segunda': 0,
            'Terça': 1,
            'Quarta': 2,
            'Quinta': 3,
            'Sexta': 4,
            'Sábado': 5,
            'Domingo': 6,
        }
        horarios.sort(key=lambda h: weekday_order.get(h.dia_semana, 7))
        horarios_grouped = []
        for h in horarios:
            if not horarios_grouped or horarios_grouped[-1]['dia'] != h.dia_semana:
                horarios_grouped.append({'dia': h.dia_semana, 'itens': []})
            horarios_grouped[-1]['itens'].append(h)
        now = datetime.utcnow()
        today_start_local = datetime.now(BR_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_start_utc = (
            today_start_local.astimezone(timezone.utc).replace(tzinfo=None)
        )
        start_str = request.args.get('start')
        end_str = request.args.get('end')
        if start_str and end_str:
            start_dt = datetime.fromisoformat(start_str)
            end_dt = datetime.fromisoformat(end_str) + timedelta(days=1)
            restrict_to_today = False
        else:
            today = date.today()
            start_dt = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
            end_dt = start_dt + timedelta(days=7)
            restrict_to_today = True
        start_dt_utc, end_dt_utc = local_date_range_to_utc(start_dt, end_dt)
        upcoming_start = start_dt_utc or today_start_utc
        if restrict_to_today and today_start_utc:
            upcoming_start = max(upcoming_start, today_start_utc)

        appointment_scope_conditions = [
            Appointment.veterinario_id == veterinario.id
        ]
        if vet_user_id:
            appointment_scope_conditions.append(Appointment.created_by == vet_user_id)
        if len(appointment_scope_conditions) == 1:
            appointment_scope_filter = appointment_scope_conditions[0]
        else:
            appointment_scope_filter = or_(*appointment_scope_conditions)

        pending_consultas = (
            Appointment.query.filter(Appointment.status == 'scheduled')
            .filter(Appointment.scheduled_at > now)
            .filter(appointment_scope_filter)
            .order_by(Appointment.scheduled_at)
            .all()
        )
        appointments_pending_consults = []
        pending_consults_for_me = []
        pending_consults_waiting_others = []
        for appt in pending_consultas:
            appt.time_left = (appt.scheduled_at - timedelta(hours=2)) - now
            kind = appt.kind or ('retorno' if appt.consulta_id else 'consulta')
            if kind == 'general':
                kind = 'consulta'
            item = {'kind': kind, 'appt': appt}
            appointments_pending_consults.append(item)
            if appt.veterinario_id == veterinario.id:
                pending_consults_for_me.append(item)
            else:
                pending_consults_waiting_others.append(item)

        from models import ExamAppointment, Message, BlocoExames

        exam_pending = (
            ExamAppointment.query.filter_by(specialist_id=veterinario.id, status='pending')
            .filter(ExamAppointment.scheduled_at > now)
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        exams_pending_to_accept = []
        for ex in exam_pending:
            ex.time_left = ex.confirm_by - now
            if ex.time_left.total_seconds() <= 0:
                ex.status = 'canceled'
                msg = Message(
                    sender_id=vet_user_id or getattr(current_user, "id", None),
                    receiver_id=ex.requester_id,
                    animal_id=ex.animal_id,
                    content=f"Especialista não aceitou exame para {ex.animal.name}. Reagende com outro profissional.",
                )
                db.session.add(msg)
                db.session.commit()
            else:
                exams_pending_to_accept.append(ex)

        if vet_user_id:
            pending_requested_exams = (
                ExamAppointment.query.filter(
                    ExamAppointment.requester_id == vet_user_id,
                    ExamAppointment.status.in_(['pending', 'confirmed']),
                    ExamAppointment.specialist_id != veterinario.id,
                    ExamAppointment.scheduled_at > now,
                )
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
        else:
            pending_requested_exams = []
        exams_waiting_other_vets = []
        status_styles = {
            'pending': {
                'badge_class': 'bg-warning text-dark',
                'icon_class': 'text-warning',
                'status_label': 'Aguardando confirmação',
                'show_time_left': True,
            },
            'confirmed': {
                'badge_class': 'bg-success',
                'icon_class': 'text-success',
                'status_label': 'Confirmado',
                'show_time_left': False,
            },
        }
        default_style = {
            'badge_class': 'bg-secondary',
            'icon_class': 'text-secondary',
            'status_label': 'Status desconhecido',
            'show_time_left': False,
        }
        for ex in pending_requested_exams:
            if ex.confirm_by:
                ex.time_left = ex.confirm_by - now
            else:
                ex.time_left = timedelta(0)
            style = status_styles.get(ex.status, default_style)
            include_exam = ex.status == 'confirmed'
            if ex.status == 'pending':
                include_exam = ex.time_left.total_seconds() > 0
            if not include_exam:
                continue
            exams_waiting_other_vets.append(
                {
                    'exam': ex,
                    'status': ex.status,
                    'status_label': style['status_label'],
                    'badge_class': style['badge_class'],
                    'icon_class': style['icon_class'],
                    'show_time_left': style['show_time_left'] and ex.time_left.total_seconds() > 0,
                }
            )

        accepted_consultas_in_range = (
            Appointment.query.filter(Appointment.status == 'accepted')
            .filter(Appointment.scheduled_at >= start_dt_utc)
            .filter(Appointment.scheduled_at < end_dt_utc)
            .filter(appointment_scope_filter)
            .order_by(Appointment.scheduled_at)
            .all()
        )
        future_cutoff = max(now, upcoming_start) if upcoming_start else now
        past_accepted_consultas = []
        upcoming_consultas = []
        for appt in accepted_consultas_in_range:
            scheduled_at = appt.scheduled_at
            if scheduled_at and scheduled_at >= future_cutoff:
                upcoming_consultas.append(appt)
            else:
                past_accepted_consultas.append(appt)

        upcoming_exams = (
            ExamAppointment.query.filter_by(specialist_id=veterinario.id, status='confirmed')
            .filter(ExamAppointment.scheduled_at >= future_cutoff)
            .filter(ExamAppointment.scheduled_at < end_dt_utc)
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        appointments_upcoming = []
        for appt in upcoming_consultas:
            kind = appt.kind or ('retorno' if appt.consulta_id else 'consulta')
            if kind == 'general':
                kind = 'consulta'
            appointments_upcoming.append({'kind': kind, 'appt': appt})
        for exam in upcoming_exams:
            appointments_upcoming.append({'kind': 'exame', 'appt': exam})
        appointments_upcoming.sort(key=lambda x: x['appt'].scheduled_at)

        appointments_upcoming_for_me = []
        appointments_upcoming_requested = []
        for item in appointments_upcoming:
            if item['kind'] == 'exame':
                appointments_upcoming_for_me.append(item)
                continue
            appt = item['appt']
            if getattr(appt, 'veterinario_id', None) == veterinario.id:
                appointments_upcoming_for_me.append(item)
            elif vet_user_id and getattr(appt, 'created_by', None) == vet_user_id:
                appointments_upcoming_requested.append(item)

        consulta_filters = [Consulta.status == 'finalizada']
        scope_filters = []
        if vet_user_id:
            scope_filters.append(Consulta.created_by == vet_user_id)
        if veterinario.clinica_id:
            scope_filters.append(Consulta.clinica_id == veterinario.clinica_id)
        if scope_filters:
            consulta_filters.append(or_(*scope_filters))

        consultas_query = (
            Consulta.query.outerjoin(Appointment, Consulta.appointment)
            .options(
                joinedload(Consulta.animal).joinedload(Animal.owner),
                joinedload(Consulta.veterinario),
                joinedload(Consulta.appointment)
                .joinedload(Appointment.animal)
                .joinedload(Animal.owner),
            )
            .filter(*consulta_filters)
        )

        consulta_timestamp_expr = case(
            (Consulta.finalizada_em.isnot(None), Consulta.finalizada_em),
            (Appointment.scheduled_at.isnot(None), Appointment.scheduled_at),
            else_=Consulta.created_at,
        )
        if start_dt_utc is not None:
            consultas_query = consultas_query.filter(consulta_timestamp_expr >= start_dt_utc)
        if end_dt_utc is not None:
            consultas_query = consultas_query.filter(consulta_timestamp_expr < end_dt_utc)

        consultas_finalizadas = consultas_query.all()

        consulta_animal_ids = {c.animal_id for c in consultas_finalizadas}
        exam_blocks_by_consulta = defaultdict(list)
        exam_blocks_by_animal = defaultdict(list)
        if consulta_animal_ids:
            blocos_query = (
                BlocoExames.query.options(joinedload(BlocoExames.exames))
                .filter(BlocoExames.animal_id.in_(consulta_animal_ids))
            )
            for bloco in blocos_query.all():
                exam_blocks_by_animal[bloco.animal_id].append(bloco)
                consulta_ref = getattr(bloco, 'consulta_id', None)
                if consulta_ref:
                    exam_blocks_by_consulta[consulta_ref].append(bloco)

        schedule_events = []

        def _consulta_timestamp(consulta_obj):
            if consulta_obj.finalizada_em:
                return consulta_obj.finalizada_em
            if consulta_obj.appointment and consulta_obj.appointment.scheduled_at:
                return consulta_obj.appointment.scheduled_at
            return consulta_obj.created_at

        for consulta in consultas_finalizadas:
            timestamp = _consulta_timestamp(consulta)
            if not timestamp or not (start_dt_utc <= timestamp < end_dt_utc):
                continue
            relevant_blocks = exam_blocks_by_consulta.get(consulta.id)
            if not relevant_blocks:
                relevant_blocks = [
                    bloco
                    for bloco in exam_blocks_by_animal.get(consulta.animal_id, [])
                    if bloco.data_criacao
                    and timestamp
                    and bloco.data_criacao.date() == timestamp.date()
                ]
            exam_summary = []
            exam_ids = []
            for bloco in relevant_blocks or []:
                for exame in bloco.exames:
                    exam_ids.append(exame.id)
                    exam_summary.append(
                        {
                            'nome': exame.nome,
                            'status': exame.status,
                            'justificativa': exame.justificativa,
                            'bloco_id': bloco.id,
                        }
                    )
            schedule_events.append(
                {
                    'kind': 'consulta_finalizada',
                    'timestamp': timestamp,
                    'animal': consulta.animal,
                    'consulta': consulta,
                    'consulta_id': consulta.id,
                    'appointment': consulta.appointment,
                    'exam_summary': exam_summary,
                    'exam_blocks': relevant_blocks or [],
                    'exam_ids': exam_ids,
                }
            )

        for appt in past_accepted_consultas:
            if not appt.scheduled_at or not (start_dt_utc <= appt.scheduled_at < end_dt_utc):
                continue
            schedule_events.append(
                {
                    'kind': 'consulta_aceita',
                    'timestamp': appt.scheduled_at,
                    'animal': appt.animal,
                    'consulta': appt.consulta,
                    'consulta_id': appt.consulta_id,
                    'appointment': appt,
                    'exam_summary': [],
                    'exam_blocks': [],
                    'exam_ids': [],
                }
            )

        for item in appointments_upcoming:
            if item['kind'] == 'retorno':
                appt = item['appt']
                schedule_events.append(
                    {
                        'kind': 'retorno',
                        'timestamp': appt.scheduled_at,
                        'animal': appt.animal,
                        'appointment': appt,
                        'consulta_id': appt.consulta_id,
                        'exam_summary': [],
                        'exam_blocks': [],
                        'exam_ids': [],
                    }
                )

        for exam in upcoming_exams:
            schedule_events.append(
                {
                    'kind': 'exame',
                    'timestamp': exam.scheduled_at,
                    'animal': exam.animal,
                    'exam': exam,
                    'consulta_id': None,
                    'exam_summary': [],
                    'exam_blocks': [],
                    'exam_ids': [exam.id],
                }
            )

        schedule_events.sort(
            key=lambda event: event.get('timestamp') or datetime.min,
            reverse=True,
        )

        session['exam_pending_seen_count'] = ExamAppointment.query.filter_by(
            specialist_id=veterinario.id, status='pending'
        ).count()
        session['appointment_pending_seen_count'] = (
            Appointment.query.filter(Appointment.status == 'scheduled')
            .filter(Appointment.scheduled_at >= now + timedelta(hours=2))
            .filter(appointment_scope_filter)
            .count()
        )
        clinic_pending_query = _clinic_pending_appointments_query(veterinario)
        session['clinic_pending_seen_count'] = (
            clinic_pending_query.count() if clinic_pending_query is not None else 0
        )

        return render_template(
            'agendamentos/edit_vet_schedule.html',
            schedule_form=schedule_form,
            appointment_form=appointment_form,
            veterinario=veterinario,
            agenda_veterinarios=agenda_veterinarios,
            agenda_colaboradores=agenda_colaboradores,
            admin_selected_view=admin_selected_view,
            admin_selected_veterinario_id=admin_selected_veterinario_id,
            admin_selected_colaborador_id=admin_selected_colaborador_id,
            horarios_grouped=horarios_grouped,
            appointments_pending_consults=appointments_pending_consults,
            pending_consults_for_me=pending_consults_for_me,
            pending_consults_waiting_others=pending_consults_waiting_others,
            exams_pending_to_accept=exams_pending_to_accept,
            exams_waiting_other_vets=exams_waiting_other_vets,
            appointments_upcoming=appointments_upcoming,
            appointments_upcoming_for_me=appointments_upcoming_for_me,
            appointments_upcoming_requested=appointments_upcoming_requested,
            schedule_events=schedule_events,
            start_dt=start_dt,
            end_dt=end_dt,
            timedelta=timedelta,
            calendar_summary_vets=calendar_summary_vets,
            calendar_summary_clinic_ids=calendar_summary_clinic_ids,
            calendar_redirect_url=calendar_redirect_url,
            exam_confirm_default_hours=current_app.config.get(
                'EXAM_CONFIRM_DEFAULT_HOURS',
                2,
            ),
        )
    else:
        if worker in ['colaborador', 'admin']:
            appointment_form = AppointmentForm(prefix='appointment')
            clinica_id = current_user.clinica_id
            if current_user.role == 'admin' and worker == 'colaborador':
                colaborador_id_arg = request.args.get('colaborador_id', type=int)
                if colaborador_id_arg:
                    selected_colaborador = next(
                        (c for c in agenda_colaboradores if c.id == colaborador_id_arg),
                        None,
                    )
                    if not selected_colaborador:
                        selected_colaborador = (
                            User.query.filter_by(
                                id=colaborador_id_arg, worker='colaborador'
                            )
                            .first_or_404()
                        )
                elif agenda_colaboradores:
                    selected_colaborador = agenda_colaboradores[0]
                if selected_colaborador:
                    admin_selected_colaborador_id = selected_colaborador.id
                    if selected_colaborador.clinica_id:
                        clinica_id = selected_colaborador.clinica_id
                if not clinica_id:
                    clinica = Clinica.query.first()
                    clinica_id = clinica.id if clinica else None
            elif current_user.role == 'admin' and not clinica_id:
                clinica = Clinica.query.first()
                clinica_id = clinica.id if clinica else None
            animals = Animal.query.filter_by(clinica_id=clinica_id).all()
            appointment_form.animal_id.choices = [(a.id, a.name) for a in animals]

            clinic = Clinica.query.get(clinica_id) if clinica_id else None
            vets = Veterinario.query.filter_by(clinica_id=clinica_id).all()
            specialists = []
            if clinic:
                specialists = [
                    vet
                    for vet in getattr(clinic, 'veterinarios_associados', []) or []
                    if getattr(vet, 'id', None) is not None
                ]
            combined_vets = unique_items_by_id(vets + specialists)

            def _vet_sort_key(vet):
                name = (
                    getattr(getattr(vet, 'user', None), 'name', '')
                    or ''
                )
                return name.lower()

            combined_vets = sorted(
                (vet for vet in combined_vets if getattr(vet, 'id', None) is not None),
                key=_vet_sort_key,
            )

            clinic_vet_ids = {getattr(vet, 'id', None) for vet in vets if getattr(vet, 'id', None) is not None}
            specialist_ids = {getattr(vet, 'id', None) for vet in specialists}

            def _vet_label(vet):
                base_name = getattr(getattr(vet, 'user', None), 'name', None)
                label = base_name or f"Profissional #{getattr(vet, 'id', '—')}"
                if getattr(vet, 'id', None) in specialist_ids and getattr(vet, 'id', None) not in clinic_vet_ids:
                    return f"{label} (Especialista)"
                return label

            appointment_form.veterinario_id.choices = [
                (vet.id, _vet_label(vet)) for vet in combined_vets
            ]
            calendar_summary_vets = [
                {
                    'id': vet.id,
                    'name': _vet_label(vet),
                    'label': _vet_label(vet),
                    'full_name': getattr(getattr(vet, 'user', None), 'name', None),
                    'specialty_list': getattr(vet, 'specialty_list', None),
                    'is_specialist': getattr(vet, 'id', None) in specialist_ids
                    and getattr(vet, 'id', None) not in clinic_vet_ids,
                }
                for vet in combined_vets
            ]
            calendar_summary_clinic_ids = [clinica_id] if clinica_id else []
            if appointment_form.validate_on_submit():
                scheduled_at_local = datetime.combine(
                    appointment_form.date.data, appointment_form.time.data
                )
                if not is_slot_available(
                    appointment_form.veterinario_id.data,
                    scheduled_at_local,
                    kind=appointment_form.kind.data,
                ):
                    flash(
                        'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                        'danger'
                    )
                else:
                    scheduled_at = (
                        scheduled_at_local
                        .replace(tzinfo=BR_TZ)
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                    if appointment_form.kind.data == 'exame':
                        duration = get_appointment_duration('exame')
                        if has_conflict_for_slot(
                            appointment_form.veterinario_id.data,
                            scheduled_at_local,
                            duration,
                        ):
                            flash(
                                'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                                'danger'
                            )
                        else:
                            appt = ExamAppointment(
                                animal_id=appointment_form.animal_id.data,
                                specialist_id=appointment_form.veterinario_id.data,
                                requester_id=current_user.id,
                                scheduled_at=scheduled_at,
                                status='confirmed',
                            )
                            db.session.add(appt)
                            db.session.commit()
                            flash('Exame agendado com sucesso.', 'success')
                    else:
                        animal = get_animal_or_404(appointment_form.animal_id.data)
                        tutor_id = animal.user_id
                        requires_plan = current_app.config.get(
                            'REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT', False
                        )
                        if requires_plan and not Appointment.has_active_subscription(
                            animal.id, tutor_id
                        ):
                            flash(
                                'O animal não possui uma assinatura de plano de saúde ativa.',
                                'danger',
                            )
                            return _redirect_to_current_appointments()

                    appt = Appointment(
                        animal_id=animal.id,
                        tutor_id=tutor_id,
                        veterinario_id=appointment_form.veterinario_id.data,
                        scheduled_at=scheduled_at,
                        clinica_id=clinica_id,
                        notes=appointment_form.reason.data,
                        kind=appointment_form.kind.data,
                        created_by=current_user.id,
                        created_at=datetime.utcnow(),
                    )
                    db.session.add(appt)
                    db.session.commit()
                    flash('Agendamento criado com sucesso.', 'success')
                return _redirect_to_current_appointments()
            appointments = (
                Appointment.query
                .filter_by(clinica_id=clinica_id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            exam_appointments = (
                ExamAppointment.query
                .join(ExamAppointment.animal)
                .filter(Animal.clinica_id == clinica_id)
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
            vaccine_appointments = (
                Vacina.query
                .join(Vacina.animal)
                .filter(Animal.clinica_id == clinica_id)
                .filter(Vacina.aplicada_em >= date.today())
                .order_by(Vacina.aplicada_em)
                .all()
            )
            for vac in vaccine_appointments:
                vac.scheduled_at = datetime.combine(vac.aplicada_em, time.min, tzinfo=BR_TZ)
            form = appointment_form
        else:
            tutor_user = current_user
            if current_user.role == 'admin' and worker == 'tutor':
                tutor_user = User.query.filter(User.worker.is_(None)).first() or current_user
            appointments = (
                Appointment.query.filter_by(tutor_id=tutor_user.id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            exam_appointments = (
                ExamAppointment.query
                .join(ExamAppointment.animal)
                .filter(Animal.user_id == tutor_user.id)
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
            vaccine_appointments = (
                Vacina.query
                .join(Vacina.animal)
                .filter(Animal.user_id == tutor_user.id)
                .filter(Vacina.aplicada_em >= date.today())
                .order_by(Vacina.aplicada_em)
                .all()
            )
            for vac in vaccine_appointments:
                vac.scheduled_at = datetime.combine(vac.aplicada_em, time.min, tzinfo=BR_TZ)
            form = None
        appointments_grouped = group_appointments_by_day(appointments)
        exam_appointments_grouped = group_appointments_by_day(exam_appointments)
        vaccine_appointments_grouped = group_appointments_by_day(vaccine_appointments)
        if request.headers.get('X-Partial') == 'appointments_table' or request.args.get('partial') == 'appointments_table':
            return render_template(
                'partials/appointments_table.html',
                appointments_grouped=appointments_grouped,
            )

        return render_template(
            'agendamentos/appointments.html',
            appointments=appointments,
            appointments_grouped=appointments_grouped,
            exam_appointments=exam_appointments,
            exam_appointments_grouped=exam_appointments_grouped,
            vaccine_appointments=vaccine_appointments,
            vaccine_appointments_grouped=vaccine_appointments_grouped,
            form=form,
            agenda_users=agenda_users,
            agenda_veterinarios=agenda_veterinarios,
            agenda_colaboradores=agenda_colaboradores,
            admin_selected_view=admin_selected_view,
            admin_selected_veterinario_id=admin_selected_veterinario_id,
            admin_selected_colaborador_id=admin_selected_colaborador_id,
            admin_default_selection_value=admin_default_selection_value,
            calendar_summary_vets=calendar_summary_vets,
            calendar_summary_clinic_ids=calendar_summary_clinic_ids,
        )


@app.route('/appointments/calendar')
@login_required
def appointments_calendar():
    """Página experimental de calendário para tutores."""
    return render_template('agendamentos/appointments_calendar.html')


@app.route('/appointments/<int:veterinario_id>/schedule/<int:horario_id>/edit', methods=['POST'])
@login_required
def edit_vet_schedule_slot(veterinario_id, horario_id):
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )

    def json_response(success, status=200, message=None, errors=None, extra=None):
        if not wants_json:
            abort(status)
        payload = {'success': success}
        if message:
            payload['message'] = message
        if errors:
            payload['errors'] = errors
        if extra:
            payload.update(extra)
        response = jsonify(payload)
        response.status_code = status
        return response

    if not (
        _is_admin()
        or (
            current_user.worker == 'veterinario'
            and getattr(current_user, 'veterinario', None)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
        abort(403)
    veterinario = Veterinario.query.get_or_404(veterinario_id)
    horario = VetSchedule.query.get_or_404(horario_id)
    if not _is_admin() and horario.veterinario_id != veterinario_id:
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
        abort(403)
    form = VetScheduleForm(prefix='schedule')
    if _is_admin():
        vet_choices = Veterinario.query.all()
    else:
        vet_choices = [veterinario]
    form.veterinario_id.choices = [
        (v.id, v.user.name) for v in vet_choices
    ]
    if not _is_admin():
        raw_vet_id = request.form.get(form.veterinario_id.name)
        if raw_vet_id is None:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        try:
            submitted_vet_id = int(raw_vet_id)
        except (TypeError, ValueError):
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        if submitted_vet_id != veterinario_id:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
    redirect_response = redirect(url_for('appointments'))
    if form.validate_on_submit():
        novo_vet = form.veterinario_id.data
        if not _is_admin() and novo_vet != veterinario_id:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        dias = form.dias_semana.data
        if not dias:
            if wants_json:
                return json_response(False, status=400, message='Selecione ao menos um dia da semana.')
            flash('Selecione ao menos um dia da semana.', 'danger')
            return redirect_response
        dia = dias[0]
        inicio = form.hora_inicio.data
        fim = form.hora_fim.data
        if has_schedule_conflict(novo_vet, dia, inicio, fim, exclude_id=horario.id):
            if wants_json:
                return json_response(False, status=400, message='Conflito de horário.')
            flash('Conflito de horário.', 'danger')
        else:
            horario.veterinario_id = novo_vet
            horario.dia_semana = dia
            horario.hora_inicio = inicio
            horario.hora_fim = fim
            horario.intervalo_inicio = form.intervalo_inicio.data
            horario.intervalo_fim = form.intervalo_fim.data
            db.session.commit()
            if wants_json:
                return json_response(
                    True,
                    message='Horário atualizado com sucesso.',
                    extra={
                        'schedule': {
                            'id': horario.id,
                            'veterinario_id': horario.veterinario_id,
                            'dia_semana': horario.dia_semana,
                            'hora_inicio': horario.hora_inicio.strftime('%H:%M') if horario.hora_inicio else None,
                            'hora_fim': horario.hora_fim.strftime('%H:%M') if horario.hora_fim else None,
                            'intervalo_inicio': horario.intervalo_inicio.strftime('%H:%M') if horario.intervalo_inicio else None,
                            'intervalo_fim': horario.intervalo_fim.strftime('%H:%M') if horario.intervalo_fim else None,
                        }
                    }
                )
            flash('Horário atualizado com sucesso.', 'success')
        return redirect_response
    if wants_json:
        errors = form.errors or {}
        flat_errors = [err for field_errors in errors.values() for err in field_errors]
        message = flat_errors[0] if flat_errors else 'Não foi possível atualizar o horário.'
        return json_response(False, status=400, message=message, errors=errors if errors else None)
    flash('Não foi possível atualizar o horário. Verifique os dados e tente novamente.', 'danger')
    return redirect_response


@app.route('/appointments/<int:veterinario_id>/schedule/<int:horario_id>/delete', methods=['POST'])
@login_required
def delete_vet_schedule(veterinario_id, horario_id):
    if not (
        _is_admin()
        or (
            current_user.worker == 'veterinario'
            and getattr(current_user, 'veterinario', None)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        abort(403)
    horario = VetSchedule.query.get_or_404(horario_id)
    if not _is_admin() and horario.veterinario_id != veterinario_id:
        abort(403)
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('appointments'))


@app.route('/appointments/pending')
@login_required
def pending_appointments():
    return redirect(url_for('appointments'))


@app.route('/appointments/manage')
@login_required
def manage_appointments():
    if current_user.role != 'admin' and current_user.worker not in ['veterinario', 'colaborador']:
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('index'))
    query = Appointment.query.order_by(Appointment.scheduled_at)
    if current_user.role != 'admin':
        if current_user.worker == 'veterinario':
            query = query.filter_by(clinica_id=current_user.veterinario.clinica_id)
        elif current_user.worker == 'colaborador':
            query = query.filter_by(clinica_id=current_user.clinica_id)
    appointments = query.all()
    delete_form = AppointmentDeleteForm()
    return render_template('agendamentos/appointments_admin.html', appointments=appointments, delete_form=delete_form)


@app.route('/appointments/<int:appointment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if current_user.worker in ['veterinario', 'colaborador']:
        if current_user.worker == 'veterinario':
            user_clinic = current_user.veterinario.clinica_id
        else:
            user_clinic = current_user.clinica_id

        # Some legacy appointments might not have `clinica_id` stored.
        # In that case, fall back to the clinic of the assigned veterinarian
        # to validate access instead of denying with a 403.
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if appointment_clinic != user_clinic:
            abort(403)
    elif current_user.role != 'admin' and appointment.tutor_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        date_str = data.get('date')
        time_str = data.get('time')
        vet_id = data.get('veterinario_id')
        notes = data.get('notes')
        if not date_str or not time_str or not vet_id:
            return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
        try:
            scheduled_at_local = datetime.combine(
                datetime.strptime(date_str, '%Y-%m-%d').date(),
                datetime.strptime(time_str, '%H:%M').time(),
            )
            vet_id = int(vet_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Dados inválidos.'}), 400
        existing_local = (
            appointment.scheduled_at
            .replace(tzinfo=timezone.utc)
            .astimezone(BR_TZ)
            .replace(tzinfo=None)
        )
        if not is_slot_available(vet_id, scheduled_at_local, kind=appointment.kind) and not (
            vet_id == appointment.veterinario_id and scheduled_at_local == existing_local
        ):
            return jsonify({
                'success': False,
                'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
            }), 400
        appointment.veterinario_id = vet_id
        appointment.scheduled_at = (
            scheduled_at_local
            .replace(tzinfo=BR_TZ)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        if notes is not None:
            appointment.notes = notes
        db.session.commit()
        card_html = render_template('partials/_appointment_card.html', appt=appointment)
        return jsonify({
            'success': True,
            'message': 'Agendamento atualizado com sucesso.',
            'card_html': card_html,
            'appointment_id': appointment.id,
        })

    veterinarios = Veterinario.query.all()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template(
            'partials/edit_appointment_form.html',
            appointment=appointment,
            veterinarios=veterinarios,
        )
    return render_template('agendamentos/edit_appointment.html', appointment=appointment, veterinarios=veterinarios)


@app.route('/appointments/<int:appointment_id>/status', methods=['POST'])
@login_required
def update_appointment_status(appointment_id):
    """Update the status of an appointment."""
    appointment = Appointment.query.get_or_404(appointment_id)

    if current_user.role == 'admin':
        pass
    elif current_user.worker in ['veterinario', 'colaborador']:
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if current_user.worker == 'veterinario':
            veterinario = getattr(current_user, 'veterinario', None)
            vet_id = getattr(veterinario, 'id', None)
            if not (vet_id and appointment.veterinario_id == vet_id):
                clinic_ids = set()
                primary_clinic = getattr(veterinario, 'clinica_id', None)
                if primary_clinic is not None:
                    clinic_ids.add(primary_clinic)
                clinic_ids.update(
                    clinica_id
                    for clinica_id in (
                        getattr(clinica, 'id', None)
                        for clinica in getattr(veterinario, 'clinicas', [])
                    )
                    if clinica_id is not None
                )

                if appointment_clinic not in clinic_ids:
                    abort(403)
        else:
            user_clinic = getattr(current_user, 'clinica_id', None)
            if appointment_clinic != user_clinic:
                abort(403)
    elif appointment.tutor_id != current_user.id:
        abort(403)

    accepts = request.accept_mimetypes
    accept_json = accepts['application/json']
    accept_html = accepts['text/html']
    wants_json = (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or (accept_json > 0 and accept_json > accept_html)
    )
    redirect_url = request.referrer or url_for('appointments')

    status_value = request.form.get('status') or (request.get_json(silent=True) or {}).get('status')
    status = (status_value or '').strip().lower()
    allowed_statuses = {'scheduled', 'completed', 'canceled', 'accepted'}
    if status not in allowed_statuses:
        message = 'Status inválido.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 400
        flash(message, 'error')
        return redirect(redirect_url)

    if status == 'accepted' and current_user.role != 'admin':
        error_message = 'Somente o veterinário responsável pode aceitar este agendamento.'
        if current_user.worker != 'veterinario':
            if wants_json:
                return jsonify({'success': False, 'message': error_message}), 403
            flash(error_message, 'error')
            return redirect(redirect_url)
        veterinario = getattr(current_user, 'veterinario', None)
        vet_id = getattr(veterinario, 'id', None)
        if not (vet_id and appointment.veterinario_id == vet_id):
            if wants_json:
                return jsonify({'success': False, 'message': error_message}), 403
            flash(error_message, 'error')
            return redirect(redirect_url)

    should_enforce_deadline = False
    if status == 'accepted':
        should_enforce_deadline = current_user.role != 'admin'
    elif status == 'canceled':
        should_enforce_deadline = (
            current_user.role != 'admin'
            and current_user.worker not in {'veterinario', 'colaborador'}
        )

    if should_enforce_deadline and appointment.scheduled_at - datetime.utcnow() < timedelta(hours=2):
        message = 'Prazo expirado.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 400
        # Mantém o comportamento simples de texto quando o prazo expira.
        return message, 400

    appointment.status = status
    db.session.commit()

    if wants_json:
        card_html = render_template('partials/_appointment_card.html', appt=appointment)
        return jsonify({
            'success': True,
            'message': 'Status atualizado.',
            'status': appointment.status,
            'appointment_id': appointment.id,
            'card_html': card_html,
        })

    flash('Status atualizado.', 'success')
    # Sempre redireciona de volta à página anterior para evitar exibir apenas
    # o JSON "{\"success\": true}".
    return redirect(request.referrer or url_for('appointments'))


@app.route('/appointments/<int:appointment_id>/delete', methods=['POST'])
@login_required
def delete_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    if current_user.role == 'admin':
        pass
    elif current_user.worker in ['veterinario', 'colaborador']:
        if current_user.worker == 'veterinario':
            veterinario = getattr(current_user, 'veterinario', None)
            user_clinic = getattr(veterinario, 'clinica_id', None)
        else:
            user_clinic = getattr(current_user, 'clinica_id', None)

        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if appointment_clinic != user_clinic:
            abort(403)
    else:
        abort(403)
    db.session.delete(appointment)
    db.session.commit()
    flash('Agendamento removido.', 'success')
    return redirect(request.referrer or url_for('manage_appointments'))


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


@app.route('/api/my_pets')
@login_required
def api_my_pets():
    """Return the authenticated tutor's pets ordered by recency."""
    pets = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
        )
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.date_added.desc())
        .all()
    )
    return jsonify([_serialize_calendar_pet(p) for p in pets])


@app.route('/api/clinic_pets')
@login_required
def api_clinic_pets():
    """Return pets associated with the current clinic (or admin selection)."""

    if current_user.worker not in {"veterinario", "colaborador"} and current_user.role != 'admin':
        return api_my_pets()

    clinic_id = None
    view_as = request.args.get('view_as')

    if current_user.role == 'admin':
        if view_as == 'veterinario':
            vet_id = request.args.get('veterinario_id', type=int)
            if vet_id:
                veterinario = Veterinario.query.get(vet_id)
                clinic_id = veterinario.clinica_id if veterinario else None
        elif view_as == 'colaborador':
            colaborador_id = request.args.get('colaborador_id', type=int)
            if colaborador_id:
                colaborador = User.query.get(colaborador_id)
                clinic_id = colaborador.clinica_id if colaborador else None
        if clinic_id is None:
            clinic_id = request.args.get('clinica_id', type=int)
        if clinic_id is None:
            # Default to the first accessible clinic for the admin, if any.
            clinic_rows = clinicas_do_usuario().with_entities(Clinica.id).all()
            for row in clinic_rows:
                try:
                    clinic_id = row[0]
                except (TypeError, IndexError):
                    clinic_id = getattr(row, 'id', None)
                if clinic_id:
                    break
    else:
        clinic_id = current_user_clinic_id()

    if not clinic_id:
        return jsonify([])

    last_appt = (
        db.session.query(
            Appointment.animal_id,
            func.max(Appointment.scheduled_at).label('last_at'),
        )
        .filter(Appointment.clinica_id == clinic_id)
        .group_by(Appointment.animal_id)
        .subquery()
    )

    pets = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
        )
        .outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
        .filter(Animal.removido_em.is_(None))
        .filter(
            or_(
                Animal.clinica_id == clinic_id,
                last_appt.c.last_at.isnot(None),
            )
        )
        .order_by(func.coalesce(last_appt.c.last_at, Animal.date_added).desc())
        .all()
    )

    return jsonify([_serialize_calendar_pet(p) for p in pets])


@app.route('/api/my_appointments')
@login_required
def api_my_appointments():
    """Return the current user's appointments as calendar events."""
    from models import (
        Appointment,
        ExamAppointment,
        Vacina,
        Animal,
        Veterinario,
        User,
        Clinica,
    )

    query = Appointment.query
    context = {
        'mode': None,
        'tutor_id': None,
        'vet': None,
        'clinic_ids': [],
    }

    if current_user.role == 'admin':
        def _coerce_first_int(values):
            if values is None:
                return None
            if isinstance(values, (list, tuple)):
                values = values[0] if values else None
            if values in (None, ""):
                return None
            try:
                return int(values)
            except (TypeError, ValueError):
                return None

        def _admin_view_context():
            referrer_params = {}
            if request.referrer:
                parsed = urlparse(request.referrer)
                referrer_params = parse_qs(parsed.query)
            view_as = request.args.get('view_as') or referrer_params.get('view_as', [None])[0]
            vet_id = request.args.get('veterinario_id', type=int)
            if vet_id is None:
                vet_id = _coerce_first_int(referrer_params.get('veterinario_id'))
            clinic_id = request.args.get('clinica_id', type=int)
            if clinic_id is None:
                clinic_id = _coerce_first_int(referrer_params.get('clinica_id'))
            tutor_id = request.args.get('tutor_id', type=int)
            if tutor_id is None:
                tutor_id = _coerce_first_int(referrer_params.get('tutor_id'))
            return view_as, vet_id, clinic_id, tutor_id

        accessible_clinic_ids = None

        def _accessible_clinic_ids():
            nonlocal accessible_clinic_ids
            if accessible_clinic_ids is None:
                rows = clinicas_do_usuario().with_entities(Clinica.id).all()
                clinic_ids = []
                for row in rows:
                    try:
                        clinic_id_value = row[0]
                    except (TypeError, IndexError):
                        clinic_id_value = getattr(row, 'id', None)
                    if clinic_id_value is None or clinic_id_value in clinic_ids:
                        continue
                    clinic_ids.append(clinic_id_value)
                accessible_clinic_ids = clinic_ids
            return accessible_clinic_ids

        view_as, vet_id, clinic_id, tutor_id = _admin_view_context()

        context['clinic_ids'] = list(_accessible_clinic_ids())
        if view_as == 'tutor' and tutor_id:
            context['mode'] = 'tutor'
            context['tutor_id'] = tutor_id
        elif view_as == 'veterinario':
            target_vet = Veterinario.query.get(vet_id) if vet_id else None
            context['mode'] = 'veterinario'
            context['vet'] = target_vet
            target_clinics = []
            if clinic_id:
                target_clinics.append(clinic_id)
            elif context['clinic_ids']:
                target_clinics.extend(context['clinic_ids'])
            context['clinic_ids'] = [cid for cid in target_clinics if cid]
        elif view_as == 'colaborador':
            target_clinics = []
            if clinic_id:
                target_clinics.append(clinic_id)
            elif context['clinic_ids']:
                target_clinics.extend(context['clinic_ids'])
            context['mode'] = 'clinics'
            context['clinic_ids'] = [cid for cid in target_clinics if cid]
        else:
            context['mode'] = 'clinics'

        def _creator_clinic_filter(clinic_ids):
            sanitized = [cid for cid in (clinic_ids or []) if cid]
            if not sanitized:
                return None
            return Appointment.creator.has(
                or_(
                    User.clinica_id.in_(sanitized),
                    User.veterinario.has(
                        or_(
                            Veterinario.clinica_id.in_(sanitized),
                            Veterinario.clinicas.any(Clinica.id.in_(sanitized)),
                        )
                    ),
                )
            )

        if view_as == 'veterinario':
            if not vet_id and getattr(current_user, 'veterinario', None):
                vet_id = current_user.veterinario.id
            filters = []
            if vet_id:
                filters.append(Appointment.veterinario_id == vet_id)
                target_vet = target_vet or Veterinario.query.get(vet_id)
            target_vet_user_id = getattr(target_vet, 'user_id', None) if target_vet else None
            if target_vet_user_id:
                filters.append(Appointment.created_by == target_vet_user_id)
            if filters:
                query = query.filter(or_(*filters) if len(filters) > 1 else filters[0])
        elif view_as == 'colaborador':
            clinic_ids = list(_accessible_clinic_ids())
            if clinic_id and clinic_id not in clinic_ids:
                clinic_ids.append(clinic_id)
            if clinic_ids:
                creator_filter = _creator_clinic_filter(clinic_ids)
                clinic_filters = [Appointment.clinica_id.in_(clinic_ids)]
                if creator_filter is not None:
                    clinic_filters.append(creator_filter)
                query = query.filter(
                    or_(*clinic_filters)
                    if len(clinic_filters) > 1
                    else clinic_filters[0]
                )
        elif view_as == 'tutor':
            target_tutor_id = tutor_id or current_user.id
            query = query.filter(Appointment.tutor_id == target_tutor_id)
        else:
            clinic_ids = _accessible_clinic_ids()
            if clinic_ids:
                creator_filter = _creator_clinic_filter(clinic_ids)
                clinic_filters = [
                    Appointment.clinica_id.in_(clinic_ids),
                    Appointment.veterinario.has(
                        Veterinario.clinica_id.in_(clinic_ids)
                    ),
                ]
                if creator_filter is not None:
                    clinic_filters.append(creator_filter)
                query = query.filter(
                    or_(*clinic_filters)
                    if len(clinic_filters) > 1
                    else clinic_filters[0]
                )
            if not context['clinic_ids']:
                context['clinic_ids'] = [cid for cid in (clinic_ids or []) if cid]
            context['mode'] = context['mode'] or 'clinics'
    elif current_user.worker == 'veterinario' and getattr(current_user, 'veterinario', None):
        query = query.filter(
            or_(
                Appointment.veterinario_id == current_user.veterinario.id,
                Appointment.created_by == current_user.id,
            )
        )
        vet_profile = current_user.veterinario
        context['mode'] = 'veterinario'
        context['vet'] = vet_profile
        clinic_ids = []
        primary_clinic = getattr(vet_profile, 'clinica_id', None)
        if primary_clinic:
            clinic_ids.append(primary_clinic)
        for clinic in getattr(vet_profile, 'clinicas', []) or []:
            clinic_id_value = getattr(clinic, 'id', None)
            if clinic_id_value and clinic_id_value not in clinic_ids:
                clinic_ids.append(clinic_id_value)
        context['clinic_ids'] = clinic_ids
    elif current_user.worker == 'colaborador' and current_user.clinica_id:
        query = query.filter(
            or_(
                Appointment.clinica_id == current_user.clinica_id,
                Appointment.created_by == current_user.id,
            )
        )
        context['mode'] = 'clinics'
        context['clinic_ids'] = [current_user.clinica_id]
    else:
        query = query.filter_by(tutor_id=current_user.id)
        context['mode'] = 'tutor'
        context['tutor_id'] = current_user.id

    appts = query.order_by(Appointment.scheduled_at).all()
    events = appointments_to_events(appts)

    existing_event_ids = set()
    for event in events:
        event_id = event.get('id') if isinstance(event, dict) else None
        if event_id:
            existing_event_ids.add(event_id)

    def _append_event(event):
        if not event or not isinstance(event, dict):
            return
        event_id = event.get('id')
        if event_id and event_id in existing_event_ids:
            return
        events.append(event)
        if event_id:
            existing_event_ids.add(event_id)

    def _extend_exam_events(*, or_filters=None, and_filters=None):
        query_obj = ExamAppointment.query.outerjoin(ExamAppointment.animal)
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        exam_items = query_obj.order_by(ExamAppointment.scheduled_at).all()
        for exam in unique_items_by_id(exam_items):
            event = exam_to_event(exam)
            if event:
                _append_event(event)

    def _extend_vaccine_events(*, or_filters=None, and_filters=None):
        query_obj = Vacina.query.outerjoin(Vacina.animal)
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        vaccine_items = query_obj.order_by(Vacina.aplicada_em).all()
        for vaccine in unique_items_by_id(vaccine_items):
            event = vaccine_to_event(vaccine)
            if event:
                _append_event(event)

    def _extend_consulta_events(*, or_filters=None, and_filters=None):
        query_obj = (
            Consulta.query
            .outerjoin(Consulta.animal)
            .options(
                joinedload(Consulta.animal).joinedload(Animal.owner),
                joinedload(Consulta.veterinario),
                joinedload(Consulta.clinica),
            )
            .filter(~Consulta.appointment.has())
        )
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        consulta_items = query_obj.order_by(Consulta.created_at).all()
        for consulta in unique_items_by_id(consulta_items):
            event = consulta_to_event(consulta)
            if event:
                _append_event(event)

    def _extend_for_tutor(tutor_id):
        if not tutor_id:
            return
        tutor_vet = None
        if current_user.is_authenticated and current_user.id == tutor_id:
            tutor_vet = getattr(current_user, 'veterinario', None)
        else:
            tutor_obj = User.query.get(tutor_id)
            tutor_vet = getattr(tutor_obj, 'veterinario', None) if tutor_obj else None
        or_filters = [
            ExamAppointment.requester_id == tutor_id,
            Animal.user_id == tutor_id,
        ]
        if tutor_vet:
            or_filters.append(ExamAppointment.specialist_id == tutor_vet.id)
        _extend_exam_events(or_filters=or_filters)
        _extend_vaccine_events(
            or_filters=[
                Animal.user_id == tutor_id,
                Vacina.aplicada_por == tutor_id,
            ],
            and_filters=[
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            ],
        )
        _extend_consulta_events(or_filters=[Animal.user_id == tutor_id])

    def _extend_for_vet(vet_profile, clinic_ids=None):
        if not vet_profile:
            return
        vet_id = getattr(vet_profile, 'id', None)
        if not vet_id:
            return
        sanitized_clinic_ids = [cid for cid in (clinic_ids or []) if cid]
        vet_user_id = getattr(vet_profile, 'user_id', None)
        exam_filters = [ExamAppointment.specialist_id == vet_id]
        exam_filters.append(ExamAppointment.status.in_(['pending', 'confirmed']))
        if sanitized_clinic_ids:
            exam_filters.append(
                or_(
                    Animal.clinica_id.in_(sanitized_clinic_ids),
                    ExamAppointment.specialist.has(
                        Veterinario.clinica_id.in_(sanitized_clinic_ids)
                    ),
                )
            )
        _extend_exam_events(and_filters=exam_filters)

        vaccine_filters = [
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em >= date.today(),
        ]
        vet_user_id = getattr(vet_profile, 'user_id', None)
        if vet_user_id:
            vaccine_filters.append(Vacina.aplicada_por == vet_user_id)
        if sanitized_clinic_ids:
            vaccine_filters.append(Animal.clinica_id.in_(sanitized_clinic_ids))
        _extend_vaccine_events(and_filters=vaccine_filters)

        consulta_filters = []
        if vet_user_id:
            consulta_filters.append(Consulta.created_by == vet_user_id)
        if sanitized_clinic_ids:
            consulta_filters.append(Consulta.clinica_id.in_(sanitized_clinic_ids))
        if consulta_filters:
            _extend_consulta_events(and_filters=consulta_filters)

    def _extend_for_clinics(clinic_ids):
        sanitized = [cid for cid in (clinic_ids or []) if cid]
        if not sanitized:
            return
        clinic_filters = [
            or_(
                Animal.clinica_id.in_(sanitized),
                ExamAppointment.specialist.has(
                    Veterinario.clinica_id.in_(sanitized)
                ),
            ),
            ExamAppointment.status.in_(['pending', 'confirmed']),
        ]
        _extend_exam_events(and_filters=clinic_filters)
        vaccine_filters = [
            Animal.clinica_id.in_(sanitized),
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em >= date.today(),
        ]
        _extend_vaccine_events(and_filters=vaccine_filters)
        _extend_consulta_events(and_filters=[Consulta.clinica_id.in_(sanitized)])

    if context['mode'] == 'tutor':
        _extend_for_tutor(context.get('tutor_id'))
    elif context['mode'] == 'veterinario':
        _extend_for_vet(context.get('vet'), context.get('clinic_ids'))
    elif context['mode'] == 'clinics':
        _extend_for_clinics(context.get('clinic_ids'))

    return jsonify(events)


@app.route('/api/user_appointments/<int:user_id>')
@login_required
def api_user_appointments(user_id):
    """Return appointments for the selected user (admin only)."""
    if current_user.role != 'admin':
        abort(403)

    user = User.query.get_or_404(user_id)
    vet = getattr(user, 'veterinario', None)

    appointment_filters = [Appointment.tutor_id == user.id]
    if vet:
        appointment_filters.append(Appointment.veterinario_id == vet.id)
    appointments = (
        Appointment.query.filter(or_(*appointment_filters))
        .order_by(Appointment.scheduled_at)
        .all()
    ) if appointment_filters else []

    events = appointments_to_events(appointments)

    exam_filters = [ExamAppointment.requester_id == user.id]
    if vet:
        exam_filters.append(ExamAppointment.specialist_id == vet.id)
    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_filters.append(Animal.user_id == user.id)
    if exam_filters:
        exam_appointments = (
            exam_query.filter(or_(*exam_filters))
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        for exam in unique_items_by_id(exam_appointments):
            event = exam_to_event(exam)
            if event:
                events.append(event)

    vaccine_filters = [Animal.user_id == user.id, Vacina.aplicada_por == user.id]
    vaccine_query = Vacina.query.outerjoin(Vacina.animal)
    if vaccine_filters:
        vaccine_appointments = (
            vaccine_query.filter(
                or_(*vaccine_filters),
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            )
            .order_by(Vacina.aplicada_em)
            .all()
        )
        for vac in unique_items_by_id(vaccine_appointments):
            event = vaccine_to_event(vac)
            if event:
                events.append(event)

    return jsonify(events)


@app.route('/api/appointments/<int:appointment_id>/reschedule', methods=['POST'])
@login_required
def api_reschedule_appointment(appointment_id):
    """Update the schedule of an appointment after drag & drop operations."""

    appointment = Appointment.query.get_or_404(appointment_id)

    if current_user.worker in ['veterinario', 'colaborador']:
        if current_user.worker == 'veterinario':
            user_clinic = current_user.veterinario.clinica_id
        else:
            user_clinic = current_user.clinica_id
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id
        if appointment_clinic != user_clinic:
            abort(403)
    elif current_user.role != 'admin' and appointment.tutor_id != current_user.id:
        abort(403)

    data = request.get_json(silent=True) or {}
    start_str = data.get('start') or data.get('startStr')

    def _parse_client_datetime(value):
        if not value or not isinstance(value, str):
            return None
        value = value.strip()
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    new_start = _parse_client_datetime(start_str)
    if not new_start:
        return jsonify({'success': False, 'message': 'Horário inválido.'}), 400

    if new_start.tzinfo is None:
        new_start_with_tz = new_start.replace(tzinfo=BR_TZ)
        new_start_local = new_start
    else:
        new_start_with_tz = new_start.astimezone(BR_TZ)
        new_start_local = new_start_with_tz.replace(tzinfo=None)

    if appointment.scheduled_at.tzinfo is None:
        existing_local = (
            appointment.scheduled_at
            .replace(tzinfo=timezone.utc)
            .astimezone(BR_TZ)
            .replace(tzinfo=None)
        )
    else:
        existing_local = appointment.scheduled_at.astimezone(BR_TZ).replace(tzinfo=None)

    if (
        not is_slot_available(appointment.veterinario_id, new_start_local, kind=appointment.kind)
        and new_start_local != existing_local
    ):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.',
        }), 400

    appointment.scheduled_at = (
        new_start_with_tz
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    db.session.commit()

    updated_start = to_timezone_aware(appointment.scheduled_at)
    return jsonify({
        'success': True,
        'message': 'Agendamento atualizado com sucesso.',
        'start': updated_start.isoformat() if updated_start else None,
    })


@app.route('/api/clinic_appointments/<int:clinica_id>')
@login_required
def api_clinic_appointments(clinica_id):
    """Return appointments for a clinic as calendar events."""
    ensure_clinic_access(clinica_id)
    from models import User, Clinica

    creator_filter = Appointment.creator.has(
        or_(
            User.clinica_id == clinica_id,
            User.veterinario.has(
                or_(
                    Veterinario.clinica_id == clinica_id,
                    Veterinario.clinicas.any(Clinica.id == clinica_id),
                )
            ),
        )
    )

    appt_filters = [Appointment.clinica_id == clinica_id, creator_filter]
    appts = (
        Appointment.query
        .filter(or_(*appt_filters))
        .order_by(Appointment.scheduled_at)
        .all()
    )
    events = appointments_to_events(appts)

    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_appointments = (
        exam_query
        .filter(
            or_(
                Animal.clinica_id == clinica_id,
                ExamAppointment.specialist.has(Veterinario.clinica_id == clinica_id),
            ),
            ExamAppointment.status.in_(['pending', 'confirmed']),
        )
        .order_by(ExamAppointment.scheduled_at)
        .all()
    )
    for exam in unique_items_by_id(exam_appointments):
        event = exam_to_event(exam)
        if event:
            events.append(event)

    vaccine_query = Vacina.query.outerjoin(Vacina.animal)
    vaccine_appointments = (
        vaccine_query
        .filter(
            Animal.clinica_id == clinica_id,
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em >= date.today(),
        )
        .order_by(Vacina.aplicada_em)
        .all()
    )
    for vaccine in unique_items_by_id(vaccine_appointments):
        event = vaccine_to_event(vaccine)
        if event:
            events.append(event)

    return jsonify(events)


@app.route('/api/vet_appointments/<int:veterinario_id>')
@login_required
def api_vet_appointments(veterinario_id):
    """Return appointments for a veterinarian as calendar events."""
    veterinario = Veterinario.query.get_or_404(veterinario_id)

    vet_clinic_ids = set()
    primary_clinic_id = getattr(veterinario, 'clinica_id', None)
    if primary_clinic_id:
        vet_clinic_ids.add(primary_clinic_id)
    for clinic in getattr(veterinario, 'clinicas', []) or []:
        clinic_id_value = getattr(clinic, 'id', None)
        if clinic_id_value:
            vet_clinic_ids.add(clinic_id_value)

    requested_clinic_ids = []
    for value in request.args.getlist('clinica_id'):
        try:
            clinic_id_value = int(value)
        except (TypeError, ValueError):
            continue
        if clinic_id_value not in requested_clinic_ids:
            requested_clinic_ids.append(clinic_id_value)

    query = Appointment.query.filter_by(veterinario_id=veterinario_id)
    target_clinic_ids = []

    if current_user.role == 'admin':
        if requested_clinic_ids:
            query = query.filter(Appointment.clinica_id.in_(requested_clinic_ids))
            target_clinic_ids = requested_clinic_ids
    elif current_user.worker == 'veterinario':
        current_vet = getattr(current_user, 'veterinario', None)
        if not current_vet or current_vet.id != veterinario_id:
            abort(403)
    elif current_user.worker == 'colaborador':
        collaborator_clinic_id = getattr(current_user, 'clinica_id', None)
        ensure_clinic_access(collaborator_clinic_id)
        if not collaborator_clinic_id:
            abort(404)
        if vet_clinic_ids and collaborator_clinic_id not in vet_clinic_ids:
            abort(404)
        query = query.filter(Appointment.clinica_id == collaborator_clinic_id)
        target_clinic_ids = [collaborator_clinic_id]
    else:
        abort(403)

    appointments = query.order_by(Appointment.scheduled_at).all()
    events = appointments_to_events(appointments)

    exam_filters = [
        ExamAppointment.specialist_id == veterinario_id,
        ExamAppointment.status.in_(['pending', 'confirmed']),
    ]

    if target_clinic_ids:
        exam_filters.append(
            or_(
                Animal.clinica_id.in_(target_clinic_ids),
                ExamAppointment.specialist.has(
                    Veterinario.clinica_id.in_(target_clinic_ids)
                ),
            )
        )

    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_appointments = (
        exam_query.filter(*exam_filters)
        .order_by(ExamAppointment.scheduled_at)
        .all()
    )

    for exam in unique_items_by_id(exam_appointments):
        event = exam_to_event(exam)
        if event:
            events.append(event)

    vaccine_filters = [
        Vacina.aplicada_em.isnot(None),
        Vacina.aplicada_em >= date.today(),
    ]

    vet_user_id = getattr(veterinario, 'user_id', None)
    if vet_user_id:
        vaccine_filters.append(Vacina.aplicada_por == vet_user_id)

    if target_clinic_ids:
        vaccine_filters.append(Animal.clinica_id.in_(target_clinic_ids))

    vaccine_query = Vacina.query.outerjoin(Vacina.animal)
    vaccine_appointments = (
        vaccine_query.filter(*vaccine_filters)
        .order_by(Vacina.aplicada_em)
        .all()
    )

    for vaccine in unique_items_by_id(vaccine_appointments):
        event = vaccine_to_event(vaccine)
        if event:
            events.append(event)

    return jsonify(events)


@app.route('/api/specialists')
def api_specialists():
    from models import Veterinario, Specialty
    specialty_id = request.args.get('specialty_id', type=int)
    query = Veterinario.query
    if specialty_id:
        query = query.join(Veterinario.specialties).filter(Specialty.id == specialty_id)
    vets = query.all()
    return jsonify([
        {
            'id': v.id,
            'nome': v.user.name,
            'especialidades': [s.nome for s in v.specialties],
        }
        for v in vets
    ])


@app.route('/api/specialties')
def api_specialties():
    from models import Specialty
    specs = Specialty.query.order_by(Specialty.nome).all()
    return jsonify([{ 'id': s.id, 'nome': s.nome } for s in specs])


@app.route('/api/specialist/<int:veterinario_id>/available_times')
def api_specialist_available_times(veterinario_id):
    date_str = request.args.get('date')
    if not date_str:
        return jsonify([])
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    kind = request.args.get('kind', 'consulta')
    include_booked = request.args.get('include_booked', '').lower() in ('1', 'true', 'yes', 'on')
    times = get_available_times(
        veterinario_id,
        date_obj,
        kind=kind,
        include_booked=include_booked,
    )
    return jsonify(times)


@app.route('/api/specialist/<int:veterinario_id>/weekly_schedule')
def api_specialist_weekly_schedule(veterinario_id):
    start_str = request.args.get('start')
    days = int(request.args.get('days', 7))
    start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()
    data = get_weekly_schedule(veterinario_id, start_date, days)
    return jsonify(data)


@app.route('/animal/<int:animal_id>/schedule_exam', methods=['POST'])
@login_required
def schedule_exam(animal_id):
    from models import ExamAppointment, AgendaEvento, Veterinario, Animal, Message
    data = request.get_json(silent=True) or {}
    specialist_id = data.get('specialist_id')
    date_str = data.get('date')
    time_str = data.get('time')
    if not all([specialist_id, date_str, time_str]):
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    scheduled_at_local = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    scheduled_at = (
        scheduled_at_local
        .replace(tzinfo=BR_TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    # Ensure requested time falls within the veterinarian's available schedule
    available_times = get_available_times(specialist_id, scheduled_at_local.date(), kind='exame')
    if time_str not in available_times:
        if available_times:
            msg = (
                'Horário selecionado não está disponível. '
                f"Horários disponíveis: {', '.join(available_times)}"
            )
        else:
            msg = 'Nenhum horário disponível para a data escolhida.'
        return jsonify({'success': False, 'message': msg}), 400
    duration = get_appointment_duration('exame')
    if has_conflict_for_slot(specialist_id, scheduled_at_local, duration):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
        }), 400
    vet = Veterinario.query.get(specialist_id)
    animal = Animal.query.get(animal_id)
    same_user = vet and vet.user_id == current_user.id
    appt = ExamAppointment(
        animal_id=animal_id,
        specialist_id=specialist_id,
        requester_id=current_user.id,
        scheduled_at=scheduled_at,
        status='confirmed' if same_user else 'pending',
    )
    if vet and animal:
        evento = AgendaEvento(
            titulo=f"Exame de {animal.name}",
            inicio=scheduled_at,
            fim=scheduled_at + duration,
            responsavel_id=vet.user_id,
            clinica_id=animal.clinica_id,
        )
        db.session.add(evento)
        if not same_user:
            msg = Message(
                sender_id=current_user.id,
                receiver_id=vet.user_id,
                animal_id=animal_id,
                content=(
                    f"Exame agendado para {animal.name} em {scheduled_at_local.strftime('%d/%m/%Y %H:%M')}. "
                    f"Confirme até {appt.confirm_by.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime('%H:%M')}"
                ),
            )
            db.session.add(msg)
    db.session.add(appt)
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    confirm_by = None if same_user else appt.confirm_by.isoformat()
    return jsonify({'success': True, 'confirm_by': confirm_by, 'html': html})


@app.route('/exam_appointment/<int:appointment_id>/status', methods=['POST'])
@login_required
def update_exam_appointment_status(appointment_id):
    from models import ExamAppointment, Message
    appt = ExamAppointment.query.get_or_404(appointment_id)
    if current_user.id != appt.specialist.user_id and current_user.role != 'admin':
        abort(403)
    status = request.form.get('status') or (request.get_json(silent=True) or {}).get('status')
    if status not in {'confirmed', 'canceled'}:
        return jsonify({'success': False, 'message': 'Status inválido.'}), 400
    if status == 'confirmed' and datetime.utcnow() > appt.confirm_by:
        return jsonify({'success': False, 'message': 'Tempo de confirmação expirado.'}), 400
    appt.status = status
    if status == 'canceled':
        msg = Message(
            sender_id=current_user.id,
            receiver_id=appt.requester_id,
            animal_id=appt.animal_id,
            content=f"Especialista não aceitou exame para {appt.animal.name}. Reagende com outro profissional.",
        )
        db.session.add(msg)
    elif status == 'confirmed':
        scheduled_local = appt.scheduled_at.replace(tzinfo=timezone.utc).astimezone(BR_TZ)
        msg = Message(
            sender_id=current_user.id,
            receiver_id=appt.requester_id,
            animal_id=appt.animal_id,
            content=(
                f"Exame de {appt.animal.name} confirmado para "
                f"{scheduled_local.strftime('%d/%m/%Y %H:%M')} com {appt.specialist.user.name}."
            ),
        )
        db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/exam_appointment/<int:appointment_id>/update', methods=['POST'])
@login_required
def update_exam_appointment(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    data = request.get_json(silent=True) or {}
    date_str = data.get('date')
    time_str = data.get('time')
    specialist_id = data.get('specialist_id', appt.specialist_id)
    if not date_str or not time_str:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    scheduled_at_local = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    scheduled_at = (
        scheduled_at_local
        .replace(tzinfo=BR_TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    duration = get_appointment_duration('exame')
    if has_conflict_for_slot(
        specialist_id,
        scheduled_at_local,
        duration,
        exclude_exam_id=appointment_id,
    ):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
        }), 400
    appt.specialist_id = specialist_id
    appt.scheduled_at = scheduled_at
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=appt.animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    return jsonify({'success': True, 'html': html})


@app.route('/exam_appointment/<int:appointment_id>/requester_update', methods=['POST'])
@login_required
def update_exam_appointment_requester(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    if current_user.id != appt.requester_id and current_user.role != 'admin':
        abort(403)

    data = request.get_json(silent=True) or {}
    confirm_by_str = data.get('confirm_by')
    status = data.get('status')
    updated = False

    if appt.status == 'confirmed' and any(
        value is not None for value in (confirm_by_str, status)
    ):
        return jsonify({'success': False, 'message': 'Este exame já foi confirmado pelo especialista.'}), 400

    if confirm_by_str is not None:
        if not confirm_by_str:
            appt.confirm_by = None
            updated = True
        else:
            try:
                confirm_local = datetime.strptime(confirm_by_str, '%Y-%m-%dT%H:%M')
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Formato de data inválido.'}), 400
            confirm_utc = (
                confirm_local
                .replace(tzinfo=BR_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            if appt.confirm_by != confirm_utc:
                appt.confirm_by = confirm_utc
                updated = True

    if status is not None:
        normalized_status = str(status).strip().lower()
        allowed_statuses = {'pending', 'canceled'}
        if normalized_status not in allowed_statuses:
            return jsonify({'success': False, 'message': 'Status inválido.'}), 400
        if normalized_status != appt.status:
            appt.status = normalized_status
            updated = True

    if updated:
        db.session.commit()

    status_styles = {
        'pending': {
            'badge_class': 'bg-warning text-dark',
            'icon_class': 'text-warning',
            'status_label': 'Aguardando confirmação',
            'show_time_left': True,
        },
        'confirmed': {
            'badge_class': 'bg-success',
            'icon_class': 'text-success',
            'status_label': 'Confirmado',
            'show_time_left': False,
        },
        'canceled': {
            'badge_class': 'bg-secondary',
            'icon_class': 'text-secondary',
            'status_label': 'Cancelado',
            'show_time_left': False,
        },
    }

    style = status_styles.get(appt.status, status_styles['pending'])
    now = datetime.utcnow()
    time_left_seconds = None
    time_left_display = None
    if appt.confirm_by:
        time_left = appt.confirm_by - now
        time_left_seconds = time_left.total_seconds()
        if time_left_seconds > 0 and style.get('show_time_left'):
            time_left_display = format_timedelta(time_left)

    confirm_display = (
        appt.confirm_by.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')
        if appt.confirm_by
        else None
    )
    confirm_local_value = (
        appt.confirm_by.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime('%Y-%m-%dT%H:%M')
        if appt.confirm_by
        else None
    )

    return jsonify({
        'success': True,
        'updated': updated,
        'exam': {
            'id': appt.id,
            'status': appt.status,
            'status_label': style['status_label'],
            'badge_class': style['badge_class'],
            'icon_class': style['icon_class'],
            'confirm_by': appt.confirm_by.isoformat() if appt.confirm_by else None,
            'confirm_by_display': confirm_display,
            'confirm_by_value': confirm_local_value,
            'show_time_left': bool(style.get('show_time_left') and time_left_seconds and time_left_seconds > 0),
            'time_left_seconds': time_left_seconds,
            'time_left_display': time_left_display,
        },
    })


@app.route('/exam_appointment/<int:appointment_id>/delete', methods=['POST'])
@login_required
def delete_exam_appointment(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    animal_id = appt.animal_id
    db.session.delete(appt)
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    return jsonify({'success': True, 'html': html})


@app.route('/animal/<int:animal_id>/exam_appointments')
@login_required
def animal_exam_appointments(animal_id):
    from models import ExamAppointment
    appointments = (
        ExamAppointment.query.filter_by(animal_id=animal_id)
        .order_by(ExamAppointment.scheduled_at.desc())
        .all()
    )
    return render_template('partials/historico_exam_appointments.html', appointments=appointments)


@app.route('/servico', methods=['POST'])
@login_required
def criar_servico_clinica():
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem adicionar itens.'}), 403
    data = request.get_json(silent=True) or {}
    descricao = data.get('descricao')
    valor = data.get('valor')
    if not descricao or valor is None:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    clinica_id = None
    if getattr(current_user, 'veterinario', None):
        clinica_id = current_user.veterinario.clinica_id
    elif current_user.clinica_id:
        clinica_id = current_user.clinica_id
    servico = ServicoClinica(descricao=descricao, valor=valor, clinica_id=clinica_id)
    db.session.add(servico)
    db.session.commit()
    return jsonify({'id': servico.id, 'descricao': servico.descricao, 'valor': float(servico.valor)}), 201


@app.route('/imprimir_orcamento/<int:consulta_id>')
@login_required
def imprimir_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal = consulta.animal
    tutor = animal.owner
    veterinario = consulta.veterinario
    clinica = consulta.clinica or (
        veterinario.veterinario.clinica if veterinario and veterinario.veterinario else None
    )
    return render_template(
        'orcamentos/imprimir_orcamento.html',
        itens=consulta.orcamento_items,
        total=consulta.total_orcamento,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
    )


@app.route('/imprimir_bloco_orcamento/<int:bloco_id>')
@login_required
def imprimir_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else current_user
    clinica = consulta.clinica if consulta and consulta.clinica else bloco.clinica
    return render_template(
        'orcamentos/imprimir_orcamento.html',
        itens=bloco.itens,
        total=bloco.total,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
    )


@app.route('/orcamento/<int:orcamento_id>/imprimir')
@login_required
def imprimir_orcamento_padrao(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    ensure_clinic_access(orcamento.clinica_id)
    return render_template(
        'orcamentos/imprimir_orcamento_padrao.html',
        itens=orcamento.items,
        total=orcamento.total,
        clinica=orcamento.clinica,
        orcamento=orcamento,
        veterinario=current_user,
    )


@app.route('/pagar_bloco_orcamento/<int:bloco_id>')
@login_required
def pagar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if not bloco.itens:
        flash('Nenhum item no orçamento.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    items = [
        {
            'id': str(it.id),
            'title': it.descricao,
            'quantity': 1,
            'unit_price': float(it.valor),
        }
        for it in bloco.itens
    ]

    preference_data = {
        'items': items,
        'external_reference': f'bloco_orcamento-{bloco.id}',
        'notification_url': url_for('notificacoes_mercado_pago', _external=True),
        'statement_descriptor': current_app.config.get('MERCADOPAGO_STATEMENT_DESCRIPTOR'),
        'back_urls': {
            s: url_for('consulta_direct', animal_id=bloco.animal_id, _external=True)
            for s in ('success', 'failure', 'pending')
        },
        'auto_return': 'approved',
    }

    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception:
        current_app.logger.exception('Erro de conexão com Mercado Pago')
        flash('Falha ao conectar com Mercado Pago.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    if resp.get('status') != 201:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    pref = resp['response']
    return redirect(pref['init_point'])

@app.route('/consulta/<int:consulta_id>/pagar_orcamento')
@login_required
def pagar_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not consulta.orcamento_items:
        flash('Nenhum item no orçamento.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    items = [
        {
            'id': str(it.id),
            'title': it.descricao,
            'quantity': 1,
            'unit_price': float(it.valor),
        }
        for it in consulta.orcamento_items
    ]

    preference_data = {
        'items': items,
        'external_reference': f'consulta-{consulta.id}',
        'notification_url': url_for('notificacoes_mercado_pago', _external=True),
        'statement_descriptor': current_app.config.get('MERCADOPAGO_STATEMENT_DESCRIPTOR'),
        'back_urls': {
            s: url_for('consulta_direct', animal_id=consulta.animal_id, _external=True)
            for s in ('success', 'failure', 'pending')
        },
        'auto_return': 'approved',
    }

    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception:
        current_app.logger.exception('Erro de conexão com Mercado Pago')
        flash('Falha ao conectar com Mercado Pago.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    if resp.get('status') != 201:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    pref = resp['response']
    return redirect(pref['init_point'])


@app.route('/consulta/<int:consulta_id>/orcamento_item', methods=['POST'])
@login_required
def adicionar_orcamento_item(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem adicionar itens.'}), 403
    data = request.get_json(silent=True) or {}
    servico_id = data.get('servico_id')
    descricao = data.get('descricao')
    valor = data.get('valor')

    servico = None
    if servico_id:
        servico = ServicoClinica.query.get(servico_id)
        if not servico:
            return jsonify({'success': False, 'message': 'Item não encontrado.'}), 404
        descricao = servico.descricao
        if valor is None:
            valor = servico.valor

    if not descricao or valor is None:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    orcamento = None
    if consulta.clinica_id:
        orcamento = consulta.orcamento
        if not orcamento:
            desc = f"Orçamento da consulta {consulta.id} - {consulta.animal.name}"
            orcamento = Orcamento(
                clinica_id=consulta.clinica_id,
                consulta_id=consulta.id,
                descricao=desc,
            )
            db.session.add(orcamento)
            db.session.flush()

    item = OrcamentoItem(
        consulta_id=consulta.id,
        orcamento_id=orcamento.id if orcamento else None,
        descricao=descricao,
        valor=valor,
        servico_id=servico.id if servico else None,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'id': item.id, 'descricao': item.descricao, 'valor': float(item.valor), 'total': float(consulta.total_orcamento)}), 201


@app.route('/consulta/orcamento_item/<int:item_id>', methods=['DELETE'])
@login_required
def deletar_orcamento_item(item_id):
    item = OrcamentoItem.query.get_or_404(item_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem remover itens.'}), 403
    consulta = item.consulta
    ensure_clinic_access(consulta.clinica_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'total': float(consulta.total_orcamento)}), 200


@app.route('/consulta/<int:consulta_id>/bloco_orcamento', methods=['POST'])
@login_required
def salvar_bloco_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem salvar orçamento.'}), 403
    if not consulta.orcamento_items:
        return jsonify({'success': False, 'message': 'Nenhum item no orçamento.'}), 400
    bloco = BlocoOrcamento(animal_id=consulta.animal_id, clinica_id=consulta.clinica_id)
    db.session.add(bloco)
    db.session.flush()
    for item in list(consulta.orcamento_items):
        item.bloco_id = bloco.id
        item.consulta_id = None
        db.session.add(item)
    db.session.commit()
    historico_html = render_template('partials/historico_orcamentos.html', animal=consulta.animal)
    return jsonify({'success': True, 'html': historico_html})


@app.route('/bloco_orcamento/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem excluir.'}), 403
    animal_id = bloco.animal_id
    db.session.delete(bloco)
    db.session.commit()
    if request.accept_mimetypes.accept_json:
        historico_html = render_template('partials/historico_orcamentos.html', animal=Animal.query.get(animal_id))
        return jsonify({'success': True, 'html': historico_html})
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/bloco_orcamento/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403
    return render_template('orcamentos/editar_bloco_orcamento.html', bloco=bloco)


@app.route('/bloco_orcamento/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403

    data = request.get_json(silent=True) or {}
    itens = data.get('itens', [])

    for item in list(bloco.itens):
        db.session.delete(item)

    for it in itens:
        descricao = (it.get('descricao') or '').strip()
        valor = it.get('valor')
        if not descricao or valor is None:
            continue
        try:
            valor_decimal = Decimal(str(valor))
        except Exception:
            continue
        bloco.itens.append(OrcamentoItem(descricao=descricao, valor=valor_decimal))

    db.session.commit()

    historico_html = render_template('partials/historico_orcamentos.html', animal=bloco.animal)
    return jsonify(success=True, html=historico_html)


if __name__ == "__main__":
    # Usa a porta 8080 se existir no ambiente (como no Docker), senão usa 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
