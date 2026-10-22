"""Permissões do prontuário hospitalar, independentes dos links do tutor.

Um vínculo de cliente em ``User.clinica_id`` não é vínculo de equipe.
Estagiário com supervisor habilitado atua como veterinário; responsável
técnico da internação continua sendo quem tem CRMV próprio.
"""

from authz import can_view_clinic


def _clinic_id(value):
    if isinstance(value, (bool, float)):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


def _eligible_account(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    from helpers import is_intern_account

    intern = is_intern_account(user) or getattr(getattr(user, 'veterinario', None), 'is_estagiario', False)
    # Estagiário entra apenas com supervisor habilitado; atua como veterinário.
    return not intern or _supervised_intern(user)


def _supervised_intern(user):
    from helpers import is_supervised_intern

    return is_supervised_intern(user)


def _internship_clinic_ids(user):
    from helpers import active_internship_staff

    ids = set()
    staff = active_internship_staff(user)
    if staff is not None and (clinic_id := _clinic_id(getattr(staff, 'clinic_id', None))):
        ids.add(clinic_id)
    vet = getattr(user, 'veterinario', None)
    if vet is not None and getattr(vet, 'is_estagiario', False):
        if clinic_id := _clinic_id(getattr(vet, 'clinica_id', None)):
            ids.add(clinic_id)
    return ids


def _admin(user):
    return (getattr(user, 'role', None) or '').lower() == 'admin'


def _qualified_veterinarian(user):
    vet = getattr(user, 'veterinario', None)
    if not vet or not str(getattr(vet, 'crmv', None) or '').strip():
        return False
    from helpers import is_veterinarian

    return is_veterinarian(user)


def _regular_staff_ids(user):
    return {
        clinic_id
        for staff in (getattr(user, 'clinic_roles', None) or [])
        if not getattr(staff, 'is_intern', False)
        if (clinic_id := _clinic_id(getattr(staff, 'clinic_id', None)))
    }


def _bound_clinic_ids(user):
    """Vínculos próprios; não inclui o escopo global do administrador."""
    ids = {
        clinic_id
        for clinic in (getattr(user, 'clinicas', None) or [])
        if (clinic_id := _clinic_id(getattr(clinic, 'id', None)))
    }
    ids.update(_regular_staff_ids(user))

    # Compatibilidade com equipe antiga, mantendo o mesmo critério operacional
    # de authz. Um estágio não vira equipe por um worker legado no cadastro.
    internship_ids = {
        _clinic_id(getattr(staff, 'clinic_id', None))
        for staff in (getattr(user, 'clinic_roles', None) or [])
        if getattr(staff, 'is_intern', False)
    }
    clinic_id = _clinic_id(getattr(user, 'clinica_id', None))
    worker = (getattr(user, 'worker', None) or '').lower()
    if worker in {'colaborador', 'staff', 'assistente'} and clinic_id not in internship_ids:
        if clinic_id:
            ids.add(clinic_id)

    if _supervised_intern(user):
        ids.update(_internship_clinic_ids(user))

    if _qualified_veterinarian(user):
        vet = user.veterinario
        clinic_id = _clinic_id(getattr(vet, 'clinica_id', None))
        if clinic_id:
            ids.add(clinic_id)
        ids.update(
            clinic_id
            for clinic in (getattr(vet, 'clinicas', None) or [])
            if (clinic_id := _clinic_id(getattr(clinic, 'id', None)))
        )
    return ids


def pode_operar_internacao(user, clinica_id):
    """Ler e registrar cuidados como membro operacional da clínica."""
    clinic_id = _clinic_id(clinica_id)
    if not clinic_id or not _eligible_account(user):
        return False
    if _admin(user):
        return True
    if clinic_id not in _bound_clinic_ids(user):
        return False
    # ClinicStaff é vínculo explícito concedido pela clínica, inclusive em
    # contas legadas cujo worker ainda não foi sincronizado para colaborador.
    if _supervised_intern(user) and clinic_id in _internship_clinic_ids(user):
        return True
    return clinic_id in _regular_staff_ids(user) or can_view_clinic(user, clinic_id)


def pode_acessar_internacao(user):
    """Exibir a entrada somente para quem tem algum escopo hospitalar."""
    if not _eligible_account(user):
        return False
    return _admin(user) or any(
        pode_operar_internacao(user, clinic_id)
        for clinic_id in _bound_clinic_ids(user)
    )


def clinicas_internacao(user):
    """Clínicas permitidas para os seletores de painel e admissão."""
    if not _eligible_account(user):
        return []
    ids = None if _admin(user) else _bound_clinic_ids(user)
    if ids == set():
        return []
    from models import Clinica

    query = Clinica.query
    if ids is not None:
        query = query.filter(Clinica.id.in_(ids))
    return [
        clinic
        for clinic in query.order_by(Clinica.nome, Clinica.id).all()
        if pode_operar_internacao(user, clinic.id)
    ]


def pode_prescrever_internacao(user, clinica_id):
    """Prescrever/encerrar exige veterinário ativo com CRMV e vínculo local.

    O papel admin permite operação global, mas não substitui habilitação nem
    vínculo profissional para praticar os atos clínicos da internação.
    """
    clinic_id = _clinic_id(clinica_id)
    if not (clinic_id and _eligible_account(user)
            and clinic_id in _bound_clinic_ids(user)
            and pode_operar_internacao(user, clinic_id)):
        return False
    if _qualified_veterinarian(user):
        return True
    # Estagiário prescreve como o veterinário; os documentos saem no nome do
    # supervisor, que precisa estar ativo.
    from helpers import can_act_as_veterinarian

    return _supervised_intern(user) and can_act_as_veterinarian(user)


def pode_ser_responsavel_internacao(user, clinica_id):
    """Responsável técnico da internação: só quem tem CRMV próprio."""
    return bool(
        pode_prescrever_internacao(user, clinica_id)
        and getattr(getattr(user, 'veterinario', None), 'pode_assinar', False)
    )
