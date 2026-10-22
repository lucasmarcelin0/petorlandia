"""Prontuário hospitalar: acesso da equipe, execução e documentos por clínica."""
from datetime import timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from extensions import db
from models import Animal, Clinica, Consulta, User, Veterinario
from models.internacao import (
    Internacao, InternacaoEvolucao, InternacaoEvento, InternacaoOcorrencia,
    InternacaoPrescricao, InternacaoRegistro,
)
from services import internacao as hospital
from services.internacao_access import (
    clinicas_internacao, pode_acessar_internacao, pode_operar_internacao,
    pode_prescrever_internacao, pode_ser_responsavel_internacao,
)
from time_utils import BR_TZ, normalize_to_utc, utcnow

bp = Blueprint('internacao', __name__, url_prefix='/internacao')


def get_blueprint():
    return bp


def _utc(value):
    """Os novos registros são UTC; SQLite devolve-os sem tzinfo."""
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


@bp.app_template_filter('internacao_datetime')
def format_datetime(value):
    return _utc(value).astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M') if value else '—'


@bp.app_template_filter('internacao_input')
def format_datetime_input(value):
    return _utc(value).astimezone(BR_TZ).strftime('%Y-%m-%dT%H:%M') if value else ''


@bp.app_template_filter('internacao_date')
def format_date(value):
    return _utc(value).astimezone(BR_TZ).strftime('%Y-%m-%d') if value else ''


@bp.app_template_filter('internacao_fim')
def prescription_effective_end(prescription):
    end = _utc(prescription.fim_em)
    return min(end, _utc(prescription.suspensa_em)) if prescription.suspensa_em else end


@bp.app_template_filter('internacao_iso')
def format_iso(value):
    return _utc(value).isoformat() if value else ''


@bp.app_template_filter('internacao_hora')
def format_time(value):
    return _utc(value).astimezone(BR_TZ).strftime('%H:%M') if value else ''


@bp.app_context_processor
def hospital_context():
    return {'pode_acessar_internacao': pode_acessar_internacao,
            'idempotency_key': lambda: str(uuid4())}


SESSION_CLINIC_KEY = 'internacao_clinica_id'
ADMISSION_LIST_LIMIT = 500
HISTORY_WINDOW = timedelta(hours=24)


def _next_full_hour(at):
    """Primeiro horário redondo (hora cheia de Brasília) a partir de ``at``."""
    local = _utc(at).astimezone(BR_TZ)
    rounded = local.replace(minute=0, second=0, microsecond=0)
    if rounded < local:
        rounded += timedelta(hours=1)
    return rounded.astimezone(timezone.utc)


def _dose_window(dose, at, tolerance):
    """Situação de horário da dose: 'antecipada', 'no_horario' ou 'atrasada'."""
    expected = _utc(dose.prevista_para)
    if at < expected - tolerance:
        return 'antecipada'
    if at > expected + tolerance:
        return 'atrasada'
    return 'no_horario'


def _form_error(target, message):
    """Erro exibido dentro do formulário que o originou, após recarregar a tela."""
    g.ih_erro = {'alvo': target, 'mensagem': message}


class _PrescriberRequired(Exception):
    def __init__(self, episode_id):
        super().__init__(episode_id)
        self.episode_id = episode_id


PRESCRIBER_MESSAGE = ('Somente veterinário com CRMV vinculado a esta clínica pode prescrever, '
                      'revisar, retificar ou dar alta. Sua checagem de doses e evoluções continua disponível.')


@bp.errorhandler(_PrescriberRequired)
def prescriber_required(error):
    """Explica o bloqueio em vez de uma página genérica; o status continua 403."""
    db.session.rollback()
    if _json_requested():
        return jsonify(ok=False, erro=PRESCRIBER_MESSAGE), 403
    flash(PRESCRIBER_MESSAGE, 'warning')
    _form_error('pagina', PRESCRIBER_MESSAGE)
    return detalhe(error.episode_id), 403


@bp.after_request
def hospital_private_response(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _json_requested():
    return request.is_json or request.accept_mimetypes.best == 'application/json'


def _data():
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(data, dict):
        abort(400)
    return data


def _evolution_data():
    data = _data()
    parameters = dict(data.get('parametros') or {}) if isinstance(data.get('parametros'), dict) else {}
    fields = {'param_temperatura': 'Temperatura (°C)', 'param_fc': 'Frequência cardíaca (bpm)',
              'param_fr': 'Frequência respiratória (irpm)', 'param_peso': 'Peso (kg)'}
    for field, label in fields.items():
        raw = str(data.get(field) or '').strip()
        if not raw:
            continue
        try:
            if len(raw) > 24:
                raise ValueError()
            number = Decimal(raw.replace(',', '.'))
            if not number.is_finite() or number <= 0 or number > 1000000:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise hospital.InternacaoError(f'Informe um número positivo válido para {label}.') from None
        parameters[label] = format(number.normalize(), 'f')
    if parameters:
        data['parametros'] = parameters
    return data


def _integer(value, label='Identificador'):
    if value in (None, ''):
        return None
    if isinstance(value, (bool, float)):
        raise hospital.InternacaoError(f'{label} inválido.')
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise hospital.InternacaoError(f'{label} inválido.') from None
    if number < 1:
        raise hospital.InternacaoError(f'{label} inválido.')
    return number


def ensure_hospital_clinic(clinica_id=None):
    if not pode_acessar_internacao(current_user):
        abort(404)
    clinics = clinicas_internacao(current_user)
    if clinica_id is not None:
        if not pode_operar_internacao(current_user, clinica_id):
            abort(404)
        clinic = db.session.get(Clinica, clinica_id)
        if clinic is None:
            abort(404)
        session[SESSION_CLINIC_KEY] = clinic.id
        return clinic, clinics
    return _default_clinic(clinics), clinics


def _default_clinic(clinics):
    """Última clínica usada, depois a clínica do próprio usuário, depois a primeira."""
    if not clinics:
        return None
    by_id = {clinic.id: clinic for clinic in clinics}
    vet = getattr(current_user, 'veterinario', None)
    for candidate in (session.get(SESSION_CLINIC_KEY),
                      getattr(vet, 'clinica_id', None),
                      getattr(current_user, 'clinica_id', None)):
        if candidate in by_id:
            return by_id[candidate]
    return clinics[0]


def ensure_internacao(internacao_id, *, prescriber=False):
    episode = db.session.get(Internacao, internacao_id)
    if episode is None or not pode_operar_internacao(current_user, episode.clinica_id):
        abort(404)
    if prescriber and not pode_prescrever_internacao(current_user, episode.clinica_id):
        raise _PrescriberRequired(episode.id)
    return episode


def ensure_prescricao(prescricao_id, *, prescriber=False):
    prescription = db.session.get(InternacaoPrescricao, prescricao_id)
    if prescription is None:
        abort(404)
    ensure_internacao(prescription.internacao_id, prescriber=prescriber)
    return prescription


def _animal_query(clinic_id):
    # Um animal compartilhado pode ter atendimento nesta clínica sem mudar
    # sua clínica cadastral. O prontuário hospitalar continua no escopo escolhido.
    attended = db.session.query(Consulta.id).filter(
        Consulta.animal_id == Animal.id, Consulta.clinica_id == clinic_id,
    ).exists()
    return Animal.query.filter(Animal.removido_em.is_(None)).filter(
        or_(Animal.clinica_id == clinic_id, attended),
    )


def ensure_hospital_animal(animal_id, clinic_id):
    animal = _animal_query(clinic_id).filter(Animal.id == animal_id).first()
    if animal is None:
        abort(404)
    return animal


def _professionals(clinic_id):
    profiles = Veterinario.query.filter(or_(
        Veterinario.clinica_id == clinic_id,
        Veterinario.clinicas.any(Clinica.id == clinic_id),
    )).options(joinedload(Veterinario.user)).all()
    return sorted(
        [profile.user for profile in profiles
         if profile.user and pode_ser_responsavel_internacao(profile.user, clinic_id)],
        key=lambda user: (user.name or '').casefold(),
    )


def _period(*, default_start=None, default_end=None):
    start = default_start or utcnow() - timedelta(hours=12)
    end = default_end or utcnow() + timedelta(hours=24)
    try:
        if request.args.get('inicio'):
            start = normalize_to_utc(request.args['inicio'])
        if request.args.get('fim'):
            raw = request.args['fim']
            end = normalize_to_utc(raw)
            if len(raw) == 10:
                end += timedelta(days=1)
    except (TypeError, ValueError):
        raise hospital.InternacaoError('Informe um período válido.') from None
    if end <= start or end - start > timedelta(days=93):
        raise hospital.InternacaoError('Escolha um período de até 93 dias, com fim após o início.')
    return start, end


def _vigente(order, at):
    return (order.status in ('ativa', 'substituida')
            and _utc(order.inicio_em) <= at < _utc(order.fim_em)
            and (not order.suspensa_em or at < _utc(order.suspensa_em)))


def _records_for_period(records, doses, start, end):
    """Inclui a cadeia auditável mesmo quando lançada após o período clínico."""
    dose_ids = {dose.id for dose in doses}
    selected = {record.id for record in records
                if record.ocorrencia_id in dose_ids
                or start <= _utc(record.registrada_em) < end
                or (record.executada_em and start <= _utc(record.executada_em) < end)}
    changed = True
    while changed:
        previous = len(selected)
        for record in records:
            if record.retifica_id in selected:
                selected.add(record.id)
            if record.id in selected and record.retifica_id:
                selected.add(record.retifica_id)
        changed = len(selected) != previous
    return [record for record in records if record.id in selected]


def _back_to_panel(episode_id):
    """Formulários da ronda voltam ao painel da mesma clínica, e só para ele."""
    if request.form.get('voltar') != 'painel':
        return None
    episode = db.session.get(Internacao, episode_id)
    return url_for('internacao.painel', clinica_id=episode.clinica_id if episode else None,
                   doses=request.form.get('doses') if request.form.get('doses') == 'atrasadas' else None,
                   _anchor='plantao-title')


def _result(obj, message, episode_id, status=200, *, anchor=None, extra=None):
    db.session.commit()
    if _json_requested():
        return jsonify(ok=True, id=obj.id, internacao_id=episode_id, mensagem=message, **(extra or {})), status
    flash(message, 'success')
    target = _back_to_panel(episode_id) or url_for('internacao.detalhe', internacao_id=episode_id, _anchor=anchor)
    return redirect(target, code=303)


def _record_payload(record):
    """Dados para a tela atualizar a linha da dose sem recarregar a página."""
    return {'resultado': record.resultado, 'registro_id': record.id,
            'executada_em': format_datetime(record.executada_em),
            'registrada_em': format_datetime(record.registrada_em),
            'autor': record.autor.name if record.autor else None}


def _failure(error, episode_id=None, *, target=None):
    db.session.rollback()
    status = 409 if isinstance(error, (hospital.InternacaoConflict, IntegrityError)) else 400
    message = ('O registro foi alterado por outra pessoa. Atualize a página para conferir.'
               if isinstance(error, IntegrityError) else str(error))
    if _json_requested():
        return jsonify(ok=False, erro=message), status
    flash(message, 'warning')
    if episode_id and request.method == 'POST':
        panel = _back_to_panel(episode_id)
        if panel:
            return redirect(panel, code=303)
        _form_error(target or 'pagina', message)
        return detalhe(episode_id), status
    target = (url_for('internacao.detalhe', internacao_id=episode_id)
              if episode_id else url_for('internacao.painel'))
    return redirect(target, code=303)


@bp.route('')
@login_required
def painel():
    clinic, clinics = ensure_hospital_clinic(request.args.get('clinica_id', type=int))
    episodes = []
    doses = []
    agora = utcnow()
    if clinic:
        query = Internacao.query.filter_by(clinica_id=clinic.id)
        state = request.args.get('status', 'ativa')
        if state in ('ativa', 'alta'):
            query = query.filter_by(status=state)
        else:
            state = 'todas'
        term = request.args.get('q', '').strip()[:100]
        if term:
            query = query.join(Animal).filter(or_(
                Animal.name.ilike(f'%{term}%'),
                Animal.owner.has(User.name.ilike(f'%{term}%')),
            ))
        episodes = query.options(
            joinedload(Internacao.animal).joinedload(Animal.owner),
            joinedload(Internacao.responsavel),
        ).order_by(Internacao.iniciada_em.desc(), Internacao.id.desc()).limit(200).all()
        dose_query = InternacaoOcorrencia.query.join(Internacao).filter(
            Internacao.clinica_id == clinic.id, Internacao.status == 'ativa',
            InternacaoOcorrencia.status == 'pendente',
            InternacaoOcorrencia.prevista_para < agora + timedelta(hours=24),
        )
        if term:
            dose_query = dose_query.join(Animal).filter(Animal.name.ilike(f'%{term}%'))
        doses = dose_query.options(
            joinedload(InternacaoOcorrencia.internacao).joinedload(Internacao.animal),
            joinedload(InternacaoOcorrencia.prescricao),
        ).order_by(InternacaoOcorrencia.prevista_para).limit(500).all()
    atrasadas_ids = {dose.id for dose in doses if _utc(dose.prevista_para) < agora}
    resumo = {'ativos': Internacao.query.filter_by(clinica_id=clinic.id, status='ativa').count() if clinic else 0,
              'pendentes': len(doses),
              'atrasadas': len(atrasadas_ids)}
    if _json_requested():
        return jsonify(internacoes=[{'id': item.id, 'animal_id': item.animal_id,
                                     'status': item.status, 'leito': item.leito} for item in episodes],
                       resumo=resumo)
    filtro_doses = 'atrasadas' if request.args.get('doses') == 'atrasadas' else 'todas'
    doses_exibidas = [dose for dose in doses if dose.id in atrasadas_ids] if filtro_doses == 'atrasadas' else doses
    tolerancia = hospital.tolerancia_checagem()
    return render_template('internacao/painel.html', internacoes=episodes, doses_plantao=doses_exibidas,
                           agora=agora, clinicas=clinics, clinica=clinic, resumo=resumo,
                           atrasadas_ids=atrasadas_ids, filtro_doses=filtro_doses,
                           tolerancia_minutos=int(tolerancia.total_seconds() // 60),
                           janelas={dose.id: _dose_window(dose, agora, tolerancia) for dose in doses_exibidas},
                           passagens=_latest_notes([item.id for item in episodes if item.status == 'ativa']),
                           doses_por_paciente=_dose_counts(doses, atrasadas_ids))


def _latest_notes(episode_ids):
    """Último registro de evolução ou passagem de plantão de cada internação."""
    if not episode_ids:
        return {}
    latest = db.session.query(
        InternacaoEvolucao.internacao_id, func.max(InternacaoEvolucao.id).label('ultimo'),
    ).filter(InternacaoEvolucao.internacao_id.in_(episode_ids)).group_by(InternacaoEvolucao.internacao_id).subquery()
    notes = InternacaoEvolucao.query.join(latest, InternacaoEvolucao.id == latest.c.ultimo).options(
        joinedload(InternacaoEvolucao.autor)).all()
    return {note.internacao_id: note for note in notes}


def _dose_counts(doses, late_ids):
    counts = {}
    for dose in doses:
        item = counts.setdefault(dose.internacao_id, {'pendentes': 0, 'atrasadas': 0})
        item['pendentes'] += 1
        item['atrasadas'] += dose.id in late_ids
    return counts


@bp.route('/animal/<int:animal_id>')
@login_required
def paciente(animal_id):
    consulta_id = request.args.get('consulta_id', type=int)
    consultation = db.session.get(Consulta, consulta_id) if consulta_id else None
    if consulta_id and (consultation is None or consultation.animal_id != animal_id):
        abort(404)
    clinic_id = consultation.clinica_id if consultation else request.args.get('clinica_id', type=int)
    if not clinic_id:
        animal = db.session.get(Animal, animal_id)
        clinic_id = animal.clinica_id if animal else None
    clinic, _ = ensure_hospital_clinic(clinic_id)
    if not clinic:
        abort(404)
    ensure_hospital_animal(animal_id, clinic.id)
    active = Internacao.query.filter_by(animal_id=animal_id, clinica_id=clinic.id, status='ativa').first()
    if active:
        return redirect(url_for('internacao.detalhe', internacao_id=active.id))
    return redirect(url_for('internacao.nova', animal_id=animal_id, consulta_id=consulta_id,
                            clinica_id=clinic.id))


@bp.route('/nova', methods=['GET', 'POST'])
@login_required
def nova():
    data = _data() if request.method == 'POST' else request.args.to_dict()
    try:
        clinic_id = _integer(data.get('clinica_id'))
        consultation_id = _integer(data.get('consulta_id'))
        consultation = db.session.get(Consulta, consultation_id) if consultation_id else None
        if consultation_id and consultation is None:
            abort(404)
        if consultation:
            if clinic_id and consultation.clinica_id != clinic_id:
                abort(404)
            clinic_id = consultation.clinica_id
        clinic, clinics = ensure_hospital_clinic(clinic_id)
        if clinic is None:
            abort(404)
        animal_id = _integer(data.get('animal_id')) or (consultation.animal_id if consultation else None)
        animal = ensure_hospital_animal(animal_id, clinic.id) if animal_id else None
        if consultation and consultation.animal_id != animal_id:
            abort(404)
        if request.method == 'POST':
            if animal is None:
                raise hospital.InternacaoError('Selecione o animal que será internado.')
            responsible_id = _integer(data.get('responsavel_id'), 'Veterinário responsável')
            responsible = db.session.get(User, responsible_id) if responsible_id else None
            if not responsible or not pode_ser_responsavel_internacao(responsible, clinic.id):
                raise hospital.InternacaoError('Selecione um veterinário responsável habilitado nesta clínica.')
            data['responsavel_id'] = responsible.id
            data['consulta_id'] = consultation_id
            episode = hospital.criar_internacao(clinic.id, animal, current_user, data)
            return _result(episode, 'Internação aberta. A equipe já pode acompanhar este paciente.', episode.id, 201)
        animals = _animal_query(clinic.id).options(joinedload(Animal.owner))
        term = str(data.get('q') or '').strip()[:100]
        if term:
            animals = animals.filter(or_(
                Animal.name.ilike(f'%{term}%'),
                Animal.owner.has(User.name.ilike(f'%{term}%')),
            ))
        animals = animals.order_by(Animal.name).limit(ADMISSION_LIST_LIMIT + 1).all()
        more_animals = len(animals) > ADMISSION_LIST_LIMIT
        values = dict(data)
        values.setdefault('iniciada_em', format_datetime_input(utcnow()))
        return render_template('internacao/nova.html', animais=animals[:ADMISSION_LIST_LIMIT], animal=animal,
                               consulta_id=consultation_id, valores=values, clinica=clinic,
                               clinicas=clinics, profissionais=_professionals(clinic.id), agora=utcnow(),
                               busca=term, mais_animais=more_animals)
    except (hospital.InternacaoError, IntegrityError) as error:
        if request.method == 'GET' or _json_requested():
            return _failure(error)
        db.session.rollback()
        flash(str(error) if not isinstance(error, IntegrityError)
              else 'Este animal já tem uma internação ativa. Abra a ficha pelo painel.', 'warning')
        # O formulário é reapresentado com os valores, sem perder o preenchimento.
        clinic, clinics = ensure_hospital_clinic(request.form.get('clinica_id', type=int))
        if not clinic:
            abort(404)
        animal_id = request.form.get('animal_id', type=int)
        animal = ensure_hospital_animal(animal_id, clinic.id) if animal_id else None
        return render_template('internacao/nova.html', animais=_animal_query(clinic.id).order_by(Animal.name).limit(500).all(),
                               animal=animal, consulta_id=request.form.get('consulta_id', type=int),
                               valores=data, clinica=clinic, clinicas=clinics,
                               profissionais=_professionals(clinic.id), agora=utcnow()), 400


@bp.route('/<int:internacao_id>')
@login_required
def detalhe(internacao_id):
    episode = ensure_internacao(internacao_id)
    try:
        start, end = _period()
    except hospital.InternacaoError as error:
        return _failure(error, episode.id)
    prescriptions = InternacaoPrescricao.query.filter_by(internacao_id=episode.id).options(
        joinedload(InternacaoPrescricao.criado_por),
    ).order_by(InternacaoPrescricao.criada_em.desc(), InternacaoPrescricao.id.desc()).all()
    doses = InternacaoOcorrencia.query.filter_by(internacao_id=episode.id).filter(or_(
        and_(InternacaoOcorrencia.status == 'pendente', InternacaoOcorrencia.prevista_para < start),
        (InternacaoOcorrencia.prevista_para >= start) & (InternacaoOcorrencia.prevista_para < end),
    )).options(
        joinedload(InternacaoOcorrencia.prescricao),
        selectinload(InternacaoOcorrencia.registros).joinedload(InternacaoRegistro.autor),
    ).order_by(InternacaoOcorrencia.prevista_para).all()
    records = InternacaoRegistro.query.filter_by(internacao_id=episode.id).options(
        joinedload(InternacaoRegistro.prescricao), joinedload(InternacaoRegistro.autor),
    ).order_by(InternacaoRegistro.registrada_em.desc(), InternacaoRegistro.id.desc()).all()
    evolutions = InternacaoEvolucao.query.filter_by(internacao_id=episode.id).options(
        joinedload(InternacaoEvolucao.autor),
    ).order_by(InternacaoEvolucao.criada_em.desc(), InternacaoEvolucao.id.desc()).all()
    events = InternacaoEvento.query.filter_by(internacao_id=episode.id).options(
        joinedload(InternacaoEvento.autor),
    ).order_by(InternacaoEvento.id.desc()).all()
    can_prescribe = pode_prescrever_internacao(current_user, episode.clinica_id)
    at = utcnow()
    tolerance = hospital.tolerancia_checagem()
    # Histórico enxuto: últimas 24 h na tela; a impressão continua completa.
    full_history = request.args.get('historico') == 'todos'
    open_correction = request.args.get('retificar', type=int)
    if request.endpoint == 'internacao.retificar':
        open_correction = (request.view_args or {}).get('registro_id')
    visible_records = records if full_history else [
        record for record in records
        if _utc(record.registrada_em) >= at - HISTORY_WINDOW
        or (record.executada_em and _utc(record.executada_em) >= at - HISTORY_WINDOW)
        or record.id == open_correction
    ]
    if _json_requested():
        return jsonify(id=episode.id, animal_id=episode.animal_id, status=episode.status,
                       prescricoes=[{'id': order.id, 'medicamento': order.medicamento,
                                     'status': order.status, 'versao': order.versao} for order in prescriptions],
                       doses=[{'id': dose.id, 'status': dose.status,
                               'prevista_para': _utc(dose.prevista_para).isoformat()} for dose in doses])
    return render_template('internacao/detalhe.html', internacao=episode, prescricoes=prescriptions,
                           doses=doses, registros=visible_records, registros_total=len(records),
                           historico_completo=full_history, retificar_id=open_correction,
                           evolucoes=evolutions, eventos=events,
                           agora=at, inicio=start, fim=end, resumo=hospital.resumo_internacao(episode),
                           inicio_sugerido=_next_full_hour(at),
                           inicio_agora=at.replace(second=0, microsecond=0) + timedelta(minutes=1),
                           tolerancia_minutos=int(tolerance.total_seconds() // 60),
                           janelas={dose.id: _dose_window(dose, at, tolerance) for dose in doses},
                           erro_formulario=g.get('ih_erro'),
                           valores_dose=(request.form.to_dict() if request.method == 'POST'
                                         and request.endpoint in ('internacao.registrar', 'internacao.registrar_prn',
                                                                  'internacao.retificar', 'internacao.alta',
                                                                  'internacao.suspender') else {}),
                           vigentes_ids={order.id for order in prescriptions if _vigente(order, at)},
                           futuras_ids={order.id for order in prescriptions
                                        if order.status == 'ativa' and _utc(order.inicio_em) > at},
                           valores_prescricao=(request.form.to_dict() if request.method == 'POST'
                                               and request.endpoint in ('internacao.prescrever', 'internacao.revisar') else {}),
                           valores_evolucao=(request.form.to_dict() if request.method == 'POST'
                                             and request.endpoint == 'internacao.evolucao' else {}),
                           revisao_erro_id=(request.view_args.get('prescricao_id')
                                           if request.endpoint == 'internacao.revisar' else None),
                           revisao_prescricao_id=(request.view_args.get('prescricao_id')
                                                 if request.endpoint == 'internacao.revisar' else None),
                           atrasadas_ids={dose.id for dose in doses
                                          if dose.status == 'pendente' and _utc(dose.prevista_para) < utcnow()},
                           pode_prescrever=can_prescribe,
                           pode_registrar=episode.status == 'ativa' or can_prescribe,
                           pode_dar_alta=can_prescribe and episode.status == 'ativa')


@bp.route('/<int:internacao_id>/prescricoes/previa', methods=['POST'])
@login_required
def previa(internacao_id):
    episode = ensure_internacao(internacao_id, prescriber=True)
    try:
        if episode.status != 'ativa':
            raise hospital.InternacaoError('Esta internação já foi encerrada.')
        times = hospital.prever_horarios(_data())
        return jsonify(ok=True, horarios=[_utc(value).isoformat() for value in times],
                       total=len(times), fuso='America/Sao_Paulo')
    except hospital.InternacaoError as error:
        return _failure(error, episode.id)


@bp.route('/<int:internacao_id>/prescricoes', methods=['POST'])
@login_required
def prescrever(internacao_id):
    episode = ensure_internacao(internacao_id, prescriber=True)
    try:
        order = hospital.prescrever(episode, current_user, _data())
        return _result(order, 'Prescrição publicada e horários programados.', episode.id, 201,
                       anchor=f'prescricao-{order.id}')
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, episode.id, target='nova-prescricao')


@bp.route('/prescricoes/<int:prescricao_id>/revisar', methods=['POST'])
@login_required
def revisar(prescricao_id):
    order = ensure_prescricao(prescricao_id, prescriber=True)
    try:
        revision = hospital.revisar_prescricao(order, current_user, _data())
        return _result(revision, 'Nova versão publicada. O histórico anterior foi preservado.', order.internacao_id, 201,
                       anchor=f'prescricao-{revision.id}')
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, order.internacao_id, target=f'revisar-{order.id}')


@bp.route('/prescricoes/<int:prescricao_id>/suspender', methods=['POST'])
@login_required
def suspender(prescricao_id):
    order = ensure_prescricao(prescricao_id, prescriber=True)
    try:
        hospital.suspender_prescricao(order, current_user, _data().get('motivo'))
        return _result(order, 'Prescrição suspensa. Registros anteriores preservados.', order.internacao_id,
                       anchor=f'prescricao-{order.id}')
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, order.internacao_id, target=f'suspender-{order.id}')


@bp.route('/doses/<int:dose_id>/registrar', methods=['POST'])
@login_required
def registrar(dose_id):
    dose = db.session.get(InternacaoOcorrencia, dose_id)
    if dose is None:
        abort(404)
    episode = ensure_internacao(dose.internacao_id)
    if episode.status != 'ativa':
        ensure_internacao(episode.id, prescriber=True)
    try:
        data = _data()
        status = data.get('status', data.get('resultado', 'administrada'))
        if status == 'administrada':
            record = hospital.registrar_administracao(dose, current_user, data)
        elif status == 'omitida':
            record = hospital.omitir_ocorrencia(dose, current_user, data)
        else:
            raise hospital.InternacaoError('Escolha administração ou não administração.')
        return _result(record, 'Registro salvo com horário e autoria.', episode.id,
                       anchor=f'dose-{dose.id}', extra={'dose_id': dose.id, **_record_payload(record)})
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, episode.id, target=f'dose-{dose.id}')


@bp.route('/prescricoes/<int:prescricao_id>/registrar', methods=['POST'])
@login_required
def registrar_prn(prescricao_id):
    order = ensure_prescricao(prescricao_id)
    episode = ensure_internacao(order.internacao_id)
    if episode.status != 'ativa':
        ensure_internacao(episode.id, prescriber=True)
    try:
        record = hospital.registrar_prn(order, current_user, _data())
        return _result(record, 'Administração se necessário registrada.', episode.id,
                       anchor=f'prescricao-{order.id}', extra={'prescricao_id': order.id, **_record_payload(record)})
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, episode.id, target=f'prn-{order.id}')


@bp.route('/registros/<int:registro_id>/retificar', methods=['POST'])
@login_required
def retificar(registro_id):
    record = db.session.get(InternacaoRegistro, registro_id)
    if record is None:
        abort(404)
    # Retificações são decisões clínicas auditáveis, exclusivas do veterinário.
    episode = ensure_internacao(record.internacao_id, prescriber=True)
    try:
        correction = hospital.retificar_registro(record, current_user, _data())
        return _result(correction, 'Retificação registrada; o lançamento original foi preservado.', episode.id, 201,
                       anchor='historico')
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, episode.id, target=f'retificar-{record.id}')


@bp.route('/<int:internacao_id>/evolucoes', methods=['POST'])
@login_required
def evolucao(internacao_id):
    episode = ensure_internacao(internacao_id)
    try:
        note = hospital.registrar_evolucao(episode, current_user, _evolution_data())
        return _result(note, 'Anotação adicionada ao prontuário.', episode.id, 201, anchor='evolucoes')
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, episode.id, target='evolucao')


@bp.route('/<int:internacao_id>/alta', methods=['POST'])
@login_required
def alta(internacao_id):
    episode = ensure_internacao(internacao_id, prescriber=True)
    try:
        hospital.dar_alta(episode, current_user, _data())
        return _result(episode, 'Alta registrada. A programação futura foi encerrada.', episode.id)
    except (hospital.InternacaoError, IntegrityError) as error:
        return _failure(error, episode.id, target='alta')


@bp.route('/<int:internacao_id>/imprimir')
@login_required
def imprimir(internacao_id):
    episode = ensure_internacao(internacao_id)
    kind = request.args.get('tipo', 'prontuario')
    if kind not in ('prescricao', 'mapa', 'prontuario'):
        abort(400)
    try:
        start, end = _period(default_start=_utc(episode.iniciada_em),
                             default_end=_utc(episode.encerrada_em) or utcnow() + timedelta(days=1))
    except hospital.InternacaoError as error:
        return _failure(error, episode.id)
    prescriptions = InternacaoPrescricao.query.filter_by(internacao_id=episode.id).options(
        joinedload(InternacaoPrescricao.criado_por),
    ).order_by(InternacaoPrescricao.criada_em, InternacaoPrescricao.id).all()
    at = utcnow()
    if kind == 'prescricao':
        prescriptions = [order for order in prescriptions
                         if _vigente(order, at)
                         or (order.status == 'ativa' and _utc(order.inicio_em) > at)]
    doses = InternacaoOcorrencia.query.filter_by(internacao_id=episode.id).filter(
        InternacaoOcorrencia.prevista_para >= start, InternacaoOcorrencia.prevista_para < end,
    ).options(
        joinedload(InternacaoOcorrencia.prescricao),
        selectinload(InternacaoOcorrencia.registros).joinedload(InternacaoRegistro.autor),
    ).order_by(InternacaoOcorrencia.prevista_para).all()
    records = InternacaoRegistro.query.filter_by(internacao_id=episode.id).options(
        joinedload(InternacaoRegistro.prescricao), joinedload(InternacaoRegistro.autor),
    ).order_by(InternacaoRegistro.registrada_em, InternacaoRegistro.id).all()
    records = _records_for_period(records, doses, start, end)
    evolutions = InternacaoEvolucao.query.filter_by(internacao_id=episode.id).filter(
        InternacaoEvolucao.criada_em >= start, InternacaoEvolucao.criada_em < end,
    ).options(joinedload(InternacaoEvolucao.autor)).order_by(
        InternacaoEvolucao.criada_em, InternacaoEvolucao.id).all()
    return render_template('internacao/imprimir.html', internacao=episode, tipo=kind,
                           prescricoes=prescriptions, doses=doses, registros=records,
                           evolucoes=evolutions, inicio=start, fim=end, agora=utcnow(),
                           emitido_em=utcnow(), clinica=episode.clinica,
                           vigentes_ids={order.id for order in prescriptions if _vigente(order, at)},
                           futuras_ids={order.id for order in prescriptions
                                        if order.status == 'ativa' and _utc(order.inicio_em) > at})
