"""Testes da proteção contra SSRF (Server-Side Request Forgery) em URLs externas."""
from __future__ import annotations

from datetime import date
import app as _app_import  # noqa: F401 - Garante inicialização do app Flask
from extensions import db
from security.url_safe import is_ip_safe, is_url_ssrf_safe


def test_is_ip_safe_bloqueia_ips_privados_e_especiais():
    assert is_ip_safe("127.0.0.1") is False
    assert is_ip_safe("::1") is False
    assert is_ip_safe("169.254.169.254") is False
    assert is_ip_safe("10.0.0.1") is False
    assert is_ip_safe("172.16.0.1") is False
    assert is_ip_safe("192.168.1.1") is False
    assert is_ip_safe("0.0.0.0") is False
    assert is_ip_safe("224.0.0.1") is False
    assert is_ip_safe("invalido") is False


def test_is_ip_safe_aceita_ips_publicos():
    assert is_ip_safe("8.8.8.8") is True
    assert is_ip_safe("1.1.1.1") is True


def test_is_url_ssrf_safe_bloqueia_urls_internas_e_esquemas_invalidos():
    assert is_url_ssrf_safe("http://localhost/secret") is False
    assert is_url_ssrf_safe("http://127.0.0.1:5000/admin") is False
    assert is_url_ssrf_safe("http://169.254.169.254/latest/meta-data/") is False
    assert is_url_ssrf_safe("http://10.0.0.1/internal") is False
    assert is_url_ssrf_safe("file:///etc/passwd") is False
    assert is_url_ssrf_safe("ftp://example.com/file") is False
    assert is_url_ssrf_safe("gopher://127.0.0.1:70/") is False


def test_is_url_ssrf_safe_aceita_urls_publicas():
    assert is_url_ssrf_safe("https://s3.amazonaws.com/bucket/photo.jpg") is True


def test_vacina_pmo_photo_src_rejeita_ssrf(client):
    from models import Animal, PmoVaccinationAnimal, PmoVaccinationVisit, User

    admin = User(name="Admin", email="admin_ssrf@test.com", role="admin")
    admin.set_password("pass123")
    db.session.add(admin)
    db.session.flush()

    animal = Animal(name="Pet SSRF", user_id=admin.id, image="http://169.254.169.254/latest/meta-data/")
    db.session.add(animal)
    db.session.flush()

    visit = PmoVaccinationVisit(
        spreadsheet_id="plan-1",
        sheet_gid="0",
        sheet_title="29/08/2026",
        shift="Manha",
        source_row=1,
        tutor_name="Tutor",
        address="Rua 1",
        password="pass",
        vaccine_date=date(2026, 8, 29),
    )
    db.session.add(visit)
    db.session.flush()

    pmo_animal = PmoVaccinationAnimal(
        visit=visit,
        animal_id=animal.id,
        position=1,
        name="Pet SSRF",
        species="cao",
        status="pendente",
    )
    db.session.add(pmo_animal)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin.id)

    response = client.get(f"/vacina-pmo/animal/{pmo_animal.id}/photo-src")
    assert response.status_code == 400
