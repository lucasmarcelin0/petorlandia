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
            "necessity__nome": "Essencial",
            "redundancy__nome": "Nao parece redundante",
            "clarity__nome": "Clara",
            "comment__nome": "Pergunta clara e necessaria.",
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
        nome = next(question for question in payload["questions"] if question["key"] == "nome")
        assert nome["necessity"] == "Essencial"
        assert nome["comment"] == "Pergunta clara e necessaria."

    response = client.get("/sfa/revisao/resumo")
    assert response.status_code == 200
    assert "Pergunta clara e necessaria.".encode() in response.data


def test_sfa_review_links_and_qrcode_render(client):
    response = client.get("/sfa/revisao/links")
    assert response.status_code == 200
    assert b"/sfa/revisao/t0" in response.data
    assert b"/sfa/revisao/graficos" in response.data

    response = client.get("/sfa/revisao/qrcode/t0.png")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")


def test_sfa_chart_review_records_feedback(app, client):
    response = client.get("/sfa/revisao/graficos")
    assert response.status_code == 200
    assert b"Revisao colaborativa dos graficos" in response.data
    assert b"Resumo visual atual" in response.data
    assert b"Perguntas e campos usados neste bloco" in response.data
    assert b"Sintomas principais no inicio" in response.data

    response = client.post(
        "/sfa/revisao/graficos",
        data={
            "reviewer_name": "Bruno",
            "usefulness__cards_principais": "Util",
            "chart_clarity__cards_principais": "Precisa melhorar",
            "chart_redundancy__cards_principais": "Nao parece redundante",
            "chart_comment__cards_principais": "Explicar melhor a leitura rapida.",
        },
    )
    assert response.status_code == 200

    with app.app_context():
        review = SfaInstrumentReview.query.one()
        payload = json.loads(review.payload_json)
        assert review.kind == "graficos"
        resumo = next(chart for chart in payload["charts"] if chart["key"] == "cards_principais")
        assert resumo["clarity"] == "Precisa melhorar"
        assert resumo["comment"] == "Explicar melhor a leitura rapida."
