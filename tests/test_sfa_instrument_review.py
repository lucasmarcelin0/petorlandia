import json

from models.sfa import SfaInstrumentReview


def test_sfa_review_form_records_question_feedback(app, client):
    response = client.get("/sfa/revisao/t0")
    assert response.status_code == 200
    assert b"Revisao colaborativa do instrumento" in response.data
    assert b"Necessidade" in response.data
    assert b"Redundancia" in response.data

    response = client.post(
        "/sfa/revisao/t0",
        data={
            "reviewer_name": "Ana Revisora",
            "reviewer_email": "ana@example.com",
            "reviewer_profile": "profissional de saude",
            "necessity__outras_pessoas_com_sintomas": "Essencial",
            "redundancy__outras_pessoas_com_sintomas": "Nao parece redundante",
            "clarity__outras_pessoas_com_sintomas": "Clara",
            "comment__outras_pessoas_com_sintomas": "Pergunta clara e necessaria.",
            "overall_comment": "Formulario objetivo.",
        },
    )
    assert response.status_code == 200
    assert b"Avaliacao enviada" in response.data

    with app.app_context():
        review = SfaInstrumentReview.query.one()
        payload = json.loads(review.payload_json)
        assert review.kind == "t0"
        assert review.reviewer_name == "Ana Revisora"
        assert payload["reviewer"]["overall_comment"] == "Formulario objetivo."
        cluster = next(
            question
            for question in payload["questions"]
            if question["key"] == "outras_pessoas_com_sintomas"
        )
        assert cluster["necessity"] == "Essencial"
        assert cluster["comment"] == "Pergunta clara e necessaria."

    response = client.get("/sfa/revisao/resumo")
    assert response.status_code == 200
    assert "Pergunta clara e necessaria.".encode() in response.data

    response = client.get("/sfa/revisao/resumo?kind=t0")
    assert response.status_code == 200
    assert b"Formulario T0" in response.data
    assert "Pergunta clara e necessaria.".encode() in response.data


def test_sfa_review_links_and_qrcode_render(client):
    response = client.get("/sfa/revisao/links")
    assert response.status_code == 200
    assert b"/sfa/revisao/t0" in response.data
    assert b"/sfa/revisao/graficos" in response.data
    assert b"Ver resumo" in response.data
    assert b"/sfa/revisao/resumo?kind=t0" in response.data
    assert b'id="sfa-instrument-lab"' in response.data
    assert b'id="sfa-lab-form-host"' in response.data
    assert b'id="sfa-lab-funnel"' in response.data
    assert b'id="sfa-lab-kpis"' in response.data
    assert b'id="sfa-lab-ai-review"' in response.data
    assert b'id="sfa-lab-ial"' in response.data
    assert b'id="sfa-lab-ablation-result"' in response.data
    assert b'id="sfa-lab-data-rows"' in response.data
    assert b'id="sfa-lab-decisions"' in response.data
    assert b'id="sfa-lab-question-utility"' in response.data
    assert b"sfa_instrument_lab.css?v=20260824b" in response.data
    assert b"sfa_instrument_lab.js?v=20260824b" in response.data
    assert "nada é gravado e os formulários reais não são alterados".encode() in response.data
    assert "IA assistiva, não diagnóstica".encode() in response.data
    assert b'value="semantic"' in response.data
    assert b'value="falsefriends"' in response.data
    assert b'value="onehealth"' in response.data

    response = client.get("/sfa/revisao/qrcode/t0.png")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")


def test_sfa_chart_review_records_feedback(app, client):
    response = client.get("/sfa/revisao/graficos")
    assert response.status_code == 200
    assert b"Revisao colaborativa dos graficos" in response.data
    assert b"Resumo visual atual" in response.data
    assert b"Perguntas reais usadas neste bloco" in response.data
    assert b"Vinculos coletivos e novas pistas" in response.data
    assert b"Exposicoes One Health" in response.data
    assert b"Houve contato animal" in response.data
    assert b"Caes" in response.data
    assert b"Gatos" in response.data
    assert b"Leite cru/queijo nao pasteurizado" in response.data
    assert b"Sintomas principais no inicio" not in response.data

    response = client.post(
        "/sfa/revisao/graficos",
        data={
            "reviewer_name": "Bruno",
            "usefulness__one_health": "Util",
            "chart_clarity__one_health": "Precisa melhorar",
            "chart_redundancy__one_health": "Nao parece redundante",
            "chart_comment__one_health": "Explicar melhor a leitura rapida.",
            "question_need__one_health__t0__exposicao_animal": "Essencial",
            "question_reuse__one_health__t0__exposicao_animal": "Manter como esta",
            "question_comment__one_health__t0__exposicao_animal": "As especies precisam aparecer.",
        },
    )
    assert response.status_code == 200

    with app.app_context():
        review = SfaInstrumentReview.query.one()
        payload = json.loads(review.payload_json)
        assert review.kind == "graficos"
        exposicoes = next(chart for chart in payload["charts"] if chart["key"] == "one_health")
        assert exposicoes["clarity"] == "Precisa melhorar"
        assert exposicoes["comment"] == "Explicar melhor a leitura rapida."
        animal = next(question for question in exposicoes["questions"] if question["key"] == "exposicao_animal")
        assert animal["graph_need"] == "Essencial"
        assert animal["comment"] == "As especies precisam aparecer."
