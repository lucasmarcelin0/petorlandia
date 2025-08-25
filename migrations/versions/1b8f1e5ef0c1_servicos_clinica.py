"""servicos clinica

Revision ID: 1b8f1e5ef0c1
Revises: 045745abcdcf
Create Date: 2025-08-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1b8f1e5ef0c1'
down_revision = '045745abcdcf'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'servico_clinica',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('descricao', sa.String(length=120), nullable=False),
        sa.Column('valor', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.add_column('orcamento_item', sa.Column('servico_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        None, 'orcamento_item', 'servico_clinica', ['servico_id'], ['id']
    )


def downgrade():
    op.drop_constraint(None, 'orcamento_item', type_='foreignkey')
    op.drop_column('orcamento_item', 'servico_id')
    op.drop_table('servico_clinica')
