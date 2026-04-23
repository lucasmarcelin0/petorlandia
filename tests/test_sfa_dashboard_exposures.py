import json
from types import SimpleNamespace

from blueprints.sfa import _montar_dashboard_testes_sfa


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
