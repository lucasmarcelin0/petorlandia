"""Planos de saúde e grooming.

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




class SubscribePlanForm(FlaskForm):
    plan_id = SelectField('Plano', coerce=int, validators=[DataRequired()])
    tutor_document = StringField(
        'Documento do tutor (CPF/CNPJ)',
        validators=[DataRequired(), Length(min=5, max=40)],
    )
    animal_document = StringField(
        'Registro do animal (microchip, RG, etc.)',
        validators=[Optional(), Length(max=60)],
    )
    contract_reference = StringField(
        'Número da apólice/contrato',
        validators=[Optional(), Length(max=80)],
    )
    document_links = TextAreaField(
        'Links para documentos exigidos pela seguradora',
        validators=[Optional(), Length(max=500)],
    )
    extra_notes = TextAreaField(
        'Observações adicionais',
        validators=[Optional(), Length(max=500)],
    )
    consent = BooleanField(
        'Confirmo que revisei e aceitei o contrato do plano.',
        validators=[DataRequired(message='É necessário aceitar os termos.')],
    )
    submit = SubmitField('Contratar Plano')


class ConsultaPlanAuthorizationForm(FlaskForm):
    subscription_id = SelectField(
        'Plano do animal',
        coerce=int,
        validators=[DataRequired(message='Escolha um plano para validar.')],
    )
    notes = TextAreaField('Anotações para a seguradora', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Validar cobertura')


class HealthPlanForm(FlaskForm):
    """Criação/edição de plano de saúde (admin)."""
    name = StringField('Nome do plano', validators=[DataRequired(), Length(max=50)])
    description = TextAreaField('Descrição', validators=[Optional()])
    price = DecimalField('Mensalidade (R$)', places=2, validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Salvar plano')


class GroomingPlanForm(FlaskForm):
    """Usado pelo dono da clínica para criar/editar um plano de banho e tosa."""
    name = StringField('Nome do plano', validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Descrição', validators=[Optional()])
    service_type = SelectField(
        'Tipo de serviço',
        choices=[
            ('banho', 'Banho'),
            ('tosa', 'Tosa'),
            ('banho_e_tosa', 'Banho e Tosa'),
        ],
        validators=[DataRequired()],
    )
    price = DecimalField('Mensalidade (R$)', places=2, validators=[DataRequired(), NumberRange(min=1)])
    sessions_per_month = IntegerField(
        'Sessões por mês',
        validators=[DataRequired(), NumberRange(min=1, max=31)],
        default=1,
    )
    submit = SubmitField('Salvar plano')


class GroomingSubscribeForm(FlaskForm):
    """Usado pelo tutor para assinar um plano de banho e tosa."""
    animal_id = SelectField('Animal', coerce=int, validators=[DataRequired()])
    consent = BooleanField(
        'Concordo com os termos do plano e autorizo a cobrança mensal recorrente.',
        validators=[DataRequired(message='Você deve aceitar os termos para continuar.')],
    )
    submit = SubmitField('Assinar plano')

