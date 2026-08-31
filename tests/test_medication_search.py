from pathlib import Path

from extensions import db
from models import ApresentacaoMedicamento, DoseMedicamento, Medicamento, User


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


def test_buscar_medicamentos_autocomplete_leve_e_detalhe_sob_demanda(client, app):
    with app.app_context():
        user = User(name="Vet", email="vet-detail@example.com", worker="veterinario")
        user.set_password("x")
        db.session.add(user)
        db.session.flush()
        med = Medicamento(
            nome="Dipirona",
            principio_ativo="Dipirona sodica",
            classificacao="Analgesico",
            via_administracao="Oral",
            observacoes="Usar com criterio clinico.",
            conteudo_estruturado={
                "indicacoes": "Analgesia e antipirese.",
                "contraindicacoes": "Evitar em pacientes sensiveis.",
            },
            created_by=user.id,
        )
        db.session.add(med)
        db.session.flush()
        db.session.add(
            ApresentacaoMedicamento(
                medicamento_id=med.id,
                forma="gotas",
                concentracao="500 mg/mL",
            )
        )
        db.session.add(
            DoseMedicamento(
                medicamento_id=med.id,
                especie="Caes",
                dose="25 mg/kg",
            )
        )
        db.session.commit()
        med_id = med.id

    resp = client.get("/buscar_medicamentos?q=dipirona")
    assert resp.status_code == 200
    data = resp.get_json()
    item = next(entry for entry in data if entry["id"] == med_id)

    assert item["tem_doses"] is True
    assert item["tem_apresentacoes"] is True
    assert item["apresentacoes_count"] == 1
    assert "monografia_estruturada" not in item
    assert "apresentacoes" not in item
    assert "bula" not in item

    detail_resp = client.get(f"/medicamento/{med_id}/detalhe")
    assert detail_resp.status_code == 200
    detail = detail_resp.get_json()
    assert detail["id"] == med_id
    assert detail["apresentacoes"]
    assert "monografia_estruturada" in detail


def test_busca_prioriza_nome_cadastrado_sobre_alias_comercial_generico(client, app):
    with app.app_context():
        user = User(name="Vet", email="vet-med-name@example.com", worker="veterinario")
        user.set_password("x")
        db.session.add(user)
        db.session.flush()
        med = Medicamento(
            nome="Sulfadiazina de Prata 10mg/g Creme Dermatologico",
            principio_ativo="Sulfadiazina de Prata",
            conteudo_estruturado={
                "produtos_vetsmart": [
                    {
                        "nome": "Sulfadiazina de prata Animalia Farma",
                        "fabricante": "Animalia Farma",
                        "vetsmart_produto_id": 98765,
                    }
                ]
            },
            created_by=user.id,
        )
        db.session.add(med)
        db.session.commit()
        med_id = med.id

    resp = client.get("/buscar_medicamentos?q=sulfadiazina")

    assert resp.status_code == 200
    item = next(entry for entry in resp.get_json() if entry["id"] == med_id)
    assert item["nome_exibicao_busca"] == "Sulfadiazina de Prata 10mg/g Creme Dermatologico"
    assert "produto_match_nome" not in item

    alias_resp = client.get("/buscar_medicamentos?q=animalia")
    assert alias_resp.status_code == 200
    alias_item = next(entry for entry in alias_resp.get_json() if entry["id"] == med_id)
    assert alias_item["nome_exibicao_busca"] == "Sulfadiazina de prata Animalia Farma"
    assert alias_item["produto_match_nome"] == "Sulfadiazina de prata Animalia Farma"


def test_edicao_usa_nome_persistido_e_descarta_alias_visual_desatualizado():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/partials/prescricao_form.html").read_text(encoding="utf-8")

    assert "med?.nome || _nomeVisivelMedicamento(med)" in template
    assert "medicamentoSelecionado.nome_exibicao_busca = nome" in template
    assert "medicamentoSelecionado.produto_match_nome = null" in template
    assert "_medicationSearchCache.clear()" in template
    assert "_medicationDetailCache.clear()" in template
