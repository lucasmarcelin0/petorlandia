from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    PasswordField,
    SubmitField,
    BooleanField,
    DecimalField,
    IntegerField,
    DateField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional
from flask_wtf.file import FileField, FileAllowed


class ResetPasswordRequestForm(FlaskForm):
    email = StringField(
        'E-mail',
        validators=[DataRequired(message="Email é obrigatório"), Email()],
        render_kw={"required": True},
    )
    submit = SubmitField('Solicitar redefinição de senha')

class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        'Nova senha',
        validators=[DataRequired(message="Senha é obrigatória")],
        render_kw={"required": True},
    )
    confirm_password = PasswordField(
        'Confirme a nova senha',
        validators=[DataRequired(message="Confirmação de senha é obrigatória"), EqualTo('password')],
        render_kw={"required": True},
    )
    submit = SubmitField('Redefinir senha')


class RegistrationForm(FlaskForm):
    name = StringField(
        'Name',
        validators=[DataRequired(message="Nome é obrigatório"), Length(min=2, max=120)],
        render_kw={"required": True},
    )
    email = StringField(
        'Email',
        validators=[DataRequired(message="Email é obrigatório"), Email()],
        render_kw={"required": True},
    )
    phone = StringField('Phone', validators=[Optional(), Length(min=8, max=20)])
    address = StringField('Address', validators=[Optional(), Length(max=200)])
    profile_photo = FileField('Foto de Perfil', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')
    ])
    photo_rotation = IntegerField('Rotação', default=0, validators=[Optional()])
    photo_zoom = DecimalField('Zoom', places=2, default=1.0, validators=[Optional()])
    photo_offset_x = DecimalField('Offset X', places=0, default=0, validators=[Optional()])
    photo_offset_y = DecimalField('Offset Y', places=0, default=0, validators=[Optional()])
    password = PasswordField(
        'Password',
        validators=[DataRequired(message="Senha é obrigatória"), Length(min=6)],
        render_kw={"required": True},
    )
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(message="Confirmação de senha é obrigatória"), EqualTo('password', message='Passwords must match')],
        render_kw={"required": True},
    )
    submit = SubmitField('Cadastrar')






class RegistrationForm(FlaskForm):
    name = StringField(
        'Nome',
        validators=[DataRequired(message="Nome é obrigatório"), Length(min=2, max=120)],
        render_kw={"required": True},
    )
    email = StringField(
        'Email',
        validators=[DataRequired(message="Email é obrigatório"), Email()],
        render_kw={"required": True},
    )
    phone = StringField('Telefone', validators=[Optional(), Length(min=8, max=20)])
    address = StringField('Endereço', validators=[Optional(), Length(max=200)])
    
    profile_photo = FileField('Foto de Perfil', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')
    ])
    photo_rotation = IntegerField('Rotação', default=0, validators=[Optional()])
    photo_zoom = DecimalField('Zoom', places=2, default=1.0, validators=[Optional()])
    photo_offset_x = DecimalField('Offset X', places=0, default=0, validators=[Optional()])
    photo_offset_y = DecimalField('Offset Y', places=0, default=0, validators=[Optional()])

    password = PasswordField(
        'Senha',
        validators=[DataRequired(message="Senha é obrigatória"), Length(min=6)],
        render_kw={"required": True},
    )
    confirm_password = PasswordField(
        'Confirme a senha',
        validators=[
            DataRequired(message="Confirmação obrigatória"),
            EqualTo('password', message='As senhas devem coincidir')
        ],
        render_kw={"required": True},
    )

    submit = SubmitField('Cadastrar')



    password = PasswordField(
        'Password',
        validators=[DataRequired(message="Senha é obrigatória"), Length(min=6)],
        render_kw={"required": True},
    )
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(message="Confirmação de senha é obrigatória"), EqualTo('password', message='Passwords must match')],
        render_kw={"required": True},
    )
    submit = SubmitField('Cadastrar')





class LoginForm(FlaskForm):

    email = StringField(
        'Email',
        validators=[DataRequired(message="Email é obrigatório"), Email()],
        render_kw={"required": True},
    )
    password = PasswordField(
        'Senha',
        validators=[DataRequired(message="Senha é obrigatória")],
        render_kw={"required": True},
    )



    # Deixa marcada por padrao para que o usuario permaneça logado ao fechar o navegador
    remember = BooleanField('Lembrar de mim', default=True)
    submit = SubmitField('Entrar')



class AnimalForm(FlaskForm):
    name = StringField('Nome do Animal', validators=[DataRequired()])
    age = StringField('Idade', validators=[DataRequired()])
    date_of_birth = DateField('Data de Nascimento', format='%Y-%m-%d', validators=[Optional()])
    sex = SelectField('Sexo', choices=[('Macho', 'Macho'), ('Fêmea', 'Fêmea')], validators=[DataRequired()])
    description = TextAreaField('Descrição', validators=[Optional(), Length(max=500)])
    image = FileField('Imagem do Animal', validators=[
    Optional(),
    FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Somente imagens!')
])
    photo_rotation = IntegerField('Rotação', default=0, validators=[Optional()])
    photo_zoom = DecimalField('Zoom', places=2, default=1.0, validators=[Optional()])
    photo_offset_x = DecimalField('Offset X', places=0, default=0, validators=[Optional()])
    photo_offset_y = DecimalField('Offset Y', places=0, default=0, validators=[Optional()])
    price = DecimalField('Preço (R$)', places=2, validators=[Optional()])

    modo = SelectField('Modo de Disponibilidade', choices=[
    ('doação', 'Doação'),
    ('venda', 'Venda'),
    ('adotado', 'Adotado (meu)'),
    ('perdido', 'Perdido')
], validators=[DataRequired()], render_kw={"id": "modo"})


    submit = SubmitField('Cadastrar Animal')

class EditProfileForm(FlaskForm):
    name = StringField('Nome', validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField('E-mail', validators=[DataRequired(), Email()])
    phone = StringField('Telefone', validators=[Optional(), Length(max=20)])
    address = StringField('Endereço', validators=[Optional(), Length(max=200)])
    profile_photo = FileField('Foto de Perfil', validators=[
    Optional(),
    FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Somente imagens!')
])
    photo_rotation = IntegerField('Rotação', default=0, validators=[Optional()])
    photo_zoom = DecimalField('Zoom', places=2, default=1.0, validators=[Optional()])
    photo_offset_x = DecimalField('Offset X', places=0, default=0, validators=[Optional()])
    photo_offset_y = DecimalField('Offset Y', places=0, default=0, validators=[Optional()])
    submit = SubmitField('Salvar Alterações')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Senha Atual', validators=[DataRequired()])
    new_password = PasswordField(
        'Nova Senha',
        validators=[DataRequired(), Length(min=6)]
    )
    confirm_password = PasswordField(
        'Confirme a Nova Senha',
        validators=[DataRequired(), EqualTo('new_password')]
    )
    submit = SubmitField('Alterar Senha')


class DeleteAccountForm(FlaskForm):
    submit = SubmitField('Excluir Conta')



class MessageForm(FlaskForm):
    content = TextAreaField('Mensagem', validators=[DataRequired(), Length(max=1000)])
    submit = SubmitField('Enviar Mensagem')

class OrderItemForm(FlaskForm):
    item_name = StringField('Item', validators=[DataRequired()])
    quantity = IntegerField('Quantidade', validators=[DataRequired()])
    submit = SubmitField('Adicionar')

class AddToCartForm(FlaskForm):
    quantity = IntegerField('Quantidade', default=1, validators=[DataRequired()])
    submit = SubmitField('Adicionar ao Carrinho')


class CartAddressForm(FlaskForm):
    """Formulário simples para salvar endereços via carrinho."""
    cep = StringField('CEP', validators=[DataRequired()])
    rua = StringField('Rua', validators=[DataRequired()])
    numero = StringField('Número', validators=[Optional()])
    complemento = StringField('Complemento', validators=[Optional()])
    bairro = StringField('Bairro', validators=[Optional()])
    cidade = StringField('Cidade', validators=[DataRequired()])
    estado = StringField('Estado', validators=[DataRequired()])

class DeliveryRequestForm(FlaskForm):
    submit = SubmitField('Gerar Solicitação')


class SubscribePlanForm(FlaskForm):
    plan_id = SelectField('Plano', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Contratar Plano')
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


class ProductUpdateForm(FlaskForm):
    name = StringField('Nome', validators=[DataRequired()])
    description = TextAreaField('Descrição')
    price = DecimalField('Preço', validators=[DataRequired()])
    stock = IntegerField('Estoque', validators=[DataRequired()])
    mp_category_id = StringField('Categoria MP', validators=[Optional(), Length(max=50)])
    image_upload = FileField('Imagem', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField('Salvar')


class ProductPhotoForm(FlaskForm):
    image = FileField('Foto do Produto', validators=[DataRequired(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField('Adicionar Foto')
