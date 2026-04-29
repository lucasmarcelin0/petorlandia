from types import SimpleNamespace

from services.bulario import montar_monografia_medicamento


def test_monografia_agrupa_doses_por_especie_e_indicacao():
    med = SimpleNamespace(
        dosagem_recomendada="0,5 - 1 mg/kg",
        frequencia="12/12h",
        duracao_tratamento="7 dias",
        observacoes=None,
        conteudo_estruturado={},
        doses=[
            SimpleNamespace(
                especie="Cães",
                especie_code="CAES",
                faixa_peso="Até 10 kg",
                via="VO",
                dose="0,5 mg/kg",
                frequencia="12/12h",
                duracao="7 dias",
                observacao=None,
                indicacao="Alergia",
            ),
            SimpleNamespace(
                especie="Cães e Gatos",
                especie_code="AMBOS",
                faixa_peso="Uso geral",
                via="VO",
                dose="1 mg/kg",
                frequencia="24/24h",
                duracao="5 dias",
                observacao="Reduzir gradualmente.",
                indicacao="Imunossupressão",
            ),
        ],
    )

    mono = montar_monografia_medicamento(med)

    assert [tab["slug"] for tab in mono["resumo_posologia"]["tabs"]] == ["caes", "gatos"]
    caes = mono["resumo_posologia"]["tabs"][0]
    assert [p["indicacao"] for p in caes["protocolos"]] == ["Alergia", "Imunossupressão"]
    gatos = mono["resumo_posologia"]["tabs"][1]
    assert [p["indicacao"] for p in gatos["protocolos"]] == ["Imunossupressão"]


def test_monografia_estrutura_contraindicacoes_e_interacoes_legadas():
    med = SimpleNamespace(
        dosagem_recomendada=None,
        frequencia=None,
        duracao_tratamento=None,
        doses=[],
        observacoes=(
            "Indicações/Contraindicações:\n"
            "Contraindicado para pacientes com hipersensibilidade; evitar uso em gestantes.\n\n"
            "Interações medicamentosas:\n"
            "Fenobarbital: monitorar resposta clínica e ajustar dose.\n\n"
            "Advertências:\n"
            "Usar com cautela em nefropatas."
        ),
        conteudo_estruturado={},
    )

    mono = montar_monografia_medicamento(med)

    assert mono["secoes"]["contraindicacoes"]["resumo"]
    assert "gestantes" in " ".join(mono["secoes"]["contraindicacoes"]["itens"]).lower()
    assert mono["secoes"]["interacoes"]["itens"][0]["agente"] == "Fenobarbital"
    assert mono["secoes"]["interacoes"]["itens"][0]["conduta"] == "Ajustar dose"


def test_monografia_prefere_json_estruturado_v2_ao_legado():
    med = SimpleNamespace(
        dosagem_recomendada=None,
        frequencia=None,
        duracao_tratamento=None,
        doses=[],
        observacoes=(
            "Indicações/Contraindicações:\n"
            "Texto legado ruim e misturado.\n\n"
            "Interações medicamentosas:\n"
            "Texto corrido sem estrutura."
        ),
        conteudo_estruturado={
            "indicacoes": {"itens": ["Controle da dor"], "texto": "Controle da dor", "resumo": []},
            "contraindicacoes": {"itens": ["Não usar em gestantes"], "texto": "Não usar em gestantes", "resumo": []},
            "advertencias": {"itens": ["Monitorar hidratação"], "texto": "Monitorar hidratação", "resumo": []},
            "efeitos_adversos": {"itens": ["Vômito transitório"], "texto": "Vômito transitório", "resumo": []},
            "interacoes": {
                "itens": [{"agente": "Fenobarbital", "grau": "Moderada", "conduta": "Ajustar dose", "descricao": "Fenobarbital: ajustar dose."}],
                "texto": "Fenobarbital: ajustar dose.",
            },
            "metadata": {"parser_version": "v2", "fonte": "vetsmart"},
        },
    )

    mono = montar_monografia_medicamento(med)

    assert mono["secoes"]["metadata"]["parser_version"] == "v2"
    assert mono["secoes"]["indicacoes"]["itens"] == ["Controle da dor"]
    assert mono["secoes"]["contraindicacoes"]["resumo"] == ["Não usar em gestantes"]
    assert mono["secoes"]["interacoes"]["itens"][0]["agente"] == "Fenobarbital"
