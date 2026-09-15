"""Tests for request-scoped g caching in SiteFlag and SiteText."""

from app_factory import create_app
from extensions import db
from models.site import SiteFlag, SiteText


def test_site_flag_request_scoped_caching():
    app = create_app()
    with app.app_context():
        db.create_all()

        with app.test_request_context():
            # Initially flag does not exist, returns default
            val1 = SiteFlag.get("test_flag", default=False)
            assert val1 is False

            # Set value updates database and cache
            SiteFlag.set("test_flag", True, label="Test Flag")
            val2 = SiteFlag.get("test_flag", default=False)
            assert val2 is True

            # Subsequent reads in same request context hit cache
            val3 = SiteFlag.get("test_flag", default=False)
            assert val3 is True


def test_site_text_request_scoped_caching():
    app = create_app()
    with app.app_context():
        db.create_all()

        with app.test_request_context():
            # Initially text does not exist, returns default
            val1 = SiteText.get("test_text", default="Default Text")
            assert val1 == "Default Text"

            # Set value updates database and cache
            SiteText.set("test_text", "New Value")
            val2 = SiteText.get("test_text", default="Default Text")
            assert val2 == "New Value"

            # Subsequent reads in same request context hit cache
            val3 = SiteText.get("test_text", default="Default Text")
            assert val3 == "New Value"
