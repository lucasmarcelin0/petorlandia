import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config_utils import normalize_database_uri


def test_normalize_database_uri_encodes_credentials_and_database():
    uri = "postgresql://usuário:sênha@localhost/bancô"

    normalized = normalize_database_uri(uri)

    assert (
        normalized
        == "postgresql://usu%C3%A1rio:s%C3%AAnha@localhost/banc%C3%B4"
    )


def test_normalize_database_uri_accepts_bytes_input():
    uri = "postgresql://usuario:senha@localhost/db".encode("latin-1")

    assert normalize_database_uri(uri) == "postgresql://usuario:senha@localhost/db"
