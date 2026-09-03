import json
from types import SimpleNamespace

from blueprints.sfa import _montar_dashboard_testes_sfa
from extensions import db
from models.sfa import SfaPaciente, SfaRespostaT0, SfaSinanLog
from services.sfa_service import montar_resumo_sintomas_sinan, stats_painel


def test_dashboard_testes_expoe_contato_animal_pelas_opcoes_atuais():
    def _paciente(grupo, payload):
        return SimpleNamespace(
            grupo=grupo,
            bairro="Centro",
            data_nascimento="01/01/1990",
            data_t0="20/03/2026",
            data_t10="30/03/2026",
            data_t30="19/04/2026",
            resposta_t0=SimpleNamespace(
                data_inicio_sintomas="18/03/2026",
                dias_incap=3,
                custo_total=42,
                tipo_residencia=payload.get("tipo_residencia", "Casa urbana"),
                dados_json=json.dumps(payload),
            ),
            respostas_t10=[],
            respostas_t30=[],
        )

    dashboard = _montar_dashboard_testes_sfa(
        [
            _paciente(
                "A",
                {
                    "tipo_residencia": "Casa urbana",
                    "contato_animais": ["Caes ou gatos domesticos"],
                    "consumo_recente": ["Nenhum desses"],
                    "atividades_recentes": ["Nenhuma exposicao ambiental"],
                },
            ),
            _paciente(
                "B",
                {
                    "tipo_residencia": "Casa rural",
                    "contato_animais": [
                        "Gado, porcos ou galinhas",
                        "Gatos filhotes ou limpeza de fezes de gato",
                    ],
                    "contato_carrapato_mata": "Sim",
                    "consumo_recente": ["Agua nao tratada (poco, rio, mina)"],
                    "atividades_recentes": ["Trilha, camping ou caca"],
                },
            ),
        ]
    )

    animal_chart = next(chart for chart in dashboard["distributions"] if chart["title"] == "Contato com animais")
    animal_items = {item["label"]: item for item in animal_chart["items"]}

    assert animal_chart["total"] == 2
    assert animal_chart["a_total"] == 1
    assert animal_chart["b_total"] == 1
    assert list(animal_items)[:6] == [
        "Caes",
        "Gatos",
        "Gado/porcos/galinhas",
        "Roedores",
        "Carrapato",
        "Nenhum contato animal relevante",
    ]
    assert animal_items["Caes"]["count"] == 1
    assert animal_items["Gatos"]["count"] == 2
    assert animal_items["Gado/porcos/galinhas"]["count"] == 1
    assert animal_items["Carrapato"]["count"] == 1
    assert "Caes ou gatos domesticos" not in animal_items
    assert "Gatos filhotes ou limpeza de fezes de gato" not in animal_items


def test_stats_painel_filtra_pacientes_por_mes_de_inicio_dos_sintomas(app):
    with app.app_context():
        db.session.add_all(
            [
                SfaPaciente(id_estudo="SFA-MAR", nome="Paciente Marco", grupo="A"),
                SfaPaciente(id_estudo="SFA-ABR", nome="Paciente Abril", grupo="B"),
                SfaPaciente(id_estudo="SFA-SEM-T0", nome="Paciente Sem T0", grupo="A"),
            ]
        )
        db.session.add_all(
            [
                SfaRespostaT0(id_estudo="SFA-MAR", data_inicio_sintomas="18/03/2026"),
                SfaRespostaT0(id_estudo="SFA-ABR", data_inicio_sintomas="02/04/2026"),
                SfaSinanLog(
                    id_estudo_vinculado="SFA-SEM-T0",
                    data_inicio_sintomas="22/03/2026",
                    chave_dedup="sinan-sem-t0",
                ),
            ]
        )
        db.session.commit()

        stats = stats_painel(mes_inicio_sintomas="2026-03")
        stats_sem_filtro = stats_painel()

    assert stats["total"] == 2
    assert stats["grupo_a"] == 2
    assert stats["grupo_b"] == 0
    assert stats_sem_filtro["total"] == 3


def test_resumo_sintomas_sinan_mostra_contagem_percentual_e_pacientes():
    pacientes = [
        SimpleNamespace(
            id_estudo="SFA-101",
            nome="Ana",
            _sinan_dados={
                "revisao_status": "TRANSCRITO",
                "sintomas": ["Febre", "Mialgia", "Febre"],
            },
        ),
        SimpleNamespace(
            id_estudo="SFA-102",
            nome="Bruno",
            _sinan_dados={
                "revisao_status": "REVISAR",
                "sintomas": ["Febre", "Cefaleia"],
            },
        ),
        SimpleNamespace(
            id_estudo="SFA-103",
            nome="Carla",
            _sinan_dados={},
        ),
    ]

    resumo = montar_resumo_sintomas_sinan(pacientes)
    sintomas = {item["label"]: item for item in resumo["items"]}

    assert resumo["total"] == 3
    assert resumo["structured_count"] == 2
    assert resumo["missing_count"] == 1
    assert resumo["patients_with_symptoms"] == 2
    assert resumo["symptoms"] == ["Febre", "Cefaleia", "Mialgia"]
    assert sintomas["Febre"]["count"] == 2
    assert sintomas["Febre"]["percent"] == 67
    assert [patient["id_estudo"] for patient in sintomas["Febre"]["patients"]] == ["SFA-101", "SFA-102"]
    assert resumo["patients"][2]["structured"] is False


def test_dashboard_renderiza_visao_visual_dos_sintomas(app):
    with app.app_context():
        paciente = SfaPaciente(
            id_estudo="SFA-VISUAL",
            nome="Paciente Visual",
            grupo="B",
            status_geral="SINAN_Notificado",
        )
        log = SfaSinanLog(
            id_estudo_vinculado=paciente.id_estudo,
            data_inicio_sintomas="12/08/2026",
            chave_dedup="sinan-visual",
            dados_json=json.dumps({"sintomas": ["Febre", "Dor retroorbital"]}),
            revisao_status="TRANSCRITO",
        )
        db.session.add_all([paciente, log])
        db.session.commit()

        response = app.test_client().get("/sfa/?mes=2026-08")

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Quantos tiveram cada sintoma" in page
    assert "Mapa de sintomas por paciente" in page
    assert "Dor retroorbital" in page
    assert "Paciente Visual" in page
    assert "1 de 1" in page
    assert "100%" in page
