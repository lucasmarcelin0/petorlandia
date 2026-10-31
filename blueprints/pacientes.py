"""Views do domínio pacientes_routes (migrado do app.py)."""
import qrcode
from flask import Blueprint
import math, os, re, secrets, unicodedata, uuid
from urllib.parse import quote
from collections import defaultdict
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from extensions import csrf, db
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from forms import AnimalForm, ConsultaPlanAuthorizationForm, EditProfileForm
from helpers import has_professional_access
from io import BytesIO
from jinja2 import TemplateNotFound
from models import (
    Animal,
    AnimalHealthRecord,
    AnimalDocumento,
    Appointment,
    BlocoExames,
    BlocoPrescricao,
    Breed,
    CasaDeRacao,
    Clinica,
    Consulta,
    ConsultaToken,
    DataShareRequest,
    Endereco,
    ExamAppointment,
    ExameImagem,
    Interest,
    Message,
    Racao,
    ServicoClinica,
    Species,
    TipoRacao,
    Transaction,
    User,
    Vacina,
    VacinaModelo,
    Veterinario,
)
from document_utils import (
    format_phone_br,
    is_valid_cpf_length,
    is_valid_phone,
    normalize_cpf,
    normalize_phone,
    phone_national_digits,
    same_cpf,
    same_phone,
)
from models.usuarios import build_placeholder_email, is_placeholder_email
from services.animal_search import search_animals
from services.photo_intake import (
    PhotoIntakeError,
    normalize_photo_upload,
    normalized_filename,
    rotate_photo,
)
from services.photo_storage import MENSAGEM_GENERICA as MENSAGEM_FOTO_NAO_GUARDADA, PhotoStorageError, store_photo
from services.pet_growth import build_pet_opportunities
from services.product_analytics import track_event
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import aliased, joinedload, selectinload
from time_utils import BR_TZ, utcnow
from werkzeug.utils import secure_filename

# Helpers ainda hospedados no app.py (realocação em fases futuras).
from app import (  # noqa: E402
    TUTOR_SEARCH_LIMIT,
    _build_animals_pmo_dates,
    _canonicalize_racao_brand,
    _clinic_orcamento_blocks,
    _clinic_prescricao_blocks,
    _formatar_idade,
    _geocode_endereco,
    _get_recent_animais,
    _get_recent_tutores,
    _integration_create_exame_imagem,
    _integration_list_exame_imagem_history,
    _integration_release_exame_imagem,
    _integration_store_exame_pdf_upload,
    _is_specialist_veterinarian,
    _is_tutor_portal_user,
    _normalizar_unidade_idade,
    _preencher_idade_form,
    _resolve_record_panel,
    _resolve_shared_access_for_animal,
    _resolve_shared_access_for_user,
    _sanitize_login_next_url,
    _serialize_share_request,
    _serialize_tutor_share_payload,
    _update_coordinates_from_request,
    _user_visibility_clause,
    _viewer_accessible_clinic_ids,
    _web_exame_imagem_ensure_invite,
    _web_exame_imagem_notify,
    _web_exame_imagem_operator_required,
    _web_render_exames_imagem,
    _web_user_can_manage_exame_imagem,
    bake_image_rotation,
    current_user_clinic_id,
    enviar_mensagem_whatsapp,
    find_users_by_phone,
    formatar_telefone,
    get_animal_or_404,
    get_user_or_404,
    list_breeds,
    list_rations,
    list_species,
)

bp = Blueprint("pacientes_routes", __name__)


def get_blueprint():
    return bp


def BUCKET(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.BUCKET.
    import app as app_module
    return app_module.BUCKET(*args, **kwargs)


def _is_admin(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._is_admin.
    import app as app_module
    return app_module._is_admin(*args, **kwargs)


def _s3(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._s3.
    import app as app_module
    return app_module._s3(*args, **kwargs)


def is_veterinarian(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.is_veterinarian.
    import app as app_module
    return app_module.is_veterinarian(*args, **kwargs)


def can_act_as_veterinarian(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.can_act_as_veterinarian.
    import app as app_module
    return app_module.can_act_as_veterinarian(*args, **kwargs)


def pessoa_no_documento(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.pessoa_no_documento.
    import app as app_module
    return app_module.pessoa_no_documento(*args, **kwargs)


def veterinarian_denial_message(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.veterinarian_denial_message.
    import app as app_module
    return app_module.veterinarian_denial_message(*args, **kwargs)


def can_edit_animal_record(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.can_edit_animal_record.
    import app as app_module
    return app_module.can_edit_animal_record(*args, **kwargs)


def is_supervised_intern(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.is_supervised_intern.
    import app as app_module
    return app_module.is_supervised_intern(*args, **kwargs)


def acting_clinic_id(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.acting_clinic_id.
    import app as app_module
    return app_module.acting_clinic_id(*args, **kwargs)

def get_responsible_veterinarian(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.get_responsible_veterinarian.
    import app as app_module
    return app_module.get_responsible_veterinarian(*args, **kwargs)


def upload_to_s3(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.upload_to_s3.
    import app as app_module
    return app_module.upload_to_s3(*args, **kwargs)



@bp.route('/add-animal', methods=['GET', 'POST'])
@login_required
def add_animal():
    form = AnimalForm()
    _preencher_idade_form(form)

    # Listas para o template
    try:
        species_list = list_species()
    except Exception:
        species_list = []
    try:
        breed_list = list_breeds()
    except Exception:
        breed_list = []

    # Debug da requisição
    current_app.logger.debug("add_animal request method=%s", request.method)
    current_app.logger.debug("add_animal form data keys=%s", list(request.form.keys()))

    if form.validate_on_submit():
        current_app.logger.debug("add_animal form validated")

        image_url = None
        if form.image.data:
            file = form.image.data
            original_filename = secure_filename(file.filename)
            filename = f"{uuid.uuid4().hex}_{original_filename}"
            current_app.logger.debug("add_animal image upload started filename=%s", filename)
            image_url = upload_to_s3(file, filename, folder="animals")
            current_app.logger.debug("add_animal image upload completed url=%s", image_url)

        # IDs das listas
        species_id = request.form.get("species_id", type=int)
        breed_id = request.form.get("breed_id", type=int)
        current_app.logger.debug("add_animal species_id=%s breed_id=%s", species_id, breed_id)

        dob = form.date_of_birth.data
        idade_valor = (form.age.data or '').strip()
        unidade_valor = _normalizar_unidade_idade(form.age_unit.data if hasattr(form, 'age_unit') else 'anos')
        idade_numero = None
        try:
            idade_numero = int(idade_valor)
        except (ValueError, TypeError):
            idade_numero = None

        if not dob and idade_numero is not None:
            if unidade_valor == 'meses':
                dob = date.today() - relativedelta(months=idade_numero)
            else:
                dob = date.today() - relativedelta(years=idade_numero)

        idade_formatada = None if not idade_valor else idade_valor
        if idade_numero is not None:
            idade_formatada = _formatar_idade(idade_numero, unidade_valor)

        # Grava a rotação nos pixels para a foto ficar igual em qualquer container
        # (o card é retangular; o editor é quadrado).
        rotation_add = int(form.photo_rotation.data or 0) % 360
        if rotation_add and image_url:
            image_url = bake_image_rotation(image_url, rotation_add, folder="animals")

        # Criação do animal
        animal = Animal(
            name=form.name.data,
            species_id=species_id,
            breed_id=breed_id,
            age=idade_formatada,
            date_of_birth=dob,
            sex=form.sex.data,
            description=form.description.data,
            image=image_url,
            photo_rotation=0,
            photo_zoom=form.photo_zoom.data,
            photo_offset_x=form.photo_offset_x.data,
            photo_offset_y=form.photo_offset_y.data,
            modo=form.modo.data,
            price=form.price.data if form.modo.data == 'venda' else None,
            status='disponível',
            owner=current_user,
            is_alive=True
        )

        db.session.add(animal)
        try:
            db.session.commit()
            current_app.logger.info("Animal cadastrado com ID %s", animal.id)
            flash(f'Prontinho! {animal.name} agora faz parte da PetOrlândia. 🐾', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Erro ao salvar animal: %s", e)
            flash('Erro ao salvar o animal.', 'danger')

    elif request.method == 'POST':
        current_app.logger.debug("add_animal invalid form errors=%s", form.errors)

    return render_template(
        'animais/add_animal.html',
        form=form,
        species_list=species_list,
        breed_list=breed_list
    )


@bp.route('/exames-imagem', methods=['GET', 'POST'])
@login_required
def exames_imagem_painel():
    _web_exame_imagem_operator_required()
    if request.method == 'GET':
        return _web_render_exames_imagem(request.args.get('exame_id', type=int))

    form = request.form
    pdf_file = request.files.get('arquivo_pdf')
    wants_share = any(
        form.get(name)
        for name in ('liberar_clinica', 'gerar_convite_clinica', 'liberar_tutor', 'gerar_convite_tutor')
    )
    has_pdf_upload = bool(pdf_file and getattr(pdf_file, 'filename', ''))
    if wants_share and not has_pdf_upload:
        flash('Anexe o PDF do laudo antes de liberar acesso para clinica ou tutor.', 'warning')
        return _web_render_exames_imagem(), 400

    payload = {
        'nome_clinica': form.get('nome_clinica'),
        'email_clinica': form.get('email_clinica'),
        'telefone_clinica': form.get('telefone_clinica'),
        'nome_tutor': form.get('nome_tutor'),
        'email_tutor': form.get('email_tutor'),
        'telefone_tutor': form.get('telefone_tutor'),
        'nome_animal': form.get('nome_animal'),
        'especie': form.get('especie'),
        'raca': form.get('raca'),
        'sexo': form.get('sexo'),
        'idade': form.get('idade'),
        'tipo_exame': form.get('tipo_exame'),
        'data_exame': form.get('data_exame'),
        'titulo': form.get('titulo') or form.get('tipo_exame'),
        'descricao': form.get('descricao'),
        'impressao_diagnostica': form.get('impressao_diagnostica'),
        'profissional_nome': form.get('profissional_nome') or getattr(current_user, 'name', None),
        'profissional_crmv': form.get('profissional_crmv') or getattr(getattr(current_user, 'veterinario', None), 'crmv', None),
        'finalizar': True,
    }

    try:
        result = _integration_create_exame_imagem(current_user, payload)
        exame = db.session.get(ExameImagem, result['exame']['id'])
        if has_pdf_upload:
            _integration_store_exame_pdf_upload(current_user, exame, pdf_file)
            exame = db.session.get(ExameImagem, exame.id)

        if form.get('liberar_clinica'):
            _integration_release_exame_imagem(
                current_user,
                {'exame_id': exame.id, 'clinica_id': exame.clinica_requisitante_id},
                target='clinica',
            )
            exame = db.session.get(ExameImagem, exame.id)
        if form.get('gerar_convite_clinica'):
            clinic_invite = _web_exame_imagem_ensure_invite(current_user, exame, 'clinic', form)
            _web_exame_imagem_notify(exame, clinic_invite, 'clinic')
        if form.get('liberar_tutor'):
            _integration_release_exame_imagem(
                current_user,
                {'exame_id': exame.id, 'tutor_id': exame.tutor_id},
                target='tutor',
            )
            exame = db.session.get(ExameImagem, exame.id)
        if form.get('gerar_convite_tutor'):
            tutor_invite = _web_exame_imagem_ensure_invite(current_user, exame, 'tutor', form)
            _web_exame_imagem_notify(exame, tutor_invite, 'tutor')
        db.session.commit()
    except PermissionError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return _web_render_exames_imagem(), 403
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
        return _web_render_exames_imagem(), 400

    flash('Laudo salvo e acessos preparados.', 'success')
    return redirect(url_for('exames_imagem_painel', exame_id=exame.id))


@bp.route('/exames-imagem/<int:exame_id>/compartilhar', methods=['POST'])
@login_required
def exames_imagem_compartilhar(exame_id):
    _web_exame_imagem_operator_required()
    exame = db.session.get(ExameImagem, exame_id)
    if not exame:
        abort(404)
    if not _web_user_can_manage_exame_imagem(current_user, exame):
        abort(403)
    if not exame.arquivo_pdf_url:
        flash('Anexe o PDF antes de gerar links de acesso.', 'warning')
        return redirect(url_for('exames_imagem_painel', exame_id=exame.id))

    target = (request.form.get('target') or '').strip().lower()
    try:
        if target == 'clinica':
            _integration_release_exame_imagem(
                current_user,
                {'exame_id': exame.id, 'clinica_id': exame.clinica_requisitante_id},
                target='clinica',
            )
            exame = db.session.get(ExameImagem, exame.id)
            invite = _web_exame_imagem_ensure_invite(current_user, exame, 'clinic', request.form)
            _web_exame_imagem_notify(exame, invite, 'clinic')
            flash('Acesso da clinica preparado.', 'success')
        elif target == 'tutor':
            _integration_release_exame_imagem(
                current_user,
                {'exame_id': exame.id, 'tutor_id': exame.tutor_id},
                target='tutor',
            )
            exame = db.session.get(ExameImagem, exame.id)
            invite = _web_exame_imagem_ensure_invite(current_user, exame, 'tutor', request.form)
            _web_exame_imagem_notify(exame, invite, 'tutor')
            flash('Acesso do tutor preparado.', 'success')
        else:
            abort(400)
        db.session.commit()
    except PermissionError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')

    return redirect(url_for('exames_imagem_painel', exame_id=exame.id))


@bp.route('/meus-animais')
@login_required
def meus_animais():
    return redirect(url_for('list_animals'))


@bp.route('/animals')
def list_animals():
    page = request.args.get('page', 1, type=int)
    per_page = 9
    modo = request.args.get('modo')
    species_id = request.args.get('species_id', type=int)
    breed_id = request.args.get('breed_id', type=int)
    sex = request.args.get('sex')
    age = request.args.get('age')
    show_all = _is_admin() and request.args.get('show_all') == '1'
    name_query = request.args.get('name')
    tutor_name_query = (request.args.get('tutor_name') or '').strip()
    tutor_search_query = (request.args.get('tutor_search') or '').strip()
    is_admin_user = _is_admin()
    admin_tutor_query = (tutor_search_query or tutor_name_query) if is_admin_user else ''

    def admin_tutor_filters(term):
        """Busca administrativa por dados do tutor, inclusive CPF sem máscara."""
        like_term = f"%{term}%"
        filters = [
            User.name.ilike(like_term),
            User.email.ilike(like_term),
            User.cpf.ilike(like_term),
            User.rg.ilike(like_term),
            User.phone.ilike(like_term),
            User.phone2.ilike(like_term),
            User.address.ilike(like_term),
        ]
        digits = re.sub(r'\D', '', term)
        if digits:
            normalized_like = f"%{digits}%"
            for column, punctuation in (
                (User.cpf, ['.', '-', '/', ' ']),
                (User.rg, ['.', '-', '/', ' ']),
                (User.phone, ['(', ')', '-', ' ']),
                (User.phone2, ['(', ')', '-', ' ']),
            ):
                normalized_column = column
                for char in punctuation:
                    normalized_column = func.replace(normalized_column, char, '')
                filters.append(normalized_column.ilike(normalized_like))
        return filters

    # Base query: ignora animais removidos e sem responsável cadastrado
    query = Animal.query.filter(Animal.removido_em.is_(None), Animal.user_id.isnot(None))

    # Escopo "meus": só os pets do usuário logado (qualquer modo). É o destino
    # do link "Meus pets" da navbar — a listagem geral continua servindo
    # adoção/venda/perdidos para todo mundo.
    scope = request.args.get('scope')
    if scope == 'meus' and current_user.is_authenticated:
        query = query.filter(Animal.user_id == current_user.id)
        if modo and modo.lower() != 'todos':
            query = query.filter_by(modo=modo)
    # Filtro por modo
    elif modo and modo.lower() != 'todos':
        query = query.filter_by(modo=modo)
    else:
        # Admins can see all animals without filtering
        vet_authorized = current_user.is_authenticated and can_act_as_veterinarian(current_user)
        collaborator = (
            current_user.is_authenticated
            and getattr(current_user, 'worker', None) == 'colaborador'
        )

        if is_admin_user or show_all:
            # Admins and show_all mode: no additional filtering
            pass
        elif vet_authorized:
            # Veterinários só podem ver animais perdidos, à venda ou para adoção,
            # ou então animais cadastrados pela própria clínica
            allowed = ['perdido', 'venda', 'doação']
            clinic_id = getattr(current_user.veterinario, 'clinica_id', None) or current_user.clinica_id
            if clinic_id:
                query = query.filter(
                    or_(
                        Animal.modo.in_(allowed),
                        Animal.clinica_id == clinic_id
                    )
                )
            else:
                query = query.filter(Animal.modo.in_(allowed))
        elif not collaborator:
            # Para usuários comuns e não colaboradores: mostrar animais à venda/doação ou próprios
            if current_user.is_authenticated:
                query = query.filter(
                    or_(
                        Animal.user_id == current_user.id,
                        Animal.modo.in_(["venda", "doação"])
                    )
                )
            else:
                query = query.filter(Animal.modo.in_(["venda", "doação"]))

    if species_id:
        query = query.filter_by(species_id=species_id)
    if breed_id:
        query = query.filter_by(breed_id=breed_id)
    if sex:
        query = query.filter_by(sex=sex)
    if age:
        query = query.filter(Animal.age.ilike(f"{age}%"))
    if name_query:
        query = query.filter(Animal.name.ilike(f"%{name_query}%"))
    tutor_results = None
    if is_admin_user and admin_tutor_query:
        tutor_filters = admin_tutor_filters(admin_tutor_query)
        query = query.join(User, Animal.user_id == User.id)
        query = query.filter(or_(*tutor_filters))
        matched_tutors = (
            User.query
            .options(selectinload(User.animals))
            .filter(or_(*tutor_filters))
            .order_by(func.lower(User.name))
            .limit(30)
            .all()
        )
        tutor_results = [
            {
                'tutor': tutor,
                'animal_count': sum(
                    1 for animal in tutor.animals if not getattr(animal, 'removido_em', None)
                ),
            }
            for tutor in matched_tutors
        ]
    elif tutor_name_query:
        query = query.join(User, Animal.user_id == User.id).filter(
            User.name.ilike(f"%{tutor_name_query}%")
        )

    # Ordenação e paginação
    query = query.options(
        selectinload(Animal.species),
        selectinload(Animal.breed),
        selectinload(Animal.owner),
    )
    query = query.order_by(Animal.date_added.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    animals = pagination.items
    pmo_dates = _build_animals_pmo_dates(animals)

    try:
        species_list = list_species()
    except Exception:
        species_list = []
    try:
        breed_list = list_breeds()
    except Exception:
        breed_list = []

    context = dict(
        animals=animals,
        pagination=pagination,
        page=page,
        total_pages=pagination.pages,
        modo=modo,
        species_list=species_list,
        breed_list=breed_list,
        species_id=species_id,
        breed_id=breed_id,
        sex=sex,
        age=age,
        name=name_query,
        tutor_name=tutor_name_query,
        tutor_search=tutor_search_query if is_admin_user else '',
        tutor_results=tutor_results,
        pmo_dates=pmo_dates,
        is_admin=is_admin_user,
        show_all=show_all,
        scope=scope,
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_template('animais/_animals_content.html', **context)
        return jsonify(
            {
                'html': html,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_pages': pagination.pages,
                    'total_items': pagination.total,
                    'has_next': pagination.has_next,
                    'has_prev': pagination.has_prev,
                    'next_page': pagination.next_num if pagination.has_next else None,
                    'prev_page': pagination.prev_num if pagination.has_prev else None,
                },
            }
        )

    return render_template('animais/animals.html', **context)


@bp.route('/animal/<int:animal_id>/adotar', methods=['POST'])
@login_required
def adotar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.status != 'disponível':
        flash('Este animal já foi adotado ou vendido.', 'danger')
        return redirect(url_for('list_animals'))

    animal.status = 'adotado'  # ou 'vendido', se for o caso
    animal.user_id = current_user.id  # <- transfere a posse do animal
    db.session.commit()
    flash(f'Você adotou {animal.name} com sucesso!', 'success')
    return redirect(url_for('list_animals'))


#: Mesmas extensões aceitas pelo AnimalForm na edição do animal.
_FOTO_ANUNCIO_EXTENSOES = {'jpg', 'jpeg', 'png', 'gif'}


@bp.route('/adocao/revisar', methods=['GET', 'POST'])
@login_required
def revisar_adocao():
    """Tela em que o responsável confirma, encerra e completa seus anúncios.

    É também o destino do pop-up mensal do layout e dos e-mails de
    services/adocao_lembretes.py.
    """
    from context_processors import _invalidate_cached_context
    from services import adocao_lembretes

    if request.method == 'POST':
        destino = _sanitize_login_next_url(
            request.form.get('next'), fallback=url_for('revisar_adocao')
        )
        animais = adocao_lembretes.ensure_own_adoption_listings(
            current_user, request.form.getlist('animal_id')
        )
        confirmados, devolvidos, adotados, fotos, avisos = [], [], [], [], []
        for animal in animais:
            resposta = request.form.get(f'resposta_{animal.id}')
            if resposta == 'adotado':
                adocao_lembretes.mark_adopted(animal)
                adotados.append(animal.name)
                continue

            foto = request.files.get(f'foto_{animal.id}')
            foto_salva = False
            if foto and getattr(foto, 'filename', ''):
                extensao = foto.filename.rsplit('.', 1)[-1].lower() if '.' in foto.filename else ''
                image_url = None
                if extensao in _FOTO_ANUNCIO_EXTENSOES:
                    filename = f"{uuid.uuid4().hex}_{secure_filename(foto.filename)}"
                    image_url = upload_to_s3(foto, filename, folder="animals")
                if image_url:
                    animal.image = image_url
                    # Enquadramento era da foto antiga; a nova começa do zero.
                    animal.photo_rotation = 0
                    animal.photo_zoom = 1
                    animal.photo_offset_x = 0
                    animal.photo_offset_y = 0
                    foto_salva = True
                    fotos.append(animal.name)
                else:
                    avisos.append(
                        f'Não foi possível salvar a foto de {animal.name}. '
                        'Envie uma imagem JPG, PNG ou GIF.'
                    )

            # Quem manda foto nova está dizendo que o animal segue disponível.
            if resposta == 'disponivel' or foto_salva:
                # Anúncio que saiu da lista por falta de resposta volta a ela.
                fora_da_lista = animal.modo != adocao_lembretes.ADOPTION_MODE
                adocao_lembretes.confirm_still_available(animal)
                (devolvidos if fora_da_lista else confirmados).append(animal.name)

        telefone = (request.form.get('telefone') or '').strip()
        telefone_salvo = False
        if telefone and adocao_lembretes.needs_phone(current_user):
            if not is_valid_phone(telefone):
                avisos.append('Telefone inválido. Informe o DDD e o número.')
            elif find_users_by_phone(telefone, exclude_user_id=current_user.id):
                avisos.append('Este telefone já está em uso em outra conta.')
            else:
                current_user.phone = normalize_phone(telefone)
                telefone_salvo = True

        db.session.commit()
        _invalidate_cached_context(current_user.id, 'adoption_review')

        feito = []
        if adotados:
            verbo = 'saiu' if len(adotados) == 1 else 'saíram'
            feito.append(
                f'Que notícia boa! {adocao_lembretes.join_names(adotados)} '
                f'{verbo} da lista de adoção.'
            )
        if confirmados:
            verbo = 'continua' if len(confirmados) == 1 else 'continuam'
            feito.append(
                f'{adocao_lembretes.join_names(confirmados)} {verbo} na lista de '
                'adoção; perguntamos de novo daqui a um mês.'
            )
        if devolvidos:
            verbo = 'voltou' if len(devolvidos) == 1 else 'voltaram'
            feito.append(
                f'{adocao_lembretes.join_names(devolvidos)} {verbo} para a lista de adoção.'
            )
        if fotos:
            feito.append(f'Foto nova de {adocao_lembretes.join_names(fotos)} salva.')
        if telefone_salvo:
            feito.append('Telefone salvo.')
        if feito:
            flash(' '.join(feito), 'success')
        for aviso in avisos:
            flash(aviso, 'warning')
        if not (feito or avisos):
            flash('Nada foi alterado.', 'info')
        return redirect(destino)

    return render_template(
        'animais/adocao_revisar.html',
        review_animals=adocao_lembretes.review_cards(
            adocao_lembretes.listings_of(current_user)
            + adocao_lembretes.expired_listings_of(current_user)
        ),
        review_needs_phone=adocao_lembretes.needs_phone(current_user),
        # A própria tela já é o formulário: o pop-up por cima seria redundante.
        adoption_review_modal_disabled=True,
    )


@bp.route('/animal/<int:animal_id>/editar', methods=['GET', 'POST'])
@bp.route('/editar_animal/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def editar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.user_id != current_user.id:
        flash('Você não tem permissão para editar este animal.', 'danger')
        return redirect(url_for('profile'))

    form = AnimalForm(obj=animal)
    _preencher_idade_form(form, animal)

    species_list = list_species()
    breed_list = list_breeds()




    if form.validate_on_submit():
        animal.name = form.name.data
        animal.sex = form.sex.data
        animal.description = form.description.data
        animal.modo = form.modo.data
        animal.price = form.price.data if form.modo.data == 'venda' else None

        # Data de nascimento calculada a partir da idade se necessário
        dob = form.date_of_birth.data
        idade_valor = (form.age.data or '').strip()
        unidade_valor = _normalizar_unidade_idade(form.age_unit.data if hasattr(form, 'age_unit') else 'anos')
        idade_numero = None
        try:
            idade_numero = int(idade_valor)
        except (ValueError, TypeError):
            idade_numero = None

        if not dob and idade_numero is not None:
            if unidade_valor == 'meses':
                dob = date.today() - relativedelta(months=idade_numero)
            else:
                dob = date.today() - relativedelta(years=idade_numero)
        animal.age = _formatar_idade(idade_numero, unidade_valor) if idade_numero is not None else (idade_valor or None)
        animal.date_of_birth = dob

        # Relacionamentos
        species_id = request.form.get('species_id')
        breed_id = request.form.get('breed_id')
        if species_id:
            animal.species_id = int(species_id)
        if breed_id:
            animal.breed_id = int(breed_id)

        # Upload da nova imagem, se fornecida
        if form.image.data and getattr(form.image.data, 'filename', ''):
            file = form.image.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            image_url = upload_to_s3(file, filename, folder="animals")
            if image_url:
                animal.image = image_url

        # Grava a rotação nos pixels (para ficar igual em cards retangulares) e
        # persiste zoom/deslocamento do cropper. Sem isto a rotação feita no editor
        # era descartada/renderizada deitada fora do editor.
        rotation = int(form.photo_rotation.data or 0) % 360
        if rotation and animal.image:
            animal.image = bake_image_rotation(animal.image, rotation, folder="animals")
        animal.photo_rotation = 0
        animal.photo_zoom = form.photo_zoom.data or 1
        animal.photo_offset_x = form.photo_offset_x.data or 0
        animal.photo_offset_y = form.photo_offset_y.data or 0

        db.session.commit()
        flash(f'Os dados de {animal.name} foram atualizados!', 'success')
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    return render_template('animais/editar_animal.html',
                           form=form,
                           animal=animal,
                           species_list=species_list,
                           breed_list=breed_list)


@bp.route('/animal/<int:animal_id>/deletar', methods=['POST'])
@login_required
def deletar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if not (
        current_user.role == 'admin'
        or animal.user_id == current_user.id
        or animal.added_by_id == current_user.id
    ):
        message = 'Você não tem permissão para excluir este animal.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='danger'), 403
        flash(message, 'danger')
        abort(403)

    if animal.removido_em:
        message = 'Animal já foi removido anteriormente.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(
                message=message,
                category='warning',
                deleted=True,
                status='already_removed',
                undo_available=False,
                restore_available=False,
            ), 200
        flash(message, 'warning')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    animal.removido_em = utcnow()
    db.session.commit()
    message = 'Animal marcado como removido. Histórico preservado.'
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(
            message=message,
            category='success',
            deleted=True,
            status='removed',
            undo_available=False,
            restore_available=False,
        )
    flash(message, 'success')
    return redirect(request.referrer or url_for('list_animals'))


@bp.route('/termo/interesse/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_interesse(animal_id, user_id):
    # Bypass strict privacy checks for interest term to allow adoption flow
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

    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    return render_template('termos/termo_interesse.html', animal=animal, interessado=interessado, data_atual=data_atual)


@bp.route('/termo/transferencia/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_transferencia(animal_id, user_id):
    animal = get_animal_or_404(animal_id)
    novo_dono = get_user_or_404(user_id)

    if animal.owner.id != current_user.id:
        flash("Você não tem permissão para transferir esse animal.", "danger")
        return redirect(url_for('profile'))

    if request.method == 'POST':
        try:
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
                date=utcnow()
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

            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao transferir tutoria")
            flash('Ocorreu um erro ao transferir a tutoria.', 'danger')
        else:
            flash(f'Tutoria de {animal.name} transferida para {novo_dono.name}.', 'success')

            # WhatsApp para o novo tutor
            if novo_dono.phone:
                numero_formatado = f"whatsapp:{formatar_telefone(novo_dono.phone)}"
                texto_wpp = f"Parabéns, {novo_dono.name}! Agora você é o tutor de {animal.name} pelo PetOrlândia. 🐶🐱"

                try:
                    enviar_mensagem_whatsapp(texto_wpp, numero_formatado)
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        return redirect(url_for('profile'))

    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    return render_template('termos/termo_transferencia.html', animal=animal, novo_dono=novo_dono)


@bp.route('/animal/<int:animal_id>/termo/<string:tipo>')
@login_required
def termo_animal(animal_id, tipo):
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    # Estagiário emite o termo no nome do supervisor.
    emissor = pessoa_no_documento(current_user)
    veterinario = getattr(emissor, 'veterinario', None)
    clinica = veterinario.clinica if veterinario else None
    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    templates = {
        'internacao': 'termos/termo_internacao.html',
        'eutanasia': 'termos/termo_eutanasia.html',
        'procedimentos': 'termos/termo_procedimentos.html',
        'exames': 'termos/termo_exames.html',
        'imagem': 'termos/termo_imagem.html',
        'medicacao': 'termos/termo_medicacao.html',
        'planos': 'termos/termo_planos.html',
        'adocao': 'termos/termo_adocao.html',
        'viagem': 'termos/termo_viagem.html',
    }
    template = templates.get(tipo)
    if not template:
        abort(404)
    return render_template(template, animal=animal, tutor=tutor, clinica=clinica,
                           data_atual=data_atual, veterinario=veterinario, printing_user=emissor)


@bp.route('/termo/<int:animal_id>/<tipo>')
@login_required
def gerar_termo(animal_id, tipo):
    """Gera um termo específico para um animal."""
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    veterinario = getattr(pessoa_no_documento(current_user), 'veterinario', None)
    template_name = f'termos/{tipo}.html'
    try:
        return render_template(
            template_name,
            animal=animal,
            tutor=tutor,
            veterinario=veterinario,
            tipo=tipo,
        )
    except TemplateNotFound:
        abort(404)


@bp.route('/animal/<int:animal_id>/ficha')
@login_required
def ficha_animal(animal_id):
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner

    wants_json = 'application/json' in request.headers.get('Accept', '')
    section = request.args.get('section')

    def _consultas_query():
        consultas_query = Consulta.query.filter_by(
            animal_id=animal.id,
            status='finalizada',
        )
        if (
            current_user.role != 'admin'
            and has_professional_access(current_user)
        ):
            consultas_query = consultas_query.filter_by(
                clinica_id=current_user_clinic_id()
            )
        return consultas_query.order_by(Consulta.created_at.desc())

    def _load_consultas():
        return _consultas_query().all()

    def _load_history_data():
        consultas = _load_consultas()
        blocos_prescricao_query = BlocoPrescricao.query.filter_by(
            animal_id=animal.id
        )
        clinic_scope = None
        if current_user.role != 'admin':
            clinic_scope = current_user_clinic_id()
        if clinic_scope:
            blocos_prescricao_query = blocos_prescricao_query.filter_by(
                clinica_id=clinic_scope
            )
        blocos_prescricao = blocos_prescricao_query.all()
        blocos_exames = BlocoExames.query.filter_by(animal_id=animal.id).all()
        vacinas_aplicadas = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=True)
            .order_by(Vacina.aplicada_em.desc())
            .all()
        )
        proxima_vacina = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
            .filter(Vacina.aplicada_em.isnot(None))
            .filter(Vacina.aplicada_em >= date.today())
            .order_by(Vacina.aplicada_em)
            .first()
        )
        doses_atrasadas = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
            .filter(Vacina.aplicada_em < date.today())
            .order_by(Vacina.aplicada_em)
            .all()
        )
        exames_imagem = _integration_list_exame_imagem_history(current_user, animal)
        return {
            'consultas': consultas,
            'blocos_prescricao': blocos_prescricao,
            'blocos_exames': blocos_exames,
            'exames_imagem': exames_imagem,
            'vacinas_aplicadas': vacinas_aplicadas,
            'proxima_vacina': proxima_vacina,
            'doses_atrasadas': doses_atrasadas,
        }

    def _load_events_data():
        now = utcnow()
        vacinas_agendadas = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
            .filter(Vacina.aplicada_em >= date.today())
            .order_by(Vacina.aplicada_em)
            .all()
        )
        retornos = (
            Appointment.query.filter_by(animal_id=animal.id)
            .filter(Appointment.scheduled_at >= now)
            .filter(Appointment.status.in_(["scheduled", "accepted"]))
            .filter(Appointment.consulta_id.isnot(None))
            .order_by(Appointment.scheduled_at)
            .all()
        )
        exames_agendados = (
            ExamAppointment.query.filter_by(animal_id=animal.id)
            .filter(ExamAppointment.scheduled_at >= now)
            .filter(ExamAppointment.status.in_(["pending", "confirmed"]))
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        return {
            'vacinas_agendadas': vacinas_agendadas,
            'retornos': retornos,
            'exames_agendados': exames_agendados,
        }

    if wants_json or section:
        current_section = section or 'events'
        if current_section == 'events':
            data = _load_events_data()
            html = render_template(
                'animais/_animal_events.html',
                animal=animal,
                **data,
            )
            return jsonify({'success': True, 'html': html, 'section': 'events'})
        if current_section == 'history':
            data = _load_history_data()
            html = render_template(
                'animais/_animal_history.html',
                animal=animal,
                tutor=tutor,
                **data,
            )
            return jsonify({'success': True, 'html': html, 'section': 'history'})
        return jsonify({'success': False, 'message': 'Seção inválida.'}), 400

    events_url = url_for('ficha_animal', animal_id=animal.id, section='events')
    history_url = url_for('ficha_animal', animal_id=animal.id, section='history')
    pet_opportunities = []
    health_card_whatsapp_url = None
    if animal.user_id == current_user.id:
        pet_opportunities = build_pet_opportunities(animal)
        if animal.public_token:
            card_url = url_for(
                'carteirinha_publica', token=animal.public_token, _external=True
            )
            message = f'Carteirinha digital de {animal.name}: {card_url}'
            health_card_whatsapp_url = f'https://wa.me/?text={quote(message)}'
    from services.selo_prefeitura import selo_atual, situacao_do_selo

    selo_prefeitura = situacao_do_selo(selo_atual(animal))
    return render_template(
        'animais/ficha_animal.html',
        animal=animal,
        tutor=tutor,
        events_url=events_url,
        history_url=history_url,
        pet_opportunities=pet_opportunities,
        health_card_whatsapp_url=health_card_whatsapp_url,
        selo_prefeitura=selo_prefeitura,
        hoje=date.today(),
        resumo=_resumo_ficha_animal(animal, _consultas_query()),
        contatos_tutor=_contatos_do_tutor(tutor) if tutor else None,
        idade_animal=_idade_exibicao(animal),
        peso_animal=_peso_exibicao(animal.peso),
    )


def _resumo_ficha_animal(animal, consultas_query):
    """Quadro do topo da ficha: última consulta, vacinas e próximo retorno.

    Só consultas leves (``first``/``count``); as listas completas continuam
    nas abas, carregadas por AJAX. A consulta de consultas vem pronta da rota
    para respeitar o mesmo recorte por clínica do histórico.
    """
    hoje = date.today()
    pendentes = Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
    proxima_vacina = (
        pendentes.filter(Vacina.aplicada_em.isnot(None))
        .filter(Vacina.aplicada_em >= hoje)
        .order_by(Vacina.aplicada_em)
        .first()
    )
    vacinas_atrasadas = pendentes.filter(Vacina.aplicada_em < hoje).count()
    tem_vacina_aplicada = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=True).first() is not None
    )
    proximo_retorno = (
        Appointment.query.filter_by(animal_id=animal.id)
        .filter(Appointment.scheduled_at >= utcnow())
        .filter(Appointment.status.in_(["scheduled", "accepted"]))
        .filter(Appointment.consulta_id.isnot(None))
        .order_by(Appointment.scheduled_at)
        .first()
    )
    return {
        'ultima_consulta': consultas_query.first(),
        'proxima_vacina': proxima_vacina,
        'vacinas_atrasadas': vacinas_atrasadas,
        'tem_vacina_aplicada': tem_vacina_aplicada,
        'proximo_retorno': proximo_retorno,
    }


@bp.route('/animal/<int:animal_id>/documentos', methods=['POST'])
@login_required
def upload_document(animal_id):
    animal = get_animal_or_404(animal_id)
    if not can_edit_animal_record(current_user, animal):
        flash(veterinarian_denial_message('Apenas veterinários podem enviar documentos.'), 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    files = [file for file in request.files.getlist('documento') if file and file.filename]
    if not files:
        flash('Nenhum arquivo enviado.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))
    if len(files) > 5:
        flash('Envie no máximo 5 documentos por vez.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    descricao = (request.form.get('descricao') or '').strip().lower()
    tipo_termo = (request.form.get('tipo') or descricao)
    documentos_criados = []
    for index, file in enumerate(files, start=1):
        filename_base = secure_filename(file.filename)
        ext = os.path.splitext(filename_base)[1]
        if tipo_termo in ['termo_interesse', 'termo_transferencia']:
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            suffix = f"_{index}" if len(files) > 1 else ""
            filename = f"{tipo_termo}_{animal.id}_{timestamp}{suffix}{ext}"
        else:
            filename = f"{uuid.uuid4().hex}_{filename_base}"

        file_url = upload_to_s3(file, filename, folder='documentos')
        if not file_url:
            db.session.rollback()
            flash('Falha ao enviar arquivo.', 'danger')
            return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

        documento = AnimalDocumento(
            animal_id=animal.id,
            veterinario_id=current_user.id,
            filename=filename,
            file_url=file_url,
            descricao=descricao
        )
        db.session.add(documento)
        documentos_criados.append(documento)
    db.session.commit()

    if len(documentos_criados) == 1:
        flash('Documento enviado com sucesso!', 'success')
    else:
        flash(f'{len(documentos_criados)} documentos enviados com sucesso!', 'success')
    return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))


@bp.route('/animal/<int:animal_id>/documentos/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(animal_id, doc_id):
    documento = AnimalDocumento.query.filter_by(id=doc_id, animal_id=animal_id).first_or_404()

    if not (
        current_user.role == 'admin'
        or (
            can_act_as_veterinarian(current_user)
            and current_user.id == documento.veterinario_id
        )
    ):
        flash('Você não tem permissão para excluir este documento.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal_id))

    prefix = f"https://{BUCKET}.s3.amazonaws.com/"
    if documento.file_url and documento.file_url.startswith(prefix):
        key = documento.file_url[len(prefix):]
        try:
            _s3().delete_object(Bucket=BUCKET, Key=key)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception('Falha ao remover arquivo do S3: %s', exc)

    db.session.delete(documento)
    db.session.commit()

    flash('Documento excluído com sucesso!', 'success')
    return redirect(request.referrer or url_for('ficha_animal', animal_id=animal_id))


@bp.route('/animal/<int:animal_id>/editar_ficha', methods=['GET', 'POST'])
@login_required
def editar_ficha_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if getattr(current_user, 'worker', None) != 'veterinario' and current_user.role != 'admin':
        flash("Acesso restrito a veterinarios.", "danger")
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    # Dados fictícios para fins de edição simples (substituir por formulário real depois)
    if request.method == 'POST':
        nova_vacina = request.form.get("vacina")
        nova_consulta = request.form.get("consulta")
        novo_medicamento = request.form.get("medicamento")

        print(f"Vacina adicionada: {nova_vacina}")
        print(f"Consulta adicionada: {nova_consulta}")
        print(f"Medicação adicionada: {novo_medicamento}")

        flash("Informacoes adicionadas com sucesso.", "success")
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    return render_template("editar_ficha.html", animal=animal)


@bp.route('/generate_qr/<int:animal_id>')
@login_required
def generate_qr(animal_id):
    animal = get_animal_or_404(animal_id)
    if current_user.id != animal.user_id:
        flash('Você não tem permissão para gerar o QR code deste animal.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal_id))

    # Gera token
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(minutes=10)  # por exemplo, 10 minutos

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


@bp.route('/consulta_qr', methods=['GET'])
@login_required
def consulta_qr():
    animal_id = request.args.get('animal_id', type=int)
    token = request.args.get('token')  # se estiver usando QR com token

    # Aqui você já deve ter carregado o animal
    animal = get_animal_or_404(animal_id)
    clinica_id = current_user_clinic_id()
    is_active_vet = can_act_as_veterinarian(current_user)
    worker_role = 'veterinario' if is_active_vet else getattr(current_user, 'worker', None)

    # Idade e unidade (anos/meses)
    idade = ''
    idade_unidade = ''
    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            idade = delta.years
            idade_unidade = 'ano' if delta.years == 1 else 'anos'
        else:
            idade = delta.months
            idade_unidade = 'mês' if delta.months == 1 else 'meses'
    elif animal.age:
        partes = str(animal.age).split()
        try:
            idade = int(partes[0])
        except (ValueError, IndexError):
            idade = ''
        if len(partes) > 1:
            idade_unidade = partes[1]


    # Lógica adicional
    tutor = animal.owner
    consulta = (
        Consulta.query
        .filter_by(animal_id=animal.id, clinica_id=clinica_id)
        .order_by(Consulta.id.desc())
        .first()
    )
    tutor_form = EditProfileForm(obj=tutor)

    servicos = []
    if clinica_id:
        servicos = (
            ServicoClinica.query
            .filter_by(clinica_id=clinica_id)
            .order_by(ServicoClinica.descricao)
            .all()
        )

    plan_form = None
    active_plan_subscriptions = []
    authorization_summary = None
    if animal and is_active_vet and consulta:
        from models import HealthSubscription
        active_plan_subscriptions = (
            HealthSubscription.query
            .filter_by(animal_id=animal.id, active=True)
            .all()
        )
        plan_form = ConsultaPlanAuthorizationForm()
        plan_form.subscription_id.choices = [
            (s.id, f"{s.plan.name} – desde {s.start_date.date():%d/%m/%Y}")
            for s in active_plan_subscriptions
        ]
        if consulta.health_subscription_id:
            plan_form.subscription_id.data = consulta.health_subscription_id
        authorization_summary = {
            'status': consulta.authorization_status,
            'notes': consulta.authorization_notes,
            'checked_at': consulta.authorization_checked_at,
        }

    clinic_scope_id = clinica_id
    shared_access = _resolve_shared_access_for_animal(animal, viewer=current_user, clinic_scope=clinic_scope_id)
    blocos_orcamento = _clinic_orcamento_blocks(animal, clinic_scope_id)
    blocos_prescricao = _clinic_prescricao_blocks(animal, clinic_scope_id)

    return render_template(
        'consulta_qr.html',
        tutor=tutor,
        animal=animal,
        consulta=consulta,
        animal_idade=idade,
        animal_idade_unidade=idade_unidade,
        tutor_form=tutor_form,
        servicos=servicos,
        worker=worker_role,
        blocos_orcamento=blocos_orcamento,
        blocos_prescricao=blocos_prescricao,
        clinic_scope_id=clinic_scope_id,
        plan_form=plan_form,
        active_plan_subscriptions=active_plan_subscriptions,
        authorization_summary=authorization_summary,
        shared_access=shared_access,
        viewer_clinic_id=clinica_id,
    )


@bp.route('/buscar_tutores', methods=['GET'])
@login_required
def buscar_tutores():
    raw_query = request.args.get('q', '')
    query = raw_query.strip()

    if not query:
        return jsonify([])

    clinic_id = current_user_clinic_id()

    sort_param = (request.args.get('sort') or 'name_asc').strip().lower()
    allowed_sorts = {'name_asc', 'recent_added', 'recent_attended'}
    if sort_param not in allowed_sorts:
        sort_param = 'name_asc'

    like_query = f"%{query}%"
    numeric_query = re.sub(r'\D', '', query)
    numeric_like = f"%{numeric_query}%" if numeric_query else None

    def sanitize_expression(expr, characters):
        sanitized = expr
        for char in characters:
            sanitized = func.replace(sanitized, char, '')
        return sanitized

    text_columns = [
        User.name,
        User.email,
        User.worker,
        User.address,
        User.cpf,
        User.rg,
        User.phone,
        Endereco.cep,
        Endereco.rua,
        Endereco.numero,
        Endereco.complemento,
        Endereco.bairro,
        Endereco.cidade,
        Endereco.estado,
    ]

    digit_columns = [
        sanitize_expression(User.cpf, ['.', '-', '/', ' ']),
        sanitize_expression(User.rg, ['.', '-', '/', ' ']),
        sanitize_expression(User.phone, ['(', ')', '-', ' ']),
        sanitize_expression(Endereco.cep, ['-', ' ']),
    ]

    filters = [column.ilike(like_query) for column in text_columns]

    if numeric_like:
        filters.extend(column.ilike(numeric_like) for column in digit_columns)

    visibility_clause = _user_visibility_clause(clinic_scope=clinic_id)

    tutores_query = (
        User.query.outerjoin(Endereco)
        .options(
            joinedload(User.endereco),
            joinedload(User.veterinario).joinedload(Veterinario.specialties),
        )
        .filter(or_(*filters))
    )

    if not _is_admin():
        tutores_query = tutores_query.filter(User.clinica_id == clinic_id)

    tutores_query = tutores_query.filter(visibility_clause).distinct()

    order_columns = []
    last_appt_subquery = None

    if sort_param == 'recent_attended':
        last_appt_query = db.session.query(
            Appointment.tutor_id.label('tutor_id'),
            func.max(Appointment.scheduled_at).label('last_at'),
        )
        if clinic_id:
            last_appt_query = last_appt_query.filter(Appointment.clinica_id == clinic_id)
        last_appt_subquery = last_appt_query.group_by(Appointment.tutor_id).subquery()
        tutores_query = tutores_query.outerjoin(last_appt_subquery, User.id == last_appt_subquery.c.tutor_id)
        order_columns.append(func.coalesce(last_appt_subquery.c.last_at, User.created_at).desc())
        order_columns.append(func.lower(User.name))
    elif sort_param == 'recent_added':
        order_columns.append(User.created_at.desc())
        order_columns.append(func.lower(User.name))
    else:
        order_columns.append(func.lower(User.name))

    tutores = (
        tutores_query
        .order_by(*order_columns)
        .limit(TUTOR_SEARCH_LIMIT)
        .all()
    )

    resultados = []

    for tutor in tutores:
        address_summary = (
            tutor.address
            or (tutor.endereco.full if getattr(tutor, 'endereco', None) else '')
        )
        detalhes = [
            valor
            for valor in [
                None if getattr(tutor, 'email_is_placeholder', False) else tutor.email,
                tutor.phone,
                f"CPF: {tutor.cpf}" if tutor.cpf else '',
                f"RG: {tutor.rg}" if tutor.rg else '',
                tutor.worker,
            ]
            if valor
        ]

        resultados.append(
            {
                'id': tutor.id,
                'name': tutor.name,
                'email': None if getattr(tutor, 'email_is_placeholder', False) else tutor.email,
                'email_is_placeholder': bool(getattr(tutor, 'email_is_placeholder', False)),
                'cpf': tutor.cpf,
                'rg': tutor.rg,
                'phone': tutor.phone,
                'worker': tutor.worker,
                'address_summary': address_summary,
                'details': ' • '.join(detalhes),
                'specialties': ', '.join(
                    s.nome for s in tutor.veterinario.specialties
                )
                if getattr(tutor, 'veterinario', None)
                else '',
            }
        )

    return jsonify(resultados)


@bp.route('/tutor/<int:tutor_id>')
@login_required
def obter_tutor(tutor_id):
    tutor = get_user_or_404(tutor_id)
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


@bp.route('/tutor/<int:tutor_id>')
@login_required
def tutor_detail(tutor_id):
    tutor   = get_user_or_404(tutor_id)
    animais = tutor.animais.order_by(Animal.name).all()
    return render_template('animais/tutor_detail.html', tutor=tutor, animais=animais)


def _find_user_by_cpf(cpf: str | None, *, exclude_id: int | None = None) -> User | None:
    """Localiza um tutor pelo CPF ignorando a máscara.

    O mesmo documento aparece como ``123.456.789-00`` e ``12345678900`` conforme
    a tela que cadastrou. Comparar a string crua deixava passar a duplicata, que
    só estourava no commit como IntegrityError.
    """
    digits = re.sub(r'\D', '', cpf or '')
    if not digits:
        return None
    normalized_column = User.cpf
    for char in ('.', '-', '/', ' '):
        normalized_column = func.replace(normalized_column, char, '')
    query = User.query.filter(normalized_column == digits)
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    return query.first()


_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _cadastro_em_conflito(existing: User) -> str:
    """Quem já usa o dado, para a equipe abrir o cadastro certo.

    Só identifica a pessoa quando quem está editando já pode ver esse
    cadastro; fora disso o nome de um tutor de outra clínica vazaria aqui.
    """
    try:
        get_user_or_404(existing.id)
    except Exception:
        return ''
    return f'{existing.name} (cadastro nº {existing.id})'


_PAPEIS_SEM_UNIFICACAO = {'admin', 'veterinario'}


def _pode_unificar_tutores(origem: User, destino: User) -> bool:
    """Quem pode juntar ``origem`` (que deixa de existir) em ``destino``.

    Mesma regra de excluir tutor, porque o cadastro de origem é apagado ao
    final: veterinário, e só o admin ou quem cadastrou a origem. O destino
    precisa estar visível para quem pede ou ser uma conta que a própria
    pessoa criou e que nenhuma clínica acompanha (o caso real: ela se
    cadastrou com o e-mail certo). Contas de equipe (admin, veterinário,
    colaborador, dono de clínica) e a própria conta de quem pede ficam de
    fora: a unificação é para o mesmo tutor cadastrado duas vezes.
    """
    if origem is None or destino is None or origem.id == destino.id:
        return False
    if not can_act_as_veterinarian(current_user):
        return False
    if current_user.role != 'admin' and origem.added_by_id != current_user.id:
        return False
    for conta in (origem, destino):
        if conta.id == current_user.id:
            return False
        if (conta.role or '') in _PAPEIS_SEM_UNIFICACAO:
            return False
        if conta.worker or conta.veterinario is not None:
            return False
        if getattr(conta, 'clinicas', None):
            return False
    return _destino_visivel(destino) or _conta_propria_sem_clinica(destino)


def _destino_visivel(destino: User) -> bool:
    try:
        get_user_or_404(destino.id)
    except Exception:
        return False
    return True


def _conta_propria_sem_clinica(conta: User) -> bool:
    """Conta criada pela própria pessoa, sem clínica nem quem a cadastrou.

    Nenhuma clínica enxerga essa conta, por isso ela não passaria pela regra
    de visibilidade; mas é justamente onde a pessoa entra com o e-mail certo.
    """
    return conta.clinica_id is None and conta.added_by_id is None


def _oferta_unificacao(origem: User, destino: User):
    """Dados para a tela oferecer a unificação no lugar do simples erro."""
    if not _pode_unificar_tutores(origem, destino):
        return None
    visivel = _destino_visivel(destino)
    return {
        'source_id': origem.id,
        'target_id': destino.id,
        # Conta que a clínica ainda não enxerga: nada dela é exposto antes da
        # unificação, nem o nome nem quantos animais tem.
        'target_name': destino.name if visivel else None,
        'target_visible': visivel,
        'source_animals': Animal.query.filter_by(user_id=origem.id).count(),
        'target_animals': Animal.query.filter_by(user_id=destino.id).count() if visivel else None,
        'email': (destino.email or '').strip().lower(),
        'url': url_for('unificar_tutor', source_id=origem.id),
    }


@bp.route('/tutores', methods=['GET', 'POST'])
@login_required
def tutores():
    # Restrição de acesso
    if not has_professional_access(current_user):
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    clinic_id = current_user_clinic_id()
    accessible_clinic_ids = _viewer_accessible_clinic_ids(current_user)
    clinic_scope = (
        accessible_clinic_ids
        if len(accessible_clinic_ids) > 1
        else accessible_clinic_ids[0]
        if accessible_clinic_ids
        else None
    )
    vet_profile = getattr(current_user, 'veterinario', None)
    require_appointments = _is_specialist_veterinarian(vet_profile)
    veterinarian_scope_id = vet_profile.id if require_appointments and vet_profile else None
    scope = request.args.get('scope', 'all')
    page = request.args.get('page', 1, type=int)
    effective_user_id = getattr(current_user, 'id', None)

    # Criação de novo tutor
    if request.method == 'POST':
        wants_json = 'application/json' in request.headers.get('Accept', '')
        name = (request.form.get('tutor_name') or request.form.get('name') or '').strip()
        email = (request.form.get('tutor_email') or request.form.get('email') or '').strip().lower()
        email_is_placeholder = not email

        if not name:
            message = 'Informe o nome do tutor.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning'), 400
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        if email_is_placeholder:
            email = build_placeholder_email()
        # Comparação sem caixa: contas antigas foram gravadas com a caixa que o
        # usuário digitou, então filter_by(email=...) deixava passar duplicatas
        # que só diferem em maiúsculas.
        if User.query.filter(func.lower(User.email) == email.lower()).first():
            message = 'Já existe um tutor com esse e‑mail.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning'), 409
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        cpf = (request.form.get('tutor_cpf') or request.form.get('cpf') or '').strip() or None
        if cpf and _find_user_by_cpf(cpf):
            message = 'CPF já cadastrado para outro tutor.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning'), 409
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        novo = User(
            name=name,
            email=email,
            email_is_placeholder=email_is_placeholder,
            role='adotante',  # padrão inicial
            clinica_id=current_user_clinic_id(),
            added_by=current_user,
            is_private=True,
        )
        novo.set_password(secrets.token_urlsafe(32))

        # Campos opcionais
        novo.phone = normalize_phone(request.form.get('tutor_phone') or request.form.get('phone')) or None
        novo.cpf = normalize_cpf(cpf) or None
        novo.rg = (request.form.get('tutor_rg') or request.form.get('rg') or '').strip() or None
        novo.address = None

        # Data de nascimento
        date_str = request.form.get('tutor_date_of_birth') or request.form.get('date_of_birth')
        if date_str:
            try:
                novo.date_of_birth = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
            except ValueError:
                message = 'Data de nascimento inválida. Use o formato AAAA-MM-DD.'
                if wants_json:
                    return jsonify(success=False, message=message, category='danger')
                flash(message, 'danger')
                return redirect(url_for('tutores'))

        # Endereço
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')

        has_address = any((value or '').strip() for value in (cep, rua, numero, complemento, bairro, cidade, estado))
        required_address_labels = {
            'rua': 'Rua',
            'cidade': 'Cidade',
            'estado': 'Estado',
        }

        required_missing = [
            label for key, label in required_address_labels.items()
            if not (request.form.get(key) or '').strip()
        ]

        if has_address and required_missing:
            message = 'Preencha os campos obrigatórios do endereço: ' + ', '.join(required_missing) + '.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning'), 400
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        if has_address:
            endereco = Endereco(
                cep=cep, rua=rua, numero=numero, complemento=complemento,
                bairro=bairro, cidade=cidade, estado=estado,
            )
            cep_digits = ''.join(char for char in (cep or '') if char.isdigit())
            has_complete_cep = len(cep_digits) == 8 and cep_digits != '00000000'
            if not _update_coordinates_from_request(endereco) and has_complete_cep:
                _geocode_endereco(endereco)
            db.session.add(endereco)
            db.session.flush()
            novo.endereco_id = endereco.id

        # Foto
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            filename = secure_filename(file.filename)
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            novo.profile_photo = f"/static/uploads/{filename}"

        db.session.add(novo)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Erro ao cadastrar tutor')
            message = 'Não foi possível cadastrar o tutor. Revise os dados e tente novamente.'
            if wants_json:
                return jsonify(success=False, message=message, category='danger'), 500
            flash(message, 'danger')
            return redirect(url_for('tutores'))

        # Mesmo critério dos ramos de erro acima. ``accept_mimetypes.accept_json``
        # é verdadeiro para o ``*/*`` que todo navegador manda, então o submit
        # normal (sem fetch) recebia o JSON cru na tela em vez do redirect.
        if wants_json:
            scope = request.args.get('scope', 'all')
            page = request.args.get('page', 1, type=int)
            tutor_search = (request.args.get('tutor_search', '', type=str) or '').strip()
            tutor_sort = (request.args.get('tutor_sort', 'name_asc', type=str) or 'name_asc').strip()
            tutores_adicionados, pagination, resolved_scope = _get_recent_tutores(
                scope,
                page,
                clinic_id=clinic_scope,
                user_id=effective_user_id,
                require_appointments=require_appointments,
                veterinario_id=veterinarian_scope_id,
                search=tutor_search,
                sort_option=tutor_sort,
            )
            html = render_template(
                'partials/tutores_adicionados.html',
                tutores_adicionados=tutores_adicionados,
                pagination=pagination,
                scope=resolved_scope,
                scope_param=request.args.get('scope_param', 'scope'),
                search_param='tutor_search',
                sort_param='tutor_sort',
                page_param=request.args.get('page_param', 'page'),
                fetch_url=url_for('tutores'),
                compact=True,
            )
            return jsonify(
                success=True,
                message='Tutor criado com sucesso!',
                category='success',
                html=html,
                tutor={
                    'id': novo.id,
                    'name': novo.name or f'Tutor #{novo.id}',
                    'display_name': novo.name or f'Tutor #{novo.id}',
                    'email': None if novo.email_is_placeholder else novo.email,
                    'email_is_placeholder': bool(novo.email_is_placeholder),
                    'phone': novo.phone,
                    'cpf': novo.cpf,
                    'profile_photo': novo.profile_photo,
                    'photo_offset_x': novo.photo_offset_x,
                    'photo_offset_y': novo.photo_offset_y,
                    'photo_rotation': novo.photo_rotation,
                    'photo_zoom': novo.photo_zoom,
                    'date_of_birth': novo.date_of_birth.isoformat() if novo.date_of_birth else None,
                    'created_at': novo.created_at.isoformat() if novo.created_at else None,
                    'worker': novo.worker,
                    'detail_url': url_for('ficha_tutor', tutor_id=novo.id),
                },
                redirect_url=url_for('ficha_tutor', tutor_id=novo.id),
            )

        flash('Tutor criado com sucesso!', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=novo.id))

    # — GET com paginação —
    tutor_search = (request.args.get('tutor_search', '', type=str) or '').strip()
    tutor_sort = (request.args.get('tutor_sort', 'name_asc', type=str) or 'name_asc').strip()
    wants_listing_payload = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (
        request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
    )
    active_record_panel = _resolve_record_panel(
        request.args,
        listing_params=('scope', 'tutor_search', 'tutor_sort', 'page'),
        default='list',
    )
    defer_tutor_listing = active_record_panel != 'list' and not wants_listing_payload

    if defer_tutor_listing:
        tutores_adicionados = []
        pagination = None
        resolved_scope = scope
        shared_access_map = {}
    else:
        tutores_adicionados, pagination, resolved_scope = _get_recent_tutores(
            scope,
            page,
            clinic_id=clinic_scope,
            user_id=effective_user_id,
            require_appointments=require_appointments,
            veterinario_id=veterinarian_scope_id,
            search=tutor_search,
            sort_option=tutor_sort,
        )
        shared_access_map = {
            t.id: _resolve_shared_access_for_user(t, viewer=current_user, clinic_scope=clinic_scope)
            for t in tutores_adicionados
        }

    if wants_listing_payload:
        html = render_template(
            'partials/tutores_adicionados.html',
            tutores_adicionados=tutores_adicionados,
            pagination=pagination,
            scope=resolved_scope,
            scope_param=request.args.get('scope_param', 'scope'),
            search_param='tutor_search',
            sort_param='tutor_sort',
            page_param=request.args.get('page_param', 'page'),
            fetch_url=url_for('tutores'),
            compact=True,
            shared_access_map=shared_access_map,
            viewer_clinic_id=clinic_id,
        )
        return jsonify(html=html, scope=resolved_scope)

    tutor_listing_args = {'scope': scope}
    if tutor_search:
        tutor_listing_args['tutor_search'] = tutor_search
    if tutor_sort:
        tutor_listing_args['tutor_sort'] = tutor_sort
    if page > 1:
        tutor_listing_args['page'] = page

    return render_template(
        'animais/tutores.html',
        tutores_adicionados=tutores_adicionados,
        pagination=pagination,
        scope=resolved_scope,
        tutor_search=tutor_search,
        tutor_sort=tutor_sort,
        viewer_clinic_id=clinic_id,
        shared_access_map=shared_access_map,
        active_record_panel=active_record_panel,
        defer_tutor_listing=defer_tutor_listing,
        tutor_listing_fetch_url=url_for('tutores', **tutor_listing_args),
    )


@bp.route('/tutor/compartilhamentos')
@login_required
def tutor_sharing_dashboard():
    if not _is_tutor_portal_user(current_user):
        abort(403)
    payload = _serialize_tutor_share_payload(current_user)
    token = request.args.get('token')
    token_request = None
    if token:
        share_request = DataShareRequest.query.filter_by(token=token).first()
        if share_request and share_request.tutor_id == current_user.id:
            token_request = _serialize_share_request(share_request)
        else:
            flash('Pedido não encontrado ou expirado.', 'warning')
    return render_template(
        'tutor/sharing_dashboard.html',
        share_payload=payload,
        share_api=url_for('shares_api'),
        pending_token=token,
        token_request=token_request,
    )


@bp.route('/deletar_tutor/<int:tutor_id>', methods=['POST'])
@login_required
def deletar_tutor(tutor_id):
    tutor = get_user_or_404(tutor_id)

    if not can_act_as_veterinarian(current_user):
        flash(veterinarian_denial_message('Apenas veterinários podem excluir tutores.'), 'danger')
        return redirect(url_for('index'))

    if current_user.role != 'admin' and tutor.added_by_id != current_user.id:
        message = 'Você não tem permissão para excluir este tutor.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='danger'), 403
        flash(message, 'danger')
        abort(403)

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
        current_app.logger.exception('Erro ao excluir tutor %s', tutor_id)
        flash('Não foi possível excluir o tutor. Tente novamente mais tarde.', 'danger')

    return redirect(url_for('tutores'))


@bp.route('/tutor/<int:source_id>/unificar', methods=['POST'])
@login_required
def unificar_tutor(source_id):
    """Junta o cadastro ``source_id`` no cadastro informado em ``target_id``.

    Tudo o que aponta para a origem (animais, consultas, vacinas, mensagens...)
    passa para o destino, que mantém e-mail, senha e dados próprios e herda o
    que estiver em branco. A origem, já sem vínculos, é apagada; a ficha do
    destino registra de onde vieram os dados.
    """
    wants_json = 'application/json' in request.headers.get('Accept', '')

    def _responder(message, status, category, **extra):
        if wants_json:
            return jsonify(success=status < 400, message=message, category=category, **extra), status
        flash(message, category)
        if status < 400 and extra.get('redirect'):
            return redirect(extra['redirect'])
        return redirect(request.referrer or url_for('tutores'))

    origem = get_user_or_404(source_id)
    target_id = request.form.get('target_id', type=int)
    destino = db.session.get(User, target_id) if target_id else None
    if destino is None:
        return _responder('Cadastro de destino não encontrado.', 404, 'danger')
    if not _pode_unificar_tutores(origem, destino):
        return _responder('Você não tem permissão para unificar estes cadastros.', 403, 'danger')
    if not _destino_visivel(destino):
        # Conta que a clínica não enxerga: só quem digitou o e-mail dela na
        # ficha chega aqui; o número do cadastro sozinho não basta.
        email = (request.form.get('email') or '').strip().lower()
        if not email or email != (destino.email or '').strip().lower():
            return _responder('Você não tem permissão para unificar estes cadastros.', 403, 'danger')

    from services.tutor_merge import merge_accounts

    origem_nome = origem.name
    destino_id, destino_nome = destino.id, destino.name
    animais = Animal.query.filter_by(user_id=origem.id).count()
    try:
        resultado = merge_accounts(
            source_id=origem.id,
            target_id=destino_id,
            delete_source=True,
            extra_inherit_fields=('clinica_id', 'added_by_id'),
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Erro ao unificar tutor %s em %s', source_id, target_id)
        return _responder('Não foi possível unificar os cadastros. Nada foi alterado.', 500, 'danger')
    if resultado != 0:
        db.session.rollback()
        return _responder('Não foi possível unificar os cadastros. Nada foi alterado.', 400, 'danger')

    destino_url = url_for('ficha_tutor', tutor_id=destino_id)
    plural = 'animal' if animais == 1 else 'animais'
    message = (
        f'Cadastros unificados: {animais} {plural} e o histórico de {origem_nome} '
        f'agora estão no cadastro de {destino_nome} (nº {destino_id}).'
    )
    return _responder(message, 200, 'success', redirect=destino_url, target_id=destino_id)


@bp.route('/buscar_animais')
@login_required
def buscar_animais():
    term = (request.args.get('q', '') or '').strip()
    clinic_id = current_user_clinic_id()
    is_admin = _is_admin()

    if not is_admin and not clinic_id:
        return jsonify([])

    visibility_clause = _user_visibility_clause(clinic_scope=clinic_id)
    sort = request.args.get('sort')
    tutor_id = request.args.get('tutor_id', type=int)

    results = search_animals(
        term=term,
        clinic_scope=clinic_id,
        is_admin=is_admin,
        visibility_clause=visibility_clause,
        sort=sort,
        tutor_id=tutor_id,
    )

    return jsonify(results)


@bp.route('/update_tutor/<int:user_id>', methods=['POST'])
@login_required
def update_tutor(user_id):
    user = get_user_or_404(user_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    # 🔐 Permissão: veterinários ou colaboradores
    if not has_professional_access(current_user):
        message = 'Apenas veterinários ou colaboradores podem editar dados do tutor.'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    def _recusar(message, status=400, category='warning'):
        if wants_json:
            return jsonify(success=False, message=message, category=category), status
        flash(message, category)
        return redirect(request.referrer or url_for('index'))

    # E-mail, telefone e CPF são conferidos ANTES de qualquer alteração no
    # objeto: uma consulta com o cadastro já modificado dispara o autoflush, e
    # a duplicata estourava ali como IntegrityError (erro 500 "Unexpected
    # error") em vez de virar um aviso para quem está digitando.
    #
    # Cada um só é validado quando o valor realmente mudou. O banco guarda o
    # mesmo dado com e sem máscara, com e sem +55; reenviar o que já está
    # gravado nunca pode impedir o salvamento dos outros campos.
    email = (request.form.get('email') or '').strip().lower()
    email_changed = bool(email) and email != (user.email or '').strip().lower()
    if email_changed:
        if not _EMAIL_RE.match(email):
            return _recusar('Informe um e-mail válido, como nome@exemplo.com.')
        existing = User.query.filter(
            func.lower(User.email) == email, User.id != user.id
        ).first()
        if existing:
            quem = _cadastro_em_conflito(existing)
            message = (
                f'Este e-mail já está no cadastro de {quem}. '
                'Use esse cadastro ou informe outro e-mail.'
                if quem else
                'Este e-mail já está em uso por outro cadastro.'
            )
            oferta = _oferta_unificacao(user, existing) if wants_json else None
            if oferta:
                # Caso típico: a clínica cadastrou com e-mail errado e a pessoa
                # criou a própria conta com o certo. Em vez de só barrar, a
                # tela oferece juntar os dois cadastros (ver unificar_tutor).
                return jsonify(
                    success=False, message=message, category='warning',
                    merge_offer=oferta,
                ), 409
            return _recusar(message, 409)

    phone = (request.form.get('phone') or '').strip()
    phone_changed = bool(phone) and not same_phone(phone, user.phone)
    if phone_changed and not is_valid_phone(phone):
        return _recusar('Informe o telefone com DDD (10 ou 11 dígitos).')

    cpf = (request.form.get('cpf') or '').strip()
    cpf_changed = bool(cpf) and not same_cpf(cpf, user.cpf)
    if cpf_changed:
        if not is_valid_cpf_length(cpf):
            return _recusar('Informe o CPF com 11 dígitos.')
        existing = _find_user_by_cpf(cpf, exclude_id=user.id)
        if existing:
            quem = _cadastro_em_conflito(existing)
            message = 'CPF já cadastrado para outro tutor'
            message += f': {quem}.' if quem else '.'
            return _recusar(message, 409, 'danger')

    # 📋 Campos básicos
    for field in ['name', 'rg']:
        value = (request.form.get(field) or '').strip()
        if value:
            setattr(user, field, value)
    if email_changed:
        user.email = email
        user.email_is_placeholder = is_placeholder_email(email)
    if phone_changed:
        user.phone = normalize_phone(phone)
    if cpf_changed:
        user.cpf = normalize_cpf(cpf)

    # Observações: diferente dos campos acima, aceita ficar vazio — é assim que
    # a clínica apaga uma anotação que não vale mais.
    if 'observacoes' in request.form:
        user.observacoes = (request.form.get('observacoes') or '').strip() or None

    # 📅 Data de nascimento
    date_str = request.form.get('date_of_birth')
    if date_str:
        try:
            user.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            message = 'Data de nascimento inválida. Use o formato correto.'
            if wants_json:
                return jsonify(success=False, message=message, category='danger'), 400
            flash(message, 'danger')
            return redirect(request.referrer or url_for('index'))

    # 📸 Foto de perfil
    photo = request.files.get('profile_photo')
    if photo and photo.filename:
        filename = f"{uuid.uuid4().hex}_{secure_filename(photo.filename)}"
        # Upload sincronamente para garantir a atualização imediata
        image_url = upload_to_s3(photo, filename, folder="tutors")
        if image_url:
            user.profile_photo = image_url

    # Controles de corte da foto
    try:
        user.photo_rotation = int(request.form.get('photo_rotation', user.photo_rotation or 0))
    except ValueError:
        pass
    try:
        user.photo_zoom = float(request.form.get('photo_zoom', user.photo_zoom or 1.0))
    except ValueError:
        pass
    try:
        user.photo_offset_x = float(request.form.get('photo_offset_x', user.photo_offset_x or 0))
    except ValueError:
        pass
    try:
        user.photo_offset_y = float(request.form.get('photo_offset_y', user.photo_offset_y or 0))
    except ValueError:
        pass

    # 📍 Endereço
    addr_fields = {
        k: request.form.get(k) or None
        for k in ['cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado']
    }
    required_address_labels = {
        'cep': 'CEP',
        'rua': 'Rua',
        'cidade': 'Cidade',
        'estado': 'Estado',
    }

    missing_required = [
        label for key, label in required_address_labels.items()
        if not (addr_fields.get(key) or '').strip()
    ]

    if missing_required:
        message = 'Preencha os campos obrigatórios do endereço: ' + ', '.join(missing_required) + '.'
        if wants_json:
            return jsonify(success=False, message=message, category='warning'), 400
        flash(message, 'warning')
        return redirect(request.referrer or url_for('index'))

    endereco = user.endereco or Endereco()
    for k, v in addr_fields.items():
        setattr(endereco, k, v)
    if not user.endereco_id:
        db.session.add(endereco)
        db.session.flush()
        user.endereco_id = endereco.id

    if not _update_coordinates_from_request(endereco):
        _geocode_endereco(endereco)

    # 💾 Commit final
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Falha ao salvar tutor %s", user.id)
        message = 'Não foi possível salvar os dados do tutor. Tente novamente.'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 500
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    message = 'Dados do tutor atualizados com sucesso!'
    if wants_json:
        tutor_payload = {
            'id': user.id,
            'name': user.name,
            'profile_photo': user.profile_photo,
            'photo_offset_x': user.photo_offset_x,
            'photo_offset_y': user.photo_offset_y,
            'photo_rotation': user.photo_rotation,
            'photo_zoom': user.photo_zoom,
        }
        return jsonify(
            success=True,
            message=message,
            tutor_name=user.name,
            tutor=tutor_payload,
            category='success'
        )
    flash(message, 'success')
    return redirect(request.referrer or url_for('index'))


def _contatos_do_tutor(tutor):
    """Atalhos de contato da ficha do tutor: WhatsApp, ligação, mapa e e-mail.

    Tudo calculado aqui (e não no template) para a tela nunca montar um link
    quebrado: sem telefone brasileiro válido não há botão de WhatsApp, sem rua
    não há mapa (o mapa só da cidade não ajuda a chegar na casa).
    """
    from template_filters import whatsapp_chat_url

    bruto = (tutor.phone or '').strip()
    nacional = phone_national_digits(bruto)
    telefone = format_phone_br(bruto) if bruto else ''
    whatsapp_url = whatsapp_chat_url(nacional) if nacional else None
    if nacional:
        ligar_url = f'tel:+55{nacional}'
    else:
        discavel = re.sub(r'[^\d+]', '', bruto)
        ligar_url = f'tel:{discavel}' if len(re.sub(r'\D', '', discavel)) >= 8 else None

    linha1 = linha2 = busca = ''
    endereco = tutor.endereco
    if endereco is not None and (endereco.rua or '').strip():
        def _t(valor):
            return (valor or '').strip()

        rua_numero = ', '.join(p for p in (_t(endereco.rua), _t(endereco.numero)) if p)
        linha1 = rua_numero
        if _t(endereco.complemento):
            linha1 = f'{linha1} – {_t(endereco.complemento)}'
        cidade_uf = '/'.join(p for p in (_t(endereco.cidade), _t(endereco.estado)) if p)
        linha2 = ' · '.join(p for p in (_t(endereco.bairro), cidade_uf, _t(endereco.cep)) if p)
        busca = ', '.join(
            p for p in (
                rua_numero,
                _t(endereco.bairro),
                ' - '.join(p for p in (_t(endereco.cidade), _t(endereco.estado)) if p),
                _t(endereco.cep),
            ) if p
        )
    elif (tutor.address or '').strip():
        linha1 = busca = tutor.address.strip()

    mapa_url = f'https://www.google.com/maps/search/?api=1&query={quote(busca)}' if busca else None

    email = (getattr(tutor, 'email_informado', None) or '').strip()
    return {
        'telefone': telefone,
        'whatsapp_url': whatsapp_url,
        'ligar_url': ligar_url,
        'endereco_linha1': linha1,
        'endereco_linha2': linha2,
        'mapa_url': mapa_url,
        'email': email,
        'email_url': f'mailto:{email}' if email else None,
    }


def _idade_exibicao(animal):
    """Idade atual a partir do nascimento; senão, o texto salvo no cadastro."""
    nascimento = animal.date_of_birth
    if nascimento:
        delta = relativedelta(date.today(), nascimento)
        if delta.years >= 1:
            return f"{delta.years} {'ano' if delta.years == 1 else 'anos'}"
        if delta.months >= 1:
            return f"{delta.months} {'mês' if delta.months == 1 else 'meses'}"
        return 'menos de 1 mês'
    texto = (animal.age or '').strip()
    return texto or None


def _peso_exibicao(peso):
    try:
        valor = float(peso)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(valor) or valor <= 0:
        return None
    texto = f'{valor:.2f}' if valor < 1 else f'{valor:.1f}'
    texto = texto.rstrip('0').rstrip('.')
    return f"{texto.replace('.', ',')} kg"


def _animais_da_ficha(tutor):
    """Animais do tutor para a ficha: com nome primeiro, em ordem alfabética.

    O ``ORDER BY name`` simples punha o cadastro sem nome no topo (SQLite) ou
    no fim (Postgres) conforme o banco; aqui a ordem é a mesma em qualquer um.
    """
    return (
        Animal.query.options(joinedload(Animal.species), joinedload(Animal.breed))
        .filter_by(user_id=tutor.id)
        .order_by(Animal.name.is_(None), func.lower(Animal.name), Animal.id)
        .all()
    )


def _contexto_lista_animais(animais):
    """Variáveis que a lista de animais da ficha usa (página e parcial)."""
    return {
        'animais': animais,
        'detalhes_animais': {
            a.id: {'idade': _idade_exibicao(a), 'peso': _peso_exibicao(a.peso)}
            for a in animais
        },
        'can_consult': has_professional_access(current_user),
    }


def check_ficha_tutor_access():
    """Quem abre a ficha do tutor: profissionais clínicos ou donos de casa de ração."""
    is_store_owner = CasaDeRacao.query.filter_by(owner_id=current_user.id).first() is not None
    return has_professional_access(current_user) or is_store_owner


def check_animal_removal_permission(animal):
    """Mesma regra de deletar_animal: admin, o próprio tutor ou quem cadastrou."""
    return bool(
        current_user.role == 'admin'
        or animal.user_id == current_user.id
        or animal.added_by_id == current_user.id
    )


def _chave_ordenacao_raca(opcao):
    nome = unicodedata.normalize('NFKD', (opcao.get('name') or '').strip()).encode('ascii', 'ignore').decode()
    return (nome.upper() != 'SRD', nome.lower())


@bp.route('/ficha_tutor/<int:tutor_id>')
@login_required
def ficha_tutor(tutor_id):
    # Restrição de acesso — profissionais clínicos OU donos de casa de ração
    if not check_ficha_tutor_access():
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    # Dados do tutor
    tutor = get_user_or_404(tutor_id)

    # Lista de animais do tutor (com species e breed carregados)
    animais = _animais_da_ficha(tutor)

    # Ano atual
    current_year = datetime.now(BR_TZ).year

    # Formulários para usar o photo_cropper no template
    tutor_form = EditProfileForm(obj=tutor)
    animal_forms = {}
    for a in animais:
        form_obj = AnimalForm(obj=a)
        _preencher_idade_form(form_obj, a)
        animal_forms[a.id] = form_obj
    new_animal_form = AnimalForm()
    _preencher_idade_form(new_animal_form)

    # Busca todas as espécies e raças
    species_list = list_species()
    breeds = Breed.query.options(joinedload(Breed.species)).all()

    # Mapeia raças por species_id (como string, para uso seguro no JS)
    breed_map = {}
    for breed in breeds:
        sp_id = str(breed.species.id)
        breed_map.setdefault(sp_id, []).append({
            'id': breed.id,
            'name': breed.name
        })

    # "SRD" é uma raça única no banco (não duplicada por espécie), mas deve
    # ficar disponível na lista de qualquer espécie no formulário.
    srd_entries = [b for b in breeds if (b.name or '').strip().upper() == 'SRD']
    for srd in srd_entries:
        for sp in species_list:
            sp_id = str(sp['id'])
            options = breed_map.setdefault(sp_id, [])
            if not any(opt['id'] == srd.id for opt in options):
                options.append({'id': srd.id, 'name': srd.name})

    # SRD primeiro e o resto em ordem alfabética: é o que mais se escolhe.
    for options in breed_map.values():
        options.sort(key=_chave_ordenacao_raca)

    editar_id = request.args.get('editar', type=int)

    return render_template(
        'animais/tutor_detail.html',
        tutor=tutor,
        endereco=tutor.endereco,
        contatos=_contatos_do_tutor(tutor),
        current_year=current_year,
        species_list=species_list,
        breed_map=breed_map,
        tutor_form=tutor_form,
        animal_forms=animal_forms,
        new_animal_form=new_animal_form,
        editar_animal_id=editar_id if editar_id in animal_forms else None,
        **_contexto_lista_animais(animais),
    )


@bp.route('/ficha_tutor/<int:tutor_id>/animais')
@login_required
def ficha_tutor_animais(tutor_id):
    """Só a lista de animais da ficha, para a tela se atualizar sem recarregar."""
    if not check_ficha_tutor_access():
        return jsonify(success=False, message='Apenas veterinários ou colaboradores podem acessar esta página.'), 403
    tutor = get_user_or_404(tutor_id)
    animais = _animais_da_ficha(tutor)
    contexto = _contexto_lista_animais(animais)
    html = render_template('animais/_tutor_animais_lista.html', tutor=tutor, **contexto)
    response = jsonify(
        success=True,
        html=html,
        ativos=sum(1 for a in animais if not a.removido_em),
        removidos=sum(1 for a in animais if a.removido_em),
    )
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/animal/<int:animal_id>/restaurar', methods=['POST'])
@login_required
def restaurar_animal(animal_id):
    """Desfaz a remoção (que só marca ``removido_em``; o histórico ficou)."""
    animal = get_animal_or_404(animal_id)
    wants_json = _cliente_quer_json()
    # Mesma regra de quem pode remover (deletar_animal).
    if not check_animal_removal_permission(animal):
        message = 'Você não tem permissão para restaurar este animal.'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        flash(message, 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    nome = animal.name or 'Animal'
    if animal.removido_em is None:
        message = f'{nome} já está na lista de animais.'
    else:
        animal.removido_em = None
        db.session.commit()
        message = f'{nome} voltou para a lista de animais.'
    if wants_json:
        return jsonify(success=True, message=message, category='success', animal=_animal_payload(animal))
    flash(message, 'success')
    return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))


# ── Cadastro de animal: entrada tolerante e foto padronizada ──────────────────
#
# Usado por update_animal e novo_animal. O celular manda peso com vírgula,
# selects com opção "—" vazia e fotos HEIC de 12 MP; nada disso pode virar
# erro 500 nem apagar o que já estava salvo.

PESO_ANIMAL_MAXIMO_KG = 2000  # equinos registrados (selo da Prefeitura) passam de 500 kg


def _cliente_quer_json():
    return (
        'application/json' in (request.headers.get('Accept') or '')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )


def _peso_do_formulario(valor):
    """'12,5', '12.5' ou ' 12 ' -> 12.5; vazio -> None; inválido -> ValueError."""
    texto = (valor or '').strip().replace(' ', '').replace(',', '.')
    if not texto:
        return None
    peso = float(texto)
    if not math.isfinite(peso) or peso <= 0 or peso > PESO_ANIMAL_MAXIMO_KG:
        raise ValueError(texto)
    return round(peso, 3)


def _castrado_do_formulario(valor):
    """'1' -> True, '0' -> False, '' (opção "—") -> None (não informado)."""
    if valor == '1':
        return True
    if valor == '0':
        return False
    return None


def _texto_opcional(valor):
    texto = (valor or '').strip()
    return texto or None


def _guardar_foto_animal(arquivo, rotacao=0):
    """Padroniza a foto (HEIC, tamanho), grava o giro nos pixels e guarda.

    Devolve ``(url, giro_aplicado)``. Levanta ``PhotoIntakeError`` (foto
    ilegível) ou ``PhotoStorageError`` (armazenamento indisponível), ambos com
    mensagem pronta para a tela. Nunca devolve ``None``: antes, uma falha no S3
    virava ``animal.image = None`` e a foto anterior sumia.
    """
    foto = normalize_photo_upload(arquivo.read())
    girada = rotate_photo(foto, rotacao)
    nome = f"{uuid.uuid4().hex}_{secure_filename(normalized_filename(arquivo.filename or 'foto', girada))}"
    if not (current_app.config.get('ALLOW_LOCAL_UPLOAD_FALLBACK') or current_app.config.get('TESTING')):
        url = store_photo(girada.stream, nome, folder='animals', uploader=upload_to_s3)
        return url, girada is not foto
    # Desenvolvimento/testes: o fallback local (static/uploads) continua
    # valendo, como antes. Em produção store_photo recusa URL que não seja
    # http (arquivo local some no próximo restart do Heroku).
    try:
        url = upload_to_s3(girada.stream, nome, folder='animals')
    except Exception as exc:  # noqa: BLE001 - vira mensagem para a tela
        raise PhotoStorageError(
            code='desconhecido',
            user_message=MENSAGEM_FOTO_NAO_GUARDADA,
            retryable=True,
            detail=str(exc),
        ) from exc
    if not url:
        raise PhotoStorageError(
            code='sem-bucket',
            user_message=MENSAGEM_FOTO_NAO_GUARDADA,
            retryable=True,
            detail='upload_to_s3 devolveu None',
        )
    return url, girada is not foto


ENVIOS_ANIMAL_NA_SESSAO = 'animais_por_envio'


def _animal_do_envio(envio_id, tutor_id):
    """Animal já criado por este mesmo envio (reenvio após a resposta se perder).

    O modal da ficha gera um ``envio_id`` por animal. Se a conexão cai depois
    que o servidor salvou, a pessoa toca em "Salvar" de novo com o mesmo id:
    devolvemos o animal que já existe em vez de duplicar ou acusar erro. A
    sessão fica no servidor (Redis/arquivo), então o registro sobrevive mesmo
    quando a resposta não chegou ao celular.
    """
    if not envio_id:
        return None
    animal_id = (session.get(ENVIOS_ANIMAL_NA_SESSAO) or {}).get(envio_id)
    if not animal_id:
        return None
    animal = db.session.get(Animal, animal_id)
    if animal is None or animal.user_id != tutor_id or animal.removido_em:
        return None
    return animal


def _lembrar_envio(envio_id, animal_id):
    if not envio_id:
        return
    recentes = dict(session.get(ENVIOS_ANIMAL_NA_SESSAO) or {})
    recentes[envio_id] = animal_id
    session[ENVIOS_ANIMAL_NA_SESSAO] = dict(list(recentes.items())[-20:])


def _foto_enviada():
    arquivo = request.files.get('image')
    if arquivo is not None and (arquivo.filename or '').strip():
        return arquivo
    return None


def _resposta_erro_foto(exc, wants_json):
    if isinstance(exc, PhotoStorageError):
        current_app.logger.error("Foto de animal não guardada (code=%s): %s", exc.code, exc.detail or exc.user_message)
        message, status = exc.user_message, 502
    else:
        message, status = exc.user_message, getattr(exc, 'status_code', 400)
    if wants_json:
        return jsonify(success=False, message=message, category='danger', field='image'), status
    flash(message, 'danger')
    return redirect(request.referrer or url_for('index'))


def _animal_payload(animal):
    """Dados do animal para a tela atualizar o card sem recarregar."""
    return {
        'id': animal.id,
        'name': animal.name,
        'species': animal.species.name if animal.species else None,
        'breed': animal.breed.name if animal.breed else None,
        'sex': animal.sex,
        'age': animal.age,
        'neutered': animal.neutered,
        'peso': animal.peso,
        'image': animal.image,
        'photo_offset_x': animal.photo_offset_x,
        'photo_offset_y': animal.photo_offset_y,
        'photo_rotation': animal.photo_rotation,
        'photo_zoom': animal.photo_zoom,
        'links': {
            'consulta': url_for('consulta_direct', animal_id=animal.id),
            'ficha': url_for('ficha_animal', animal_id=animal.id),
            'delete': url_for('deletar_animal', animal_id=animal.id),
        },
    }


@bp.route('/update_animal/<int:animal_id>', methods=['POST'])
@login_required
def update_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')
    queued_messages = [] if wants_json else None

    def queue_message(text, category='info'):
        if wants_json:
            queued_messages.append({'message': text, 'category': category})
        else:
            flash(text, category)

    if not can_edit_animal_record(current_user, animal):
        message = veterinarian_denial_message('Apenas veterinários podem editar dados do animal.')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    # Corpo incompleto nunca pode sobrescrever o cadastro. Quando o upload da
    # foto cai no meio (rede do celular), o Werkzeug descarta o multipart em
    # silêncio e ``request.form`` chega vazio; o token CSRF vem no cabeçalho
    # (csrf_fetch.js), então a requisição passava e gravava nome, sexo, peso e
    # o resto como vazio — o prontuário passava a mostrar "None". Todas as
    # telas de edição enviam o campo ``name``: sem ele, nada é alterado.
    nome_enviado = request.form.get('name')
    if nome_enviado is None:
        current_app.logger.warning(
            "update_animal %s recebido sem o campo name (corpo incompleto ou ilegível; content_length=%s); nada foi alterado",
            animal.id,
            request.content_length,
        )
        message = ('Os dados do animal chegaram incompletos (a conexão pode ter caído durante o envio). '
                   'Nada foi alterado. Tente salvar de novo.')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 400
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))
    nome_enviado = nome_enviado.strip()
    if not nome_enviado:
        message = 'Informe o nome do animal.'
        if wants_json:
            return jsonify(success=False, message=message, category='warning'), 400
        flash(message, 'warning')
        return redirect(request.referrer or url_for('index'))

    # Foto primeiro: se ela não puder ser guardada, nada do cadastro muda e a
    # foto anterior continua lá (antes uma falha no S3 gravava image=None).
    foto = _foto_enviada()
    nova_imagem, giro_aplicado = None, False
    if foto is not None:
        try:
            nova_imagem, giro_aplicado = _guardar_foto_animal(foto, request.form.get('photo_rotation'))
        except (PhotoIntakeError, PhotoStorageError) as exc:
            db.session.rollback()
            return _resposta_erro_foto(exc, wants_json)

    # Campos básicos
    animal.name = nome_enviado
    animal.sex = _texto_opcional(request.form.get('sex'))
    animal.description = request.form.get('description') or ''
    animal.microchip_number = _texto_opcional(request.form.get('microchip_number'))
    animal.health_plan = _texto_opcional(request.form.get('health_plan'))
    if 'neutered' in request.form:
        # "—" é "não informado": antes virava "Não" a cada edição.
        animal.neutered = _castrado_do_formulario(request.form.get('neutered'))

    # Espécie (relacional)
    species_id = request.form.get('species_id')
    if species_id:
        try:
            animal.species_id = int(species_id)
        except ValueError:
            queue_message('ID de espécie inválido.', 'warning')

    # Raça (relacional)
    breed_id = request.form.get('breed_id')
    if breed_id:
        try:
            animal.breed_id = int(breed_id)
        except ValueError:
            queue_message('ID de raça inválido.', 'warning')

    # Peso (aceita vírgula, como o teclado do celular manda)
    try:
        animal.peso = _peso_do_formulario(request.form.get('peso'))
    except ValueError:
        queue_message('Peso inválido: use só números, como 12,5. O peso anterior foi mantido.', 'warning')

    # Data de nascimento ou idade
    dob_str = request.form.get('date_of_birth')
    age_input = request.form.get('age')
    age_unit_input = request.form.get('age_unit')
    idade_numero = None
    if dob_str:
        try:
            nascimento = datetime.strptime(dob_str, '%Y-%m-%d').date()
            if nascimento > date.today():
                raise ValueError(dob_str)
            animal.date_of_birth = nascimento
        except ValueError:
            queue_message('Data de nascimento inválida.', 'warning')
    elif age_input:
        try:
            idade_numero = int(age_input)
            unidade_norm = _normalizar_unidade_idade(age_unit_input)
            if unidade_norm == 'meses':
                animal.date_of_birth = date.today() - relativedelta(months=idade_numero)
            else:
                animal.date_of_birth = date.today() - relativedelta(years=idade_numero)
        except ValueError:
            queue_message('Idade inválida. Deve ser um número inteiro.', 'warning')
    elif 'date_of_birth' in request.form and 'age' in request.form:
        # Data e idade vieram vazias de propósito (a pessoa apagou as duas):
        # sem isto a data antiga voltava e recalculava a idade.
        animal.date_of_birth = None

    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            animal.age = _formatar_idade(delta.years, 'anos')
        else:
            animal.age = _formatar_idade(delta.months, 'meses')
    elif idade_numero is not None:
        animal.age = _formatar_idade(idade_numero, age_unit_input)
    elif age_input:
        animal.age = age_input
    else:
        animal.age = None

    # Foto nova (já guardada acima)
    if nova_imagem:
        animal.image = nova_imagem

    if giro_aplicado:
        # O giro foi gravado nos pixels; manter o CSS giraria de novo.
        animal.photo_rotation = 0
    else:
        try:
            animal.photo_rotation = int(float(request.form.get('photo_rotation', animal.photo_rotation or 0)))
        except ValueError:
            pass
    try:
        animal.photo_zoom = float(request.form.get('photo_zoom', animal.photo_zoom or 1.0))
    except ValueError:
        pass
    try:
        animal.photo_offset_x = float(request.form.get('photo_offset_x', animal.photo_offset_x or 0))
    except ValueError:
        pass
    try:
        animal.photo_offset_y = float(request.form.get('photo_offset_y', animal.photo_offset_y or 0))
    except ValueError:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Falha ao salvar animal %s", animal.id)
        message = 'Não foi possível salvar os dados do animal. Tente novamente.'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 500
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    message = 'Dados do animal atualizados com sucesso!'
    if wants_json:
        payload = dict(
            success=True,
            message=message,
            animal_name=animal.name,
            animal=_animal_payload(animal),
            category='success',
        )
        if queued_messages:
            payload['messages'] = queued_messages
        return jsonify(payload)
    flash(message, 'success')
    return redirect(request.referrer or url_for('index'))


@bp.route('/animal/<int:animal_id>/racoes', methods=['POST'])
@login_required
def salvar_racao(animal_id):
    animal = get_animal_or_404(animal_id)

    # Verifica se o usuário pode editar esse animal
    if not can_edit_animal_record(current_user, animal):
        return jsonify({'success': False, 'error': veterinarian_denial_message('Permissão negada.')}), 403

    data = request.get_json(silent=True) or {}

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
                tamanho_embalagem=data.get('tamanho_embalagem'),  # ✅ CORRIGIDO
                created_by=current_user.id
            )
            db.session.add(nova_racao)

        # ✅ SUPORTE AO FORMATO ANTIGO: lista de racoes com marca/linha
        elif 'racoes' in data:
            racoes_data = data.get('racoes', [])
            for r in racoes_data:
                marca = _canonicalize_racao_brand(r.get('marca_racao', ''))
                linha_val = r.get('linha_racao')
                linha = linha_val.strip() if linha_val else None

                if not marca:
                    continue  # ignora se não houver marca

                tipo_racao = TipoRacao.query.filter_by(marca=marca, linha=linha).first()

                if not tipo_racao:
                    tipo_racao = TipoRacao(
                        marca=marca,
                        linha=linha,
                        created_by=current_user.id,
                    )
                    db.session.add(tipo_racao)
                    db.session.flush()  # garante que o ID estará disponível

                nova_racao = Racao(
                    animal_id=animal.id,
                    tipo_racao_id=tipo_racao.id,
                    recomendacao_custom=r.get('recomendacao_custom'),
                    observacoes_racao=r.get('observacoes_racao'),
                    created_by=current_user.id
                )
                db.session.add(nova_racao)

        else:
            return jsonify({'success': False, 'error': 'Formato de dados inválido.'}), 400

        db.session.commit()
        # Limpa o cache caso um novo tipo tenha sido criado acima
        try:
            list_rations.cache_clear()
        except Exception:
            pass

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao salvar ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao salvar ração.'}), 500


@bp.route('/api/tipos_racao', methods=['GET'])
@login_required
def api_tipos_racao():
    """Retorna lista de tipos de ração em JSON para atualização dinâmica"""
    tipos = TipoRacao.query.order_by(TipoRacao.marca, TipoRacao.linha).all()
    return jsonify({
        'success': True,
        'tipos': [{
            'id': t.id,
            'marca': t.marca,
            'linha': t.linha
        } for t in tipos]
    })


@bp.route('/tipo_racao', methods=['POST'])
@login_required
def criar_tipo_racao():
    if not can_edit_animal_record(current_user):
        return jsonify({'success': False, 'error': veterinarian_denial_message('Permissão negada.')}), 403

    data = request.get_json(silent=True) or {}
    marca = _canonicalize_racao_brand(data.get('marca', ''))
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
            observacoes=observacoes if observacoes else None,
            created_by=current_user.id,
        )
        db.session.add(nova_racao)
        db.session.commit()
        # Limpa o cache para que novas rações apareçam imediatamente
        try:
            list_rations.cache_clear()
        except Exception:
            pass

        return jsonify({'success': True, 'id': nova_racao.id})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao cadastrar tipo de ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao cadastrar tipo de ração.'}), 500


@bp.route('/tipo_racao/<int:tipo_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_tipo_racao(tipo_id):
    tipo = TipoRacao.query.get_or_404(tipo_id)
    if tipo.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        db.session.delete(tipo)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    marca_val = data.get('marca', tipo.marca)
    if marca_val is not None:
        marca_val = _canonicalize_racao_brand(marca_val)
    tipo.marca = marca_val
    linha_val = data.get('linha', tipo.linha)
    if linha_val is not None:
        linha_val = linha_val.strip()
    tipo.linha = linha_val or None
    tipo.recomendacao = data.get('recomendacao', tipo.recomendacao)
    tipo.peso_pacote_kg = data.get('peso_pacote_kg', tipo.peso_pacote_kg)
    tipo.observacoes = data.get('observacoes', tipo.observacoes)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/tipos_racao')
def tipos_racao():
    termos = request.args.get('q', '')
    resultados = TipoRacao.query.filter(
        (TipoRacao.marca + ' - ' + (TipoRacao.linha or '')).ilike(f'%{termos}%')
    ).limit(15).all()

    return jsonify([
        f"{r.marca} - {r.linha}" if r.linha else r.marca
        for r in resultados
    ])


@bp.route('/buscar_racoes')
def buscar_racoes():
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])

    # Pool maior para o re-ranqueamento por espécie ter material para reorganizar
    resultados = (
        TipoRacao.query
        .filter(
            (TipoRacao.marca.ilike(f'%{q}%')) |
            (TipoRacao.linha.ilike(f'%{q}%'))
        )
        .order_by(TipoRacao.marca)
        .limit(40)
        .all()
    )

    from services.species_ranking import (
        resolver_species_scope_do_animal,
        ordenar_por_species_scope,
    )
    scope_alvo = resolver_species_scope_do_animal(request.args.get('animal_id'))
    if scope_alvo:
        resultados = ordenar_por_species_scope(resultados, scope_alvo)

    return jsonify([
        {
            'id': r.id,
            'marca': r.marca,
            'linha': r.linha,
            'recomendacao': r.recomendacao,
            'peso_pacote_kg': r.peso_pacote_kg,
            'observacoes': r.observacoes,
            'species_scope': r.species_scope,
        }
        for r in resultados[:15]
    ])


@bp.route('/racao/<int:racao_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def alterar_racao(racao_id):
    racao = Racao.query.get_or_404(racao_id)

    if not can_edit_animal_record(current_user, racao.animal):
        return jsonify({'success': False, 'error': veterinarian_denial_message('Permissão negada.')}), 403

    if racao.created_by and racao.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': veterinarian_denial_message('Permissão negada.')}), 403

    if request.method == 'GET':
        return jsonify({
            'success': True,
            'racao': {
                'observacoes_racao': racao.observacoes_racao,
                'recomendacao_custom': racao.recomendacao_custom,
                'preco_pago': racao.preco_pago,
                'tamanho_embalagem': racao.tamanho_embalagem,
            }
        })

    if request.method == 'DELETE':
        try:
            db.session.delete(racao)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            print(f"Erro ao excluir ração: {e}")
            return jsonify({'success': False, 'error': 'Erro técnico ao excluir ração.'}), 500

    data = request.get_json(silent=True) or {}
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


@bp.route("/relatorio/racoes")
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

    return render_template("loja/relatorio_racoes.html", racoes_por_tipo=racoes_por_tipo)


@bp.route("/historico_animal/<int:animal_id>")
@login_required
def historico_animal(animal_id):
    animal = get_animal_or_404(animal_id)
    racoes = Racao.query.filter_by(animal_id=animal.id).order_by(Racao.data_cadastro.desc()).all()
    return render_template("historico_racoes.html", animal=animal, racoes=racoes)


@bp.route('/relatorio/racoes/<int:tipo_id>')
@login_required
def detalhes_racao(tipo_id):
    tipo = TipoRacao.query.get_or_404(tipo_id)
    racoes = tipo.usos  # usa o backref 'usos'
    return render_template('loja/detalhes_racao.html', tipo=tipo, racoes=racoes)


@bp.route('/buscar_vacinas')
def buscar_vacinas():
    termo = request.args.get('q', '').strip().lower()

    if not termo or len(termo) < 2:
        return jsonify([])

    try:
        resultados = VacinaModelo.query.filter(
            VacinaModelo.nome.ilike(f"%{termo}%")
        ).order_by(VacinaModelo.nome).limit(40).all()

        from services.species_ranking import (
            resolver_species_scope_do_animal,
            ordenar_por_species_scope,
        )
        scope_alvo = resolver_species_scope_do_animal(request.args.get('animal_id'))
        if scope_alvo:
            resultados = ordenar_por_species_scope(resultados, scope_alvo)

        return jsonify([
            {
                'id': v.id,
                'nome': v.nome,
                'tipo': v.tipo or '',
                'fabricante': v.fabricante or '',
                'doses_totais': v.doses_totais,
                'intervalo_dias': v.intervalo_dias,
                'frequencia': v.frequencia or '',
                'species_scope': v.species_scope,
            }
            for v in resultados[:15]
        ])
    except Exception as e:
        print(f"Erro ao buscar vacinas: {e}")
        return jsonify([])  # Não quebra o front se der erro


@bp.route('/vacina_modelo', methods=['POST'])
@login_required
def criar_vacina_modelo():
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    tipo = (data.get('tipo') or '').strip()
    fabricante = (data.get('fabricante') or '').strip() or None
    doses_totais = data.get('doses_totais')
    intervalo_dias = data.get('intervalo_dias')
    frequencia = (data.get('frequencia') or '').strip() or None
    if not nome or not tipo:
        return jsonify({'success': False, 'message': 'Nome e tipo são obrigatórios.'}), 400
    try:
        existente = VacinaModelo.query.filter(func.lower(VacinaModelo.nome) == nome.lower()).first()
        if existente:
            return jsonify({'success': False, 'message': 'Vacina já cadastrada.'}), 400
        vacina = VacinaModelo(
            nome=nome,
            tipo=tipo,
            fabricante=fabricante,
            doses_totais=doses_totais,
            intervalo_dias=intervalo_dias,
            frequencia=frequencia,
            created_by=current_user.id,
        )
        db.session.add(vacina)
        db.session.commit()
        return jsonify({
            'success': True,
            'vacina': {
                'id': vacina.id,
                'nome': vacina.nome,
                'tipo': vacina.tipo,
                'fabricante': vacina.fabricante,
                'doses_totais': vacina.doses_totais,
                'intervalo_dias': vacina.intervalo_dias,
                'frequencia': vacina.frequencia,
            },
        })
    except Exception as e:
        db.session.rollback()
        print('Erro ao salvar vacina modelo:', e)
        return jsonify({'success': False, 'message': 'Erro ao salvar vacina.'}), 500


@bp.route('/vacina_modelo/<int:vacina_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_vacina_modelo(vacina_id):
    vacina = VacinaModelo.query.get_or_404(vacina_id)
    if vacina.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'message': 'Permissão negada'}), 403

    if request.method == 'DELETE':
        db.session.delete(vacina)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    nome_val = data.get('nome', vacina.nome)
    if nome_val is not None:
        nome_val = nome_val.strip()
    vacina.nome = nome_val
    tipo_val = data.get('tipo', vacina.tipo)
    if tipo_val is not None:
        tipo_val = tipo_val.strip()
    vacina.tipo = tipo_val or None
    vacina.fabricante = (data.get('fabricante', vacina.fabricante) or '').strip() or None
    vacina.doses_totais = data.get('doses_totais', vacina.doses_totais)
    vacina.intervalo_dias = data.get('intervalo_dias', vacina.intervalo_dias)
    vacina.frequencia = (data.get('frequencia', vacina.frequencia) or '').strip() or None
    db.session.commit()
    return jsonify({'success': True})


def _current_user_can_manage_vaccine_history(animal: Animal) -> bool:
    if not current_user.is_authenticated:
        return False
    if getattr(current_user, 'role', '') == 'admin':
        return True
    if animal.user_id == current_user.id or animal.added_by_id == current_user.id:
        return True
    if getattr(current_user, 'worker', '') == 'veterinario' and not animal.clinica_id:
        return True
    if has_professional_access(current_user):
        return bool(animal.clinica_id and animal.clinica_id in set(_viewer_accessible_clinic_ids(current_user) or ()))
    return False


@bp.route("/animal/<int:animal_id>/vacinas", methods=["POST"])
@login_required
def salvar_vacinas(animal_id):
    data = request.get_json(silent=True) or {}

    if not data or "vacinas" not in data:
        return jsonify({"success": False, "error": "Dados incompletos"}), 400

    try:
        animal = Animal.query.get_or_404(animal_id)
        if not _current_user_can_manage_vaccine_history(animal):
            return jsonify({"success": False, "error": "Permissao negada"}), 403
        for v in data["vacinas"]:
            aplicada_em_str = v.get("aplicada_em")
            if aplicada_em_str:
                try:
                    aplicada_em = datetime.strptime(aplicada_em_str, "%Y-%m-%d").date()
                except ValueError:
                    aplicada_em = None
            else:
                aplicada_em = None

            vacina = Vacina(
                animal_id=animal_id,
                nome=v.get("nome"),
                tipo=v.get("tipo"),
                fabricante=v.get("fabricante"),
                doses_totais=v.get("doses_totais"),
                intervalo_dias=v.get("intervalo_dias"),
                frequencia=v.get("frequencia"),
                aplicada=v.get("aplicada", False),
                aplicada_em=aplicada_em,
                observacoes=v.get("observacoes"),
                created_by=current_user.id if current_user.is_authenticated else None,
            )
            db.session.add(vacina)

        db.session.commit()
        historico_html = render_template(
            'partials/historico_vacinas.html',
            animal=animal
        )
        return jsonify({"success": True, "html": historico_html})

    except Exception as e:
        print("Erro ao salvar vacinas:", e)
        return jsonify({"success": False, "error": "Erro técnico ao salvar vacinas"}), 500


@bp.route("/animal/<int:animal_id>/vacinas/imprimir")
@login_required
def imprimir_vacinas(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if not _current_user_can_manage_vaccine_history(animal):
        abort(403)
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = get_responsible_veterinarian(
        consulta.veterinario if consulta else None,
        fallback=pessoa_no_documento(current_user) if can_act_as_veterinarian(current_user) else None,
    )
    clinica = consulta.clinica if consulta and consulta.clinica else None
    if not clinica and veterinario and getattr(veterinario, "veterinario", None):
        vet = veterinario.veterinario
        if vet.clinica:
            clinica = vet.clinica
    if not clinica:
        clinica = getattr(animal, "clinica", None)
    if not clinica:
        clinica_id = request.args.get("clinica_id", type=int)
        if clinica_id:
            clinica = Clinica.query.get_or_404(clinica_id)
    if not clinica and any((vac.tipo or "").startswith("Campanha PMO") for vac in animal.vacinas):
        from types import SimpleNamespace
        pmo_vac = next(
            (vac for vac in animal.vacinas if (vac.tipo or "").startswith("Campanha PMO") and vac.aplicador),
            None,
        )
        pmo_vet = pmo_vac.aplicador if pmo_vac else None
        clinica = SimpleNamespace(
            nome="Prefeitura de Orlândia",
            endereco="Campanha municipal de vacinação antirrábica",
            telefone=pmo_vet.phone if pmo_vet else None,
            email=None,
            cnpj=None,
            logotipo=None,
        )
        if not veterinario and pmo_vet:
            veterinario = pmo_vet
    if not clinica:
        abort(400, description="É necessário informar uma clínica.")
    if request.args.get('pdf') in ('inline', 'download'):
        from services.vacinas_pdf import gerar_pdf_carteira
        pdf = gerar_pdf_carteira(animal, clinica, veterinario)
        response = current_app.response_class(pdf, mimetype='application/pdf')
        disposition = 'inline' if request.args.get('pdf') == 'inline' else 'attachment'
        response.headers['Content-Disposition'] = f'{disposition}; filename="carteira-vacinacao-{animal.id}.pdf"'
        response.headers['Cache-Control'] = 'private, no-store'
        return response
    return render_template("orcamentos/imprimir_vacinas.html", animal=animal, clinica=clinica, veterinario=veterinario)


@bp.route('/vacina/<int:vacina_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_vacina(vacina_id):
    vacina = Vacina.query.get_or_404(vacina_id)

    if not (
        is_veterinarian(current_user, require_membership=False)
        or getattr(current_user, 'worker', None) == 'veterinario'
        or can_act_as_veterinarian(current_user)
    ):
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if vacina.created_by and vacina.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            animal_id = vacina.animal_id
            db.session.delete(vacina)
            db.session.commit()
            return jsonify({'success': True, 'animal_id': animal_id})
        except Exception as e:
            db.session.rollback()
            print('Erro ao excluir vacina:', e)
            return jsonify({'success': False, 'error': 'Erro ao excluir vacina.'}), 500

    data = request.get_json(silent=True) or {}
    vacina.nome = data.get('nome', vacina.nome)
    vacina.tipo = data.get('tipo', vacina.tipo)
    vacina.fabricante = data.get('fabricante', vacina.fabricante)
    vacina.doses_totais = data.get('doses_totais', vacina.doses_totais)
    vacina.intervalo_dias = data.get('intervalo_dias', vacina.intervalo_dias)
    vacina.frequencia = data.get('frequencia', vacina.frequencia)
    vacina.observacoes = data.get('observacoes', vacina.observacoes)
    vacina.aplicada = data.get('aplicada', vacina.aplicada)

    aplicada_em_str = data.get('aplicada_em')
    if aplicada_em_str is not None:
        if aplicada_em_str:
            try:
                vacina.aplicada_em = datetime.strptime(aplicada_em_str, '%Y-%m-%d').date()
            except ValueError:
                vacina.aplicada_em = None
        else:
            vacina.aplicada_em = None

    nova_vacina = None
    if vacina.aplicada:
        base_date = vacina.aplicada_em or date.today()
        proxima_data = None
        if vacina.intervalo_dias:
            proxima_data = base_date + timedelta(days=vacina.intervalo_dias)
        elif vacina.frequencia:
            def _norm(txt):
                txt_lower = txt.lower()
                if txt_lower.isascii():
                    return txt_lower
                return ''.join([
                    c for c in unicodedata.normalize('NFD', txt_lower)
                    if unicodedata.category(c) != 'Mn'
                ])

            freq_map = {
                'diario': 1,
                'diaria': 1,
                'semanal': 7,
                'quinzenal': 15,
                'mensal': 30,
                'bimestral': 60,
                'trimestral': 91,
                'quadrimestral': 120,
                'semestral': 182,
                'anual': 365,
                'bienal': 730,
            }
            dias = freq_map.get(_norm(vacina.frequencia))
            if dias:
                proxima_data = base_date + timedelta(days=dias)

        if proxima_data:
            nova_vacina = Vacina(
                animal_id=vacina.animal_id,
                nome=vacina.nome,
                tipo=vacina.tipo,
                fabricante=vacina.fabricante,
                doses_totais=vacina.doses_totais,
                intervalo_dias=vacina.intervalo_dias,
                frequencia=vacina.frequencia,
                observacoes=vacina.observacoes,
                aplicada=False,
                aplicada_em=proxima_data,
                created_by=vacina.created_by,
            )

    try:
        if nova_vacina:
            db.session.add(nova_vacina)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print('Erro ao editar vacina:', e)
        return jsonify({'success': False, 'error': 'Erro ao editar vacina.'}), 500


@bp.route('/criar_tutor_ajax', methods=['POST'])
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
        clinica_id=current_user_clinic_id(),
        added_by=current_user,
        is_private=True,

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


@bp.route('/novo_animal', methods=['GET', 'POST'])
@login_required
def novo_animal():
    if not has_professional_access(current_user):
        # Tutor comum caiu na rota profissional (link antigo ou compartilhado):
        # leva direto para o cadastro de pet do tutor em vez de mostrar erro.
        return redirect(url_for('add_animal'))

    clinic_id = current_user_clinic_id()
    accessible_clinic_ids = _viewer_accessible_clinic_ids(current_user)
    clinic_scope = (
        accessible_clinic_ids
        if len(accessible_clinic_ids) > 1
        else accessible_clinic_ids[0]
        if accessible_clinic_ids
        else None
    )
    vet_profile = getattr(current_user, 'veterinario', None)
    require_appointments = _is_specialist_veterinarian(vet_profile)
    veterinarian_scope_id = vet_profile.id if require_appointments and vet_profile else None
    current_user_id = getattr(current_user, 'id', None)

    if request.method == 'POST':
        # Retorna conteúdo em JSON apenas quando o cliente realmente
        # priorizar "application/json" ou quando for uma requisição AJAX.
        prefers_json = (
            request.accept_mimetypes['application/json'] >
            request.accept_mimetypes['text/html']
        )
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        quer_json = prefers_json or is_ajax
        tutor = None

        def _recusar(message, status=400, category='warning', field=None):
            # Antes os erros viravam flash + redirect; o fetch seguia o
            # redirect, recebia 200 e a tela dizia "Animal cadastrado com
            # sucesso!" sem nada ter sido salvo.
            if quer_json:
                payload = dict(success=False, message=message, category=category)
                if field:
                    payload['field'] = field
                return jsonify(payload), status
            flash(message, category)
            if tutor is not None:
                return redirect(url_for('ficha_tutor', tutor_id=tutor.id))
            return redirect(request.referrer or url_for('novo_animal'))

        tutor_id = request.form.get('tutor_id', type=int)
        if not tutor_id:
            return _recusar('Selecione o tutor antes de salvar o animal.', field='tutor_id')
        tutor = get_user_or_404(tutor_id)

        nome_animal = ' '.join((request.form.get('name') or '').split())
        if not nome_animal:
            return _recusar('Informe o nome do animal.', field='name')
        if len(nome_animal) > 100:
            return _recusar('O nome do animal pode ter no máximo 100 caracteres.', field='name')

        envio_id = (request.form.get('envio_id') or '').strip()[:64]
        ja_criado = _animal_do_envio(envio_id, tutor.id) if quer_json else None
        if ja_criado is not None:
            return jsonify(
                success=True,
                already_existed=True,
                message=f'O cadastro de {ja_criado.name} já estava salvo. Nada foi duplicado.',
                category='info',
                animal=_animal_payload(ja_criado),
            )

        dob_str = request.form.get('date_of_birth')
        dob = None
        idade_numero = None
        age_unit_input = request.form.get('age_unit')
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                if dob > date.today():
                    raise ValueError(dob_str)
            except ValueError:
                return _recusar('Data de nascimento inválida. Confira o dia, o mês e o ano.', field='date_of_birth')
        else:
            age_input = (request.form.get('age') or '').strip()
            if age_input:
                try:
                    idade_numero = int(age_input)
                    if idade_numero < 0:
                        raise ValueError(age_input)
                    unidade_norm = _normalizar_unidade_idade(age_unit_input)
                    if unidade_norm == 'meses':
                        dob = date.today() - relativedelta(months=idade_numero)
                    else:
                        dob = date.today() - relativedelta(years=idade_numero)
                except ValueError:
                    return _recusar('Idade inválida: use um número inteiro, como 3.', field='age')

        idade_registrada = None
        if dob:
            delta = relativedelta(date.today(), dob)
            if delta.years > 0:
                idade_registrada = _formatar_idade(delta.years, 'anos')
            else:
                idade_registrada = _formatar_idade(delta.months, 'meses')
        elif idade_numero is not None:
            idade_registrada = _formatar_idade(idade_numero, age_unit_input)

        try:
            peso = _peso_do_formulario(request.form.get('peso'))
        except ValueError:
            return _recusar('Peso inválido: use só números, como 12,5.', field='peso')

        neutered = _castrado_do_formulario(request.form.get('neutered'))

        # IDs para espécie e raça
        species_id = request.form.get('species_id', type=int)
        breed_id = request.form.get('breed_id', type=int)

        microchip_number = (request.form.get('microchip_number') or '').strip() or None

        duplicate_filters = [
            Animal.user_id == tutor.id,
            func.lower(Animal.name) == func.lower(nome_animal),
            # Animal removido não impede cadastrar de novo.
            Animal.removido_em.is_(None),
        ]

        duplicate_conditions = []
        if microchip_number:
            duplicate_conditions.append(Animal.microchip_number == microchip_number)
        if dob:
            duplicate_conditions.append(Animal.date_of_birth == dob)
        if idade_registrada:
            duplicate_conditions.append(and_(Animal.age.isnot(None), Animal.age == idade_registrada))

        # Evita duplicação por cliques repetidos considerando cadastros recentes
        # Only use the time window when no other identifying conditions exist
        recent_window = utcnow() - timedelta(minutes=10)
        if not duplicate_conditions:
            duplicate_conditions.append(Animal.date_added >= recent_window)

        existing_animal = None
        if duplicate_conditions and request.form.get('confirmar_duplicado') != '1':
            existing_animal = (
                Animal.query.filter(*duplicate_filters)
                .filter(or_(*duplicate_conditions))
                .order_by(Animal.id.desc())
                .first()
            )

        if existing_animal:
            # O reenvio do mesmo cadastro (conexão caiu depois de salvar) já foi
            # reconhecido acima pelo envio_id. Aqui é outro envio com os mesmos
            # dados: a tela mostra o aviso e deixa confirmar se for outro animal.
            message = (
                f'Já existe um animal chamado {existing_animal.name} para este tutor '
                'com os mesmos dados. Se for outro animal, confirme para cadastrar mesmo assim.'
            )
            if quer_json:
                return (
                    jsonify(
                        success=False,
                        duplicate=True,
                        message=message,
                        category='warning',
                        redirect=url_for('ficha_animal', animal_id=existing_animal.id),
                        animal=_animal_payload(existing_animal),
                    ),
                    409,
                )
            flash(message, 'warning')
            return redirect(url_for('ficha_animal', animal_id=existing_animal.id))

        # Foto por último antes de criar: nada sobe ao armazenamento se o
        # cadastro for recusado acima.
        image_path = None
        giro_aplicado = False
        foto = _foto_enviada()
        if foto is not None:
            try:
                image_path, giro_aplicado = _guardar_foto_animal(foto, request.form.get('photo_rotation'))
            except (PhotoIntakeError, PhotoStorageError) as exc:
                return _resposta_erro_foto(exc, quer_json)

        def _numero_do_form(campo, padrao, minimo, maximo):
            try:
                valor = float(request.form.get(campo))
            except (TypeError, ValueError):
                return padrao
            if not math.isfinite(valor):
                return padrao
            return min(max(valor, minimo), maximo)

        # Enquadramento escolhido no editor (antes era descartado no cadastro).
        if image_path:
            photo_rotation = 0 if giro_aplicado else int(_numero_do_form('photo_rotation', 0, 0, 359))
            photo_zoom = _numero_do_form('photo_zoom', 1.0, 0.5, 3.0)
            photo_offset_x = _numero_do_form('photo_offset_x', 0.0, -2000, 2000)
            photo_offset_y = _numero_do_form('photo_offset_y', 0.0, -2000, 2000)
        else:
            photo_rotation, photo_zoom, photo_offset_x, photo_offset_y = 0, 1.0, 0.0, 0.0

        # Criação do animal
        animal = Animal(
            name=nome_animal,
            species_id=species_id,
            breed_id=breed_id,
            sex=_texto_opcional(request.form.get('sex')),
            date_of_birth=dob,
            age=idade_registrada,
            microchip_number=microchip_number,
            peso=peso,
            health_plan=_texto_opcional(request.form.get('health_plan')),
            neutered=neutered,
            user_id=tutor.id,
            added_by_id=current_user.id,
            clinica_id=current_user_clinic_id(),
            status='disponível',
            image=image_path,
            photo_rotation=photo_rotation,
            photo_zoom=photo_zoom,
            photo_offset_x=photo_offset_x,
            photo_offset_y=photo_offset_y,
            is_alive=True,
            modo='adotado',
        )
        db.session.add(animal)
        if neutered is None:
            # "Não sei": a coluna tem default=False e o INSERT aplicaria o
            # padrão sobre o None; a edição seguinte mostraria "Não".
            db.session.flush()
            animal.neutered = None
        db.session.commit()

        # Criação da consulta
        consulta = Consulta(
            animal_id=animal.id,
            created_by=current_user.id,
            clinica_id=current_user_clinic_id(),
            status='in_progress'
        )
        db.session.add(consulta)
        db.session.commit()
        _lembrar_envio(envio_id, animal.id)

        if quer_json:
            payload = dict(
                success=True,
                message='Animal cadastrado com sucesso!',
                category='success',
                animal=_animal_payload(animal),
            )
            # A lista "animais adicionados" só interessa às telas que a
            # mostram; a ficha do tutor pede sem (sem_lista=1). Se montar a
            # lista falhar, o animal já está salvo: a resposta continua sendo
            # de sucesso, só sem o HTML.
            if request.form.get('sem_lista') != '1':
                try:
                    scope_param = request.args.get('scope', 'all')
                    page = request.args.get('page', 1, type=int)
                    animal_search = (request.args.get('animal_search', '', type=str) or '').strip()
                    animal_sort = (request.args.get('animal_sort', 'date_desc', type=str) or 'date_desc').strip()
                    animais_adicionados, pagination, scope = _get_recent_animais(
                        scope_param,
                        page,
                        clinic_id=clinic_scope,
                        user_id=current_user_id,
                        require_appointments=require_appointments,
                        veterinario_id=veterinarian_scope_id,
                        search=animal_search,
                        sort_option=animal_sort,
                    )
                    payload['html'] = render_template(
                        'partials/animais_adicionados.html',
                        animais_adicionados=animais_adicionados,
                        pagination=pagination,
                        scope=scope,
                        scope_param=request.args.get('scope_param', 'scope'),
                        search_param='animal_search',
                        sort_param='animal_sort',
                        page_param=request.args.get('page_param', 'page'),
                        fetch_url=url_for('novo_animal'),
                        compact=True,
                        can_create_animals=False,
                        new_animal_url=url_for('novo_animal'),
                    )
                except Exception:
                    db.session.rollback()
                    current_app.logger.exception(
                        "Animal %s salvo, mas a lista de animais adicionados não foi montada", animal.id
                    )
            return jsonify(payload)

        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('consulta_direct', animal_id=animal.id))

    # GET: lista de animais adicionados para exibição
    page = request.args.get('page', 1, type=int)
    scope_param = request.args.get('scope', 'all')
    animal_search = (request.args.get('animal_search', '', type=str) or '').strip()
    animal_sort = (request.args.get('animal_sort', 'date_desc', type=str) or 'date_desc').strip()
    wants_listing_payload = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (
        request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
    )
    active_record_panel = _resolve_record_panel(
        request.args,
        listing_params=('scope', 'animal_search', 'animal_sort', 'page'),
        default='list',
    )
    defer_animal_listing = active_record_panel != 'list' and not wants_listing_payload

    if defer_animal_listing:
        animais_adicionados = []
        pagination = None
        scope = scope_param
    else:
        animais_adicionados, pagination, scope = _get_recent_animais(
            scope_param,
            page,
            clinic_id=clinic_scope,
            user_id=current_user_id,
            require_appointments=require_appointments,
            veterinario_id=veterinarian_scope_id,
            search=animal_search,
            sort_option=animal_sort,
        )

    # Lista de espécies e raças para os <select> do formulário
    species_list = list_species()
    breed_list = list_breeds()

    if wants_listing_payload:
        html = render_template(
            'partials/animais_adicionados.html',
            animais_adicionados=animais_adicionados,
            pagination=pagination,
            scope=scope,
            scope_param=request.args.get('scope_param', 'scope'),
            search_param='animal_search',
            sort_param='animal_sort',
            page_param=request.args.get('page_param', 'page'),
            fetch_url=url_for('novo_animal'),
            compact=True,
            can_create_animals=False,
            new_animal_url=url_for('novo_animal'),
        )
        return jsonify(html=html, scope=scope)

    animal_listing_args = {'scope': scope_param}
    if animal_search:
        animal_listing_args['animal_search'] = animal_search
    if animal_sort:
        animal_listing_args['animal_sort'] = animal_sort
    if page > 1:
        animal_listing_args['page'] = page

    return render_template(
        'animais/novo_animal.html',
        animais_adicionados=animais_adicionados,
        pagination=pagination,
        species_list=species_list,
        breed_list=breed_list,
        scope=scope,
        animal_search=animal_search,
        animal_sort=animal_sort,
        active_record_panel=active_record_panel,
        defer_animal_listing=defer_animal_listing,
        animal_listing_fetch_url=url_for('novo_animal', **animal_listing_args),
    )


@bp.route('/animal/<int:animal_id>/marcar_falecido', methods=['POST'])
@login_required
def marcar_como_falecido(animal_id):
    animal = get_animal_or_404(animal_id)

    if not can_act_as_veterinarian(current_user):
        flash(veterinarian_denial_message('Apenas veterinários podem realizar essa ação.'), 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    data = request.form.get('falecimento_em')

    try:
        animal.falecido_em = datetime.strptime(data, '%Y-%m-%dT%H:%M') if data else utcnow()
        animal.is_alive = False
        db.session.commit()
        flash(f'{animal.name} foi marcado como falecido.', 'success')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(
                message=f'{animal.name} foi marcado como falecido.',
                category='success',
                redirect=url_for('ficha_animal', animal_id=animal.id)
            )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Erro ao marcar animal %s como falecido', animal_id)
        flash('Não foi possível marcar como falecido. Tente novamente.', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message='Não foi possível marcar como falecido.', category='danger'), 400

    return redirect(url_for('ficha_animal', animal_id=animal.id))


@bp.route('/animal/<int:animal_id>/reverter_falecimento', methods=['POST'])
@login_required
def reverter_falecimento(animal_id):
    if not can_act_as_veterinarian(current_user):
        abort(403)

    animal = get_animal_or_404(animal_id)
    animal.is_alive = True
    animal.falecido_em = None
    db.session.commit()
    flash('Falecimento revertido com sucesso.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(
            message='Falecimento revertido com sucesso.',
            category='success',
            redirect=url_for('ficha_animal', animal_id=animal.id)
        )
    return redirect(url_for('ficha_animal', animal_id=animal.id))


@bp.route('/animal/<int:animal_id>/arquivar', methods=['POST'])
@login_required
def arquivar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if not can_act_as_veterinarian(current_user):
        flash(veterinarian_denial_message('Apenas veterinários podem excluir animais definitivamente.'), 'danger')
        return redirect(request.referrer or url_for('index'))

    try:
        db.session.delete(animal)
        db.session.commit()
        flash(f'Animal {animal.name} excluído permanentemente.', 'success')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(
                message=f'Animal {animal.name} excluído permanentemente.',
                category='success',
                redirect=url_for('ficha_tutor', tutor_id=animal.user_id)
            )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Erro ao arquivar animal %s', animal_id)
        flash('Não foi possível excluir o animal. Tente novamente.', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message='Não foi possível excluir o animal.', category='danger'), 400

    return redirect(url_for('ficha_tutor', tutor_id=animal.user_id))


@bp.route("/api/animal/<int:animal_id>/peso", methods=["PATCH"])
@csrf.exempt
@login_required
def api_atualizar_peso_animal(animal_id):
    """Atualiza apenas o peso de um animal. Usado no inline-input da prescrição."""
    animal = get_animal_or_404(animal_id)
    # Permite ao veterinário da clínica ou ao dono do animal alterar o peso.
    from flask_login import current_user as cu
    is_owner  = (animal.user_id == cu.id)
    is_clinic = bool(getattr(animal, "clinica_id", None) and acting_clinic_id(cu) == animal.clinica_id)
    if not is_owner and not is_clinic:
        return jsonify({"ok": False, "erro": "Sem permissão."}), 403

    data = request.get_json(silent=True) or {}
    try:
        novo_peso = float(data.get("peso_kg", ""))
        if novo_peso <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Peso inválido."}), 400

    animal.peso = novo_peso
    db.session.commit()
    return jsonify({"ok": True, "peso_kg": novo_peso})



# ---------------------------------------------------------------------------
# Carteirinha digital pública do pet
# ---------------------------------------------------------------------------

def _carteirinha_pode_gerenciar(animal):
    return (
        current_user.is_authenticated
        and (
            current_user.role == 'admin'
            or animal.user_id == current_user.id
        )
    )


@bp.route('/animal/<int:animal_id>/carteirinha/ativar', methods=['POST'])
@login_required
def carteirinha_ativar(animal_id):
    animal = get_animal_or_404(animal_id)
    if not _carteirinha_pode_gerenciar(animal):
        abort(403)
    if not animal.public_token:
        animal.public_token = secrets.token_urlsafe(20)[:32]
        db.session.commit()
        track_event('health_card_activated', feature='health_card')
    flash('Carteirinha digital ativada! Compartilhe o link com quem cuida do seu pet.', 'success')
    return redirect(url_for('ficha_animal', animal_id=animal.id))


@bp.route('/animal/<int:animal_id>/carteirinha/desativar', methods=['POST'])
@login_required
def carteirinha_desativar(animal_id):
    animal = get_animal_or_404(animal_id)
    if not _carteirinha_pode_gerenciar(animal):
        abort(403)
    if animal.public_token:
        animal.public_token = None
        db.session.commit()
        track_event('health_card_deactivated', feature='health_card')
    flash('Carteirinha digital desativada. O link antigo deixou de funcionar.', 'info')
    return redirect(url_for('ficha_animal', animal_id=animal.id))


# ---------------------------------------------------------------------------
# Selo de registro na Prefeitura (somente administradores)
# ---------------------------------------------------------------------------

@bp.route('/animal/<int:animal_id>/selo-prefeitura', methods=['POST'])
@login_required
def selo_prefeitura_conceder(animal_id):
    from services import selo_prefeitura

    if current_user.role != 'admin':
        abort(403)
    animal = get_animal_or_404(animal_id)
    inicio_raw = (request.form.get('inicio') or '').strip()
    try:
        inicio = datetime.strptime(inicio_raw, '%Y-%m-%d').date()
    except ValueError:
        flash('Informe a data de início do registro.', 'warning')
        return redirect(url_for('ficha_animal', animal_id=animal.id))
    try:
        selo_prefeitura.garantir_tabela()
        selo_prefeitura.conceder_selo(
            animal, inicio, current_user.id, request.form.get('observacao')
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha ao conceder selo da Prefeitura ao animal %s', animal_id)
        flash('Não foi possível registrar o selo agora. Tente novamente.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal_id))
    validade = selo_prefeitura.validade_do_selo(inicio)
    flash(
        f'Selo da Prefeitura registrado para {animal.name}: válido até {validade.strftime("%d/%m/%Y")}.',
        'success',
    )
    return redirect(url_for('ficha_animal', animal_id=animal.id))


@bp.route('/animal/<int:animal_id>/selo-prefeitura/remover', methods=['POST'])
@login_required
def selo_prefeitura_remover(animal_id):
    from services import selo_prefeitura

    if current_user.role != 'admin':
        abort(403)
    animal = get_animal_or_404(animal_id)
    try:
        removidos = selo_prefeitura.retirar_selo(animal)
        db.session.commit()
    except Exception:
        db.session.rollback()
        removidos = 0
    if removidos:
        flash(f'Selo da Prefeitura retirado de {animal.name}.', 'info')
    else:
        flash('Este animal não tinha selo da Prefeitura.', 'info')
    return redirect(url_for('ficha_animal', animal_id=animal.id))


@bp.route('/carteirinha/<token>')
def carteirinha_publica(token):
    """Página pública da carteirinha — não exige login.

    Mostra apenas dados do pet (nunca contato completo do tutor). O token é
    opaco e revogável pelo tutor a qualquer momento.
    """
    animal = (
        Animal.query
        .filter_by(public_token=token)
        .filter(Animal.removido_em.is_(None))
        .first_or_404()
    )

    vacinas_aplicadas = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=True)
        .order_by(Vacina.aplicada_em.desc())
        .all()
    )
    proximas_doses = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
        .filter(Vacina.aplicada_em.isnot(None))
        .order_by(Vacina.aplicada_em)
        .all()
    )
    vermifugacoes = (
        AnimalHealthRecord.query
        .filter_by(animal_id=animal.id, kind='vermifugacao')
        .order_by(AnimalHealthRecord.occurred_on.desc(), AnimalHealthRecord.id.desc())
        .all()
    )

    # Public card: group commercial brands by clinical protection. A later
    # Rabisin/Raiva PM dose, for example, supersedes an older Canigen R dose.
    def grupo_clinico(vacina):
        raw = f'{vacina.nome or ""} {vacina.tipo or ""}'.casefold()
        if raw.isascii():
            normalized = raw
        else:
            normalized = ''.join([
                char for char in unicodedata.normalize('NFD', raw)
                if unicodedata.category(char) != 'Mn'
            ])
        if any(token in normalized for token in ('antirrab', 'raiva', 'rabisin', 'defensor', 'hertaliq', 'canigen r')):
            return 'antirrabica'
        if 'leish' in normalized:
            return 'leishmaniose'
        if 'giardia' in normalized:
            return 'giardiase'
        if any(token in normalized for token in ('dhppi', 'vanguard', 'nobivac canine', 'polivalente', 'multipla')):
            return 'multipla'
        return normalized or str(vacina.id)

    proximas_acoes = []
    doses_a_revisar = []
    vacinas_atuais = {}
    for vacina in vacinas_aplicadas:
        vacinas_atuais.setdefault(grupo_clinico(vacina), vacina)
    for vacina in vacinas_atuais.values():
        if not vacina.proxima_dose:
            continue
        action = {'tipo': 'Vacina', 'titulo': vacina.nome, 'data': vacina.proxima_dose}
        if vacina.proxima_dose >= date.today():
            proximas_acoes.append(action)
        else:
            doses_a_revisar.append(action)
    for vacina in proximas_doses:
        action = {
            'tipo': 'Vacina',
            'titulo': vacina.nome,
            'data': vacina.aplicada_em,
        }
        if vacina.aplicada_em >= date.today():
            proximas_acoes.append(action)
        else:
            doses_a_revisar.append(action)
    ultima_vermifugacao = vermifugacoes[0] if vermifugacoes else None
    if ultima_vermifugacao and ultima_vermifugacao.next_due_on:
        action = {
            'tipo': 'Vermífugo',
            'titulo': ultima_vermifugacao.title,
            'data': ultima_vermifugacao.next_due_on,
        }
        if ultima_vermifugacao.next_due_on >= date.today():
            proximas_acoes.append(action)
        else:
            doses_a_revisar.append(action)
    proximas_acoes.sort(key=lambda item: item['data'])
    doses_a_revisar.sort(key=lambda item: item['data'])

    tutor_nome = None
    if animal.owner and animal.owner.name:
        tutor_nome = animal.owner.name.split()[0]

    track_event('health_card_viewed', feature='health_card', channel='public')

    from services.selo_prefeitura import selo_atual, situacao_do_selo

    return render_template(
        'animais/carteirinha_publica.html',
        animal=animal,
        selo_prefeitura=situacao_do_selo(selo_atual(animal)),
        proximas_acoes=proximas_acoes,
        doses_a_revisar=doses_a_revisar,
        vacinas_recentes=vacinas_aplicadas[:6],
        vermifugacoes_recentes=vermifugacoes[:6],
        ultima_vermifugacao=ultima_vermifugacao,
        tutor_nome=tutor_nome,
        hoje=date.today(),
        signup_url=url_for('register', audience='tutor'),
    )


@bp.route('/carteirinha/<token>/qr.png')
def carteirinha_qr(token):
    animal = (
        Animal.query
        .filter_by(public_token=token)
        .filter(Animal.removido_em.is_(None))
        .first_or_404()
    )
    url = url_for('carteirinha_publica', token=animal.public_token, _external=True)
    img = qrcode.make(url)
    buffer = BytesIO()
    img.save(buffer)
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')
