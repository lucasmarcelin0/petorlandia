from alembic import op
import sqlalchemy as sa

revision = 'be9a1dc58c6f'
down_revision = '07c9382e9aad'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS photo_rotation INTEGER')
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS photo_zoom INTEGER')
    op.execute('UPDATE "user" SET photo_rotation = COALESCE(photo_rotation, 0)')
    op.execute('UPDATE "user" SET photo_zoom = COALESCE(photo_zoom, 100)')
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_rotation SET DEFAULT 0')
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_zoom SET DEFAULT 100')
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_rotation SET NOT NULL')
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_zoom SET NOT NULL')

def downgrade():
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_zoom DROP NOT NULL')
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_rotation DROP NOT NULL')
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_zoom DROP DEFAULT')
    op.execute('ALTER TABLE "user" ALTER COLUMN photo_rotation DROP DEFAULT')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS photo_zoom')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS photo_rotation')
