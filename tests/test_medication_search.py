from pathlib import Path

import pytest

from extensions import db
from models import ApresentacaoMedicamento, DoseMedicamento, Medicamento, User


@pytest.fixture(autouse=True)
def clear_search_cache():
    # Os testes recriam o catálogo; não reutilizar respostas de outro banco.
    from app import _clear_medication_search_cache
    _clear_medication_search_cache()


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


def test_busca_medicamentos_tolerancia_erro_amoxilina_e_expansao_vetsmart(client, app):
    with app.app_context():
        user = User(name="Vet Amox", email="vet-amox@example.com", worker="veterinario")
        user.set_password("x")
        db.session.add(user)
        db.session.flush()

        med = Medicamento(
            nome="Amoxicilina + Clavulanato de Potássio",
            principio_ativo="Amoxicilina + Clavulanato de Potássio",
            classificacao="Antibacteriano",
            via_administracao="Oral",
            conteudo_estruturado={
                "produtos_vetsmart": [
                    {
                        "nome": "Synulox",
                        "fabricante": "Zoetis",
                        "classificacao": "Antimicrobiano",
                        "especies": ["Cães", "Gatos"],
                        "vetsmart_produto_id": 1001,
                        "apresentacoes": [
                            {"forma": "Comprimido", "concentracao": "50 mg"},
                            {"forma": "Comprimido", "concentracao": "250 mg"},
                        ],
                    },
                    {
                        "nome": "Agemoxi CL",
                        "fabricante": "Agener União",
                        "classificacao": "Antibacteriano",
                        "especies": ["Cães", "Gatos"],
                        "vetsmart_produto_id": 1002,
                    },
                ]
            },
            created_by=user.id,
        )
        db.session.add(med)
        db.session.commit()
        med_id = med.id

    # Busca com erro de digitação comum: 'amoxilina' (sem o 'c')
    resp_typo = client.get("/buscar_medicamentos?q=amoxilina")
    assert resp_typo.status_code == 200
    data_typo = resp_typo.get_json()
    assert len(data_typo) >= 3

    nomes = [item["nome_exibicao_busca"] for item in data_typo if item["id"] == med_id]
    assert "Amoxicilina + Clavulanato de Potássio" in nomes
    assert "Synulox" in nomes
    assert "Agemoxi CL" in nomes

    # O princípio ativo canônico vem antes das marcas derivadas na busca pelo princípio
    idx_canonico = nomes.index("Amoxicilina + Clavulanato de Potássio")
    idx_synulox = nomes.index("Synulox")
    assert idx_canonico < idx_synulox

    synulox_item = next(item for item in data_typo if item["nome_exibicao_busca"] == "Synulox")
    assert synulox_item["tipo_item"] == "comercial"
    assert synulox_item["fabricante"] == "Zoetis"
    assert synulox_item["nome_comercial_filtro"] == "Synulox"

    # Busca direta pela marca 'synulox' coloca a marca no topo
    resp_marca = client.get("/buscar_medicamentos?q=synulox")
    assert resp_marca.status_code == 200
    data_marca = resp_marca.get_json()
    assert data_marca
    assert data_marca[0]["nome_exibicao_busca"] == "Synulox"
    assert data_marca[0]["fabricante"] == "Zoetis"


def test_frontend_configuracao_busca_instantanea():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/partials/prescricao_form.html").read_text(encoding="utf-8")

    assert "_medicationCatalogPool" in template
    assert "_filtrarMedicamentosDoPool" in template
    assert "_renderizarSugestoesPrescricao" in template
    # Debounce ultrarrápido de 80ms
    assert "}, 80);" in template
    # Pré-carregamento no pool
    assert "_armazenarNoPoolMedicamentos(lista)" in template


def test_busca_shampoo_clorexidina_nao_perde_resultado_no_limite_alfabetico(client, app):
    with app.app_context():
        vet = User(name="Vet Shampoo", email="shampoo-search@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.flush()
        # Estes resultados ocupavam o limite antes da avaliação de relevância.
        db.session.add_all([
            Medicamento(nome=f"A Shampoo Neutro {i:03d}", created_by=vet.id)
            for i in range(75)
        ])
        shampoo = Medicamento(
            nome="Shampoo de Clorexidina 2%", principio_ativo="Clorexidina",
            created_by=vet.id,
        )
        db.session.add(shampoo)
        db.session.commit()
        med_id = shampoo.id

    for query in ["shampoo de clorexidina", "clorexidina shampoo", "shampoo clorexid"]:
        response = client.get("/buscar_medicamentos", query_string={"q": query})
        assert response.status_code == 200
        assert [item["id"] for item in response.get_json()] == [med_id]


def test_busca_shampoo_comercial_combina_nome_e_principio_sem_produtos_alheios(client, app):
    with app.app_context():
        vet = User(name="Vet Catálogo", email="shampoo-catalog@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.flush()
        db.session.add(Medicamento(
            nome="Catálogo de higiene dermatológica",
            conteudo_estruturado={"produtos_vetsmart": [
                {"nome": "Shampoo Antisséptico", "principio_ativo": "Clorexidina", "fabricante": "Lab X"},
                {"nome": "Shampoo Neutro", "principio_ativo": "Aloe vera"},
                {"nome": "Solução de Clorexidina", "principio_ativo": "Clorexidina"},
            ]},
            created_by=vet.id,
        ))
        db.session.commit()

    for query in ["shampoo de clorexidina", "clorexidina shampoo"]:
        response = client.get("/buscar_medicamentos", query_string={"q": query})
        assert response.status_code == 200
        assert [item["nome_exibicao_busca"] for item in response.get_json()] == ["Shampoo Antisséptico"]


def test_busca_multiplos_termos_mantem_correcao_de_digitacao(client, app):
    with app.app_context():
        vet = User(name="Vet Busca", email="search-typo-compound@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.flush()
        db.session.add(Medicamento(
            nome="Shampoo de Neomicina", principio_ativo="Neomicina",
            conteudo_estruturado={"indicacoes": "Uso tópico"}, created_by=vet.id,
        ))
        db.session.commit()
    response = client.get("/buscar_medicamentos", query_string={"q": "shampoo neomcicina"})
    assert response.status_code == 200
    assert [item["nome_exibicao_busca"] for item in response.get_json()] == ["Shampoo de Neomicina"]


def test_busca_medicamentos_frontend_runtime():
    import shutil
    import subprocess
    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js necessário para testar as respostas assíncronas da busca")
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_suffix(".js"))],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
