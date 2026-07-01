from extensions import db
from models import Medicamento, User


def test_buscar_medicamentos_encontra_composto_por_tokens_fora_de_ordem(client, app):
    with app.app_context():
        user = User(name="Vet", email="vet-search@example.com", worker="veterinario")
        user.set_password("x")
        db.session.add(user)
        db.session.flush()
        med = Medicamento(
            nome="Cetoconazol + Dipropionato de Betametasona + Sulfato de Neomicina",
            principio_ativo="Cetoconazol; Betametasona; Neomicina",
            classificacao="Dermatologico",
            via_administracao="Topica",
            created_by=user.id,
        )
        db.session.add(med)
        db.session.commit()
        med_id = med.id

    resp = client.get("/buscar_medicamentos?q=betametasona neomcicina cetoconazol")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data
    assert data[0]["id"] == med_id
    assert "Cetoconazol" in data[0]["nome"]
