import os
import sys

# Ensure in-memory DB before importing app
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import routes.app as app
from routes.app import enviar_mensagem_whatsapp

from unittest.mock import Mock

def test_enviar_mensagem_whatsapp(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "sid")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+123")

    messages_create = Mock()
    client_instance = Mock(messages=Mock(create=messages_create))
    client_class = Mock(return_value=client_instance)
    monkeypatch.setattr(app, "Client", client_class)

    enviar_mensagem_whatsapp("ola", "whatsapp:+456")

    client_class.assert_called_once_with("sid", "token")
    messages_create.assert_called_once_with(
        body="ola", from_="whatsapp:+123", to="whatsapp:+456"
    )

