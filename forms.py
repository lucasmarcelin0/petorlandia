from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
    PasswordField,
    SubmitField,
    BooleanField,
    DecimalField,
    IntegerField,
    DateField,
    DateTimeField,
    TimeField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, NumberRange
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
            DataRequired(message="Confirmação de senha é obrigatória"),
            EqualTo('password', message='As senhas devem coincidir')
        ],
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
    age_unit = SelectField(
        'Unidade da Idade',
        choices=[('anos', 'anos'), ('meses', 'meses')],
        default='anos',
        validators=[DataRequired()],
    )
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

class AppointmentForm(FlaskForm):
    veterinario_id = SelectField('Veterinário', coerce=int, validators=[DataRequired()])
    scheduled_at = DateTimeField('Data e Hora', format='%Y-%m-%d %H:%M', validators=[DataRequired()])
    description = TextAreaField('Descrição', validators=[Optional()])
    submit = SubmitField('Agendar')


class AppointmentDeleteForm(FlaskForm):
    submit = SubmitField('Excluir')


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


class ClinicForm(FlaskForm):
    nome = StringField('Nome', validators=[DataRequired()])
    cnpj = StringField('CNPJ', validators=[Optional()])
    endereco = StringField('Endereço', validators=[Optional()])
    telefone = StringField('Telefone', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    logotipo = FileField('Imagem da Clínica', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Apenas imagens!')])
    photo_rotation = IntegerField('Rotação', default=0, validators=[Optional()])
    photo_zoom = DecimalField('Zoom', places=2, default=1.0, validators=[Optional()])
    photo_offset_x = DecimalField('Offset X', places=0, default=0, validators=[Optional()])
    photo_offset_y = DecimalField('Offset Y', places=0, default=0, validators=[Optional()])
    submit = SubmitField('Salvar')


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
    submit = SubmitField('Salvar')


class InventoryItemForm(FlaskForm):
    name = StringField('Nome do item', validators=[DataRequired()])
    quantity = IntegerField('Quantidade', validators=[DataRequired(), NumberRange(min=0)])
    unit = StringField('Unidade', validators=[Optional(), Length(max=50)])
    submit = SubmitField('Adicionar')


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


class EditAddressForm(FlaskForm):
    """Formulário simples para atualizar o endereço de entrega de um pedido."""
    shipping_address = TextAreaField('Endereço', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Salvar')


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


class OrcamentoForm(FlaskForm):
    descricao = StringField('Descrição', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Salvar')


class AppointmentForm(FlaskForm):
    """Formulário para agendamento de consultas."""

    animal_id = SelectField(
        'Animal',
        coerce=int,
        validators=[DataRequired()],
    )

    veterinario_id = SelectField(
        'Veterinário',
        coerce=int,
        validators=[DataRequired()],
    )

    date = DateField(
        'Data',
        validators=[DataRequired()],
        format='%Y-%m-%d',
    )

    time = TimeField(
        'Horário',
        format='%H:%M',
        validators=[DataRequired()],
    )

    kind = SelectField(
        'Tipo',
        choices=[
            ('consulta', 'Consulta'),
            ('retorno', 'Retorno'),
            ('exame', 'Exame'),
            ('banho_tosa', 'Banho e Tosa'),
            ('vacina', 'Vacina'),
        ],
        validators=[DataRequired()],
        default='consulta',
    )

    reason = TextAreaField(
        'Motivo',
        validators=[Optional(), Length(max=500)],
    )

    submit = SubmitField('Agendar')

    def __init__(self, tutor=None, is_veterinario=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from models import Animal, Veterinario

        if is_veterinario:
            animals = Animal.query.all()
        elif tutor is not None:
            animals = Animal.query.filter_by(user_id=tutor.id).all()
        else:
            animals = Animal.query.all()

        self.animal_id.choices = [(a.id, a.name) for a in animals]

        veterinarios = Veterinario.query.all()
        self.veterinario_id.choices = [
            (v.id, v.user.name if v.user else str(v.id)) for v in veterinarios
        ]
        if not self.kind.data:
            self.kind.data = 'consulta'

