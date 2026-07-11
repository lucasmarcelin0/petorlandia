"""Views do domínio auth_routes (migrado do app.py)."""
from flask import Blueprint
import os, uuid
from datetime import datetime
from extensions import csrf, db, limiter, mail
from services.product_analytics import track_event
from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message as MailMessage
from forms import ChangePasswordForm, DeleteAccountForm, EditProfileForm, FirstAccessPasswordForm, FirstAccessPhoneForm, LoginForm, RegistrationForm, ResetPasswordForm, ResetPasswordRequestForm
from models import Endereco, Transaction, User
from sqlalchemy import func
from template_filters import normalize_email, normalize_phone
from time_utils import BR_TZ
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

# Helpers ainda hospedados no app.py (realocação em fases futuras).
from app import (  # noqa: E402
    _first_access_invite_from_token,
    _first_access_next_url,
    _first_access_user_allowed,
    _first_access_user_from_signed_token,
    _geocode_endereco,
    _is_provisional_first_access_user,
    _sanitize_login_next_url,
    _update_coordinates_from_request,
    find_user_by_login_identifier,
    find_users_by_phone,
    s,
)

bp = Blueprint("auth_routes", __name__)


def get_blueprint():
    return bp


def upload_to_s3(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.upload_to_s3.
    import app as app_module
    return app_module.upload_to_s3(*args, **kwargs)



@bp.route("/reset_password_request", methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
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
                sender=current_app.config['MAIL_DEFAULT_SENDER'],
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
            try:
                mail.send(msg)
            except Exception as exc:  # noqa: BLE001 - evita erro 500 quando SMTP não está configurado
                current_app.logger.warning(
                    "Falha ao enviar e-mail de redefinição de senha para %s: %s",
                    user.email,
                    exc,
                )
                message = (
                    "Não foi possível enviar o e-mail de redefinição agora. "
                    "Verifique a configuração de e-mail e tente novamente."
                )
                if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                    return jsonify({
                        'success': False,
                        'errors': {'email': [message]},
                        'message': message,
                    }), 503
                flash(message, 'warning')
                return render_template('auth/reset_password_request.html', form=form), 200
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('login_view')})
            flash('Um e-mail foi enviado com instruções para redefinir sua senha.', 'info')
            return redirect(url_for('login_view'))
        if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
            return jsonify({'success': False, 'errors': {'email': ['E-mail não encontrado.']}}), 400
        flash('E-mail não encontrado.', 'danger')
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        errors = {field: messages for field, messages in form.errors.items()}
        return jsonify({'success': False, 'errors': errors}), 400
    return render_template('auth/reset_password_request.html', form=form)


@bp.route("/reset_password/<token>", methods=['GET', 'POST'])
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
            return redirect(url_for('login_view'))
    return render_template('auth/reset_password.html', form=form)


@bp.route("/primeiro-acesso", methods=['GET', 'POST'])
@csrf.exempt
@limiter.limit("10 per minute", methods=["POST"])
def first_access():
    if current_user.is_authenticated:
        return redirect(_sanitize_login_next_url(request.args.get('next')))

    form = FirstAccessPhoneForm()
    token = (request.values.get('token') or '').strip()
    invite = _first_access_invite_from_token(token)
    token_user = None if invite else _first_access_user_from_signed_token(token)
    if request.method == 'GET' and token_user and token_user.phone:
        form.phone.data = token_user.phone
    if token and not invite and not token_user:
        flash('Este link de primeiro acesso expirou ou é inválido.', 'warning')

    if form.validate_on_submit():
        matches = find_users_by_phone(form.phone.data)
        if len(matches) > 1:
            flash('Há mais de uma conta com este celular. Entre com seu e-mail ou fale com a clínica.', 'warning')
            return render_template('auth/first_access_phone.html', form=form, invite=invite, token=token, next_url=request.form.get('next') or '')
        user = matches[0] if matches else None
        if not user or not _first_access_user_allowed(user, invite, token_user):
            flash('Não encontramos um primeiro acesso ativo para este celular.', 'danger')
            return render_template('auth/first_access_phone.html', form=form, invite=invite, token=token, next_url=request.form.get('next') or '')

        session['first_access_user_id'] = user.id
        session['first_access_invite_token'] = token if invite else ''
        if token_user:
            session['first_access_token_user_id'] = token_user.id
        else:
            session.pop('first_access_token_user_id', None)
        session['first_access_next'] = _first_access_next_url(invite)
        return redirect(url_for('first_access_password'))

    return render_template('auth/first_access_phone.html', form=form, invite=invite, token=token, next_url=request.args.get('next') or '')


@bp.route("/primeiro-acesso/senha", methods=['GET', 'POST'])
@csrf.exempt
def first_access_password():
    user_id = session.get('first_access_user_id')
    if not user_id:
        flash('Informe seu celular para começar o primeiro acesso.', 'info')
        return redirect(url_for('first_access'))

    user = db.session.get(User, int(user_id))
    invite = _first_access_invite_from_token(session.get('first_access_invite_token'))
    token_user_id = session.get('first_access_token_user_id')
    token_user = db.session.get(User, int(token_user_id)) if token_user_id else None
    if not _first_access_user_allowed(user, invite, token_user):
        session.pop('first_access_user_id', None)
        session.pop('first_access_invite_token', None)
        session.pop('first_access_token_user_id', None)
        session.pop('first_access_next', None)
        flash('Não encontramos um primeiro acesso ativo para este celular.', 'danger')
        return redirect(url_for('first_access'))

    form = FirstAccessPasswordForm()
    if request.method == 'GET':
        email = normalize_email(getattr(user, 'email', None))
        if email and not _is_provisional_first_access_user(user):
            form.email.data = email

    if form.validate_on_submit():
        normalized_email = normalize_email(form.email.data)
        if normalized_email:
            existing = User.query.filter(
                func.lower(User.email) == normalized_email,
                User.id != user.id,
            ).first()
            if existing:
                form.email.errors.append('Este e-mail já pertence a outra conta.')
                return render_template('auth/first_access_password.html', form=form, user=user, invite=invite)
            user.email = normalized_email

        user.set_password(form.password.data)
        if invite and not invite.used_at:
            invite.used_at = datetime.now(BR_TZ)
        db.session.commit()

        next_url = _sanitize_login_next_url(session.pop('first_access_next', None))
        session.pop('first_access_user_id', None)
        session.pop('first_access_invite_token', None)
        session.pop('first_access_token_user_id', None)
        login_user(user, remember=True)
        session.permanent = True
        flash('Senha cadastrada com sucesso. Você já está conectado.', 'success')
        return redirect(next_url)

    return render_template('auth/first_access_password.html', form=form, user=user, invite=invite)


@bp.route("/register", methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    form = RegistrationForm()
    is_json_request = request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']

    # Programa de indicação: guarda o código vindo de ?ref= para creditar após o cadastro.
    ref_code = (request.args.get('ref') or '').strip()
    if ref_code:
        session['referral_code'] = ref_code[:16]

    if form.validate_on_submit():
        normalized_email = normalize_email(form.email.data)
        normalized_phone = normalize_phone(form.phone.data)

        # Verifica se o e-mail já está em uso
        existing_user = User.query.filter(func.lower(User.email) == normalized_email).first()
        if existing_user:
            if is_json_request:
                return jsonify({'success': False, 'errors': {'email': ['Email já está em uso.']}, 'message': 'Email já está em uso.'}), 400
            flash('Email já está em uso.', 'danger')
            return render_template('auth/register.html', form=form, endereco=None)

        if normalized_phone and find_users_by_phone(normalized_phone):
            if is_json_request:
                return jsonify({'success': False, 'errors': {'phone': ['Celular já está em uso.']}, 'message': 'Celular já está em uso.'}), 400
            flash('Celular já está em uso.', 'danger')
            return render_template('auth/register.html', form=form, endereco=None)

        # Address is progressive: only validate it when the user starts filling
        # the section. A tutor can create an account before choosing delivery.
        address_started = any(
            (request.form.get(key) or '').strip()
            for key in ('cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado')
        )
        required_address_labels = {
            'rua': 'Rua',
            'cidade': 'Cidade',
            'estado': 'Estado',
        } if address_started else {}

        required_missing = [
            label for key, label in required_address_labels.items()
            if not (request.form.get(key) or '').strip()
        ]

        if required_missing:
            message = 'Preencha os campos obrigatórios do endereço: ' + ', '.join(required_missing) + '.'
            if is_json_request:
                return jsonify({'success': False, 'errors': {'endereco': [message]}, 'message': message}), 400
            flash(message, 'warning')
            return render_template('auth/register.html', form=form, endereco=None)

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
        if not address_started:
            endereco = None
        if endereco is not None and not _update_coordinates_from_request(endereco):
            # Sem geocodificação síncrona aqui: as chamadas externas (Nominatim)
            # podem levar dezenas de segundos e estourar o timeout do Heroku,
            # derrubando o cadastro. As coordenadas ficam nulas e podem ser
            # calculadas depois, quando forem necessárias.
            endereco.latitude = None
            endereco.longitude = None

        # Upload da foto de perfil para o S3 — nunca pode impedir a criação da conta
        photo_url = None
        if form.profile_photo.data and getattr(form.profile_photo.data, 'filename', ''):
            try:
                file = form.profile_photo.data
                filename = secure_filename(file.filename)
                photo_url = upload_to_s3(file, filename, folder="users")
            except Exception:
                current_app.logger.exception('Falha ao enviar foto de perfil no cadastro; conta criada sem foto')
                photo_url = None


        # Cria o usuário com a URL da imagem no S3
        user = User(
            name=form.name.data,
            email=normalized_email,
            phone=normalized_phone,
            profile_photo=photo_url,
            endereco=endereco
        )
        user.set_password(form.password.data)

        # Salva no banco com tratamento de erros
        try:
            if endereco is not None:
                db.session.add(endereco)
            db.session.add(user)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            error_message = str(e).lower()
            if 'phone' in error_message or 'telefone' in error_message or 'celular' in error_message:
                if is_json_request:
                    return jsonify({'success': False, 'errors': {'phone': ['Celular já está em uso.']}, 'message': 'Celular já está em uso.'}), 400
                flash('Celular já está em uso.', 'danger')
            elif 'unique' in error_message or 'duplicate' in error_message or 'email' in error_message:
                if is_json_request:
                    return jsonify({'success': False, 'errors': {'email': ['Email já está em uso.']}, 'message': 'Email já está em uso.'}), 400
                flash('Email já está em uso.', 'danger')
            else:
                if is_json_request:
                    return jsonify({'success': False, 'errors': {'form': ['Erro ao criar conta. Tente novamente.']}, 'message': 'Erro ao criar conta.'}), 500
                flash('Erro ao criar conta. Tente novamente.', 'danger')
            return render_template('auth/register.html', form=form, endereco=None)

        # Programa de indicação: credita quem indicou (não bloqueia o cadastro em caso de erro).
        try:
            referral_code_value = session.pop('referral_code', None)
            if referral_code_value:
                from models import ReferralCode, ReferralSignup
                referral = ReferralCode.query.filter_by(code=referral_code_value).first()
                if referral and referral.user_id != user.id:
                    db.session.add(ReferralSignup(code_id=referral.id, referred_user_id=user.id))
                    db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Falha ao registrar indicação no cadastro')

        # Faz login automático do usuário recém-criado
        login_user(user)
        track_event('signup_completed', role=getattr(user, 'role', None))

        if is_json_request:
            return jsonify({'success': True, 'redirect': url_for('index')})
        flash('Usuário registrado com sucesso!', 'success')
        return redirect(url_for('index'))

    if request.method == 'POST' and is_json_request:
        errors = dict(form.errors) if form.errors else {}
        if 'csrf_token' in errors:
            message = 'Sua sessão expirou. Recarregue a página e tente novamente.'
        elif errors:
            message = 'Confira os campos destacados e tente novamente.'
        else:
            errors = {'form': ['Não foi possível validar o formulário. Recarregue a página e tente novamente.']}
            message = 'Não foi possível criar a conta. Recarregue a página e tente novamente.'
        return jsonify({'success': False, 'errors': errors, 'message': message}), 400

    return render_template('auth/register.html', form=form, endereco=None)


@bp.route("/login", methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login_view():
    form = LoginForm()
    next_url = request.values.get('next') or url_for('index')
    next_url = _sanitize_login_next_url(next_url)
    oauth_login_flow = urlparse(next_url).path == '/oauth/authorize'
    if request.method == 'POST' and not form.login.data and request.form.get('email'):
        form.login.data = request.form.get('email')
    is_json_request = request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']

    if form.validate_on_submit():
        user, login_error = find_user_by_login_identifier(form.login.data)
        if login_error:
            if is_json_request:
                return jsonify({'success': False, 'errors': {'login': [login_error]}, 'message': login_error}), 400
            flash(login_error, 'warning')
            return render_template(
                'auth/login.html',
                form=form,
                next_url=next_url,
                oauth_login_flow=oauth_login_flow,
            )

        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            track_event('login_succeeded', role=getattr(user, 'role', None))
            if form.remember.data:
                session.permanent = True
            if is_json_request:
                return jsonify({'success': True, 'redirect': next_url})
            flash('Login realizado com sucesso!', 'success')
            return redirect(next_url)
        else:
            if is_json_request:
                return jsonify({'success': False, 'errors': {'login': ['E-mail, celular ou senha inválidos.']}, 'message': 'E-mail, celular ou senha inválidos.'}), 400
            flash('E-mail, celular ou senha inválidos.', 'danger')
    elif request.method == 'POST' and is_json_request:
        # Captura erros de validação do formulário (incluindo CSRF)
        errors = {}
        if form.errors:
            errors = {field: messages for field, messages in form.errors.items()}
        # Se não houver erros específicos, pode ser um erro de CSRF
        if not errors:
            errors = {'form': ['Erro na validação do formulário. Por favor, recarregue a página e tente novamente.']}
        return jsonify({'success': False, 'errors': errors, 'message': 'Não foi possível processar o login.'}), 400

    return render_template(
        'auth/login.html',
        form=form,
        next_url=next_url,
        oauth_login_flow=oauth_login_flow,
    )


@bp.route("/logout", methods=['GET'])
@login_required
def logout():
    logout_user()
    flash('Você saiu com sucesso!', 'success')
    return redirect(url_for('index'))


@bp.route("/profile", methods=['GET', 'POST'])
@login_required
def profile():
    form = EditProfileForm(obj=current_user)
    delete_form = DeleteAccountForm()
    is_json_request = request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']

    if form.validate_on_submit():
        normalized_email = normalize_email(form.email.data)
        normalized_phone = normalize_phone(form.phone.data)

        required_address_labels = {
            'cep': 'CEP',
            'rua': 'Rua',
            'cidade': 'Cidade',
            'estado': 'Estado',
        }

        missing_required = [
            label for key, label in required_address_labels.items()
            if not (request.form.get(key) or '').strip()
        ]

        if missing_required:
            message = 'Preencha os campos obrigatórios do endereço: ' + ', '.join(missing_required) + '.'
            if is_json_request:
                return jsonify({'success': False, 'errors': {'endereco': [message]}}), 400
            flash(message, 'warning')
            return redirect(url_for('profile'))

        email_conflict = User.query.filter(
            func.lower(User.email) == normalized_email,
            User.id != current_user.id,
        ).first()
        if email_conflict:
            if is_json_request:
                return jsonify({'success': False, 'errors': {'email': ['Email já está em uso.']}}), 400
            flash('Email já está em uso.', 'danger')
            return redirect(url_for('profile'))

        if normalized_phone and find_users_by_phone(normalized_phone, exclude_user_id=current_user.id):
            if is_json_request:
                return jsonify({'success': False, 'errors': {'phone': ['Celular já está em uso.']}}), 400
            flash('Celular já está em uso.', 'danger')
            return redirect(url_for('profile'))

        current_user.name = form.name.data
        current_user.email = normalized_email
        current_user.phone = normalized_phone
        current_user.is_private = form.is_private.data
        current_user.photo_rotation = form.photo_rotation.data
        current_user.photo_zoom = form.photo_zoom.data
        current_user.photo_offset_x = form.photo_offset_x.data
        current_user.photo_offset_y = form.photo_offset_y.data

        # Atualiza ou cria endereço somente depois de validar os campos obrigatórios.
        endereco = current_user.endereco or Endereco()
        current_user.endereco = endereco
        endereco.cep = request.form.get("cep")
        endereco.rua = request.form.get("rua")
        endereco.numero = request.form.get("numero")
        endereco.complemento = request.form.get("complemento")
        endereco.bairro = request.form.get("bairro")
        endereco.cidade = request.form.get("cidade")
        endereco.estado = request.form.get("estado")

        if not _update_coordinates_from_request(endereco):
            _geocode_endereco(endereco)
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
        'auth/profile.html',
        user=current_user,
        form=form,
        delete_form=delete_form,
        transactions=transactions
    )


@bp.route("/change_password", methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': False, 'errors': {'current_password': ['Senha atual incorreta.']}}), 400
            flash('Senha atual incorreta.', 'danger')
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('profile')})
            flash('Senha atualizada com sucesso!', 'success')
            return redirect(url_for('profile'))
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        errors = {field: messages for field, messages in form.errors.items()}
        return jsonify({'success': False, 'errors': errors}), 400
    return render_template('auth/change_password.html', form=form)


@bp.route("/delete_account", methods=['POST'])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if form.validate_on_submit():
        # Capture the actual user object before logging out because
        # `current_user` becomes `AnonymousUserMixin` after logout.
        user = current_user._get_current_object()

        # Remove mensagens associadas ao usuário antes de excluí-lo
        for msg in list(user.sent_messages) + list(user.received_messages):
            db.session.delete(msg)

        # Remove pagamentos vinculados ao usuário antes de excluí-lo
        for payment in list(user.payments):
            # Desassocia assinaturas que usam este pagamento
            for sub in list(payment.subscriptions):
                sub.payment = None
            db.session.delete(payment)

        logout_user()
        db.session.delete(user)
        db.session.commit()
        flash('Sua conta foi excluída.', 'success')
        return redirect(url_for('index'))
    flash('Operação inválida.', 'danger')
    return redirect(url_for('profile'))

