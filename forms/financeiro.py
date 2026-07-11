"""Financeiro: pagamentos PJ e escalas de plantonistas.

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




class PJPaymentForm(FlaskForm):
    PRESTADOR_TIPO_CHOICES = [
        ('servico', 'Fornecedor / Serviço avulso'),
        ('plantonista', 'Plantonista vinculado à escala'),
    ]

    clinic_id = SelectField(
        'Clínica',
        coerce=int,
        validators=[DataRequired(message='Selecione a clínica.')],
    )
    prestador_tipo = SelectField(
        'Tipo de prestador',
        choices=PRESTADOR_TIPO_CHOICES,
        validators=[DataRequired(message='Selecione o tipo de prestador.')],
        render_kw={"data-controller": "pj-payment-type"},
    )
    plantao_vinculado = QuerySelectField(
        'Plantão vinculado',
        allow_blank=True,
        blank_text='Sem vínculo',
        get_label=lambda escala: getattr(escala, 'turno', 'Plantão'),
        query_factory=lambda: [],
        validators=[Optional()],
    )
    valor_por_hora = DecimalField(
        'Valor por hora',
        places=2,
        validators=[Optional(), NumberRange(min=0)],
        render_kw={"min": "0", "step": "0.01"},
    )
    horas_previstas = DecimalField(
        'Horas previstas',
        places=2,
        validators=[Optional(), NumberRange(min=0)],
        render_kw={"min": "0", "step": "0.25"},
    )
    plantao_inicio = DateTimeField(
        'Início do plantão',
        format='%Y-%m-%dT%H:%M',
        validators=[Optional()],
    )
    plantao_fim = DateTimeField(
        'Fim do plantão',
        format='%Y-%m-%dT%H:%M',
        validators=[Optional()],
    )
    prestador_nome = StringField(
        'Nome do prestador',
        validators=[DataRequired(message='Informe o nome do prestador.'), Length(max=150)],
    )
    prestador_cnpj = StringField(
        'CNPJ',
        validators=[DataRequired(message='Informe o CNPJ do prestador.'), Length(max=20)],
        render_kw={"placeholder": "00.000.000/0000-00"},
    )
    nota_fiscal_numero = StringField('Número da nota fiscal', validators=[Optional(), Length(max=80)])
    tipo_prestador = SelectField(
        'Tipo de prestador',
        choices=[
            ('plantonista', 'Plantonista'),
            ('especialista', 'Especialista'),
            ('demais_pj', 'Demais PJs'),
        ],
        default='especialista',
        validators=[DataRequired(message='Selecione o tipo de prestador.')],
    )
    plantao_horas = DecimalField(
        'Horas do plantão',
        places=2,
        validators=[Optional()],
        render_kw={"min": "0", "step": "0.25"},
    )
    valor = DecimalField(
        'Valor do pagamento',
        places=2,
        validators=[DataRequired(message='Informe o valor do pagamento.')],
        render_kw={"min": "0", "step": "0.01"},
    )
    data_servico = DateField('Data do serviço', format='%Y-%m-%d', validators=[DataRequired(message='Informe a data do serviço.')])
    data_pagamento = DateField('Data do pagamento', format='%Y-%m-%d', validators=[Optional()])
    observacoes = TextAreaField('Observações', validators=[Optional(), Length(max=2000)])
    submit = SubmitField('Salvar')

    def validate_prestador_cnpj(self, field):
        digits = ''.join(ch for ch in (field.data or '') if ch.isdigit())
        if len(digits) != 14:
            raise ValidationError('Informe um CNPJ válido com 14 dígitos.')

    def validate_prestador_tipo(self, field):
        valid_types = {choice[0] for choice in self.PRESTADOR_TIPO_CHOICES}
        if (field.data or '').strip() not in valid_types:
            raise ValidationError('Selecione um tipo de prestador válido.')

    def validate_plantao_vinculado(self, field):
        selected_type = (self.prestador_tipo.data or '').strip()
        escala = field.data
        if selected_type == 'plantonista' and not escala:
            raise ValidationError('Selecione o plantão vinculado ao pagamento.')
        if not escala:
            return
        clinic_id = self.clinic_id.data
        if clinic_id and getattr(escala, 'clinic_id', None) != clinic_id:
            raise ValidationError('O plantão selecionado pertence a outra clínica.')
        linked_payment_id = getattr(escala, 'pj_payment_id', None)
        current_payment_id = getattr(self, 'payment_id', None)
        if linked_payment_id and linked_payment_id != current_payment_id:
            raise ValidationError('O plantão selecionado já possui um pagamento vinculado.')

    def validate_valor_por_hora(self, field):
        if (self.prestador_tipo.data or '').strip() == 'plantonista':
            if field.data is None or field.data <= 0:
                raise ValidationError('Informe o valor por hora do plantão.')

    def validate_horas_previstas(self, field):
        if (self.prestador_tipo.data or '').strip() == 'plantonista':
            if field.data is None or field.data <= 0:
                raise ValidationError('Informe as horas previstas do plantão.')

    def validate_plantao_inicio(self, field):
        if (self.prestador_tipo.data or '').strip() == 'plantonista' and not field.data:
            raise ValidationError('Informe a data e hora de início do plantão.')

    def validate_plantao_fim(self, field):
        if (self.prestador_tipo.data or '').strip() != 'plantonista':
            return
        if not field.data:
            raise ValidationError('Informe a data e hora de término do plantão.')
        if self.plantao_inicio.data and field.data <= self.plantao_inicio.data:
            raise ValidationError('O término do plantão deve ser posterior ao início.')

    def validate_valor(self, field):
        if field.data is None or field.data <= 0:
            raise ValidationError('O valor deve ser maior que zero.')

    def validate_data_servico(self, field):
        if field.data and field.data > date.today():
            raise ValidationError('A data do serviço não pode estar no futuro.')

    def validate_plantao_horas(self, field):
        if field.data is not None and field.data <= 0:
            raise ValidationError('Informe um número de horas maior que zero ou deixe em branco.')


class PlantonistaEscalaForm(FlaskForm):
    clinic_id = SelectField('Clínica', coerce=int, validators=[DataRequired()])
    medico_id = SelectField('Médico (opcional)', coerce=int, validators=[Optional()], choices=[])
    medico_nome = StringField('Nome exibido do médico', validators=[DataRequired(), Length(max=150)])
    medico_cnpj = StringField('CNPJ do médico', validators=[Optional(), Length(max=20)])
    plantao_modelo_id = SelectField('Modelo de plantão', coerce=int, validators=[Optional()], choices=[])
    turno = StringField('Turno', validators=[DataRequired(), Length(max=80)])
    data_inicio = DateField('Data do plantão', format='%Y-%m-%d', validators=[DataRequired()])
    hora_inicio = TimeField('Hora de início', validators=[DataRequired()])
    hora_fim = TimeField('Hora de término', validators=[DataRequired()])
    valor_previsto = DecimalField(
        'Valor previsto',
        places=2,
        validators=[DataRequired(), NumberRange(min=0)],
        render_kw={"min": "0", "step": "0.01"},
    )
    status = SelectField('Status operacional', choices=PLANTONISTA_ESCALA_STATUS_CHOICES, validators=[DataRequired()])
    nota_fiscal_recebida = BooleanField('Nota fiscal recebida')
    retencao_validada = BooleanField('Retenção/NF verificada')
    observacoes = TextAreaField('Observações', validators=[Optional(), Length(max=2000)])
    salvar_modelo = BooleanField('Salvar como modelo da clínica')
    modelo_nome = StringField('Nome do modelo', validators=[Optional(), Length(max=80)])
    submit = SubmitField('Salvar plantão')

