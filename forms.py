from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, PasswordField, SubmitField, BooleanField, DecimalField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional
from flask_wtf.file import FileField, FileAllowed


class ResetPasswordRequestForm(FlaskForm):
    email = StringField('E-mail', validators=[DataRequired(), Email()])
    submit = SubmitField('Solicitar redefinição de senha')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('Nova senha', validators=[DataRequired()])
    confirm_password = PasswordField('Confirme a nova senha', validators=[
        DataRequired(), EqualTo('password')])
    submit = SubmitField('Redefinir senha')




class RegistrationForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone', validators=[Optional(), Length(min=8, max=20)])
    address = StringField('Address', validators=[Optional(), Length(max=200)])

    profile_photo = FileField('Foto de Perfil', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')
    ])

    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Register')




class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Senha', validators=[DataRequired()])
    remember = BooleanField('Lembrar de mim')
    submit = SubmitField('Entrar')



class AnimalForm(FlaskForm):
    name = StringField('Nome do Animal', validators=[DataRequired()])
    species = StringField('Espécie', validators=[DataRequired()])
    breed = StringField('Raça', validators=[DataRequired()])
    age = StringField('Idade', validators=[DataRequired()])
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
    ('adotado', 'Adotado (meu)')
], validators=[DataRequired()], render_kw={"id": "modo"})

    submit = SubmitField('Cadastrar Animal')

class EditProfileForm(FlaskForm):
    name = StringField('Nome', validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
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
