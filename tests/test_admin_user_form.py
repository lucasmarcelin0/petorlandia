from wtforms import SelectField

from admin import USER_ROLE_CHOICES, USER_WORKER_CHOICES, UserAdminView
from extensions import db
from models import User


def test_user_admin_role_and_worker_are_select_fields(app):
    with app.app_context():
        view = UserAdminView(User, db.session)
        form = view.scaffold_form()()

    assert isinstance(form.role, SelectField)
    assert isinstance(form.worker, SelectField)
    assert ('parceiro', 'Parceiro de cadastro') in form.role.choices
    assert ('', 'Sem perfil interno') in form.worker.choices
    assert 'parceiro' not in {value for value, _label in USER_WORKER_CHOICES}


def test_user_admin_normalizes_blank_worker(app):
    with app.app_context():
        view = UserAdminView(User, db.session)
        user = User(name='Tutor', email='tutor-admin-form@example.com', role='parceiro', worker='')

        view.on_model_change(type('Form', (), {'profile_photo_upload': type('Upload', (), {'data': None})()})(), user, False)

    assert user.worker is None
    assert ('parceiro', 'Parceiro de cadastro') in USER_ROLE_CHOICES
