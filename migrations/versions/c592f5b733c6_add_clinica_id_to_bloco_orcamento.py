"""add clinica_id to bloco_orcamento

Revision ID: c592f5b733c6
Revises: 577a5ea273a3
Create Date: 2025-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c592f5b733c6'
down_revision = '577a5ea273a3'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('bloco_orcamento', sa.Column('clinica_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_bloco_orcamento_clinica_id', 'bloco_orcamento', 'clinica', ['clinica_id'], ['id'])
    op.execute(
        sa.text(
            'UPDATE bloco_orcamento bo SET clinica_id = a.clinica_id FROM animal a WHERE bo.animal_id = a.id'
        )
    )
    op.alter_column('bloco_orcamento', 'clinica_id', nullable=False)

def downgrade():
    op.drop_constraint('fk_bloco_orcamento_clinica_id', 'bloco_orcamento', type_='foreignkey')
    op.drop_column('bloco_orcamento', 'clinica_id')
