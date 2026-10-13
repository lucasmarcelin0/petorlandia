"""Rotas operacionais para o trabalho Casa a Casa e gestão de quarteirões.

Permite colorir e organizar quarteirões para impressão, registrar histórico
de quadras trabalhadas e receber em lote visitas domiciliares sincronizadas do
modo offline.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime

from flask import abort, current_app, jsonify, make_response, request
from flask_login import current_user

from extensions import db
from models.entomologia import EntomologiaQuarteiraoTrabalho, EntomologiaVisitaDomiciliar
from services.entomologia_service import consultar_sem_interromper
from time_utils import utcnow


def _ator():
    from flask import has_request_context
    if not has_request_context():
        return 'sem contexto'
    if current_user.is_authenticated:
        return str(current_user.get_id())
    return 'token_interno'


def _sem_cache(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def _parse_data(valor):
    if not valor:
        return None
    if isinstance(valor, (date, datetime)):
        return valor
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except Exception:
        try:
            return datetime.strptime(str(valor)[:10], '%Y-%m-%d').date()
        except Exception:
            return None


def register(bp, require_access):
    """Registra as rotas de campo no blueprint do SFA."""

    @bp.route('/entomologia/quarteiroes/estado')
    @require_access
    def entomologia_quarteiroes_estado():
        ciclo = request.args.get('ciclo', 'vigente')

        def consulta():
            rows = EntomologiaQuarteiraoTrabalho.query.filter_by(ciclo=ciclo).all()
            return [{
                'id': q.id,
                'setor': q.setor,
                'quarteirao': q.quarteirao,
                'ciclo': q.ciclo,
                'cor': q.cor or '',
                'responsavel': q.responsavel or '',
                'status': q.status,
                'trabalhado_em': q.trabalhado_em.isoformat() if q.trabalhado_em else None,
                'atualizado_em': q.atualizado_em.isoformat() if q.atualizado_em else None,
            } for q in rows]

        quadras = consultar_sem_interromper(consulta, [])

        # Resumo de visitas já gravadas por quarteirão
        def consulta_visitas():
            todas = EntomologiaVisitaDomiciliar.query.with_entities(
                EntomologiaVisitaDomiciliar.setor,
                EntomologiaVisitaDomiciliar.quarteirao,
                EntomologiaVisitaDomiciliar.situacao,
                EntomologiaVisitaDomiciliar.larvas_encontradas,
            ).all()
            agrupado = {}
            for v in todas:
                chave = f"{v.setor}-{v.quarteirao}"
                if chave not in agrupado:
                    agrupado[chave] = {'total': 0, 'abertas': 0, 'fechadas': 0, 'recusas': 0, 'larvas': 0}
                agrupado[chave]['total'] += 1
                if v.situacao == 'ABERTA':
                    agrupado[chave]['abertas'] += 1
                elif v.situacao == 'FECHADA':
                    agrupado[chave]['fechadas'] += 1
                elif v.situacao == 'RECUSA':
                    agrupado[chave]['recusas'] += 1
                if v.larvas_encontradas:
                    agrupado[chave]['larvas'] += 1
            return agrupado

        resumo_visitas = consultar_sem_interromper(consulta_visitas, {})

        return _sem_cache(jsonify({
            'status': 'ok',
            'ciclo': ciclo,
            'quarteiroes': quadras,
            'resumo_visitas': resumo_visitas,
        }))

    @bp.route('/entomologia/quarteiroes/salvar', methods=['POST'])
    @require_access
    def entomologia_quarteiroes_salvar():
        payload = request.get_json(force=True, silent=True) or {}
        items = payload.get('items')
        if not items and 'quarteirao' in payload:
            items = [payload]
        if not items:
            return jsonify({'error': 'Nenhum quarteirão informado.'}), 400

        ciclo_padrao = payload.get('ciclo', 'vigente')
        salvos = 0

        for item in items:
            setor = str(item.get('setor') or '').strip()
            quarteirao = str(item.get('quarteirao') or '').strip()
            if not setor or not quarteirao:
                continue

            ciclo = str(item.get('ciclo') or ciclo_padrao).strip()
            cor = str(item.get('cor') or '').strip()
            responsavel = str(item.get('responsavel') or '').strip()
            status = str(item.get('status') or 'PLANEJADO').upper().strip()
            if status not in {'PLANEJADO', 'EM_ANDAMENTO', 'TRABALHADO'}:
                status = 'PLANEJADO'

            registro = EntomologiaQuarteiraoTrabalho.query.filter_by(
                setor=setor, quarteirao=quarteirao, ciclo=ciclo
            ).first()

            agora = utcnow()
            if not registro:
                registro = EntomologiaQuarteiraoTrabalho(
                    setor=setor,
                    quarteirao=quarteirao,
                    ciclo=ciclo,
                    cor=cor or None,
                    responsavel=responsavel or None,
                    status=status,
                    trabalhado_em=agora if status == 'TRABALHADO' else None,
                    atualizado_em=agora,
                    criado_em=agora,
                )
                db.session.add(registro)
            else:
                if cor or 'cor' in item:
                    registro.cor = cor or None
                if responsavel or 'responsavel' in item:
                    registro.responsavel = responsavel or None
                registro.status = status
                if status == 'TRABALHADO' and not registro.trabalhado_em:
                    registro.trabalhado_em = agora
                elif status != 'TRABALHADO':
                    registro.trabalhado_em = None
                registro.atualizado_em = agora

            salvos += 1

        db.session.commit()
        return _sem_cache(jsonify({'status': 'ok', 'salvos': salvos}))

    @bp.route('/entomologia/visitas/sincronizar', methods=['POST'])
    @require_access
    def entomologia_visitas_sincronizar():
        payload = request.get_json(force=True, silent=True) or {}
        visitas = payload.get('visitas') or []
        if not isinstance(visitas, list):
            return jsonify({'error': 'Lista de visitas inválida.'}), 400

        inseridas = 0
        agora = utcnow()

        for v in visitas:
            uuid_local = str(v.get('uuid_local') or v.get('id') or '').strip()
            if not uuid_local:
                continue

            # Idempotência: se já existe, não duplica
            existente = EntomologiaVisitaDomiciliar.query.filter_by(uuid_local=uuid_local).first()
            if existente:
                continue

            setor = str(v.get('setor') or '').strip()
            quarteirao = str(v.get('quarteirao') or '').strip()
            situacao = str(v.get('situacao') or 'ABERTA').upper().strip()
            if situacao not in {'ABERTA', 'FECHADA', 'RECUSA', 'DESABITADO'}:
                situacao = 'ABERTA'

            criadouros = v.get('criadouros')
            if isinstance(criadouros, list):
                criadouros_json = json.dumps(criadouros, ensure_ascii=False)
            elif isinstance(criadouros, str):
                criadouros_json = criadouros
            else:
                criadouros_json = '[]'

            larvas = bool(v.get('larvas') or v.get('larvas_encontradas'))
            data_visita_dt = _parse_data(v.get('data_visita') or v.get('data'))
            data_visita = data_visita_dt.date() if isinstance(data_visita_dt, datetime) else data_visita_dt
            horario_visita = _parse_data(v.get('horario_visita') or v.get('timestamp'))

            nova = EntomologiaVisitaDomiciliar(
                uuid_local=uuid_local,
                setor=setor,
                quarteirao=quarteirao,
                logradouro=str(v.get('logradouro') or v.get('street') or '')[:200],
                numero=str(v.get('numero') or v.get('house_number') or '')[:50],
                cnefe_id=str(v.get('cnefe_id') or '')[:100] or None,
                latitude=float(v['latitude']) if v.get('latitude') is not None else None,
                longitude=float(v['longitude']) if v.get('longitude') is not None else None,
                situacao=situacao,
                criadouros_json=criadouros_json,
                larvas_encontradas=larvas,
                larvas_quantidade_tubitos=int(v.get('tubitos') or v.get('larvas_quantidade_tubitos') or 0),
                larvas_especie=str(v.get('larvas_especie') or '')[:50] or None,
                agente=str(v.get('agente') or '')[:160] or None,
                data_visita=data_visita or agora.date(),
                horario_visita=horario_visita or agora,
                observacao=str(v.get('observacao') or ''),
                sincronizado_em=agora,
                criado_em=agora,
            )
            db.session.add(nova)
            inseridas += 1

            # Atualiza status do quarteirão para EM_ANDAMENTO caso ainda esteja PLANEJADO
            if setor and quarteirao:
                quadra = EntomologiaQuarteiraoTrabalho.query.filter_by(
                    setor=setor, quarteirao=quarteirao, ciclo=v.get('ciclo', 'vigente')
                ).first()
                if quadra and quadra.status == 'PLANEJADO':
                    quadra.status = 'EM_ANDAMENTO'
                    quadra.atualizado_em = agora

        if inseridas > 0:
            db.session.commit()

        return _sem_cache(jsonify({
            'status': 'ok',
            'recebidas': len(visitas),
            'inseridas': inseridas,
        }))

    @bp.route('/entomologia/visitas/listar')
    @require_access
    def entomologia_visitas_listar():
        setor = request.args.get('setor')
        quarteirao = request.args.get('quarteirao')

        query = EntomologiaVisitaDomiciliar.query
        if setor:
            query = query.filter_by(setor=setor)
        if quarteirao:
            query = query.filter_by(quarteirao=quarteirao)

        rows = query.order_by(EntomologiaVisitaDomiciliar.id.desc()).limit(500).all()

        return _sem_cache(jsonify({
            'status': 'ok',
            'visitas': [{
                'id': v.id,
                'uuid_local': v.uuid_local,
                'setor': v.setor,
                'quarteirao': v.quarteirao,
                'logradouro': v.logradouro,
                'numero': v.numero,
                'situacao': v.situacao,
                'criadouros': json.loads(v.criadouros_json or '[]'),
                'larvas': v.larvas_encontradas,
                'tubitos': v.larvas_quantidade_tubitos,
                'agente': v.agente,
                'data_visita': v.data_visita.isoformat() if v.data_visita else None,
                'horario_visita': v.horario_visita.isoformat() if v.horario_visita else None,
                'observacao': v.observacao,
            } for v in rows],
        }))

    @bp.route('/entomologia/visitas/exportar.csv')
    @require_access
    def entomologia_visitas_exportar_csv():
        setor = request.args.get('setor')
        quarteirao = request.args.get('quarteirao')

        query = EntomologiaVisitaDomiciliar.query
        if setor:
            query = query.filter_by(setor=setor)
        if quarteirao:
            query = query.filter_by(quarteirao=quarteirao)

        rows = query.order_by(EntomologiaVisitaDomiciliar.data_visita.desc(), EntomologiaVisitaDomiciliar.id.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow([
            'Data', 'Horario', 'Setor', 'Quarteirao', 'Logradouro', 'Numero',
            'Situacao', 'Criadouros_Com_Agua', 'Larvas_Encontradas', 'Quantidade_Tubitos',
            'Agente', 'Observacao', 'UUID_Local'
        ])

        for v in rows:
            writer.writerow([
                v.data_visita.isoformat() if v.data_visita else '',
                v.horario_visita.strftime('%H:%M:%S') if v.horario_visita else '',
                v.setor,
                v.quarteirao,
                v.logradouro or '',
                v.numero or '',
                v.situacao,
                v.criadouros_json or '[]',
                'SIM' if v.larvas_encontradas else 'NAO',
                v.larvas_quantidade_tubitos or 0,
                v.agente or '',
                v.observacao or '',
                v.uuid_local or '',
            ])

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
        response.headers['Content-Disposition'] = f'attachment; filename=visitas_campo_orlandia_{date.today().isoformat()}.csv'
        return _sem_cache(response)
