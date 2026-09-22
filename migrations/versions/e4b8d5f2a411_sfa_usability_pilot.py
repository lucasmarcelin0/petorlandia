"""Pilotos de usabilidade separados da coorte municipal."""
from alembic import op
import sqlalchemy as sa

revision = 'e4b8d5f2a411'
down_revision = '8d9c2e1f4a5b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sfa_pilot_participant',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('label', sa.String(120), nullable=False),
        sa.Column('token', sa.String(64), nullable=False, unique=True),
        sa.Column('creation_key', sa.String(64), nullable=False, unique=True),
        sa.Column('reported_onset', sa.Date()),
        sa.Column('context_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('sfa_pilot_response',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pilot_id', sa.Integer(), sa.ForeignKey('sfa_pilot_participant.id'), nullable=False),
        sa.Column('stage', sa.String(10), nullable=False),
        sa.Column('interview_date', sa.Date(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('pilot_id', 'stage', name='uq_sfa_pilot_response_stage'))
    op.create_index('ix_sfa_pilot_response_pilot_id', 'sfa_pilot_response', ['pilot_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM sfa_pilot_participant')).scalar():
        raise RuntimeError('Existem pilotos cadastrados. Preserve os dados antes de planejar a reversão.')
    op.drop_table('sfa_pilot_response')
    op.drop_table('sfa_pilot_participant')
