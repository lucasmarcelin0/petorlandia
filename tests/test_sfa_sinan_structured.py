import csv
import io
import json
from types import SimpleNamespace

from extensions import db
from models.sfa import SfaPaciente, SfaSinanLog
from services.sfa_service import (
    anexar_dados_sinan_pacientes,
    gerar_csv_exportacao_analitica,
    importar_fichas_sinan_estruturadas,
    montar_analise_respostas,
)


def _record(**overrides):
    data = {
        "ficha_sinan": "2985999",
        "n_caso": "199",
        "nome": "Participante da Ficha",
        "data_nascimento": "01/01/1990",
        "data_notificacao": "10/08/2026",
        "data_inicio_sintomas": "09/08/2026",
        "tipo_exame": "NS1",
        "resultado": "Negativo",
        "numero_controle": "FC-199",
        "agravo": "Dengue",
        "data_investigacao": "10/08/2026",
        "unidade_notificante": "Unidade teste",
        "idade_anos": 36,
        "sexo": "Feminino",
        "raca_cor": "Parda",
        "zona": "Urbana",
        "sintomas": ["Febre", "Cefaleia"],
        "comorbidades": ["Hipertensao arterial"],
        "ns1_data_coleta": "10/08/2026",
        "ns1_resultado": "Negativo",
        "revisao_status": "TRANSCRITO",
        "cpf": "nao-deve-ser-persistido",
        "cartao_sus": "nao-deve-ser-persistido",
    }
    data.update(overrides)
    return data


def test_importar_ficha_atualiza_existente_cria_nova_e_remove_identificadores(app):
    existing_patient = SfaPaciente(
        id_estudo="SFA-410",
        nome="Participante Existente",
        ficha_sinan="",
        grupo="B",
    )
    existing_log = SfaSinanLog(
        chave_dedup="N-198",
        n_caso="198",
        nome="Participante Existente",
        resultado="negativo",
        grupo="B",
        id_estudo_vinculado="SFA-410",
    )
    db.session.add_all([existing_patient, existing_log])
    db.session.commit()

    summary = importar_fichas_sinan_estruturadas(
        [
            _record(
                ficha_sinan="2985998",
                n_caso="198",
                nome="Participante Existente",
                campos_revisar=["sexo"],
            ),
            _record(),
        ]
    )

    assert summary["criados"] == 1
    assert summary["atualizados"] == 1
    assert summary["revisar"] == 1
    assert SfaPaciente.query.count() == 2
    assert SfaSinanLog.query.count() == 2
    assert existing_patient.ficha_sinan == "2985998"

    new_log = SfaSinanLog.query.filter_by(ficha_sinan="2985999").one()
    payload = json.loads(new_log.dados_json)
    assert payload["sintomas"] == ["Febre", "Cefaleia"]
    assert "cpf" not in payload
    assert "cartao_sus" not in payload
    assert new_log.revisao_status == "TRANSCRITO"


def test_anexo_sinan_alimenta_lista_exportacao_e_analise(app):
    patient = SfaPaciente(
        id_estudo="SFA-420",
        ficha_sinan="2985001",
        nome="Participante Agosto",
        grupo="B",
        status_geral="SINAN_Notificado",
    )
    log = SfaSinanLog(
        chave_dedup="FICHA-2985001",
        ficha_sinan="2985001",
        n_caso="201",
        nome=patient.nome,
        data_notificacao="12/08/2026",
        data_inicio_sintomas="11/08/2026",
        tipo_exame="NS1",
        resultado="Negativo",
        grupo="B",
        id_estudo_vinculado=patient.id_estudo,
        dados_json=json.dumps(
            {
                "numero_controle": "FC-201",
                "sintomas": ["Febre", "Mialgia"],
                "comorbidades": ["Diabetes"],
                "sexo": "Masculino",
                "ns1_resultado": "Negativo",
            }
        ),
        fonte_complementar="ficha_sinan_fotografada",
        revisao_status="TRANSCRITO",
    )
    db.session.add_all([patient, log])
    db.session.commit()

    anexar_dados_sinan_pacientes([patient])

    assert patient._data_inicio_sintomas == "11/08/2026"
    assert patient._sinan_dados["sintomas"] == ["Febre", "Mialgia"]

    exported = list(csv.DictReader(io.StringIO(gerar_csv_exportacao_analitica([patient]))))[0]
    assert exported["sinan__numero_controle"] == "FC-201"
    assert exported["sinan__sintomas"] == "Febre | Mialgia"
    assert exported["sinan__revisao_status"] == "TRANSCRITO"

    analysis = montar_analise_respostas([patient])
    assert analysis["sinan"]["estruturados"] == 1
    assert analysis["missing"]["data_inicio_sintomas"] == 0
    assert analysis["timeline"][0]["inicio_sintomas"] == "11/08/2026"
    symptom_values = dict(
        zip(
            analysis["charts"]["sinan_symptoms"]["labels"],
            analysis["charts"]["sinan_symptoms"]["data"],
        )
    )
    assert symptom_values["Febre"] == 1


def test_telas_identificam_ficha_estruturada_e_exibem_escopo(client, app):
    summary = importar_fichas_sinan_estruturadas([_record()])
    patient_id = summary["itens"][0]["id_estudo"]

    patient_page = client.get(f"/sfa/paciente/{patient_id}")
    assert patient_page.status_code == 200
    assert "Ficha SINAN estruturada" in patient_page.get_data(as_text=True)
    assert "Sinais clínicos" in patient_page.get_data(as_text=True)

    listing = client.get("/sfa/pacientes?mes_inicio_sintomas=2026-08")
    assert listing.status_code == 200
    assert "Ficha clínica" in listing.get_data(as_text=True)
    assert "Transcrito" in listing.get_data(as_text=True)
    assert "09/08/2026" in listing.get_data(as_text=True)

    analysis = client.get("/sfa/analise-respostas?mes_inicio_sintomas=2026-08")
    assert analysis.status_code == 200
    page = analysis.get_data(as_text=True)
    assert "Proposta de escopo do projeto de mestrado" in page
    assert "Variáveis dependentes" in page
    assert "adjudicação independente" in page
