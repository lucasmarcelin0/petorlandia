"""add payment and discount fields to bloco_orcamento

Revision ID: 0b6d8a4fdc9b
Revises: d2f5b90edc2e
Create Date: 2025-02-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0b6d8a4fdc9b'
down_revision = 'd2f5b90edc2e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bloco_orcamento', sa.Column('cobranca_tipo', sa.String(length=20), server_default='plano', nullable=False))
    op.add_column('bloco_orcamento', sa.Column('desconto_tipo', sa.String(length=20), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('desconto_percentual', sa.Numeric(5, 2), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('desconto_valor', sa.Numeric(10, 2), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('total_liquido', sa.Numeric(10, 2), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('observacoes_tutor', sa.Text(), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('pagamento_status', sa.String(length=20), server_default='rascunho', nullable=False))
    op.add_column('bloco_orcamento', sa.Column('pagamento_link', sa.String(length=255), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('pagamento_preference_id', sa.String(length=64), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('pagamento_atualizado_em', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('bloco_orcamento', 'pagamento_atualizado_em')
    op.drop_column('bloco_orcamento', 'pagamento_preference_id')
    op.drop_column('bloco_orcamento', 'pagamento_link')
    op.drop_column('bloco_orcamento', 'pagamento_status')
    op.drop_column('bloco_orcamento', 'observacoes_tutor')
    op.drop_column('bloco_orcamento', 'total_liquido')
    op.drop_column('bloco_orcamento', 'desconto_valor')
    op.drop_column('bloco_orcamento', 'desconto_percentual')
    op.drop_column('bloco_orcamento', 'desconto_tipo')
    op.drop_column('bloco_orcamento', 'cobranca_tipo')
