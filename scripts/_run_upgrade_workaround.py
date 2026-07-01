"""Temporary workaround: `flask db upgrade` via the Flask CLI currently fails
on Heroku one-off dynos with `AttributeError: module 'petorlandia_app' has no
attribute 'blueprints'` inside app_factory/blueprint_utils, even though the
exact same create_app() call works fine locally and under gunicorn. Calling
create_app() directly here sidesteps whatever Flask-CLI app-discovery quirk
triggers it. Delete this file once the CLI issue is root-caused and fixed.
"""
from app_factory import create_app
from flask_migrate import upgrade

app = create_app()
with app.app_context():
    upgrade()
print("OK: migrations applied")
