"""normalize pit bull and srd breeds

Revision ID: fde8a1c4b9d2
Revises: fdd4c2a9b8e1
Create Date: 2026-07-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import unicodedata


revision = 'fde8a1c4b9d2'
down_revision = 'fdd4c2a9b8e1'
branch_labels = None
depends_on = None


def _key(value):
    raw = (value or "").strip()
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(normalized.lower().replace("-", " ").replace("(", " ").replace(")", " ").split())


def _is_srd(value):
    token = _key(value)
    return token in {
        "srd",
        "sem raca definida",
        "srd sem raca definida",
        "vira lata",
        "viralata",
        "mestico",
    }


def _ensure_breed(conn, species_id, name):
    row = conn.execute(
        sa.text("SELECT id FROM breed WHERE species_id = :species_id AND lower(name) = lower(:name) ORDER BY id LIMIT 1"),
        {"species_id": species_id, "name": name},
    ).fetchone()
    if row:
        return row[0]
    result = conn.execute(
        sa.text("INSERT INTO breed (name, species_id) VALUES (:name, :species_id)"),
        {"name": name, "species_id": species_id},
    )
    return result.lastrowid


def _merge_breed_ids(conn, src_id, dst_id):
    if src_id == dst_id:
        return
    conn.execute(sa.text("UPDATE animal SET breed_id = :dst WHERE breed_id = :src"), {"dst": dst_id, "src": src_id})
    conn.execute(sa.text("DELETE FROM breed WHERE id = :src"), {"src": src_id})


def upgrade():
    conn = op.get_bind()
    breeds = conn.execute(sa.text("SELECT id, name, species_id FROM breed ORDER BY id")).fetchall()

    # "Pit Bull Terrier" estava sendo usado como guarda-chuva. O cadastro
    # correto separa Pit Bull e Bull Terrier.
    pit_rows = [row for row in breeds if _key(row[1]) in {"pit bull terrier", "american pit bull terrier", "pitbull", "pit bull"}]
    for breed_id, _name, species_id in pit_rows:
        pit_id = _ensure_breed(conn, species_id, "Pit Bull")
        conn.execute(sa.text("UPDATE breed SET name = 'Pit Bull' WHERE id = :id"), {"id": pit_id})
        _ensure_breed(conn, species_id, "Bull Terrier")
        _merge_breed_ids(conn, breed_id, pit_id)

    # SRD aparece com vários aliases e até espécies diferentes. Para cadastro
    # operacional, uma opção única é suficiente.
    breeds = conn.execute(sa.text("SELECT id, name, species_id FROM breed ORDER BY id")).fetchall()
    srd_rows = [row for row in breeds if _is_srd(row[1])]
    if srd_rows:
        canonical_id = srd_rows[0][0]
        conn.execute(sa.text("UPDATE breed SET name = 'SRD' WHERE id = :id"), {"id": canonical_id})
        for breed_id, _name, _species_id in srd_rows[1:]:
            _merge_breed_ids(conn, breed_id, canonical_id)


def downgrade():
    # Não recriamos aliases duplicados de SRD. O downgrade só preserva dados
    # funcionais, mantendo a lista normalizada.
    pass
