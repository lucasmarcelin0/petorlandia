"""Testes para o produto Cefalexina 250mg/5ml Pó para Suspensão Oral."""

from extensions import db
from models.bulario import ApresentacaoMedicamento, Medicamento
from models.loja import Product, ProductVariant
from models.racao import CasaDeRacao
from models.usuarios import User
from services.prescription_store import build_prescription_offers


class _FakePrescricao:
    def __init__(self, medicamento):
        self.medicamento = medicamento


def test_cefalexina_suspensao_match_produto_loja(app):
    with app.app_context():
        user = User(
            name="Lojista Cefa",
            email="lojista.cefa@teste.com",
            password_hash="test_hash",
            role="adotante",
        )
        db.session.add(user)
        db.session.commit()

        casa = CasaDeRacao(
            nome="AgroGraner Teste",
            status="ativa",
            owner_id=user.id,
        )
        db.session.add(casa)
        db.session.commit()

        # Preço base de R$ 60,00 (sem taxas). Com 10% da plataforma: 60.00 / 0.90 = R$ 66,67
        produto = Product(
            name="Cefalexina 250mg/5ml Pó para Suspensão Oral 100ml",
            description="Cefalexina 250 mg/5 mL suspensão oral",
            price=60.00,
            stock=10,
            status="active",
            is_demo=False,
            category="medicamento",
            casa_de_racao_id=casa.id,
            image_url="https://petorlandia.s3.amazonaws.com/products/cefalexina_250mg_suspensao_100ml.png",
        )
        db.session.add(produto)
        db.session.flush()

        variant = ProductVariant(
            product_id=produto.id,
            name="Frasco 100 mL",
            dosage="250 mg/5 mL (50 mg/mL)",
            package_quantity="1 frasco + seringa",
            weight_volume="100 mL",
            price=60.00,
            stock=10,
            status="active",
            position=0,
        )
        db.session.add(variant)
        db.session.commit()

        # Valida cálculo de preços
        assert float(produto.price) == 60.00
        assert float(produto.preco_publico) == 66.67

        # Prescrição de Cefalexina 250mg/5ml
        prescricao = _FakePrescricao("Cefalexina 250mg/5ml — Suspensão oral")
        linhas = build_prescription_offers([prescricao])

        assert len(linhas) == 1
        linha = linhas[0]
        assert linha.has_offer is True
        assert linha.best is not None
        assert "Cefalexina 250mg/5ml" in linha.best.product.name
        assert float(linha.best.product.price) == 60.00
        assert float(linha.best.product.preco_publico) == 66.67
