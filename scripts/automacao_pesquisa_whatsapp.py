from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageGrab


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "automacao_pesquisa_whatsapp.json"
TEMPLATES_DIR = SCRIPT_DIR / "automacao_pesquisa_templates"

BUTTON_KEYS = (
    "send_pesquisa",
    "whatsapp_send",
    "site_tab",
    "mark_sent",
    "do_not_send",
)

DEFAULT_CONFIG = {
    "capture": {
        "width": 240,
        "height": 90,
    },
    "match": {
        "coarse_stride": 5,
        "fine_radius": 18,
        "pixel_tolerance": 36,
        "score_threshold": 0.92,
    },
    "delays": {
        "after_send_pesquisa": 1.2,
        "after_whatsapp_send": 0.9,
        "after_site_tab": 0.6,
        "after_status_click": 1.8,
    },
    "buttons": {},
}


user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@dataclass
class MatchResult:
    found: bool
    x: int | None = None
    y: int | None = None
    score: float = 0.0
    source: str = "missing"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_dirs() -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def get_cursor_pos() -> tuple[int, int]:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise RuntimeError("Não foi possível ler a posição do mouse.")
    return point.x, point.y


def set_cursor_pos(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def left_click() -> None:
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def screenshot() -> Image.Image:
    return ImageGrab.grab(all_screens=True).convert("RGB")


def template_path_for(key: str) -> Path:
    return TEMPLATES_DIR / f"{key}.png"


def prompt(message: str) -> None:
    print(message, flush=True)


def calibrate_button(config: dict, key: str) -> None:
    capture_width = int(config["capture"]["width"])
    capture_height = int(config["capture"]["height"])
    ensure_dirs()

    prompt("")
    prompt(f"Calibrando: {key}")
    prompt("Posicione o mouse no CENTRO do botão desejado.")
    input("Quando estiver pronto, pressione Enter...")

    x, y = get_cursor_pos()
    half_w = capture_width // 2
    half_h = capture_height // 2
    bbox = (x - half_w, y - half_h, x + half_w, y + half_h)
    image = screenshot().crop(bbox)
    image.save(template_path_for(key))

    config.setdefault("buttons", {})[key] = {
        "fallback_point": {"x": x, "y": y},
        "template_path": str(template_path_for(key)),
        "template_size": {"width": capture_width, "height": capture_height},
    }
    save_config(config)
    prompt(f"Template salvo para {key} em {template_path_for(key)}")


def build_sample_points(width: int, height: int) -> list[tuple[int, int]]:
    points = {
        (0, 0),
        (width // 2, 0),
        (width - 1, 0),
        (0, height // 2),
        (width // 2, height // 2),
        (width - 1, height // 2),
        (0, height - 1),
        (width // 2, height - 1),
        (width - 1, height - 1),
    }

    step_x = max(1, width // 5)
    step_y = max(1, height // 3)
    for y in range(step_y // 2, height, step_y):
        for x in range(step_x // 2, width, step_x):
            points.add((min(x, width - 1), min(y, height - 1)))

    return sorted(points)


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def score_candidate(
    screen_px,
    template_px,
    origin_x: int,
    origin_y: int,
    sample_points: list[tuple[int, int]],
    pixel_tolerance: int,
    best_so_far: float,
) -> float:
    matches = 0
    total = 0
    cutoff_misses = int((1.0 - best_so_far) * max(1, len(sample_points)) + 1)
    misses = 0

    for sx, sy in sample_points:
        total += 1
        if color_distance(screen_px[origin_x + sx, origin_y + sy], template_px[sx, sy]) <= pixel_tolerance:
            matches += 1
        else:
            misses += 1
            if misses > cutoff_misses:
                break
    return matches / max(1, total)


def find_template(config: dict, key: str) -> MatchResult:
    button = config.get("buttons", {}).get(key)
    if not button:
        return MatchResult(found=False, source="missing")

    path = Path(button.get("template_path") or "")
    if not path.exists():
        return MatchResult(found=False, source="missing")

    screen = screenshot()
    template = Image.open(path).convert("RGB")
    screen_px = screen.load()
    template_px = template.load()
    template_w, template_h = template.size
    screen_w, screen_h = screen.size

    if template_w >= screen_w or template_h >= screen_h:
        return MatchResult(found=False, source="invalid_template")

    match_config = config["match"]
    coarse_stride = int(match_config["coarse_stride"])
    fine_radius = int(match_config["fine_radius"])
    pixel_tolerance = int(match_config["pixel_tolerance"])
    score_threshold = float(match_config["score_threshold"])

    sample_points = build_sample_points(template_w, template_h)

    best_score = 0.0
    best_xy = None

    max_x = screen_w - template_w
    max_y = screen_h - template_h

    for y in range(0, max_y + 1, coarse_stride):
        for x in range(0, max_x + 1, coarse_stride):
            score = score_candidate(
                screen_px,
                template_px,
                x,
                y,
                sample_points,
                pixel_tolerance,
                best_score,
            )
            if score > best_score:
                best_score = score
                best_xy = (x, y)

    if best_xy is None:
        return MatchResult(found=False, score=0.0, source="template")

    start_x = max(0, best_xy[0] - fine_radius)
    end_x = min(max_x, best_xy[0] + fine_radius)
    start_y = max(0, best_xy[1] - fine_radius)
    end_y = min(max_y, best_xy[1] + fine_radius)

    for y in range(start_y, end_y + 1):
        for x in range(start_x, end_x + 1):
            score = score_candidate(
                screen_px,
                template_px,
                x,
                y,
                sample_points,
                pixel_tolerance,
                best_score,
            )
            if score > best_score:
                best_score = score
                best_xy = (x, y)

    if best_xy and best_score >= score_threshold:
        center_x = best_xy[0] + (template_w // 2)
        center_y = best_xy[1] + (template_h // 2)
        return MatchResult(
            found=True,
            x=center_x,
            y=center_y,
            score=best_score,
            source="template",
        )

    fallback = button.get("fallback_point") or {}
    if "x" in fallback and "y" in fallback:
        return MatchResult(
            found=True,
            x=int(fallback["x"]),
            y=int(fallback["y"]),
            score=best_score,
            source="fallback",
        )

    return MatchResult(found=False, score=best_score, source="template")


def click_button(config: dict, key: str, description: str) -> None:
    result = find_template(config, key)
    if not result.found or result.x is None or result.y is None:
        raise RuntimeError(f"Não encontrei o alvo {description}. Recalibre o botão {key}.")

    prompt(
        f"{description}: clique em ({result.x}, {result.y}) "
        f"via {result.source} com confiança {result.score:.3f}"
    )
    set_cursor_pos(result.x, result.y)
    time.sleep(0.15)
    left_click()


def run_sequence(config: dict, mode: str) -> None:
    delays = config["delays"]
    if mode == "sent":
        click_button(config, "send_pesquisa", "Enviar pesquisa")
        time.sleep(float(delays["after_send_pesquisa"]))

        click_button(config, "whatsapp_send", "Enviar no WhatsApp")
        time.sleep(float(delays["after_whatsapp_send"]))

        click_button(config, "site_tab", "Voltar para a aba do site")
        time.sleep(float(delays["after_site_tab"]))

        click_button(config, "mark_sent", "Marcar como enviado")
        time.sleep(float(delays["after_status_click"]))
        prompt("Fluxo concluído.")
        return

    if mode == "do-not-send":
        click_button(config, "site_tab", "Voltar para a aba do site")
        time.sleep(float(delays["after_site_tab"]))

        click_button(config, "do_not_send", "Não enviar por agora")
        time.sleep(float(delays["after_status_click"]))
        prompt("Fluxo de exceção concluído.")
        return

    raise ValueError(f"Modo desconhecido: {mode}")


def show_status(config: dict) -> None:
    print("Configuração atual:")
    print(json.dumps(config, ensure_ascii=False, indent=2))
    print("")
    print("Templates salvos:")
    for key in BUTTON_KEYS:
        path = template_path_for(key)
        print(f"- {key}: {'OK' if path.exists() else 'ausente'} -> {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automação visual da pesquisa de rações no desktop."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    calibrate = subparsers.add_parser("calibrate", help="Captura template de um botão.")
    calibrate.add_argument("button", choices=BUTTON_KEYS)

    run = subparsers.add_parser("run", help="Executa um fluxo completo.")
    run.add_argument("mode", choices=("sent", "do-not-send"))
    run.add_argument("--countdown", type=int, default=3, help="Segundos antes de começar.")

    subparsers.add_parser("status", help="Mostra a configuração atual.")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()

    if args.command == "calibrate":
        calibrate_button(config, args.button)
        return 0

    if args.command == "status":
        show_status(config)
        return 0

    if args.command == "run":
        countdown = max(0, int(args.countdown))
        for remaining in range(countdown, 0, -1):
            prompt(f"Iniciando em {remaining}...")
            time.sleep(1)
        run_sequence(config, args.mode)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nOperação interrompida pelo usuário.", file=sys.stderr)
        raise SystemExit(130)
