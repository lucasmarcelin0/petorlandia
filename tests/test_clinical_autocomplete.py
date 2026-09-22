import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

from pathlib import Path
from app import app as flask_app, db, _clinical_suspicion_catalog, _clinical_suspicion_options
from models import ProtocoloClinico, ProtocoloClinicoMedicamento, ProtocoloClinicoExame, Clinica

ROOT = Path(__file__).resolve().parents[1]


def test_clinical_suspicion_catalog_returns_structured_metadata():
    with flask_app.app_context():
        db.create_all()
        try:
            clinic = Clinica(id=99, nome='Clinica Autocomplete')
            db.session.add(clinic)
            db.session.flush()

            proto1 = ProtocoloClinico(
                id=901,
                nome='Erliquiose / Babesiose (hemoparasitose)',
                suspeita_principal='erliquiose',
                especie='cao',
                sinais_gatilho='Febre, apatia, carrapatos.',
                ativo=True,
                clinica_id=None,
            )
            med1 = ProtocoloClinicoMedicamento(
                protocolo=proto1,
                nome_medicamento='Doxiciclina',
                dosagem_texto='10 mg/kg',
                frequencia_texto='a cada 24h',
                duracao_texto='por 28 dias',
            )
            exame1 = ProtocoloClinicoExame(
                protocolo=proto1,
                nome='Hemograma Completo',
                justificativa='Avaliar trombocitopenia e anemia',
            )
            db.session.add_all([proto1, med1, exame1])

            proto2 = ProtocoloClinico(
                id=902,
                nome='Obstrução Urinária Felina',
                suspeita_principal='obstrucao uretral',
                especie='gato',
                sinais_gatilho='Disúria, anúria, dor abdominal.',
                ativo=True,
                clinica_id=clinic.id,
            )
            db.session.add(proto2)
            db.session.commit()

            catalog = _clinical_suspicion_catalog(clinic_id=clinic.id)
            assert isinstance(catalog, list)
            assert len(catalog) >= 2

            erliquiose_item = next((item for item in catalog if item['id'] == 901), None)
            assert erliquiose_item is not None
            assert erliquiose_item['nome'] == 'Erliquiose / Babesiose (hemoparasitose)'
            assert erliquiose_item['suspeita'] == 'erliquiose'
            assert erliquiose_item['especie'] == 'cao'
            assert erliquiose_item['medicamentos_count'] == 1
            assert erliquiose_item['exames_count'] == 1
            assert erliquiose_item['is_clinic_custom'] is False

            obstrucao_item = next((item for item in catalog if item['id'] == 902), None)
            assert obstrucao_item is not None
            assert obstrucao_item['especie'] == 'gato'
            assert obstrucao_item['is_clinic_custom'] is True

            options = _clinical_suspicion_options(clinic_id=clinic.id)
            assert 'erliquiose' in options
            assert 'Erliquiose / Babesiose (hemoparasitose)' in options
        finally:
            db.session.rollback()
            db.drop_all()


def test_clinical_panel_template_has_custom_autocomplete_elements():
    template_path = ROOT / "templates" / "partials" / "clinical_suggestions_panel.html"
    content = template_path.read_text(encoding="utf-8")

    assert 'id="clinical-suspicion-dropdown"' in content
    assert 'clinical-autocomplete-menu' in content
    assert 'id="clinical-suspicion-catalog-data"' in content
    assert 'clinical_suspicion_catalog' in content
    assert "suspicionField.removeAttribute('list')" in content
    assert 'list="clinical-suspicion-options" autocomplete="off" placeholder="Pesquisar suspeita clínica"' not in content
    assert 'form="consulta-form"' in content
    assert 'id="suspeita-clinica"' in content
    assert '.clinical-autocomplete-menu' in content
    assert '.clinical-autocomplete-item' in content
    assert '.clinical-autocomplete-highlight' in content
    assert '.clinical-autocomplete-empty' in content
    assert 'overflow: visible;' in content
