"""
Exporta tutores e animais do VetSmart para um JSON local.

Fluxo:
1. Abre o VetSmart com Playwright em modo visivel.
2. Reaproveita cookies da sessao do navegador aberto pelo script.
3. Tenta detectar o sessionToken no localStorage.
4. Consulta a API do prontuario e salva o resultado em JSON.

Uso:
    py scripts/exportar_clientes_vetsmart.py
    py scripts/exportar_clientes_vetsmart.py --output vetsmart_clientes.json
    py scripts/exportar_clientes_vetsmart.py --headless
    py scripts/exportar_clientes_vetsmart.py --session-token r:abcd1234

Dependencias:
    pip install playwright requests
    playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PRONTUARIO_URL = "https://prontuario.vetsmart.com.br/"
CLIENTS_URL = "https://prontuario.vetsmart.com.br/api/v1/clients"
PATIENTS_URL = "https://prontuario.vetsmart.com.br/api/v1/clients/{client_id}/patients"
DEFAULT_OUTPUT = Path("vetsmart_tutores_animais.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exporta tutores e animais do VetSmart para JSON.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Arquivo JSON de saida.")
    parser.add_argument("--headless", action="store_true", help="Executa o navegador sem interface.")
    parser.add_argument("--session-token", help="Usa um sessionToken do VetSmart sem abrir o navegador.")
    parser.add_argument("--page-size", type=int, default=50, help="Quantidade de tutores por pagina.")
    parser.add_argument("--max-pages", type=int, default=0, help="Limite de paginas para teste. 0 = sem limite.")
    parser.add_argument(
        "--chrome-user-data-dir",
        type=Path,
        default=None,
        help="Diretorio de perfil do Chrome para reaproveitar a sessao ja logada.",
    )
    parser.add_argument(
        "--chrome-profile",
        default="Default",
        help="Nome do perfil dentro do user data dir do Chrome. Ex.: Default ou Profile 1.",
    )
    parser.add_argument(
        "--capture-network",
        action="store_true",
        help="Abre o VetSmart e registra chamadas de rede para descobrir os endpoints reais.",
    )
    parser.add_argument(
        "--capture-seconds",
        type=int,
        default=60,
        help="Segundos de espera para captura automatica quando nao houver stdin interativo.",
    )
    return parser.parse_args()


def prioritize_storage_keys(keys: list[str]) -> list[str]:
    priority_patterns = [
        "sessiontoken",
        "currentuser",
        "parse",
        "user",
        "token",
        "auth",
        "access",
        "session",
    ]

    def score(key: str) -> int:
        lowered = key.lower()
        total = 0
        for index, pattern in enumerate(priority_patterns):
            if pattern in lowered:
                total += (len(priority_patterns) - index) * 10
        return total

    return sorted(keys, key=score, reverse=True)


def parse_storage_value(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return value


def extract_token_string(value: Any, key: str = "") -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        if key and "sessiontoken" in key.lower() and len(value) > 10:
            return value
        if value.startswith("r:") and len(value) > 10:
            return value
        if len(value) > 20 and ("." in value or value.startswith("ey")):
            return value
        if len(value) > 30:
            return value
        return None

    if isinstance(value, list):
        for item in value:
            token = extract_token_string(item, key)
            if token:
                return token
        return None

    if isinstance(value, dict):
        session_token = value.get("sessionToken")
        if isinstance(session_token, str) and len(session_token) > 10:
            return session_token

        for field in [
            "sessionToken",
            "token",
            "access_token",
            "accessToken",
            "jwt",
            "bearer",
            "id_token",
            "idToken",
            "Authorization",
        ]:
            candidate = value.get(field)
            token = extract_token_string(candidate, field)
            if token:
                return token

        for child_key, child_value in value.items():
            token = extract_token_string(child_value, child_key)
            if token:
                return token

    return None


def build_auth_variants(token: str | None) -> list[tuple[str, dict[str, str]]]:
    base_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    variants: list[tuple[str, dict[str, str]]] = [("cookie-only", dict(base_headers))]

    if not token:
        return variants

    if token.startswith("ey") or "." in token:
        variants.insert(0, ("bearer-jwt", {**base_headers, "Authorization": f"Bearer {token}"}))
        return variants

    variants = [
        ("parse-session-header", {**base_headers, "X-Parse-Session-Token": token}),
        ("raw-authorization", {**base_headers, "Authorization": token}),
        ("x-auth-token", {**base_headers, "X-Auth-Token": token}),
        (
            "all-session-headers",
            {
                **base_headers,
                "Authorization": token,
                "X-Auth-Token": token,
                "X-Parse-Session-Token": token,
            },
        ),
        ("bearer-session-token", {**base_headers, "Authorization": f"Bearer {token}"}),
        ("cookie-only", dict(base_headers)),
    ]
    return variants


def normalize_items(data: Any, possible_keys: list[str]) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in possible_keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def default_chrome_user_data_dir() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    candidate = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    return candidate if candidate.exists() else None


def clone_chrome_profile(user_data_dir: Path, profile_name: str) -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix="vetsmart_chrome_profile_"))
    source_profile = user_data_dir / profile_name
    target_profile = temp_root / profile_name

    if not source_profile.exists():
        raise RuntimeError(f"Perfil do Chrome nao encontrado: {source_profile}")

    local_state = user_data_dir / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, temp_root / "Local State")

    ignore_names = shutil.ignore_patterns(
        "Singleton*",
        "lockfile",
        "LOCK",
        "DevToolsActivePort",
        "Last Browser",
        "Last Version",
        "Crashpad",
        "BrowserMetrics*",
    )
    shutil.copytree(source_profile, target_profile, ignore=ignore_names, dirs_exist_ok=True)
    return temp_root


def open_vetsmart_browser(
    headless: bool,
    chrome_user_data_dir: Path | None = None,
    chrome_profile: str = "Default",
) -> tuple[Any, Any, Any, Any, str | None]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright nao instalado. Rode: pip install playwright && playwright install chromium") from exc

    playwright = sync_playwright().start()
    browser = None
    temp_profile_root = None

    resolved_user_data_dir = chrome_user_data_dir or default_chrome_user_data_dir()
    if resolved_user_data_dir and resolved_user_data_dir.exists():
        try:
            print(f"Tentando usar perfil do Chrome em: {resolved_user_data_dir} [{chrome_profile}]")
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(resolved_user_data_dir),
                channel="chrome",
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    f"--profile-directory={chrome_profile}",
                ],
                locale="pt-BR",
                viewport={"width": 1400, "height": 900},
            )
            page = context.pages[0] if context.pages else context.new_page()
        except Exception as exc:
            print(f"Aviso: nao foi possivel abrir o perfil persistente do Chrome: {exc}")
            try:
                temp_profile_root = clone_chrome_profile(resolved_user_data_dir, chrome_profile)
                print(f"Tentando usar uma copia temporaria do perfil em: {temp_profile_root}")
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(temp_profile_root),
                    channel="chrome",
                    headless=headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        f"--profile-directory={chrome_profile}",
                    ],
                    locale="pt-BR",
                    viewport={"width": 1400, "height": 900},
                )
                page = context.pages[0] if context.pages else context.new_page()
            except Exception as copied_exc:
                print(f"Aviso: tambem nao foi possivel abrir a copia do perfil: {copied_exc}")
                browser = playwright.chromium.launch(
                    headless=headless,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(locale="pt-BR", viewport={"width": 1400, "height": 900})
                page = context.new_page()
    else:
        browser = playwright.chromium.launch(
            headless=headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(locale="pt-BR", viewport={"width": 1400, "height": 900})
        page = context.new_page()

    print(f"Abrindo {PRONTUARIO_URL}")
    page.goto(PRONTUARIO_URL, wait_until="domcontentloaded", timeout=60000)
    wait_for_page_to_settle(page)

    token = extract_token_from_page(page)
    if not token:
        print("Se o VetSmart pedir login, conclua o login na janela aberta.")
        print("Depois volte aqui e pressione ENTER para continuar.")
        input()
        page.goto(PRONTUARIO_URL, wait_until="domcontentloaded", timeout=60000)
        wait_for_page_to_settle(page)
        token = extract_token_from_page(page)

    return playwright, browser, context, page, token, temp_profile_root


def wait_for_page_to_settle(page: Any, timeout_ms: int = 15000) -> None:
    deadlines = time.time() + (timeout_ms / 1000)
    last_error: Exception | None = None

    while time.time() < deadlines:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception as exc:
            last_error = exc

        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception as exc:
            last_error = exc

        try:
            if page.evaluate("() => document.readyState") in {"interactive", "complete"}:
                time.sleep(1)
                return
        except Exception as exc:
            last_error = exc

        time.sleep(1)

    if last_error:
        print(f"Aviso: pagina ainda instavel apos espera inicial: {last_error}")


def attach_network_capture(context: Any, output_path: Path) -> None:
    events: list[dict[str, Any]] = []
    output_path.write_text("[]", encoding="utf-8")

    def should_track(url: str, resource_type: str | None = None) -> bool:
        lowered = url.lower()
        keywords = [
            "vetsmart",
            "parse",
            "graphql",
            "/api/",
            "client",
            "patient",
            "animal",
            "tutor",
            "owner",
        ]
        if any(keyword in lowered for keyword in keywords):
            return True
        return resource_type in {"fetch", "xhr"}

    def append_event(event: dict[str, Any]) -> None:
        events.append(event)
        try:
            output_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def safe_post_data(request: Any) -> str | None:
        try:
            payload = request.post_data
        except Exception:
            return None

        if payload is None:
            return None

        if isinstance(payload, bytes):
            return payload[:500].hex()

        if isinstance(payload, str):
            return payload[:1000]

        return str(payload)[:1000]

    def on_request(request: Any) -> None:
        if not should_track(request.url, request.resource_type):
            return
        headers = request.headers or {}
        append_event(
            {
                "type": "request",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
                "headers": headers,
                "post_data": safe_post_data(request),
            }
        )

    def on_response(response: Any) -> None:
        request = response.request
        if not should_track(response.url, request.resource_type):
            return

        body_snippet = None
        content_type = response.headers.get("content-type", "")
        if "json" in content_type.lower() or request.resource_type in {"fetch", "xhr"}:
            try:
                body_snippet = response.text()[:1000]
            except Exception:
                body_snippet = None

        append_event(
            {
                "type": "response",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": request.method,
                "url": response.url,
                "resource_type": request.resource_type,
                "status": response.status,
                "headers": response.headers,
                "body_snippet": body_snippet,
            }
        )

    def on_request_failed(request: Any) -> None:
        if not should_track(request.url, request.resource_type):
            return
        failure = request.failure
        append_event(
            {
                "type": "request_failed",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
                "failure": failure,
            }
        )

    context.on("request", on_request)
    context.on("response", on_response)
    context.on("requestfailed", on_request_failed)


def summarize_network_capture(events_path: Path) -> list[str]:
    if not events_path.exists():
        return ["Nenhum arquivo de captura foi encontrado."]

    try:
        events = json.loads(events_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Nao foi possivel ler a captura: {exc}"]

    interesting_urls: dict[str, dict[str, Any]] = {}
    keywords = ("client", "patient", "animal", "tutor", "owner", "parse", "graphql", "/api/")

    for event in events:
        url = event.get("url") or ""
        lowered = url.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue

        entry = interesting_urls.setdefault(
            url,
            {
                "methods": set(),
                "statuses": set(),
                "types": set(),
                "count": 0,
            },
        )
        entry["count"] += 1
        if event.get("method"):
            entry["methods"].add(event["method"])
        if event.get("status") is not None:
            entry["statuses"].add(str(event["status"]))
        if event.get("resource_type"):
            entry["types"].add(event["resource_type"])

    if not interesting_urls:
        return ["Nenhuma URL candidata foi encontrada na captura."]

    lines = ["URLs candidatas encontradas:"]
    sorted_items = sorted(
        interesting_urls.items(),
        key=lambda item: (item[1]["count"], item[0]),
        reverse=True,
    )
    for url, meta in sorted_items[:20]:
        methods = ",".join(sorted(meta["methods"])) or "-"
        statuses = ",".join(sorted(meta["statuses"])) or "-"
        resource_types = ",".join(sorted(meta["types"])) or "-"
        lines.append(
            f"- {methods} {url} | status={statuses} | tipo={resource_types} | ocorrencias={meta['count']}"
        )
    return lines


def extract_token_from_page(page: Any) -> str | None:
    storage_map = None
    last_error: Exception | None = None

    for _ in range(6):
        try:
            storage_map = page.evaluate(
                """
                () => {
                  const found = {};
                  for (let i = 0; i < window.localStorage.length; i++) {
                    const key = window.localStorage.key(i);
                    try {
                      const raw = window.localStorage.getItem(key);
                      try {
                        found[key] = JSON.parse(raw);
                      } catch {
                        found[key] = raw;
                      }
                    } catch (_) {}
                  }
                  return found;
                }
                """
            )
            break
        except Exception as exc:
            last_error = exc
            time.sleep(1)

    if storage_map is None:
        if last_error:
            print(f"Aviso: nao foi possivel ler localStorage ainda: {last_error}")
        return None

    for key in prioritize_storage_keys(list(storage_map.keys())):
        token = extract_token_string(storage_map.get(key), key)
        if token:
            return token
    return None


def fetch_json_in_page(page: Any, url: str, token: str | None) -> Any:
    failures: list[str] = []

    for label, headers in build_auth_variants(token):
        result = page.evaluate(
            """
            async ({ url, headers, label }) => {
              try {
                const response = await fetch(url, {
                  method: 'GET',
                  headers,
                  credentials: 'include'
                });

                const text = await response.text();
                let json = null;
                try {
                  json = JSON.parse(text);
                } catch (_) {}

                return {
                  ok: response.ok,
                  status: response.status,
                  label,
                  contentType: response.headers.get('content-type') || '',
                  textSnippet: text.slice(0, 200),
                  json
                };
              } catch (error) {
                return {
                  ok: false,
                  status: 0,
                  label,
                  error: String(error)
                };
              }
            }
            """,
            {"url": url, "headers": headers, "label": label},
        )

        if result.get("ok") and result.get("json") is not None:
            return result["json"]

        if result.get("error"):
            failures.append(f"{label}: {result['error']}")
            continue

        if result.get("ok"):
            snippet = (result.get("textSnippet") or "").replace("\n", " ")
            failures.append(f"{label}: conteudo nao-JSON ({snippet})")
            continue

        failures.append(f"{label}: HTTP {result.get('status')}")

    raise RuntimeError(f"Falha ao consultar API do VetSmart: {' | '.join(failures)}")


def export_all(page: Any, token: str | None, page_size: int, max_pages: int) -> dict[str, Any]:
    tutors: list[dict[str, Any]] = []
    animals: list[dict[str, Any]] = []
    page_number = 1
    total_pages = 1

    while page_number <= total_pages:
        if max_pages and page_number > max_pages:
            break

        print(f"Buscando tutores - pagina {page_number}/{total_pages}")
        data = fetch_json_in_page(page, f"{CLIENTS_URL}?page={page_number}&per_page={page_size}", token)
        current_tutors = normalize_items(data, ["data", "clients", "results", "items"])
        total_pages = (
            data.get("total_pages")
            or data.get("last_page")
            or data.get("pages")
            or total_pages
        ) if isinstance(data, dict) else total_pages

        for tutor in current_tutors:
            tutors.append(tutor)
            tutor_id = tutor.get("id")
            if not tutor_id:
                continue

            try:
                animals_data = fetch_json_in_page(
                    page,
                    PATIENTS_URL.format(client_id=tutor_id),
                    token,
                )
                pet_list = normalize_items(animals_data, ["data", "patients", "results", "items"])
                for animal in pet_list:
                    animal["tutor_id"] = tutor_id
                    animal["tutor_name"] = tutor.get("name") or tutor.get("nome")
                    animals.append(animal)
            except Exception as exc:
                print(f"  Aviso: nao foi possivel buscar animais do tutor {tutor_id}: {exc}")

        page_number += 1

    return {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "VetSmart",
        "token_detected": bool(token),
        "tutors": tutors,
        "animals": animals,
    }


def main() -> int:
    args = parse_args()
    playwright = None
    browser = None
    context = None
    temp_profile_root = None

    try:
        playwright, browser, context, page, detected_token, temp_profile_root = open_vetsmart_browser(
            headless=args.headless,
            chrome_user_data_dir=args.chrome_user_data_dir,
            chrome_profile=args.chrome_profile,
        )
        token = args.session_token or detected_token
        print(f"Token detectado: {'sim' if token else 'nao'}")

        if args.capture_network:
            network_output = args.output.with_name(f"{args.output.stem}_network.json")
            if network_output.exists():
                network_output.unlink()
            attach_network_capture(context, network_output)
            print()
            print("Captura de rede ativada.")
            print("1. Na janela do navegador, navegue ate a lista de tutores do VetSmart.")
            print("2. Abra um tutor e, se possivel, a lista de animais.")
            if sys.stdin and sys.stdin.isatty():
                print("3. Depois volte aqui e pressione ENTER.")
                try:
                    input()
                except EOFError:
                    print(f"Stdin indisponivel; capturando automaticamente por {args.capture_seconds} segundos...")
                    time.sleep(args.capture_seconds)
            else:
                print(f"3. Capturando automaticamente por {args.capture_seconds} segundos...")
                time.sleep(args.capture_seconds)
            print(f"Log salvo em: {network_output.resolve()}")
            print()
            for line in summarize_network_capture(network_output):
                print(line)
            return 0

        data = export_all(page, token, page_size=args.page_size, max_pages=args.max_pages)
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        print()
        print(f"Exportacao concluida: {len(data['tutors'])} tutores e {len(data['animals'])} animais")
        print(f"Arquivo salvo em: {args.output.resolve()}")
        return 0
    finally:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
        if temp_profile_root is not None:
            shutil.rmtree(temp_profile_root, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nOperacao cancelada pelo usuario.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nErro: {exc}", file=sys.stderr)
        raise SystemExit(1)
