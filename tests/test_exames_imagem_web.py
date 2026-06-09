import io
import sys

from extensions import db
from models import (
    AnimalDocumento,
    ExameImagem,
    ExternalOnboardingInvite,
    User,
    Veterinario,
)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_exames_imagem_requires_login(client):
    response = client.get('/exames-imagem')

    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_veterinarian_creates_image_exam_and_public_links(app, client, monkeypatch):
    app_module = sys.modules[app.import_name]

    def fake_upload(file_storage, filename, folder='uploads'):
        assert folder == 'laudos_exames'
        assert filename.endswith('Ultrassom_SID_Rosa.pdf')
        return '/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf'

    monkeypatch.setattr(app_module, 'upload_to_s3', fake_upload)

    with app.app_context():
        vet_user = User(
            name='Robson Oliveira',
            email='robson-web-exame@example.com',
            role='veterinario',
            worker='veterinario',
        )
        vet_user.set_password('secret123')
        db.session.add(vet_user)
        db.session.flush()
        db.session.add(Veterinario(user_id=vet_user.id, crmv='CRMV-MG 26136'))
        db.session.commit()
        vet_user_id = vet_user.id

    _login(client, vet_user_id)
    response = client.post(
        '/exames-imagem',
        data={
            'nome_clinica': 'Angrisano',
            'nome_responsavel_clinica': 'Dono Angrisano',
            'email_clinica': 'dono-angrisano@example.com',
            'telefone_clinica': '16999990000',
            'nome_tutor': 'Rosa',
            'email_tutor': 'rosa-web-exame@example.com',
            'telefone_tutor': '16988887777',
            'nome_animal': 'Sid',
            'especie': 'Canina',
            'tipo_exame': 'Ultrassonografia abdominal',
            'data_exame': '2026-02-16',
            'profissional_nome': 'Robson Oliveira',
            'profissional_crmv': 'CRMV-MG 26136',
            'impressao_diagnostica': 'Massa abdominal a esclarecer.',
            'liberar_clinica': '1',
            'gerar_convite_clinica': '1',
            'liberar_tutor': '1',
            'gerar_convite_tutor': '1',
            'arquivo_pdf': (io.BytesIO(b'%PDF-1.4\nlaudo sid'), 'Ultrassom_SID_Rosa.pdf'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 302

    with app.app_context():
        exame = ExameImagem.query.one()
        assert exame.arquivo_pdf_url == '/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf'
        assert exame.arquivo_pdf_filename == 'Ultrassom_SID_Rosa.pdf'
        assert exame.liberado_para_clinica is True
        assert exame.liberado_para_tutor is True
        assert exame.status == 'liberado_para_tutor'
        assert exame.clinica_requisitante.nome == 'Angrisano'
        assert exame.tutor.name == 'Rosa'
        assert exame.animal.name == 'Sid'
        assert AnimalDocumento.query.count() == 1
        invites = ExternalOnboardingInvite.query.order_by(ExternalOnboardingInvite.invite_type).all()
        assert {invite.invite_type for invite in invites} == {'clinic', 'tutor'}
        exame_id = exame.id

    page = client.get(f'/exames-imagem?exame_id={exame_id}')

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'Sid' in html
    assert 'Angrisano' in html
    assert '/primeiro-acesso-clinica/' in html
    assert '/acesso-laudo/' in html
    assert '/api/integrations/clinical-document' not in html
