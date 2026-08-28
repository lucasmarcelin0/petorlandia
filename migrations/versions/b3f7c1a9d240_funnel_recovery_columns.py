"""Ancorar a assinatura na clínica e dar estado às réguas de recuperação.

Três buracos do funil, um schema:

1. ``veterinarian_membership.veterinario_id`` deixa de ser obrigatório e ganha
   ``owner_user_id``/``clinica_id``. A avaliação nascia de um CRMV: quem criava
   a clínica sem ser veterinário ficava com o sistema funcionando e sem
   nenhuma relação comercial — sem trial, sem lembrete, sem win-back.
2. ``order.abandoned_reminder_2_at`` guarda o segundo toque do carrinho. Um
   lembrete só alcança quem estava disponível naquele dia.
3. ``waitlist_lead.status``/``followup_note`` transformam a lista de espera em
   fila de trabalho: sem estado, ninguém sabia quem já tinha sido procurado.

Revision ID: b3f7c1a9d240
Revises: a7f1c2d5b83e
Create Date: 2026-08-25 01:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b3f7c1a9d240"
down_revision = "a7f1c2d5b83e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("veterinarian_membership") as batch_op:
        batch_op.alter_column(
            "veterinario_id", existing_type=sa.Integer(), nullable=True
        )
        batch_op.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("clinica_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_veterinarian_membership_owner_user_id", ["owner_user_id"]
        )
        batch_op.create_index("ix_veterinarian_membership_clinica_id", ["clinica_id"])
        batch_op.create_unique_constraint(
            "uq_veterinarian_membership_owner_user", ["owner_user_id"]
        )
        batch_op.create_foreign_key(
            "fk_veterinarian_membership_owner_user",
            "user",
            ["owner_user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_veterinarian_membership_clinica",
            "clinica",
            ["clinica_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("order") as batch_op:
        batch_op.add_column(
            sa.Column(
                "abandoned_reminder_2_at", sa.DateTime(timezone=True), nullable=True
            )
        )

    with op.batch_alter_table("waitlist_lead") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="novo",
            )
        )
        batch_op.add_column(
            sa.Column("followup_note", sa.String(length=500), nullable=True)
        )
        batch_op.create_index("ix_waitlist_lead_status", ["status"])


def downgrade():
    with op.batch_alter_table("waitlist_lead") as batch_op:
        batch_op.drop_index("ix_waitlist_lead_status")
        batch_op.drop_column("followup_note")
        batch_op.drop_column("status")

    with op.batch_alter_table("order") as batch_op:
        batch_op.drop_column("abandoned_reminder_2_at")

    with op.batch_alter_table("veterinarian_membership") as batch_op:
        batch_op.drop_constraint(
            "fk_veterinarian_membership_clinica", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_veterinarian_membership_owner_user", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "uq_veterinarian_membership_owner_user", type_="unique"
        )
        batch_op.drop_index("ix_veterinarian_membership_clinica_id")
        batch_op.drop_index("ix_veterinarian_membership_owner_user_id")
        batch_op.drop_column("clinica_id")
        batch_op.drop_column("owner_user_id")
        # Assinaturas sem veterinário (criadas por responsável de clínica) não
        # cabem no esquema antigo; a coluna só volta a ser obrigatória depois
        # de removê-las.
        op.execute("DELETE FROM veterinarian_membership WHERE veterinario_id IS NULL")
        batch_op.alter_column(
            "veterinario_id", existing_type=sa.Integer(), nullable=False
        )
