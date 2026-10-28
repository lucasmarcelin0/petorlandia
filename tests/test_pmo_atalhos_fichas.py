"""Atalhos do painel de vacinacao para as fichas do tutor e do animal.

Tocar no nome do tutor abre a ficha dele; a foto ampliada do animal oferece
"Ficha do animal" ao lado de "Da galeria". Os atalhos so aparecem para quem
consegue abrir as fichas: o vacinador sem perfil clinico cairia num 404.
"""

import json
import shutil
import subprocess
import textwrap

import pytest

from extensions import db
from models import Animal, User
from models.pmo import PmoVaccinationAnimal, PmoVaccinationVisit
from tests.test_pmo_doses_do_dia import TEMPLATE, extract_function


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _user(name, email, role):
    user = User(name=name, email=email, role=role)
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    return user


def _visit(**extra):
    visit = PmoVaccinationVisit(
        spreadsheet_id="sheet-1",
        sheet_gid="123",
        sheet_title="28/10/2026",
        source_row=2,
        tutor_name="Lavinia",
        password="PMOA1234",
        **extra,
    )
    db.session.add(visit)
    db.session.flush()
    return visit


def test_admin_ve_atalhos_para_as_fichas(app):
    admin = _user("PMO Admin", "pmo-fichas-admin@test", "admin")
    client = app.test_client()
    _login(client, admin.id)

    body = client.get("/vacina-pmo").get_data(as_text=True)

    assert "const CAN_OPEN_FICHAS = true;" in body
    assert '"/ficha_tutor/999999999"' in body
    assert '"/animal/999999999/ficha"' in body
    # O botao fica logo depois de "Da galeria" no visualizador da foto.
    assert body.index('id="pmo-photo-pick"') < body.index('id="pmo-photo-ficha"')
    assert "${renderTutorName(row)}" in body


def test_vacinador_sem_perfil_clinico_nao_ve_atalhos(app):
    vacinador = _user("Vacinador", "pmo-fichas-vac@test", "vacinador")
    client = app.test_client()
    _login(client, vacinador.id)

    response = client.get("/vacina-pmo")

    assert response.status_code == 200
    assert "const CAN_OPEN_FICHAS = false;" in response.get_data(as_text=True)


def test_visita_expoe_tutor_vinculado(app):
    from services.vacina_pmo_service import _serialize_visit

    tutor = _user("Lavinia", "pmo-fichas-tutor@test", "adotante")
    visit = _visit(tutor_user_id=tutor.id)

    assert _serialize_visit(visit)["tutorUserId"] == tutor.id


def test_visita_sem_vinculo_usa_dono_do_animal(app):
    from services.vacina_pmo_service import _serialize_visit

    tutor = _user("Lavinia", "pmo-fichas-dono@test", "adotante")
    animal = Animal(name="Luna", user_id=tutor.id)
    db.session.add(animal)
    db.session.flush()
    visit = _visit()
    db.session.add(
        PmoVaccinationAnimal(
            visit_id=visit.id, position=1, name="Luna", species="cao", animal_id=animal.id
        )
    )
    db.session.flush()
    db.session.refresh(visit)

    serialized = _serialize_visit(visit)
    assert serialized["tutorUserId"] == tutor.id
    assert serialized["animals"][0]["animalId"] == animal.id


def test_visita_sem_cadastro_nao_tem_ficha(app):
    from services.vacina_pmo_service import _serialize_visit

    assert _serialize_visit(_visit())["tutorUserId"] is None


def _run_links(can_open, row, animal):
    node = shutil.which("node")
    if not node:
        pytest.skip("node nao disponivel neste ambiente")
    source = TEMPLATE.read_text(encoding="utf-8")
    script = textwrap.dedent(
        f"""
        const CAN_OPEN_FICHAS = {json.dumps(can_open)};
        const FICHA_ID_PLACEHOLDER = '999999999';
        const FICHA_TUTOR_URL = '/ficha_tutor/999999999';
        const FICHA_ANIMAL_URL = '/animal/999999999/ficha';
        """
    )
    script += "\n".join(
        extract_function(source, name)
        for name in ("escapeHtml", "fichaTutorUrl", "fichaAnimalUrl", "renderTutorName")
    )
    script += (
        f"\nconst row = {json.dumps(row)}; const animal = {json.dumps(animal)};"
        "\nconsole.log(JSON.stringify({tutor: renderTutorName(row), animal: fichaAnimalUrl(animal)}));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_nome_do_tutor_vira_link_para_a_ficha():
    out = _run_links(True, {"tutor": "Lavínia <b>", "tutorUserId": 42}, {"animalId": 7})
    assert 'href="/ficha_tutor/42"' in out["tutor"]
    assert 'target="_blank"' in out["tutor"]
    assert "Lavínia &lt;b&gt;" in out["tutor"]
    assert out["animal"] == "/animal/7/ficha"


def test_sem_cadastro_ou_sem_permissao_fica_texto_simples():
    sem_cadastro = _run_links(True, {"tutor": "Ana", "tutorUserId": None}, {"animalId": None})
    assert sem_cadastro == {"tutor": "Ana", "animal": ""}
    sem_permissao = _run_links(False, {"tutor": "Ana", "tutorUserId": 3}, {"animalId": 9})
    assert sem_permissao == {"tutor": "Ana", "animal": ""}
