from .extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import enum
from sqlalchemy import Enum

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
    __tablename__ = 'animal'  # força o nome da tabela
    __table_args__ = {'extend_existing': True}  # evita conflito de redefinição

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    species = db.Column(db.String(50))  # cão, gato, etc.
    breed = db.Column(db.String(100))
    age = db.Column(db.String(50))
    peso = db.Column(db.Float, nullable=True)  # em kg
    date_of_birth = db.Column(db.Date, nullable=True)  # 🆕
    sex = db.Column(db.String(10))  # macho, fêmea
    description = db.Column(db.Text)
    status = db.Column(db.String(20))  # disponível, adotado, vendido
    image = db.Column(db.String(200))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

 # Novos campos adicionados com segurança:
    modo = db.Column(db.String(20), default='doação')  # doação, venda, adotado
    price = db.Column(db.Float, nullable=True)         # apenas se for venda
    vacinas = db.relationship('Vacina', backref='animal', cascade='all, delete-orphan')


    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)



    photos = db.relationship('AnimalPhoto', backref='animal', cascade='all, delete-orphan', lazy=True)
    transactions = db.relationship('Transaction', backref='animal', cascade='all, delete-orphan', lazy=True)
    favorites = db.relationship('Favorite', backref='animal', cascade='all, delete-orphan', lazy=True)




    microchip_number = db.Column(db.String(50), nullable=True)  # 🆕 novo campo
    neutered = db.Column(db.Boolean, default=False)  # 🆕
    health_plan = db.Column(db.String(100), nullable=True)  # 🆕

    removido_em = db.Column(db.DateTime, nullable=True)  # Soft delete marker


    added_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # 🆕
    added_by = db.relationship('User', foreign_keys=[added_by_id])  # 🆕



    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    clinica = db.relationship('Clinica', backref='animais')

    is_alive = db.Column(db.Boolean, default=True)  # Animal está vivo ou já faleceu

    falecido_em = db.Column(db.DateTime, nullable=True)  # opcional




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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



# models.py


class BlocoPrescricao(db.Model):
    __tablename__ = 'bloco_prescricao'

    id = db.Column(db.Integer, primary_key=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    consulta = db.relationship('Consulta', backref=db.backref('blocos_prescricao', cascade='all, delete-orphan', lazy=True))
    prescricoes = db.relationship('Prescricao', backref='bloco', cascade='all, delete-orphan')
    instrucoes_gerais = db.Column(db.Text)


class Prescricao(db.Model):
    __tablename__ = 'prescricao'

    id = db.Column(db.Integer, primary_key=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=False)
    bloco_id = db.Column(db.Integer, db.ForeignKey('bloco_prescricao.id'))  # 🆕

    medicamento = db.Column(db.String(100), nullable=False)
    dosagem = db.Column(db.String(100))
    frequencia = db.Column(db.String(100))
    duracao = db.Column(db.String(100))
    observacoes = db.Column(db.Text)
    data_prescricao = db.Column(db.DateTime, default=datetime.utcnow)

    consulta = db.relationship('Consulta', backref=db.backref('prescricoes', cascade='all, delete-orphan', lazy=True))

    def __repr__(self):
        return f'<Prescrição {self.medicamento} para Consulta {self.consulta_id}>'


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
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=False)
    observacoes_gerais = db.Column(db.Text)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    consulta = db.relationship('Consulta', backref=db.backref('blocos_exames', cascade='all, delete-orphan', lazy=True))
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


class Racao(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    tipo_racao_id = db.Column(db.Integer, db.ForeignKey('tipo_racao.id'), nullable=False)

    peso_animal = db.Column(db.Float)
    recomendacao_custom = db.Column(db.Float)  # se quiser ajustar a recomendação
    observacoes_racao = db.Column(db.Text)

    data_cadastro = db.Column(db.DateTime, default=datetime.utcnow)

    animal = db.relationship('Animal', backref=db.backref('racoes', lazy=True, cascade='all, delete-orphan'))
    tipo_racao = db.relationship('TipoRacao', backref=db.backref('usos', lazy=True))



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
