"""Clínica: cadastro, equipe, convites, estoque e orçamento.

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




class ClinicForm(FlaskForm):
    nome = StringField('Nome', validators=[DataRequired()])
    cnpj = StringField('CNPJ', validators=[Optional()])
    endereco = StringField('Endereço', validators=[Optional()])
    telefone = StringField('Telefone', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    modo_entrega = SelectField(
        'Modo de entrega',
        choices=[
            ('plataforma', 'Entregadores da plataforma PetOrlândia'),
            ('propria', 'Entrega própria'),
        ],
        default='plataforma',
    )
    valor_frete = DecimalField('Frete por pedido (R$)', places=2, default=0, validators=[Optional(), NumberRange(min=0)])
    pedido_minimo_entrega = DecimalField('Pedido mínimo para entrega (R$)', places=2, validators=[Optional(), NumberRange(min=0)])
    prazo_entrega_min = IntegerField('Prazo mínimo (min)', validators=[Optional(), NumberRange(min=0, max=1440)])
    prazo_entrega_max = IntegerField('Prazo máximo (min)', validators=[Optional(), NumberRange(min=0, max=1440)])
    logotipo = FileField('Imagem da Clínica', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    photo_rotation = IntegerField('Rotação', default=0, validators=[Optional()])
    photo_zoom = DecimalField('Zoom', places=2, default=1.0, validators=[Optional()])
    photo_offset_x = DecimalField('Offset X', places=0, default=0, validators=[Optional()])
    photo_offset_y = DecimalField('Offset Y', places=0, default=0, validators=[Optional()])
    submit = SubmitField('Salvar')

    def validate_cnpj(self, field):
        if not field.data:
            return
        digits = only_digits(field.data)
        if len(digits) != 14:
            raise ValidationError('Informe um CNPJ válido com 14 dígitos.')
        field.data = format_cnpj(field.data)


class ClinicHoursForm(FlaskForm):
    clinica_id = SelectField(
        'Clínica',
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
    hora_abertura = TimeField(
        'Hora de Abertura',
        validators=[DataRequired()],
        render_kw={"class": "form-control", "type": "time"},
    )
    hora_fechamento = TimeField(
        'Hora de Fechamento',
        validators=[DataRequired()],
        render_kw={"class": "form-control", "type": "time"},
    )
    submit = SubmitField('Salvar')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from helpers import clinicas_do_usuario

        self.clinica_id.choices = [
            (c.id, c.nome) for c in clinicas_do_usuario().all()
        ]


def _strip_filter(value):
    return value.strip() if isinstance(value, str) else value


class ClinicInviteVeterinarianForm(FlaskForm):
    email = StringField(
        'Email do Veterinário',
        validators=[DataRequired(), Email()],
        filters=[_strip_filter],
    )
    submit = SubmitField('Convidar')


class ClinicInviteCancelForm(FlaskForm):
    submit = SubmitField('Cancelar')


class ClinicInviteResendForm(FlaskForm):
    submit = SubmitField('Reenviar')


class ClinicInviteResponseForm(FlaskForm):
    submit = SubmitField('Enviar')


class ClinicAddStaffForm(FlaskForm):
    """Simple form to add an existing user as clinic staff."""
    email = StringField('Email do usuário', validators=[DataRequired(), Email()])
    submit = SubmitField('Adicionar')


class ClinicAddSpecialistForm(FlaskForm):
    """Form to associate an existing veterinarian as a clinic specialist."""

    email = StringField('Email do especialista', validators=[DataRequired(), Email()])
    submit = SubmitField('Adicionar especialista')


class ClinicStaffPermissionForm(FlaskForm):
    can_manage_clients = BooleanField('Clientes')
    can_manage_animals = BooleanField('Animais')
    can_manage_staff = BooleanField('Funcionários')
    can_manage_schedule = BooleanField('Agenda')
    can_manage_inventory = BooleanField('Estoque')
    can_view_full_calendar = BooleanField('Visualizar agenda completa da clínica', default=True)
    appointments_view = SelectField(
        'Visão de Agenda',
        choices=[
            ('', '— padrão —'),
            ('colaborador', 'Colaborador'),
            ('veterinario', 'Veterinário'),
        ],
        default='',
    )
    submit = SubmitField('Salvar')


class InventoryItemForm(FlaskForm):
    name = StringField('Nome do item', validators=[DataRequired()])
    quantity = IntegerField('Quantidade', validators=[DataRequired(), NumberRange(min=0)])
    unit = StringField('Unidade', validators=[Optional(), Length(max=50)])
    min_quantity = IntegerField('Quantidade mínima', validators=[Optional(), NumberRange(min=0)])
    max_quantity = IntegerField('Quantidade máxima', validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField('Adicionar')

    def validate(self, **kwargs):  # type: ignore[override]
        rv = super().validate(**kwargs)
        if not rv:
            return False
        if (
            self.min_quantity.data is not None
            and self.max_quantity.data is not None
            and self.min_quantity.data > self.max_quantity.data
        ):
            self.max_quantity.errors.append('O máximo deve ser maior ou igual ao mínimo.')
            return False
        return True


class OrcamentoForm(FlaskForm):
    clinica_id = HiddenField(validators=[DataRequired()])
    descricao = StringField('Descrição', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Salvar')

