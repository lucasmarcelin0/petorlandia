"""Envia mensagens em lote no WhatsApp Web usando Selenium.

Uso:
  python scripts/send_whatsapp_batch_selenium.py --input input.json --output output.json

O script usa um perfil persistente do navegador para reaproveitar o login do
WhatsApp Web. Na primeira execucao, o usuario pode precisar escanear o QR code.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "instance" / "whatsapp_selenium_profile"
DEFAULT_BROWSER = "chrome"
STATE_FILE_NAME = "session_state.json"
READY_SELECTORS = (
    "div[role='textbox'][contenteditable='true']",
    "div[contenteditable='true'][data-tab]",
    "#side",
    "[data-testid='chat-list']",
    "[data-testid='search']",
)
QR_SELECTORS = (
    "canvas[aria-label='Scan me!']",
    "canvas[aria-label*='Scan']",
    "[data-testid='qrcode'] canvas",
    "div[data-ref] canvas",
)
SEND_BUTTON_SELECTORS = (
    "button[aria-label='Enviar']",
    "button[aria-label='Send']",
    "button span[data-icon='send']",
    "button span[data-icon='wds-ic-send-filled']",
    "[data-testid='compose-btn-send']",
)
CHAT_READY_SELECTORS = (
    "[data-testid='conversation-panel-body']",
    "[data-testid='conversation-compose-box-input']",
    "footer div[contenteditable='true']",
)
LOADING_TEXT_SNIPPETS = (
    "Carregando conversas",
    "Loading chats",
    "Carregando mensagens",
    "Loading messages",
    "Loading chat",
)
INVALID_NUMBER_TEXT_SNIPPETS = (
    "Phone number shared via url is invalid",
    "O numero de telefone compartilhado por url e invalido",
    "Número de telefone compartilhado por URL é inválido",
    "This phone number isn't on WhatsApp",
    "Este número de telefone não está no WhatsApp",
    "Esse número de telefone não está no WhatsApp",
    "Nenhuma conta do WhatsApp",
)


def _has_any_selector(driver: webdriver.Remote, selectors: tuple[str, ...]) -> bool:
    return any(driver.find_elements(By.CSS_SELECTOR, selector) for selector in selectors)


def _page_diagnostics(driver: webdriver.Remote) -> str:
    try:
        title = driver.title or "(sem titulo)"
    except Exception:
        title = "(titulo indisponivel)"

    try:
        current_url = driver.current_url or "(sem url)"
    except Exception:
        current_url = "(url indisponivel)"

    body_excerpt = ""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        body_excerpt = " ".join(body_text.split())[:280]
    except Exception:
        body_excerpt = ""

    parts = [f"titulo={title}", f"url={current_url}"]
    if body_excerpt:
        parts.append(f"texto={body_excerpt}")
    return " | ".join(parts)


def _write_output(output_path: Path, browser: str | None, results: list[dict], error: str | None = None) -> None:
    payload = {"browser": browser, "results": results}
    if error:
        payload["error"] = error
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _state_file(profile_dir: Path) -> Path:
    return profile_dir / STATE_FILE_NAME


def _load_session_state(profile_dir: Path) -> dict:
    state_path = _state_file(profile_dir)
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_session_state(profile_dir: Path, browser: str) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "preferred_browser": browser,
        "updated_at": int(time.time()),
    }
    _state_file(profile_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _body_text(driver: webdriver.Remote) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return ""


def _detect_invalid_number_message(driver: webdriver.Remote) -> str | None:
    body_text = _body_text(driver)
    normalized = " ".join(body_text.split())
    lowered = normalized.lower()
    for snippet in INVALID_NUMBER_TEXT_SNIPPETS:
        if snippet.lower() in lowered:
            return normalized[:280] or snippet
    return None


def _detect_loading_message(driver: webdriver.Remote) -> str | None:
    body_text = _body_text(driver)
    normalized = " ".join(body_text.split())
    lowered = normalized.lower()
    for snippet in LOADING_TEXT_SNIPPETS:
        if snippet.lower() in lowered:
            return normalized[:280] or snippet
    return None


def _detect_browser_binary(browser: str) -> str | None:
    candidates = {
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
    }
    for path in candidates.get(browser, []):
        if os.path.exists(path):
            return path
    return None


def _browser_profile_dir(profile_dir: Path, browser: str) -> Path:
    return profile_dir / browser


def _apply_common_chromium_options(options, profile_dir: Path) -> None:
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-features=RendererCodeIntegrity")


def _build_driver(browser: str, profile_dir: Path):
    profile_dir.mkdir(parents=True, exist_ok=True)

    if browser == "edge":
        options = webdriver.EdgeOptions()
        options.use_chromium = True
        binary = _detect_browser_binary("edge")
        if binary:
            options.binary_location = binary
        _apply_common_chromium_options(options, profile_dir)
        return webdriver.Edge(options=options)

    options = webdriver.ChromeOptions()
    binary = _detect_browser_binary("chrome")
    if binary:
        options.binary_location = binary
    _apply_common_chromium_options(options, profile_dir)
    return webdriver.Chrome(options=options)


def _resolve_browser_order(requested_browser: str, profile_dir: Path) -> list[str]:
    saved_browser = _load_session_state(profile_dir).get("preferred_browser")
    if saved_browser in {"chrome", "edge"}:
        return [saved_browser]

    browser_order = [requested_browser]
    if requested_browser == "chrome":
        browser_order.append("edge")
    else:
        browser_order.append("chrome")
    return browser_order


def _build_driver_with_fallback(preferred_browser: str, profile_dir: Path):
    browser_order = _resolve_browser_order(preferred_browser, profile_dir)

    errors = []
    for browser in browser_order:
        try:
            browser_profile_dir = _browser_profile_dir(profile_dir, browser)
            return _build_driver(browser, browser_profile_dir), browser
        except (SessionNotCreatedException, WebDriverException) as exc:
            errors.append(f"{browser}: {exc}")

    raise RuntimeError(
        "Nao foi possivel iniciar um navegador Chromium para o WhatsApp Web. "
        "Feche janelas abertas do navegador da automacao que possam estar usando o perfil do WhatsApp "
        "e tente novamente. Detalhes: " + " | ".join(errors)
    )


def _wait_for_whatsapp_ready(driver: webdriver.Remote, timeout: int = 180) -> None:
    driver.get("https://web.whatsapp.com/")
    wait = WebDriverWait(driver, 30)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

    deadline = time.time() + timeout
    qr_seen = False
    while time.time() < deadline:
        if _has_any_selector(driver, READY_SELECTORS):
            return
        if _has_any_selector(driver, QR_SELECTORS):
            qr_seen = True
        time.sleep(1.0)

    if qr_seen:
        raise RuntimeError(
            "WhatsApp Web abriu, mas o login nao foi concluido a tempo. "
            "Escaneie o QR Code na janela do navegador e tente novamente. "
            f"Diagnostico: {_page_diagnostics(driver)}"
        )

    raise RuntimeError(
        "Nao foi possivel confirmar que o WhatsApp Web ficou pronto para uso. "
        f"Diagnostico: {_page_diagnostics(driver)}"
    )


def _click_send_button(driver: webdriver.Remote, wait_timeout: int) -> bool:
    wait = WebDriverWait(driver, wait_timeout)
    last_error = None
    for selector in SEND_BUTTON_SELECTORS:
        try:
            button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            button.click()
            return True
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return False


def _press_enter_to_send(driver: webdriver.Remote) -> bool:
    for selector in READY_SELECTORS:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                element.send_keys(Keys.ENTER)
                return True
            except Exception:
                continue
    return False


def _wait_for_chat_to_open(driver: webdriver.Remote, timeout: int) -> str | None:
    deadline = time.time() + timeout
    saw_loading = False
    while time.time() < deadline:
        invalid_number_message = _detect_invalid_number_message(driver)
        if invalid_number_message:
            return invalid_number_message
        if _has_any_selector(driver, CHAT_READY_SELECTORS):
            return None
        if _detect_loading_message(driver):
            saw_loading = True
        time.sleep(1.0)

    if saw_loading:
        raise RuntimeError(
            "A conversa ficou carregando por muito tempo no WhatsApp Web. "
            f"Diagnostico: {_page_diagnostics(driver)}"
        )

    raise RuntimeError(
        "A conversa nao abriu a tempo no WhatsApp Web. "
        f"Diagnostico: {_page_diagnostics(driver)}"
    )


def _send_single_message(driver: webdriver.Remote, item: dict, wait_timeout: int = 45) -> dict:
    phone = str(item.get("phone") or "").strip()
    message = str(item.get("message") or "")
    tutor_id = item.get("tutor_id")
    tutor_name = item.get("tutor_name") or "Tutor"
    if not phone or not message:
        return {"tutor_id": tutor_id, "tutor_name": tutor_name, "status": "skipped", "error": "Dados incompletos"}

    url = f"https://web.whatsapp.com/send?phone={phone}&text={quote(message)}"
    last_error = None
    for attempt in range(2):
        driver.get(url)
        try:
            invalid_number_message = _wait_for_chat_to_open(driver, wait_timeout)
            if invalid_number_message:
                return {
                    "tutor_id": tutor_id,
                    "tutor_name": tutor_name,
                    "status": "failed",
                    "error": f"Numero sem WhatsApp ou invalido. {invalid_number_message}",
                }
            _click_send_button(driver, 12)
            time.sleep(2.2)
            return {"tutor_id": tutor_id, "tutor_name": tutor_name, "status": "sent"}
        except TimeoutException:
            if _press_enter_to_send(driver):
                time.sleep(2.2)
                return {"tutor_id": tutor_id, "tutor_name": tutor_name, "status": "sent"}
            last_error = RuntimeError(
                "Nao foi possivel localizar o botao de envio no WhatsApp Web. "
                + _page_diagnostics(driver)
            )
        except RuntimeError as exc:
            last_error = exc
        except Exception as exc:
            last_error = RuntimeError(f"Erro inesperado no envio: {exc}")

        if attempt == 0:
            try:
                driver.get("https://web.whatsapp.com/")
                WebDriverWait(driver, 20).until(lambda d: _has_any_selector(d, READY_SELECTORS))
            except Exception:
                pass

    return {
        "tutor_id": tutor_id,
        "tutor_name": tutor_name,
        "status": "failed",
        "error": str(last_error) if last_error else "Falha nao detalhada no envio.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--browser", default=DEFAULT_BROWSER, choices=["chrome", "edge"])
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--warmup-only", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])

    driver, active_browser = _build_driver_with_fallback(args.browser, Path(args.profile_dir))
    results = []
    try:
        _wait_for_whatsapp_ready(driver)
        _save_session_state(Path(args.profile_dir), active_browser)
        if args.warmup_only:
            _write_output(output_path, active_browser, results)
        else:
            for item in items:
                try:
                    results.append(_send_single_message(driver, item))
                except Exception as exc:
                    results.append(
                        {
                            "tutor_id": item.get("tutor_id"),
                            "tutor_name": item.get("tutor_name") or "Tutor",
                            "status": "failed",
                            "error": f"Erro inesperado no lote: {exc}",
                        }
                    )
                finally:
                    _write_output(output_path, active_browser, results)
                time.sleep(max(args.delay, 0))
    finally:
        try:
            driver.quit()
        finally:
            _write_output(output_path, active_browser, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
