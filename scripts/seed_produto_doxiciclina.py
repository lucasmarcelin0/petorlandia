"""Cadastra/atualiza a doxiciclina 100mg na Loja (idempotente).

Uso (no Heroku, após o deploy):

    python scripts/seed_produto_doxiciclina.py
    # ou ajustando preço/estoque:
    python scripts/seed_produto_doxiciclina.py --preco 40 --estoque 1

É seguro rodar várias vezes: casa pelo nome e só atualiza os campos abaixo.

ATENÇÃO: doxiciclina é venda sob prescrição médica. A Loja ainda não tem
nenhum conceito de receita — nem campo no ``Product``, nem no formulário, nem
no template — então o produto fica com compra direta, igual a uma ração.
Enquanto esse campo não existir, tratar este cadastro como decisão consciente
de quem opera a loja.
"""

import argparse

from app_factory import create_app
from extensions import db
from models import Product


NOME = "Doxiciclina 100mg 15 comprimidos Sandoz Genérico"
DESCRICAO = (
    "Cloridrato de doxiciclina 100mg, 15 comprimidos solúveis. "
    "Medicamento genérico. Venda sob prescrição médica."
)
CATEGORIA = "medicamento"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nome", default=NOME)
    parser.add_argument("--preco", type=float, default=40.0)
    parser.add_argument("--estoque", type=int, default=1)
    parser.add_argument("--categoria", default=CATEGORIA)
    return parser.parse_args()


def main():
    args = parse_args()
    app = create_app()
    with app.app_context():
        produto = Product.query.filter_by(name=args.nome).first()
        criado = produto is None
        if criado:
            produto = Product(name=args.nome)
            db.session.add(produto)

        produto.description = DESCRICAO
        produto.price = args.preco
        produto.stock = args.estoque
        produto.category = args.categoria
        produto.status = "active"
        produto.is_demo = False
        db.session.commit()

        print(
            f"{'Criado' if criado else 'Atualizado'}: id={produto.id} "
            f"preco={produto.price} estoque={produto.stock} "
            f"status={produto.status} categoria={produto.category}"
        )


if __name__ == "__main__":
    main()
