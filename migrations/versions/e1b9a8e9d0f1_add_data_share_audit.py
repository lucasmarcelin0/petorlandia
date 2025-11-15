"""add data share audit"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'e1b9a8e9d0f1'
down_revision = 'd5e2c9a1c3f4'
branch_labels = None
depends_on = None


data_share_party_enum = postgresql.ENUM(
    'clinic', 'veterinarian', 'insurer', name='data_share_party_type', create_type=False
)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        enum_exists = bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = :name)"
            ),
            {"name": data_share_party_enum.name},
        ).scalar()
        if not enum_exists:
            bind.execute(
                sa.text(
                    """
                    CREATE TYPE data_share_party_type AS ENUM (
                        'clinic', 'veterinarian', 'insurer'
                    )
                    """
                )
            )

    op.create_table(
        'data_share_access',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('animal_id', sa.Integer(), sa.ForeignKey('animal.id'), nullable=True),
        sa.Column('source_clinic_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=True),
        sa.Column('granted_to_type', data_share_party_enum, nullable=False),
        sa.Column('granted_to_id', sa.Integer(), nullable=False),
        sa.Column('granted_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('granted_via', sa.String(length=50), nullable=True),
        sa.Column('grant_reason', sa.String(length=255), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('revoke_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_data_share_access_user_id', 'data_share_access', ['user_id'])
    op.create_index('ix_data_share_access_animal_id', 'data_share_access', ['animal_id'])
    op.create_index('ix_data_share_access_source_clinic_id', 'data_share_access', ['source_clinic_id'])

    op.create_table(
        'data_share_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('access_id', sa.Integer(), sa.ForeignKey('data_share_access.id'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=True),
        sa.Column('request_path', sa.String(length=255), nullable=True),
        sa.Column('request_ip', sa.String(length=50), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_data_share_log_access_id', 'data_share_log', ['access_id'])
    op.create_index('ix_data_share_log_actor_id', 'data_share_log', ['actor_id'])
    op.create_index('ix_data_share_log_resource', 'data_share_log', ['resource_type', 'resource_id'])

    inspector = sa.inspect(bind)
    if 'veterinarian_access' in inspector.get_table_names():
        insert_stmt = sa.text(
            """
            INSERT INTO data_share_access (
                user_id,
                animal_id,
                source_clinic_id,
                granted_to_type,
                granted_to_id,
                granted_via,
                created_at,
                updated_at
            )
            SELECT a.user_id,
                   va.animal_id,
                   a.clinica_id,
                   :granted_type,
                   va.vet_id,
                   'legacy',
                   COALESCE(va.date_granted, CURRENT_TIMESTAMP),
                   COALESCE(va.date_granted, CURRENT_TIMESTAMP)
            FROM veterinarian_access va
            JOIN animal a ON a.id = va.animal_id
            """
        )
        bind.execute(insert_stmt, {"granted_type": 'veterinarian'})
        op.drop_table('veterinarian_access')


def downgrade():
    bind = op.get_bind()
    op.drop_index('ix_data_share_log_resource', table_name='data_share_log')
    op.drop_index('ix_data_share_log_actor_id', table_name='data_share_log')
    op.drop_index('ix_data_share_log_access_id', table_name='data_share_log')
    op.drop_table('data_share_log')

    op.drop_index('ix_data_share_access_source_clinic_id', table_name='data_share_access')
    op.drop_index('ix_data_share_access_animal_id', table_name='data_share_access')
    op.drop_index('ix_data_share_access_user_id', table_name='data_share_access')
    op.drop_table('data_share_access')

    if bind.dialect.name != 'sqlite':
        data_share_party_enum.drop(bind, checkfirst=True)
