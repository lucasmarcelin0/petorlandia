"""Request-scoped navigation derived from the same helpers used by routes."""
from dataclasses import dataclass

from flask import g, url_for
from flask_login import current_user


@dataclass(frozen=True)
class WorkAction:
    label: str
    url: str
    icon: str


@dataclass(frozen=True)
class Workspace:
    key: str
    label: str
    icon: str
    actions: tuple[WorkAction, ...]


@dataclass(frozen=True)
class Experience:
    workspaces: tuple[Workspace, ...] = ()
    capabilities: frozenset[str] = frozenset()

    @property
    def primary_workspace(self):
        return self.workspaces[0] if self.workspaces else None

    @property
    def visible_nav(self):
        return self.workspaces


def resolve_experience(user, *, active_vet=False, accounting=False, store=None):
    from helpers import active_internship_staff, can_start_consulta

    if not getattr(user, 'is_authenticated', False):
        return Experience()
    role = (getattr(user, 'role', None) or '').lower()
    worker = (getattr(user, 'worker', None) or '').lower()
    admin = role == 'admin'
    internship = active_internship_staff(user)
    capabilities = set()
    areas = []

    def action(label, endpoint, icon, **values):
        return WorkAction(label, url_for(endpoint, **values), icon)

    def area(key, label, icon, *actions):
        areas.append(Workspace(key, label, icon, actions))
        capabilities.add(key)

    if admin:
        area('admin', 'Administração', 'fa-chart-line',
             action('Painel de operação', 'painel_admin.index', 'fa-gauge'),
             action('Alertas', 'admin_notifications', 'fa-bell'),
             action('Funil do produto', 'admin_routes.product_analytics_dashboard', 'fa-chart-line'))
    if active_vet or worker == 'colaborador' or admin:
        area('professional', 'Área profissional', 'fa-stethoscope',
             action('Agenda', 'appointments', 'fa-calendar-check'),
             action('Animais', 'novo_animal', 'fa-paw'),
             action('Tutores', 'tutores', 'fa-users'),
             action('Minha clínica', 'minha_clinica', 'fa-hospital'))
    elif getattr(user, 'clinicas', None):
        area('clinic', 'Minha clínica', 'fa-hospital',
             action('Gerenciar clínica', 'minha_clinica', 'fa-hospital'))
    if store:
        area('store', store.nome, 'fa-store',
             action('Minha loja', 'casa_de_racao_dashboard', 'fa-store', casa_id=store.id),
             action('Produtos', 'casa_de_racao_produtos', 'fa-box-open', casa_id=store.id),
             action('Vendas', 'casa_de_racao_vendas', 'fa-chart-line', casa_id=store.id),
             action('Entregas', 'casa_de_racao_entregas', 'fa-truck', casa_id=store.id))
    if worker == 'delivery' or admin:
        area('delivery', 'Área de Entregas', 'fa-truck',
             action('Solicitações', 'list_delivery_requests', 'fa-truck'))
    if role in {'parceiro', 'admin'}:
        area('partner', 'Área do Parceiro', 'fa-handshake',
             action('Painel do parceiro', 'parceiro_dashboard', 'fa-handshake'),
             action('Cadastrar estabelecimento', 'parceiro_novo_estabelecimento', 'fa-plus'))
    if role in {'vacinador', 'admin'}:
        area('vaccinator', 'Área do Vacinador', 'fa-syringe',
             action('Vacinação', 'vacina_pmo', 'fa-syringe'))
    if internship:
        area('internship', 'Estágio supervisionado', 'fa-user-graduate',
             action('Minha clínica de estágio', 'student_internship_clinic', 'fa-hospital',
                    clinica_id=internship.clinic_id))
    if worker == 'estudante' or role == 'estagiario':
        area('student', 'Estudar', 'fa-graduation-cap',
             action('Biblioteca educacional', 'student_hub', 'fa-book'),
             action('Prática simulada', 'student_practice', 'fa-graduation-cap'))
    if accounting:
        area('accounting', 'Contabilidade', 'fa-chart-line',
             action('Financeiro', 'contabilidade_financeiro', 'fa-chart-line'),
             WorkAction('Pagamentos', '/contabilidade/pagamentos', 'fa-wallet'),
             WorkAction('Obrigações', '/contabilidade/obrigacoes', 'fa-file-invoice'),
             WorkAction('NFS-e', '/contabilidade/nfse', 'fa-receipt'))
    if active_vet:
        capabilities.add('documents')
    if can_start_consulta(user):
        capabilities.add('start_consultation')
    return Experience(tuple(areas), frozenset(capabilities))


def current_experience():
    if 'user_experience' not in g:
        from context_processors import inject_minha_casa_de_racao
        from helpers import _user_can_access_accounting, is_veterinarian

        g.user_experience = resolve_experience(
            current_user,
            active_vet=is_veterinarian(current_user),
            accounting=_user_can_access_accounting(current_user),
            store=inject_minha_casa_de_racao()['minha_casa_de_racao'],
        )
    return g.user_experience


def home_next_actions(user, experience, pets, overdue, appointments):
    """Only query operational data for the workspaces visible to this user."""
    from models import CasaDeRacao, DeliveryRequest, Product, StorePaymentAccount

    actions = []

    def add(label, detail, endpoint, icon, tone='normal', **values):
        actions.append(dict(label=label, detail=detail, url=url_for(endpoint, **values),
                            icon=icon, tone=tone))

    if 'store' in experience.capabilities:
        store = CasaDeRacao.query.filter_by(owner_id=user.id).first()
        if store:
            if not Product.query.filter_by(casa_de_racao_id=store.id).first():
                add('Preparar catálogo', 'Cadastre o primeiro produto com preço e estoque.',
                    'casa_de_racao_produtos', 'fa-box-open', casa_id=store.id)
            elif Product.query.filter_by(casa_de_racao_id=store.id, status='pending').first() and store.status == 'ativa':
                add('Publicar produtos preparados', 'Sua loja foi aprovada. Revise e ative os produtos.',
                    'casa_de_racao_produtos', 'fa-box-open', casa_id=store.id)
            payment = StorePaymentAccount.query.filter_by(casa_de_racao_id=store.id, provider='mercado_pago').first()
            if not payment or payment.status != 'connected':
                add('Configurar recebimentos', 'Conecte sua conta Mercado Pago.',
                    'casa_de_racao_dashboard', 'fa-wallet', casa_id=store.id, _anchor='recebimentos')
            if store.status != 'ativa':
                add('Acompanhar ativação da loja',
                    'Cadastro em análise.' if store.status == 'pendente' else 'Loja suspensa. Consulte a situação do cadastro.',
                    'casa_de_racao_dashboard', 'fa-store', casa_id=store.id)
    if 'delivery' in experience.capabilities and user.worker == 'delivery':
        delivery = (DeliveryRequest.query.filter_by(worker_id=user.id, status='em_andamento', archived=False)
                    .order_by(DeliveryRequest.accepted_at, DeliveryRequest.id).first())
        if delivery:
            add('Continuar entrega', 'Uma entrega aceita aguarda conclusão.',
                'delivery_detail', 'fa-truck', req_id=delivery.id)
        else:
            add('Ver solicitações de entrega', 'Consulte as entregas disponíveis.',
                'list_delivery_requests', 'fa-truck')
    if 'professional' in experience.capabilities:
        add('Atendimentos e retornos', 'Agenda, solicitações e próximos pacientes.',
            'appointments', 'fa-calendar-check')
    if 'accounting' in experience.capabilities:
        add('Revisar recebimentos', 'Pagamentos em aberto e movimento da clínica.',
            'contabilidade_financeiro', 'fa-chart-line')
    if 'partner' in experience.capabilities and user.role == 'parceiro':
        add('Ativar estabelecimentos', 'Acompanhe os cadastros e as pendências das lojas.',
            'parceiro_dashboard', 'fa-handshake')
    for pet in pets:
        if overdue.get(pet.id):
            add(f'Revisar vacinas de {pet.name}', f'{len(overdue[pet.id])} dose(s) com data vencida no cadastro.',
                'ficha_animal', 'fa-syringe', tone='attention', animal_id=pet.id)
    for pet in pets:
        if pet.id in appointments:
            add(f'Próximo atendimento de {pet.name}', 'Confira o agendamento e os detalhes do atendimento.',
                'minhas_solicitacoes', 'fa-calendar-check')
    if not pets and not experience.workspaces:
        add('Cadastrar meu primeiro pet', 'Comece a organizar vacinas e atendimentos.',
            'add_animal', 'fa-paw')
    # Clinical reminders stay visible even when a user also owns a business.
    actions.sort(key=lambda item: item['tone'] != 'attention')
    return actions[:6]
