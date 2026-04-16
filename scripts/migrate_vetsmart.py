"""
migrate_vetsmart.py
===================
Pipeline ETL completo: VetSmart (Parse Server) → Petorlandia (PostgreSQL)

COMO USAR
---------
1. Instale dependências:
       pip install requests psycopg2-binary flask flask-sqlalchemy werkzeug

2. Execute da raiz do projeto Petorlandia:
       python scripts/migrate_vetsmart.py

3. O script cria checkpoints em  scripts/vetsmart_raw/  (JSON brutos)
   para que você possa reprocessar sem refazer a extração.

CONFIGURAÇÃO (edite a seção abaixo)
-------------------------------------
"""

# ─── CONFIGURAÇÃO ────────────────────────────────────────────────────────────
PARSE_APP_ID       = "XhI4EJ09WGTwlYIT8kpQDrsVEsCjwatFNHDHQOEi"
PARSE_SESSION      = "r:7046f7c91b7784a7e83f744bfdc7b0b1"   # expira; atualize se necessário
PARSE_INSTALL_ID   = "abd97cd5-c0b6-497a-9002-d0c9f22b10bd"
PARSE_CLINIC_ID    = "33UAFzEPV1"   # objectId da Clínica no Parse
PARSE_USER_ID      = "hjkBbPkuJL"  # objectId do usuário logado

# URL do servidor Parse (confirmada via network capture)
PARSE_URL = "https://parse.vetsmart.com.br/parse"
CLIENT_VERSION = "js6.1.1"

# Fallbacks (caso a URL principal falhe)
PARSE_URL_CANDIDATES = [
    "https://parse.vetsmart.com.br/parse",
    "https://prontuario.vetsmart.com.br/parse",
    "https://prontuario.vetsmart.com.br/api",
]

# ID da clínica no Petorlandia (rode SELECT id,nome FROM clinica; para confirmar)
PETORLANDIA_CLINICA_ID = None   # deixe None para detectar automaticamente

# Usuário veterinário criador das consultas (seu usuário no Petorlandia)
# Deixe None para criar um usuário "importação" automaticamente
PETORLANDIA_VET_USER_ID = None

# Senha padrão para tutores criados na importação
TUTOR_DEFAULT_PASSWORD = "VetSmart@2024"

# Diretório de checkpoints
RAW_DIR = "scripts/vetsmart_raw"
# ─────────────────────────────────────────────────────────────────────────────

import os, sys, json, hashlib, logging, time, re
from datetime import datetime, date
from pathlib import Path

import requests
from werkzeug.security import generate_password_hash

DEFAULT_NETWORK_DUMP = Path("vetsmart_dump_network.json")

# Adiciona a raiz do projeto no path para importar os models
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scripts/migrate_vetsmart.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("vetsmart_migrate")

Path(RAW_DIR).mkdir(parents=True, exist_ok=True)


def refresh_parse_credentials_from_network_dump(dump_path: Path) -> bool:
    """Atualiza credenciais Parse a partir de um dump de rede do navegador."""
    global PARSE_SESSION, PARSE_INSTALL_ID, PARSE_USER_ID

    if not dump_path.exists():
        log.debug("Dump de rede nao encontrado: %s", dump_path)
        return False

    try:
        text = dump_path.read_text(encoding="utf-8")
    except Exception as exc:
        log.warning("Nao foi possivel ler dump de rede %s: %s", dump_path, exc)
        return False

    session_matches = re.findall(r'"_SessionToken":"([^"]+)"', text)
    install_matches = re.findall(r'"_InstallationId":"([^"]+)"', text)
    user_matches = re.findall(r"/parse/classes/_User/([A-Za-z0-9]+)", text)

    updated = False

    if session_matches:
        latest_session = session_matches[-1]
        if latest_session != PARSE_SESSION:
            PARSE_SESSION = latest_session
            updated = True

    if install_matches:
        latest_install = install_matches[-1]
        if latest_install != PARSE_INSTALL_ID:
            PARSE_INSTALL_ID = latest_install
            updated = True

    if user_matches:
        latest_user = user_matches[-1]
        if latest_user != PARSE_USER_ID:
            PARSE_USER_ID = latest_user
            updated = True

    if updated:
        log.info("🔐 Credenciais Parse atualizadas de %s", dump_path)
        log.info("   user_id=%s | install_id=%s | session=%s...",
                 PARSE_USER_ID, PARSE_INSTALL_ID, PARSE_SESSION[:10])
    else:
        log.info("🔐 Dump de rede lido sem novas credenciais: %s", dump_path)

    return updated


# ════════════════════════════════════════════════════════════════════════════
# 1. EXTRAÇÃO — Parse Server REST API
# ════════════════════════════════════════════════════════════════════════════

class VetSmartAPI:
    """Cliente REST para o Parse Server do VetSmart.

    Usa duas estratégias de autenticação:
      (a) GET com headers X-Parse-*         — REST padrão
      (b) POST com _method:'GET' no corpo  — estilo usado pelo frontend JS SDK
    Tenta (a) primeiro; se falhar, usa (b) como fallback.
    """

    PARSE_BASE: str = ""

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

    def __init__(self):
        self.session = requests.Session()
        self.headers_get = {
            **self.BROWSER_HEADERS,
            "X-Parse-Application-Id":  PARSE_APP_ID,
            "X-Parse-Session-Token":   PARSE_SESSION,
            "X-Parse-Installation-Id": PARSE_INSTALL_ID,
        }

    # ── Descoberta da URL base ──────────────────────────────────────────────
    def discover_base_url(self) -> str:
        for base in PARSE_URL_CANDIDATES:
            for strategy_name, caller in [
                ("GET+headers", lambda: self.session.get(
                    f"{base}/users/me", headers=self.headers_get, timeout=10)),
                ("POST-as-GET", lambda: self.session.post(
                    f"{base}/users/me",
                    headers={**self.BROWSER_HEADERS, "Content-Type": "text/plain"},
                    data=json.dumps(self._post_payload("GET")),
                    timeout=10,
                )),
            ]:
                try:
                    r = caller()
                    if r.status_code == 200 and r.json().get("objectId"):
                        log.info("✅ Parse Server OK: %s [via %s]", base, strategy_name)
                        log.info("   Usuário: %s <%s>",
                                 r.json().get("fullName") or r.json().get("name"),
                                 r.json().get("email"))
                        VetSmartAPI.PARSE_BASE = base
                        self.strategy = strategy_name
                        return base
                    log.debug("  %s [%s] → HTTP %s", base, strategy_name, r.status_code)
                except Exception as e:
                    log.debug("  %s [%s] → %s", base, strategy_name, e)
        raise RuntimeError(
            "❌ Não foi possível conectar ao servidor Parse do VetSmart.\n"
            "   Verifique:\n"
            "   1. Se o token em PARSE_SESSION está atualizado (ele expira)\n"
            "   2. Se você tem acesso à internet\n"
            "   3. Se o VetSmart mudou o domínio da API (veja em Network tab do DevTools)"
        )

    # ── Payload padrão estilo JS SDK ───────────────────────────────────────
    def _post_payload(self, method: str = "GET", extra: dict = None) -> dict:
        payload = {
            "_method":         method,
            "_ApplicationId":  PARSE_APP_ID,
            "_ClientVersion":  CLIENT_VERSION,
            "_InstallationId": PARSE_INSTALL_ID,
            "_SessionToken":   PARSE_SESSION,
        }
        if extra:
            payload.update(extra)
        return payload

    # ── Requisição genérica com retry e fallback de estratégia ────────────
    def get(self, path: str, params: dict = None, retries: int = 3) -> dict:
        url = f"{self.PARSE_BASE}{path}"
        last_err = None

        for attempt in range(retries):
            # Estratégia a) GET com headers
            try:
                r = self.session.get(url, headers=self.headers_get,
                                     params=params, timeout=30)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 401:
                    raise RuntimeError(
                        "⛔ Token expirado (HTTP 401). Abra o VetSmart, copie "
                        "o novo sessionToken do localStorage e atualize "
                        "PARSE_SESSION no topo do script."
                    )
                if r.status_code == 404:
                    # Classe não existe — propaga sem retry
                    raise RuntimeError(f"HTTP 404 (classe não existe): {path}")
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            except requests.RequestException as e:
                last_err = str(e)

            # Estratégia b) POST com _method no body
            try:
                extra = dict(params) if params else {}
                # Parse aceita 'where' como string JSON tanto via GET como POST
                r = self.session.post(
                    url,
                    headers={**self.BROWSER_HEADERS, "Content-Type": "text/plain"},
                    data=json.dumps(self._post_payload("GET", extra)),
                    timeout=30,
                )
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 401:
                    raise RuntimeError(
                        "⛔ Token expirado (HTTP 401). Atualize PARSE_SESSION."
                    )
                if r.status_code == 404:
                    raise RuntimeError(f"HTTP 404 (classe não existe): {path}")
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            except requests.RequestException as e:
                last_err = str(e)

            if attempt < retries - 1:
                log.warning("Tentativa %d falhou (%s). Aguardando 2s...",
                            attempt + 1, last_err)
                time.sleep(2)

        raise RuntimeError(f"Falha em {path} após {retries} tentativas: {last_err}")

    # ── Paginação genérica ──────────────────────────────────────────────────
    def fetch_all(self, class_name: str, where: dict = None,
                  include: str = None, order: str = None) -> list:
        """Busca todos os registros de uma classe com paginação automática."""
        results = []
        limit   = 100
        skip    = 0

        while True:
            params = {"limit": limit, "skip": skip, "count": 1}
            if where:
                params["where"] = json.dumps(where)
            if include:
                params["include"] = include
            if order:
                params["order"] = order

            data  = self.get(f"/classes/{class_name}", params=params)
            items = data.get("results", [])
            total = data.get("count", len(items))

            results.extend(items)
            log.info("  %s: %d/%d registros", class_name, len(results), total)

            if len(items) < limit or len(results) >= total:
                break
            skip += limit
            time.sleep(0.3)   # gentil com a API

        return results

    # ── Extratores específicos ──────────────────────────────────────────────
    def _try_classes(self, candidates: list[str],
                      filter_fields: list[str] = ["clinic", "clinica", "healthUnit"],
                      include: str | None = None,
                      order: str = "-createdAt",
                      clinic_class: str = "Clinic") -> tuple[str, list]:
        """Tenta várias classes × filter_fields e retorna a primeira com dados."""
        pointer = {"__type": "Pointer", "className": clinic_class,
                   "objectId": PARSE_CLINIC_ID}
        for cls in candidates:
            for field in filter_fields:
                try:
                    items = self.fetch_all(cls, where={field: pointer},
                                           include=include, order=order)
                    if items:
                        log.info("✅ %s (filter=%s): %d registros", cls, field, len(items))
                        return cls, items
                except RuntimeError as e:
                    if "404" in str(e):
                        break   # classe não existe — tenta próxima
                    log.debug("  %s/%s: %s", cls, field, e)
                except Exception as e:
                    log.debug("  %s/%s: %s", cls, field, e)
        return "", []

    def fetch_tutors(self) -> list:
        """Busca tutores (clientes) cadastrados na clínica."""
        log.info("📋 Buscando tutores...")
        _, items = self._try_classes(
            ["Tutor", "Client", "Owner", "Customer", "TutorProfile", "ClientProfile"]
        )
        if not items:
            log.warning("⚠ Não encontrou tutores. Rode vetsmart_discover.py primeiro "
                        "para descobrir o nome correto da classe.")
        return items

    def fetch_patients(self) -> list:
        """Busca animais (patients) da clínica."""
        log.info("🐾 Buscando animais...")
        _, items = self._try_classes(
            ["Patient", "Animal", "Pet", "PetProfile"],
            include="tutor,owner,client",
        )
        return items

    def fetch_medical_records(self) -> list:
        """Busca prontuários/consultas."""
        log.info("📄 Buscando consultas...")
        _, items = self._try_classes(
            ["MedicalRecord", "Attendance", "Appointment", "Consultation",
             "Prontuario", "Record", "Atendimento", "Visit"],
            include="patient,tutor,prescriptions",
        )
        return items

    def fetch_prescriptions(self) -> list:
        """Busca prescrições."""
        log.info("💊 Buscando prescrições...")
        _, items = self._try_classes(
            ["Prescription", "Prescricao", "MedicalPrescription", "Medication"],
            include="patient,drugs,drug",
        )
        return items

    def fetch_vaccines(self) -> list:
        """Busca vacinas."""
        log.info("💉 Buscando vacinas...")
        _, items = self._try_classes(
            ["Vaccine", "Vaccination", "Vacina", "VaccineRecord", "Immunization"],
            include="patient",
        )
        return items


# ════════════════════════════════════════════════════════════════════════════
# 2. CHECKPOINT — salva/lê JSONs brutos para reprocessamento
# ════════════════════════════════════════════════════════════════════════════

def save_checkpoint(name: str, data: list):
    path = Path(RAW_DIR) / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("💾 Checkpoint salvo: %s (%d registros)", path, len(data))

def load_checkpoint(name: str) -> list | None:
    path = Path(RAW_DIR) / f"{name}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        log.info("⏩ Checkpoint carregado: %s (%d registros)", path, len(data))
        return data
    return None


# ════════════════════════════════════════════════════════════════════════════
# 3. TRANSFORMAÇÃO — mapeia VetSmart → Petorlandia
# ════════════════════════════════════════════════════════════════════════════

# Mapeamento de espécies VetSmart → Petorlandia
SPECIES_MAP = {
    "dog":    "Cão",  "canine": "Cão",   "cachorro": "Cão",   "cao": "Cão",
    "cat":    "Gato", "feline": "Gato",  "felino":   "Gato",  "gato": "Gato",
    "bird":   "Ave",  "rabbit": "Coelho","hamster":  "Hamster",
    "reptile":"Réptil", "fish": "Peixe",
}

def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        # Pointer ou Date do Parse
        if v.get("__type") == "Date":
            return v.get("iso", "")
        return str(v)
    return str(v)

def _date(v) -> date | None:
    if not v:
        return None
    iso = v.get("iso", v) if isinstance(v, dict) else v
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
    except Exception:
        return None

def _dt(v) -> datetime | None:
    if not v:
        return None
    iso = v.get("iso", v) if isinstance(v, dict) else v
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None

def _phone(v: str) -> str:
    if not v:
        return ""
    return "".join(c for c in str(v) if c.isdigit() or c in "+()")

def _sex(v: str) -> str:
    if not v:
        return "indefinido"
    v = v.lower()
    if v in ("m", "male", "macho"):
        return "macho"
    if v in ("f", "female", "femea", "fêmea"):
        return "fêmea"
    return "indefinido"

def _dedup_email(email: str, existing_emails: set) -> str:
    """Garante e-mail único adicionando sufixo se necessário."""
    base  = email.lower().strip() if email else ""
    if not base:
        base = f"tutor_{hashlib.md5(email.encode() if email else b'x').hexdigest()[:8]}@vetsmart.import"
    if base not in existing_emails:
        existing_emails.add(base)
        return base
    i = 1
    while f"{base.split('@')[0]}_{i}@{base.split('@')[1]}" in existing_emails:
        i += 1
    unique = f"{base.split('@')[0]}_{i}@{base.split('@')[1]}"
    existing_emails.add(unique)
    return unique

def transform_tutor(vs: dict, existing_emails: set) -> dict:
    """Transforma um registro de tutor do VetSmart para o schema User do Petorlandia."""
    raw_email = _str(vs.get("email") or vs.get("ownerEmail") or vs.get("mail") or "")
    normalized_email = raw_email.lower().strip()
    email = _dedup_email(normalized_email, existing_emails)

    name = (
        _str(vs.get("name") or vs.get("fullName") or
             vs.get("ownerName") or vs.get("nome") or
             email.split("@")[0])
    ).strip() or "Tutor Importado"

    return {
        "vetsmart_id":  vs.get("objectId", ""),
        "name":         name,
        "email":        email,
        "source_email": normalized_email or None,
        "phone":        _phone(vs.get("phone") or vs.get("cellphone") or
                               vs.get("telefone") or vs.get("celular") or ""),
        "cpf":          _str(vs.get("cpf") or vs.get("document") or "").replace(".", "").replace("-", "") or None,
        "address":      _str(vs.get("address") or vs.get("endereco") or ""),
        "role":         "tutor",
        "is_private":   True,
        "created_at":   _dt(vs.get("createdAt") or vs.get("changedAt") or vs.get("updatedAt")),
        "password_hash": generate_password_hash(TUTOR_DEFAULT_PASSWORD),
        "vs_raw":       vs,   # guardado para diagnóstico
    }

def transform_animal(vs: dict, tutor_pet_id: int,
                     species_map: dict, breed_map: dict) -> dict:
    """Transforma um registro de animal do VetSmart para o schema Animal do Petorlandia."""
    raw_species = _str(
        vs.get("species") or vs.get("specie") or vs.get("especie") or vs.get("speciesName") or ""
    ).lower().strip()
    mapped_species = SPECIES_MAP.get(raw_species, raw_species.capitalize() or "Outro")
    species_id = species_map.get(mapped_species)

    raw_breed = _str(
        vs.get("breed") or vs.get("raca") or vs.get("breedName") or ""
    ).strip()
    breed_id = breed_map.get((mapped_species, raw_breed))

    name = _str(
        vs.get("name") or vs.get("nome") or vs.get("petName") or "Animal Importado"
    ).strip()

    return {
        "vetsmart_id":   vs.get("objectId", ""),
        "name":          name,
        "sex":           _sex(vs.get("sex") or vs.get("gender") or vs.get("sexo") or ""),
        "date_of_birth": _date(vs.get("birthdate") or vs.get("birthday") or vs.get("dateOfBirth") or vs.get("dataNascimento")),
        "species_id":    species_id,
        "breed_id":      breed_id,
        "neutered":      bool(vs.get("neutered") or vs.get("castrated") or vs.get("castrado")),
        "microchip_number": _str(vs.get("microchip") or vs.get("chip") or ""),
        "peso":          vs.get("weight") or vs.get("peso"),
        "status":        "ativo",
        "is_alive":      True,
        "user_id":       tutor_pet_id,     # FK → User (tutor)
        "date_added":    _dt(vs.get("createdAt") or vs.get("changedAt") or vs.get("updatedAt")),
        "vs_raw":        vs,
    }

def transform_consulta(vs: dict, animal_pet_id: int,
                       vet_user_id: int, clinica_id: int) -> dict:
    """Transforma um prontuário/consulta do VetSmart."""
    return {
        "vetsmart_id":      vs.get("objectId", ""),
        "animal_id":        animal_pet_id,
        "created_by":       vet_user_id,
        "clinica_id":       clinica_id,
        "created_at":       _dt(vs.get("documentDate") or vs.get("createdAt") or vs.get("date") or vs.get("data")),
        "queixa_principal": _str(vs.get("chiefComplaint") or vs.get("queixa") or
                                  vs.get("reason") or vs.get("motivo") or ""),
        "historico_clinico": _str(vs.get("clinicalHistory") or vs.get("anamnesis") or
                                   vs.get("historico") or vs.get("history") or ""),
        "exame_fisico":     _str(vs.get("physicalExam") or vs.get("exame") or
                                  vs.get("examination") or ""),
        "conduta":          _str(vs.get("conduct") or vs.get("treatment") or
                                  vs.get("conduta") or vs.get("tratamento") or
                                  vs.get("notes") or ""),
        "exames_solicitados": _str(vs.get("exams") or vs.get("labTests") or
                                    vs.get("exameSolicitado") or ""),
        "prescricao":       _str(vs.get("prescriptionText") or vs.get("prescricao") or ""),
        "status":           "finalizada",
        "finalizada_em":    _dt(vs.get("updatedAt") or vs.get("finishedAt") or vs.get("documentDate")),
        "vs_raw":           vs,
    }

def transform_prescricao(vs: dict, animal_pet_id: int) -> list[dict]:
    """
    Uma prescrição do VetSmart pode conter múltiplos medicamentos.
    Retorna uma lista de dicts prontos para Prescricao.
    """
    drugs = vs.get("drugs") or vs.get("medications") or vs.get("medicamentos") or []
    if not drugs and vs.get("drug"):
        drugs = [vs]

    results = []
    base_date = _dt(
        vs.get("documentDate")
        or vs.get("displayDate")
        or vs.get("createdAt")
        or vs.get("date")
        or vs.get("updatedAt")
    )

    for drug in drugs:
        results.append({
            "vetsmart_id":   f"{vs.get('objectId','')}_{drug.get('objectId','') or len(results)}",
            "animal_id":     animal_pet_id,
            "medicamento":   _str(drug.get("name") or drug.get("drug") or drug.get("medicamento") or ""),
            "dosagem":       _str(drug.get("dosage") or drug.get("dose") or drug.get("dosagem") or ""),
            "frequencia":    _str(drug.get("frequency") or drug.get("frequencia") or ""),
            "duracao":       _str(drug.get("duration") or drug.get("duracao") or ""),
            "observacoes":   _str(drug.get("notes") or drug.get("observacoes") or ""),
            "data_prescricao": base_date,
        })

    # Se não tem lista de drugs, usa o próprio registro
    if not results:
        results.append({
            "vetsmart_id":   vs.get("objectId", ""),
            "animal_id":     animal_pet_id,
            "medicamento":   _str(vs.get("medication") or vs.get("drug") or
                                   vs.get("medicamento") or "Importado do VetSmart"),
            "dosagem":       _str(vs.get("dosage") or vs.get("dosagem") or ""),
            "frequencia":    _str(vs.get("frequency") or vs.get("frequencia") or ""),
            "duracao":       _str(vs.get("duration") or vs.get("duracao") or ""),
            "observacoes":   _str(vs.get("notes") or vs.get("observacoes") or ""),
            "data_prescricao": base_date,
        })
    return results

def transform_vacina(vs: dict, animal_pet_id: int, vet_user_id: int) -> dict:
    vaccine_data = vs.get("vaccine")
    vaccine_name = vaccine_data.get("name") if isinstance(vaccine_data, dict) else vaccine_data
    return {
        "vetsmart_id":  vs.get("objectId", ""),
        "animal_id":    animal_pet_id,
        "nome":         _str(vs.get("name") or vaccine_name or vs.get("vaccineName") or vs.get("nome") or "Vacina"),
        "fabricante":   _str(vs.get("manufacturer") or vs.get("brand") or vs.get("fabricante") or ""),
        "aplicada":     True,
        "aplicada_em":  _date(vs.get("applicationDate") or vs.get("documentDate") or vs.get("date") or vs.get("data") or vs.get("createdAt")),
        "aplicada_por": vet_user_id,
        "observacoes":  _str(vs.get("notes") or vs.get("observacoes") or ""),
    }


# ════════════════════════════════════════════════════════════════════════════
# 4. INSERÇÃO — Petorlandia (Flask + SQLAlchemy)
# ════════════════════════════════════════════════════════════════════════════

def get_or_create_species(db, Species, name: str) -> int:
    sp = Species.query.filter_by(name=name).first()
    if not sp:
        sp = Species(name=name)
        db.session.add(sp)
        db.session.flush()
        log.info("  + Espécie criada: %s", name)
    return sp.id

def get_or_create_breed(db, Breed, species_id: int, name: str) -> int | None:
    if not name:
        return None
    br = Breed.query.filter_by(name=name, species_id=species_id).first()
    if not br:
        br = Breed(name=name, species_id=species_id)
        db.session.add(br)
        db.session.flush()
        log.info("  + Raça criada: %s", name)
    return br.id

def build_species_breed_maps(db, Species, Breed, raw_animals: list) -> tuple[dict, dict]:
    """Cria espécies/raças que ainda não existem e retorna mapas nome→id."""
    species_map = {}
    breed_map   = {}

    for a in raw_animals:
        raw_sp = _str(a.get("species") or a.get("especie") or "").lower().strip()
        sp_name = SPECIES_MAP.get(raw_sp, raw_sp.capitalize() or "Outro")
        if sp_name not in species_map:
            species_map[sp_name] = get_or_create_species(db, Species, sp_name)

        raw_br = _str(a.get("breed") or a.get("raca") or "").strip()
        key    = (sp_name, raw_br)
        if raw_br and key not in breed_map:
            breed_map[key] = get_or_create_breed(db, Breed, species_map[sp_name], raw_br)

    db.session.flush()
    return species_map, breed_map

def get_or_create_vet_user(db, User, clinica_id: int, preferred_user_id: int | None = None) -> int:
    """Retorna o ID de um usuário veterinário padrão para as consultas importadas."""
    if preferred_user_id:
        return preferred_user_id
    if PETORLANDIA_VET_USER_ID:
        return PETORLANDIA_VET_USER_ID

    sentinel_email = "importacao_vetsmart@petorlandia.internal"
    u = User.query.filter_by(email=sentinel_email).first()
    if not u:
        u = User(
            name="Importação VetSmart",
            email=sentinel_email,
            role="veterinario",
            clinica_id=clinica_id,
            is_private=True,
        )
        u.set_password("VetSmart@Import2024")
        db.session.add(u)
        db.session.flush()
        log.info("  + Usuário sentinela criado: %s (id=%s)", sentinel_email, u.id)
    return u.id

def get_clinica_id(db, Clinica, preferred_clinic_id: int | None = None) -> int:
    if preferred_clinic_id:
        return preferred_clinic_id
    if PETORLANDIA_CLINICA_ID:
        return PETORLANDIA_CLINICA_ID
    clinica = Clinica.query.filter(
        Clinica.nome.ilike("%orlando%")
    ).first() or Clinica.query.first()
    if not clinica:
        raise RuntimeError("Nenhuma clínica encontrada no Petorlandia. Crie uma antes de importar.")
    log.info("🏥 Clínica detectada: %s (id=%d)", clinica.nome, clinica.id)
    return clinica.id


# ─── Pipeline de inserção ────────────────────────────────────────────────────

def import_all(
    raw: dict,
    *,
    target_clinic_id: int | None = None,
    added_by_user_id: int | None = None,
    target_vet_user_id: int | None = None,
):
    """
    Importa todos os dados brutos no banco do Petorlandia.
    raw = { "tutores": [...], "animais": [...], "consultas": [...],
            "prescricoes": [...], "vacinas": [...] }
    """
    from app_factory import create_app
    from extensions import db
    from models.base import (
        User, Animal, Species, Breed,
        Consulta, Prescricao, BlocoPrescricao,
        Vacina, Clinica,
    )

    app = create_app()
    with app.app_context():
        log.info("=" * 60)
        log.info("Iniciando importação no banco Petorlandia")
        log.info("=" * 60)

        clinica_id = get_clinica_id(db, Clinica, preferred_clinic_id=target_clinic_id)
        vet_user_id = get_or_create_vet_user(
            db,
            User,
            clinica_id,
            preferred_user_id=target_vet_user_id or added_by_user_id,
        )

        # ── a) Espécies e Raças ───────────────────────────────────────────
        log.info("\n[1/5] Preparando espécies e raças...")
        species_map, breed_map = build_species_breed_maps(
            db, Species, Breed, raw.get("animais", [])
        )

        # ── b) Tutores ────────────────────────────────────────────────────
        log.info("\n[2/5] Importando tutores (%d)...", len(raw.get("tutores", [])))
        existing_emails: set = {e for (e,) in db.session.query(User.email).all() if e}
        tutor_id_map: dict[str, int] = {}   # vetsmart_id → petorlandia user.id

        for i, vs_tutor in enumerate(raw.get("tutores", []), 1):
            vs_id = vs_tutor.get("objectId", f"noId_{i}")
            t = transform_tutor(vs_tutor, existing_emails)

            # Deduplica pelo vetsmart_id já importado (campo description usado como tag)
            existing = User.query.filter(
                User.email.like(f"%{vs_id}%")
            ).first()

            if existing:
                tutor_id_map[vs_id] = existing.id
                log.debug("  skip tutor %s (já existe)", vs_id)
                continue

            if t["cpf"]:
                existing = User.query.filter_by(cpf=t["cpf"]).first()
                if existing:
                    tutor_id_map[vs_id] = existing.id
                    log.info("  [%d/%d] Tutor reconciliado por CPF: %s → id=%d",
                             i, len(raw["tutores"]), t["name"], existing.id)
                    continue

            if t["source_email"]:
                existing = User.query.filter_by(email=t["source_email"]).first()
                if existing:
                    tutor_id_map[vs_id] = existing.id
                    log.info("  [%d/%d] Tutor reconciliado por email: %s → id=%d",
                             i, len(raw["tutores"]), t["name"], existing.id)
                    continue

            user = User(
                name         = t["name"],
                email        = t["email"],
                password_hash= t["password_hash"],
                phone        = t["phone"],
                cpf          = t["cpf"],
                address      = t["address"],
                role         = "tutor",
                clinica_id   = clinica_id,
                added_by_id  = added_by_user_id,
                is_private   = True,
                created_at   = t["created_at"] or datetime.utcnow(),
            )
            db.session.add(user)
            db.session.flush()
            tutor_id_map[vs_id] = user.id
            log.info("  [%d/%d] Tutor: %s → id=%d",
                     i, len(raw["tutores"]), t["name"], user.id)

        db.session.flush()

        # ── c) Animais ────────────────────────────────────────────────────
        log.info("\n[3/5] Importando animais (%d)...", len(raw.get("animais", [])))
        animal_id_map: dict[str, int] = {}   # vetsmart_id → petorlandia animal.id

        for i, vs_animal in enumerate(raw.get("animais", []), 1):
            vs_id = vs_animal.get("objectId", f"noId_{i}")

            # Encontra o tutor dono
            tutor_ptr = vs_animal.get("tutor") or vs_animal.get("client") or vs_animal.get("owner") or {}
            tutor_vs_id = tutor_ptr.get("objectId") if isinstance(tutor_ptr, dict) else None
            tutor_pet_id = tutor_id_map.get(tutor_vs_id)

            if not tutor_pet_id:
                log.warning("  ⚠ Animal '%s' sem tutor mapeado (vs_id=%s). Atribuindo ao vet.",
                            vs_animal.get("name"), tutor_vs_id)
                tutor_pet_id = vet_user_id

            t = transform_animal(vs_animal, tutor_pet_id, species_map, breed_map)
            animal = Animal(
                name           = t["name"],
                sex            = t["sex"],
                date_of_birth  = t["date_of_birth"],
                species_id     = t["species_id"],
                breed_id       = t["breed_id"],
                neutered       = t["neutered"],
                microchip_number = t["microchip_number"],
                peso           = t["peso"],
                status         = "ativo",
                is_alive       = True,
                user_id        = tutor_pet_id,
                added_by_id    = added_by_user_id,
                clinica_id     = clinica_id,
                date_added     = t["date_added"] or datetime.utcnow(),
            )
            db.session.add(animal)
            db.session.flush()
            animal_id_map[vs_id] = animal.id
            log.info("  [%d/%d] Animal: %s → id=%d", i, len(raw["animais"]), t["name"], animal.id)

        db.session.flush()

        # ── d) Consultas ──────────────────────────────────────────────────
        log.info("\n[4/5] Importando consultas (%d)...", len(raw.get("consultas", [])))
        for i, vs_c in enumerate(raw.get("consultas", []), 1):
            vs_id = vs_c.get("objectId", f"noId_{i}")

            pat_ptr   = vs_c.get("patient") or vs_c.get("animal") or vs_c.get("pet") or {}
            animal_vs = pat_ptr.get("objectId") if isinstance(pat_ptr, dict) else None
            animal_pet_id = animal_id_map.get(animal_vs)

            if not animal_pet_id:
                log.warning("  ⚠ Consulta '%s' sem animal mapeado. Pulando.", vs_id)
                continue

            t = transform_consulta(vs_c, animal_pet_id, vet_user_id, clinica_id)
            c = Consulta(
                animal_id         = animal_pet_id,
                created_by        = vet_user_id,
                clinica_id        = clinica_id,
                created_at        = t["created_at"] or datetime.utcnow(),
                queixa_principal  = t["queixa_principal"],
                historico_clinico = t["historico_clinico"],
                exame_fisico      = t["exame_fisico"],
                conduta           = t["conduta"],
                exames_solicitados= t["exames_solicitados"],
                prescricao        = t["prescricao"],
                status            = "finalizada",
                finalizada_em     = t["finalizada_em"],
            )
            db.session.add(c)
            log.info("  [%d/%d] Consulta → animal id=%d", i, len(raw["consultas"]), animal_pet_id)

        db.session.flush()

        # ── e) Prescrições ────────────────────────────────────────────────
        log.info("\n[4b] Importando prescrições (%d)...", len(raw.get("prescricoes", [])))
        for vs_p in raw.get("prescricoes", []):
            pat_ptr  = vs_p.get("patient") or vs_p.get("animal") or {}
            animal_vs = pat_ptr.get("objectId") if isinstance(pat_ptr, dict) else None
            animal_pet_id = animal_id_map.get(animal_vs)
            if not animal_pet_id:
                continue

            for presc_data in transform_prescricao(vs_p, animal_pet_id):
                if not presc_data["medicamento"]:
                    continue
                p = Prescricao(
                    animal_id       = animal_pet_id,
                    medicamento     = presc_data["medicamento"],
                    dosagem         = presc_data["dosagem"],
                    frequencia      = presc_data["frequencia"],
                    duracao         = presc_data["duracao"],
                    observacoes     = presc_data["observacoes"],
                    data_prescricao = presc_data["data_prescricao"] or datetime.utcnow(),
                )
                db.session.add(p)

        # ── f) Vacinas ────────────────────────────────────────────────────
        log.info("\n[5/5] Importando vacinas (%d)...", len(raw.get("vacinas", [])))
        for vs_v in raw.get("vacinas", []):
            pat_ptr  = vs_v.get("patient") or vs_v.get("animal") or {}
            animal_vs = pat_ptr.get("objectId") if isinstance(pat_ptr, dict) else None
            animal_pet_id = animal_id_map.get(animal_vs)
            if not animal_pet_id:
                continue

            tv = transform_vacina(vs_v, animal_pet_id, vet_user_id)
            v = Vacina(
                animal_id  = animal_pet_id,
                nome       = tv["nome"],
                fabricante = tv["fabricante"],
                aplicada   = True,
                aplicada_em= tv["aplicada_em"],
                aplicada_por = tv["aplicada_por"],
                observacoes= tv["observacoes"],
                created_by = vet_user_id,
            )
            db.session.add(v)

        # ── Commit final ──────────────────────────────────────────────────
        log.info("\n✅ Fazendo commit...")
        db.session.commit()
        log.info("=" * 60)
        log.info("MIGRAÇÃO CONCLUÍDA!")
        log.info("  Tutores  : %d", len(tutor_id_map))
        log.info("  Animais  : %d", len(animal_id_map))
        log.info("  Consultas: %d", len(raw.get("consultas", [])))
        log.info("  Prescrições: %d", len(raw.get("prescricoes", [])))
        log.info("  Vacinas  : %d", len(raw.get("vacinas", [])))
        log.info("=" * 60)


# ════════════════════════════════════════════════════════════════════════════
# 5. ORQUESTRADOR PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def extract_phase(api: VetSmartAPI) -> dict:
    """
    Fase de extração: busca tudo do VetSmart e salva checkpoints.
    Se um checkpoint existir, reutiliza (não refaz a requisição).
    """
    raw = {}

    raw["tutores"] = load_checkpoint("tutores") or []
    if not raw["tutores"]:
        raw["tutores"] = api.fetch_tutors()
        save_checkpoint("tutores", raw["tutores"])

    raw["animais"] = load_checkpoint("animais") or []
    if not raw["animais"]:
        raw["animais"] = api.fetch_patients()
        save_checkpoint("animais", raw["animais"])

    raw["consultas"] = load_checkpoint("consultas") or []
    if not raw["consultas"]:
        raw["consultas"] = api.fetch_medical_records()
        save_checkpoint("consultas", raw["consultas"])

    raw["prescricoes"] = load_checkpoint("prescricoes") or []
    if not raw["prescricoes"]:
        raw["prescricoes"] = api.fetch_prescriptions()
        save_checkpoint("prescricoes", raw["prescricoes"])

    raw["vacinas"] = load_checkpoint("vacinas") or []
    if not raw["vacinas"]:
        raw["vacinas"] = api.fetch_vaccines()
        save_checkpoint("vacinas", raw["vacinas"])

    return raw


def load_from_exportar_clientes_json(json_path: Path) -> dict:
    """
    Carrega dados do formato produzido por scripts/exportar_clientes_vetsmart.py
    (que usa Playwright + Chrome logado, bypass Cloudflare).
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    log.info("📂 JSON carregado de %s", json_path)
    log.info("   Tutores: %d | Animais: %d",
             len(data.get("tutors", [])), len(data.get("animals", [])))

    # Salva como checkpoints para reuso
    raw = {
        "tutores":    data.get("tutors",    []),
        "animais":    data.get("animals",   []),
        "consultas":  data.get("consultas", []),
        "prescricoes":data.get("prescricoes",[]),
        "vacinas":    data.get("vacinas",   []),
    }
    for name, items in raw.items():
        if items:
            save_checkpoint(name, items)
    return raw


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", type=Path,
                        help="Le dados do JSON produzido por exportar_clientes_vetsmart.py "
                             "(bypassa extracao HTTP, usa Playwright)")
    parser.add_argument("--network-dump", type=Path, default=None,
                        help="Usa um dump de rede do navegador para atualizar sessionToken/"
                             "installationId antes da extracao HTTP.")
    parser.add_argument("--only-extract", action="store_true",
                        help="So extrai os dados, nao importa no banco.")
    parser.add_argument("--only-import", action="store_true",
                        help="So importa dos checkpoints existentes.")
    parser.add_argument("--target-clinic-id", type=int, default=None,
                        help="ID da clinica destino no Petorlandia.")
    parser.add_argument("--added-by-user-id", type=int, default=None,
                        help="ID do usuario que deve constar como responsavel pelos tutores/animais importados.")
    parser.add_argument("--target-vet-user-id", type=int, default=None,
                        help="ID do usuario veterinario responsavel pelas consultas e vacinas.")
    args = parser.parse_args()

    log.info("🚀 VetSmart → Petorlandia Migration")
    log.info("   Checkpoints em: %s", RAW_DIR)

    # ── Fase 1: Extração ──────────────────────────────────────────────────
    raw = None

    # MODO A: JSON do exportar_clientes_vetsmart.py (recomendado pra Cloudflare)
    if args.from_json:
        if not args.from_json.exists():
            log.error("Arquivo nao encontrado: %s", args.from_json)
            sys.exit(1)
        raw = load_from_exportar_clientes_json(args.from_json)

    # MODO B: Só importa dos checkpoints existentes
    elif args.only_import:
        raw = {
            "tutores":    load_checkpoint("tutores")    or [],
            "animais":    load_checkpoint("animais")    or [],
            "consultas":  load_checkpoint("consultas")  or [],
            "prescricoes":load_checkpoint("prescricoes") or [],
            "vacinas":    load_checkpoint("vacinas")    or [],
        }
        if not any(raw.values()):
            log.error("Nenhum checkpoint encontrado em %s. "
                      "Rode extracao primeiro.", RAW_DIR)
            sys.exit(1)

    # MODO C: Extração HTTP direta (pode falhar pelo Cloudflare)
    else:
        dump_path = args.network_dump or DEFAULT_NETWORK_DUMP
        if dump_path and dump_path.exists():
            refresh_parse_credentials_from_network_dump(dump_path)

        api = VetSmartAPI()

        only_extract = args.only_extract
        if not only_extract:
            print("\n[?] Deseja apenas EXTRAIR os dados (sem importar no banco)? [s/N] ", end="")
            only_extract = input().strip().lower() == "s"

        if not any(Path(RAW_DIR).glob("*.json")):
            log.info("\n📡 Descobrindo URL do servidor Parse...")
            try:
                api.discover_base_url()
                raw = extract_phase(api)
            except RuntimeError as e:
                log.error("\n❌ Extracao HTTP falhou: %s", e)
                log.error("\n💡 Use extracao via browser (Playwright):")
                log.error("   python scripts/exportar_clientes_vetsmart.py")
                log.error("   python scripts/migrate_vetsmart.py --from-json vetsmart_tutores_animais.json")
                sys.exit(1)
        else:
            print(f"\n[?] Checkpoints existentes encontrados em '{RAW_DIR}'.")
            print("    (r) Reusar checkpoints e importar    (e) Reextrair tudo    (q) Sair")
            choice = input("    Escolha: ").strip().lower()
            if choice == "q":
                return
            elif choice == "e":
                if dump_path and dump_path.exists():
                    refresh_parse_credentials_from_network_dump(dump_path)
                    api = VetSmartAPI()
                api.discover_base_url()
                raw = extract_phase(api)
            else:
                raw = {
                    "tutores":    load_checkpoint("tutores")    or [],
                    "animais":    load_checkpoint("animais")    or [],
                    "consultas":  load_checkpoint("consultas")  or [],
                    "prescricoes":load_checkpoint("prescricoes") or [],
                    "vacinas":    load_checkpoint("vacinas")    or [],
                }

    log.info("\n📊 Dados carregados:")
    for k, v in raw.items():
        log.info("  %-15s: %d registros", k, len(v))

    if args.only_extract:
        log.info("\n✅ Extração concluída. JSONs salvos em '%s'.", RAW_DIR)
        return

    # ── Fase 2: Importação ────────────────────────────────────────────────
    print("\n[?] Confirma importação no banco PostgreSQL do Petorlandia? [s/N] ", end="")
    if input().strip().lower() != "s":
        log.info("Importação cancelada pelo usuário.")
        return

    import_all(
        raw,
        target_clinic_id=args.target_clinic_id,
        added_by_user_id=args.added_by_user_id,
        target_vet_user_id=args.target_vet_user_id,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("\nInterrompido pelo usuário.")
    except Exception as e:
        log.exception("Erro fatal: %s", e)
        sys.exit(1)
