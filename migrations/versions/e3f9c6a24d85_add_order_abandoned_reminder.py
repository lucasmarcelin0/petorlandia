"""Remember which abandoned carts were already recovered by e-mail.

Revision ID: e3f9c6a24d85
Revises: d2e8b5f31c74
Create Date: 2026-08-02 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e3f9c6a24d85"
down_revision = "d2e8b5f31c74"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("order") as batch_op:
        batch_op.add_column(
            sa.Column(
                "abandoned_reminder_at", sa.DateTime(timezone=True), nullable=True
            )
        )

    # Carrinhos que já existiam nascem marcados: ninguém deve receber um
    # lembrete sobre um carrinho esquecido há meses no primeiro deploy.
    op.execute(
        """
        UPDATE "order"
           SET abandoned_reminder_at = created_at
         WHERE abandoned_reminder_at IS NULL
        """
    )


def downgrade():
    with op.batch_alter_table("order") as batch_op:
        batch_op.drop_column("abandoned_reminder_at")
