"""Views do domínio pacientes_routes (migrado do app.py)."""
import qrcode
from flask import Blueprint
import os, re, secrets, unicodedata, uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from extensions import csrf, db
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
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
from services.animal_search import search_animals
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
        is_admin_user = _is_admin()
        vet_authorized = current_user.is_authenticated and is_veterinarian(current_user)
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
    if tutor_name_query:
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
        pmo_dates=pmo_dates,
        is_admin=_is_admin(),
        show_all=show_all,
        scope=scope,
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_template('animais/_animals_grid.html', **context)
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
    clinica = current_user.veterinario.clinica if current_user.veterinario else None
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
    veterinario = current_user.veterinario if current_user.veterinario else None
    return render_template(template, animal=animal, tutor=tutor, clinica=clinica,
                           data_atual=data_atual, veterinario=veterinario, printing_user=current_user)


@bp.route('/termo/<int:animal_id>/<tipo>')
@login_required
def gerar_termo(animal_id, tipo):
    """Gera um termo específico para um animal."""
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    veterinario = current_user.veterinario
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

    def _load_consultas():
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
        return consultas_query.order_by(Consulta.created_at.desc()).all()

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
    return render_template(
        'animais/ficha_animal.html',
        animal=animal,
        tutor=tutor,
        events_url=events_url,
        history_url=history_url,
    )


@bp.route('/animal/<int:animal_id>/documentos', methods=['POST'])
@login_required
def upload_document(animal_id):
    animal = get_animal_or_404(animal_id)
    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem enviar documentos.', 'danger')
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
            is_veterinarian(current_user)
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
    is_active_vet = is_veterinarian(current_user)
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
                tutor.email,
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
                'email': tutor.email,
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
        name = request.form.get('tutor_name') or request.form.get('name')
        email = request.form.get('tutor_email') or request.form.get('email')

        if not name or not email:
            message = 'Nome e e‑mail são obrigatórios.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning')
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        if User.query.filter_by(email=email).first():
            message = 'Já existe um tutor com esse e‑mail.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning')
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        novo = User(
            name=name.strip(),
            email=email.strip(),
            role='adotante',  # padrão inicial
            clinica_id=current_user_clinic_id(),
            added_by=current_user,
            is_private=True,
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

        required_address_labels = {
            'rua': 'Rua',
            'cidade': 'Cidade',
            'estado': 'Estado',
        }

        required_missing = [
            label for key, label in required_address_labels.items()
            if not (request.form.get(key) or '').strip()
        ]

        if required_missing:
            message = 'Preencha os campos obrigatórios do endereço: ' + ', '.join(required_missing) + '.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning'), 400
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        endereco = Endereco(
            cep=cep,
            rua=rua,
            numero=numero,
            complemento=complemento,
            bairro=bairro,
            cidade=cidade,
            estado=estado
        )
        if not _update_coordinates_from_request(endereco):
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
        db.session.commit()

        if request.accept_mimetypes.accept_json:
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
                message='Tutor criado com sucesso!',
                category='success',
                html=html,
                tutor={
                    'id': novo.id,
                    'name': novo.name or f'Tutor #{novo.id}',
                    'display_name': novo.name or f'Tutor #{novo.id}',
                    'email': novo.email,
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

    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem excluir tutores.', 'danger')
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
        flash(f'Erro ao excluir tutor: {str(e)}', 'danger')

    return redirect(url_for('tutores'))


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

    # 📋 Campos básicos (exceto CPF)
    for field in ['name', 'email', 'phone', 'rg']:
        value = request.form.get(field)
        if value:
            setattr(user, field, value)

    # CPF precisa ser único
    cpf_val = request.form.get('cpf')
    if cpf_val:
        cpf_val = cpf_val.strip()
        if cpf_val != (user.cpf or ''):
            existing = User.query.filter(User.cpf == cpf_val, User.id != user.id).first()
            if existing:
                message = 'CPF já cadastrado para outro tutor.'
                if wants_json:
                    return jsonify(success=False, message=message, category='danger'), 400
                flash(message, 'danger')
                return redirect(request.referrer or url_for('index'))
        user.cpf = cpf_val

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
        print(f"❌ ERRO ao salvar tutor: {e}")
        message = f'Ocorreu um erro ao salvar: {str(e)}'
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


@bp.route('/ficha_tutor/<int:tutor_id>')
@login_required
def ficha_tutor(tutor_id):
    # Restrição de acesso — profissionais clínicos OU donos de casa de ração
    is_store_owner = CasaDeRacao.query.filter_by(owner_id=current_user.id).first() is not None
    if not has_professional_access(current_user) and not is_store_owner:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    can_consult = has_professional_access(current_user)

    # Dados do tutor
    tutor = get_user_or_404(tutor_id)

    # Lista de animais do tutor (com species e breed carregados)
    animais = Animal.query.options(
        joinedload(Animal.species),
        joinedload(Animal.breed)
    ).filter_by(user_id=tutor.id).order_by(Animal.name).all()

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

    return render_template(
        'animais/tutor_detail.html',
        tutor=tutor,
        endereco=tutor.endereco,
        animais=animais,
        current_year=current_year,
        species_list=species_list,
        breed_map=breed_map,
        tutor_form=tutor_form,
        animal_forms=animal_forms,
        new_animal_form=new_animal_form,
        can_consult=can_consult,
    )


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

    if not is_veterinarian(current_user):
        message = 'Apenas veterinários podem editar dados do animal.'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        flash(message, 'danger')
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
            queue_message('ID de espécie inválido.', 'warning')

    # Raça (relacional)
    breed_id = request.form.get('breed_id')
    if breed_id:
        try:
            animal.breed_id = int(breed_id)
        except ValueError:
            queue_message('ID de raça inválido.', 'warning')

    # Peso
    peso_valor = request.form.get('peso')
    if peso_valor:
        try:
            animal.peso = float(peso_valor)
        except ValueError:
            queue_message('Peso inválido. Deve ser um número.', 'warning')
    else:
        animal.peso = None

    # Data de nascimento ou idade
    dob_str = request.form.get('date_of_birth')
    age_input = request.form.get('age')
    age_unit_input = request.form.get('age_unit')
    idade_numero = None
    if dob_str:
        try:
            animal.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
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

    # Upload de imagem
    if 'image' in request.files and request.files['image'].filename != '':
        image_file = request.files['image']
        original_filename = secure_filename(image_file.filename)
        filename = f"{uuid.uuid4().hex}_{original_filename}"
        image_url = upload_to_s3(image_file, filename, folder="animals")
        animal.image = image_url

    try:
        animal.photo_rotation = int(request.form.get('photo_rotation', animal.photo_rotation or 0))
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
        message = f'Ocorreu um erro ao salvar: {str(e)}'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 500
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    message = 'Dados do animal atualizados com sucesso!'
    if wants_json:
        payload = dict(success=True, message=message, animal_name=animal.name, category='success')
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
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

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
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

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

    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if racao.created_by and racao.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

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


@bp.route("/animal/<int:animal_id>/vacinas", methods=["POST"])
def salvar_vacinas(animal_id):
    data = request.get_json(silent=True) or {}

    if not data or "vacinas" not in data:
        return jsonify({"success": False, "error": "Dados incompletos"}), 400

    try:
        animal = Animal.query.get_or_404(animal_id)
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
def imprimir_vacinas(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else None
    if not veterinario and current_user.is_authenticated and getattr(current_user, "worker", None) == "veterinario":
        veterinario = current_user
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
    return render_template("orcamentos/imprimir_vacinas.html", animal=animal, clinica=clinica, veterinario=veterinario)


@bp.route('/vacina/<int:vacina_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_vacina(vacina_id):
    vacina = Vacina.query.get_or_404(vacina_id)

    if not (
        is_veterinarian(current_user, require_membership=False)
        or getattr(current_user, 'worker', None) == 'veterinario'
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
                return ''.join(
                    c for c in unicodedata.normalize('NFD', txt.lower())
                    if unicodedata.category(c) != 'Mn'
                )

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
        tutor_id = request.form.get('tutor_id', type=int)
        tutor = get_user_or_404(tutor_id)
        nome_animal = (request.form.get('name') or '').strip()

        dob_str = request.form.get('date_of_birth')
        dob = None
        idade_numero = None
        age_unit_input = request.form.get('age_unit')
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Data de nascimento inválida. Use AAAA‑MM‑DD.', 'warning')
                return redirect(url_for('ficha_tutor', tutor_id=tutor.id))
        else:
            age_input = request.form.get('age')
            if age_input:
                try:
                    idade_numero = int(age_input)
                    unidade_norm = _normalizar_unidade_idade(age_unit_input)
                    if unidade_norm == 'meses':
                        dob = date.today() - relativedelta(months=idade_numero)
                    else:
                        dob = date.today() - relativedelta(years=idade_numero)
                except ValueError:
                    flash('Idade inválida. Deve ser um número inteiro.', 'warning')
                    return redirect(url_for('ficha_tutor', tutor_id=tutor.id))

        idade_registrada = None
        if dob:
            delta = relativedelta(date.today(), dob)
            if delta.years > 0:
                idade_registrada = _formatar_idade(delta.years, 'anos')
            else:
                idade_registrada = _formatar_idade(delta.months, 'meses')
        elif idade_numero is not None:
            idade_registrada = _formatar_idade(idade_numero, age_unit_input)

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

        microchip_number = (request.form.get('microchip_number') or '').strip() or None

        duplicate_filters = [
            Animal.user_id == tutor.id,
            func.lower(Animal.name) == func.lower(nome_animal),
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
        if duplicate_conditions:
            existing_animal = (
                Animal.query.filter(*duplicate_filters)
                .filter(or_(*duplicate_conditions))
                .first()
            )

        if existing_animal:
            message = 'Já existe um animal com os mesmos dados para este tutor recentemente cadastrado.'
            flash(message, 'warning')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (
                request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
            ):
                return (
                    jsonify(
                        message=message,
                        category='warning',
                        redirect=url_for('ficha_animal', animal_id=existing_animal.id),
                    ),
                    409,
                )
            return redirect(url_for('ficha_animal', animal_id=existing_animal.id))

        # Criação do animal
        animal = Animal(
            name=nome_animal,
            species_id=species_id,
            breed_id=breed_id,
            sex=request.form.get('sex'),
            date_of_birth=dob,
            age=idade_registrada,
            microchip_number=microchip_number,
            peso=peso,
            health_plan=request.form.get('health_plan'),
            neutered=neutered,
            user_id=tutor.id,
            added_by_id=current_user.id,
            clinica_id=current_user_clinic_id(),
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
            clinica_id=current_user_clinic_id(),
            status='in_progress'
        )
        db.session.add(consulta)
        db.session.commit()

        # Retorna conteúdo em JSON apenas quando o cliente realmente
        # priorizar "application/json" ou quando for uma requisição AJAX.
        prefers_json = (
            request.accept_mimetypes['application/json'] >
            request.accept_mimetypes['text/html']
        )
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if prefers_json or is_ajax:
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

            animal_payload = {
                'id': animal.id,
                'name': animal.name,
                'species': animal.species.name if animal.species else None,
                'breed': animal.breed.name if animal.breed else None,
                'sex': animal.sex,
                'image': animal.image,
                'photo_offset_x': animal.photo_offset_x,
                'photo_offset_y': animal.photo_offset_y,
                'photo_rotation': animal.photo_rotation,
                'photo_zoom': animal.photo_zoom,
                'links': {
                    'consulta': url_for('consulta_direct', animal_id=animal.id),
                    'ficha': url_for('ficha_animal', animal_id=animal.id),
                    'delete': url_for('deletar_animal', animal_id=animal.id),
                }
            }
            return jsonify(
                message='Animal cadastrado com sucesso!',
                category='success',
                html=html,
                animal=animal_payload
            )

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

    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem realizar essa ação.', 'danger')
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
        flash(f'Erro ao marcar como falecido: {str(e)}', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=f'Erro ao marcar como falecido: {str(e)}', category='danger'), 400

    return redirect(url_for('ficha_animal', animal_id=animal.id))


@bp.route('/animal/<int:animal_id>/reverter_falecimento', methods=['POST'])
@login_required
def reverter_falecimento(animal_id):
    if not is_veterinarian(current_user):
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

    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem excluir animais definitivamente.', 'danger')
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
        flash(f'Erro ao excluir: {str(e)}', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=f'Erro ao excluir: {str(e)}', category='danger'), 400

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
    is_clinic = bool(getattr(animal, "clinica_id", None) and cu.clinica_id == animal.clinica_id)
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
    flash('Carteirinha digital desativada. O link antigo deixou de funcionar.', 'info')
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
        normalized = ''.join(
            char for char in unicodedata.normalize('NFD', raw)
            if unicodedata.category(char) != 'Mn'
        )
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

    return render_template(
        'animais/carteirinha_publica.html',
        animal=animal,
        proximas_acoes=proximas_acoes,
        doses_a_revisar=doses_a_revisar,
        vacinas_recentes=vacinas_aplicadas[:6],
        vermifugacoes_recentes=vermifugacoes[:6],
        ultima_vermifugacao=ultima_vermifugacao,
        tutor_nome=tutor_nome,
        hoje=date.today(),
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
