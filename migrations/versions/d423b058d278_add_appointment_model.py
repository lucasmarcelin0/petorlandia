"""add appointment model

Revision ID: d423b058d278
Revises: b5c3f2d1e0ab, f9730e287995
Create Date: 2025-08-11 13:00:31.631922

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd423b058d278'
down_revision = ('b5c3f2d1e0ab', 'f9730e287995')
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'appointment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('tutor_id', sa.Integer(), nullable=False),
        sa.Column('veterinario_id', sa.Integer(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('consulta_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id']),
        sa.ForeignKeyConstraint(['tutor_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['veterinario_id'], ['veterinario.id']),
        sa.ForeignKeyConstraint(['consulta_id'], ['consulta.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('appointment')
