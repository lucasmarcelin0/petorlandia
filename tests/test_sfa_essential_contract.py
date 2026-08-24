import json
import unicodedata
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATHS = {
    "t0": PROJECT_ROOT / "config" / "sfa_t0_form.json",
    "t10": PROJECT_ROOT / "config" / "sfa_t10_form.json",
    "t30": PROJECT_ROOT / "config" / "sfa_t30_form.json",
}

ESSENTIAL_KEYS = {
    "t0": {
        "respondent_role",
        "aceite_tcle",
        "outras_pessoas_com_sintomas",
        "vinculo_compartilhado",
        "exposicao_ambiental",
        "exposicao_animal",
        "exposicao_alimentar",
        "fonte_ainda_ativa",
        "outras_pessoas_ainda_expostas",
        "diagnostico_medico",
        "diagnostico_medico_qual",
        "sinais_alerta_atuais",
        "dias_incap",
        "houve_gasto",
        "custo_total",
        "ausencia_familiar",
    },
    "t10": {
        "classificacao_melhora",
        "sinais_alerta_atuais",
        "retornou_servico_saude",
        "diagnostico_medico",
        "diagnostico_medico_qual",
        "novos_casos_semelhantes",
        "nova_pista_exposicao",
        "fonte_ainda_ativa",
        "outras_pessoas_ainda_expostas",
        "dias_incap_novos",
        "houve_novos_gastos",
        "perda_renda",
    },
    "t30": {
        "estado_saude_final",
        "sinais_alerta_atuais",
        "retorno_atividades_normais",
        "diagnostico_medico",
        "diagnostico_medico_qual",
        "novos_casos_semelhantes",
        "nova_informacao_fonte",
        "fonte_ainda_ativa",
        "outras_pessoas_ainda_expostas",
        "orientacao_ou_acao_percebida",
        "novos_casos_apos_acao",
        "dias_incap_novos",
        "houve_novos_gastos",
        "perda_renda",
    },
}

BANNED_VISIBLE_KEYS = {
    "cpf",
    "nome",
    "ficha_sinan",
    "numero_ficha_sinan",
    "data_nascimento",
    "vacinas_12_meses",
}

CONDITIONAL_KEYS = {
    "t0": {
        "respondent_name",
        "outras_pessoas_quantidade",
        "vinculo_compartilhado",
        "vinculo_local",
        "vinculo_data_periodo",
        "vinculo_exposicao_suspeita",
        "exposicao_ambiental_detalhe",
        "exposicao_ambiental_outros_doentes",
        "exposicao_animal_detalhe",
        "exposicao_animal_outros_doentes",
        "exposicao_alimentar_item",
        "exposicao_alimentar_origem",
        "exposicao_alimentar_data",
        "exposicao_alimentar_expostos",
        "exposicao_alimentar_doentes",
        "fonte_ainda_ativa",
        "outras_pessoas_ainda_expostas",
        "diagnostico_medico_qual",
        "diagnostico_medico_status",
        "custo_total",
        "dias_cuidador",
    },
    "t10": {
        "diagnostico_medico_qual",
        "diagnostico_medico_status",
        "novos_casos_quantidade",
        "novos_casos_local_periodo",
        "nova_pista_detalhe",
        "fonte_ainda_ativa",
        "outras_pessoas_ainda_expostas",
        "custo_outros",
    },
    "t30": {
        "diagnostico_medico_qual",
        "diagnostico_medico_status",
        "novos_casos_quantidade",
        "novos_casos_local_periodo",
        "nova_informacao_fonte",
        "nova_informacao_fonte_detalhe",
        "fonte_ainda_ativa",
        "outras_pessoas_ainda_expostas",
        "orientacao_ou_acao_percebida",
        "novos_casos_apos_acao",
        "custo_outros",
    },
}

ATOMIC_OPERATORS = {
    "equals",
    "eq",
    "not_equals",
    "neq",
    "in",
    "selected_any",
    "contains_any",
    "selected_any_except",
    "nonempty",
    "present",
    "absent",
    "positive",
}


def _load_schema(stage: str) -> dict:
    return json.loads(SCHEMA_PATHS[stage].read_text(encoding="utf-8"))


def _fields(schema: dict) -> list[dict]:
    return [
        field
        for section in schema.get("sections", [])
        for field in section.get("fields", [])
        if isinstance(field, dict)
    ]


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").strip().lower()


def _assert_rule_structure(rule: object, *, stage: str, known_keys: dict[str, set[str]]) -> None:
    assert isinstance(rule, dict) and rule, f"{stage}: visible_if deve ser um objeto nao vazio"

    if "const" in rule:
        assert set(rule) == {"const"}, f"{stage}: const nao pode ser combinada com outra regra"
        assert isinstance(rule["const"], bool), f"{stage}: const deve ser booleana"
        return

    combinators = [name for name in ("all", "any", "not") if name in rule]
    if combinators:
        assert len(combinators) == 1, f"{stage}: use somente um combinador por nivel"
        combinator = combinators[0]
        assert set(rule) == {combinator}, f"{stage}: combinador nao pode ser misturado com folha atomica"
        if combinator == "not":
            _assert_rule_structure(rule[combinator], stage=stage, known_keys=known_keys)
            return
        children = rule[combinator]
        assert isinstance(children, list) and children, f"{stage}: {combinator} exige uma lista nao vazia"
        for child in children:
            _assert_rule_structure(child, stage=stage, known_keys=known_keys)
        return

    assert "atom" not in rule, f"{stage}: use folha direta; o motor nao aceita wrapper atom"
    source = str(rule.get("source") or "current").strip().lower()
    assert source in {"current", "prior"}, f"{stage}: source condicional desconhecido: {source}"

    key = str(rule.get("key") or rule.get("field") or "").strip()
    assert key, f"{stage}: folha condicional sem key/field"
    if source == "current":
        assert key in known_keys[stage], f"{stage}: condicao referencia campo atual inexistente: {key}"
    else:
        prior_stages = ("t0",) if stage == "t10" else (("t0", "t10") if stage == "t30" else ())
        assert prior_stages, f"{stage}: T0 nao pode depender de resposta prior"
        assert any(key in known_keys[item] for item in prior_stages), (
            f"{stage}: condicao referencia campo anterior inexistente: {key}"
        )

    operator = str(rule.get("operator") or rule.get("op") or "equals").strip().lower()
    assert operator in ATOMIC_OPERATORS, f"{stage}: operador condicional desconhecido: {operator}"
    if operator == "selected_any_except":
        assert isinstance(rule.get("values"), list) and rule["values"], (
            f"{stage}: selected_any_except exige values nao vazio"
        )
    elif operator in {"in", "selected_any", "contains_any"}:
        assert isinstance(rule.get("values"), list), f"{stage}: {operator} exige values"
    elif operator in {"equals", "eq", "not_equals", "neq"}:
        assert "value" in rule, f"{stage}: {operator} exige value"


@pytest.mark.parametrize("stage", ["t0", "t10", "t30"])
def test_active_sfa_schema_is_collective_v2(stage):
    schema = _load_schema(stage)

    assert schema.get("instrument_version") == "collective-v2"
    assert schema.get("sections"), f"{stage}: schema essencial sem secoes"


@pytest.mark.parametrize("stage", ["t0", "t10", "t30"])
def test_active_sfa_schema_omits_imported_identification_and_vaccines(stage):
    fields = _fields(_load_schema(stage))
    keys = {str(field.get("key") or "") for field in fields}

    assert keys.isdisjoint(BANNED_VISIBLE_KEYS), (
        f"{stage}: campos importados ainda visiveis: {sorted(keys & BANNED_VISIBLE_KEYS)}"
    )

    labels = {_normalize(field.get("label")) for field in fields}
    assert "cpf" not in labels
    assert "nome completo" not in labels
    assert not any("sinan" in label for label in labels)
    assert not any(label.startswith("vacina") for label in labels)


@pytest.mark.parametrize("stage", ["t0", "t10", "t30"])
def test_active_sfa_schema_keeps_essential_collective_keys(stage):
    keys = {str(field.get("key") or "") for field in _fields(_load_schema(stage))}
    missing = ESSENTIAL_KEYS[stage] - keys

    assert not missing, f"{stage}: faltam chaves essenciais: {sorted(missing)}"


def test_active_sfa_visible_if_rules_match_the_shared_condition_dsl():
    schemas = {stage: _load_schema(stage) for stage in ("t0", "t10", "t30")}
    known_keys = {
        stage: {str(field.get("key") or "") for field in _fields(schema)}
        for stage, schema in schemas.items()
    }
    conditional_count = 0

    for stage, schema in schemas.items():
        for field in _fields(schema):
            if "visible_if" not in field:
                continue
            conditional_count += 1
            _assert_rule_structure(field["visible_if"], stage=stage, known_keys=known_keys)

    assert conditional_count >= 12, "os instrumentos essenciais devem manter ramificacao condicional relevante"


@pytest.mark.parametrize("stage", ["t0", "t10", "t30"])
def test_detail_questions_only_open_after_their_trigger(stage):
    fields_by_key = {
        str(field.get("key") or ""): field
        for field in _fields(_load_schema(stage))
    }

    missing_rules = {
        key
        for key in CONDITIONAL_KEYS[stage]
        if key not in fields_by_key or not isinstance(fields_by_key[key].get("visible_if"), dict)
    }
    assert not missing_rules, (
        f"{stage}: perguntas de detalhe sem gatilho declarativo: {sorted(missing_rules)}"
    )

    if stage == "t0":
        proxy_rule = fields_by_key["respondent_name"]["visible_if"]
        assert isinstance(proxy_rule.get("all"), list), (
            "respondent_name deve exigir papel preenchido e papel diferente da propria pessoa"
        )
        operators = {
            str(item.get("operator") or item.get("op") or "").lower()
            for item in proxy_rule["all"]
            if isinstance(item, dict)
        }
        assert {"nonempty", "not_equals"} <= operators
