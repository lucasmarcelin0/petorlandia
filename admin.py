from flask_admin import Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuLink
from flask_admin.form import ImageUploadField
from flask import redirect, url_for, flash
from flask_login import current_user, login_required
from wtforms import SelectField, DateField
import os

# --------------------------------------------------------------------------
# Imports dos modelos
# --------------------------------------------------------------------------
try:
    from models import (
        TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario,
        Clinica, Prescricao, Medicamento, db, User, Animal, Message,
        Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo
    )
except ImportError:
    from .models import (
        TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario,
        Clinica, Prescricao, Medicamento, db, User, Animal, Message,
        Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo
    )

# --------------------------------------------------------------------------
# Configurações gerais
# --------------------------------------------------------------------------
ADMIN_EMAIL = "lukemarki3@gmail.com"

def _is_admin():
    return current_user.is_authenticated and current_user.email == ADMIN_EMAIL

# --------------------------------------------------------------------------
# Base para todas as views protegidas
# --------------------------------------------------------------------------
class MyModelView(ModelView):
    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login'))

# --------------------------------------------------------------------------
# Dashboard (será a página inicial do painel)
# --------------------------------------------------------------------------
class AdminDashboard(BaseView):
    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login'))

    @expose('/')
    @login_required
    def index(self):
        total_users = User.query.count()
        total_animals = Animal.query.count()
        total_consultas = Consulta.query.count()

        return self.render(
            'admin/home_admin.html',
            total_users=total_users,
            total_animals=total_animals,
            total_consultas=total_consultas
        )

# --------------------------------------------------------------------------
# Views específicas
# --------------------------------------------------------------------------
class UserAdminView(MyModelView):
    column_list = (
        'name', 'email', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth',
        'phone', 'address', 'clinica', 'added_by'
    )
    column_labels = {'added_by': 'Adicionado por'}
    column_formatters = {
        'added_by': lambda v, c, m, p: m.added_by.name if m.added_by else '—'
    }
    form_overrides = {'role': SelectField, 'date_of_birth': DateField}
    form_args = {'role': {'choices': [(r.name, r.value) for r in UserRole]}}
    form_columns = (
        'name', 'email', 'password_hash', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth', 'phone', 'address', 'clinica'
    )
    column_details_list = column_list

class VeterinarioAdmin(MyModelView):
    form_columns = ['user', 'crmv', 'clinica']
    column_list = ['id', 'user', 'crmv', 'clinica']

class ClinicaAdmin(MyModelView):
    form_extra_fields = {
        'logotipo': ImageUploadField(
            'Logotipo',
            base_path=os.path.join(os.getcwd(), 'static/uploads/clinicas'),
            url_relative_path='uploads/clinicas/',
            allowed_extensions=['jpg', 'jpeg', 'png', 'gif']
        )
    }

class TutorAdminView(MyModelView):
    """Exemplo de deleção em cascata (caso use tutores)."""
    def on_model_delete(self, model):
        for animal in model.animais:
            for consulta in animal.consultas:
                db.session.delete(consulta)
            db.session.delete(animal)

# --------------------------------------------------------------------------
# Função de inicialização do painel
# --------------------------------------------------------------------------
def init_admin(app):
    dashboard_view = AdminDashboard(endpoint='painel_admin')

    admin = Admin(
        app,
        name='Administração PetOrlândia',
        url='/painel',
        endpoint='painel_admin',       # mantém compatibilidade com url_for('painel_admin.index')
        index_view=dashboard_view,     # dashboard é a home
        template_mode=None             # usa templates customizados (master.html)
    )

    # Registro das demais views
    admin.add_view(UserAdminView(User, db.session))
    admin.add_view(MyModelView(Animal, db.session))
    admin.add_view(MyModelView(Message, db.session))
    admin.add_view(MyModelView(Transaction, db.session))
    admin.add_view(MyModelView(Medicamento, db.session))
    admin.add_view(MyModelView(Prescricao, db.session))
    admin.add_view(ClinicaAdmin(Clinica, db.session))
    admin.add_view(VeterinarioAdmin(Veterinario, db.session))
    admin.add_view(MyModelView(ExameModelo, db.session))
    admin.add_view(MyModelView(Consulta, db.session))
    admin.add_view(MyModelView(VacinaModelo, db.session))
    admin.add_view(MyModelView(ApresentacaoMedicamento, db.session))
    admin.add_view(MyModelView(TipoRacao, db.session))

    # Link para voltar ao site principal
    admin.add_link(MenuLink(name='🔙 Voltar ao Site', url='/'))
