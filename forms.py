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
    submit = SubmitField('Salvar Alterações')



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

    submit = SubmitField('Finalizar Compra')


class ProductUpdateForm(FlaskForm):
    name = StringField('Nome', validators=[DataRequired()])
    description = TextAreaField('Descrição')
    price = DecimalField('Preço', validators=[DataRequired()])
    stock = IntegerField('Estoque', validators=[DataRequired()])
    image_upload = FileField('Imagem', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField('Salvar')


class ProductPhotoForm(FlaskForm):
    image = FileField('Foto do Produto', validators=[DataRequired(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    submit = SubmitField('Adicionar Foto')
