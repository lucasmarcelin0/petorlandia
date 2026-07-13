from flask_admin import Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuLink
from flask import redirect, url_for, flash, current_app, request
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import (
    SelectField,
    DateField,
    FileField,
    DecimalField,
    SubmitField,
    StringField,
    PasswordField,
)
from markupsafe import Markup
import os
import uuid
from datetime import timedelta
from werkzeug.utils import secure_filename
from sqlalchemy import func
from decimal import Decimal
import re
from time_utils import now_in_brazil, coerce_to_brazil_tz
from security.crypto import MissingMasterKeyError, encrypt_text

USER_ROLE_CHOICES = [
    ('tutor', 'Tutor'),
    ('adotante', 'Adotante'),
    ('doador', 'Doador'),
    ('veterinario', 'Veterinário'),
    ('admin', 'Administrador'),
    ('vacinador', 'Vacinador PMO'),
    ('parceiro', 'Parceiro de cadastro'),
]

USER_WORKER_CHOICES = [
    ('', 'Sem perfil interno'),
    ('veterinario', 'Veterinário'),
    ('colaborador', 'Colaborador de clínica'),
    ('delivery', 'Entregador'),
    ('seguradora', 'Seguradora'),
    ('gestor', 'Gestor financeiro'),
    ('administrador', 'Administrador financeiro'),
    ('admin_clinica', 'Administrador de clínica'),
    ('master', 'Master'),
]

def _is_admin():
    """Return True if the current user has the admin role."""
    return current_user.is_authenticated and current_user.role == "admin"






# --------------------------------------------------------------------------
# Imports dos modelos
# --------------------------------------------------------------------------
try:
    from models import (
        Breed,
        Species,
        TipoRacao,
        ApresentacaoMedicamento,
        VacinaModelo,
        Consulta,
        Veterinario,
        Specialty,
        CasaDeRacao,
        CasaDeRacaoHorario,
        StorePaymentAccount,
        Clinica,
        ClinicHours,
        VetSchedule,
        ClinicStaff,
        Prescricao,
        Medicamento,
        db,
        User,
        Animal,
        Message,
        Transaction,
        Review,
        Favorite,
        AnimalPhoto,
        UserRole,
        ExameModelo,
        ProtocoloClinico,
        ProtocoloClinicoExame,
        ProtocoloClinicoMedicamento,
        ProtocoloClinicoRetorno,
        AuditoriaSugestaoClinica,
        Product,
        ProductCategory,
        Order,
        OrderItem,
        DeliveryRequest,
        AppointmentRequest,
        HealthPlan,
        HealthSubscription,
        PickupLocation,
        Endereco,
        Payment,
        PaymentMethod,
        PaymentStatus,
        VeterinarianMembership,
        VeterinarianSettings,
        clinica_has_column,
        get_clinica_field,
    )
except ImportError:
    from .models import (
        Breed,
        Species,
        TipoRacao,
        ApresentacaoMedicamento,
        VacinaModelo,
        Consulta,
        Veterinario,
        Specialty,
        CasaDeRacao,
        CasaDeRacaoHorario,
        StorePaymentAccount,
        Clinica,
        ClinicHours,
        VetSchedule,
        ClinicStaff,
        Prescricao,
        Medicamento,
        db,
        User,
        Animal,
        Message,
        Transaction,
        Review,
        Favorite,
        AnimalPhoto,
        UserRole,
        ExameModelo,
        ProtocoloClinico,
        ProtocoloClinicoExame,
        ProtocoloClinicoMedicamento,
        ProtocoloClinicoRetorno,
        AuditoriaSugestaoClinica,
        Product,
        ProductCategory,
        Order,
        OrderItem,
        DeliveryRequest,
        AppointmentRequest,
        HealthPlan,
        HealthSubscription,
        PickupLocation,
        Endereco,
        Payment,
        PaymentMethod,
        PaymentStatus,
        VeterinarianMembership,
        VeterinarianSettings,
        clinica_has_column,
        get_clinica_field,
    )














# --------------------------------------------------------------------------
# Configurações gerais
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Base para todas as views protegidas
# --------------------------------------------------------------------------
class MyModelView(ModelView):
    # Ordena objetos mais recentes primeiro por padrão
    column_default_sort = ('id', True)

    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login_view'))

# --------------------------------------------------------------------------
# Dashboard (será a página inicial do painel)
# --------------------------------------------------------------------------
class AdminDashboard(BaseView):
    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login_view'))

    @expose('/')
    @login_required
    def index(self):
        agora = now_in_brazil()

        def _coerce(dt):
            try:
                return coerce_to_brazil_tz(dt) if dt else None
            except Exception:
                return None

        # ── Crescimento de usuários (últimas 8 semanas) ──────────────────
        inicio_janela = agora - timedelta(weeks=8)
        datas_cadastro = [
            _coerce(c)
            for (c,) in db.session.query(User.created_at)
            .filter(User.created_at.isnot(None))
            .all()
        ]
        datas_cadastro = [c for c in datas_cadastro if c]

        semana_labels, semana_counts = [], []
        for i in range(8):
            inicio = inicio_janela + timedelta(weeks=i)
            fim = inicio + timedelta(weeks=1)
            semana_labels.append(inicio.strftime('%d/%m'))
            semana_counts.append(sum(1 for c in datas_cadastro if inicio <= c < fim))

        d7 = agora - timedelta(days=7)
        d30 = agora - timedelta(days=30)
        novos_usuarios_7d = sum(1 for c in datas_cadastro if c >= d7)
        novos_usuarios_30d = sum(1 for c in datas_cadastro if c >= d30)

        logins_7d = sum(
            1
            for (l,) in db.session.query(User.last_login).filter(User.last_login.isnot(None)).all()
            if (_coerce(l) or inicio_janela) >= d7
        )

        # ── Atividade recente (solicitações e cadastros) ─────────────────
        atividades = []

        def _add(quando, icone, cor, texto, url=None):
            quando = _coerce(quando)
            if quando:
                atividades.append(
                    {'quando': quando, 'icone': icone, 'cor': cor, 'texto': texto, 'url': url}
                )

        for u in (
            User.query.filter(User.created_at.isnot(None))
            .order_by(User.created_at.desc())
            .limit(10)
        ):
            _add(u.created_at, 'bi-person-plus-fill', 'primary',
                 f'Novo usuário: {u.name}', url_for('user.index_view'))

        for o in Order.query.order_by(Order.created_at.desc()).limit(10):
            nome = o.user.name if o.user else 'Usuário removido'
            _add(o.created_at, 'bi-cart-fill', 'success',
                 f'Pedido #{o.id} — {nome} (R$ {o.total_value():.2f})',
                 url_for('order.index_view'))

        for dr in DeliveryRequest.query.order_by(DeliveryRequest.requested_at.desc()).limit(10):
            solicitante = dr.requested_by.name if dr.requested_by else '—'
            _add(dr.requested_at, 'bi-truck', 'warning',
                 f'Entrega do pedido #{dr.order_id} ({dr.status}) — {solicitante}',
                 url_for('deliveryrequest.index_view'))

        for ar in AppointmentRequest.query.order_by(AppointmentRequest.created_at.desc()).limit(10):
            _add(ar.created_at, 'bi-calendar-plus', 'info',
                 f'Solicitação de {ar.kind_label.lower()} — {ar.tutor.name} '
                 f'para {ar.animal.name} ({ar.status_display.lower()})')

        atividades.sort(key=lambda a: a['quando'], reverse=True)
        atividades = atividades[:15]

        # ── Pendências de parcerias (cadastros aguardando aprovação) ─────
        from models import CareerApplication

        try:
            clinicas_pendentes = Clinica.query.filter_by(status='pendente').count()
        except Exception:
            db.session.rollback()
            clinicas_pendentes = 0
        try:
            casas_pendentes = CasaDeRacao.query.filter_by(status='pendente').count()
        except Exception:
            db.session.rollback()
            casas_pendentes = 0
        try:
            candidaturas_pendentes = CareerApplication.query.filter_by(status='pendente').count()
        except Exception:
            db.session.rollback()
            candidaturas_pendentes = 0

        # ── Métricas de negócio (tração para investidores) ───────────────
        from models import VaccineServiceRequest

        vets_pagantes = (
            VeterinarianMembership.query
            .filter(VeterinarianMembership.paid_until.isnot(None),
                    VeterinarianMembership.paid_until >= agora)
            .count()
        )
        gmv_loja = (
            db.session.query(func.sum(Payment.amount))
            .filter(Payment.status == PaymentStatus.COMPLETED,
                    Payment.order_id.isnot(None))
            .scalar() or 0
        )
        pedidos_vacina_30d = (
            VaccineServiceRequest.query
            .filter(VaccineServiceRequest.created_at >= d30)
            .count()
        )
        # Tutores ativos = logaram nos últimos 30 dias e não são equipe
        # (vet/entregador/colaborador etc.) nem admin.
        tutores_ativos_30d = (
            User.query
            .filter(User.last_login.isnot(None), User.last_login >= d30)
            .filter(db.or_(User.worker.is_(None), User.worker == ''))
            .filter(db.func.lower(func.coalesce(User.role, '')) != 'admin')
            .count()
        )

        return self.render(
            'admin/home_admin.html',
            clinicas_pendentes=clinicas_pendentes,
            casas_pendentes=casas_pendentes,
            candidaturas_pendentes=candidaturas_pendentes,
            parcerias_pendentes=clinicas_pendentes + casas_pendentes + candidaturas_pendentes,
            vets_pagantes=vets_pagantes,
            gmv_loja=gmv_loja,
            pedidos_vacina_30d=pedidos_vacina_30d,
            tutores_ativos_30d=tutores_ativos_30d,
            total_users=User.query.count(),
            total_animals=Animal.query.count(),
            total_consultas=Consulta.query.count(),
            total_orders = Order.query.count(),
            completed_orders = Order.query.join(DeliveryRequest).filter(DeliveryRequest.status == 'concluida').count(),
            pending_deliveries = DeliveryRequest.query.filter_by(status='pendente').count(),
            total_products = Product.query.count(),
            low_stock_products = Product.query.filter(Product.stock < 5).count(),
            total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status == PaymentStatus.COMPLETED).scalar() or 0,
            pending_payments = Payment.query.filter_by(status=PaymentStatus.PENDING).count(),
            active_health_plans = HealthSubscription.query.filter_by(active=True).count(),
            novos_usuarios_7d=novos_usuarios_7d,
            novos_usuarios_30d=novos_usuarios_30d,
            logins_7d=logins_7d,
            semana_labels=semana_labels,
            semana_counts=semana_counts,
            atividades=atividades,
            pending_requests=AppointmentRequest.query.filter_by(status='pending').count(),
            agora=agora,
        )

# --------------------------------------------------------------------------
# Views específicas
# --------------------------------------------------------------------------

from wtforms import validators


class VeterinarianSettingsForm(FlaskForm):
    membership_price = DecimalField(
        'Valor da assinatura (R$)',
        places=2,
        rounding=None,
        validators=[
            validators.DataRequired(message='Informe o valor da assinatura.'),
            validators.NumberRange(min=Decimal('0.01'), message='O valor deve ser maior que zero.'),
        ],
        render_kw={'min': '0', 'step': '0.01'},
    )
    submit = SubmitField('Salvar alterações')


def _normalize_municipio(municipio: str) -> str:
    normalized = (municipio or "").strip().lower().replace("-", " ")
    normalized = normalized.replace("á", "a").replace("â", "a").replace("ã", "a")
    normalized = normalized.replace("é", "e").replace("ê", "e")
    normalized = normalized.replace("í", "i")
    normalized = normalized.replace("ó", "o").replace("ô", "o")
    normalized = normalized.replace("ú", "u")
    normalized = " ".join(normalized.split())
    if normalized in {"bh", "belo horizonte", "belo horizonte mg", "belo horizonte/mg"}:
        return "belo_horizonte"
    if normalized in {"contagem", "contagem mg", "contagem/mg"}:
        return "contagem"
    if normalized in {"orlandia", "orlandia sp", "orlandia/sp"}:
        return "orlandia"
    return normalized.replace(" ", "_")


class ContabilidadeConfigForm(FlaskForm):
    clinica_id = SelectField(
        "Clínica",
        coerce=int,
        validators=[validators.DataRequired(message="Selecione uma clínica.")],
    )
    municipio_nfse = SelectField(
        "Município (NFS-e)",
        choices=[
            ("", "Selecione um município"),
            ("orlandia", "Orlândia (SP)"),
            ("belo_horizonte", "Belo Horizonte (MG)"),
            ("contagem", "Contagem (MG)"),
        ],
        validators=[validators.DataRequired(message="Informe o município da NFS-e.")],
    )
    inscricao_municipal = StringField("Inscrição municipal")
    inscricao_estadual = StringField("Inscrição estadual")
    regime_tributario = SelectField(
        "Regime tributário",
        choices=[
            ("", "Selecione o regime"),
            ("simples_nacional", "Simples Nacional"),
            ("lucro_presumido", "Lucro Presumido"),
            ("lucro_real", "Lucro Real"),
        ],
    )
    cnae = StringField("CNAE")
    codigo_servico = StringField("Código de serviço")
    aliquota_iss = DecimalField(
        "Alíquota ISS (%)",
        places=2,
        validators=[validators.Optional(), validators.NumberRange(min=0)],
    )
    aliquota_pis = DecimalField(
        "Alíquota PIS (%)",
        places=2,
        validators=[validators.Optional(), validators.NumberRange(min=0)],
    )
    aliquota_cofins = DecimalField(
        "Alíquota COFINS (%)",
        places=2,
        validators=[validators.Optional(), validators.NumberRange(min=0)],
    )
    aliquota_csll = DecimalField(
        "Alíquota CSLL (%)",
        places=2,
        validators=[validators.Optional(), validators.NumberRange(min=0)],
    )
    aliquota_ir = DecimalField(
        "Alíquota IR (%)",
        places=2,
        validators=[validators.Optional(), validators.NumberRange(min=0)],
    )
    nfse_username = StringField("Usuário NFS-e")
    nfse_password = PasswordField("Senha NFS-e")
    nfse_cert_path = StringField("Caminho do certificado")
    nfse_cert_password = PasswordField("Senha do certificado")
    nfse_token = StringField("Token/Chave NFS-e")
    submit = SubmitField("Salvar configurações")

    def __init__(self, *args, **kwargs):
        self.existing_values = kwargs.pop("existing_values", {})
        super().__init__(*args, **kwargs)

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators)
        if not is_valid:
            return False

        municipio_key = _normalize_municipio(self.municipio_nfse.data)
        rules = {
            "orlandia": {
                "label": "Orlândia (SP)",
                "required": [
                    "inscricao_municipal",
                    "regime_tributario",
                    "cnae",
                    "codigo_servico",
                    "aliquota_iss",
                    "nfse_username",
                    "nfse_password",
                ],
                "formats": {
                    "inscricao_municipal": r"^\d{1,12}$",
                    "cnae": r"^(\d{7}|\d{4}-?\d/\d{2})$",
                    "codigo_servico": r"^\d{3,6}$",
                },
            },
            "belo_horizonte": {
                "label": "Belo Horizonte (MG)",
                "required": [
                    "inscricao_municipal",
                    "cnae",
                    "codigo_servico",
                    "nfse_cert_path",
                    "nfse_cert_password",
                ],
                "formats": {
                    "inscricao_municipal": r"^\d{1,15}$",
                    "cnae": r"^(\d{7}|\d{4}-?\d/\d{2})$",
                    "codigo_servico": r"^\d{4,6}$",
                },
            },
            "contagem": {
                "label": "Contagem (MG)",
                "required": [
                    "regime_tributario",
                    "cnae",
                    "codigo_servico",
                ],
                "formats": {
                    "cnae": r"^(\d{7}|\d{4}-?\d/\d{2})$",
                    "codigo_servico": r"^\d{4,6}$",
                },
            },
        }

        rule = rules.get(municipio_key)
        if not rule:
            return True

        ok = True
        for field_name in rule["required"]:
            field = getattr(self, field_name)
            if field.data in (None, "", []) and not self.existing_values.get(field_name):
                field.errors.append(f"Campo obrigatório para {rule['label']}.")
                ok = False

        for field_name, pattern in rule.get("formats", {}).items():
            field = getattr(self, field_name)
            if field.data:
                value = str(field.data).strip()
                if not re.fullmatch(pattern, value):
                    field.errors.append(f"Formato inválido para {rule['label']}.")
                    ok = False

        return ok


NFSE_FIELD_NAMES = [
    "municipio_nfse",
    "inscricao_municipal",
    "inscricao_estadual",
    "regime_tributario",
    "cnae",
    "codigo_servico",
    "aliquota_iss",
    "aliquota_pis",
    "aliquota_cofins",
    "aliquota_csll",
    "aliquota_ir",
    "nfse_username",
    "nfse_password",
    "nfse_cert_path",
    "nfse_cert_password",
    "nfse_token",
]

# ─── Subform de Endereco ----------------------------------------------------
class EnderecoInlineForm(ModelView):
    form_columns = ("rua", "numero", "bairro", "cidade", "estado", "cep")
    can_delete   = False
    can_view_details = False
    can_export   = False

# ─── View de PickupLocation -------------------------------------------------
class PickupLocationView(ModelView):
    column_list   = ("id", "nome", "endereco.full", "ativo")
    column_labels = {"endereco.full": "Endereço"}

    form_columns  = ("nome", "ativo", "endereco")



    column_searchable_list = ("nome", "endereco.rua", "endereco.cidade")
    column_filters = ("ativo",)

    form_args = {
        "nome": dict(validators=[validators.DataRequired(), validators.Length(max=120)])
    }

    def is_accessible(self):
        return current_user.is_authenticated and _is_admin()
















class UserAdminView(MyModelView):
    form_extra_fields = {
        'profile_photo_upload': FileField('Foto de perfil')
    }

    column_list = (
        'profile_photo', 'name', 'email', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth',
        'phone', 'address', 'clinica', 'added_by', 'created_at'
    )

    column_labels = {'added_by': 'Adicionado por', 'created_at': 'Registrado em'}

    column_searchable_list = ('name', 'email')
    column_filters = ('role', 'created_at', 'clinica')
    column_sortable_list = ('name', 'email', 'created_at')

    column_default_sort = ('created_at', True)

    column_formatters = {
        'name': lambda v, c, m, p: Markup(
            f'<a href="{url_for("ficha_tutor", tutor_id=m.id)}">{m.name}</a>'
        ),
        'phone': lambda v, c, m, p: Markup(
            f'<a href="https://wa.me/55{re.sub("[^0-9]", "", m.phone)}" target="_blank">{m.phone}</a>'
        ) if m.phone else '—',
        'profile_photo': lambda v, c, m, p: Markup(
            f'<img src="{m.profile_photo}" width="100">'
        ) if m.profile_photo else '',
        'added_by': lambda v, c, m, p: m.added_by.name if m.added_by else '—'
    }

    form_overrides = {'role': SelectField, 'worker': SelectField, 'date_of_birth': DateField}
    form_args = {
        'role': {'choices': USER_ROLE_CHOICES},
        'worker': {'choices': USER_WORKER_CHOICES},
    }
    form_columns = (
        'name', 'email', 'password_hash', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth', 'phone', 'address', 'clinica', 'profile_photo_upload'
    )
    column_details_list = column_list

    def on_model_change(self, form, model, is_created):
        model.worker = (model.worker or '').strip() or None
        if form.profile_photo_upload.data:
            file = form.profile_photo_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="profile_photos")
            if image_url:
                model.profile_photo = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.profile_photo:
            form.profile_photo_upload.description = Markup(
                f'<img src="{obj.profile_photo}" alt="Foto atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )




class EnderecoAdmin(MyModelView):
    column_list = ['cep', 'rua', 'numero', 'bairro', 'cidade', 'estado']
    column_searchable_list = ['cep', 'rua', 'bairro', 'cidade']
    column_filters = ['cidade', 'estado']
    form_columns = ['cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado']
    column_labels = {
        'cep': 'CEP',
        'rua': 'Rua',
        'numero': 'Número',
        'complemento': 'Complemento',
        'bairro': 'Bairro',
        'cidade': 'Cidade',
        'estado': 'UF'
    }


class VeterinarioAdmin(MyModelView):
    form_columns = ['user', 'crmv', 'clinica', 'specialties']
    column_list = ['id', 'user', 'crmv', 'clinica', 'specialty_list']
    column_labels = {'specialty_list': 'Especialidades'}


class VeterinarianMembershipAdmin(MyModelView):
    column_list = (
        'veterinario',
        'status_label',
        'started_at',
        'trial_ends_at',
        'paid_until',
        'last_payment_status',
        'last_payment_amount',
    )

    column_labels = {
        'veterinario': 'Veterinário',
        'status_label': 'Status',
        'started_at': 'Início',
        'trial_ends_at': 'Fim do Teste',
        'paid_until': 'Pago Até',
        'last_payment_status': 'Status do Pagamento',
        'last_payment_amount': 'Valor do Pagamento',
    }

    column_filters = (
        'is_active_flag',
        'trial_ends_at',
        'paid_until',
        'last_payment.status',
        'last_payment.amount',
    )

    column_searchable_list = (
        'veterinario.user.name',
        'veterinario.crmv',
    )

    column_formatters = {
        'status_label': lambda v, c, m, p: Markup(
            '<span class="badge bg-{color}">{label}</span>'.format(
                color='success' if m.is_active() else 'secondary',
                label=m.status_label,
            )
        ),
        'last_payment_status': lambda v, c, m, p: (
            m.last_payment_status or '—'
        ),
        'last_payment_amount': lambda v, c, m, p: (
            f"R$ {m.last_payment_amount:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
            if m.last_payment_amount is not None else '—'
        ),
    }

    column_default_sort = ('started_at', True)

    form_columns = (
        'veterinario',
        'started_at',
        'trial_ends_at',
        'paid_until',
        'last_payment',
    )


class VeterinarianSettingsView(BaseView):
    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login_view'))

    @expose('/', methods=['GET', 'POST'])
    @login_required
    def index(self):
        settings = VeterinarianSettings.load()
        form = VeterinarianSettingsForm(obj=settings)

        if not form.is_submitted():
            if settings and settings.membership_price is not None:
                form.membership_price.data = Decimal(settings.membership_price)
            else:
                default_price = Decimal(
                    str(current_app.config.get('VETERINARIAN_MEMBERSHIP_PRICE', 60.00))
                )
                form.membership_price.data = default_price

        if form.validate_on_submit():
            price = form.membership_price.data
            if price is not None:
                price = price.quantize(Decimal('0.01'))

            if settings is None:
                settings = VeterinarianSettings(membership_price=price)
            else:
                settings.membership_price = price

            db.session.add(settings)

            try:
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                current_app.logger.exception('Erro ao salvar configuração de assinatura de veterinário')
                flash('Não foi possível salvar as configurações. Tente novamente.', 'danger')
            else:
                flash('Valor da assinatura atualizado com sucesso.', 'success')
                return redirect(self.get_url('.index'))

        return self.render('admin/veterinarian_settings.html', form=form, settings=settings)


class ClinicaAdmin(MyModelView):
    form_extra_fields = {
        'logotipo_upload': FileField('Logotipo')
    }

    form_ajax_refs = {
        'owner': {
            'fields': ('name', 'email')
        }
    }

    form_columns = [
        'nome', 'cnpj', 'endereco', 'telefone', 'email', 'logotipo_upload', 'owner'
    ]

    column_list = ['nome', 'cnpj', 'logotipo', 'owner']

    column_formatters = {
        'logotipo': lambda v, c, m, p: Markup(
            f'<img src="{m.logotipo}" width="100">'
        ) if m.logotipo else ''
    }

    def on_model_change(self, form, model, is_created):
        file = form.logotipo_upload.data
        if file and getattr(file, "filename", ""):
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="clinicas")
            if image_url:
                model.logotipo = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.logotipo:
            form.logotipo_upload.description = Markup(
                f'<img src="{obj.logotipo}" alt="Logotipo atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )


class ContabilidadeConfigView(BaseView):
    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login_view'))

    @expose('/', methods=['GET', 'POST'])
    @login_required
    def index(self):
        form = ContabilidadeConfigForm()
        clinics = Clinica.query.order_by(Clinica.nome).all()
        form.clinica_id.choices = [(clinic.id, clinic.nome) for clinic in clinics]
        selected_id = request.args.get("clinica_id", type=int)
        if not selected_id and form.clinica_id.data:
            selected_id = form.clinica_id.data
        if not selected_id and clinics:
            selected_id = clinics[0].id

        clinic = Clinica.query.get(selected_id) if selected_id else None
        if clinic:
            form.existing_values = {
                "nfse_password": get_clinica_field(clinic, "nfse_password"),
                "nfse_cert_password": get_clinica_field(clinic, "nfse_cert_password"),
            }

        if request.method == 'GET' and clinic:
            clinic_values = {
                name: get_clinica_field(clinic, name) for name in NFSE_FIELD_NAMES
            }
            form.process(data=clinic_values)
            form.clinica_id.data = clinic.id
            form.municipio_nfse.data = clinic_values.get("municipio_nfse") or ""
            form.nfse_password.data = ""
            form.nfse_cert_password.data = ""

        if form.validate_on_submit():
            clinic = Clinica.query.get(form.clinica_id.data)
            if not clinic:
                flash("Clínica não encontrada.", "danger")
                return redirect(self.get_url('.index'))

            password_fields = {"nfse_password", "nfse_cert_password"}
            sensitive_fields = {
                "nfse_username",
                "nfse_password",
                "nfse_cert_path",
                "nfse_cert_password",
                "nfse_token",
            }
            for name in NFSE_FIELD_NAMES:
                if not clinica_has_column(name):
                    continue
                value = getattr(form, name).data
                if name in password_fields and not value:
                    continue
                if isinstance(value, str) and not value:
                    value = None
                if value is not None and name in sensitive_fields:
                    try:
                        value = encrypt_text(value)
                    except MissingMasterKeyError:
                        flash(
                            "Chave fiscal não configurada. Configure FISCAL_MASTER_KEY antes de salvar.",
                            "danger",
                        )
                        return redirect(self.get_url('.index', clinica_id=clinic.id))
                setattr(clinic, name, value)

            db.session.add(clinic)
            try:
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                current_app.logger.exception("Erro ao salvar configurações contábeis")
                flash("Não foi possível salvar as configurações. Tente novamente.", "danger")
            else:
                flash("Configurações contábeis atualizadas com sucesso.", "success")
                return redirect(self.get_url('.index', clinica_id=clinic.id))

        return self.render(
            "admin/contabilidade_config.html",
            form=form,
            clinic=clinic,
            clinics=clinics,
        )


class ClinicHoursAdmin(MyModelView):
    column_list = ['clinica', 'dia_semana', 'hora_abertura', 'hora_fechamento']
    form_columns = ['clinica', 'dia_semana', 'hora_abertura', 'hora_fechamento']


class VetScheduleAdmin(MyModelView):
    column_list = [
        'veterinario',
        'dia_semana',
        'hora_inicio',
        'hora_fim',
        'intervalo_inicio',
        'intervalo_fim',
    ]
    form_columns = [
        'veterinario',
        'dia_semana',
        'hora_inicio',
        'hora_fim',
        'intervalo_inicio',
        'intervalo_fim',
    ]


class ClinicStaffAdmin(MyModelView):
    column_list = (
        'clinic',
        'user',
        'can_manage_clients',
        'can_manage_animals',
        'can_manage_staff',
        'can_manage_schedule',
        'can_manage_inventory',
    )
    form_columns = column_list
    column_labels = {
        'clinic': 'Clínica',
        'user': 'Usuário',
        'can_manage_clients': 'Clientes',
        'can_manage_animals': 'Animais',
        'can_manage_staff': 'Equipe',
        'can_manage_schedule': 'Agenda',
        'can_manage_inventory': 'Estoque',
    }


class TutorAdminView(MyModelView):
    """Exemplo de deleção em cascata (caso use tutores)."""
    def on_model_delete(self, model):
        for animal in model.animais:
            for consulta in animal.consultas:
                db.session.delete(consulta)
            db.session.delete(animal)


from flask import url_for

class AnimalAdminView(MyModelView):
    form_extra_fields = {
        'image_upload': FileField('Imagem'),
        'modo': SelectField(
            'Modo',
            choices=[
                ('', 'Não disponível'),
                ('venda', 'Venda'),
                ('doação', 'Adoção'),
                ('doacao', 'Adoção (sem acento)'),
                ('adotado', 'Adotado'),
                ('perdido', 'Perdido'),
            ],
            description='Valores "adotado" e "perdido" são tratados como não disponível.'
        ),
    }

    column_list = (
        'image', 'name', 'species.name', 'breed.name', 'age', 'peso',
        'date_of_birth', 'sex', 'status', 'modo', 'price', 'clinica',
        'date_added', 'added_by'
    )

    column_labels = {
        'name': 'Nome',
        'species.name': 'Espécie',
        'breed.name': 'Raça',
        'date_of_birth': 'Nascimento',
        'peso': 'Peso (kg)',
        'added_by': 'Criado por',
        'date_added': 'Registrado em',
        'modo': 'Modo',
        'price': 'Preço (R$)'
    }

    form_columns = (
        'name', 'species', 'breed', 'age', 'peso', 'date_of_birth',
        'sex', 'status', 'modo', 'price', 'clinica', 'added_by',
        'image_upload'
    )

    def on_model_change(self, form, model, is_created):
        if form.image_upload.data:
            file = form.image_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="animals")
            if image_url:
                model.image = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.image:
            form.image_upload.description = Markup(
                f'<img src="{obj.image}" alt="Imagem atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )


    column_formatters = {
        'image': lambda v, c, m, p: Markup(
            f'<img src="{m.image}" width="100">'
        ) if m.image else '',
        'name': lambda v, c, m, p: Markup(
            f'<a href="{url_for("consulta_direct", animal_id=m.id)}" target="_blank">{m.name}</a>'
        ),
        'status': lambda v, c, m, p: Markup(
            f'<span class="badge bg-{"success" if m.status == "disponível" else "secondary"}">{m.status}</span>'
        ),
        'added_by': lambda v, c, m, p: m.added_by.name if m.added_by else '—',
        'modo': lambda v, c, m, p: Markup(
            '<span class="badge bg-{}">{}</span>'.format(
                'success' if m.modo == 'venda' else 'info' if m.modo in ('doação', 'doacao') else 'secondary',
                'Venda' if m.modo == 'venda' else 'Adoção' if m.modo in ('doação', 'doacao') else 'Não disponível'
            )
        )
    }

    # 🔧 Atualizado para apontar para atributos relacionados
    column_searchable_list = ('name', 'breed.name', 'species.name')
    column_filters = (
        'species.name', 'breed.name', 'sex', 'status', 'modo', 'clinica',
        'date_added'
    )

    column_sortable_list = ('name', 'date_added')
    column_default_sort = ('date_added', True)


class SpeciesAdminView(MyModelView):
    form_excluded_columns = ['breeds']
    column_labels = {'name': 'Espécie'}
    column_searchable_list = ['name']
    column_default_sort = ('name', True)


class BreedAdminView(MyModelView):
    form_excluded_columns = ['animals']
    column_labels = {
        'name': 'Raça',
        'species': 'Espécie'
    }
    column_searchable_list = ['name']
    column_filters = ['species']
    column_default_sort = ('name', True)



class ProductCategoryAdmin(MyModelView):
    """Gerencia as categorias da Loja (filtros/chips). Adicione conforme a necessidade."""
    column_list = ['label', 'slug', 'icon', 'position', 'active']
    form_columns = ['label', 'slug', 'icon', 'position', 'active']
    column_default_sort = ('position', False)
    column_editable_list = ['label', 'position', 'active']
    column_labels = {
        'label': 'Nome',
        'slug': 'Identificador',
        'icon': 'Ícone (Font Awesome)',
        'position': 'Ordem',
        'active': 'Ativa',
    }
    form_args = {
        'slug': {'description': 'Sem espaços/acentos (ex.: racao, brinquedo). Não altere depois de criada — produtos guardam este valor.'},
        'icon': {'description': 'Classe Font Awesome (ex.: fa-bone, fa-pills, fa-tag).'},
        'position': {'description': 'Ordem de exibição dos chips (menor primeiro).'},
    }


class ProductAdmin(MyModelView):
    form_extra_fields = {
        'image_upload': FileField('Imagem')
    }

    form_columns = [
        'name',
        'description',
        'price',
        'stock',
        'status',
        'clinica',
        'casa_de_racao',
        'mp_category_id',
        'image_upload',
    ]

    column_list = ['image_url', 'name', 'price', 'stock', 'status', 'seller']
    column_searchable_list = ('name', 'casa_de_racao.nome', 'clinica.nome')
    column_filters = ('status', 'clinica', 'casa_de_racao')
    column_sortable_list = ('name', 'price', 'stock', 'status', 'id')
    column_labels = {
        'image_url': 'Imagem',
        'name': 'Produto',
        'price': 'Preco',
        'stock': 'Estoque',
        'status': 'Status',
        'seller': 'Vendedor',
        'casa_de_racao': 'Casa de racao',
        'clinica': 'Clinica',
    }
    column_formatters = {
        'image_url': lambda v, c, m, p: Markup(
            f'<img src="{m.image_url}" width="100">'
        ) if m.image_url else '',
        'seller': lambda v, c, m, p: (
            m.casa_de_racao.nome if m.casa_de_racao else
            m.clinica.nome if m.clinica else
            'Sem vendedor'
        ),
    }

    def on_model_change(self, form, model, is_created):
        if form.image_upload.data:
            file = form.image_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="products")
            model.image_url = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.image_url:
            form.image_upload.description = Markup(
                f'<img src="{obj.image_url}" alt="Imagem atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )

    def on_model_delete(self, model):
        """Remover itens de pedido antes de excluir o produto."""
        for item in list(model.order_items):
            db.session.delete(item)


class CasaDeRacaoAdminView(MyModelView):
    form_extra_fields = {
        'logotipo_upload': FileField('Logotipo')
    }

    column_list = (
        'nome',
        'razao_social',
        'cnpj',
        'status',
        'owner',
        'telefone',
        'email',
        'modo_entrega',
        'created_at',
    )
    column_searchable_list = ('nome', 'razao_social', 'cnpj', 'email', 'telefone', 'owner.name')
    column_filters = ('status', 'modo_entrega', 'created_at')
    column_sortable_list = ('nome', 'razao_social', 'cnpj', 'status', 'created_at')
    column_default_sort = ('created_at', True)
    form_columns = (
        'nome',
        'razao_social',
        'cnpj',
        'descricao',
        'telefone',
        'email',
        'endereco',
        'status',
        'modo_entrega',
        'valor_frete',
        'pedido_minimo_entrega',
        'prazo_entrega_min',
        'prazo_entrega_max',
        'owner',
        'logotipo_upload',
        'photo_rotation',
        'photo_zoom',
        'photo_offset_x',
        'photo_offset_y',
    )
    column_labels = {
        'nome': 'Nome fantasia',
        'razao_social': 'Razao social',
        'cnpj': 'CNPJ',
        'status': 'Status',
        'owner': 'Responsavel',
        'telefone': 'Telefone',
        'email': 'E-mail',
        'endereco': 'Endereco',
        'modo_entrega': 'Modo de entrega',
        'valor_frete': 'Frete',
        'pedido_minimo_entrega': 'Pedido minimo',
        'prazo_entrega_min': 'Prazo min',
        'prazo_entrega_max': 'Prazo max',
        'created_at': 'Criada em',
    }
    column_formatters = {
        'status': lambda v, c, m, p: Markup(
            '<span class="badge bg-{color}">{label}</span>'.format(
                color='success' if m.status == 'ativa' else 'warning' if m.status == 'pendente' else 'secondary',
                label=m.status,
            )
        ),
        'owner': lambda v, c, m, p: Markup(
            f'<a href="{url_for("user.edit_view", id=m.owner.id)}">{m.owner.name}</a>'
        ) if m.owner else 'Sem responsavel',
    }
    form_overrides = {
        'status': SelectField,
        'modo_entrega': SelectField,
    }
    form_args = {
        'status': {
            'choices': [
                ('pendente', 'Pendente'),
                ('ativa', 'Ativa'),
                ('suspensa', 'Suspensa'),
            ]
        },
        'modo_entrega': {
            'choices': [
                ('plataforma', 'Entregadores da plataforma'),
                ('propria', 'Entrega propria'),
            ]
        },
    }

    def on_model_change(self, form, model, is_created):
        if form.logotipo_upload.data:
            file = form.logotipo_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="casas_de_racao")
            if image_url:
                model.logotipo = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.logotipo:
            form.logotipo_upload.description = Markup(
                f'<img src="{obj.logotipo}" alt="Logotipo atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )


class CasaDeRacaoHorarioAdminView(MyModelView):
    column_list = ('casa_de_racao', 'dia_semana', 'hora_abertura', 'hora_fechamento')
    column_filters = ('casa_de_racao', 'dia_semana')
    form_columns = column_list
    column_labels = {
        'casa_de_racao': 'Casa de racao',
        'dia_semana': 'Dia da semana',
        'hora_abertura': 'Abertura',
        'hora_fechamento': 'Fechamento',
    }


class StorePaymentAccountAdminView(MyModelView):
    can_create = False
    column_list = (
        'casa_de_racao',
        'clinica',
        'provider',
        'provider_user_id',
        'status',
        'connected_at',
        'last_refreshed_at',
        'error_message',
    )
    column_searchable_list = ('provider_user_id', 'casa_de_racao.nome', 'clinica.nome')
    column_filters = ('provider', 'status', 'connected_at', 'last_refreshed_at')
    form_columns = ('status', 'error_message')
    column_labels = {
        'casa_de_racao': 'Casa de racao',
        'clinica': 'Clinica',
        'provider': 'Provedor',
        'provider_user_id': 'ID do provedor',
        'status': 'Status',
        'connected_at': 'Conectado em',
        'last_refreshed_at': 'Atualizado em',
        'error_message': 'Erro',
    }



# --------------------------------------------------------------------------
# Exame Modelo Admin
# --------------------------------------------------------------------------
class ExameModeloAdminView(MyModelView):
    column_searchable_list = ('nome', 'justificativa')
    form_columns = ('nome', 'justificativa')


class ProtocoloClinicoAdminView(MyModelView):
    column_list = (
        'nome',
        'suspeita_principal',
        'especie',
        'clinica',
        'ativo',
        'prioridade',
        'versao',
        'taxa_aceitacao',
    )
    column_searchable_list = ('nome', 'suspeita_principal', 'sinais_gatilho')
    form_columns = (
        'nome',
        'suspeita_principal',
        'especie',
        'sinais_gatilho',
        'conduta_sugerida',
        'orientacoes_tutor',
        'alertas',
        'prioridade',
        'versao',
        'ativo',
        'clinica',
        'criador',
    )


class AuditoriaSugestaoClinicaAdminView(MyModelView):
    can_create = False
    can_edit = False
    column_list = (
        'created_at',
        'consulta_id',
        'protocolo',
        'actor',
        'tipo_item',
        'acao',
        'titulo_item',
    )
    column_searchable_list = ('tipo_item', 'acao', 'titulo_item')


# --------------------------------------------------------------------------
# Função de inicialização do painel
# --------------------------------------------------------------------------
def init_admin(app):
    dashboard_view = AdminDashboard(endpoint='painel_admin')

    admin_kwargs = dict(
        name='Administração PetOrlândia',
        url='/painel',
        endpoint='painel_admin',       # mantém compatibilidade com url_for('painel_admin.index')
        index_view=dashboard_view,     # dashboard é a home
    )

    # bootstrap4 gera markup moderno (nav-link, dropdown-item, ícones FA),
    # que renderiza corretamente sob o Bootstrap 5 do master.html.
    admin = Admin(app, template_mode='bootstrap4', **admin_kwargs)

    # Registro das demais views
    admin.add_view(AnimalAdminView(
        Animal, db.session,
        name='Animais', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-paw'
    ))

    admin.add_view(SpeciesAdminView(
        Species, db.session,
        name='Espécies', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-dna'
    ))
    admin.add_view(MyModelView(
        Breed, db.session,
        name='Raças', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-dog'
    ))

    admin.add_view(UserAdminView(
        User, db.session,
        name='Usuários', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-users'
    ))
    admin.add_view(MyModelView(
        Message, db.session,
        name='Mensagens', category='Comunicação',
        menu_icon_type='fa', menu_icon_value='fa-envelope'
    ))
    admin.add_view(MyModelView(
        Transaction, db.session,
        name='Transações', category='Financeiro',
        menu_icon_type='fa', menu_icon_value='fa-dollar-sign'
    ))
    admin.add_view(MyModelView(
        Medicamento, db.session,
        name='Medicamentos', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-pills'
    ))
    admin.add_view(MyModelView(
        Prescricao, db.session,
        name='Prescrições', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-file-medical'
    ))
    admin.add_view(ClinicaAdmin(
        Clinica, db.session,
        name='Clínicas', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-hospital'
    ))
    admin.add_view(ContabilidadeConfigView(
        name='Configurações Contábeis', category='Contabilidade',
        menu_icon_type='fa', menu_icon_value='fa-calculator'
    ))
    admin.add_view(ClinicHoursAdmin(
        ClinicHours, db.session,
        name='Horários da Clínica', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-clock'
    ))
    admin.add_view(VetScheduleAdmin(
        VetSchedule, db.session,
        name='Agenda do Veterinário', category='Veterinários',
        menu_icon_type='fa', menu_icon_value='fa-calendar'
    ))
    admin.add_view(VeterinarianSettingsView(
        name='Configurar Assinatura', category='Veterinários',
        menu_icon_type='fa', menu_icon_value='fa-sliders-h'
    ))
    admin.add_view(VeterinarianMembershipAdmin(
        VeterinarianMembership, db.session,
        name='Assinaturas de Veterinários', category='Veterinários',
        menu_icon_type='fa', menu_icon_value='fa-id-card'
    ))
    admin.add_view(VeterinarioAdmin(
        Veterinario, db.session,
        name='Veterinários', category='Veterinários',
        menu_icon_type='fa', menu_icon_value='fa-user-md'
    ))
    admin.add_view(ClinicStaffAdmin(
        ClinicStaff, db.session,
        name='Staff da Clínica', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-user-nurse'
    ))
    admin.add_view(MyModelView(
        Specialty, db.session,
        name='Especialidades', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-stethoscope'
    ))
    admin.add_view(ExameModeloAdminView(
        ExameModelo, db.session,
        name='Exames', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-vials'
    ))
    admin.add_view(ProtocoloClinicoAdminView(
        ProtocoloClinico, db.session,
        name='Protocolos Clínicos', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-notes-medical'
    ))
    admin.add_view(MyModelView(
        ProtocoloClinicoExame, db.session,
        name='Protocolos • Exames', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-flask'
    ))
    admin.add_view(MyModelView(
        ProtocoloClinicoMedicamento, db.session,
        name='Protocolos • Medicamentos', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-capsules'
    ))
    admin.add_view(MyModelView(
        ProtocoloClinicoRetorno, db.session,
        name='Protocolos • Retornos', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-calendar-check'
    ))
    admin.add_view(AuditoriaSugestaoClinicaAdminView(
        AuditoriaSugestaoClinica, db.session,
        name='Auditoria de Sugestões', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-chart-line'
    ))
    admin.add_view(MyModelView(
        Consulta, db.session,
        name='Consultas', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-notes-medical'
    ))
    admin.add_view(MyModelView(
        VacinaModelo, db.session,
        name='Vacinas', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-syringe'
    ))
    admin.add_view(MyModelView(
        ApresentacaoMedicamento, db.session,
        name='Apresentações de Medicamento', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-capsules'
    ))
    admin.add_view(MyModelView(
        TipoRacao, db.session,
        name='Tipos de Ração', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-bone'
    ))
    admin.add_view(ProductAdmin(
        Product, db.session,
        name='Produtos', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-box-open'
    ))
    admin.add_view(ProductCategoryAdmin(
        ProductCategory, db.session,
        name='Categorias', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-tags'
    ))
    admin.add_view(CasaDeRacaoAdminView(
        CasaDeRacao, db.session,
        name='Casas de racao', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-store'
    ))
    admin.add_view(CasaDeRacaoHorarioAdminView(
        CasaDeRacaoHorario, db.session,
        name='Horarios das casas', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-clock'
    ))
    admin.add_view(StorePaymentAccountAdminView(
        StorePaymentAccount, db.session,
        name='Contas de pagamento', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-credit-card'
    ))
    admin.add_view(MyModelView(
        HealthPlan, db.session,
        name='Planos de Saúde', category='Financeiro',
        menu_icon_type='fa', menu_icon_value='fa-heart'
    ))
    admin.add_view(MyModelView(
        HealthSubscription, db.session,
        name='Assinaturas', category='Financeiro',
        menu_icon_type='fa', menu_icon_value='fa-file-contract'
    ))

    admin.add_view(MyModelView(
        Order, db.session,
        name='Pedidos', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-shopping-cart'
    ))
    admin.add_view(MyModelView(
        OrderItem, db.session,
        name='Itens de Pedido', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-list'
    ))
    admin.add_view(MyModelView(
        DeliveryRequest, db.session,
        name='Entregas', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-truck'
    ))
    # registrar
    admin.add_view(PickupLocationView(
        PickupLocation, db.session,
        name="Pontos de Retirada", category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-store'
    ))
    # Link para voltar ao site principal
    admin.add_link(MenuLink(name='🔙 Voltar ao Site', url='/'))
