"""Testes para os produtos de Dipirona vendidos pela PetOrlândia."""

import os
from pathlib import Path
from extensions import db
from models.bulario import Medicamento, ApresentacaoMedicamento
from models.loja import Product, ProductVariant
from scripts.seed_produtos_dipirona import seed_dipirona_produtos
from services.prescription_store import build_prescription_offers


class _FakePrescricao:
    def __init__(self, medicamento):
        self.medicamento = medicamento


def test_seed_dipirona_produtos_loja(app):
    with app.app_context():
        med, prods = seed_dipirona_produtos(app)

        assert med is not None
        assert med.nome == "Dipirona"
        assert med.principio_ativo == "Dipirona"
        assert len(prods) == 4

        # 1. Dipirona 500mg 10 comprimidos
        p1 = Product.query.filter(Product.name.like("%500mg%comprimidos%")).first()
        assert p1 is not None
        assert float(p1.price) == 13.00
        assert float(p1.preco_publico) == 14.44
        assert p1.clinica_id is None
        assert p1.casa_de_racao_id is None
        assert p1.status == "active"
        assert p1.category == "medicamento"
        assert p1.image_url == "/static/img/produtos/dipirona_500mg_10_comprimidos.png"
        assert len(p1.variants) >= 1

        # 2. Dipirona 1g 10 comprimidos
        p2 = Product.query.filter(Product.name.like("%1g%comprimidos%")).first()
        assert p2 is not None
        assert float(p2.price) == 16.00
        assert float(p2.preco_publico) == 17.78
        assert p2.clinica_id is None
        assert p2.casa_de_racao_id is None
        assert p2.status == "active"
        assert p2.category == "medicamento"
        assert p2.image_url == "/static/img/produtos/dipirona_1g_10_comprimidos.png"
        assert len(p2.variants) >= 1

        # 3. Dipirona Líquido 500mg/ml Gotas
        p3 = Product.query.filter(Product.name.like("%500mg/ml%")).first()
        assert p3 is not None
        assert float(p3.price) == 10.00
        assert float(p3.preco_publico) == 11.11
        assert p3.clinica_id is None
        assert p3.casa_de_racao_id is None
        assert p3.status == "active"
        assert p3.category == "medicamento"
        assert p3.image_url == "/static/img/produtos/dipirona_liquido_500mg_ml.png"
        assert len(p3.variants) >= 1

        # 4. Dipirona Líquido Infantil 50mg/ml
        p4 = Product.query.filter(Product.name.like("%50mg/ml%")).first()
        assert p4 is not None
        assert float(p4.price) == 30.00
        assert float(p4.preco_publico) == 33.33
        assert p4.clinica_id is None
        assert p4.casa_de_racao_id is None
        assert p4.status == "active"
        assert p4.category == "medicamento"
        assert p4.image_url == "/static/img/produtos/dipirona_liquido_infantil_50mg_ml.png"
        assert len(p4.variants) >= 1


def test_dipirona_prescription_store_matching(app):
    with app.app_context():
        seed_dipirona_produtos(app)

        # Prescrição de Dipirona 500mg
        presc_500 = _FakePrescricao("Dipirona 500mg comprimidos")
        linhas = build_prescription_offers([presc_500])
        assert len(linhas) == 1
        assert linhas[0].has_offer is True
        assert linhas[0].compatible is not None
        assert "500mg" in linhas[0].compatible.product.name

        # Prescrição de Dipirona 1g
        presc_1g = _FakePrescricao("Dipirona 1g comprimidos")
        linhas_1g = build_prescription_offers([presc_1g])
        assert len(linhas_1g) == 1
        assert linhas_1g[0].has_offer is True
        assert linhas_1g[0].compatible is not None
        assert "1g" in linhas_1g[0].compatible.product.name

        # Prescrição de Dipirona 500mg/ml Gotas
        presc_gotas = _FakePrescricao("Dipirona 500mg/ml gotas")
        linhas_gotas = build_prescription_offers([presc_gotas])
        assert len(linhas_gotas) == 1
        assert linhas_gotas[0].has_offer is True
        assert linhas_gotas[0].compatible is not None
        assert "500mg/ml" in linhas_gotas[0].compatible.product.name

        # Prescrição de Dipirona Infantil 50mg/ml
        presc_inf = _FakePrescricao("Dipirona 50mg/ml solução oral infantil")
        linhas_inf = build_prescription_offers([presc_inf])
        assert len(linhas_inf) == 1
        assert linhas_inf[0].has_offer is True
        assert linhas_inf[0].compatible is not None
        assert "50mg/ml" in linhas_inf[0].compatible.product.name


def test_dipirona_imagens_estaticas_existem():
    project_root = Path(__file__).resolve().parent.parent
    imagens = [
        "dipirona_500mg_10_comprimidos.png",
        "dipirona_1g_10_comprimidos.png",
        "dipirona_liquido_500mg_ml.png",
        "dipirona_liquido_infantil_50mg_ml.png",
    ]
    for img in imagens:
        caminho = project_root / "static" / "img" / "produtos" / img
        assert caminho.exists(), f"Imagem não encontrada: {caminho}"
        assert caminho.stat().st_size > 1000, f"Imagem muito pequena ou vazia: {caminho}"
