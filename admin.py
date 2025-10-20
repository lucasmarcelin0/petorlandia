from flask_admin import Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuLink
from flask import redirect, url_for, flash
from flask_login import current_user, login_required
from wtforms import SelectField, DateField, FileField
from markupsafe import Markup
import os
import uuid
from werkzeug.utils import secure_filename
from sqlalchemy import func

def _is_admin():
    """Return True if the current user has the admin role."""
    return current_user.is_authenticated and current_user.role == "admin"






# --------------------------------------------------------------------------
# Imports dos modelos
# --------------------------------------------------------------------------
try:
    from models import (
        Breed, Species, TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario, Specialty,
        Clinica, ClinicHours, VetSchedule, ClinicStaff, Prescricao, Medicamento, db, User, Animal, Message,
        Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo,
        Product, Order, OrderItem, DeliveryRequest, HealthPlan, HealthSubscription, PickupLocation, Endereco, Payment, PaymentMethod, PaymentStatus
    )
except ImportError:
    from .models import (
        Breed, Species, TipoRacao, ApresentacaoMedicamento, VacinaModelo, Consulta, Veterinario, Specialty,
        Clinica, ClinicHours, VetSchedule, ClinicStaff, Prescricao, Medicamento, db, User, Animal, Message,
        Transaction, Review, Favorite, AnimalPhoto, UserRole, ExameModelo,
        Product, Order, OrderItem, DeliveryRequest, HealthPlan, HealthSubscription, PickupLocation, Endereco, Payment, PaymentMethod, PaymentStatus
    )














# --------------------------------------------------------------------------
# Configurações gerais
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Base para todas as views protegidas
# --------------------------------------------------------------------------
class MyModelView(ModelView):
    # Ordena objetos mais recentes primeiro por padrão
    column_default_sort = ('id', True)

    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login_view'))

# --------------------------------------------------------------------------
# Dashboard (será a página inicial do painel)
# --------------------------------------------------------------------------
class AdminDashboard(BaseView):
    def is_accessible(self):
        return _is_admin()

    def inaccessible_callback(self, name, **kwargs):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('login_view'))

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
            total_consultas=total_consultas,
            total_orders = Order.query.count(),
            completed_orders = Order.query.join(DeliveryRequest).filter(DeliveryRequest.status == 'concluida').count(),
            pending_deliveries = DeliveryRequest.query.filter_by(status='pendente').count(),
            total_products = Product.query.count(),
            low_stock_products = Product.query.filter(Product.stock < 5).count(),
            total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status == PaymentStatus.COMPLETED).scalar() or 0,
            pending_payments = Payment.query.filter_by(status=PaymentStatus.PENDING).count(),
            active_health_plans = HealthSubscription.query.filter_by(active=True).count(),

        )

# --------------------------------------------------------------------------
# Views específicas
# --------------------------------------------------------------------------

from wtforms import validators



# ─── Subform de Endereco ----------------------------------------------------
class EnderecoInlineForm(ModelView):
    form_columns = ("rua", "numero", "bairro", "cidade", "estado", "cep")
    can_delete   = False
    can_view_details = False
    can_export   = False

# ─── View de PickupLocation -------------------------------------------------
class PickupLocationView(ModelView):
    column_list   = ("id", "nome", "endereco.full", "ativo")
    column_labels = {"endereco.full": "Endereço"}

    form_columns  = ("nome", "ativo", "endereco")



    column_searchable_list = ("nome", "endereco.rua", "endereco.cidade")
    column_filters = ("ativo",)

    form_args = {
        "nome": dict(validators=[validators.DataRequired(), validators.Length(max=120)])
    }

    def is_accessible(self):
        return current_user.is_authenticated and _is_admin()















import re

class UserAdminView(MyModelView):
    form_extra_fields = {
        'profile_photo_upload': FileField('Foto de perfil')
    }

    column_list = (
        'profile_photo', 'name', 'email', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth',
        'phone', 'address', 'clinica', 'added_by', 'created_at'
    )

    column_labels = {'added_by': 'Adicionado por', 'created_at': 'Registrado em'}

    column_searchable_list = ('name', 'email')
    column_filters = ('role', 'created_at', 'clinica')
    column_sortable_list = ('name', 'email', 'created_at')

    column_default_sort = ('created_at', True)

    column_formatters = {
        'name': lambda v, c, m, p: Markup(
            f'<a href="{url_for("ficha_tutor", tutor_id=m.id)}">{m.name}</a>'
        ),
        'phone': lambda v, c, m, p: Markup(
            f'<a href="https://wa.me/55{re.sub("[^0-9]", "", m.phone)}" target="_blank">{m.phone}</a>'
        ) if m.phone else '—',
        'profile_photo': lambda v, c, m, p: Markup(
            f'<img src="{m.profile_photo}" width="100">'
        ) if m.profile_photo else '',
        'added_by': lambda v, c, m, p: m.added_by.name if m.added_by else '—'
    }

    form_overrides = {'role': SelectField, 'date_of_birth': DateField}
    form_args = {'role': {'choices': [(r.name, r.value) for r in UserRole]}}
    form_columns = (
        'name', 'email', 'password_hash', 'role', 'worker',
        'cpf', 'rg', 'date_of_birth', 'phone', 'address', 'clinica', 'profile_photo_upload'
    )
    column_details_list = column_list

    def on_model_change(self, form, model, is_created):
        if form.profile_photo_upload.data:
            file = form.profile_photo_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="profile_photos")
            if image_url:
                model.profile_photo = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.profile_photo:
            form.profile_photo_upload.description = Markup(
                f'<img src="{obj.profile_photo}" alt="Foto atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )




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
    form_columns = ['user', 'crmv', 'clinica', 'specialties']
    column_list = ['id', 'user', 'crmv', 'clinica', 'specialty_list']
    column_labels = {'specialty_list': 'Especialidades'}

class ClinicaAdmin(MyModelView):
    form_extra_fields = {
        'logotipo_upload': FileField('Logotipo')
    }

    form_ajax_refs = {
        'owner': {
            'fields': ('name', 'email')
        }
    }

    form_columns = [
        'nome', 'cnpj', 'endereco', 'telefone', 'email', 'logotipo_upload', 'owner'
    ]

    column_list = ['nome', 'cnpj', 'logotipo', 'owner']

    column_formatters = {
        'logotipo': lambda v, c, m, p: Markup(
            f'<img src="{m.logotipo}" width="100">'
        ) if m.logotipo else ''
    }

    def on_model_change(self, form, model, is_created):
        file = form.logotipo_upload.data
        if file and getattr(file, "filename", ""):
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="clinicas")
            if image_url:
                model.logotipo = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.logotipo:
            form.logotipo_upload.description = Markup(
                f'<img src="{obj.logotipo}" alt="Logotipo atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )


class ClinicHoursAdmin(MyModelView):
    column_list = ['clinica', 'dia_semana', 'hora_abertura', 'hora_fechamento']
    form_columns = ['clinica', 'dia_semana', 'hora_abertura', 'hora_fechamento']


class VetScheduleAdmin(MyModelView):
    column_list = [
        'veterinario',
        'dia_semana',
        'hora_inicio',
        'hora_fim',
        'intervalo_inicio',
        'intervalo_fim',
    ]
    form_columns = [
        'veterinario',
        'dia_semana',
        'hora_inicio',
        'hora_fim',
        'intervalo_inicio',
        'intervalo_fim',
    ]


class ClinicStaffAdmin(MyModelView):
    column_list = (
        'clinic',
        'user',
        'can_manage_clients',
        'can_manage_animals',
        'can_manage_staff',
        'can_manage_schedule',
        'can_manage_inventory',
    )
    form_columns = column_list
    column_labels = {
        'clinic': 'Clínica',
        'user': 'Usuário',
        'can_manage_clients': 'Clientes',
        'can_manage_animals': 'Animais',
        'can_manage_staff': 'Equipe',
        'can_manage_schedule': 'Agenda',
        'can_manage_inventory': 'Estoque',
    }


class TutorAdminView(MyModelView):
    """Exemplo de deleção em cascata (caso use tutores)."""
    def on_model_delete(self, model):
        for animal in model.animais:
            for consulta in animal.consultas:
                db.session.delete(consulta)
            db.session.delete(animal)


from flask import url_for

class AnimalAdminView(MyModelView):
    form_extra_fields = {
        'image_upload': FileField('Imagem')
    }

    column_list = (
        'image', 'name', 'species.name', 'breed.name', 'age', 'peso',
        'date_of_birth', 'sex', 'status', 'clinica', 'date_added',
        'added_by'
    )

    column_labels = {
        'name': 'Nome',
        'species.name': 'Espécie',
        'breed.name': 'Raça',
        'date_of_birth': 'Nascimento',
        'peso': 'Peso (kg)',
        'added_by': 'Criado por',
        'date_added': 'Registrado em'
    }

    form_columns = (
        'name', 'species', 'breed', 'age', 'peso', 'date_of_birth',
        'sex', 'status', 'clinica', 'added_by', 'image_upload'
    )

    def on_model_change(self, form, model, is_created):
        if form.image_upload.data:
            file = form.image_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="animals")
            if image_url:
                model.image = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.image:
            form.image_upload.description = Markup(
                f'<img src="{obj.image}" alt="Imagem atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )


    column_formatters = {
        'image': lambda v, c, m, p: Markup(
            f'<img src="{m.image}" width="100">'
        ) if m.image else '',
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
    column_filters = ('species.name', 'breed.name', 'sex', 'status', 'clinica', 'date_added')

    column_sortable_list = ('name', 'date_added')
    column_default_sort = ('date_added', True)


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



class ProductAdmin(MyModelView):
    form_extra_fields = {
        'image_upload': FileField('Imagem')
    }

    form_columns = ['name', 'description', 'price', 'stock', 'is_active', 'image_upload']

    column_list = ['image_url', 'name', 'price', 'stock', 'is_active']
    column_searchable_list = ('name',)
    column_sortable_list = ('name', 'price', 'stock', 'id')
    column_formatters = {
        'image_url': lambda v, c, m, p: Markup(
            f'<img src="{m.image_url}" width="100">'
        ) if m.image_url else ''
    }

    def on_model_change(self, form, model, is_created):
        if form.image_upload.data:
            file = form.image_upload.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            from app import upload_to_s3
            image_url = upload_to_s3(file, filename, folder="products")
            model.image_url = image_url

    def on_form_prefill(self, form, id):
        obj = self.get_one(id)
        if obj and obj.image_url:
            form.image_upload.description = Markup(
                f'<img src="{obj.image_url}" alt="Imagem atual" '
                f'style="max-height:150px;margin-top:10px;">'
            )

    def on_model_delete(self, model):
        """Remover itens de pedido antes de excluir o produto."""
        for item in list(model.order_items):
            db.session.delete(item)



# --------------------------------------------------------------------------
# Exame Modelo Admin
# --------------------------------------------------------------------------
class ExameModeloAdminView(MyModelView):
    column_searchable_list = ('nome', 'justificativa')
    form_columns = ('nome', 'justificativa')


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
    admin.add_view(AnimalAdminView(
        Animal, db.session,
        name='Animais', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-paw'
    ))

    admin.add_view(SpeciesAdminView(
        Species, db.session,
        name='Espécies', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-dna'
    ))
    admin.add_view(MyModelView(
        Breed, db.session,
        name='Raças', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-dog'
    ))

    admin.add_view(UserAdminView(
        User, db.session,
        name='Usuários', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-users'
    ))
    admin.add_view(MyModelView(
        Message, db.session,
        name='Mensagens', category='Comunicação',
        menu_icon_type='fa', menu_icon_value='fa-envelope'
    ))
    admin.add_view(MyModelView(
        Transaction, db.session,
        name='Transações', category='Financeiro',
        menu_icon_type='fa', menu_icon_value='fa-dollar-sign'
    ))
    admin.add_view(MyModelView(
        Medicamento, db.session,
        name='Medicamentos', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-pills'
    ))
    admin.add_view(MyModelView(
        Prescricao, db.session,
        name='Prescrições', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-file-medical'
    ))
    admin.add_view(ClinicaAdmin(
        Clinica, db.session,
        name='Clínicas', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-hospital'
    ))
    admin.add_view(ClinicHoursAdmin(
        ClinicHours, db.session,
        name='Horários da Clínica', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-clock'
    ))
    admin.add_view(VetScheduleAdmin(
        VetSchedule, db.session,
        name='Agenda do Veterinário', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-calendar'
    ))
    admin.add_view(VeterinarioAdmin(
        Veterinario, db.session,
        name='Veterinários', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-user-md'
    ))
    admin.add_view(ClinicStaffAdmin(
        ClinicStaff, db.session,
        name='Staff da Clínica', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-user-nurse'
    ))
    admin.add_view(MyModelView(
        Specialty, db.session,
        name='Especialidades', category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-stethoscope'
    ))
    admin.add_view(ExameModeloAdminView(
        ExameModelo, db.session,
        name='Exames', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-vials'
    ))
    admin.add_view(MyModelView(
        Consulta, db.session,
        name='Consultas', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-notes-medical'
    ))
    admin.add_view(MyModelView(
        VacinaModelo, db.session,
        name='Vacinas', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-syringe'
    ))
    admin.add_view(MyModelView(
        ApresentacaoMedicamento, db.session,
        name='Apresentações de Medicamento', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-capsules'
    ))
    admin.add_view(MyModelView(
        TipoRacao, db.session,
        name='Tipos de Ração', category='Atendimento',
        menu_icon_type='fa', menu_icon_value='fa-bone'
    ))
    admin.add_view(ProductAdmin(
        Product, db.session,
        name='Produtos', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-box-open'
    ))
    admin.add_view(MyModelView(
        HealthPlan, db.session,
        name='Planos de Saúde', category='Financeiro',
        menu_icon_type='fa', menu_icon_value='fa-heart'
    ))
    admin.add_view(MyModelView(
        HealthSubscription, db.session,
        name='Assinaturas', category='Financeiro',
        menu_icon_type='fa', menu_icon_value='fa-file-contract'
    ))

    admin.add_view(MyModelView(
        Order, db.session,
        name='Pedidos', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-shopping-cart'
    ))
    admin.add_view(MyModelView(
        OrderItem, db.session,
        name='Itens de Pedido', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-list'
    ))
    admin.add_view(MyModelView(
        DeliveryRequest, db.session,
        name='Entregas', category='Loja',
        menu_icon_type='fa', menu_icon_value='fa-truck'
    ))
    # registrar
    admin.add_view(PickupLocationView(
        PickupLocation, db.session,
        name="Pontos de Retirada", category='Cadastros',
        menu_icon_type='fa', menu_icon_value='fa-store'
    ))
    # Link para voltar ao site principal
    admin.add_link(MenuLink(name='🔙 Voltar ao Site', url='/'))
