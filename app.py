import uuid


from flask import current_app

import logging
import hashlib
import hmac

import os

import boto3

from dotenv import load_dotenv
load_dotenv()

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

bucket_name = os.getenv("S3_BUCKET_NAME")

def upload_to_s3(file, filename, folder="uploads"):
    try:
        s3_path = f"{folder}/{filename}"
        s3.upload_fileobj(
            file,
            bucket_name,
            s3_path,
            ExtraArgs={"ContentType": file.content_type}
        )
        return f"https://{bucket_name}.s3.amazonaws.com/{s3_path}"
    except Exception as e:
        print(f"[ERRO S3] Falha ao enviar para o S3: {e}")
        return None



import os



from flask import Flask

try:
    from config import Config
except ImportError:
    from .config import Config


try:
    from extensions import db, migrate, mail, login, session
except ImportError:
    from .extensions import db, migrate, mail, login, session

# Cria o diretório instance (caso não exista)
instance_path = os.path.join(os.getcwd(), 'instance')
os.makedirs(instance_path, exist_ok=True)

# Cria o app Flask
app = Flask(__name__, instance_path=instance_path)
app.config.from_object(Config)

app.config['FRONTEND_URL'] = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:5000')


print(f"FRONTEND_URL carregado: {app.config['FRONTEND_URL']}")


# Inicializa as extensões
db.init_app(app)
migrate.init_app(app, db)
mail.init_app(app)
login.init_app(app)
session.init_app(app)





from io import BytesIO


from datetime import datetime
import pytz

# Fuso horário de São Paulo
br_tz = pytz.timezone('America/Sao_Paulo')

# Filtro para converter datetime UTC para o fuso de Brasília
def format_datetime_brazil(value, format="%d/%m/%Y %H:%M"):
    if value is None:
        return ""
    if value.tzinfo is None:
        value = pytz.utc.localize(value)
    local_dt = value.astimezone(br_tz)
    return local_dt.strftime(format)

app.jinja_env.filters['datetime_brazil'] = format_datetime_brazil







from flask_login import login_user
from dateutil.relativedelta import relativedelta
from datetime import timedelta
import secrets
import qrcode
import base64

try:
    from forms import (
        MessageForm,
        RegistrationForm,
        LoginForm,
        AnimalForm,
        EditProfileForm,
        ResetPasswordRequestForm,
        ResetPasswordForm,
        OrderItemForm,
        DeliveryRequestForm,
        AddToCartForm,
    )
except ImportError:
    from .forms import (
        MessageForm,
        RegistrationForm,
        LoginForm,
        AnimalForm,
        EditProfileForm,
        ResetPasswordRequestForm,
        ResetPasswordForm,
        OrderItemForm,
        DeliveryRequestForm,
        AddToCartForm,
    )

try:
    from admin import init_admin, _is_admin
except ImportError:
    from .admin import init_admin, _is_admin


from flask_migrate import Migrate, upgrade, migrate, init



from flask_sqlalchemy import SQLAlchemy






from flask_session import Session
from flask_login import LoginManager, login_required, current_user, logout_user

try:
    from models import *
except ImportError:
    from .models import *

# Reimporta explicitamente o objeto `db` das extensões para evitar
# possíveis conflitos de importação tanto quando o módulo é executado
# diretamente quanto quando é importado como parte do pacote
try:
    from extensions import db as _db
except ImportError:  # quando importado como pacote
    from .extensions import db as _db
db = _db

from wtforms.fields import SelectField
from flask import Flask, jsonify, render_template, redirect, url_for, request, session, flash, abort


import sys
import os
from werkzeug.utils import secure_filename


from math import ceil

try:
    from helpers import calcular_idade, parse_data_nascimento
except ImportError:
    from .helpers import calcular_idade, parse_data_nascimento

from flask_mail import Mail, Message as MailMessage

from flask_mail import Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'gpt.assistente.orlandia@gmail.com'
app.config['MAIL_PASSWORD'] = 'SENHA_DE_APP'  # ← Cole a senha de aplicativo aqui
app.config['MAIL_DEFAULT_SENDER'] = ('PetOrlândia', 'gpt.assistente.orlandia@gmail.com')

mail = Mail(app)



sys.path.append(os.path.dirname(os.path.abspath(__file__)))


import os

instance_path = os.path.join(os.getcwd(), 'instance')
os.makedirs(instance_path, exist_ok=True)




app.config.from_object(Config)

 
migrate = Migrate(app, db)

mail = Mail(app)  # ✅ ESSA LINHA ESTAVA FALTANDO
login = LoginManager(app)


@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


login.login_view = 'login'


app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


# Após db.init_app(app)
migrate = Migrate(app, db)


app.config['SERVER_NAME'] = 'orange-space-pancake-j9456jjjv9vcqrxx-5000.app.github.dev'


with app.app_context():
    init_admin(app)      # ⬅️ Primeiro registra o admin e os modelos
  #  db.create_all()      # ⬅️ Só depois chama o create_all()


@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


from itsdangerous import URLSafeTimedSerializer




s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

@app.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = s.dumps(user.email, salt='password-reset-salt')
            base_url = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:5000')
            link = f"{base_url}{url_for('reset_password', token=token)}"

            msg = MailMessage(
                subject='Redefinir sua senha - PetOrlândia',
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[user.email],
                body=f'Clique no link para redefinir sua senha: {link}',
                html=f""" 
                    <!DOCTYPE html>
                    <html lang="pt-BR">
                    <head><meta charset="UTF-8"><title>Redefinição de Senha</title></head>
                    <body style="font-family: Arial; padding: 20px;">
                        <h2>🐾 PetOrlândia</h2>
                        <p>Recebemos uma solicitação para redefinir sua senha.</p>
                        <p><a href="{link}" style="background:#0d6efd;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;">Redefinir Senha</a></p>
                        <p>Se você não solicitou, ignore este e-mail.</p>
                        <hr><small>PetOrlândia • Cuidando com amor dos seus melhores amigos</small>
                    </body>
                    </html>
                """
            )
            mail.send(msg)
            flash('Um e-mail foi enviado com instruções para redefinir sua senha.', 'info')
            return redirect(url_for('login'))
        flash('E-mail não encontrado.', 'danger')
    return render_template('reset_password_request.html', form=form)



@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)  # 1 hour
    except:
        flash('O link de redefinição expirou ou é inválido.', 'danger')
        return redirect(url_for('reset_password_request'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(form.password.data)  # Your User model must have set_password method
            db.session.commit()
            flash('Sua senha foi redefinida. Você já pode entrar!', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html', form=form)



#admin configuration

@app.route('/painel')
@login_required
def painel_dashboard():
    cards = [
        {"icon": "👤", "title": "Usuários", "description": f"Total: {User.query.count()}"},
        {"icon": "🐶", "title": "Animais", "description": f"Total: {Animal.query.count()}"},
        {"icon": "🏥", "title": "Clínicas", "description": f"Total: {Clinica.query.count()}"},
        {"icon": "💉", "title": "Vacinas", "description": f"Hoje: {VacinaModelo.query.count()}"},
        {"icon": "📋", "title": "Consultas", "description": f"Pendentes: {Consulta.query.filter_by(status='pendente').count()}"},
        {"icon": "💊", "title": "Prescrições", "description": f"Semana: {Prescricao.query.count()}"},
    ]
    return render_template('admin/admin_dashboard.html', cards=cards)



# Rota principal


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()

    if form.validate_on_submit():
        # Verifica se o e-mail já está em uso
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('Email já está em uso.', 'danger')
            return render_template('register.html', form=form)

        # Cria o endereço
        endereco = Endereco(
            cep=request.form.get('cep'),
            rua=request.form.get('rua'),
            numero=request.form.get('numero'),
            complemento=request.form.get('complemento'),
            bairro=request.form.get('bairro'),
            cidade=request.form.get('cidade'),
            estado=request.form.get('estado')
        )

        # Upload da foto de perfil para o S3
        photo_url = None
        if form.profile_photo.data:
            file = form.profile_photo.data
            filename = secure_filename(file.filename)
            photo_url = upload_to_s3(file, filename, folder="users")


        # Cria o usuário com a URL da imagem no S3
        user = User(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            profile_photo=photo_url,
            endereco=endereco
        )
        user.set_password(form.password.data)

        # Salva no banco
        db.session.add(endereco)
        db.session.add(user)
        db.session.commit()

        flash('Usuário registrado com sucesso!', 'success')
        return redirect(url_for('index'))

    return render_template('register.html', form=form, endereco=None)




@app.route('/add-animal', methods=['GET', 'POST'])
@login_required
def add_animal():
    form = AnimalForm()

    # Listas para o template
    species_list = Species.query.order_by(Species.name).all()
    breed_list = Breed.query.order_by(Breed.name).all()

    # Debug da requisição
    print("📥 Método da requisição:", request.method)
    print("📋 Dados recebidos:", request.form)

    if form.validate_on_submit():
        print("✅ Formulário validado com sucesso.")

        image_url = None
        if form.image.data:
            file = form.image.data
            original_filename = secure_filename(file.filename)
            filename = f"{uuid.uuid4().hex}_{original_filename}"
            print("🖼️ Upload de imagem iniciado:", filename)
            image_url = upload_to_s3(file, filename, folder="animals")
            print("✅ Upload concluído. URL:", image_url)

        # IDs das listas
        species_id = request.form.get("species_id", type=int)
        breed_id = request.form.get("breed_id", type=int)
        print("🔍 Species ID:", species_id)
        print("🔍 Breed ID:", breed_id)

        # Criação do animal
        animal = Animal(
            name=form.name.data,
            species_id=species_id,
            breed_id=breed_id,
            age=form.age.data,
            sex=form.sex.data,
            description=form.description.data,
            image=image_url,
            modo=form.modo.data,
            price=form.price.data if form.modo.data == 'venda' else None,
            status='disponível',
            owner=current_user,
            is_alive=True
        )

        db.session.add(animal)
        try:
            db.session.commit()
            print("✅ Animal salvo com ID:", animal.id)
            flash('Animal cadastrado com sucesso!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            print("❌ Erro ao salvar no banco:", str(e))
            flash('Erro ao salvar o animal.', 'danger')

    else:
        print("⚠️ Formulário inválido.")
        print("🧾 Erros do formulário:", form.errors)

    return render_template(
        'add_animal.html',
        form=form,
        species_list=species_list,
        breed_list=breed_list
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Email ou senha inválidos.', 'danger')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu com sucesso!', 'success')
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Garante que current_user.endereco exista para pré-preenchimento
    form = EditProfileForm(obj=current_user)

    if form.validate_on_submit():
        if not current_user.endereco:
            current_user.endereco = Endereco()


    form = EditProfileForm(obj=current_user)

    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.email = form.email.data
        current_user.phone = form.phone.data

        # Atualiza ou cria endereço
        endereco = current_user.endereco
        endereco.cep = request.form.get("cep")
        endereco.rua = request.form.get("rua")
        endereco.numero = request.form.get("numero")
        endereco.complemento = request.form.get("complemento")
        endereco.bairro = request.form.get("bairro")
        endereco.cidade = request.form.get("cidade")
        endereco.estado = request.form.get("estado")

        db.session.add(endereco)

        # Upload de imagem para S3 (se houver nova)
        if (
            form.profile_photo.data and
            hasattr(form.profile_photo.data, 'filename') and
            form.profile_photo.data.filename != ''
        ):
            file = form.profile_photo.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            current_user.profile_photo = upload_to_s3(file, filename, folder="profile_photos")

        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    # Transações recentes
    transactions = Transaction.query.filter(
        (Transaction.from_user_id == current_user.id) | (Transaction.to_user_id == current_user.id)
    ).order_by(Transaction.date.desc()).limit(10).all()

    return render_template(
        'profile.html',
        user=current_user,
        form=form,
        transactions=transactions
    )




@app.route('/animals')
def list_animals():
    page = request.args.get('page', 1, type=int)
    per_page = 9
    modo = request.args.get('modo')

    # Base query: ignora animais removidos
    query = Animal.query.filter(Animal.removido_em == None)

    # Filtro por modo
    if modo and modo.lower() != 'todos':
        query = query.filter_by(modo=modo)
    else:
        # Evita mostrar adotados para usuários não autorizados
        if not current_user.is_authenticated or current_user.worker not in ['veterinario', 'colaborador']:
            query = query.filter(Animal.modo != 'adotado')

    # Ordenação e paginação
    query = query.order_by(Animal.date_added.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    animals = pagination.items

    return render_template(
        'animals.html',
        animals=animals,
        page=page,
        total_pages=pagination.pages,
        modo=modo
    )




@app.route('/animal/<int:animal_id>/adotar', methods=['POST'])
@login_required
def adotar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if animal.status != 'disponível':
        flash('Este animal já foi adotado ou vendido.', 'danger')
        return redirect(url_for('list_animals'))

    animal.status = 'adotado'  # ou 'vendido', se for o caso
    animal.user_id = current_user.id  # <- transfere a posse do animal
    db.session.commit()

    db.session.commit()
    flash(f'Você adotou {animal.name} com sucesso!', 'success')
    return redirect(url_for('list_animals'))


@app.route('/animal/<int:animal_id>/editar', methods=['GET', 'POST'])
@app.route('/editar_animal/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def editar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if animal.user_id != current_user.id:
        flash('Você não tem permissão para editar este animal.', 'danger')
        return redirect(url_for('profile'))

    form = AnimalForm(obj=animal)

    species_list = Species.query.order_by(Species.name).all()
    breed_list = Breed.query.order_by(Breed.name).all()

    if form.validate_on_submit():
        form.populate_obj(animal)  # pega tudo do form automaticamente
        # Atualiza os relacionamentos manuais
        species_id = request.form.get('species_id')
        breed_id = request.form.get('breed_id')
        if species_id:
            animal.species_id = int(species_id)
        if breed_id:
            animal.breed_id = int(breed_id)

        db.session.commit()
        flash('Animal atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    return render_template('editar_animal.html',
                           form=form,
                           animal=animal,
                           species_list=species_list,
                           breed_list=breed_list)


@app.route('/mensagem/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def enviar_mensagem(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = MessageForm()

    if animal.user_id == current_user.id:
        flash("Você não pode enviar mensagem para si mesmo.", "warning")
        return redirect(url_for('list_animals'))

    if form.validate_on_submit():
        msg = Message(
            sender_id=current_user.id,
            receiver_id=animal.user_id,
            animal_id=animal.id,
            content=form.content.data
        )
        db.session.add(msg)
        db.session.commit()
        flash('Mensagem enviada com sucesso!', 'success')
        return redirect(url_for('list_animals'))

    return render_template('enviar_mensagem.html', form=form, animal=animal)


@app.route('/mensagem/<int:message_id>/aceitar', methods=['POST'])
@login_required
def aceitar_interesse(message_id):
    mensagem = Message.query.get_or_404(message_id)

    if mensagem.animal.owner.id != current_user.id:
        flash("Você não tem permissão para aceitar esse interesse.", "danger")
        return redirect(url_for('conversa', animal_id=mensagem.animal.id, user_id=mensagem.sender_id))

    animal = mensagem.animal
    animal.status = 'adotado'
    animal.user_id = mensagem.sender_id
    db.session.commit()

    flash(f"Você aceitou a adoção de {animal.name} por {mensagem.sender.name}.", "success")
    return redirect(url_for('conversa', animal_id=animal.id, user_id=mensagem.sender_id))


@app.route('/mensagens')
@login_required
def mensagens():
    mensagens_recebidas = current_user.received_messages
    return render_template('mensagens.html', mensagens=mensagens_recebidas)


@app.route('/conversa/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def conversa(animal_id, user_id):
    animal = Animal.query.get_or_404(animal_id)
    outro_usuario = User.query.get_or_404(user_id)
    interesse_existente = Interest.query.filter_by(
        user_id=outro_usuario.id, animal_id=animal.id).first()

    form = MessageForm()

    # Busca todas as mensagens entre current_user e outro_usuario sobre o animal
    mensagens = Message.query.filter(
        Message.animal_id == animal.id,
        ((Message.sender_id == current_user.id) & (Message.receiver_id == outro_usuario.id)) |
        ((Message.sender_id == outro_usuario.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()

    # Enviando nova mensagem
    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=outro_usuario.id,
            animal_id=animal.id,
            content=form.content.data,
            lida=False

        )
        db.session.add(nova_msg)
        db.session.commit()
        return redirect(url_for('conversa', animal_id=animal.id, user_id=outro_usuario.id))

    for m in mensagens:
        if m.receiver_id == current_user.id and not m.lida:
            m.lida = True
        db.session.commit()

    return render_template(
        'conversa.html',
        mensagens=mensagens,
        form=form,
        animal=animal,
        outro_usuario=outro_usuario,
        interesse_existente=interesse_existente
    )


@app.context_processor
def inject_unread_count():
    if current_user.is_authenticated:
        unread = Message.query.filter_by(receiver_id=current_user.id, lida=False).count()
        return dict(unread_messages=unread)
    return dict(unread_messages=0)


@app.context_processor
def inject_mp_public_key():
    """Disponibiliza a chave pública do Mercado Pago para os templates."""
    return dict(MERCADOPAGO_PUBLIC_KEY=current_app.config.get("MERCADOPAGO_PUBLIC_KEY"))


@app.route('/animal/<int:animal_id>/deletar', methods=['POST'])
@login_required
def deletar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if animal.removido_em:
        flash('Animal já foi removido anteriormente.', 'warning')
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    animal.removido_em = datetime.utcnow()
    db.session.commit()
    flash('Animal marcado como removido. Histórico preservado.', 'success')
    return redirect(url_for('list_animals'))


@app.route('/termo/interesse/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_interesse(animal_id, user_id):
    animal = Animal.query.get_or_404(animal_id)
    interessado = User.query.get_or_404(user_id)

    if request.method == 'POST':
        # Verifica se já existe um interesse registrado
        interesse_existente = Interest.query.filter_by(
            user_id=interessado.id, animal_id=animal.id).first()

        if not interesse_existente:
            # Cria novo interesse
            novo_interesse = Interest(user_id=interessado.id, animal_id=animal.id)
            db.session.add(novo_interesse)

            # Cria mensagem automática
            mensagem = Message(
                sender_id=current_user.id,
                receiver_id=animal.user_id,
                animal_id=animal.id,
                content=f"Tenho interesse em {'comprar' if animal.modo == 'venda' else 'adotar'} o animal {animal.name}.",
                lida=False
            )
            db.session.add(mensagem)
            db.session.commit()

            flash('Você demonstrou interesse. Aguardando aprovação do tutor.', 'info')
        else:
            flash('Você já demonstrou interesse anteriormente.', 'warning')

        return redirect(url_for('conversa', animal_id=animal.id, user_id=animal.user_id))

    data_atual = datetime.now().strftime('%d/%m/%Y')
    return render_template('termo_interesse.html', animal=animal, interessado=interessado, data_atual=data_atual)


# Função local de formatação, caso ainda não tenha no projeto
def formatar_telefone(telefone: str) -> str:
    telefone = ''.join(filter(str.isdigit, telefone))  # Remove qualquer coisa que não seja número
    if telefone.startswith('55'):
        return f"+{telefone}"
    elif telefone.startswith('0'):
        return f"+55{telefone[1:]}"
    elif len(telefone) == 11:
        return f"+55{telefone}"
    else:
        return f"+55{telefone}"


@app.route('/termo/transferencia/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_transferencia(animal_id, user_id):
    animal = Animal.query.get_or_404(animal_id)
    novo_dono = User.query.get_or_404(user_id)

    if animal.owner.id != current_user.id:
        flash("Você não tem permissão para transferir esse animal.", "danger")
        return redirect(url_for('profile'))

    if request.method == 'POST':
        # Transfere a tutoria
        animal.user_id = novo_dono.id
        animal.status = 'indisponível'
        animal.modo = 'adotado'

        # Cria a transação
        transacao = Transaction(
            animal_id=animal.id,
            from_user_id=current_user.id,
            to_user_id=novo_dono.id,
            type='adoção' if animal.modo == 'doação' else 'venda',
            status='concluída',
            date=datetime.utcnow()
        )
        db.session.add(transacao)

        # Envia uma mensagem interna para o novo tutor
        msg = Message(
            sender_id=current_user.id,
            receiver_id=novo_dono.id,
            animal_id=animal.id,
            content=f"Parabéns! Você agora é o tutor de {animal.name}. 🐾",
            lida=False
        )
        db.session.add(msg)

        # WhatsApp para o novo tutor
        if novo_dono.phone:
            numero_formatado = f"whatsapp:{formatar_telefone(novo_dono.phone)}"

            texto_wpp = f"Parabéns, {novo_dono.name}! Agora você é o tutor de {animal.name} pelo PetOrlândia. 🐶🐱"
            # Antes de chamar o envio
            print("=== Tentando enviar WhatsApp ===")
            print(f"Telefone formatado: {numero_formatado}")
            print(f"Texto: {texto_wpp}")

            try:
                enviar_mensagem_whatsapp(texto_wpp, numero_formatado)
            except Exception as e:
                print(f"Erro ao enviar WhatsApp: {e}")

        db.session.commit()

        flash(f'Tutoria de {animal.name} transferida para {novo_dono.name}.', 'success')
        return redirect(url_for('profile'))

    data_atual = datetime.now().strftime('%d/%m/%Y')
    return render_template('termo_transferencia.html', animal=animal, novo_dono=novo_dono)


@app.route('/animal/<int:animal_id>/planosaude', methods=['GET', 'POST'])
@login_required
def planosaude_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if animal.owner != current_user:
        flash("Você não tem permissão para acessar esse animal.", "danger")
        return redirect(url_for('profile'))

    # Aqui, você pode carregar um formulário ou exibir informações
    return render_template('planosaude_animal.html', animal=animal)


@app.route('/plano-saude')
@login_required
def plano_saude_overview():
    animais_do_usuario = Animal.query.filter_by(user_id=current_user.id).filter(Animal.removido_em == None).all()
    return render_template(
        'plano_saude_overview.html',
        animais=animais_do_usuario,
        user=current_user  # ← esta linha resolve o erro
    )




@app.route('/animal/<int:animal_id>/ficha')
@login_required
def ficha_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    tutor = animal.owner

    consultas = (Consulta.query
                 .filter_by(animal_id=animal.id, status='finalizada')
                 .order_by(Consulta.created_at.desc())
                 .all())

    blocos_prescricao = BlocoPrescricao.query.filter_by(animal_id=animal.id).all()
    blocos_exames = BlocoExames.query.filter_by(animal_id=animal.id).all()
    vacinas = Vacina.query.filter_by(animal_id=animal.id).all()

    return render_template(
        'ficha_animal.html',
        animal=animal,
        tutor=tutor,
        consultas=consultas,
        blocos_prescricao=blocos_prescricao,
        blocos_exames=blocos_exames,
        vacinas=vacinas
    )




@app.route('/animal/<int:animal_id>/editar_ficha', methods=['GET', 'POST'])
@login_required
def editar_ficha_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    # Dados fictícios para fins de edição simples (substituir por formulário real depois)
    if request.method == 'POST':
        nova_vacina = request.form.get("vacina")
        nova_consulta = request.form.get("consulta")
        novo_medicamento = request.form.get("medicamento")

        print(f"Vacina adicionada: {nova_vacina}")
        print(f"Consulta adicionada: {nova_consulta}")
        print(f"Medicação adicionada: {novo_medicamento}")

        flash("Informacões adicionadas com sucesso (simulação).", "success")
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    return render_template("editar_ficha.html", animal=animal)


@app.route('/generate_qr/<int:animal_id>')
@login_required
def generate_qr(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if current_user.id != animal.tutor_id:
        flash('Você não tem permissão para gerar o QR code deste animal.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal_id))

    # Gera token
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(minutes=10)  # por exemplo, 10 minutos

    qr_token = ConsultaToken(
        token=token,
        animal_id=animal.id,
        tutor_id=current_user.id,
        expires_at=expires
    )
    db.session.add(qr_token)
    db.session.commit()

    consulta_url = url_for('consulta_qr', token=token, _external=True)
    img = qrcode.make(consulta_url)

    buffer = BytesIO()
    img.save(buffer)
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')




@app.route('/consulta_qr', methods=['GET'])
@login_required
def consulta_qr():
    animal_id = request.args.get('animal_id', type=int)
    token = request.args.get('token')  # se estiver usando QR com token

    # Aqui você já deve ter carregado o animal
    animal = Animal.query.get_or_404(animal_id)
    idade = calcular_idade(animal.date_of_birth) if animal.date_of_birth else ''

    # Lógica adicional
    tutor = animal.tutor
    consulta = Consulta.query.filter_by(animal_id=animal.id).order_by(Consulta.id.desc()).first()

    return render_template('consulta_qr.html',
                           tutor=tutor,
                           animal=animal,
                           consulta=consulta,
                           animal_idade=idade)








@app.route('/consulta/<int:animal_id>')
@login_required
def consulta_direct(animal_id):
    if current_user.worker not in ['veterinario', 'colaborador']:
        abort(403)

    animal = Animal.query.get_or_404(animal_id)
    tutor  = animal.owner

    edit_id = request.args.get('c', type=int)
    edit_mode = False

    if current_user.worker == 'veterinario':
        if edit_id:
            consulta = Consulta.query.get_or_404(edit_id)
            edit_mode = True
        else:
            consulta = (Consulta.query
                        .filter_by(animal_id=animal.id, status='in_progress')
                        .first())
            if not consulta:
                consulta = Consulta(animal_id=animal.id,
                                    created_by=current_user.id,
                                    status='in_progress')
                db.session.add(consulta)
                db.session.commit()
    else:
        consulta = None

    historico = []
    if current_user.worker == 'veterinario':
        historico = (Consulta.query
                    .filter_by(animal_id=animal.id, status='finalizada')
                    .order_by(Consulta.created_at.desc())
                    .all())

    tipos_racao = TipoRacao.query.order_by(TipoRacao.marca.asc()).all()
    marcas_existentes = sorted(set([t.marca for t in tipos_racao if t.marca]))
    linhas_existentes = sorted(set([t.linha for t in tipos_racao if t.linha]))

    # 🆕 Carregar listas de espécies e raças para o formulário
    species_list = Species.query.order_by(Species.name).all()
    breed_list = Breed.query.order_by(Breed.name).all()

    return render_template('consulta_qr.html',
                           animal=animal,
                           tutor=tutor,
                           consulta=consulta,
                           historico_consultas=historico,
                           edit_mode=edit_mode,
                           worker=current_user.worker,
                           tipos_racao=tipos_racao,
                           marcas_existentes=marcas_existentes,
                           linhas_existentes=linhas_existentes,
                           species_list=species_list,
                           breed_list=breed_list)



@app.route('/finalizar_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def finalizar_consulta(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem finalizar consultas.', 'danger')
        return redirect(url_for('index'))

    consulta.status = 'finalizada'
    db.session.commit()
    flash('Consulta finalizada e registrada no histórico!', 'success')
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/consulta/<int:consulta_id>/deletar', methods=['POST'])
@login_required
def deletar_consulta(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    animal_id = consulta.animal_id
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir consultas.', 'danger')
        return redirect(url_for('index'))

    db.session.delete(consulta)
    db.session.commit()
    flash('Consulta excluída!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/imprimir_consulta/<int:consulta_id>')
@login_required
def imprimir_consulta(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    animal = consulta.animal
    tutor = animal.owner
    clinica = current_user.veterinario.clinica if current_user.veterinario else None

    return render_template('imprimir_consulta.html',
                           consulta=consulta,
                           animal=animal,
                           tutor=tutor,
                           clinica=clinica)




@app.route('/buscar_tutores', methods=['GET'])
def buscar_tutores():
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify([])

    query = f"%{query}%"

    # Filtra por campos individualmente e junta os resultados (sem usar or_)
    nome_matches = User.query.filter(User.name.ilike(query)).all()
    email_matches = User.query.filter(User.email.ilike(query)).all()
    cpf_matches = User.query.filter(User.cpf.ilike(query)).all()
    rg_matches = User.query.filter(User.rg.ilike(query)).all()
    phone_matches = User.query.filter(User.phone.ilike(query)).all()

    # Junta os resultados e remove duplicados (por ID)
    todos = {user.id: user for user in (
        nome_matches + email_matches + cpf_matches + rg_matches + phone_matches
    )}.values()

    resultados = [
        {'id': tutor.id, 'name': tutor.name, 'email': tutor.email}
        for tutor in todos
    ]

    return jsonify(resultados)


@app.route('/tutor/<int:tutor_id>')
@login_required
def obter_tutor(tutor_id):
    tutor = User.query.get_or_404(tutor_id)
    return jsonify({
        'id': tutor.id,
        'name': tutor.name,
        'phone': tutor.phone,
        'address': tutor.address,
        'cpf': tutor.cpf,
        'rg': tutor.rg,
        'email': tutor.email,
        'date_of_birth': tutor.date_of_birth.strftime('%Y-%m-%d') if tutor.date_of_birth else ''
    })


@app.route('/tutor/<int:tutor_id>')
@login_required
def tutor_detail(tutor_id):
    tutor   = User.query.get_or_404(tutor_id)
    animais = tutor.animais.order_by(Animal.name).all()
    return render_template('tutor_detail.html', tutor=tutor, animais=animais)


@app.route('/tutores', methods=['GET', 'POST'])
@login_required
def tutores():
    # Restrição de acesso
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    # Criação de novo tutor
    if request.method == 'POST':
        name = request.form.get('tutor_name') or request.form.get('name')
        email = request.form.get('tutor_email') or request.form.get('email')

        if not name or not email:
            flash('Nome e e‑mail são obrigatórios.', 'warning')
            return redirect(url_for('tutores'))

        if User.query.filter_by(email=email).first():
            flash('Já existe um tutor com esse e‑mail.', 'warning')
            return redirect(url_for('tutores'))

        novo = User(
            name=name.strip(),
            email=email.strip(),
            role='adotante',  # padrão inicial
            clinica_id=current_user.clinica_id,
            added_by=current_user
        )
        novo.set_password('123456789')  # ⚠️ Sugestão: depois trocar por um token de convite

        # Campos opcionais
        novo.phone = (request.form.get('tutor_phone') or request.form.get('phone') or '').strip() or None
        novo.cpf = (request.form.get('tutor_cpf') or request.form.get('cpf') or '').strip() or None
        novo.rg = (request.form.get('tutor_rg') or request.form.get('rg') or '').strip() or None
        novo.address = None

        # Data de nascimento
        date_str = request.form.get('tutor_date_of_birth') or request.form.get('date_of_birth')
        if date_str:
            try:
                novo.date_of_birth = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
            except ValueError:
                flash('Data de nascimento inválida. Use o formato AAAA-MM-DD.', 'danger')
                return redirect(url_for('tutores'))

        # Endereço
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')

        if cep and rua and cidade and estado:
            endereco = Endereco(
                cep=cep,
                rua=rua,
                numero=numero,
                complemento=complemento,
                bairro=bairro,
                cidade=cidade,
                estado=estado
            )
            db.session.add(endereco)
            db.session.flush()
            novo.endereco_id = endereco.id

        # Foto
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            novo.profile_photo = f"/static/uploads/{filename}"

        db.session.add(novo)
        db.session.commit()

        flash('Tutor criado com sucesso!', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=novo.id))

    # — GET com paginação —
    page = request.args.get('page', 1, type=int)
    if current_user.clinica_id:
        pagination = User.query \
            .filter(User.clinica_id == current_user.clinica_id) \
            .order_by(User.created_at.desc()) \
            .paginate(page=page, per_page=9)
        tutores_adicionados = pagination.items
    else:
        pagination = None
        tutores_adicionados = []

    return render_template(
        'tutores.html',
        tutores_adicionados=tutores_adicionados,
        pagination=pagination
    )



@app.route('/deletar_tutor/<int:tutor_id>', methods=['POST'])
@login_required
def deletar_tutor(tutor_id):
    tutor = User.query.get_or_404(tutor_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir tutores.', 'danger')
        return redirect(url_for('index'))

    try:
        with db.session.no_autoflush:
            for animal in tutor.animals:
                # Deletar blocos de prescrição manualmente
                for bloco in animal.blocos_prescricao:
                    db.session.delete(bloco)

                # Você pode incluir aqui: exames, vacinas, etc., se necessário

                db.session.delete(animal)

        db.session.delete(tutor)
        db.session.commit()
        flash('Tutor e todos os seus dados foram excluídos com sucesso.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir tutor: {str(e)}', 'danger')

    return redirect(url_for('tutores'))




@app.route('/buscar_animais')
@login_required
def buscar_animais():
    termo = request.args.get('q', '').lower()
    animais = Animal.query.filter(
        (Animal.name.ilike(f"%{termo}%")) |
        (Animal.species.ilike(f"%{termo}%")) |
        (Animal.breed.ilike(f"%{termo}%")) |
        (Animal.microchip_number.ilike(f"%{termo}%"))
    ).all()

    return jsonify([{
        'id': a.id,
        'name': a.name,
        'species': a.species,
        'breed': a.breed,
        'sex': a.sex,
        'date_of_birth': a.date_of_birth.strftime('%Y-%m-%d') if a.date_of_birth else '',
        'microchip_number': a.microchip_number,
        'peso': a.peso,
        'health_plan': a.health_plan,
        'neutered': int(a.neutered) if a.neutered is not None else '',
    } for a in animais])





@app.route('/update_tutor/<int:user_id>', methods=['POST'])
@login_required
def update_tutor(user_id):
    user = User.query.get_or_404(user_id)

    # 🔐 Permissão: somente veterinários
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar dados do tutor.', 'danger')
        return redirect(request.referrer or url_for('index'))

    # 🧪 Debug: imprime o formulário recebido
    print("📥 FORM DATA RECEBIDA:")
    for campo in ["cep", "rua", "numero", "complemento", "bairro", "cidade", "estado"]:
        print(f"→ {campo}: {request.form.get(campo)}")

    # 📋 Dados básicos
    user.name = request.form.get("name") or user.name
    user.email = request.form.get("email") or user.email
    user.phone = request.form.get("phone") or user.phone
    user.cpf = request.form.get("cpf") or user.cpf
    user.rg = request.form.get("rg") or user.rg

    # 📅 Data de nascimento
    date_str = request.form.get("date_of_birth")
    if date_str:
        try:
            user.date_of_birth = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Data de nascimento inválida. Use o formato correto.", "danger")
            return redirect(request.referrer or url_for("index"))

    # 📸 Foto de perfil
    if 'profile_photo' in request.files and request.files['profile_photo'].filename != '':
        file = request.files['profile_photo']
        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        image_url = upload_to_s3(file, filename, folder="tutors")
        user.profile_photo = image_url

    # 📍 Endereço
    cep         = request.form.get('cep') or None
    rua         = request.form.get('rua') or None
    numero      = request.form.get('numero') or None
    complemento = request.form.get('complemento') or None
    bairro      = request.form.get('bairro') or None
    cidade      = request.form.get('cidade') or None
    estado      = request.form.get('estado') or None

    campos_obrigatorios = [cep, rua, numero, bairro, cidade, estado]

    if all(campos_obrigatorios):
        if user.endereco:
            endereco = user.endereco
        else:
            endereco = Endereco()
            db.session.add(endereco)

        # Primeiro preenche os dados
        endereco.cep = cep
        endereco.rua = rua
        endereco.numero = numero
        endereco.complemento = complemento
        endereco.bairro = bairro
        endereco.cidade = cidade
        endereco.estado = estado

        # Só depois faz flush para pegar o ID
        if not user.endereco_id:
            db.session.flush()
            user.endereco_id = endereco.id

    elif any([cep, rua, numero, bairro, cidade, estado]):
        flash('Por favor, preencha todos os campos obrigatórios do endereço.', 'warning')
        return redirect(request.referrer or url_for('index'))
    else:
        print("📭 Nenhum campo de endereço preenchido. Endereço não será criado.")

    # 💾 Commit final
    try:
        db.session.commit()
        flash('Dados do tutor atualizados com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERRO ao salvar tutor: {e}")
        flash(f'Ocorreu um erro ao salvar: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('index'))



# ——— FICHA DO TUTOR (dados + lista de animais) ————————————
from sqlalchemy.orm import joinedload

@app.route('/ficha_tutor/<int:tutor_id>')
@login_required
def ficha_tutor(tutor_id):
    # Restrição de acesso
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    # Dados do tutor
    tutor = User.query.get_or_404(tutor_id)

    # Lista de animais do tutor (com species e breed carregados)
    animais = Animal.query.options(
        joinedload(Animal.species),
        joinedload(Animal.breed)
    ).filter_by(user_id=tutor.id).order_by(Animal.name).all()

    # Ano atual
    current_year = datetime.now().year

    # Busca todas as espécies e raças
    species_list = Species.query.order_by(Species.name).all()
    breeds = Breed.query.options(joinedload(Breed.species)).all()

    # Mapeia raças por species_id (como string, para uso seguro no JS)
    breed_map = {}
    for breed in breeds:
        sp_id = str(breed.species.id)
        breed_map.setdefault(sp_id, []).append({
            'id': breed.id,
            'name': breed.name
        })

    return render_template(
        'tutor_detail.html',
        tutor=tutor,
        animais=animais,
        current_year=current_year,
        species_list=species_list,
        breed_map=breed_map
    )






@app.route('/update_animal/<int:animal_id>', methods=['POST'])
@login_required
def update_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar dados do animal.', 'danger')
        return redirect(request.referrer or url_for('index'))

    # Campos básicos
    animal.name = request.form.get('name')
    animal.sex = request.form.get('sex')
    animal.description = request.form.get('description') or ''
    animal.microchip_number = request.form.get('microchip_number')
    animal.health_plan = request.form.get('health_plan')
    animal.neutered = request.form.get('neutered') == '1'

    # Espécie (relacional)
    species_id = request.form.get('species_id')
    if species_id:
        try:
            animal.species_id = int(species_id)
        except ValueError:
            flash('ID de espécie inválido.', 'warning')

    # Raça (relacional)
    breed_id = request.form.get('breed_id')
    if breed_id:
        try:
            animal.breed_id = int(breed_id)
        except ValueError:
            flash('ID de raça inválido.', 'warning')

    # Peso
    peso_valor = request.form.get('peso')
    if peso_valor:
        try:
            animal.peso = float(peso_valor)
        except ValueError:
            flash('Peso inválido. Deve ser um número.', 'warning')
    else:
        animal.peso = None

    # Data de nascimento ou idade
    dob_str = request.form.get('date_of_birth')
    age_input = request.form.get('age')
    if dob_str:
        try:
            animal.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Data de nascimento inválida.', 'warning')
    elif age_input:
        try:
            age_years = int(age_input)
            animal.date_of_birth = date.today() - relativedelta(years=age_years)
        except ValueError:
            flash('Idade inválida. Deve ser um número inteiro.', 'warning')

    # Upload de imagem
    if 'image' in request.files and request.files['image'].filename != '':
        image_file = request.files['image']
        original_filename = secure_filename(image_file.filename)
        filename = f"{uuid.uuid4().hex}_{original_filename}"
        image_url = upload_to_s3(image_file, filename, folder="animals")
        animal.image = image_url

    db.session.commit()
    flash('Dados do animal atualizados com sucesso!', 'success')
    return redirect(request.referrer or url_for('index'))




@app.route('/update_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def update_consulta(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar a consulta.', 'danger')
        return redirect(url_for('index'))

    # Atualiza os campos
    consulta.queixa_principal = request.form.get('queixa_principal')
    consulta.historico_clinico = request.form.get('historico_clinico')
    consulta.exame_fisico = request.form.get('exame_fisico')
    consulta.conduta = request.form.get('conduta')

    # Se estiver editando uma consulta antiga
    if request.args.get('edit') == '1':
        db.session.commit()
        flash('Consulta atualizada com sucesso!', 'success')

    else:
        # Salva, finaliza e cria nova automaticamente
        consulta.status = 'finalizada'
        db.session.commit()

        nova = Consulta(
            animal_id=consulta.animal_id,
            created_by=current_user.id,
            status='in_progress'
        )
        db.session.add(nova)
        db.session.commit()

        flash('Consulta salva e movida para o histórico!', 'success')

    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/animal/<int:animal_id>/racoes', methods=['POST'])
@login_required
def salvar_racao(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    # Verifica se o usuário pode editar esse animal
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    data = request.get_json()

    try:
        # ✅ SUPORTE AO FORMATO NOVO: tipo_racao_id direto
        if 'tipo_racao_id' in data:
            tipo_racao_id = data.get('tipo_racao_id')
            recomendacao_custom = data.get('recomendacao_custom')
            observacoes_racao = data.get('observacoes_racao')

            # Garante que tipo_racao existe
            tipo_racao = TipoRacao.query.get(tipo_racao_id)
            if not tipo_racao:
                return jsonify({'success': False, 'error': 'Tipo de ração não encontrado.'}), 404

            nova_racao = Racao(
                animal_id=animal.id,
                tipo_racao_id=tipo_racao.id,
                recomendacao_custom=recomendacao_custom,
                observacoes_racao=observacoes_racao,
                preco_pago=data.get('preco_pago'),  # ✅ CORRIGIDO
                tamanho_embalagem=data.get('tamanho_embalagem')  # ✅ CORRIGIDO
            )
            db.session.add(nova_racao)

        # ✅ SUPORTE AO FORMATO ANTIGO: lista de racoes com marca/linha
        elif 'racoes' in data:
            racoes_data = data.get('racoes', [])
            for r in racoes_data:
                marca = r.get('marca_racao', '').strip()
                linha = r.get('linha_racao', '').strip()

                if not marca:
                    continue  # ignora se não houver marca

                tipo_racao = TipoRacao.query.filter_by(marca=marca, linha=linha).first()

                if not tipo_racao:
                    tipo_racao = TipoRacao(marca=marca, linha=linha)
                    db.session.add(tipo_racao)
                    db.session.flush()  # garante que o ID estará disponível

                nova_racao = Racao(
                    animal_id=animal.id,
                    tipo_racao_id=tipo_racao.id,
                    recomendacao_custom=r.get('recomendacao_custom'),
                    observacoes_racao=r.get('observacoes_racao')
                )
                db.session.add(nova_racao)

        else:
            return jsonify({'success': False, 'error': 'Formato de dados inválido.'}), 400

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao salvar ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao salvar ração.'}), 500


@app.route('/tipo_racao', methods=['POST'])
@login_required
def criar_tipo_racao():
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    data = request.get_json()
    marca = data.get('marca', '').strip()
    linha = data.get('linha', '').strip()
    recomendacao = data.get('recomendacao')
    peso_pacote_kg = data.get('peso_pacote_kg')  # Novo campo
    observacoes = data.get('observacoes', '').strip()

    if not marca:
        return jsonify({'success': False, 'error': 'Marca é obrigatória.'}), 400

    try:
        # Evita duplicidade
        existente = TipoRacao.query.filter_by(marca=marca, linha=linha).first()
        if existente:
            return jsonify({'success': False, 'error': 'Esta ração já existe.'}), 409

        nova_racao = TipoRacao(
            marca=marca,
            linha=linha if linha else None,
            recomendacao=recomendacao,
            peso_pacote_kg=peso_pacote_kg or 15.0,  # valor padrão se não enviado
            observacoes=observacoes if observacoes else None
        )
        db.session.add(nova_racao)
        db.session.commit()

        return jsonify({'success': True, 'id': nova_racao.id})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao cadastrar tipo de ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao cadastrar tipo de ração.'}), 500




@app.route('/tipos_racao')
def tipos_racao():
    termos = request.args.get('q', '')
    resultados = TipoRacao.query.filter(
        (TipoRacao.marca + ' - ' + (TipoRacao.linha or '')).ilike(f'%{termos}%')
    ).limit(15).all()

    return jsonify([
        f"{r.marca} - {r.linha}" if r.linha else r.marca
        for r in resultados
    ])


@app.route('/racao/<int:racao_id>/editar', methods=['PUT'])
@login_required
def editar_racao(racao_id):
    racao = Racao.query.get_or_404(racao_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    data = request.get_json()
    racao.recomendacao_custom = data.get('recomendacao_custom') or None
    racao.observacoes_racao = data.get('observacoes_racao') or ''
    racao.preco_pago = data.get('preco_pago') or None
    racao.tamanho_embalagem = data.get('tamanho_embalagem') or None

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Erro ao editar ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao editar ração.'}), 500



@app.route('/racao/<int:racao_id>/excluir', methods=['DELETE'])
@login_required
def excluir_racao(racao_id):
    racao = Racao.query.get_or_404(racao_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    try:
        db.session.delete(racao)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Erro ao excluir ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao excluir ração.'}), 500





from sqlalchemy.orm import aliased
from sqlalchemy import func, desc

from collections import defaultdict

@app.route("/relatorio/racoes")
@login_required
def relatorio_racoes():
    subquery = (
        db.session.query(
            Racao.animal_id,
            func.max(Racao.data_cadastro).label("ultima_data")
        )
        .group_by(Racao.animal_id)
        .subquery()
    )

    RacaoAlias = aliased(Racao)

    racoes_recentes = (
        db.session.query(RacaoAlias)
        .join(subquery, (RacaoAlias.animal_id == subquery.c.animal_id) & 
                         (RacaoAlias.data_cadastro == subquery.c.ultima_data))
        .all()
    )

    # Agrupar por tipo_racao
    racoes_por_tipo = defaultdict(list)
    for r in racoes_recentes:
        racoes_por_tipo[r.tipo_racao].append(r)

    return render_template("relatorio_racoes.html", racoes_por_tipo=racoes_por_tipo)


@app.route("/historico_animal/<int:animal_id>")
@login_required
def historico_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    racoes = Racao.query.filter_by(animal_id=animal.id).order_by(Racao.data_cadastro.desc()).all()
    return render_template("historico_racoes.html", animal=animal, racoes=racoes)



@app.route('/relatorio/racoes/<int:tipo_id>')
@login_required
def detalhes_racao(tipo_id):
    tipo = TipoRacao.query.get_or_404(tipo_id)
    racoes = tipo.usos  # usa o backref 'usos'
    return render_template('detalhes_racao.html', tipo=tipo, racoes=racoes)





@app.route('/buscar_vacinas')
def buscar_vacinas():
    termo = request.args.get('q', '').strip().lower()

    if not termo or len(termo) < 2:
        return jsonify([])

    try:
        resultados = VacinaModelo.query.filter(
            VacinaModelo.nome.ilike(f"%{termo}%")
        ).all()

        return jsonify([
            {'nome': v.nome, 'tipo': v.tipo or ''}
            for v in resultados
        ])
    except Exception as e:
        print(f"Erro ao buscar vacinas: {e}")
        return jsonify([])  # Não quebra o front se der erro


from datetime import datetime

@app.route("/animal/<int:animal_id>/vacinas", methods=["POST"])
def salvar_vacinas(animal_id):
    data = request.get_json()

    if not data or "vacinas" not in data:
        return jsonify({"success": False, "error": "Dados incompletos"}), 400

    try:
        for v in data["vacinas"]:
            data_formatada = datetime.strptime(v.get("data"), "%Y-%m-%d").date() if v.get("data") else None

            vacina = Vacina(
                animal_id=animal_id,
                nome=v.get("nome"),
                tipo=v.get("tipo"),
                data=data_formatada,
                observacoes=v.get("observacoes")
            )
            db.session.add(vacina)

        db.session.commit()
        return jsonify({"success": True})

    except Exception as e:
        print("Erro ao salvar vacinas:", e)
        return jsonify({"success": False, "error": "Erro técnico ao salvar vacinas"}), 500




@app.route("/animal/<int:animal_id>/vacinas/imprimir")
def imprimir_vacinas(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_template("imprimir_vacinas.html", animal=animal)


@app.route("/vacina/<int:vacina_id>/deletar", methods=["POST"])
def deletar_vacina(vacina_id):
    vacina = Vacina.query.get_or_404(vacina_id)
    db.session.delete(vacina)
    db.session.commit()
    return redirect(request.referrer or url_for("index"))




@app.route("/vacina/<int:vacina_id>/editar", methods=["POST"])
def editar_vacina(vacina_id):
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "Dados ausentes"}), 400

    try:
        vacina = Vacina.query.get_or_404(vacina_id)

        vacina.nome = data.get("nome", vacina.nome)
        vacina.tipo = data.get("tipo", vacina.tipo)
        vacina.observacoes = data.get("observacoes", vacina.observacoes)

        if data.get("data"):
            vacina.data = datetime.strptime(data["data"], "%Y-%m-%d").date()

        db.session.commit()
        return jsonify({"success": True})

    except Exception as e:
        print("Erro ao editar vacina:", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/consulta/<int:consulta_id>/prescricao', methods=['POST'])
@login_required
def criar_prescricao(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem adicionar prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    medicamento = request.form.get('medicamento')
    dosagem = request.form.get('dosagem')
    frequencia = request.form.get('frequencia')
    duracao = request.form.get('duracao')
    observacoes = request.form.get('observacoes')

    if not medicamento:
        flash('É necessário informar o nome do medicamento.', 'warning')
        return redirect(request.referrer)

    nova_prescricao = Prescricao(
        consulta_id=consulta.id,
        medicamento=medicamento,
        dosagem=dosagem,
        frequencia=frequencia,
        duracao=duracao,
        observacoes=observacoes
    )

    db.session.add(nova_prescricao)
    db.session.commit()

    flash('Prescrição adicionada com sucesso!', 'success')
    # criar_prescricao
    return redirect(url_for('consulta_qr', animal_id=Consulta.query.get(consulta_id).animal_id))


from flask import request, jsonify


@app.route('/prescricao/<int:prescricao_id>/deletar', methods=['POST'])
@login_required
def deletar_prescricao(prescricao_id):
    prescricao = Prescricao.query.get_or_404(prescricao_id)
    consulta_id = prescricao.consulta_id

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    db.session.delete(prescricao)
    db.session.commit()
    flash('Prescrição removida com sucesso!', 'info')
    return redirect(url_for('consulta_qr', animal_id=consulta.animal_id))


@app.route('/importar_medicamentos')
def importar_medicamentos():
    import pandas as pd


    try:
        df = pd.read_csv("medicamentos_pet_orlandia.csv")

        for _, row in df.iterrows():
            medicamento = Medicamento(
                classificacao=row["classificacao"],
                nome=row["nome"],
                principio_ativo=row["principio_ativo"],
                via_administracao=row["via_administracao"],
                dosagem_recomendada=row["dosagem_recomendada"],
                duracao_tratamento=row["duracao_tratamento"],
                observacoes=row["observacoes"],
                bula=row["link_bula"]
            )
            db.session.add(medicamento)

        db.session.commit()
        return "✅ Medicamentos importados com sucesso!"

    except Exception as e:
        return f"❌ Erro: {e}"


@app.route("/buscar_medicamentos")
def buscar_medicamentos():
    q = (request.args.get("q") or "").strip()

    # evita erro de None.lower()
    if len(q) < 2:
        return jsonify([])

    # busca por nome OU princípio ativo
    resultados = (
        Medicamento.query
        .filter(
            (Medicamento.nome.ilike(f"%{q}%")) |
            (Medicamento.principio_ativo.ilike(f"%{q}%"))
        )
        .order_by(Medicamento.nome)
        .limit(15)                     # devolve no máximo 15
        .all()
    )

    return jsonify([
        {
            "id": m.id,  # ✅ ESSENCIAL PARA O FUNCIONAMENTO
            "nome": m.nome,
            "classificacao": m.classificacao,
            "principio_ativo": m.principio_ativo,
            "via_administracao": m.via_administracao,
            "dosagem_recomendada": m.dosagem_recomendada,
            "duracao_tratamento": m.duracao_tratamento,
            "observacoes": m.observacoes,
            "bula": m.bula,
        }
        for m in resultados
    ])



@app.route("/buscar_apresentacoes")
def buscar_apresentacoes():
    try:
        medicamento_id = request.args.get("medicamento_id")
        q = (request.args.get("q") or "").strip()

        if not medicamento_id or not medicamento_id.isdigit():
            return jsonify([])

        # Log for debugging
        print(f"Searching for presentations of medicamento_id={medicamento_id}, query='{q}'")

        apresentacoes = (
            ApresentacaoMedicamento.query
            .filter(
                ApresentacaoMedicamento.medicamento_id == int(medicamento_id),
                (ApresentacaoMedicamento.forma.ilike(f"%{q}%")) |
                (ApresentacaoMedicamento.concentracao.ilike(f"%{q}%"))
            )
            .all()
        )

        return jsonify([
            {"forma": a.forma, "concentracao": a.concentracao}
            for a in apresentacoes
        ])

    except Exception as e:
        print(f"[ERROR] /buscar_apresentacoes: {str(e)}")
        return jsonify({"error": str(e)}), 500



@app.route('/consulta/<int:consulta_id>/prescricao/lote', methods=['POST'])
@login_required
def salvar_prescricoes_lote(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    data = request.get_json()
    novas_prescricoes = data.get('prescricoes', [])

    for item in novas_prescricoes:
        nova = Prescricao(
            animal_id=consulta.animal_id,
            medicamento=item.get('nome'),
            dosagem=item.get('dosagem'),
            frequencia=item.get('frequencia'),
            duracao=item.get('duracao'),
            observacoes=item.get('observacoes')
        )
        db.session.add(nova)

    db.session.commit()

    historico_html = render_template('partials/historico_prescricoes.html', consulta=consulta)
    return jsonify({'status': 'ok', 'historico_html': historico_html})


@app.route('/consulta/<int:consulta_id>/bloco_prescricao', methods=['POST'])
@login_required
def salvar_bloco_prescricao(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem prescrever.'}), 403

    dados = request.get_json()
    lista_prescricoes = dados.get('prescricoes')
    instrucoes = dados.get('instrucoes_gerais')  # 🟢 AQUI você precisa pegar o campo

    if not lista_prescricoes:
        return jsonify({'success': False, 'message': 'Nenhuma prescrição recebida.'}), 400

    # ⬇️ Aqui é onde a instrução geral precisa ser usada
    bloco = BlocoPrescricao(animal_id=consulta.animal_id, instrucoes_gerais=instrucoes)
    db.session.add(bloco)
    db.session.flush()  # Garante o ID do bloco

    for item in lista_prescricoes:
        nova = Prescricao(
            animal_id=consulta.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=item.get('dosagem'),
            frequencia=item.get('frequencia'),
            duracao=item.get('duracao'),
            observacoes=item.get('observacoes')
        )
        db.session.add(nova)

    db.session.commit()
    return jsonify({'success': True, 'message': 'Prescrições salvas com sucesso!'})


@app.route('/bloco_prescricao/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    db.session.delete(bloco)
    db.session.commit()
    flash('Bloco de prescrição excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/bloco_prescricao/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar prescrições.', 'danger')
        return redirect(url_for('index'))

    return render_template('editar_bloco.html', bloco=bloco)


@app.route('/bloco_prescricao/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403

    data = request.get_json()
    novos_medicamentos = data.get('medicamentos', [])

    # Limpa os medicamentos atuais do bloco
    for p in bloco.prescricoes:
        db.session.delete(p)

    # Adiciona os novos medicamentos ao bloco
    for item in novos_medicamentos:
        nova = Prescricao(
            animal_id=bloco.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=item.get('dosagem'),
            frequencia=item.get('frequencia'),
            duracao=item.get('duracao'),
            observacoes=item.get('observacoes')
        )
        db.session.add(nova)

    db.session.commit()
    return jsonify({'success': True})


@app.route('/bloco_prescricao/<int:bloco_id>/imprimir')
@login_required
def imprimir_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem imprimir prescrições.', 'danger')
        return redirect(url_for('index'))

    animal = bloco.animal
    tutor = animal.owner

    # Pegando a clínica do veterinário (se houver)
    clinica = None
    if current_user.veterinario:
        clinica = current_user.veterinario.clinica

    return render_template(
        'imprimir_bloco.html',
        bloco=bloco,
        consulta = animal.consultas[-1] if animal.consultas else None,
        animal=animal,
        tutor=tutor,
        clinica=clinica  # ✅ incluído
    )


@app.route('/animal/<int:animal_id>/bloco_exames', methods=['POST'])
@login_required
def salvar_bloco_exames(animal_id):
    data = request.get_json()
    exames_data = data.get('exames', [])
    observacoes_gerais = data.get('observacoes_gerais', '')

    bloco = BlocoExames(animal_id=animal_id, observacoes_gerais=observacoes_gerais)
    db.session.add(bloco)
    db.session.flush()  # Garante que bloco.id esteja disponível

    for exame in exames_data:
        exame_modelo = ExameSolicitado(
            bloco_id=bloco.id,
            nome=exame.get('nome'),
            justificativa=exame.get('justificativa')
        )
        db.session.add(exame_modelo)

    db.session.commit()
    return jsonify({'success': True})



@app.route('/buscar_exames')
@login_required
def buscar_exames():
    q = request.args.get('q', '').lower()
    exames = ExameModelo.query.filter(ExameModelo.nome.ilike(f'%{q}%')).all()
    return jsonify([{'id': e.id, 'nome': e.nome} for e in exames])


@app.route('/imprimir_bloco_exames/<int:bloco_id>')
@login_required
def imprimir_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    animal = bloco.animal
    tutor = animal.owner

    clinica = current_user.veterinario.clinica if current_user.veterinario else Clinica.query.first()

    return render_template('imprimir_exames.html', bloco=bloco, animal=animal, tutor=tutor, clinica=clinica)


@app.route('/bloco_exames/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir blocos de exames.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    db.session.delete(bloco)
    db.session.commit()

    flash('Bloco de exames excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))



@app.route('/bloco_exames/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar exames.'}), 403
    return render_template('editar_bloco_exames.html', bloco=bloco)





@app.route('/exame/<int:exame_id>/editar', methods=['POST'])
@login_required
def editar_exame(exame_id):
    exame = ExameSolicitado.query.get_or_404(exame_id)
    data = request.get_json()

    exame.nome = data.get('nome', exame.nome)
    exame.justificativa = data.get('justificativa', exame.justificativa)

    db.session.commit()
    return jsonify(success=True)





@app.route('/bloco_exames/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    dados = request.get_json()

    bloco.observacoes_gerais = dados.get('observacoes_gerais', '')

    # ---------- mapeia exames já existentes ----------
    existentes = {e.id: e for e in bloco.exames}
    enviados_ids = set()

    for ex_json in dados.get('exames', []):
        ex_id = ex_json.get('id')
        nome  = ex_json.get('nome', '').strip()
        just  = ex_json.get('justificativa', '').strip()

        if not nome:                 # pulamos entradas vazias
            continue

        if ex_id and ex_id in existentes:
            # --- atualizar exame já salvo ---
            exame = existentes[ex_id]
            exame.nome = nome
            exame.justificativa = just
            enviados_ids.add(ex_id)
        else:
            # --- criar exame novo ---
            novo = ExameSolicitado(
                bloco=bloco,
                nome=nome,
                justificativa=just
            )
            db.session.add(novo)

    # ---------- remover os que ficaram de fora ----------
    for ex in bloco.exames:
        if ex.id not in enviados_ids and ex.id in existentes:
            db.session.delete(ex)

    db.session.commit()
    return jsonify(success=True)



@app.route('/novo_atendimento')
@login_required
def novo_atendimento():
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    return render_template('novo_atendimento.html')


@app.route('/criar_tutor_ajax', methods=['POST'])
@login_required
def criar_tutor_ajax():
    name = request.form.get('name')
    email = request.form.get('email')

    if not name or not email:
        return jsonify({'success': False, 'message': 'Nome e e-mail são obrigatórios.'})

    tutor_existente = User.query.filter_by(email=email).first()
    if tutor_existente:
        return jsonify({'success': False, 'message': 'Já existe um tutor com este e-mail.'})

    novo_tutor = User(
        name=name,
        phone=request.form.get('phone'),
        address=request.form.get('address'),
        cpf=request.form.get('cpf'),
        rg=request.form.get('rg'),
        email=email,
        role='adotante',
        clinica_id=current_user.clinica_id

    )

    date_str = request.form.get('date_of_birth')
    if date_str:
        try:
            novo_tutor.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Data de nascimento inválida.'})

    novo_tutor.set_password('123456789')  # Senha padrão

    db.session.add(novo_tutor)
    db.session.commit()

    return jsonify({'success': True, 'tutor_id': novo_tutor.id})


# app.py  – dentro da rota /novo_animal
from datetime import datetime, date
from dateutil.relativedelta import relativedelta   # já está importado acima

@app.route('/novo_animal', methods=['GET', 'POST'])
@login_required
def novo_animal():
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem cadastrar animais.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        tutor_id = request.form.get('tutor_id', type=int)
        tutor = User.query.get_or_404(tutor_id)

        dob_str = request.form.get('date_of_birth')
        dob = None
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Data de nascimento inválida. Use AAAA‑MM‑DD.', 'warning')
                return redirect(url_for('ficha_tutor', tutor_id=tutor.id))

        peso_str = request.form.get('peso')
        peso = float(peso_str) if peso_str else None

        neutered_val = request.form.get('neutered')
        neutered = True if neutered_val == '1' else False if neutered_val == '0' else None

        image_path = None
        if 'image' in request.files and request.files['image'].filename != '':
            image_file = request.files['image']
            filename = secure_filename(image_file.filename)
            image_path = upload_to_s3(image_file, filename)

        # IDs para espécie e raça
        species_id = request.form.get('species_id', type=int)
        breed_id = request.form.get('breed_id', type=int)

        # Carrega os objetos Species e Breed (opcional)
        species_obj = Species.query.get(species_id) if species_id else None
        breed_obj = Breed.query.get(breed_id) if breed_id else None

        # Criação do animal
        animal = Animal(
            name=request.form.get('name'),
            species_id=species_id,
            breed_id=breed_id,
            sex=request.form.get('sex'),
            date_of_birth=dob,
            microchip_number=request.form.get('microchip_number'),
            peso=peso,
            health_plan=request.form.get('health_plan'),
            neutered=neutered,
            user_id=tutor.id,
            added_by_id=current_user.id,
            clinica_id=current_user.clinica_id,
            status='disponível',
            image=image_path,
            is_alive=True,
            modo='adotado',
        )
        db.session.add(animal)
        db.session.commit()

        # Criação da consulta
        consulta = Consulta(
            animal_id=animal.id,
            created_by=current_user.id,
            status='in_progress'
        )
        db.session.add(consulta)
        db.session.commit()

        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('consulta_direct', animal_id=animal.id))

    # GET: lista de animais adicionados para exibição
    page = request.args.get('page', 1, type=int)
    if current_user.clinica_id:
        pagination = Animal.query \
            .filter_by(clinica_id=current_user.clinica_id) \
            .filter(Animal.removido_em == None) \
            .order_by(Animal.date_added.desc()) \
            .paginate(page=page, per_page=9)
    else:
        pagination = Animal.query \
            .filter_by(added_by_id=current_user.id) \
            .filter(Animal.removido_em == None) \
            .order_by(Animal.date_added.desc()) \
            .paginate(page=page, per_page=9)

    animais_adicionados = pagination.items

    # Lista de espécies e raças para os <select> do formulário
    species_list = Species.query.order_by(Species.name).all()
    breed_list = Breed.query.order_by(Breed.name).all()

    return render_template(
        'novo_animal.html',
        animais_adicionados=animais_adicionados,
        pagination=pagination,
        species_list=species_list,
        breed_list=breed_list
    )





@app.route('/animal/<int:animal_id>/marcar_falecido', methods=['POST'])
@login_required
def marcar_como_falecido(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem realizar essa ação.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    data = request.form.get('falecimento_em')

    try:
        animal.falecido_em = datetime.strptime(data, '%Y-%m-%dT%H:%M') if data else datetime.utcnow()
        animal.is_alive = False
        db.session.commit()
        flash(f'{animal.name} foi marcado como falecido.', 'success')
    except Exception as e:
        flash(f'Erro ao marcar como falecido: {str(e)}', 'danger')

    return redirect(url_for('ficha_animal', animal_id=animal.id))




@app.route('/animal/<int:animal_id>/reverter_falecimento', methods=['POST'])
@login_required
def reverter_falecimento(animal_id):
    if current_user.worker != 'veterinario':
        abort(403)

    animal = Animal.query.get_or_404(animal_id)
    animal.is_alive = True
    animal.falecido_em = None
    db.session.commit()
    flash('Falecimento revertido com sucesso.', 'success')
    return redirect(url_for('ficha_animal', animal_id=animal.id))





@app.route('/animal/<int:animal_id>/arquivar', methods=['POST'])
@login_required
def arquivar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir animais definitivamente.', 'danger')
        return redirect(request.referrer or url_for('index'))

    try:
        db.session.delete(animal)
        db.session.commit()
        flash(f'Animal {animal.name} excluído permanentemente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {str(e)}', 'danger')

    return redirect(url_for('ficha_tutor', tutor_id=animal.user_id))


@app.route('/orders/new', methods=['GET', 'POST'])
@login_required
def create_order():
    if current_user.worker != 'delivery':
        abort(403)

    order_id = session.get('current_order')
    if order_id:
        order = Order.query.get_or_404(order_id)
    else:
        order = Order(user_id=current_user.id)
        db.session.add(order)
        db.session.commit()
        session['current_order'] = order.id

    form = OrderItemForm()
    delivery_form = DeliveryRequestForm()

    if form.validate_on_submit():
        item = OrderItem(order_id=order.id,
                         item_name=form.item_name.data,
                         quantity=form.quantity.data)
        db.session.add(item)
        db.session.commit()
        flash('Item adicionado ao pedido.', 'success')
        return redirect(url_for('create_order'))

    total_quantity = sum(i.quantity for i in order.items)
    return render_template(
        'create_order.html',
        form=form,
        delivery_form=delivery_form,
        order=order,
        total_quantity=total_quantity,
    )


@app.route('/orders/<int:order_id>/request_delivery', methods=['POST'])
@login_required
def request_delivery(order_id):
    if current_user.worker != 'delivery':
        abort(403)
    order = Order.query.get_or_404(order_id)
    req = DeliveryRequest(
        order_id=order.id,
        requested_by_id=current_user.id,
        status='pendente',
    )
    db.session.add(req)
    db.session.commit()
    session.pop('current_order', None)
    flash('Solicitação de entrega gerada.', 'success')
    return redirect(url_for('list_delivery_requests'))


@app.route('/delivery_requests')
@login_required
def list_delivery_requests():
    if current_user.worker == 'delivery':
        requests = DeliveryRequest.query.order_by(DeliveryRequest.requested_at.desc()).all()
    else:
        requests = DeliveryRequest.query.filter_by(requested_by_id=current_user.id).order_by(DeliveryRequest.requested_at.desc()).all()
    return render_template('delivery_requests.html', requests=requests)



@app.route('/delivery_requests/<int:req_id>/accept', methods=['POST'])
@login_required
def accept_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.status != 'pendente':
        flash('Solicitação não disponível.', 'warning')
        return redirect(url_for('list_delivery_requests'))
    req.status = 'em_andamento'
    req.worker_id = current_user.id
    req.accepted_at = datetime.utcnow()
    db.session.commit()
    flash('Entrega aceita.', 'success')
    return redirect(url_for('list_delivery_requests'))


@app.route('/delivery_requests/<int:req_id>/complete', methods=['POST'])
@login_required
def complete_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id != current_user.id:
        abort(403)
    req.status = 'concluida'
    req.completed_at = datetime.utcnow()
    db.session.commit()
    flash('Entrega concluída.', 'success')
    return redirect(url_for('worker_history'))


@app.route('/delivery_requests/<int:req_id>/cancel', methods=['POST'])
@login_required
def cancel_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id != current_user.id:
        abort(403)
    req.status = 'cancelada'
    req.canceled_at = datetime.utcnow()
    req.canceled_by_id = current_user.id
    db.session.commit()
    flash('Entrega cancelada.', 'info')
    return redirect(url_for('worker_history'))


@app.route('/delivery_requests/<int:req_id>/buyer_cancel', methods=['POST'])
@login_required
def buyer_cancel_delivery(req_id):
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.requested_by_id != current_user.id:
        abort(403)
    if req.status in ['concluida', 'cancelada']:
        flash('Não é possível cancelar.', 'warning')
        return redirect(url_for('loja'))
    req.status = 'cancelada'
    req.canceled_at = datetime.utcnow()
    req.canceled_by_id = current_user.id
    db.session.commit()
    flash('Solicitação cancelada.', 'info')
    return redirect(url_for('loja'))


@app.route('/admin/delivery/<int:req_id>')
@login_required
def admin_delivery_detail(req_id):
    if not _is_admin():
        abort(403)
    
    req = DeliveryRequest.query.get_or_404(req_id)
    order = Order.query.get_or_404(req.order_id)
    items = order.items  # Order has one-to-many OrderItem
    buyer = order.user
    delivery_worker = req.worker if req.worker_id else None

    # Acessando produtos relacionados e somando valor total
    total = 0
    for item in items:
        if hasattr(item, 'product') and item.product:
            total += item.quantity * item.product.price

    return render_template('admin/delivery_detail.html',
                           req=req,
                           order=order,
                           items=items,
                           buyer=buyer,
                           delivery_worker=delivery_worker,
                           total=total)




@app.route('/worker/history')
@login_required
def worker_history():
    if current_user.worker != 'delivery':
        abort(403)
    available = DeliveryRequest.query.filter_by(status='pendente').all()
    doing = DeliveryRequest.query.filter_by(worker_id=current_user.id, status='em_andamento').all()
    done = DeliveryRequest.query.filter_by(worker_id=current_user.id, status='concluida').all()
    canceled = DeliveryRequest.query.filter_by(worker_id=current_user.id, status='cancelada').all()
    return render_template('worker_history.html', available=available, doing=doing, done=done, canceled=canceled)


@app.route('/fluxograma_entregas')
@login_required
def fluxograma_entregas():
    if current_user.worker != 'delivery':
        abort(403)
    return render_template('fluxograma_entregas.html')


@app.route('/admin/delivery_overview')
@login_required
def delivery_overview():
    if not _is_admin():
        abort(403)
    # Garantimos que todas as consultas sejam executadas dentro de um
    # contexto de aplicação para evitar problemas caso o objeto ``db``
    # não esteja associado ao app atual.
    with app.app_context():
        products = Product.query.all()
        open_requests = DeliveryRequest.query.filter_by(status='pendente').all()
        in_progress = DeliveryRequest.query.filter_by(status='em_andamento').all()
        completed = DeliveryRequest.query.filter_by(status='concluida').all()
    return render_template('admin/delivery_overview.html',
                           products=products,
                           open_requests=open_requests,
                           in_progress=in_progress,
                           completed=completed)







@app.route("/loja")
@login_required
def loja():
    pagamento_pendente = None
    payment_id = session.get("last_pending_payment")
    if payment_id:
        payment = Payment.query.get(payment_id)
        if payment and payment.status.name == "PENDING":
            pagamento_pendente = payment

    produtos = Product.query.all()
    form = AddToCartForm()
    return render_template("loja.html", products=produtos, pagamento_pendente=pagamento_pendente, form=form)


@app.route('/carrinho/adicionar/<int:product_id>', methods=['POST'])
@login_required
def adicionar_carrinho(product_id):
    product = Product.query.get_or_404(product_id)
    form = AddToCartForm()
    if form.validate_on_submit():
        order_id = session.get('current_order')
        if order_id:
            order = Order.query.get(order_id)
        else:
            order = Order(user_id=current_user.id)
            db.session.add(order)
            db.session.commit()
            session['current_order'] = order.id
        
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,  # ESSENCIAL para mostrar valor e outras infos
            item_name=product.name,
            quantity=form.quantity.data
)

        db.session.add(item)
        product.stock = product.stock - form.quantity.data
        db.session.commit()
        flash('Produto adicionado ao carrinho.', 'success')
    return redirect(url_for('loja'))


@app.route('/carrinho')
@login_required
def ver_carrinho():
    # Redireciona para pagamento pendente, se existir
    payment_id = session.get('last_pending_payment')
    if payment_id:
        payment = Payment.query.get(payment_id)
        if payment and payment.status.name == "PENDING":
            return redirect(url_for('payment_status', payment_id=payment.id))

    # Caso não haja pagamento pendente, exibe o carrinho normalmente
    order_id = session.get('current_order')
    order = Order.query.get(order_id) if order_id else None
    return render_template('carrinho.html', order=order)


@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    order_id = session.get("current_order")
    order = Order.query.get(order_id) if order_id else None

    if not order or not order.items:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("ver_carrinho"))

    payment = Payment(
        user_id=current_user.id,
        order_id=order.id,
        method=PaymentMethod.PIX,
        status=PaymentStatus.PENDING
    )
    db.session.add(payment)
    db.session.commit()

    items = []
    for item in order.items:
        if item.product:
            items.append({
                "title": item.product.name,
                "quantity": int(item.quantity),
                "unit_price": float(item.product.price)
            })

    preference_data = {
        "items": items,
        "payment_methods": {
            "excluded_payment_types": [{"id": "credit_card"}],
            "installments": 1
        },
        "payer": {"email": current_user.email},
        "notification_url": url_for("notificacoes_mercado_pago", _external=True),
        "external_reference": str(payment.id),
        "back_urls": {
            "success": url_for("payment_status", payment_id=payment.id, status='success', _external=True),
            "failure": url_for("payment_status", payment_id=payment.id, status='failure', _external=True),
            "pending": url_for("payment_status", payment_id=payment.id, status='pending', _external=True)
        },
        "auto_return": "approved"
    }

    try:
        preference_response = sdk.preference().create(preference_data)
    except Exception:
        current_app.logger.exception("Erro comunicando com Mercado Pago")
        flash("Não foi possível iniciar o pagamento.", "danger")
        return redirect(url_for("ver_carrinho"))

    if preference_response.get("status") != 201:
        current_app.logger.error("Resposta inesperada MP: %s", preference_response)
        flash("Erro ao iniciar pagamento.", "danger")
        return redirect(url_for("ver_carrinho"))

    preference = preference_response["response"]
    payment.transaction_id = str(preference["id"])
    db.session.commit()

    session['last_pending_payment'] = payment.id

    return redirect(preference["init_point"])


@app.route('/pagamento/<int:order_id>')
@login_required
def pagamento(order_id):
    order = Order.query.get_or_404(order_id)
    payment = order.payment
    return render_template('pagamento.html', order=order, payment=payment)


import mercadopago

# SDK do Mercado Pago configurado com o token definido no arquivo de configuração
sdk = mercadopago.SDK(app.config.get('MERCADOPAGO_ACCESS_TOKEN'))

@app.route("/criar_pagamento_pix", methods=["POST"])
def criar_pagamento_pix():
    data = request.get_json()

    preference_data = {
        "items": [
            {
                "title": data.get("titulo", "Produto Teste"),
                "quantity": int(data.get("quantidade", 1)),
                "unit_price": float(data.get("preco", 10.0))
            }
        ],
        "payment_methods": {
            "excluded_payment_types": [{"id": "credit_card"}],  # aceita só PIX
            "installments": 1
        },
        "payer": {
            "email": data.get("email", "cliente@email.com")
        },
        "notification_url": "https://petorlandia.com.br/notificacoes"
    }

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response["response"]

    return jsonify({
        "id": preference["id"],
        "init_point": preference["init_point"],
    })




from flask import request, jsonify
from datetime import datetime
from models import Payment, PaymentMethod, PaymentStatus, DeliveryRequest

@app.route("/notificacoes", methods=["POST"])
def notificacoes_mercado_pago():
    secret = current_app.config.get("MERCADOPAGO_WEBHOOK_SECRET")
    signature = request.headers.get("X-MP-Signature")
    if secret:
        calculated = hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, signature or ""):
            current_app.logger.warning("Invalid Mercado Pago webhook signature")
            return jsonify({"error": "invalid signature"}), 400

    data = request.get_json()
    current_app.logger.info("🔔 Notificação recebida: %s", data)

    if data and data.get("type") == "payment":
        mp_payment_id = data.get("data", {}).get("id")
        if mp_payment_id:
            try:
                resp = sdk.payment().get(mp_payment_id)
                if resp.get("status") != 200:
                    current_app.logger.error("Erro Mercado Pago: %s", resp)
                    return jsonify({"error": "api error"}), 500
                payment_info = resp["response"]

                status = payment_info.get("status", "pending")
                external_ref = payment_info.get("external_reference")
                pagamento = Payment.query.get(int(external_ref)) if external_ref else None
                if pagamento:
                    if pagamento.status == PaymentStatus.COMPLETED:
                        return jsonify({"status": "already_processed"}), 200
                    pagamento.transaction_id = str(payment_info.get("id"))
                    if status == "approved":
                        pagamento.status = PaymentStatus.COMPLETED
                        if pagamento.order_id and not DeliveryRequest.query.filter_by(order_id=pagamento.order_id).first():
                            req = DeliveryRequest(order_id=pagamento.order_id,
                                                  requested_by_id=pagamento.user_id,
                                                  status='pendente')
                            db.session.add(req)
                    elif status == "rejected":
                        pagamento.status = PaymentStatus.FAILED
                    else:
                        pagamento.status = PaymentStatus.PENDING
                    db.session.commit()
                return jsonify({"status": "atualizado"}), 200
            except Exception:
                current_app.logger.exception("Erro ao processar pagamento")
                return jsonify({"erro": "falha interna"}), 500

    return jsonify({"status": "ignorado"}), 200





@app.route("/simular_pagamento/<int:payment_id>", methods=["POST"])
@login_required
def simular_pagamento(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if payment.user_id != current_user.id:
        abort(403)

    payment.status = PaymentStatus.COMPLETED
    db.session.commit()

    # Limpa da sessão
    session.pop("last_pending_payment", None)
    flash("Pagamento confirmado!", "success")
    return redirect(url_for("loja"))



@app.route('/confirmar_pagamento/<int:payment_id>', methods=['POST'])
@login_required
def confirmar_pagamento(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    payment.status = 'pago'
    db.session.commit()

    # Criar solicitação de entrega
    req = DeliveryRequest(order_id=payment.order_id,
                          requested_by_id=current_user.id,
                          status='pendente')
    db.session.add(req)
    db.session.commit()

    flash('Pagamento confirmado com sucesso!', 'success')
    return redirect(url_for('list_delivery_requests'))



@app.route('/payment_status/<int:payment_id>')
@login_required
def payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    result = request.args.get('status')
    return render_template('payment_status.html', payment=payment, result=result)






import os

if __name__ == "__main__":
    # Usa a porta 8080 se existir no ambiente (como no Docker), senão usa 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)











@app.route('/teste_endereco', methods=['GET', 'POST'])
def teste_endereco():
    endereco = None

    if request.method == 'POST':
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')

        endereco = Endereco(
            cep=cep,
            rua=rua,
            numero=numero,
            complemento=complemento,
            bairro=bairro,
            cidade=cidade,
            estado=estado
        )
        db.session.add(endereco)
        db.session.commit()
        flash('Endereço salvo com sucesso!', 'success')
        return redirect(url_for('teste_endereco'))

    return render_template('teste_endereco.html', endereco=endereco)
