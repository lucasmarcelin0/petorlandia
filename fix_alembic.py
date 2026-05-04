"""Fix overlapping alembic_version entries on Heroku."""
from app import app, db
from sqlalchemy import text

with app.app_context():
    rows = db.session.execute(text('SELECT version_num FROM alembic_version ORDER BY version_num')).fetchall()
    print('BEFORE:', [r[0] for r in rows])

    # Remove overlapping parent revisions; keep only b8f2e1d3c9a7 (leaf of alias branch)
    to_remove = ('7ddc4b706765', '7eb22b9c3ba9', 'c6c8c78ce463')
    for rev in to_remove:
        result = db.session.execute(
            text('DELETE FROM alembic_version WHERE version_num = :v'),
            {'v': rev}
        )
        if result.rowcount:
            print(f'Deleted: {rev}')

    db.session.commit()

    rows = db.session.execute(text('SELECT version_num FROM alembic_version ORDER BY version_num')).fetchall()
    print('AFTER:', [r[0] for r in rows])
