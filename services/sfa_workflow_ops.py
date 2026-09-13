"""Comandos internos validados; auditoria e alteração na mesma transação."""
import json
from decimal import Decimal, InvalidOperation

from extensions import db
from models.sfa import (SfaPaciente, SfaContextoEpisodio, SfaContato,
                        SfaEventoColetivo, SfaEventoVinculo, SfaAcao, SfaAuditoria)
from time_utils import utcnow
from services.sfa_workflow import hoje_local, aplicar_calendario


def registrar_operacao(form, ator):
    from services.sfa_service import parse_data, atualizar_operacional_paciente
    from services.entomologia_service import load_entomologia

    def texto(campo, limite=200, obrigatorio=True):
        value = str(form.get(campo) or "").strip()
        if (obrigatorio and not value) or len(value) > limite:
            raise ValueError(f"Preencha {campo} com até {limite} caracteres.")
        return value

    def escolha(campo, opcoes):
        value = texto(campo)
        if value not in opcoes:
            raise ValueError(f"Opção inválida: {campo}.")
        return value

    def data(campo, obrigatorio=True, futuro=True):
        value = texto(campo, 20, obrigatorio)
        parsed = parse_data(value)
        if (value and not parsed) or (obrigatorio and not parsed) or (parsed and not futuro and parsed > hoje_local()):
            raise ValueError(f"Data inválida: {campo}.")
        return parsed

    def buscar(model, campo):
        value = texto(campo, 30)
        if not value.isdigit():
            raise ValueError(f"Identificador inválido: {campo}.")
        row = db.session.get(model, int(value))
        if not row:
            raise ValueError(f"Registro não encontrado: {campo}.")
        return row

    def setor_validado(value):
        setores = {str(r.get('sector') or '') for r in load_entomologia().get('records', [])}
        if value and value not in setores:
            raise ValueError("Setor não encontrado na malha operacional do levantamento. Confira o código completo.")
        return value

    operacao = texto('operacao', 30)
    responsavel = texto('responsavel', 160)
    episodio = texto('id_estudo', 30, False)
    paciente = SfaPaciente.query.filter_by(id_estudo=episodio).first() if episodio else None
    if episodio and not paciente:
        raise ValueError("Episódio não encontrado.")
    if operacao in {'contexto', 'contato', 'vinculo'} and not paciente:
        raise ValueError("Selecione o episódio.")
    antes = {}
    registro = None

    if operacao == 'contexto':
        contexto = paciente.contexto or SfaContextoEpisodio(id_estudo=episodio)
        antes = {c.name: str(getattr(contexto, c.name) or '') for c in contexto.__table__.columns}
        inicio = data('inicio_sintomas', False, False)
        fonte_inicio = texto('fonte_inicio', 200, bool(inicio))
        setor = setor_validado(texto('setor', 15, False))
        validado = form.get('local_validado') == '1'
        fonte_local = texto('fonte_local', 200, validado)
        tipo_local = escolha('tipo_local', {'RESIDENCIA', 'PROVAVEL_INFECCAO', 'INDEFINIDO'})
        if validado and (not setor or tipo_local == 'INDEFINIDO'):
            raise ValueError("Para validar o território, informe setor, tipo de local e fonte da conferência.")
        classificacao = escolha('classificacao', {'INDEFINIDA', 'SUSPEITO', 'CONFIRMADO', 'DESCARTADO'})
        fonte_classificacao = texto('fonte_classificacao', 200, classificacao != 'INDEFINIDA')
        contexto.inicio_sintomas, contexto.fonte_inicio = inicio, fonte_inicio
        contexto.setor, contexto.malha = setor, 'operacional'
        contexto.local_validado, contexto.fonte_local = validado, fonte_local
        contexto.tipo_local, contexto.responsavel = tipo_local, responsavel
        contexto.classificacao, contexto.fonte_classificacao = classificacao, fonte_classificacao
        paciente.contexto = contexto
        db.session.add(contexto)
        aplicar_calendario(paciente)
        atualizar_operacional_paciente(paciente)
        registro = contexto

    elif operacao == 'contato':
        etapa = escolha('etapa', {'T0', 'T7', 'T30', 'REVISAO'})
        canal = escolha('canal', {'TELEFONE', 'WHATSAPP', 'PRESENCIAL', 'OUTRO'})
        resultado = escolha('resultado', {'ACEITOU', 'RECUSOU', 'SEM_RETORNO', 'NAO_LOCALIZADO', 'REAGENDADO', 'PERDA_CONFIRMADA'})
        motivo = texto('motivo', 2000, resultado in {'RECUSOU', 'PERDA_CONFIRMADA', 'REAGENDADO'})
        proximo = data('proximo_contato', resultado == 'REAGENDADO')
        if proximo and proximo < hoje_local():
            raise ValueError("O próximo contato não pode estar no passado.")
        antes = {'retorno_contato': paciente.retorno_contato, 'status_geral': paciente.status_geral}
        registro = SfaContato(id_estudo=episodio, etapa=etapa, canal=canal, resultado=resultado,
                              responsavel=responsavel, motivo=motivo, proximo_contato=proximo)
        paciente.contatos.append(registro)
        paciente.retorno_contato = resultado
        if resultado == 'PERDA_CONFIRMADA':
            paciente.status_geral = 'PERDA_SEGUIMENTO'
        elif resultado == 'ACEITOU' and paciente.status_geral == 'PERDA_SEGUIMENTO':
            paciente.status_geral = 'Em_Andamento' if paciente.resposta_t0 else 'SINAN_Notificado'
        atualizar_operacional_paciente(paciente)

    elif operacao == 'evento':
        inicio, fim = data('inicio', futuro=False), data('fim', False, False)
        if fim and fim < inicio:
            raise ValueError("O fim do evento não pode preceder seu início.")
        registro = SfaEventoColetivo(titulo=texto('titulo'), local=texto('local', 300),
                                     inicio=inicio, fim=fim, exposicao=texto('exposicao', 3000), avaliacao='PENDENTE')

    elif operacao == 'avaliacao':
        registro = buscar(SfaEventoColetivo, 'evento_id')
        antes = {'avaliacao': registro.avaliacao, 'justificativa': registro.justificativa}
        avaliacao = escolha('avaliacao', {'PENDENTE', 'ACIONAVEL', 'NAO_ACIONAVEL', 'INCONCLUSIVO'})
        justificativa = texto('justificativa', 3000)
        registro.avaliacao, registro.justificativa = avaliacao, justificativa
        registro.avaliador, registro.avaliado_em = responsavel, utcnow()

    elif operacao == 'vinculo':
        evento = buscar(SfaEventoColetivo, 'evento_id')
        if db.session.get(SfaEventoVinculo, (evento.id, episodio)):
            raise ValueError("Episódio já vinculado a esse evento.")
        registro = SfaEventoVinculo(evento_id=evento.id, id_estudo=episodio, fonte=texto('fonte'))

    elif operacao == 'acao':
        evento = buscar(SfaEventoColetivo, 'evento_id') if form.get('evento_id') else None
        setor = setor_validado(texto('setor', 15, False))
        if not (paciente or evento or setor):
            raise ValueError("Vincule a ação a um episódio, evento ou setor.")
        registro = SfaAcao(id_estudo=episodio or None, evento_id=evento.id if evento else None,
                           setor=setor, tipo=texto('tipo', 40), motivo=texto('motivo', 3000),
                           responsavel=responsavel, prazo=data('prazo'), status='ABERTA')

    elif operacao == 'acao_status':
        registro = buscar(SfaAcao, 'acao_id')
        episodio = registro.id_estudo or ''
        antes = {'status': registro.status, 'resultado': registro.resultado}
        status = escolha('status', {'EM_ANDAMENTO', 'EXECUTADA', 'VERIFICADA', 'ABERTA'})
        transicoes = {'ABERTA': {'EM_ANDAMENTO', 'EXECUTADA'}, 'EM_ANDAMENTO': {'EXECUTADA'},
                      'EXECUTADA': {'VERIFICADA', 'ABERTA'}, 'VERIFICADA': {'ABERTA'}}
        if status not in transicoes.get(registro.status, set()):
            raise ValueError("Transição inválida. Execute a ação antes de verificar seu resultado.")
        resultado = texto('resultado', 3000, status != 'EM_ANDAMENTO')
        evidencia = texto('evidencia_verificacao', 3000, status == 'VERIFICADA')
        numeros = {}
        for campo, maximo in [('horas', Decimal('999999.99')), ('custo', Decimal('99999999.99'))]:
            raw = texto(campo, 30, False)
            if raw:
                try:
                    numero = Decimal(raw.replace(',', '.'))
                except InvalidOperation:
                    raise ValueError(f"Valor inválido: {campo}.")
                if not numero.is_finite() or not 0 <= numero <= maximo or numero.as_tuple().exponent < -2:
                    raise ValueError(f"Informe {campo} não negativo, com até duas casas decimais.")
                numeros[campo] = numero
        registro.status = status
        if resultado:
            registro.resultado = resultado
        for campo, numero in numeros.items():
            setattr(registro, campo, numero)
        if status == 'EXECUTADA':
            registro.executado_em = utcnow()
        elif status == 'VERIFICADA':
            registro.verificado_em, registro.verificador = utcnow(), responsavel
            registro.evidencia_verificacao = evidencia
        elif status == 'ABERTA':
            registro.executado_em = registro.verificado_em = None
            registro.verificador = registro.evidencia_verificacao = None
    else:
        raise ValueError("Operação desconhecida.")

    db.session.add(registro)
    db.session.flush()
    depois = {c.name: str(getattr(registro, c.name) or '') for c in registro.__table__.columns}
    db.session.add(SfaAuditoria(nivel='INFO', categoria='FLUXO_TRABALHO', funcao=operacao,
                               id_estudo=episodio, mensagem=f'{operacao} registrada por {responsavel}',
                               detalhes_json=json.dumps({'ator_autenticado': ator, 'responsavel_informado': responsavel,
                                                        'antes': antes, 'depois': depois}, ensure_ascii=False)))
    db.session.commit()
    return registro
