"""Casas de ração / lojas parceiras — views do domínio.

``_is_admin`` e ``upload_to_s3`` são late-bound via módulo app (testes fazem
monkeypatch desses nomes — contrato do antigo lazy_view).
"""
import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from document_utils import format_cnpj as format_cnpj_value, only_digits
from extensions import db
from forms import CasaDeRacaoForm, CasaDeRacaoProductEditForm, CasaDeRacaoProductForm
from models import (
    Animal,
    CasaDeRacao,
    CasaDeRacaoHorario,
    CasaDeRacaoOnboardingInvite,
    DeliveryRequest,
    Endereco,
    Order,
    OrderItem,
    Product,
    Racao,
    StorePaymentAccount,
    TipoRacao,
    User,
)
from security.crypto import MissingMasterKeyError
from services.mercadopago_oauth import (
    MercadoPagoOAuthError,
    build_authorization_start,
    exchange_code_for_credentials,
)
from template_filters import normalize_email, normalize_phone
from time_utils import now_in_brazil, utcnow

from app import (
    _canonicalize_racao_brand,
    _casa_de_racao_product_onboarding_target,
    _casa_loja_access,
    _concluir_entrega_efeitos,
    _create_initial_variant,
    _geocode_endereco,
    _onboarding_decimal,
    _onboarding_final_from_payout,
    _onboarding_money_display,
    _onboarding_payout_from_final,
    _onboarding_prefill_email,
    _onboarding_product_form_state,
    _optional_decimal_from_form,
    _sync_variants_from_request,
    _update_coordinates_from_request,
    _user_can_manage_clinic,
    find_users_by_phone,
    list_rations,
)

bp = Blueprint("casa_de_racao_routes", __name__)


def get_blueprint():
    return bp


def _is_admin():
    import app as app_module

    return app_module._is_admin()


def upload_to_s3(*args, **kwargs):
    import app as app_module

    return app_module.upload_to_s3(*args, **kwargs)


@bp.route("/parceiros/loja", methods=["GET"])
def parceiro_loja_landing():
    if current_user.is_authenticated:
        casa = CasaDeRacao.query.filter_by(owner_id=current_user.id).first()
        if casa:
            return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))
        return redirect(url_for('minha_casa_de_racao'))
    return render_template('casa_de_racao/parceiro_landing.html', product_intent=False)


@bp.route("/parceiros/loja/produtos", methods=["GET"])
def parceiro_loja_produtos_landing():
    if current_user.is_authenticated:
        casa = CasaDeRacao.query.filter_by(owner_id=current_user.id).first()
        if casa:
            return redirect(_casa_de_racao_product_onboarding_target(casa))
        return redirect(url_for('minha_casa_de_racao', next='produtos'))
    return render_template('casa_de_racao/parceiro_landing.html', product_intent=True)


@bp.route("/ativar-loja/<token>", methods=["GET", "POST"])
def casa_de_racao_onboarding(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    invite = CasaDeRacaoOnboardingInvite.query.filter_by(token_hash=token_hash).first_or_404()
    casa = invite.casa_de_racao
    owner = casa.owner

    if invite.used_at:
        flash('Este convite já foi concluído. Entre com seu e-mail ou celular.', 'info')
        return redirect(url_for('login_view'))
    if invite.is_expired:
        return render_template(
            'casa_de_racao/onboarding_expired.html',
            casa=casa,
        ), 410

    produtos = Product.query.filter_by(casa_de_racao_id=casa.id).order_by(Product.id).all()
    errors = []
    values = {
        'owner_name': owner.name or '',
        'email': _onboarding_prefill_email(owner.email),
        'phone': owner.phone or casa.telefone or '',
        'store_name': casa.nome or '',
        'cnpj': casa.cnpj or '',
        'store_email': normalize_email(casa.email) or _onboarding_prefill_email(owner.email),
        'address': casa.endereco or owner.address or '',
        'modo_entrega': casa.modo_entrega or 'plataforma',
    }
    product_form_state, configured_count, fee_percent, seller_percent = _onboarding_product_form_state(produtos)

    if request.method == 'POST':
        values.update({
            'owner_name': (request.form.get('owner_name') or '').strip(),
            'email': normalize_email(request.form.get('email')) or '',
            'phone': (request.form.get('phone') or '').strip(),
            'store_name': (request.form.get('store_name') or '').strip(),
            'cnpj': (request.form.get('cnpj') or '').strip(),
            'store_email': normalize_email(request.form.get('store_email')) or '',
            'address': (request.form.get('address') or '').strip(),
            'modo_entrega': (request.form.get('modo_entrega') or 'plataforma').strip(),
        })
        password = request.form.get('password') or ''
        password_confirmation = request.form.get('password_confirmation') or ''

        if len(values['owner_name']) < 2:
            errors.append('Informe o nome completo.')
        if not values['email'] or '@' not in values['email']:
            errors.append('Informe um e-mail válido.')
        else:
            email_owner = User.query.filter(
                func.lower(User.email) == values['email'],
                User.id != owner.id,
            ).first()
            if email_owner:
                errors.append('Este e-mail já pertence a outra conta.')
        normalized_phone = normalize_phone(values['phone'])
        if not normalized_phone:
            errors.append('Informe o celular com DDD.')
        elif find_users_by_phone(normalized_phone, exclude_user_id=owner.id):
            errors.append('Este celular já pertence a outra conta.')
        if not values['store_name']:
            errors.append('Informe o nome da loja.')
        if not values['address']:
            errors.append('Informe o endereço da loja.')
        if values['modo_entrega'] not in {'plataforma', 'propria'}:
            errors.append('Escolha um modo de entrega válido.')
        if values['cnpj']:
            cnpj_digits = only_digits(values['cnpj'])
            if len(cnpj_digits) != 14:
                errors.append('O CNPJ deve ter 14 dígitos.')
            else:
                values['cnpj'] = format_cnpj_value(cnpj_digits)
                existing_cnpj = CasaDeRacao.query.filter(
                    CasaDeRacao.cnpj == values['cnpj'],
                    CasaDeRacao.id != casa.id,
                ).first()
                if existing_cnpj:
                    errors.append('Este CNPJ já está vinculado a outra loja.')
        if len(password) < 8:
            errors.append('Crie uma senha com pelo menos 8 caracteres.')
        if password != password_confirmation:
            errors.append('A confirmação da senha não confere.')

        product_updates = []
        configured_products = 0
        for item in product_form_state:
            product = item['product']
            raw_price = request.form.get(f'price_{product.id}')
            raw_payout = request.form.get(f'payout_{product.id}')
            pricing_mode = (request.form.get(f'pricing_mode_{product.id}') or 'payout').strip()
            if pricing_mode not in {'final', 'payout'}:
                pricing_mode = 'payout'
            price = _onboarding_decimal(raw_price)
            payout = _onboarding_decimal(raw_payout)
            raw_stock = (request.form.get(f'stock_{product.id}') or '').strip()
            touched = bool(str(raw_price or '').strip() or str(raw_payout or '').strip() or raw_stock)
            try:
                stock = int(raw_stock) if raw_stock else 0
            except ValueError:
                stock = -1

            if not touched:
                product_updates.append((product, None, None, False))
                item['price_value'] = ''
                item['payout_value'] = ''
                item['stock_value'] = ''
                item['configured'] = False
                item['pricing_mode'] = pricing_mode
                continue

            # O que é salvo em product.price é sempre o REPASSE (valor que
            # a loja recebe); a vitrine é derivada com a taxa embutida.
            if pricing_mode == 'payout':
                seller_price = payout
                if payout is None or payout <= 0:
                    errors.append(f'Informe quanto deseja receber por {product.name}.')
            else:
                if price is None or price <= 0:
                    errors.append(f'Informe um preço de vitrine válido para {product.name}.')
                seller_price = _onboarding_payout_from_final(price)
            final_price = _onboarding_final_from_payout(seller_price)
            if stock < 0:
                errors.append(f'Informe um estoque válido para {product.name}.')
            if seller_price is not None and seller_price > 0 and stock >= 0:
                configured_products += 1
            item['price_value'] = _onboarding_money_display(final_price) if final_price else str(raw_price or '').strip()
            item['payout_value'] = _onboarding_money_display(seller_price) if seller_price else str(raw_payout or '').strip()
            item['stock_value'] = raw_stock
            item['configured'] = bool(seller_price is not None and seller_price > 0 and stock >= 0)
            item['pricing_mode'] = pricing_mode
            product_updates.append((product, seller_price, stock, True))

        if configured_products == 0:
            errors.append('Preencha ao menos um produto com preço e estoque para concluir.')

        if not errors:
            owner.name = values['owner_name']
            owner.email = values['email']
            owner.phone = normalized_phone
            owner.address = values['address']
            owner.set_password(password)

            casa.nome = values['store_name']
            casa.cnpj = values['cnpj'] or None
            casa.telefone = normalized_phone
            casa.email = values['store_email'] or values['email']
            casa.endereco = values['address']
            casa.modo_entrega = values['modo_entrega']
            casa.status = 'ativa'

            for product, price, stock, should_activate in product_updates:
                if should_activate and price is not None and price > 0 and stock is not None and stock >= 0:
                    product.price = float(price)
                    product.stock = stock
                    product.status = 'active'
                else:
                    product.price = 0
                    product.stock = 0
                    product.status = 'inactive'

            invite.used_at = datetime.now(timezone.utc)
            db.session.commit()
            login_user(owner)
            flash(
                f'Cadastro concluído. Sua loja já está pronta com {configured_products} produto(s) ativo(s).',
                'success',
            )
            return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))

    return render_template(
        'casa_de_racao/onboarding.html',
        invite=invite,
        casa=casa,
        owner=owner,
        produtos=product_form_state,
        values=values,
        errors=errors,
        configured_count=configured_count,
        fee_percent=float(fee_percent),
        seller_percent=float(seller_percent),
    )


@bp.route("/minha-casa-de-racao", methods=["GET", "POST"])
@login_required
def minha_casa_de_racao():
    wants_products = request.args.get('next') == 'produtos'
    casa = CasaDeRacao.query.filter_by(owner_id=current_user.id).first()
    if casa:
        if wants_products:
            return redirect(_casa_de_racao_product_onboarding_target(casa))
        return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))

    form = CasaDeRacaoForm()
    if form.validate_on_submit():
        nova_casa = CasaDeRacao(
            nome=form.nome.data,
            razao_social=form.razao_social.data or None,
            cnpj=form.cnpj.data or None,
            descricao=form.descricao.data or None,
            telefone=form.telefone.data or None,
            email=form.email.data or None,
            endereco=form.endereco.data or None,
            modo_entrega=form.modo_entrega.data or 'plataforma',
            valor_frete=form.valor_frete.data or Decimal('0'),
            pedido_minimo_entrega=form.pedido_minimo_entrega.data or None,
            prazo_entrega_min=form.prazo_entrega_min.data or None,
            prazo_entrega_max=form.prazo_entrega_max.data or None,
            owner_id=current_user.id,
            status='pendente',
        )
        file = form.logotipo.data
        if file and getattr(file, 'filename', ''):
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            image_url = upload_to_s3(file, filename, folder='casas_de_racao')
            if image_url:
                nova_casa.logotipo = image_url
                nova_casa.photo_rotation = form.photo_rotation.data
                nova_casa.photo_zoom = float(form.photo_zoom.data)
                nova_casa.photo_offset_x = float(form.photo_offset_x.data)
                nova_casa.photo_offset_y = float(form.photo_offset_y.data)
        db.session.add(nova_casa)
        db.session.commit()
        from services.notifications import notify_admins
        notify_admins(
            f'Nova loja aguardando aprovação: {nova_casa.nome} (responsável: {current_user.name}).',
            kind='casa_pendente',
            url=url_for('admin_parcerias', _external=True),
        )
        flash(
            'Cadastro enviado! Aguarde a aprovação do administrador para começar a vender.',
            'success',
        )
        if wants_products:
            return redirect(_casa_de_racao_product_onboarding_target(nova_casa))
        return redirect(url_for('casa_de_racao_dashboard', casa_id=nova_casa.id))
    return render_template('casa_de_racao/create.html', form=form, editing=False)


@bp.route("/casa-de-racao/<int:casa_id>", methods=["GET", "POST"])
@login_required
def casa_de_racao_dashboard(casa_id):
    from forms import CasaDeRacaoForm, StoreHoursForm
    casa = _casa_loja_access(casa_id)

    store_form = CasaDeRacaoForm(obj=casa)
    hours_form = StoreHoursForm()

    if request.method == 'POST':
        if request.form.get('_action') == 'add_product':
            if casa.status == 'pendente' and not _is_admin():
                flash('Sua loja ainda está aguardando aprovação. Produtos poderão ser publicados em breve.', 'warning')
                return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#produtos')
            from forms import CasaDeRacaoProductForm
            product_form = CasaDeRacaoProductForm()
            if product_form.validate_on_submit():
                image_url = None
                if product_form.image_upload.data:
                    file = product_form.image_upload.data
                    image_url = upload_to_s3(file, secure_filename(file.filename), folder='products')
                product = Product(
                    casa_de_racao_id=casa.id,
                    name=product_form.name.data,
                    description=product_form.description.data or None,
                    price=float(product_form.price.data),
                    stock=product_form.stock.data or 0,
                    image_url=image_url,
                    category=(product_form.category.data or None),
                    mp_category_id=(product_form.mp_category_id.data or 'others').strip(),
                    status='active',
                )
                db.session.add(product)
                _create_initial_variant(product, product_form)
                db.session.commit()
                flash('Produto publicado com sucesso!', 'success')
                return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#produtos')
            flash('Verifique os campos do produto.', 'warning')
            return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#produtos')

        if request.form.get('_action') == 'update_info' and store_form.validate_on_submit():
            casa.nome = store_form.nome.data
            casa.razao_social = store_form.razao_social.data or None
            casa.cnpj = store_form.cnpj.data or None
            casa.descricao = store_form.descricao.data or None
            casa.telefone = store_form.telefone.data or None
            casa.email = store_form.email.data or None
            casa.endereco = store_form.endereco.data or None
            casa.modo_entrega = store_form.modo_entrega.data or 'plataforma'
            casa.valor_frete = store_form.valor_frete.data or Decimal('0')
            casa.pedido_minimo_entrega = store_form.pedido_minimo_entrega.data or None
            casa.prazo_entrega_min = store_form.prazo_entrega_min.data or None
            casa.prazo_entrega_max = store_form.prazo_entrega_max.data or None
            file = request.files.get(store_form.logotipo.name)
            logo_marked_as_selected = request.form.get('store_logo_has_new_file') == '1'
            if file and getattr(file, 'filename', ''):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                image_url = upload_to_s3(file, filename, folder='casas_de_racao')
                if image_url:
                    casa.logotipo = image_url
                    casa.photo_rotation = store_form.photo_rotation.data
                    casa.photo_zoom = float(store_form.photo_zoom.data)
                    casa.photo_offset_x = float(store_form.photo_offset_x.data)
                    casa.photo_offset_y = float(store_form.photo_offset_y.data)
                else:
                    flash('Não foi possível salvar a nova imagem da loja. Tente novamente ou use outro arquivo.', 'danger')
                    return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#loja')
            elif logo_marked_as_selected:
                flash('A nova imagem não chegou ao servidor. Escolha a imagem novamente antes de salvar.', 'warning')
                return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#loja')
            db.session.commit()
            flash('Dados da loja atualizados.', 'success')
            return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#loja')

        elif request.form.get('_action') == 'add_hours' and hours_form.validate_on_submit():
            for dia in hours_form.dias_semana.data:
                existing = CasaDeRacaoHorario.query.filter_by(
                    casa_de_racao_id=casa.id, dia_semana=dia
                ).first()
                if existing:
                    existing.hora_abertura = hours_form.hora_abertura.data
                    existing.hora_fechamento = hours_form.hora_fechamento.data
                else:
                    db.session.add(CasaDeRacaoHorario(
                        casa_de_racao_id=casa.id,
                        dia_semana=dia,
                        hora_abertura=hours_form.hora_abertura.data,
                        hora_fechamento=hours_form.hora_fechamento.data,
                    ))
            db.session.commit()
            flash('Horários salvos.', 'success')
            return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#horarios')

    payment_account = (
        StorePaymentAccount.query
        .filter_by(casa_de_racao_id=casa.id, provider='mercado_pago')
        .first()
    )
    mp_oauth_available = bool((current_app.config.get("MERCADOPAGO_CLIENT_ID") or "").strip())
    mp_platform_configured = bool((current_app.config.get("MERCADOPAGO_ACCESS_TOKEN") or "").strip())

    tutores_adicionados = User.query.filter_by(casa_de_racao_id=casa.id).order_by(User.name).all()
    animais_adicionados = (
        Animal.query
        .filter_by(casa_de_racao_id=casa.id)
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.date_added.desc())
        .all()
    )
    horarios = CasaDeRacaoHorario.query.filter_by(casa_de_racao_id=casa.id).all()

    _dia_order = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    horarios = sorted(horarios, key=lambda h: _dia_order.index(h.dia_semana) if h.dia_semana in _dia_order else 99)

    from forms import CasaDeRacaoProductForm
    product_form = CasaDeRacaoProductForm(formdata=None)
    produtos = Product.query.filter_by(casa_de_racao_id=casa.id).order_by(Product.name).all()
    produtos_count = sum(1 for p in produtos if p.status == 'active')
    entregas_pendentes = 0
    if casa.modo_entrega == 'propria':
        entregas_pendentes = (
            DeliveryRequest.query
            .filter_by(casa_de_racao_id=casa.id, tipo_entrega='propria', archived=False)
            .filter(DeliveryRequest.status.in_(['pendente', 'em_andamento']))
            .count()
        )

    store_initials = ''.join(w[0].upper() for w in (casa.nome or '').split() if w)[:2] or '??'

    return render_template(
        'casa_de_racao/dashboard.html',
        casa=casa,
        store_form=store_form,
        hours_form=hours_form,
        product_form=product_form,
        payment_account=payment_account,
        mp_oauth_available=mp_oauth_available,
        mp_platform_configured=mp_platform_configured,
        tutores=tutores_adicionados,
        animais=animais_adicionados,
        tutores_adicionados=tutores_adicionados,
        animais_adicionados=animais_adicionados,
        horarios=horarios,
        produtos=produtos,
        produtos_count=produtos_count,
        entregas_pendentes=entregas_pendentes,
        store_initials=store_initials,
        pode_editar=True,
        is_admin=_is_admin(),
    )


@bp.route("/casa-de-racao/<int:casa_id>/horario/<int:horario_id>/delete", methods=["POST"])
@login_required
def casa_de_racao_horario_delete(casa_id, horario_id):
    casa = _casa_loja_access(casa_id)
    horario = CasaDeRacaoHorario.query.filter_by(id=horario_id, casa_de_racao_id=casa.id).first_or_404()
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido.', 'info')
    return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#horarios')


@bp.route("/casa-de-racao/<int:casa_id>/mercado-pago/conectar", methods=["POST"])
@login_required
def mercadopago_oauth_start(casa_id):
    casa = _casa_loja_access(casa_id)
    try:
        oauth_start = build_authorization_start()
    except MercadoPagoOAuthError as exc:
        current_app.logger.error('mercadopago_oauth_start failed for casa %s: %s', casa.id, exc)
        flash('Não foi possível iniciar a conexão com o Mercado Pago. Tente novamente ou entre em contato com o suporte.', 'danger')
        return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))

    account = (
        StorePaymentAccount.query
        .filter_by(casa_de_racao_id=casa.id, provider='mercado_pago')
        .first()
    )
    if not account:
        account = StorePaymentAccount(casa_de_racao_id=casa.id, provider='mercado_pago')
        db.session.add(account)

    account.oauth_state = oauth_start.state
    account.code_verifier = oauth_start.code_verifier
    account.status = 'pending'
    account.error_message = None
    db.session.commit()
    return redirect(oauth_start.authorization_url)


@bp.route("/casa-de-racao/mercado-pago/callback", methods=["GET"])
@login_required
def mercadopago_oauth_callback():
    code = (request.args.get('code') or '').strip()
    state = (request.args.get('state') or '').strip()
    error = (request.args.get('error') or '').strip()

    account = (
        StorePaymentAccount.query
        .filter_by(oauth_state=state, provider='mercado_pago')
        .first()
        if state else None
    )
    if not account:
        flash('NÃ£o foi possÃ­vel validar a conexÃ£o com o Mercado Pago. Tente novamente.', 'danger')
        return redirect(url_for('minha_casa_de_racao'))

    casa = account.casa_de_racao
    clinica = account.clinica
    if casa:
        can_manage_account = _is_admin() or current_user.id == casa.owner_id
        success_redirect = url_for('casa_de_racao_dashboard', casa_id=casa.id)
    elif clinica:
        can_manage_account = _user_can_manage_clinic(clinica)
        success_redirect = url_for('clinic_detail', clinica_id=clinica.id) + '#clinica'
    else:
        can_manage_account = False
        success_redirect = url_for('minha_casa_de_racao')

    if not can_manage_account:
        abort(403)

    if error or not code:
        account.status = 'error'
        account.error_message = error or 'AutorizaÃ§Ã£o cancelada ou incompleta.'
        account.oauth_state = None
        account.code_verifier = None
        db.session.commit()
        flash('A conexÃ£o com o Mercado Pago foi cancelada ou nÃ£o foi concluÃ­da.', 'warning')
        return redirect(success_redirect)

    try:
        credentials = exchange_code_for_credentials(code, account.code_verifier)
        account.access_token = credentials.access_token
        account.refresh_token = credentials.refresh_token
        account.public_key = credentials.public_key
        account.provider_user_id = credentials.provider_user_id
        account.token_expires_at = credentials.expires_at
        account.status = 'connected'
        account.error_message = None
        account.connected_at = utcnow()
        account.last_refreshed_at = utcnow()
        account.oauth_state = None
        account.code_verifier = None
        db.session.commit()
    except (MercadoPagoOAuthError, MissingMasterKeyError) as exc:
        db.session.rollback()
        account.status = 'error'
        account.error_message = str(exc)
        account.oauth_state = None
        account.code_verifier = None
        db.session.add(account)
        db.session.commit()
        flash('NÃ£o foi possÃ­vel concluir a conexÃ£o com o Mercado Pago.', 'danger')
        return redirect(success_redirect)

    flash('Mercado Pago conectado com sucesso. Sua loja jÃ¡ pode receber pagamentos.', 'success')
    return redirect(success_redirect)


@bp.route("/casa-de-racao/<int:casa_id>/mercado-pago/desconectar", methods=["POST"])
@login_required
def mercadopago_oauth_disconnect(casa_id):
    casa = _casa_loja_access(casa_id)
    account = (
        StorePaymentAccount.query
        .filter_by(casa_de_racao_id=casa.id, provider='mercado_pago')
        .first()
    )
    if account:
        account.status = 'revoked'
        account.access_token = None
        account.refresh_token = None
        account.oauth_state = None
        account.code_verifier = None
        db.session.commit()
    flash('Conexão com o Mercado Pago desativada para esta loja.', 'info')
    return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/mercado-pago/credenciais", methods=["POST"])
@login_required
def mercadopago_direct_save(casa_id):
    casa = _casa_loja_access(casa_id)
    access_token = (request.form.get('access_token') or '').strip()
    public_key = (request.form.get('public_key') or '').strip()

    if not access_token:
        flash('Informe o Access Token do Mercado Pago.', 'danger')
        return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))

    if not (access_token.startswith('APP_USR-') or access_token.startswith('TEST-')):
        flash('Access Token inválido. Deve começar com APP_USR- (produção) ou TEST- (teste).', 'danger')
        return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))

    account = (
        StorePaymentAccount.query
        .filter_by(casa_de_racao_id=casa.id, provider='mercado_pago')
        .first()
    )
    if not account:
        account = StorePaymentAccount(casa_de_racao_id=casa.id, provider='mercado_pago')
        db.session.add(account)

    account.access_token = access_token
    account.public_key = public_key or None
    account.refresh_token = None
    account.oauth_state = None
    account.code_verifier = None
    account.status = 'connected'
    account.error_message = None
    account.connected_at = utcnow()
    account.last_refreshed_at = utcnow()
    db.session.commit()
    flash('Credenciais do Mercado Pago salvas. Sua loja já pode receber pagamentos.', 'success')
    return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/produtos", methods=["GET", "POST"])
@login_required
def casa_de_racao_produtos(casa_id):
    casa = _casa_loja_access(casa_id)
    if casa.status == 'pendente' and not _is_admin():
        flash('Sua loja ainda está aguardando aprovação. Você poderá publicar produtos em breve.', 'warning')
        return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))

    form = CasaDeRacaoProductForm()
    if form.validate_on_submit():
        image_url = None
        if form.image_upload.data:
            file = form.image_upload.data
            image_url = upload_to_s3(file, secure_filename(file.filename), folder='products')

        product = Product(
            casa_de_racao_id=casa.id,
            name=form.name.data,
            description=form.description.data or None,
            price=float(form.price.data),
            stock=form.stock.data or 0,
            image_url=image_url,
            category=(form.category.data or None),
            mp_category_id=(form.mp_category_id.data or 'others').strip(),
            status='active',
        )
        db.session.add(product)
        _create_initial_variant(product, form)
        db.session.commit()
        flash('Produto publicado na loja com sucesso!', 'success')
        return redirect(url_for('casa_de_racao_produtos', casa_id=casa.id))

    produtos = Product.query.filter_by(casa_de_racao_id=casa.id).order_by(Product.name).all()
    return render_template('casa_de_racao/produtos.html', casa=casa, produtos=produtos, form=form)


@bp.route("/casa-de-racao/<int:casa_id>/produto/<int:product_id>/editar", methods=["GET", "POST"])
@login_required
def casa_produto_editar(casa_id, product_id):
    casa = _casa_loja_access(casa_id)
    product = Product.query.filter_by(id=product_id, casa_de_racao_id=casa.id).first_or_404()

    form = CasaDeRacaoProductEditForm(obj=product)
    if form.validate_on_submit():
        product.name = form.name.data
        product.description = form.description.data or None
        product.price = float(form.price.data)
        product.stock = form.stock.data or 0
        product.category = form.category.data or None
        product.mp_category_id = (form.mp_category_id.data or 'others').strip()
        _sync_variants_from_request(product)
        if form.image_upload.data:
            file = form.image_upload.data
            url = upload_to_s3(file, secure_filename(file.filename), folder='products')
            if url:
                product.image_url = url
        db.session.commit()
        flash('Produto atualizado.', 'success')
        return redirect(url_for('casa_de_racao_produtos', casa_id=casa.id))

    return render_template('casa_de_racao/produto_editar.html', casa=casa, product=product, form=form)


@bp.route("/casa-de-racao/<int:casa_id>/produto/<int:product_id>/toggle", methods=["POST"])
@login_required
def casa_produto_toggle(casa_id, product_id):
    casa = _casa_loja_access(casa_id)
    product = Product.query.filter_by(id=product_id, casa_de_racao_id=casa.id).first_or_404()
    has_sellable_variant = any((v.status == 'active' and (v.price or 0) > 0) for v in product.variants)
    if product.status != 'active' and not has_sellable_variant and product.price <= 0:
        flash('Defina ao menos uma apresentação com preço maior que zero antes de ativar o produto.', 'warning')
        return redirect(url_for('casa_de_racao_produtos', casa_id=casa.id))
    product.status = 'inactive' if product.status == 'active' else 'active'
    db.session.commit()
    state = 'ativado' if product.status == 'active' else 'desativado'
    flash(f'Produto {state} na loja.', 'success')
    return redirect(url_for('casa_de_racao_produtos', casa_id=casa.id))


@bp.route("/admin/casas-de-racao", methods=["GET"])
@login_required
def admin_casas_de_racao():
    if not _is_admin():
        abort(403)
    pendentes = CasaDeRacao.query.filter_by(status='pendente').order_by(CasaDeRacao.created_at).all()
    ativas = CasaDeRacao.query.filter_by(status='ativa').order_by(CasaDeRacao.nome).all()
    suspensas = CasaDeRacao.query.filter_by(status='suspensa').order_by(CasaDeRacao.nome).all()
    return render_template(
        'casa_de_racao/admin_lista.html',
        pendentes=pendentes,
        ativas=ativas,
        suspensas=suspensas,
    )


@bp.route("/admin/casa-de-racao/<int:casa_id>/aprovar", methods=["POST"])
@login_required
def admin_aprovar_casa_de_racao(casa_id):
    if not _is_admin():
        abort(403)
    casa = CasaDeRacao.query.get_or_404(casa_id)
    casa.status = 'ativa'
    db.session.commit()
    from services.notifications import notify_user
    notify_user(
        casa.owner,
        'Sua loja foi aprovada no PetOrlândia! 🎉',
        (
            f'Boa notícia: a loja "{casa.nome}" foi aprovada e já está ativa na plataforma.\n\n'
            f'Acesse seu painel para publicar produtos e começar a vender:\n'
            f'{url_for("casa_de_racao_dashboard", casa_id=casa.id, _external=True)}\n\n'
            'Abraços,\nEquipe PetOrlândia'
        ),
        kind='casa_aprovada',
    )
    flash(f'Casa de ração "{casa.nome}" aprovada. O responsável foi avisado por e-mail.', 'success')
    return redirect(request.referrer or url_for('admin_casas_de_racao'))


@bp.route("/admin/casa-de-racao/<int:casa_id>/suspender", methods=["POST"])
@login_required
def admin_suspender_casa_de_racao(casa_id):
    if not _is_admin():
        abort(403)
    casa = CasaDeRacao.query.get_or_404(casa_id)
    casa.status = 'suspensa'
    db.session.commit()
    from services.notifications import notify_user
    notify_user(
        casa.owner,
        'Sua loja foi suspensa no PetOrlândia',
        (
            f'A loja "{casa.nome}" foi suspensa e não está mais visível na plataforma.\n\n'
            'Em caso de dúvidas, responda este e-mail ou fale com a administração.\n\n'
            'Equipe PetOrlândia'
        ),
        kind='casa_suspensa',
    )
    flash(f'Casa de ração "{casa.nome}" suspensa.', 'warning')
    return redirect(request.referrer or url_for('admin_casas_de_racao'))


@bp.route("/casa-de-racao/<int:casa_id>/vendas", methods=["GET"])
@login_required
def casa_de_racao_vendas(casa_id):
    """Dashboard de vendas: pedidos que contêm produtos da casa de ração."""
    casa = _casa_loja_access(casa_id)

    # Todos os OrderItems cujo produto pertence a esta casa
    from sqlalchemy import func
    items = (
        OrderItem.query
        .join(Product, OrderItem.product_id == Product.id)
        .filter(Product.casa_de_racao_id == casa.id)
        .options(
            db.joinedload(OrderItem.product),
            db.joinedload(OrderItem.order).joinedload(Order.user),
        )
        .order_by(OrderItem.order_id.desc())
        .all()
    )

    # Agrupa por pedido para exibição
    pedidos: dict = {}
    for oi in items:
        oid = oi.order_id
        if oid not in pedidos:
            pedidos[oid] = {
                'order': oi.order,
                'items': [],
                'total': 0.0,
                'delivery': None,
            }
        pedidos[oid]['items'].append(oi)
        pedidos[oid]['total'] += float(oi.unit_price or 0) * oi.quantity

    # Busca os DeliveryRequests correspondentes
    if pedidos:
        drs = (
            DeliveryRequest.query
            .filter(
                DeliveryRequest.order_id.in_(list(pedidos.keys())),
                DeliveryRequest.casa_de_racao_id == casa.id,
            )
            .all()
        )
        for dr in drs:
            if dr.order_id in pedidos:
                pedidos[dr.order_id]['delivery'] = dr

    receita_total = sum(p['total'] for p in pedidos.values())
    pedidos_list = sorted(pedidos.values(), key=lambda p: p['order'].id, reverse=True)

    return render_template(
        'casa_de_racao/vendas.html',
        casa=casa,
        pedidos=pedidos_list,
        receita_total=receita_total,
    )


@bp.route("/casa-de-racao/<int:casa_id>/entregas", methods=["GET"])
@login_required
def casa_de_racao_entregas(casa_id):
    """Lista de entregas próprias para a casa de ração gerenciar."""
    casa = _casa_loja_access(casa_id)
    if casa.modo_entrega != 'propria' and not _is_admin():
        flash('Sua loja usa entregadores da plataforma — não há entregas próprias para gerenciar.', 'info')
        return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id))

    pendentes = (
        DeliveryRequest.query
        .filter_by(casa_de_racao_id=casa.id, tipo_entrega='propria', archived=False)
        .filter(DeliveryRequest.status.in_(['pendente', 'em_andamento']))
        .options(db.joinedload(DeliveryRequest.order).joinedload(Order.user))
        .order_by(DeliveryRequest.requested_at.asc())
        .all()
    )
    concluidas = (
        DeliveryRequest.query
        .filter_by(casa_de_racao_id=casa.id, tipo_entrega='propria', archived=False)
        .filter(DeliveryRequest.status.in_(['concluida', 'cancelada']))
        .options(db.joinedload(DeliveryRequest.order).joinedload(Order.user))
        .order_by(DeliveryRequest.completed_at.desc())
        .limit(30)
        .all()
    )

    return render_template(
        'casa_de_racao/entregas.html',
        casa=casa,
        pendentes=pendentes,
        concluidas=concluidas,
    )


@bp.route("/casa-de-racao/<int:casa_id>/planos/tosa", methods=["GET", "POST"])
@login_required
def casa_de_racao_grooming_planos(casa_id):
    from forms import GroomingPlanForm
    from models import GroomingPlan

    casa = _casa_loja_access(casa_id)
    form = GroomingPlanForm()
    if form.validate_on_submit():
        plan = GroomingPlan(
            casa_de_racao_id=casa.id,
            name=form.name.data,
            description=form.description.data or None,
            service_type=form.service_type.data,
            price=form.price.data,
            sessions_per_month=form.sessions_per_month.data,
        )
        db.session.add(plan)
        db.session.commit()
        flash('Plano de banho e tosa criado para a casa de racao.', 'success')
        return redirect(url_for('casa_de_racao_grooming_planos', casa_id=casa.id))

    planos = (
        GroomingPlan.query
        .filter_by(casa_de_racao_id=casa.id)
        .order_by(GroomingPlan.name)
        .all()
    )
    return render_template(
        'casa_de_racao/grooming_planos.html',
        casa=casa,
        planos=planos,
        form=form,
    )


@bp.route("/casa-de-racao/<int:casa_id>/planos/tosa/<int:plan_id>/toggle", methods=["POST"])
@login_required
def casa_de_racao_grooming_plano_toggle(casa_id, plan_id):
    from models import GroomingPlan

    casa = _casa_loja_access(casa_id)
    plan = GroomingPlan.query.filter_by(id=plan_id, casa_de_racao_id=casa.id).first_or_404()
    plan.active = not plan.active
    db.session.commit()
    state = 'ativado' if plan.active else 'desativado'
    flash(f'Plano {state}.', 'success')
    return redirect(url_for('casa_de_racao_grooming_planos', casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/tutores", methods=["GET", "POST"])
@login_required
def casa_de_racao_tutores(casa_id):
    casa = _casa_loja_access(casa_id)
    if request.method == 'POST':
        from_dashboard = bool(request.form.get('_from_dashboard'))
        _back = (url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#tutores') if from_dashboard else url_for('casa_de_racao_tutores', casa_id=casa.id)
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        phone = (request.form.get('phone') or '').strip() or None
        cpf = (request.form.get('cpf') or '').strip() or None

        if not name:
            flash('Informe o nome do tutor.', 'warning')
            return redirect(_back)

        tutor = User.query.filter_by(email=email).first() if email else None
        if tutor and tutor.casa_de_racao_id not in (None, casa.id):
            flash('Este e-mail ja esta vinculado a outra loja.', 'warning')
            return redirect(_back)
        if not tutor:
            tutor = User(
                name=name,
                email=email or f"tutor-{casa.id}-{uuid.uuid4().hex[:12]}@petorlandia.local",
                role='adotante',
                added_by=current_user,
                casa_de_racao_id=casa.id,
                is_private=True,
            )
            tutor.set_password(uuid.uuid4().hex)
            db.session.add(tutor)
        else:
            tutor.name = name
            tutor.casa_de_racao_id = casa.id
            tutor.added_by = tutor.added_by or current_user
            tutor.is_private = True

        tutor.phone = phone
        tutor.cpf = cpf
        tutor.rg = (request.form.get('rg') or '').strip() or None

        date_str = (request.form.get('date_of_birth') or '').strip()
        if date_str:
            try:
                tutor.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        cep = (request.form.get('cep') or '').strip() or None
        rua = (request.form.get('rua') or '').strip() or None
        numero = (request.form.get('numero') or '').strip() or None
        complemento = (request.form.get('complemento') or '').strip() or None
        bairro = (request.form.get('bairro') or '').strip() or None
        cidade = (request.form.get('cidade') or '').strip() or None
        estado = (request.form.get('estado') or '').strip() or None

        has_address_data = any([cep, rua, numero, complemento, bairro, cidade, estado])
        if has_address_data:
            endereco = tutor.endereco or Endereco()
            endereco.cep = cep
            endereco.rua = rua
            endereco.numero = numero
            endereco.complemento = complemento
            endereco.bairro = bairro
            endereco.cidade = cidade
            endereco.estado = estado
            if not _update_coordinates_from_request(endereco):
                _geocode_endereco(endereco)
            if not tutor.endereco:
                db.session.add(endereco)
                db.session.flush()
                tutor.endereco_id = endereco.id

        db.session.commit()
        flash('Tutor cadastrado para a loja.', 'success')
        if from_dashboard:
            return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#tutores')
        return redirect(url_for('casa_de_racao_tutores', casa_id=casa.id))

    tutor_search = (request.args.get('tutor_search', '') or '').strip()
    tutor_sort = request.args.get('tutor_sort', 'name_asc')

    q = User.query.filter_by(casa_de_racao_id=casa.id)
    if tutor_search:
        q = q.filter(db.or_(
            User.name.ilike(f'%{tutor_search}%'),
            User.email.ilike(f'%{tutor_search}%'),
            User.phone.ilike(f'%{tutor_search}%'),
        ))
    sort_map = {
        'name_desc': User.name.desc(),
        'date_desc': User.created_at.desc(),
        'date_asc': User.created_at.asc(),
    }
    q = q.order_by(sort_map.get(tutor_sort, User.name.asc()))
    tutores = q.all()

    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
    )
    if is_ajax:
        html = render_template(
            'partials/tutores_adicionados.html',
            tutores_adicionados=tutores,
            pagination=None,
            compact=True,
            fetch_url=url_for('casa_de_racao_tutores', casa_id=casa.id),
            shared_access_map={},
            viewer_clinic_id=None,
            scope='all',
            tutor_search=tutor_search,
            tutor_sort=tutor_sort,
        )
        return jsonify(html=html, scope='all')

    return render_template('casa_de_racao/tutores.html', casa=casa, tutores=tutores)


@bp.route("/casa-de-racao/<int:casa_id>/animais", methods=["GET", "POST"])
@login_required
def casa_de_racao_animais(casa_id):
    casa = _casa_loja_access(casa_id)
    tutores = (
        User.query
        .filter_by(casa_de_racao_id=casa.id)
        .order_by(User.name.asc())
        .all()
    )

    if request.method == 'POST':
        from_dashboard = bool(request.form.get('_from_dashboard'))
        _back = (url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#animais') if from_dashboard else url_for('casa_de_racao_animais', casa_id=casa.id)
        tutor_id = request.form.get('tutor_id', type=int)
        tutor = User.query.filter_by(id=tutor_id, casa_de_racao_id=casa.id).first()
        if not tutor:
            flash('Selecione um tutor cadastrado nesta loja.', 'warning')
            return redirect(_back)

        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Informe o nome do animal.', 'warning')
            return redirect(_back)

        animal = Animal(
            name=name,
            user_id=tutor.id,
            added_by_id=current_user.id,
            casa_de_racao_id=casa.id,
            age=(request.form.get('age') or '').strip() or None,
            sex=(request.form.get('sex') or '').strip() or None,
            peso=_optional_decimal_from_form('peso'),
            description=(request.form.get('description') or '').strip() or None,
            status='privado',
            modo='adotado',
        )
        db.session.add(animal)
        db.session.commit()
        flash('Animal cadastrado.', 'success')
        if from_dashboard:
            return redirect(url_for('casa_de_racao_dashboard', casa_id=casa.id) + '#animais')
        return redirect(url_for('casa_de_racao_animais', casa_id=casa.id))

    animal_search = (request.args.get('animal_search', '') or '').strip()
    animal_sort = request.args.get('animal_sort', 'date_desc')

    q = (
        Animal.query
        .filter_by(casa_de_racao_id=casa.id)
        .filter(Animal.removido_em.is_(None))
        .options(joinedload(Animal.owner), joinedload(Animal.racoes).joinedload(Racao.tipo_racao))
    )
    if animal_search:
        q = q.filter(Animal.name.ilike(f'%{animal_search}%'))
    sort_map_a = {
        'name_asc': Animal.name.asc(),
        'name_desc': Animal.name.desc(),
        'date_asc': Animal.date_added.asc(),
    }
    q = q.order_by(sort_map_a.get(animal_sort, Animal.date_added.desc()))
    animais = q.all()

    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
    )
    if is_ajax:
        html = render_template(
            'partials/animais_adicionados.html',
            animais_adicionados=animais,
            pagination=None,
            compact=True,
            fetch_url=url_for('casa_de_racao_animais', casa_id=casa.id),
            can_create_animals=True,
            can_start_consultation=False,
            new_animal_url=url_for('casa_de_racao_animais', casa_id=casa.id),
            animal_search=animal_search,
            animal_sort=animal_sort,
        )
        return jsonify(html=html, scope='all')

    return render_template(
        'casa_de_racao/animais.html',
        casa=casa,
        tutores=tutores,
        animais=animais,
    )


@bp.route("/casa-de-racao/<int:casa_id>/animal/<int:animal_id>/racoes", methods=["GET", "POST"])
@login_required
def casa_de_racao_animal_racoes(casa_id, animal_id):
    casa = _casa_loja_access(casa_id)
    animal = Animal.query.filter_by(id=animal_id, casa_de_racao_id=casa.id).first_or_404()
    if request.method == 'POST':
        marca = _canonicalize_racao_brand(request.form.get('marca') or '')
        linha = (request.form.get('linha') or '').strip() or None
        if not marca:
            flash('Informe a marca da racao.', 'warning')
            return redirect(url_for('casa_de_racao_animal_racoes', casa_id=casa.id, animal_id=animal.id))

        tipo = TipoRacao.query.filter_by(marca=marca, linha=linha).first()
        if not tipo:
            tipo = TipoRacao(marca=marca, linha=linha, created_by=current_user.id)
            db.session.add(tipo)
            db.session.flush()

        racao = Racao(
            animal_id=animal.id,
            tipo_racao_id=tipo.id,
            preco_pago=_optional_decimal_from_form('preco_pago'),
            tamanho_embalagem=(request.form.get('tamanho_embalagem') or '').strip() or None,
            observacoes_racao=(request.form.get('observacoes_racao') or '').strip() or None,
            created_by=current_user.id,
        )
        db.session.add(racao)
        db.session.commit()
        try:
            list_rations.cache_clear()
        except Exception:
            pass
        flash('Racao vinculada ao animal.', 'success')
        return redirect(url_for('casa_de_racao_animal_racoes', casa_id=casa.id, animal_id=animal.id))

    racoes = (
        Racao.query
        .filter_by(animal_id=animal.id)
        .options(joinedload(Racao.tipo_racao))
        .order_by(Racao.data_cadastro.desc())
        .all()
    )
    return render_template(
        'casa_de_racao/animal_racoes.html',
        casa=casa,
        animal=animal,
        racoes=racoes,
    )


@bp.route("/casa-de-racao/<int:casa_id>/entrega/<int:dr_id>/status", methods=["POST"])
@login_required
def casa_entrega_atualizar_status(casa_id, dr_id):
    """Vendedor atualiza o status de uma entrega própria."""
    casa = _casa_loja_access(casa_id)
    dr = DeliveryRequest.query.filter_by(
        id=dr_id,
        casa_de_racao_id=casa.id,
        tipo_entrega='propria',
    ).first_or_404()

    novo_status = request.form.get('status', '').strip()
    validos = {'em_andamento', 'concluida', 'cancelada'}
    if novo_status not in validos:
        flash('Status inválido.', 'danger')
        return redirect(url_for('casa_de_racao_entregas', casa_id=casa.id))

    dr.status = novo_status
    if novo_status == 'concluida':
        dr.completed_at = now_in_brazil()
        _concluir_entrega_efeitos(dr)
    elif novo_status == 'cancelada':
        dr.canceled_at = now_in_brazil()
        dr.canceled_by_id = current_user.id
    db.session.commit()
    flash('Status da entrega atualizado.', 'success')
    return redirect(url_for('casa_de_racao_entregas', casa_id=casa.id))

