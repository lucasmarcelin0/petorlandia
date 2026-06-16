import os

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

import flask_login.utils as login_utils

from app import app as flask_app, db
from models import (
    Animal,
    Clinica,
    Consulta,
    Medicamento,
    ProtocoloClinico,
    ProtocoloClinicoExame,
    ProtocoloClinicoMedicamento,
    ProtocoloClinicoRetorno,
    User,
    Veterinario,
)
from models.base import ApresentacaoMedicamento, DoseMedicamento, Species
from services.clinical_plan import BLOCKED, READY, REVIEW, build_clinical_plan


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _fake_vet(vet_user_id, vet_id, clinic_id):
    return type("U", (), {
        "id": vet_user_id,
        "worker": "veterinario",
        "role": "adotante",
        "name": "Vet",
        "is_authenticated": True,
        "veterinario": type("V", (), {
            "id": vet_id,
            "user": type("WU", (), {"name": "Vet"})(),
            "clinica_id": clinic_id,
        })(),
    })()


def _seed_calculable_protocol(*, animal_weight=10.0):
    clinic = Clinica(id=1, nome="Clinica Plano")
    tutor = User(id=1, name="Tutor", email="tutor-plano@test")
    tutor.set_password("x")
    vet_user = User(id=2, name="Vet", email="vet-plano@test", worker="veterinario")
    vet_user.set_password("x")
    vet = Veterinario(id=1, user_id=vet_user.id, crmv="123", clinica_id=clinic.id)
    species = Species(id=1, name="Cachorro")
    animal = Animal(
        id=1,
        name="Luna",
        user_id=tutor.id,
        clinica_id=clinic.id,
        species=species,
        peso=animal_weight,
    )
    consulta = Consulta(
        id=1,
        animal=animal,
        created_by=vet_user.id,
        clinica_id=clinic.id,
        status="in_progress",
    )
    medicamento = Medicamento(
        id=10,
        nome="Cefalexina",
        classificacao="Antibacteriano",
        via_administracao="Oral",
        created_by=vet_user.id,
    )
    apresentacao = ApresentacaoMedicamento(
        id=1,
        medicamento=medicamento,
        forma="Comprimido",
        concentracao="500 mg",
        concentracao_valor=500,
        concentracao_unidade="mg",
        volume_valor=1,
        volume_unidade="un",
    )
    dose = DoseMedicamento(
        id=1,
        medicamento=medicamento,
        especie="Caes",
        especie_code="CAES",
        via="Oral",
        dose="20 - 30 mg/kg",
        dose_min=20,
        dose_max=30,
        dose_unidade="MG_KG",
        frequencia="a cada 12 horas",
        intervalo_horas=12,
        duracao_min_dias=7,
        duracao_max_dias=10,
        indicacao="Antibiotico",
        fonte="TESTE",
        confianca="ALTA",
    )
    protocolo = ProtocoloClinico(
        id=1,
        nome="Mastite / Pseudociese em cadelas",
        suspeita_principal="mastite / pseudociese",
        especie="cao",
        clinica_id=clinic.id,
        created_by=vet_user.id,
        prioridade=1,
        conduta_sugerida="Avaliar mamas, dor, febre e secrecao.",
        orientacoes_tutor="Evitar estimulo mamario e observar piora.",
    )
    protocolo.medicamentos_sugeridos.append(
        ProtocoloClinicoMedicamento(
            id=1,
            medicamento=medicamento,
            nome_medicamento="Cefalexina",
            dosagem_texto="20 a 30 mg/kg",
            frequencia_texto="a cada 12 horas",
            duracao_texto="por 7 a 10 dias",
            indicacao="Antibiotico",
            justificativa="Cobertura antimicrobiana quando indicada.",
            prioridade=1,
        )
    )
    protocolo.exames_sugeridos.append(
        ProtocoloClinicoExame(
            id=1,
            nome="Citologia de secrecao mamaria",
            justificativa="Avaliar inflamacao e bacterias.",
            prioridade=1,
        )
    )
    protocolo.retornos_sugeridos.append(
        ProtocoloClinicoRetorno(
            id=1,
            prazo_min_dias=3,
            prazo_max_dias=5,
            tipo_retorno="reavaliacao",
            objetivo="Reavaliar dor, lactacao e resposta clinica.",
            prioridade=1,
        )
    )
    db.session.add_all([
        clinic,
        tutor,
        vet_user,
        vet,
        species,
        animal,
        consulta,
        medicamento,
        apresentacao,
        dose,
        protocolo,
    ])
    db.session.commit()
    return consulta, protocolo, vet_user, vet, clinic


def test_build_clinical_plan_calculates_medication_and_keeps_sections(app):
    with flask_app.app_context():
        consulta, protocolo, _vet_user, _vet, _clinic = _seed_calculable_protocol(animal_weight=10.0)

        plan = build_clinical_plan(consulta, protocolo, session=db.session)

        assert plan["status"] == READY
        assert plan["summary"]["ready"] == 1
        assert plan["summary"]["exams_total"] == 1
        assert plan["summary"]["returns_total"] == 1
        med = plan["medications"][0]
        assert med["status"] == READY
        assert med["calculation"]["dose_calculada"] == "250 mg"
        assert med["calculation"]["dose_pratica"] == "meio comprimido"
        assert med["calculation"]["posologia_pratica"] == "meio comprimido a cada 12 horas por 7 a 10 dias"
        assert med["draft_prescription"]["medicamento"] == "Cefalexina"
        assert med["draft_prescription"]["dosagem"] == "meio comprimido"
        assert med["draft_prescription"]["frequencia"] == "a cada 12 horas"
        assert med["draft_prescription"]["duracao"] == "por 7 a 10 dias"
        assert med["draft_prescription"]["use_weight_based_dose"] is False
        presentation = med["calculation"]["apresentacao_pratica"]["presentation"]
        assert isinstance(presentation["label"], str)
        assert presentation["label"]
        assert isinstance(med["draft_prescription"]["apresentacao_nome"], str)
        assert "[object Object]" not in med["draft_prescription"]["apresentacao_nome"]
        assert plan["draft_prescriptions"][0]["dosagem"] == "meio comprimido"


def test_build_clinical_plan_formats_half_tablets_for_tutor(app):
    with flask_app.app_context():
        consulta, protocolo, _vet_user, _vet, _clinic = _seed_calculable_protocol(animal_weight=50.0)

        plan = build_clinical_plan(consulta, protocolo, session=db.session)

        med = plan["medications"][0]
        assert med["status"] == READY
        assert med["calculation"]["dose_calculada"] == "1250 mg"
        assert med["calculation"]["dose_pratica"] == "2 comprimidos e meio"
        assert med["calculation"]["posologia_pratica"] == "2 comprimidos e meio a cada 12 horas por 7 a 10 dias"
        assert med["draft_prescription"]["dosagem"] == "2 comprimidos e meio"
        assert "2,5 comprimidos" not in med["draft_prescription"]["texto"]


def test_build_clinical_plan_exposes_presentation_options_for_manual_choice(app):
    with flask_app.app_context():
        consulta, protocolo, _vet_user, _vet, _clinic = _seed_calculable_protocol(animal_weight=5.0)
        medicamento = protocolo.medicamentos_sugeridos[0].medicamento
        db.session.add_all([
            ApresentacaoMedicamento(
                id=2,
                medicamento=medicamento,
                forma="Comprimido sulcado",
                concentracao="50 mg",
                concentracao_valor=50,
                concentracao_unidade="mg",
            ),
            ApresentacaoMedicamento(
                id=3,
                medicamento=medicamento,
                forma="Comprimido sulcado",
                concentracao="100 mg",
                concentracao_valor=100,
                concentracao_unidade="mg",
            ),
            ApresentacaoMedicamento(
                id=4,
                medicamento=medicamento,
                forma="Comprimido",
                concentracao="300 mg",
                concentracao_valor=300,
                concentracao_unidade="mg",
            ),
        ])
        db.session.commit()

        plan = build_clinical_plan(consulta, protocolo, session=db.session)

        med = plan["medications"][0]
        options = med["calculation"]["apresentacao_opcoes"]
        labels = [option["option_label"] for option in options]
        assert len(options) >= 3
        assert any("2 comprimidos e meio" in label and "50 mg" in label for label in labels)
        assert any("meio comprimido" in label and "300 mg" in label for label in labels)
        assert options[0]["dose_text"] == med["draft_prescription"]["dosagem"]
        assert med["calculation"]["apresentacao_opcao_selecionada"] == 0


def test_build_clinical_plan_formats_liquid_dose_in_ml(app):
    with flask_app.app_context():
        consulta, protocolo, _vet_user, _vet, _clinic = _seed_calculable_protocol(animal_weight=10.0)
        apresentacao = protocolo.medicamentos_sugeridos[0].medicamento.apresentacoes[0]
        apresentacao.forma = "Solução oral"
        apresentacao.concentracao = "50 mg/mL"
        apresentacao.concentracao_valor = 50
        apresentacao.concentracao_unidade = "mg/ml"
        db.session.commit()

        plan = build_clinical_plan(consulta, protocolo, session=db.session)

        med = plan["medications"][0]
        assert med["status"] == READY
        assert med["calculation"]["dose_pratica"] == "5 mL"
        assert med["draft_prescription"]["dosagem"] == "5 mL"


def test_build_clinical_plan_resolves_multiple_indications_by_protocol_dose(app):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome="Clinica Meloxicam")
        tutor = User(id=1, name="Tutor", email="tutor-meloxicam@test")
        tutor.set_password("x")
        vet_user = User(id=2, name="Vet", email="vet-meloxicam@test", worker="veterinario")
        vet_user.set_password("x")
        vet = Veterinario(id=1, user_id=vet_user.id, crmv="123", clinica_id=clinic.id)
        species = Species(id=1, name="Cachorro")
        animal = Animal(
            id=1,
            name="Luna",
            user_id=tutor.id,
            clinica_id=clinic.id,
            species=species,
            peso=10,
        )
        consulta = Consulta(
            id=1,
            animal=animal,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status="in_progress",
        )
        medicamento = Medicamento(
            id=20,
            nome="Meloxicam",
            classificacao="Anti-inflamatório",
            via_administracao="Oral",
            created_by=vet_user.id,
        )
        apresentacao = ApresentacaoMedicamento(
            id=20,
            medicamento=medicamento,
            forma="Comprimido",
            concentracao="1 mg",
            concentracao_valor=1,
            concentracao_unidade="mg",
        )
        dose_dor = DoseMedicamento(
            id=20,
            medicamento=medicamento,
            especie="Caes",
            especie_code="CAES",
            via="Oral",
            dose="0,2 mg/kg",
            dose_min=0.2,
            dose_max=0.2,
            dose_unidade="MG_KG",
            intervalo_horas=24,
            duracao_min_dias=3,
            duracao_max_dias=3,
            indicacao="Dor",
            fonte="TESTE",
            confianca="ALTA",
        )
        dose_inflamacao = DoseMedicamento(
            id=21,
            medicamento=medicamento,
            especie="Caes",
            especie_code="CAES",
            via="Oral",
            dose="0,1 mg/kg",
            dose_min=0.1,
            dose_max=0.1,
            dose_unidade="MG_KG",
            intervalo_horas=24,
            duracao_min_dias=5,
            duracao_max_dias=5,
            indicacao="Inflamação",
            fonte="TESTE",
            confianca="ALTA",
        )
        protocolo = ProtocoloClinico(
            id=1,
            nome="Mastite / Pseudociese em cadelas",
            suspeita_principal="mastite / pseudociese",
            especie="cao",
            clinica_id=clinic.id,
            created_by=vet_user.id,
            prioridade=1,
        )
        protocolo.medicamentos_sugeridos.append(
            ProtocoloClinicoMedicamento(
                id=1,
                medicamento=medicamento,
                nome_medicamento="Meloxicam",
                dosagem_texto="0,1 mg/kg",
                frequencia_texto="a cada 24 horas",
                duracao_texto="por 5 dias",
                indicacao="Anti-inflamatório",
                justificativa="Controle de dor e inflamação mamária.",
                prioridade=1,
            )
        )
        db.session.add_all([
            clinic,
            tutor,
            vet_user,
            vet,
            species,
            animal,
            consulta,
            medicamento,
            apresentacao,
            dose_dor,
            dose_inflamacao,
            protocolo,
        ])
        db.session.commit()

        plan = build_clinical_plan(consulta, protocolo, session=db.session)

        med = plan["medications"][0]
        assert med["status"] == READY
        assert med["calculation"]["dose_calculada"] == "1 mg"
        assert med["calculation"]["dose_pratica"] == "1 comprimido"
        assert med["draft_prescription"]["dosagem"] == "1 comprimido"
        assert med["status_label"] == "Pronto para revisar"


def test_build_clinical_plan_blocks_calculation_without_weight(app):
    with flask_app.app_context():
        consulta, protocolo, _vet_user, _vet, _clinic = _seed_calculable_protocol(animal_weight=None)

        plan = build_clinical_plan(consulta, protocolo, session=db.session)

        assert plan["status"] == BLOCKED
        assert plan["summary"]["blocked"] == 1
        med = plan["medications"][0]
        assert med["status"] == BLOCKED
        assert med["status_label"] == "Peso necessario"
        assert med["draft_prescription"]["dosagem"] == "20 a 30 mg/kg"


def test_build_clinical_plan_marks_manual_when_medication_has_no_structured_dose(app):
    with flask_app.app_context():
        consulta, protocolo, _vet_user, _vet, _clinic = _seed_calculable_protocol(animal_weight=10.0)
        medicamento = protocolo.medicamentos_sugeridos[0].medicamento
        medicamento.doses[:] = []
        db.session.commit()

        plan = build_clinical_plan(consulta, protocolo, session=db.session)

        assert plan["status"] == REVIEW
        assert plan["summary"]["manual"] == 1
        med = plan["medications"][0]
        assert med["status"] == "manual"
        assert med["status_label"] == "Sem dose estruturada"
        assert med["draft_prescription"]["dosagem"] == "20 a 30 mg/kg"


def test_clinical_plan_endpoint_returns_calculated_plan(client, monkeypatch):
    with flask_app.app_context():
        consulta, protocolo, vet_user, vet, clinic = _seed_calculable_protocol(animal_weight=10.0)
        consulta_id = consulta.id
        protocolo_id = protocolo.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        clinic_id = clinic.id

    _login(monkeypatch, _fake_vet(vet_user_id, vet_id, clinic_id))

    response = client.post(
        f"/consulta/{consulta_id}/sugestoes_clinicas/plano",
        json={"protocol_id": protocolo_id},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["plan"]["status"] == READY
    assert payload["plan"]["medications"][0]["calculation"]["dose_calculada"] == "250 mg"
