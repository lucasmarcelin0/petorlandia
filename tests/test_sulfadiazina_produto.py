"""Testes para o cadastro e correspondência da Sulfadiazina de Prata 10mg/g Creme 30g com a loja."""

from extensions import db
from models.bulario import ApresentacaoMedicamento, DoseMedicamento, Medicamento
from models.loja import Product, ProductVariant
from models.racao import CasaDeRacao
from models.usuarios import User
from services.prescription_store import build_prescription_offers


class _FakePrescricao:
    def __init__(self, medicamento):
        self.medicamento = medicamento


def test_sulfadiazina_match_produto_loja(app):
    with app.app_context():
        user = User(
            name="Lojista Teste",
            email="lojista.sulfadiazina@teste.com",
            password_hash="test_hash",
            role="adotante",
        )
        db.session.add(user)
        db.session.commit()

        # Casa de ração ativa
        casa = CasaDeRacao(
            nome="AgroGraner Teste",
            status="ativa",
            owner_id=user.id,
        )
        db.session.add(casa)
        db.session.commit()

        # Produto na loja com preco base de 29.00 (sem taxas da plataforma)
        # Com taxa da plataforma de 10%, preco publico = 29.00 / 0.90 = 32.22
        produto = Product(
            name="Sulfadiazina de Prata 10mg/g Creme 30g",
            description="Sulfadiazina de Prata 10 mg/g (1%) Creme dermatológico, bisnaga com 30 g.",
            price=29.00,
            stock=10,
            status="active",
            is_demo=False,
            category="medicamento",
            casa_de_racao_id=casa.id,
            image_url="https://petorlandia.s3.amazonaws.com/products/sulfadiazina_de_prata_10mg_creme_30g.png",
        )
        db.session.add(produto)
        db.session.flush()

        variant = ProductVariant(
            product_id=produto.id,
            name="Bisnaga 30 g",
            dosage="10 mg/g (1%)",
            package_quantity="1 bisnaga",
            weight_volume="30 g",
            price=29.00,
            stock=10,
            status="active",
            position=0,
        )
        db.session.add(variant)
        db.session.commit()

        # Validar cálculo de preço público com taxa embutida
        assert float(produto.price) == 29.00
        assert float(produto.preco_publico) == 32.22

        # Prescrição veterinária de Sulfadiazina de Prata 10mg/g
        prescricao = _FakePrescricao("Sulfadiazina de Prata 10mg/g — Creme dermatológico")
        linhas = build_prescription_offers([prescricao])

        assert len(linhas) == 1
        linha = linhas[0]
        assert linha.has_offer is True
        assert linha.best is not None
        assert linha.best.product.name == "Sulfadiazina de Prata 10mg/g Creme 30g"
        assert float(linha.best.product.price) == 29.00
        assert float(linha.best.product.preco_publico) == 32.22
        assert linha.best.product.stock == 10
        assert linha.best.product.category == "medicamento"
        assert "sulfadiazina_de_prata" in linha.best.product.image_url
