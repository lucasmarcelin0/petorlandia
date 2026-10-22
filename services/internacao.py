"""Operações hospitalares transacionais; o chamador faz commit ou rollback.

Horários do formulário sem offset são locais (America/Sao_Paulo); datas lidas
do banco sem offset são UTC, inclusive nos testes SQLite. Nenhuma frequência
livre é interpretada e nenhuma dose clínica é calculada neste módulo.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import update

from extensions import db
from models import Animal, Consulta, User
from models.internacao import (
    Internacao, InternacaoPrescricao, InternacaoOcorrencia,
    InternacaoRegistro, InternacaoEvolucao, InternacaoEvento,
)
from time_utils import BR_TZ, normalize_to_utc, utcnow


MAX_DIAS_AGENDA = 31
MAX_OCORRENCIAS = 1000
# Janela de checagem sem justificativa, simétrica em torno do horário previsto
# (referência usual para medicação não crítica: até 1 hora antes ou depois).
# Ajustável por ``INTERNACAO_TOLERANCIA_MINUTOS`` na configuração do app.
TOLERANCIA_PADRAO_MINUTOS = 60


def tolerancia_checagem():
    """Minutos de tolerância; valores inválidos voltam ao padrão seguro."""
    try:
        from flask import current_app
        value = int(current_app.config.get('INTERNACAO_TOLERANCIA_MINUTOS', TOLERANCIA_PADRAO_MINUTOS))
    except (RuntimeError, TypeError, ValueError):
        value = TOLERANCIA_PADRAO_MINUTOS
    return timedelta(minutes=min(max(value, 0), 240))


class InternacaoError(ValueError):
    pass


class InternacaoConflict(InternacaoError):
    pass


def _utc(value):
    """Banco: SQLite remove timezone, mas persistimos instantes UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _data(value, label):
    try:
        if not isinstance(value, (str, datetime)) or not value:
            raise ValueError()
        return normalize_to_utc(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InternacaoError(f'Informe {label} com data e horário válidos.') from exc


def _texto(data, field, *, required=False, maximum=10000):
    value = str(data.get(field) or '').strip()
    if required and not value:
        raise InternacaoError(f'O campo {field.replace("_", " ")} é obrigatório.')
    if len(value) > maximum:
        raise InternacaoError(f'O campo {field.replace("_", " ")} excede {maximum} caracteres.')
    return value or None


def _numero(value, field, *, integer=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > 1000000:
            raise ValueError()
        if integer and number != number.to_integral_value():
            raise ValueError()
        if not integer and number < Decimal('0.001'):
            raise ValueError()
        if not integer and number != number.quantize(Decimal('0.001')):
            raise ValueError()
        return int(number) if integer else number.quantize(Decimal('0.001'))
    except (TypeError, InvalidOperation, ValueError) as exc:
        raise InternacaoError(f'Informe {field.replace("_", " ")} positivo e válido.') from exc


def _actor_id(actor):
    identifier = getattr(actor, 'id', actor)
    if not identifier or db.session.get(User, identifier) is None:
        raise InternacaoError('Funcionário responsável pelo registro não encontrado.')
    return identifier


def _lock_internacao(internacao, *, ativa=True):
    identifier = getattr(internacao, 'id', internacao)
    obj = db.session.query(Internacao).filter_by(id=identifier).populate_existing().with_for_update().first()
    if obj is None:
        raise InternacaoError('Internação não encontrada.')
    if ativa and obj.status != 'ativa':
        raise InternacaoConflict('A internação já foi encerrada.')
    return obj


def _lock_prescricao(prescricao, *, ativa=True):
    obj = db.session.get(InternacaoPrescricao, getattr(prescricao, 'id', prescricao))
    if obj is None:
        raise InternacaoError('Prescrição não encontrada.')
    internacao = _lock_internacao(obj.internacao_id, ativa=ativa)
    obj = db.session.query(InternacaoPrescricao).filter_by(id=obj.id).populate_existing().with_for_update().one()
    if ativa and obj.status != 'ativa':
        raise InternacaoConflict('Esta versão da prescrição não está ativa. Atualize a página.')
    return obj, internacao


def _evento(internacao, actor_id, tipo, dados=None):
    db.session.add(InternacaoEvento(internacao_id=internacao.id, autor_id=actor_id, tipo=tipo, dados=dados, criado_em=utcnow()))


def _normalizar_prescricao(data):
    inicio = _data(data.get('inicio_em'), 'o início da prescrição')
    modo = data.get('modo')
    if modo not in ('intervalo', 'fixos', 'unica', 'prn'):
        raise InternacaoError('Selecione frequência por intervalo, horários fixos, dose única ou se necessário.')
    fim = _data(data['fim_em'], 'o fim da prescrição') if data.get('fim_em') else None
    if fim is None or fim <= inicio:
        raise InternacaoError('Informe fim da prescrição posterior ao início (fim exclusivo).')
    if fim - inicio > timedelta(days=MAX_DIAS_AGENDA):
        raise InternacaoError(f'O piloto permite até {MAX_DIAS_AGENDA} dias por prescrição; divida o período explicitamente.')
    result = dict(modo=modo, inicio_em=inicio, fim_em=fim,
                  intervalo_horas=None, horarios_fixos=None,
                  intervalo_minimo_horas=None, max_doses_24h=None)
    if modo == 'intervalo':
        result['intervalo_horas'] = _numero(data.get('intervalo_horas'), 'intervalo_horas')
    elif modo == 'fixos':
        horarios = data.get('horarios_fixos') or []
        if isinstance(horarios, str):
            horarios = horarios.replace(';', ',').split(',')
        if not isinstance(horarios, (list, tuple)) or not horarios or len(horarios) > 24:
            raise InternacaoError('Informe entre 1 e 24 horários fixos no formato HH:MM.')
        parsed = []
        for horario in horarios:
            try:
                value = str(horario).strip()
                if len(value) != 5 or value[2] != ':':
                    raise ValueError()
                parsed.append(time.fromisoformat(value).strftime('%H:%M'))
            except ValueError as exc:
                raise InternacaoError('Horários fixos devem usar HH:MM, como 08:00, 20:00.') from exc
        if len(set(parsed)) != len(parsed):
            raise InternacaoError('Não repita um horário fixo na mesma prescrição.')
        result['horarios_fixos'] = sorted(parsed)
    elif modo == 'prn':
        result['intervalo_minimo_horas'] = _numero(data.get('intervalo_minimo_horas'), 'intervalo_minimo_horas')
        result['max_doses_24h'] = _numero(data.get('max_doses_24h'), 'max_doses_24h', integer=True)
        result['indicacao_prn'] = _texto(data, 'indicacao_prn', required=True)
    return result


def prever_horarios(data):
    """Agenda completa, com início incluso e fim exclusivo; PRN não gera doses."""
    config = _normalizar_prescricao(data)
    inicio, fim, modo = config['inicio_em'], config['fim_em'], config['modo']
    if modo == 'prn':
        return []
    if modo == 'unica':
        return [inicio]
    horarios = []
    if modo == 'intervalo':
        intervalo = timedelta(seconds=float(config['intervalo_horas'] * 3600))
        quantidade = int((fim - inicio - timedelta(microseconds=1)) // intervalo) + 1
        if quantidade > MAX_OCORRENCIAS:
            raise InternacaoError(f'A agenda excede {MAX_OCORRENCIAS} ocorrências; reduza o período.')
        horarios = [inicio + i * intervalo for i in range(quantidade)]
    else:
        dia = inicio.astimezone(BR_TZ).date()
        ultimo = fim.astimezone(BR_TZ).date()
        while dia <= ultimo:
            for horario in config['horarios_fixos']:
                candidato = datetime.combine(dia, time.fromisoformat(horario), tzinfo=BR_TZ).astimezone(timezone.utc)
                if inicio <= candidato < fim:
                    horarios.append(candidato)
            dia += timedelta(days=1)
        if len(horarios) > MAX_OCORRENCIAS:
            raise InternacaoError(f'A agenda excede {MAX_OCORRENCIAS} ocorrências; reduza o período.')
    if not horarios:
        raise InternacaoError('Nenhum horário está dentro do período. Confira a prévia e o fim exclusivo.')
    return horarios


def criar_internacao(clinica_id, animal, actor, data):
    actor_id = _actor_id(actor)
    animal = db.session.get(Animal, getattr(animal, 'id', animal))
    if animal is None:
        raise InternacaoError('Animal não encontrado.')
    # A trava do animal serializa admissões; o índice parcial também garante
    # a unicidade se a operação for executada fora deste serviço.
    db.session.query(Animal).filter_by(id=animal.id).with_for_update().one()
    if Internacao.query.filter_by(clinica_id=clinica_id, animal_id=animal.id, status='ativa').first():
        raise InternacaoConflict('O animal já possui internação ativa nesta clínica.')
    consulta_id = data.get('consulta_id') or None
    if consulta_id:
        consulta = db.session.get(Consulta, int(consulta_id))
        if consulta is None or consulta.animal_id != animal.id or consulta.clinica_id != clinica_id:
            raise InternacaoError('Consulta não corresponde ao animal e à clínica desta internação.')
    if animal.clinica_id not in (None, clinica_id) and not consulta_id:
        vinculo_local = Consulta.query.filter_by(animal_id=animal.id, clinica_id=clinica_id).first()
        if vinculo_local is None:
            raise InternacaoError('Animal não possui vínculo de atendimento com a clínica selecionada.')
    iniciada = _data(data['iniciada_em'], 'a admissão') if data.get('iniciada_em') else utcnow()
    if iniciada > utcnow():
        raise InternacaoError('A admissão não pode estar no futuro.')
    responsavel_id = _actor_id(data.get('responsavel_id') or actor_id)
    internacao = Internacao(
        clinica_id=clinica_id, animal_id=animal.id, consulta_id=consulta_id,
        criado_por_id=actor_id, responsavel_id=responsavel_id,
        status='ativa', motivo=_texto(data, 'motivo', required=True),
        leito=_texto(data, 'leito', maximum=100), alergias=_texto(data, 'alergias'),
        observacoes=_texto(data, 'observacoes'), iniciada_em=iniciada,
        peso_kg=_numero(data['peso_kg'], 'peso_kg') if data.get('peso_kg') else None,
    )
    db.session.add(internacao)
    db.session.flush()
    _evento(internacao, actor_id, 'admissao')
    return internacao


def _criar_prescricao(internacao, actor_id, data, *, anterior=None):
    config = _normalizar_prescricao(data)
    horarios = prever_horarios(data)
    if config['inicio_em'] < _utc(internacao.iniciada_em):
        raise InternacaoError('A prescrição não pode começar antes da admissão.')
    # Revisões entram em vigor agora ou no futuro. Retroatividade reescreveria
    # uma agenda que a equipe já consultou ou executou.
    if anterior and config['inicio_em'] < utcnow() - timedelta(minutes=1):
        raise InternacaoError('A revisão deve começar agora ou no futuro.')
    if anterior and anterior.anterior_id and config['inicio_em'] < _utc(anterior.inicio_em):
        raise InternacaoError(
            'A revisão de uma versão futura deve começar no mesmo horário ou depois '
            'do início dessa versão, para não sobrepor a prescrição anterior ainda vigente.'
        )
    prescricao = InternacaoPrescricao(
        internacao_id=internacao.id, anterior_id=anterior.id if anterior else None,
        versao=anterior.versao + 1 if anterior else 1,
        status='ativa', criado_por_id=actor_id, criada_em=utcnow(),
        medicamento=_texto(data, 'medicamento', required=True, maximum=240),
        apresentacao=_texto(data, 'apresentacao', maximum=240),
        dose=_texto(data, 'dose', required=True, maximum=240),
        via=_texto(data, 'via', required=True, maximum=100),
        instrucoes=_texto(data, 'instrucoes'),
        limites_prn=_texto(data, 'limites_prn'), **config,
    )
    db.session.add(prescricao)
    db.session.flush()
    for prevista in horarios:
        db.session.add(InternacaoOcorrencia(internacao_id=internacao.id, prescricao_id=prescricao.id,
                                           prevista_para=prevista, status='pendente'))
    _evento(internacao, actor_id, 'prescricao_revisada' if anterior else 'prescricao_publicada',
            {'prescricao_id': prescricao.id, 'anterior_id': anterior.id if anterior else None,
             'inicio_em': prescricao.inicio_em.isoformat(),
             'motivo': _texto(data, 'motivo') if anterior else None})
    db.session.flush()
    return prescricao


def prescrever(internacao, actor, data):
    return _criar_prescricao(_lock_internacao(internacao), _actor_id(actor), data)


def _cancelar_pendentes(prescricao, motivo, agora, *, desde=None):
    query = InternacaoOcorrencia.query.filter_by(prescricao_id=prescricao.id, status='pendente')
    if desde is not None:
        query = query.filter(InternacaoOcorrencia.prevista_para >= desde)
    query.update({'status': 'cancelada', 'cancelada_em': agora, 'motivo_cancelamento': motivo}, synchronize_session='fetch')


def revisar_prescricao(prescricao, actor, data):
    anterior, internacao = _lock_prescricao(prescricao)
    actor_id = _actor_id(actor)
    motivo = _texto(data, 'motivo', required=True)
    nova = _criar_prescricao(internacao, actor_id, data, anterior=anterior)
    agora = utcnow()
    anterior.status = 'substituida'
    anterior.suspensa_em = nova.inicio_em
    anterior.suspensa_por_id = actor_id
    anterior.motivo_suspensao = motivo
    # Pendências anteriores à vigência da revisão permanecem no histórico,
    # podendo receber lançamento retrospectivo do período anterior.
    _cancelar_pendentes(anterior, 'revisao', agora, desde=nova.inicio_em)
    db.session.flush()
    return nova


def suspender_prescricao(prescricao, actor, motivo):
    prescricao, internacao = _lock_prescricao(prescricao, ativa=False)
    if internacao.status != 'ativa':
        raise InternacaoConflict('A internação já foi encerrada.')
    agora = utcnow()
    substituicao_futura = (prescricao.status == 'substituida' and prescricao.suspensa_em
                          and agora < _utc(prescricao.suspensa_em))
    if prescricao.status != 'ativa' and not substituicao_futura:
        raise InternacaoConflict('Esta versão da prescrição já foi suspensa ou encerrada.')
    actor_id = _actor_id(actor)
    motivo = _texto({'motivo': motivo}, 'motivo', required=True)
    # Se uma revisão futura já existe, suspender o item atual também impede
    # que essa versão futura passe a produzir tarefas após a suspensão.
    cadeia = [prescricao]
    while True:
        seguinte = InternacaoPrescricao.query.filter_by(anterior_id=cadeia[-1].id).first()
        if seguinte is None:
            break
        cadeia.append(seguinte)
    for item in cadeia:
        item.status = 'suspensa'
        item.suspensa_em = agora
        item.suspensa_por_id = actor_id
        item.motivo_suspensao = motivo
        _cancelar_pendentes(item, 'suspensao', agora)
    _evento(internacao, actor_id, 'prescricao_suspensa',
            {'prescricao_id': prescricao.id, 'versoes_suspensas': [item.id for item in cadeia], 'motivo': motivo})
    db.session.flush()
    return prescricao


def _key(data):
    return _texto(data, 'idempotency_key', maximum=100)


def _retry(internacao_id, data, actor_id, *, prescricao_id, ocorrencia_id, acao, retifica_id=None):
    key = _key(data)
    if key is None:
        return None
    existing = InternacaoRegistro.query.filter_by(internacao_id=internacao_id, idempotency_key=key).first()
    if existing:
        if (existing.autor_id != actor_id or existing.prescricao_id != prescricao_id or
                existing.ocorrencia_id != ocorrencia_id or existing.acao != acao or
                existing.retifica_id != retifica_id):
            raise InternacaoConflict('Chave de repetição já usada por outro registro.')
        return existing
    return None


def _momento_execucao(internacao, data, agora, *, omitida=False):
    explicit = bool(data.get('executada_em'))
    executada = _data(data['executada_em'], 'a administração') if explicit else agora
    motivo = _texto(data, 'motivo')
    if executada > agora:
        raise InternacaoError('O horário realizado não pode estar no futuro.')
    if executada < _utc(internacao.iniciada_em):
        raise InternacaoError('O horário realizado não pode ser anterior à admissão.')
    if explicit and executada < agora and not motivo:
        raise InternacaoError('Registro retrospectivo exige justificativa.')
    if omitida and not motivo:
        raise InternacaoError('Informe o motivo da não administração.')
    if internacao.status != 'ativa':
        if not explicit or not motivo or executada > _utc(internacao.encerrada_em):
            raise InternacaoConflict('Após alta, informe horário anterior à alta e justificativa para lançamento histórico.')
    return executada, motivo


def _vigencia(prescricao, executada, *, explicit):
    if executada < _utc(prescricao.inicio_em):
        raise InternacaoError('Administração anterior ao início da prescrição.')
    if executada >= _utc(prescricao.fim_em):
        raise InternacaoConflict('Horário realizado fora da vigência da prescrição (fim exclusivo).')
    if prescricao.suspensa_em and executada >= _utc(prescricao.suspensa_em):
        raise InternacaoConflict('Prescrição suspensa ou substituída neste horário.')
    substituicao_futura = (prescricao.status == 'substituida' and prescricao.suspensa_em
                          and executada < _utc(prescricao.suspensa_em))
    if prescricao.status in ('suspensa', 'substituida', 'encerrada') and not explicit and not substituicao_futura:
        raise InternacaoConflict('Esta versão da prescrição não está ativa. Atualize a página.')


def _autorizar_historico(internacao, actor_id):
    # Revalidação após adquirir a trava: a alta pode ter ocorrido entre a
    # autorização HTTP da equipe e o início efetivo desta transação.
    if internacao.status != 'ativa':
        from services.internacao_access import pode_prescrever_internacao
        if not pode_prescrever_internacao(db.session.get(User, actor_id), internacao.clinica_id):
            raise InternacaoConflict('Lançamento após alta exige veterinário autorizado da clínica.')


def _registrar_ocorrencia(ocorrencia, actor, data, *, omitida=False):
    actor_id = _actor_id(actor)
    obj = db.session.get(InternacaoOcorrencia, getattr(ocorrencia, 'id', ocorrencia))
    if obj is None:
        raise InternacaoError('Dose não encontrada.')
    internacao = _lock_internacao(obj.internacao_id, ativa=False)
    prescricao = db.session.query(InternacaoPrescricao).filter_by(id=obj.prescricao_id).populate_existing().with_for_update().one()
    obj = db.session.query(InternacaoOcorrencia).filter_by(id=obj.id).populate_existing().with_for_update().one()
    if prescricao.internacao_id != internacao.id:
        raise InternacaoError('Dose não corresponde à internação.')
    acao, resultado = ('omissao', 'omitida') if omitida else ('administracao', 'administrada')
    retry = _retry(internacao.id, data, actor_id, prescricao_id=prescricao.id, ocorrencia_id=obj.id, acao=acao)
    if retry:
        return retry
    agora = utcnow()
    executada, motivo = _momento_execucao(internacao, data, agora, omitida=omitida)
    _autorizar_historico(internacao, actor_id)
    _vigencia(prescricao, executada, explicit=bool(data.get('executada_em')))
    tolerancia = tolerancia_checagem()
    minutos = int(tolerancia.total_seconds() // 60)
    if executada < _utc(obj.prevista_para) - tolerancia and not motivo:
        raise InternacaoError(
            f'Administração mais de {minutos} min antes do horário previsto exige justificativa.')
    if executada > _utc(obj.prevista_para) + tolerancia and not motivo:
        raise InternacaoError(
            f'Dose checada mais de {minutos} min após o horário previsto: informe a justificativa do atraso.')
    if obj.status not in ('pendente', 'cancelada'):
        raise InternacaoConflict('Esta dose já foi registrada. Atualize a página para consultar o responsável.')
    if obj.status == 'cancelada':
        if (not data.get('executada_em') or not motivo or not obj.cancelada_em or
                executada > _utc(obj.cancelada_em) or
                (obj.motivo_cancelamento == 'revisao' and executada >= _utc(prescricao.suspensa_em))):
            raise InternacaoConflict('Dose cancelada: permitido apenas lançamento histórico anterior ao cancelamento, com justificativa.')
    status_anterior = obj.status
    changed = db.session.execute(update(InternacaoOcorrencia).where(
        InternacaoOcorrencia.id == obj.id, InternacaoOcorrencia.status == status_anterior,
    ).values(status=resultado), execution_options={'synchronize_session': 'fetch'})
    if changed.rowcount != 1:
        raise InternacaoConflict('Outro funcionário já registrou esta dose. Atualize a página.')
    registro = InternacaoRegistro(
        internacao_id=internacao.id, prescricao_id=prescricao.id, ocorrencia_id=obj.id,
        acao=acao, resultado=resultado, executada_em=executada,
        registrada_em=agora, autor_id=actor_id, motivo=motivo,
        observacoes=_texto(data, 'observacoes'), idempotency_key=_key(data),
    )
    db.session.add(registro)
    db.session.flush()
    return registro


def registrar_administracao(ocorrencia, actor, data):
    return _registrar_ocorrencia(ocorrencia, actor, data)


def omitir_ocorrencia(ocorrencia, actor, data):
    return _registrar_ocorrencia(ocorrencia, actor, data, omitida=True)


def _prn_limites(prescricao, executada, *, excluir=None):
    """Últimos eventos das cadeias: retificação não duplica nem apaga doses."""
    # Uma revisão do mesmo item não zera doses das últimas 24 horas.
    versoes = InternacaoPrescricao.query.filter_by(internacao_id=prescricao.internacao_id).all()
    por_id = {item.id: item for item in versoes}
    raiz = prescricao
    while raiz.anterior_id:
        raiz = por_id[raiz.anterior_id]
    familia = {raiz.id}
    for item in sorted(versoes, key=lambda item: item.versao):
        if item.anterior_id in familia:
            familia.add(item.id)
    registros = InternacaoRegistro.query.filter(InternacaoRegistro.prescricao_id.in_(familia)).all()
    substituidos = {r.retifica_id for r in registros if r.retifica_id is not None}
    doses = [r for r in registros if r.id not in substituidos and r.id != excluir
             and r.resultado == 'administrada' and r.executada_em is not None]
    minimo = timedelta(hours=float(prescricao.intervalo_minimo_horas))
    if any(abs(_utc(r.executada_em) - executada) < minimo for r in doses):
        raise InternacaoConflict('Intervalo mínimo da prescrição se necessário ainda não foi respeitado.')
    # Verifica todas as janelas que conteriam a nova dose, incluindo doses
    # posteriores já registradas quando o lançamento é retrospectivo.
    instantes = sorted([_utc(r.executada_em) for r in doses] + [executada])
    janela = timedelta(hours=24)
    for inicio in instantes:
        if inicio <= executada < inicio + janela:
            quantidade = sum(inicio <= instante < inicio + janela for instante in instantes)
            if quantidade > prescricao.max_doses_24h:
                raise InternacaoConflict('Limite de administrações em 24 horas atingido para esta prescrição.')


def registrar_prn(prescricao, actor, data):
    actor_id = _actor_id(actor)
    prescricao, internacao = _lock_prescricao(prescricao, ativa=False)
    if prescricao.modo != 'prn':
        raise InternacaoError('Use uma ocorrência programada para registrar este medicamento.')
    retry = _retry(internacao.id, data, actor_id, prescricao_id=prescricao.id, ocorrencia_id=None, acao='administracao')
    if retry:
        return retry
    agora = utcnow()
    executada, motivo = _momento_execucao(internacao, data, agora)
    _autorizar_historico(internacao, actor_id)
    _vigencia(prescricao, executada, explicit=bool(data.get('executada_em')))
    if executada >= _utc(prescricao.fim_em):
        raise InternacaoConflict('Prescrição se necessário fora do período de vigência.')
    _prn_limites(prescricao, executada)
    registro = InternacaoRegistro(
        internacao_id=internacao.id, prescricao_id=prescricao.id, acao='administracao',
        resultado='administrada', executada_em=executada, registrada_em=agora,
        autor_id=actor_id, motivo=motivo, observacoes=_texto(data, 'observacoes'),
        idempotency_key=_key(data),
    )
    db.session.add(registro)
    db.session.flush()
    return registro


def retificar_registro(registro, actor, data):
    actor_id = _actor_id(actor)
    registro = db.session.get(InternacaoRegistro, getattr(registro, 'id', registro))
    if registro is None:
        raise InternacaoError('Registro não encontrado.')
    prescricao, internacao = _lock_prescricao(registro.prescricao_id, ativa=False)
    retry = _retry(internacao.id, data, actor_id, prescricao_id=prescricao.id,
                   ocorrencia_id=registro.ocorrencia_id, acao='retificacao', retifica_id=registro.id)
    if retry:
        return retry
    if InternacaoRegistro.query.filter_by(retifica_id=registro.id).first():
        raise InternacaoConflict('Este registro já foi retificado. Selecione a última retificação.')
    motivo = _texto(data, 'motivo', required=True)
    resultado = data.get('resultado') or registro.resultado
    if resultado not in ('administrada', 'omitida', 'pendente'):
        raise InternacaoError('Resultado da retificação inválido.')
    agora = utcnow()
    _autorizar_historico(internacao, actor_id)
    executada = _data(data['executada_em'], 'a administração') if data.get('executada_em') else _utc(registro.executada_em) if registro.executada_em else agora
    if internacao.status != 'ativa' and (not data.get('executada_em') or executada > _utc(internacao.encerrada_em)):
        raise InternacaoError('Retificação após alta exige horário explícito anterior à alta.')
    if executada > agora or executada < _utc(internacao.iniciada_em):
        raise InternacaoError('Horário da retificação fora do período permitido.')
    if resultado == 'administrada':
        _vigencia(prescricao, executada, explicit=True)
        if prescricao.modo == 'prn':
            if executada >= _utc(prescricao.fim_em):
                raise InternacaoError('Horário da retificação fora da vigência da prescrição.')
            _prn_limites(prescricao, executada, excluir=registro.id)
    if registro.ocorrencia_id:
        ocorrencia = db.session.query(InternacaoOcorrencia).filter_by(id=registro.ocorrencia_id).populate_existing().with_for_update().one()
        ultimo = InternacaoRegistro.query.filter_by(ocorrencia_id=ocorrencia.id).order_by(InternacaoRegistro.id.desc()).first()
        if ultimo.id != registro.id:
            raise InternacaoConflict('Selecione o registro mais recente desta dose para retificar.')
        # Uma substituição agendada preserva a versão atual até o corte.
        # Retificar para pendente nesse intervalo permite a rechecagem
        # explícita, sem reabrir agendas que já terminaram de fato.
        fim_atingido = agora >= _utc(prescricao.fim_em)
        corte_atingido = bool(prescricao.suspensa_em and agora >= _utc(prescricao.suspensa_em))
        nao_reabrir = (
            internacao.status != 'ativa' or fim_atingido or corte_atingido
            or prescricao.status in ('suspensa', 'encerrada')
        )
        ocorrencia.status = 'cancelada' if resultado == 'pendente' and nao_reabrir else resultado
        if ocorrencia.status == 'cancelada':
            ocorrencia.cancelada_em = ocorrencia.cancelada_em or agora
            if not ocorrencia.motivo_cancelamento:
                ocorrencia.motivo_cancelamento = (
                    'alta' if internacao.status != 'ativa' else
                    'fim_prescricao' if fim_atingido else
                    'revisao' if prescricao.status == 'substituida' else 'suspensao'
                )
    nova = InternacaoRegistro(
        internacao_id=internacao.id, prescricao_id=prescricao.id,
        ocorrencia_id=registro.ocorrencia_id, acao='retificacao', resultado=resultado,
        executada_em=executada if resultado != 'pendente' else None,
        registrada_em=agora, autor_id=actor_id, motivo=motivo,
        observacoes=_texto(data, 'observacoes'), idempotency_key=_key(data), retifica_id=registro.id,
    )
    db.session.add(nova)
    db.session.flush()
    return nova


def registrar_evolucao(internacao, actor, data):
    internacao = _lock_internacao(internacao)
    tipo = data.get('tipo') or 'evolucao'
    if tipo not in ('evolucao', 'plantao'):
        raise InternacaoError('Tipo de anotação inválido.')
    parametros = data.get('parametros') or None
    if parametros is not None and not isinstance(parametros, dict):
        raise InternacaoError('Parâmetros clínicos devem ser um objeto estruturado.')
    if parametros is not None and (
        len(parametros) > 20
        or any(len(str(chave)) > 80 or len(str(valor)) > 240 for chave, valor in parametros.items())
    ):
        raise InternacaoError('Informe até 20 parâmetros clínicos, com nome de até 80 e valor de até 240 caracteres.')
    evolucao = InternacaoEvolucao(
        internacao_id=internacao.id, tipo=tipo, texto=_texto(data, 'texto', required=True),
        pendencias=_texto(data, 'pendencias'), parametros=parametros,
        autor_id=_actor_id(actor), criada_em=utcnow(),
    )
    db.session.add(evolucao)
    db.session.flush()
    return evolucao


def dar_alta(internacao, actor, data):
    internacao = _lock_internacao(internacao)
    actor_id = _actor_id(actor)
    resumo = _texto(data, 'resumo_alta', required=True)
    agora = utcnow()
    internacao.status = 'alta'
    internacao.encerrada_em = agora
    internacao.alta_por_id = actor_id
    internacao.resumo_alta = resumo
    # Leia as versões após a trava; uma coleção carregada pela tela antes
    # de outra publicação não pode deixar uma prescrição aberta na alta.
    prescricoes = InternacaoPrescricao.query.filter_by(internacao_id=internacao.id).populate_existing().all()
    for prescricao in prescricoes:
        if prescricao.status == 'ativa':
            prescricao.status = 'encerrada'
            prescricao.suspensa_em = agora
            prescricao.suspensa_por_id = actor_id
            prescricao.motivo_suspensao = 'Alta da internação'
        _cancelar_pendentes(prescricao, 'alta', agora)
    _evento(internacao, actor_id, 'alta', {'resumo_alta': resumo})
    db.session.flush()
    return internacao


def resumo_internacao(internacao, agora=None):
    agora = _utc(agora or utcnow())
    contagem = dict(pendentes=0, administradas=0, omitidas=0, canceladas=0, atrasadas=0)
    keys = {'pendente': 'pendentes', 'administrada': 'administradas', 'omitida': 'omitidas', 'cancelada': 'canceladas'}
    for ocorrencia in internacao.ocorrencias:
        contagem[keys[ocorrencia.status]] += 1
        if ocorrencia.status == 'pendente' and _utc(ocorrencia.prevista_para) < agora:
            contagem['atrasadas'] += 1
    contagem['total'] = sum(contagem[k] for k in ('pendentes', 'administradas', 'omitidas', 'canceladas'))
    contagem['prescricoes_ativas'] = sum(p.status == 'ativa' for p in internacao.prescricoes)
    return contagem
