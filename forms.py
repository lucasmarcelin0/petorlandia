from flask_wtf import FlaskForm
from sqlalchemy import or_, false
from datetime import date
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
    HiddenField,
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


PJ_PAYMENT_TYPE_CHOICES = [
    ('prestador', 'Prestador PJ / fixo'),
    ('plantonista', 'Plantonista / plantão'),
    ('consultoria', 'Consultoria / serviço pontual'),
]


class PJPaymentForm(FlaskForm):
    clinic_id = SelectField('Clínica', coerce=int, validators=[DataRequired(message='Selecione a clínica.')])
    tipo_prestador = SelectField(
        'Tipo de prestador',
        choices=PJ_PAYMENT_TYPE_CHOICES,
        validators=[DataRequired(message='Informe o tipo de prestador.')],
        default='prestador',
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
    valor = DecimalField(
        'Valor do pagamento',
        places=2,
        validators=[Optional()],
        render_kw={"min": "0", "step": "0.01"},
    )
    valor_hora = DecimalField(
        'Valor por hora',
        places=2,
        validators=[Optional()],
        render_kw={"min": "0", "step": "0.01"},
    )
    horas_previstas = DecimalField(
        'Horas previstas',
        places=2,
        validators=[Optional()],
        render_kw={"min": "0", "step": "0.25"},
    )
    plantonista_id = SelectField(
        'Escala/plantão',
        coerce=int,
        validators=[Optional()],
        choices=[],
        default=0,
    )
    plantonista_turno_inicio = DateTimeField(
        'Início do plantão',
        format='%Y-%m-%dT%H:%M',
        validators=[Optional()],
        render_kw={"type": "datetime-local"},
    )
    plantonista_turno_fim = DateTimeField(
        'Fim do plantão',
        format='%Y-%m-%dT%H:%M',
        validators=[Optional()],
        render_kw={"type": "datetime-local"},
    )
    data_servico = DateField('Data do serviço', format='%Y-%m-%d', validators=[DataRequired(message='Informe a data do serviço.')])
    data_pagamento = DateField('Data do pagamento', format='%Y-%m-%d', validators=[Optional()])
    observacoes = TextAreaField('Observações', validators=[Optional(), Length(max=2000)])
    retencao_obrigatoria = BooleanField('Aplicar retenção obrigatória?')
    submit = SubmitField('Salvar')

    def validate_prestador_cnpj(self, field):
        digits = ''.join(ch for ch in (field.data or '') if ch.isdigit())
        if len(digits) != 14:
            raise ValidationError('Informe um CNPJ válido com 14 dígitos.')

    def validate_valor(self, field):
        tipo = (self.tipo_prestador.data or '').strip()
        if tipo == 'plantonista' and self.valor_hora.data and self.horas_previstas.data:
            return
        if field.data is None or field.data <= 0:
            raise ValidationError('O valor deve ser maior que zero.')

    def validate_data_servico(self, field):
        if field.data and field.data > date.today():
            raise ValidationError('A data do serviço não pode estar no futuro.')

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators)
        tipo = (self.tipo_prestador.data or '').strip()

        if self.valor_hora.data is not None and self.valor_hora.data <= 0:
            self.valor_hora.errors.append('Informe um valor por hora maior que zero.')
            is_valid = False

        if self.horas_previstas.data is not None and self.horas_previstas.data <= 0:
            self.horas_previstas.errors.append('Informe horas previstas maiores que zero.')
            is_valid = False

        if self.plantonista_turno_inicio.data and self.plantonista_turno_fim.data:
            if self.plantonista_turno_fim.data <= self.plantonista_turno_inicio.data:
                self.plantonista_turno_fim.errors.append('O fim do plantão deve ser posterior ao início.')
                is_valid = False
        elif self.plantonista_turno_inicio.data or self.plantonista_turno_fim.data:
            self.plantonista_turno_fim.errors.append('Informe o início e o fim do plantão.')
            is_valid = False

        if tipo == 'plantonista':
            if not self.horas_previstas.data and not (
                self.plantonista_turno_inicio.data and self.plantonista_turno_fim.data
            ):
                self.horas_previstas.errors.append('Informe as horas previstas ou os horários do plantão.')
                is_valid = False
            if not (self.valor_hora.data and self.horas_previstas.data) and not self.valor.data:
                self.valor.errors.append('Informe o valor total ou o valor por hora para plantonistas.')
                is_valid = False
            if not self.plantonista_id.data and not (
                self.plantonista_turno_inicio.data and self.plantonista_turno_fim.data
            ):
                self.plantonista_id.errors.append('Selecione uma escala existente ou preencha o plantão.')
                is_valid = False

        return is_valid


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
    clinica_id = HiddenField(validators=[DataRequired()])
    descricao = StringField('Descrição', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Salvar')


class AppointmentForm(FlaskForm):
    """Formulário para agendamento de consultas."""

    tutor_id = SelectField(
        'Tutor',
        coerce=int,
        validators=[Optional()],
        default=0,
    )

    animal_id = SelectField(
        'Animal',
        coerce=int,
        validators=[DataRequired()],
        validate_choice=False,
    )

    veterinario_id = SelectField(
        'Veterinário',
        coerce=int,
        validators=[DataRequired()],
        validate_choice=False,
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

    animal_data = None

    def populate_animals(
        self,
        animals,
        *,
        restrict_tutors=False,
        selected_tutor_id=None,
        allow_all_option=True,
    ):
        """Populate animal choices and tutor selector metadata."""

        def _normalize_tutor_name(name, tutor_id):
            if name:
                return name
            if tutor_id:
                return f'Tutor #{tutor_id}'
            return 'Tutor não atribuído'

        records = []
        tutor_map = {}
        for animal in animals:
            tutor_id = getattr(animal, 'user_id', None)
            owner = getattr(animal, 'owner', None)
            tutor_name = getattr(owner, 'name', None)
            animal_id = getattr(animal, 'id', None)
            if animal_id is None:
                continue
            record = {
                'id': animal_id,
                'name': getattr(animal, 'name', None) or f'Animal #{animal_id}',
                'tutor_id': tutor_id,
                'tutor_name': _normalize_tutor_name(tutor_name, tutor_id),
            }
            records.append(record)
            if tutor_id:
                tutor_map[tutor_id] = _normalize_tutor_name(tutor_name, tutor_id)

        def _format_animal_label(item):
            name = item.get('name') or f"Animal #{item.get('id', '—')}"
            tutor_name = item.get('tutor_name')
            if tutor_name:
                return f"{name} — {tutor_name}"
            return name

        records.sort(key=lambda item: ((item['name'] or '').lower(), item['id']))
        self.animal_data = records
        self.animal_id.choices = [
            (item['id'], _format_animal_label(item)) for item in records
        ]

        if not hasattr(self, 'tutor_id'):
            return

        sorted_tutors = sorted(
            tutor_map.items(),
            key=lambda entry: (entry[1] or '').lower(),
        )

        choices = []
        if allow_all_option and (not restrict_tutors or len(sorted_tutors) > 1):
            choices.append((0, 'Todos os tutores'))
        choices.extend(
            (tutor_id, name or f'Tutor #{tutor_id}')
            for tutor_id, name in sorted_tutors
        )

        if not choices:
            if allow_all_option:
                choices = [(0, 'Todos os tutores')]
            else:
                choices = [(0, 'Nenhum tutor disponível')]

        self.tutor_id.choices = choices

        available_ids = {choice[0] for choice in choices}
        resolved_tutor_id = selected_tutor_id if selected_tutor_id in available_ids else None
        if resolved_tutor_id is None:
            if restrict_tutors and sorted_tutors:
                resolved_tutor_id = sorted_tutors[0][0]
            elif 0 in available_ids:
                resolved_tutor_id = 0
            elif sorted_tutors:
                resolved_tutor_id = sorted_tutors[0][0]
            else:
                resolved_tutor_id = 0

        self.tutor_id.data = resolved_tutor_id

    def __init__(
        self,
        tutor=None,
        is_veterinario=False,
        clinic_ids=None,
        *args,
        **kwargs,
    ):
        self._restricted_tutor_id = getattr(tutor, 'id', None)
        self._clinic_scope_ids = []
        require_clinic_scope = kwargs.pop('require_clinic_scope', None)
        if clinic_ids is not None:
            if isinstance(clinic_ids, (list, tuple, set)):
                candidates = clinic_ids
            else:
                candidates = [clinic_ids]
            for candidate in candidates:
                try:
                    value = int(candidate)
                except (TypeError, ValueError):
                    continue
                if value and value not in self._clinic_scope_ids:
                    self._clinic_scope_ids.append(value)
        self._clinic_scope_ids = [cid for cid in self._clinic_scope_ids if cid]
        if require_clinic_scope is None:
            require_clinic_scope = bool(is_veterinario)
        self._clinic_scope_required = bool(require_clinic_scope)
        self._is_veterinario_context = bool(is_veterinario)
        super().__init__(*args, **kwargs)
        from models import Animal, Veterinario, Clinica

        self._restricted_tutor_id = getattr(tutor, 'id', None)

        def _build_animal_query():
            query = Animal.query.filter(Animal.removido_em.is_(None))
            if self._clinic_scope_required and not self._clinic_scope_ids:
                return query.filter(false())
            if self._clinic_scope_ids:
                query = query.filter(Animal.clinica_id.in_(self._clinic_scope_ids))
            if self._restricted_tutor_id is not None:
                query = query.filter(Animal.user_id == self._restricted_tutor_id)
            return query

        def _build_veterinarian_query():
            query = Veterinario.query
            if self._clinic_scope_ids:
                query = query.filter(
                    or_(
                        Veterinario.clinica_id.in_(self._clinic_scope_ids),
                        Veterinario.clinicas.any(Clinica.id.in_(self._clinic_scope_ids)),
                    )
                )
            return query

        self._animal_query_factory = _build_animal_query
        self._veterinarian_query_factory = _build_veterinarian_query

        selected_animal_id = self.animal_id.data
        animal_query = self._animal_query_factory()
        if selected_animal_id:
            animals = animal_query.filter(Animal.id == selected_animal_id).all()
        else:
            animals = animal_query.all()

        restrict_tutors = self._restricted_tutor_id is not None
        allow_all = not restrict_tutors
        selected_tutor_id = None
        if restrict_tutors:
            selected_tutor_id = self._restricted_tutor_id
        elif animals:
            selected_tutor_id = getattr(animals[0], 'user_id', None)
        else:
            selected_tutor_id = self.tutor_id.data

        self.populate_animals(
            animals,
            restrict_tutors=restrict_tutors,
            selected_tutor_id=selected_tutor_id,
            allow_all_option=allow_all,
        )

        selected_vet_id = self.veterinario_id.data
        veterinarian_query = self._veterinarian_query_factory()
        if selected_vet_id:
            veterinarios = veterinarian_query.filter(Veterinario.id == selected_vet_id).all()
        else:
            veterinarios = veterinarian_query.all()

        def _vet_label(vet):
            return getattr(getattr(vet, 'user', None), 'name', None) or str(vet.id)

        self.veterinario_id.choices = [
            (v.id, _vet_label(v)) for v in veterinarios
        ]

        if selected_vet_id and selected_vet_id not in {choice[0] for choice in self.veterinario_id.choices}:
            vet = Veterinario.query.get(selected_vet_id)
            if vet:
                self.veterinario_id.choices.append((vet.id, _vet_label(vet)))

        if not self.kind.data:
            self.kind.data = 'consulta'

    def _animal_lookup_query(self):
        from models import Animal

        query = Animal.query.filter(Animal.removido_em.is_(None))
        if self._clinic_scope_required and not self._clinic_scope_ids:
            return query.filter(false())
        if self._clinic_scope_ids:
            query = query.filter(Animal.clinica_id.in_(self._clinic_scope_ids))
        if self._restricted_tutor_id is not None:
            query = query.filter(Animal.user_id == self._restricted_tutor_id)
        return query

    def _veterinarian_lookup_query(self):
        from models import Veterinario, Clinica

        query = Veterinario.query
        if self._clinic_scope_ids:
            query = query.filter(
                or_(
                    Veterinario.clinica_id.in_(self._clinic_scope_ids),
                    Veterinario.clinicas.any(Clinica.id.in_(self._clinic_scope_ids)),
                )
            )
        return query

    def validate_animal_id(self, field):
        if not field.data:
            raise ValidationError('Selecione um animal válido.')

        query = self._animal_lookup_query()
        from models import Animal

        animal = query.filter(Animal.id == field.data).first()
        if not animal:
            raise ValidationError('Selecione um animal válido para esta clínica.')

    def validate_veterinario_id(self, field):
        if not field.data:
            raise ValidationError('Selecione um veterinário válido.')

        query = self._veterinarian_lookup_query()
        from models import Veterinario

        veterinario = query.filter(Veterinario.id == field.data).first()
        if not veterinario:
            raise ValidationError('Selecione um veterinário válido para esta clínica.')

