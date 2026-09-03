"""Cadastra/atualiza a Sulfadiazina de Prata 10mg/g Creme 30g no Bulario e na Loja (idempotente).

Uso:
    python scripts/seed_produto_sulfadiazina.py
    # ou ajustando parametros:
    python scripts/seed_produto_sulfadiazina.py --preco 29.00 --estoque 10 --casa-de-racao-id 34
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

NOME_MEDICAMENTO = "Sulfadiazina de Prata"
PRINCIPIO_ATIVO = "Sulfadiazina de Prata"
CLASSIFICACAO = "Antimicrobiano topico / Cicatrizante"

NOME_PRODUTO = "Sulfadiazina de Prata 10mg/g Creme 30g"
NOMES_ANTERIORES = [
    "Sulfadiazina de Prata 10mg/g Creme Dermatologico 30g",
    "Sulfadiazina de Prata 10mg/g Creme Dermatologico",
    "Sulfadiazina de Prata 1% Creme 30g",
    "Sulfadiazina de Prata Creme 30g",
    "Sulfadiazina de Prata",
]
DESCRICAO_PRODUTO = (
    "Sulfadiazina de Prata 10 mg/g (1%) Creme dermatologico, bisnaga com 30 g. "
    "Antimicrobiano topico e cicatrizante indicado na prevencao e tratamento de infeccoes em feridas, queimaduras e lesoes cutaneas. "
    "Venda sob prescricao medica com retencao de receita."
)
IMAGEM_PRODUTO = "https://petorlandia.s3.amazonaws.com/products/sulfadiazina_de_prata_10mg_creme_30g.png"
IMAGEM_LOCAL = "/static/img/produtos/sulfadiazina_de_prata_10mg_creme_30g.png"
CATEGORIA_PRODUTO = "medicamento"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nome-produto", default=NOME_PRODUTO)
    parser.add_argument("--preco", type=float, default=29.00, help="Preco base liquido do vendedor (sem taxas)")
    parser.add_argument("--estoque", type=int, default=10)
    parser.add_argument("--categoria", default=CATEGORIA_PRODUTO)
    parser.add_argument("--casa-de-racao-id", type=int, default=34, help="ID da Casa de Racao (padrao: 34 AgroGraner)")
    return parser.parse_args()


def seed_sulfadiazina(
    preco: float = 29.00,
    estoque: int = 10,
    nome_produto: str = NOME_PRODUTO,
    casa_de_racao_id: int | None = None,
):
    # 1. Garantir Medicamento no Bulario
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
            via_administracao="Topica",
            dosagem_recomendada="Aplicar camada fina sobre a lesao 1 a 2 vezes ao dia",
            frequencia="A cada 12 a 24 horas",
            duracao_tratamento="Ate a cicatrizacao completa",
            created_by=1,
        )
        db.session.add(med)
        db.session.flush()
        print(f"Medicamento criado: {med.nome} (id={med.id})")
    else:
        if not med.principio_ativo:
            med.principio_ativo = PRINCIPIO_ATIVO
        if not med.classificacao:
            med.classificacao = CLASSIFICACAO
        print(f"Medicamento encontrado: {med.nome} (id={med.id})")

    # 2. Garantir Apresentacao no Bulario
    apres = (
        ApresentacaoMedicamento.query
        .filter_by(medicamento_id=med.id)
        .filter(
            ApresentacaoMedicamento.forma.ilike("creme"),
            ApresentacaoMedicamento.concentracao.ilike("%10%mg%"),
        )
        .first()
    )

    if apres is None:
        apres = ApresentacaoMedicamento(
            medicamento_id=med.id,
            forma="creme",
            concentracao="10 mg/g",
            concentracao_valor=10.0,
            concentracao_unidade="mg/g",
            volume_valor=30.0,
            volume_unidade="g",
            fabricante="Medicamento Generico",
            nome_variante=NOME_PRODUTO,
            nome_comercial="Sulfadiazina de Prata 10mg/g Creme 30g",
        )
        db.session.add(apres)
        db.session.flush()
        print(f"Apresentacao criada: {apres.forma} {apres.concentracao} {apres.volume_valor}{apres.volume_unidade} (id={apres.id})")
    else:
        apres.forma = "creme"
        apres.concentracao = "10 mg/g"
        apres.concentracao_valor = 10.0
        apres.concentracao_unidade = "mg/g"
        apres.volume_valor = 30.0
        apres.volume_unidade = "g"
        if not apres.fabricante:
            apres.fabricante = "Medicamento Generico"
        if not apres.nome_variante:
            apres.nome_variante = NOME_PRODUTO
        print(f"Apresentacao atualizada: {apres.forma} {apres.concentracao} (id={apres.id})")

    # 3. Garantir Dose padrao no Bulario se nao houver
    dose_existente = DoseMedicamento.query.filter_by(medicamento_id=med.id).first()
    if dose_existente is None:
        dose_padrao = DoseMedicamento(
            medicamento_id=med.id,
            especie="Caes e Gatos",
            especie_code="AMBOS",
            faixa_peso="Qualquer peso",
            via="Topica",
            dose="Aplicar fina camada sobre a regiao acometida",
            frequencia="A cada 12 horas",
            intervalo_horas=12,
            duracao="Ate a cicatrizacao completa ou a criterio medico-veterinario",
            observacao="Aplicar fina camada sobre a regiao acometida apos limpeza local.",
        )
        db.session.add(dose_padrao)
        print("Dose padrao cadastrada no Bulario.")

    # 4. Validar Casa de Racao se informada
    casa = None
    if casa_de_racao_id:
        try:
            casa = CasaDeRacao.query.get(casa_de_racao_id)
        except Exception:
            casa = None
        if casa:
            print(f"Vinculado a Casa de Racao: {casa.nome} (id={casa.id}, status={casa.status})")
        else:
            print(f"Aviso: CasaDeRacao {casa_de_racao_id} nao encontrada; cadastrando sem casa especifica.")
            casa_de_racao_id = None

    # 5. Garantir Produto na Loja
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

    # 6. Garantir ProductVariant (apresentacao na Loja)
    variant = ProductVariant.query.filter_by(product_id=produto.id).first()
    if variant is None:
        variant = ProductVariant(
            product_id=produto.id,
            name="Bisnaga 30 g",
            dosage="10 mg/g (1%)",
            package_quantity="1 bisnaga",
            weight_volume="30 g",
            price=float(preco),
            stock=estoque,
            image_url=IMAGEM_PRODUTO,
            status="active",
            position=0,
        )
        db.session.add(variant)
        print("Variacao de produto (ProductVariant) criada.")
    else:
        variant.price = float(preco)
        variant.stock = estoque
        variant.status = "active"
        variant.weight_volume = "30 g"
        variant.dosage = "10 mg/g (1%)"
        if not variant.image_url:
            variant.image_url = IMAGEM_PRODUTO
        print(f"Variacao de produto existente atualizada: id={variant.id}")

    db.session.commit()

    preco_pub = produto.preco_publico
    taxa = (Decimal(str(preco_pub)) - Decimal(str(preco))) if preco_pub else Decimal("0")

    print("\n" + "="*60)
    print(f"OK: Produto {'criado' if criado else 'atualizado'}:")
    print(f" - ID: {produto.id}")
    print(f" - Nome: {produto.name}")
    print(f" - Preco Base (Repasse sem taxas): R$ {produto.price:.2f}")
    print(f" - Preco Publico com Taxa: R$ {preco_pub:.2f} (Taxa da plataforma: R$ {taxa:.2f})")
    print(f" - Estoque: {produto.stock} unidades")
    print(f" - Categoria: {produto.category}")
    print(f" - Status: {produto.status} (Visivel na loja)")
    print(f" - Casa de Racao: {casa.nome if casa else 'Geral / Plataforma'} (ID: {produto.casa_de_racao_id})")
    print(f" - Imagem: {produto.image_url}")
    print("="*60 + "\n")

    return med, apres, produto


def main():
    args = parse_args()
    app = create_app()
    with app.app_context():
        seed_sulfadiazina(
            preco=args.preco,
            estoque=args.estoque,
            nome_produto=args.nome_produto,
            casa_de_racao_id=args.casa_de_racao_id,
        )


if __name__ == "__main__":
    main()
