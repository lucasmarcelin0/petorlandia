"""Fluxo de pilotos individuais, isolado dos registros municipais."""
import json
import math
import uuid
from datetime import date
from flask import abort, flash, make_response, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import MultiDict


def register(bp, require_access, schema_loader):
    from services.sfa_pilot import STAGES, create_pilot, pilot_calendar, pilot_metadata, pilot_schema
    from services import sfa_pilot as service
    from extensions import db
    from models.sfa import SfaPilotParticipant, SfaPilotResponse, SfaInstrumentReview

    def private_response(body, status=200):
        response = make_response(body, status)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @bp.route('/pilotos', methods=['GET', 'POST'])
    @require_access
    def pilotos():
        if request.method == 'POST':
            try:
                onset = date.fromisoformat(request.form['onset']) if request.form.get('onset') else None
                context = {key: request.form.get(key, '') for key in ('pilot_ns1_resultado', 'pilot_pcr_resultado')}
                context.update(pilot_sintomas=request.form.getlist('pilot_sintomas'), source='Relato informado no cadastro do piloto; laudo não conferido')
                pilot = create_pilot(request.form.get('label', ''), onset, context, request.form.get('creation_key', ''))
            except ValueError:
                flash('Confira o rótulo e a data informada. O piloto não foi cadastrado.', 'danger')
            else:
                return redirect(url_for('sfa_routes.piloto_detail', pilot_id=pilot.id))
        return render_template('sfa/pilots.html',
            pilotos=[(p, pilot_calendar(p)) for p in SfaPilotParticipant.query.order_by(SfaPilotParticipant.id.desc()).all()],
            creation_key=uuid.uuid4().hex)

    @bp.route('/pilotos/<int:pilot_id>')
    @require_access
    def piloto_detail(pilot_id):
        pilot = db.get_or_404(SfaPilotParticipant, pilot_id)
        feedback = []
        for review in SfaInstrumentReview.query.filter_by(reviewer_profile='PILOTO DE USABILIDADE').all():
            payload = json.loads(review.payload_json or '{}')
            if payload.get('pilot', {}).get('participant_id') == pilot.id:
                feedback.append(dict(stage=review.kind, created_at=review.created_at, data=payload['pilot']['feedback']))
        return private_response(render_template('sfa/pilot_detail.html', pilot=pilot,
            calendar=pilot_calendar(pilot), context=json.loads(pilot.context_json),
            responses=[(r, json.loads(r.payload_json)) for r in pilot.responses], feedback=feedback))

    @bp.route('/piloto')
    def piloto_inicio():
        return private_response(render_template('sfa/pilot_start.html', pilot=None))

    @bp.route('/piloto/<token>')
    def piloto_convite(token):
        pilot = SfaPilotParticipant.query.filter_by(token=token).first_or_404()
        return private_response(render_template('sfa/pilot_start.html', pilot=pilot, calendar=pilot_calendar(pilot)))

    @bp.route('/piloto/<token>/<kind>', methods=['GET', 'POST'])
    def piloto_formulario(token, kind):
        if kind not in STAGES:
            abort(404)
        pilot = SfaPilotParticipant.query.filter_by(token=token).first_or_404()
        calendar = pilot_calendar(pilot)
        stage = next(s for s in calendar['stages'] if s['stage'] == kind)
        schema = pilot_schema(kind, schema_loader(kind)(), pilot)

        def show(error=None, status=200, submitted=None):
            if submitted is None:
                submitted = MultiDict()
                if kind == 't0':
                    for key, value in json.loads(pilot.context_json).items():
                        if key == 'source':
                            continue
                        submitted.setlist('answer__'+key, value if isinstance(value, list) else [value])
                    if calendar['onset']:
                        submitted['answer__data_inicio_sintomas'] = calendar['onset'].isoformat()
            return private_response(render_template('sfa/pilot_form.html', kind=kind, schema=schema, pilot=pilot,
                calendar=calendar, stage=stage, hoje=service.hoje_local(), error=error, submitted=submitted), status)

        if request.method == 'GET':
            if stage['response']:
                return private_response(render_template('sfa/pilot_submitted.html', kind=kind, pilot=pilot, feedback_only=False, already=True))
            return show()
        action = request.form.get('action')
        if action not in ('answer', 'feedback'):
            return show('Escolha enviar respostas ou somente sugestões.', 400, request.form)
        if action == 'answer' and stage['response']:
            return private_response(render_template('sfa/pilot_submitted.html', kind=kind, pilot=pilot, already=True))
        if action == 'answer' and stage['blocked']:
            return show(stage['blocked'], 409, request.form)
        try:
            metadata = pilot_metadata(request.form, kind)
            if action == 'feedback':
                # Não guardar as respostas clínicas de uma revisão antecipada.
                metadata = {k: metadata[k] for k in ('purpose', 'pilot_version', 'municipal_study', 'feedback')}
                metadata.update(participant_id=pilot.id, feedback_only=True)
                db.session.add(SfaInstrumentReview(kind=kind, reviewer_name=pilot.label,
                    reviewer_profile='PILOTO DE USABILIDADE', payload_json=json.dumps({'pilot': metadata}, ensure_ascii=False)))
                db.session.commit()
                return private_response(render_template('sfa/pilot_submitted.html', kind=kind, pilot=pilot, feedback_only=True))
            answers = {}
            from services.sfa_service import iterar_campos_form, _avaliar_regra_visibilidade
            for item in iterar_campos_form(schema):
                key = item['key']
                if not _avaliar_regra_visibilidade(item.get('visible_if'), answers, []):
                    continue
                value = request.form.getlist('answer__'+key) if item['type'] == 'checkboxes' else request.form.get('answer__'+key, '').strip()
                if isinstance(value, list):
                    if any(v not in item.get('options', []) for v in value):
                        raise ValueError('Confira as opções selecionadas.')
                elif value:
                    if len(value) > 3000 or (item.get('options') and value not in item['options']):
                        raise ValueError('Confira as respostas e o tamanho dos textos.')
                    if item['type'] == 'number':
                        number = float(value.replace(',', '.'))
                        if not math.isfinite(number) or number < item.get('min', -math.inf) or number > item.get('max', math.inf):
                            raise ValueError('Confira os valores numéricos informados.')
                    if item['type'] == 'date':
                        parsed = date.fromisoformat(value)
                        if parsed > service.hoje_local():
                            raise ValueError('Não informe uma data futura.')
                answers[key] = value
            onset = date.fromisoformat(metadata['reported_onset']) if metadata['reported_onset'] and kind == 't0' else calendar['onset']
            today = service.hoje_local()
            metadata.update(participant_id=pilot.id, actual_interview_date=today.isoformat(),
                reported_onset=onset.isoformat() if onset else '', illness_days=(today-onset).days if onset else None,
                target_date=stage['target'].isoformat() if stage['target'] else None,
                interval_from=(calendar['stages'][1]['response'] or calendar['stages'][0]['response']).interview_date.isoformat() if kind=='t30' else (calendar['first_interview'].isoformat() if calendar['first_interview'] else None))
            payload = dict(answers=answers, pilot=metadata, source_instrument_version=schema.get('instrument_version'),
                           question_labels={f['key']: f['label'] for f in iterar_campos_form(schema)})
            db.session.add(SfaPilotResponse(pilot_id=pilot.id, stage=kind, interview_date=today,
                                           payload_json=json.dumps(payload, ensure_ascii=False)))
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            return show(str(exc) or 'Confira as respostas informadas.', 400, request.form)
        except IntegrityError:
            db.session.rollback()
            if not SfaPilotResponse.query.filter_by(pilot_id=pilot.id, stage=kind).first():
                raise
        return private_response(render_template('sfa/pilot_submitted.html', kind=kind, pilot=pilot, feedback_only=False))
