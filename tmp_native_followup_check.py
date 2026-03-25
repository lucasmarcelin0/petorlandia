import sys

sys.path[:0] = [r"C:\Users\Visa10\petorlandia", r"C:\Users\Visa10\petorlandia\.codex-site-packages"]

import app as app_module
from extensions import db
from models.sfa import SfaPaciente, SfaRespostaT10, SfaRespostaT30

app = app_module.app
id_estudo = "SFA-NATIVE-FOLLOWUP"
client = app.test_client()

def cleanup():
    with app.app_context():
        resposta_t10 = SfaRespostaT10.query.filter_by(id_estudo=id_estudo).all()
        resposta_t30 = SfaRespostaT30.query.filter_by(id_estudo=id_estudo).all()
        paciente = SfaPaciente.query.filter_by(id_estudo=id_estudo).first()
        for item in resposta_t10 + resposta_t30:
            db.session.delete(item)
        if paciente is not None:
            db.session.delete(paciente)
        db.session.commit()

cleanup()

with app.app_context():
    paciente = SfaPaciente(
        id_estudo=id_estudo,
        ficha_sinan="808080",
        nome="Paciente Followup",
        data_nascimento="01/01/2000",
        endereco="Rua Teste, 20",
        status_t0="T0_Completo",
        status_t10="Aguardando",
        status_t30="Aguardando",
        status_geral="Em_Andamento",
        data_t0="18/03/2026",
        data_t10="28/03/2026",
        data_t30="17/04/2026",
    )
    paciente.gerar_token()
    token = paciente.token_acesso
    db.session.add(paciente)
    db.session.commit()

response_t10_get = client.get(f"/sfa/p/{token}/t10")
assert response_t10_get.status_code == 200, response_t10_get.status_code
assert "T10 Estudo SFA Orlandia" in response_t10_get.get_data(as_text=True)

payload_t10 = {
    "dias_incap_novos": "3",
    "custo_remedios": "10.50",
    "custo_consultas": "20.00",
    "custo_transporte": "5.25",
    "custo_outros": "2.00",
    "observacoes_finais": "Melhorando",
}
response_t10_post = client.post(f"/sfa/p/{token}/t10", data=payload_t10)
assert response_t10_post.status_code == 200, response_t10_post.status_code
assert "Obrigado pela sua participacao" in response_t10_post.get_data(as_text=True)

response_t30_get = client.get(f"/sfa/p/{token}/t30")
assert response_t30_get.status_code == 200, response_t30_get.status_code
assert "T30 Estudo SFA Orlandia" in response_t30_get.get_data(as_text=True)

payload_t30 = {
    "dias_incap_novos": "1",
    "custo_remedios": "0",
    "custo_consultas": "0",
    "custo_transporte": "3.50",
    "custo_outros": "0",
    "observacoes_finais": "Recuperado",
}
response_t30_post = client.post(f"/sfa/p/{token}/t30", data=payload_t30)
assert response_t30_post.status_code == 200, response_t30_post.status_code
assert "Obrigado pela sua participacao" in response_t30_post.get_data(as_text=True)

with app.app_context():
    paciente = SfaPaciente.query.filter_by(id_estudo=id_estudo).first()
    resposta_t10 = SfaRespostaT10.query.filter_by(id_estudo=id_estudo).first()
    resposta_t30 = SfaRespostaT30.query.filter_by(id_estudo=id_estudo).first()
    assert paciente is not None
    assert resposta_t10 is not None
    assert resposta_t30 is not None
    print({
        "status_t10": paciente.status_t10,
        "status_t30": paciente.status_t30,
        "status_geral": paciente.status_geral,
    })

cleanup()