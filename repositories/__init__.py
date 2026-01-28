"""Repositories encapsulating data access queries."""

from repositories.appointment_repository import AppointmentRepository
from repositories.clinic_repository import ClinicRepository
from repositories.consulta_repository import ConsultaRepository
from repositories.message_repository import MessageRepository

__all__ = [
    "AppointmentRepository",
    "ClinicRepository",
    "ConsultaRepository",
    "MessageRepository",
]
