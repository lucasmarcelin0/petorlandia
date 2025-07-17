from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, login_required, logout_user, current_user

try:
    from forms import RegistrationForm, LoginForm, EditProfileForm, ResetPasswordRequestForm, ResetPasswordForm
    from models import User, Endereco, Transaction
    from extensions import db, mail
    from werkzeug.utils import secure_filename
    from s3_utils import upload_to_s3
except ImportError:  # pragma: no cover - fallback for package imports
    from ..forms import RegistrationForm, LoginForm, EditProfileForm, ResetPasswordRequestForm, ResetPasswordForm
    from ..models import User, Endereco, Transaction
    from ..extensions import db, mail
    from werkzeug.utils import secure_filename
    from ..s3_utils import upload_to_s3
from flask_mail import Message as MailMessage
from itsdangerous import URLSafeTimedSerializer
import os
import uuid

auth_bp = Blueprint('auth', __name__)

s = URLSafeTimedSerializer(os.getenv('SECRET_KEY', 'dev'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('Email já está em uso.', 'danger')
            return render_template('register.html', form=form)
        endereco = Endereco(
            cep=request.form.get('cep'),
            rua=request.form.get('rua'),
            numero=request.form.get('numero'),
            complemento=request.form.get('complemento'),
            bairro=request.form.get('bairro'),
            cidade=request.form.get('cidade'),
            estado=request.form.get('estado')
        )
        photo_url = None
        if form.profile_photo.data:
            file = form.profile_photo.data
            filename = secure_filename(file.filename)
            photo_url = upload_to_s3(file, filename, folder='users')
        user = User(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            profile_photo=photo_url,
            endereco=endereco
        )
        user.set_password(form.password.data)
        db.session.add(endereco)
        db.session.add(user)
        db.session.commit()
        flash('Usuário registrado com sucesso!', 'success')
        return redirect(url_for('index'))
    return render_template('register.html', form=form, endereco=None)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        flash('Email ou senha inválidos.', 'danger')
    return render_template('login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu com sucesso!', 'success')
    return redirect(url_for('index'))

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = EditProfileForm(obj=current_user)
    if form.validate_on_submit():
        if not current_user.endereco:
            current_user.endereco = Endereco()
        current_user.name = form.name.data
        current_user.email = form.email.data
        current_user.phone = form.phone.data
        endereco = current_user.endereco
        endereco.cep = request.form.get('cep')
        endereco.rua = request.form.get('rua')
        endereco.numero = request.form.get('numero')
        endereco.complemento = request.form.get('complemento')
        endereco.bairro = request.form.get('bairro')
        endereco.cidade = request.form.get('cidade')
        endereco.estado = request.form.get('estado')
        db.session.add(endereco)
        if (form.profile_photo.data and hasattr(form.profile_photo.data, 'filename') and form.profile_photo.data.filename != ''):
            file = form.profile_photo.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            current_user.profile_photo = upload_to_s3(file, filename, folder='profile_photos')
        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('auth.profile'))
    transactions = Transaction.query.filter((Transaction.from_user_id == current_user.id) | (Transaction.to_user_id == current_user.id)).order_by(Transaction.date.desc()).limit(10).all()
    return render_template('profile.html', user=current_user, form=form, transactions=transactions)

@auth_bp.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = s.dumps(user.email, salt='password-reset-salt')
            base_url = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:5000')
            link = f"{base_url}{url_for('auth.reset_password', token=token)}"
            msg = MailMessage(
                subject='Redefinir sua senha - PetOrlândia',
                sender=mail.default_sender,
                recipients=[user.email],
                body=f'Clique no link para redefinir sua senha: {link}',
                html=f"""
                    <!DOCTYPE html>
                    <html lang='pt-BR'>
                    <head><meta charset='UTF-8'><title>Redefinição de Senha</title></head>
                    <body style='font-family: Arial; padding: 20px;'>
                        <h2>🐾 PetOrlândia</h2>
                        <p>Recebemos uma solicitação para redefinir sua senha.</p>
                        <p><a href='{link}' style='background:#0d6efd;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;'>Redefinir Senha</a></p>
                        <p>Se você não solicitou, ignore este e-mail.</p>
                        <hr><small>PetOrlândia • Cuidando com amor dos seus melhores amigos</small>
                    </body>
                    </html>
                """
            )
            mail.send(msg)
            flash('Um e-mail foi enviado com instruções para redefinir sua senha.', 'info')
            return redirect(url_for('auth.login'))
        flash('E-mail não encontrado.', 'danger')
    return render_template('reset_password_request.html', form=form)

@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except Exception:
        flash('O link de redefinição expirou ou é inválido.', 'danger')
        return redirect(url_for('auth.reset_password_request'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(form.password.data)
            db.session.commit()
            flash('Sua senha foi redefinida. Você já pode entrar!', 'success')
            return redirect(url_for('auth.login'))
    return render_template('reset_password.html', form=form)
