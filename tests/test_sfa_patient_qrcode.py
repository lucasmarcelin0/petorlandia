import qrcode

from extensions import db
from models.sfa import SfaPaciente


class _FakeQrImage:
    def save(self, stream, format=None):
        assert format == "PNG"
        stream.write(b"\x89PNG\r\n\x1a\nqr-test")


def test_qr_operacional_usa_link_nativo_de_cada_etapa(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "1")
    targets = []
    monkeypatch.setattr(
        qrcode,
        "make",
        lambda target: targets.append(target) or _FakeQrImage(),
    )

    with app.app_context():
        paciente = SfaPaciente(
            id_estudo="SFA-QR-001",
            nome="Participante QR",
            token_acesso="token-qr-operacional",
        )
        db.session.add(paciente)
        db.session.commit()

    expected_targets = {
        "t0": "https://localhost/sfa/p/token-qr-operacional",
        "t10": "https://localhost/sfa/p/token-qr-operacional/t10",
        "t30": "https://localhost/sfa/p/token-qr-operacional/t30",
    }
    for stage, expected_target in expected_targets.items():
        response = client.get(f"/sfa/paciente/SFA-QR-001/qrcode/{stage}.png")

        assert response.status_code == 200
        assert response.mimetype == "image/png"
        assert response.data.startswith(b"\x89PNG")
        assert response.headers["Cache-Control"] == "private, no-store"
        assert targets[-1] == expected_target

    generated_before_invalid_request = len(targets)
    response = client.get("/sfa/paciente/SFA-QR-001/qrcode/t99.png")

    assert response.status_code == 404
    assert len(targets) == generated_before_invalid_request
