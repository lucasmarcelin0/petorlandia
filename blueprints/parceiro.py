"""Parceiros (estabelecimentos, onboarding por convite) — views do domínio."""
import hashlib
import secrets
from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user
from sqlalchemy import func

from document_utils import format_cnpj as format_cnpj_value, only_digits
from extensions import db
from helpers import parceiro_required
from models import CasaDeRacao, Clinica, PartnerInvite, User, Veterinario
from template_filters import normalize_email, normalize_phone

# Helper ainda hospedado no app.py (realocação em fase futura).
from app import find_users_by_phone

bp = Blueprint("parceiro_routes", __name__)


def get_blueprint():
    return bp


def _is_admin():
    # Late-binding: testes fazem monkeypatch de ``app._is_admin``.
    import app as app_module

    return app_module._is_admin()


_PARTNER_INVITE_ESTABLISHMENT_TIPOS = {'clinica', 'casa_de_racao', 'petshop', 'banho_tosa'}


def _parceiro_resolve_owner(form):
    """Resolve o usuário dono conforme ``owner_mode``.

    Retorna ``(owner, senha_temporaria, erro)``. ``senha_temporaria`` só é
    preenchida quando um novo usuário é criado, para que o parceiro possa
    repassá-la ao dono.
    """
    mode = (form.owner_mode.data or 'new').strip()
    if mode == 'self':
        return current_user, None, None

    email = (form.owner_email.data or '').strip().lower()
    if mode == 'existing':
        owner = User.query.filter(func.lower(User.email) == email).first()
        if not owner:
            return None, None, 'Nenhum usuário encontrado com esse e-mail.'
        return owner, None, None

    # mode == 'new'
    if User.query.filter(func.lower(User.email) == email).first():
        return None, None, 'Já existe um usuário com esse e-mail. Use "vincular a um usuário existente".'
    senha = secrets.token_urlsafe(6)
    owner = User(
        name=(form.owner_name.data or '').strip(),
        email=email,
        phone=(form.owner_phone.data or '').strip() or None,
        role='adotante',
        added_by=current_user,
        is_private=True,
    )
    owner.set_password(senha)
    db.session.add(owner)
    db.session.flush()
    return owner, senha, None


def _parceiro_estabelecimentos(user):
    """Lista os estabelecimentos cadastrados pelo parceiro (ou todos, se admin)."""
    from models.petsitter import PetsitterProfile

    if _is_admin():
        clinicas = Clinica.query.order_by(Clinica.id.desc()).all()
        casas = CasaDeRacao.query.order_by(CasaDeRacao.id.desc()).all()
        sitters = PetsitterProfile.query.order_by(PetsitterProfile.id.desc()).all()
    else:
        clinicas = (
            Clinica.query.filter_by(registered_by_id=user.id)
            .order_by(Clinica.id.desc())
            .all()
        )
        casas = (
            CasaDeRacao.query.filter_by(registered_by_id=user.id)
            .order_by(CasaDeRacao.id.desc())
            .all()
        )
        sitters = (
            PetsitterProfile.query.filter_by(registered_by_id=user.id)
            .order_by(PetsitterProfile.id.desc())
            .all()
        )
    return clinicas, casas, sitters



@bp.route("/parceiro", methods=["GET"])
@login_required
@parceiro_required
def parceiro_dashboard():
    from services.establishments import establishment_label

    clinicas, casas, sitters = _parceiro_estabelecimentos(current_user)
    total = len(clinicas) + len(casas) + len(sitters)
    return render_template(
        'parceiro/dashboard.html',
        clinicas=clinicas,
        casas=casas,
        sitters=sitters,
        total=total,
        establishment_label=establishment_label,
    )


@bp.route("/parceiro/estabelecimentos/novo", methods=["GET", "POST"])
@login_required
@parceiro_required
def parceiro_novo_estabelecimento():
    from forms import ParceiroEstabelecimentoForm
    from services.establishments import establishment_label

    form = ParceiroEstabelecimentoForm()
    if form.validate_on_submit():
        owner, senha_temp, erro = _parceiro_resolve_owner(form)
        if erro:
            flash(erro, 'danger')
            return render_template('parceiro/novo_estabelecimento.html', form=form)

        tipo = form.tipo.data
        nome = (form.nome.data or '').strip()

        if senha_temp:
            flash(
                f'Usuário {owner.name} criado. Senha temporária: {senha_temp} '
                '(oriente o dono a alterá-la no primeiro acesso).',
                'info',
            )

        if tipo == 'clinica':
            clinica = Clinica(
                nome=nome,
                cnpj=form.cnpj.data or None,
                endereco=form.endereco.data or None,
                telefone=form.telefone.data or None,
                email=form.email.data or None,
                owner_id=owner.id,
                registered_by_id=current_user.id,
            )
            db.session.add(clinica)
            db.session.commit()
            if owner.id != current_user.id:
                owner.clinica_id = clinica.id
                if getattr(owner, 'veterinario', None):
                    owner.veterinario.clinica_id = clinica.id
                db.session.commit()
            flash(f'Clínica "{nome}" cadastrada e ativa.', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#clinica')

        if tipo == 'petsitter':
            from models.petsitter import PetsitterProfile

            if PetsitterProfile.query.filter_by(user_id=owner.id).first():
                flash('Esse usuário já possui um perfil de pet sitter.', 'warning')
                return redirect(url_for('parceiro_dashboard'))
            sitter = PetsitterProfile(
                user_id=owner.id,
                bio=form.descricao.data or None,
                cidade=form.cidade.data or None,
                preco_diaria=form.preco_diaria.data or None,
                status='aprovado',
                registered_by_id=current_user.id,
            )
            db.session.add(sitter)
            db.session.commit()
            flash(f'Pet sitter "{owner.name}" cadastrado e aprovado.', 'success')
            return redirect(url_for('parceiro_dashboard'))

        # casa_de_racao | petshop | banho_tosa — modelo de loja compartilhado
        casa = CasaDeRacao(
            nome=nome,
            tipo=tipo,
            cnpj=form.cnpj.data or None,
            descricao=form.descricao.data or None,
            telefone=form.telefone.data or None,
            email=form.email.data or None,
            endereco=form.endereco.data or None,
            owner_id=owner.id,
            registered_by_id=current_user.id,
            status='ativa',
        )
        db.session.add(casa)
        db.session.commit()
        flash(f'{establishment_label(tipo)} "{nome}" cadastrada e ativa.', 'success')
        return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#produtos')

    return render_template('parceiro/novo_estabelecimento.html', form=form)


@bp.route("/parceiro/usuarios/novo", methods=["GET", "POST"])
@login_required
@parceiro_required
def parceiro_novo_usuario():
    from forms import ParceiroUsuarioForm

    form = ParceiroUsuarioForm()
    if form.validate_on_submit():
        email = (form.email.data or '').strip().lower()
        if User.query.filter(func.lower(User.email) == email).first():
            flash('Já existe um usuário com esse e-mail.', 'danger')
            return render_template('parceiro/novo_usuario.html', form=form)
        senha = secrets.token_urlsafe(6)
        novo = User(
            name=(form.name.data or '').strip(),
            email=email,
            phone=form.phone.data or None,
            cpf=form.cpf.data or None,
            role='adotante',
            added_by=current_user,
            is_private=True,
        )
        novo.set_password(senha)
        db.session.add(novo)
        db.session.commit()
        flash(
            f'Usuário {novo.name} criado. Senha temporária: {senha} '
            '(oriente-o a alterá-la no primeiro acesso).',
            'success',
        )
        return redirect(url_for('parceiro_dashboard'))
    return render_template('parceiro/novo_usuario.html', form=form)


@bp.route("/convite/<string:token>", methods=["GET", "POST"])
def partner_invite_onboarding(token):
    """Página pública de onboarding de um convite de parceria."""
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    invite = PartnerInvite.query.filter_by(token_hash=token_hash).first_or_404()

    if invite.used_at:
        flash('Este convite já foi utilizado. Entre com seu e-mail e senha.', 'info')
        return redirect(url_for('login_view'))
    if invite.is_expired:
        return render_template('parceiro/convite_expirado.html', invite=invite), 410

    precisa_estabelecimento = invite.tipo in _PARTNER_INVITE_ESTABLISHMENT_TIPOS
    precisa_crmv = invite.tipo == 'veterinario'

    errors = []
    values = {
        'nome': invite.nome or '',
        'email': invite.email or '',
        'telefone': invite.telefone or '',
        'estabelecimento_nome': invite.nome or '',
        'cnpj': '',
        'endereco': '',
        'crmv': '',
    }

    if request.method == 'POST':
        values.update({
            'nome': (request.form.get('nome') or '').strip(),
            'email': normalize_email(request.form.get('email')) or '',
            'telefone': (request.form.get('telefone') or '').strip(),
            'estabelecimento_nome': (request.form.get('estabelecimento_nome') or '').strip(),
            'cnpj': (request.form.get('cnpj') or '').strip(),
            'endereco': (request.form.get('endereco') or '').strip(),
            'crmv': (request.form.get('crmv') or '').strip(),
        })
        password = request.form.get('password') or ''
        password_confirmation = request.form.get('password_confirmation') or ''

        usuario = current_user if current_user.is_authenticated else None
        normalized_phone = normalize_phone(values['telefone'])

        if usuario is None:
            if len(values['nome']) < 2:
                errors.append('Informe seu nome completo.')
            if not values['email'] or '@' not in values['email']:
                errors.append('Informe um e-mail válido.')
            elif User.query.filter(func.lower(User.email) == values['email']).first():
                errors.append('Este e-mail já tem conta. Entre primeiro e abra o link do convite de novo.')
            if not normalized_phone:
                errors.append('Informe o celular com DDD.')
            elif find_users_by_phone(normalized_phone):
                errors.append('Este celular já pertence a outra conta.')
            if len(password) < 8:
                errors.append('Crie uma senha com pelo menos 8 caracteres.')
            if password != password_confirmation:
                errors.append('A confirmação da senha não confere.')

        if precisa_estabelecimento and not values['estabelecimento_nome']:
            errors.append('Informe o nome do estabelecimento.')
        if values['cnpj']:
            cnpj_digits = only_digits(values['cnpj'])
            if len(cnpj_digits) != 14:
                errors.append('O CNPJ deve ter 14 dígitos.')
            else:
                values['cnpj'] = format_cnpj_value(cnpj_digits)
        if precisa_crmv:
            if not values['crmv']:
                errors.append('Informe o CRMV.')
            else:
                existing_crmv = Veterinario.query.filter(
                    func.lower(Veterinario.crmv) == values['crmv'].lower()
                )
                if usuario is not None:
                    existing_crmv = existing_crmv.filter(Veterinario.user_id != usuario.id)
                if existing_crmv.first():
                    errors.append('Este CRMV já está cadastrado.')

        if not errors:
            if usuario is None:
                usuario = User(
                    name=values['nome'],
                    email=values['email'],
                    phone=normalized_phone,
                )
                usuario.set_password(password)
                db.session.add(usuario)
                db.session.flush()

            destino = url_for('index')
            if invite.tipo == 'clinica':
                clinica = Clinica(
                    nome=values['estabelecimento_nome'],
                    cnpj=values['cnpj'] or None,
                    endereco=values['endereco'] or None,
                    telefone=usuario.phone,
                    email=usuario.email,
                    owner_id=usuario.id,
                    registered_by_id=invite.created_by_id,
                    status='ativa',
                )
                db.session.add(clinica)
                db.session.flush()
                usuario.clinica_id = clinica.id
                if getattr(usuario, 'veterinario', None):
                    usuario.veterinario.clinica_id = clinica.id
                destino = url_for('clinic_detail', clinica_id=clinica.id) + '#clinica'
            elif invite.tipo in {'casa_de_racao', 'petshop', 'banho_tosa'}:
                casa = CasaDeRacao(
                    nome=values['estabelecimento_nome'],
                    tipo=invite.tipo,
                    cnpj=values['cnpj'] or None,
                    telefone=usuario.phone,
                    email=usuario.email,
                    endereco=values['endereco'] or None,
                    owner_id=usuario.id,
                    registered_by_id=invite.created_by_id,
                    status='ativa',
                )
                db.session.add(casa)
                db.session.flush()
                destino = url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#produtos'
            elif invite.tipo == 'veterinario':
                usuario.worker = 'veterinario'
                if not getattr(usuario, 'veterinario', None):
                    db.session.add(Veterinario(user=usuario, crmv=values['crmv']))
                destino = url_for('index')
            elif invite.tipo == 'petsitter':
                from models.petsitter import PetsitterProfile
                if not PetsitterProfile.query.filter_by(user_id=usuario.id).first():
                    db.session.add(PetsitterProfile(
                        user_id=usuario.id,
                        cidade=invite.cidade,
                        status='aprovado',
                        registered_by_id=invite.created_by_id,
                    ))
                destino = url_for('petsitter_routes.petsitter_home')

            invite.used_at = datetime.now(timezone.utc)
            invite.used_by_id = usuario.id
            db.session.commit()

            if not current_user.is_authenticated:
                login_user(usuario)

            from services.notifications import notify_admins
            notify_admins(
                f'Convite de {invite.tipo_label.lower()} concluído por {usuario.name}.',
                kind='convite_concluido',
                url=url_for('admin_parcerias', _external=True),
            )
            flash('Cadastro concluído! Seja bem-vindo(a) ao PetOrlândia. 🐾', 'success')
            return redirect(destino)

    return render_template(
        'parceiro/convite_onboarding.html',
        invite=invite,
        values=values,
        errors=errors,
        precisa_estabelecimento=precisa_estabelecimento,
        precisa_crmv=precisa_crmv,
    )

