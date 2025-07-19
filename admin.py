from flask_admin import Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuLink
from flask_admin.form import ImageUploadField
from flask import redirect, url_for, flash
from flask_login import current_user, login_required
from wtforms import SelectField, DateField
import os
import uuid
from werkzeug.utils import secure_filename



# --------------------------------------------------------------------------
# Imports dos modelos
# --------------------------------------------------------------------------
try:
    from models import (
        Breed, Species, TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario,
        Clinica, Prescricao, Medicamento, db, User, Animal, Message,
        Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo,
        Product, Order, OrderItem, DeliveryRequest
    )
except ImportError:
    from .models import (
        Breed, Species, TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario,
        Clinica, Prescricao, Medicamento, db, User, Animal, Message,
        Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo,
        Product, Order, OrderItem, DeliveryRequest
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


import re

class UserAdminView(MyModelView):
    column_list = (
        'name', 'email', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth',
        'phone', 'address', 'clinica', 'added_by'
    )

    column_labels = {'added_by': 'Adicionado por'}

    column_formatters = {
        'name': lambda v, c, m, p: Markup(
            f'<a href="{url_for("ficha_tutor", tutor_id=m.id)}">{m.name}</a>'
        ),
        'phone': lambda v, c, m, p: Markup(
            f'<a href="https://wa.me/55{re.sub(r"\\D", "", m.phone)}" target="_blank">{m.phone}</a>'
        ) if m.phone else '—',
        'added_by': lambda v, c, m, p: m.added_by.name if m.added_by else '—'
    }

    form_overrides = {'role': SelectField, 'date_of_birth': DateField}
    form_args = {'role': {'choices': [(r.name, r.value) for r in UserRole]}}
    form_columns = (
        'name', 'email', 'password_hash', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth', 'phone', 'address', 'clinica'
    )
    column_details_list = column_list




class EnderecoAdmin(MyModelView):
    column_list = ['cep', 'rua', 'numero', 'bairro', 'cidade', 'estado']
    column_searchable_list = ['cep', 'rua', 'bairro', 'cidade']
    column_filters = ['cidade', 'estado']
    form_columns = ['cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado']
    column_labels = {
        'cep': 'CEP',
        'rua': 'Rua',
        'numero': 'Número',
        'complemento': 'Complemento',
        'bairro': 'Bairro',
        'cidade': 'Cidade',
        'estado': 'UF'
    }


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


from markupsafe import Markup
from flask import url_for

class AnimalAdminView(MyModelView):
    column_list = (
        'name', 'species.name', 'breed.name', 'age', 'peso',
        'date_of_birth', 'sex', 'status', 'clinica',
        'added_by'
    )

    column_labels = {
        'name': 'Nome',
        'species.name': 'Espécie',
        'breed.name': 'Raça',
        'date_of_birth': 'Nascimento',
        'peso': 'Peso (kg)',
        'added_by': 'Criado por'
    }

    form_columns = (
        'name', 'species', 'breed', 'age', 'peso', 'date_of_birth',
        'sex', 'status', 'clinica', 'added_by'
    )


    column_formatters = {
        'name': lambda v, c, m, p: Markup(
            f'<a href="{url_for("consulta_direct", animal_id=m.id)}" target="_blank">{m.name}</a>'
        ),
        'status': lambda v, c, m, p: Markup(
            f'<span class="badge bg-{"success" if m.status == "disponível" else "secondary"}">{m.status}</span>'
        ),
        'added_by': lambda v, c, m, p: m.added_by.name if m.added_by else '—'
    }

    # 🔧 Atualizado para apontar para atributos relacionados
    column_searchable_list = ('name', 'breed.name', 'species.name')
    column_filters = ('species.name', 'breed.name', 'sex', 'status', 'clinica')

    column_default_sort = ('name', True)


class SpeciesAdminView(MyModelView):
    form_excluded_columns = ['breeds']
    column_labels = {'name': 'Espécie'}
    column_searchable_list = ['name']
    column_default_sort = ('name', True)


class BreedAdminView(MyModelView):
    form_excluded_columns = ['animals']
    column_labels = {
        'name': 'Raça',
        'species': 'Espécie'
    }
    column_searchable_list = ['name']
    column_filters = ['species']
    column_default_sort = ('name', True)


from wtforms import FileField

class ProductAdmin(MyModelView):
    form_extra_fields = {
        'image_upload': FileField('Imagem')
    }

    form_columns = ['name', 'description', 'price', 'stock', 'image_upload']

    def on_model_change(self, form, model, is_created):
        if form.image_upload.data:
            file = form.image_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="products")
            model.image_url = image_url



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
    admin.add_view(AnimalAdminView(Animal, db.session, name='Animais'))

    admin.add_view(SpeciesAdminView(Species, db.session, name='Espécies'))
    admin.add_view(MyModelView(Breed, db.session, name='Raças'))

    admin.add_view(UserAdminView(User, db.session))
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
    admin.add_view(ProductAdmin(Product, db.session))

    admin.add_view(MyModelView(Order, db.session))
    admin.add_view(MyModelView(OrderItem, db.session))
    admin.add_view(MyModelView(DeliveryRequest, db.session))

    # Link para voltar ao site principal
    admin.add_link(MenuLink(name='🔙 Voltar ao Site', url='/'))
