import json
from types import SimpleNamespace

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
        payloads_t0 = [
            json.loads(resposta.dados_json or "{}")
            for resposta in SfaRespostaT0.query.order_by(SfaRespostaT0.id.asc()).all()
        ]
        assert all("contato_animais" in payload for payload in payloads_t0)
        assert all("consumo_recente" in payload for payload in payloads_t0)
        assert all("atividades_recentes" in payload for payload in payloads_t0)
        animais = {
            item
            for payload in payloads_t0
            for item in payload.get("exposicao_animal", [])
        }
        assert "Caes" in animais
        assert "Gatos" in animais
        assert "Caes ou gatos" not in animais
        assert "Caes ou gatos domesticos" not in animais
        assert any(payload.get("contato_agua_suja") == "Sim" for payload in payloads_t0)
        assert any(payload.get("contato_carrapato_mata") == "Sim" for payload in payloads_t0)

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


def test_paciente_eh_teste_sfa_reconhece_marcadores_antigos():
    assert paciente_eh_teste_sfa(SimpleNamespace(nome="Participante", ficha_sinan="TESTE-123", token_acesso=""))
    assert paciente_eh_teste_sfa(SimpleNamespace(nome="Participante", ficha_sinan="", token_acesso="teste-lote-01"))
    assert paciente_eh_teste_sfa(
        SimpleNamespace(
            nome="Participante",
            ficha_sinan="",
            token_acesso="",
            resposta_t0=SimpleNamespace(dados_json=json.dumps({"_sfa_test_batch": "teste-20260422"})),
            respostas_t10=[],
            respostas_t30=[],
        )
    )
