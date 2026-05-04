"""Verify schema on Heroku after migration."""
from app import app, db
from sqlalchemy import text

with app.app_context():
    checks = [
        ("consulta.suspeita_clinica", "SELECT column_name FROM information_schema.columns WHERE table_name='consulta' AND column_name='suspeita_clinica'"),
        ("prescricao_alias_medicamento", "SELECT to_regclass('prescricao_alias_medicamento')"),
        ("medicamento_favorito", "SELECT to_regclass('medicamento_favorito')"),
        ("protocolo_clinico", "SELECT to_regclass('protocolo_clinico')"),
        ("alembic head", "SELECT version_num FROM alembic_version"),
    ]
    for label, sql in checks:
        row = db.session.execute(text(sql)).fetchone()
        print(f"{label}: {row[0] if row else 'MISSING'}")
