"""Pilotos individuais de usabilidade, separados do cadastro e das análises municipais."""
from copy import deepcopy
from datetime import date, timedelta
import json
import secrets
from services.sfa_workflow import hoje_local

PILOT_VERSION = 'usabilidade-2026-09-15'
STAGES = ('t0', 't7', 't30')


def field(key, label, kind='text', options=None, **kwargs):
    result = dict(key=key, label=label, type=kind, required=False, **kwargs)
    if options is not None:
        result['options'] = options
    return result


def pilot_schema(stage, original, participant=None):
    from services.sfa_service import _resolver_regra_visibilidade_para_cliente
    prior = [json.loads(r.payload_json).get('answers', {}) for r in (participant.responses if participant else [])
             if STAGES.index(r.stage) < STAGES.index(stage)]
    schema = deepcopy(original)
    schema['pilot_version'] = PILOT_VERSION
    for section in schema['sections']:
        section['fields'] = [f for f in section['fields'] if f['key'] not in ('aceite_tcle', 'respondent_name')]
        for item in section['fields']:
            item['required'] = False
            if 'visible_if' in item:
                item['visible_if'] = _resolver_regra_visibilidade_para_cliente(item['visible_if'], prior)
            if item['key'] == 'retornou_servico_saude':
                item['label'] = 'Desde o T0, você precisou procurar algum serviço de saúde, em qualquer município?'
            if item['key'] == 'data_inicio_sintomas':
                item.pop('prefill', None)
    if stage == 't0':
        schema['sections'][0]['description'] = 'Este é um teste de compreensão das perguntas. Não há vínculo com SINAN nem inscrição no estudo.'
        for section in schema['sections']:
            if any(f['key'] == 'data_inicio_sintomas' for f in section['fields']):
                section['description'] = 'O primeiro dia de sintomas é D0. Se não souber a data, deixe em branco.'
        baseline = [
            field('pilot_municipio', 'Em qual município e estado você mora?'),
            field('pilot_bairro', 'Em qual bairro você mora? (opcional)'),
            field('pilot_idade', 'Qual é sua idade em anos? (opcional)', 'number', min=0, max=120, step=1),
            field('pilot_sintomas', 'Quais sintomas você percebeu neste episódio?', 'checkboxes',
                  ['Febre', 'Dor de cabeça', 'Dor atrás dos olhos', 'Dores musculares', 'Dores articulares', 'Cansaço', 'Manchas na pele', 'Coceira', 'Náusea ou vômitos', 'Outros', 'Não sei']),
            field('pilot_sintomas_detalhe', 'Quer descrever outros sintomas ou alguma informação que faltou?', 'textarea'),
        ]
        exams = []
        for test in ('PCR', 'NS1'):
            exams.extend([
                field('pilot_'+test.lower()+'_resultado', f'Você fez exame {test} para dengue? Qual resultado recebeu?', 'radio',
                      ['Não realizado', 'Positivo', 'Negativo', 'Inconclusivo', 'Aguardando resultado', 'Não sei']),
                field('pilot_'+test.lower()+'_coleta', f'Qual foi a data de coleta do {test}? (se souber)', 'date'),
            ])
        exams.append(field('pilot_exame_observacao', 'Alguma observação sobre exames ou resultados diferentes?', 'textarea'))
        schema['sections'].insert(2, dict(title='Informações para testar sem SINAN', description='Preencha apenas o que souber. Não informe CPF, nome completo, número de prontuário ou foto de laudo. Estas informações são autorrelatadas e não confirmam um diagnóstico.', fields=baseline))
        schema['sections'].insert(3, dict(title='Exames deste episódio', description='Pode testar mesmo sem exame. Não é preciso adivinhar o resultado.', fields=exams))
        schema['sections'].insert(4, dict(title='Locais de trabalho e estudo', description='Antes do início dos sintomas, onde você costumava trabalhar ou estudar? Informe todos os locais, se houver mais de um.', workplaces=True, fields=[
            field('pilot_rotina_locais', 'Quais situações descrevem sua rotina antes dos sintomas?', 'checkboxes',
                  ['Trabalho ou estudo fora de casa', 'Trabalho ou estudo em casa', 'Não tenho local fixo de trabalho ou estudo', 'Não trabalho nem estudo'])
        ]))
    else:
        schema['sections'][0]['description'] = 'Responda conforme o que sabe hoje. O contexto vem somente das respostas anteriores deste piloto, sem consulta ao SINAN.'
    return schema


def pilot_metadata(form, stage):
    """Valida metadados e locais. Nunca recebe id_estudo, token ou classificação."""
    def short(name, limit=500):
        value = str(form.get(name, '')).strip()
        if len(value) > limit:
            raise ValueError('Um campo de texto excedeu o tamanho permitido. Resuma sua resposta.')
        return value
    onset = short('answer__data_inicio_sintomas', 10)
    start = None
    if onset:
        try:
            start = date.fromisoformat(onset)
        except ValueError as exc:
            raise ValueError('Confira a data de início dos sintomas.') from exc
        if start > hoje_local():
            raise ValueError('O início dos sintomas não pode estar no futuro. Deixe em branco se não souber.')
    minutes = short('pilot_minutes', 10)
    if minutes:
        try:
            n = float(minutes.replace(',', '.'))
            if not 0 <= n <= 1440:
                raise ValueError()
        except ValueError as exc:
            raise ValueError('Informe o tempo em minutos, entre 0 e 1440, ou deixe em branco.') from exc
    columns = ('activity', 'name', 'city', 'neighborhood', 'address', 'days', 'hours')
    values = {key: form.getlist('work_'+key) for key in columns}
    lengths = {len(v) for v in values.values()}
    if len(lengths) != 1 or max(lengths, default=0) > 20:
        raise ValueError('Confira a lista de locais de trabalho e estudo (até 20 locais).')
    workplaces = []
    for i in range(max(lengths, default=0)):
        row = {key: str(values[key][i]).strip() for key in columns}
        if not any(row.values()):
            continue
        if any(len(value) > 500 for value in row.values()):
            raise ValueError('Resuma as informações do local de trabalho ou estudo.')
        if row['activity'] not in ('', 'Trabalho', 'Estudo', 'Trabalho e estudo'):
            raise ValueError('Confira a atividade do local informado.')
        for key, maximum in [('days', 7), ('hours', 24)]:
            if row[key]:
                try:
                    n = float(row[key].replace(',', '.'))
                    if not 0 <= n <= maximum:
                        raise ValueError()
                except ValueError as exc:
                    raise ValueError('Confira os dias por semana (0–7) e as horas por dia (0–24).') from exc
        workplaces.append(row)
    return dict(purpose='usability_pilot', pilot_version=PILOT_VERSION, municipal_study=False,
                code=short('pilot_code', 60), mode=short('pilot_mode', 40),
                reported_onset=onset, target_date=(start+timedelta(days={'t0': 0, 't7': 7, 't30': 30}[stage])).isoformat() if start and stage != 't0' else None,
                timing_reference='symptom_onset_D0', workplaces=workplaces if stage == 't0' else [],
                feedback=dict(minutes=minutes, confusing=short('pilot_confusing', 3000),
                              missing=short('pilot_missing', 3000), suggestion=short('pilot_suggestion', 3000)))


def pilot_calendar(participant):
    responses = {r.stage: r for r in participant.responses}
    onset = participant.reported_onset
    t0 = responses.get('t0')
    if t0:
        saved = json.loads(t0.payload_json).get('pilot', {}).get('reported_onset')
        if saved:
            onset = date.fromisoformat(saved)
    stages = []
    for stage in STAGES:
        target = onset + timedelta(days={'t0': 0, 't7': 7, 't30': 30}[stage]) if onset and stage != 't0' else None
        reason = ''
        if stage != 't0':
            if not t0:
                reason = 'O T0 ainda não foi respondido. Não há entrevista inicial registrada.'
            elif not target:
                reason = 'Confirme o início dos sintomas com Lucas antes deste acompanhamento.'
            elif hoje_local() < target:
                reason = 'O preenchimento desta etapa abre em '+target.strftime('%d/%m/%Y')+'. Por enquanto, você pode enviar somente sugestões.'
        response = responses.get(stage)
        stages.append(dict(stage=stage, target=target, response=response, blocked=reason,
                           status='Respondido' if response else ('Aguardando T0' if not t0 and stage != 't0' else ('Data a revisar' if stage != 't0' and not target else ('Ainda não abriu' if target and hoje_local() < target else 'Aguardando resposta')))))
    flags = []
    if not onset:
        flags.append('Início dos sintomas não informado')
    if not t0:
        flags.append('Primeira entrevista ainda não realizada')
    if t0 and onset:
        for days in (7, 30):
            if t0.interview_date > onset + timedelta(days=days):
                flags.append(f'T0 realizado após o D{days}; não reconstruir entrevista anterior')
    return dict(onset=onset, first_interview=t0.interview_date if t0 else None,
                illness_days_t0=(t0.interview_date-onset).days if t0 and onset else None,
                illness_days_today=(hoje_local()-onset).days if onset else None, stages=stages, flags=flags)


def create_pilot(label, onset, context, creation_key):
    """Cadastro explícito e idempotente; sem criar SINAN, TCLE ou resposta T0."""
    from models.sfa import SfaPilotParticipant
    from extensions import db
    existing = SfaPilotParticipant.query.filter_by(creation_key=creation_key).first()
    if existing:
        return existing
    if not creation_key or len(creation_key) > 64 or not label.strip() or len(label) > 120:
        raise ValueError('Confira o rótulo e a chave do piloto.')
    if onset and (not isinstance(onset, date) or onset > hoje_local()):
        raise ValueError('Confira a data de início dos sintomas.')
    # Lista explícita: nenhum identificador pessoal pode entrar por este comando.
    allowed = {key: context[key] for key in ('pilot_ns1_resultado', 'pilot_pcr_resultado', 'pilot_sintomas', 'source') if key in context}
    pilot = SfaPilotParticipant(label=label.strip(), token=secrets.token_urlsafe(32),
                               creation_key=creation_key, reported_onset=onset,
                               context_json=json.dumps(allowed, ensure_ascii=False))
    db.session.add(pilot)
    from sqlalchemy.exc import IntegrityError
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = SfaPilotParticipant.query.filter_by(creation_key=creation_key).first()
        if existing:
            return existing
        raise
    return pilot
