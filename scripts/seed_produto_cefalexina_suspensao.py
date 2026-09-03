"""Cadastra/atualiza a Cefalexina 250mg/5ml Pó para Suspensão Oral no Bulário e na Loja (idempotente).

Uso:
    python scripts/seed_produto_cefalexina_suspensao.py
    # ou ajustando parâmetros:
    python scripts/seed_produto_cefalexina_suspensao.py --preco 60.00 --estoque 10 --casa-de-racao-id 34
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
from models.loja import Product, ProductVariant
from models.racao import CasaDeRacao

NOME_MEDICAMENTO = "Cefalexina"
PRINCIPIO_ATIVO = "Cefalexina"
CLASSIFICACAO = "Antimicrobiano"

NOME_PRODUTO = "Cefalexina 250mg/5ml Pó para Suspensão Oral 100ml"
NOMES_ANTERIORES = [
    "Cefalexina 250mg/5ml Pó para Suspensão Oral",
    "Cefalexina 250mg/5ml Suspensão Oral",
    "Cefalexina 250 mg / 5 mL Suspensão Oral",
    "Cefalexina 250mg/5ml Suspensão Oral 100ml",
    "Cefalexina 250mg/5ml Suspensão Oral 60ml",
]
DESCRICAO_PRODUTO = (
    "Cefalexina 250 mg/5 mL (50 mg/mL) pó para preparação de suspensão oral. "
    "Frasco para reconstituição de 100 mL com seringa dosadora. "
    "Antimicrobiano de amplo espectro para cães e gatos. "
    "Venda sob prescrição médica com retenção de receita."
)
IMAGEM_PRODUTO = "https://petorlandia.s3.amazonaws.com/products/cefalexina_250mg_suspensao_100ml.png"
IMAGEM_LOCAL = "/static/img/produtos/cefalexina_250mg_suspensao_100ml.png"
CATEGORIA_PRODUTO = "medicamento"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nome-produto", default=NOME_PRODUTO)
    parser.add_argument("--preco", type=float, default=60.00, help="Preço base líquido do vendedor (sem taxas)")
    parser.add_argument("--estoque", type=int, default=10)
    parser.add_argument("--categoria", default=CATEGORIA_PRODUTO)
    parser.add_argument("--casa-de-racao-id", type=int, default=34, help="ID da Casa de Ração (padrão: 34 AgroGraner)")
    return parser.parse_args()


def seed_cefalexina_suspensao(
    preco: float = 60.00,
    estoque: int = 10,
    nome_produto: str = NOME_PRODUTO,
    casa_de_racao_id: int | None = 34,
):
    # 1. Garantir Medicamento no Bulário
    med = Medicamento.query.filter(
        db.or_(
            Medicamento.nome.ilike(f"%{NOME_MEDICAMENTO}%"),
            Medicamento.principio_ativo.ilike(f"%{PRINCIPIO_ATIVO}%"),
        )
    ).first()

    if med is None:
        med = Medicamento(
            nome=NOME_MEDICAMENTO,
            principio_ativo=PRINCIPIO_ATIVO,
            classificacao=CLASSIFICACAO,
            via_administracao="Oral",
            dosagem_recomendada="20 a 30 mg/kg a cada 8 a 12 horas",
            frequencia="BID (a cada 12 horas)",
            duracao_tratamento="7 a 14 dias",
            created_by=1,
        )
        db.session.add(med)
        db.session.flush()
        print(f"Medicamento criado: {med.nome} (id={med.id})")
    else:
        print(f"Medicamento encontrado: {med.nome} (id={med.id})")

    # 2. Garantir Apresentação Suspensão 250mg/5ml no Bulário
    apres = (
        ApresentacaoMedicamento.query
        .filter_by(medicamento_id=med.id)
        .filter(
            db.or_(
                ApresentacaoMedicamento.forma.ilike("%suspensão%"),
                ApresentacaoMedicamento.forma.ilike("%solução%"),
            ),
            ApresentacaoMedicamento.concentracao.ilike("%250%5%"),
        )
        .first()
    )

    if apres is None:
        apres = ApresentacaoMedicamento(
            medicamento_id=med.id,
            forma="suspensão oral",
            concentracao="250 mg / 5 mL",
            concentracao_valor=50.0,
            concentracao_unidade="mg/ml",
            volume_valor=100.0,
            volume_unidade="ml",
            fabricante="Medicamento Genérico",
            nome_variante=NOME_PRODUTO,
            nome_comercial="Cefalexina 250 mg / 5 mL Suspensão Oral",
        )
        db.session.add(apres)
        db.session.flush()
        print(f"Apresentação criada: {apres.forma} {apres.concentracao} (id={apres.id})")
    else:
        apres.forma = "suspensão oral"
        apres.concentracao = "250 mg / 5 mL"
        apres.concentracao_valor = 50.0
        apres.concentracao_unidade = "mg/ml"
        apres.volume_valor = 100.0
        apres.volume_unidade = "ml"
        if not apres.fabricante:
            apres.fabricante = "Medicamento Genérico"
        if not apres.nome_variante:
            apres.nome_variante = NOME_PRODUTO
        print(f"Apresentação existente atualizada: {apres.forma} {apres.concentracao} (id={apres.id})")

    # 3. Validar Casa de Ração se informada
    casa = None
    if casa_de_racao_id:
        try:
            casa = CasaDeRacao.query.get(casa_de_racao_id)
        except Exception:
            casa = None
        if casa:
            print(f"Vinculado à Casa de Ração: {casa.nome} (id={casa.id}, status={casa.status})")
        else:
            print(f"Aviso: CasaDeRacao {casa_de_racao_id} não encontrada; cadastrando sem casa específica.")
            casa_de_racao_id = None

    # 4. Garantir Produto na Loja
    produto = None
    if casa_de_racao_id:
        produto = Product.query.filter_by(casa_de_racao_id=casa_de_racao_id, name=nome_produto).first()
    if produto is None:
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
    produto.price = float(preco)
    produto.stock = estoque
    produto.category = CATEGORIA_PRODUTO
    produto.image_url = IMAGEM_PRODUTO
    produto.status = "active"
    produto.is_demo = False
    if casa_de_racao_id:
        produto.casa_de_racao_id = casa_de_racao_id

    db.session.flush()

    # 5. Garantir ProductVariant
    variant = ProductVariant.query.filter_by(product_id=produto.id).first()
    if variant is None:
        variant = ProductVariant(
            product_id=produto.id,
            name="Frasco 100 mL",
            dosage="250 mg/5 mL (50 mg/mL)",
            package_quantity="1 frasco + seringa",
            weight_volume="100 mL",
            price=float(preco),
            stock=estoque,
            image_url=IMAGEM_PRODUTO,
            status="active",
            position=0,
        )
        db.session.add(variant)
        print("ProductVariant criada.")
    else:
        variant.name = "Frasco 100 mL"
        variant.dosage = "250 mg/5 mL (50 mg/mL)"
        variant.package_quantity = "1 frasco + seringa"
        variant.weight_volume = "100 mL"
        variant.price = float(preco)
        variant.stock = estoque
        variant.status = "active"
        variant.image_url = IMAGEM_PRODUTO
        print(f"ProductVariant atualizada: id={variant.id}")

    db.session.commit()

    preco_pub = produto.preco_publico
    taxa = (Decimal(str(preco_pub)) - Decimal(str(preco))) if preco_pub else Decimal("0")

    print("\n" + "="*60)
    print(f"OK: Produto {'criado' if criado else 'atualizado'}:")
    print(f" - ID: {produto.id}")
    print(f" - Nome: {produto.name}")
    print(f" - Preço Base (Repasse sem taxas): R$ {produto.price:.2f}")
    print(f" - Preço Público com Taxa: R$ {preco_pub:.2f} (Taxa da plataforma: R$ {taxa:.2f})")
    print(f" - Estoque: {produto.stock} unidades")
    print(f" - Categoria: {produto.category}")
    print(f" - Status: {produto.status} (Visível na loja)")
    print(f" - Casa de Ração: {casa.nome if casa else 'Geral / Plataforma'} (ID: {produto.casa_de_racao_id})")
    print(f" - Imagem: {produto.image_url}")
    print("="*60 + "\n")

    return med, apres, produto


def main():
    args = parse_args()
    app = create_app()
    with app.app_context():
        seed_cefalexina_suspensao(
            preco=args.preco,
            estoque=args.estoque,
            nome_produto=args.nome_produto,
            casa_de_racao_id=args.casa_de_racao_id,
        )


if __name__ == "__main__":
    main()
