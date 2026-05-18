"""Shared helpers for pet establishments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EstablishmentCapabilities:
    can_sell_products: bool = True
    can_manage_shipping: bool = True
    can_connect_payments: bool = True
    can_manage_grooming: bool = True
    can_manage_tutors: bool = True
    can_manage_animals: bool = True
    can_manage_health_plans: bool = False
    can_use_veterinary_records: bool = False


def capabilities_for(kind: str) -> EstablishmentCapabilities:
    kind = (kind or "").strip().lower()
    if kind == "clinica":
        return EstablishmentCapabilities(
            can_manage_health_plans=True,
            can_use_veterinary_records=True,
        )
    if kind in {"casa_de_racao", "petshop", "banho_tosa"}:
        return EstablishmentCapabilities()
    return EstablishmentCapabilities(
        can_sell_products=False,
        can_manage_shipping=False,
        can_connect_payments=False,
        can_manage_grooming=False,
        can_manage_tutors=False,
        can_manage_animals=False,
    )


def establishment_label(kind: str) -> str:
    labels = {
        "clinica": "Clinica",
        "casa_de_racao": "Casa de racao",
        "petshop": "Pet shop",
        "banho_tosa": "Banho e tosa",
    }
    return labels.get((kind or "").strip().lower(), "Estabelecimento")
