from models.sfa import SfaPaciente, SfaRespostaT0, SfaRespostaT10, SfaRespostaT30, SfaSinanLog
from services.sfa_service import (
    apagar_lote_pacientes_teste_sfa,
    filtrar_pacientes_reais_sfa,
    gerar_lote_pacientes_teste_sfa,
    paciente_eh_teste_sfa,
    stats_painel,
)


def test_sfa_test_batch_generation_and_cleanup(app):
    with app.app_context():
        resumo = gerar_lote_pacientes_teste_sfa(20)

        pacientes = SfaPaciente.query.order_by(SfaPaciente.id.asc()).all()
        assert len(pacientes) == 20
        assert all(paciente_eh_teste_sfa(paciente) for paciente in pacientes)
        assert SfaRespostaT0.query.count() == 20
        assert SfaRespostaT10.query.count() == 20
        assert SfaRespostaT30.query.count() == 20
        assert SfaSinanLog.query.count() == 20

        stats = stats_painel()
        assert stats["total"] == 0
        assert filtrar_pacientes_reais_sfa(pacientes) == []

        limpeza = apagar_lote_pacientes_teste_sfa(resumo["batch_id"])
        assert limpeza["removidos"] == 20
        assert SfaPaciente.query.count() == 0
        assert SfaRespostaT0.query.count() == 0
        assert SfaRespostaT10.query.count() == 0
        assert SfaRespostaT30.query.count() == 0
        assert SfaSinanLog.query.count() == 0
