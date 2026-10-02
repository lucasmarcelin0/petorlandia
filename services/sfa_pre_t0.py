"""Ficha digital SINAN para a etapa anterior ao T0."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from flask import current_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SINAN_SCHEMA_PATH = PROJECT_ROOT / "config" / "sfa_sinan_ficha_dengue.json"


def _options(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in items]


YES_NO = _options(("1", "1 - Sim"), ("2", "2 - Não"))
YES_NO_UNKNOWN = _options(("1", "1 - Sim"), ("2", "2 - Não"), ("9", "9 - Ignorado"))
LAB_RESULTS = _options(
    ("1", "1 - Positivo"),
    ("2", "2 - Negativo"),
    ("3", "3 - Inconclusivo"),
    ("4", "4 - Não realizado"),
)


FIELD_SPECS: dict[str, dict] = {
    "Nº": {"key": "ficha_sinan", "type": "text", "required": True, "numeric": True, "minlength": 5, "maxlength": 50},
    "1": {"key": "tipo_notificacao", "type": "fixed", "value": "2", "options": _options(("2", "2 - Individual"))},
    "2": {"key": "agravo", "type": "radio", "required": True, "options": _options(("1", "1 - DENGUE"), ("2", "2 - CHIKUNGUNYA"))},
    "3": {"key": "data_notificacao", "type": "date", "required": True},
    "4": {"key": "uf_notificacao", "type": "text", "maxlength": 2, "uppercase": True},
    "5": {"key": "municipio_notificacao", "type": "paired_text", "maxlength": 120, "extra_key": "codigo_municipio_notificacao", "extra_label": "Código (IBGE)", "extra_maxlength": 7},
    "6": {"key": "unidade_notificante", "type": "paired_text", "maxlength": 180, "extra_key": "codigo_unidade_notificante", "extra_label": "Código", "extra_maxlength": 12},
    "7": {"key": "data_inicio_sintomas", "type": "date", "required": True},
    "8": {"key": "nome", "type": "text", "required": True, "maxlength": 200, "autocomplete": "name"},
    "9": {"key": "data_nascimento", "type": "date"},
    "10": {
        "key": "idade",
        "type": "age",
        "units": _options(("1", "1 - Hora"), ("2", "2 - Dia"), ("3", "3 - Mês"), ("4", "4 - Ano")),
    },
    "11": {"key": "sexo", "type": "radio", "options": _options(("M", "M - Masculino"), ("F", "F - Feminino"), ("I", "I - Ignorado"))},
    "12": {"key": "gestante", "type": "radio", "options": _options(
        ("1", "1 - 1º Trimestre"), ("2", "2 - 2º Trimestre"), ("3", "3 - 3º Trimestre"),
        ("4", "4 - Idade gestacional ignorada"), ("5", "5 - Não"), ("6", "6 - Não se aplica"), ("9", "9 - Ignorado"),
    )},
    "13": {"key": "raca_cor", "type": "radio", "options": _options(
        ("1", "1 - Branca"), ("2", "2 - Preta"), ("3", "3 - Amarela"),
        ("4", "4 - Parda"), ("5", "5 - Indígena"), ("9", "9 - Ignorado"),
    )},
    "14": {"key": "escolaridade", "type": "radio", "options": _options(
        ("0", "0 - Analfabeto"),
        ("1", "1 - 1ª a 4ª série incompleta do EF (antigo primário ou 1º grau)"),
        ("2", "2 - 4ª série completa do EF (antigo primário ou 1º grau)"),
        ("3", "3 - 5ª à 8ª série incompleta do EF (antigo ginásio ou 1º grau)"),
        ("4", "4 - Ensino fundamental completo (antigo ginásio ou 1º grau)"),
        ("5", "5 - Ensino médio incompleto (antigo colegial ou 2º grau)"),
        ("6", "6 - Ensino médio completo (antigo colegial ou 2º grau)"),
        ("7", "7 - Educação superior incompleta"), ("8", "8 - Educação superior completa"),
        ("9", "9 - Ignorado"), ("10", "10 - Não se aplica"),
    )},
    "15": {"key": "cartao_sus", "type": "text", "numeric": True, "maxlength": 20},
    "16": {"key": "nome_mae", "type": "text", "maxlength": 200},
    "17": {"key": "uf_residencia", "type": "text", "maxlength": 2, "uppercase": True},
    "18": {"key": "municipio_residencia", "type": "paired_text", "maxlength": 120, "extra_key": "codigo_municipio_residencia", "extra_label": "Código (IBGE)", "extra_maxlength": 7},
    "19": {"key": "distrito_residencia", "type": "text", "maxlength": 120},
    "20": {"key": "bairro", "type": "text", "maxlength": 120},
    "21": {"key": "logradouro", "type": "paired_text", "maxlength": 180, "extra_key": "codigo_logradouro", "extra_label": "Código", "extra_maxlength": 12},
    "22": {"key": "numero_residencia", "type": "text", "maxlength": 30},
    "23": {"key": "complemento", "type": "text", "maxlength": 120},
    "24": {"key": "geo_campo_1", "type": "text", "maxlength": 80},
    "25": {"key": "geo_campo_2", "type": "text", "maxlength": 80},
    "26": {"key": "ponto_referencia", "type": "text", "maxlength": 160},
    "27": {"key": "cep", "type": "text", "numeric": True, "maxlength": 9},
    "28": {"key": "telefone", "type": "tel", "maxlength": 25, "autocomplete": "tel"},
    "29": {"key": "zona", "type": "radio", "options": _options(("1", "1 - Urbana"), ("2", "2 - Rural"), ("3", "3 - Periurbana"), ("9", "9 - Ignorado"))},
    "30": {"key": "pais_residencia", "type": "text", "maxlength": 100},
    "31": {"key": "data_investigacao", "type": "date"},
    "32": {"key": "ocupacao", "type": "text", "maxlength": 160},
    "33": {"key": "sinais_clinicos", "type": "matrix", "options": YES_NO, "items": [
        ("febre", "Febre"), ("mialgia", "Mialgia"), ("cefaleia", "Cefaleia"), ("exantema", "Exantema"),
        ("vomito", "Vômito"), ("nauseas", "Náuseas"), ("dor_nas_costas", "Dor nas costas"),
        ("conjuntivite", "Conjuntivite"), ("artrite", "Artrite"), ("artralgia_intensa", "Artralgia intensa"),
        ("petequias", "Petéquias"), ("leucopenia", "Leucopenia"),
        ("prova_laco_positiva", "Prova do laço positiva"), ("dor_retroorbital", "Dor retroorbital"),
    ]},
    "34": {"key": "doencas_preexistentes", "type": "matrix", "options": YES_NO_UNKNOWN, "items": [
        ("diabetes", "Diabetes"), ("doencas_hematologicas", "Doenças hematológicas"),
        ("hepatopatias", "Hepatopatias"), ("doenca_renal_cronica", "Doença renal crônica"),
        ("hipertensao_arterial", "Hipertensão arterial"), ("doenca_acido_peptica", "Doença ácido-péptica"),
        ("doencas_autoimunes", "Doenças auto-imunes"),
    ]},
    "35": {"key": "chikungunya_s1_data", "type": "date"},
    "36": {"key": "chikungunya_s2_data", "type": "date"},
    "37": {"key": "prnt_data", "type": "date"},
    "38": {"key": "prnt_resultado", "type": "test_result", "samples": [("s1", "S1"), ("s2", "S2"), ("prnt", "PRNT")], "options": _options(
        ("1", "1 - Reagente"), ("2", "2 - Não Reagente"), ("3", "3 - Inconclusivo"), ("4", "4 - Não Realizado"),
    )},
    "39": {"key": "dengue_igm_data", "type": "date"},
    "40": {"key": "dengue_igm_resultado", "type": "radio", "options": LAB_RESULTS},
    "41": {"key": "ns1_data_coleta", "type": "date"},
    "42": {"key": "ns1_resultado", "type": "radio", "options": LAB_RESULTS},
    "43": {"key": "isolamento_data", "type": "date"},
    "44": {"key": "isolamento_resultado", "type": "radio", "options": LAB_RESULTS},
    "45": {"key": "rt_pcr_data", "type": "date"},
    "46": {"key": "rt_pcr_resultado", "type": "radio", "options": LAB_RESULTS},
    "47": {"key": "sorotipo", "type": "radio", "options": _options(("1", "1 - DENV 1"), ("2", "2 - DENV 2"), ("3", "3 - DENV 3"), ("4", "4 - DENV 4"))},
    "48": {"key": "histopatologia_resultado", "type": "radio", "options": _options(
        ("1", "1 - Compatível"), ("2", "2 - Incompatível"), ("3", "3 - Inconclusivo"), ("4", "4 - Não realizado"),
    )},
    "49": {"key": "imunohistoquimica_resultado", "type": "radio", "options": LAB_RESULTS},
    "50": {"key": "hospitalizacao", "type": "radio", "options": YES_NO_UNKNOWN},
    "51": {"key": "data_internacao", "type": "date"},
    "52": {"key": "uf_hospital", "type": "text", "maxlength": 2, "uppercase": True},
    "53": {"key": "municipio_hospital", "type": "paired_text", "maxlength": 120, "extra_key": "codigo_municipio_hospital", "extra_label": "Código (IBGE)", "extra_maxlength": 7},
    "54": {"key": "nome_hospital", "type": "paired_text", "maxlength": 180, "extra_key": "codigo_hospital", "extra_label": "Código", "extra_maxlength": 12},
    "55": {"key": "telefone_hospital", "type": "tel", "maxlength": 25},
    "56": {"key": "caso_autoctone", "type": "radio", "options": _options(("1", "1 - Sim"), ("2", "2 - Não"), ("3", "3 - Indeterminado"))},
    "57": {"key": "uf_local_infeccao", "type": "text", "maxlength": 2, "uppercase": True},
    "58": {"key": "pais_local_infeccao", "type": "text", "maxlength": 100},
    "59": {"key": "municipio_local_infeccao", "type": "paired_text", "maxlength": 120, "extra_key": "codigo_municipio_local_infeccao", "extra_label": "Código (IBGE)", "extra_maxlength": 7},
    "60": {"key": "distrito_local_infeccao", "type": "text", "maxlength": 120},
    "61": {"key": "bairro_local_infeccao", "type": "text", "maxlength": 120},
    "62": {"key": "classificacao", "type": "radio", "options": _options(
        ("5", "5 - Descartado"), ("10", "10 - Dengue"), ("11", "11 - Dengue com Sinais de Alarme"),
        ("12", "12 - Dengue Grave"), ("13", "13 - Chikungunya"),
    )},
    "63": {"key": "criterio_confirmacao", "type": "radio", "options": _options(
        ("1", "1 - Laboratório"), ("2", "2 - Clínico-Epidemiológico"), ("3", "3 - Em investigação"),
    )},
    "64": {"key": "apresentacao_clinica", "type": "radio", "options": _options(("1", "1 - Aguda"), ("2", "2 - Crônica"))},
    "65": {"key": "evolucao_caso", "type": "radio", "options": _options(
        ("1", "1 - Cura"), ("2", "2 - Óbito pelo agravo"), ("3", "3 - Óbito por outras causas"),
        ("4", "4 - Óbito em investigação"), ("9", "9 - Ignorado"),
    )},
    "66": {"key": "data_obito", "type": "date"},
    "67": {"key": "data_encerramento", "type": "date"},
    "68": {"key": "sinais_alarme", "type": "flag_matrix", "options": YES_NO_UNKNOWN, "items": [
        ("hipotensao_postural_lipotimia", "Hipotensão postural e/ou lipotímia"),
        ("queda_plaquetas", "Queda abrupta de plaquetas"), ("vomitos_persistentes", "Vômitos persistentes"),
        ("dor_abdominal", "Dor abdominal intensa e contínua"), ("letargia_irritabilidade", "Letargia ou irritabilidade"),
        ("sangramento_mucosa", "Sangramento de mucosa/outras hemorragias"),
        ("hematocrito_progressivo", "Aumento progressivo do hematócrito"),
        ("hepatomegalia", "Hepatomegalia >= 2cm"), ("acumulo_liquidos", "Acúmulo de líquidos"),
    ]},
    "69": {"key": "data_inicio_sinais_alarme", "type": "date"},
    "70": {"key": "dengue_grave", "type": "severity", "options": YES_NO_UNKNOWN, "groups": [
        ("Extravasamento grave de plasma", [
            ("pulso_debil", "Pulso débil ou indetectável"), ("pa_convergente", "PA convergente <= 20 mmHg"),
            ("tempo_enchimento_capilar", "Tempo de enchimento capilar"),
            ("acumulo_liquidos_insuficiencia", "Acúmulo de líquidos com insuficiência respiratória"),
            ("taquicardia", "Taquicardia"), ("extremidades_frias", "Extremidades frias"),
            ("hipotensao_tardia", "Hipotensão arterial em fase tardia"),
        ]),
        ("Sangramento grave", [
            ("hematemese", "Hematêmese"), ("melena", "Melena"),
            ("metrorragia_volumosa", "Metrorragia volumosa"), ("sangramento_snc", "Sangramento do SNC"),
        ]),
        ("Comprometimento grave de órgãos", [
            ("ast_alt", "AST/ALT > 1.000"), ("miocardite", "Miocardite"),
            ("alteracao_consciencia", "Alteração da consciência"), ("outros_orgaos", "Outros órgãos, especificar"),
        ]),
    ]},
    "71": {"key": "data_inicio_sinais_gravidade", "type": "date"},
    "OBS": {"key": "observacoes_adicionais", "type": "textarea", "maxlength": 3000},
    "INV": {"key": "investigador", "type": "investigator", "items": [
        ("municipio_unidade", "Município/Unidade de Saúde", 180),
        ("codigo_unidade", "Cód. da Unid. de Saúde", 30),
        ("nome", "Nome", 160), ("funcao", "Função", 120), ("assinatura", "Assinatura", 160),
    ]},
}


def _mover_agravo_para_primeira_pagina(sections: list[dict]) -> None:
    """Dengue x Chikungunya (campo 2) é a primeira escolha da ficha: sobe para a página do número da notificação."""
    if not sections:
        return
    for section in sections[1:]:
        for position, field in enumerate(section["fields"]):
            if field.get("key") == "agravo":
                sections[0]["fields"].append(section["fields"].pop(position))
                return


def carregar_esquema_pre_t0() -> dict:
    """Combina a redação da ficha fonte com os controles eletrônicos."""
    try:
        raw = json.loads(SINAN_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        current_app.logger.exception("Não foi possível carregar o esquema da ficha SINAN.")
        raise RuntimeError("Esquema da ficha indisponível.") from exc

    sections = []
    for source_section in raw.get("secoes", []):
        section = {"title": source_section.get("secao", ""), "fields": []}
        for source_field in source_section.get("campos", []):
            number = str(source_field.get("numero") or "").strip()
            label = str(source_field.get("campo") or "").strip()
            lookup = number if number in FIELD_SPECS else ("OBS" if label == "Observações Adicionais" else "INV" if not number else "")
            spec = FIELD_SPECS.get(lookup)
            if not spec:
                raise RuntimeError(f"Campo SINAN sem controle eletrônico definido: {number or label}")
            section["fields"].append({**source_field, **spec, "number": number})
        sections.append(section)
    _mover_agravo_para_primeira_pagina(sections)
    return {"title": raw.get("titulo", "Ficha de Investigação"), "version": raw.get("versao", ""),
            "definitions": raw.get("definicoes", []), "sections": sections}


class CampoInvalido(ValueError):
    """ValueError que também diz qual campo (atributo name do input) precisa de correção."""

    def __init__(self, mensagem: str, campo: str = ""):
        super().__init__(mensagem)
        self.campo = campo


_SEPARADORES_NUMERICOS = re.compile(r"[\s.\-–—/()]")


def _field_text(form, name: str, maximum: int, *, required: bool = False, numeric: bool = False, uppercase: bool = False) -> str:
    value = str(form.get(name) or "").strip()
    if numeric:
        # CEP "14620-000", cartão SUS com espaços etc.: o preenchimento automático do navegador
        # insere separadores; eles são descartados em vez de travar o envio.
        value = _SEPARADORES_NUMERICOS.sub("", value)
    if required and not value:
        raise CampoInvalido("Preencha os campos obrigatórios indicados antes de enviar.", name)
    if len(value) > maximum:
        raise CampoInvalido("Um dos campos ultrapassou o limite de caracteres.", name)
    if numeric and value and not re.fullmatch(r"\d+", value):
        raise CampoInvalido("Confira os campos numéricos. Use somente números.", name)
    if uppercase:
        value = value.upper()
    return value


def _field_date(form, name: str, *, required: bool = False) -> str:
    value = str(form.get(name) or "").strip()
    if not value:
        if required:
            raise CampoInvalido("Preencha os campos obrigatórios indicados antes de enviar.", name)
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError as exc:
        raise CampoInvalido("Confira as datas informadas.", name) from exc


def _field_choice(form, name: str, choices: list[dict[str, str]], *, required: bool = False) -> str:
    value = str(form.get(name) or "").strip()
    allowed = {item["value"] for item in choices}
    if required and not value:
        raise CampoInvalido("Preencha os campos obrigatórios indicados antes de enviar.", name)
    if value and value not in allowed:
        raise CampoInvalido("Uma das opções enviadas não pertence a esta ficha.", name)
    return value


def _answer_field(form, field: dict) -> object:
    kind, key = field["type"], field["key"]
    if kind == "fixed":
        return field["value"]
    if kind in {"text", "tel"}:
        value = _field_text(form, key, field.get("maxlength", 160), required=field.get("required", False),
                            numeric=field.get("numeric", False), uppercase=field.get("uppercase", False))
        if field.get("minlength") and len(value) < field["minlength"]:
            raise CampoInvalido("Informe o número da ficha SINAN com pelo menos cinco dígitos.", key)
        return value
    if kind == "paired_text":
        return {
            "valor": _field_text(form, key, field.get("maxlength", 160), required=field.get("required", False)),
            "codigo": _field_text(form, field["extra_key"], field.get("extra_maxlength", 12), numeric=True),
        }
    if kind == "date":
        return _field_date(form, key, required=field.get("required", False))
    if kind == "radio":
        return _field_choice(form, key, field.get("options", []), required=field.get("required", False))
    if kind == "age":
        value = _field_text(form, "idade_valor", 7, numeric=True)
        unit = _field_choice(form, "idade_unidade", field["units"])
        if value and not unit:
            raise CampoInvalido("Selecione a unidade da idade informada.", "idade_unidade")
        return {"valor": value, "unidade": unit}
    if kind == "matrix":
        answers = {}
        for item_key, _label in field["items"]:
            value = _field_choice(form, f"{key}__{item_key}", field["options"])
            if value:
                answers[item_key] = value
        return answers
    if kind == "test_result":
        # Um resultado por exame (S1, S2, PRNT). "amostras" e "resultado" seguem existindo para
        # fichas e análises antigas: amostras = exames com resultado; resultado = o do exame mais conclusivo.
        resultados = {}
        for sample_key, _label in field["samples"]:
            value = _field_choice(form, f"{key}__res__{sample_key}", field["options"])
            if value:
                resultados[sample_key] = value
        if resultados:
            amostras = [sample_key for sample_key, _label in field["samples"] if sample_key in resultados]
            principal = next((resultados[k] for k in ("prnt", "s2", "s1") if k in resultados), "")
            return {"amostras": amostras, "resultado": principal, "resultados": resultados}
        samples = []
        for sample_key, _label in field["samples"]:
            value = str(form.get(f"{key}__{sample_key}") or "").strip()
            if value not in {"", "1"}:
                raise CampoInvalido("Uma das opções enviadas não pertence a esta ficha.", f"{key}__{sample_key}")
            if value == "1":
                samples.append(sample_key)
        result = _field_choice(form, key, field["options"])
        return {"amostras": samples, "resultado": result, "resultados": {}}
    if kind == "flag_matrix":
        status = _field_choice(form, key, field["options"])
        items = []
        for item_key, _label in field["items"]:
            value = str(form.get(f"{key}__{item_key}") or "").strip()
            if value not in {"", "1"}:
                raise ValueError("Uma das opções enviadas não pertence a esta ficha.")
            if value == "1":
                items.append(item_key)
        return {"status": status, "sinais_marcados": items}
    if kind == "severity":
        status = _field_choice(form, key, field["options"])
        answers = {}
        for _group, items in field["groups"]:
            for item_key, _label in items:
                value = str(form.get(f"{key}__{item_key}") or "").strip()
                if value not in {"", "1"}:
                    raise ValueError("Uma das opções enviadas não pertence a esta ficha.")
                if value == "1":
                    answers[item_key] = "1"
        return {"status": status, "sinais_marcados": answers,
                "outros_orgaos_especificar": _field_text(form, "outros_orgaos_especificar", 180)}
    if kind == "textarea":
        return _field_text(form, key, field.get("maxlength", 3000))
    if kind == "investigator":
        return {item_key: _field_text(form, f"{key}__{item_key}", maximum) for item_key, _label, maximum in field["items"]}
    raise ValueError("A ficha contém um controle desconhecido.")


def coletar_respostas_pre_t0(form, schema: dict | None = None) -> dict:
    schema = schema or carregar_esquema_pre_t0()
    answers = {}
    for section in schema["sections"]:
        for field in section["fields"]:
            if field["key"] in answers:
                raise RuntimeError("A ficha contém identificadores duplicados.")
            answers[field["key"]] = _answer_field(form, field)
    return answers


def _option_label(field: dict, value: str) -> str:
    return next((item["label"].split(" - ", 1)[-1] for item in field.get("options", []) if item["value"] == value), "")


def salvar_ficha_pre_t0(answers: dict) -> dict:
    """Cria ou complementa o caso pendente de T0 a partir da ficha digital."""
    from extensions import db
    from models.sfa import SfaAuditoria, SfaPaciente, SfaSinanLog
    from time_utils import now_in_brazil
    from services.sfa_service import (
        atualizar_operacional_paciente,
        normalizar_dados_estruturados_sinan,
        normalizar_telefone,
        proximo_id_estudo,
    )

    ficha = str(answers.get("ficha_sinan") or "").strip()
    ficha_digits = re.sub(r"\D", "", ficha)
    if len(ficha_digits) < 5:
        raise CampoInvalido("Informe o número da ficha SINAN com pelo menos cinco dígitos.", "ficha_sinan")
    dedup_key = f"FICHA-{ficha_digits}"
    full_key = "formulario_pre_t0"

    def answer_value(key: str) -> str:
        value = answers.get(key)
        if isinstance(value, dict):
            value = value.get("valor")
        return str(value or "")

    existing_log = SfaSinanLog.query.filter_by(chave_dedup=dedup_key).with_for_update().first()
    existing_patient = None
    if existing_log and existing_log.id_estudo_vinculado:
        existing_patient = SfaPaciente.query.filter_by(id_estudo=existing_log.id_estudo_vinculado).first()
    if existing_patient is None:
        existing_patient = SfaPaciente.query.filter_by(ficha_sinan=ficha).first()

    old_json = {}
    if existing_log and existing_log.dados_json:
        try:
            loaded = json.loads(existing_log.dados_json)
            old_json = loaded if isinstance(loaded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            old_json = {}
        if full_key in old_json:
            raise ValueError("Esta ficha já foi enviada. A equipe pode conferir o registro no SFA.")

    created = existing_patient is None
    patient = existing_patient
    if created:
        patient = SfaPaciente(
            id_estudo=proximo_id_estudo(),
            ficha_sinan=ficha,
            nome=answers.get("nome") or "",
            data_nascimento=answers.get("data_nascimento") or "",
            telefone=normalizar_telefone(answers.get("telefone") or ""),
            bairro=answers.get("bairro") or "",
            endereco=" ".join(part for part in [answer_value("logradouro"), answers.get("numero_residencia"), answers.get("complemento")] if part).strip()[:300],
            grupo="PENDENTE_REVISAO",
            status_t0="SINAN_Aguardando_T0",
            status_geral="SINAN_Notificado",
        )
        patient.gerar_token()
        db.session.add(patient)
        db.session.flush()
    else:
        patient_values = {
            "ficha_sinan": ficha,
            "nome": answers.get("nome"),
            "data_nascimento": answers.get("data_nascimento"),
            "telefone": normalizar_telefone(answers.get("telefone") or ""),
            "bairro": answers.get("bairro"),
            "endereco": " ".join(part for part in [answer_value("logradouro"), answers.get("numero_residencia"), answers.get("complemento")] if part).strip()[:300],
        }
        for field, value in patient_values.items():
            if value and not str(getattr(patient, field, "") or "").strip():
                setattr(patient, field, value)
        if not patient.status_t0:
            patient.status_t0 = "SINAN_Aguardando_T0"
        if not patient.status_geral:
            patient.status_geral = "SINAN_Notificado"

    fields_by_number = {}
    schema = carregar_esquema_pre_t0()
    for section in schema["sections"]:
        for field in section["fields"]:
            if field["number"]:
                fields_by_number[field["number"]] = field

    symptoms_field = fields_by_number["33"]
    symptoms = [label for key, label in symptoms_field["items"] if answers.get("sinais_clinicos", {}).get(key) == "1"]
    conditions_field = fields_by_number["34"]
    conditions = [label for key, label in conditions_field["items"] if answers.get("doencas_preexistentes", {}).get(key) == "1"]
    ns1_date = answers.get("ns1_data_coleta") or ""
    ns1_result = _option_label(fields_by_number["42"], str(answers.get("ns1_resultado") or ""))
    analytic = {
        "numero_controle": ficha,
        "agravo": _option_label(fields_by_number["2"], str(answers.get("agravo") or "")),
        "data_investigacao": answers.get("data_investigacao") or "",
        "unidade_notificante": answer_value("unidade_notificante"),
        "sexo": _option_label(fields_by_number["11"], str(answers.get("sexo") or "")),
        "idade_anos": answers.get("idade", {}).get("valor") if answers.get("idade", {}).get("unidade") == "4" else None,
        "raca_cor": _option_label(fields_by_number["13"], str(answers.get("raca_cor") or "")),
        "zona": _option_label(fields_by_number["29"], str(answers.get("zona") or "")),
        "ocupacao": answers.get("ocupacao") or "",
        "sintomas": symptoms,
        "comorbidades": conditions,
        "ns1_data_coleta": ns1_date,
        "ns1_resultado": ns1_result,
    }
    structured = normalizar_dados_estruturados_sinan(analytic)
    if answers.get("doencas_preexistentes"):
        structured["comorbidades_status"] = "Informado na ficha digital"
    structured[full_key] = {
        "versao": "sinan-online-svs-2016-pre-t0-2026-09",
        "recebido_em": now_in_brazil().isoformat(timespec="seconds"),
        "respostas": answers,
    }

    log_entry = existing_log or SfaSinanLog(chave_dedup=dedup_key)
    log_entry.ficha_sinan = log_entry.ficha_sinan or ficha
    log_entry.nome = log_entry.nome or answers.get("nome") or ""
    log_entry.telefone = log_entry.telefone or normalizar_telefone(answers.get("telefone") or "")
    log_entry.bairro = log_entry.bairro or answers.get("bairro") or ""
    log_entry.data_notificacao = log_entry.data_notificacao or answers.get("data_notificacao") or ""
    log_entry.data_inicio_sintomas = log_entry.data_inicio_sintomas or answers.get("data_inicio_sintomas") or ""
    log_entry.id_estudo_vinculado = patient.id_estudo
    existing_analytic = normalizar_dados_estruturados_sinan(old_json)
    existing_analytic.update({key: value for key, value in structured.items() if key != full_key})
    existing_analytic[full_key] = structured[full_key]
    log_entry.dados_json = json.dumps(existing_analytic, ensure_ascii=False, sort_keys=True)
    log_entry.fonte_complementar = "formulario_digital_pre_t0"
    log_entry.revisao_status = "TRANSCRITO"
    if not log_entry.grupo:
        log_entry.grupo = "PENDENTE_REVISAO"
    db.session.add(log_entry)

    atualizar_operacional_paciente(patient)
    db.session.add(SfaAuditoria(
        nivel="INFO",
        categoria="SINAN_PRE_T0_DIGITAL",
        funcao="salvar_ficha_pre_t0",
        id_estudo=patient.id_estudo,
        mensagem="Ficha SINAN digital recebida antes do T0.",
        detalhes_json=json.dumps({"campos": len(answers), "novo_caso": created}, ensure_ascii=False),
    ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Falha ao gravar ficha SINAN digital pré-T0.")
        raise RuntimeError("Não foi possível registrar a ficha agora. Tente novamente em instantes.")
    return {"id_estudo": patient.id_estudo, "created": created}


def obter_ficha_pre_t0(id_estudo: str) -> dict | None:
    """Monta uma leitura interna da ficha completa sem expor os campos à análise."""
    from models.sfa import SfaSinanLog

    schema = carregar_esquema_pre_t0()
    logs = (SfaSinanLog.query
            .filter_by(id_estudo_vinculado=id_estudo)
            .order_by(SfaSinanLog.timestamp_importacao.desc(), SfaSinanLog.id.desc())
            .all())
    for log_entry in logs:
        try:
            payload = json.loads(log_entry.dados_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        full_form = payload.get("formulario_pre_t0") if isinstance(payload, dict) else None
        if not isinstance(full_form, dict) or not isinstance(full_form.get("respostas"), dict):
            continue
        answers = full_form["respostas"]

        def option_text(options: list[dict], value: object) -> str:
            value = str(value or "")
            return next((item["label"] for item in options if item["value"] == value), "Não informado")

        def present(field: dict) -> str:
            key, kind = field["key"], field["type"]
            value = answers.get(key)
            if kind == "fixed":
                return option_text(field.get("options", []), field.get("value"))
            if kind in {"text", "tel", "date", "textarea"}:
                return str(value or "Não informado")
            if kind == "paired_text":
                value = value if isinstance(value, dict) else {}
                details = [str(value.get("valor") or "Não informado")]
                if value.get("codigo"):
                    details.append(f"{field['extra_label']}: {value['codigo']}")
                return " · ".join(details)
            if kind == "radio":
                return option_text(field.get("options", []), value)
            if kind == "age":
                value = value if isinstance(value, dict) else {}
                amount = str(value.get("valor") or "").strip()
                unit = option_text(field.get("units", []), value.get("unidade"))
                return f"{amount} · {unit}" if amount else "Não informado"
            if kind == "matrix":
                value = value if isinstance(value, dict) else {}
                lines = [f"{label}: {option_text(field['options'], value.get(item_key))}"
                         for item_key, label in field["items"]]
                return "; ".join(lines) if any(item_key in value for item_key, _label in field["items"]) else "Não informado"
            if kind == "flag_matrix":
                value = value if isinstance(value, dict) else {}
                status = option_text(field["options"], value.get("status"))
                labels = dict(field["items"])
                marked = [labels[item] for item in value.get("sinais_marcados", []) if item in labels]
                return status + (" · " + ", ".join(marked) if marked else "")
            if kind == "test_result":
                value = value if isinstance(value, dict) else {}
                samples = dict(field["samples"])
                por_exame = value.get("resultados") if isinstance(value.get("resultados"), dict) else {}
                if por_exame:
                    return "; ".join(f"{label}: {option_text(field['options'], por_exame[key_])}"
                                     for key_, label in field["samples"] if key_ in por_exame)
                marked = [samples[item] for item in value.get("amostras", []) if item in samples]
                result = option_text(field["options"], value.get("resultado"))
                return (", ".join(marked) + " · " if marked else "") + result
            if kind == "severity":
                value = value if isinstance(value, dict) else {}
                status = option_text(field["options"], value.get("status"))
                labels = {item_key: label for _group, items in field["groups"] for item_key, label in items}
                marks = value.get("sinais_marcados") if isinstance(value.get("sinais_marcados"), dict) else {}
                marked = [labels[item] for item, enabled in marks.items() if enabled == "1" and item in labels]
                details = str(value.get("outros_orgaos_especificar") or "").strip()
                if details:
                    marked.append(f"Outros órgãos: {details}")
                return status + (" · " + ", ".join(marked) if marked else "")
            if kind == "investigator":
                value = value if isinstance(value, dict) else {}
                return "; ".join(f"{label}: {value.get(item_key) or 'Não informado'}"
                                  for item_key, label, _maximum in field["items"])
            return "Não informado"

        sections = []
        for section in schema["sections"]:
            sections.append({
                "title": section["title"],
                "fields": [{"number": field["number"], "label": field["campo"], "value": present(field)}
                           for field in section["fields"]],
            })
        timestamp = log_entry.timestamp_importacao
        received_at = full_form.get("recebido_em")
        if received_at:
            try:
                timestamp = datetime.fromisoformat(str(received_at))
            except ValueError:
                pass
        if timestamp and timestamp.tzinfo is not None:
            from time_utils import coerce_to_brazil_tz
            timestamp = coerce_to_brazil_tz(timestamp)
        return {
            "sections": sections,
            "version": full_form.get("versao", ""),
            "submitted_at": timestamp.strftime("%d/%m/%Y %H:%M") if timestamp else "",
            "ficha_sinan": log_entry.ficha_sinan or "",
        }
    return None
