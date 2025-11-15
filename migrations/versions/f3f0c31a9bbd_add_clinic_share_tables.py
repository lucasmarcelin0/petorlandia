"""add clinic share tables"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import Boolean, DateTime, Integer


# revision identifiers, used by Alembic.
revision = 'f3f0c31a9bbd'
down_revision = 'c49321bb88a2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tutor_clinic_share',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tutor_id', sa.Integer(), nullable=False),
        sa.Column('clinica_id', sa.Integer(), nullable=False),
        sa.Column('granted_by_id', sa.Integer(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by_id', sa.Integer(), nullable=True),
        sa.Column('scope_clinic', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('scope_insurer', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('scope_all', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['tutor_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clinica_id'], ['clinica.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['revoked_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tutor_id', 'clinica_id', name='uq_tutor_clinic_share_tutor_clinic'),
    )
    op.create_index('ix_tutor_clinic_share_tutor_id', 'tutor_clinic_share', ['tutor_id'])
    op.create_index('ix_tutor_clinic_share_clinica_id', 'tutor_clinic_share', ['clinica_id'])

    op.create_table(
        'animal_clinic_share',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('clinica_id', sa.Integer(), nullable=False),
        sa.Column('granted_by_id', sa.Integer(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by_id', sa.Integer(), nullable=True),
        sa.Column('scope_clinic', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('scope_insurer', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('scope_all', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clinica_id'], ['clinica.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['revoked_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('animal_id', 'clinica_id', name='uq_animal_clinic_share_animal_clinic'),
    )
    op.create_index('ix_animal_clinic_share_animal_id', 'animal_clinic_share', ['animal_id'])
    op.create_index('ix_animal_clinic_share_clinica_id', 'animal_clinic_share', ['clinica_id'])

    user_table = table(
        'user',
        column('id', Integer),
        column('clinica_id', Integer),
        column('added_by_id', Integer),
        column('created_at', DateTime),
    )
    animal_table = table(
        'animal',
        column('id', Integer),
        column('clinica_id', Integer),
        column('user_id', Integer),
        column('added_by_id', Integer),
        column('date_added', DateTime),
    )
    tutor_share_table = table(
        'tutor_clinic_share',
        column('tutor_id', Integer),
        column('clinica_id', Integer),
        column('granted_by_id', Integer),
        column('granted_at', DateTime),
        column('scope_clinic', Boolean),
        column('scope_insurer', Boolean),
        column('scope_all', Boolean),
    )
    animal_share_table = table(
        'animal_clinic_share',
        column('animal_id', Integer),
        column('clinica_id', Integer),
        column('granted_by_id', Integer),
        column('granted_at', DateTime),
        column('scope_clinic', Boolean),
        column('scope_insurer', Boolean),
        column('scope_all', Boolean),
    )

    user_select = sa.select(
        user_table.c.id,
        user_table.c.clinica_id,
        user_table.c.added_by_id,
        sa.func.coalesce(user_table.c.created_at, sa.func.now()),
        sa.literal(True),
        sa.literal(False),
        sa.literal(False),
    ).where(user_table.c.clinica_id.isnot(None))
    op.execute(
        tutor_share_table.insert().from_select(
            ['tutor_id', 'clinica_id', 'granted_by_id', 'granted_at', 'scope_clinic', 'scope_insurer', 'scope_all'],
            user_select,
        )
    )

    animal_select = sa.select(
        animal_table.c.id,
        animal_table.c.clinica_id,
        animal_table.c.added_by_id,
        sa.func.coalesce(animal_table.c.date_added, sa.func.now()),
        sa.literal(True),
        sa.literal(False),
        sa.literal(False),
    ).where(animal_table.c.clinica_id.isnot(None))
    op.execute(
        animal_share_table.insert().from_select(
            ['animal_id', 'clinica_id', 'granted_by_id', 'granted_at', 'scope_clinic', 'scope_insurer', 'scope_all'],
            animal_select,
        )
    )


def downgrade():
    op.drop_index('ix_animal_clinic_share_clinica_id', table_name='animal_clinic_share')
    op.drop_index('ix_animal_clinic_share_animal_id', table_name='animal_clinic_share')
    op.drop_table('animal_clinic_share')
    op.drop_index('ix_tutor_clinic_share_clinica_id', table_name='tutor_clinic_share')
    op.drop_index('ix_tutor_clinic_share_tutor_id', table_name='tutor_clinic_share')
    op.drop_table('tutor_clinic_share')
