"""Parceiros e casas de ração.

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
from .loja import _ProductCategoryChoicesMixin
from models import PLANTONISTA_ESCALA_STATUS_CHOICES
from models import PRODUCT_CATEGORY_CHOICES




class CasaDeRacaoForm(FlaskForm):
    """Cadastro/edição de uma casa de ração parceira."""
    nome = StringField('Nome da loja', validators=[DataRequired(), Length(max=120)])
    razao_social = StringField('Razão social', validators=[Optional(), Length(max=200)])
    cnpj = StringField('CNPJ', validators=[Optional()])
    descricao = TextAreaField('Descrição / bio da loja', validators=[Optional()])
    telefone = StringField('Telefone', validators=[Optional(), Length(max=20)])
    email = StringField('E-mail', validators=[Optional(), Email()])
    endereco = StringField('Endereço', validators=[Optional(), Length(max=200)])
    modo_entrega = RadioField(
        'Modo de entrega',
        choices=[
            ('plataforma', 'Entregadores da plataforma PetOrlândia'),
            ('propria', 'Entrega própria — eu mesmo entrego meus pedidos'),
        ],
        default='plataforma',
    )
    valor_frete = DecimalField(
        'Frete por pedido (R$)',
        places=2,
        default=0,
        validators=[Optional(), NumberRange(min=0)],
    )
    pedido_minimo_entrega = DecimalField(
        'Pedido mínimo para entrega (R$)',
        places=2,
        validators=[Optional(), NumberRange(min=0)],
    )
    prazo_entrega_min = IntegerField(
        'Prazo mínimo (min)',
        validators=[Optional(), NumberRange(min=0, max=1440)],
    )
    prazo_entrega_max = IntegerField(
        'Prazo máximo (min)',
        validators=[Optional(), NumberRange(min=0, max=1440)],
    )
    logotipo = FileField(
        'Logo da loja',
        validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')],
    )
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


class ParceiroEstabelecimentoForm(FlaskForm):
    """Cadastro de estabelecimento pela Área do Parceiro.

    Um único formulário cobre clínica, casa de ração, pet shop, banho e tosa e
    pet sitter; campos específicos são validados conforme o ``tipo`` escolhido.
    """

    TIPO_CHOICES = [
        ('clinica', 'Clínica veterinária'),
        ('casa_de_racao', 'Casa de ração'),
        ('petshop', 'Pet shop'),
        ('banho_tosa', 'Banho e tosa'),
        ('petsitter', 'Pet sitter'),
    ]

    tipo = SelectField('Tipo de estabelecimento', choices=TIPO_CHOICES, validators=[DataRequired()])
    nome = StringField('Nome', validators=[DataRequired(), Length(max=120)])
    cnpj = StringField('CNPJ', validators=[Optional()])
    telefone = StringField('Telefone', validators=[Optional(), Length(max=20)])
    email = StringField('E-mail de contato', validators=[Optional(), Email()])
    endereco = StringField('Endereço', validators=[Optional(), Length(max=200)])
    cidade = StringField('Cidade', validators=[Optional(), Length(max=120)])
    descricao = TextAreaField('Descrição', validators=[Optional()])
    preco_diaria = DecimalField(
        'Preço da diária (pet sitter)',
        places=2,
        validators=[Optional(), NumberRange(min=0)],
    )

    owner_mode = RadioField(
        'Quem é o dono?',
        choices=[
            ('new', 'Criar novo usuário (dono do negócio)'),
            ('existing', 'Vincular a um usuário existente (por e-mail)'),
            ('self', 'Manter sob minha gestão (sem dono separado)'),
        ],
        default='new',
    )
    owner_name = StringField('Nome do dono', validators=[Optional(), Length(max=120)])
    owner_email = StringField('E-mail do dono', validators=[Optional(), Email()])
    owner_phone = StringField('Telefone do dono', validators=[Optional(), Length(max=20)])
    submit = SubmitField('Cadastrar estabelecimento')

    def validate_cnpj(self, field):
        if not field.data:
            return
        digits = only_digits(field.data)
        if len(digits) != 14:
            raise ValidationError('Informe um CNPJ válido com 14 dígitos.')
        field.data = format_cnpj(field.data)

    def validate_owner_email(self, field):
        if (self.owner_mode.data or '') in {'new', 'existing'} and not (field.data or '').strip():
            raise ValidationError('Informe o e-mail do dono.')

    def validate_owner_name(self, field):
        if (self.owner_mode.data or '') == 'new' and not (field.data or '').strip():
            raise ValidationError('Informe o nome do dono.')


class ParceiroUsuarioForm(FlaskForm):
    """Cadastro avulso de usuário pela Área do Parceiro."""

    name = StringField('Nome completo', validators=[DataRequired(), Length(max=120)])
    email = StringField('E-mail', validators=[DataRequired(), Email()])
    phone = StringField('Telefone', validators=[Optional(), Length(max=20)])
    cpf = StringField('CPF', validators=[Optional()])
    submit = SubmitField('Criar usuário')


class CasaDeRacaoProductForm(_ProductCategoryChoicesMixin, FlaskForm):
    """Formulário para publicar um produto da casa de ração na loja."""
    name = StringField('Nome do produto', validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Descrição', validators=[Optional()])
    price = DecimalField('Preço da primeira apresentação (R$)', places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    stock = IntegerField('Estoque da primeira apresentação', validators=[Optional(), NumberRange(min=0)], default=0)
    variant_name = StringField('Primeira apresentação', validators=[Optional(), Length(max=160)])
    dosage = StringField('Dosagem (opcional)', validators=[Optional(), Length(max=80)])
    package_quantity = StringField('Embalagem (opcional)', validators=[Optional(), Length(max=80)])
    weight_volume = StringField('Peso/volume (opcional)', validators=[Optional(), Length(max=80)])
    sku = StringField('SKU/código interno (opcional)', validators=[Optional(), Length(max=80)])
    image_upload = FileField(
        'Imagem',
        validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')],
    )
    category = SelectField('Categoria na loja', choices=PRODUCT_CATEGORY_CHOICES, validators=[Optional()])
    mp_category_id = StringField('Categoria', validators=[Optional(), Length(max=50)])
    submit = SubmitField('Publicar na loja')


class CasaDeRacaoProductEditForm(_ProductCategoryChoicesMixin, FlaskForm):
    """Formulário de edição de produto da casa de ração."""
    name = StringField('Nome do produto', validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Descrição', validators=[Optional()])
    price = DecimalField('Preço padrão/menor apresentação (R$)', places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    stock = IntegerField('Estoque total/legado', validators=[Optional(), NumberRange(min=0)])
    image_upload = FileField(
        'Nova imagem',
        validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')],
    )
    category = SelectField('Categoria na loja', choices=PRODUCT_CATEGORY_CHOICES, validators=[Optional()])
    mp_category_id = StringField('Categoria', validators=[Optional(), Length(max=50)])
    submit = SubmitField('Salvar alterações')

