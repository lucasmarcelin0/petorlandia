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
    op.create_foreign_key(
        'fk_bloco_orcamento_clinica_id',
        'bloco_orcamento',
        'clinica',
        ['clinica_id'],
        ['id'],
    )

    conn = op.get_bind()

    # Fill in clinic from related animal when available
    conn.execute(
        sa.text(
            'UPDATE bloco_orcamento bo SET clinica_id = a.clinica_id '
            'FROM animal a WHERE bo.animal_id = a.id'
        )
    )

    # If any rows are still missing a clinic, use an existing one or create a default
    result = conn.execute(sa.text('SELECT id FROM clinica ORDER BY id LIMIT 1')).fetchone()
    if result is None:
        clinic_id = conn.execute(
            sa.text("INSERT INTO clinica (nome) VALUES ('Clinica Padrão') RETURNING id")
        ).scalar()
    else:
        clinic_id = result[0]

    conn.execute(
        sa.text('UPDATE bloco_orcamento SET clinica_id = :clinic_id WHERE clinica_id IS NULL'),
        {'clinic_id': clinic_id},
    )

    op.alter_column('bloco_orcamento', 'clinica_id', nullable=False)

def downgrade():
    op.drop_constraint('fk_bloco_orcamento_clinica_id', 'bloco_orcamento', type_='foreignkey')
    op.drop_column('bloco_orcamento', 'clinica_id')
