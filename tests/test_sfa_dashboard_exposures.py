import json
from types import SimpleNamespace

from blueprints.sfa import _montar_dashboard_testes_sfa
from extensions import db
from models.sfa import SfaPaciente, SfaRespostaT0, SfaSinanLog
from services.sfa_service import stats_painel


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
