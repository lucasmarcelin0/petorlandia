"""
vetsmart_extract_browser.py
============================
Extrai dados do VetSmart via Playwright (Chrome real) — bypassa Cloudflare 100%.

Abre um Chrome visivel, voce faz login uma vez, e o script faz TODAS as
chamadas ao Parse Server via `page.evaluate(fetch(...))` — no contexto do
proprio navegador, com os cookies do Cloudflare ja estabelecidos.

Salva os resultados em:
    scripts/vetsmart_raw/tutores.json
    scripts/vetsmart_raw/animais.json
    scripts/vetsmart_raw/consultas.json
    scripts/vetsmart_raw/prescricoes.json
    scripts/vetsmart_raw/vacinas.json
    scripts/vetsmart_raw/schema_discovery.json   (classes descobertas)

Depois rode:  python scripts/migrate_vetsmart.py --only-import

COMO USAR:
    pip install playwright
    playwright install chromium
    python scripts/vetsmart_extract_browser.py
"""

import json, sys, time
from pathlib import Path

# ─── Configuração ────────────────────────────────────────────────────────────
PARSE_URL        = "https://parse.vetsmart.com.br/parse"
PARSE_APP_ID     = "XhI4EJ09WGTwlYIT8kpQDrsVEsCjwatFNHDHQOEi"
PARSE_CLINIC_ID  = "33UAFzEPV1"
CLIENT_VERSION   = "js6.1.1"
PRONTUARIO_URL   = "https://prontuario.vetsmart.com.br/"

OUT = Path("scripts/vetsmart_raw")
OUT.mkdir(parents=True, exist_ok=True)

# Classes candidatas a testar (nomes comuns em sistemas veterinarios)
CLASS_GROUPS = {
    "tutores":    ["Tutor", "Client", "Owner", "Customer", "TutorProfile"],
    "animais":    ["Patient", "Animal", "Pet", "PetProfile"],
    "consultas":  ["MedicalRecord", "Attendance", "Appointment",
                    "Consultation", "Prontuario", "Atendimento", "Visit"],
    "prescricoes":["Prescription", "Prescricao", "MedicalPrescription", "Medication"],
    "vacinas":    ["Vaccine", "Vaccination", "Vacina", "Immunization"],
}
# ─────────────────────────────────────────────────────────────────────────────

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright nao instalado. Rode:")
    print("   pip install playwright")
    print("   playwright install chromium")
    sys.exit(1)


# ─── JS helper: chama Parse Server no contexto do browser ───────────────────
PARSE_QUERY_JS = r"""
async ({ parseUrl, appId, installationId, sessionToken, clientVersion,
         path, where, includeFields, limit, skip, count }) => {
  try {
    const body = {
      _method:         'GET',
      _ApplicationId:  appId,
      _ClientVersion:  clientVersion,
      _InstallationId: installationId,
      _SessionToken:   sessionToken,
    };
    if (where)         body.where   = JSON.stringify(where);
    if (includeFields) body.include = includeFields;
    if (limit != null) body.limit   = limit;
    if (skip  != null) body.skip    = skip;
    if (count)         body.count   = 1;

    const response = await fetch(parseUrl + path, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      credentials: 'include',
      body: JSON.stringify(body),
    });

    const text = await response.text();
    let data = null;
    try { data = JSON.parse(text); } catch {}

    return {
      ok:       response.ok,
      status:   response.status,
      data:     data,
      raw:      data ? null : text.slice(0, 200),
    };
  } catch (error) {
    return { ok: false, status: 0, error: String(error) };
  }
}
"""


def parse_query(page, path, **kwargs):
    """Executa uma consulta Parse Server no contexto do navegador."""
    args = {
        "parseUrl":       PARSE_URL,
        "appId":          PARSE_APP_ID,
        "installationId": session_state["installation_id"],
        "sessionToken":   session_state["session_token"],
        "clientVersion":  CLIENT_VERSION,
        "path":           path,
        **kwargs,
    }
    # Preenche defaults ausentes com null para JS
    for k in ("where", "includeFields", "limit", "skip", "count"):
        args.setdefault(k, None)

    result = page.evaluate(PARSE_QUERY_JS, args)
    if not result.get("ok"):
        status = result.get("status")
        raw = result.get("raw") or result.get("error") or ""
        raise RuntimeError(f"HTTP {status} em {path}: {str(raw)[:150]}")
    return result["data"]


# ─── Extrai token e installationId do localStorage (com retry automatico) ───
def extract_auth_from_context(context):
    """
    Le sessionToken/installationId de QUALQUER aba do VetSmart.
    Procura em todas as paginas abertas — o login do VetSmart pode abrir
    abas diferentes (conta.vetsmart.com.br e prontuario.vetsmart.com.br).
    """
    session_token = None
    installation_id = None
    active_page = None

    for page in list(context.pages):
        url = ""
        try:
            url = page.url or ""
        except Exception:
            continue

        if "vetsmart.com.br" not in url:
            continue

        try:
            storage = page.evaluate(
                """
                () => {
                    const found = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const k = localStorage.key(i);
                        try { found[k] = localStorage.getItem(k); } catch(_) {}
                    }
                    return found;
                }
                """
            )
        except Exception:
            continue

        for key, raw in (storage or {}).items():
            if not raw:
                continue
            if "currentUser" in key:
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict) and obj.get("sessionToken"):
                        session_token = obj["sessionToken"]
                        active_page = page
                except Exception:
                    pass
            if "currentInstallationId" in key and "/" not in raw and len(raw) == 36:
                installation_id = raw

        if session_token:
            break

    return session_token, installation_id, active_page


def wait_for_login(context, timeout_seconds: int = 300, poll_interval: float = 2.0):
    """Espera ate o token aparecer no localStorage (usuario fez login)."""
    print()
    print("=" * 60)
    print("Fazendo login no VetSmart...")
    print("-" * 60)
    print("  1. Se a janela pediu login, faca login normalmente.")
    print("  2. Espere o PRONTUARIO carregar (tela principal apos o login).")
    print("  3. NAO pressione nada aqui — o script detecta automaticamente.")
    print()
    print(f"Aguardando ate {timeout_seconds}s...")
    print("=" * 60)

    start = time.time()
    last_url = ""
    last_dot = 0

    while time.time() - start < timeout_seconds:
        token, install_id, page = extract_auth_from_context(context)
        if token:
            print(f"\n✅ Token detectado apos {int(time.time()-start)}s!")
            return token, install_id, page

        # Mostra URL atual periodicamente
        try:
            current_url = context.pages[0].url if context.pages else ""
            if current_url != last_url:
                print(f"\n   📍 URL atual: {current_url[:100]}")
                last_url = current_url
            else:
                # Imprime pontinho a cada 2s pra mostrar que ta vivo
                if time.time() - last_dot > 2:
                    print(".", end="", flush=True)
                    last_dot = time.time()
        except Exception:
            pass

        time.sleep(poll_interval)

    raise TimeoutError(f"Login nao detectado em {timeout_seconds}s.")


# ─── Paginação genérica ──────────────────────────────────────────────────────
def fetch_all(page, class_name, where=None, include=None):
    """Busca todos os registros de uma classe Parse com paginação."""
    results = []
    limit = 100
    skip  = 0
    while True:
        data = parse_query(page, f"/classes/{class_name}",
                           where=where, includeFields=include,
                           limit=limit, skip=skip, count=1)
        items = data.get("results", [])
        total = data.get("count", len(items))
        results.extend(items)
        print(f"      {class_name}: {len(results)}/{total}", end="\r")
        if len(items) < limit or len(results) >= total:
            break
        skip += limit
        time.sleep(0.15)
    print()
    return results


# ─── Tenta descobrir o nome correto da classe ───────────────────────────────
def discover_class(page, candidates, where=None):
    """Testa varios nomes de classe e retorna o primeiro que tem dados."""
    for cls in candidates:
        try:
            data = parse_query(page, f"/classes/{cls}",
                               where=where, limit=1, count=1)
            total = data.get("count", 0)
            if data.get("results") or total > 0:
                print(f"   ✅ '{cls}' → {total} registros")
                return cls
        except RuntimeError as e:
            msg = str(e)
            if "404" in msg or "invalid class" in msg.lower() or "does not exist" in msg.lower():
                continue
            # Outro erro — pode ser de permissao, loga e tenta proxima
            print(f"      {cls}: {msg[:80]}")
    return None


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

session_state = {"session_token": None, "installation_id": None}


def main():
    with sync_playwright() as pw:
        print("🌐 Abrindo Chrome...")
        browser = pw.chromium.launch(headless=False, channel="chrome",
                                      args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(locale="pt-BR",
                                       viewport={"width": 1400, "height": 900})
        page = context.new_page()

        print(f"📄 Navegando para {PRONTUARIO_URL}")
        page.goto(PRONTUARIO_URL, wait_until="domcontentloaded", timeout=60000)

        # Espera o login automaticamente — sem precisar apertar ENTER
        try:
            token, install_id, _ = wait_for_login(context,
                                                   timeout_seconds=300)
        except TimeoutError as e:
            print(f"\n❌ {e}")
            print("   Se voce ja estava logado, tente:")
            print("   1. Dar F5 na pagina do prontuario")
            print("   2. Ou sair e fazer login de novo")
            sys.exit(1)

        session_state["session_token"] = token
        session_state["installation_id"] = install_id or "00000000-0000-0000-0000-000000000000"
        print(f"\n   Token          : {token[:25]}...")
        print(f"   InstallationId : {session_state['installation_id']}")

        # ─── IMPORTANTE: cria uma aba NOVA na origem correta (prontuario)  ──
        # O fetch cross-origin para parse.vetsmart.com.br so funciona se
        # estivermos na origem prontuario.vetsmart.com.br (por causa do CSP
        # connect-src). Tambem nao pode estar em conta.vetsmart.com.br.
        print(f"\n📄 Abrindo aba nova em {PRONTUARIO_URL}...")
        page = context.new_page()
        page.goto(PRONTUARIO_URL, wait_until="domcontentloaded", timeout=60000)

        # Espera carregar completamente (ate o JS rodar e o Cloudflare liberar)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Confirma que estamos na origem certa
        current_url = page.url or ""
        if "prontuario.vetsmart.com.br" not in current_url:
            # Pode ter redirecionado de novo pro login, mas agora o cookie esta
            # valido — aguardar voltar
            print(f"   ⏳ Redirecionou para {current_url[:80]}, aguardando voltar...")
            for _ in range(30):
                time.sleep(1)
                current_url = page.url or ""
                if "prontuario.vetsmart.com.br" in current_url and \
                   "conta.vetsmart.com.br" not in current_url:
                    break
        print(f"   📍 Aba posicionada em: {page.url[:100]}")

        # ─── Verifica autenticacao ──────────────────────────────────────────
        print("\n🔐 Verificando autenticacao via Parse Server...")
        try:
            me = parse_query(page, "/users/me")
            print(f"   ✅ Autenticado como: {me.get('fullName') or me.get('name')} "
                  f"<{me.get('email')}>")
        except Exception as e:
            print(f"   ❌ Falha: {e}")
            print()
            print("   Diagnostico:")
            print(f"   - URL da aba atual : {page.url}")
            print(f"   - Token capturado  : {token[:25]}...")
            print()
            print("   Tente:")
            print("   1. Na janela do Chrome, abra o prontuario manualmente")
            print("   2. Rode o script de novo")
            sys.exit(1)

        # ─── Descobre classes ──────────────────────────────────────────────
        clinic_pointer = {"__type": "Pointer", "className": "Clinic",
                           "objectId": PARSE_CLINIC_ID}

        discovered = {}
        print("\n🔍 Descobrindo classes do Parse Server...")
        for group, candidates in CLASS_GROUPS.items():
            print(f"\n   [{group}]")
            # Tenta com filtro de clinica
            for filter_field in ["clinic", "clinica", "healthUnit"]:
                cls = discover_class(page, candidates,
                                     where={filter_field: clinic_pointer})
                if cls:
                    discovered[group] = (cls, filter_field)
                    break
            if group not in discovered:
                # Tenta sem filtro
                cls = discover_class(page, candidates)
                if cls:
                    discovered[group] = (cls, None)

        # Salva schema
        (OUT / "schema_discovery.json").write_text(
            json.dumps({"parse_url": PARSE_URL,
                        "clinic_id": PARSE_CLINIC_ID,
                        "discovered": {k: {"class": v[0], "filter_field": v[1]}
                                       for k, v in discovered.items()}},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # ─── Extrai cada grupo ─────────────────────────────────────────────
        print("\n📦 Extraindo dados...")
        for group, (cls, filter_field) in discovered.items():
            print(f"\n   ⬇ {group} ({cls})")
            where = None
            if filter_field:
                where = {filter_field: clinic_pointer}
            try:
                items = fetch_all(page, cls, where=where)
                out_file = OUT / f"{group}.json"
                out_file.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
                print(f"      💾 Salvo: {out_file} ({len(items)} registros)")
            except Exception as e:
                print(f"      ❌ Erro: {e}")

        print("\n" + "═" * 60)
        print("✅ Extracao concluida!")
        print(f"   Arquivos em: {OUT}/")
        print()
        print("Proximo passo — importar no banco Petorlandia:")
        print("   python scripts/migrate_vetsmart.py --only-import")
        print("═" * 60)

        print("\nPressione ENTER para fechar o navegador...")
        input()
        browser.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
