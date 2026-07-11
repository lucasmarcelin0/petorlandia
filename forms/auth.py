"""Autenticação, cadastro e conta do usuário.

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


class FirstAccessPhoneForm(FlaskForm):
    class Meta:
        csrf = False

    phone = StringField(
        'Celular',
        validators=[DataRequired(message="Informe o celular com DDD")],
        render_kw={"required": True},
    )
    submit = SubmitField('Continuar')


class FirstAccessPasswordForm(FlaskForm):
    class Meta:
        csrf = False

    email = EmailField(
        'E-mail',
        validators=[Optional(), Email(message="Informe um e-mail válido")],
    )
    password = PasswordField(
        'Nova senha',
        validators=[DataRequired(message="Senha é obrigatória"), Length(min=6, message="A senha deve ter pelo menos 6 caracteres")],
        render_kw={"required": True},
    )
    confirm_password = PasswordField(
        'Confirme a nova senha',
        validators=[
            DataRequired(message="Confirmação de senha é obrigatória"),
            EqualTo('password', message='As senhas devem coincidir'),
        ],
        render_kw={"required": True},
    )
    submit = SubmitField('Criar senha e entrar')


class RegistrationForm(FlaskForm):
    name = StringField(
        'Nome completo',
        validators=[
            DataRequired(message="Informe seu nome"),
            Length(min=2, max=120, message="O nome deve ter entre 2 e 120 caracteres"),
        ],
        render_kw={"required": True, "aria-required": "true", "autocomplete": "name"},
    )
    email = EmailField(
        'E-mail',
        validators=[
            DataRequired(message="Informe seu e-mail"),
            Email(message="Informe um e-mail válido (ex.: nome@exemplo.com)"),
        ],
        render_kw={"required": True, "aria-required": "true", "autocomplete": "email", "inputmode": "email"},
    )
    phone = StringField(
        'Celular (opcional)',
        validators=[Optional(), Length(min=8, max=20, message="Informe um celular válido com DDD")],
        render_kw={"autocomplete": "tel", "inputmode": "tel"},
    )
    address = StringField('Endereço', validators=[Optional(), Length(max=200)])

    profile_photo = FileField('Foto de perfil (opcional)', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Envie uma imagem nos formatos JPG, PNG ou GIF.')
    ])
    photo_rotation = IntegerField('Rotação', default=0, validators=[Optional()])
    photo_zoom = DecimalField('Zoom', places=2, default=1.0, validators=[Optional()])
    photo_offset_x = DecimalField('Offset X', places=0, default=0, validators=[Optional()])
    photo_offset_y = DecimalField('Offset Y', places=0, default=0, validators=[Optional()])

    password = PasswordField(
        'Senha',
        validators=[
            DataRequired(message="Crie uma senha"),
            Length(min=6, message="A senha deve ter pelo menos 6 caracteres"),
        ],
        render_kw={"required": True, "aria-required": "true", "autocomplete": "new-password", "minlength": "6"},
    )
    confirm_password = PasswordField(
        'Confirme a senha',
        validators=[
            DataRequired(message="Repita a senha para confirmar"),
            EqualTo('password', message='As senhas digitadas não são iguais')
        ],
        render_kw={"required": True, "aria-required": "true", "autocomplete": "new-password", "minlength": "6"},
    )

    submit = SubmitField('Criar conta')


class LoginForm(FlaskForm):

    login = StringField(
        'E-mail ou celular',
        validators=[DataRequired(message="Informe seu e-mail ou celular")],
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


class EditProfileForm(FlaskForm):
    name = StringField('Nome', validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField('E-mail', validators=[DataRequired(), Email()])
    phone = StringField('Telefone', validators=[Optional(), Length(max=20)])
    address = StringField('Endereço', validators=[Optional(), Length(max=200)])
    is_private = BooleanField('Manter perfil privado', default=True)
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

