"""add unit_price nullable"""

from alembic import op
import sqlalchemy as sa

revision = "79f0241cd5c4"       # ← mantém o mesmo hash
down_revision = "690572b9db75"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("order_item") as batch_op:
        batch_op.add_column(
            sa.Column("unit_price", sa.Numeric(10, 2), nullable=True)
        )
    # nada mais aqui – NÃO altere product_id


def downgrade():
    with op.batch_alter_table("order_item") as batch_op:
        batch_op.drop_column("unit_price")
