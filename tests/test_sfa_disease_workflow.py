import csv
import importlib.util
import io
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from extensions import db
from models.sfa import (SfaPaciente, SfaRespostaT0, SfaRespostaT7, SfaRespostaT10,
                        SfaContextoEpisodio, SfaSinanLog, SfaAcao, SfaAuditoria, SfaContato)
from services import sfa_service as service
from services import sfa_workflow as flow
from services.sfa_workflow_ops import registrar_operacao
from services.sfa_source_reconciliation import reconciliar, grupo_resultado


@pytest.fixture
def hoje(monkeypatch):
    dia = [date(2026, 9, 13)]
    monkeypatch.setattr(flow, 'hoje_local', lambda: dia[0])
    from services import sfa_workflow_ops as ops
    monkeypatch.setattr(ops, 'hoje_local', lambda: dia[0])
    return dia


def paciente(app, id_estudo='SFA-901'):
    p = SfaPaciente(id_estudo=id_estudo, nome='Participante de validação', grupo='A')
    p.gerar_token()
    db.session.add(p)
    db.session.commit()
    return p


def t0_payload(p, inicio='10/09/2026'):
    return dict(id_estudo=p.id_estudo, nome=p.nome, aceite_tcle=[service.T0_CONSENT_ACCEPTED],
                respondent_role='A propria pessoa', data_inicio_sintomas=inicio,
                _instrument_version=flow.VERSION)


def test_t0_agenda_por_doenca_e_nao_reinicia_por_reenvio(app, hoje):
    p = paciente(app)
    assert service.on_submit_t0(t0_payload(p))['ok']
    assert p.data_t0 == '13/09/2026'
    assert p.data_t7 == '17/09/2026'
    assert p.data_t30 == '10/10/2026'
    payload = json.loads(p.resposta_t0.dados_json)
    assert payload['_calendario']['dia_doenca'] == 3
    assert service.on_submit_t0(t0_payload(p, '12/09/2026'))['acao'] == 'ja_registrado'
    assert SfaRespostaT0.query.count() == 1
    assert p.data_t7 == '17/09/2026'


def test_datas_ausentes_conflitantes_e_futuras_nao_viram_entrevista(app, hoje):
    p = paciente(app)
    assert not service.on_submit_t0(t0_payload(p, '14/09/2026'))['ok']
    assert service.on_submit_t0(t0_payload(p, ''))['ok']
    assert p.data_t7 is None and p.status_t7 == 'REVISAR_DATA'
    assert p.data_t30 is None
    p.resposta_t0.data_inicio_sintomas = '10/09/2026'
    p._sinan_log = SimpleNamespace(data_inicio_sintomas='09/09/2026')
    assert flow.inicio_doenca(p)[0] is None
    p.contexto = SfaContextoEpisodio(inicio_sintomas=date(2026, 9, 9), fonte_inicio='Ficha conferida', local_validado=False)
    flow.aplicar_calendario(p)
    assert p.data_t7 == '16/09/2026'


def test_t7_t30_coleta_real_intervalos_e_idempotencia(app, hoje):
    p = paciente(app)
    service.on_submit_t0(t0_payload(p))
    assert not service.on_submit_t7({'id_estudo': p.id_estudo})['ok']
    hoje[0] = date(2026, 9, 18)  # T7 coletado no D8, um dia depois do alvo.
    assert service.on_submit_t7({'id_estudo': p.id_estudo, '_instrument_version': flow.VERSION})['ok']
    assert service.on_submit_t7({'id_estudo': p.id_estudo})['ok']
    assert SfaRespostaT7.query.count() == 1
    meta = json.loads(p.respostas_t7[0].dados_json)['_calendario']
    assert meta['dia_doenca'] == 8
    assert meta['data_alvo'] == '2026-09-17'
    assert meta['intervalo_desde'] == '2026-09-13'
    hoje[0] = date(2026, 10, 10)
    a = SfaAcao(id_estudo=p.id_estudo, motivo='Investigar fonte', tipo='Visita', responsavel='Equipe', prazo=hoje[0])
    db.session.add(a)
    db.session.commit()
    assert service.on_submit_t30({'id_estudo': p.id_estudo, '_instrument_version': flow.VERSION})['ok']
    assert p.status_geral == 'COMPLETO'
    assert a.status == 'ABERTA'
    assert json.loads(p.respostas_t30[0].dados_json)['_calendario']['intervalo_desde'] == '2026-09-18'


def test_t10_historico_nao_vira_t7_e_exporta_separado(app, hoje):
    p = paciente(app)
    service.on_submit_t0(t0_payload(p, '01/08/2026'))
    antigo = SfaRespostaT10(id_estudo=p.id_estudo, dados_json=json.dumps({'_instrument_version':'collective-v2','classificacao_melhora':'Melhorando'}))
    db.session.add(antigo)
    p.data_t10 = '15/08/2026'
    db.session.commit()
    flow.aplicar_calendario(p)
    assert p.status_t7 == 'LEGADO_T10' and p.data_t7 is None
    assert p.data_t10 == '15/08/2026'
    assert not service.on_submit_t7({'id_estudo':p.id_estudo})['ok']
    row = next(csv.DictReader(io.StringIO(service.gerar_csv_exportacao_analitica([p]))))
    assert row['t10__instrument_version'] == 'collective-v2'
    assert row['t7__instrument_version'] == ''
    assert row['t10__classificacao_melhora'] == 'Melhorando'


def test_atraso_nao_confirma_perda_e_recusa_suspende_contato(app, hoje):
    p = paciente(app)
    service.on_submit_t0(t0_payload(p, '01/08/2026'))
    service.verificar_seguimento()
    assert p.status_t30 == 'ATRASADO'
    assert p.status_geral != 'PERDA_SEGUIMENTO'
    registrar_operacao(dict(operacao='contato',id_estudo=p.id_estudo,responsavel='Agente',
                            etapa='T30',canal='TELEFONE',resultado='RECUSOU',motivo='Solicitou interrupção'), 'user:1')
    assert service.calcular_acao_operacional(p)['acao'] not in service.ACOES_QUE_GERAM_CONTATO
    assert not service.on_submit_t30({'id_estudo':p.id_estudo})['ok']
    assert SfaContato.query.count() == 1


def test_assinatura_identifica_representante(app, hoje):
    p = paciente(app)
    payload = t0_payload(p)
    payload.update(respondent_role='Pai, mae ou responsavel',respondent_name='Responsável, mãe')
    assert service.on_submit_t0(payload)['ok']
    assert json.loads(p.resposta_t0.dados_json)['assinatura_tcle_nome'] == 'Responsável, mãe'


def test_acao_exige_execucao_e_evidencia_e_audita(app, hoje):
    p = paciente(app)
    acao = registrar_operacao(dict(operacao='acao',id_estudo=p.id_estudo,responsavel='Equipe',
                                  motivo='Investigar exposição',tipo='Visita',prazo='2026-09-20'), 'user:1')
    dados = dict(operacao='acao_status',acao_id=str(acao.id),responsavel='Supervisor',status='VERIFICADA',resultado='Conferido')
    with pytest.raises(ValueError, match='Execute'):
        registrar_operacao(dados,'user:1')
    dados.update(status='EXECUTADA',resultado='Fonte removida',horas='2.5',custo='10')
    registrar_operacao(dados,'user:1')
    dados.update(status='VERIFICADA')
    with pytest.raises(ValueError, match='evidencia'):
        registrar_operacao(dados,'user:1')
    dados.update(evidencia_verificacao='Revisita, sem fonte ativa',custo='NaN')
    with pytest.raises(ValueError, match='custo'):
        registrar_operacao(dados,'user:1')
    dados.update(custo='10')
    registrar_operacao(dados,'user:1')
    assert acao.status == 'VERIFICADA' and acao.verificador == 'Supervisor'
    assert SfaAuditoria.query.filter_by(categoria='FLUXO_TRABALHO').count() == 3


def test_semana_defasagem_nao_multiplica_pacientes_e_preserva_nulls(hoje):
    p = SimpleNamespace(id_estudo='SFA-123', resposta_t0=None, respostas_t7=[],respostas_t10=[],respostas_t30=[],
        contexto=SimpleNamespace(inicio_sintomas=date(2026,9,6),fonte_inicio='Conferido',local_validado=True,
                                 malha='operacional',setor='123',tipo_local='RESIDENCIA',classificacao='SUSPEITO'))
    registros = [{'date':'2026-09-01','sector':'123','worked':10,'positive':0,'aegypti_larvae':None},
                 {'date':'2026-09-03','sector':'123','worked':5,'positive':1,'aegypti_larvae':0}]
    dados = flow.vigilancia_semanal([p], {'records':registros}, 1)
    assert len(dados['linhas']) == 1
    r = dados['linhas'][0]
    assert r['semana'] == date(2026,9,6) and r['semana_vetor'] == date(2026,8,30)
    assert r['episodios'] == 1 and r['worked'] == 15 and r['registros_vetor'] == 2
    assert r['aegypti_larvae'] == 0 and r['larvas_preenchidas'] == 1
    assert r['closed'] is None
    p.contexto.local_validado=False
    assert flow.vigilancia_semanal([p], {'records':registros})['excluidos']['sem_residencia_validada'] == 1


@pytest.mark.parametrize('resultado,grupo',[('', 'PENDENTE_REVISAO'),('Não reagente','B'),('Reagente','A'),('Inconclusivo','PENDENTE_REVISAO'),('Autoctone','PENDENTE_REVISAO')])
def test_grupo_importado_nao_inventa_negativo(resultado,grupo):
    assert grupo_resultado(resultado)==grupo


def test_reconciliacao_atualiza_fonte_preserva_local_e_eh_idempotente(app,hoje):
    p=paciente(app)
    p.telefone='telefone corrigido manualmente'
    log=SfaSinanLog(chave_dedup='ficha-1',id_estudo_vinculado=p.id_estudo,telefone='telefone da fonte',resultado='pendente',grupo='PENDENTE_REVISAO')
    db.session.add(log);db.session.commit()
    novos=dict(telefone='telefone atualizado',resultado='positivo',grupo='A',data_inicio_sintomas='01/09/2026')
    assert reconciliar(log,novos)
    db.session.commit()
    assert p.telefone=='telefone corrigido manualmente'
    assert log.resultado=='positivo'
    assert not reconciliar(log,novos)
    assert SfaAuditoria.query.filter_by(categoria='SINAN_ATUALIZADO').count()==1


def test_telas_e_barreira_de_etapas(app,client,hoje):
    p=paciente(app)
    assert client.get('/sfa/trabalho').status_code==200
    assert client.get('/sfa/trabalho?episodio='+p.id_estudo).status_code==200
    assert client.get('/sfa/vigilancia-semanal?defasagem=1').status_code==200
    assert client.get('/sfa/vigilancia-semanal?defasagem=8').status_code==400
    assert client.get(f'/sfa/p/{p.token_acesso}/t7').status_code==409
    assert client.post(f'/sfa/p/{p.token_acesso}/t10').status_code==410
    assert client.get(f'/sfa/p/{p.token_acesso}/t10').status_code==302


def test_migracao_preserva_t10_e_impede_downgrade_com_dados():
    path=Path(__file__).resolve().parents[1]/'migrations/versions/d3a7c4e1f300_sfa_disease_workflow.py'
    spec=importlib.util.spec_from_file_location('migration_sfa',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE sfa_paciente (id_estudo VARCHAR(30) PRIMARY KEY, data_t10 VARCHAR(15))'))
        connection.execute(sa.text('CREATE TABLE sfa_resposta_t10 (id INTEGER PRIMARY KEY, id_estudo VARCHAR(30), dados_json TEXT)'))
        connection.execute(sa.text("INSERT INTO sfa_paciente VALUES ('SFA-1','10/08/2026')"))
        connection.execute(sa.text("INSERT INTO sfa_resposta_t10 VALUES (1,'SFA-1','{}')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(sa.text('SELECT status_t7,data_t10 FROM sfa_paciente')).one()==('LEGADO_T10','10/08/2026')
            assert connection.execute(sa.text('SELECT COUNT(*) FROM sfa_resposta_t7')).scalar()==0
            connection.execute(sa.text("INSERT INTO sfa_resposta_t7 (id,id_estudo) VALUES (1,'SFA-1')"))
            with pytest.raises(RuntimeError,match='Há dados'):
                migration.downgrade()


@pytest.mark.parametrize('method,path', [('get','/sfa/trabalho'),('get','/sfa/vigilancia-semanal'),('post','/sfa/trabalho/registrar')])
def test_novas_rotas_exigem_acesso_interno(app,client,monkeypatch,method,path):
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    monkeypatch.setitem(app.config,'TESTING',False)
    response=getattr(client,method)(path)
    assert response.status_code==302 and '/login' in response.headers['Location']


def test_contato_reagendado_preserva_resultado_e_data(app,hoje):
    p=paciente(app)
    service.on_submit_t0(t0_payload(p,'01/09/2026'))
    registrar_operacao(dict(operacao='contato',id_estudo=p.id_estudo,responsavel='Agente',
        etapa='T7',canal='TELEFONE',resultado='REAGENDADO',motivo='Horário combinado',proximo_contato='2026-09-15'),'user:1')
    assert p.retorno_contato=='REAGENDADO'
    assert service.calcular_acao_operacional(p)['data_alvo']=='15/09/2026'
    assert service.calcular_acao_operacional(p)['acao']=='Aguardar contato combinado'


def test_sinan_reimporta_atualizacoes_sem_duplicar(app,hoje,monkeypatch):
    row=['']*20
    for key,value in [('NOME','Registro para validação'),('N','1'),('FICHA_SINAN','101'),('DATA_INICIO_SINTOMAS','01/09/2026'),('RESULTADO','')]:
        row[service.COLS_SINAN[key]]=value
    rows=[['header']*20,row]
    class Sheets:
        def spreadsheets(self):return self
        def values(self):return self
        def get(self,**kwargs):return self
        def execute(self):return {'values':rows}
    monkeypatch.setattr(service,'SHEET_ID_SINAN','sheet-test')
    monkeypatch.setattr(service,'_get_sheets_service',lambda:Sheets())
    monkeypatch.setattr(service,'_resolve_sinan_sheet_target',lambda unused:('sheet-test','A:T'))
    assert service.sincronizar_sinan()['novos']==1
    assert SfaPaciente.query.one().grupo=='PENDENTE_REVISAO'
    row[service.COLS_SINAN['RESULTADO']]='positivo'
    resultado=service.sincronizar_sinan()
    assert resultado['novos']==0 and resultado['atualizados']==1
    assert SfaPaciente.query.count()==1 and SfaPaciente.query.one().grupo=='A'
    assert service.sincronizar_sinan()['atualizados']==0


def test_nome_nascimento_ambiguos_nao_juntam_episodios(app,hoje):
    for identificador in ['SFA-901','SFA-902']:
        p=paciente(app,identificador)
        p.data_nascimento='01/01/2000'
    db.session.commit()
    dados=t0_payload(p)
    dados.pop('id_estudo');dados['data_nascimento']='01/01/2000'
    resultado=service.on_submit_t0(dados)
    assert not resultado['ok'] and 'mais de um episódio' in resultado['erro']
    assert SfaRespostaT0.query.count()==0
