"""Views do domínio vacina_pmo_routes (migrado do app.py)."""
from flask import Blueprint
from PIL import Image
import os, requests, threading as _pmo_threading, uuid
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from extensions import csrf, db
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from io import BytesIO
from models import Animal, Endereco, User, Vacina
from time_utils import BR_TZ
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

# Helpers ainda hospedados no app.py (realocação em fases futuras).
from app import (  # noqa: E402
    PROJECT_ROOT,
    _export_vacina_pmo_pet_certificate_pdf,
    _first_access_url_for_user,
    _pmo_animal_booster_guidance,
    _pmo_booster_countdown_label,
    _pmo_doses_compile_lock,
    _pmo_protocol_label,
    _pmo_status_context,
    _pmo_status_labels,
    _pmo_status_sync_lock,
)

bp = Blueprint("vacina_pmo_routes", __name__)


def get_blueprint():
    return bp


def upload_to_s3(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.upload_to_s3.
    import app as app_module
    return app_module.upload_to_s3(*args, **kwargs)



@bp.route('/vacina-pmo')
@login_required
def vacina_pmo():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    # datetime resolvido via módulo app em tempo de request: testes congelam a
    # data com monkeypatch de app.datetime (contrato do antigo lazy_view).
    import app as app_module

    today = app_module.datetime.now(BR_TZ).date().isoformat()
    return render_template('vacina_pmo/dashboard.html', today=today)


@bp.route('/vacina-pmo/agenda')
@login_required
def vacina_pmo_agenda():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    from models import PmoVaccinationVisit
    from sqlalchemy import func
    from datetime import datetime, date as _date
    rows = (
        db.session.query(
            PmoVaccinationVisit.sheet_title,
            PmoVaccinationVisit.shift,
            func.count(PmoVaccinationVisit.id).label('tutores'),
            func.sum(PmoVaccinationVisit.dogs).label('caes'),
            func.sum(PmoVaccinationVisit.cats).label('gatos'),
        )
        .group_by(PmoVaccinationVisit.sheet_title, PmoVaccinationVisit.shift)
        .all()
    )
    _weekdays_pt = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    dias = []
    for r in rows:
        try:
            dt = datetime.strptime(r.sheet_title, '%d/%m/%Y').date()
            weekday = _weekdays_pt[dt.weekday()]
        except Exception:
            dt = None
            weekday = ''
        date_str = r.sheet_title.replace('/', '-')
        turno = 'manha' if r.shift == 'Manha' else 'tarde'
        shift_label = 'Manhã' if r.shift == 'Manha' else 'Tarde'
        dias.append(dict(
            sheet_title=r.sheet_title,
            date=dt,
            weekday=weekday,
            date_str=date_str,
            turno=turno,
            shift_label=shift_label,
            tutores=r.tutores,
            caes=int(r.caes or 0),
            gatos=int(r.gatos or 0),
        ))
    dias.sort(key=lambda x: x['date'] or _date.min, reverse=True)
    return render_template('vacina_pmo/agenda.html', dias=dias)


@bp.route('/vacina-pmo/c/<token>', methods=['GET', 'POST'])
def vacina_pmo_public(token):
    from services.vacina_pmo_service import (
        format_pmo_phone_for_login,
        get_pmo_educational_video,
        get_vacina_pmo_public_visit,
        get_vacina_pmo_evaluation_payload,
        save_vacina_pmo_evaluation,
    )

    visit = get_vacina_pmo_public_visit(token)
    if not visit:
        abort(404)

    evaluation_saved = False
    evaluation_error = ""
    if request.method == 'POST':
        try:
            rating = int(request.form.get('rating') or 0)
            comment = request.form.get('comment') or ""
            visit = save_vacina_pmo_evaluation(
                token,
                rating,
                comment,
                registration_rating=request.form.get('registration_rating'),
                service_rating=request.form.get('service_rating'),
                information_rating=request.form.get('information_rating'),
                survey_rating=request.form.get('survey_rating'),
            )
            evaluation_saved = True
        except Exception as exc:
            evaluation_error = str(exc)

    primary_pet_card_url = None
    for pmo_animal in visit.animals:
        primary_pet_card_url = primary_pet_card_url or url_for(
            'vacina_pmo_public_pet',
            token=token,
            pmo_animal_id=pmo_animal.id,
        )
    status_labels = _pmo_status_labels()
    first_access_url = url_for('first_access', next=request.path, _external=True)
    if getattr(visit, 'tutor_user', None):
        first_access_url = _first_access_url_for_user(
            visit.tutor_user,
            next_url=request.path,
            _external=True,
        )

    return render_template(
        'vacina_pmo/public_certificate.html',
        visit=visit,
        token=token,
        login_phone=format_pmo_phone_for_login(visit.phone1 or visit.phone2),
        first_access_url=first_access_url,
        evaluation_saved=evaluation_saved,
        evaluation_error=evaluation_error,
        evaluation=get_vacina_pmo_evaluation_payload(visit),
        educational_video=get_pmo_educational_video(),
        primary_pet_card_url=primary_pet_card_url,
        status_labels=status_labels,
        protocol_label=_pmo_protocol_label(visit),
    )


@bp.route('/vacina-pmo/c/<token>/pet/<int:pmo_animal_id>')
def vacina_pmo_public_pet(token, pmo_animal_id):
    from services.vacina_pmo_service import get_vacina_pmo_public_visit

    visit = get_vacina_pmo_public_visit(token)
    if not visit:
        abort(404)

    pmo_animal = next((item for item in visit.animals if item.id == pmo_animal_id), None)
    if not pmo_animal:
        abort(404)

    animal = db.session.get(Animal, pmo_animal.animal_id) if pmo_animal.animal_id else None
    vaccines = []
    if animal:
        vaccines = (
            Vacina.query.filter_by(animal_id=animal.id)
            .order_by(Vacina.criada_em.desc())
            .all()
        )
        vaccines = sorted(
            vaccines,
            key=lambda item: (bool(item.aplicada), item.aplicada_em or date.min, item.criada_em or datetime.min),
            reverse=True,
        )

    campaign_vaccine = None
    for vaccine in vaccines:
        if pmo_animal.vaccine_id and vaccine.id == pmo_animal.vaccine_id:
            campaign_vaccine = vaccine
            break
        if not campaign_vaccine and (vaccine.tipo or "").startswith("Campanha PMO"):
            campaign_vaccine = vaccine

    effective_status = pmo_animal.status
    if campaign_vaccine and campaign_vaccine.aplicada:
        effective_status = "vacinado"
    status_context = _pmo_status_context(effective_status)

    next_booster_date = None
    if campaign_vaccine and campaign_vaccine.proxima_dose:
        next_booster_date = campaign_vaccine.proxima_dose
    elif visit.vaccine_date and effective_status == "vacinado":
        next_booster_date = visit.vaccine_date + relativedelta(years=1)
    booster_days_remaining = None
    booster_countdown_label = ""
    if next_booster_date:
        booster_days_remaining = (next_booster_date - date.today()).days
        booster_countdown_label = _pmo_booster_countdown_label(next_booster_date)

    if (request.args.get('format') or '').lower() == 'pdf':
        return _export_vacina_pmo_pet_certificate_pdf(
            visit=visit,
            pmo_animal=pmo_animal,
            campaign_vaccine=campaign_vaccine,
            effective_status=effective_status,
            next_booster_date=next_booster_date,
        )

    return render_template(
        'vacina_pmo/public_pet_card.html',
        visit=visit,
        token=token,
        pmo_animal=pmo_animal,
        animal=animal,
        vaccines=vaccines,
        campaign_vaccine=campaign_vaccine,
        effective_status=effective_status,
        status_context=status_context,
        next_booster_date=next_booster_date,
        booster_days_remaining=booster_days_remaining,
        booster_countdown_label=booster_countdown_label,
        educational_video={"url": "", "embed_url": ""},
        protocol_label=_pmo_protocol_label(visit),
    )


@bp.route('/vacina-pmo/sync', methods=['POST'])
@login_required
def vacina_pmo_sync():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import persist_vacina_pmo_rows, sync_vacina_pmo_sheet

        payload = request.get_json(silent=True) or {}
        result = sync_vacina_pmo_sheet(
            sheet_gid=(payload.get('sheet_gid') or '').strip(),
            sheet_title=(payload.get('sheet_title') or '').strip(),
            force_ai=bool(payload.get('force_ai')),
        )
        rows = persist_vacina_pmo_rows(
            result.rows,
            spreadsheet_id=result.spreadsheet_id,
            sheet_gid=result.sheet_gid,
            sheet_title=result.sheet_title,
        )
        return jsonify(
            {
                'success': True,
                'rows': rows,
                'spreadsheet_id': result.spreadsheet_id,
                'sheet_range': result.sheet_range,
                'sheet_gid': result.sheet_gid,
                'sheet_title': result.sheet_title,
            }
        )
    except Exception as exc:
        current_app.logger.exception("Falha ao sincronizar planilha Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/avaliacoes', methods=['GET'])
@login_required
def vacina_pmo_avaliacoes():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import get_all_vacina_pmo_evaluations
        data = get_all_vacina_pmo_evaluations()
        return jsonify({'success': True, **data})
    except Exception as exc:
        current_app.logger.exception("Falha ao agregar avaliações Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/criar-dia', methods=['POST'])
@login_required
def vacina_pmo_criar_dia():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import criar_dia_vacinacao

        payload = request.get_json(silent=True) or {}
        result = criar_dia_vacinacao((payload.get('date') or '').strip())
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao criar dia de vacinação Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/webhook/atualizar-status', methods=['POST', 'GET'])
@csrf.exempt
def vacina_pmo_status_webhook():
    """Dispara a sincronização completa de status (Vacinação 2026) em background.

    Protegido por token (env PMO_SYNC_WEBHOOK_TOKEN) para ser chamado pelo Apps
    Script da planilha. Retorna na hora; o trabalho pesado roda numa thread, então
    não estoura o timeout do Heroku nem do UrlFetchApp.
    """
    import hmac

    expected = os.getenv('PMO_SYNC_WEBHOOK_TOKEN', '').strip()
    provided = (request.args.get('token') or request.headers.get('X-PMO-Token') or '').strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        abort(403)

    if not _pmo_status_sync_lock.acquire(blocking=False):
        return jsonify({
            'success': True,
            'running': True,
            'message': 'Uma sincronização de status já está em andamento.',
        })

    def _job():
        try:
            from scripts.sync_pmo_full_status import run_pmo_full_sync
            result = run_pmo_full_sync(apply=True, skip_sheet_sync=False)
            current_app.logger.info('[PMO webhook] Sincronização de status concluída: %s', result)
        except Exception:
            current_app.logger.exception('[PMO webhook] Falha na sincronização de status')
        finally:
            _pmo_status_sync_lock.release()

    _pmo_threading.Thread(target=_job, name='pmo-status-sync', daemon=True).start()
    return jsonify({'success': True, 'message': 'Atualização de status iniciada.'})


@bp.route('/vacina-pmo/webhook/compilar-doses', methods=['POST', 'GET'])
@csrf.exempt
def vacina_pmo_doses_webhook():
    """Compila o Controle de doses sob demanda (menu "Vacinação 2026" da planilha).

    Mesmo token do webhook de status (PMO_SYNC_WEBHOOK_TOKEN). Retorna na hora;
    a compilação roda numa thread e as colunas aparecem na planilha em seguida.
    """
    import hmac

    expected = os.getenv('PMO_SYNC_WEBHOOK_TOKEN', '').strip()
    provided = (request.args.get('token') or request.headers.get('X-PMO-Token') or '').strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        abort(403)

    if not _pmo_doses_compile_lock.acquire(blocking=False):
        return jsonify({
            'success': True,
            'running': True,
            'message': 'Uma compilação do Controle de doses já está em andamento.',
        })

    include_compiled = (request.args.get('completo') or '').strip().lower() in {'1', 'true', 'sim'}

    app_obj = current_app._get_current_object()

    def _job():
        try:
            from services.vacina_pmo_service import compile_controle_de_doses
            with app_obj.app_context():
                result = compile_controle_de_doses(include_compiled=include_compiled)
            app_obj.logger.info('[PMO webhook] Controle de doses compilado: %s', result)
        except Exception:
            app_obj.logger.exception('[PMO webhook] Falha na compilação do Controle de doses')
        finally:
            _pmo_doses_compile_lock.release()

    _pmo_threading.Thread(target=_job, name='pmo-doses-compile', daemon=True).start()
    return jsonify({'success': True, 'message': 'Compilação do Controle de doses iniciada.'})


@bp.route('/vacina-pmo/painel')
@login_required
def vacina_pmo_painel():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    from services.vacina_pmo_service import get_vacina_pmo_kpis, get_controle_de_doses_summary
    try:
        kpis = get_vacina_pmo_kpis()
    except Exception as exc:
        current_app.logger.exception("Falha ao montar painel Vacina PMO")
        kpis = {'error': str(exc)}
    try:
        doses = get_controle_de_doses_summary()
    except Exception as exc:
        current_app.logger.exception("Falha ao ler Controle de doses PMO")
        doses = {'error': str(exc)}
    try:
        from services.vacina_pmo_service import get_vacina_pmo_cobertura_summary
        cobertura = get_vacina_pmo_cobertura_summary()
    except Exception as exc:
        current_app.logger.exception("Falha ao montar cobertura ativa PMO")
        cobertura = {'error': str(exc)}
    try:
        from services.vacina_pmo_service import get_pmo_frascos_ledger
        frascos = get_pmo_frascos_ledger()
    except Exception as exc:
        current_app.logger.exception("Falha ao montar controle de frascos PMO")
        frascos = {'error': str(exc)}
    return render_template(
        'vacina_pmo/painel.html', kpis=kpis, doses=doses, cobertura=cobertura, frascos=frascos
    )


@bp.route('/vacina-pmo/cobertura-ativa')
@login_required
def vacina_pmo_cobertura_ativa():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import get_vacina_pmo_cobertura_detail
        detail = get_vacina_pmo_cobertura_detail()
        return jsonify({'success': True, 'animals': detail})
    except Exception as exc:
        current_app.logger.exception("Falha ao buscar cobertura ativa PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/imprimir/<date_str>/<turno>')
@login_required
def vacina_pmo_imprimir(date_str, turno):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    from models import PmoVaccinationVisit
    sheet_title = date_str.replace('-', '/')
    shift_key = "Manha" if turno.lower().startswith("man") else "Tarde"
    shift_label = "Manhã" if shift_key == "Manha" else "Tarde"
    other_turno = "tarde" if shift_key == "Manha" else "manha"

    visits = (
        PmoVaccinationVisit.query
        .filter_by(sheet_title=sheet_title, shift=shift_key)
        .order_by(PmoVaccinationVisit.source_row.asc())
        .all()
    )
    return render_template(
        'vacina_pmo/imprimir.html',
        visits=visits,
        sheet_title=sheet_title,
        shift_label=shift_label,
        shift_key=shift_key,
        date_str=date_str,
        other_turno=other_turno,
    )


@bp.route('/vacina-pmo/sheets', methods=['GET'])
@login_required
def vacina_pmo_sheets():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import list_vacina_pmo_sheets

        return jsonify({'success': True, 'sheets': list_vacina_pmo_sheets()})
    except Exception as exc:
        current_app.logger.exception("Falha ao listar abas da planilha Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/state', methods=['GET'])
@login_required
def vacina_pmo_state():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import get_saved_vacina_pmo_rows

        return jsonify(
            {
                'success': True,
                **get_saved_vacina_pmo_rows(
                    sheet_gid=(request.args.get('sheet_gid') or '').strip(),
                    sheet_title=(request.args.get('sheet_title') or '').strip(),
                ),
            }
        )
    except Exception as exc:
        current_app.logger.exception("Falha ao carregar estado Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/route/optimize', methods=['POST'])
@login_required
def vacina_pmo_route_optimize():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import optimize_vacina_pmo_route

        payload = request.get_json(silent=True) or {}
        result = optimize_vacina_pmo_route(
            sheet_gid=(payload.get('sheet_gid') or '').strip(),
            sheet_title=(payload.get('sheet_title') or '').strip(),
            shift=(payload.get('shift') or '').strip(),
            created_by_id=current_user.id,
        )
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao otimizar rota Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/route/preview', methods=['POST'])
@login_required
def vacina_pmo_route_preview():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import preview_vacina_pmo_route

        payload = request.get_json(silent=True) or {}
        result = preview_vacina_pmo_route(
            sheet_gid=(payload.get('sheet_gid') or '').strip(),
            sheet_title=(payload.get('sheet_title') or '').strip(),
            shift=(payload.get('shift') or '').strip(),
        )
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao pré-visualizar rota Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/route/undo', methods=['POST'])
@login_required
def vacina_pmo_route_undo():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import undo_last_vacina_pmo_route_optimization

        payload = request.get_json(silent=True) or {}
        result = undo_last_vacina_pmo_route_optimization(
            sheet_gid=(payload.get('sheet_gid') or '').strip(),
            sheet_title=(payload.get('sheet_title') or '').strip(),
            shift=(payload.get('shift') or '').strip(),
        )
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao desfazer rota Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/animal/<int:animal_id>/status', methods=['POST'])
@login_required
def vacina_pmo_animal_status(animal_id):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import update_vacina_pmo_animal_status

        payload = request.get_json(silent=True) or {}
        row = update_vacina_pmo_animal_status(animal_id, (payload.get('status') or '').strip())
        return jsonify({'success': True, 'row': row})
    except Exception as exc:
        current_app.logger.exception("Falha ao salvar status de animal Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/animal/<int:animal_id>/name', methods=['POST'])
@login_required
def vacina_pmo_animal_name(animal_id):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import update_vacina_pmo_animal_name

        payload = request.get_json(silent=True) or {}
        row = update_vacina_pmo_animal_name(animal_id, payload.get('name') or '')
        return jsonify({'success': True, 'row': row})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao salvar nome de animal Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/animal/<int:animal_id>/photo', methods=['POST'])
@login_required
def vacina_pmo_animal_photo(animal_id):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)

    file = request.files.get('photo')
    if not file or not getattr(file, 'filename', ''):
        return jsonify({'success': False, 'message': 'Nenhuma foto enviada.'}), 400

    try:
        max_photo_bytes = 8 * 1024 * 1024
        file.stream.seek(0, os.SEEK_END)
        photo_size = file.stream.tell()
        file.stream.seek(0)
        if photo_size <= 0:
            return jsonify({'success': False, 'message': 'A foto enviada está vazia.'}), 400
        if photo_size > max_photo_bytes:
            return jsonify({
                'success': False,
                'message': 'A foto é muito grande. Use uma imagem de até 8 MB.',
            }), 413

        try:
            with Image.open(file.stream) as uploaded_image:
                uploaded_image.verify()
                image_format = (uploaded_image.format or '').upper()
        except Exception:
            return jsonify({
                'success': False,
                'message': 'O arquivo selecionado não é uma foto válida.',
            }), 400
        finally:
            file.stream.seek(0)

        if image_format not in {'JPEG', 'PNG', 'WEBP'}:
            return jsonify({
                'success': False,
                'message': 'Formato não compatível. Tire a foto novamente ou use JPG, PNG ou WebP.',
            }), 415

        from services.vacina_pmo_service import ensure_vacina_pmo_real_animal

        animal = ensure_vacina_pmo_real_animal(animal_id)
        if animal is None:
            return jsonify({
                'success': False,
                'message': 'Este animal ainda não tem cadastro vinculado para guardar a foto.',
            }), 400

        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        image_url = upload_to_s3(file, filename, folder='animals')
        if not image_url:
            return jsonify({'success': False, 'message': 'Falha ao enviar a imagem.'}), 502
        # Recusa o fallback local (efêmero no Heroku): sem armazenamento durável
        # a foto sumiria no próximo restart. Melhor avisar para tentar de novo.
        if not image_url.startswith('http'):
            current_app.logger.error("Foto PMO sem armazenamento durável (S3 indisponível): %s", image_url)
            return jsonify({
                'success': False,
                'message': 'Não foi possível guardar a foto agora. Tente novamente em instantes.',
            }), 502

        animal.image = image_url
        # Nova foto: zera o enquadramento salvo para exibir corretamente.
        animal.photo_rotation = 0
        animal.photo_zoom = 1.0
        animal.photo_offset_x = 0.0
        animal.photo_offset_y = 0.0
        db.session.commit()

        return jsonify({'success': True, 'image_url': image_url, 'animal_id': animal.id})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Falha ao salvar foto de animal Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/animal/<int:animal_id>/photo-src')
@login_required
def vacina_pmo_animal_photo_src(animal_id):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)

    from models import PmoVaccinationAnimal

    pmo_animal = PmoVaccinationAnimal.query.get_or_404(animal_id)
    animal = db.session.get(Animal, pmo_animal.animal_id) if pmo_animal.animal_id else None
    image_url = (animal.image or '').strip() if animal else ''
    if not image_url:
        abort(404)

    parsed = urlparse(image_url)
    if not parsed.scheme and image_url.startswith('/static/'):
        requested = (PROJECT_ROOT / image_url.lstrip('/')).resolve()
        uploads_root = (PROJECT_ROOT / 'static' / 'uploads').resolve()
        if not str(requested).startswith(str(uploads_root)):
            abort(404)
        return send_file(requested)

    if parsed.scheme not in {'http', 'https'}:
        abort(404)

    try:
        upstream = requests.get(image_url, timeout=8)
        upstream.raise_for_status()
    except requests.RequestException:
        current_app.logger.exception("Falha ao buscar foto PMO para video")
        abort(502)

    content_type = (upstream.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
    if content_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
        abort(415)
    if len(upstream.content) > 10 * 1024 * 1024:
        abort(413)

    return send_file(BytesIO(upstream.content), mimetype=content_type, max_age=3600)


@bp.route('/vacina-pmo/visit/<int:visit_id>/attended-by', methods=['POST'])
@login_required
def vacina_pmo_visit_attended_by(visit_id):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import update_vacina_pmo_visit_attended_by

        payload = request.get_json(silent=True) or {}
        row = update_vacina_pmo_visit_attended_by(visit_id, payload.get('attended_by'))
        return jsonify({'success': True, 'row': row})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao salvar 'atendido por' Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/visit/<int:visit_id>/losses', methods=['POST'])
@login_required
def vacina_pmo_visit_losses(visit_id):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import update_vacina_pmo_visit_losses

        payload = request.get_json(silent=True) or {}
        row = update_vacina_pmo_visit_losses(visit_id, payload.get('losses'))
        return jsonify({'success': True, 'row': row})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao salvar perdas Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/doses/compilar', methods=['POST'])
@login_required
def vacina_pmo_doses_compilar():
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import compile_controle_de_doses

        payload = request.get_json(silent=True) or {}
        result = compile_controle_de_doses(
            dry_run=bool(payload.get('dry_run')),
            include_compiled=bool(payload.get('include_compiled')),
        )
        return jsonify({'success': True, **result})
    except Exception as exc:
        current_app.logger.exception("Falha ao compilar Controle de doses PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/visit/<int:visit_id>/note', methods=['POST'])
@login_required
def vacina_pmo_visit_note(visit_id):
    if current_user.role not in ('admin', 'vacinador'):
        abort(403)
    try:
        from services.vacina_pmo_service import append_vacina_pmo_visit_note

        payload = request.get_json(silent=True) or {}
        row = append_vacina_pmo_visit_note(visit_id, payload.get('note'))
        return jsonify({'success': True, 'row': row})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Falha ao salvar observação Vacina PMO")
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.route('/vacina-pmo/solicitar', methods=['GET', 'POST'])
@login_required
def vacina_pmo_solicitar():
    from models import PmoVaccinationVisit
    from flask import session as flask_session

    user_animals = (
        Animal.query.filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.name)
        .all()
    )

    if not user_animals:
        flash(
            'Você precisa ter ao menos um animal cadastrado para solicitar a vacina antirrábica.',
            'warning',
        )
        return redirect(url_for('add_animal'))

    # Pré-preenche endereço do perfil
    from services.vacina_pmo_service import normalize_pmo_request_address

    _prof_street = ''
    _prof_number = ''
    _prof_complement = ''
    _prof_neighborhood = ''
    if current_user.endereco:
        _e = current_user.endereco
        _prof_street = _e.rua or ''
        _prof_number = _e.numero or ''
        _prof_complement = _e.complemento or ''
        _prof_neighborhood = _e.bairro or ''
    elif current_user.address:
        _profile_address = normalize_pmo_request_address({
            'address_street': current_user.address,
            'address_number': '',
            'address_complement': '',
            'address_neighborhood': '',
        })
        _prof_street = _profile_address['street']
        _prof_number = _profile_address['number']
        _prof_complement = _profile_address['complement']
        _prof_neighborhood = _profile_address['neighborhood']

    form_state = {
        'animal_ids': [],
        'tutor': current_user.name or '',
        'email': current_user.email or '',
        'cpf': current_user.cpf or '',
        'phone': current_user.phone or '',
        'phone2': current_user.phone2 or '',
        'address_street': _prof_street,
        'address_number': _prof_number,
        'address_complement': _prof_complement,
        'address_neighborhood': _prof_neighborhood,
        'save_address': False,
        'shift': '',
        'note': '',
    }
    animal_booster_guidance = _pmo_animal_booster_guidance(user_animals)

    if request.method == 'POST':
        from services.vacina_pmo_service import submit_vacina_pmo_request

        selected_ids = set(request.form.getlist('animal_ids', type=int))
        form_state['animal_ids'] = list(selected_ids)
        form_state['tutor'] = (request.form.get('tutor') or '').strip() or current_user.name
        form_state['email'] = (request.form.get('email') or '').strip() or current_user.email
        form_state['cpf'] = (request.form.get('cpf') or '').strip() or (current_user.cpf or '')
        form_state['phone'] = (request.form.get('phone') or '').strip()
        form_state['phone2'] = (request.form.get('phone2') or '').strip()
        form_state['address_street'] = (request.form.get('address_street') or '').strip()
        form_state['address_number'] = (request.form.get('address_number') or '').strip()
        form_state['address_complement'] = (request.form.get('address_complement') or '').strip()
        form_state['address_neighborhood'] = (request.form.get('address_neighborhood') or '').strip()
        form_state['shift'] = (request.form.get('shift') or '').strip()
        form_state['note'] = (request.form.get('note') or '').strip()
        save_address = request.form.get('save_address') == '1'
        form_state['save_address'] = save_address
        normalized_address = normalize_pmo_request_address(form_state)
        form_state['address_street'] = normalized_address['street']
        form_state['address_number'] = normalized_address['number']
        form_state['address_complement'] = normalized_address['complement']
        form_state['address_neighborhood'] = normalized_address['neighborhood']

        selected_animals = [a for a in user_animals if a.id in selected_ids]
        duplicate_cpf = None
        if form_state['cpf'] and form_state['cpf'] != (current_user.cpf or ''):
            duplicate_cpf = User.query.filter(User.cpf == form_state['cpf'], User.id != current_user.id).first()
        duplicate_email = None
        if form_state['email'] and form_state['email'] != (current_user.email or ''):
            duplicate_email = User.query.filter(User.email == form_state['email'], User.id != current_user.id).first()

        if not selected_animals:
            flash('Selecione ao menos um animal para vacinar.', 'danger')
        elif duplicate_cpf:
            flash('Este CPF já está cadastrado em outro tutor. Confira o número informado.', 'danger')
        elif duplicate_email:
            flash('Este e-mail já está cadastrado em outro tutor. Confira o e-mail informado.', 'danger')
        elif not form_state['phone']:
            flash('Informe um telefone para contato.', 'danger')
        elif not form_state['address_street'] or not form_state['address_neighborhood']:
            flash('Informe rua e bairro onde os animais serão vacinados.', 'danger')
        elif form_state['shift'] not in ('Manha', 'Tarde'):
            flash('Selecione o turno preferencial (Manhã ou Tarde).', 'danger')
        else:
            dogs = 0
            cats = 0
            names = []
            for animal in selected_animals:
                names.append(animal.name or 'Sem nome')
                species_name = (animal.species.name if animal.species else '').lower()
                if 'gat' in species_name:
                    cats += 1
                else:
                    dogs += 1

            payload = {
                'tutor': form_state['tutor'],
                'cpf': form_state['cpf'],
                'phone': form_state['phone'],
                'phone2': form_state['phone2'],
                'email': form_state['email'],
                'address_street': form_state['address_street'],
                'address_number': form_state['address_number'],
                'address_complement': form_state['address_complement'],
                'address_neighborhood': form_state['address_neighborhood'],
                'dogs': dogs,
                'cats': cats,
                'animal_names': ', '.join(names),
                'note': form_state['note'],
                'shift': form_state['shift'],
                'user_id': current_user.id,
            }

            try:
                result = submit_vacina_pmo_request(payload)

                if save_address:
                    endereco = current_user.endereco or Endereco()
                    endereco.rua = normalized_address['street'] or None
                    endereco.numero = normalized_address['number'] or None
                    endereco.complemento = normalized_address['complement'] or None
                    endereco.bairro = normalized_address['neighborhood'] or None
                    if current_user.endereco is None:
                        db.session.add(endereco)
                        db.session.flush()
                        current_user.endereco_id = endereco.id
                        current_user.endereco = endereco
                    current_user.address = normalized_address['full']
                current_user.name = form_state['tutor'] or current_user.name
                if form_state['email']:
                    current_user.email = form_state['email']
                current_user.phone = form_state['phone'] or current_user.phone
                current_user.phone2 = form_state['phone2'] or current_user.phone2
                current_user.cpf = form_state['cpf'] or current_user.cpf
                db.session.commit()
                flask_session['pmo_solicitar_success'] = result.get('public_token') or True
                return redirect(url_for('vacina_pmo_solicitar'))
            except Exception as exc:
                current_app.logger.exception("Falha ao enviar solicitação Vacina PMO")
                flash(f'Não foi possível enviar a solicitação agora: {exc}', 'danger')

    from services.vacina_pmo_service import PMO_REQUEST_SHEET_DEFAULT_TITLE, PMO_REQUEST_SHEET_TITLE_ENV
    request_sheet_title = os.getenv(PMO_REQUEST_SHEET_TITLE_ENV, PMO_REQUEST_SHEET_DEFAULT_TITLE)
    historico = (
        PmoVaccinationVisit.query
        .filter_by(tutor_user_id=current_user.id)
        .filter(PmoVaccinationVisit.sheet_title == request_sheet_title)
        .order_by(PmoVaccinationVisit.updated_at.desc(), PmoVaccinationVisit.synced_at.desc())
        .all()
    )
    from flask import session as flask_session
    success_token = flask_session.pop('pmo_solicitar_success', None)
    return render_template(
        'vacina_pmo/solicitar.html',
        user_animals=user_animals,
        form_state=form_state,
        historico=historico,
        pmo_protocol_label=_pmo_protocol_label,
        animal_booster_guidance=animal_booster_guidance,
        success_token=success_token,
    )


@bp.route('/castracao-pmo/solicitar', methods=['GET', 'POST'])
@login_required
def castracao_pmo_solicitar():
    from flask import session as flask_session
    from models import PmoCastrationRequest
    from services.castracao_pmo_service import (
        PMO_CASTRATION_REQUEST_SHEET_DEFAULT_TITLE,
        PMO_CASTRATION_REQUEST_SHEET_TITLE_ENV,
        build_castration_animal_payloads,
        submit_castracao_pmo_request,
    )
    from services.vacina_pmo_service import normalize_pmo_request_address

    user_animals = (
        Animal.query.filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.name)
        .all()
    )

    if not user_animals:
        flash(
            'Você precisa ter ao menos um animal cadastrado para solicitar a castração PMO.',
            'warning',
        )
        return redirect(url_for('add_animal'))

    _prof_street = ''
    _prof_number = ''
    _prof_complement = ''
    _prof_neighborhood = ''
    if current_user.endereco:
        _e = current_user.endereco
        _prof_street = _e.rua or ''
        _prof_number = _e.numero or ''
        _prof_complement = _e.complemento or ''
        _prof_neighborhood = _e.bairro or ''
    elif current_user.address:
        _profile_address = normalize_pmo_request_address({
            'address_street': current_user.address,
            'address_number': '',
            'address_complement': '',
            'address_neighborhood': '',
        })
        _prof_street = _profile_address['street']
        _prof_number = _profile_address['number']
        _prof_complement = _profile_address['complement']
        _prof_neighborhood = _profile_address['neighborhood']

    form_state = {
        'animal_ids': [],
        'tutor': current_user.name or '',
        'email': current_user.email or '',
        'cpf': current_user.cpf or '',
        'phone': current_user.phone or '',
        'phone2': current_user.phone2 or '',
        'address_street': _prof_street,
        'address_number': _prof_number,
        'address_complement': _prof_complement,
        'address_neighborhood': _prof_neighborhood,
        'save_address': False,
        'preferred_contact': '',
        'female_status': '',
        'health_notes': '',
        'note': '',
        'consent': False,
    }

    if request.method == 'POST':
        selected_ids = set(request.form.getlist('animal_ids', type=int))
        form_state['animal_ids'] = list(selected_ids)
        form_state['tutor'] = (request.form.get('tutor') or '').strip() or current_user.name
        form_state['email'] = (request.form.get('email') or '').strip() or current_user.email
        form_state['cpf'] = (request.form.get('cpf') or '').strip() or (current_user.cpf or '')
        form_state['phone'] = (request.form.get('phone') or '').strip()
        form_state['phone2'] = (request.form.get('phone2') or '').strip()
        form_state['address_street'] = (request.form.get('address_street') or '').strip()
        form_state['address_number'] = (request.form.get('address_number') or '').strip()
        form_state['address_complement'] = (request.form.get('address_complement') or '').strip()
        form_state['address_neighborhood'] = (request.form.get('address_neighborhood') or '').strip()
        form_state['preferred_contact'] = (request.form.get('preferred_contact') or '').strip()
        form_state['female_status'] = (request.form.get('female_status') or '').strip()
        form_state['health_notes'] = (request.form.get('health_notes') or '').strip()
        form_state['note'] = (request.form.get('note') or '').strip()
        form_state['consent'] = request.form.get('consent') == '1'
        save_address = request.form.get('save_address') == '1'
        form_state['save_address'] = save_address
        normalized_address = normalize_pmo_request_address(form_state)
        form_state['address_street'] = normalized_address['street']
        form_state['address_number'] = normalized_address['number']
        form_state['address_complement'] = normalized_address['complement']
        form_state['address_neighborhood'] = normalized_address['neighborhood']

        selected_animals = [a for a in user_animals if a.id in selected_ids]
        duplicate_cpf = None
        if form_state['cpf'] and form_state['cpf'] != (current_user.cpf or ''):
            duplicate_cpf = User.query.filter(User.cpf == form_state['cpf'], User.id != current_user.id).first()
        duplicate_email = None
        if form_state['email'] and form_state['email'] != (current_user.email or ''):
            duplicate_email = User.query.filter(User.email == form_state['email'], User.id != current_user.id).first()

        already_neutered = [a.name or 'Sem nome' for a in selected_animals if a.neutered is True]
        if not selected_animals:
            flash('Selecione ao menos um animal para castrar.', 'danger')
        elif already_neutered:
            flash(
                'Remova da solicitação animal já marcado como castrado: ' + ', '.join(already_neutered),
                'danger',
            )
        elif duplicate_cpf:
            flash('Este CPF já está cadastrado em outro tutor. Confira o número informado.', 'danger')
        elif duplicate_email:
            flash('Este e-mail já está cadastrado em outro tutor. Confira o e-mail informado.', 'danger')
        elif not form_state['phone']:
            flash('Informe um telefone para contato.', 'danger')
        elif not form_state['address_street'] or not form_state['address_neighborhood']:
            flash('Informe rua e bairro do tutor.', 'danger')
        elif form_state['preferred_contact'] not in ('WhatsApp', 'Ligação', 'Indiferente'):
            flash('Selecione a preferência de contato.', 'danger')
        elif not form_state['consent']:
            flash('Confirme a ciência para enviar a solicitação.', 'danger')
        else:
            payload = {
                'tutor': form_state['tutor'],
                'cpf': form_state['cpf'],
                'phone': form_state['phone'],
                'phone2': form_state['phone2'],
                'email': form_state['email'],
                'address_street': form_state['address_street'],
                'address_number': form_state['address_number'],
                'address_complement': form_state['address_complement'],
                'address_neighborhood': form_state['address_neighborhood'],
                'preferred_contact': form_state['preferred_contact'],
                'female_status': form_state['female_status'],
                'health_notes': form_state['health_notes'],
                'note': form_state['note'],
                'animals': build_castration_animal_payloads(selected_animals),
                'user_id': current_user.id,
            }

            try:
                result = submit_castracao_pmo_request(payload)

                if save_address:
                    endereco = current_user.endereco or Endereco()
                    endereco.rua = normalized_address['street'] or None
                    endereco.numero = normalized_address['number'] or None
                    endereco.complemento = normalized_address['complement'] or None
                    endereco.bairro = normalized_address['neighborhood'] or None
                    if current_user.endereco is None:
                        db.session.add(endereco)
                        db.session.flush()
                        current_user.endereco_id = endereco.id
                        current_user.endereco = endereco
                    current_user.address = normalized_address['full']
                current_user.name = form_state['tutor'] or current_user.name
                if form_state['email']:
                    current_user.email = form_state['email']
                current_user.phone = form_state['phone'] or current_user.phone
                current_user.phone2 = form_state['phone2'] or current_user.phone2
                current_user.cpf = form_state['cpf'] or current_user.cpf
                db.session.commit()
                flask_session['pmo_castracao_solicitar_success'] = result.get('public_token') or True
                return redirect(url_for('castracao_pmo_solicitar'))
            except Exception as exc:
                current_app.logger.exception("Falha ao enviar solicitação Castração PMO")
                flash(f'Não foi possível enviar a solicitação agora: {exc}', 'danger')

    request_sheet_title = os.getenv(
        PMO_CASTRATION_REQUEST_SHEET_TITLE_ENV,
        PMO_CASTRATION_REQUEST_SHEET_DEFAULT_TITLE,
    )
    historico = (
        PmoCastrationRequest.query
        .filter_by(tutor_user_id=current_user.id)
        .filter(PmoCastrationRequest.sheet_title == request_sheet_title)
        .order_by(PmoCastrationRequest.updated_at.desc(), PmoCastrationRequest.synced_at.desc())
        .all()
    )
    success_token = flask_session.pop('pmo_castracao_solicitar_success', None)
    return render_template(
        'castracao_pmo/solicitar.html',
        user_animals=user_animals,
        form_state=form_state,
        historico=historico,
        success_token=success_token,
    )

