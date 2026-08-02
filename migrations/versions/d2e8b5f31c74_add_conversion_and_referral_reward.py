"""Track trial conversion and pay the referral reward.

A conversão da avaliação em assinatura paga não tinha marcador: não dava para
medir trial→pago nem para creditar quem indicou. ``converted_at`` registra a
primeira cobrança paga; ``conversion_processed_at`` garante que o efeito
colateral (evento de funil + crédito do indicador) rode exatamente uma vez,
fora da transação que gravou a cobrança.

Revision ID: d2e8b5f31c74
Revises: c1d7e4a92b60
Create Date: 2026-08-02 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d2e8b5f31c74"
down_revision = "c1d7e4a92b60"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("veterinarian_membership") as batch_op:
        batch_op.add_column(
            sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "conversion_processed_at", sa.DateTime(timezone=True), nullable=True
            )
        )

    with op.batch_alter_table("referral_signup") as batch_op:
        batch_op.add_column(
            sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True)
        )

    # Quem já pagava antes desta migração não deve disparar evento de
    # conversão retroativo nem gerar crédito de indicação a posteriori.
    op.execute(
        """
        UPDATE veterinarian_membership
           SET converted_at = paid_until,
               conversion_processed_at = paid_until
         WHERE paid_until IS NOT NULL
        """
    )


def downgrade():
    with op.batch_alter_table("referral_signup") as batch_op:
        batch_op.drop_column("rewarded_at")

    with op.batch_alter_table("veterinarian_membership") as batch_op:
        batch_op.drop_column("conversion_processed_at")
        batch_op.drop_column("converted_at")
