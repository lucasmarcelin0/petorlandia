from models import FiscalEmitter
from services.fiscal.nfse_service import _is_nacional_nfse


def test_provider_selection_usa_nfse_nacional_para_bh():
    emitter = FiscalEmitter(
        clinic_id=1,
        cnpj="50721798000139",
        razao_social="RS Servicos Veterinarios",
        municipio_ibge="3106200",
    )

    assert _is_nacional_nfse(emitter, {}) is True
    assert _is_nacional_nfse(emitter, {"municipio_nfse": "Belo Horizonte"}) is True


def test_provider_selection_mantem_betha_fora_de_bh():
    emitter = FiscalEmitter(
        clinic_id=1,
        cnpj="12345678000199",
        razao_social="Clinica Orlandia",
        municipio_ibge="3534302",
    )

    assert _is_nacional_nfse(emitter, {"municipio_nfse": "orlandia"}) is False
