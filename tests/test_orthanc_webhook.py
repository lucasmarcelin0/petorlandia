from datetime import date

from extensions import db
from models import Animal, Clinica, ExameImagem, OrthancStudy, User

TOKEN = "orthanc-test-token"


def _payload(patient_name="Thor", uid="1.2.3.4.5", **overrides):
    payload = {
        "token": TOKEN,
        "event": "stable_study",
        "orthanc_study_id": "abcd-efgh",
        "study": {
            "StudyInstanceUID": uid,
            "StudyDate": "20260713",
            "StudyDescription": "Ultrassonografia Abdominal",
            "AccessionNumber": "ACC-1",
        },
        "patient": {
            "PatientName": patient_name,
            "PatientID": "PID-1",
            "PatientSex": "M",
        },
        "series_count": 3,
    }
    payload.update(overrides)
    return payload


def _setup_animal(name="Thor"):
    clinic = Clinica(nome="Clinica Orthanc")
    tutor = User(name="Tutor Orthanc", email=f"tutor-orthanc-{name.lower()}@example.com", role="adotante")
    tutor.set_password("secret123")
    db.session.add_all([clinic, tutor])
    db.session.flush()
    animal = Animal(name=name, user_id=tutor.id, clinica_id=clinic.id)
    db.session.add(animal)
    db.session.commit()
    return animal


def test_orthanc_webhook_disabled_without_token_config(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = None

    response = client.post("/api/integrations/orthanc/webhook", json=_payload())

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "orthanc_webhook_disabled"


def test_orthanc_webhook_rejects_invalid_token(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = TOKEN

    response = client.post(
        "/api/integrations/orthanc/webhook",
        json=_payload(token="wrong-token"),
    )

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "invalid_orthanc_token"


def test_orthanc_webhook_requires_study_uid(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = TOKEN

    response = client.post(
        "/api/integrations/orthanc/webhook",
        json=_payload(study={"StudyDate": "20260713"}),
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "missing_study_uid"


def test_orthanc_webhook_matches_animal_and_creates_exam_draft(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = TOKEN
    with app.app_context():
        animal = _setup_animal("Thor")
        animal_id = animal.id
        tutor_id = animal.user_id
        clinic_id = animal.clinica_id

    response = client.post("/api/integrations/orthanc/webhook", json=_payload("Thor"))

    assert response.status_code == 201
    data = response.get_json()["data"]["orthanc_study"]
    assert data["criado_agora"] is True
    assert data["match_status"] == "matched"
    assert data["animal_id"] == animal_id
    assert data["exame_imagem_id"]

    with app.app_context():
        record = OrthancStudy.query.filter_by(study_instance_uid="1.2.3.4.5").one()
        assert record.patient_name == "Thor"
        assert record.study_date == date(2026, 7, 13)
        assert record.series_count == 3
        assert "orthanc-test-token" not in (record.raw_payload or "")
        exame = db.session.get(ExameImagem, record.exame_imagem_id)
        assert exame.animal_id == animal_id
        assert exame.tutor_id == tutor_id
        assert exame.clinica_requisitante_id == clinic_id
        assert exame.tipo_exame == "Ultrassonografia Abdominal"
        assert exame.status == "rascunho"
        assert "1.2.3.4.5" in exame.descricao


def test_orthanc_webhook_is_idempotent_per_study_uid(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = TOKEN
    with app.app_context():
        _setup_animal("Thor")

    first = client.post("/api/integrations/orthanc/webhook", json=_payload("Thor"))
    second = client.post("/api/integrations/orthanc/webhook", json=_payload("Thor"))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["data"]["orthanc_study"]["criado_agora"] is False
    with app.app_context():
        assert OrthancStudy.query.count() == 1
        assert ExameImagem.query.count() == 1


def test_orthanc_webhook_records_unmatched_patient_without_exam(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = TOKEN

    response = client.post(
        "/api/integrations/orthanc/webhook",
        json=_payload("Desconhecido", uid="9.8.7.6"),
    )

    assert response.status_code == 201
    data = response.get_json()["data"]["orthanc_study"]
    assert data["match_status"] == "unmatched"
    assert data["animal_id"] is None
    assert data["exame_imagem_id"] is None
    with app.app_context():
        assert ExameImagem.query.count() == 0


def test_orthanc_webhook_does_not_match_ambiguous_patient_name(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = TOKEN
    with app.app_context():
        _setup_animal("Rex")
        clinic = Clinica(nome="Outra Clinica Orthanc")
        tutor = User(name="Outro Tutor", email="outro-tutor-orthanc@example.com", role="adotante")
        tutor.set_password("secret123")
        db.session.add_all([clinic, tutor])
        db.session.flush()
        db.session.add(Animal(name="Rex", user_id=tutor.id, clinica_id=clinic.id))
        db.session.commit()

    response = client.post(
        "/api/integrations/orthanc/webhook",
        json=_payload("Rex", uid="5.5.5.5"),
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["orthanc_study"]["match_status"] == "unmatched"


def test_orthanc_webhook_matches_dicom_caret_separated_name(app, client):
    app.config["ORTHANC_WEBHOOK_TOKEN"] = TOKEN
    with app.app_context():
        animal = _setup_animal("Luna")
        animal_id = animal.id

    response = client.post(
        "/api/integrations/orthanc/webhook",
        json=_payload("LUNA^SILVA", uid="7.7.7.7"),
    )

    assert response.status_code == 201
    data = response.get_json()["data"]["orthanc_study"]
    assert data["match_status"] == "matched"
    assert data["animal_id"] == animal_id
