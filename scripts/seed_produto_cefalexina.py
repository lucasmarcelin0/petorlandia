"""Cadastra/atualiza a Cefalexina 500mg no Bulário e na Loja (idempotente).

Uso:
    python scripts/seed_produto_cefalexina.py
    # ou ajustando preço:
    python scripts/seed_produto_cefalexina.py --preco 25.20 --estoque 10
"""

import argparse
import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app_factory import create_app
from extensions import db
from models.bulario import ApresentacaoMedicamento, DoseMedicamento, Medicamento
from models.loja import Product
from models.usuarios import User

NOME_MEDICAMENTO = "Cefalexina"
PRINCIPIO_ATIVO = "Cefalexina"
CLASSIFICACAO = "Antimicrobiano"

NOME_PRODUTO = "Cefalexina 500mg 10 comprimidos Genérico"
NOMES_ANTERIORES = [
    "Cefalexina 500mg Genérico",
    "Cefalexina 500 mg Genérico",
    "Cefalexina 500mg 10 comprimidos",
]
DESCRICAO_PRODUTO = (
    "Cefalexina 500 mg, caixa com 10 comprimidos. "
    "Medicamento genérico. Venda sob prescrição médica."
)
IMAGEM_PRODUTO = "/static/img/produtos/cefalexina_500mg.png"
CATEGORIA_PRODUTO = "medicamento"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nome-produto", default=NOME_PRODUTO)
    # Preço base 25.20 com taxa de 10% resulta em preço público de R$ 28.00 (25.20 / 0.90 = 28.00)
    parser.add_argument("--preco", type=float, default=25.20)
    parser.add_argument("--estoque", type=int, default=10)
    parser.add_argument("--categoria", default=CATEGORIA_PRODUTO)
    return parser.parse_args()


def seed_cefalexina(preco: float = 25.20, estoque: int = 10, nome_produto: str = NOME_PRODUTO):
    # 1. Garantir Medicamento no Bulário
    med = Medicamento.query.filter(
        db.or_(
            Medicamento.nome.ilike(NOME_MEDICAMENTO),
            Medicamento.principio_ativo.ilike(PRINCIPIO_ATIVO),
        )
    ).first()

    if med is None:
        user = User.query.first()
        user_id = user.id if user else 1
        med = Medicamento(
            nome=NOME_MEDICAMENTO,
            principio_ativo=PRINCIPIO_ATIVO,
            classificacao=CLASSIFICACAO,
            via_administracao="Oral",
            dosagem_recomendada="20 a 30 mg/kg a cada 8 a 12 horas",
            frequencia="BID (a cada 12 horas)",
            duracao_tratamento="7 a 14 dias",
            created_by=user_id,
        )
        db.session.add(med)
        db.session.flush()
        print(f"Medicamento criado: {med.nome} (id={med.id})")
    else:
        print(f"Medicamento encontrado: {med.nome} (id={med.id})")

    # 2. Garantir Apresentação 500mg comprimido (não drágea)
    apres = (
        ApresentacaoMedicamento.query
        .filter_by(medicamento_id=med.id)
        .filter(
            ApresentacaoMedicamento.forma.ilike("comprimido"),
            ApresentacaoMedicamento.concentracao.ilike("%500%mg%"),
        )
        .first()
    )

    if apres is None:
        apres = ApresentacaoMedicamento(
            medicamento_id=med.id,
            forma="comprimido",
            concentracao="500 mg",
            concentracao_valor=500.0,
            concentracao_unidade="mg",
            fabricante="Medicamento Genérico",
            nome_variante="Cefalexina 500 mg Genérico",
            nome_comercial="Cefalexina 500 mg",
        )
        db.session.add(apres)
        db.session.flush()
        print(f"Apresentação criada: {apres.forma} {apres.concentracao} (id={apres.id})")
    else:
        apres.forma = "comprimido"
        apres.concentracao = "500 mg"
        apres.concentracao_valor = 500.0
        apres.concentracao_unidade = "mg"
        if not apres.fabricante:
            apres.fabricante = "Medicamento Genérico"
        print(f"Apresentação existente atualizada: {apres.forma} {apres.concentracao} (id={apres.id})")

    # 3. Garantir Dose padrão para cálculo automático se não houver
    dose_existente = DoseMedicamento.query.filter_by(medicamento_id=med.id).first()
    if dose_existente is None:
        dose_padrao = DoseMedicamento(
            medicamento_id=med.id,
            especie="Cães e Gatos",
            especie_code="AMBOS",
            faixa_peso="Todos os portes",
            via="Oral",
            dose="25 mg/kg",
            dose_min=Decimal("20.0"),
            dose_max=Decimal("30.0"),
            dose_unidade="MG_KG",
            frequencia="A cada 12 horas",
            intervalo_horas=12,
            duracao="7 a 14 dias",
            duracao_min_dias=7,
            duracao_max_dias=14,
            observacao="Administrar junto ou após as refeições para diminuir desconforto gástrico.",
        )
        db.session.add(dose_padrao)
        print("Dose padrão de Cefalexina cadastrada para cálculo de posologia.")

    # 4. Garantir Produto na Loja
    produto = Product.query.filter_by(name=nome_produto).first()
    if produto is None:
        produto = Product.query.filter(Product.name.in_(NOMES_ANTERIORES)).first()

    criado = produto is None
    if criado:
        produto = Product(name=nome_produto)
        db.session.add(produto)
    else:
        produto.name = nome_produto

    produto.description = DESCRICAO_PRODUTO
    produto.price = preco
    produto.stock = estoque
    produto.category = CATEGORIA_PRODUTO
    produto.image_url = IMAGEM_PRODUTO
    produto.status = "active"
    produto.is_demo = False

    db.session.commit()

    preco_pub = produto.preco_publico
    print(
        f"Produto Loja {'Criado' if criado else 'Atualizado'}: id={produto.id} "
        f"nome='{produto.name}' preco_base=R$ {produto.price:.2f} preco_publico=R$ {preco_pub:.2f} "
        f"estoque={produto.stock} categoria={produto.category} imagem={produto.image_url}"
    )
    return med, apres, produto


def main():
    args = parse_args()
    app = create_app()
    with app.app_context():
        seed_cefalexina(preco=args.preco, estoque=args.estoque, nome_produto=args.nome_produto)


if __name__ == "__main__":
    main()
