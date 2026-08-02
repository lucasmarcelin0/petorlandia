"""Normalize products sold directly by the PetOrlandia platform.

Revision ID: e5b3c7d9a1f2
Revises: e4a2b7d9c1f6
Create Date: 2026-08-02 21:10:00.000000
"""
from alembic import op


revision = 'e5b3c7d9a1f2'
down_revision = 'e4a2b7d9c1f6'
branch_labels = None
depends_on = None


def upgrade():
    # Estes medicamentos foram cadastrados pelo administrador da plataforma,
    # mas ficaram associados por engano à clínica institucional de id 1.
    # Produto próprio não tem seller parceiro: assim usa a conta Mercado Pago
    # da plataforma e não herda CNPJ/dados fiscais de uma clínica.
    op.execute(
        """
        UPDATE product
           SET clinica_id = NULL
         WHERE id IN (299, 300, 301)
           AND clinica_id = 1
           AND casa_de_racao_id IS NULL
        """
    )


def downgrade():
    # A propriedade comercial pode ter sido alterada depois do upgrade; não
    # restaure automaticamente uma associação incorreta em um rollback.
    pass
