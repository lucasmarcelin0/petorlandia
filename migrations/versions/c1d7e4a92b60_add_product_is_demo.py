"""Mark demo products so the public store opens by itself.

A vitrine ficava anunciando "os melhores produtos" com um único item chamado
"Teste produto 1". Com este marcador, produtos de demonstração somem do
catálogo público e deixam de contar como sortimento — a loja volta a aparecer
sozinha quando o primeiro produto real for cadastrado.

Revision ID: c1d7e4a92b60
Revises: b9c5d3f8e1a2
Create Date: 2026-08-02 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c1d7e4a92b60"
down_revision = "b9c5d3f8e1a2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_demo",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # Produtos já existentes cujo nome denuncia que são de teste. O filtro é
    # deliberadamente estreito: marcar um produto real como demo o tiraria da
    # loja, então na dúvida o produto continua público.
    op.execute(
        """
        UPDATE product
           SET is_demo = TRUE
         WHERE lower(name) LIKE 'teste %'
            OR lower(name) LIKE 'test %'
            OR lower(name) = 'teste'
        """
    )


def downgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.drop_column("is_demo")
