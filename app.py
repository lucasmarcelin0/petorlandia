from io import BytesIO
from datetime import date, datetime  # Certifique-se de ter isso no topo do arquivo
from flask_login import login_user
from dateutil.relativedelta import relativedelta
from datetime import timedelta
import secrets
import qrcode
import base64
from forms import MessageForm, RegistrationForm, LoginForm, AnimalForm, EditProfileForm, ResetPasswordRequestForm, ResetPasswordForm
from admin import init_admin
from flask_migrate import Migrate, upgrade, migrate, init
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from flask_login import LoginManager, login_required, current_user, logout_user

from models import (VacinaModelo, Vacina, ExameSolicitado, BlocoExames, ExameModelo, Clinica, ConsultaToken, Consulta, Medicamento, Prescricao, BlocoPrescricao,
                    Veterinario, User, Animal, Message, Transaction, Review, Favorite, AnimalPhoto, Interest
                    )
from extensions import db
from wtforms.fields import SelectField
from config import Config
from flask import Flask, jsonify, render_template, redirect, url_for, request, session, flash


import sys
import os
from werkzeug.utils import secure_filename


from math import ceil

from helpers import calcular_idade, parse_data_nascimento

from flask_mail import Mail, Message as MailMessage


sys.path.append(os.path.dirname(os.path.abspath(__file__)))


app = Flask(__name__, static_folder='static')
UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


app.config.from_object(Config)


migrate = Migrate(app, db)

db.init_app(app)  # Aqui sim você registra o app corretamente
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


app.config['SERVER_NAME'] = 'petorlandia.onrender.com'



with app.app_context():
    init_admin(app)      # ⬅️ Primeiro registra o admin e os modelos
    db.create_all()      # ⬅️ Só depois chama o create_all()


@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


from itsdangerous import URLSafeTimedSerializer




# Serializer for generating token
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

@app.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = s.dumps(user.email, salt='password-reset-salt')
            link = url_for('reset_password', token=token, _external=True)
            msg = MailMessage(
                subject='Redefinir sua senha - PetOrlândia',
                sender='noreply@petorlandia.com',
                recipients=[user.email]
            )
            msg.html = f"""
                <!DOCTYPE html>
                <html lang="pt-BR">
                <head>
                    <meta charset="UTF-8">
                    <title>Redefinição de Senha - PetOrlândia</title>
                </head>
                <body style="font-family: Arial, sans-serif; background-color: #f8f9fa; margin: 0; padding: 20px;">
                    <table align="center" style="max-width: 600px; background: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                        <tr>
                            <td align="center">
                                <h2 style="color: #0d6efd;">🐾 PetOrlândia</h2>
                            </td>
                        </tr>
                        <tr>
                            <td>
                                <p>Olá,</p>
                                <p>Recebemos uma solicitação para redefinir a sua senha.</p>
                                <p>Para criar uma nova senha, clique no botão abaixo:</p>
                                <div style="text-align: center; margin: 30px 0;">
                                    <a href="{link}" style="background-color: #0d6efd; color: white; padding: 14px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Redefinir Senha</a>
                                </div>
                                <p style="font-size: 0.9em; color: #6c757d;">
                                    Se você não solicitou esta alteração, pode ignorar este e-mail com segurança.
                                </p>
                                <hr style="border: none; border-top: 1px solid #dee2e6; margin: 30px 0;">
                                <p style="font-size: 0.8em; color: #adb5bd; text-align: center;">
                                    PetOrlândia • Cuidando com amor dos seus melhores amigos
                                </p>
                            </td>
                        </tr>
                    </table>
                </body>
                </html>
                """



            msg.body = f'Clique no link para redefinir sua senha: {link}'
            mail.send(msg)
            flash('Um e-mail foi enviado com instruções para redefinir sua senha.', 'info')
            return redirect(url_for('login'))
        else:
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





# Rota principal


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('Email já está em uso.', 'danger')
            return render_template('register.html', form=form)

        user = User(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            address=form.address.data,
            profile_photo=form.profile_photo.data
        )

        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Usuário registrado com sucesso!', 'success')

        print("Método do form:", request.method)
        print("Erros do form:", form.errors)

        return redirect(url_for('index'))

    return render_template('register.html', form=form)


@app.route('/add-animal', methods=['GET', 'POST'])
@login_required
def add_animal():
    form = AnimalForm()

    if form.validate_on_submit():
        # Salvar o arquivo de imagem
        filename = None
        if form.image.data:
            filename = secure_filename(form.image.data.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            form.image.data.save(image_path)

        # Criar o animal com o caminho da imagem (caso tenha)
        animal = Animal(
            name=form.name.data,
            species=form.species.data,
            breed=form.breed.data,
            age=form.age.data,
            sex=form.sex.data,
            description=form.description.data,
            image=f"/static/uploads/{filename}" if filename else None,
            status='disponível',
            owner=current_user
        )

        db.session.add(animal)
        db.session.commit()
        flash('Animal cadastrado com sucesso!', 'success')

        print("Método do form:", request.method)
        print("Erros do form:", form.errors)

        return redirect(url_for('index'))

    return render_template('add_animal.html', form=form)


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
    form = EditProfileForm(obj=current_user)

    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.email = form.email.data
        current_user.phone = form.phone.data
        current_user.address = form.address.data

        if form.profile_photo.data and hasattr(form.profile_photo.data, 'filename') and form.profile_photo.data.filename != '':
            filename = secure_filename(form.profile_photo.data.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            form.profile_photo.data.save(path)
            current_user.profile_photo = f"/static/uploads/{filename}"

        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    # Apenas envia as 3 primeiras transações
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
    per_page = 12
    modo = request.args.get('modo')

    query = Animal.query.filter(Animal.removido_em == None)  # 🧠 ignora animais removidos

    if modo:
        query = query.filter_by(modo=modo)

    total_animais = query.count()
    animals = query.order_by(Animal.date_added.desc()).offset((page - 1) * per_page).limit(per_page).all()
    total_pages = ceil(total_animais / per_page)

    return render_template(
        'animals.html',
        animals=animals,
        page=page,
        total_pages=total_pages,
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
@login_required
def editar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if animal.user_id != current_user.id:
        flash('Você não tem permissão para editar este animal.', 'danger')
        return redirect(url_for('profile'))

    form = AnimalForm(obj=animal)  # <- AQUI é onde o form é definido

    if form.validate_on_submit():
        animal.name = form.name.data
        animal.species = form.species.data
        animal.breed = form.breed.data
        animal.age = form.age.data
        animal.sex = form.sex.data
        animal.description = form.description.data
        animal.status = 'disponível'
        animal.modo = form.modo.data
        animal.price = form.price.data

        if form.image.data and hasattr(form.image.data, 'filename'):
            filename = secure_filename(form.image.data.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            form.image.data.save(path)
            animal.image = f"/static/uploads/{filename}"

        db.session.commit()
        flash('Animal atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    return render_template('editar_animal.html', form=form, animal=animal)


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
    animais_do_usuario = Animal.query.filter_by(user_id=current_user.id).all()
    return render_template('plano_saude_overview.html', animais=animais_do_usuario)


@app.route('/animal/<int:animal_id>/ficha')
@login_required
def ficha_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    # Consultas finalizadas
    consultas = (Consulta.query
                 .filter_by(animal_id=animal.id, status='finalizada')
                 .order_by(Consulta.created_at.desc())
                 .all())

    # Buscar blocos de prescrição e exames relacionados
    blocos_prescricao = BlocoPrescricao.query.join(Consulta).filter(Consulta.animal_id == animal.id).all()
    blocos_exames = BlocoExames.query.join(Consulta).filter(Consulta.animal_id == animal.id).all()

    return render_template(
        'ficha_animal.html',
        animal=animal,
        consultas=consultas,
        blocos_prescricao=blocos_prescricao,
        blocos_exames=blocos_exames,
         vacinas = db.relationship('Vacina', backref='animal', lazy=True, cascade="all, delete-orphan")
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
        abort(403)  # forbidden access if not vet or colaborador

    animal = Animal.query.get_or_404(animal_id)
    tutor  = animal.owner

    edit_id = request.args.get('c', type=int)
    edit_mode = False

    # Only veterinarians should create or edit consultations
    if current_user.worker == 'veterinario':
        if edit_id:  # ← veio do botão Editar
            consulta = Consulta.query.get_or_404(edit_id)
            edit_mode = True
        else:  # fluxo normal
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
        consulta = None  # colaboradores can't create or edit consultations

    # Historical consultations: veterinário sees them; colaborador maybe not
    historico = []
    if current_user.worker == 'veterinario':
        historico = (Consulta.query
                    .filter_by(animal_id=animal.id, status='finalizada')
                    .order_by(Consulta.created_at.desc())
                    .all())

    return render_template('consulta_qr.html',
                           animal=animal,
                           tutor=tutor,
                           consulta=consulta,
                           historico_consultas=historico,
                           edit_mode=edit_mode,
                           worker=current_user.worker)  # sending worker role




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


# ———  BUSCAR / CRIAR TUTORES  ——————————————————————————
@app.route('/tutores', methods=['GET', 'POST'])
@login_required
def tutores():
    """Página de busca de tutor + criação rápida."""
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))


    if request.method == 'POST':
        # Pega os campos principais
        name  = request.form.get('tutor_name') or request.form.get('name')
        email = request.form.get('tutor_email') or request.form.get('email')

        if not name or not email:
            flash('Nome e e‑mail são obrigatórios.', 'warning')
            return redirect(url_for('tutores'))

        # Evita duplicidade por e‑mail
        if User.query.filter_by(email=email).first():
            flash('Já existe um tutor com esse e‑mail.', 'warning')
            return redirect(url_for('tutores'))

        # Cria o novo usuário
        novo = User(name=name.strip(), email=email.strip(), role='adotante')
        novo.set_password('123456789')  # senha padrão

        # Tenta pegar campos extras
        phone = request.form.get('tutor_phone') or request.form.get('phone')
        address = request.form.get('tutor_address') or request.form.get('address')
        cpf = request.form.get('tutor_cpf') or request.form.get('cpf')
        rg = request.form.get('tutor_rg') or request.form.get('rg')
        date_str = request.form.get('tutor_date_of_birth') or request.form.get('date_of_birth')

        # Salva se existirem
        novo.phone = phone.strip() if phone else None
        novo.address = address.strip() if address else None
        novo.cpf = cpf.strip() if cpf else None
        novo.rg = rg.strip() if rg else None

        if date_str:
            try:
                novo.date_of_birth = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
            except ValueError:
                flash('Data de nascimento inválida. Use o formato AAAA-MM-DD.', 'danger')
                return redirect(url_for('tutores'))

        # Tenta salvar a imagem se foi enviada
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            novo.profile_photo = f"/static/uploads/{filename}"

        # Salva no banco
        db.session.add(novo)
        db.session.commit()

        flash('Tutor criado com sucesso!', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=novo.id))

    # — GET — apenas exibe a página
    return render_template('tutores.html')



@app.route('/deletar_tutor/<int:tutor_id>', methods=['POST'])
@login_required
def deletar_tutor(tutor_id):
    tutor = User.query.get_or_404(tutor_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir tutores.', 'danger')
        return redirect(url_for('index'))

    db.session.delete(tutor)
    db.session.commit()
    flash('Tutor e todos os seus animais foram excluídos com sucesso!', 'success')
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

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar dados do tutor.', 'danger')
        return redirect(request.referrer or url_for('index'))

    # Segurança: validação mínima de nome
    nome = request.form.get('tutor_name')  # ⚠️ conferindo o nome correto do campo
    if not nome:
        flash('O nome do tutor é obrigatório.', 'danger')
        return redirect(request.referrer or url_for('index'))

    user.name = nome
    user.phone = request.form.get('tutor_phone')
    user.address = request.form.get('tutor_address')
    user.cpf = request.form.get('tutor_cpf')
    user.rg = request.form.get('tutor_rg')

    # Data de nascimento com tratamento robusto
    date_str = request.form.get('tutor_date_of_birth')
    if date_str:
        try:
            user.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Data de nascimento inválida. Use o formato correto.', 'danger')
            return redirect(request.referrer or url_for('index'))

    # Upload de imagem (caso exista)
    if 'image' in request.files and request.files['image'].filename != '':
        file = request.files['image']
        filename = secure_filename(file.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)
        user.profile_photo = f"/static/uploads/{filename}"

    try:
        db.session.commit()
        flash('Dados do tutor atualizados com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao salvar: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('index'))




# ——— FICHA DO TUTOR (dados + lista de animais) ————————————
@app.route('/ficha_tutor/<int:tutor_id>')
@login_required
def ficha_tutor(tutor_id):
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))


    tutor   = User.query.get_or_404(tutor_id)
    animais = Animal.query.filter_by(user_id=tutor.id).order_by(Animal.name).all()
    current_year = datetime.now().year

    return render_template('tutor_detail.html',
                           tutor=tutor,
                           animais=animais,
                           current_year=current_year)




@app.route('/update_animal/<int:animal_id>', methods=['POST'])
@login_required
def update_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar dados do animal.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal.name = request.form.get('name')
    animal.species = request.form.get('species')
    animal.breed = request.form.get('breed')
    animal.sex = request.form.get('sex')
    animal.description = request.form.get('description')
    animal.microchip_number = request.form.get('microchip_number')
    animal.health_plan = request.form.get('health_plan')
    animal.neutered = request.form.get('neutered') == '1'

    # 📅 Aqui está a data
    animal.date_of_birth = parse_data_nascimento(request.form.get('date_of_birth'))


    peso_valor = request.form.get('peso')
    if peso_valor:
        try:
            animal.peso = float(peso_valor)
        except ValueError:
            flash('Peso inválido. Deve ser um número.', 'warning')
    else:
        animal.peso = None

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
            flash('Idade inválida. Deve ser um número.', 'warning')

    if 'image' in request.files and request.files['image'].filename != '':
        image_file = request.files['image']
        filename = secure_filename(image_file.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(path)
        animal.image = f"/static/uploads/{filename}"

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
    from models import Medicamento

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


@app.route('/consulta/<int:consulta_id>/prescricao/lote', methods=['POST'])
@login_required
def salvar_prescricoes_lote(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    data = request.get_json()
    novas_prescricoes = data.get('prescricoes', [])

    for item in novas_prescricoes:
        nova = Prescricao(
            consulta_id=consulta.id,
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
    bloco = BlocoPrescricao(consulta_id=consulta.id, instrucoes_gerais=instrucoes)
    db.session.add(bloco)
    db.session.flush()  # Garante o ID do bloco

    for item in lista_prescricoes:
        nova = Prescricao(
            consulta_id=consulta.id,
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

    consulta_id = bloco.consulta_id
    db.session.delete(bloco)
    db.session.commit()
    flash('Bloco de prescrição excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct',
                        animal_id=Consulta.query.get(consulta_id).animal_id))

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
            consulta_id=bloco.consulta_id,
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

    consulta = bloco.consulta
    animal = consulta.animal
    tutor = animal.owner

    # Pegando a clínica do veterinário (se houver)
    clinica = None
    if current_user.veterinario:
        clinica = current_user.veterinario.clinica

    return render_template(
        'imprimir_bloco.html',
        bloco=bloco,
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica  # ✅ incluído
    )


@app.route('/consulta/<int:consulta_id>/bloco_exames', methods=['POST'])
@login_required
def salvar_bloco_exames(consulta_id):
    data = request.get_json()
    exames_data = data.get('exames', [])
    observacoes_gerais = data.get('observacoes_gerais', '')

    bloco = BlocoExames(consulta_id=consulta_id, observacoes_gerais=observacoes_gerais)
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

    # Corrige o acesso à clínica via modelo Veterinario
    veterinario = Veterinario.query.filter_by(user_id=bloco.consulta.created_by).first()
    clinica = veterinario.clinica if veterinario else Clinica.query.first()

    return render_template('imprimir_exames.html', bloco=bloco, clinica=clinica)


@app.route('/bloco_exames/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir blocos de exames.', 'danger')
        return redirect(request.referrer or url_for('index'))

    consulta_id = bloco.consulta_id
    db.session.delete(bloco)
    db.session.commit()

    flash('Bloco de exames excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=Consulta.query.get(consulta_id).animal_id))



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
        role='adotante'
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
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(path)
            image_path = f"/static/uploads/{filename}"

        animal = Animal(
            name=request.form.get('name'),
            species=request.form.get('species'),
            breed=request.form.get('breed'),
            sex=request.form.get('sex'),
            date_of_birth=dob,
            microchip_number=request.form.get('microchip_number'),
            peso=peso,
            health_plan=request.form.get('health_plan'),
            neutered=neutered,
            user_id=tutor.id,
            status='disponível',
            image=image_path
        )
        db.session.add(animal)
        db.session.commit()

        consulta = Consulta(animal_id=animal.id,
                            created_by=current_user.id,
                            status='in_progress')
        db.session.add(consulta)
        db.session.commit()

        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('consulta_direct', animal_id=animal.id))

    return render_template('novo_animal.html')








@app.route('/loja')
@login_required
def loja():
    return render_template('loja.html')
