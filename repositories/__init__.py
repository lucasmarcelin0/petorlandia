"""Repositories encapsulating data access queries."""

from repositories.appointment_repository import AppointmentRepository
from repositories.clinic_repository import ClinicRepository

__all__ = ["AppointmentRepository", "ClinicRepository"]
