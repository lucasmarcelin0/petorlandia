"""O que cada pessoa da equipe consegue fazer numa clínica, e por quê.

Só leitura: cada item chama a mesma função que a rota usa para liberar ou
barrar, então o quadro nunca diverge do comportamento real. Serve à tela de
permissões (o dono vê na hora o que falta) e a
``scripts/auditar_acessos_equipe.py`` (diagnóstico sem abrir o banco).
"""
from dataclasses import dataclass

from authz import ROLE_PERMISSION_MATRIX, _user_roles, _viewer_operational_clinic_ids


@dataclass(frozen=True)
class AccessItem:
    key: str
    label: str
    allowed: bool
    detail: str = ''


def _staff_for(user, clinic_id):
    for staff in getattr(user, 'clinic_roles', None) or []:
        if getattr(staff, 'clinic_id', None) == clinic_id:
            return staff
    return None


def _matrix_allows(user, clinic_id, resource, action):
    """Mesma regra de ``authz._can_clinic_resource`` sem gravar auditoria.

    O relatório consulta várias permissões de uma vez; passar por ``_can``
    encheria a janela de negações que alimenta os alertas de segurança.
    """
    roles = _user_roles(user)
    if not any(ROLE_PERMISSION_MATRIX.get(r, {}).get(resource, {}).get(action) for r in roles):
        return False
    return 'admin' in roles or clinic_id in _viewer_operational_clinic_ids(user)


def _clinical_reason(user):
    """Motivo, em linguagem de gente, de o usuário não praticar atos clínicos."""
    from helpers import (
        _membership_expired, active_internship_staff, is_intern_account,
    )

    vet = getattr(user, 'veterinario', None)
    intern = (
        getattr(vet, 'is_estagiario', False)
        or is_intern_account(user)
        or active_internship_staff(user) is not None
    )
    if intern:
        sup_vet = getattr(vet, 'supervisor', None) if vet is not None else None
        staff = active_internship_staff(user)
        sup_user = getattr(sup_vet, 'user', None) or getattr(staff, 'internship_supervisor', None)
        if sup_user is None:
            return 'Estagiário sem supervisor: defina o supervisor no cadastro do profissional.'
        if not getattr(getattr(sup_user, 'veterinario', None), 'pode_assinar', False):
            return f'O supervisor ({sup_user.name}) não tem CRMV cadastrado.'
        if _membership_expired(sup_user):
            return f'A assinatura do supervisor ({sup_user.name}) venceu; renove para liberar.'
        return 'Supervisor sem assinatura ativa.'
    if vet is not None:
        if _membership_expired(user):
            return 'Assinatura do PetOrlândia vencida.'
        return 'Perfil veterinário sem CRMV ou sem assinatura ativa.'
    return 'Não é veterinário nem estagiário supervisionado.'


def access_report(user, clinic):
    """Lista de ``AccessItem`` para ``user`` na ``clinic``."""
    from helpers import (
        _user_can_access_accounting, can_act_as_veterinarian, can_start_consulta,
        pessoa_no_documento, staff_can_manage_animals,
    )
    from services.internacao_access import pode_operar_internacao, pode_prescrever_internacao

    clinic_id = clinic.id
    staff = _staff_for(user, clinic_id)
    is_admin = (getattr(user, 'role', None) or '').lower() == 'admin'
    is_owner = getattr(clinic, 'owner_id', None) == user.id
    clinical = can_act_as_veterinarian(user)
    clinical_reason = '' if clinical else _clinical_reason(user)
    items = []

    def add(key, label, allowed, denied='', granted=''):
        items.append(AccessItem(key, label, bool(allowed), granted if allowed else denied))

    add('atender', 'Abrir atendimento pela agenda', can_start_consulta(user),
        denied='Precisa ser veterinário, estagiário com estágio ativo ou colaborador.')
    signer = pessoa_no_documento(user) if clinical else None
    add('clinico', 'Consultas, receitas, exames, vacinas e atestados', clinical,
        denied=clinical_reason,
        granted=(f'Documentos saem no nome de {signer.name}.'
                 if signer is not None and signer.id != user.id else ''))
    add('animais', 'Editar cadastro dos animais',
        clinical or staff_can_manage_animals(user, clinic_id),
        denied='Marque "Animais" nas permissões.')
    add('internacao', 'Internação: registrar cuidados', pode_operar_internacao(user, clinic_id),
        denied=clinical_reason or 'Sem vínculo de equipe com esta clínica.')
    add('internacao_prescrever', 'Internação: prescrever e dar alta',
        pode_prescrever_internacao(user, clinic_id),
        denied=clinical_reason or 'Exige veterinário com CRMV ou estagiário supervisionado.')
    add('orcamentos', 'Orçamentos', _matrix_allows(user, clinic_id, 'budget', 'manage'),
        denied='Sem vínculo de equipe com esta clínica.')
    add('estoque', 'Estoque', is_admin or is_owner or bool(getattr(staff, 'can_manage_inventory', False)),
        denied='Marque "Estoque" nas permissões.')
    add('financeiro', 'Ver financeiro da clínica', _matrix_allows(user, clinic_id, 'financial', 'view'),
        denied='Sem vínculo de equipe com esta clínica.')
    add('contabilidade', 'Contabilidade', _user_can_access_accounting(user),
        denied='Só o dono da clínica (veterinário) ou gestor.')
    add('fiscal', 'Notas fiscais', _matrix_allows(user, clinic_id, 'fiscal_documents', 'view'),
        denied='Só o dono da clínica.')
    add('equipe', 'Gerenciar equipe e permissões', is_admin or is_owner,
        denied='Só o dono da clínica.')
    add('vacinacao_pmo', 'Vacinação antirrábica (PMO)',
        (getattr(user, 'role', None) or '').lower() in {'admin', 'vacinador'},
        denied='Precisa do papel "Vacinador PMO" (definido pelo administrador).')
    return items
