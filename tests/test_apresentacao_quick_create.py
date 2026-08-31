"""Testes para inclusão rápida de apresentações e correspondência da Cefalexina 500mg com a loja."""

from extensions import db
from models.bulario import ApresentacaoMedicamento, Medicamento
from models.loja import Product
from models.usuarios import User
from services.prescription_store import build_prescription_offers


def _login(client, user_id: int):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


class _FakePrescricao:
    def __init__(self, medicamento):
        self.medicamento = medicamento


def test_criar_apresentacao_medicamento_autenticado(app, client):
    with app.app_context():
        user = User(
            name="Vet Teste",
            email="vet.apres@teste.com",
            password_hash="test_hash",
            role="veterinario",
        )
        db.session.add(user)
        db.session.commit()

        med = Medicamento(
            nome="Amoxicilina",
            principio_ativo="Amoxicilina",
            classificacao="Antimicrobiano",
            created_by=user.id,
        )
        db.session.add(med)
        db.session.commit()

        _login(client, user.id)

        # POST /apresentacao_medicamento com parsing de concentração
        payload = {
            "medicamento_id": med.id,
            "forma": "comprimido",
            "concentracao": "500 mg",
            "fabricante": "Medicamento Genérico",
        }
        resp = client.post("/apresentacao_medicamento", json=payload)
        assert resp.status_code == 200
        dados = resp.get_json()
        assert dados["success"] is True
        assert dados["forma"] == "comprimido"
        assert dados["concentracao"] == "500 mg"
        assert dados["fabricante"] == "Medicamento Genérico"
        assert "apresentacoes" in dados
        assert len(dados["apresentacoes"]) >= 1

        # Verifica persistência no banco
        ap = ApresentacaoMedicamento.query.get(dados["id"])
        assert ap is not None
        assert ap.forma == "comprimido"
        assert float(ap.concentracao_valor) == 500.0
        assert ap.concentracao_unidade == "mg"


def test_criar_apresentacao_medicamento_sem_login_bloqueado(app, client):
    with app.app_context():
        med = Medicamento(
            nome="Metronidazol",
            principio_ativo="Metronidazol",
            created_by=1,
        )
        db.session.add(med)
        db.session.commit()

        # Sem login deve redirecionar ou retornar 401/302
        resp = client.post("/apresentacao_medicamento", json={
            "medicamento_id": med.id,
            "forma": "comprimido",
            "concentracao": "250 mg",
        })
        assert resp.status_code in (302, 401)


def test_cefalexina_500mg_match_produto_loja(app):
    with app.app_context():
        # Cria o produto na loja com preço base de 25.20 (R$ 28.00 público com taxa de 10%)
        produto = Product(
            name="Cefalexina 500mg 10 comprimidos Genérico",
            description="Cefalexina 500 mg comprimido genérico",
            price=25.20,
            stock=10,
            status="active",
            is_demo=False,
            image_url="/static/img/produtos/cefalexina_500mg.png",
        )
        db.session.add(produto)
        db.session.commit()

        # Prescrição de Cefalexina 500mg comprimido
        prescricao = _FakePrescricao("Cefalexina — 500 mg comprimido")
        linhas = build_prescription_offers([prescricao])

        assert len(linhas) == 1
        linha = linhas[0]
        assert linha.has_offer is True
        assert linha.best is not None
        assert linha.best.same_strength is True
        assert linha.best.product.name == "Cefalexina 500mg 10 comprimidos Genérico"
        # Preço público deve ser R$ 28.00
        assert float(linha.best.product.preco_publico) == 28.00
        assert linha.best.product.image_url == "/static/img/produtos/cefalexina_500mg.png"
