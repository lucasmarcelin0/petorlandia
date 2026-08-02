"""Compra dos medicamentos direto na receita.

O caso que originou estes testes é real: a receita 3499 prescreve
"Prednisona — 5 mg comprimido" e a loja tem "Prednisona 5mg" (sem estoque) e
"Prednisona 20mg" (com estoque). Trocar uma pela outra é dano, não
conveniência — e é isso que a maior parte destes testes protege.
"""

from extensions import db
from models import (
    Animal,
    BlocoPrescricao,
    Clinica,
    OrderItem,
    Prescricao,
    Product,
    User,
)
from services.prescription_store import (
    build_prescription_offers,
    bulk_buyable_products,
)


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _produto(nome, price=20.0, stock=5, is_demo=False, status='active') -> Product:
    produto = Product(
        name=nome, description='', price=price, stock=stock,
        status=status, is_demo=is_demo,
    )
    db.session.add(produto)
    db.session.commit()
    return produto


class _FakePrescricao:
    def __init__(self, medicamento):
        self.medicamento = medicamento


def _cenario_real():
    """Reproduz o catálogo e a receita que existem em produção."""
    _produto('Shampoo Clorexidina', 28.0, 4)
    _produto('Cetoconazol + Dipropionato de betametasona + Sulfato de Neomicina', 27.78, 2)
    _produto('Prednisona 20mg 10 comprimidos', 20.18, 2)
    _produto('Prednisona 5mg', 16.42, 0)
    return [
        _FakePrescricao('Shampoo de clorexidina - 0,20%, frasco (500mL) — 0,20% shampoo (500 mL)'),
        _FakePrescricao('Simparic — 20 mg comprimido (Caes 5,1 a 10 kg)'),
        _FakePrescricao('Prednisona — 5 mg comprimido'),
        _FakePrescricao('Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g + Sulfato de Neomicina'),
    ]


# ------------------------------------------------------------- correspondência


def test_encontra_o_produto_pelo_principio_ativo(app):
    with app.app_context():
        prescritos = _cenario_real()
        linhas = build_prescription_offers(prescritos)

        shampoo = linhas[0]
        assert shampoo.best.product.name == 'Shampoo Clorexidina'
        assert shampoo.best.same_strength is True


def test_item_sem_produto_correspondente_fica_explicito(app):
    with app.app_context():
        linhas = build_prescription_offers(_cenario_real())
        simparic = linhas[1]
        assert simparic.has_offer is False


def test_composto_casa_por_varios_principios(app):
    with app.app_context():
        linhas = build_prescription_offers(_cenario_real())
        composto = linhas[3]
        assert composto.best.score >= 3
        assert composto.best.same_strength is True


def test_concentracao_diferente_e_marcada(app):
    with app.app_context():
        linhas = build_prescription_offers(_cenario_real())
        prednisona = linhas[2]

        nomes = {m.product.name: m for m in prednisona.matches}
        assert 'Prednisona 5mg' in nomes
        assert 'Prednisona 20mg 10 comprimidos' in nomes
        assert nomes['Prednisona 5mg'].same_strength is True
        assert nomes['Prednisona 20mg 10 comprimidos'].same_strength is False


def test_outra_concentracao_some_quando_a_prescrita_esta_a_venda(app):
    """Dois cartões sob o mesmo item só geram dúvida sobre qual é o certo."""
    with app.app_context():
        _produto('Prednisona 5mg', 16.42, 3)
        _produto('Prednisona 20mg 10 comprimidos', 20.18, 2)

        linhas = build_prescription_offers([_FakePrescricao('Prednisona — 5 mg comprimido')])
        nomes = [m.product.name for m in linhas[0].matches]

        assert nomes == ['Prednisona 5mg']
        assert linhas[0].alternative_reason is None


def test_outra_concentracao_aparece_com_motivo_quando_falta_estoque(app):
    with app.app_context():
        _produto('Prednisona 5mg', 16.42, 0)
        _produto('Prednisona 20mg 10 comprimidos', 20.18, 2)

        linha = build_prescription_offers([_FakePrescricao('Prednisona — 5 mg comprimido')])[0]

        assert len(linha.matches) == 2
        assert 'sem estoque' in linha.alternative_reason


def test_sem_apresentacao_exata_o_motivo_diz_isso(app):
    with app.app_context():
        _produto('Prednisona 20mg 10 comprimidos', 20.18, 2)

        linha = build_prescription_offers([_FakePrescricao('Prednisona — 5 mg comprimido')])[0]

        assert linha.compatible is None
        assert 'Não temos a apresentação exata' in linha.alternative_reason


def test_palavra_generica_sozinha_nao_gera_sugestao(app):
    """"Sulfato" isolado não pode arrastar um produto para a receita."""
    with app.app_context():
        _produto('Sulfato de Neomicina pomada', 30.0, 5)
        linhas = build_prescription_offers([_FakePrescricao('Sulfato ferroso 40mg')])
        assert linhas[0].has_offer is False


def test_produto_de_demo_e_inativo_ficam_de_fora(app):
    with app.app_context():
        _produto('Prednisona 5mg', 16.0, 5, is_demo=True)
        _produto('Prednisona 5mg inativa', 16.0, 5, status='inactive')
        linhas = build_prescription_offers([_FakePrescricao('Prednisona — 5 mg comprimido')])
        assert linhas[0].has_offer is False


# ------------------------------------------------------- regra do "adicionar todos"


def test_lote_ignora_sem_estoque_e_apresentacao_divergente(app):
    with app.app_context():
        linhas = build_prescription_offers(_cenario_real())
        nomes = {p.name for p in bulk_buyable_products(linhas)}

        assert nomes == {
            'Shampoo Clorexidina',
            'Cetoconazol + Dipropionato de betametasona + Sulfato de Neomicina',
        }
        # A de 5 mg está sem estoque; a de 20 mg não é a prescrita.
        assert not any('Prednisona' in nome for nome in nomes)


# ---------------------------------------------------------------- fluxo na tela


def _receita_completa():
    clinica = Clinica(nome='Clínica Teste', status='ativa')
    tutor = User(name='Tutor', email='tutor-receita@example.test', password_hash='x')
    db.session.add_all([clinica, tutor])
    db.session.commit()

    animal = Animal(name='Rex', user_id=tutor.id, clinica_id=clinica.id)
    db.session.add(animal)
    db.session.commit()

    bloco = BlocoPrescricao(animal_id=animal.id, clinica_id=clinica.id)
    db.session.add(bloco)
    db.session.commit()

    for texto in (
        'Shampoo de clorexidina - 0,20%, frasco (500mL)',
        'Prednisona — 5 mg comprimido',
    ):
        db.session.add(Prescricao(
            bloco_id=bloco.id, animal_id=animal.id, medicamento=texto
        ))
    db.session.commit()
    return bloco, tutor


def _abrir_loja():
    from models.base import SiteFlag

    SiteFlag.set('loja_em_breve', False)
    db.session.commit()


def test_receita_mostra_bloco_de_compra_para_o_tutor(app, client):
    with app.app_context():
        _abrir_loja()
        _produto('Shampoo Clorexidina', 28.0, 4)
        _produto('Prednisona 20mg 10 comprimidos', 20.18, 2)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id = bloco.id, tutor.id

    _login(client, tutor_id)
    body = client.get(f'/bloco_prescricao/{bloco_id}/imprimir').data.decode()

    assert 'Comprar os medicamentos desta receita' in body
    assert 'Shampoo Clorexidina' in body
    assert 'Apresentação diferente da prescrita' in body
    # Nunca sai no papel: a receita impressa é documento clínico.
    assert '.receita-loja { display: none !important; }' in body


def test_adicionar_todos_coloca_so_o_que_confere(app, client):
    with app.app_context():
        _abrir_loja()
        _produto('Shampoo Clorexidina', 28.0, 4)
        _produto('Prednisona 20mg 10 comprimidos', 20.18, 2)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id = bloco.id, tutor.id

    _login(client, tutor_id)
    response = client.post(f'/bloco_prescricao/{bloco_id}/comprar')
    assert response.status_code == 302
    assert '/carrinho' in response.headers['Location']

    with app.app_context():
        itens = OrderItem.query.all()
        assert [item.item_name for item in itens] == ['Shampoo Clorexidina']


def test_adicionar_todos_nao_duplica_o_que_ja_esta_no_carrinho(app, client):
    """Garante presença, não soma outra caixa do mesmo medicamento."""
    with app.app_context():
        _abrir_loja()
        shampoo = _produto('Shampoo Clorexidina', 28.0, 4)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id, shampoo_id = bloco.id, tutor.id, shampoo.id

    _login(client, tutor_id)
    client.post(f'/bloco_prescricao/{bloco_id}/comprar', data={'product_id': shampoo_id})
    resposta = client.post(
        f'/bloco_prescricao/{bloco_id}/comprar',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )

    assert resposta.get_json()['info'] is True
    with app.app_context():
        assert OrderItem.query.one().quantity == 1


def test_nao_da_para_forjar_um_produto_fora_da_receita(app, client):
    with app.app_context():
        _abrir_loja()
        _produto('Shampoo Clorexidina', 28.0, 4)
        intruso = _produto('Ração Golden 15kg', 180.0, 10)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id, intruso_id = bloco.id, tutor.id, intruso.id

    _login(client, tutor_id)
    client.post(
        f'/bloco_prescricao/{bloco_id}/comprar',
        data={'product_id': intruso_id},
    )

    with app.app_context():
        assert OrderItem.query.count() == 0


def test_adicionar_responde_em_json_para_o_tutor_ficar_na_receita(app, client):
    with app.app_context():
        _abrir_loja()
        shampoo = _produto('Shampoo Clorexidina', 28.0, 4)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id, shampoo_id = bloco.id, tutor.id, shampoo.id

    _login(client, tutor_id)
    response = client.post(
        f'/bloco_prescricao/{bloco_id}/comprar',
        data={'product_id': shampoo_id},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )

    assert response.status_code == 200
    dados = response.get_json()
    assert dados['success'] is True
    assert dados['added'] == [shampoo_id]
    assert dados['cart_quantity'] == 1
    assert dados['cart_url'].endswith('/carrinho')


def test_item_em_outra_concentracao_pode_ser_adicionado_um_a_um(app, client):
    """Quem clica está vendo o aviso ao lado do botão; o lote é que não pode."""
    with app.app_context():
        _abrir_loja()
        _produto('Prednisona 5mg', 16.42, 0)
        vinte = _produto('Prednisona 20mg 10 comprimidos', 20.18, 2)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id, vinte_id = bloco.id, tutor.id, vinte.id

    _login(client, tutor_id)
    client.post(
        f'/bloco_prescricao/{bloco_id}/comprar',
        data={'product_id': vinte_id},
    )

    with app.app_context():
        assert OrderItem.query.one().item_name == 'Prednisona 20mg 10 comprimidos'


def test_produto_sem_estoque_nao_entra_nem_um_a_um(app, client):
    with app.app_context():
        _abrir_loja()
        esgotado = _produto('Prednisona 5mg', 16.42, 0)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id, esgotado_id = bloco.id, tutor.id, esgotado.id

    _login(client, tutor_id)
    client.post(
        f'/bloco_prescricao/{bloco_id}/comprar',
        data={'product_id': esgotado_id},
    )

    with app.app_context():
        assert OrderItem.query.count() == 0


def test_receita_mostra_a_foto_do_produto(app, client):
    with app.app_context():
        _abrir_loja()
        shampoo = _produto('Shampoo Clorexidina', 28.0, 4)
        shampoo.image_url = 'https://exemplo.test/shampoo.png'
        db.session.commit()
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id = bloco.id, tutor.id

    _login(client, tutor_id)
    body = client.get(f'/bloco_prescricao/{bloco_id}/imprimir').data.decode()
    assert 'https://exemplo.test/shampoo.png' in body


def test_item_avulso_entra_no_carrinho(app, client):
    with app.app_context():
        _abrir_loja()
        shampoo = _produto('Shampoo Clorexidina', 28.0, 4)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id, shampoo_id = bloco.id, tutor.id, shampoo.id

    _login(client, tutor_id)
    client.post(
        f'/bloco_prescricao/{bloco_id}/comprar',
        data={'product_id': shampoo_id},
    )

    with app.app_context():
        item = OrderItem.query.one()
        assert item.item_name == 'Shampoo Clorexidina'
        # O preço gravado é o público (taxa embutida), não o repasse.
        assert float(item.unit_price) > 28.0
        assert float(item.seller_unit_amount) == 28.0


def test_estranho_nao_compra_pela_receita_de_outro(app, client):
    with app.app_context():
        _abrir_loja()
        _produto('Shampoo Clorexidina', 28.0, 4)
        bloco, _tutor = _receita_completa()
        estranho = User(name='Estranho', email='estranho@example.test', password_hash='x')
        db.session.add(estranho)
        db.session.commit()
        bloco_id, estranho_id = bloco.id, estranho.id

    _login(client, estranho_id)
    response = client.post(f'/bloco_prescricao/{bloco_id}/comprar')

    assert response.status_code in (403, 404)
    with app.app_context():
        assert OrderItem.query.count() == 0


def test_sem_catalogo_a_receita_nao_mostra_loja(app, client):
    with app.app_context():
        _produto('Teste produto 1', 1.11, 1, is_demo=True)
        bloco, tutor = _receita_completa()
        bloco_id, tutor_id = bloco.id, tutor.id

    _login(client, tutor_id)
    body = client.get(f'/bloco_prescricao/{bloco_id}/imprimir').data.decode()
    assert 'Comprar os medicamentos desta receita' not in body
