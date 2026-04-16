"""
vetsmart_discover.py  (v2)
==========================
Descobre a estrutura de dados do VetSmart Parse Server.

URL real do Parse Server (já descoberta via Network):
    https://parse.vetsmart.com.br/parse

COMO USAR:
    python scripts/vetsmart_discover.py

Resultado salvo em: scripts/vetsmart_raw/schema_discovery.json
"""

import json, sys, time
from pathlib import Path

import requests

# Headers de navegador real para bypassar Cloudflare WAF
BROWSER_HEADERS = {
    "User-Agent":         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/147.0.0.0 Safari/537.36",
    "sec-ch-ua":          '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Accept-Language":    "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept":             "*/*",
    "Origin":             "https://prontuario.vetsmart.com.br",
    "Referer":            "https://prontuario.vetsmart.com.br/",
    "Sec-Fetch-Dest":     "empty",
    "Sec-Fetch-Mode":     "cors",
    "Sec-Fetch-Site":     "same-site",
}

# ─── Credenciais ─────────────────────────────────────────────────────────────
PARSE_URL        = "https://parse.vetsmart.com.br/parse"
PARSE_APP_ID     = "XhI4EJ09WGTwlYIT8kpQDrsVEsCjwatFNHDHQOEi"
PARSE_SESSION    = "r:7046f7c91b7784a7e83f744bfdc7b0b1"
PARSE_INSTALL_ID = "abd97cd5-c0b6-497a-9002-d0c9f22b10bd"
PARSE_CLINIC_ID  = "33UAFzEPV1"
PARSE_USER_ID    = "hjkBbPkuJL"
CLIENT_VERSION   = "js6.1.1"
# ─────────────────────────────────────────────────────────────────────────────

OUT = Path("scripts/vetsmart_raw")
OUT.mkdir(parents=True, exist_ok=True)

# Classes candidatas — ordenadas por probabilidade
CLASS_CANDIDATES = [
    # Tutores
    "Tutor", "TutorProfile", "Client", "ClientProfile", "Owner", "Customer",
    # Animais
    "Patient", "Animal", "Pet", "PetProfile",
    # Prontuários/Consultas
    "MedicalRecord", "Attendance", "Appointment", "Consultation",
    "Prontuario", "Record", "Visit", "ServiceOrder", "Atendimento",
    # Prescrições
    "Prescription", "Prescricao", "MedicalPrescription", "Drug", "Medication",
    # Vacinas
    "Vaccine", "Vaccination", "Vacina", "VaccineRecord", "Immunization",
    # Exames
    "Exam", "LabTest", "Exame", "Resultado", "ExamResult",
    # Arquivos
    "File", "Attachment", "Document", "Arquivo", "MedicalFile",
    # Clínica / estruturas
    "Clinic", "Clinica", "HealthUnit", "Unit",
]

# ─── Helper de request (estilo Parse SDK) ────────────────────────────────────

def parse_rest(path, method="GET", body=None, where=None, include=None,
               limit=None, skip=None, count=0):
    """
    Chama Parse Server usando duas estratégias:
      a) REST GET com headers (mais simples)
      b) POST com _method: GET no corpo (estilo JS SDK — usado pelo frontend)
    Retorna a primeira resposta HTTP 200.
    """
    url = f"{PARSE_URL}{path}"

    params = {}
    if where:   params["where"]   = json.dumps(where)
    if include: params["include"] = include
    if limit is not None:  params["limit"]  = limit
    if skip  is not None:  params["skip"]   = skip
    if count:  params["count"]  = 1

    # Estratégia a) POST com _method:GET (estilo JS SDK — jeito que o frontend usa)
    body_payload = {
        "_method":         method,
        "_ApplicationId":  PARSE_APP_ID,
        "_ClientVersion":  CLIENT_VERSION,
        "_InstallationId": PARSE_INSTALL_ID,
        "_SessionToken":   PARSE_SESSION,
    }
    if where:   body_payload["where"]   = json.dumps(where)
    if include: body_payload["include"] = include
    if limit is not None:  body_payload["limit"]  = limit
    if skip  is not None:  body_payload["skip"]   = skip
    if count:  body_payload["count"]  = 1

    try:
        r = requests.post(
            url,
            headers={**BROWSER_HEADERS, "Content-Type": "text/plain"},
            data=json.dumps(body_payload),
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        elif r.status_code in (401, 403):
            # Tenta estrategia b como fallback
            pass
    except requests.RequestException as e:
        print(f"  [debug] POST falhou: {e}")

    # Estratégia b) GET com headers X-Parse-*
    headers_get = {
        **BROWSER_HEADERS,
        "X-Parse-Application-Id":  PARSE_APP_ID,
        "X-Parse-Session-Token":   PARSE_SESSION,
        "X-Parse-Installation-Id": PARSE_INSTALL_ID,
    }
    try:
        r = requests.get(url, headers=headers_get, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        body_short = r.text[:200].replace("\n", " ")
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"Auth falhou (HTTP {r.status_code}). Provavel token expirado "
                f"OU bloqueio Cloudflare. Body: {body_short}"
            )
        raise RuntimeError(f"HTTP {r.status_code} em {path}: {body_short}")
    except requests.RequestException as e:
        raise RuntimeError(f"Request falhou em {path}: {e}")


# ─── 1. Verificar conectividade / sessão ─────────────────────────────────────

print("═" * 60)
print("Verificando autenticação no Parse Server...")
print(f"URL: {PARSE_URL}")
print("═" * 60)

try:
    me = parse_rest("/users/me")
    print(f"✅ Autenticado como: {me.get('fullName') or me.get('name')} "
          f"({me.get('email')})")
    print(f"   Object ID: {me.get('objectId')}")
    (OUT / "user_me.json").write_text(json.dumps(me, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
except Exception as e:
    print(f"❌ Falha: {e}")
    sys.exit(1)

# ─── 2. Buscar a Clínica ─────────────────────────────────────────────────────
print("\n" + "═" * 60)
print(f"Buscando dados da clínica {PARSE_CLINIC_ID}...")
print("═" * 60)

clinic = None
for cls_name in ["Clinic", "Clinica"]:
    try:
        clinic = parse_rest(f"/classes/{cls_name}/{PARSE_CLINIC_ID}")
        print(f"✅ Clínica encontrada na classe '{cls_name}':")
        print(f"   Nome: {clinic.get('name')}")
        print(f"   Campos: {', '.join(list(clinic.keys())[:15])}")
        (OUT / "clinic.json").write_text(
            json.dumps(clinic, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        CLINIC_CLASS = cls_name
        break
    except Exception as e:
        print(f"  {cls_name}: {e}")

if not clinic:
    print("⚠ Não foi possível confirmar o nome da classe da Clínica.")
    CLINIC_CLASS = "Clinic"

# ─── 3. Inspecionar classes candidatas ───────────────────────────────────────
print("\n" + "═" * 60)
print(f"Testando {len(CLASS_CANDIDATES)} classes candidatas...")
print("═" * 60)

found = {}
pointer_clinic = {"__type": "Pointer", "className": CLINIC_CLASS, "objectId": PARSE_CLINIC_ID}

for cls in CLASS_CANDIDATES:
    for filter_field in ["clinic", "clinica", "healthUnit"]:
        try:
            data = parse_rest(
                f"/classes/{cls}",
                where={filter_field: pointer_clinic},
                limit=2,
                count=1,
            )
            total = data.get("count", 0)
            items = data.get("results", [])
            if items or total:
                sample_fields = list(items[0].keys()) if items else []
                found[cls] = {
                    "filter_field": filter_field,
                    "count": total,
                    "fields":  sample_fields,
                    "sample":  items[0] if items else None,
                }
                print(f"\n✅ {cls} (filtrando por {filter_field}): {total} registros")
                if sample_fields:
                    print(f"   Campos: {', '.join(sample_fields[:15])}"
                          f"{'…' if len(sample_fields) > 15 else ''}")
                (OUT / f"sample_{cls}.json").write_text(
                    json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                break   # achou com esse filter_field, vai para próxima classe
        except Exception as e:
            # HTTP 404 = classe não existe; outros são reais
            if "404" not in str(e) and "ClassNotFound" not in str(e):
                print(f"  [debug] {cls}/{filter_field}: {e}")
    time.sleep(0.15)

# Tenta também sem filtro, limitando a 1 amostra
print("\n" + "═" * 60)
print("Testando classes sem filtro (apenas 1 amostra cada)...")
print("═" * 60)
for cls in CLASS_CANDIDATES:
    if cls in found:
        continue
    try:
        data = parse_rest(f"/classes/{cls}", limit=1, count=1)
        items = data.get("results", [])
        total = data.get("count", 0)
        if items or total:
            found[cls] = {
                "filter_field": None,
                "count": total,
                "fields": list(items[0].keys()) if items else [],
                "sample": items[0] if items else None,
            }
            print(f"✅ {cls}: {total} registros (sem filtro de clínica)")
    except Exception:
        pass
    time.sleep(0.1)

# ─── 4. Salvar resultado ─────────────────────────────────────────────────────
output = {
    "parse_url":     PARSE_URL,
    "app_id":        PARSE_APP_ID,
    "clinic_id":     PARSE_CLINIC_ID,
    "clinic_class":  CLINIC_CLASS,
    "classes_found": {k: {kk: vv for kk, vv in v.items() if kk != "sample"}
                      for k, v in found.items()},
}
(OUT / "schema_discovery.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
)

print("\n" + "═" * 60)
print(f"✅ Descoberta concluída — {len(found)} classes encontradas")
print(f"   Resultado: {OUT / 'schema_discovery.json'}")
print("   Amostras:  scripts/vetsmart_raw/sample_*.json")
print("═" * 60)
print("\nPróximo passo:")
print("   python scripts/migrate_vetsmart.py")
