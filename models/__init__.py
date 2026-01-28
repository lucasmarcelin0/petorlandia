"""Pacote de modelos com reexportações para compatibilidade."""

from .base import *  # noqa: F401,F403
from .agenda import AgendaEvento, Appointment, ExamAppointment, PlantaoModelo, PlantonistaEscala, VetSchedule
from .loja import (
    DeliveryRequest,
    Order,
    OrderItem,
    Payment,
    PaymentMethod,
    PaymentStatus,
    PickupLocation,
    Product,
    ProductPhoto,
    SavedAddress,
    Transaction,
)
from .usuarios import (
    Endereco,
    Specialty,
    User,
    UserRole,
    Veterinario,
    VeterinarianMembership,
    VeterinarianSettings,
)

__all__ = [
    "AgendaEvento",
    "Appointment",
    "ExamAppointment",
    "PlantonistaEscala",
    "PlantaoModelo",
    "VetSchedule",
    "DeliveryRequest",
    "Order",
    "OrderItem",
    "Payment",
    "PaymentMethod",
    "PaymentStatus",
    "PickupLocation",
    "Product",
    "ProductPhoto",
    "SavedAddress",
    "Transaction",
    "Endereco",
    "Specialty",
    "User",
    "UserRole",
    "Veterinario",
    "VeterinarianMembership",
    "VeterinarianSettings",
]
