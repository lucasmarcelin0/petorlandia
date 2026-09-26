from security.redact import redact_sensitive_text


def test_payment_payload_redaction_masks_cpf_cnpj():
    """Garante que payloads de pagamento do Mercado Pago contendo CPF ou CNPJ são mascarados."""
    sample_payload = {
        "payer": {
            "first_name": "João",
            "last_name": "Silva",
            "email": "joao@exemplo.com",
            "identification": {"type": "CPF", "number": "12345678901"}
        },
        "items": [{"title": "Ração", "unit_price": 50.0}],
    }

    redacted = redact_sensitive_text(str(sample_payload))
    assert "12345678901" not in redacted
    assert "***" in redacted


def test_payment_error_response_redaction():
    """Garante que respostas de erro com dados sensíveis do MP são redatadas antes do log."""
    sample_response = {
        "status": 400,
        "response": {
            "message": "Invalid CPF 123.456.789-00",
            "error": "bad_request"
        }
    }

    redacted = redact_sensitive_text(str(sample_response))
    assert "123.456.789-00" not in redacted
    assert "***" in redacted
