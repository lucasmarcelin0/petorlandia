"""expand medicamento text fields"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2f9a0dc93f25'
down_revision = 'b1db1e768d50'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'medicamento',
        'dosagem_recomendada',
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'medicamento',
        'frequencia',
        existing_type=sa.String(length=50),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'medicamento',
        'duracao_tratamento',
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'medicamento',
        'duracao_tratamento',
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        'medicamento',
        'frequencia',
        existing_type=sa.Text(),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        'medicamento',
        'dosagem_recomendada',
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
