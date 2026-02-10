from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services import nfse_queue
from services.nfse_queue import (
    NfseCancelRules,
    get_nfse_cancel_rules,
    should_emit_async,
    validate_nfse_cancel_request,
)


def test_should_emit_async_matches_normalized_municipio(app):
    app.config["NFSE_ASYNC_MUNICIPIOS"] = ["Belo Horizonte", "Orlândia"]

    with app.app_context():
        assert should_emit_async("Belo Horizonte/MG") is True
        assert should_emit_async("Orlandia") is True
        assert should_emit_async("Campinas") is False


def test_get_nfse_cancel_rules_reads_config(app):
    app.config["NFSE_CANCEL_RULES"] = {
        "orlandia": {
            "deadline_days": 3,
            "require_reason": True,
            "allowed_reasons": [{"code": "1", "label": "Erro"}],
        }
    }

    with app.app_context():
        rules = get_nfse_cancel_rules("Orlândia")

    assert rules == NfseCancelRules(
        deadline_days=3,
        require_reason=True,
        allowed_reasons=[{"code": "1", "label": "Erro"}],
    )


def test_validate_nfse_cancel_request_flags_errors(monkeypatch):
    base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    issue = SimpleNamespace(
        status="cancelamento_solicitado",
        numero_nfse=None,
        data_emissao=base_date,
        created_at=base_date,
    )
    rules = NfseCancelRules(
        deadline_days=2,
        require_reason=True,
        allowed_reasons=[{"code": "A1"}],
    )
    monkeypatch.setattr(nfse_queue, "utcnow", lambda: base_date + timedelta(days=5))

    errors = validate_nfse_cancel_request(
        issue=issue,
        rules=rules,
        reason_code="B2",
        reason_description="",
        substituicao=True,
        substituida_por_nfse="",
    )

    assert "A NFS-e já está em cancelamento/substituição." in errors
    assert "A NFS-e ainda não possui número para cancelamento/substituição." in errors
    assert "O motivo informado não é permitido pelo município." in errors
    assert "Prazo de cancelamento/substituição expirado para este município." in errors
    assert "Informe o número da NFS-e substituta." in errors


def test_validate_nfse_cancel_request_requires_reason():
    issue = SimpleNamespace(
        status="emitida",
        numero_nfse="123",
        data_emissao=None,
        created_at=None,
    )
    rules = NfseCancelRules(
        deadline_days=None,
        require_reason=True,
        allowed_reasons=[],
    )

    errors = validate_nfse_cancel_request(
        issue=issue,
        rules=rules,
        reason_code="",
        reason_description="",
        substituicao=False,
        substituida_por_nfse=None,
    )

    assert errors == ["Informe o motivo exigido pelo município."]
