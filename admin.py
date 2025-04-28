from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask import redirect, url_for, flash
from flask_login import current_user
from .models import (
    VacinaModelo, Consulta, Veterinario, Clinica, Prescricao, Medicamento, db, User, Animal, Message,
    Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo  # 👈 adicionado aqui
)

from wtforms import SelectField, DateField


from flask_admin.form import ImageUploadField
import os

class MyModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.email == "admin@petorlandia.com"

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login'))

class UserAdminView(MyModelView):
    column_list = (
        'name', 'email', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth',
        'phone', 'address'
    )

    form_overrides = {
        'role': SelectField,
        'date_of_birth': DateField
    }

    form_args = {
        'role': {
            'choices': [(role.name, role.value) for role in UserRole]
        }
    }


class VeterinarioAdmin(ModelView):
    # Use os relacionamentos para que o formulário mostre dropdowns
    form_columns = ['user', 'crmv', 'clinica']
    column_list = ['id', 'user', 'crmv', 'clinica']




class ClinicaAdmin(MyModelView):
    form_extra_fields = {
        'logotipo': ImageUploadField('Logotipo',
            base_path=os.path.join(os.getcwd(), 'static/uploads/clinicas'),
            url_relative_path='uploads/clinicas/',
            allowed_extensions=['jpg', 'png', 'jpeg', 'gif']
        )
    }




def init_admin(app):
    admin = Admin(app, name='Administração PetOrlândia', template_mode='bootstrap4', url='/painel', endpoint='painel_admin')

    admin.add_view(UserAdminView(User, db.session))
    admin.add_view(MyModelView(Animal, db.session))
    admin.add_view(MyModelView(Message, db.session))
    admin.add_view(MyModelView(Transaction, db.session))
    admin.add_view(MyModelView(Medicamento, db.session))
    admin.add_view(MyModelView(Prescricao, db.session))
    admin.add_view(ClinicaAdmin(Clinica, db.session))
    admin.add_view(VeterinarioAdmin(Veterinario, db.session))
    admin.add_view(MyModelView(ExameModelo, db.session))  # 👈 nova entrada
    admin.add_view(MyModelView(Consulta, db.session))
    admin.add_view(ModelView(VacinaModelo, db.session))


class TutorAdminView(ModelView):
    def on_model_delete(self, model):
        # Delete consultations first
        for animal in model.animais:
            for consulta in animal.consultas:
                db.session.delete(consulta)
            db.session.delete(animal)
