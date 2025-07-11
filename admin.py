from flask_admin import Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.form import ImageUploadField
from flask_admin.menu import MenuLink
from flask import redirect, url_for, flash
from flask_login import current_user
from wtforms import SelectField, DateField
import os

# Modelos
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

# Acesso restrito ao admin
class MyModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.email == "lukemarki3@gmail.com"

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login'))

# Dashboard customizado
class DashboardView(BaseView):
    @expose('/')
    def index(self):
        cards = [
            {
                "title": "Usuários",
                "description": f"Total: {User.query.count()}",
                "icon": "👤",
                "url": url_for('user.index_view')
            },
            {
                "title": "Animais",
                "description": f"Total: {Animal.query.count()}",
                "icon": "🐶",
                "url": url_for('animal.index_view')
            },
            {
                "title": "Clínicas",
                "description": f"Total: {Clinica.query.count()}",
                "icon": "🏥",
                "url": url_for('clinica.index_view')
            },
            {
                "title": "Vacinas",
                "description": f"Hoje: {VacinaModelo.query.count()}",
                "icon": "💉",
                "url": url_for('vacinamodelo.index_view')
            },
            {
                "title": "Consultas",
                "description": f"Pendentes: {Consulta.query.filter_by(status='pendente').count()}",
                "icon": "📋",
                "url": url_for('consulta.index_view')
            },
            {
                "title": "Prescrições",
                "description": f"Total: {Prescricao.query.count()}",
                "icon": "💊",
                "url": url_for('prescricao.index_view')
            },
        ]
        return self.render('admin/admin_dashboard.html', cards=cards)


# Usuários
class UserAdminView(MyModelView):
    column_list = (
        'name', 'email', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth', 'phone',
        'address', 'clinica', 'added_by'
    )
    column_labels = {'added_by': 'Adicionado por'}
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
        'cpf', 'rg', 'date_of_birth', 'phone', 'address', 'clinica'
    )
    column_details_list = column_list

# Veterinários
class VeterinarioAdmin(MyModelView):
    form_columns = ['user', 'crmv', 'clinica']
    column_list = ['id', 'user', 'crmv', 'clinica']

# Clínicas com upload
class ClinicaAdmin(MyModelView):
    form_extra_fields = {
        'logotipo': ImageUploadField(
            'Logotipo',
            base_path=os.path.join(os.getcwd(), 'static/uploads/clinicas'),
            url_relative_path='uploads/clinicas/',
            allowed_extensions=['jpg', 'png', 'jpeg', 'gif']
        )
    }

# Excluir tutor e seus animais
class TutorAdminView(MyModelView):
    def on_model_delete(self, model):
        for animal in model.animais:
            for consulta in animal.consultas:
                db.session.delete(consulta)
            db.session.delete(animal)

# Inicializa o painel admin
def init_admin(app):
    admin = Admin(
        app,
        name='PetOrlândia',
        template_mode='bootstrap4',
        url='/painel'  # ✅ Isso garante que o painel esteja em /painel/
    )

    # Dashboard
    admin.add_view(DashboardView(name="🏠 Início", endpoint='painel_inicio'))

    # Usuários
    admin.add_view(UserAdminView(User, db.session, category="Usuários"))
    admin.add_view(MyModelView(Animal, db.session, category="Usuários"))
    admin.add_view(MyModelView(Message, db.session, category="Usuários"))

    # Atendimento
    admin.add_view(MyModelView(Consulta, db.session, category="Atendimento"))
    admin.add_view(MyModelView(Prescricao, db.session, category="Atendimento"))
    admin.add_view(MyModelView(ExameModelo, db.session, category="Atendimento"))
    admin.add_view(MyModelView(VacinaModelo, db.session, category="Atendimento"))

    # Veterinários
    admin.add_view(ClinicaAdmin(Clinica, db.session, category="Veterinários"))
    admin.add_view(VeterinarioAdmin(Veterinario, db.session, category="Veterinários"))

    # Farmácia e alimentação
    admin.add_view(MyModelView(Medicamento, db.session, category="Farmácia"))
    admin.add_view(MyModelView(ApresentacaoMedicamento, db.session, category="Farmácia"))
    admin.add_view(MyModelView(TipoRacao, db.session, category="Alimentação"))

    # Transações
    admin.add_view(MyModelView(Transaction, db.session, category="Financeiro"))

    # Link de saída
    admin.add_link(MenuLink(name='🔙 Voltar ao Site', url='/', category='Navegação'))



