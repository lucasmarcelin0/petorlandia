from datetime import timedelta

from extensions import db
from models import (
    Animal,
    ApresentacaoMedicamento,
    BlocoPrescricao,
    Clinica,
    CuradoriaMedicamentoReview,
    DoseMedicamento,
    Medicamento,
    Prescricao,
    PrescricaoAliasMedicamento,
    User,
)
from services.medicamento_curadoria import gerar_ranking_curadoria, sincronizar_fila_curadoria
from time_utils import now_in_brazil


def _seed_prescription_context():
    clinica = Clinica(nome="Clinica Curadoria")
    vet = User(name="Vet Curadoria", email="vet-curadoria@example.com", role="admin", worker="veterinario")
    tutor = User(name="Tutor Curadoria", email="tutor-curadoria@example.com")
    vet.set_password("x")
    tutor.set_password("x")
    db.session.add_all([clinica, vet, tutor])
    db.session.flush()
    animal = Animal(name="Rex", owner=tutor, clinica=clinica)
    db.session.add(animal)
    db.session.flush()
    bloco = BlocoPrescricao(animal=animal, saved_by=vet, clinica=clinica)
    db.session.add(bloco)
    db.session.flush()
    return vet, animal, bloco


def _add_prescricao(bloco, animal, nome, dosagem="", frequencia="", duracao="", days_ago=0):
    db.session.add(Prescricao(
        bloco_id=bloco.id,
        animal_id=animal.id,
        medicamento=nome,
        dosagem=dosagem,
        frequencia=frequencia,
        duracao=duracao,
        data_prescricao=now_in_brazil() - timedelta(days=days_ago),
    ))


def test_ranking_prioriza_uso_real_e_resolve_alias_cache(app):
    with app.app_context():
        vet, animal, bloco = _seed_prescription_context()
        med = Medicamento(nome="Canex Original", classificacao="Endoparasiticida", created_by=vet.id)
        db.session.add(med)
        db.session.flush()
        db.session.add(PrescricaoAliasMedicamento(
            nome_prescrito="Canex Original - Comprimido (4 un)",
            medicamento_id=med.id,
            confianca="manual",
        ))
        _add_prescricao(bloco, animal, "Canex Original - Comprimido (4 un)", "Dar 2 comprimido", "", "")
        _add_prescricao(bloco, animal, "Canex Original - Comprimido (4 un)", "Dar 1/2 comprimido", "", "")
        _add_prescricao(bloco, animal, "Dipirona", "25 mg/kg", "12/12h", "3 dias", days_ago=10)
        db.session.commit()

        ranking = gerar_ranking_curadoria(db.session, limite=10)

        assert ranking[0].nome_prescrito_principal == "Canex Original - Comprimido (4 un)"
        assert ranking[0].medicamento_id == med.id
        assert ranking[0].confianca_alias == "manual"
        codigos = {p["codigo"] for p in ranking[0].diagnostico["problemas"]}
        assert "SEM_APRESENTACOES" in codigos
        assert "SEM_DOSE_ESTRUTURADA" in codigos
        assert ranking[0].proposta["aplicar_automaticamente"] is False


def test_ranking_detecta_medicamento_sem_alias(app):
    with app.app_context():
        _vet, animal, bloco = _seed_prescription_context()
        _add_prescricao(bloco, animal, "Produto Misterioso", "conforme bula", "conforme bula", "")
        db.session.commit()

        item = gerar_ranking_curadoria(db.session, limite=1)[0]

        assert item.medicamento_id is None
        assert item.confianca_alias == "sem_match"
        codigos = {p["codigo"] for p in item.diagnostico["problemas"]}
        assert "SEM_MEDICAMENTO_CANONICO" in codigos
        assert "HISTORICO_INCOMPLETO" in codigos


def test_sincronizar_fila_dry_run_nao_grava_review(app):
    with app.app_context():
        _vet, animal, bloco = _seed_prescription_context()
        _add_prescricao(bloco, animal, "Dipirona", "25 mg/kg", "12/12h", "3 dias")
        db.session.commit()

        resultado = sincronizar_fila_curadoria(db.session, limite=25, dry_run=True)

        assert resultado["dry_run"] is True
        assert resultado["total_candidatos"] == 1
        assert CuradoriaMedicamentoReview.query.count() == 0


def test_sincronizar_fila_grava_apenas_review_sem_alterar_bulario(app):
    with app.app_context():
        vet, animal, bloco = _seed_prescription_context()
        med = Medicamento(nome="Dipirona", classificacao="Analgesico", created_by=vet.id)
        db.session.add(med)
        db.session.flush()
        db.session.add(ApresentacaoMedicamento(medicamento_id=med.id, forma="Gotas", concentracao="500 mg/mL"))
        db.session.add(DoseMedicamento(medicamento_id=med.id, especie="Caes", dose="25 mg/kg"))
        _add_prescricao(bloco, animal, "Dipirona", "25 mg/kg", "12/12h", "3 dias")
        db.session.commit()

        resultado = sincronizar_fila_curadoria(db.session, limite=25, dry_run=False)

        assert resultado["criados"] == 1
        assert CuradoriaMedicamentoReview.query.count() == 1
        assert Medicamento.query.count() == 1
        assert ApresentacaoMedicamento.query.count() == 1
        assert DoseMedicamento.query.count() == 1


def test_tela_curadoria_admin_renderiza(client, app):
    with app.app_context():
        admin = User(name="Admin Curadoria", email="admin-curadoria@example.com", role="admin")
        admin.set_password("senha")
        db.session.add(admin)
        db.session.commit()

    login = client.post(
        "/login",
        data={"email": "admin-curadoria@example.com", "password": "senha"},
        follow_redirects=True,
    )
    assert login.status_code == 200

    resp = client.get("/bulario/curadoria")

    assert resp.status_code == 200
    assert "Curadoria dos medicamentos mais prescritos".encode("utf-8") in resp.data
