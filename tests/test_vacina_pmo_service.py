from services.vacina_pmo_service import parse_vacina_pmo_rows


def test_parse_vacina_pmo_rows_ignores_summaries_and_dates_as_counts():
    rows = [
        [
            "Nome completo do tutor",
            "Endereço",
            "Número da casa",
            "Complemento",
            "Bairro",
            "Telefone",
            "Telefone 2",
            "Quantidade de cachorros para vacinar.",
            "Quantidade de gatos para vacinar",
            "Nome do(s) animal(is)",
            "Observação:",
            "Data Vacina",
            "Cão",
            "Gato",
            "Nome",
            "Column 16",
            "Data",
            "Turno",
        ],
        [
            "Bruno Henrique",
            "Rua 20",
            "1107",
            "Casa 73",
            "Jardim Benini",
            "16992928199",
            "16991134357",
            "1",
            "0",
            "Lunna",
            "Remarcar se ausente",
            "",
            "",
            "",
            "",
            "",
            "28/05/2026",
            "Manhã",
        ],
        ["", "", "", "", "", "", "", "10", "0", "", "", "", "0", "0"],
        ["", "", "", "", "Manhã 14:30 as 17:00", "", "", "", "", "", "", "", "", "", "", "", "28/05/2026", "Perdas"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "Sobras", "", "0"],
    ]

    parsed = parse_vacina_pmo_rows(rows)

    assert len(parsed) == 1
    assert parsed[0]["tutor"] == "Bruno Henrique"
    assert parsed[0]["dogs"] == 1
    assert parsed[0]["cats"] == 0
    assert parsed[0]["date"] == "2026-05-28"
    assert parsed[0]["shift"] == "Manha"
    assert parsed[0]["animals"] == [{"name": "Lunna", "species": "cao", "status": "pendente"}]


def test_parse_vacina_pmo_rows_splits_partial_house_animals():
    rows = [
        [
            "Daiana Maria da Silva",
            "Rua 08",
            "1395",
            "",
            "Jardim boa vista",
            "99169-2393",
            "99308-0634",
            "2",
            "2",
            "Lupy e Luma",
            "",
            "",
            "",
            "",
            "",
            "",
            "28/05/2026",
            "Tarde",
        ],
    ]

    parsed = parse_vacina_pmo_rows(rows)

    assert len(parsed) == 1
    assert parsed[0]["dogs"] == 2
    assert parsed[0]["cats"] == 2
    assert [animal["name"] for animal in parsed[0]["animals"]] == [
        "Lupy",
        "Luma",
        "Gato 1",
        "Gato 2",
    ]
