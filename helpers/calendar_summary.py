from __future__ import annotations

from typing import Iterable, Optional, Set
import re
import unicodedata

__all__ = ["serialize_vet_for_summary"]


def _clean_string(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    return stripped or None


def _normalize_id_set(values: Optional[Iterable[object]]) -> Set[int]:
    result: Set[int] = set()
    if not values:
        return result
    for candidate in values:
        if candidate is None:
            continue
        try:
            normalized = int(candidate)
        except (TypeError, ValueError):
            continue
        result.add(normalized)
    return result


def _collect_vet_clinic_ids(vet: object) -> Set[int]:
    clinic_ids: Set[int] = set()
    primary_clinic_id = getattr(vet, "clinica_id", None)
    if primary_clinic_id is not None:
        try:
            clinic_ids.add(int(primary_clinic_id))
        except (TypeError, ValueError):
            pass
    associated_clinics = getattr(vet, "clinicas", None) or []
    for clinic in associated_clinics:
        clinic_id = getattr(clinic, "id", None)
        if clinic_id is None:
            continue
        try:
            clinic_ids.add(int(clinic_id))
        except (TypeError, ValueError):
            continue
    return clinic_ids


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _compute_initials(name: Optional[str], fallback: Optional[object] = None) -> str:
    candidate = _clean_string(name)
    if candidate:
        words = re.split(r"\s+", _strip_accents(candidate))
        words = [word for word in words if word]
        if len(words) == 1:
            word = words[0]
            if len(word) >= 2:
                return (word[0] + word[1]).upper()
            return word[:1].upper()
        if words:
            first = words[0][:1]
            last = words[-1][:1]
            initials = (first + last).strip()
            if initials:
                return initials.upper()
    fallback_text = _clean_string(fallback)
    if fallback_text:
        fallback_text = _strip_accents(fallback_text)
        if len(fallback_text) >= 2:
            return fallback_text[-2:].upper()
        return fallback_text[:1].upper()
    return ""


def serialize_vet_for_summary(
    vet: object,
    *,
    label: Optional[str] = None,
    clinic_ids: Optional[Iterable[object]] = None,
) -> Optional[dict]:
    """Return a normalized mapping with metadata for calendar summaries.

    The result contains the keys ``id``, ``label``, ``full_name``, ``initials``,
    ``is_specialist`` and ``specialty_text`` so that templates and client-side
    code can operate on a predictable shape.
    """

    if vet is None:
        return None

    vet_id = getattr(vet, "id", None)
    if vet_id is None:
        return None
    try:
        normalized_id = int(vet_id)
    except (TypeError, ValueError):
        return None

    vet_user = getattr(vet, "user", None)
    full_name = _clean_string(getattr(vet_user, "name", None))
    provided_label = _clean_string(label)
    normalized_label = provided_label or full_name or f"Profissional #{normalized_id}"

    specialty_text = _clean_string(getattr(vet, "specialty_list", None))
    normalized_clinic_ids = _normalize_id_set(clinic_ids)
    vet_clinic_ids = _collect_vet_clinic_ids(vet)

    is_specialist = bool(specialty_text)
    if not is_specialist and normalized_label and "especialista" in normalized_label.lower():
        is_specialist = True
    if not is_specialist and normalized_clinic_ids:
        if vet_clinic_ids and not vet_clinic_ids.intersection(normalized_clinic_ids):
            is_specialist = bool(specialty_text)

    initials = _compute_initials(full_name or normalized_label, normalized_id)

    return {
        "id": normalized_id,
        "label": normalized_label,
        "full_name": full_name or normalized_label,
        "initials": initials,
        "is_specialist": bool(is_specialist),
        "specialty_text": specialty_text,
    }
