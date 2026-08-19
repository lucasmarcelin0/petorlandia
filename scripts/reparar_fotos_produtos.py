"""Repara produtos cuja imagem principal ficou vazia (idempotente).

Antes da correção em ``blueprints/loja.py``, o botão "Adicionar Foto" sempre
criava uma foto extra e nunca preenchia ``Product.image_url``. O resultado é
um produto com miniaturas na galeria e "Imagem indisponível" no slot do topo —
o que leva a pessoa a reenviar a mesma foto, gerando duplicatas.

Este script conserta o estado já gravado:

1. promove a primeira foto extra a imagem principal quando ela está vazia;
2. remove fotos extras que apontam para a mesma URL da principal.

Uso (no Heroku, após o deploy):

    python scripts/reparar_fotos_produtos.py            # dry-run
    python scripts/reparar_fotos_produtos.py --aplicar  # grava
"""

import argparse

from app_factory import create_app
from extensions import db
from models import Product, ProductPhoto


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Grava as alterações. Sem esta flag, apenas relata o que faria.",
    )
    parser.add_argument(
        "--produto-id",
        type=int,
        default=None,
        help="Limita o reparo a um produto específico.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    app = create_app()
    with app.app_context():
        query = Product.query
        if args.produto_id:
            query = query.filter(Product.id == args.produto_id)

        promovidos = 0
        duplicatas = 0
        for produto in query.all():
            extras = list(produto.extra_photos)
            if not extras:
                continue

            if not produto.image_url:
                principal = next(
                    (foto.image_url for foto in extras if foto.image_url), None
                )
                if principal:
                    print(f"produto {produto.id}: principal <- {principal}")
                    produto.image_url = principal
                    promovidos += 1

            if not produto.image_url:
                continue

            for foto in extras:
                if foto.image_url == produto.image_url:
                    print(f"produto {produto.id}: remove extra duplicada {foto.id}")
                    db.session.delete(foto)
                    duplicatas += 1

        print(
            f"Promovidos: {promovidos} | extras duplicadas removidas: {duplicatas}"
        )
        if args.aplicar:
            db.session.commit()
            print("Alterações gravadas.")
        else:
            db.session.rollback()
            print("Dry-run: nada gravado. Use --aplicar.")


if __name__ == "__main__":
    main()
