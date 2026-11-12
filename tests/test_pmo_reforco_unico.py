from datetime import date
from types import SimpleNamespace

from extensions import db
from models import Animal, Vacina, User
from services.pmo_reforcos import OBS, filtrar_reforcos_automaticos
from services import vacina_pmo_service


def test_reforco_pmo_mais_distante_preserva_doses_e_agendamento_manual(app, monkeypatch):
    with app.app_context():
        tutor = User(name="Tutor", email="teste-reforco@example.com")
        tutor.set_password("senha")
        db.session.add(tutor)
        db.session.flush()
        animal = Animal(name="Nega", user_id=tutor.id)
        db.session.add(animal)
        db.session.flush()
        monkeypatch.setattr(vacina_pmo_service, "_ensure_real_animal", lambda x: None)
        monkeypatch.setattr(vacina_pmo_service, "_campaign_vet_user_id", lambda: None)
        for dia in (date(2026, 11, 10), date(2026, 6, 18), date(2026, 6, 25)):
            item = SimpleNamespace(status="vacinado", animal=animal, animal_id=animal.id,
                                   vaccine_id=None, vaccine=None, visit=SimpleNamespace(vaccine_date=dia))
            vacina_pmo_service._ensure_pmo_vaccine_record(item)
            db.session.flush()
        automaticos = Vacina.query.filter_by(animal_id=animal.id, aplicada=False).all()
        assert len(automaticos) == 1
        assert automaticos[0].aplicada_em == date(2027, 11, 10)
        assert Vacina.query.filter_by(animal_id=animal.id, aplicada=True).count() == 3
        antigo = Vacina(animal_id=animal.id, nome=automaticos[0].nome, tipo=automaticos[0].tipo,
                        observacoes=OBS, aplicada=False, aplicada_em=date(2027, 6, 18))
        manual = Vacina(animal_id=animal.id, nome=automaticos[0].nome, tipo=automaticos[0].tipo,
                        observacoes="Orientação veterinária", aplicada=False, aplicada_em=date(2027, 6, 25))
        db.session.add_all([antigo, manual]); db.session.flush()
        visiveis = filtrar_reforcos_automaticos(Vacina.query.filter_by(animal_id=animal.id, aplicada=False)).all()
        assert {v.id for v in visiveis} == {automaticos[0].id, manual.id}
        assert Vacina.query.filter_by(animal_id=animal.id, aplicada=False).count() == 3


