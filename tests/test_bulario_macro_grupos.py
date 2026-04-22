"""Testes do agrupamento macro do bulário (services/bulario.py).

Razão: são 10 buckets clínicos consumindo >170 classificações reais da
VetSmart. Qualquer ajuste nos regex pode silenciosamente jogar uma classe
inteira em "Outros" — e o vet perde a capacidade de filtrar. Estes testes
travam o mapeamento das classes mais importantes.
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.bulario import classificar_em_macro_grupo, construir_macro_grupos


# ── Antimicrobiano ──────────────────────────────────────────────────────────

def test_antibiotico_vai_para_antimicrobiano():
    assert classificar_em_macro_grupo("Antibiótico") == "antimicrobiano"
    assert classificar_em_macro_grupo("Antibacteriano") == "antimicrobiano"
    assert classificar_em_macro_grupo("Antifúngico") == "antimicrobiano"
    assert classificar_em_macro_grupo("Sulfonamida") == "antimicrobiano"
    assert classificar_em_macro_grupo("Quinolona") == "antimicrobiano"


# ── Antiparasitário ─────────────────────────────────────────────────────────

def test_antiparasitarios():
    assert classificar_em_macro_grupo("Antiparasitário") == "antiparasitario"
    assert classificar_em_macro_grupo("Endectocida") == "antiparasitario"
    assert classificar_em_macro_grupo("Carrapaticida") == "antiparasitario"
    assert classificar_em_macro_grupo("Vermífugo") == "antiparasitario"
    assert classificar_em_macro_grupo("Leishmanicida") == "antiparasitario"


# ── Vacina ──────────────────────────────────────────────────────────────────

def test_todas_as_vacinas_vao_para_vacina():
    # A motivação original do usuário: "há várias vacinas diferentes sendo
    # filtradas. poderíamos ter só um filtro 'vacina' que mostra todas".
    for c in [
        "Vacina V8", "Vacina V10", "Vacina Antirrábica",
        "Vacina tríplice felina", "Vacina contra leptospirose",
        "Imunobiológico", "Imunomodulador", "Soro antitetânico",
    ]:
        assert classificar_em_macro_grupo(c) == "vacina", c


# ── Anti-inflamatório ───────────────────────────────────────────────────────

def test_anti_inflamatorios_e_analgesicos():
    assert classificar_em_macro_grupo("Anti-inflamatório Esteroidal") == "anti_inflamatorio"
    assert classificar_em_macro_grupo("Anti-inflamatório Não Esteroidal") == "anti_inflamatorio"
    assert classificar_em_macro_grupo("AINE") == "anti_inflamatorio"
    assert classificar_em_macro_grupo("Analgésico") == "anti_inflamatorio"
    assert classificar_em_macro_grupo("Opioide") == "anti_inflamatorio"


# ── Cardiovascular ──────────────────────────────────────────────────────────

def test_cardiovascular():
    assert classificar_em_macro_grupo("Cardiotônico") == "cardiovascular"
    assert classificar_em_macro_grupo("Anti-hipertensivo") == "cardiovascular"
    assert classificar_em_macro_grupo("Diurético") == "cardiovascular"
    assert classificar_em_macro_grupo("Antiarrítmico") == "cardiovascular"


# ── Endócrino ───────────────────────────────────────────────────────────────

def test_endocrino():
    assert classificar_em_macro_grupo("Hormônio") == "endocrino"
    assert classificar_em_macro_grupo("Insulina") == "endocrino"
    assert classificar_em_macro_grupo("Tireoideano") == "endocrino"
    assert classificar_em_macro_grupo("Anticoncepcional") == "endocrino"


# ── Respiratório ────────────────────────────────────────────────────────────

def test_respiratorio():
    assert classificar_em_macro_grupo("Broncodilatador") == "respiratorio"
    assert classificar_em_macro_grupo("Mucolítico") == "respiratorio"
    assert classificar_em_macro_grupo("Antitussígeno") == "respiratorio"


# ── SNC ─────────────────────────────────────────────────────────────────────

def test_snc():
    assert classificar_em_macro_grupo("Anticonvulsivante") == "snc"
    assert classificar_em_macro_grupo("Ansiolítico") == "snc"
    assert classificar_em_macro_grupo("Anestésico") == "snc"
    assert classificar_em_macro_grupo("Sedativo") == "snc"


# ── GI ──────────────────────────────────────────────────────────────────────

def test_gastrointestinal():
    assert classificar_em_macro_grupo("Antiemético") == "gastrointestinal"
    assert classificar_em_macro_grupo("Antidiarreico") == "gastrointestinal"
    assert classificar_em_macro_grupo("Hepatoprotetor") == "gastrointestinal"
    assert classificar_em_macro_grupo("Protetor gástrico") == "gastrointestinal"


# ── Catch-all "outros" ─────────────────────────────────────────────────────

def test_catch_all_outros():
    # Coisas que não cabem em nenhum dos 9 macros clínicos específicos
    assert classificar_em_macro_grupo("Dermatológico") == "outros"
    assert classificar_em_macro_grupo("Suplemento alimentar") == "outros"
    assert classificar_em_macro_grupo("Vitamina") == "outros"
    assert classificar_em_macro_grupo("Abortivo") == "outros"  # raro, sem match
    assert classificar_em_macro_grupo("") == "outros"
    assert classificar_em_macro_grupo(None) == "outros"


# ── Regressões críticas ─────────────────────────────────────────────────────

def test_nao_confunde_anti_inflamatorio_com_antimicrobiano():
    # Regressão: se "anti-" aparecer antes de algum regex de antimicrobiano,
    # não pode roubar o match. Ordem dos macros importa.
    assert classificar_em_macro_grupo("Anti-inflamatório Esteroidal") == "anti_inflamatorio"


def test_anti_helmintico_nao_vira_anti_inflamatorio():
    # "Anti-helmíntico" tem "anti-" mas é antiparasitário.
    assert classificar_em_macro_grupo("Anti-helmíntico") == "antiparasitario"


# ── construir_macro_grupos ─────────────────────────────────────────────────

def test_construir_macro_grupos_agrega_e_marca_ativo():
    classes = [
        "Antibiótico", "Antifúngico",
        "Vacina V8", "Vacina V10", "Vacina Antirrábica",
        "Anti-inflamatório Esteroidal",
        "Dermatológico",
    ]
    grupos, ativo = construir_macro_grupos(classes, classe_ativa="Vacina V10")

    # Só volta macros com >=1 subclasse → esperamos 4 (antimic, vacina,
    # anti_inflam, outros). Não retorna macros vazios.
    keys = [g["key"] for g in grupos]
    assert "antimicrobiano" in keys
    assert "vacina" in keys
    assert "anti_inflamatorio" in keys
    assert "outros" in keys
    # Nenhum dos demais, porque não foram populados.
    assert "cardiovascular" not in keys

    # O drawer da vacina deve estar marcado ativo (para a UI abrir).
    vacina = next(g for g in grupos if g["key"] == "vacina")
    assert vacina["is_active"] is True
    assert vacina["count"] == 3
    assert "Vacina V10" in vacina["subclasses"]
    assert ativo == "vacina"


def test_construir_macro_grupos_sem_filtro_nao_marca_ninguem_ativo():
    grupos, ativo = construir_macro_grupos(["Antibiótico"], classe_ativa=None)
    assert ativo is None
    assert all(g["is_active"] is False for g in grupos)
