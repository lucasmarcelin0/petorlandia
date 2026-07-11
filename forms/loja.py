"""Loja: carrinho, checkout, produtos e endereços.

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




class OrderItemForm(FlaskForm):
    item_name = StringField('Item', validators=[DataRequired()])
    quantity = IntegerField('Quantidade', validators=[DataRequired()])
    submit = SubmitField('Adicionar')


class AddToCartForm(FlaskForm):
    quantity = IntegerField('Quantidade', default=1, validators=[DataRequired()])
    variant_id = HiddenField(validators=[Optional()])
    submit = SubmitField('Adicionar ao Carrinho')


class CartAddressForm(FlaskForm):
    """Formulário simples para salvar endereços via carrinho."""
    cep = StringField('CEP (opcional)', validators=[Optional(), Length(max=9)])
    rua = StringField('Rua', validators=[DataRequired()])
    numero = StringField('Número', validators=[Optional()])
    complemento = StringField('Complemento', validators=[Optional()])
    bairro = StringField('Bairro', validators=[Optional()])
    cidade = StringField('Cidade', validators=[DataRequired()])
    estado = StringField('Estado', validators=[DataRequired()])


class DeliveryRequestForm(FlaskForm):
    submit = SubmitField('Gerar Solicitação')


class CheckoutForm(FlaskForm):
    """
    Formulário usado apenas para proteger a rota /checkout com CSRF
    e, se quiser, capturar informações extras de entrega/pagamento.
    Adicione campos conforme a necessidade.
    """
    # exemplos de campos opcionais:
    # name   = StringField('Nome',   validators=[DataRequired(), Length(max=120)])
    # email  = StringField('E‑mail', validators=[DataRequired(), Email()])
    # phone  = StringField('Telefone (WhatsApp)', validators=[Optional(), Length(max=20)])

    address_id = SelectField('Endereço salvo', choices=[], coerce=int, validators=[Optional()])
    shipping_address = TextAreaField('Novo Endereço', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Finalizar Compra')


class StoreHoursForm(FlaskForm):
    dias_semana = SelectMultipleField(
        'Dias da semana',
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
        render_kw={"class": "form-select", "multiple": True, "size": "4"},
    )
    hora_abertura = TimeField(
        'Hora de abertura',
        validators=[DataRequired()],
        render_kw={"class": "form-control", "type": "time"},
    )
    hora_fechamento = TimeField(
        'Hora de fechamento',
        validators=[DataRequired()],
        render_kw={"class": "form-control", "type": "time"},
    )
    submit = SubmitField('Salvar horário')


class EditAddressForm(FlaskForm):
    """Formulário simples para atualizar o endereço de entrega de um pedido."""
    shipping_address = TextAreaField('Endereço', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Salvar')


class _ProductCategoryChoicesMixin:
    """Popula o select de categoria da loja dinamicamente a partir do banco.

    As choices vêm de ``product_category_choices()``, que cai para a lista
    semente caso a tabela ainda não exista — assim o formulário nunca quebra.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self, "category"):
            from models import product_category_choices
            self.category.choices = product_category_choices()


class ProductUpdateForm(_ProductCategoryChoicesMixin, FlaskForm):
    name = StringField('Nome', validators=[DataRequired()])
    description = TextAreaField('Descrição')
    price = DecimalField('Preço', validators=[DataRequired()])
    stock = IntegerField('Estoque', validators=[DataRequired()])
    category = SelectField('Categoria na loja', choices=PRODUCT_CATEGORY_CHOICES, validators=[Optional()])
    mp_category_id = StringField('Categoria MP', validators=[Optional(), Length(max=50)])
    ncm = StringField('NCM', validators=[Optional(), Length(max=10)])
    cfop = StringField('CFOP', validators=[Optional(), Length(max=10)])
    cst = StringField('CST', validators=[Optional(), Length(max=5)])
    csosn = StringField('CSOSN', validators=[Optional(), Length(max=5)])
    origem = StringField('Origem', validators=[Optional(), Length(max=2)])
    unidade = StringField('Unidade', validators=[Optional(), Length(max=10)])
    aliquota_icms = DecimalField('Alíquota ICMS', validators=[Optional()])
    aliquota_pis = DecimalField('Alíquota PIS', validators=[Optional()])
    aliquota_cofins = DecimalField('Alíquota COFINS', validators=[Optional()])
    image_upload = FileField('Imagem', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField('Salvar')


class ProductPhotoForm(FlaskForm):
    image = FileField('Foto do Produto', validators=[DataRequired(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField('Adicionar Foto')


class ClinicProductForm(_ProductCategoryChoicesMixin, FlaskForm):
    """Formulário usado pelo dono da clínica para publicar um produto na loja."""
    name = StringField('Nome do produto', validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Descrição', validators=[Optional()])
    price = DecimalField('Preço (R$)', places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    image_upload = FileField('Imagem', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    category = SelectField('Categoria na loja', choices=PRODUCT_CATEGORY_CHOICES, validators=[Optional()])
    mp_category_id = StringField('Categoria', validators=[Optional(), Length(max=50)])
    # Quantidade inicial quando não há item de estoque vinculado
    quantity = IntegerField('Quantidade em estoque', validators=[Optional(), NumberRange(min=0)], default=0)
    unit = StringField('Unidade (ex: unidade, kg, caixa)', validators=[Optional(), Length(max=50)])
    # ID do ClinicInventoryItem existente (0 = criar novo)
    inventory_item_id = SelectField('Vincular ao estoque existente', coerce=int, validators=[Optional()])
    submit = SubmitField('Publicar na loja')


class ClinicProductEditForm(_ProductCategoryChoicesMixin, FlaskForm):
    """Formulário de edição de produto da clínica."""
    name = StringField('Nome do produto', validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Descrição', validators=[Optional()])
    price = DecimalField('Preço (R$)', places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    image_upload = FileField('Nova imagem', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    category = SelectField('Categoria na loja', choices=PRODUCT_CATEGORY_CHOICES, validators=[Optional()])
    mp_category_id = StringField('Categoria', validators=[Optional(), Length(max=50)])
    submit = SubmitField('Salvar alterações')

