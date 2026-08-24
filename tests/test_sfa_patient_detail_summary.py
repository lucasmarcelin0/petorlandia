import json
from decimal import Decimal

from extensions import db
from models.sfa import SfaPaciente, SfaRespostaT0, SfaRespostaT10, SfaRespostaT30


def test_detalhe_resume_respostas_collective_v2_com_indicadores_acionaveis(
    app, client
):
    with app.app_context():
        paciente = SfaPaciente(
            id_estudo="SFA-RESUMO",
            ficha_sinan="12345",
            nome="Pessoa Resumo",
            token_acesso="token-resumo",
        )
        t0 = SfaRespostaT0(
            id_estudo="SFA-RESUMO",
            dias_incap=4,
            custo_total=Decimal("12.50"),
            dados_json=json.dumps(
                {
                    "_instrument_version": "collective-v2",
                    "outras_pessoas_com_sintomas": "Sim",
                    "fonte_ainda_ativa": "Sim",
                    "dias_incap": "4",
                    "custo_total": "12.50",
                }
            ),
        )
        t10 = SfaRespostaT10(
            id_estudo="SFA-RESUMO",
            dias_incap_novos=2,
            custo_outros=Decimal("18.75"),
            dados_json=json.dumps(
                {
                    "_instrument_version": "collective-v2",
                    "classificacao_melhora": "Melhorando",
                    "novos_casos_semelhantes": "Nao",
                    "fonte_ainda_ativa": "Nao sei",
                    "dias_incap_novos": "2",
                    "custo_outros": "18.75",
                }
            ),
        )
        t30 = SfaRespostaT30(
            id_estudo="SFA-RESUMO",
            dias_incap_novos=1,
            custo_outros=Decimal("7.25"),
            dados_json=json.dumps(
                {
                    "_instrument_version": "collective-v2",
                    "estado_saude_final": "Quase recuperado(a) - diferencas minimas",
                    "novos_casos_semelhantes": "Sim",
                    "fonte_ainda_ativa": "Nao",
                    "orientacao_ou_acao_percebida": "Sim",
                    "dias_incap_novos": "1",
                    "custo_outros": "7.25",
                }
            ),
        )
        db.session.add_all([paciente, t0, t10, t30])
        db.session.commit()

    response = client.get("/sfa/paciente/SFA-RESUMO")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Outros doentes" in html
    assert "Fonte ainda ativa" in html
    assert "Dias sem atividades" in html
    assert "Evolucao" in html
    assert "Novos casos semelhantes" in html
    assert "Orientacao ou acao percebida" in html
    assert "Gasto adicional" in html
    assert "R$ 12.50" in html
    assert "R$ 18.75" in html
    assert "R$ 7.25" in html
    assert "Tipo de moradia" not in html
    assert "Previsao retorno" not in html
