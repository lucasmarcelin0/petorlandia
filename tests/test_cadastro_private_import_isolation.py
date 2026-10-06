"""Private cadastral snapshots stay outside ordinary team-import workflows."""
import csv
import io
import json
from datetime import timedelta

import pytest
from flask import g

from extensions import db
from models import User
from models.entomologia import EntomologiaImportacao
from models.sfa import SfaAuditoria
from scripts.import_entomologia import METRICS
from services.entomologia_acesso import conceder
from time_utils import utcnow

HTTPS = {'base_url': 'https://localhost'}
PRIVATE_MARKER = 'SYNTHETIC-PRIVATE-CADASTRAL-OWNER'


def ordinary_visits_csv():
    fields = ['LOGIN', 'AGENTE', 'DATA', 'AREA', 'CENSITARIO', 'QUARTEIRÃO', *METRICS.values()]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, delimiter=';')
    writer.writeheader()
    writer.writerow({'LOGIN': 'synthetic', 'AGENTE': 'Synthetic team', 'DATA': '2026-09-12',
                     'AREA': '1', 'CENSITARIO': '353430205000001', 'QUARTEIRÃO': '7', 'IM TRAB': '1'})
    return output.getvalue().encode('utf-8')


def snapshot(tipo='cadastro_privado', status='ATIVA', old=False):
    row = EntomologiaImportacao(
        tipo=tipo, status=status,
        nome_arquivo=PRIVATE_MARKER if tipo == 'cadastro_privado' else 'ordinary-team.kml',
        titulo=PRIVATE_MARKER if tipo == 'cadastro_privado' else 'Ordinary team layer',
        sha256='a' * 64, linhas=1,
        dados_json=json.dumps({'owner': PRIVATE_MARKER}),
        resumo_json=json.dumps({'owner': PRIVATE_MARKER}),
        responsavel=PRIVATE_MARKER if tipo == 'cadastro_privado' else 'Team',
        criado_em=utcnow() - timedelta(days=10) if old else utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture(params=['admin', 'vacinador'])
def editor(app, client, monkeypatch, request):
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    user = User(name='Synthetic editor', email=f'{request.param}-isolation@example.test',
                password_hash='x', role=request.param)
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    for key in ('_login_user', '_entomologia_membro', 'user_experience'):
        g.pop(key, None)
    if request.param != 'admin':
        conceder(user, 'Synthetic test admin')
        db.session.commit()
    return user


def test_private_snapshots_are_absent_from_history_and_guessed_preview(client, editor):
    ordinary = snapshot(tipo='camada')
    private_rows = [snapshot(status=status) for status in ('PREVIA', 'ATIVA', 'DESFEITA')]
    for row in private_rows:
        response = client.get(f'/sfa/entomologia/atualizar?previa={row.id}', **HTTPS)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert ordinary.titulo in html
        assert PRIVATE_MARKER not in html
        assert 'PRÉVIA — AINDA NÃO APLICADA' not in html
        assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('status,action', [
    ('PREVIA', 'confirmar'), ('PREVIA', 'desfazer'), ('ATIVA', 'desfazer'),
])
def test_common_mutations_cannot_modify_private_snapshot(client, editor, status, action):
    row = snapshot(status=status)
    response = client.post(f'/sfa/entomologia/envios/{row.id}/{action}',
                           data={'responsavel': 'Synthetic team'}, **HTTPS)
    assert response.status_code == 404
    assert PRIVATE_MARKER not in response.get_data(as_text=True)
    db.session.expire_all()
    preserved = db.session.get(EntomologiaImportacao, row.id)
    assert preserved is not None and preserved.status == status
    assert SfaAuditoria.query.filter_by(funcao=f'{action}_envio').count() == 0


def test_upload_cleanup_preserves_private_snapshot(client, editor):
    private = snapshot(status='PREVIA', old=True)
    ordinary = snapshot(tipo='camada', status='PREVIA', old=True)
    private_id, ordinary_id = private.id, ordinary.id
    response = client.post('/sfa/entomologia/atualizar', data={
        'tipo': 'visitas', 'responsavel': 'Synthetic team',
        'arquivo': (io.BytesIO(ordinary_visits_csv()), 'ordinary.csv'),
    }, content_type='multipart/form-data', **HTTPS)
    assert response.status_code == 302 and 'previa=' in response.headers['Location']
    db.session.expire_all()
    assert db.session.get(EntomologiaImportacao, private_id) is not None
    # SQLite may reuse the deleted id for the new visit preview.
    assert EntomologiaImportacao.query.filter_by(id=ordinary_id, tipo='camada').count() == 0
    assert EntomologiaImportacao.query.filter_by(tipo='visitas', status='PREVIA').count() == 1


def test_private_snapshot_does_not_enter_operational_or_public_dataset(app):
    from services import entomologia_service as service
    snapshot()
    dataset = service.dataset_atual()
    assert PRIVATE_MARKER not in json.dumps(dataset)
    assert PRIVATE_MARKER not in json.dumps(service.boletim_publico(dataset))


def test_private_snapshot_does_not_change_shared_cache_signature_or_load(app):
    from services import entomologia_atlas_search as search
    from services import entomologia_service as service
    ordinary = snapshot(tipo='camada')
    before_dataset = service._chave_ativas()
    before_atlas = search._signature()
    assert before_atlas == ((ordinary.id, ordinary.sha256),)
    private = snapshot()
    assert service._chave_ativas() == before_dataset
    assert search._signature() == before_atlas
    assert service._ler_ativas([private.id]) == []
    assert [row.id for row in service._ler_ativas([ordinary.id, private.id])] == [ordinary.id]
    private.sha256 = 'b' * 64
    db.session.commit()
    assert service._chave_ativas() == before_dataset
    assert search._signature() == before_atlas
