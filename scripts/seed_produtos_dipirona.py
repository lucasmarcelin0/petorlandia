"""Cadastra/atualiza os produtos de Dipirona no Bulario e na Loja da PetOrlandia (idempotente).

Produtos cadastrados (vendidos diretamente pela PetOrlandia, sem clinicas ou casas de racao vinculadas):
1. Dipirona 500mg 10 comprimidos - Preco base: R$ 13,00
2. Dipirona 1g 10 comprimidos - Preco base: R$ 16,00
3. Dipirona Liquido 500mg/ml Gotas 20ml - Preco base: R$ 10,00
4. Dipirona Liquido Infantil 50mg/ml Solucao Oral - Preco base: R$ 30,00

Uso:
    python scripts/seed_produtos_dipirona.py
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
from models.usuarios import User

NOME_MEDICAMENTO = "Dipirona"
PRINCIPIO_ATIVO = "Dipirona"
CLASSIFICACAO = "Analgésico e Antipirético"

PRODUTOS_DIPIRONA = [
    {
        "nome": "Dipirona 500mg 10 comprimidos",
        "nomes_anteriores": [
            "Dipirona 500mg",
            "Dipirona 500 mg 10 comprimidos",
            "Dipirona 500mg 10 comprimidos Genérico",
        ],
        "preco_base": 13.00,
        "estoque": 10,
        "imagem": "/static/img/produtos/dipirona_500mg_10_comprimidos.png",
        "descricao": (
            "Dipirona 500 mg, caixa com 10 comprimidos. "
            "Analgésico e antipirético indicado para alívio de dor e febre. "
            "Medicamento genérico. Medicamento isento de prescrição médica (venda livre)."
        ),
        "forma": "comprimido",
        "concentracao": "500 mg",
        "concentracao_valor": 500.0,
        "concentracao_unidade": "mg",
        "variante": {
            "name": "Caixa com 10 comprimidos",
            "dosage": "500 mg",
            "package_quantity": "10 comprimidos",
            "weight_volume": "10 comprimidos",
        },
    },
    {
        "nome": "Dipirona 1g 10 comprimidos",
        "nomes_anteriores": [
            "Dipirona 1g",
            "Dipirona 1 g 10 comprimidos",
            "Dipirona 1000mg 10 comprimidos",
            "Dipirona 1g 10 comprimidos Genérico",
        ],
        "preco_base": 16.00,
        "estoque": 10,
        "imagem": "/static/img/produtos/dipirona_1g_10_comprimidos.png",
        "descricao": (
            "Dipirona 1 g (1000 mg), caixa com 10 comprimidos. "
            "Analgésico e antipirético potente para controle de dor e febre em animais de médio e grande porte. "
            "Medicamento genérico. Medicamento isento de prescrição médica (venda livre)."
        ),
        "forma": "comprimido",
        "concentracao": "1 g",
        "concentracao_valor": 1000.0,
        "concentracao_unidade": "mg",
        "variante": {
            "name": "Caixa com 10 comprimidos",
            "dosage": "1 g (1000 mg)",
            "package_quantity": "10 comprimidos",
            "weight_volume": "10 comprimidos",
        },
    },
    {
        "nome": "Dipirona Líquido 500mg/ml Gotas 20ml",
        "nomes_anteriores": [
            "Dipirona Líquido 500mg/ml",
            "Dipirona 500mg/ml Gotas",
            "Dipirona 500mg/ml Gotas 20ml",
            "Dipirona Gotas 500mg/ml",
            "Dipirona 500mg/ml Solução Oral",
        ],
        "preco_base": 10.00,
        "estoque": 10,
        "imagem": "/static/img/produtos/dipirona_liquido_500mg_ml.png",
        "descricao": (
            "Dipirona 500 mg/mL, solução oral em gotas, frasco com 20 mL. "
            "Analgésico e antitérmico de rápida absorção, ideal para dosagem fracionada por peso (gotas). "
            "Medicamento genérico. Medicamento isento de prescrição médica (venda livre)."
        ),
        "forma": "gotas",
        "concentracao": "500 mg/mL",
        "concentracao_valor": 500.0,
        "concentracao_unidade": "mg/ml",
        "volume_valor": 20.0,
        "volume_unidade": "ml",
        "variante": {
            "name": "Frasco 20 mL com conta-gotas",
            "dosage": "500 mg/mL",
            "package_quantity": "1 frasco conta-gotas",
            "weight_volume": "20 mL",
        },
    },
    {
        "nome": "Dipirona Líquido Infantil 50mg/ml Solução Oral",
        "nomes_anteriores": [
            "Dipirona Líquido Infantil 50mg/ml",
            "Dipirona Infantil 50mg/ml",
            "Dipirona Gotas Infantil 50mg/ml",
            "Dipirona Infantil 50mg/ml Solução Oral",
            "Dipirona Solução Oral Infantil 50mg/ml",
        ],
        "preco_base": 30.00,
        "estoque": 10,
        "imagem": "/static/img/produtos/dipirona_liquido_infantil_50mg_ml.png",
        "descricao": (
            "Dipirona Infantil 50 mg/mL, solução oral, frasco com seringa dosadora para dosagem milimétrica segura. "
            "Indicado para alívio de dor e febre em filhotes e animais de pequeno porte. "
            "Medicamento genérico. Medicamento isento de prescrição médica (venda livre)."
        ),
        "forma": "solução oral",
        "concentracao": "50 mg/mL",
        "concentracao_valor": 50.0,
        "concentracao_unidade": "mg/ml",
        "volume_valor": 50.0,
        "volume_unidade": "ml",
        "variante": {
            "name": "Frasco com seringa dosadora",
            "dosage": "50 mg/mL",
            "package_quantity": "1 frasco + seringa dosadora",
            "weight_volume": "50 mL",
        },
    },
]


def seed_dipirona_produtos(app=None):
    med = Medicamento.query.filter(
        db.or_(
            Medicamento.nome.ilike(NOME_MEDICAMENTO),
            Medicamento.principio_ativo.ilike(PRINCIPIO_ATIVO),
        )
    ).first()

    if med is None:
        user_id = 1
        med = Medicamento(
            nome=NOME_MEDICAMENTO,
            principio_ativo=PRINCIPIO_ATIVO,
            classificacao=CLASSIFICACAO,
            via_administracao="Oral",
            dosagem_recomendada="25 mg/kg a cada 8 a 12 horas",
            frequencia="TID (a cada 8 horas) ou BID (a cada 12 horas)",
            duracao_tratamento="1 a 5 dias conforme prescrição",
            created_by=user_id,
        )
        db.session.add(med)
        db.session.flush()
        print(f"Medicamento criado no Bulário: {med.nome} (id={med.id})")
    else:
        print(f"Medicamento encontrado no Bulário: {med.nome} (id={med.id})")

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
            dose_max=Decimal("28.0"),
            dose_unidade="MG_KG",
            frequencia="A cada 8 a 12 horas",
            intervalo_horas=8,
            duracao="1 a 3 dias",
            duracao_min_dias=1,
            duracao_max_dias=5,
            observacao="Uso sob prescrição veterinária. Evitar superdosagem.",
        )
        db.session.add(dose_padrao)
        print("Dose padrão de Dipirona cadastrada.")

    produtos_cadastrados = []

    for item in PRODUTOS_DIPIRONA:
        nome_prod = item["nome"]
        nomes_ant = item["nomes_anteriores"]
        preco_base = float(item["preco_base"])
        estoque = int(item["estoque"])
        imagem = item["imagem"]
        descricao = item["descricao"]

        apres = (
            ApresentacaoMedicamento.query
            .filter_by(medicamento_id=med.id)
            .filter(
                ApresentacaoMedicamento.forma.ilike(f"%{item['forma']}%"),
                ApresentacaoMedicamento.concentracao.ilike(f"%{item['concentracao']}%"),
            )
            .first()
        )
        if apres is None:
            apres = ApresentacaoMedicamento(
                medicamento_id=med.id,
                forma=item["forma"],
                concentracao=item["concentracao"],
                concentracao_valor=item.get("concentracao_valor"),
                concentracao_unidade=item.get("concentracao_unidade"),
                volume_valor=item.get("volume_valor"),
                volume_unidade=item.get("volume_unidade"),
                fabricante="Medicamento Genérico",
                nome_variante=nome_prod,
                nome_comercial=nome_prod,
            )
            db.session.add(apres)
            db.session.flush()
            print(f"Apresentação criada: {apres.forma} {apres.concentracao} (id={apres.id})")
        else:
            apres.forma = item["forma"]
            apres.concentracao = item["concentracao"]
            apres.concentracao_valor = item.get("concentracao_valor")
            apres.concentracao_unidade = item.get("concentracao_unidade")
            if item.get("volume_valor"):
                apres.volume_valor = item.get("volume_valor")
                apres.volume_unidade = item.get("volume_unidade")
            if not apres.fabricante:
                apres.fabricante = "Medicamento Genérico"

        produto = Product.query.filter_by(name=nome_prod).first()
        if produto is None:
            produto = Product.query.filter(Product.name.in_(nomes_ant)).first()

        criado = produto is None
        if criado:
            produto = Product(name=nome_prod)
            db.session.add(produto)
        else:
            produto.name = nome_prod

        produto.description = descricao
        produto.price = preco_base
        produto.stock = estoque
        produto.category = "medicamento"
        produto.image_url = imagem
        produto.status = "active"
        produto.is_demo = False
        produto.clinica_id = None
        produto.casa_de_racao_id = None

        db.session.flush()

        var_data = item["variante"]
        variant = ProductVariant.query.filter_by(product_id=produto.id).first()
        if variant is None:
            variant = ProductVariant(
                product_id=produto.id,
                name=var_data["name"],
                dosage=var_data.get("dosage"),
                package_quantity=var_data.get("package_quantity"),
                weight_volume=var_data.get("weight_volume"),
                price=preco_base,
                stock=estoque,
                image_url=imagem,
                status="active",
                position=0,
            )
            db.session.add(variant)
        else:
            variant.name = var_data["name"]
            variant.dosage = var_data.get("dosage")
            variant.package_quantity = var_data.get("package_quantity")
            variant.weight_volume = var_data.get("weight_volume")
            variant.price = preco_base
            variant.stock = estoque
            variant.status = "active"
            variant.image_url = imagem

        db.session.commit()
        produtos_cadastrados.append(produto)

        preco_pub = produto.preco_publico
        taxa = (Decimal(str(preco_pub)) - Decimal(str(produto.price))) if preco_pub else Decimal("0")

        print(f"\n[Produto {'CRIADO' if criado else 'ATUALIZADO'}]")
        print(f"  ID: {produto.id}")
        print(f"  Nome: {produto.name}")
        print(f"  Preço Base (repasse lojista): R$ {produto.price:.2f}")
        print(f"  Preço Público (+ taxa): R$ {preco_pub:.2f} (Taxa estimada: R$ {taxa:.2f})")
        print(f"  Estoque: {produto.stock} un")
        print(f"  Vendedor: PetOrlândia (clinica_id={produto.clinica_id}, casa_id={produto.casa_de_racao_id})")
        print(f"  Imagem: {produto.image_url}")

    return med, produtos_cadastrados


def main():
    app = create_app()
    with app.app_context():
        seed_dipirona_produtos(app)
        print("\nSeed de Dipirona concluído com sucesso!")


if __name__ == "__main__":
    main()
