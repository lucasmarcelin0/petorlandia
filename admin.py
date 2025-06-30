from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask import redirect, url_for, flash
from flask_login import current_user
try:
    from models import (
    TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario, Clinica, Prescricao, Medicamento, db, User, Animal, Message,
    Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo  # 👈 adicionado aqui
)
except ImportError:
    from .models import (
    TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario, Clinica, Prescricao, Medicamento, db, User, Animal, Message,
    Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo  # 👈 adicionado aqui
)

from wtforms import SelectField, DateField

from flask_admin.menu import MenuLink


from flask_admin.form import ImageUploadField
import os


class MyModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.email == "lukemarki3@gmail.com"

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login'))

    #def scaffold_list_columns(self):
    #    return [c.key for c in self.model.__table__.columns]


class UserAdminView(MyModelView):
    column_list = (
        'name', 'email', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth',
        'phone', 'address', 'clinica',
        'added_by'  # ✅ Certifique-se que está aqui!
    )

    column_labels = {
        'added_by': 'Adicionado por'
    }

    column_formatters = {
        'added_by': lambda v, c, m, p: m.added_by.name if m.added_by else '—'
    }

    form_overrides = {
        'role': SelectField,
        'date_of_birth': DateField
    }

    form_args = {
        'role': {
            'choices': [(role.name, role.value) for role in UserRole]
        }
    }

    form_columns = (
        'name', 'email', 'password_hash', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth', 'phone', 'address',
        'clinica',
        # ⚠️ Não inclua 'added_by' aqui se você não quer que editem manualmente
    )

    # Se quiser mostrar "added_by" também na tela de detalhes:
    column_details_list = column_list






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
    admin.add_view(MyModelView(ApresentacaoMedicamento, db.session))  # 🆕 exibir apresentações
    admin.add_link(MenuLink(name='🏠 Voltar ao Site', url='/'))
    admin.add_view(ModelView(TipoRacao, db.session))


class TutorAdminView(ModelView):
    def on_model_delete(self, model):
        # Delete consultations first
        for animal in model.animais:
            for consulta in animal.consultas:
                db.session.delete(consulta)
            db.session.delete(animal)
