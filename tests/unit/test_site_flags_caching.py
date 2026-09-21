"""Tests for request-scoped g caching in SiteFlag and SiteText."""

from app_factory import create_app
from extensions import db
from models.site import SiteFlag, SiteText


def test_site_flag_request_scoped_caching():
    app = create_app()
    with app.app_context():
        db.create_all()

    # Request 1: Get, Set, and verify in-request cache
    with app.test_request_context():
        val1 = SiteFlag.get("test_flag", default=False)
        assert val1 is False

        SiteFlag.set("test_flag", True, label="Test Flag")
        val2 = SiteFlag.get("test_flag", default=False)
        assert val2 is True

        val3 = SiteFlag.get("test_flag", default=False)
        assert val3 is True

    # Request 2: New request context gets fresh state
    with app.test_request_context():
        val4 = SiteFlag.get("test_flag", default=False)
        assert val4 is True


def test_site_text_request_scoped_caching():
    app = create_app()
    with app.app_context():
        db.create_all()

    # Request 1: Get, Set, and verify in-request cache
    with app.test_request_context():
        val1 = SiteText.get("test_text", default="Default Text")
        assert val1 == "Default Text"

        SiteText.set("test_text", "New Value")
        val2 = SiteText.get("test_text", default="Default Text")
        assert val2 == "New Value"

        val3 = SiteText.get("test_text", default="Default Text")
        assert val3 == "New Value"

    # Request 2: New request context gets fresh state
    with app.test_request_context():
        val4 = SiteText.get("test_text", default="Default Text")
        assert val4 == "New Value"
