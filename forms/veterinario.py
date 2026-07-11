"""Veterinário: perfil, promoções, membership, agenda e serviços.

Extraído de forms.py na modularização (2026-07-10).
"""
from flask_wtf import FlaskForm
from sqlalchemy import or_, false
from datetime import date
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
    RadioField,
    PasswordField,
    SubmitField,
    BooleanField,
    DecimalField,
    IntegerField,
    DateField,
    DateTimeField,
    TimeField,
    HiddenField,
    EmailField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    NumberRange,
    ValidationError,
)
# Some deployments might not have ``wtforms_sqlalchemy`` available. In that
# case we fall back to the compatible field that ships with Flask-Admin to
# avoid crashing the application when importing the forms module.
try:  # pragma: no cover - import guard
    from wtforms_sqlalchemy.fields import QuerySelectField
except ImportError:  # pragma: no cover - executed only when optional dep missing
    from flask_admin.contrib.sqla.fields import QuerySelectField
from flask_wtf.file import FileField, FileAllowed
try:
    from document_utils import format_cnpj, only_digits
except ImportError:
    from .document_utils import format_cnpj, only_digits
from models import PLANTONISTA_ESCALA_STATUS_CHOICES
from models import PRODUCT_CATEGORY_CHOICES


from .clinica import _strip_filter


class VeterinarianProfileForm(FlaskForm):
    crmv = StringField(
        'CRMV',
        validators=[DataRequired(), Length(max=20)],
        filters=[_strip_filter],
    )
    phone = StringField(
        'Telefone profissional',
        validators=[Optional(), Length(max=20)],
        filters=[_strip_filter],
    )
    submit = SubmitField('Salvar cadastro')


class VeterinarianPromotionForm(FlaskForm):
    crmv = StringField(
        'CRMV',
        validators=[DataRequired(), Length(max=20)],
        filters=[_strip_filter],
    )
    phone = StringField(
        'Telefone profissional',
        validators=[Optional(), Length(max=20)],
        filters=[_strip_filter],
    )
    submit = SubmitField('Promover a Veterinário')


class DeliveryPromotionForm(FlaskForm):
    confirm = BooleanField(
        'Confirmo a promoção deste usuário a entregador',
        validators=[DataRequired(message='Confirme a promoção para continuar.')],
    )
    submit = SubmitField('Promover a Entregador')


class DeliveryDemotionForm(FlaskForm):
    submit = SubmitField('Cancelar status de entregador')


class ParceiroPromotionForm(FlaskForm):
    confirm = BooleanField(
        'Confirmo a promoção deste usuário a parceiro de cadastro',
        validators=[DataRequired(message='Confirme a promoção para continuar.')],
    )
    submit = SubmitField('Promover a Parceiro')


class ParceiroDemotionForm(FlaskForm):
    submit = SubmitField('Remover status de parceiro')


class VeterinarianMembershipCheckoutForm(FlaskForm):
    submit = SubmitField('Ativar assinatura')


class VeterinarianMembershipCancelTrialForm(FlaskForm):
    submit = SubmitField('Cancelar avaliação gratuita')


class VeterinarianMembershipRequestNewTrialForm(FlaskForm):
    submit = SubmitField('Iniciar nova avaliação gratuita')


class VetScheduleForm(FlaskForm):
    veterinario_id = SelectField(
        'Veterinário',
        coerce=int,
        validators=[DataRequired()],
        render_kw={"class": "form-select"},
    )
    dias_semana = SelectMultipleField(
        'Dias da Semana',
        choices=[
            ('Segunda', 'Segunda'),
            ('Terça', 'Terça'),
            ('Quarta', 'Quarta'),
            ('Quinta', 'Quinta'),
            ('Sexta', 'Sexta'),
            ('Sábado', 'Sábado'),
            ('Domingo', 'Domingo'),
        ],
        validators=[DataRequired()],
        render_kw={"class": "form-select", "multiple": True},
    )
    hora_inicio = TimeField(
        'Hora de Início',
        validators=[DataRequired()],
        render_kw={"class": "form-control", "type": "time"},
    )
    hora_fim = TimeField(
        'Hora de Fim',
        validators=[DataRequired()],
        render_kw={"class": "form-control", "type": "time"},
    )
    intervalo_inicio = TimeField(
        'Início do Intervalo',
        validators=[Optional()],
        render_kw={"class": "form-control", "type": "time"},
    )
    intervalo_fim = TimeField(
        'Fim do Intervalo',
        validators=[Optional()],
        render_kw={"class": "form-control", "type": "time"},
    )
    submit = SubmitField('Salvar')


class VetSpecialtyForm(FlaskForm):
    specialties = SelectMultipleField('Especialidades', coerce=int)
    submit = SubmitField('Salvar')


_UF_CHOICES = [
    ('', '— UF —'),
    ('AC', 'AC'), ('AL', 'AL'), ('AM', 'AM'), ('AP', 'AP'), ('BA', 'BA'),
    ('CE', 'CE'), ('DF', 'DF'), ('ES', 'ES'), ('GO', 'GO'), ('MA', 'MA'),
    ('MG', 'MG'), ('MS', 'MS'), ('MT', 'MT'), ('PA', 'PA'), ('PB', 'PB'),
    ('PE', 'PE'), ('PI', 'PI'), ('PR', 'PR'), ('RJ', 'RJ'), ('RN', 'RN'),
    ('RO', 'RO'), ('RR', 'RR'), ('RS', 'RS'), ('SC', 'SC'), ('SE', 'SE'),
    ('SP', 'SP'), ('TO', 'TO'),
]


class VetProfileForm(FlaskForm):
    name = StringField('Nome completo', validators=[DataRequired(), Length(max=120)])
    phone = StringField('Telefone / WhatsApp', validators=[Optional(), Length(max=20)])
    email = EmailField('E-mail', validators=[Optional(), Email(), Length(max=120)])
    crmv = StringField('Número do CRMV', validators=[DataRequired(), Length(max=20)])
    crmv_estado = SelectField('UF do CRMV', choices=_UF_CHOICES, default='')
    specialties = SelectMultipleField('Especialidades', coerce=int, validators=[Optional()])
    cidades_atendidas = TextAreaField(
        'Cidades atendidas',
        validators=[Optional(), Length(max=2000)],
    )
    submit = SubmitField('Salvar perfil')


class ProfessionalServiceForm(FlaskForm):
    service_id = HiddenField(validators=[Optional()])
    title = StringField('Nome do serviço', validators=[DataRequired(), Length(max=140)])
    service_type = SelectField(
        'Tipo',
        choices=[
            ('consulta', 'Consulta'),
            ('ultrassom', 'Ultrassonografia'),
            ('exame', 'Exame'),
            ('outro', 'Outro'),
        ],
        validators=[DataRequired()],
    )
    description = TextAreaField('Descrição pública', validators=[Optional(), Length(max=2000)])
    audience = SelectField(
        'Quem pode ver',
        choices=[
            ('tutor', 'Somente tutores'),
            ('clinic', 'Somente donos de clínica'),
            ('both', 'Tutores e donos de clínica'),
        ],
        validators=[DataRequired()],
    )
    mode = SelectField(
        'Modalidade',
        choices=[
            ('domicilio', 'Domicílio'),
            ('clinica', 'Clínica'),
            ('clinica_ou_domicilio', 'Clínica ou domicílio'),
            ('online', 'Online'),
            ('outro', 'Outro'),
        ],
        validators=[Optional()],
    )
    duration_minutes = IntegerField('Duração padrão (min)', validators=[Optional(), NumberRange(min=5, max=600)])
    business_start = TimeField('Início do horário comercial', validators=[Optional()])
    business_end = TimeField('Fim do horário comercial', validators=[Optional()])
    tutor_price = DecimalField('Repasse tutor (R$)', places=2, validators=[Optional(), NumberRange(min=0)])
    clinic_business_price = DecimalField('Repasse clínica - horário comercial (R$)', places=2, validators=[Optional(), NumberRange(min=0)])
    clinic_after_hours_price = DecimalField('Repasse clínica - fora do comercial (R$)', places=2, validators=[Optional(), NumberRange(min=0)])
    active = BooleanField('Publicado', default=True)
    submit = SubmitField('Salvar serviço')

