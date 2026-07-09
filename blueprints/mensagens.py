"""Mensagens e conversas (tutor↔tutor, usuário↔admin, chat por animal).

Migrado do app.py monolítico. As views api_* deste domínio continuam
registradas pelo blueprint api (via lazy_view + reexport no app.py).

Helpers compartilhados de página/inbox continuam no app.py e são importados
tardiamente (o módulo app já está completo quando este blueprint executa).
"""
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
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from context_processors import (
    _invalidate_admin_unread_cache,
    _invalidate_cached_context,
)
from extensions import db
from forms import (
    DeliveryDemotionForm,
    DeliveryPromotionForm,
    MessageForm,
    ParceiroDemotionForm,
    ParceiroPromotionForm,
    VeterinarianMembershipCancelTrialForm,
    VeterinarianMembershipRequestNewTrialForm,
    VeterinarianPromotionForm,
)
from helpers import ensure_veterinarian_membership, has_veterinarian_profile
from models import Animal, Interest, Message, User

# Helpers ainda hospedados no app.py (serão realocados em fases futuras).
# Import seguro: blueprints só são importados após o app.py executar por completo.
from app import (
    _get_inbox_messages,
    _notify_admin_message,
    _render_messages_page,
    _serialize_message_threads,
    get_animal_or_404,
    get_user_or_404,
)

bp = Blueprint("mensagens_routes", __name__)


def get_blueprint():
    return bp


def _push_nova_mensagem(receiver_id, url='/mensagens'):
    """Push best-effort quando chega mensagem nova (complementa o badge)."""
    try:
        from services.push import push_to_user

        nome = getattr(current_user, 'name', None) or 'Alguém'
        push_to_user(
            receiver_id,
            'Nova mensagem 💬',
            f'{nome} te enviou uma mensagem no PetOrlândia.',
            url=url,
            tag='mensagem',
        )
    except Exception:  # noqa: BLE001 - push nunca bloqueia o fluxo
        current_app.logger.debug('Falha silenciosa de push de mensagem', exc_info=True)



@bp.route("/mensagem/<int:animal_id>", methods=["GET", "POST"])
@login_required
def enviar_mensagem(animal_id):
    animal = get_animal_or_404(animal_id)
    form = MessageForm()
    promotion_form = None
    target_membership = None

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
        _push_nova_mensagem(animal.user_id)
        flash('Mensagem enviada com sucesso!', 'success')
        return redirect(url_for('list_animals'))

    return render_template('mensagens/enviar_mensagem.html', form=form, animal=animal)


@bp.route("/mensagem/<int:message_id>/aceitar", methods=["POST"])
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


@bp.route("/mensagens", methods=["GET"])
@login_required
def mensagens():
    return _render_messages_page()


@login_required
def api_message_threads():
    """Return aggregated conversation threads for the authenticated user."""
    mensagens = _get_inbox_messages()
    threads = _serialize_message_threads(mensagens)
    return jsonify({"threads": threads})


@bp.route("/chat/<int:animal_id>", methods=["GET", "POST"])
@login_required
def chat_messages(animal_id):
    """API simples para listar e criar mensagens relacionadas a um animal."""
    Animal.query.get_or_404(animal_id)
    if request.method == 'GET':
        mensagens = (
            Message.query
            .filter_by(animal_id=animal_id)
            .order_by(Message.timestamp)
            .all()
        )
        return jsonify([
            {
                'id': m.id,
                'sender_id': m.sender_id,
                'receiver_id': m.receiver_id,
                'animal_id': m.animal_id,
                'clinica_id': m.clinica_id,
                'content': m.content,
                'timestamp': m.timestamp.isoformat(),
            }
            for m in mensagens
        ])

    data = request.get_json() or {}
    nova_msg = Message(
        sender_id=data.get('sender_id', current_user.id),
        receiver_id=data['receiver_id'],
        animal_id=animal_id,
        clinica_id=data.get('clinica_id'),
        content=data['content'],
    )
    db.session.add(nova_msg)
    db.session.commit()
    return (
        jsonify(
            {
                'id': nova_msg.id,
                'sender_id': nova_msg.sender_id,
                'receiver_id': nova_msg.receiver_id,
                'animal_id': nova_msg.animal_id,
                'clinica_id': nova_msg.clinica_id,
                'content': nova_msg.content,
                'timestamp': nova_msg.timestamp.isoformat(),
            }
        ),
        201,
    )


@bp.route("/chat/<int:animal_id>/view", methods=["GET"])
@login_required
def chat_view(animal_id):
    animal = get_animal_or_404(animal_id)
    return render_template('chat/conversa.html', animal=animal)


def _resolve_animal_conversation(animal_id, user_id):
    """Return the animal and the interlocutor for a conversation.

    The conversation is always between the animal's owner and another user.
    We accept URLs that point either to the owner (from interested users) or
    directly to the interested user (from the owner). Any other combination
    is blocked to avoid leaking conversations.
    """

    animal = Animal.query.get_or_404(animal_id)
    owner_id = animal.user_id
    is_admin = (current_user.role or '').lower() == 'admin'

    # Admins can jump directly into either side of the conversation. This lets
    # them answer interested users (user_id == interested) or the owner
    # (user_id == owner_id) without being incorrectly blocked.
    if is_admin:
        if user_id == current_user.id:
            abort(404)

        interlocutor = User.query.get_or_404(user_id)
        return animal, interlocutor

    if current_user.id == owner_id:
        interlocutor_id = user_id
    elif user_id in {owner_id, current_user.id}:
        interlocutor_id = owner_id
    else:
        abort(404)

    if interlocutor_id == current_user.id:
        abort(404)

    interlocutor = User.query.get_or_404(interlocutor_id)
    return animal, interlocutor


@bp.route("/conversa/<int:animal_id>/<int:user_id>", methods=["GET", "POST"])
@login_required
def conversa(animal_id, user_id):
    animal, outro_usuario = _resolve_animal_conversation(animal_id, user_id)

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
        _push_nova_mensagem(
            outro_usuario.id,
            url=url_for('conversa', animal_id=animal.id, user_id=current_user.id),
        )
        return redirect(url_for('conversa', animal_id=animal.id, user_id=outro_usuario.id))

    updated = False
    for m in mensagens:
        if m.receiver_id == current_user.id and not m.lida:
            m.lida = True
            updated = True
    if updated:
        db.session.commit()
        _invalidate_cached_context(current_user.id, 'unread_messages')

    return render_template(
        'mensagens/conversa.html',
        mensagens=mensagens,
        form=form,
        animal=animal,
        outro_usuario=outro_usuario,
        interesse_existente=interesse_existente
    )


@login_required
def api_conversa_message(animal_id, user_id):
    """Recebe uma nova mensagem da conversa e retorna o HTML renderizado."""
    form = MessageForm()
    animal, outro_usuario = _resolve_animal_conversation(animal_id, user_id)
    if not form.validate_on_submit():
        # CSRF can fail after dyno restart (filesystem sessions lost).
        # Fall back to manual content validation since @login_required
        # already guarantees the user is authenticated.
        if form.errors.keys() - {'csrf_token'}:
            current_app.logger.warning('api_conversa_message validation failed for user %s: %s', current_user.id, form.errors)
            return jsonify(error='Falha de validação. Recarregue a página e tente novamente.'), 400
        content = request.form.get('content', '').strip()
        if not content or len(content) > 1000:
            return jsonify(error='Mensagem vazia ou muito longa.'), 400
    else:
        content = form.content.data
    nova_msg = Message(
        sender_id=current_user.id,
        receiver_id=outro_usuario.id,
        animal_id=animal_id,
        content=content,
        lida=False
    )
    db.session.add(nova_msg)
    db.session.commit()
    _push_nova_mensagem(
        outro_usuario.id,
        url=url_for('conversa', animal_id=animal_id, user_id=current_user.id),
    )
    return render_template('components/message.html', msg=nova_msg)


@bp.route("/conversa_admin", methods=["GET", "POST"])
@bp.route("/conversa_admin/<int:user_id>", methods=["GET", "POST"])
@login_required
def conversa_admin(user_id=None):
    """Permite conversar diretamente com o administrador.

    - Usuários comuns acessam ``/conversa_admin`` para falar com o admin.
    - O administrador acessa ``/conversa_admin/<user_id>`` para responder
      mensagens de um usuário específico.
    """

    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        flash('Administrador não encontrado.', 'danger')
        return redirect(url_for('mensagens'))

    form = MessageForm()
    promotion_form = None
    delivery_promotion_form = None
    delivery_demotion_form = None
    parceiro_promotion_form = None
    parceiro_demotion_form = None
    target_membership = None
    cancel_trial_form = VeterinarianMembershipCancelTrialForm()
    request_new_trial_form = VeterinarianMembershipRequestNewTrialForm()
    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'

    if is_admin:
        if user_id is None:
            flash('Selecione um usuário para conversar.', 'warning')
            return redirect(url_for('mensagens_admin'))
        interlocutor = get_user_or_404(user_id)
        admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
        participant_id = interlocutor.id
        promotion_form = VeterinarianPromotionForm()
        delivery_promotion_form = DeliveryPromotionForm()
        delivery_demotion_form = DeliveryDemotionForm()
        parceiro_promotion_form = ParceiroPromotionForm()
        parceiro_demotion_form = ParceiroDemotionForm()
        if has_veterinarian_profile(interlocutor):
            target_membership = ensure_veterinarian_membership(interlocutor.veterinario)
            if target_membership and not hasattr(target_membership, 'is_trial_active'):
                target_membership = None
            elif target_membership and getattr(target_membership, 'id', None) is None:
                db.session.flush()
    else:
        interlocutor = admin_user
        admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
        participant_id = current_user.id
        if has_veterinarian_profile(current_user):
            target_membership = getattr(current_user.veterinario, 'membership', None)
            if target_membership:
                trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
                target_membership.ensure_trial_dates(trial_days)
                if not hasattr(target_membership, 'is_trial_active'):
                    target_membership = None
                elif getattr(target_membership, 'id', None) is None:
                    db.session.flush()

    mensagens = (
        Message.query
        .filter(
            ((Message.sender_id.in_(admin_ids)) & (Message.receiver_id == participant_id)) |
            ((Message.sender_id == participant_id) & (Message.receiver_id.in_(admin_ids)))
        )
        .order_by(Message.timestamp)
        .all()
    )

    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=interlocutor.id,
            content=form.content.data,
            lida=False
        )
        db.session.add(nova_msg)
        _notify_admin_message(
            receiver=interlocutor,
            sender=current_user,
            message_content=form.content.data,
        )
        db.session.commit()
        _push_nova_mensagem(
            interlocutor.id,
            url=(url_for('conversa_admin', user_id=current_user.id) if not is_admin else url_for('conversa_admin')),
        )
        if is_admin:
            return redirect(url_for('conversa_admin', user_id=interlocutor.id))
        return redirect(url_for('conversa_admin'))

    marked_read = False
    for m in mensagens:
        if is_admin:
            if m.receiver_id in admin_ids and not m.lida:
                m.lida = True
                marked_read = True
        else:
            if m.receiver_id == current_user.id and not m.lida:
                m.lida = True
                marked_read = True
    db.session.commit()
    if marked_read:
        if is_admin:
            _invalidate_admin_unread_cache()
        else:
            _invalidate_cached_context(current_user.id, 'unread_messages')

    can_cancel_trial = bool(
        target_membership
        and hasattr(target_membership, 'is_trial_active')
        and hasattr(target_membership, 'has_valid_payment')
        and getattr(target_membership, 'id', None)
        and target_membership.is_trial_active()
        and not target_membership.has_valid_payment()
    )

    can_request_new_trial = bool(
        target_membership
        and hasattr(target_membership, 'is_trial_active')
        and hasattr(target_membership, 'has_valid_payment')
        and getattr(target_membership, 'id', None)
        and not target_membership.is_trial_active()
        and not target_membership.has_valid_payment()
    )

    return render_template(
        'mensagens/conversa_admin.html',
        mensagens=mensagens,
        form=form,
        admin=interlocutor,
        promotion_form=promotion_form,
        delivery_promotion_form=delivery_promotion_form,
        delivery_demotion_form=delivery_demotion_form,
        parceiro_promotion_form=parceiro_promotion_form,
        parceiro_demotion_form=parceiro_demotion_form,
        target_membership=target_membership,
        is_admin=is_admin,
        cancel_trial_form=cancel_trial_form,
        can_cancel_trial=can_cancel_trial,
        request_new_trial_form=request_new_trial_form,
        can_request_new_trial=can_request_new_trial,
    )


@login_required
def api_conversa_admin_message(user_id=None):
    """Recebe nova mensagem na conversa com o admin e retorna HTML."""
    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        abort(404)

    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'

    if is_admin:
        if user_id is None:
            return '', 400
        interlocutor = get_user_or_404(user_id)
    else:
        interlocutor = admin_user

    form = MessageForm()
    if not form.validate_on_submit():
        if form.errors.keys() - {'csrf_token'}:
            current_app.logger.warning('api_conversa_admin_message validation failed for user %s: %s', current_user.id, form.errors)
            return jsonify(error='Falha de validação. Recarregue a página e tente novamente.'), 400
        content = request.form.get('content', '').strip()
        if not content or len(content) > 1000:
            return jsonify(error='Mensagem vazia ou muito longa.'), 400
    else:
        content = form.content.data
    nova_msg = Message(
        sender_id=current_user.id,
        receiver_id=interlocutor.id,
        content=content,
        lida=False,
    )
    db.session.add(nova_msg)
    _notify_admin_message(
        receiver=interlocutor,
        sender=current_user,
        message_content=content,
    )
    db.session.commit()
    _push_nova_mensagem(
        interlocutor.id,
        url=(url_for('conversa_admin', user_id=current_user.id) if not is_admin else url_for('conversa_admin')),
    )
    return render_template('components/message.html', msg=nova_msg)


@bp.route("/mensagens_admin", methods=["GET"])
@login_required
def mensagens_admin():
    """Lista as conversas iniciadas pelos usuários com o administrador."""
    if current_user.role != 'admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('index'))

    wants_json = 'application/json' in request.headers.get('Accept', '')
    page = max(request.args.get('page', type=int, default=1), 1)
    per_page = request.args.get('per_page', type=int, default=10)
    per_page = max(1, min(per_page or 10, 50))
    kind = request.args.get('kind', 'animals')

    admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]

    def _build_query(target_kind):
        query = (
            Message.query
            .options(
                selectinload(Message.sender),
                selectinload(Message.receiver),
                selectinload(Message.animal),
            )
            .filter((Message.sender_id.in_(admin_ids)) | (Message.receiver_id.in_(admin_ids)))
            .order_by(Message.timestamp.desc())
        )
        if target_kind == 'animals':
            query = query.filter(Message.animal_id.isnot(None))
        else:
            query = query.filter(Message.animal_id.is_(None))
        return query

    def _collect_threads(query):
        seen = set()
        threads = []
        offset = 0
        step = per_page * max(page, 2)
        last_batch_size = 0
        required = page * per_page
        while len(threads) < required:
            batch = query.offset(offset).limit(step).all()
            last_batch_size = len(batch)
            if not batch:
                break
            for message in batch:
                other_id = (
                    message.sender_id
                    if message.sender_id not in admin_ids
                    else message.receiver_id
                )
                key = (other_id, message.animal_id or 0)
                if message.sender_id in admin_ids:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                threads.append(message)
            offset += step
        start = (page - 1) * per_page
        page_items = threads[start:start + per_page]
        has_more = len(threads) > start + per_page
        if not has_more and last_batch_size == step:
            extra_batch = query.offset(offset).limit(per_page).all()
            for message in extra_batch:
                other_id = (
                    message.sender_id
                    if message.sender_id not in admin_ids
                    else message.receiver_id
                )
                key = (other_id, message.animal_id or 0)
                if key not in seen:
                    has_more = True
                    break
        return page_items, has_more

    unread = (
        db.session.query(Message.sender_id, db.func.count())
        .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
        .group_by(Message.sender_id)
        .all()
    )
    unread_counts = {u[0]: u[1] for u in unread}

    if wants_json:
        query = _build_query(kind)
        threads, has_more = _collect_threads(query)
        html = render_template(
            'mensagens/_admin_threads.html',
            threads=threads,
            unread_counts=unread_counts,
            kind=kind,
        )
        next_page = page + 1 if has_more else None
        return jsonify({
            'success': True,
            'html': html,
            'next_page': next_page,
            'kind': kind,
            'page': page,
        })

    animais_threads, animais_has_more = _collect_threads(_build_query('animals'))
    gerais_threads, gerais_has_more = _collect_threads(_build_query('general'))

    return render_template(
        'mensagens/mensagens_admin.html',
        mensagens_animais=animais_threads,
        mensagens_gerais=gerais_threads,
        unread_counts=unread_counts,
        animais_next=2 if animais_has_more else None,
        gerais_next=2 if gerais_has_more else None,
        per_page=per_page,
    )


@bp.route("/mensagens_admin/marcar_lidas", methods=["POST"])
@login_required
def mensagens_admin_marcar_lidas():
    """Marca como lidas todas as mensagens endereçadas ao pool de admins.

    Resolve badges fantasma: mensagens antigas em conversas nunca abertas
    (ou de remetentes que não aparecem na lista) ficavam não lidas para
    sempre, mantendo a notificação na navbar.
    """
    if current_user.role != 'admin':
        abort(403)

    admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
    atualizadas = (
        Message.query
        .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
        .update({Message.lida: True}, synchronize_session=False)
    )
    db.session.commit()
    _invalidate_admin_unread_cache()
    if atualizadas:
        flash(f'{atualizadas} mensagem(ns) marcada(s) como lida(s).', 'success')
    else:
        flash('Nenhuma mensagem pendente de leitura.', 'info')
    return redirect(url_for('mensagens_admin'))

