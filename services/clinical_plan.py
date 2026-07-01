"""Build calculated clinical plans from protocols.

This module is the bridge between clinical protocols and the prescription
calculator. It keeps the protocol panel from needing to know how the bulario
chooses doses, presentations, or practical quantities.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from extensions import db
from models import Medicamento
from services.bulario import sugerir_dose
from services.clinical_suggestions import build_followup_prefill
from services.posologia_normalizacao import normalizar_frequencia
from services.prescricao_alias import resolver_alias


READY = "ready"
REVIEW = "review"
BLOCKED = "blocked"
MANUAL = "manual"


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _fmt_number(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 0.0001:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _fmt_range(min_value: int | None, max_value: int | None, unit: str) -> str:
    if min_value and max_value and min_value != max_value:
        return f"por {min_value} a {max_value} {unit}"
    if min_value:
        return f"por {min_value} {unit}"
    if max_value:
        return f"por ate {max_value} {unit}"
    return ""


def _pluralize(unit: str, amount: float) -> str:
    normalized = unit.strip() or "unidade"
    singular_map = {
        "comprimido(s)": "comprimido",
        "gota(s)": "gota",
        "pipeta(s)": "pipeta",
        "capsula": "capsula",
    }
    normalized = singular_map.get(normalized.lower(), normalized)
    if amount <= 1 or abs(amount - 1) < 0.0001:
        return normalized
    if normalized.endswith("l"):
        return normalized
    if normalized.endswith("s"):
        return normalized
    return f"{normalized}s"


def _unit_key(unit: str | None) -> str:
    return re.sub(r"\s+", "", _normalize(unit))


def _format_whole_unit(amount: float, singular: str, plural: str) -> str:
    rounded = int(round(amount))
    label = singular if rounded == 1 else plural
    return f"{rounded} {label}"


def _format_tablet_quantity(amount: float) -> str:
    rounded = round(amount * 4) / 4
    whole = int(rounded)
    fraction = rounded - whole

    if abs(fraction) < 0.001:
        return _format_whole_unit(whole, "comprimido", "comprimidos")

    fraction_labels = (
        (0.25, "1/4 de comprimido", "1/4"),
        (0.50, "meio comprimido", "meio"),
        (0.75, "3/4 de comprimido", "3/4"),
    )
    for expected, standalone, suffix in fraction_labels:
        if abs(fraction - expected) < 0.001:
            if whole == 0:
                return standalone
            return f"{_format_whole_unit(whole, 'comprimido', 'comprimidos')} e {suffix}"

    return f"{_fmt_number(amount)} comprimidos"


def _format_practical_quantity(amount: float, unit: str) -> str:
    key = _unit_key(unit)
    if key == "ml":
        return f"{_fmt_number(amount)} mL"
    if "comprim" in key or key == "cp":
        return _format_tablet_quantity(amount)
    if "gota" in key:
        return _format_whole_unit(amount, "gota", "gotas")
    if "pipeta" in key:
        return _format_whole_unit(amount, "pipeta", "pipetas")
    if "capsul" in key:
        return _format_whole_unit(amount, "cápsula", "cápsulas")
    if "drage" in key:
        return _format_whole_unit(amount, "drágea", "drágeas")
    if "aplic" in key:
        return _format_whole_unit(amount, "aplicação", "aplicações")

    normalized = unit.strip() or "unidade"
    if abs(amount - round(amount)) < 0.001:
        return _format_whole_unit(amount, normalized, _pluralize(normalized, 2))
    return f"{_fmt_number(amount)} {_pluralize(normalized, amount)}"


def _text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, dict):
        parts = [_text_value(value.get(key)) for key in ("principal", "secundario", "forma", "concentracao")]
        return " - ".join(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        return " - ".join(part for part in (_text_value(item) for item in value) if part)
    return re.sub(r"\s+", " ", str(value)).strip()


def _presentation_label(ap: dict[str, Any]) -> str:
    choice = ap.get("rotulo_escolha") if isinstance(ap.get("rotulo_escolha"), dict) else {}
    clinical_label = (
        _text_value(ap.get("rotulo_principal"))
        or _text_value(ap.get("descricao"))
        or _text_value(ap.get("nome_variante"))
        or _text_value(ap.get("concentracao_label"))
        or _text_value(ap.get("concentracao_texto"))
    )
    context_label = _text_value(choice.get("principal"))
    label = clinical_label or context_label
    if context_label and clinical_label and _normalize(context_label) != _normalize(clinical_label):
        label = f"{context_label} - {clinical_label}"

    secondary = _text_value(ap.get("rotulo_secundario")) or _text_value(choice.get("secundario"))
    if secondary and secondary.lower() not in label.lower():
        label = f"{label} - {secondary}" if label else secondary

    if label:
        return label

    parts = [_text_value(ap.get("forma")), _text_value(ap.get("concentracao"))]
    return " - ".join(part for part in parts if part)


def _dose_value_for_mode(suggestion: dict[str, Any], mode: str) -> float | None:
    min_value = _float_or_none(suggestion.get("dose_min"))
    max_value = _float_or_none(suggestion.get("dose_max"))
    if min_value is None and max_value is None:
        return None
    if max_value is None:
        max_value = min_value
    if min_value is None:
        min_value = max_value
    if mode == "min":
        return min_value
    if mode == "max":
        return max_value
    return (min_value + max_value) / 2


def _format_dose_value(suggestion: dict[str, Any], mode: str) -> str:
    value = _dose_value_for_mode(suggestion, mode)
    unit = (suggestion.get("dose_unit_out") or "").strip()
    if value is None:
        return suggestion.get("dose_exibir") or ""
    return f"{_fmt_number(value)} {unit}".strip()


def _dose_text_matches_protocol(suggestion: dict[str, Any], item) -> bool:
    expected = _normalize(getattr(item, "dosagem_texto", None))
    if not expected:
        return False
    candidates = [
        suggestion.get("faixa_texto"),
        suggestion.get("dose_exibir"),
        suggestion.get("dose_bruta"),
        suggestion.get("observacao"),
    ]
    for candidate in candidates:
        normalized = _normalize(candidate)
        if normalized and (expected in normalized or normalized in expected):
            return True
    return False


def _suggestion_protocol_score(suggestion: dict[str, Any], item, mode: str) -> float:
    score = 100.0
    item_indication = _normalize(getattr(item, "indicacao", None))
    suggestion_indication = _normalize(suggestion.get("indicacao"))
    if item_indication and suggestion_indication == item_indication:
        score -= 35
    if item_indication:
        alternatives = [_normalize(value) for value in (suggestion.get("indicacoes_alternativas") or [])]
        if item_indication in alternatives:
            score -= 15
    if _dose_text_matches_protocol(suggestion, item):
        score -= 40

    frequency = _frequency_text(suggestion, getattr(item, "frequencia_texto", None))
    if frequency and _normalize(frequency) == _normalize(getattr(item, "frequencia_texto", None)):
        score -= 10

    via = _normalize(suggestion.get("via"))
    if "oral" in via:
        score -= 6
    if _practical_presentation_options(suggestion, mode):
        score -= 6
    return score


def _resolve_multiplo_suggestion(
    medication: Medicamento,
    animal,
    item,
    mode: str,
    commercial_filter: str | None,
    indications: list[str],
) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for indication in indications or []:
        suggestion = sugerir_dose(
            medication,
            animal,
            indicacao=indication,
            nome_comercial_filtro=commercial_filter,
            preservar_variantes_comerciais=True,
        )
        if not suggestion or suggestion.get("multiplo"):
            continue
        candidates.append((_suggestion_protocol_score(suggestion, item, mode), suggestion))

    if not candidates:
        return None
    candidates.sort(key=lambda item_score: item_score[0])
    return candidates[0][1]


def _frequency_text(suggestion: dict[str, Any], override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    if suggestion.get("intervalo_horas"):
        return f"a cada {suggestion['intervalo_horas']} horas"
    return (suggestion.get("frequencia_texto") or "").strip()


def _duration_text(suggestion: dict[str, Any], override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    return (
        _fmt_range(suggestion.get("duracao_min_dias"), suggestion.get("duracao_max_dias"), "dias")
        or (suggestion.get("duracao_texto") or "").strip()
    )


def _normalize_textual_duration(value: str) -> str:
    text = _text_value(value)
    if not text:
        return ""
    if _normalize(text).startswith(("por ", "ate ", "criterio ")):
        return text
    if re.match(r"^\d+(?:\s+a\s+\d+)?\s+dias?$", _normalize(text)):
        return f"por {text}"
    return text


def _preferred_dose_mode(item) -> str:
    name = _normalize(getattr(item, "nome_exibicao", None))
    indication = _normalize(getattr(item, "indicacao", None))
    dose_text = _normalize(getattr(item, "dosagem_texto", None))
    if name == "prednisona" and indication == "alergia":
        return "min"
    if any(token in dose_text for token in (" a ", " ate ", " - ")) or "-" in (getattr(item, "dosagem_texto", "") or ""):
        return "media"
    return "media"


def _resolve_medication(item, session) -> Medicamento | None:
    if getattr(item, "medicamento", None):
        return item.medicamento
    med_id = getattr(item, "medicamento_id", None)
    if not med_id and getattr(item, "nome_exibicao", None):
        med_id, _confidence = resolver_alias(item.nome_exibicao, session)
    if not med_id:
        return None
    getter = getattr(session, "get", None)
    if getter:
        return getter(Medicamento, med_id)
    return Medicamento.query.get(med_id)


def _commercial_filter(item, medication: Medicamento | None) -> str | None:
    if not medication:
        return None
    item_name = (getattr(item, "nome_exibicao", None) or "").strip()
    med_name = (getattr(medication, "nome", None) or "").strip()
    if item_name and med_name and _normalize(item_name) != _normalize(med_name):
        return item_name
    return None


def _concentration_in_dose_unit(ap: dict[str, Any], dose_unit: str) -> float | None:
    value = _float_or_none(ap.get("concentracao_valor"))
    if value is None:
        return None
    unit = (ap.get("concentracao_unidade") or "").lower()
    dose_unit = dose_unit.lower()
    if dose_unit == "mg":
        if unit == "mg":
            return value
        if unit == "g":
            return value * 1000
        if unit == "mcg":
            return value / 1000
        if unit == "ui":
            return value
    return None


def _round_quantity(quantity: float, unit: str) -> float:
    key = _unit_key(unit)
    if key == "ml":
        return round(quantity * 10) / 10
    if "gota" in key:
        return round(quantity)
    if "comprim" in key or key == "cp":
        return round(quantity * 2) / 2
    return round(quantity)


def _practical_score(quantity: float, desired: float, delivered: float) -> float:
    if desired <= 0:
        return 9999
    error = abs(delivered - desired) / desired
    penalty = 0
    if quantity > 6:
        penalty += 50
    elif quantity > 4:
        penalty += 20
    elif quantity > 2:
        penalty += 8
    if abs(quantity - round(quantity)) > 0.001:
        penalty += 2
    return penalty + error * 100


def _practical_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    quantity = candidate["quantity"]
    ap = candidate["presentation"]
    dose_text = _format_practical_quantity(quantity, candidate["unit"])
    presentation = {
        "id": ap.get("id"),
        "label": _presentation_label(ap),
        "forma": ap.get("forma") or "",
        "concentracao": ap.get("concentracao_label") or ap.get("concentracao_texto") or "",
        "nome_variante": ap.get("nome_variante") or "",
        "nome_comercial": ap.get("nome_comercial") or "",
        "fabricante": ap.get("fabricante") or "",
    }
    delivered = _float_or_none(candidate.get("delivered"))
    desired = _float_or_none(candidate.get("desired"))
    delivered_text = ""
    if delivered is not None:
        delivered_text = f"{_fmt_number(delivered)} {candidate.get('dose_unit') or ''}".strip()
    desired_text = ""
    if desired is not None:
        desired_text = f"{_fmt_number(desired)} {candidate.get('dose_unit') or ''}".strip()
    return {
        "quantity": quantity,
        "unit": candidate["unit"],
        "dose_text": dose_text,
        "option_label": " — ".join(part for part in [dose_text, presentation["label"]] if part),
        "delivered_dose": delivered_text,
        "desired_dose": desired_text,
        "score": candidate.get("score"),
        "presentation": presentation,
    }


def _practical_presentation_options(suggestion: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    presentations = [
        ap for ap in (suggestion.get("apresentacoes") or [])
        if ap.get("permite_calculo_automatico")
    ]
    if not presentations:
        return []

    preferred_id = suggestion.get("apresentacao_preferida_id")
    if preferred_id:
        for ap in presentations:
            if ap.get("id") == preferred_id:
                presentations = [ap] + [item for item in presentations if item.get("id") != preferred_id]
                break

    dose_value = _dose_value_for_mode(suggestion, mode)
    dose_unit = (suggestion.get("dose_unit_out") or "").lower()
    if dose_value is None:
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[Any, float, str]] = set()
    for ap in presentations:
        practical_unit = (ap.get("unidade_pratica") or "unidade").strip() or "unidade"
        concentration_unit = (ap.get("concentracao_unidade") or "").lower()
        quantity = None
        delivered = dose_value
        if dose_unit == "mg" and concentration_unit in {"mg", "g", "mcg", "ui"}:
            concentration = _concentration_in_dose_unit(ap, "mg")
            if concentration:
                quantity = dose_value / concentration
                delivered = _round_quantity(quantity, practical_unit) * concentration
        elif dose_unit == "mg" and concentration_unit in {"mg/ml", "mcg/ml"}:
            concentration = _float_or_none(ap.get("concentracao_valor"))
            if concentration:
                if concentration_unit == "mcg/ml":
                    concentration = concentration / 1000
                quantity = dose_value / concentration
                practical_unit = "mL"
                delivered = _round_quantity(quantity, practical_unit) * concentration
        elif dose_unit in {"ml", "ml."}:
            quantity = dose_value
            practical_unit = "mL"
        elif dose_unit in {"comprimido(s)", "cp"}:
            quantity = dose_value
            practical_unit = "comprimido"
        elif dose_unit == "gota(s)":
            quantity = dose_value
            practical_unit = "gota"
        elif dose_unit == "pipeta(s)":
            quantity = dose_value
            practical_unit = "pipeta"

        if quantity is None or quantity <= 0:
            continue
        rounded = _round_quantity(quantity, practical_unit)
        if rounded <= 0:
            continue
        key = (ap.get("id"), rounded, practical_unit)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "presentation": ap,
            "quantity": rounded,
            "unit": practical_unit,
            "desired": dose_value,
            "delivered": delivered,
            "dose_unit": suggestion.get("dose_unit_out") or "",
            "score": _practical_score(rounded, dose_value, delivered),
        })

    if not candidates:
        return []
    candidates.sort(key=lambda item: (item["score"], item["quantity"]))
    return [_practical_payload(candidate) for candidate in candidates]


def _is_topical_textual_suggestion(suggestion: dict[str, Any]) -> bool:
    dose_unit = _normalize(suggestion.get("dose_unit_out"))
    via = _normalize(suggestion.get("via"))
    faixa = _normalize(suggestion.get("faixa_texto"))
    dose_text = _normalize(suggestion.get("dose_exibir"))
    return (
        "camada fina" in dose_unit
        or "aplicacao topica" in faixa
        or "topica" in via
        or "topico" in via
        or "camada fina" in dose_text
    )


def _normalize_topical_application_text(value: str | None) -> str:
    text = _text_value(value)
    normalized = _normalize(text)
    if not text or not normalized:
        return ""
    if any(token in normalized for token in (
        "area afetada",
        "regiao acometida",
        "regiao afetada",
        "lesao",
        "lesoes",
    )):
        return "Aplicar sobre a região acometida"
    return text


def _textual_presentation_options(
    suggestion: dict[str, Any],
    dose_text: str,
) -> list[dict[str, Any]]:
    if not _is_topical_textual_suggestion(suggestion):
        return []
    presentations = [
        ap for ap in (suggestion.get("apresentacoes") or [])
        if (ap.get("categoria") or "") in {"topico", "otico", "oftalmico"}
    ]
    if len(presentations) != 1:
        return []
    ap = presentations[0]
    dose_text = dose_text or "Aplicar sobre a região acometida"
    presentation = {
        "id": ap.get("id"),
        "label": _presentation_label(ap),
        "forma": ap.get("forma") or "",
        "concentracao": ap.get("concentracao_label") or ap.get("concentracao_texto") or "",
        "nome_variante": ap.get("nome_variante") or "",
        "nome_comercial": ap.get("nome_comercial") or "",
        "fabricante": ap.get("fabricante") or "",
    }
    return [{
        "quantity": 1,
        "unit": ap.get("unidade_pratica") or "aplicação",
        "dose_text": dose_text,
        "option_label": " — ".join(part for part in [dose_text, presentation["label"]] if part),
        "delivered_dose": "",
        "desired_dose": "",
        "score": 0,
        "presentation": presentation,
    }]


def _choose_practical_presentation(suggestion: dict[str, Any], mode: str) -> dict[str, Any] | None:
    options = _practical_presentation_options(suggestion, mode)
    return options[0] if options else None


def _build_medication_plan(item, consulta, session) -> dict[str, Any]:
    animal = getattr(consulta, "animal", None)
    med = _resolve_medication(item, session)
    mode = _preferred_dose_mode(item)
    fallback_draft = {
        "medicamento_id": getattr(med, "id", None),
        "medicamento": getattr(item, "nome_exibicao", None) or "",
        "dosagem": getattr(item, "dosagem_texto", None) or "",
        "frequencia": getattr(item, "frequencia_texto", None) or "",
        "duracao": getattr(item, "duracao_texto", None) or "",
        "observacoes": getattr(item, "observacoes", None) or "",
        "texto": getattr(item, "observacoes", None) or "",
        "indicacao": getattr(item, "indicacao", None) or "",
        "use_weight_based_dose": False,
        "preferred_dose_mode": mode,
        "compact_practical_dose": _normalize(getattr(item, "nome_exibicao", None)) == "simparic",
    }

    base = {
        "id": item.id,
        "protocol_item_id": item.id,
        "nome": getattr(item, "nome_exibicao", None) or "",
        "medicamento_id": getattr(med, "id", None),
        "medicamento_canonico": getattr(med, "nome", None) if med else None,
        "indicacao": getattr(item, "indicacao", None) or "",
        "justificativa": getattr(item, "justificativa", None) or "",
        "observacoes": getattr(item, "observacoes", None) or "",
        "dose_protocolo": getattr(item, "dosagem_texto", None) or "",
        "frequencia_protocolo": getattr(item, "frequencia_texto", None) or "",
        "duracao_protocolo": getattr(item, "duracao_texto", None) or "",
        "preferred_dose_mode": mode,
        "draft_prescription": fallback_draft,
        "calculation": None,
        "messages": [],
    }

    if not med:
        status = MANUAL if base["dose_protocolo"] else BLOCKED
        base.update({
            "status": status,
            "status_label": "Medicamento nao vinculado ao bulario",
            "messages": ["Vincule este medicamento ao bulario para calcular automaticamente."],
        })
        return base

    peso = _float_or_none(getattr(animal, "peso", None))
    if not peso:
        base.update({
            "status": BLOCKED,
            "status_label": "Peso necessario",
            "messages": ["Informe o peso do animal para calcular a dose automaticamente."],
        })
        return base

    if not (getattr(med, "doses", None) or []):
        status = MANUAL if base["dose_protocolo"] else BLOCKED
        base.update({
            "status": status,
            "status_label": "Sem dose estruturada",
            "messages": ["Este medicamento ainda nao tem regra de dose no bulario."],
        })
        return base

    commercial_filter = _commercial_filter(item, med)
    suggestion = sugerir_dose(
        med,
        animal,
        indicacao=(getattr(item, "indicacao", None) or "").strip() or None,
        nome_comercial_filtro=commercial_filter,
        preservar_variantes_comerciais=True,
    )
    if not suggestion:
        base.update({
            "status": REVIEW,
            "status_label": "Sem protocolo aplicavel",
            "messages": ["Nao encontramos dose aplicavel para especie, peso e indicacao."],
        })
        return base
    if suggestion.get("multiplo"):
        resolved = _resolve_multiplo_suggestion(
            med,
            animal,
            item,
            mode,
            commercial_filter,
            suggestion.get("indicacoes", []),
        )
        if resolved:
            suggestion = resolved
        else:
            base.update({
                "status": REVIEW,
                "status_label": "Escolher indicacao",
                "messages": ["Ha mais de uma indicacao possivel para este medicamento."],
                "calculation": {"indicacoes": suggestion.get("indicacoes", [])},
            })
            return base

    protocol_dose_text = _normalize_topical_application_text(getattr(item, "dosagem_texto", None))
    practical_options = _practical_presentation_options(suggestion, mode)
    if not practical_options and protocol_dose_text:
        practical_options = _textual_presentation_options(suggestion, protocol_dose_text)
    practical = practical_options[0] if practical_options else None
    has_textual_practical = bool(practical and practical.get("delivered_dose") == "" and practical.get("desired_dose") == "")
    frequency = _frequency_text(suggestion, getattr(item, "frequencia_texto", None))
    duration = _duration_text(suggestion, getattr(item, "duracao_texto", None))
    if has_textual_practical:
        frequency = normalizar_frequencia(frequency) or frequency
        duration = _normalize_textual_duration(duration)
    calculated_dose = _format_dose_value(suggestion, mode)
    final_dose = practical["dose_text"] if practical else (protocol_dose_text or calculated_dose)
    practical_posology = " ".join(part for part in [final_dose, frequency, duration] if part) if practical else ""
    technical_posology = " ".join(part for part in [calculated_dose, frequency, duration] if part)
    final_name = base["nome"]

    fallback_draft.update({
        "medicamento_id": med.id,
        "medicamento": final_name,
        "dosagem": final_dose,
        "frequencia": frequency,
        "duracao": duration,
        "texto": practical_posology or technical_posology,
        "use_weight_based_dose": False if practical else True,
        "apresentacao_id": practical["presentation"].get("id") if practical else None,
        "apresentacao_nome": practical["presentation"].get("label") if practical else "",
    })

    status = READY if practical else REVIEW
    messages = []
    if not practical:
        messages.append("Dose calculada, mas a apresentacao ainda precisa ser escolhida ou revisada.")
    for flag in suggestion.get("flags_risco") or []:
        messages.append(flag.get("titulo") or flag.get("codigo") or "Revisar")

    base.update({
        "status": status,
        "status_label": "Pronto para revisar" if status == READY else "Dose calculada sem apresentacao pratica",
        "calculation": {
            "peso_kg": peso,
            "dose_mode": mode,
            "dose_calculada": calculated_dose,
            "dose_pratica": final_dose if practical else "",
            "dose_faixa": suggestion.get("faixa_texto") or "",
            "frequencia": frequency,
            "duracao": duration,
            "posologia_pratica": practical_posology,
            "posologia_tecnica": technical_posology,
            "apresentacao_pratica": practical,
            "apresentacao_opcoes": practical_options,
            "apresentacao_opcao_selecionada": 0 if practical_options else None,
            "raw_suggestion": suggestion,
        },
        "messages": messages,
    })
    return base


def build_clinical_plan(
    consulta,
    protocolo,
    *,
    session=None,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Return a calculated plan for a protocol in the context of a consultation."""
    session = session or db.session
    animal = getattr(consulta, "animal", None)
    medications = [
        _build_medication_plan(item, consulta, session)
        for item in (getattr(protocolo, "medicamentos_sugeridos", None) or [])
        if getattr(item, "nome_exibicao", None)
    ]
    exams = [
        {
            "id": item.id,
            "nome": item.nome,
            "justificativa": item.justificativa,
            "status": READY,
        }
        for item in (getattr(protocolo, "exames_sugeridos", None) or [])
    ]
    returns = [
        {
            **build_followup_prefill(item, reference_date=reference_date),
            "status": READY,
        }
        for item in (getattr(protocolo, "retornos_sugeridos", None) or [])
    ]
    counts = {
        "ready": sum(1 for item in medications if item["status"] == READY),
        "review": sum(1 for item in medications if item["status"] == REVIEW),
        "manual": sum(1 for item in medications if item["status"] == MANUAL),
        "blocked": sum(1 for item in medications if item["status"] == BLOCKED),
    }
    return {
        "protocol": {
            "id": protocolo.id,
            "nome": protocolo.nome,
            "suspeita_principal": protocolo.suspeita_principal,
            "especie": protocolo.especie,
            "versao": protocolo.versao,
        },
        "animal": {
            "id": getattr(animal, "id", None),
            "nome": getattr(animal, "name", None) or getattr(animal, "nome", None) or "",
            "especie": getattr(getattr(animal, "species", None), "name", None) or "",
            "peso_kg": _float_or_none(getattr(animal, "peso", None)),
        },
        "status": BLOCKED if counts["blocked"] else (REVIEW if counts["review"] or counts["manual"] else READY),
        "summary": {
            **counts,
            "medications_total": len(medications),
            "exams_total": len(exams),
            "returns_total": len(returns),
        },
        "conduct": {
            "texto": (getattr(protocolo, "conduta_sugerida", None) or "").strip(),
            "status": READY if getattr(protocolo, "conduta_sugerida", None) else MANUAL,
        },
        "instructions": (getattr(protocolo, "orientacoes_tutor", None) or "").strip(),
        "alerts": (getattr(protocolo, "alertas", None) or "").strip(),
        "medications": medications,
        "exams": exams,
        "returns": returns,
        "draft_prescriptions": [
            item["draft_prescription"]
            for item in medications
            if item["status"] == READY
        ],
    }
