try:
    from extensions import db
except ImportError:
    from .extensions import db

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import enum
from sqlalchemy import Enum
from enum import Enum
from sqlalchemy import Enum as PgEnum




class Endereco(db.Model):
    __tablename__ = 'endereco'
    id = db.Column(db.Integer, primary_key=True)
    cep = db.Column(db.String(9), nullable=False)  # Ex: 14620-000
    rua = db.Column(db.String(120), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    complemento = db.Column(db.String(100), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(2), nullable=True)  # Ex: SP

    def __repr__(self):
        return f"{self.rua}, {self.numero or 's/n'} - {self.bairro}, {self.cidade}/{self.estado} - {self.cep}"

    # relação 1‑para‑1 de volta
    pickup_location = db.relationship(
        "PickupLocation",
        back_populates="endereco",
        uselist=False
    )

    @property
    def full(self):
        """Rua, número, bairro – cidade/UF – CEP."""
        partes = []
        if self.rua:
            partes.append(f"{self.rua}{', ' + self.numero if self.numero else ''}")
        if self.bairro:
            partes.append(self.bairro)
        if self.cidade and self.estado:
            partes.append(f"{self.cidade}/{self.estado}")
        if self.cep:
            partes.append(f"CEP {self.cep}")
        return " – ".join(partes)


class UserRole(enum.Enum):
    adotante = 'adotante'
    doador = 'doador'
    veterinario = 'veterinario'
    admin = 'admin'


# Usuário
class User(UserMixin, db.Model):
    __table_args__ = {'extend_existing': True}  # <- isso permite redefinir sem erro

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='adotante', nullable=True)



    phone = db.Column(db.String(20))

    address = db.Column(db.String(200))
    endereco_id = db.Column(db.Integer, db.ForeignKey('endereco.id'), nullable=True)
    endereco = db.relationship('Endereco', backref='usuarios')



    profile_photo = db.Column(db.String(200))

    # 🆕 Novos campos adicionados:
    cpf = db.Column(db.String(14), unique=True, nullable=True)  # Ex: 123.456.789-00
    rg = db.Column(db.String(20), nullable=True)               # Ex: 12.345.678-9
    date_of_birth = db.Column(db.Date, nullable=True)          # Armazenado como data
    worker = db.Column(db.String(50), nullable=True)
    # dentro da classe User
    veterinario = db.relationship('Veterinario', back_populates='user', uselist=False)




    animals = db.relationship(
        'Animal',
        backref='owner',
        cascade="all, delete",
        lazy=True,
        foreign_keys='Animal.user_id'  # 🛠 THIS LINE
    )




    # Correção dos campos:
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', back_populates='sender', lazy=True)
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id', back_populates='receiver', lazy=True)

    given_reviews = db.relationship('Review', foreign_keys='Review.reviewer_id', backref='reviewer', lazy=True)
    received_reviews = db.relationship('Review', foreign_keys='Review.reviewed_user_id', backref='reviewed', lazy=True)
    favorites = db.relationship('Favorite', backref='user', lazy=True)

    added_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # 🆕
    added_by = db.relationship('User', remote_side=[id], backref='users_added')  # 🆕



    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    clinica = db.relationship('Clinica', backref='usuarios')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)




    @property
    def added_by_display(self):
        return self.added_by.name if self.added_by else "N/A"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __str__(self):
        return f'{self.name} ({self.email})'









class VeterinarianAccess(db.Model):
    __table_args__ = {'extend_existing': True}  # ← ESSA LINHA

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    vet_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_granted = db.Column(db.DateTime, default=datetime.utcnow)

    animal = db.relationship('Animal', backref='vet_accesses')
    veterinarian = db.relationship('User', backref='authorized_animals')



# Animal
class Animal(db.Model):
    __tablename__ = 'animal'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    species = db.Column(db.String(50))
    breed = db.Column(db.String(100))
    age = db.Column(db.String(50))
    peso = db.Column(db.Float, nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    sex = db.Column(db.String(10))
    description = db.Column(db.Text)
    status = db.Column(db.String(20))
    image = db.Column(db.String(200))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

    modo = db.Column(db.String(20), default='doação')
    price = db.Column(db.Float, nullable=True)
    vacinas = db.relationship('Vacina', backref='animal', cascade='all, delete-orphan')

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    photos = db.relationship('AnimalPhoto', backref='animal', cascade='all, delete-orphan', lazy=True)
    transactions = db.relationship('Transaction', backref='animal', cascade='all, delete-orphan', lazy=True)
    favorites = db.relationship('Favorite', backref='animal', cascade='all, delete-orphan', lazy=True)

    microchip_number = db.Column(db.String(50), nullable=True)
    neutered = db.Column(db.Boolean, default=False)
    health_plan = db.Column(db.String(100), nullable=True)

    removido_em = db.Column(db.DateTime, nullable=True)

    added_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    added_by = db.relationship('User', foreign_keys=[added_by_id])

    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    clinica = db.relationship('Clinica', backref='animais')

    is_alive = db.Column(db.Boolean, default=True)
    falecido_em = db.Column(db.DateTime, nullable=True)

    species_id = db.Column(db.Integer, db.ForeignKey('species.id'))
    breed_id   = db.Column(db.Integer, db.ForeignKey('breed.id'))

    species = db.relationship('Species')
    breed   = db.relationship('Breed')


    blocos_prescricao = db.relationship(
        'BlocoPrescricao',
        back_populates='animal',
        cascade='all, delete-orphan'
    )

    def __str__(self):
        return f"{self.name} ({self.species.name if self.species else self.species})"

    

class Species(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    def __str__(self):
        return self.name  # 👈 Isso garante que apareça como texto legível no admin

class Breed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    species_id = db.Column(db.Integer, db.ForeignKey('species.id'), nullable=False)
    species = db.relationship('Species', backref='breeds')

    def __str__(self):
        return self.name



# Transações
class Transaction(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20))  # adoção, doação, venda, compra
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20))  # pendente, concluída, cancelada

    from_user = db.relationship('User', foreign_keys=[from_user_id], backref='transacoes_enviadas')
    to_user = db.relationship('User', foreign_keys=[to_user_id], backref='transacoes_recebidas')



class Message(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)

    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=True)

    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # Relações
    sender = db.relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')
    animal = db.relationship('Animal', backref=db.backref('messages', cascade='all, delete-orphan'))

    lida = db.Column(db.Boolean, default=False)


    def __repr__(self):
        return f'<Message from {self.sender_id} to {self.receiver_id}>'




class Interest(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='interesses')
    animal = db.relationship('Animal', backref=db.backref('interesses', cascade='all, delete-orphan'))



class ConsultaToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)




class Consulta(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # veterinário
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Campos principais da consulta
    queixa_principal = db.Column(db.Text)
    historico_clinico = db.Column(db.Text)
    exame_fisico = db.Column(db.Text)
    conduta = db.Column(db.Text)
    prescricao = db.Column(db.Text)
    exames_solicitados = db.Column(db.Text)

    # Status da consulta (em andamento, finalizada, etc)
    status = db.Column(db.String(20), default='in_progress')

    # Relacionamentos (se quiser acessar animal ou vet diretamente)
    animal = db.relationship('Animal', backref=db.backref('consultas', cascade='all, delete-orphan'))
    veterinario = db.relationship('User', backref='consultas', foreign_keys=[created_by])



# models.py

class BlocoPrescricao(db.Model):
    __tablename__ = 'bloco_prescricao'

    id = db.Column(db.Integer, primary_key=True)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    prescricoes = db.relationship('Prescricao', backref='bloco', cascade='all, delete-orphan')
    instrucoes_gerais = db.Column(db.Text)

    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    animal = db.relationship('Animal', back_populates='blocos_prescricao')

class Prescricao(db.Model):
    __tablename__ = 'prescricao'

    id = db.Column(db.Integer, primary_key=True)
    bloco_id = db.Column(db.Integer, db.ForeignKey('bloco_prescricao.id'))  # pode manter se quiser blocos

    medicamento = db.Column(db.String(100), nullable=False)
    dosagem = db.Column(db.String(100))
    frequencia = db.Column(db.String(100))
    duracao = db.Column(db.String(100))
    observacoes = db.Column(db.Text)
    data_prescricao = db.Column(db.DateTime, default=datetime.utcnow)

    # em Prescricao
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    animal = db.relationship('Animal', backref='prescricoes')  # em Prescricao

    def __repr__(self):
        return f'<Prescrição {self.medicamento} (ID: {self.id})>'


class Clinica(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    cnpj = db.Column(db.String(18))
    endereco = db.Column(db.String(200))
    telefone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    logotipo = db.Column(db.String(200))  # caminho para imagem do logo

    veterinarios = db.relationship('Veterinario', backref='clinica', lazy=True)


    def __str__(self):
        return f'{self.nome} ({self.cnpj})'

class Veterinario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crmv = db.Column(db.String(20), nullable=False)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'))

    user = db.relationship('User', back_populates='veterinario', uselist=False)

    def __str__(self):
        return f"{self.user.name} (CRMV: {self.crmv})"



class Medicamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    classificacao = db.Column(db.String(100))  # 🆕 antibiótico, anti-inflamatório, etc.
    principio_ativo = db.Column(db.String(100))  # opcional
    via_administracao = db.Column(db.String(50))  # oral, IM, IV...
    dosagem_recomendada = db.Column(db.String(100))  # Ex: 5 mg/kg SID
    frequencia = db.Column(db.String(50))  # Ex: SID, BID, TID
    duracao_tratamento = db.Column(db.String(100))  # Ex: 7 dias
    observacoes = db.Column(db.Text)  # para contraindicações, interações, etc.
    bula = db.Column(db.Text)  # 🆕 Texto completo da bula, opcional

    apresentacoes = db.relationship('ApresentacaoMedicamento', backref='medicamento', cascade='all, delete-orphan')

    def __str__(self):
        return self.nome

class ApresentacaoMedicamento(db.Model):
    __tablename__ = 'apresentacao_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    medicamento_id = db.Column(db.Integer, db.ForeignKey('medicamento.id'), nullable=False)

    forma = db.Column(db.String(50), nullable=False)          # cápsula, líquido, etc.
    concentracao = db.Column(db.String(100), nullable=False)  # Ex: 50 mg/mL, 500 mg/cápsula

    def __str__(self):
        return f"{self.medicamento.nome} – {self.forma} ({self.concentracao})"


class ExameModelo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)  # ex: Hemograma, Raio-X...

class BlocoExames(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)  # <- novo campo
    observacoes_gerais = db.Column(db.Text)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    animal = db.relationship('Animal', backref=db.backref('blocos_exames', cascade='all, delete-orphan', lazy=True))
    exames = db.relationship('ExameSolicitado', backref='bloco', cascade='all, delete-orphan')

class ExameSolicitado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bloco_id = db.Column(db.Integer, db.ForeignKey('bloco_exames.id'), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    justificativa = db.Column(db.Text)


class VacinaModelo(db.Model):
    __tablename__ = 'vacina_modelo'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))  # Opcional, mas útil para o frontend

    def __repr__(self):
        return f'<VacinaModelo {self.nome}>'


class Vacina(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)

    nome = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))  # Campanha, Obrigatória, Reforço
    data = db.Column(db.Date)        # Data da aplicação
    observacoes = db.Column(db.Text)
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)


class TipoRacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marca = db.Column(db.String(100), nullable=False)
    linha = db.Column(db.String(100))  # Ex: "Premium Filhotes", "Golden Fórmula"
    recomendacao = db.Column(db.Float)  # g/kg/dia
    observacoes = db.Column(db.Text)
    peso_pacote_kg = db.Column(db.Float, default=15.0)  # Peso do pacote (kg)


class Racao(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    tipo_racao_id = db.Column(db.Integer, db.ForeignKey('tipo_racao.id'), nullable=False)

    recomendacao_custom = db.Column(db.Float)  # se quiser ajustar a recomendação
    observacoes_racao = db.Column(db.Text)

    data_cadastro = db.Column(db.DateTime, default=datetime.utcnow)

    animal = db.relationship('Animal', backref=db.backref('racoes', lazy=True, cascade='all, delete-orphan'))
    tipo_racao = db.relationship('TipoRacao', backref=db.backref('usos', lazy=True))

    preco_pago = db.Column(db.Float)  # R$ que o tutor paga
    tamanho_embalagem = db.Column(db.String(50))  # Ex: "15kg", "10,1kg", etc.



# to implement in the future!


# Avaliações de usuários
class Review(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviewed_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1 a 5
    comment = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)


# Fotos extras dos animais
class AnimalPhoto(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    image_url = db.Column(db.String(200))
    is_primary = db.Column(db.Boolean, default=False)


# Animais favoritados por usuários
class Favorite(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)

# Loja virtual
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(200))

    # Items de pedido associados ao produto. O cascade facilita remover os
    # OrderItem relacionados quando o produto é excluído.
    order_items = db.relationship(
        "OrderItem",
        back_populates="product",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"{self.name} (R$ {self.price})"


class ProductPhoto(db.Model):
    """Fotos adicionais para produtos."""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    image_url = db.Column(db.String(200))

    product = db.relationship('Product', backref='extra_photos')






class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='orders')
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')




    def total_value(self):
        """Calcula o valor total do pedido com base nos produtos e quantidades."""
        total = 0.0
        for item in self.items:
            if item.product:
                total += (item.product.price or 0) * item.quantity
        return total

class OrderItem(db.Model):
    __tablename__ = "order_item"

    id          = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id  = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    # back_populates permite acesso recíproco a partir de Product.order_items
    product     = db.relationship("Product", back_populates="order_items")

    item_name   = db.Column(db.String(100), nullable=False)
    quantity    = db.Column(db.Integer, nullable=False, default=1)
    unit_price  = db.Column(db.Numeric(10, 2), nullable=True)   # NOVO 👈


class DeliveryRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pendente')
    worker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    canceled_at = db.Column(db.DateTime, nullable=True)
    canceled_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    order = db.relationship('Order', backref='delivery_requests')
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    worker = db.relationship('User', foreign_keys=[worker_id])
    canceled_by = db.relationship('User', foreign_keys=[canceled_by_id])
    pickup_id   = db.Column(db.Integer, db.ForeignKey('pickup_location.id'))
    pickup      = db.relationship('PickupLocation')



class PickupLocation(db.Model):
    __tablename__ = "pickup_location"
    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(120))           # “Galpão Central”, “Hub Ribeirão”…
    endereco_id = db.Column(db.Integer, db.ForeignKey('endereco.id'))
    endereco    = db.relationship('Endereco')
    ativo       = db.Column(db.Boolean, default=True) # permite desativar pontos


    endereco    = db.relationship(
        "Endereco",
        back_populates="pickup_location",
        uselist=False
    )



class PaymentMethod(Enum):
    PIX = 'PIX'
    CREDIT_CARD = 'Cartão de Crédito'
    DEBIT_CARD = 'Cartão de Débito'
    BOLETO = 'Boleto'

class PaymentStatus(Enum):
    PENDING = 'Pendente'
    COMPLETED = 'Concluído'
    FAILED = 'Falhou'

class Payment(db.Model):
    __tablename__  = "payment"
    __table_args__ = (
        db.UniqueConstraint("transaction_id",  name="uq_payment_tx"),
        db.UniqueConstraint("external_reference", name="uq_payment_extref"),
    )

    id       = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)

    # ✅ fica só esta definição
    order = db.relationship(
        "Order",
        backref=db.backref("payment", uselist=False, cascade="all, delete-orphan"),
        uselist=False,
    )

    method = db.Column(
        PgEnum(PaymentMethod, name="paymentmethod", create_type=False),
        nullable=False,
    )
    status = db.Column(
        PgEnum(PaymentStatus, name="paymentstatus", create_type=False),
        default=PaymentStatus.PENDING,
        index=True,
    )

    transaction_id     = db.Column(db.String(255))
    external_reference = db.Column(db.String(255))
    mercado_pago_id    = db.Column(db.String(64))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    user    = db.relationship("User", backref="payments")

    init_point = db.Column(db.String)

    # NOVO: valor congelado do pagamento
    amount = db.Column(db.Numeric(10, 2), nullable=True)  # Adicione este campo


# -------------------------- Planos de Saúde ---------------------------

class HealthPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f"{self.name} (R$ {self.price})"


class HealthSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('health_plan.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))

    active = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=True)

    animal = db.relationship('Animal', backref=db.backref('health_subscriptions', cascade='all, delete-orphan'))
    plan = db.relationship('HealthPlan', backref='subscriptions')
    user = db.relationship('User', backref='health_subscriptions')
    payment = db.relationship('Payment', backref='subscriptions')

    def __repr__(self):
        return f"{self.animal.name} – {self.plan.name}"






















#testing sandbox
class PendingWebhook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mp_id = db.Column(db.BigInteger, unique=True)
    attempts = db.Column(db.Integer, default=0)
