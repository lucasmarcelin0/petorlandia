# ───────────────────────────  app.py  ───────────────────────────
import os, sys, pathlib, importlib, logging, uuid, re
import requests
from collections import defaultdict
from io import BytesIO, StringIO
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from urllib.parse import urlparse, parse_qs
from typing import Iterable, Optional, Set, Dict



from datetime import datetime, timezone, date, timedelta, time
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
from PIL import Image


from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import (
    Flask,
    session,
    send_from_directory,
    send_file,
    abort,
    request,
    jsonify,
    flash,
    render_template,
    redirect,
    url_for,
    current_app,
    has_request_context,
    make_response,
)
from flask_cors import CORS
from flask_socketio import SocketIO, disconnect, emit, join_room, leave_room
from twilio.rest import Client
from itsdangerous import URLSafeTimedSerializer
from jinja2 import TemplateNotFound
import json
import csv
import unicodedata
from sqlalchemy import func, or_, exists, and_, case, true, false, inspect, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import joinedload, selectinload, aliased

# ----------------------------------------------------------------
# 1)  Alias único para “models”
# ----------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    models_pkg = importlib.import_module("petorlandia.models")
except ModuleNotFoundError:
    models_pkg = importlib.import_module("models")
sys.modules["models"] = models_pkg

# 📌 Expose every model name (CamelCase) globally
globals().update({
    name: obj
    for name, obj in models_pkg.__dict__.items()
    if name[:1].isupper()          # naive check: classes start with capital
})

from models import DataShareAccess, DataSharePartyType, DataShareRequest

# ----------------------------------------------------------------
# 2)  Flask app + config
# ----------------------------------------------------------------
load_dotenv()

app = Flask(
    __name__,
    instance_path=str(PROJECT_ROOT / "instance"),
    instance_relative_config=True,
)
app.config.from_object("config.Config")
app.config.setdefault("FRONTEND_URL", "http://127.0.0.1:5000")
app.config.update(SESSION_PERMANENT=True, SESSION_TYPE="filesystem")
CORS(app, resources={r"/surpresa*": {"origins": "*"}, r"/socket.io/*": {"origins": "*"}})
async_mode = os.getenv("SOCKETIO_ASYNC_MODE", "eventlet").strip().lower() or None
if async_mode == "eventlet":
    try:
        import eventlet  # noqa: F401  # pragma: no cover - optional dependency
    except ImportError:  # pragma: no cover - exercised in CI where eventlet is absent
        async_mode = None

socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)

# ----------------------------------------------------------------
# 3)  Extensões
# ----------------------------------------------------------------

@app.template_filter('date_now')
def date_now(format_string='%Y-%m-%d'):
    return datetime.now(BR_TZ).strftime(format_string)
# já existe no topo, logo depois das extensões:
from extensions import db, migrate, mail, login, session as session_ext, babel
from flask_login import login_user, logout_user, current_user, login_required
from flask_mail import Message as MailMessage      #  ←  adicione esta linha
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from werkzeug.routing import BuildError

db.init_app(app)
migrate.init_app(app, db, compare_type=True)
mail.init_app(app)
login.init_app(app)
session_ext.init_app(app)
babel.init_app(app)
app.config.setdefault("BABEL_DEFAULT_LOCALE", "pt_BR")

# ----------------------------------------------------------------
# 3a)  Runtime safety checks for legacy databases
# ----------------------------------------------------------------

_inventory_threshold_columns_checked = False
_inventory_movement_table_checked = False


def _ensure_inventory_threshold_columns() -> None:
    """Add inventory threshold columns when the migration wasn't applied.

    Some self-hosted deployments might skip Alembic migrations, which means
    new columns such as ``min_quantity``/``max_quantity`` are missing and the
    ``ClinicInventoryItem`` queries fail immediately.  We opportunistically
    add those columns the first time the clinic inventory is accessed so the
    UI keeps working even on older databases.  This is intentionally defensive
    and becomes a no-op once the Alembic migration runs.
    """

    global _inventory_threshold_columns_checked
    if _inventory_threshold_columns_checked:
        return

    try:
        inspector = inspect(db.engine)
        existing_columns = {
            column["name"] for column in inspector.get_columns("clinic_inventory_item")
        }
    except Exception:  # pragma: no cover - only triggered on engine init failures
        return

    statements = []
    if "min_quantity" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_item ADD COLUMN min_quantity INTEGER")
    if "max_quantity" not in existing_columns:
        statements.append("ALTER TABLE clinic_inventory_item ADD COLUMN max_quantity INTEGER")

    if statements:
        for statement in statements:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text(statement))
            except ProgrammingError:
                # Another worker may have created the column first; ignore it.
                continue

    _inventory_threshold_columns_checked = True


def _ensure_inventory_movement_table() -> None:
    """Create ``clinic_inventory_movement`` defensively when missing.

    Some self-hosted deployments occasionally skip Alembic migrations.  When
    that happens we opportunistically create the clinic inventory movement
    table the first time the inventory UI is accessed so the application keeps
    working.  Once the table exists the function becomes a cheap no-op.
    """

    global _inventory_movement_table_checked
    if _inventory_movement_table_checked:
        return

    try:
        inspector = inspect(db.engine)
    except Exception:  # pragma: no cover - engine init failures
        return

    if inspector.has_table("clinic_inventory_movement"):
        _inventory_movement_table_checked = True
        return

    try:
        ClinicInventoryMovement.__table__.create(bind=db.engine, checkfirst=True)
    except ProgrammingError:
        # Another worker may have created the table already; nothing else to do.
        pass
    finally:
        _inventory_movement_table_checked = True

# ----------------------------------------------------------------
# 4)  AWS S3 helper (lazy)
# ----------------------------------------------------------------
import boto3

AWS_ID, AWS_SECRET = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")
BUCKET = os.getenv("S3_BUCKET_NAME")

def _s3():
    return boto3.client("s3", aws_access_key_id=AWS_ID, aws_secret_access_key=AWS_SECRET)

def upload_to_s3(file, filename, folder="uploads") -> str | None:
    """Compress and upload a file to S3.

    Falls back to saving the file locally under ``static/uploads`` if the
    S3 bucket is not configured or the upload fails for any reason.  Returns
    the public URL of the uploaded file or ``None`` on failure.
    """
    try:
        fileobj = file
        content_type = file.content_type
        filename = secure_filename(filename)

        if content_type and content_type.startswith("image"):
            image = Image.open(file.stream)
            image = image.convert("RGB")
            image.thumbnail((1280, 1280))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", optimize=True, quality=85)
            buffer.seek(0)
            fileobj = buffer
            content_type = "image/jpeg"
            name, ext = os.path.splitext(filename)
            if ext.lower() not in {".jpg", ".jpeg"}:
                filename = f"{name}.jpg"

        filename = secure_filename(filename)
        key = f"{folder}/{filename}"

        # Keep a copy of the data so that we can retry if S3 upload fails
        fileobj.seek(0)
        data = fileobj.read()
        buffer = BytesIO(data)

        if BUCKET:
            try:
                buffer.seek(0)
                _s3().upload_fileobj(
                    buffer,
                    BUCKET,
                    key,
                    ExtraArgs={"ContentType": content_type},
                )
                return f"https://{BUCKET}.s3.amazonaws.com/{key}"
            except Exception as exc:  # noqa: BLE001
                app.logger.exception("S3 upload failed: %s", exc)
                buffer.seek(0)

        # Local fallback when S3 is not configured or fails
        local_path = PROJECT_ROOT / "static" / "uploads" / key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as fp:
            fp.write(buffer.read())

        return f"/static/uploads/{key}"
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Upload failed: %s", exc)
        return None

# ------------------------ Background S3 upload -------------------------
executor = ThreadPoolExecutor(max_workers=2)

def upload_profile_photo_async(user_id, data, content_type, filename):
    """Upload profile photo in a background thread and update the user."""
    def _task():
        file_storage = FileStorage(stream=BytesIO(data), filename=filename, content_type=content_type)
        image_url = upload_to_s3(file_storage, filename, folder="tutors")
        if image_url:
            with app.app_context():
                user = User.query.get(user_id)
                if user:
                    user.profile_photo = image_url
                    db.session.commit()

    executor.submit(_task)

# ----------------------------------------------------------------
# 5)  Filtros Jinja para data BR
# ----------------------------------------------------------------

BR_TZ = ZoneInfo("America/Sao_Paulo")


# ----------------------------------------------------------------
# Nim game with Socket.IO
# ----------------------------------------------------------------
NIM_TEMPLATE_ROWS = [
    [True, True, True],
    [True, True, True],
    [True, True, True],
    [True, True],
    [True, True],
]


def _nim_default_rows() -> list[list[bool]]:
    return [row.copy() for row in NIM_TEMPLATE_ROWS]


def _nim_default_state() -> dict:
    return {
        "rows": _nim_default_rows(),
        "turn": 1,
        "starting_player": 1,
        "winner": None,
        "players": {1: "Jogador 1", 2: "Jogador 2"},
        "has_played": False,
        "active_row": None,
        "bg_gradient": None,
        "stick_color": None,
        "player_emojis": ["🐾", "🐾"],
        "turn_origin_rows": _nim_default_rows(),
        "last_turn": None,
        "alternate_rows": [False] * len(NIM_TEMPLATE_ROWS),
    }


nim_rooms = defaultdict(_nim_default_state)
nim_session_rooms: Dict[str, str] = {}
nim_session_players: Dict[str, int] = {}
nim_room_members: Dict[str, set[str]] = defaultdict(set)
nim_room_players: Dict[str, dict[int, str]] = defaultdict(dict)

EASTER_EGG_STATIC_DIR = PROJECT_ROOT / "static" / "easter_egg"


def _nim_payload(room: str) -> dict:
    state = nim_rooms[room]
    return {
        "rows": [row.copy() for row in state["rows"]],
        "turn": state["turn"],
        "starting_player": state.get("starting_player", 1),
        "winner": state["winner"],
        "players": dict(state.get("players", {})),
        "has_played": bool(state.get("has_played", False)),
        "active_row": state.get("active_row"),
        "bg_gradient": state.get("bg_gradient"),
        "stick_color": state.get("stick_color"),
        "player_emojis": list(state.get("player_emojis", [])),
        "last_turn": state.get("last_turn"),
        "alternate_rows": list(state.get("alternate_rows", [])),
        "turn_origin_rows": [row.copy() for row in state.get("turn_origin_rows", _nim_default_rows())],
    }


def _nim_copy_rows(rows: Iterable[Iterable[bool]]) -> list[list[bool]]:
    copied: list[list[bool]] = []
    for index, template_row in enumerate(NIM_TEMPLATE_ROWS):
        try:
            row = rows[index]
        except (TypeError, IndexError):
            copied.append(template_row.copy())
            continue
        if not isinstance(row, (list, tuple)):
            copied.append(template_row.copy())
            continue
        copied.append([bool(value) for value in row[: len(template_row)]])
    return copied


def _nim_enforce_rules(current_state: dict, proposed_state: dict) -> dict | None:
    """Validate the proposed state according to the house rules."""

    proposed_rows = _nim_copy_rows(proposed_state.get("rows", []))
    current_rows = _nim_copy_rows(current_state.get("rows", _nim_default_rows()))

    current_start = current_state.get("starting_player", 1)
    try:
        current_start_int = int(current_start)
    except (TypeError, ValueError):
        current_start_int = 1
    if current_start_int not in (1, 2):
        current_start_int = 1

    proposed_state["starting_player"] = current_start_int

    origin_candidate = current_state.get("turn_origin_rows")
    if (
        not isinstance(origin_candidate, list)
        or len(origin_candidate) != len(NIM_TEMPLATE_ROWS)
    ):
        baseline_rows = _nim_copy_rows(current_rows)
    else:
        baseline_rows = _nim_copy_rows(origin_candidate)

    default_rows = _nim_default_rows()

    proposed_turn = proposed_state.get("turn")
    try:
        proposed_turn_int = int(proposed_turn)
    except (TypeError, ValueError):
        proposed_turn_int = None
    if proposed_turn_int not in (1, 2):
        proposed_turn_int = None

    has_played_flag = proposed_state.get("has_played")
    has_played_bool = bool(has_played_flag)

    winner_flag = proposed_state.get("winner")
    is_reset = (
        proposed_rows == default_rows
        and (winner_flag is None or winner_flag == "")
        and not has_played_bool
        and proposed_turn_int in (1, 2)
    )

    restorations_from_current: list[tuple[int, int]] = []
    for row_index, (current_row, next_row) in enumerate(zip(current_rows, proposed_rows)):
        for stick_index, (current_value, next_value) in enumerate(zip(current_row, next_row)):
            if not current_value and next_value:
                restorations_from_current.append((row_index, stick_index))

    if restorations_from_current and not is_reset:
        return None

    removed_by_row_turn: list[int] = [0] * len(NIM_TEMPLATE_ROWS)

    for row_index, (baseline_row, next_row) in enumerate(zip(baseline_rows, proposed_rows)):
        for stick_index, (baseline_value, next_value) in enumerate(zip(baseline_row, next_row)):
            if baseline_value and not next_value:
                removed_by_row_turn[row_index] += 1

    total_removed_turn = sum(removed_by_row_turn)
    rows_with_removals = [
        index for index, count in enumerate(removed_by_row_turn) if count > 0
    ]

    current_turn = current_state.get("turn")
    try:
        current_turn_int = int(current_turn)
    except (TypeError, ValueError):
        current_turn_int = 1
    if current_turn_int not in (1, 2):
        current_turn_int = 1

    next_turn = proposed_state.get("turn")
    try:
        next_turn_int = int(next_turn)
    except (TypeError, ValueError):
        next_turn_int = current_turn_int
    if next_turn_int not in (1, 2):
        next_turn_int = current_turn_int

    proposed_state["turn"] = next_turn_int
    turn_changed = current_turn_int != next_turn_int

    current_alternates = current_state.get("alternate_rows")
    if not isinstance(current_alternates, (list, tuple)):
        normalized_alternates = [False] * len(NIM_TEMPLATE_ROWS)
    else:
        normalized_alternates = [
            bool(current_alternates[index]) if index < len(current_alternates) else False
            for index in range(len(NIM_TEMPLATE_ROWS))
        ]

    if is_reset:
        next_start = 2 if current_start_int == 1 else 1
        proposed_state["rows"] = proposed_rows
        proposed_state["has_played"] = False
        proposed_state["turn"] = next_start
        proposed_state["winner"] = None
        proposed_state["alternate_rows"] = [False] * len(NIM_TEMPLATE_ROWS)
        proposed_state["starting_player"] = next_start
        return proposed_state

    if total_removed_turn > 3:
        return None

    if len(rows_with_removals) > 1:
        return None

    if turn_changed and total_removed_turn == 0:
        return None

    for row_index, removed_count in enumerate(removed_by_row_turn):
        if normalized_alternates[row_index] and removed_count > 1:
            return None

    # Update alternate row metadata based on the resulting board.
    next_alternates = normalized_alternates.copy()
    for row_index, row in enumerate(proposed_rows):
        remaining = sum(1 for stick in row if stick)
        if remaining <= 1:
            next_alternates[row_index] = False
            continue

        if len(row) == 3:
            left, middle, right = row
            if left and right and not middle:
                next_alternates[row_index] = True

    proposed_state["rows"] = proposed_rows
    proposed_state["alternate_rows"] = next_alternates

    if turn_changed:
        proposed_state["has_played"] = False
    else:
        proposed_state["has_played"] = total_removed_turn > 0

    # Winner is only valid when the board is empty. With the misère rule, the
    # winner corresponds to the opponent of the player who removed the last
    # stick, so any inconsistent winner flag is cleared here.
    all_taken = all(not any(row) for row in proposed_rows)
    if not all_taken:
        proposed_state["winner"] = None
    else:
        if turn_changed:
            proposed_state["winner"] = next_turn_int
        else:
            proposed_state["winner"] = 1 if next_turn_int == 2 else 2

    proposed_state["starting_player"] = current_start_int
    return proposed_state


def _nim_player_name(state: dict, index: int) -> str:
    players = state.get("players")
    if isinstance(players, dict):
        for key in (index, str(index)):
            value = players.get(key)
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
    return f"Jogador {index}"


def _nim_build_turn_summary(
    previous_state: dict, next_state: dict, baseline_rows: list[list[bool]]
) -> dict | None:
    prev_turn = previous_state.get("turn", 1)
    next_turn = next_state.get("turn", prev_turn)
    prev_winner = previous_state.get("winner")
    next_winner = next_state.get("winner")

    removed_segments: list[dict[str, int]] = []
    total_removed = 0
    total_restored = 0

    for index, (start_row, end_row) in enumerate(
        zip(baseline_rows, next_state.get("rows", []))
    ):
        removed = 0
        restored = 0
        for start_value, end_value in zip(start_row, end_row):
            start_bool = bool(start_value)
            end_bool = bool(end_value)
            if start_bool and not end_bool:
                removed += 1
            elif not start_bool and end_bool:
                restored += 1
        if removed:
            removed_segments.append({"row": index + 1, "count": removed})
            total_removed += removed
        total_restored += restored

    previous_player_name = _nim_player_name(next_state, prev_turn)
    next_player_name = _nim_player_name(next_state, next_turn)

    message_parts = []
    for segment in removed_segments:
        count = segment["count"]
        row_label = segment["row"]
        noun = "palito" if count == 1 else "palitos"
        message_parts.append(f"{count} {noun} da linha {row_label}")

    if not message_parts:
        removed_text = ""
    elif len(message_parts) == 1:
        removed_text = message_parts[0]
    else:
        removed_text = ", ".join(message_parts[:-1]) + " e " + message_parts[-1]

    if next_winner in (1, 2) and next_winner == prev_turn:
        if removed_text:
            message = (
                f"{previous_player_name} removeu {removed_text} e venceu a partida!"
            )
        else:
            message = f"{previous_player_name} venceu a partida!"
    elif next_winner in (1, 2):
        winner_name = _nim_player_name(next_state, next_winner)
        if removed_text:
            message = (
                f"{previous_player_name} removeu {removed_text} e ficou sem jogadas. "
                f"{winner_name} venceu a partida!"
            )
        else:
            message = f"{winner_name} venceu a partida!"
    elif total_removed:
        if removed_text:
            message = (
                f"{previous_player_name} removeu {removed_text}. "
                f"Agora é a vez de {next_player_name}."
            )
        else:
            message = f"{previous_player_name} passou a vez."
    elif total_restored:
        message = f"{previous_player_name} reiniciou o tabuleiro."
    elif prev_winner and not next_winner:
        message = "Uma nova partida foi iniciada."
    else:
        message = f"{previous_player_name} passou a vez."

    return {
        "player": int(prev_turn) if isinstance(prev_turn, int) else prev_turn,
        "player_name": previous_player_name,
        "next_player": int(next_turn) if isinstance(next_turn, int) else next_turn,
        "next_player_name": next_player_name,
        "removed": removed_segments,
        "total_removed": total_removed,
        "restored": total_restored,
        "winner": int(next_winner)
        if isinstance(next_winner, int) and next_winner in (1, 2)
        else None,
        "message": message,
    }


def _nim_turn_metadata(previous_state: dict, next_state: dict) -> tuple[dict | None, list[list[bool]]]:
    baseline = previous_state.get("turn_origin_rows")
    if not isinstance(baseline, list) or len(baseline) != len(NIM_TEMPLATE_ROWS):
        baseline_rows = _nim_default_rows()
    else:
        baseline_rows = _nim_copy_rows(baseline)

    prev_turn = previous_state.get("turn")
    next_turn = next_state.get("turn")
    prev_winner = previous_state.get("winner")
    next_winner = next_state.get("winner")

    turn_changed = prev_turn != next_turn
    winner_declared = (next_winner and next_winner != prev_winner)
    winner_cleared = prev_winner and not next_winner

    last_turn_summary = previous_state.get("last_turn")
    next_origin_rows = baseline_rows

    if winner_cleared:
        last_turn_summary = None
        next_origin_rows = _nim_copy_rows(next_state.get("rows", _nim_default_rows()))
    elif turn_changed or winner_declared:
        summary = _nim_build_turn_summary(previous_state, next_state, baseline_rows)
        last_turn_summary = summary
        next_origin_rows = _nim_copy_rows(next_state.get("rows", _nim_default_rows()))

    return last_turn_summary, next_origin_rows


def _normalize_nim_payload(payload: dict | None, current_state: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None

    rows = payload.get("rows")
    if not isinstance(rows, (list, tuple)) or len(rows) != len(NIM_TEMPLATE_ROWS):
        return None

    normalized_rows: list[list[bool]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != len(NIM_TEMPLATE_ROWS[index]):
            return None
        normalized_rows.append([bool(value) for value in row])

    turn = payload.get("turn", current_state["turn"])
    try:
        turn_int = int(turn)
    except (TypeError, ValueError):
        turn_int = current_state["turn"]
    if turn_int not in (1, 2):
        turn_int = 1

    winner_value = payload.get("winner")
    if winner_value in (None, "", "null"):
        winner_int = None
    else:
        try:
            winner_int = int(winner_value)
        except (TypeError, ValueError):
            winner_int = None
        if winner_int not in (1, 2):
            winner_int = None

    has_played_raw = payload.get("has_played")
    if has_played_raw is None:
        has_played_raw = current_state.get("has_played", False)
    if isinstance(has_played_raw, str):
        has_played_raw = has_played_raw.strip().lower()
        if has_played_raw in {"1", "true", "yes", "on"}:
            has_played = True
        elif has_played_raw in {"0", "false", "no", "off", ""}:
            has_played = False
        else:
            has_played = current_state.get("has_played", False)
    else:
        has_played = bool(has_played_raw)

    has_active_row_key = "active_row" in payload or "activeRow" in payload
    active_row_value = payload.get("active_row")
    if active_row_value is None and "active_row" not in payload:
        active_row_value = payload.get("activeRow")
    if active_row_value is None and not has_active_row_key:
        active_row_value = current_state.get("active_row")
    try:
        active_row_int = int(active_row_value)
    except (TypeError, ValueError):
        active_row_int = None
    if active_row_int is not None and not (
        0 <= active_row_int < len(NIM_TEMPLATE_ROWS)
    ):
        active_row_int = None

    bg_gradient_value = payload.get("bg_gradient")
    if bg_gradient_value is None:
        bg_gradient_value = payload.get("bgGradient")
    if bg_gradient_value is None:
        bg_gradient = current_state.get("bg_gradient")
    else:
        bg_gradient_text = str(bg_gradient_value).strip()
        bg_gradient = bg_gradient_text[:200] if bg_gradient_text else current_state.get("bg_gradient")

    stick_color_value = payload.get("stick_color")
    if stick_color_value is None:
        stick_color_value = payload.get("stickColor")
    if stick_color_value is None:
        stick_color = current_state.get("stick_color")
    else:
        stick_color_text = str(stick_color_value).strip()
        stick_color = stick_color_text[:50] if stick_color_text else current_state.get("stick_color")

    player_emojis_value = payload.get("player_emojis")
    if player_emojis_value is None:
        player_emojis_value = payload.get("playerEmojis")
    if isinstance(player_emojis_value, (list, tuple)):
        normalized_emojis: list[str] = []
        for index in range(2):
            try:
                raw = player_emojis_value[index]
            except IndexError:
                raw = ""
            text = str(raw).strip()
            normalized_emojis.append(text[:8] if text else "🐾")
        player_emojis = normalized_emojis
    else:
        current_emojis = current_state.get("player_emojis")
        if isinstance(current_emojis, (list, tuple)):
            player_emojis = [str(value)[:8] for value in current_emojis[:2]]
            if len(player_emojis) < 2:
                player_emojis.extend(["🐾"] * (2 - len(player_emojis)))
        else:
            player_emojis = ["🐾", "🐾"]

    starting_player_value = payload.get("starting_player")
    if starting_player_value is None:
        starting_player_value = payload.get("startingPlayer")
    if starting_player_value is None:
        starting_player = current_state.get("starting_player", 1)
    else:
        try:
            starting_player = int(starting_player_value)
        except (TypeError, ValueError):
            starting_player = current_state.get("starting_player", 1)
        if starting_player not in (1, 2):
            starting_player = current_state.get("starting_player", 1) or 1

    return {
        "rows": normalized_rows,
        "turn": turn_int,
        "winner": winner_int,
        "players": _normalize_nim_players(payload.get("players"), current_state.get("players", {})),
        "has_played": has_played,
        "active_row": active_row_int,
        "bg_gradient": bg_gradient,
        "stick_color": stick_color,
        "player_emojis": player_emojis,
        "starting_player": starting_player,
    }


def _normalize_nim_players(players: dict | None, current_players: dict | None) -> dict:
    defaults = {1: "Jogador 1", 2: "Jogador 2"}
    normalized: dict[int, str] = {}

    if not isinstance(current_players, dict):
        current_players = {}

    if not isinstance(players, dict):
        players = {}

    for player_index in (1, 2):
        fallback = current_players.get(player_index) or defaults[player_index]
        value = (
            players.get(player_index)
            or players.get(str(player_index))
            or fallback
        )
        text = str(value).strip()
        text = " ".join(text.split())
        if not text:
            text = defaults[player_index]
        normalized[player_index] = text[:40]

    return normalized


@app.route("/surpresa")
def secret_game():
    if not EASTER_EGG_STATIC_DIR.exists():
        abort(404)
    return send_from_directory(str(EASTER_EGG_STATIC_DIR), "index.html")


@app.route("/surpresa/<path:filename>")
def secret_game_static(filename: str):
    return send_from_directory(str(EASTER_EGG_STATIC_DIR), filename)


def _nim_room_from_request() -> str:
    room = (
        request.args.get("room", "")
        or request.args.get("sala", "")
        or ""
    ).strip()
    if not room:
        return "lobby"
    sanitized = "".join(ch for ch in room if ch.isalnum() or ch in {"_", "-"})
    return sanitized[:32].upper() or "lobby"


@socketio.on("connect")
def nim_connect():  # pragma: no cover - exercised via browser
    room = _nim_room_from_request()
    members = nim_room_members[room]
    if len(members) >= 2:
        emit(
            "room_full",
            {
                "message": "Sala cheia. Somente dois jogadores podem participar desta partida.",
                "room": room,
            },
        )
        disconnect()
        return

    nim_session_rooms[request.sid] = room
    players_map = nim_room_players[room]

    # Clear out any stale seat assignments that might linger if a client
    # disconnected without triggering ``nim_disconnect`` (for example when the
    # server restarted).
    for seat, occupant in list(players_map.items()):
        if occupant not in members:
            players_map.pop(seat, None)

    assigned_seat = None
    for candidate in (1, 2):
        occupant = players_map.get(candidate)
        if not occupant:
            assigned_seat = candidate
            break

    if assigned_seat is None:
        # Should not happen because the room is limited to two players, but
        # default to seat ``1`` to avoid leaving the session without a slot.
        assigned_seat = 1

    players_map[assigned_seat] = request.sid
    nim_session_players[request.sid] = assigned_seat
    members.add(request.sid)
    join_room(room)
    emit("update_state", _nim_payload(room))


@socketio.on("move")
def nim_move(data):  # pragma: no cover - exercised via browser
    room = nim_session_rooms.get(request.sid)
    if not room:
        room = _nim_room_from_request()
        nim_session_rooms[request.sid] = room
    current_state = nim_rooms[room]
    player_seat = nim_session_players.get(request.sid)
    normalized = _normalize_nim_payload(data, current_state)
    if not normalized:
        emit("update_state", _nim_payload(room))
        return

    current_turn = current_state.get("turn")
    try:
        current_turn_int = int(current_turn)
    except (TypeError, ValueError):
        current_turn_int = 1
    if current_turn_int not in (1, 2):
        current_turn_int = 1

    board_changed = (
        normalized.get("rows") != current_state.get("rows")
        or normalized.get("turn") != current_turn_int
        or normalized.get("winner") != current_state.get("winner")
        or normalized.get("has_played") != current_state.get("has_played")
        or normalized.get("active_row") != current_state.get("active_row")
    )

    if board_changed and player_seat != current_turn_int:
        emit("update_state", _nim_payload(room))
        return

    enforced = _nim_enforce_rules(current_state, normalized)
    if not enforced:
        emit("update_state", _nim_payload(room))
        return

    last_turn_summary, next_origin_rows = _nim_turn_metadata(current_state, enforced)
    enforced["turn_origin_rows"] = next_origin_rows
    enforced["last_turn"] = last_turn_summary

    nim_rooms[room] = enforced
    emit("update_state", _nim_payload(room), room=room)


@socketio.on("disconnect")
def nim_disconnect():  # pragma: no cover - exercised via browser
    room = nim_session_rooms.pop(request.sid, None)
    seat = nim_session_players.pop(request.sid, None)
    if room:
        members = nim_room_members.get(room)
        if members and request.sid in members:
            members.discard(request.sid)
            if not members:
                nim_room_members.pop(room, None)
        players = nim_room_players.get(room)
        if players and seat in players and players.get(seat) == request.sid:
            players.pop(seat, None)
            if not players:
                nim_room_players.pop(room, None)
        leave_room(room)


def local_date_range_to_utc(start_dt, end_dt):
    """Convert local date/datetime boundaries to naive UTC datetimes."""

    def _convert(value):
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, time.min)
        if value.tzinfo is None:
            value = value.replace(tzinfo=BR_TZ)
        else:
            value = value.astimezone(BR_TZ)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return _convert(start_dt), _convert(end_dt)


@app.template_filter("datetime_brazil")
def datetime_brazil(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:

            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M")
    return value

@app.template_filter("format_datetime_brazil")
def format_datetime_brazil(value, fmt="%d/%m/%Y %H:%M"):
    if value is None:
        return ""

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(BR_TZ)
        return value.strftime(fmt)

    if isinstance(value, date):
        return value.strftime(fmt)

    return value


@app.template_filter("format_timedelta")
def format_timedelta(value):
    """Format a ``timedelta`` as ``'Xh Ym'``."""
    total_seconds = int(value.total_seconds())
    if total_seconds <= 0:
        return "0h 0m"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"

@app.template_filter("digits_only")
def digits_only(value):
    """Return only the digits from a string."""
    return "".join(filter(str.isdigit, value)) if value else ""


@app.template_filter("payment_status_label")
def payment_status_label(value):
    """Translate payment status codes to Portuguese labels."""
    mapping = {
        "pending": "Pendente",
        "success": "Aprovado",
        "completed": "Aprovado",
        "approved": "Aprovado",
        "failure": "Falha no pagamento",
        "failed": "Falha no pagamento",
    }
    return mapping.get(value.lower(), value) if value else ""


PAYER_TYPE_LABELS = {
    "plan": "Plano",
    "particular": "Particular",
}


def payer_type_label(value):
    return PAYER_TYPE_LABELS.get(value or "particular", "Particular")


def default_payer_type_for_consulta(consulta):
    return "plan" if getattr(consulta, "health_subscription_id", None) else "particular"


@app.template_filter("payer_label")
def payer_label_filter(value):
    return payer_type_label(value)


@app.template_filter('coverage_label')
def coverage_label_filter(value):
    return coverage_label(value)


@app.template_filter('coverage_badge')
def coverage_badge_filter(value):
    return coverage_badge(value)


def _resolve_species_name(species) -> str | None:
    if not species:
        return None
    name = getattr(species, "name", None)
    if isinstance(name, str) and name.strip():
        return name
    if isinstance(species, str):
        return species
    return str(species)


@app.template_filter('species_display')
def species_display(species) -> str:
    """Return a readable label for a Species relationship or string."""
    return _resolve_species_name(species) or "Espécie não informada"


def _normalize_species_token(species: str | None) -> str | None:
    name = _resolve_species_name(species)
    if not name:
        return None
    normalized = unicodedata.normalize("NFKD", name)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents).strip("-")
    token = cleaned.lower()
    return token or None


_SPECIES_VISUAL_TOKENS = {
    "cao": "dog",
    "cachorro": "dog",
    "canino": "dog",
    "gato": "cat",
    "felino": "cat",
    "gata": "cat",
    "ave": "bird",
    "passaro": "bird",
    "canario": "bird",
    "papagaio": "bird",
    "coelho": "rabbit",
    "lagarto": "reptile",
    "jabuti": "reptile",
    "tartaruga": "reptile",
    "reptil": "reptile",
    "hamster": "rodent",
    "roedor": "rodent",
}


def _resolve_species_visual(species) -> str:
    token = _normalize_species_token(species)
    if not token:
        return "default"
    if token in _SPECIES_VISUAL_TOKENS:
        return _SPECIES_VISUAL_TOKENS[token]
    root = token.split("-")[0]
    return _SPECIES_VISUAL_TOKENS.get(root, "default")


@app.template_filter("species_visual_token")
def species_visual_token_filter(species) -> str:
    """Return a semantic token used to colorize and iconize species placeholders."""
    return _resolve_species_visual(species)


def _resolve_size_data(weight):
    try:
        value = float(weight)
    except (TypeError, ValueError):
        value = None

    if value is None or value <= 0:
        return "Porte indefinido", "unknown"
    if value < 10:
        return "Porte pequeno", "small"
    if value < 25:
        return "Porte médio", "medium"
    return "Porte grande", "large"


@app.template_filter('animal_size_label')
def animal_size_label(weight) -> str:
    return _resolve_size_data(weight)[0]


@app.template_filter('animal_size_token')
def animal_size_token(weight) -> str:
    return _resolve_size_data(weight)[1]

# ----------------------------------------------------------------
# 6)  Forms e helpers
# ----------------------------------------------------------------
from forms import (
    AddToCartForm,
    AnimalForm,
    AppointmentDeleteForm,
    AppointmentForm,
    CartAddressForm,
    ChangePasswordForm,
    ClinicAddSpecialistForm,
    ClinicAddStaffForm,
    ClinicForm,
    ClinicHoursForm,
    ClinicInviteCancelForm,
    ClinicInviteResendForm,
    ClinicInviteResponseForm,
    ClinicInviteVeterinarianForm,
    ClinicStaffPermissionForm,
    DeleteAccountForm,
    DeliveryRequestForm,
    EditProfileForm,
    InventoryItemForm,
    LoginForm,
    MessageForm,
    OrcamentoForm,
    OrderItemForm,
    ProductPhotoForm,
    ProductUpdateForm,
    RegistrationForm,
    ResetPasswordForm,
    ResetPasswordRequestForm,
    SubscribePlanForm,
    ConsultaPlanAuthorizationForm,
    VetScheduleForm,
    VetSpecialtyForm,
    VeterinarianMembershipCheckoutForm,
    VeterinarianMembershipCancelTrialForm,
    VeterinarianMembershipRequestNewTrialForm,
    VeterinarianProfileForm,
    VeterinarianPromotionForm,
)
from helpers import (
    appointments_to_events,
    calcular_idade,
    clinicas_do_usuario,
    consulta_to_event,
    ensure_veterinarian_membership,
    exam_to_event,
    get_appointment_duration,
    get_available_times,
    get_weekly_schedule,
    grant_veterinarian_role,
    group_appointments_by_day,
    group_vet_schedules_by_day,
    has_conflict_for_slot,
    has_schedule_conflict,
    has_veterinarian_profile,
    is_slot_available,
    is_veterinarian,
    parse_data_nascimento,
    to_timezone_aware,
    unique_items_by_id,
    vaccine_to_event,
    veterinarian_required,
)
from services import (
    build_usage_history,
    coverage_badge,
    coverage_label,
    evaluate_consulta_coverages,
    find_active_share,
    get_calendar_access_scope,
    insurer_token_valid,
    log_data_share_event,
    summarize_plan_metrics,
)
from services.animal_search import search_animals


def current_user_clinic_id():
    """Return the clinic ID associated with the current user, if any."""
    if not current_user.is_authenticated:
        return None
    if has_veterinarian_profile(current_user):
        return getattr(current_user.veterinario, 'clinica_id', None)
    return current_user.clinica_id


def _collect_clinic_ids(viewer=None, clinic_scope=None):
    """Return a set with clinic IDs derived from the viewer and scope hints."""
    clinic_ids = set()

    if clinic_scope:
        if isinstance(clinic_scope, (list, tuple, set)):
            clinic_ids.update(cid for cid in clinic_scope if cid)
        else:
            if clinic_scope:
                clinic_ids.add(clinic_scope)

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer:
        viewer_clinic = getattr(viewer, 'clinica_id', None)
        if viewer_clinic:
            clinic_ids.add(viewer_clinic)

        vet_profile = getattr(viewer, 'veterinario', None)
        if vet_profile:
            primary = getattr(vet_profile, 'clinica_id', None)
            if primary:
                clinic_ids.add(primary)
            for clinic in getattr(vet_profile, 'clinicas', []) or []:
                clinic_id = getattr(clinic, 'id', None)
                if clinic_id:
                    clinic_ids.add(clinic_id)

    return clinic_ids


def _viewer_parties(viewer=None, clinic_scope=None):
    parties = []

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    for clinic_id in clinic_ids:
        if clinic_id:
            parties.append((DataSharePartyType.clinic, clinic_id))

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer:
        worker = getattr(viewer, 'worker', None)
        viewer_id = getattr(viewer, 'id', None)
        if worker == 'veterinario' and viewer_id:
            parties.append((DataSharePartyType.veterinarian, viewer_id))
        elif worker == 'seguradora' and viewer_id:
            parties.append((DataSharePartyType.insurer, viewer_id))

    unique = []
    seen = set()
    for party in parties:
        if not party or party[1] is None:
            continue
        key = (party[0].value if isinstance(party[0], DataSharePartyType) else party[0], party[1])
        if key in seen:
            continue
        seen.add(key)
        unique.append(party)
    return unique


def _shared_user_clause(viewer=None, clinic_scope=None):
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    if not parties:
        return None

    now = datetime.utcnow()
    query = (
        db.session.query(DataShareAccess.user_id)
        .filter(DataShareAccess.user_id.isnot(None))
        .filter(DataShareAccess.revoked_at.is_(None))
        .filter(or_(DataShareAccess.expires_at.is_(None), DataShareAccess.expires_at > now))
    )
    party_clauses = [
        and_(
            DataShareAccess.granted_to_type == party_type,
            DataShareAccess.granted_to_id == party_id,
        )
        for party_type, party_id in parties
    ]
    if not party_clauses:
        return None
    query = query.filter(or_(*party_clauses))
    return User.id.in_(query.subquery())


def _user_visibility_clause(viewer=None, clinic_scope=None):
    """Return a SQLAlchemy clause enforcing user privacy for listings."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer and getattr(viewer, 'role', None) == 'admin':
        return true()

    clauses = []

    if viewer:
        viewer_id = getattr(viewer, 'id', None)
        if viewer_id:
            clauses.append(User.id == viewer_id)
            clauses.append(User.added_by_id == viewer_id)

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    if clinic_ids:
        clauses.append(User.clinica_id.in_(list(clinic_ids)))

    shared_clause = _shared_user_clause(viewer=viewer, clinic_scope=clinic_scope)
    if shared_clause is not None:
        clauses.append(shared_clause)

    if not clauses:
        return false()

    return or_(*clauses)


def _can_view_user(user, viewer=None, clinic_scope=None):
    """Return ``True`` if the viewer can see the given user respecting privacy."""
    if user is None:
        return False

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer is None:
        return False

    if getattr(viewer, 'role', None) == 'admin':
        return True

    viewer_id = getattr(viewer, 'id', None)
    if viewer_id and user.id == viewer_id:
        return True

    if viewer_id and user.added_by_id == viewer_id:
        return True

    if _resolve_shared_access_for_user(user, viewer=viewer, clinic_scope=clinic_scope):
        return True

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    return bool(user.clinica_id and user.clinica_id in clinic_ids)


def _resolve_shared_access_for_user(user, viewer=None, clinic_scope=None):
    if not user:
        return None
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    return find_active_share(parties, user_id=getattr(user, 'id', None))


def _resolve_shared_access_for_animal(animal, viewer=None, clinic_scope=None):
    if not animal:
        return None
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    user_id = getattr(animal, 'user_id', None)
    animal_id = getattr(animal, 'id', None)
    return find_active_share(parties, user_id=user_id, animal_id=animal_id)


def _resolve_shared_access_for_consulta(consulta, viewer=None, clinic_scope=None):
    if not consulta:
        return None
    if getattr(consulta, 'animal', None):
        return _resolve_shared_access_for_animal(consulta.animal, viewer=viewer, clinic_scope=clinic_scope)
    return None


def _log_data_share(access, *, event_type, resource_type, resource_id=None, actor=None):
    if not access:
        return None
    return log_data_share_event(
        access,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor,
    )


def _default_share_duration(days=None):
    value = days or current_app.config.get('DATA_SHARE_DEFAULT_DAYS', 30)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 30
    return max(value, 1)


def _serialize_share_request(req):
    clinic_name = getattr(req.clinic, 'nome', None)
    requester_name = getattr(req.requester, 'name', None)
    status = req.status
    if status == 'pending' and req.expires_at and req.expires_at <= datetime.utcnow():
        status = 'expired'
    return {
        'id': req.id,
        'token': req.token,
        'message': req.message,
        'status': status,
        'expires_at': req.expires_at.isoformat() if req.expires_at else None,
        'created_at': req.created_at.isoformat() if req.created_at else None,
        'clinic': clinic_name,
        'requester': requester_name,
        'animal': getattr(req.animal, 'name', None),
    }


def _serialize_share_access(access):
    clinic_name = getattr(access.source_clinic, 'nome', None)
    return {
        'id': access.id,
        'clinic': clinic_name,
        'expires_at': access.expires_at.isoformat() if access.expires_at else None,
        'expires_label': access.expires_at.strftime('%d/%m/%Y') if access.expires_at else None,
        'grant_reason': access.grant_reason,
    }


def _send_share_email(subject, recipients, body):
    if not recipients:
        return False
    try:
        msg = MailMessage(subject=subject, recipients=recipients, body=body)
        mail.send(msg)
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning('Falha ao enviar email de compartilhamento: %s', exc)
        return False


def _send_share_sms(phone, body):
    if not phone or not body:
        return False
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_SMS_FROM')
    if not all([account_sid, auth_token, from_number]):
        return False
    number = formatar_telefone(phone)
    try:
        client = Client(account_sid, auth_token)
        client.messages.create(body=body, from_=from_number, to=number)
        return True
    except Exception as exc:  # pragma: no cover - avoid test flakes
        current_app.logger.warning('Falha ao enviar SMS: %s', exc)
        return False


def _share_request_link(token):
    try:
        return url_for('tutor_sharing_dashboard', token=token, _external=True)
    except Exception:  # pragma: no cover - fallback when outside request
        return None


def _notify_tutor_share_request(share_request):
    tutor = share_request.tutor
    clinic_name = getattr(share_request.clinic, 'nome', 'uma clínica parceira')
    link = _share_request_link(share_request.token)
    lines = [
        f'Olá {tutor.name or "tutor"},',
        '',
        f'A clínica {clinic_name} está solicitando acesso aos dados do seu tutorado.',
    ]
    if share_request.animal:
        lines.append(f'Animal: {share_request.animal.name}.')
    if share_request.message:
        lines.extend(['', f'Mensagem da clínica:', share_request.message])
    if link:
        lines.extend(['', 'Para revisar o pedido, acesse o link seguro:', link])
    subject = 'Novo pedido de compartilhamento de dados - PetOrlândia'
    _send_share_email(subject, [tutor.email] if tutor.email else [], '\n'.join(lines))
    if tutor.phone:
        sms_body = f'PetOrlândia: {clinic_name} pediu acesso aos seus dados. Confirme em {link}' if link else (
            f'PetOrlândia: {clinic_name} pediu acesso aos seus dados.'
        )
        _send_share_sms(tutor.phone, sms_body)


def _notify_clinic_share_decision(share_request, approved):
    requester = share_request.requester
    if not requester:
        return
    clinic_name = getattr(share_request.clinic, 'nome', 'sua clínica')
    if approved:
        subject = 'Compartilhamento aprovado - PetOrlândia'
        status_line = 'foi aprovado'
    else:
        subject = 'Compartilhamento negado - PetOrlândia'
        status_line = 'foi negado'
    lines = [
        f'Olá {requester.name or "time"},',
        '',
        f'O pedido de compartilhamento com {share_request.tutor.name} {status_line}.',
        f'Clínica: {clinic_name}',
    ]
    if share_request.animal:
        lines.append(f'Animal: {share_request.animal.name}')
    if share_request.denial_reason and not approved:
        lines.extend(['', f'Motivo informado: {share_request.denial_reason}'])
    _send_share_email(subject, [requester.email] if requester.email else [], '\n'.join(lines))
    if requester.phone:
        sms_body = f'PetOrlândia: pedido com {share_request.tutor.name} {status_line}.'
        _send_share_sms(requester.phone, sms_body)


def _serialize_tutor_share_payload(user):
    now = datetime.utcnow()
    pending = (
        DataShareRequest.query.filter_by(tutor_id=user.id)
        .order_by(DataShareRequest.created_at.desc())
        .all()
    )
    active_access = (
        DataShareAccess.query.filter_by(user_id=user.id)
        .filter(DataShareAccess.revoked_at.is_(None))
        .filter(or_(DataShareAccess.expires_at.is_(None), DataShareAccess.expires_at > now))
        .order_by(DataShareAccess.created_at.desc())
        .all()
    )
    return {
        'pending_requests': [_serialize_share_request(req) for req in pending if req.is_pending()],
        'active_shares': [_serialize_share_access(access) for access in active_access if access.is_active],
    }


def _serialize_clinic_share_payload(user):
    requests = (
        DataShareRequest.query.filter_by(requested_by_id=user.id)
        .order_by(DataShareRequest.created_at.desc())
        .limit(25)
        .all()
    )
    clinic_ids = list(_collect_clinic_ids(viewer=user))
    active = []
    if clinic_ids:
        active = (
            DataShareAccess.query
            .filter(DataShareAccess.granted_to_type == DataSharePartyType.clinic)
            .filter(DataShareAccess.granted_to_id.in_(clinic_ids))
            .filter(DataShareAccess.revoked_at.is_(None))
            .filter(or_(DataShareAccess.expires_at.is_(None), DataShareAccess.expires_at > datetime.utcnow()))
            .order_by(DataShareAccess.created_at.desc())
            .limit(25)
            .all()
        )
    return {
        'pending_requests': [_serialize_share_request(req) for req in requests if req.is_pending()],
        'active_shares': [_serialize_share_access(access) for access in active],
    }


def _is_tutor_portal_user(user=None):
    user = user or (current_user if current_user.is_authenticated else None)
    if not user:
        return False
    worker = (getattr(user, 'worker', None) or '').lower()
    return worker not in {'veterinario', 'colaborador', 'admin'}


def get_user_or_404(user_id, *, viewer=None, clinic_scope=None):
    """Load a user enforcing privacy-aware visibility."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    user = User.query.get_or_404(user_id)
    shared_access = _resolve_shared_access_for_user(user, viewer=viewer, clinic_scope=clinic_scope)
    if not shared_access and not _can_view_user(user, viewer=viewer, clinic_scope=clinic_scope):
        abort(404)

    if shared_access:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='user',
            resource_id=user.id,
            actor=viewer,
        )
    return user


def ensure_clinic_access(clinica_id):
    """Abort with 404 if the current user cannot access the given clinic."""
    if not clinica_id:
        return
    if not current_user.is_authenticated:
        abort(404)
    if current_user.is_authenticated and current_user.role == 'admin':
        return
    if current_user_clinic_id() != clinica_id:
        abort(404)


def get_animal_or_404(animal_id, *, viewer=None, clinic_scope=None):
    """Return animal if accessible to current user, otherwise 404."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    animal = Animal.query.get_or_404(animal_id)
    shared_access = _resolve_shared_access_for_animal(animal, viewer=viewer, clinic_scope=clinic_scope)
    if not shared_access:
        ensure_clinic_access(animal.clinica_id)
    else:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='animal',
            resource_id=animal.id,
            actor=viewer,
        )

    tutor_id = getattr(animal, "user_id", None)
    if tutor_id:
        visibility_clause = _user_visibility_clause(viewer=viewer, clinic_scope=clinic_scope)
        tutor_visible = (
            db.session.query(User.id)
            .filter(User.id == tutor_id)
            .filter(visibility_clause)
            .first()
        )
        if not tutor_visible and not shared_access:
            abort(404)

    return animal


def get_consulta_or_404(consulta_id, *, viewer=None, clinic_scope=None):
    """Return consulta if accessible to current user, otherwise 404."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    consulta = Consulta.query.get_or_404(consulta_id)
    shared_access = _resolve_shared_access_for_consulta(consulta, viewer=viewer, clinic_scope=clinic_scope)
    if not shared_access:
        ensure_clinic_access(consulta.clinica_id)
    else:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='consulta',
            resource_id=consulta.id,
            actor=viewer,
        )
    return consulta


def _filter_records_by_clinic(records, clinic_id):
    """Return a list limited to the given clinic id (if provided)."""

    if not records:
        return []

    items = list(records)
    if clinic_id:
        return [item for item in items if getattr(item, 'clinica_id', None) == clinic_id]
    return items


def _clinic_orcamento_blocks(animal, clinic_id):
    return _filter_records_by_clinic(getattr(animal, 'blocos_orcamento', []) or [], clinic_id)


def _clinic_prescricao_blocks(animal, clinic_id):
    return _filter_records_by_clinic(getattr(animal, 'blocos_prescricao', []) or [], clinic_id)


def _render_orcamento_history(animal, clinic_id):
    blocos = _clinic_orcamento_blocks(animal, clinic_id)
    return render_template(
        'partials/historico_orcamentos.html',
        animal=animal,
        blocos_orcamento=blocos,
        clinic_scope_id=clinic_id,
    )


def _render_prescricao_history(animal, clinic_id):
    blocos = _clinic_prescricao_blocks(animal, clinic_id)
    return render_template(
        'partials/historico_prescricoes.html',
        animal=animal,
        blocos_prescricao=blocos,
        clinic_scope_id=clinic_id,
    )


MISSING_VET_PROFILE_MESSAGE = (
    "Para visualizar os convites de clínica, finalize seu cadastro de "
    "veterinário informando o CRMV e demais dados profissionais."
)


def _render_missing_vet_profile(form=None, profile_form=None):
    """Render the clinic invite page guiding the vet to complete the profile."""
    if form is None:
        form = ClinicInviteResponseForm()
    if profile_form is None:
        profile_form = VeterinarianProfileForm()
    return render_template(
        "clinica/clinic_invites.html",
        invites=[],
        form=form,
        missing_vet_profile=True,
        missing_vet_profile_message=MISSING_VET_PROFILE_MESSAGE,
        vet_profile_form=profile_form,
    )


def _build_vet_invites_context(response_form=None, vet_profile_form=None):
    """Return context data for clinic invites within the messages page."""
    show_clinic_invites = getattr(current_user, "worker", None) == "veterinario"

    if not show_clinic_invites:
        return {
            "show_clinic_invites": False,
            "clinic_invites": [],
            "clinic_invite_form": None,
            "vet_profile_form": None,
            "missing_vet_profile": False,
            "missing_vet_profile_message": MISSING_VET_PROFILE_MESSAGE,
        }

    if response_form is None:
        response_form = ClinicInviteResponseForm()

    vet_profile = getattr(current_user, "veterinario", None)
    invites = []
    missing_vet_profile = False

    if vet_profile is None:
        missing_vet_profile = True
        if vet_profile_form is None:
            vet_profile_form = VeterinarianProfileForm()
    else:
        invites = (
            VetClinicInvite.query.options(
                joinedload(VetClinicInvite.clinica).joinedload(Clinica.owner)
            )
            .filter_by(
                veterinario_id=vet_profile.id,
                status="pending",
            )
            .order_by(VetClinicInvite.created_at.desc())
            .all()
        )

    return {
        "show_clinic_invites": True,
        "clinic_invites": invites,
        "clinic_invite_form": response_form,
        "vet_profile_form": vet_profile_form,
        "missing_vet_profile": missing_vet_profile,
        "missing_vet_profile_message": MISSING_VET_PROFILE_MESSAGE,
    }


def _get_inbox_messages():
    """Return received messages with sender information for current user."""
    if not current_user.is_authenticated:
        return []

    mensagens = (
        Message.query.options(
            selectinload(Message.sender),
            selectinload(Message.animal),
        )
        .filter_by(receiver_id=current_user.id)
        .order_by(Message.timestamp.desc().nullslast())
        .all()
    )

    return [mensagem for mensagem in mensagens if mensagem.sender is not None]


def _notify_admin_message(receiver, sender, message_content, conversation_url=None):
    """Send an email notification when an administrator sends a message.

    This keeps tutors and veterinarians informed even when they are
    outside da plataforma, addressing the reported communication gap where
    admin replies were silently stored without any alert.
    """

    if not receiver or not sender:
        return

    sender_role = (getattr(sender, "role", "") or "").lower()
    if sender_role != "admin":
        return

    email = (getattr(receiver, "email", "") or "").strip()
    if not email:
        return

    first_name_source = (getattr(receiver, "name", "") or "").strip()
    if first_name_source:
        first_name = first_name_source.split()[0]
    else:
        first_name = email.split("@")[0]

    if conversation_url is None:
        try:
            relative_url = url_for("conversa_admin")
            base_url = request.url_root.rstrip("/") if has_request_context() else ""
            conversation_url = f"{base_url}{relative_url}" if base_url else relative_url
        except Exception:  # pragma: no cover - defensive fallback
            conversation_url = None

    preview = (message_content or "").strip()
    if len(preview) > 280:
        preview = f"{preview[:277]}..."

    lines = [
        f"Olá {first_name},",
        "",
        "Você recebeu uma nova mensagem do administrador do PetOrlândia.",
    ]
    if preview:
        lines.extend(["", preview])
    if conversation_url:
        lines.extend([
            "",
            "Acesse suas mensagens para responder:",
            conversation_url,
        ])
    lines.extend(["", "Abraços,", "Equipe PetOrlândia"])

    body = "\n".join(lines)

    try:
        mail_msg = MailMessage(
            subject="Nova mensagem do administrador no PetOrlândia",
            recipients=[email],
            body=body,
        )
        mail.send(mail_msg)
    except Exception as exc:  # pragma: no cover - only log the failure
        current_app.logger.warning(
            "Falha ao enviar notificação de mensagem para %s: %s", email, exc
        )

    try:
        db.session.add(
            Notification(
                user_id=receiver.id,
                message=body,
                channel="email",
                kind="admin_message",
            )
        )
    except Exception as exc:  # pragma: no cover - logging only
        current_app.logger.warning(
            "Não foi possível registrar a notificação de mensagem: %s", exc
        )


def _render_messages_page(mensagens=None, **extra_context):
    """Render the messages page with optional overrides for clinic invites."""
    if mensagens is None:
        mensagens = _get_inbox_messages()

    context_overrides = extra_context.copy()
    response_form = context_overrides.pop("clinic_invite_form", None)
    vet_profile_form = context_overrides.pop("vet_profile_form", None)

    clinic_invite_context = _build_vet_invites_context(
        response_form=response_form,
        vet_profile_form=vet_profile_form,
    )
    clinic_invite_context.update(context_overrides)
    clinic_invite_context["mensagens"] = mensagens

    return render_template("mensagens/mensagens.html", **clinic_invite_context)


def _serialize_message_threads(mensagens):
    """Aggregate messages into conversation threads for the authenticated user."""
    threads = {}

    for mensagem in mensagens:
        key = (mensagem.sender_id, mensagem.animal_id or None)
        last_timestamp = mensagem.timestamp or datetime.min

        thread = threads.get(key)
        if thread is None or last_timestamp > thread["last_message_dt"]:
            if mensagem.animal is not None:
                conversation_url = url_for(
                    "conversa", animal_id=mensagem.animal_id, user_id=mensagem.sender_id
                )
                animal_payload = {
                    "id": mensagem.animal_id,
                    "name": mensagem.animal.name,
                }
            else:
                if current_user.role == "admin":
                    conversation_url = url_for("conversa_admin", user_id=mensagem.sender_id)
                else:
                    conversation_url = url_for("conversa_admin", user_id=mensagem.sender_id)
                animal_payload = None

            sender_name = mensagem.sender.name or "Usuário"
            sender_initial = sender_name.strip()[:1].upper() if sender_name.strip() else "?"

            thread = {
                "id": f"{mensagem.sender_id}-{mensagem.animal_id or 'admin'}",
                "sender": {
                    "id": mensagem.sender_id,
                    "name": sender_name,
                    "profile_photo": mensagem.sender.profile_photo,
                    "initials": sender_initial,
                },
                "animal": animal_payload,
                "last_message_dt": last_timestamp,
                "last_message_at": last_timestamp.isoformat(),
                "unread_count": 0,
                "conversation_url": conversation_url,
            }
            threads[key] = thread
        else:
            if last_timestamp > thread["last_message_dt"]:
                thread["last_message_dt"] = last_timestamp
                thread["last_message_at"] = last_timestamp.isoformat()

        if not mensagem.lida:
            threads[key]["unread_count"] += 1

    sorted_threads = sorted(
        threads.values(), key=lambda thread: thread["last_message_dt"], reverse=True
    )

    for thread in sorted_threads:
        thread.pop("last_message_dt", None)

    return sorted_threads


def _ensure_veterinarian_profile(form=None):
    """Return veterinarian profile or render guidance message when missing."""
    if not has_veterinarian_profile(current_user):
        abort(403)

    vet_profile = current_user.veterinario
    if vet_profile is None:
        return None, _render_missing_vet_profile(form=form)

    membership = ensure_veterinarian_membership(vet_profile)
    if membership and not membership.is_active():
        flash('Sua assinatura de veterinário está inativa. Regularize para continuar.', 'warning')
        return None, redirect(url_for('veterinarian_membership'))

    return vet_profile, None


def _get_veterinarian_membership_price() -> Decimal:
    """Return the configured membership price for veterinarians."""

    return VeterinarianSettings.membership_price_amount()


def _resolve_membership_from_payment(payment):
    external = getattr(payment, 'external_reference', '') or ''
    match = re.match(r'vet-membership-(\d+)', external)
    if not match:
        return None
    membership_id = int(match.group(1))
    return VeterinarianMembership.query.get(membership_id)


def _sync_veterinarian_membership_payment(payment):
    membership = _resolve_membership_from_payment(payment)
    if not membership:
        return

    membership.last_payment_id = payment.id
    if payment.status == PaymentStatus.COMPLETED:
        cycle_days = current_app.config.get('VETERINARIAN_MEMBERSHIP_BILLING_DAYS', 30)
        now = datetime.utcnow()
        start_from = membership.paid_until if membership.paid_until and membership.paid_until > now else now
        membership.paid_until = start_from + timedelta(days=cycle_days)
        membership.ensure_trial_dates(current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30))
    db.session.add(membership)


# ----------------------------------------------------------------
# CEP lookup API
# ----------------------------------------------------------------


@app.route('/api/cep/<cep>')
def api_cep_lookup(cep: str):
    """Lookup CEP information using a list of public providers.

    The frontend calls this endpoint instead of contacting third-party
    services directly, which avoids CORS issues in the browser and lets us
    provide consistent error handling/fallbacks.
    """

    sanitized = re.sub(r'\D', '', cep or '')
    if len(sanitized) != 8:
        return jsonify(success=False, error='CEP inválido'), 400

    providers = (
        ('https://viacep.com.br/ws/{cep}/json/', 'viacep'),
        ('https://brasilapi.com.br/api/cep/v1/{cep}', 'brasilapi'),
    )

    def _normalize(payload: dict, provider: str):
        if not isinstance(payload, dict):
            return None

        if provider == 'viacep':
            if payload.get('erro'):
                return None
            return {
                'cep': payload.get('cep'),
                'logradouro': payload.get('logradouro'),
                'complemento': payload.get('complemento'),
                'bairro': payload.get('bairro'),
                'localidade': payload.get('localidade'),
                'uf': payload.get('uf'),
            }

        if provider == 'brasilapi':
            if payload.get('errors') or payload.get('message'):
                return None
            return {
                'cep': payload.get('cep'),
                'logradouro': payload.get('street') or payload.get('logradouro'),
                'complemento': payload.get('complement'),
                'bairro': payload.get('neighborhood') or payload.get('bairro'),
                'localidade': payload.get('city') or payload.get('localidade'),
                'uf': payload.get('state') or payload.get('uf'),
            }

        return None

    for template, provider in providers:
        url = template.format(cep=sanitized)
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        normalized = _normalize(payload, provider)
        if normalized:
            return jsonify(success=True, data=normalized)

    return jsonify(success=False, error='CEP não encontrado'), 404


@app.route('/veterinario/assinatura')
@login_required
def veterinarian_membership():
    role = getattr(current_user, 'role', None)
    role_lower = role.lower() if isinstance(role, str) else ''
    is_admin = bool(current_user.is_authenticated and role_lower == 'admin')
    has_profile = has_veterinarian_profile(current_user)

    if not (is_admin or has_profile):
        abort(403)

    membership = None
    if has_profile:
        membership = ensure_veterinarian_membership(current_user.veterinario)

    status = request.args.get('status')

    checkout_form = VeterinarianMembershipCheckoutForm()
    price = _get_veterinarian_membership_price()
    trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)

    return render_template(
        'veterinarios/membership.html',
        membership=membership,
        checkout_form=checkout_form,
        price=price,
        trial_days=trial_days,
        status=status,
    )


@app.route('/veterinario/assinatura/checkout', methods=['POST'])
@login_required
def veterinarian_membership_checkout():
    role = getattr(current_user, 'role', None)
    role_lower = role.lower() if isinstance(role, str) else ''
    is_admin = bool(current_user.is_authenticated and role_lower == 'admin')
    has_profile = has_veterinarian_profile(current_user)

    if not (is_admin or has_profile):
        abort(403)

    form = VeterinarianMembershipCheckoutForm()
    if not form.validate_on_submit():
        flash('Não foi possível iniciar a assinatura. Tente novamente.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    membership = None
    if has_profile:
        membership = ensure_veterinarian_membership(current_user.veterinario)
    trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
    if membership:
        membership.ensure_trial_dates(trial_days)

    price = _get_veterinarian_membership_price()

    if membership and membership.id is None:
        db.session.flush()

    reason_suffix = current_user.name.strip() if (current_user.name or '').strip() else current_user.email
    reason = f'Assinatura Profissional PetOrlândia - {reason_suffix}'

    preapproval_data = {
        'reason': reason,
        'back_url': url_for('veterinarian_membership', _external=True),
        'payer_email': current_user.email,
        'auto_recurring': {
            'frequency': 1,
            'frequency_type': 'months',
            'transaction_amount': float(price),
            'currency_id': 'BRL',
        },
    }

    if membership and membership.id:
        preapproval_data['external_reference'] = f'vet-membership-{membership.id}'

    try:
        resp = mp_sdk().preapproval().create(preapproval_data)
    except Exception:  # noqa: BLE001
        current_app.logger.exception('Erro de conexão com Mercado Pago para assinatura de veterinário')
        db.session.rollback()
        flash('Não foi possível iniciar o pagamento. Tente novamente em instantes.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    if resp.get('status') not in {200, 201}:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        db.session.rollback()
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    init_point = (
        resp.get('response', {}).get('init_point')
        or resp.get('response', {}).get('sandbox_init_point')
    )

    if not init_point:
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    db.session.commit()

    return redirect(init_point)


@app.route('/veterinario/assinatura/<int:membership_id>/cancelar_avaliacao', methods=['POST'])
@login_required
def veterinarian_cancel_trial(membership_id):
    from models import VeterinarianMembership

    membership = VeterinarianMembership.query.get_or_404(membership_id)
    form = VeterinarianMembershipCancelTrialForm()

    if not form.validate_on_submit():
        flash('Não foi possível cancelar a avaliação gratuita. Tente novamente.', 'danger')
        return redirect(url_for('conversa_admin'))

    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'
    owns_membership = (
        has_veterinarian_profile(current_user)
        and membership.veterinario_id == current_user.veterinario.id
    )

    if not (is_admin or owns_membership):
        abort(403)

    if not membership.is_trial_active():
        flash('O período de avaliação gratuita já havia sido encerrado.', 'info')
    else:
        membership.trial_ends_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.add(membership)
        db.session.commit()
        flash('Período de avaliação gratuita cancelado com sucesso.', 'success')

    if is_admin and membership.veterinario and membership.veterinario.user:
        return redirect(url_for('conversa_admin', user_id=membership.veterinario.user.id))

    return redirect(url_for('conversa_admin'))


@app.route('/veterinario/assinatura/<int:membership_id>/nova_avaliacao', methods=['POST'])
@login_required
def veterinarian_request_new_trial(membership_id):
    from models import VeterinarianMembership

    membership = VeterinarianMembership.query.get_or_404(membership_id)
    form = VeterinarianMembershipRequestNewTrialForm()

    if not form.validate_on_submit():
        flash('Não foi possível iniciar uma nova avaliação gratuita. Tente novamente.', 'danger')
        return redirect(url_for('conversa_admin'))

    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'
    owns_membership = (
        has_veterinarian_profile(current_user)
        and membership.veterinario_id == current_user.veterinario.id
    )

    if not (is_admin or owns_membership):
        abort(403)

    if not is_admin:
        admin_user = User.query.filter_by(role='admin').first()
        if not admin_user:
            flash('Não foi possível localizar um administrador. Tente novamente mais tarde.', 'danger')
        else:
            content = (
                'Olá! Gostaria de solicitar a reativação da minha assinatura de veterinário '
                f'(assinatura #{membership.id}).'
            )
            message = Message(
                sender_id=current_user.id,
                receiver_id=admin_user.id,
                content=content,
            )
            db.session.add(message)
            db.session.commit()
            flash('Seu pedido foi enviado ao administrador. Aguarde a confirmação.', 'success')
        return redirect(url_for('conversa_admin'))

    if membership.is_trial_active():
        flash('A avaliação gratuita atual ainda está ativa.', 'info')
    elif membership.has_valid_payment():
        flash('Não é possível iniciar uma nova avaliação gratuita com uma assinatura ativa.', 'warning')
    else:
        trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
        membership.restart_trial(trial_days)
        db.session.add(membership)
        db.session.commit()
        flash('Novo período de avaliação gratuita iniciado com sucesso.', 'success')

    if is_admin and membership.veterinario and membership.veterinario.user:
        return redirect(url_for('conversa_admin', user_id=membership.veterinario.user.id))

    return redirect(url_for('conversa_admin'))

# ----------------------------------------------------------------
# 7)  Login & serializer
# ----------------------------------------------------------------
from models import User   # noqa: E402  (import depois de alias)

@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

login.login_view = "login_view"
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

# ----------------------------------------------------------------
# 8)  Admin & blueprints
# ----------------------------------------------------------------
with app.app_context():
    from admin import init_admin, _is_admin  # import interno evita loop
    init_admin(app)
    # outras blueprints ->  from views import bp as views_bp ; app.register_blueprint(views_bp)

# (rotas podem ser definidas em módulos separados e registrados via blueprint)
# ────────────────────────────── fim ─────────────────────────────
@app.context_processor
def inject_unread_count():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
            unread = (
                Message.query
                .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
                .count()
            )
        else:
            unread = (
                Message.query
                .filter_by(receiver_id=current_user.id, lida=False)
                .count()
            )
    else:
        unread = 0
    return dict(unread_messages=unread)


@app.context_processor
def inject_pending_exam_count():
    if current_user.is_authenticated and is_veterinarian(current_user):
        from models import ExamAppointment

        pending = ExamAppointment.query.filter_by(
            specialist_id=current_user.veterinario.id, status='pending'
        ).count()
        seen = session.get('exam_pending_seen_count', 0)
        pending = max(pending - seen, 0)
    else:
        pending = 0
    return dict(pending_exam_count=pending)


@app.context_processor
def inject_pending_appointment_count():
    """Expose count of upcoming appointments requiring vet action."""

    if current_user.is_authenticated and is_veterinarian(current_user):
        from models import Appointment

        now = datetime.utcnow()
        pending = Appointment.query.filter(
            Appointment.veterinario_id == current_user.veterinario.id,
            Appointment.status == "scheduled",
            Appointment.scheduled_at >= now + timedelta(hours=2),
        ).count()
        seen = session.get('appointment_pending_seen_count', 0)
        pending = max(pending - seen, 0)
    else:
        pending = 0
    return dict(pending_appointment_count=pending)


def _clinic_pending_appointments_query(veterinario):
    """Return query for scheduled clinic appointments excluding the given vet."""
    if not veterinario or not getattr(veterinario, "clinica_id", None):
        return None

    from models import Appointment

    return Appointment.query.filter(
        Appointment.clinica_id == veterinario.clinica_id,
        Appointment.status == "scheduled",
        Appointment.veterinario_id != veterinario.id,
    )


@app.context_processor
def inject_clinic_pending_appointment_count():
    """Expose count of scheduled appointments in the clinic excluding the current vet."""

    if current_user.is_authenticated and is_veterinarian(current_user):
        pending_query = _clinic_pending_appointments_query(
            getattr(current_user, "veterinario", None)
        )
        pending = pending_query.count() if pending_query is not None else 0
        seen = session.get("clinic_pending_seen_count", 0)
        pending = max(pending - seen, 0)
    else:
        pending = 0
    return dict(clinic_pending_appointment_count=pending)


@app.context_processor
def inject_veterinarian_membership_context():
    if not current_user.is_authenticated:
        return dict(
            is_active_veterinarian=False,
            has_veterinarian_profile_flag=False,
            current_veterinarian_membership=None,
        )

    has_profile = has_veterinarian_profile(current_user)
    membership = None
    if has_profile:
        membership = ensure_veterinarian_membership(getattr(current_user, 'veterinario', None))

    return dict(
        is_active_veterinarian=has_profile and is_veterinarian(current_user),
        has_veterinarian_profile_flag=has_profile,
        current_veterinarian_membership=membership,
    )


@app.context_processor
def inject_clinic_invite_count():
    if current_user.is_authenticated and has_veterinarian_profile(current_user):
        from models import VetClinicInvite

        pending = VetClinicInvite.query.filter_by(
            veterinario_id=current_user.veterinario.id, status='pending'
        ).count()
    else:
        pending = 0
    return dict(pending_clinic_invites=pending)


s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

@app.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = s.dumps(user.email, salt='password-reset-salt')
            base_url = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:5000')
            link = f"{base_url}{url_for('reset_password', token=token)}"

            msg = MailMessage(
                subject='Redefinir sua senha - PetOrlândia',
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[user.email],
                body=f'Clique no link para redefinir sua senha: {link}',
                html=f""" 
                    <!DOCTYPE html>
                    <html lang="pt-BR">
                    <head><meta charset="UTF-8"><title>Redefinição de Senha</title></head>
                    <body style="font-family: Arial; padding: 20px;">
                        <h2>🐾 PetOrlândia</h2>
                        <p>Recebemos uma solicitação para redefinir sua senha.</p>
                        <p><a href="{link}" style="background:#0d6efd;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;">Redefinir Senha</a></p>
                        <p>Se você não solicitou, ignore este e-mail.</p>
                        <hr><small>PetOrlândia • Cuidando com amor dos seus melhores amigos</small>
                    </body>
                    </html>
                """
            )
            mail.send(msg)
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('login_view')})
            flash('Um e-mail foi enviado com instruções para redefinir sua senha.', 'info')
            return redirect(url_for('login_view'))
        if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
            return jsonify({'success': False, 'errors': {'email': ['E-mail não encontrado.']}}), 400
        flash('E-mail não encontrado.', 'danger')
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400
    return render_template('auth/reset_password_request.html', form=form)



@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)  # 1 hour
    except:
        flash('O link de redefinição expirou ou é inválido.', 'danger')
        return redirect(url_for('reset_password_request'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(form.password.data)  # Your User model must have set_password method
            db.session.commit()
            flash('Sua senha foi redefinida. Você já pode entrar!', 'success')
            return redirect(url_for('login_view'))
    return render_template('auth/reset_password.html', form=form)



#admin configuration

@app.route('/painel')
@login_required
def painel_dashboard():
    if not _is_admin():
        abort(403)
    cards = [
        {"icon": "👤", "title": "Usuários", "description": f"Total: {User.query.count()}"},
        {"icon": "🐶", "title": "Animais", "description": f"Total: {Animal.query.count()}"},
        {"icon": "🏥", "title": "Clínicas", "description": f"Total: {Clinica.query.count()}"},
        {"icon": "💉", "title": "Vacinas", "description": f"Hoje: {VacinaModelo.query.count()}"},
        {"icon": "📋", "title": "Consultas", "description": f"Pendentes: {Consulta.query.filter_by(status='pendente').count()}"},
        {"icon": "💊", "title": "Prescrições", "description": f"Semana: {Prescricao.query.count()}"},
    ]
    return render_template('admin/admin_dashboard.html', cards=cards)



# Rota principal


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/service-worker.js')
def service_worker():
    return send_from_directory(app.static_folder, 'service-worker.js')


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()

    if form.validate_on_submit():
        # Verifica se o e-mail já está em uso
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': False, 'errors': {'email': ['Email já está em uso.']}}), 400
            flash('Email já está em uso.', 'danger')
            return render_template('auth/register.html', form=form, endereco=None)

        # Cria o endereço
        endereco = Endereco(
            cep=request.form.get('cep'),
            rua=request.form.get('rua'),
            numero=request.form.get('numero'),
            complemento=request.form.get('complemento'),
            bairro=request.form.get('bairro'),
            cidade=request.form.get('cidade'),
            estado=request.form.get('estado')
        )

        # Upload da foto de perfil para o S3
        photo_url = None
        if form.profile_photo.data:
            file = form.profile_photo.data
            filename = secure_filename(file.filename)
            photo_url = upload_to_s3(file, filename, folder="users")


        # Cria o usuário com a URL da imagem no S3
        user = User(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            profile_photo=photo_url,
            endereco=endereco
        )
        user.set_password(form.password.data)

        # Salva no banco
        db.session.add(endereco)
        db.session.add(user)
        db.session.commit()

        if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
            return jsonify({'success': True, 'redirect': url_for('index')})
        flash('Usuário registrado com sucesso!', 'success')
        return redirect(url_for('index'))

    if request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400

    return render_template('auth/register.html', form=form, endereco=None)




def _normalizar_unidade_idade(unidade):
    if not unidade:
        return 'anos'
    texto = unicodedata.normalize('NFKD', str(unidade))
    texto = texto.encode('ASCII', 'ignore').decode('ASCII').strip().lower()
    if texto.startswith('mes'):
        return 'meses'
    if texto.startswith('ano'):
        return 'anos'
    return 'anos'


def _formatar_idade(numero, unidade):
    if numero is None:
        return ''
    unidade_norm = _normalizar_unidade_idade(unidade)
    if unidade_norm == 'meses':
        sufixo = 'mês' if numero == 1 else 'meses'
    else:
        sufixo = 'ano' if numero == 1 else 'anos'
    return f"{numero} {sufixo}"


def _extrair_idade(unidade_texto):
    if not unidade_texto:
        return None, None
    partes = str(unidade_texto).split()
    numero = None
    try:
        numero = int(partes[0])
    except (ValueError, IndexError):
        numero = None
    unidade = None
    if len(partes) > 1:
        unidade = _normalizar_unidade_idade(partes[1])
    return numero, unidade


def _preencher_idade_form(form, animal=None):
    if not hasattr(form, 'age') or not hasattr(form, 'age_unit'):
        return
    if form.is_submitted():
        return

    numero = None
    unidade = None

    if animal and animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            numero = delta.years
            unidade = 'anos'
        else:
            numero = delta.months
            unidade = 'meses'
    elif animal and animal.age:
        numero, unidade = _extrair_idade(animal.age)
    elif form.age.data:
        numero, unidade = _extrair_idade(form.age.data)

    if numero is not None:
        form.age.data = str(numero)
    if unidade:
        form.age_unit.data = unidade
    elif not form.age_unit.data:
        form.age_unit.data = 'anos'


@app.route('/add-animal', methods=['GET', 'POST'])
@login_required
def add_animal():
    form = AnimalForm()
    _preencher_idade_form(form)

    # Listas para o template
    try:
        species_list = list_species()
    except Exception:
        species_list = []
    try:
        breed_list = list_breeds()
    except Exception:
        breed_list = []

    # Debug da requisição
    print("📥 Método da requisição:", request.method)
    print("📋 Dados recebidos:", request.form)

    if form.validate_on_submit():
        print("✅ Formulário validado com sucesso.")

        image_url = None
        if form.image.data:
            file = form.image.data
            original_filename = secure_filename(file.filename)
            filename = f"{uuid.uuid4().hex}_{original_filename}"
            print("🖼️ Upload de imagem iniciado:", filename)
            image_url = upload_to_s3(file, filename, folder="animals")
            print("✅ Upload concluído. URL:", image_url)

        # IDs das listas
        species_id = request.form.get("species_id", type=int)
        breed_id = request.form.get("breed_id", type=int)
        print("🔍 Species ID:", species_id)
        print("🔍 Breed ID:", breed_id)

        dob = form.date_of_birth.data
        idade_valor = (form.age.data or '').strip()
        unidade_valor = _normalizar_unidade_idade(form.age_unit.data if hasattr(form, 'age_unit') else 'anos')
        idade_numero = None
        try:
            idade_numero = int(idade_valor)
        except (ValueError, TypeError):
            idade_numero = None

        if not dob and idade_numero is not None:
            if unidade_valor == 'meses':
                dob = date.today() - relativedelta(months=idade_numero)
            else:
                dob = date.today() - relativedelta(years=idade_numero)

        idade_formatada = None if not idade_valor else idade_valor
        if idade_numero is not None:
            idade_formatada = _formatar_idade(idade_numero, unidade_valor)

        # Criação do animal
        animal = Animal(
            name=form.name.data,
            species_id=species_id,
            breed_id=breed_id,
            age=idade_formatada,
            date_of_birth=dob,
            sex=form.sex.data,
            description=form.description.data,
            image=image_url,
            photo_rotation=form.photo_rotation.data,
            photo_zoom=form.photo_zoom.data,
            photo_offset_x=form.photo_offset_x.data,
            photo_offset_y=form.photo_offset_y.data,
            modo=form.modo.data,
            price=form.price.data if form.modo.data == 'venda' else None,
            status='disponível',
            owner=current_user,
            is_alive=True
        )

        db.session.add(animal)
        try:
            db.session.commit()
            print("✅ Animal salvo com ID:", animal.id)
            flash('Animal cadastrado com sucesso!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            print("❌ Erro ao salvar no banco:", str(e))
            flash('Erro ao salvar o animal.', 'danger')

    else:
        print("⚠️ Formulário inválido.")
        print("🧾 Erros do formulário:", form.errors)

    return render_template(
        'animais/add_animal.html',
        form=form,
        species_list=species_list,
        breed_list=breed_list
    )


@app.route('/login', methods=['GET', 'POST'])
def login_view():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            if form.remember.data:
                session.permanent = True
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('index')})
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        else:
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': False, 'errors': {'email': ['Email ou senha inválidos.']}}), 400
            flash('Email ou senha inválidos.', 'danger')
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400
    return render_template('auth/login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu com sucesso!', 'success')
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Garante que current_user.endereco exista para pré-preenchimento
    form = EditProfileForm(obj=current_user)
    delete_form = DeleteAccountForm()

    if form.validate_on_submit():
        if not current_user.endereco:
            current_user.endereco = Endereco()


    form = EditProfileForm(obj=current_user)

    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.email = form.email.data
        current_user.phone = form.phone.data
        current_user.is_private = form.is_private.data
        current_user.photo_rotation = form.photo_rotation.data
        current_user.photo_zoom = form.photo_zoom.data
        current_user.photo_offset_x = form.photo_offset_x.data
        current_user.photo_offset_y = form.photo_offset_y.data

        # Atualiza ou cria endereço
        endereco = current_user.endereco
        endereco.cep = request.form.get("cep")
        endereco.rua = request.form.get("rua")
        endereco.numero = request.form.get("numero")
        endereco.complemento = request.form.get("complemento")
        endereco.bairro = request.form.get("bairro")
        endereco.cidade = request.form.get("cidade")
        endereco.estado = request.form.get("estado")

        db.session.add(endereco)

        # Upload de imagem para S3 (se houver nova)
        if (
            form.profile_photo.data and
            hasattr(form.profile_photo.data, 'filename') and
            form.profile_photo.data.filename != ''
        ):
            file = form.profile_photo.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            current_user.profile_photo = upload_to_s3(file, filename, folder="profile_photos")

        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    # Transações recentes
    transactions = Transaction.query.filter(
        (Transaction.from_user_id == current_user.id) | (Transaction.to_user_id == current_user.id)
    ).order_by(Transaction.date.desc()).limit(10).all()

    return render_template(
        'auth/profile.html',
        user=current_user,
        form=form,
        delete_form=delete_form,
        transactions=transactions
    )


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': False, 'errors': {'current_password': ['Senha atual incorreta.']}}), 400
            flash('Senha atual incorreta.', 'danger')
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            if request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
                return jsonify({'success': True, 'redirect': url_for('profile')})
            flash('Senha atualizada com sucesso!', 'success')
            return redirect(url_for('profile'))
    elif request.method == 'POST' and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']:
        return jsonify({'success': False, 'errors': form.errors}), 400
    return render_template('auth/change_password.html', form=form)


@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if form.validate_on_submit():
        # Capture the actual user object before logging out because
        # `current_user` becomes `AnonymousUserMixin` after logout.
        user = current_user._get_current_object()

        # Remove mensagens associadas ao usuário antes de excluí-lo
        for msg in list(user.sent_messages) + list(user.received_messages):
            db.session.delete(msg)

        # Remove pagamentos vinculados ao usuário antes de excluí-lo
        for payment in list(user.payments):
            # Desassocia assinaturas que usam este pagamento
            for sub in list(payment.subscriptions):
                sub.payment = None
            db.session.delete(payment)

        logout_user()
        db.session.delete(user)
        db.session.commit()
        flash('Sua conta foi excluída.', 'success')
        return redirect(url_for('index'))
    flash('Operação inválida.', 'danger')
    return redirect(url_for('profile'))




@app.route('/animals')
def list_animals():
    page = request.args.get('page', 1, type=int)
    per_page = 9
    modo = request.args.get('modo')
    species_id = request.args.get('species_id', type=int)
    breed_id = request.args.get('breed_id', type=int)
    sex = request.args.get('sex')
    age = request.args.get('age')
    show_all = _is_admin() and request.args.get('show_all') == '1'

    # Base query: ignora animais removidos
    query = Animal.query.filter(Animal.removido_em == None)

    # Filtro por modo
    if modo and modo.lower() != 'todos':
        query = query.filter_by(modo=modo)
    else:
        # Evita mostrar adotados para usuários não autorizados, exceto quando o admin opta por ver todos
        vet_authorized = current_user.is_authenticated and is_veterinarian(current_user)
        collaborator = (
            current_user.is_authenticated
            and getattr(current_user, 'worker', None) == 'colaborador'
        )
        if not show_all and not (vet_authorized or collaborator):
            query = query.filter(Animal.modo != 'adotado')

    if species_id:
        query = query.filter_by(species_id=species_id)
    if breed_id:
        query = query.filter_by(breed_id=breed_id)
    if sex:
        query = query.filter_by(sex=sex)
    if age:
        query = query.filter(Animal.age.ilike(f"{age}%"))

    # Veterinários só podem ver animais perdidos, à venda ou para adoção,
    # ou então animais cadastrados pela própria clínica
    if current_user.is_authenticated and is_veterinarian(current_user) and not show_all:
        allowed = ['perdido', 'venda', 'doação']
        clinic_id = getattr(current_user.veterinario, 'clinica_id', None) or current_user.clinica_id
        if clinic_id:
            query = query.filter(
                or_(
                    Animal.modo.in_(allowed),
                    Animal.clinica_id == clinic_id
                )
            )
        else:
            query = query.filter(Animal.modo.in_(allowed))

    # Ordenação e paginação
    query = query.options(
        selectinload(Animal.species),
        selectinload(Animal.breed),
        selectinload(Animal.owner),
    )
    query = query.order_by(Animal.date_added.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    animals = pagination.items

    try:
        species_list = list_species()
    except Exception:
        species_list = []
    try:
        breed_list = list_breeds()
    except Exception:
        breed_list = []

    context = dict(
        animals=animals,
        page=page,
        total_pages=pagination.pages,
        modo=modo,
        species_list=species_list,
        breed_list=breed_list,
        species_id=species_id,
        breed_id=breed_id,
        sex=sex,
        age=age,
        is_admin=_is_admin(),
        show_all=show_all
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_template('animais/_animals_grid.html', **context)
        return jsonify(
            {
                'html': html,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_pages': pagination.pages,
                    'total_items': pagination.total,
                    'has_next': pagination.has_next,
                    'has_prev': pagination.has_prev,
                    'next_page': pagination.next_num if pagination.has_next else None,
                    'prev_page': pagination.prev_num if pagination.has_prev else None,
                },
            }
        )

    return render_template('animais/animals.html', **context)




@app.route('/animal/<int:animal_id>/adotar', methods=['POST'])
@login_required
def adotar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.status != 'disponível':
        flash('Este animal já foi adotado ou vendido.', 'danger')
        return redirect(url_for('list_animals'))

    animal.status = 'adotado'  # ou 'vendido', se for o caso
    animal.user_id = current_user.id  # <- transfere a posse do animal
    db.session.commit()
    flash(f'Você adotou {animal.name} com sucesso!', 'success')
    return redirect(url_for('list_animals'))


@app.route('/animal/<int:animal_id>/editar', methods=['GET', 'POST'])
@app.route('/editar_animal/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def editar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.user_id != current_user.id:
        flash('Você não tem permissão para editar este animal.', 'danger')
        return redirect(url_for('profile'))

    form = AnimalForm(obj=animal)
    _preencher_idade_form(form, animal)

    species_list = list_species()
    breed_list = list_breeds()




    if form.validate_on_submit():
        animal.name = form.name.data
        animal.sex = form.sex.data
        animal.description = form.description.data
        animal.modo = form.modo.data
        animal.price = form.price.data if form.modo.data == 'venda' else None

        # Data de nascimento calculada a partir da idade se necessário
        dob = form.date_of_birth.data
        idade_valor = (form.age.data or '').strip()
        unidade_valor = _normalizar_unidade_idade(form.age_unit.data if hasattr(form, 'age_unit') else 'anos')
        idade_numero = None
        try:
            idade_numero = int(idade_valor)
        except (ValueError, TypeError):
            idade_numero = None

        if not dob and idade_numero is not None:
            if unidade_valor == 'meses':
                dob = date.today() - relativedelta(months=idade_numero)
            else:
                dob = date.today() - relativedelta(years=idade_numero)
        animal.age = _formatar_idade(idade_numero, unidade_valor) if idade_numero is not None else (idade_valor or None)
        animal.date_of_birth = dob

        # Relacionamentos
        species_id = request.form.get('species_id')
        breed_id = request.form.get('breed_id')
        if species_id:
            animal.species_id = int(species_id)
        if breed_id:
            animal.breed_id = int(breed_id)

        # Upload da nova imagem, se fornecida
        if form.image.data and getattr(form.image.data, 'filename', ''):
            file = form.image.data
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            image_url = upload_to_s3(file, filename, folder="animals")
            if image_url:
                animal.image = image_url

        db.session.commit()
        flash('Animal atualizado com sucesso!', 'success')
        return redirect(url_for('profile'))

    return render_template('animais/editar_animal.html',
                           form=form,
                           animal=animal,
                           species_list=species_list,
                           breed_list=breed_list)


@app.route('/mensagem/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def enviar_mensagem(animal_id):
    animal = get_animal_or_404(animal_id)
    form = MessageForm()
    promotion_form = None
    target_membership = None

    if animal.user_id == current_user.id:
        flash("Você não pode enviar mensagem para si mesmo.", "warning")
        return redirect(url_for('list_animals'))

    if form.validate_on_submit():
        msg = Message(
            sender_id=current_user.id,
            receiver_id=animal.user_id,
            animal_id=animal.id,
            content=form.content.data
        )
        db.session.add(msg)
        db.session.commit()
        flash('Mensagem enviada com sucesso!', 'success')
        return redirect(url_for('list_animals'))

    return render_template('mensagens/enviar_mensagem.html', form=form, animal=animal)


@app.route('/mensagem/<int:message_id>/aceitar', methods=['POST'])
@login_required
def aceitar_interesse(message_id):
    mensagem = Message.query.get_or_404(message_id)

    if mensagem.animal.owner.id != current_user.id:
        flash("Você não tem permissão para aceitar esse interesse.", "danger")
        return redirect(url_for('conversa', animal_id=mensagem.animal.id, user_id=mensagem.sender_id))

    animal = mensagem.animal
    animal.status = 'adotado'
    animal.user_id = mensagem.sender_id
    db.session.commit()

    flash(f"Você aceitou a adoção de {animal.name} por {mensagem.sender.name}.", "success")
    return redirect(url_for('conversa', animal_id=animal.id, user_id=mensagem.sender_id))


@app.route('/mensagens')
@login_required
def mensagens():
    return _render_messages_page()


@app.route('/api/messages/threads')
@login_required
def api_message_threads():
    """Return aggregated conversation threads for the authenticated user."""
    mensagens = _get_inbox_messages()
    threads = _serialize_message_threads(mensagens)
    return jsonify({"threads": threads})


@app.route('/chat/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def chat_messages(animal_id):
    """API simples para listar e criar mensagens relacionadas a um animal."""
    get_animal_or_404(animal_id)
    if request.method == 'GET':
        mensagens = (
            Message.query
            .filter_by(animal_id=animal_id)
            .order_by(Message.timestamp)
            .all()
        )
        return jsonify([
            {
                'id': m.id,
                'sender_id': m.sender_id,
                'receiver_id': m.receiver_id,
                'animal_id': m.animal_id,
                'clinica_id': m.clinica_id,
                'content': m.content,
                'timestamp': m.timestamp.isoformat(),
            }
            for m in mensagens
        ])

    data = request.get_json() or {}
    nova_msg = Message(
        sender_id=data.get('sender_id', current_user.id),
        receiver_id=data['receiver_id'],
        animal_id=animal_id,
        clinica_id=data.get('clinica_id'),
        content=data['content'],
    )
    db.session.add(nova_msg)
    db.session.commit()
    return (
        jsonify(
            {
                'id': nova_msg.id,
                'sender_id': nova_msg.sender_id,
                'receiver_id': nova_msg.receiver_id,
                'animal_id': nova_msg.animal_id,
                'clinica_id': nova_msg.clinica_id,
                'content': nova_msg.content,
                'timestamp': nova_msg.timestamp.isoformat(),
            }
        ),
        201,
    )


@app.route('/chat/<int:animal_id>/view')
@login_required
def chat_view(animal_id):
    animal = get_animal_or_404(animal_id)
    return render_template('chat/conversa.html', animal=animal)


@app.route('/conversa/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def conversa(animal_id, user_id):
    animal = get_animal_or_404(animal_id)
    outro_usuario = get_user_or_404(user_id)
    interesse_existente = Interest.query.filter_by(
        user_id=outro_usuario.id, animal_id=animal.id).first()

    form = MessageForm()

    # Busca todas as mensagens entre current_user e outro_usuario sobre o animal
    mensagens = Message.query.filter(
        Message.animal_id == animal.id,
        ((Message.sender_id == current_user.id) & (Message.receiver_id == outro_usuario.id)) |
        ((Message.sender_id == outro_usuario.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()

    # Enviando nova mensagem
    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=outro_usuario.id,
            animal_id=animal.id,
            content=form.content.data,
            lida=False

        )
        db.session.add(nova_msg)
        db.session.commit()
        return redirect(url_for('conversa', animal_id=animal.id, user_id=outro_usuario.id))

    updated = False
    for m in mensagens:
        if m.receiver_id == current_user.id and not m.lida:
            m.lida = True
            updated = True
    if updated:
        db.session.commit()

    return render_template(
        'mensagens/conversa.html',
        mensagens=mensagens,
        form=form,
        animal=animal,
        outro_usuario=outro_usuario,
        interesse_existente=interesse_existente
    )


@app.route('/api/conversa/<int:animal_id>/<int:user_id>', methods=['POST'])
@login_required
def api_conversa_message(animal_id, user_id):
    """Recebe uma nova mensagem da conversa e retorna o HTML renderizado."""
    form = MessageForm()
    get_animal_or_404(animal_id)
    outro_usuario = get_user_or_404(user_id)
    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=outro_usuario.id,
            animal_id=animal_id,
            content=form.content.data,
            lida=False
        )
        db.session.add(nova_msg)
        db.session.commit()
        return render_template('components/message.html', msg=nova_msg)
    return '', 400


@app.route('/conversa_admin', methods=['GET', 'POST'])
@app.route('/conversa_admin/<int:user_id>', methods=['GET', 'POST'])
@login_required
def conversa_admin(user_id=None):
    """Permite conversar diretamente com o administrador.

    - Usuários comuns acessam ``/conversa_admin`` para falar com o admin.
    - O administrador acessa ``/conversa_admin/<user_id>`` para responder
      mensagens de um usuário específico.
    """

    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        flash('Administrador não encontrado.', 'danger')
        return redirect(url_for('mensagens'))

    form = MessageForm()
    promotion_form = None
    target_membership = None
    cancel_trial_form = VeterinarianMembershipCancelTrialForm()
    request_new_trial_form = VeterinarianMembershipRequestNewTrialForm()
    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'

    if is_admin:
        if user_id is None:
            flash('Selecione um usuário para conversar.', 'warning')
            return redirect(url_for('mensagens_admin'))
        interlocutor = get_user_or_404(user_id)
        admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
        participant_id = interlocutor.id
        promotion_form = VeterinarianPromotionForm()
        if has_veterinarian_profile(interlocutor):
            target_membership = ensure_veterinarian_membership(interlocutor.veterinario)
            if target_membership and not hasattr(target_membership, 'is_trial_active'):
                target_membership = None
            elif target_membership and getattr(target_membership, 'id', None) is None:
                db.session.flush()
    else:
        interlocutor = admin_user
        admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
        participant_id = current_user.id
        if has_veterinarian_profile(current_user):
            target_membership = getattr(current_user.veterinario, 'membership', None)
            if target_membership:
                trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
                target_membership.ensure_trial_dates(trial_days)
                if not hasattr(target_membership, 'is_trial_active'):
                    target_membership = None
                elif getattr(target_membership, 'id', None) is None:
                    db.session.flush()

    mensagens = (
        Message.query
        .filter(
            ((Message.sender_id.in_(admin_ids)) & (Message.receiver_id == participant_id)) |
            ((Message.sender_id == participant_id) & (Message.receiver_id.in_(admin_ids)))
        )
        .order_by(Message.timestamp)
        .all()
    )

    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=interlocutor.id,
            content=form.content.data,
            lida=False
        )
        db.session.add(nova_msg)
        _notify_admin_message(
            receiver=interlocutor,
            sender=current_user,
            message_content=form.content.data,
        )
        db.session.commit()
        if is_admin:
            return redirect(url_for('conversa_admin', user_id=interlocutor.id))
        return redirect(url_for('conversa_admin'))

    for m in mensagens:
        if is_admin:
            if m.receiver_id in admin_ids and not m.lida:
                m.lida = True
        else:
            if m.receiver_id == current_user.id and not m.lida:
                m.lida = True
    db.session.commit()

    can_cancel_trial = bool(
        target_membership
        and hasattr(target_membership, 'is_trial_active')
        and hasattr(target_membership, 'has_valid_payment')
        and getattr(target_membership, 'id', None)
        and target_membership.is_trial_active()
        and not target_membership.has_valid_payment()
    )

    can_request_new_trial = bool(
        target_membership
        and hasattr(target_membership, 'is_trial_active')
        and hasattr(target_membership, 'has_valid_payment')
        and getattr(target_membership, 'id', None)
        and not target_membership.is_trial_active()
        and not target_membership.has_valid_payment()
    )

    return render_template(
        'mensagens/conversa_admin.html',
        mensagens=mensagens,
        form=form,
        admin=interlocutor,
        promotion_form=promotion_form,
        target_membership=target_membership,
        is_admin=is_admin,
        cancel_trial_form=cancel_trial_form,
        can_cancel_trial=can_cancel_trial,
        request_new_trial_form=request_new_trial_form,
        can_request_new_trial=can_request_new_trial,
    )


@app.route('/api/conversa_admin', methods=['POST'])
@app.route('/api/conversa_admin/<int:user_id>', methods=['POST'])
@login_required
def api_conversa_admin_message(user_id=None):
    """Recebe nova mensagem na conversa com o admin e retorna HTML."""
    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        abort(404)

    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'

    if is_admin:
        if user_id is None:
            return '', 400
        interlocutor = get_user_or_404(user_id)
    else:
        interlocutor = admin_user

    form = MessageForm()
    if form.validate_on_submit():
        nova_msg = Message(
            sender_id=current_user.id,
            receiver_id=interlocutor.id,
            content=form.content.data,
            lida=False,
        )
        db.session.add(nova_msg)
        _notify_admin_message(
            receiver=interlocutor,
            sender=current_user,
            message_content=form.content.data,
        )
        db.session.commit()
        return render_template('components/message.html', msg=nova_msg)
    return '', 400


@app.route('/admin/users/<int:user_id>/promover_veterinario', methods=['POST'])
@login_required
def admin_promote_veterinarian(user_id):
    if not (current_user.is_authenticated and (current_user.role or '').lower() == 'admin'):
        abort(403)

    user = User.query.get_or_404(user_id)
    form = VeterinarianPromotionForm()

    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    crmv = form.crmv.data
    existing = (
        Veterinario.query.filter(
            func.lower(Veterinario.crmv) == crmv.lower(),
            Veterinario.user_id != user.id,
        ).first()
    )
    if existing:
        flash('Este CRMV já está associado a outro profissional.', 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    vet_profile = grant_veterinarian_role(
        user,
        crmv=crmv,
        phone=form.phone.data or None,
    )
    membership = ensure_veterinarian_membership(vet_profile)
    if membership:
        membership.ensure_trial_dates(current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30))

    db.session.commit()
    flash('Usuário promovido a veterinário. Período de avaliação iniciado.', 'success')
    return redirect(url_for('conversa_admin', user_id=user.id))


@app.route('/mensagens_admin')
@login_required
def mensagens_admin():
    """Lista as conversas iniciadas pelos usuários com o administrador."""
    if current_user.role != 'admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('index'))

    wants_json = 'application/json' in request.headers.get('Accept', '')
    page = max(request.args.get('page', type=int, default=1), 1)
    per_page = request.args.get('per_page', type=int, default=10)
    per_page = max(1, min(per_page or 10, 50))
    kind = request.args.get('kind', 'animals')

    admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]

    def _build_query(target_kind):
        query = (
            Message.query
            .options(
                selectinload(Message.sender),
                selectinload(Message.receiver),
                selectinload(Message.animal),
            )
            .filter((Message.sender_id.in_(admin_ids)) | (Message.receiver_id.in_(admin_ids)))
            .order_by(Message.timestamp.desc())
        )
        if target_kind == 'animals':
            query = query.filter(Message.animal_id.isnot(None))
        else:
            query = query.filter(Message.animal_id.is_(None))
        return query

    def _collect_threads(query):
        seen = set()
        threads = []
        offset = 0
        step = per_page * max(page, 2)
        last_batch_size = 0
        required = page * per_page
        while len(threads) < required:
            batch = query.offset(offset).limit(step).all()
            last_batch_size = len(batch)
            if not batch:
                break
            for message in batch:
                other_id = (
                    message.sender_id
                    if message.sender_id not in admin_ids
                    else message.receiver_id
                )
                key = (other_id, message.animal_id or 0)
                if key in seen:
                    continue
                seen.add(key)
                threads.append(message)
            offset += step
        start = (page - 1) * per_page
        page_items = threads[start:start + per_page]
        has_more = len(threads) > start + per_page
        if not has_more and last_batch_size == step:
            extra_batch = query.offset(offset).limit(per_page).all()
            for message in extra_batch:
                other_id = (
                    message.sender_id
                    if message.sender_id not in admin_ids
                    else message.receiver_id
                )
                key = (other_id, message.animal_id or 0)
                if key not in seen:
                    has_more = True
                    break
        return page_items, has_more

    unread = (
        db.session.query(Message.sender_id, db.func.count())
        .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
        .group_by(Message.sender_id)
        .all()
    )
    unread_counts = {u[0]: u[1] for u in unread}

    if wants_json:
        query = _build_query(kind)
        threads, has_more = _collect_threads(query)
        html = render_template(
            'mensagens/_admin_threads.html',
            threads=threads,
            unread_counts=unread_counts,
            kind=kind,
        )
        next_page = page + 1 if has_more else None
        return jsonify({
            'success': True,
            'html': html,
            'next_page': next_page,
            'kind': kind,
            'page': page,
        })

    animais_threads, animais_has_more = _collect_threads(_build_query('animals'))
    gerais_threads, gerais_has_more = _collect_threads(_build_query('general'))

    return render_template(
        'mensagens/mensagens_admin.html',
        mensagens_animais=animais_threads,
        mensagens_gerais=gerais_threads,
        unread_counts=unread_counts,
        animais_next=2 if animais_has_more else None,
        gerais_next=2 if gerais_has_more else None,
        per_page=per_page,
    )


@app.context_processor
def inject_unread_count():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
            unread = (
                Message.query
                .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
                .count()
            )
        else:
            unread = (
                Message.query
                .filter_by(receiver_id=current_user.id, lida=False)
                .count()
            )
        return dict(unread_messages=unread)
    return dict(unread_messages=0)


@app.context_processor
def inject_mp_public_key():
    """Disponibiliza a chave pública do Mercado Pago para os templates."""
    return dict(MERCADOPAGO_PUBLIC_KEY=current_app.config.get("MERCADOPAGO_PUBLIC_KEY"))


@app.context_processor
def inject_default_pickup_address():
    """Exposes DEFAULT_PICKUP_ADDRESS config to templates."""
    return dict(DEFAULT_PICKUP_ADDRESS=current_app.config.get("DEFAULT_PICKUP_ADDRESS"))


@app.route('/animal/<int:animal_id>/deletar', methods=['POST'])
@login_required
def deletar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if not (
        current_user.role == 'admin'
        or animal.user_id == current_user.id
        or animal.added_by_id == current_user.id
    ):
        message = 'Você não tem permissão para excluir este animal.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='danger'), 403
        flash(message, 'danger')
        abort(403)

    if animal.removido_em:
        message = 'Animal já foi removido anteriormente.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='warning'), 400
        flash(message, 'warning')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    animal.removido_em = datetime.utcnow()
    db.session.commit()
    message = 'Animal marcado como removido. Histórico preservado.'
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message=message, category='success', deleted=True)
    flash(message, 'success')
    return redirect(request.referrer or url_for('list_animals'))


@app.route('/termo/interesse/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_interesse(animal_id, user_id):
    animal = get_animal_or_404(animal_id)
    interessado = get_user_or_404(user_id)

    if request.method == 'POST':
        # Verifica se já existe um interesse registrado
        interesse_existente = Interest.query.filter_by(
            user_id=interessado.id, animal_id=animal.id).first()

        if not interesse_existente:
            # Cria novo interesse
            novo_interesse = Interest(user_id=interessado.id, animal_id=animal.id)
            db.session.add(novo_interesse)

            # Cria mensagem automática
            mensagem = Message(
                sender_id=current_user.id,
                receiver_id=animal.user_id,
                animal_id=animal.id,
                content=f"Tenho interesse em {'comprar' if animal.modo == 'venda' else 'adotar'} o animal {animal.name}.",
                lida=False
            )
            db.session.add(mensagem)
            db.session.commit()

            flash('Você demonstrou interesse. Aguardando aprovação do tutor.', 'info')
        else:
            flash('Você já demonstrou interesse anteriormente.', 'warning')

        return redirect(url_for('conversa', animal_id=animal.id, user_id=animal.user_id))

    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    return render_template('termos/termo_interesse.html', animal=animal, interessado=interessado, data_atual=data_atual)


# Função local de formatação, caso ainda não tenha no projeto
def formatar_telefone(telefone: str) -> str:
    telefone = ''.join(filter(str.isdigit, telefone))  # Remove qualquer coisa que não seja número
    if telefone.startswith('55'):
        return f"+{telefone}"
    elif telefone.startswith('0'):
        return f"+55{telefone[1:]}"
    elif len(telefone) == 11:
        return f"+55{telefone}"
    else:
        return f"+55{telefone}"


APPOINTMENT_STATUS_LABELS = {
    'scheduled': 'A fazer',
    'accepted': 'Aceita',
    'completed': 'Realizada',
    'canceled': 'Cancelada',
}

APPOINTMENT_KIND_LABELS = {
    'consulta': 'Consulta',
    'retorno': 'Retorno',
    'exame': 'Exame',
    'banho_tosa': 'Banho e Tosa',
    'vacina': 'Vacina',
    'general': 'Geral',
}

ORCAMENTO_STATUS_LABELS = {
    'draft': 'Rascunho',
    'sent': 'Enviado',
    'approved': 'Aprovado',
    'rejected': 'Rejeitado',
    'canceled': 'Cancelado',
}

ORCAMENTO_STATUS_STYLES = {
    'draft': 'secondary',
    'sent': 'info',
    'approved': 'success',
    'rejected': 'danger',
    'canceled': 'dark',
}


def enviar_mensagem_whatsapp(texto: str, numero: str) -> None:
    """Envia uma mensagem de WhatsApp usando a API do Twilio."""

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM")

    if not all([account_sid, auth_token, from_number]):
        raise RuntimeError("Credenciais do Twilio não configuradas")

    client = Client(account_sid, auth_token)
    client.messages.create(body=texto, from_=from_number, to=numero)


def verificar_datas_proximas() -> None:
    from models import Appointment, ExameSolicitado, Vacina, Notification

    with app.app_context():
        agora = datetime.now(BR_TZ)
        limite = agora + timedelta(days=1)

        consultas = (
            Appointment.query
            .filter(Appointment.scheduled_at >= agora, Appointment.scheduled_at <= limite)
            .all()
        )
        for appt in consultas:
            tutor = appt.tutor
            texto = (
                f"Lembrete: consulta de {appt.animal.name} em "
                f"{appt.scheduled_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')}"
            )
            if tutor.email:
                msg = MailMessage(
                    subject="Lembrete de consulta - PetOrlândia",
                    sender=app.config['MAIL_DEFAULT_SENDER'],
                    recipients=[tutor.email],
                    body=texto,
                )
                mail.send(msg)
                db.session.add(Notification(user_id=tutor.id, message=texto, channel='email', kind='appointment'))
            if tutor.phone:
                numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
                try:
                    enviar_mensagem_whatsapp(texto, numero)
                    db.session.add(Notification(user_id=tutor.id, message=texto, channel='whatsapp', kind='appointment'))
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        exames = (
            ExameSolicitado.query
            .filter(
                ExameSolicitado.status == 'pendente',
                ExameSolicitado.performed_at.isnot(None),
                ExameSolicitado.performed_at >= agora,
                ExameSolicitado.performed_at <= limite,
            )
            .all()
        )
        for ex in exames:
            tutor = ex.bloco.animal.owner
            texto = (
                f"Lembrete: exame '{ex.nome}' de {ex.bloco.animal.name} em "
                f"{ex.performed_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')}"
            )
            if tutor.email:
                msg = MailMessage(
                    subject="Lembrete de exame - PetOrlândia",
                    sender=app.config['MAIL_DEFAULT_SENDER'],
                    recipients=[tutor.email],
                    body=texto,
                )
                mail.send(msg)
                db.session.add(Notification(user_id=tutor.id, message=texto, channel='email', kind='exam'))
            if tutor.phone:
                numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
                try:
                    enviar_mensagem_whatsapp(texto, numero)
                    db.session.add(Notification(user_id=tutor.id, message=texto, channel='whatsapp', kind='exam'))
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        vacinas = (
            Vacina.query
            .filter(Vacina.aplicada_em >= agora.date(), Vacina.aplicada_em <= limite.date())
            .all()
        )
        for vac in vacinas:
            tutor = vac.animal.owner
            texto = (
                f"Lembrete: vacina '{vac.nome}' de {vac.animal.name} em "
                f"{vac.aplicada_em.strftime('%d/%m/%Y')}"
            )
            if tutor.email:
                msg = MailMessage(
                    subject="Lembrete de vacina - PetOrlândia",
                    sender=app.config['MAIL_DEFAULT_SENDER'],
                    recipients=[tutor.email],
                    body=texto,
                )
                mail.send(msg)
                db.session.add(Notification(user_id=tutor.id, message=texto, channel='email', kind='vaccine'))
            if tutor.phone:
                numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
                try:
                    enviar_mensagem_whatsapp(texto, numero)
                    db.session.add(Notification(user_id=tutor.id, message=texto, channel='whatsapp', kind='vaccine'))
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        db.session.commit()


if not app.config.get("TESTING"):
    scheduler = BackgroundScheduler(timezone=str(BR_TZ))
    scheduler.add_job(verificar_datas_proximas, 'cron', hour=8)
    scheduler.start()


@app.route('/termo/transferencia/<int:animal_id>/<int:user_id>', methods=['GET', 'POST'])
@login_required
def termo_transferencia(animal_id, user_id):
    animal = get_animal_or_404(animal_id)
    novo_dono = get_user_or_404(user_id)

    if animal.owner.id != current_user.id:
        flash("Você não tem permissão para transferir esse animal.", "danger")
        return redirect(url_for('profile'))

    if request.method == 'POST':
        try:
            # Transfere a tutoria
            animal.user_id = novo_dono.id
            animal.status = 'indisponível'
            animal.modo = 'adotado'

            # Cria a transação
            transacao = Transaction(
                animal_id=animal.id,
                from_user_id=current_user.id,
                to_user_id=novo_dono.id,
                type='adoção' if animal.modo == 'doação' else 'venda',
                status='concluída',
                date=datetime.utcnow()
            )
            db.session.add(transacao)

            # Envia uma mensagem interna para o novo tutor
            msg = Message(
                sender_id=current_user.id,
                receiver_id=novo_dono.id,
                animal_id=animal.id,
                content=f"Parabéns! Você agora é o tutor de {animal.name}. 🐾",
                lida=False
            )
            db.session.add(msg)

            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao transferir tutoria")
            flash('Ocorreu um erro ao transferir a tutoria.', 'danger')
        else:
            flash(f'Tutoria de {animal.name} transferida para {novo_dono.name}.', 'success')

            # WhatsApp para o novo tutor
            if novo_dono.phone:
                numero_formatado = f"whatsapp:{formatar_telefone(novo_dono.phone)}"
                texto_wpp = f"Parabéns, {novo_dono.name}! Agora você é o tutor de {animal.name} pelo PetOrlândia. 🐶🐱"

                try:
                    enviar_mensagem_whatsapp(texto_wpp, numero_formatado)
                except Exception as e:
                    current_app.logger.error("Erro ao enviar WhatsApp: %s", e)

        return redirect(url_for('profile'))

    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    return render_template('termos/termo_transferencia.html', animal=animal, novo_dono=novo_dono)

@app.route('/animal/<int:animal_id>/termo/<string:tipo>')
@login_required
def termo_animal(animal_id, tipo):
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    clinica = current_user.veterinario.clinica if current_user.veterinario else None
    data_atual = datetime.now(BR_TZ).strftime('%d/%m/%Y')
    templates = {
        'internacao': 'termos/termo_internacao.html',
        'eutanasia': 'termos/termo_eutanasia.html',
        'procedimentos': 'termos/termo_procedimentos.html',
        'exames': 'termos/termo_exames.html',
        'imagem': 'termos/termo_imagem.html',
        'medicacao': 'termos/termo_medicacao.html',
        'planos': 'termos/termo_planos.html',
        'adocao': 'termos/termo_adocao.html',
    }
    template = templates.get(tipo)
    if not template:
        abort(404)
    return render_template(template, animal=animal, tutor=tutor, clinica=clinica, data_atual=data_atual)




@app.route('/termo/<int:animal_id>/<tipo>')
@login_required
def gerar_termo(animal_id, tipo):
    """Gera um termo específico para um animal."""
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    veterinario = current_user.veterinario
    template_name = f'termos/{tipo}.html'
    try:
        return render_template(
            template_name,
            animal=animal,
            tutor=tutor,
            veterinario=veterinario,
            tipo=tipo,
        )
    except TemplateNotFound:
        abort(404)


@app.route("/plano-saude")
@login_required
def plano_saude_overview():
    # animais ativos do tutor
    animais_do_usuario = (
        Animal.query
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .all()
    )

    # assinaturas de plano de saúde do tutor → dict {animal_id: sub}
    from models import HealthSubscription
    subs = (
        HealthSubscription.query
        .filter_by(user_id=current_user.id, active=True)
        .all()
    )
    subscriptions = {s.animal_id: s for s in subs}

    return render_template(
        "planos/plano_saude_overview.html",
        animais=animais_do_usuario,
        subscriptions=subscriptions,   # ← agora o template encontra
        user=current_user,
    )


@app.route('/admin/planos/dashboard')
@login_required
def planos_dashboard():
    from admin import _is_admin
    if not _is_admin():
        abort(403)
    metrics = summarize_plan_metrics()
    history = build_usage_history(limit=25)
    return render_template('planos/dashboard.html', metrics=metrics, history=history)

@app.route("/animal/<int:animal_id>/planosaude", methods=["GET", "POST"])
@login_required
def planosaude_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.owner != current_user:
        flash("Você não tem permissão para acessar esse animal.", "danger")
        return redirect(url_for("profile"))

    form = SubscribePlanForm()
    from models import HealthPlan, HealthPlanOnboarding, HealthSubscription
    plans = HealthPlan.query.options(selectinload(HealthPlan.coverages)).all()
    form.plan_id.choices = [
        (p.id, f"{p.name} - R$ {p.price:.2f}") for p in plans
    ]
    plans_data = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": p.price,
            "coverages": [
                {
                    "name": c.name,
                    "code": c.procedure_code,
                    "limit": float(c.monetary_limit or 0),
                    "waiting": c.waiting_period_days,
                    "deductible": float(c.deductible_amount or 0),
                }
                for c in p.coverages
            ],
        }
        for p in plans
    ]
    subscription = (
        HealthSubscription.query
        .filter_by(animal_id=animal.id, user_id=current_user.id, active=True)
        .first()
    )
    onboarding = (
        HealthPlanOnboarding.query
        .filter_by(animal_id=animal.id)
        .order_by(HealthPlanOnboarding.created_at.desc())
        .first()
    )

    if form.validate_on_submit():
        # TODO: processar contratação do plano aqui…
        flash("Plano de saúde contratado!", "success")
        return redirect(url_for("planosaude_animal", animal_id=animal_id))

    return render_template(
        "animais/planosaude_animal.html",
        animal=animal,
        form=form,        # {{ form.hidden_tag() }} agora existe
        subscription=subscription,
        plans=plans_data,
        onboarding=onboarding,
    )



@app.route("/plano-saude/<int:animal_id>/contratar", methods=["POST"])
@login_required
def contratar_plano(animal_id):
    """Inicia a assinatura de um plano de saúde via Mercado Pago."""
    animal = get_animal_or_404(animal_id)

    if animal.owner != current_user:
        flash("Você não tem permissão para contratar este plano.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    form = SubscribePlanForm()
    from models import HealthPlan, HealthPlanOnboarding
    plans = HealthPlan.query.all()
    form.plan_id.choices = [
        (p.id, f"{p.name} - R$ {p.price:.2f}") for p in plans
    ]
    if not form.validate_on_submit():
        flash("Selecione um plano válido.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    plan = HealthPlan.query.get_or_404(form.plan_id.data)

    onboarding = HealthPlanOnboarding(
        plan_id=plan.id,
        animal_id=animal.id,
        user_id=current_user.id,
        guardian_document=form.tutor_document.data,
        animal_document=form.animal_document.data or None,
        contract_reference=form.contract_reference.data or None,
        extra_notes=form.extra_notes.data or None,
        consent_ip=request.remote_addr,
        attachments={'document_links': form.document_links.data} if form.document_links.data else None,
    )
    db.session.add(onboarding)
    db.session.commit()
    flash('Documentos enviados para análise da seguradora.', 'info')

    preapproval_data = {
        "reason": f"{plan.name} - {animal.name}",
        "back_url": url_for("planosaude_animal", animal_id=animal.id, _external=True),
        "payer_email": current_user.email,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(plan.price),
            "currency_id": "BRL",
        },
    }

    try:
        resp = mp_sdk().preapproval().create(preapproval_data)
    except Exception:  # pragma: no cover - network failures
        app.logger.exception("Erro de conexão com Mercado Pago")
        flash("Falha ao conectar com Mercado Pago.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    if resp.get("status") not in {200, 201}:
        app.logger.error("MP error (HTTP %s): %s", resp.get("status"), resp)
        flash("Erro ao iniciar assinatura.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    init_point = (resp.get("response", {}).get("init_point") or
                  resp.get("response", {}).get("sandbox_init_point"))
    if not init_point:
        flash("Erro ao iniciar assinatura.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    return redirect(init_point)


@app.route('/consulta/<int:consulta_id>/validar-plano', methods=['POST'])
@login_required
def validar_plano_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        abort(403)
    form = ConsultaPlanAuthorizationForm()
    from models import HealthSubscription
    active_subs = (
        HealthSubscription.query
        .filter_by(animal_id=consulta.animal_id, active=True)
        .all()
    )
    form.subscription_id.choices = [
        (s.id, f"{s.plan.name} – vigente desde {s.start_date.date():%d/%m/%Y}")
        for s in active_subs
    ]
    if not active_subs:
        flash('O tutor não possui plano ativo para este animal.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))
    if not form.validate_on_submit():
        flash('Selecione um plano válido para validar a cobertura.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))

    subscription = HealthSubscription.query.get_or_404(form.subscription_id.data)
    if subscription.animal_id != consulta.animal_id:
        flash('Plano selecionado não pertence a este animal.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))

    consulta.health_subscription_id = subscription.id
    consulta.health_plan_id = subscription.plan_id
    consulta.authorization_reference = f"PRG-{consulta.id}-{int(datetime.utcnow().timestamp())}"
    consulta.authorization_checked_at = datetime.utcnow()
    consulta.authorization_notes = form.notes.data or ''

    result = evaluate_consulta_coverages(consulta)
    consulta.authorization_status = result['status']
    if result.get('messages'):
        consulta.authorization_notes = '\n'.join(result['messages'])
    db.session.commit()

    category = 'success' if result['status'] == 'approved' else 'warning'
    flash(' '.join(result.get('messages', [])) or 'Cobertura analisada.', category)
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))








@app.route('/api/seguradoras/sinistros', methods=['POST'])
def api_criar_sinistro():
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    payload = request.get_json(silent=True) or {}
    subscription_id = payload.get('subscription_id') or payload.get('subscriptionId')
    if not subscription_id:
        return jsonify({'error': 'subscription_id é obrigatório'}), 400
    from models import HealthSubscription, HealthClaim
    subscription = HealthSubscription.query.get_or_404(subscription_id)
    consulta_id = payload.get('consulta_id') or payload.get('consultaId')
    coverage_code = payload.get('procedure_code') or payload.get('procedureCode')
    coverage = None
    if coverage_code and subscription.plan:
        coverage = next((c for c in subscription.plan.coverages if c.matches(coverage_code)), None)
    claim = HealthClaim(
        subscription_id=subscription.id,
        consulta_id=consulta_id,
        coverage_id=coverage.id if coverage else None,
        insurer_reference=payload.get('reference') or payload.get('id'),
        request_format='fhir' if payload.get('resourceType') else 'json',
        payload=payload,
        status=payload.get('status') or 'received',
    )
    db.session.add(claim)
    db.session.commit()
    return jsonify({'id': claim.id, 'status': claim.status}), 201


@app.route('/api/seguradoras/sinistros/<int:claim_id>')
def api_status_sinistro(claim_id):
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    from models import HealthClaim
    claim = HealthClaim.query.get_or_404(claim_id)
    return jsonify({
        'id': claim.id,
        'status': claim.status,
        'consulta_id': claim.consulta_id,
        'subscription_id': claim.subscription_id,
        'coverage_id': claim.coverage_id,
        'payload': claim.payload,
        'response_payload': claim.response_payload,
    })


@app.route('/api/seguradoras/planos/<int:plan_id>/historico')
def api_historico_uso(plan_id):
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    limit = request.args.get('limit', 50, type=int)
    history = build_usage_history(plan_id=plan_id, limit=limit)
    return jsonify({'plan_id': plan_id, 'historico': history})


@app.route('/api/seguradoras/consultas/<int:consulta_id>/autorizacao')
def api_status_autorizacao(consulta_id):
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    consulta = Consulta.query.get_or_404(consulta_id)
    return jsonify({
        'consulta_id': consulta.id,
        'animal_id': consulta.animal_id,
        'status': consulta.authorization_status,
        'status_label': coverage_label(consulta.authorization_status),
        'checked_at': consulta.authorization_checked_at.isoformat() if consulta.authorization_checked_at else None,
        'notes': consulta.authorization_notes,
    })


@app.route('/animal/<int:animal_id>/ficha')
@login_required
def ficha_animal(animal_id):
    animal = get_animal_or_404(animal_id)
    tutor = animal.owner

    wants_json = 'application/json' in request.headers.get('Accept', '')
    section = request.args.get('section')

    def _load_consultas():
        consultas_query = Consulta.query.filter_by(
            animal_id=animal.id,
            status='finalizada',
        )
        if (
            current_user.role != 'admin'
            and current_user.worker in ['veterinario', 'colaborador']
        ):
            consultas_query = consultas_query.filter_by(
                clinica_id=current_user_clinic_id()
            )
        return consultas_query.order_by(Consulta.created_at.desc()).all()

    def _load_history_data():
        consultas = _load_consultas()
        blocos_prescricao_query = BlocoPrescricao.query.filter_by(
            animal_id=animal.id
        )
        clinic_scope = None
        if current_user.role != 'admin':
            clinic_scope = current_user_clinic_id()
        if clinic_scope:
            blocos_prescricao_query = blocos_prescricao_query.filter_by(
                clinica_id=clinic_scope
            )
        blocos_prescricao = blocos_prescricao_query.all()
        blocos_exames = BlocoExames.query.filter_by(animal_id=animal.id).all()
        vacinas_aplicadas = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=True)
            .order_by(Vacina.aplicada_em.desc())
            .all()
        )
        doses_atrasadas = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
            .filter(Vacina.aplicada_em < date.today())
            .order_by(Vacina.aplicada_em)
            .all()
        )
        return {
            'consultas': consultas,
            'blocos_prescricao': blocos_prescricao,
            'blocos_exames': blocos_exames,
            'vacinas_aplicadas': vacinas_aplicadas,
            'doses_atrasadas': doses_atrasadas,
        }

    def _load_events_data():
        now = datetime.utcnow()
        vacinas_agendadas = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
            .filter(Vacina.aplicada_em >= date.today())
            .order_by(Vacina.aplicada_em)
            .all()
        )
        retornos = (
            Appointment.query.filter_by(animal_id=animal.id)
            .filter(Appointment.scheduled_at >= now)
            .filter(Appointment.status.in_(["scheduled", "accepted"]))
            .filter(Appointment.consulta_id.isnot(None))
            .order_by(Appointment.scheduled_at)
            .all()
        )
        exames_agendados = (
            ExamAppointment.query.filter_by(animal_id=animal.id)
            .filter(ExamAppointment.scheduled_at >= now)
            .filter(ExamAppointment.status.in_(["pending", "confirmed"]))
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        return {
            'vacinas_agendadas': vacinas_agendadas,
            'retornos': retornos,
            'exames_agendados': exames_agendados,
        }

    if wants_json or section:
        current_section = section or 'events'
        if current_section == 'events':
            data = _load_events_data()
            html = render_template(
                'animais/_animal_events.html',
                animal=animal,
                **data,
            )
            return jsonify({'success': True, 'html': html, 'section': 'events'})
        if current_section == 'history':
            data = _load_history_data()
            html = render_template(
                'animais/_animal_history.html',
                animal=animal,
                tutor=tutor,
                **data,
            )
            return jsonify({'success': True, 'html': html, 'section': 'history'})
        return jsonify({'success': False, 'message': 'Seção inválida.'}), 400

    events_url = url_for('ficha_animal', animal_id=animal.id, section='events')
    history_url = url_for('ficha_animal', animal_id=animal.id, section='history')
    return render_template(
        'animais/ficha_animal.html',
        animal=animal,
        tutor=tutor,
        events_url=events_url,
        history_url=history_url,
    )
@app.route('/animal/<int:animal_id>/documentos', methods=['POST'])
@login_required
def upload_document(animal_id):
    animal = get_animal_or_404(animal_id)
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem enviar documentos.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    file = request.files.get('documento')
    if not file or file.filename == '':
        flash('Nenhum arquivo enviado.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    descricao = (request.form.get('descricao') or '').strip().lower()
    tipo_termo = (request.form.get('tipo') or descricao)
    filename_base = secure_filename(file.filename)
    ext = os.path.splitext(filename_base)[1]
    if tipo_termo in ['termo_interesse', 'termo_transferencia']:
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{tipo_termo}_{animal.id}_{timestamp}{ext}"
    else:
        filename = f"{uuid.uuid4().hex}_{filename_base}"

    file_url = upload_to_s3(file, filename, folder='documentos')
    if not file_url:
        flash('Falha ao enviar arquivo.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))

    documento = AnimalDocumento(
        animal_id=animal.id,
        veterinario_id=current_user.id,
        filename=filename,
        file_url=file_url,
        descricao=descricao
    )
    db.session.add(documento)
    db.session.commit()

    flash('Documento enviado com sucesso!', 'success')
    return redirect(request.referrer or url_for('ficha_animal', animal_id=animal.id))


@app.route('/animal/<int:animal_id>/documentos/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(animal_id, doc_id):
    documento = AnimalDocumento.query.filter_by(id=doc_id, animal_id=animal_id).first_or_404()

    if not (
        current_user.role == 'admin'
        or (
            is_veterinarian(current_user)
            and current_user.id == documento.veterinario_id
        )
    ):
        flash('Você não tem permissão para excluir este documento.', 'danger')
        return redirect(request.referrer or url_for('ficha_animal', animal_id=animal_id))

    prefix = f"https://{BUCKET}.s3.amazonaws.com/"
    if documento.file_url and documento.file_url.startswith(prefix):
        key = documento.file_url[len(prefix):]
        try:
            _s3().delete_object(Bucket=BUCKET, Key=key)
        except Exception as exc:  # noqa: BLE001
            app.logger.exception('Falha ao remover arquivo do S3: %s', exc)

    db.session.delete(documento)
    db.session.commit()

    flash('Documento excluído com sucesso!', 'success')
    return redirect(request.referrer or url_for('ficha_animal', animal_id=animal_id))






@app.route('/animal/<int:animal_id>/editar_ficha', methods=['GET', 'POST'])
@login_required
def editar_ficha_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    # Dados fictícios para fins de edição simples (substituir por formulário real depois)
    if request.method == 'POST':
        nova_vacina = request.form.get("vacina")
        nova_consulta = request.form.get("consulta")
        novo_medicamento = request.form.get("medicamento")

        print(f"Vacina adicionada: {nova_vacina}")
        print(f"Consulta adicionada: {nova_consulta}")
        print(f"Medicação adicionada: {novo_medicamento}")

        flash("Informacões adicionadas com sucesso (simulação).", "success")
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    return render_template("editar_ficha.html", animal=animal)


@app.route('/generate_qr/<int:animal_id>')
@login_required
def generate_qr(animal_id):
    animal = get_animal_or_404(animal_id)
    if current_user.id != animal.user_id:
        flash('Você não tem permissão para gerar o QR code deste animal.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal_id))

    # Gera token
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(minutes=10)  # por exemplo, 10 minutos

    qr_token = ConsultaToken(
        token=token,
        animal_id=animal.id,
        tutor_id=current_user.id,
        expires_at=expires
    )
    db.session.add(qr_token)
    db.session.commit()

    consulta_url = url_for('consulta_qr', token=token, _external=True)
    img = qrcode.make(consulta_url)

    buffer = BytesIO()
    img.save(buffer)
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')




@app.route('/consulta_qr', methods=['GET'])
@login_required
def consulta_qr():
    animal_id = request.args.get('animal_id', type=int)
    token = request.args.get('token')  # se estiver usando QR com token

    # Aqui você já deve ter carregado o animal
    animal = get_animal_or_404(animal_id)
    clinica_id = current_user_clinic_id()

    # Idade e unidade (anos/meses)
    idade = ''
    idade_unidade = ''
    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            idade = delta.years
            idade_unidade = 'ano' if delta.years == 1 else 'anos'
        else:
            idade = delta.months
            idade_unidade = 'mês' if delta.months == 1 else 'meses'
    elif animal.age:
        partes = str(animal.age).split()
        try:
            idade = int(partes[0])
        except (ValueError, IndexError):
            idade = ''
        if len(partes) > 1:
            idade_unidade = partes[1]


    # Lógica adicional
    tutor = animal.owner
    consulta = (
        Consulta.query
        .filter_by(animal_id=animal.id, clinica_id=clinica_id)
        .order_by(Consulta.id.desc())
        .first()
    )
    tutor_form = EditProfileForm(obj=tutor)

    servicos = []
    if clinica_id:
        servicos = (
            ServicoClinica.query
            .filter_by(clinica_id=clinica_id)
            .order_by(ServicoClinica.descricao)
            .all()
        )

    plan_form = None
    active_plan_subscriptions = []
    authorization_summary = None
    if animal and worker_role == 'veterinario' and consulta:
        from models import HealthSubscription
        active_plan_subscriptions = (
            HealthSubscription.query
            .filter_by(animal_id=animal.id, active=True)
            .all()
        )
        plan_form = ConsultaPlanAuthorizationForm()
        plan_form.subscription_id.choices = [
            (s.id, f"{s.plan.name} – desde {s.start_date.date():%d/%m/%Y}")
            for s in active_plan_subscriptions
        ]
        if consulta.health_subscription_id:
            plan_form.subscription_id.data = consulta.health_subscription_id
        authorization_summary = {
            'status': consulta.authorization_status,
            'notes': consulta.authorization_notes,
            'checked_at': consulta.authorization_checked_at,
        }

    clinic_scope_id = clinica_id
    shared_access = _resolve_shared_access_for_animal(animal, viewer=current_user, clinic_scope=clinic_scope_id)
    blocos_orcamento = _clinic_orcamento_blocks(animal, clinic_scope_id)
    blocos_prescricao = _clinic_prescricao_blocks(animal, clinic_scope_id)

    return render_template(
        'consulta_qr.html',
        tutor=tutor,
        animal=animal,
        consulta=consulta,
        animal_idade=idade,
        animal_idade_unidade=idade_unidade,
        tutor_form=tutor_form,
        servicos=servicos,
        worker=getattr(current_user, 'worker', None),
        blocos_orcamento=blocos_orcamento,
        blocos_prescricao=blocos_prescricao,
        clinic_scope_id=clinic_scope_id,
        plan_form=plan_form,
        active_plan_subscriptions=active_plan_subscriptions,
        authorization_summary=authorization_summary,
        shared_access=shared_access,
        viewer_clinic_id=clinica_id,
    )








@app.route('/consulta/<int:animal_id>')
@login_required
def consulta_direct(animal_id):
    worker_role = getattr(current_user, 'worker', None)
    if not (is_veterinarian(current_user) or worker_role == 'colaborador'):
        abort(403)

    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    clinica_id = current_user_clinic_id()

    appointment_id = request.args.get('appointment_id', type=int)
    appointment = None
    if appointment_id:
        appointment = Appointment.query.get_or_404(appointment_id)
        if appointment.animal_id != animal.id:
            abort(404)
        appointment_clinic_id = appointment.clinica_id or (
            appointment.veterinario.clinica_id if appointment.veterinario else None
        )
        if not appointment_clinic_id and getattr(appointment, 'animal', None):
            appointment_clinic_id = appointment.animal.clinica_id
        if appointment_clinic_id:
            ensure_clinic_access(appointment_clinic_id)
            if clinica_id and appointment_clinic_id != clinica_id:
                abort(404)
            if not clinica_id:
                clinica_id = appointment_clinic_id

    edit_id = request.args.get('c', type=int)
    edit_mode = False

    consulta = None
    if is_veterinarian(current_user):
        consulta_created = False
        appointment_updated = False

        if edit_id:
            consulta = get_consulta_or_404(edit_id)
            edit_mode = True
        else:
            if appointment and appointment.consulta_id:
                consulta_vinculada = get_consulta_or_404(appointment.consulta_id)
                if consulta_vinculada.status != 'finalizada':
                    consulta = consulta_vinculada

            if not consulta:
                consulta = (
                    Consulta.query
                    .filter_by(animal_id=animal.id, status='in_progress', clinica_id=clinica_id)
                    .first()
                )

            if not consulta:
                consulta = Consulta(
                    animal_id=animal.id,
                    created_by=current_user.id,
                    clinica_id=clinica_id,
                    status='in_progress'
                )
                db.session.add(consulta)
                consulta_created = True

        if appointment and consulta:
            if appointment.consulta_id != consulta.id:
                appointment.consulta = consulta
                appointment_updated = True

            vet_profile = getattr(current_user, 'veterinario', None)
            if (
                vet_profile
                and appointment.veterinario_id == getattr(vet_profile, 'id', None)
                and appointment.status not in {'completed', 'canceled'}
                and appointment.status != 'accepted'
            ):
                appointment.status = 'accepted'
                appointment_updated = True

        if consulta_created or appointment_updated:
            db.session.commit()
    else:
        consulta = None

    historico = []
    if is_veterinarian(current_user):
        historico = (
            Consulta.query
            .filter_by(animal_id=animal.id, status='finalizada', clinica_id=clinica_id)
            .order_by(Consulta.created_at.desc())
            .limit(10)
            .all()
        )

    clinic_scope_id = clinica_id
    blocos_orcamento = _clinic_orcamento_blocks(animal, clinic_scope_id)
    blocos_prescricao = _clinic_prescricao_blocks(animal, clinic_scope_id)

    tipos_racao = list_rations()
    marcas_existentes = sorted(set([t.marca for t in tipos_racao if t.marca]))
    linhas_existentes = sorted(set([t.linha for t in tipos_racao if t.linha]))

    # 🆕 Carregar listas de espécies e raças para o formulário
    species_list = list_species()
    breed_list = list_breeds()

    form = AnimalForm(obj=animal)
    tutor_form = EditProfileForm(obj=tutor)

    appointment_form = None
    if consulta:
        from models import Veterinario

        appointment_form = AppointmentForm()
        appointment_form.populate_animals(
            [animal],
            restrict_tutors=True,
            selected_tutor_id=getattr(animal, 'user_id', None),
            allow_all_option=False,
        )
        appointment_form.animal_id.data = animal.id
        vet_obj = None
        if consulta.veterinario and getattr(consulta.veterinario, "veterinario", None):
            vet_obj = consulta.veterinario.veterinario
        if vet_obj:
            vets = (
                Veterinario.query.filter_by(
                    clinica_id=current_user_clinic_id()
                ).all()
            )
            appointment_form.veterinario_id.choices = [
                (v.id, v.user.name) for v in vets
            ]
            appointment_form.veterinario_id.data = vet_obj.id

    # Idade e unidade (anos/meses)
    idade = ''
    idade_unidade = ''
    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            idade = delta.years
            idade_unidade = 'ano' if delta.years == 1 else 'anos'
        else:
            idade = delta.months
            idade_unidade = 'mês' if delta.months == 1 else 'meses'
    elif animal.age:
        partes = str(animal.age).split()
        try:
            idade = int(partes[0])
        except (ValueError, IndexError):
            idade = ''
        if len(partes) > 1:
            idade_unidade = partes[1]

    servicos = []
    if clinica_id:
        servicos = (
            ServicoClinica.query
            .filter_by(clinica_id=clinica_id)
            .order_by(ServicoClinica.descricao)
            .all()
        )

    return render_template(
        'consulta_qr.html',
        animal=animal,
        tutor=tutor,
        consulta=consulta,
        historico_consultas=historico,
        edit_mode=edit_mode,
        worker=current_user.worker,
        tipos_racao=tipos_racao,
        marcas_existentes=marcas_existentes,
        linhas_existentes=linhas_existentes,
        species_list=species_list,
        breed_list=breed_list,
        form=form,
        tutor_form=tutor_form,
        animal_idade=idade,
        animal_idade_unidade=idade_unidade,
        servicos=servicos,
        appointment_form=appointment_form,
        blocos_orcamento=blocos_orcamento,
        blocos_prescricao=blocos_prescricao,
        clinic_scope_id=clinic_scope_id,
    )



@app.route('/finalizar_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def finalizar_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem finalizar consultas.', 'danger')
        return redirect(url_for('index'))

    if consulta.orcamento_items:
        from models import HealthSubscription
        if not consulta.health_subscription_id:
            active_sub = (
                HealthSubscription.query
                .filter_by(animal_id=consulta.animal_id, active=True)
                .first()
            )
            if active_sub:
                flash('Associe e valide o plano de saúde antes de finalizar a consulta.', 'warning')
                return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))
        result = evaluate_consulta_coverages(consulta)
        consulta.authorization_status = result['status']
        consulta.authorization_checked_at = datetime.utcnow()
        consulta.authorization_notes = '\n'.join(result.get('messages', [])) if result.get('messages') else None
        if result['status'] != 'approved':
            db.session.commit()
            flash('Cobertura não aprovada. Revise o orçamento ou contate a seguradora.', 'danger')
            return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))

    consulta.status = 'finalizada'
    consulta.finalizada_em = datetime.utcnow()
    appointment = consulta.appointment
    if appointment and appointment.status != 'completed':
        appointment.status = 'completed'

    # Mensagem de resumo para o tutor
    resumo = (
        f"Consulta do {consulta.animal.name} finalizada.\n"
        f"Queixa: {consulta.queixa_principal or 'N/A'}\n"
        f"Conduta: {consulta.conduta or 'N/A'}\n"
        f"Prescrição: {consulta.prescricao or 'N/A'}"
    )
    msg = Message(
        sender_id=current_user.id,
        receiver_id=consulta.animal.owner.id,
        animal_id=consulta.animal_id,
        content=resumo,
    )
    db.session.add(msg)

    if appointment:
        db.session.commit()
        flash('Consulta finalizada e retorno já agendado.', 'success')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    # Prepara formulário de retorno com dados padrão
    form = AppointmentForm()
    form.populate_animals(
        [consulta.animal],
        restrict_tutors=True,
        selected_tutor_id=getattr(consulta.animal, 'user_id', None),
        allow_all_option=False,
    )
    form.animal_id.data = consulta.animal.id
    from models import Veterinario

    vets = (
        Veterinario.query.filter_by(
            clinica_id=current_user_clinic_id()
        ).all()
    )
    form.veterinario_id.choices = [(v.id, v.user.name) for v in vets]
    form.veterinario_id.data = consulta.veterinario.veterinario.id

    dias_retorno = current_app.config.get('DEFAULT_RETURN_DAYS', 7)
    data_recomendada = (datetime.now(BR_TZ) + timedelta(days=dias_retorno)).date()
    form.date.data = data_recomendada
    form.time.data = time(10, 0)

    db.session.commit()
    flash('Consulta finalizada e registrada no histórico! Agende o retorno.', 'success')
    return render_template('agendamentos/confirmar_retorno.html', consulta=consulta, form=form)


@app.route('/agendar_retorno/<int:consulta_id>', methods=['POST'])
@login_required
def agendar_retorno(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        abort(403)
    from models import Veterinario

    form = AppointmentForm()
    form.populate_animals(
        [consulta.animal],
        restrict_tutors=True,
        selected_tutor_id=getattr(consulta.animal, 'user_id', None),
        allow_all_option=False,
    )
    vets = (
        Veterinario.query.filter_by(
            clinica_id=current_user_clinic_id()
        ).all()
    )
    form.veterinario_id.choices = [(v.id, v.user.name) for v in vets]
    if form.validate_on_submit():
        scheduled_at_local = datetime.combine(form.date.data, form.time.data)
        vet_id = form.veterinario_id.data
        if not is_slot_available(vet_id, scheduled_at_local, kind='retorno'):
            flash('Horário indisponível para o veterinário selecionado.', 'danger')
        else:
            scheduled_at = (
                scheduled_at_local
                .replace(tzinfo=BR_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            duration = get_appointment_duration('retorno')
            if has_conflict_for_slot(vet_id, scheduled_at_local, duration):
                flash('Horário indisponível para o veterinário selecionado.', 'danger')
            else:
                current_vet = getattr(current_user, 'veterinario', None)
                same_user = current_vet and current_vet.id == vet_id
                appt = Appointment(
                    consulta_id=consulta.id,
                    animal_id=consulta.animal_id,
                    tutor_id=consulta.animal.owner.id,
                    veterinario_id=vet_id,
                    scheduled_at=scheduled_at,
                    notes=form.reason.data,
                    kind='retorno',
                    status='accepted' if same_user else 'scheduled',
                    created_by=current_user.id,
                    created_at=datetime.utcnow(),
                )
                db.session.add(appt)
                db.session.commit()
                flash('Retorno agendado com sucesso.', 'success')
    else:
        flash('Erro ao agendar retorno.', 'danger')
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/retorno/<int:appointment_id>/start', methods=['POST'])
@login_required
def iniciar_retorno(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    if current_user.worker != 'veterinario':
        abort(403)
    consulta = Consulta(
        animal_id=appt.animal_id,
        created_by=current_user.id,
        clinica_id=appt.clinica_id or current_user_clinic_id(),
        status='in_progress',
        retorno_de_id=appt.consulta_id,
    )
    db.session.add(consulta)
    appt.status = 'completed'
    db.session.commit()
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/consulta/<int:consulta_id>/deletar', methods=['POST'])
@login_required
def deletar_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal_id = consulta.animal_id
    if current_user.worker != 'veterinario':
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir consultas.'), 403
        flash('Apenas veterinários podem excluir consultas.', 'danger')
        return redirect(url_for('index'))

    db.session.delete(consulta)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = render_template(
            'partials/historico_consultas.html',
            animal=animal,
            historico_consultas=animal.consultas
        )
        return jsonify(success=True, html=historico_html)

    flash('Consulta excluída!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/imprimir_consulta/<int:consulta_id>')
@login_required
def imprimir_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal = consulta.animal
    tutor = animal.owner
    veterinario = consulta.veterinario
    clinica = consulta.clinica or (
        veterinario.veterinario.clinica if veterinario and veterinario.veterinario else None
    )

    return render_template(
        'orcamentos/imprimir_consulta.html',
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
    )




TUTOR_SEARCH_LIMIT = 50


@app.route('/buscar_tutores', methods=['GET'])
def buscar_tutores():
    raw_query = request.args.get('q', '')
    query = raw_query.strip()

    if not query:
        return jsonify([])

    clinic_id = current_user_clinic_id()

    sort_param = (request.args.get('sort') or 'name_asc').strip().lower()
    allowed_sorts = {'name_asc', 'recent_added', 'recent_attended'}
    if sort_param not in allowed_sorts:
        sort_param = 'name_asc'

    like_query = f"%{query}%"
    numeric_query = re.sub(r'\D', '', query)
    numeric_like = f"%{numeric_query}%" if numeric_query else None

    def sanitize_expression(expr, characters):
        sanitized = expr
        for char in characters:
            sanitized = func.replace(sanitized, char, '')
        return sanitized

    text_columns = [
        User.name,
        User.email,
        User.worker,
        User.address,
        User.cpf,
        User.rg,
        User.phone,
        Endereco.cep,
        Endereco.rua,
        Endereco.numero,
        Endereco.complemento,
        Endereco.bairro,
        Endereco.cidade,
        Endereco.estado,
    ]

    digit_columns = [
        sanitize_expression(User.cpf, ['.', '-', '/', ' ']),
        sanitize_expression(User.rg, ['.', '-', '/', ' ']),
        sanitize_expression(User.phone, ['(', ')', '-', ' ']),
        sanitize_expression(Endereco.cep, ['-', ' ']),
    ]

    filters = [column.ilike(like_query) for column in text_columns]

    if numeric_like:
        filters.extend(column.ilike(numeric_like) for column in digit_columns)

    visibility_clause = _user_visibility_clause(clinic_scope=current_user_clinic_id())

    tutores_query = (
        User.query.outerjoin(Endereco)
        .options(
            joinedload(User.endereco),
            joinedload(User.veterinario).joinedload(Veterinario.specialties),
        )
        .filter(or_(*filters))
    )

    if not _is_admin():
        tutores_query = tutores_query.filter(User.clinica_id == clinic_id)

    tutores_query = tutores_query.filter(visibility_clause).distinct()

    order_columns = []
    last_appt_subquery = None

    if sort_param == 'recent_attended':
        last_appt_query = db.session.query(
            Appointment.tutor_id.label('tutor_id'),
            func.max(Appointment.scheduled_at).label('last_at'),
        )
        if clinic_id:
            last_appt_query = last_appt_query.filter(Appointment.clinica_id == clinic_id)
        last_appt_subquery = last_appt_query.group_by(Appointment.tutor_id).subquery()
        tutores_query = tutores_query.outerjoin(last_appt_subquery, User.id == last_appt_subquery.c.tutor_id)
        order_columns.append(func.coalesce(last_appt_subquery.c.last_at, User.created_at).desc())
        order_columns.append(func.lower(User.name))
    elif sort_param == 'recent_added':
        order_columns.append(User.created_at.desc())
        order_columns.append(func.lower(User.name))
    else:
        order_columns.append(func.lower(User.name))

    tutores = (
        tutores_query
        .order_by(*order_columns)
        .limit(TUTOR_SEARCH_LIMIT)
        .all()
    )

    resultados = []

    for tutor in tutores:
        address_summary = (
            tutor.address
            or (tutor.endereco.full if getattr(tutor, 'endereco', None) else '')
        )
        detalhes = [
            valor
            for valor in [
                tutor.email,
                tutor.phone,
                f"CPF: {tutor.cpf}" if tutor.cpf else '',
                f"RG: {tutor.rg}" if tutor.rg else '',
                tutor.worker,
            ]
            if valor
        ]

        resultados.append(
            {
                'id': tutor.id,
                'name': tutor.name,
                'email': tutor.email,
                'cpf': tutor.cpf,
                'rg': tutor.rg,
                'phone': tutor.phone,
                'worker': tutor.worker,
                'address_summary': address_summary,
                'details': ' • '.join(detalhes),
                'specialties': ', '.join(
                    s.nome for s in tutor.veterinario.specialties
                )
                if getattr(tutor, 'veterinario', None)
                else '',
            }
        )

    if sort_param == 'name_asc':
        resultados.sort(key=lambda item: (item['name'] or '').lower())

    return jsonify(resultados)


@app.route('/clinicas')
def clinicas():
    clinicas = clinicas_do_usuario().all()
    return render_template('clinica/clinicas.html', clinicas=clinicas)


@app.route('/minha-clinica', methods=['GET', 'POST'])
@login_required
def minha_clinica():
    clinicas = clinicas_do_usuario().all()
    if not clinicas:
        form = ClinicForm()
        if form.validate_on_submit():
            clinica = Clinica(
                nome=form.nome.data,
                cnpj=form.cnpj.data,
                endereco=form.endereco.data,
                telefone=form.telefone.data,
                email=form.email.data,
                owner_id=current_user.id,
            )
            file = form.logotipo.data
            if file and getattr(file, "filename", ""):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                image_url = upload_to_s3(file, filename, folder="clinicas")
                if image_url:
                    clinica.logotipo = image_url
                    clinica.photo_rotation = form.photo_rotation.data
                    clinica.photo_zoom = form.photo_zoom.data
                    clinica.photo_offset_x = form.photo_offset_x.data
                    clinica.photo_offset_y = form.photo_offset_y.data
            db.session.add(clinica)
            db.session.commit()
            if current_user.veterinario:
                current_user.veterinario.clinica_id = clinica.id
            current_user.clinica_id = clinica.id
            db.session.commit()
            return redirect(url_for('clinic_detail', clinica_id=clinica.id))
        return render_template('clinica/create_clinic.html', form=form)

    if _is_admin() and current_user.clinica_id:
        return redirect(url_for('clinic_detail', clinica_id=current_user.clinica_id))
    if len(clinicas) == 1:
        return redirect(url_for('clinic_detail', clinica_id=clinicas[0].id))
    overview = []
    for c in clinicas:
        staff = c.veterinarios
        upcoming = (
            Appointment.query.filter_by(clinica_id=c.id)
            .filter(Appointment.scheduled_at >= datetime.utcnow())
            .order_by(Appointment.scheduled_at)
            .limit(5)
            .all()
        )
        overview.append({'clinic': c, 'staff': staff, 'appointments': upcoming})
    return render_template('clinica/multi_clinic_dashboard.html', clinics=overview)


def _user_can_manage_clinic(clinica):
    """Return True when the current user can manage the given clinic."""
    if not current_user.is_authenticated:
        return False
    if _is_admin():
        return True
    if current_user.id == clinica.owner_id:
        return True
    if is_veterinarian(current_user) and current_user.veterinario.clinica_id == clinica.id:
        return True
    return False


def _send_clinic_invite_email(clinica, veterinarian_user, inviter):
    """Send the invite email for a clinic invitation."""
    if not veterinarian_user:
        current_app.logger.warning(
            'Convite para clínica %s ignorado: veterinário sem usuário associado.',
            clinica.id,
        )
        return False

    acceptance_url = url_for('clinic_invites', _external=True)
    inviter_name = getattr(inviter, 'name', None) or 'Um membro da clínica'
    recipient_name = getattr(veterinarian_user, 'name', None) or 'veterinário(a)'
    subject = f"Convite para ingressar na clínica {clinica.nome}"
    body = (
        f"Olá {recipient_name},\n\n"
        f"{inviter_name} convidou você para ingressar na clínica {clinica.nome} na PetOrlândia.\n"
        f"Acesse {acceptance_url} para aceitar ou recusar o convite e concluir o processo.\n\n"
        "Se tiver dúvidas, responda a este e-mail ou entre em contato com a clínica.\n\n"
        "Equipe PetOrlândia"
    )
    msg = MailMessage(
        subject=subject,
        sender=app.config['MAIL_DEFAULT_SENDER'],
        recipients=[veterinarian_user.email],
        body=body,
    )
    try:
        mail.send(msg)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception('Falha ao enviar e-mail de convite da clínica: %s', exc)
        return False
    return True


@app.route('/clinica/<int:clinica_id>', methods=['GET', 'POST'])
@login_required
def clinic_detail(clinica_id):
    if _is_admin():
        clinica = Clinica.query.get_or_404(clinica_id)
    else:
        # Para usuários não administradores, garantimos que a clínica
        # consultada pertence ao conjunto de clínicas acessíveis ao
        # usuário atual. O uso de ``filter`` com ``Clinica.id`` evita
        # possíveis ambiguidades de ``filter_by`` e assegura que o
        # ``clinica_id`` da URL seja respeitado corretamente.
        clinica = (
            clinicas_do_usuario()
            .filter(Clinica.id == clinica_id)
            .first_or_404()
        )
    from models import VetClinicInvite

    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_inventory_perm = staff.can_manage_inventory if staff else False
    show_inventory = _is_admin() or is_owner or has_inventory_perm
    inventory_form = InventoryItemForm() if show_inventory else None
    inventory_items = []
    inventory_movements = []
    if show_inventory:
        _ensure_inventory_threshold_columns()
        _ensure_inventory_movement_table()
        inventory_items = (
            ClinicInventoryItem.query
            .filter_by(clinica_id=clinica.id)
            .order_by(ClinicInventoryItem.name)
            .all()
        )
        inventory_movements = (
            ClinicInventoryMovement.query
            .filter_by(clinica_id=clinica.id)
            .order_by(ClinicInventoryMovement.created_at.desc())
            .limit(10)
            .all()
        )
    hours_form = ClinicHoursForm()
    clinic_form = ClinicForm(obj=clinica)
    invite_form = ClinicInviteVeterinarianForm()
    invite_cancel_form = ClinicInviteCancelForm(prefix='cancel_invite')
    invite_resend_form = ClinicInviteResendForm(prefix='resend_invite')
    staff_form = ClinicAddStaffForm()
    specialist_form = ClinicAddSpecialistForm(prefix='specialist')
    if request.method == 'GET':
        hours_form.clinica_id.data = clinica.id
    pode_editar = _user_can_manage_clinic(clinica)
    can_view_metrics = _is_admin() or pode_editar
    if not can_view_metrics and staff:
        can_view_metrics = any(
            [
                staff.can_manage_clients,
                staff.can_manage_animals,
                staff.can_manage_schedule,
                staff.can_manage_inventory,
            ]
        )
    if staff_form.submit.data and staff_form.validate_on_submit():
        if not (_is_admin() or current_user.id == clinica.owner_id):
            abort(403)
        user = User.query.filter_by(email=staff_form.email.data).first()
        if not user:
            flash('Usuário não encontrado', 'danger')
        else:
            staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=user.id).first()
            if staff:
                flash('Funcionário já está na clínica', 'warning')
            else:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=user.id)
                db.session.add(staff)
                user.clinica_id = clinica.id
                if getattr(user, 'veterinario', None):
                    user.veterinario.clinica_id = clinica.id
                    db.session.add(user.veterinario)
                db.session.add(user)
                db.session.commit()
                flash('Funcionário adicionado. Defina as permissões.', 'success')
                return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if specialist_form.submit.data and specialist_form.validate_on_submit():
        if not (_is_admin() or current_user.id == clinica.owner_id):
            abort(403)
        email = specialist_form.email.data.strip().lower()
        user = (
            User.query
            .filter(func.lower(User.email) == email)
            .first()
        )
        vet_profile = getattr(user, 'veterinario', None) if user else None
        if not vet_profile:
            flash('Especialista não encontrado.', 'danger')
        elif vet_profile in clinica.veterinarios_associados or vet_profile.clinica_id == clinica.id:
            flash('Especialista já associado à clínica.', 'warning')
        else:
            clinica.veterinarios_associados.append(vet_profile)
            staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=user.id).first()
            if not staff:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=user.id)
                db.session.add(staff)
            db.session.commit()
            flash('Especialista associado com sucesso. Defina as permissões.', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#especialistas')

    if clinic_form.submit.data and clinic_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        original_logo = clinica.logotipo
        clinic_form.populate_obj(clinica)
        file = clinic_form.logotipo.data
        if file and getattr(file, 'filename', ''):
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            image_url = upload_to_s3(file, filename, folder="clinicas")
            if image_url:
                clinica.logotipo = image_url
        else:
            clinica.logotipo = original_logo
        db.session.commit()
        flash('Clínica atualizada com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    if invite_form.submit.data and invite_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        email = invite_form.email.data.strip().lower()
        user = (
            User.query
            .filter(func.lower(User.email) == email)
            .first()
        )
        if not user or getattr(user, 'worker', '') != 'veterinario' or not getattr(user, 'veterinario', None):
            flash('Veterinário não encontrado.', 'danger')
        else:
            existing = VetClinicInvite.query.filter_by(
                clinica_id=clinica.id,
                veterinario_id=user.veterinario.id,
                status='pending',
            ).first()
            if user.veterinario.clinica_id == clinica.id:
                flash('Veterinário já associado à clínica.', 'warning')
            elif existing:
                flash('Convite já enviado.', 'warning')
            else:
                invite = VetClinicInvite(
                    clinica_id=clinica.id,
                    veterinario_id=user.veterinario.id,
                )
                db.session.add(invite)
                db.session.commit()
                if _send_clinic_invite_email(clinica, user, current_user):
                    flash('Convite enviado.', 'success')
                else:
                    flash(
                        'Convite criado, mas houve um problema ao enviar o e-mail para o veterinário.',
                        'warning',
                    )
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')
    if hours_form.submit.data and hours_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        for dia in hours_form.dias_semana.data:
            existentes = ClinicHours.query.filter_by(
                clinica_id=hours_form.clinica_id.data, dia_semana=dia
            ).all()
            if existentes:
                existentes[0].hora_abertura = hours_form.hora_abertura.data
                existentes[0].hora_fechamento = hours_form.hora_fechamento.data
                for extra in existentes[1:]:
                    db.session.delete(extra)
            else:
                db.session.add(
                    ClinicHours(
                        clinica_id=hours_form.clinica_id.data,
                        dia_semana=dia,
                        hora_abertura=hours_form.hora_abertura.data,
                        hora_fechamento=hours_form.hora_fechamento.data,
                    )
                )
        db.session.commit()
        flash('Horário salvo com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    horarios = ClinicHours.query.filter_by(clinica_id=clinica_id).all()
    veterinarios = Veterinario.query.filter_by(clinica_id=clinica_id).all()
    associated_vets = list(clinica.veterinarios_associados)
    veterinarios_ids = {v.id for v in veterinarios}
    specialists = [
        v for v in associated_vets if v.id not in veterinarios_ids
    ]
    specialists.sort(key=lambda vet: (vet.user.name or '').lower())
    all_veterinarios = Veterinario.query.all()
    staff_members = ClinicStaff.query.filter(
        ClinicStaff.clinic_id == clinica.id,
        ClinicStaff.user.has(User.veterinario == None),
    ).all()

    clinic_invites = (
        VetClinicInvite.query
        .filter_by(clinica_id=clinica.id)
        .order_by(VetClinicInvite.created_at.desc())
        .all()
    )
    invites_by_status = defaultdict(list)
    for invite in clinic_invites:
        invites_by_status[invite.status].append(invite)
    invites_by_status = dict(invites_by_status)
    invite_status_order = ['pending', 'declined', 'accepted', 'cancelled']

    staff_permission_forms = {}
    for s in staff_members:
        form = ClinicStaffPermissionForm(prefix=f"perm_{s.user.id}", obj=s)
        staff_permission_forms[s.user.id] = form

    vets_for_forms = unique_items_by_id(veterinarios + specialists)

    vet_permission_forms = {}
    for v in vets_for_forms:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=v.user.id).first()
        if not staff:
            staff = ClinicStaff(clinic_id=clinica.id, user_id=v.user.id)
        form = ClinicStaffPermissionForm(prefix=f"vet_perm_{v.user.id}", obj=staff)
        vet_permission_forms[v.user.id] = form

    for s in staff_members:
        form = staff_permission_forms[s.user.id]
        if form.submit.data and form.validate_on_submit():
            if not (_is_admin() or current_user.id == clinica.owner_id):
                abort(403)
            form.populate_obj(s)
            s.user_id = s.user.id
            db.session.add(s)
            db.session.commit()
            flash('Permissões atualizadas', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    for v in vets_for_forms:
        form = vet_permission_forms[v.user.id]
        if form.submit.data and form.validate_on_submit():
            if not (_is_admin() or current_user.id == clinica.owner_id):
                abort(403)
            staff = ClinicStaff.query.filter_by(
                clinic_id=clinica.id, user_id=v.user.id
            ).first()
            if not staff:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=v.user.id)
            form.populate_obj(staff)
            staff.user_id = v.user.id
            db.session.add(staff)
            db.session.commit()
            flash('Permissões atualizadas', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    vet_schedule_forms = {}
    for v in vets_for_forms:
        form = VetScheduleForm(prefix=f"schedule_{v.id}")
        form.veterinario_id.choices = [(v.id, v.user.name)]
        if request.method == 'GET':
            form.veterinario_id.data = v.id
        vet_schedule_forms[v.id] = form

    for v in vets_for_forms:
        form = vet_schedule_forms[v.id]
        if form.submit.data and form.validate_on_submit():
            if not pode_editar:
                abort(403)
            for dia in form.dias_semana.data:
                db.session.add(
                    VetSchedule(
                        veterinario_id=form.veterinario_id.data,
                        dia_semana=dia,
                        hora_inicio=form.hora_inicio.data,
                        hora_fim=form.hora_fim.data,
                        intervalo_inicio=form.intervalo_inicio.data,
                        intervalo_fim=form.intervalo_fim.data,
                    )
                )
            db.session.commit()
            flash('Horário do funcionário salvo com sucesso.', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    animais_adicionados = (
        Animal.query
        .filter_by(clinica_id=clinica_id)
        .filter(Animal.removido_em == None)
        .all()
    )
    tutores_adicionados = (
        User.query
        .filter_by(clinica_id=clinica_id)
        .filter(or_(User.worker != 'veterinario', User.worker == None))
        .all()
    )

    clinic_metrics = {
        'animals': db.session.query(func.count(Animal.id))
        .filter(Animal.clinica_id == clinica_id, Animal.removido_em.is_(None))
        .scalar()
        or 0,
        'tutors': db.session.query(func.count(User.id))
        .filter(
            User.clinica_id == clinica_id,
            or_(User.worker != 'veterinario', User.worker == None),
        )
        .scalar()
        or 0,
        'future_appointments': db.session.query(func.count(Appointment.id))
        .filter(
            Appointment.clinica_id == clinica_id,
            Appointment.scheduled_at >= datetime.utcnow(),
            Appointment.status == 'scheduled',
        )
        .scalar()
        or 0,
        'open_prescriptions': db.session.query(func.count(BlocoPrescricao.id))
        .filter(BlocoPrescricao.clinica_id == clinica_id)
        .scalar()
        or 0,
    }

    valid_vet_ids = {getattr(v, 'id', None) for v in vets_for_forms if getattr(v, 'id', None)}
    appointment_vet_options = [
        {
            'id': v.id,
            'name': getattr(getattr(v, 'user', None), 'name', '') or f'Veterinário #{v.id}',
        }
        for v in sorted(vets_for_forms, key=lambda vet: (getattr(getattr(vet, 'user', None), 'name', '') or '').lower())
        if getattr(v, 'id', None)
    ]

    status_labels = dict(APPOINTMENT_STATUS_LABELS)
    kind_labels = dict(APPOINTMENT_KIND_LABELS)

    try:
        appointment_kind_choices = AppointmentForm().kind.choices
    except Exception:  # noqa: BLE001
        appointment_kind_choices = []

    for value, label in appointment_kind_choices:
        if value:
            kind_labels.setdefault(value, label)

    clinic_status_values = {
        status
        for (status,) in (
            db.session.query(Appointment.status)
            .filter(Appointment.clinica_id == clinica_id)
            .distinct()
        )
        if status
    }
    clinic_kind_values = {
        kind
        for (kind,) in (
            db.session.query(Appointment.kind)
            .filter(Appointment.clinica_id == clinica_id)
            .distinct()
        )
        if kind
    }

    for status in clinic_status_values:
        status_labels.setdefault(status, status.replace('_', ' ').title())

    for kind in clinic_kind_values:
        kind_labels.setdefault(kind, kind.replace('_', ' ').title())

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    vet_filter_id = request.args.get('vet_id', type=int)
    status_filter = (request.args.get('status') or '').strip()
    type_filter = (request.args.get('type') or '').strip()

    if vet_filter_id and vet_filter_id not in valid_vet_ids:
        vet_filter_id = None
    if status_filter and status_filter not in status_labels:
        status_filter = ''
    if type_filter and type_filter not in kind_labels:
        type_filter = ''
    start_dt = None
    end_dt = None
    if start_str:
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        except ValueError:
            start_dt = None
    if end_str:
        try:
            end_dt = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            end_dt = None

    start_dt_utc, end_dt_utc = local_date_range_to_utc(start_dt, end_dt)

    appointments_query = Appointment.query.filter_by(clinica_id=clinica_id)
    if start_dt_utc:
        appointments_query = appointments_query.filter(Appointment.scheduled_at >= start_dt_utc)
    if end_dt_utc:
        appointments_query = appointments_query.filter(Appointment.scheduled_at < end_dt_utc)
    if vet_filter_id:
        appointments_query = appointments_query.filter(Appointment.veterinario_id == vet_filter_id)
    if status_filter:
        appointments_query = appointments_query.filter(Appointment.status == status_filter)
    if type_filter:
        appointments_query = appointments_query.filter(Appointment.kind == type_filter)

    appointments = appointments_query.order_by(Appointment.scheduled_at).all()
    appointments_grouped = group_appointments_by_day(appointments)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template(
            "partials/appointments_table.html",
            appointments_grouped=appointments_grouped,
        )

    grouped_vet_schedules = {
        v.id: group_vet_schedules_by_day(v.horarios)
        for v in vets_for_forms
    }

    orcamento_search = (request.args.get('orcamento_search') or '').strip()
    orcamento_status_filter = request.args.get('orcamento_status') or 'all'
    orcamento_from_str = request.args.get('orcamento_from') or ''
    orcamento_to_str = request.args.get('orcamento_to') or ''
    orcamento_page = request.args.get('orcamento_page', type=int) or 1
    orcamento_page = max(1, orcamento_page)

    orcamentos_query = (
        Orcamento.query.options(
            joinedload(Orcamento.consulta)
            .joinedload(Consulta.animal)
            .joinedload(Animal.owner)
        )
        .filter(Orcamento.clinica_id == clinica_id)
    )

    if orcamento_status_filter and orcamento_status_filter != 'all':
        orcamentos_query = orcamentos_query.filter(Orcamento.status == orcamento_status_filter)

    if orcamento_search:
        like_term = f"%{orcamento_search}%"
        orcamentos_query = (
            orcamentos_query.outerjoin(Consulta, Orcamento.consulta)
            .outerjoin(Animal, Consulta.animal)
            .outerjoin(User, Animal.owner)
            .filter(
                or_(
                    Orcamento.descricao.ilike(like_term),
                    Animal.name.ilike(like_term),
                    User.name.ilike(like_term),
                )
            )
        )

    def _parse_date(date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return None

    date_from = _parse_date(orcamento_from_str)
    date_to = _parse_date(orcamento_to_str)
    if date_to:
        date_to = date_to + timedelta(days=1)

    if date_from:
        orcamentos_query = orcamentos_query.filter(Orcamento.updated_at >= date_from)
    if date_to:
        orcamentos_query = orcamentos_query.filter(Orcamento.updated_at < date_to)

    if orcamento_search:
        orcamentos_query = orcamentos_query.distinct()

    per_page = current_app.config.get('ORCAMENTOS_PER_PAGE', 10)
    orcamentos_pagination = (
        orcamentos_query
        .order_by(Orcamento.updated_at.desc())
        .paginate(page=orcamento_page, per_page=per_page, error_out=False)
    )

    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    next7_str = (today + timedelta(days=7)).strftime('%Y-%m-%d')
    now_dt = datetime.utcnow()

    try:
        clinic_new_animal_url = url_for('criar_animal', clinica_id=clinica.id)
    except BuildError:
        clinic_new_animal_url = url_for('novo_animal')

    appointment_filters = {
        'start': start_str or '',
        'end': end_str or '',
        'vet_id': str(vet_filter_id) if vet_filter_id else '',
        'status': status_filter,
        'type': type_filter,
    }

    def _normalize_filter_value(value):
        if value in (None, ''):
            return ''
        return str(value)

    def _is_active_for_query(query):
        for key, value in query.items():
            normalized = _normalize_filter_value(value)
            current = appointment_filters.get(key) or ''
            if normalized == '':
                if current not in ('', None):
                    return False
            elif current != normalized:
                return False
        return True

    def _build_filter_url(**overrides):
        params = {k: v for k, v in appointment_filters.items() if v not in ('', None)}
        for key, value in overrides.items():
            normalized_value = _normalize_filter_value(value)
            if normalized_value == '':
                params.pop(key, None)
            else:
                params[key] = normalized_value
        return url_for('clinic_detail', clinica_id=clinica.id, **params)

    def _build_quick_entry(label, query, icon=None):
        normalized_query = {k: _normalize_filter_value(v) for k, v in query.items()}
        return {
            'label': label,
            'icon': icon,
            'query': normalized_query,
            'url': _build_filter_url(**query),
            'active': _is_active_for_query(query),
        }

    appointment_status_options = [
        {'value': '', 'label': 'Todos os status'},
        *[
            {'value': key, 'label': label}
            for key, label in sorted(status_labels.items(), key=lambda item: item[1])
        ],
    ]

    appointment_type_options = [
        {'value': '', 'label': 'Todos os tipos'},
        *[
            {'value': key, 'label': label}
            for key, label in sorted(kind_labels.items(), key=lambda item: item[1])
        ],
    ]

    appointment_quick_ranges = [
        _build_quick_entry(
            'Hoje',
            {'start': today_str, 'end': today_str},
            icon='fa-solid fa-calendar-day',
        ),
        _build_quick_entry(
            'Próximos 7 dias',
            {'start': today_str, 'end': next7_str},
            icon='fa-solid fa-calendar-week',
        ),
        _build_quick_entry(
            'Todos os períodos',
            {'start': '', 'end': ''},
            icon='fa-solid fa-infinity',
        ),
    ]

    appointment_status_quick_filters = [
        _build_quick_entry('Todos os status', {'status': ''}),
        *[
            _build_quick_entry(label, {'status': key})
            for key, label in sorted(status_labels.items(), key=lambda item: item[1])
        ],
    ]

    appointment_type_quick_filters = [
        _build_quick_entry('Todos os tipos', {'type': ''}),
        *[
            _build_quick_entry(label, {'type': key})
            for key, label in sorted(kind_labels.items(), key=lambda item: item[1])
        ],
    ]

    return render_template(
        'clinica/clinic_detail.html',
        clinica=clinica,
        horarios=horarios,
        form=hours_form,
        clinic_form=clinic_form,
        invite_form=invite_form,
        invite_cancel_form=invite_cancel_form,
        invite_resend_form=invite_resend_form,
        veterinarios=veterinarios,
        all_veterinarios=all_veterinarios,
        vet_schedule_forms=vet_schedule_forms,
        staff_members=staff_members,
        staff_form=staff_form,
        specialists=specialists,
        specialist_form=specialist_form,
        staff_permission_forms=staff_permission_forms,
        vet_permission_forms=vet_permission_forms,
        appointments=appointments,
        appointments_grouped=appointments_grouped,
        grouped_vet_schedules=grouped_vet_schedules,
        orcamentos=orcamentos_pagination.items,
        orcamentos_pagination=orcamentos_pagination,
        orcamento_filters={
            'search': orcamento_search,
            'status': orcamento_status_filter,
            'from': orcamento_from_str,
            'to': orcamento_to_str,
        },
        orcamento_status_labels=ORCAMENTO_STATUS_LABELS,
        orcamento_status_styles=ORCAMENTO_STATUS_STYLES,
        pode_editar=pode_editar,
        animais_adicionados=animais_adicionados,
        tutores_adicionados=tutores_adicionados,
        pagination=None,
        start=start_str,
        end=end_str,
        appointment_filters=appointment_filters,
        appointment_vet_options=appointment_vet_options,
        appointment_status_options=appointment_status_options,
        appointment_type_options=appointment_type_options,
        appointment_quick_ranges=appointment_quick_ranges,
        appointment_status_quick_filters=appointment_status_quick_filters,
        appointment_type_quick_filters=appointment_type_quick_filters,
        today_str=today_str,
        next7_str=next7_str,
        now=now_dt,
        inventory_items=inventory_items,
        inventory_movements=inventory_movements,
        inventory_form=inventory_form,
        show_inventory=show_inventory,
        clinic_metrics=clinic_metrics,
        show_clinic_metrics=can_view_metrics,
        invites_by_status=invites_by_status,
        invite_status_order=invite_status_order,
        clinic_new_animal_url=clinic_new_animal_url,
    )


@app.route('/clinica/<int:clinica_id>/convites/<int:invite_id>/cancel', methods=['POST'])
@login_required
def cancel_clinic_invite(clinica_id, invite_id):
    """Cancel a pending clinic invite."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.clinica_id != clinica.id:
        abort(404)

    form = ClinicInviteCancelForm()
    if not form.validate_on_submit():
        abort(400)

    if invite.status != 'pending':
        flash('Somente convites pendentes podem ser cancelados.', 'warning')
    else:
        invite.status = 'cancelled'
        db.session.commit()
        flash('Convite cancelado.', 'success')

    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@app.route('/clinica/<int:clinica_id>/convites/<int:invite_id>/resend', methods=['POST'])
@login_required
def resend_clinic_invite(clinica_id, invite_id):
    """Resend a declined clinic invite."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.clinica_id != clinica.id:
        abort(404)

    form = ClinicInviteResendForm()
    if not form.validate_on_submit():
        abort(400)

    if invite.status != 'declined':
        flash('Apenas convites recusados podem ser reenviados.', 'warning')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    invite.status = 'pending'
    invite.created_at = datetime.utcnow()
    db.session.commit()

    vet_user = invite.veterinario.user if invite.veterinario else None
    if _send_clinic_invite_email(clinica, vet_user, current_user):
        flash('Convite reenviado.', 'success')
    else:
        flash('Convite reativado, mas houve um problema ao reenviar o e-mail.', 'warning')

    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@app.route('/clinica/<int:clinica_id>/veterinario', methods=['POST'])
@login_required
def create_clinic_veterinario(clinica_id):
    """Create a new veterinarian linked to a clinic."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    crmv = request.form.get('crmv', '').strip()

    if not name or not email or not crmv:
        flash('Nome, e-mail e CRMV são obrigatórios.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if User.query.filter_by(email=email).first():
        flash('E-mail já cadastrado.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if Veterinario.query.filter_by(crmv=crmv).first():
        flash('CRMV já cadastrado.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    password = uuid.uuid4().hex[:8]
    user = User(
        name=name,
        email=email,
        worker='veterinario',
        is_private=True,
        added_by=current_user,
    )
    user.set_password(password)
    user.clinica_id = clinica.id
    db.session.add(user)

    veterinario = Veterinario(user=user, crmv=crmv, clinica=clinica)
    db.session.add(veterinario)

    db.session.add(ClinicStaff(clinic_id=clinica.id, user=user))
    db.session.commit()

    flash('Veterinário cadastrado com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@app.route('/convites/clinica', methods=['GET', 'POST'])
@login_required
def clinic_invites():
    """List pending clinic invitations for the logged veterinarian."""
    from models import Veterinario

    if getattr(current_user, "worker", None) != "veterinario":
        abort(403)

    response_form = ClinicInviteResponseForm()
    profile_form = VeterinarianProfileForm()

    vet_profile = getattr(current_user, "veterinario", None)
    anchor_redirect = redirect(url_for('mensagens', _anchor='convites-clinica'))

    if request.method == 'GET':
        return anchor_redirect

    if vet_profile is None:
        if profile_form.validate_on_submit():
            crmv = profile_form.crmv.data
            existing = (
                Veterinario.query.filter(
                    func.lower(Veterinario.crmv) == crmv.lower(),
                    Veterinario.user_id != current_user.id,
                ).first()
            )
            if existing:
                profile_form.crmv.errors.append('Este CRMV já está cadastrado.')
            else:
                vet = Veterinario(user=current_user, crmv=crmv)
                phone = profile_form.phone.data
                if phone:
                    current_user.phone = phone
                db.session.add(vet)
                db.session.commit()
                flash('Cadastro de veterinário concluído com sucesso!', 'success')
                return anchor_redirect
        return _render_messages_page(
            clinic_invite_form=response_form,
            vet_profile_form=profile_form,
            missing_vet_profile=True,
        )

    return anchor_redirect


@app.route('/convites/<int:invite_id>/<string:action>', methods=['POST'])
@login_required
def respond_clinic_invite(invite_id, action):
    """Accept or decline a clinic invitation."""
    from models import VetClinicInvite

    vet_profile, response = _ensure_veterinarian_profile()
    if response is not None:
        return response

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.veterinario_id != vet_profile.id:
        abort(403)
    if action == 'accept':
        invite.status = 'accepted'
        vet = invite.veterinario
        vet.clinica_id = invite.clinica_id
        if vet.user:
            vet.user.clinica_id = invite.clinica_id
            staff = ClinicStaff.query.filter_by(
                clinic_id=invite.clinica_id, user_id=vet.user.id
            ).first()
            if not staff:
                db.session.add(ClinicStaff(clinic_id=invite.clinica_id, user_id=vet.user.id))
        flash('Convite aceito.', 'success')
    else:
        invite.status = 'declined'
        flash('Convite recusado.', 'info')
    db.session.commit()
    return redirect(url_for('clinic_invites'))


@app.route('/clinica/<int:clinica_id>/estoque', methods=['GET', 'POST'])
@login_required
def clinic_stock(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_perm = staff.can_manage_inventory if staff else False
    if not (_is_admin() or is_owner or has_perm):
        abort(403)

    inventory_form = InventoryItemForm()
    if inventory_form.validate_on_submit():
        min_qty = inventory_form.min_quantity.data
        max_qty = inventory_form.max_quantity.data
        item = ClinicInventoryItem(
            clinica_id=clinica.id,
            name=inventory_form.name.data,
            quantity=inventory_form.quantity.data,
            unit=inventory_form.unit.data,
            min_quantity=min_qty,
            max_quantity=max_qty,
        )
        db.session.add(item)
        if item.quantity:
            db.session.add(
                ClinicInventoryMovement(
                    clinica_id=clinica.id,
                    item=item,
                    quantity_change=item.quantity,
                    quantity_before=0,
                    quantity_after=item.quantity,
                )
            )
        db.session.commit()
        flash('Item adicionado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')

    inventory_items = (
        ClinicInventoryItem.query
        .filter_by(clinica_id=clinica.id)
        .order_by(ClinicInventoryItem.name)
        .all()
    )
    inventory_movements = (
        ClinicInventoryMovement.query
        .filter_by(clinica_id=clinica.id)
        .order_by(ClinicInventoryMovement.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        'clinica/clinic_stock.html',
        clinica=clinica,
        inventory_items=inventory_items,
        inventory_movements=inventory_movements,
        inventory_form=inventory_form,
    )


@app.route('/estoque/item/<int:item_id>/atualizar', methods=['POST'])
@login_required
def update_inventory_item(item_id):
    item = ClinicInventoryItem.query.get_or_404(item_id)
    clinica = item.clinica
    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_perm = staff.can_manage_inventory if staff else False
    if not (_is_admin() or is_owner or has_perm):
        abort(403)
    def _optional_nonnegative_int(value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None

    wants_json = 'application/json' in request.headers.get('Accept', '')

    old_quantity = item.quantity
    qty = _optional_nonnegative_int(request.form.get('quantity'))
    if qty is None:
        qty = old_quantity
    item.quantity = qty

    new_min = _optional_nonnegative_int(request.form.get('min_quantity'))
    new_max = _optional_nonnegative_int(request.form.get('max_quantity'))

    if new_min is not None and new_max is not None and new_min > new_max:
        message = 'O máximo deve ser maior ou igual ao mínimo.'
        category = 'warning'
        flash(message, category)
        if wants_json:
            return jsonify(success=False, message=message, category=category), 400
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')

    item.min_quantity = new_min
    item.max_quantity = new_max

    if item.quantity != old_quantity:
        db.session.add(
            ClinicInventoryMovement(
                clinica_id=clinica.id,
                item=item,
                quantity_change=item.quantity - old_quantity,
                quantity_before=old_quantity,
                quantity_after=item.quantity,
            )
        )

    db.session.commit()
    message = 'Item atualizado.'
    flash(message, 'success')
    if wants_json:
        return jsonify(success=True, message=message, category='success', quantity=item.quantity)
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')


@app.route('/clinica/<int:clinica_id>/novo_orcamento', methods=['GET', 'POST'])
@login_required
def novo_orcamento(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if current_user.clinica_id != clinica_id and not _is_admin():
        abort(403)
    form = OrcamentoForm()
    if form.validate_on_submit():
        o = Orcamento(clinica_id=clinica_id, descricao=form.descricao.data)
        db.session.add(o)
        db.session.commit()
        flash('Orçamento criado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica_id) + '#orcamento')
    return render_template('orcamentos/orcamento_form.html', form=form, clinica=clinica)


@app.route('/orcamento/<int:orcamento_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    if current_user.clinica_id != orcamento.clinica_id and not _is_admin():
        abort(403)
    form = OrcamentoForm(obj=orcamento)
    if form.validate_on_submit():
        orcamento.descricao = form.descricao.data
        db.session.commit()
        flash('Orçamento atualizado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=orcamento.clinica_id) + '#orcamento')
    return render_template('orcamentos/orcamento_form.html', form=form, clinica=orcamento.clinica)


@app.route('/orcamento/<int:orcamento_id>/enviar', methods=['POST'])
@login_required
def enviar_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    ensure_clinic_access(orcamento.clinica_id)

    channel = (request.form.get('channel') or '').lower()
    if channel not in {'email', 'whatsapp'}:
        abort(400)

    redirect_url = request.referrer or url_for('clinic_detail', clinica_id=orcamento.clinica_id) + '#orcamento'
    consulta = orcamento.consulta
    tutor = consulta.animal.owner if consulta else None
    if not tutor:
        flash('O orçamento precisa estar vinculado a uma consulta para envio automático.', 'warning')
        return redirect(redirect_url)

    link = url_for('imprimir_orcamento', consulta_id=consulta.id, _external=True)
    animal = consulta.animal
    tutor_nome = getattr(tutor, 'name', 'tutor')
    animal_nome = getattr(animal, 'name', 'pet')
    mensagem = f"Olá {tutor_nome}! Segue o orçamento para {animal_nome}: {link}"

    if channel == 'email':
        if not tutor.email:
            flash('O tutor não possui e-mail cadastrado.', 'warning')
            return redirect(redirect_url)
        msg = MailMessage(
            subject=f'Orçamento para {animal_nome}',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[tutor.email],
            body=mensagem,
        )
        try:
            mail.send(msg)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception('Falha ao enviar orçamento por e-mail: %s', exc)
            flash('Não foi possível enviar o e-mail. Tente novamente.', 'danger')
            return redirect(redirect_url)
        orcamento.email_sent_count = (orcamento.email_sent_count or 0) + 1
    else:
        if not tutor.phone:
            flash('O tutor não possui telefone cadastrado.', 'warning')
            return redirect(redirect_url)
        numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
        try:
            enviar_mensagem_whatsapp(mensagem, numero)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception('Falha ao enviar orçamento por WhatsApp: %s', exc)
            flash('Não foi possível enviar via WhatsApp. Verifique as credenciais do Twilio.', 'danger')
            return redirect(redirect_url)
        orcamento.whatsapp_sent_count = (orcamento.whatsapp_sent_count or 0) + 1

    if orcamento.status == 'draft':
        orcamento.status = 'sent'
    db.session.add(orcamento)
    db.session.commit()
    flash('Orçamento enviado com sucesso!', 'success')
    return redirect(redirect_url)


@app.route('/clinica/<int:clinica_id>/orcamentos')
@login_required
def orcamentos(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if current_user.clinica_id != clinica_id and not _is_admin():
        abort(403)
    lista = Orcamento.query.filter_by(clinica_id=clinica_id).all()
    return render_template('orcamentos/orcamentos.html', clinica=clinica, orcamentos=lista)


@app.route('/dashboard/orcamentos')
@login_required
def dashboard_orcamentos():
    from collections import defaultdict
    from admin import _is_admin
    from models import (
        Animal,
        Clinica,
        Consulta,
        Orcamento,
        Payment,
        PaymentStatus,
    )

    is_admin = _is_admin()
    requested_scope = request.args.get('scope', 'clinic')
    requested_clinic_id = request.args.get('clinica_id', type=int)

    if requested_scope == 'all' and not is_admin:
        abort(403)

    accessible_clinic_ids = _collect_clinic_ids()
    default_clinic_id = current_user_clinic_id()

    selected_clinic_id = None
    is_global_scope = False

    if is_admin:
        if requested_scope == 'all':
            is_global_scope = True
        elif requested_clinic_id:
            selected_clinic_id = requested_clinic_id
        elif default_clinic_id:
            selected_clinic_id = default_clinic_id
        else:
            is_global_scope = True
    else:
        if requested_clinic_id and requested_clinic_id not in accessible_clinic_ids:
            abort(403)
        selected_clinic_id = requested_clinic_id or default_clinic_id
        if not selected_clinic_id and accessible_clinic_ids:
            selected_clinic_id = sorted(accessible_clinic_ids)[0]
        if not selected_clinic_id:
            abort(403)

    consulta_query = (
        Consulta.query.options(
            joinedload(Consulta.animal).joinedload(Animal.owner),
        )
        .filter(Consulta.orcamento_items.any())
    )
    if not is_global_scope:
        consulta_query = consulta_query.filter(Consulta.clinica_id == selected_clinic_id)
    consultas = consulta_query.all()

    consulta_refs = {f'consulta-{consulta.id}' for consulta in consultas}
    pagamentos_concluidos = {}
    if consulta_refs:
        pagamentos_concluidos = {
            pagamento.external_reference: pagamento
            for pagamento in Payment.query.filter(
                Payment.external_reference.in_(consulta_refs),
                Payment.status == PaymentStatus.COMPLETED,
            )
        }

    dados_consultas = []
    total_por_cliente = defaultdict(lambda: {'total': 0.0, 'pagos': 0.0, 'pendentes': 0.0})
    total_por_animal = defaultdict(lambda: {'total': 0.0, 'pagos': 0.0, 'pendentes': 0.0})

    for consulta in consultas:
        cliente_nome = (
            consulta.animal.owner.name
            if consulta.animal and consulta.animal.owner
            else 'N/A'
        )
        animal_nome = consulta.animal.name if consulta.animal else 'N/A'
        total = float(consulta.total_orcamento or 0)
        pago = pagamentos_concluidos.get(f'consulta-{consulta.id}') is not None
        status = 'Pago' if pago else 'Pendente'

        dados_consultas.append(
            {
                'cliente': cliente_nome,
                'animal': animal_nome,
                'total': total,
                'status': status,
            }
        )

        total_por_cliente[cliente_nome]['total'] += total
        total_por_animal[animal_nome]['total'] += total
        if pago:
            total_por_cliente[cliente_nome]['pagos'] += total
            total_por_animal[animal_nome]['pagos'] += total
        else:
            total_por_cliente[cliente_nome]['pendentes'] += total
            total_por_animal[animal_nome]['pendentes'] += total

    orcamento_query = Orcamento.query.options(joinedload(Orcamento.clinica))
    if not is_global_scope:
        orcamento_query = orcamento_query.filter(Orcamento.clinica_id == selected_clinic_id)
    dados_orcamentos = [
        {
            'descricao': o.descricao,
            'total': float(o.total or 0),
            'clinica': o.clinica.nome if o.clinica else 'N/A',
        }
        for o in orcamento_query.all()
    ]

    total_emitido = sum(orcamento['total'] for orcamento in dados_orcamentos)
    total_aprovado = sum(
        consulta['total'] for consulta in dados_consultas if consulta['status'] == 'Pago'
    )
    total_pendente = sum(
        consulta['total'] for consulta in dados_consultas if consulta['status'] != 'Pago'
    )

    clinic_options = []
    if is_admin:
        clinic_options = Clinica.query.order_by(Clinica.nome).all()
    elif accessible_clinic_ids:
        clinic_options = (
            Clinica.query.filter(Clinica.id.in_(accessible_clinic_ids))
            .order_by(Clinica.nome)
            .all()
        )

    selected_clinic = (
        Clinica.query.get(selected_clinic_id) if selected_clinic_id else None
    )

    return render_template(
        'orcamentos/dashboard_orcamentos.html',
        consultas=dados_consultas,
        clientes=total_por_cliente,
        animais=total_por_animal,
        orcamentos=dados_orcamentos,
        is_admin=is_admin,
        clinic_options=clinic_options,
        selected_clinic=selected_clinic,
        selected_clinic_id=selected_clinic_id,
        selected_scope='all' if is_global_scope else 'clinic',
        is_global_scope=is_global_scope,
        total_emitido=total_emitido,
        total_aprovado=total_aprovado,
        total_pendente=total_pendente,
    )


@app.route('/clinica/<int:clinica_id>/dashboard')
@login_required
def clinic_dashboard(clinica_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id == clinic.owner_id:
        staff = ClinicStaff(
            clinic_id=clinic.id,
            user_id=current_user.id,
            can_manage_clients=True,
            can_manage_animals=True,
            can_manage_staff=True,
            can_manage_schedule=True,
            can_manage_inventory=True,
        )
    else:
        staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=current_user.id).first()
        if not staff:
            abort(403)
    return render_template('clinica/clinic_dashboard.html', clinic=clinic, staff=staff)


@app.route('/clinica/<int:clinica_id>/funcionarios', methods=['GET', 'POST'])
@login_required
def clinic_staff(clinica_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id != clinic.owner_id:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Sem permissão'), 403
        abort(403)
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if not user:
            if request.accept_mimetypes.accept_json:
                return jsonify(success=False, message='Usuário não encontrado'), 404
            flash('Usuário não encontrado', 'danger')
        else:
            staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=user.id).first()
            if staff:
                if request.accept_mimetypes.accept_json:
                    return jsonify(success=False, message='Funcionário já está na clínica'), 400
                flash('Funcionário já está na clínica', 'warning')
            else:
                staff = ClinicStaff(clinic_id=clinic.id, user_id=user.id)
                db.session.add(staff)
                user.clinica_id = clinic.id
                if has_veterinarian_profile(user):
                    vet_profile = user.veterinario
                    vet_profile.clinica_id = clinic.id
                    # Garanta que o veterinário tenha uma assinatura ou período
                    # de testes ativo para acessar as agendas da clínica.
                    ensure_veterinarian_membership(vet_profile)
                    db.session.add(vet_profile)
                elif getattr(user, "worker", None) is None:
                    # Garanta que colaboradores recém-adicionados apareçam nas visões
                    # de agenda que dependem do papel ``colaborador``.
                    user.worker = "colaborador"
                db.session.add(user)
                db.session.commit()
                if request.accept_mimetypes.accept_json:
                    staff_members = ClinicStaff.query.filter_by(clinic_id=clinic.id).all()
                    staff_permission_forms = {}
                    for staff_member in staff_members:
                        staff_permission_forms[staff_member.user.id] = ClinicStaffPermissionForm(
                            prefix=f"perm_{staff_member.user.id}", obj=staff_member
                        )
                    html = render_template(
                        'partials/clinic_staff_rows.html',
                        clinic=clinic,
                        staff_members=staff_members,
                        staff_permission_forms=staff_permission_forms,
                    )
                    return jsonify(success=True, html=html, message='Funcionário adicionado', category='success')
                flash('Funcionário adicionado. Defina as permissões.', 'success')
                return redirect(url_for('clinic_staff_permissions', clinica_id=clinic.id, user_id=user.id))
    staff_members = ClinicStaff.query.filter_by(clinic_id=clinic.id).all()
    staff_permission_forms = {}
    for s in staff_members:
        staff_permission_forms[s.user.id] = ClinicStaffPermissionForm(
            prefix=f"perm_{s.user.id}", obj=s
        )
    if request.accept_mimetypes.accept_json:
        html = render_template(
            'partials/clinic_staff_rows.html',
            clinic=clinic,
            staff_members=staff_members,
            staff_permission_forms=staff_permission_forms,
        )
        return jsonify(success=True, html=html)
    return render_template(
        'clinica/clinic_staff_list.html',
        clinic=clinic,
        staff_members=staff_members,
        staff_permission_forms=staff_permission_forms,
    )


@app.route('/clinica/<int:clinica_id>/funcionario/<int:user_id>/permissoes', methods=['GET', 'POST'])
@login_required
def clinic_staff_permissions(clinica_id, user_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id != clinic.owner_id:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Sem permissão'), 403
        abort(403)
    user = User.query.get(user_id)
    if not user:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Usuário não encontrado'), 404
        abort(404)
    staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=user_id).first()
    if not staff:
        staff = ClinicStaff(clinic_id=clinic.id, user_id=user_id)
    form = ClinicStaffPermissionForm(obj=staff)
    if form.validate_on_submit():
        form.populate_obj(staff)
        staff.user_id = user_id
        db.session.add(staff)
        user.clinica_id = clinic.id
        db.session.add(user)
        db.session.commit()
        if request.accept_mimetypes.accept_json:
            html = render_template('partials/clinic_staff_permissions_form.html', form=form, clinic=clinic)
            return jsonify(success=True, html=html, message='Permissões atualizadas', category='success')
        flash('Permissões atualizadas', 'success')
        return redirect(url_for('clinic_dashboard', clinica_id=clinic.id))
    if request.accept_mimetypes.accept_json:
        html = render_template('partials/clinic_staff_permissions_form.html', form=form, clinic=clinic)
        return jsonify(success=True, html=html)
    return render_template('clinica/clinic_staff_permissions.html', form=form, clinic=clinic)


@app.route('/clinica/<int:clinica_id>/funcionario/<int:user_id>/remove', methods=['POST'])
@login_required
def remove_funcionario(clinica_id, user_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    staff = ClinicStaff.query.filter_by(clinic_id=clinica_id, user_id=user_id).first_or_404()
    db.session.delete(staff)
    user = User.query.get(user_id)
    if user and user.clinica_id == clinica_id:
        user.clinica_id = None
        if has_veterinarian_profile(user):
            user.veterinario.clinica_id = None
            db.session.add(user.veterinario)
        db.session.add(user)
    db.session.commit()
    flash('Funcionário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/clinica/<int:clinica_id>/horario/<int:horario_id>/delete', methods=['POST'])
@login_required
def delete_clinic_hour(clinica_id, horario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    pode_editar = _is_admin() or (
        is_veterinarian(current_user)
        and current_user.veterinario.clinica_id == clinica_id
    ) or current_user.id == clinica.owner_id
    if not pode_editar:
        abort(403)
    horario = ClinicHours.query.filter_by(id=horario_id, clinica_id=clinica_id).first_or_404()
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/remove', methods=['POST'])
@login_required
def remove_veterinario(clinica_id, veterinario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    vet = Veterinario.query.filter_by(id=veterinario_id, clinica_id=clinica_id).first_or_404()
    vet.clinica_id = None
    if vet.user:
        # Remove clinic association and staff permissions for this user
        vet.user.clinica_id = None
        ClinicStaff.query.filter_by(
            clinic_id=clinica_id, user_id=vet.user.id
        ).delete()
    db.session.commit()
    flash('Funcionário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/clinica/<int:clinica_id>/especialista/<int:veterinario_id>/remove', methods=['POST'])
@login_required
def remove_specialist(clinica_id, veterinario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    vet = Veterinario.query.get_or_404(veterinario_id)
    if vet not in clinica.veterinarios_associados:
        abort(404)
    clinica.veterinarios_associados.remove(vet)
    staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=vet.user_id).first()
    if staff and vet.clinica_id != clinica.id:
        db.session.delete(staff)
    db.session.commit()
    flash('Especialista removido da clínica.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id) + '#especialistas')


@app.route(
    '/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/schedule/<int:horario_id>/delete',
    methods=['POST'],
)
@login_required
def delete_vet_schedule_clinic(clinica_id, veterinario_id, horario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    horario = VetSchedule.query.get_or_404(horario_id)
    vet = horario.veterinario
    if vet.id != veterinario_id:
        abort(404)
    if vet.clinica_id != clinica_id and vet not in clinica.veterinarios_associados:
        abort(404)
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@app.route('/veterinarios')
def veterinarios():
    veterinarios = Veterinario.query.all()
    return render_template('veterinarios/veterinarios.html', veterinarios=veterinarios)


@app.route('/veterinario/<int:veterinario_id>')
def vet_detail(veterinario_id):
    from models import Animal, User  # import local para evitar ciclos

    veterinario = Veterinario.query.get_or_404(veterinario_id)
    calendar_access_scope = get_calendar_access_scope(current_user)
    horarios = (
        VetSchedule.query.filter_by(veterinario_id=veterinario_id)
        .order_by(VetSchedule.dia_semana, VetSchedule.hora_inicio)
        .all()
    )

    schedule_form = VetScheduleForm(prefix='schedule')
    appointment_form = AppointmentForm(
        is_veterinario=True,
        clinic_ids=[veterinario.clinica_id] if veterinario.clinica_id else None,
        prefix='appointment',
    )
    admin_default_selection_value = ''

    if current_user.is_authenticated and current_user.role == 'admin':
        agenda_veterinarios = (
            Veterinario.query.join(User).order_by(User.name).all()
        )
        agenda_colaboradores = (
            User.query.filter(User.worker == 'colaborador')
            .order_by(User.name)
            .all()
        )
        vet_choices = [(v.id, v.user.name) for v in agenda_veterinarios]
        admin_selected_view = 'veterinario'
        admin_selected_veterinario_id = veterinario.id
        admin_selected_colaborador_id = None
        default_vet = getattr(current_user, 'veterinario', None)
        if default_vet and getattr(default_vet, 'id', None):
            admin_default_selection_value = f'veterinario:{default_vet.id}'
        else:
            admin_default_selection_value = f'veterinario:{veterinario.id}'
    else:
        agenda_veterinarios = []
        agenda_colaboradores = []
        vet_choices = [(veterinario.id, veterinario.user.name)]
        admin_selected_view = None
        admin_selected_veterinario_id = None
        admin_selected_colaborador_id = None

    schedule_form.veterinario_id.choices = vet_choices
    schedule_form.veterinario_id.data = veterinario.id

    appointment_form.veterinario_id.choices = [
        (veterinario.id, veterinario.user.name)
    ]
    appointment_form.veterinario_id.data = veterinario.id

    weekday_order = {
        'Segunda': 0,
        'Terça': 1,
        'Quarta': 2,
        'Quinta': 3,
        'Sexta': 4,
        'Sábado': 5,
        'Domingo': 6,
    }
    horarios.sort(key=lambda h: weekday_order.get(h.dia_semana, 7))
    horarios_grouped = []
    for horario in horarios:
        if not horarios_grouped or horarios_grouped[-1]['dia'] != horario.dia_semana:
            horarios_grouped.append({'dia': horario.dia_semana, 'itens': []})
        horarios_grouped[-1]['itens'].append(horario)

    calendar_redirect_url = url_for(
        'appointments', view_as='veterinario', veterinario_id=veterinario.id
    )
    calendar_summary_vets = []
    calendar_summary_clinic_ids = []

    def build_calendar_summary_entry(vet, *, label=None, is_specialist=None):
        """Return a serializable mapping with vet summary metadata."""
        if not vet:
            return None
        vet_id = getattr(vet, 'id', None)
        if not vet_id:
            return None
        clinic_ids = calendar_access_scope.get_veterinarian_clinic_ids(vet)
        vet_user = getattr(vet, 'user', None)
        vet_name = getattr(vet_user, 'name', None)
        specialty_list = getattr(vet, 'specialty_list', None)
        entry = {
            'id': vet_id,
            'name': label if label is not None else vet_name,
            'full_name': vet_name,
            'specialty_list': specialty_list,
            'clinic_ids': clinic_ids,
        }
        if label is not None:
            entry['label'] = label
        if is_specialist is None:
            is_specialist = bool(specialty_list)
        entry['is_specialist'] = bool(is_specialist)
        return entry

    def add_summary_vet(vet, *, label=None, is_specialist=None):
        if not vet:
            return
        vet_id = getattr(vet, 'id', None)
        if not vet_id:
            return
        if any(entry.get('id') == vet_id for entry in calendar_summary_vets):
            return
        if not calendar_access_scope.allows_veterinarian(vet):
            return
        entry = build_calendar_summary_entry(vet, label=label, is_specialist=is_specialist)
        if entry:
            calendar_summary_vets.append(entry)

    add_summary_vet(veterinario)

    clinic_ids = set()

    primary_clinic_id = getattr(veterinario, 'clinica_id', None)
    if primary_clinic_id:
        clinic_ids.add(primary_clinic_id)

    related_clinics = []
    main_clinic = getattr(veterinario, 'clinica', None)
    if main_clinic is not None:
        related_clinics.append(main_clinic)
    associated_clinics = getattr(veterinario, 'clinicas', None) or []
    related_clinics.extend(clinic for clinic in associated_clinics if clinic)

    for clinic in related_clinics:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id:
            clinic_ids.add(clinic_id)
        for colleague in getattr(clinic, 'veterinarios', []) or []:
            add_summary_vet(colleague)
        for colleague in getattr(clinic, 'veterinarios_associados', []) or []:
            add_summary_vet(colleague, is_specialist=True)

    if clinic_ids and len(calendar_summary_vets) == 1:
        colleagues = (
            Veterinario.query.filter(Veterinario.clinica_id.in_(clinic_ids)).all()
        )
        for colleague in colleagues:
            add_summary_vet(colleague)

    calendar_summary_clinic_ids = calendar_access_scope.filter_clinic_ids(clinic_ids)
    calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)
    if not calendar_summary_vets:
        add_summary_vet(veterinario)
        calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)

    return render_template(
        'veterinarios/vet_detail.html',
        veterinario=veterinario,
        horarios=horarios,
        horarios_grouped=horarios_grouped,
        calendar_redirect_url=calendar_redirect_url,
        schedule_form=schedule_form,
        appointment_form=appointment_form,
        agenda_veterinarios=agenda_veterinarios,
        agenda_colaboradores=agenda_colaboradores,
        admin_selected_view=admin_selected_view,
        admin_selected_veterinario_id=admin_selected_veterinario_id,
        admin_selected_colaborador_id=admin_selected_colaborador_id,
        admin_default_selection_value=admin_default_selection_value,
        calendar_summary_vets=calendar_summary_vets,
        calendar_summary_clinic_ids=calendar_summary_clinic_ids,
    )




@app.route('/admin/veterinario/<int:veterinario_id>/especialidades', methods=['GET', 'POST'])
@login_required
def edit_vet_specialties(veterinario_id):
    # Apenas o próprio veterinário ou um administrador pode alterar especialidades
    is_owner = (
        is_veterinarian(current_user)
        and current_user.veterinario
        and current_user.veterinario.id == veterinario_id
    )
    if not (_is_admin() or is_owner):
        flash('Apenas o próprio veterinário ou um administrador pode acessar esta página.', 'danger')
        return redirect(url_for('index'))

    veterinario = Veterinario.query.get_or_404(veterinario_id)
    form = VetSpecialtyForm()
    form.specialties.choices = [
        (s.id, s.nome) for s in Specialty.query.order_by(Specialty.nome).all()
    ]
    if form.validate_on_submit():
        veterinario.specialties = Specialty.query.filter(
            Specialty.id.in_(form.specialties.data)
        ).all()
        db.session.commit()
        flash('Especialidades atualizadas com sucesso.', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=veterinario.user_id))
    form.specialties.data = [s.id for s in veterinario.specialties]
    return render_template('agendamentos/edit_vet_specialties.html', form=form, veterinario=veterinario)


@app.route('/tutor/<int:tutor_id>')
@login_required
def obter_tutor(tutor_id):
    tutor = get_user_or_404(tutor_id)
    return jsonify({
        'id': tutor.id,
        'name': tutor.name,
        'phone': tutor.phone,
        'address': tutor.address,
        'cpf': tutor.cpf,
        'rg': tutor.rg,
        'email': tutor.email,
        'date_of_birth': tutor.date_of_birth.strftime('%Y-%m-%d') if tutor.date_of_birth else ''
    })


@app.route('/tutor/<int:tutor_id>')
@login_required
def tutor_detail(tutor_id):
    tutor   = get_user_or_404(tutor_id)
    animais = tutor.animais.order_by(Animal.name).all()
    return render_template('animais/tutor_detail.html', tutor=tutor, animais=animais)


@app.route('/tutores', methods=['GET', 'POST'])
@login_required
def tutores():
    # Restrição de acesso
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    clinic_id = current_user_clinic_id()
    accessible_clinic_ids = _viewer_accessible_clinic_ids(current_user)
    clinic_scope = (
        accessible_clinic_ids
        if len(accessible_clinic_ids) > 1
        else accessible_clinic_ids[0]
        if accessible_clinic_ids
        else None
    )
    vet_profile = getattr(current_user, 'veterinario', None)
    require_appointments = _is_specialist_veterinarian(vet_profile)
    veterinarian_scope_id = vet_profile.id if require_appointments and vet_profile else None
    scope = request.args.get('scope', 'all')
    page = request.args.get('page', 1, type=int)
    effective_user_id = getattr(current_user, 'id', None)

    # Criação de novo tutor
    if request.method == 'POST':
        wants_json = 'application/json' in request.headers.get('Accept', '')
        name = request.form.get('tutor_name') or request.form.get('name')
        email = request.form.get('tutor_email') or request.form.get('email')

        if not name or not email:
            message = 'Nome e e‑mail são obrigatórios.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning')
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        if User.query.filter_by(email=email).first():
            message = 'Já existe um tutor com esse e‑mail.'
            if wants_json:
                return jsonify(success=False, message=message, category='warning')
            flash(message, 'warning')
            return redirect(url_for('tutores'))

        novo = User(
            name=name.strip(),
            email=email.strip(),
            role='adotante',  # padrão inicial
            clinica_id=current_user_clinic_id(),
            added_by=current_user,
            is_private=True,
        )
        novo.set_password('123456789')  # ⚠️ Sugestão: depois trocar por um token de convite

        # Campos opcionais
        novo.phone = (request.form.get('tutor_phone') or request.form.get('phone') or '').strip() or None
        novo.cpf = (request.form.get('tutor_cpf') or request.form.get('cpf') or '').strip() or None
        novo.rg = (request.form.get('tutor_rg') or request.form.get('rg') or '').strip() or None
        novo.address = None

        # Data de nascimento
        date_str = request.form.get('tutor_date_of_birth') or request.form.get('date_of_birth')
        if date_str:
            try:
                novo.date_of_birth = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
            except ValueError:
                message = 'Data de nascimento inválida. Use o formato AAAA-MM-DD.'
                if wants_json:
                    return jsonify(success=False, message=message, category='danger')
                flash(message, 'danger')
                return redirect(url_for('tutores'))

        # Endereço
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')

        if cep and rua and cidade and estado:
            endereco = Endereco(
                cep=cep,
                rua=rua,
                numero=numero,
                complemento=complemento,
                bairro=bairro,
                cidade=cidade,
                estado=estado
            )
            db.session.add(endereco)
            db.session.flush()
            novo.endereco_id = endereco.id

        # Foto
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            novo.profile_photo = f"/static/uploads/{filename}"

        db.session.add(novo)
        db.session.commit()

        if request.accept_mimetypes.accept_json:
            scope = request.args.get('scope', 'all')
            page = request.args.get('page', 1, type=int)
            tutor_search = (request.args.get('tutor_search', '', type=str) or '').strip()
            tutor_sort = (request.args.get('tutor_sort', 'name_asc', type=str) or 'name_asc').strip()
            tutores_adicionados, pagination, resolved_scope = _get_recent_tutores(
                scope,
                page,
                clinic_id=clinic_scope,
                user_id=effective_user_id,
                require_appointments=require_appointments,
                veterinario_id=veterinarian_scope_id,
                search=tutor_search,
                sort_option=tutor_sort,
            )
            html = render_template(
                'partials/tutores_adicionados.html',
                tutores_adicionados=tutores_adicionados,
                pagination=pagination,
                scope=resolved_scope,
                scope_param=request.args.get('scope_param', 'scope'),
                search_param='tutor_search',
                sort_param='tutor_sort',
                page_param=request.args.get('page_param', 'page'),
                fetch_url=url_for('tutores'),
                compact=True,
            )
            return jsonify(
                message='Tutor criado com sucesso!',
                category='success',
                html=html,
                tutor={
                    'id': novo.id,
                    'name': novo.name or f'Tutor #{novo.id}',
                    'display_name': novo.name or f'Tutor #{novo.id}',
                },
                redirect_url=url_for('ficha_tutor', tutor_id=novo.id),
            )

        flash('Tutor criado com sucesso!', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=novo.id))

    # — GET com paginação —
    tutor_search = (request.args.get('tutor_search', '', type=str) or '').strip()
    tutor_sort = (request.args.get('tutor_sort', 'name_asc', type=str) or 'name_asc').strip()
    tutores_adicionados, pagination, resolved_scope = _get_recent_tutores(
        scope,
        page,
        clinic_id=clinic_scope,
        user_id=effective_user_id,
        require_appointments=require_appointments,
        veterinario_id=veterinarian_scope_id,
        search=tutor_search,
        sort_option=tutor_sort,
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (
        request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
    ):
        html = render_template(
            'partials/tutores_adicionados.html',
            tutores_adicionados=tutores_adicionados,
            pagination=pagination,
            scope=resolved_scope,
            scope_param=request.args.get('scope_param', 'scope'),
            search_param='tutor_search',
            sort_param='tutor_sort',
            page_param=request.args.get('page_param', 'page'),
            fetch_url=url_for('tutores'),
            compact=True,
            shared_access_map={t.id: _resolve_shared_access_for_user(t, viewer=current_user, clinic_scope=clinic_scope) for t in tutores_adicionados},
            viewer_clinic_id=clinic_id,
        )
        return jsonify(html=html, scope=resolved_scope)

    return render_template(
        'animais/tutores.html',
        tutores_adicionados=tutores_adicionados,
        pagination=pagination,
        scope=resolved_scope,
        tutor_search=tutor_search,
        tutor_sort=tutor_sort,
        viewer_clinic_id=clinic_id,
        shared_access_map={t.id: _resolve_shared_access_for_user(t, viewer=current_user, clinic_scope=clinic_scope) for t in tutores_adicionados},
    )


@app.route('/tutor/compartilhamentos')
@login_required
def tutor_sharing_dashboard():
    if not _is_tutor_portal_user(current_user):
        abort(403)
    payload = _serialize_tutor_share_payload(current_user)
    token = request.args.get('token')
    token_request = None
    if token:
        share_request = DataShareRequest.query.filter_by(token=token).first()
        if share_request and share_request.tutor_id == current_user.id:
            token_request = _serialize_share_request(share_request)
        else:
            flash('Pedido não encontrado ou expirado.', 'warning')
    return render_template(
        'tutor/sharing_dashboard.html',
        share_payload=payload,
        share_api=url_for('shares_api'),
        pending_token=token,
        token_request=token_request,
    )


def _can_request_share(user):
    worker = (getattr(user, 'worker', None) or '').lower()
    if worker in {'veterinario', 'colaborador'}:
        return True
    return getattr(user, 'role', None) == 'admin'


def _share_request_target_animals(tutor_id, animal_id):
    animal = None
    if animal_id:
        animal = Animal.query.get_or_404(animal_id)
        if animal.user_id != tutor_id:
            raise ValueError('Animal não pertence ao tutor informado.')
    return animal


@app.route('/api/shares', methods=['GET', 'POST'])
@login_required
def shares_api():
    if request.method == 'POST':
        if not _can_request_share(current_user):
            return (
                jsonify(success=False, message='Apenas colaboradores podem solicitar compartilhamentos.', category='danger'),
                403,
            )
        clinic_id = current_user_clinic_id()
        if not clinic_id:
            return jsonify(success=False, message='Associe-se a uma clínica antes de solicitar acesso.', category='warning'), 400
        payload = request.get_json(silent=True) or {}
        tutor_id = payload.get('tutor_id')
        if not tutor_id:
            return jsonify(success=False, message='tutor_id é obrigatório.', category='danger'), 400
        tutor = User.query.get_or_404(tutor_id)
        try:
            animal = _share_request_target_animals(tutor.id, payload.get('animal_id'))
        except ValueError as exc:
            return jsonify(success=False, message=str(exc), category='danger'), 400
        parties = [(DataSharePartyType.clinic, clinic_id)]
        existing_access = find_active_share(parties, user_id=tutor.id, animal_id=getattr(animal, 'id', None))
        if existing_access:
            return jsonify(success=False, message='Este tutor já concedeu acesso à sua clínica.', category='info'), 409
        pending = (
            DataShareRequest.query.filter_by(
                tutor_id=tutor.id,
                clinic_id=clinic_id,
                animal_id=getattr(animal, 'id', None),
                status='pending',
            )
            .order_by(DataShareRequest.created_at.desc())
            .first()
        )
        if pending and pending.is_pending():
            return jsonify(success=False, message='Já existe um pedido pendente para este tutor.', category='warning'), 409
        expires_days = _default_share_duration(payload.get('expires_in_days'))
        expires_at = datetime.utcnow() + timedelta(days=expires_days)
        message = (payload.get('message') or payload.get('grant_reason') or '').strip() or None
        share_request = DataShareRequest(
            tutor_id=tutor.id,
            animal_id=getattr(animal, 'id', None),
            clinic_id=clinic_id,
            requested_by_id=current_user.id,
            message=message,
            expires_at=expires_at,
        )
        db.session.add(share_request)
        db.session.commit()
        _notify_tutor_share_request(share_request)
        return jsonify(success=True, request=_serialize_share_request(share_request)), 201

    scope = request.args.get('scope') or ('tutor' if _is_tutor_portal_user(current_user) else 'clinic')
    if scope == 'tutor' and _is_tutor_portal_user(current_user):
        payload = _serialize_tutor_share_payload(current_user)
    else:
        payload = _serialize_clinic_share_payload(current_user)
    return jsonify(payload)


def _share_request_or_404(request_id):
    share_request = DataShareRequest.query.get_or_404(request_id)
    if share_request.tutor_id != current_user.id:
        abort(404)
    return share_request


def _ensure_pending(share_request):
    if not share_request.is_pending():
        abort(400, description='Pedido já foi processado ou expirou.')


def _activate_share_request(share_request, expires_in_days=None):
    now = datetime.utcnow()
    expires_at = share_request.expires_at
    if expires_in_days:
        expires_at = now + timedelta(days=_default_share_duration(expires_in_days))
    elif not expires_at or expires_at <= now:
        expires_at = now + timedelta(days=_default_share_duration(None))
    tutor = share_request.tutor
    party = (DataSharePartyType.clinic, share_request.clinic_id)
    access = find_active_share([party], user_id=share_request.tutor_id, animal_id=share_request.animal_id)
    if access:
        access.expires_at = expires_at
        access.grant_reason = share_request.message or access.grant_reason
        access.granted_by = current_user.id
        access.granted_via = 'share_request'
    else:
        access = DataShareAccess(
            user_id=share_request.tutor_id,
            animal_id=share_request.animal_id,
            source_clinic_id=getattr(tutor, 'clinica_id', None),
            granted_to_type=DataSharePartyType.clinic,
            granted_to_id=share_request.clinic_id,
            granted_by=current_user.id,
            grant_reason=share_request.message,
            granted_via='share_request',
            expires_at=expires_at,
        )
        db.session.add(access)
    share_request.status = 'approved'
    share_request.approved_at = now
    share_request.approved_by_id = current_user.id
    share_request.denied_at = None
    share_request.denial_reason = None
    db.session.add(share_request)
    db.session.flush()
    log_data_share_event(
        access,
        event_type='share_granted',
        resource_type='user',
        resource_id=share_request.tutor_id,
        actor=current_user,
        notes=f'Pedido #{share_request.id}',
    )
    if share_request.animal_id:
        log_data_share_event(
            access,
            event_type='share_granted',
            resource_type='animal',
            resource_id=share_request.animal_id,
            actor=current_user,
            notes=f'Pedido #{share_request.id}',
        )
    return access


@app.route('/api/shares/<int:request_id>/approve', methods=['POST'])
@login_required
def approve_share_request(request_id):
    if not _is_tutor_portal_user(current_user):
        abort(403)
    share_request = _share_request_or_404(request_id)
    _ensure_pending(share_request)
    payload = request.get_json(silent=True) or {}
    access = _activate_share_request(share_request, expires_in_days=payload.get('expires_in_days'))
    db.session.commit()
    _notify_clinic_share_decision(share_request, True)
    return jsonify(success=True, request=_serialize_share_request(share_request), access=_serialize_share_access(access))


@app.route('/api/shares/<int:request_id>/deny', methods=['POST'])
@login_required
def deny_share_request(request_id):
    if not _is_tutor_portal_user(current_user):
        abort(403)
    share_request = _share_request_or_404(request_id)
    _ensure_pending(share_request)
    payload = request.get_json(silent=True) or {}
    reason = (payload.get('reason') or '').strip() or None
    share_request.status = 'denied'
    share_request.denied_at = datetime.utcnow()
    share_request.denial_reason = reason
    db.session.add(share_request)
    db.session.commit()
    _notify_clinic_share_decision(share_request, False)
    return jsonify(success=True, request=_serialize_share_request(share_request))


@app.route('/api/shares/confirm', methods=['POST'])
@login_required
def confirm_share_request():
    if not _is_tutor_portal_user(current_user):
        abort(403)
    payload = request.get_json(silent=True) or {}
    token = payload.get('token')
    if not token:
        return jsonify(success=False, message='Token é obrigatório.', category='danger'), 400
    share_request = DataShareRequest.query.filter_by(token=token).first()
    if not share_request or share_request.tutor_id != current_user.id:
        return jsonify(success=False, message='Pedido não encontrado.', category='warning'), 404
    if payload.get('decision', 'approve').lower() == 'deny':
        _ensure_pending(share_request)
        share_request.status = 'denied'
        share_request.denied_at = datetime.utcnow()
        share_request.denial_reason = (payload.get('reason') or '').strip() or None
        db.session.add(share_request)
        db.session.commit()
        _notify_clinic_share_decision(share_request, False)
        return jsonify(success=True, request=_serialize_share_request(share_request))
    _ensure_pending(share_request)
    access = _activate_share_request(share_request)
    db.session.commit()
    _notify_clinic_share_decision(share_request, True)
    return jsonify(success=True, request=_serialize_share_request(share_request), access=_serialize_share_access(access))


@app.route('/api/share-requests/<string:token>', methods=['GET'])
@login_required
def share_request_detail(token):
    if not _is_tutor_portal_user(current_user):
        abort(403)
    share_request = DataShareRequest.query.filter_by(token=token).first_or_404()
    if share_request.tutor_id != current_user.id:
        abort(404)
    return jsonify(_serialize_share_request(share_request))



@app.route('/deletar_tutor/<int:tutor_id>', methods=['POST'])
@login_required
def deletar_tutor(tutor_id):
    tutor = get_user_or_404(tutor_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir tutores.', 'danger')
        return redirect(url_for('index'))

    if current_user.role != 'admin' and tutor.added_by_id != current_user.id:
        message = 'Você não tem permissão para excluir este tutor.'
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=message, category='danger'), 403
        flash(message, 'danger')
        abort(403)

    try:
        with db.session.no_autoflush:
            for animal in tutor.animals:
                # Deletar blocos de prescrição manualmente
                for bloco in animal.blocos_prescricao:
                    db.session.delete(bloco)

                # Você pode incluir aqui: exames, vacinas, etc., se necessário

                db.session.delete(animal)

        db.session.delete(tutor)
        db.session.commit()
        flash('Tutor e todos os seus dados foram excluídos com sucesso.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir tutor: {str(e)}', 'danger')

    return redirect(url_for('tutores'))




@app.route('/buscar_animais')
@login_required
def buscar_animais():
    term = (request.args.get('q', '') or '').strip()
    clinic_id = current_user_clinic_id()
    is_admin = _is_admin()

    if not is_admin and not clinic_id:
        return jsonify([])

    visibility_clause = _user_visibility_clause(clinic_scope=clinic_id)
    sort = request.args.get('sort')
    tutor_id = request.args.get('tutor_id', type=int)

    results = search_animals(
        term=term,
        clinic_scope=clinic_id,
        is_admin=is_admin,
        visibility_clause=visibility_clause,
        sort=sort,
        tutor_id=tutor_id,
    )

    return jsonify(results)





@app.route('/update_tutor/<int:user_id>', methods=['POST'])
@login_required
def update_tutor(user_id):
    user = get_user_or_404(user_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    # 🔐 Permissão: veterinários ou colaboradores
    if current_user.worker not in ['veterinario', 'colaborador']:
        message = 'Apenas veterinários ou colaboradores podem editar dados do tutor.'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    # 📋 Campos básicos (exceto CPF)
    for field in ['name', 'email', 'phone', 'rg']:
        value = request.form.get(field)
        if value:
            setattr(user, field, value)

    # CPF precisa ser único
    cpf_val = request.form.get('cpf')
    if cpf_val:
        cpf_val = cpf_val.strip()
        if cpf_val != (user.cpf or ''):
            existing = User.query.filter(User.cpf == cpf_val, User.id != user.id).first()
            if existing:
                message = 'CPF já cadastrado para outro tutor.'
                if wants_json:
                    return jsonify(success=False, message=message, category='danger'), 400
                flash(message, 'danger')
                return redirect(request.referrer or url_for('index'))
        user.cpf = cpf_val

    # 📅 Data de nascimento
    date_str = request.form.get('date_of_birth')
    if date_str:
        try:
            user.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            message = 'Data de nascimento inválida. Use o formato correto.'
            if wants_json:
                return jsonify(success=False, message=message, category='danger'), 400
            flash(message, 'danger')
            return redirect(request.referrer or url_for('index'))

    # 📸 Foto de perfil
    photo = request.files.get('profile_photo')
    if photo and photo.filename:
        filename = f"{uuid.uuid4().hex}_{secure_filename(photo.filename)}"
        # Upload sincronamente para garantir a atualização imediata
        image_url = upload_to_s3(photo, filename, folder="tutors")
        if image_url:
            user.profile_photo = image_url

    # Controles de corte da foto
    try:
        user.photo_rotation = int(request.form.get('photo_rotation', user.photo_rotation or 0))
    except ValueError:
        pass
    try:
        user.photo_zoom = float(request.form.get('photo_zoom', user.photo_zoom or 1.0))
    except ValueError:
        pass
    try:
        user.photo_offset_x = float(request.form.get('photo_offset_x', user.photo_offset_x or 0))
    except ValueError:
        pass
    try:
        user.photo_offset_y = float(request.form.get('photo_offset_y', user.photo_offset_y or 0))
    except ValueError:
        pass

    # 📍 Endereço
    addr_fields = {
        k: request.form.get(k) or None
        for k in ['cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado']
    }
    required_fields = ['cep', 'rua', 'cidade', 'estado']

    if all(addr_fields.get(f) for f in required_fields):
        endereco = user.endereco or Endereco()
        for k, v in addr_fields.items():
            setattr(endereco, k, v)
        if not user.endereco_id:
            db.session.add(endereco)
            db.session.flush()
            user.endereco_id = endereco.id
    elif any(addr_fields.values()):
        message = 'Por favor, informe CEP, rua, cidade e estado.'
        if wants_json:
            return jsonify(success=False, message=message, category='warning'), 400
        flash(message, 'warning')
        return redirect(request.referrer or url_for('index'))

    # 💾 Commit final
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERRO ao salvar tutor: {e}")
        message = f'Ocorreu um erro ao salvar: {str(e)}'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 500
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    message = 'Dados do tutor atualizados com sucesso!'
    if wants_json:
        tutor_payload = {
            'id': user.id,
            'name': user.name,
            'profile_photo': user.profile_photo,
            'photo_offset_x': user.photo_offset_x,
            'photo_offset_y': user.photo_offset_y,
            'photo_rotation': user.photo_rotation,
            'photo_zoom': user.photo_zoom,
        }
        return jsonify(
            success=True,
            message=message,
            tutor_name=user.name,
            tutor=tutor_payload,
            category='success'
        )
    flash(message, 'success')
    return redirect(request.referrer or url_for('index'))



# ——— FICHA DO TUTOR (dados + lista de animais) ————————————
from sqlalchemy.orm import joinedload

@app.route('/ficha_tutor/<int:tutor_id>')
@login_required
def ficha_tutor(tutor_id):
    # Restrição de acesso
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    # Dados do tutor
    tutor = get_user_or_404(tutor_id)

    # Lista de animais do tutor (com species e breed carregados)
    animais = Animal.query.options(
        joinedload(Animal.species),
        joinedload(Animal.breed)
    ).filter_by(user_id=tutor.id).order_by(Animal.name).all()

    # Ano atual
    current_year = datetime.now(BR_TZ).year

    # Formulários para usar o photo_cropper no template
    tutor_form = EditProfileForm(obj=tutor)
    animal_forms = {}
    for a in animais:
        form_obj = AnimalForm(obj=a)
        _preencher_idade_form(form_obj, a)
        animal_forms[a.id] = form_obj
    new_animal_form = AnimalForm()
    _preencher_idade_form(new_animal_form)

    # Busca todas as espécies e raças
    species_list = list_species()
    breeds = Breed.query.options(joinedload(Breed.species)).all()

    # Mapeia raças por species_id (como string, para uso seguro no JS)
    breed_map = {}
    for breed in breeds:
        sp_id = str(breed.species.id)
        breed_map.setdefault(sp_id, []).append({
            'id': breed.id,
            'name': breed.name
        })

    return render_template(
        'animais/tutor_detail.html',
        tutor=tutor,
        endereco=tutor.endereco,  # Passa explicitamente o endereço
        animais=animais,
        current_year=current_year,
        species_list=species_list,
        breed_map=breed_map,
        tutor_form=tutor_form,
        animal_forms=animal_forms,
        new_animal_form=new_animal_form
    )






@app.route('/update_animal/<int:animal_id>', methods=['POST'])
@login_required
def update_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')
    queued_messages = [] if wants_json else None

    def queue_message(text, category='info'):
        if wants_json:
            queued_messages.append({'message': text, 'category': category})
        else:
            flash(text, category)

    if current_user.worker != 'veterinario':
        message = 'Apenas veterinários podem editar dados do animal.'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    # Campos básicos
    animal.name = request.form.get('name')
    animal.sex = request.form.get('sex')
    animal.description = request.form.get('description') or ''
    animal.microchip_number = request.form.get('microchip_number')
    animal.health_plan = request.form.get('health_plan')
    animal.neutered = request.form.get('neutered') == '1'

    # Espécie (relacional)
    species_id = request.form.get('species_id')
    if species_id:
        try:
            animal.species_id = int(species_id)
        except ValueError:
            queue_message('ID de espécie inválido.', 'warning')

    # Raça (relacional)
    breed_id = request.form.get('breed_id')
    if breed_id:
        try:
            animal.breed_id = int(breed_id)
        except ValueError:
            queue_message('ID de raça inválido.', 'warning')

    # Peso
    peso_valor = request.form.get('peso')
    if peso_valor:
        try:
            animal.peso = float(peso_valor)
        except ValueError:
            queue_message('Peso inválido. Deve ser um número.', 'warning')
    else:
        animal.peso = None

    # Data de nascimento ou idade
    dob_str = request.form.get('date_of_birth')
    age_input = request.form.get('age')
    age_unit_input = request.form.get('age_unit')
    idade_numero = None
    if dob_str:
        try:
            animal.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
        except ValueError:
            queue_message('Data de nascimento inválida.', 'warning')
    elif age_input:
        try:
            idade_numero = int(age_input)
            unidade_norm = _normalizar_unidade_idade(age_unit_input)
            if unidade_norm == 'meses':
                animal.date_of_birth = date.today() - relativedelta(months=idade_numero)
            else:
                animal.date_of_birth = date.today() - relativedelta(years=idade_numero)
        except ValueError:
            queue_message('Idade inválida. Deve ser um número inteiro.', 'warning')

    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            animal.age = _formatar_idade(delta.years, 'anos')
        else:
            animal.age = _formatar_idade(delta.months, 'meses')
    elif idade_numero is not None:
        animal.age = _formatar_idade(idade_numero, age_unit_input)
    elif age_input:
        animal.age = age_input
    else:
        animal.age = None

    # Upload de imagem
    if 'image' in request.files and request.files['image'].filename != '':
        image_file = request.files['image']
        original_filename = secure_filename(image_file.filename)
        filename = f"{uuid.uuid4().hex}_{original_filename}"
        image_url = upload_to_s3(image_file, filename, folder="animals")
        animal.image = image_url

    try:
        animal.photo_rotation = int(request.form.get('photo_rotation', animal.photo_rotation or 0))
    except ValueError:
        pass
    try:
        animal.photo_zoom = float(request.form.get('photo_zoom', animal.photo_zoom or 1.0))
    except ValueError:
        pass
    try:
        animal.photo_offset_x = float(request.form.get('photo_offset_x', animal.photo_offset_x or 0))
    except ValueError:
        pass
    try:
        animal.photo_offset_y = float(request.form.get('photo_offset_y', animal.photo_offset_y or 0))
    except ValueError:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        message = f'Ocorreu um erro ao salvar: {str(e)}'
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 500
        flash(message, 'danger')
        return redirect(request.referrer or url_for('index'))

    message = 'Dados do animal atualizados com sucesso!'
    if wants_json:
        payload = dict(success=True, message=message, animal_name=animal.name, category='success')
        if queued_messages:
            payload['messages'] = queued_messages
        return jsonify(payload)
    flash(message, 'success')
    return redirect(request.referrer or url_for('index'))




@app.route('/update_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def update_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    if current_user.worker != 'veterinario':
        message = 'Apenas veterinários podem editar a consulta.'
        flash(message, 'danger')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        return redirect(url_for('index'))

    # Atualiza os campos
    consulta.queixa_principal = request.form.get('queixa_principal')
    consulta.historico_clinico = request.form.get('historico_clinico')
    consulta.exame_fisico = request.form.get('exame_fisico')
    consulta.conduta = request.form.get('conduta')

    # Se estiver editando uma consulta antiga
    if request.args.get('edit') == '1':
        db.session.commit()
        message = 'Consulta atualizada com sucesso!'
        flash(message, 'success')

    else:
        # Salva, finaliza e cria nova automaticamente
        consulta.status = 'finalizada'
        consulta.finalizada_em = datetime.utcnow()
        appointment = consulta.appointment
        if appointment and appointment.status != 'completed':
            appointment.status = 'completed'
        db.session.commit()

        nova = Consulta(
            animal_id=consulta.animal_id,
            created_by=current_user.id,
            clinica_id=consulta.clinica_id,
            status='in_progress'
        )
        db.session.add(nova)
        db.session.commit()

        message = 'Consulta salva e movida para o histórico!'
        flash(message, 'success')

    if wants_json:
        historico = (
            Consulta.query
            .filter_by(
                animal_id=consulta.animal_id,
                status='finalizada',
                clinica_id=consulta.clinica_id,
            )
            .order_by(Consulta.created_at.desc())
            .all()
        )
        html = render_template(
            'partials/historico_consultas.html',
            animal=consulta.animal,
            historico_consultas=historico,
        )
        appointments_html = None
        if consulta.appointment and consulta.clinica_id:
            clinic_appointments = (
                Appointment.query
                .filter_by(clinica_id=consulta.clinica_id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            appointments_grouped = group_appointments_by_day(clinic_appointments)
            appointments_html = render_template(
                'partials/appointments_table.html',
                appointments_grouped=appointments_grouped,
            )
        return jsonify(
            success=True,
            message=message,
            category='success',
            html=html,
            appointments_html=appointments_html,
        )

    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@app.route('/animal/<int:animal_id>/racoes', methods=['POST'])
@login_required
def salvar_racao(animal_id):
    animal = get_animal_or_404(animal_id)

    # Verifica se o usuário pode editar esse animal
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    data = request.get_json(silent=True) or {}

    try:
        # ✅ SUPORTE AO FORMATO NOVO: tipo_racao_id direto
        if 'tipo_racao_id' in data:
            tipo_racao_id = data.get('tipo_racao_id')
            recomendacao_custom = data.get('recomendacao_custom')
            observacoes_racao = data.get('observacoes_racao')

            # Garante que tipo_racao existe
            tipo_racao = TipoRacao.query.get(tipo_racao_id)
            if not tipo_racao:
                return jsonify({'success': False, 'error': 'Tipo de ração não encontrado.'}), 404

            nova_racao = Racao(
                animal_id=animal.id,
                tipo_racao_id=tipo_racao.id,
                recomendacao_custom=recomendacao_custom,
                observacoes_racao=observacoes_racao,
                preco_pago=data.get('preco_pago'),  # ✅ CORRIGIDO
                tamanho_embalagem=data.get('tamanho_embalagem'),  # ✅ CORRIGIDO
                created_by=current_user.id
            )
            db.session.add(nova_racao)

        # ✅ SUPORTE AO FORMATO ANTIGO: lista de racoes com marca/linha
        elif 'racoes' in data:
            racoes_data = data.get('racoes', [])
            for r in racoes_data:
                marca = r.get('marca_racao', '').strip()
                linha_val = r.get('linha_racao')
                linha = linha_val.strip() if linha_val else None

                if not marca:
                    continue  # ignora se não houver marca

                tipo_racao = TipoRacao.query.filter_by(marca=marca, linha=linha).first()

                if not tipo_racao:
                    tipo_racao = TipoRacao(
                        marca=marca,
                        linha=linha,
                        created_by=current_user.id,
                    )
                    db.session.add(tipo_racao)
                    db.session.flush()  # garante que o ID estará disponível

                nova_racao = Racao(
                    animal_id=animal.id,
                    tipo_racao_id=tipo_racao.id,
                    recomendacao_custom=r.get('recomendacao_custom'),
                    observacoes_racao=r.get('observacoes_racao'),
                    created_by=current_user.id
                )
                db.session.add(nova_racao)

        else:
            return jsonify({'success': False, 'error': 'Formato de dados inválido.'}), 400

        db.session.commit()
        # Limpa o cache caso um novo tipo tenha sido criado acima
        try:
            list_rations.cache_clear()
        except Exception:
            pass

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao salvar ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao salvar ração.'}), 500


@app.route('/tipo_racao', methods=['POST'])
@login_required
def criar_tipo_racao():
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    data = request.get_json(silent=True) or {}
    marca = data.get('marca', '').strip()
    linha = data.get('linha', '').strip()
    recomendacao = data.get('recomendacao')
    peso_pacote_kg = data.get('peso_pacote_kg')  # Novo campo
    observacoes = data.get('observacoes', '').strip()

    if not marca:
        return jsonify({'success': False, 'error': 'Marca é obrigatória.'}), 400

    try:
        # Evita duplicidade
        existente = TipoRacao.query.filter_by(marca=marca, linha=linha).first()
        if existente:
            return jsonify({'success': False, 'error': 'Esta ração já existe.'}), 409

        nova_racao = TipoRacao(
            marca=marca,
            linha=linha if linha else None,
            recomendacao=recomendacao,
            peso_pacote_kg=peso_pacote_kg or 15.0,  # valor padrão se não enviado
            observacoes=observacoes if observacoes else None,
            created_by=current_user.id,
        )
        db.session.add(nova_racao)
        db.session.commit()
        # Limpa o cache para que novas rações apareçam imediatamente
        try:
            list_rations.cache_clear()
        except Exception:
            pass

        return jsonify({'success': True, 'id': nova_racao.id})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao cadastrar tipo de ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao cadastrar tipo de ração.'}), 500


@app.route('/tipo_racao/<int:tipo_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_tipo_racao(tipo_id):
    tipo = TipoRacao.query.get_or_404(tipo_id)
    if tipo.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        db.session.delete(tipo)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    marca_val = data.get('marca', tipo.marca)
    if marca_val is not None:
        marca_val = marca_val.strip()
    tipo.marca = marca_val
    linha_val = data.get('linha', tipo.linha)
    if linha_val is not None:
        linha_val = linha_val.strip()
    tipo.linha = linha_val or None
    tipo.recomendacao = data.get('recomendacao', tipo.recomendacao)
    tipo.peso_pacote_kg = data.get('peso_pacote_kg', tipo.peso_pacote_kg)
    tipo.observacoes = data.get('observacoes', tipo.observacoes)
    db.session.commit()
    return jsonify({'success': True})




@app.route('/tipos_racao')
def tipos_racao():
    termos = request.args.get('q', '')
    resultados = TipoRacao.query.filter(
        (TipoRacao.marca + ' - ' + (TipoRacao.linha or '')).ilike(f'%{termos}%')
    ).limit(15).all()

    return jsonify([
        f"{r.marca} - {r.linha}" if r.linha else r.marca
        for r in resultados
    ])


@app.route('/buscar_racoes')
def buscar_racoes():
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])

    resultados = (
        TipoRacao.query
        .filter(
            (TipoRacao.marca.ilike(f'%{q}%')) |
            (TipoRacao.linha.ilike(f'%{q}%'))
        )
        .order_by(TipoRacao.marca)
        .limit(15)
        .all()
    )

    return jsonify([
        {
            'id': r.id,
            'marca': r.marca,
            'linha': r.linha,
            'recomendacao': r.recomendacao,
            'peso_pacote_kg': r.peso_pacote_kg,
            'observacoes': r.observacoes,
        }
        for r in resultados
    ])


@app.route('/racao/<int:racao_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_racao(racao_id):
    racao = Racao.query.get_or_404(racao_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if racao.created_by and racao.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            db.session.delete(racao)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            print(f"Erro ao excluir ração: {e}")
            return jsonify({'success': False, 'error': 'Erro técnico ao excluir ração.'}), 500

    data = request.get_json(silent=True) or {}
    racao.recomendacao_custom = data.get('recomendacao_custom') or None
    racao.observacoes_racao = data.get('observacoes_racao') or ''
    racao.preco_pago = data.get('preco_pago') or None
    racao.tamanho_embalagem = data.get('tamanho_embalagem') or None

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Erro ao editar ração: {e}")
        return jsonify({'success': False, 'error': 'Erro técnico ao editar ração.'}), 500






from sqlalchemy.orm import aliased
from sqlalchemy import desc

from collections import defaultdict

@app.route("/relatorio/racoes")
@login_required
def relatorio_racoes():
    subquery = (
        db.session.query(
            Racao.animal_id,
            func.max(Racao.data_cadastro).label("ultima_data")
        )
        .group_by(Racao.animal_id)
        .subquery()
    )

    RacaoAlias = aliased(Racao)

    racoes_recentes = (
        db.session.query(RacaoAlias)
        .join(subquery, (RacaoAlias.animal_id == subquery.c.animal_id) & 
                         (RacaoAlias.data_cadastro == subquery.c.ultima_data))
        .all()
    )

    # Agrupar por tipo_racao
    racoes_por_tipo = defaultdict(list)
    for r in racoes_recentes:
        racoes_por_tipo[r.tipo_racao].append(r)

    return render_template("loja/relatorio_racoes.html", racoes_por_tipo=racoes_por_tipo)


@app.route("/historico_animal/<int:animal_id>")
@login_required
def historico_animal(animal_id):
    animal = get_animal_or_404(animal_id)
    racoes = Racao.query.filter_by(animal_id=animal.id).order_by(Racao.data_cadastro.desc()).all()
    return render_template("historico_racoes.html", animal=animal, racoes=racoes)



@app.route('/relatorio/racoes/<int:tipo_id>')
@login_required
def detalhes_racao(tipo_id):
    tipo = TipoRacao.query.get_or_404(tipo_id)
    racoes = tipo.usos  # usa o backref 'usos'
    return render_template('loja/detalhes_racao.html', tipo=tipo, racoes=racoes)





@app.route('/buscar_vacinas')
def buscar_vacinas():
    termo = request.args.get('q', '').strip().lower()

    if not termo or len(termo) < 2:
        return jsonify([])

    try:
        resultados = VacinaModelo.query.filter(
            VacinaModelo.nome.ilike(f"%{termo}%")
        ).all()

        return jsonify([
            {
                'id': v.id,
                'nome': v.nome,
                'tipo': v.tipo or '',
                'fabricante': v.fabricante or '',
                'doses_totais': v.doses_totais,
                'intervalo_dias': v.intervalo_dias,
                'frequencia': v.frequencia or '',
            }
            for v in resultados
        ])
    except Exception as e:
        print(f"Erro ao buscar vacinas: {e}")
        return jsonify([])  # Não quebra o front se der erro

@app.route('/vacina_modelo', methods=['POST'])
@login_required
def criar_vacina_modelo():
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    tipo = (data.get('tipo') or '').strip()
    fabricante = (data.get('fabricante') or '').strip() or None
    doses_totais = data.get('doses_totais')
    intervalo_dias = data.get('intervalo_dias')
    frequencia = (data.get('frequencia') or '').strip() or None
    if not nome or not tipo:
        return jsonify({'success': False, 'message': 'Nome e tipo são obrigatórios.'}), 400
    try:
        existente = VacinaModelo.query.filter(func.lower(VacinaModelo.nome) == nome.lower()).first()
        if existente:
            return jsonify({'success': False, 'message': 'Vacina já cadastrada.'}), 400
        vacina = VacinaModelo(
            nome=nome,
            tipo=tipo,
            fabricante=fabricante,
            doses_totais=doses_totais,
            intervalo_dias=intervalo_dias,
            frequencia=frequencia,
            created_by=current_user.id,
        )
        db.session.add(vacina)
        db.session.commit()
        return jsonify({
            'success': True,
            'vacina': {
                'id': vacina.id,
                'nome': vacina.nome,
                'tipo': vacina.tipo,
                'fabricante': vacina.fabricante,
                'doses_totais': vacina.doses_totais,
                'intervalo_dias': vacina.intervalo_dias,
                'frequencia': vacina.frequencia,
            },
        })
    except Exception as e:
        db.session.rollback()
        print('Erro ao salvar vacina modelo:', e)
        return jsonify({'success': False, 'message': 'Erro ao salvar vacina.'}), 500


@app.route('/vacina_modelo/<int:vacina_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_vacina_modelo(vacina_id):
    vacina = VacinaModelo.query.get_or_404(vacina_id)
    if vacina.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'message': 'Permissão negada'}), 403

    if request.method == 'DELETE':
        db.session.delete(vacina)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    nome_val = data.get('nome', vacina.nome)
    if nome_val is not None:
        nome_val = nome_val.strip()
    vacina.nome = nome_val
    tipo_val = data.get('tipo', vacina.tipo)
    if tipo_val is not None:
        tipo_val = tipo_val.strip()
    vacina.tipo = tipo_val or None
    vacina.fabricante = (data.get('fabricante', vacina.fabricante) or '').strip() or None
    vacina.doses_totais = data.get('doses_totais', vacina.doses_totais)
    vacina.intervalo_dias = data.get('intervalo_dias', vacina.intervalo_dias)
    vacina.frequencia = (data.get('frequencia', vacina.frequencia) or '').strip() or None
    db.session.commit()
    return jsonify({'success': True})

from datetime import datetime

@app.route("/animal/<int:animal_id>/vacinas", methods=["POST"])
def salvar_vacinas(animal_id):
    data = request.get_json(silent=True) or {}

    if not data or "vacinas" not in data:
        return jsonify({"success": False, "error": "Dados incompletos"}), 400

    try:
        for v in data["vacinas"]:
            aplicada_em_str = v.get("aplicada_em")
            if aplicada_em_str:
                try:
                    aplicada_em = datetime.strptime(aplicada_em_str, "%Y-%m-%d").date()
                except ValueError:
                    aplicada_em = None
            else:
                aplicada_em = None

            vacina = Vacina(
                animal_id=animal_id,
                nome=v.get("nome"),
                tipo=v.get("tipo"),
                fabricante=v.get("fabricante"),
                doses_totais=v.get("doses_totais"),
                intervalo_dias=v.get("intervalo_dias"),
                frequencia=v.get("frequencia"),
                aplicada=v.get("aplicada", False),
                aplicada_em=aplicada_em,
                observacoes=v.get("observacoes"),
                created_by=current_user.id if current_user.is_authenticated else None,
            )
            db.session.add(vacina)

        db.session.commit()
        animal = get_animal_or_404(animal_id)
        historico_html = render_template(
            'partials/historico_vacinas.html',
            animal=animal
        )
        return jsonify({"success": True, "html": historico_html})

    except Exception as e:
        print("Erro ao salvar vacinas:", e)
        return jsonify({"success": False, "error": "Erro técnico ao salvar vacinas"}), 500




@app.route("/animal/<int:animal_id>/vacinas/imprimir")
def imprimir_vacinas(animal_id):
    animal = get_animal_or_404(animal_id)
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else None
    if not veterinario and current_user.is_authenticated and getattr(current_user, "worker", None) == "veterinario":
        veterinario = current_user
    clinica = consulta.clinica if consulta and consulta.clinica else None
    if not clinica and veterinario and getattr(veterinario, "veterinario", None):
        vet = veterinario.veterinario
        if vet.clinica:
            clinica = vet.clinica
    if not clinica:
        clinica = getattr(animal, "clinica", None)
    if not clinica:
        clinica_id = request.args.get("clinica_id", type=int)
        if clinica_id:
            clinica = Clinica.query.get_or_404(clinica_id)
    if not clinica:
        abort(400, description="É necessário informar uma clínica.")
    return render_template("orcamentos/imprimir_vacinas.html", animal=animal, clinica=clinica, veterinario=veterinario)


@app.route('/vacina/<int:vacina_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_vacina(vacina_id):
    vacina = Vacina.query.get_or_404(vacina_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if vacina.created_by and vacina.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            animal_id = vacina.animal_id
            db.session.delete(vacina)
            db.session.commit()
            return jsonify({'success': True, 'animal_id': animal_id})
        except Exception as e:
            db.session.rollback()
            print('Erro ao excluir vacina:', e)
            return jsonify({'success': False, 'error': 'Erro ao excluir vacina.'}), 500

    data = request.get_json(silent=True) or {}
    vacina.nome = data.get('nome', vacina.nome)
    vacina.tipo = data.get('tipo', vacina.tipo)
    vacina.fabricante = data.get('fabricante', vacina.fabricante)
    vacina.doses_totais = data.get('doses_totais', vacina.doses_totais)
    vacina.intervalo_dias = data.get('intervalo_dias', vacina.intervalo_dias)
    vacina.frequencia = data.get('frequencia', vacina.frequencia)
    vacina.observacoes = data.get('observacoes', vacina.observacoes)
    vacina.aplicada = data.get('aplicada', vacina.aplicada)

    aplicada_em_str = data.get('aplicada_em')
    if aplicada_em_str is not None:
        if aplicada_em_str:
            try:
                vacina.aplicada_em = datetime.strptime(aplicada_em_str, '%Y-%m-%d').date()
            except ValueError:
                vacina.aplicada_em = None
        else:
            vacina.aplicada_em = None

    nova_vacina = None
    if vacina.aplicada:
        base_date = vacina.aplicada_em or date.today()
        proxima_data = None
        if vacina.intervalo_dias:
            proxima_data = base_date + timedelta(days=vacina.intervalo_dias)
        elif vacina.frequencia:
            def _norm(txt):
                return ''.join(
                    c for c in unicodedata.normalize('NFD', txt.lower())
                    if unicodedata.category(c) != 'Mn'
                )

            freq_map = {
                'diario': 1,
                'diaria': 1,
                'semanal': 7,
                'quinzenal': 15,
                'mensal': 30,
                'bimestral': 60,
                'trimestral': 91,
                'quadrimestral': 120,
                'semestral': 182,
                'anual': 365,
                'bienal': 730,
            }
            dias = freq_map.get(_norm(vacina.frequencia))
            if dias:
                proxima_data = base_date + timedelta(days=dias)

        if proxima_data:
            nova_vacina = Vacina(
                animal_id=vacina.animal_id,
                nome=vacina.nome,
                tipo=vacina.tipo,
                fabricante=vacina.fabricante,
                doses_totais=vacina.doses_totais,
                intervalo_dias=vacina.intervalo_dias,
                frequencia=vacina.frequencia,
                observacoes=vacina.observacoes,
                aplicada=False,
                aplicada_em=proxima_data,
                created_by=vacina.created_by,
            )

    try:
        if nova_vacina:
            db.session.add(nova_vacina)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print('Erro ao editar vacina:', e)
        return jsonify({'success': False, 'error': 'Erro ao editar vacina.'}), 500



@app.route('/consulta/<int:consulta_id>/prescricao', methods=['POST'])
@login_required
def criar_prescricao(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem adicionar prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    medicamento = request.form.get('medicamento')
    dosagem = request.form.get('dosagem')
    frequencia = request.form.get('frequencia')
    duracao = request.form.get('duracao')
    observacoes = request.form.get('observacoes')

    # Se houver campos estruturados (dose, frequência ou duração),
    # ignoramos o campo de texto livre para evitar salvar ambos
    if dosagem or frequencia or duracao:
        observacoes = None
    # Caso contrário, se apenas o texto livre foi preenchido, os
    # campos estruturados não devem ser persistidos
    elif observacoes:
        dosagem = frequencia = duracao = None

    if not medicamento:
        flash('É necessário informar o nome do medicamento.', 'warning')
        return redirect(request.referrer)

    nova_prescricao = Prescricao(
        consulta_id=consulta.id,
        medicamento=medicamento,
        dosagem=dosagem,
        frequencia=frequencia,
        duracao=duracao,
        observacoes=observacoes
    )

    db.session.add(nova_prescricao)
    db.session.commit()

    flash('Prescrição adicionada com sucesso!', 'success')
    # criar_prescricao
    return redirect(url_for('consulta_qr', animal_id=Consulta.query.get(consulta_id).animal_id))


from flask import request, jsonify


@app.route('/prescricao/<int:prescricao_id>/deletar', methods=['POST'])
@login_required
def deletar_prescricao(prescricao_id):
    prescricao = Prescricao.query.get_or_404(prescricao_id)
    clinic_id = None
    if getattr(prescricao, 'bloco', None):
        clinic_id = prescricao.bloco.clinica_id
    if not clinic_id and prescricao.animal:
        clinic_id = prescricao.animal.clinica_id
    ensure_clinic_access(clinic_id)
    animal_id = prescricao.animal_id

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    db.session.delete(prescricao)
    db.session.commit()
    flash('Prescrição removida com sucesso!', 'info')
    return redirect(url_for('consulta_qr', animal_id=animal_id))


@app.route('/importar_medicamentos')
def importar_medicamentos():
    import pandas as pd


    try:
        df = pd.read_csv("medicamentos_pet_orlandia.csv")

        for _, row in df.iterrows():
            medicamento = Medicamento(
                classificacao=row["classificacao"],
                nome=row["nome"],
                principio_ativo=row["principio_ativo"],
                via_administracao=row["via_administracao"],
                dosagem_recomendada=row["dosagem_recomendada"],
                duracao_tratamento=row["duracao_tratamento"],
                observacoes=row["observacoes"],
                bula=row["link_bula"]
            )
            db.session.add(medicamento)

        db.session.commit()
        return "✅ Medicamentos importados com sucesso!"

    except Exception as e:
        return f"❌ Erro: {e}"


@app.route("/medicamento", methods=["POST"])
@login_required
def criar_medicamento():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()

    if not nome:
        return jsonify({"success": False, "message": "Nome é obrigatório"}), 400

    try:
        novo = Medicamento(
            nome=nome,
            principio_ativo=(data.get("principio_ativo") or "").strip() or None,
            classificacao=(data.get("classificacao") or "").strip() or None,
            via_administracao=(data.get("via_administracao") or "").strip() or None,
            dosagem_recomendada=(data.get("dosagem_recomendada") or "").strip() or None,
            frequencia=(data.get("frequencia") or "").strip() or None,
            duracao_tratamento=(data.get("duracao_tratamento") or "").strip() or None,
            observacoes=(data.get("observacoes") or "").strip() or None,
            bula=(data.get("bula") or "").strip() or None,
            created_by=current_user.id,
        )
        db.session.add(novo)
        db.session.commit()
        return jsonify({
            "success": True,
            "id": novo.id,
            "nome": novo.nome,
            "classificacao": novo.classificacao,
            "principio_ativo": novo.principio_ativo,
            "via_administracao": novo.via_administracao,
            "dosagem_recomendada": novo.dosagem_recomendada,
            "frequencia": novo.frequencia,
            "duracao_tratamento": novo.duracao_tratamento,
            "observacoes": novo.observacoes,
            "bula": novo.bula,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/medicamento/<int:med_id>", methods=["PUT", "DELETE"])
@login_required
def alterar_medicamento(med_id):
    medicamento = Medicamento.query.get_or_404(med_id)
    if medicamento.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({"success": False, "message": "Permissão negada"}), 403

    if request.method == "DELETE":
        db.session.delete(medicamento)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    campos = {
        "nome": "nome",
        "principio_ativo": "principio_ativo",
        "classificacao": "classificacao",
        "via_administracao": "via_administracao",
        "dosagem_recomendada": "dosagem_recomendada",
        "frequencia": "frequencia",
        "duracao_tratamento": "duracao_tratamento",
        "observacoes": "observacoes",
        "bula": "bula",
    }
    for key, attr in campos.items():
        if key in data:
            val = (data.get(key) or "").strip()
            setattr(medicamento, attr, val or None)

    db.session.commit()
    return jsonify({"success": True})


@app.route("/apresentacao_medicamento", methods=["POST"])
def criar_apresentacao_medicamento():
    data = request.get_json(silent=True) or {}
    medicamento_id = data.get("medicamento_id")
    forma = (data.get("forma") or "").strip()
    concentracao = (data.get("concentracao") or "").strip()

    if not medicamento_id or not forma or not concentracao:
        return jsonify({"success": False, "message": "Dados obrigatórios ausentes"}), 400

    try:
        apresentacao = ApresentacaoMedicamento(
            medicamento_id=int(medicamento_id),
            forma=forma,
            concentracao=concentracao,
        )
        db.session.add(apresentacao)
        db.session.commit()
        return jsonify({"success": True, "id": apresentacao.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/buscar_medicamentos")
def buscar_medicamentos():
    q = (request.args.get("q") or "").strip()

    # evita erro de None.lower()
    if len(q) < 2:
        return jsonify([])

    # busca por nome OU princípio ativo
    resultados = (
        Medicamento.query
        .filter(
            (Medicamento.nome.ilike(f"%{q}%")) |
            (Medicamento.principio_ativo.ilike(f"%{q}%"))
        )
        .order_by(Medicamento.nome)
        .limit(15)                     # devolve no máximo 15
        .all()
    )

    return jsonify([
        {
            "id": m.id,  # ✅ ESSENCIAL PARA O FUNCIONAMENTO
            "nome": m.nome,
            "classificacao": m.classificacao,
            "principio_ativo": m.principio_ativo,
            "via_administracao": m.via_administracao,
            "dosagem_recomendada": m.dosagem_recomendada,
            "frequencia": m.frequencia,
            "duracao_tratamento": m.duracao_tratamento,
            "observacoes": m.observacoes,
            "bula": m.bula,
        }
        for m in resultados
    ])



@app.route("/buscar_apresentacoes")
def buscar_apresentacoes():
    try:
        medicamento_id = request.args.get("medicamento_id")
        q = (request.args.get("q") or "").strip()

        if not medicamento_id or not medicamento_id.isdigit():
            return jsonify([])

        # Log for debugging
        print(f"Searching for presentations of medicamento_id={medicamento_id}, query='{q}'")

        apresentacoes = (
            ApresentacaoMedicamento.query
            .filter(
                ApresentacaoMedicamento.medicamento_id == int(medicamento_id),
                (ApresentacaoMedicamento.forma.ilike(f"%{q}%")) |
                (ApresentacaoMedicamento.concentracao.ilike(f"%{q}%"))
            )
            .all()
        )

        return jsonify([
            {"forma": a.forma, "concentracao": a.concentracao}
            for a in apresentacoes
        ])

    except Exception as e:
        print(f"[ERROR] /buscar_apresentacoes: {str(e)}")
        return jsonify({"error": str(e)}), 500



@app.route('/consulta/<int:consulta_id>/prescricao/lote', methods=['POST'])
@login_required
def salvar_prescricoes_lote(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    data = request.get_json(silent=True) or {}
    novas_prescricoes = data.get('prescricoes', [])

    for item in novas_prescricoes:
        nova = Prescricao(
            animal_id=consulta.animal_id,
            medicamento=item.get('nome'),
            dosagem=item.get('dosagem'),
            frequencia=item.get('frequencia'),
            duracao=item.get('duracao'),
            observacoes=item.get('observacoes')
        )
        db.session.add(nova)

    db.session.commit()

    historico_html = _render_prescricao_history(consulta.animal, consulta.clinica_id)
    return jsonify({'status': 'ok', 'historico_html': historico_html})


@app.route('/consulta/<int:consulta_id>/bloco_prescricao', methods=['POST'])
@login_required
def salvar_bloco_prescricao(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem prescrever.'}), 403

    dados = request.get_json(silent=True) or {}
    lista_prescricoes = dados.get('prescricoes')
    instrucoes = dados.get('instrucoes_gerais')  # 🟢 AQUI você precisa pegar o campo

    if not lista_prescricoes:
        return jsonify({'success': False, 'message': 'Nenhuma prescrição recebida.'}), 400

    clinic_id = consulta.clinica_id or current_user_clinic_id()
    if not clinic_id:
        return jsonify({'success': False, 'message': 'Consulta sem clínica definida.'}), 400

    # ⬇️ Aqui é onde a instrução geral precisa ser usada
    bloco = BlocoPrescricao(
        animal_id=consulta.animal_id,
        instrucoes_gerais=instrucoes,
        clinica_id=clinic_id,
    )
    bloco.saved_by = current_user
    bloco.saved_by_id = current_user.id
    db.session.add(bloco)
    db.session.flush()  # Garante o ID do bloco

    for item in lista_prescricoes:
        dosagem = item.get('dosagem')
        frequencia = item.get('frequencia')
        duracao = item.get('duracao')
        observacoes = item.get('observacoes')

        # Se qualquer campo estruturado estiver presente, descartamos o texto livre
        if dosagem or frequencia or duracao:
            observacoes = None
        # Caso contrário, usamos apenas o texto livre e ignoramos os outros
        elif observacoes:
            dosagem = frequencia = duracao = None

        nova = Prescricao(
            animal_id=consulta.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=dosagem,
            frequencia=frequencia,
            duracao=duracao,
            observacoes=observacoes
        )
        db.session.add(nova)

    db.session.commit()

    # Recarrega o animal para garantir que as prescrições recém-criadas
    # apareçam no histórico renderizado logo após o commit.
    animal_atualizado = Animal.query.get(consulta.animal_id)
    historico_html = _render_prescricao_history(animal_atualizado, clinic_id)
    return jsonify({
        'success': True,
        'message': 'Prescrições salvas com sucesso!',
        'html': historico_html
    })


@app.route('/bloco_prescricao/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if current_user.worker != 'veterinario':
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir prescrições.'), 403
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    clinic_id = bloco.clinica_id
    db.session.delete(bloco)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = _render_prescricao_history(animal, clinic_id)
        return jsonify(success=True, html=historico_html)

    flash('Bloco de prescrição excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/bloco_prescricao/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem editar prescrições.', 'danger')
        return redirect(url_for('index'))

    return render_template('orcamentos/editar_bloco.html', bloco=bloco)


@app.route('/bloco_prescricao/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403

    data = request.get_json(silent=True) or {}
    novos_medicamentos = data.get('medicamentos', [])
    instrucoes = data.get('instrucoes_gerais')

    # Limpa os medicamentos atuais do bloco
    for p in bloco.prescricoes:
        db.session.delete(p)

    # Adiciona os novos medicamentos ao bloco
    for item in novos_medicamentos:
        dosagem = item.get('dosagem')
        frequencia = item.get('frequencia')
        duracao = item.get('duracao')
        observacoes = item.get('observacoes')

        # Se qualquer campo estruturado estiver presente, descartamos o texto livre
        if dosagem or frequencia or duracao:
            observacoes = None
        # Caso contrário, usamos apenas o texto livre e ignoramos os outros
        elif observacoes:
            dosagem = frequencia = duracao = None

        nova = Prescricao(
            animal_id=bloco.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=dosagem,
            frequencia=frequencia,
            duracao=duracao,
            observacoes=observacoes
        )
        db.session.add(nova)

    bloco.instrucoes_gerais = instrucoes
    bloco.saved_by = current_user
    bloco.saved_by_id = current_user.id
    db.session.commit()
    return jsonify({'success': True})


@app.route('/bloco_prescricao/<int:bloco_id>/imprimir')
@login_required
def imprimir_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem imprimir prescrições.', 'danger')
        return redirect(url_for('index'))

    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else current_user
    clinica = consulta.clinica if consulta and consulta.clinica else (
        veterinario.veterinario.clinica if veterinario and getattr(veterinario, "veterinario", None) else None
    )
    salvo_por = bloco.saved_by or veterinario

    return render_template(
        'orcamentos/imprimir_bloco.html',
        bloco=bloco,
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        salvo_por=salvo_por,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
    )


@app.route('/animal/<int:animal_id>/bloco_exames', methods=['POST'])
@login_required
def salvar_bloco_exames(animal_id):
    data = request.get_json(silent=True) or {}
    exames_data = data.get('exames', [])
    observacoes_gerais = data.get('observacoes_gerais', '')

    bloco = BlocoExames(animal_id=animal_id, observacoes_gerais=observacoes_gerais)
    db.session.add(bloco)
    db.session.flush()  # Garante que bloco.id esteja disponível

    for exame in exames_data:
        exame_modelo = ExameSolicitado(
            bloco_id=bloco.id,
            nome=exame.get('nome'),
            justificativa=exame.get('justificativa'),
            status=exame.get('status', 'pendente'),
            resultado=exame.get('resultado'),
            performed_at=datetime.fromisoformat(exame['performed_at']) if exame.get('performed_at') else None,
        )
        db.session.add(exame_modelo)

    db.session.commit()
    animal = get_animal_or_404(animal_id)
    historico_html = render_template(
        'partials/historico_exames.html',
        animal=animal
    )
    return jsonify({'success': True, 'html': historico_html})



@app.route('/buscar_exames')
@login_required
def buscar_exames():
    q = request.args.get('q', '').lower()
    exames = ExameModelo.query.filter(ExameModelo.nome.ilike(f'%{q}%')).all()
    return jsonify([
        {'id': e.id, 'nome': e.nome, 'justificativa': e.justificativa}
        for e in exames
    ])


@app.route('/exame_modelo', methods=['POST'])
@login_required
def criar_exame_modelo():
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    justificativa = (data.get('justificativa') or '').strip() or None
    if not nome:
        return jsonify({'error': 'Nome é obrigatório'}), 400
    exame = ExameModelo(nome=nome, justificativa=justificativa, created_by=current_user.id)
    db.session.add(exame)
    db.session.commit()
    return jsonify({'id': exame.id, 'nome': exame.nome, 'justificativa': exame.justificativa})


@app.route('/exame_modelo/<int:exame_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_exame_modelo(exame_id):
    exame = ExameModelo.query.get_or_404(exame_id)
    if exame.created_by != current_user.id:
        return jsonify({'success': False, 'message': 'Permissão negada'}), 403

    if request.method == 'DELETE':
        db.session.delete(exame)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or exame.nome).strip()
    justificativa = data.get('justificativa', exame.justificativa)
    exame.nome = nome
    exame.justificativa = justificativa
    db.session.commit()
    return jsonify({'success': True})


@app.route('/imprimir_bloco_exames/<int:bloco_id>')
@login_required
def imprimir_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else None
    if not veterinario and current_user.is_authenticated and getattr(current_user, 'worker', None) == 'veterinario':
        veterinario = current_user
    clinica = consulta.clinica if consulta and consulta.clinica else None
    if not clinica and veterinario and getattr(veterinario, 'veterinario', None):
        vet = veterinario.veterinario
        if vet.clinica:
            clinica = vet.clinica
    if not clinica:
        clinica = getattr(animal, 'clinica', None)
    if not clinica:
        clinica_id = request.args.get('clinica_id', type=int)
        if clinica_id:
            clinica = Clinica.query.get_or_404(clinica_id)
    if not clinica:
        abort(400, description="É necessário informar uma clínica.")

    return render_template('orcamentos/imprimir_exames.html', bloco=bloco, animal=animal, tutor=tutor, clinica=clinica, veterinario=veterinario)


@app.route('/bloco_exames/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    if current_user.worker != 'veterinario':
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir blocos de exames.'), 403
        flash('Apenas veterinários podem excluir blocos de exames.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    db.session.delete(bloco)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = render_template('partials/historico_exames.html',
                                         animal=animal)
        return jsonify(success=True, html=historico_html)

    flash('Bloco de exames excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))



@app.route('/bloco_exames/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar exames.'}), 403
    return render_template('orcamentos/editar_bloco_exames.html', bloco=bloco)





@app.route('/exame/<int:exame_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_exame(exame_id):
    exame = ExameSolicitado.query.get_or_404(exame_id)

    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            db.session.delete(exame)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            print('Erro ao excluir exame:', e)
            return jsonify({'success': False, 'error': 'Erro ao excluir exame.'}), 500

    data = request.get_json(silent=True) or {}
    exame.nome = data.get('nome', exame.nome)
    exame.justificativa = data.get('justificativa', exame.justificativa)
    exame.status = data.get('status', exame.status)
    exame.resultado = data.get('resultado', exame.resultado)
    performed_at = data.get('performed_at')
    if performed_at:
        try:
            exame.performed_at = datetime.fromisoformat(performed_at)
        except ValueError:
            pass

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print('Erro ao editar exame:', e)
        return jsonify({'success': False, 'error': 'Erro ao editar exame.'}), 500






@app.route('/bloco_exames/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    dados = request.get_json(silent=True) or {}

    bloco.observacoes_gerais = dados.get('observacoes_gerais', '')

    # ---------- mapeia exames já existentes ----------
    existentes = {e.id: e for e in bloco.exames}
    enviados_ids = set()

    for ex_json in dados.get('exames', []):
        ex_id = ex_json.get('id')
        nome  = ex_json.get('nome', '').strip()
        just  = ex_json.get('justificativa', '').strip()
        status = ex_json.get('status', 'pendente')
        resultado = ex_json.get('resultado')
        performed_at_str = ex_json.get('performed_at')
        performed_at = datetime.fromisoformat(performed_at_str) if performed_at_str else None

        if not nome:                 # pulamos entradas vazias
            continue

        if ex_id and ex_id in existentes:
            # --- atualizar exame já salvo ---
            exame = existentes[ex_id]
            exame.nome = nome
            exame.justificativa = just
            exame.status = status
            exame.resultado = resultado
            exame.performed_at = performed_at
            enviados_ids.add(ex_id)
        else:
            # --- criar exame novo ---
            novo = ExameSolicitado(
                bloco=bloco,
                nome=nome,
                justificativa=just,
                status=status,
                resultado=resultado,
                performed_at=performed_at,
            )
            db.session.add(novo)

    # ---------- remover os que ficaram de fora ----------
    for ex in bloco.exames:
        if ex.id not in enviados_ids and ex.id in existentes:
            db.session.delete(ex)

    db.session.commit()

    historico_html = render_template(
        'partials/historico_exames.html',
        animal=bloco.animal
    )
    return jsonify(success=True, html=historico_html)



@app.route('/novo_atendimento')
@login_required
def novo_atendimento():
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    tutor_form = EditProfileForm()
    return render_template('agendamentos/novo_atendimento.html', tutor_form=tutor_form)


@app.route('/criar_tutor_ajax', methods=['POST'])
@login_required
def criar_tutor_ajax():
    name = request.form.get('name')
    email = request.form.get('email')

    if not name or not email:
        return jsonify({'success': False, 'message': 'Nome e e-mail são obrigatórios.'})

    tutor_existente = User.query.filter_by(email=email).first()
    if tutor_existente:
        return jsonify({'success': False, 'message': 'Já existe um tutor com este e-mail.'})

    novo_tutor = User(
        name=name,
        phone=request.form.get('phone'),
        address=request.form.get('address'),
        cpf=request.form.get('cpf'),
        rg=request.form.get('rg'),
        email=email,
        role='adotante',
        clinica_id=current_user_clinic_id(),
        added_by=current_user,
        is_private=True,

    )

    date_str = request.form.get('date_of_birth')
    if date_str:
        try:
            novo_tutor.date_of_birth = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Data de nascimento inválida.'})

    novo_tutor.set_password('123456789')  # Senha padrão

    db.session.add(novo_tutor)
    db.session.commit()

    return jsonify({'success': True, 'tutor_id': novo_tutor.id})


# app.py  – dentro da rota /novo_animal
@app.route('/novo_animal', methods=['GET', 'POST'])
@login_required
def novo_animal():
    if current_user.worker not in ['veterinario', 'colaborador']:
        flash('Apenas veterinários ou colaboradores podem cadastrar animais.', 'danger')
        return redirect(url_for('index'))

    clinic_id = current_user_clinic_id()
    accessible_clinic_ids = _viewer_accessible_clinic_ids(current_user)
    clinic_scope = (
        accessible_clinic_ids
        if len(accessible_clinic_ids) > 1
        else accessible_clinic_ids[0]
        if accessible_clinic_ids
        else None
    )
    vet_profile = getattr(current_user, 'veterinario', None)
    require_appointments = _is_specialist_veterinarian(vet_profile)
    veterinarian_scope_id = vet_profile.id if require_appointments and vet_profile else None
    current_user_id = getattr(current_user, 'id', None)

    if request.method == 'POST':
        tutor_id = request.form.get('tutor_id', type=int)
        tutor = get_user_or_404(tutor_id)

        dob_str = request.form.get('date_of_birth')
        dob = None
        idade_numero = None
        age_unit_input = request.form.get('age_unit')
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Data de nascimento inválida. Use AAAA‑MM‑DD.', 'warning')
                return redirect(url_for('ficha_tutor', tutor_id=tutor.id))
        else:
            age_input = request.form.get('age')
            if age_input:
                try:
                    idade_numero = int(age_input)
                    unidade_norm = _normalizar_unidade_idade(age_unit_input)
                    if unidade_norm == 'meses':
                        dob = date.today() - relativedelta(months=idade_numero)
                    else:
                        dob = date.today() - relativedelta(years=idade_numero)
                except ValueError:
                    flash('Idade inválida. Deve ser um número inteiro.', 'warning')
                    return redirect(url_for('ficha_tutor', tutor_id=tutor.id))

        idade_registrada = None
        if dob:
            delta = relativedelta(date.today(), dob)
            if delta.years > 0:
                idade_registrada = _formatar_idade(delta.years, 'anos')
            else:
                idade_registrada = _formatar_idade(delta.months, 'meses')
        elif idade_numero is not None:
            idade_registrada = _formatar_idade(idade_numero, age_unit_input)

        peso_str = request.form.get('peso')
        peso = float(peso_str) if peso_str else None

        neutered_val = request.form.get('neutered')
        neutered = True if neutered_val == '1' else False if neutered_val == '0' else None

        image_path = None
        if 'image' in request.files and request.files['image'].filename != '':
            image_file = request.files['image']
            filename = secure_filename(image_file.filename)
            image_path = upload_to_s3(image_file, filename)

        # IDs para espécie e raça
        species_id = request.form.get('species_id', type=int)
        breed_id = request.form.get('breed_id', type=int)

        # Carrega os objetos Species e Breed (opcional)
        species_obj = Species.query.get(species_id) if species_id else None
        breed_obj = Breed.query.get(breed_id) if breed_id else None

        # Criação do animal
        animal = Animal(
            name=request.form.get('name'),
            species_id=species_id,
            breed_id=breed_id,
            sex=request.form.get('sex'),
            date_of_birth=dob,
            age=idade_registrada,
            microchip_number=request.form.get('microchip_number'),
            peso=peso,
            health_plan=request.form.get('health_plan'),
            neutered=neutered,
            user_id=tutor.id,
            added_by_id=current_user.id,
            clinica_id=current_user_clinic_id(),
            status='disponível',
            image=image_path,
            is_alive=True,
            modo='adotado',
        )
        db.session.add(animal)
        db.session.commit()

        # Criação da consulta
        consulta = Consulta(
            animal_id=animal.id,
            created_by=current_user.id,
            clinica_id=current_user_clinic_id(),
            status='in_progress'
        )
        db.session.add(consulta)
        db.session.commit()

        # Retorna conteúdo em JSON apenas quando o cliente realmente
        # priorizar "application/json" ou quando for uma requisição AJAX.
        prefers_json = (
            request.accept_mimetypes['application/json'] >
            request.accept_mimetypes['text/html']
        )
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if prefers_json or is_ajax:
            scope_param = request.args.get('scope', 'all')
            page = request.args.get('page', 1, type=int)
            animal_search = (request.args.get('animal_search', '', type=str) or '').strip()
            animal_sort = (request.args.get('animal_sort', 'date_desc', type=str) or 'date_desc').strip()
            animais_adicionados, pagination, scope = _get_recent_animais(
                scope_param,
                page,
                clinic_id=clinic_scope,
                user_id=current_user_id,
                require_appointments=require_appointments,
                veterinario_id=veterinarian_scope_id,
                search=animal_search,
                sort_option=animal_sort,
            )
            html = render_template(
                'partials/animais_adicionados.html',
                animais_adicionados=animais_adicionados,
                pagination=pagination,
                scope=scope,
                scope_param=request.args.get('scope_param', 'scope'),
                search_param='animal_search',
                sort_param='animal_sort',
                page_param=request.args.get('page_param', 'page'),
                fetch_url=url_for('novo_animal'),
                compact=True,
                can_create_animals=True,
                new_animal_url=url_for('novo_animal'),
            )
            return jsonify(
                message='Animal cadastrado com sucesso!',
                category='success',
                html=html
            )

        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('consulta_direct', animal_id=animal.id))

    # GET: lista de animais adicionados para exibição
    page = request.args.get('page', 1, type=int)
    scope_param = request.args.get('scope', 'all')
    animal_search = (request.args.get('animal_search', '', type=str) or '').strip()
    animal_sort = (request.args.get('animal_sort', 'date_desc', type=str) or 'date_desc').strip()
    animais_adicionados, pagination, scope = _get_recent_animais(
        scope_param,
        page,
        clinic_id=clinic_scope,
        user_id=current_user_id,
        require_appointments=require_appointments,
        veterinario_id=veterinarian_scope_id,
        search=animal_search,
        sort_option=animal_sort,
    )

    # Lista de espécies e raças para os <select> do formulário
    species_list = list_species()
    breed_list = list_breeds()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (
        request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
    ):
        html = render_template(
            'partials/animais_adicionados.html',
            animais_adicionados=animais_adicionados,
            pagination=pagination,
            scope=scope,
            scope_param=request.args.get('scope_param', 'scope'),
            search_param='animal_search',
            sort_param='animal_sort',
            page_param=request.args.get('page_param', 'page'),
            fetch_url=url_for('novo_animal'),
            compact=True,
            can_create_animals=True,
            new_animal_url=url_for('novo_animal'),
        )
        return jsonify(html=html, scope=scope)

    return render_template(
        'animais/novo_animal.html',
        animais_adicionados=animais_adicionados,
        pagination=pagination,
        species_list=species_list,
        breed_list=breed_list,
        scope=scope,
        animal_search=animal_search,
        animal_sort=animal_sort,
    )





@app.route('/animal/<int:animal_id>/marcar_falecido', methods=['POST'])
@login_required
def marcar_como_falecido(animal_id):
    animal = get_animal_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem realizar essa ação.', 'danger')
        return redirect(url_for('ficha_animal', animal_id=animal.id))

    data = request.form.get('falecimento_em')

    try:
        animal.falecido_em = datetime.strptime(data, '%Y-%m-%dT%H:%M') if data else datetime.utcnow()
        animal.is_alive = False
        db.session.commit()
        flash(f'{animal.name} foi marcado como falecido.', 'success')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(
                message=f'{animal.name} foi marcado como falecido.',
                category='success',
                redirect=url_for('ficha_animal', animal_id=animal.id)
            )
    except Exception as e:
        flash(f'Erro ao marcar como falecido: {str(e)}', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=f'Erro ao marcar como falecido: {str(e)}', category='danger'), 400

    return redirect(url_for('ficha_animal', animal_id=animal.id))




@app.route('/animal/<int:animal_id>/reverter_falecimento', methods=['POST'])
@login_required
def reverter_falecimento(animal_id):
    if current_user.worker != 'veterinario':
        abort(403)

    animal = get_animal_or_404(animal_id)
    animal.is_alive = True
    animal.falecido_em = None
    db.session.commit()
    flash('Falecimento revertido com sucesso.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(
            message='Falecimento revertido com sucesso.',
            category='success',
            redirect=url_for('ficha_animal', animal_id=animal.id)
        )
    return redirect(url_for('ficha_animal', animal_id=animal.id))





@app.route('/animal/<int:animal_id>/arquivar', methods=['POST'])
@login_required
def arquivar_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir animais definitivamente.', 'danger')
        return redirect(request.referrer or url_for('index'))

    try:
        db.session.delete(animal)
        db.session.commit()
        flash(f'Animal {animal.name} excluído permanentemente.', 'success')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(
                message=f'Animal {animal.name} excluído permanentemente.',
                category='success',
                redirect=url_for('ficha_tutor', tutor_id=animal.user_id)
            )
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {str(e)}', 'danger')
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(message=f'Erro ao excluir: {str(e)}', category='danger'), 400

    return redirect(url_for('ficha_tutor', tutor_id=animal.user_id))
























@app.route('/orders/new', methods=['GET', 'POST'])
@login_required
def create_order():
    if current_user.worker != 'delivery':
        abort(403)

    order_id = session.get('current_order')
    if order_id:
        order = Order.query.get_or_404(order_id)
    else:
        order = Order(user_id=current_user.id)
        db.session.add(order)
        db.session.commit()
        session['current_order'] = order.id

    form = OrderItemForm()
    delivery_form = DeliveryRequestForm()

    if form.validate_on_submit():
        item = OrderItem(order_id=order.id,
                         item_name=form.item_name.data,
                         quantity=form.quantity.data)
        db.session.add(item)
        db.session.commit()
        flash('Item adicionado ao pedido.', 'success')
        return redirect(url_for('create_order'))

    total_quantity = sum(i.quantity for i in order.items)
    return render_template(
        'loja/create_order.html',
        form=form,
        delivery_form=delivery_form,
        order=order,
        total_quantity=total_quantity,
    )


















#Delivery routes
 


@app.route('/orders/<int:order_id>/request_delivery', methods=['POST'])
@login_required
def request_delivery(order_id):
    if current_user.worker != 'delivery':      # só entregadores podem solicitar
        abort(403)

    order = Order.query.get_or_404(order_id)

    # ─── 1. escolher um ponto de retirada ────────────────────────────────
    # Hoje: pega o primeiro ponto ATIVO
    pickup = (
        PickupLocation.query
        .filter_by(ativo=True)
        .first()
    )

    if pickup is None:
        default_addr = current_app.config.get("DEFAULT_PICKUP_ADDRESS")
        if default_addr:
            flash(f'Usando endereço de retirada padrão: {default_addr}', 'info')
        else:
            flash('Nenhum ponto de retirada cadastrado/ativo.', 'danger')
            return redirect(url_for('list_delivery_requests'))

    # ─── 2. criar a DeliveryRequest já com o pickup_id ───────────────────
    req = DeliveryRequest(
        order_id        = order.id,
        requested_by_id = current_user.id,
        status          = 'pendente',
        pickup          = pickup         # 🔑 chave aqui!
    )

    db.session.add(req)
    db.session.commit()

    session.pop('current_order', None)
    flash('Solicitação de entrega gerada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Solicitação de entrega gerada.', category='success')
    return redirect(url_for('list_delivery_requests'))


from sqlalchemy.orm import selectinload

@app.route("/delivery_requests")
@login_required
def list_delivery_requests():
    """
    •  Entregador → até 3 pendentes (mais antigas primeiro) + as dele
    •  Cliente    → só pedidos que ele criou
    """
    base = (DeliveryRequest.query
            .filter_by(archived=False)
            .order_by(DeliveryRequest.requested_at.asc())   # FIFO
            .options(
                selectinload(DeliveryRequest.order)          # evita N+1
                .selectinload(Order.user)
            ))

    # -------------------------------------------------------- ENTREGADOR
    if current_user.worker == "delivery":
        # total (para o badge)
        available_total = base.filter_by(status="pendente").count()

        # só as 3 primeiras pendentes
        available = (base.filter_by(status="pendente")
                          .limit(3)
                          .all())

        doing    = (base.filter_by(worker_id=current_user.id,
                                   status="em_andamento")
                         .order_by(DeliveryRequest.accepted_at.desc())
                         .all())

        done     = (base.filter_by(worker_id=current_user.id,
                                   status="concluida")
                         .order_by(DeliveryRequest.completed_at.desc())
                         .all())

        canceled = (base.filter_by(worker_id=current_user.id,
                                   status="cancelada")
                         .order_by(DeliveryRequest.canceled_at.desc())
                         .all())
    # -------------------------------------------------------- CLIENTE
    else:
        base = base.filter_by(requested_by_id=current_user.id)

        available_total = 0
        available = []                                          # não exibe

        doing    = base.filter_by(status="em_andamento").all()
        done     = base.filter_by(status="concluida").all()
        canceled = base.filter_by(status="cancelada").all()

    context = dict(
        available=available,
        doing=doing,
        done=done,
        canceled=canceled,
        available_total=available_total,
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_template("entregas/_delivery_sections.html", **context)
        counts = {
            "available_total": available_total,
            "doing": len(doing),
            "done": len(done),
            "canceled": len(canceled),
        }
        return jsonify(html=html, counts=counts)

    return render_template("entregas/delivery_requests.html", **context)


@app.route("/api/delivery_counts")
@login_required
def api_delivery_counts():
    """Return delivery counts for the current user."""
    base = DeliveryRequest.query.filter_by(archived=False)
    if current_user.worker == "delivery":
        available_total = base.filter_by(status="pendente").count()
        doing = base.filter_by(worker_id=current_user.id,
                              status="em_andamento").count()
        done = base.filter_by(worker_id=current_user.id,
                             status="concluida").count()
        canceled = base.filter_by(worker_id=current_user.id,
                                 status="cancelada").count()
    else:
        base = base.filter_by(requested_by_id=current_user.id)
        available_total = 0
        doing = base.filter_by(status="em_andamento").count()
        done = base.filter_by(status="concluida").count()
        canceled = base.filter_by(status="cancelada").count()

    return jsonify(
        available_total=available_total,
        doing=doing,
        done=done,
        canceled=canceled,
    )



# --- Compatibilidade admin ---------------------------------
@app.route("/admin/delivery/<int:req_id>")
@login_required
def admin_delivery_detail(req_id):
    # se quiser, mantenha restrição de admin aqui
    if not _is_admin():
        abort(403)
    return redirect(url_for("delivery_detail", req_id=req_id))

# --- Compatibilidade entregador ----------------------------
@app.route("/worker/delivery/<int:req_id>")
@login_required
def worker_delivery_detail(req_id):
    # garante que o usuário é entregador e dono da entrega
    if current_user.worker != "delivery":
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id and req.worker_id != current_user.id:
        abort(403)
    return redirect(url_for("delivery_detail", req_id=req_id))





@app.route('/delivery_requests/<int:req_id>/accept', methods=['POST'])
@login_required
def accept_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.status != 'pendente':
        flash('Solicitação não disponível.', 'warning')
        return redirect(url_for('list_delivery_requests'))
    req.status = 'em_andamento'
    req.worker_id = current_user.id
    req.accepted_at = datetime.utcnow()
    db.session.commit()
    flash('Entrega aceita.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(
            message='Entrega aceita.',
            category='success',
            redirect=url_for('worker_delivery_detail', req_id=req.id)
        )
    # ⬇️ redireciona direto ao detalhe unificado
    return redirect(url_for('delivery_detail', req_id=req.id))




@app.route('/delivery_requests/<int:req_id>/complete', methods=['POST'])
@login_required
def complete_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id != current_user.id:
        abort(403)
    req.status = 'concluida'
    req.completed_at = datetime.utcnow()
    db.session.commit()
    flash('Entrega concluída.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega concluída.', category='success')
    return redirect(url_for('list_delivery_requests'))


@app.route('/delivery_requests/<int:req_id>/cancel', methods=['POST'])
@login_required
def cancel_delivery(req_id):
    if current_user.worker != 'delivery':
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id != current_user.id:
        abort(403)
    req.status = 'cancelada'
    req.canceled_at = datetime.utcnow()
    req.canceled_by_id = current_user.id
    db.session.commit()
    flash('Entrega cancelada.', 'info')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega cancelada.', category='info')
    return redirect(url_for('list_delivery_requests'))


@app.route('/delivery_requests/<int:req_id>/buyer_cancel', methods=['POST'])
@login_required
def buyer_cancel_delivery(req_id):
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.requested_by_id != current_user.id:
        abort(403)
    if req.status in ['concluida', 'cancelada']:
        flash('Não é possível cancelar.', 'warning')
        return redirect(url_for('loja'))
    req.status = 'cancelada'
    req.canceled_at = datetime.utcnow()
    req.canceled_by_id = current_user.id
    db.session.commit()
    flash('Solicitação cancelada.', 'info')
    return redirect(url_for('loja'))


# routes_delivery.py  (ou app.py)
from sqlalchemy.orm import joinedload


@app.route("/delivery/<int:req_id>")
@login_required
def delivery_detail(req_id):
    """Detalhe da entrega para admin, entregador ou comprador."""
    req = (
        DeliveryRequest.query
        .options(
            joinedload(DeliveryRequest.pickup).joinedload(PickupLocation.endereco),
            joinedload(DeliveryRequest.order).joinedload(Order.user),
            joinedload(DeliveryRequest.worker),
        )
        .get_or_404(req_id)
    )

    order = req.order
    buyer = order.user
    items = order.items
    total = sum(i.quantity * i.product.price for i in items if i.product)

    if _is_admin():
        role = "admin"
    elif current_user.worker == "delivery":
        if req.worker_id and req.worker_id != current_user.id:
            abort(403)
        role = "worker"
    elif current_user.id == buyer.id:
        role = "buyer"
    else:
        abort(403)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    def _status_label_and_class(status):
        mapping = {
            'pendente': ('Pendente', 'bg-warning text-dark'),
            'em_andamento': ('Em andamento', 'bg-info'),
            'concluida': ('Concluída', 'bg-success'),
            'cancelada': ('Cancelada', 'bg-danger'),
        }
        return mapping.get(status, (status.capitalize(), 'bg-secondary'))

    if wants_json:
        label, badge_class = _status_label_and_class(req.status or '')
        timeline = []
        if req.requested_at:
            timeline.append({
                'key': 'requested_at',
                'label': 'Solicitado',
                'timestamp': format_datetime_brazil(req.requested_at),
            })
        if req.accepted_at:
            timeline.append({
                'key': 'accepted_at',
                'label': 'Aceito',
                'timestamp': format_datetime_brazil(req.accepted_at),
            })
        if req.completed_at:
            timeline.append({
                'key': 'completed_at',
                'label': 'Concluído',
                'timestamp': format_datetime_brazil(req.completed_at),
            })
        if req.canceled_at:
            timeline.append({
                'key': 'canceled_at',
                'label': 'Cancelado',
                'timestamp': format_datetime_brazil(req.canceled_at),
                'is_cancel': True,
            })
        worker_data = None
        if req.worker:
            worker_data = {
                'id': req.worker.id,
                'name': req.worker.name,
                'email': req.worker.email,
            }
        return jsonify({
            'success': True,
            'status': req.status,
            'status_label': label,
            'badge_class': badge_class,
            'timeline': timeline,
            'worker': worker_data,
        })

    label, badge_class = _status_label_and_class(req.status or '')

    return render_template(
        "entregas/delivery_detail.html",
        req=req,
        order=order,
        items=items,
        buyer=buyer,
        delivery_worker=req.worker,
        total=total,
        role=role,
        status_label=label,
        status_badge_class=badge_class,
    )


# routes_delivery.py  (ou app.py)

@app.route("/admin/delivery_overview")
@login_required
def delivery_overview():
    if not _is_admin():
        abort(403)

    # eager‑loading: DeliveryRequest ➜ Order ➜ User + Items + Product
    base_q = (
        DeliveryRequest.query.filter_by(archived=False)
        .options(
            joinedload(DeliveryRequest.order)
                .joinedload(Order.user),                       # comprador
            joinedload(DeliveryRequest.order)
                .joinedload(Order.items)
                .joinedload(OrderItem.product)                 # itens + produtos
        )
        .order_by(DeliveryRequest.id.desc())
    )

    per_page = 10
    open_page = request.args.get('open_page', 1, type=int)
    progress_page = request.args.get('progress_page', 1, type=int)
    completed_page = request.args.get('completed_page', 1, type=int)
    canceled_page = request.args.get('canceled_page', 1, type=int)

    open_pagination = (
        base_q.filter_by(status="pendente")
              .paginate(page=open_page, per_page=per_page, error_out=False)
    )
    progress_pagination = (
        base_q.filter_by(status="em_andamento")
              .paginate(page=progress_page, per_page=per_page, error_out=False)
    )
    completed_pagination = (
        base_q.filter_by(status="concluida")
              .paginate(page=completed_page, per_page=per_page, error_out=False)
    )
    canceled_pagination = (
        base_q.filter_by(status="cancelada")
              .paginate(page=canceled_page, per_page=per_page, error_out=False)
    )

    open_requests = open_pagination.items
    in_progress   = progress_pagination.items
    completed     = completed_pagination.items
    canceled      = canceled_pagination.items

    # produtos para o bloco de estoque
    products = Product.query.order_by(Product.name).all()

    return render_template(
        "admin/delivery_overview.html",
        products      = products,
        open_requests = open_requests,
        in_progress   = in_progress,
        completed     = completed,
        canceled      = canceled,
        open_pagination = open_pagination,
        progress_pagination = progress_pagination,
        completed_pagination = completed_pagination,
        canceled_pagination = canceled_pagination,
        open_page = open_page,
        progress_page = progress_page,
        completed_page = completed_page,
        canceled_page = canceled_page,
    )


@app.route('/admin/delivery_requests/<int:req_id>/status/<status>', methods=['POST'])
@login_required
def admin_set_delivery_status(req_id, status):
    if not _is_admin():
        abort(403)

    allowed = ['pendente', 'em_andamento', 'concluida', 'cancelada']
    if status not in allowed:
        abort(400)

    req = DeliveryRequest.query.get_or_404(req_id)
    now = datetime.utcnow()
    req.status = status

    if status == 'pendente':
        req.worker_id = None
        req.accepted_at = None
        req.canceled_at = None
        req.canceled_by_id = None
        req.completed_at = None
    elif status == 'em_andamento':
        if not req.accepted_at:
            req.accepted_at = now

        req.canceled_at = None
        req.canceled_by_id = None
        req.completed_at = None
    elif status == 'concluida':
        if not req.completed_at:
            req.completed_at = now
        if not req.accepted_at:
            req.accepted_at = now
        req.canceled_at = None
        req.canceled_by_id = None

    elif status == 'cancelada':
        req.canceled_at = now
        req.canceled_by_id = current_user.id
        req.completed_at = None

    db.session.commit()
    flash('Status atualizado.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Status atualizado.', category='success', status=status)
    return redirect(url_for('delivery_overview'))


@app.route('/admin/delivery_requests/<int:req_id>/delete', methods=['POST'])
@login_required
def admin_delete_delivery(req_id):
    if not _is_admin():
        abort(403)

    req = DeliveryRequest.query.get_or_404(req_id)
    db.session.delete(req)
    db.session.commit()
    flash('Entrega excluída.', 'info')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega excluída.', category='info', deleted=True)
    return redirect(url_for('delivery_overview'))


@app.route('/admin/delivery_requests/<int:req_id>/archive', methods=['POST'])
@login_required
def admin_archive_delivery(req_id):
    if not _is_admin():
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    req.archived = True
    db.session.commit()
    flash('Entrega arquivada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega arquivada.', category='success', archived=True)
    return redirect(url_for('delivery_overview'))


@app.route('/admin/delivery_requests/<int:req_id>/unarchive', methods=['POST'])
@login_required
def admin_unarchive_delivery(req_id):
    if not _is_admin():
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    req.archived = False
    db.session.commit()
    flash('Entrega desarquivada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega desarquivada.', category='success', archived=False)
    return redirect(url_for('delivery_archive'))


@app.route('/admin/delivery_archive')
@login_required
def delivery_archive():
    if not _is_admin():
        abort(403)

    reqs = (
        DeliveryRequest.query.filter_by(archived=True)
        .options(
            joinedload(DeliveryRequest.order)
                .joinedload(Order.user),
            joinedload(DeliveryRequest.order)
                .joinedload(Order.items)
                .joinedload(OrderItem.product)
        )
        .order_by(DeliveryRequest.id.desc())
        .all()
    )

    return render_template('admin/delivery_archive_admin.html', requests=reqs)


@app.route('/admin/data-share-logs')
@login_required
def admin_data_share_logs():
    if not _is_admin():
        abort(403)

    query = (
        DataShareLog.query.options(
            joinedload(DataShareLog.access).joinedload(DataShareAccess.user),
            joinedload(DataShareLog.access).joinedload(DataShareAccess.source_clinic),
            joinedload(DataShareLog.actor),
        )
        .join(DataShareAccess)
    )

    clinic_id = request.args.get('clinic_id', type=int)
    tutor_id = request.args.get('tutor_id', type=int)
    actor_id = request.args.get('actor_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if clinic_id:
        query = query.filter(DataShareAccess.source_clinic_id == clinic_id)
    if tutor_id:
        query = query.filter(DataShareAccess.user_id == tutor_id)
    if actor_id:
        query = query.filter(DataShareLog.actor_id == actor_id)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(DataShareLog.occurred_at >= start_dt)
        except ValueError:
            start_dt = None
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(DataShareLog.occurred_at < end_dt)
        except ValueError:
            end_dt = None

    filters = {
        'clinic_id': clinic_id or '',
        'tutor_id': tutor_id or '',
        'actor_id': actor_id or '',
        'start_date': start_date or '',
        'end_date': end_date or '',
    }
    query_args = {k: v for k, v in filters.items() if v not in ('', None)}
    csv_args = dict(query_args, format='csv')
    pdf_args = dict(query_args, format='pdf')

    export_format = request.args.get('format')
    total = query.count()
    ordered = query.order_by(DataShareLog.occurred_at.desc())

    if export_format in {'csv', 'pdf'}:
        logs = ordered.all()
        if export_format == 'csv':
            return _export_data_share_logs_csv(logs)
        return _export_data_share_logs_pdf(logs)

    logs = ordered.limit(500).all()
    return render_template(
        'admin/data_share_logs.html',
        logs=logs,
        total=total,
        filters=filters,
        query_args=query_args,
        csv_args=csv_args,
        pdf_args=pdf_args,
    )


def _export_data_share_logs_csv(logs):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID',
        'Data',
        'Evento',
        'Recurso',
        'Recurso ID',
        'Tutor ID',
        'Animal ID',
        'Clínica Origem',
        'Destinatário',
        'Destinatário ID',
        'Ator',
        'IP',
        'Endpoint',
    ])
    for log in logs:
        access = getattr(log, 'access', None)
        writer.writerow([
            log.id,
            log.occurred_at.isoformat() if log.occurred_at else '',
            log.event_type,
            log.resource_type,
            log.resource_id or '',
            access.user_id if access else '',
            access.animal_id if access else '',
            access.source_clinic_id if access else '',
            access.granted_to_type.value if access and access.granted_to_type else '',
            access.granted_to_id if access else '',
            log.actor_id or '',
            log.request_ip or '',
            log.request_path or '',
        ])
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=data-share-logs.csv'
    return response


def _export_data_share_logs_pdf(logs):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40
    for log in logs:
        access = getattr(log, 'access', None)
        lines = [
            f"{log.occurred_at:%Y-%m-%d %H:%M:%S} – {log.event_type} {log.resource_type} #{log.resource_id or '-'}",
            f"Tutor #{access.user_id if access else '-'} | Animal #{access.animal_id if access else '-'} | Clínica #{access.source_clinic_id if access else '-'}",
            f"Destinatário {access.granted_to_type.value if access and access.granted_to_type else '-'} #{access.granted_to_id if access else '-'} | Ator #{log.actor_id or '-'}",
            f"IP {log.request_ip or '-'} | {log.request_path or ''}",
        ]
        for text in lines:
            if y < 40:
                pdf.showPage()
                y = height - 40
            pdf.drawString(36, y, text[:130])
            y -= 16
        y -= 8
    pdf.save()
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='data-share-logs.pdf',
    )


@app.route('/delivery_archive')
@login_required
def delivery_archive_user():
    base = (
        DeliveryRequest.query.filter_by(archived=True)
        .options(
            joinedload(DeliveryRequest.order).joinedload(Order.user)
        )
        .order_by(DeliveryRequest.id.desc())
    )
    if current_user.worker == "delivery":
        reqs = base.filter_by(worker_id=current_user.id).all()
    else:
        reqs = base.filter_by(requested_by_id=current_user.id).all()
    return render_template('entregas/delivery_archive.html', requests=reqs)



# ========================================================
#  PAGAMENTO – Mercado Pago (Checkout Pro PIX) - CORRECTED
# ========================================================

import hmac, hashlib, mercadopago
from decimal   import Decimal
from functools import cache
from datetime  import datetime, timedelta

from flask import (
    render_template, redirect, url_for, flash, session,
    request, jsonify, abort, current_app
)
from flask_login import login_required, current_user

from forms import AddToCartForm, CheckoutForm, CartAddressForm  # Added CheckoutForm for CSRF

# ─────────────────────────────────────────────────────────
#  SDK (lazy – lê token do config)
# ─────────────────────────────────────────────────────────
@cache
def mp_sdk():
    return mercadopago.SDK(current_app.config["MERCADOPAGO_ACCESS_TOKEN"])


# Caches for frequently requested lists
@cache
def list_species():
    """Return a lightweight list of species as dictionaries."""
    return [
        {"id": sp.id, "name": sp.name}
        for sp in Species.query.order_by(Species.name).all()
    ]


@cache
def list_breeds():
    """Return a lightweight list of breeds as dictionaries."""
    return [
        {"id": br.id, "name": br.name, "species_id": br.species_id}
        for br in Breed.query.order_by(Breed.name).all()
    ]


def _normalize_clinic_ids(clinic_scope):
    """Return a sanitized list of clinic IDs from ``clinic_scope``."""

    if not clinic_scope:
        return []
    if isinstance(clinic_scope, (list, tuple, set)):
        return [cid for cid in clinic_scope if cid]
    return [clinic_scope] if clinic_scope else []


def _is_specialist_veterinarian(vet_profile):
    """Return ``True`` if the veterinarian acts only as a specialist."""

    if not vet_profile:
        return False

    primary = getattr(vet_profile, 'clinica_id', None)
    associated = getattr(vet_profile, 'clinicas', None) or []
    return primary is None and bool(associated)


def _veterinarian_accessible_clinic_ids(vet_profile):
    """Return clinic IDs a veterinarian can operate in."""

    if not vet_profile:
        return []

    clinic_ids = []
    primary = getattr(vet_profile, 'clinica_id', None)
    if primary:
        clinic_ids.append(primary)

    for clinic in getattr(vet_profile, 'clinicas', []) or []:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _viewer_accessible_clinic_ids(viewer):
    """Return clinic IDs accessible to ``viewer`` preserving priority order."""

    clinic_ids = []
    if not viewer:
        return clinic_ids

    viewer_clinic = getattr(viewer, 'clinica_id', None)
    if viewer_clinic and viewer_clinic not in clinic_ids:
        clinic_ids.append(viewer_clinic)

    vet_profile = getattr(viewer, 'veterinario', None)
    for clinic_id in _veterinarian_accessible_clinic_ids(vet_profile):
        if clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _get_recent_animais(
    scope,
    page,
    clinic_id=None,
    user_id=None,
    require_appointments=False,
    veterinario_id=None,
    search=None,
    sort_option=None,
):
    """Return recent animals and pagination metadata for dashboards."""

    from models import Species, Breed

    resolved_scope = 'mine' if scope == 'mine' else 'all'
    effective_user_id = user_id or (getattr(current_user, 'id', None))
    clinic_ids = _normalize_clinic_ids(clinic_id)

    if resolved_scope == 'mine' and not effective_user_id:
        resolved_scope = 'all'

    base_query = Animal.query.filter(Animal.removido_em == None)

    search_value = (search or '').strip().lower()
    sort_value = (sort_option or 'date_desc').strip().lower() or 'date_desc'
    per_page = 9

    species_alias = aliased(Species)
    breed_alias = aliased(Breed)

    def apply_search_filters(query):
        if not search_value:
            return query
        term = f"%{search_value}%"
        return (
            query.outerjoin(species_alias, Animal.species)
            .outerjoin(breed_alias, Animal.breed)
            .filter(
                or_(
                    func.lower(func.coalesce(Animal.name, '')).like(term),
                    func.lower(func.coalesce(Animal.description, '')).like(term),
                    func.lower(func.coalesce(species_alias.name, '')).like(term),
                    func.lower(func.coalesce(breed_alias.name, '')).like(term),
                    func.lower(func.coalesce(Animal.modo, '')).like(term),
                )
            )
        )

    def apply_sorting(query, last_reference=None):
        query = query.order_by(None)

        name_column = func.lower(func.coalesce(Animal.name, ''))
        age_expr = case(
            (Animal.date_of_birth != None, Animal.date_of_birth),
            else_=Animal.date_added,
        )

        if sort_value == 'name_asc':
            return query.order_by(name_column.asc(), Animal.id.asc())
        if sort_value == 'name_desc':
            return query.order_by(name_column.desc(), Animal.id.asc())
        if sort_value == 'date_asc':
            if last_reference is not None:
                return query.order_by(last_reference.asc(), Animal.id.asc())
            return query.order_by(Animal.date_added.asc(), Animal.id.asc())
        if sort_value == 'date_desc':
            if last_reference is not None:
                return query.order_by(last_reference.desc(), Animal.id.desc())
            return query.order_by(Animal.date_added.desc(), Animal.id.desc())
        if sort_value == 'age_asc':
            return query.order_by(age_expr.desc(), Animal.date_added.desc(), Animal.id.desc())
        if sort_value == 'age_desc':
            return query.order_by(age_expr.asc(), Animal.date_added.desc(), Animal.id.desc())

        # Fallback to recent first when sort option is unknown
        if last_reference is not None:
            return query.order_by(last_reference.desc(), Animal.id.desc())
        return query.order_by(Animal.date_added.desc(), Animal.id.desc())

    last_reference = None

    if resolved_scope == 'mine' and effective_user_id:
        query = base_query
        if clinic_ids and not require_appointments:
            query = query.filter(Animal.clinica_id.in_(clinic_ids))

        if require_appointments and clinic_ids:
            appointment_exists = (
                db.session.query(Appointment.id)
                .filter(
                    Appointment.animal_id == Animal.id,
                    Appointment.clinica_id.in_(clinic_ids),
                )
            )
            if veterinario_id:
                appointment_exists = appointment_exists.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            query = query.filter(appointment_exists.exists())

        consultas_exist = (
            db.session.query(Consulta.id)
            .filter(
                Consulta.animal_id == Animal.id,
                Consulta.created_by == effective_user_id,
            )
        )

        query = query.filter(
            or_(
                Animal.added_by_id == effective_user_id,
                consultas_exist.exists(),
            )
        )
    elif clinic_ids:
        if require_appointments:
            last_appt_query = (
                db.session.query(
                    Appointment.animal_id,
                    func.max(Appointment.scheduled_at).label('last_at'),
                )
                .filter(Appointment.clinica_id.in_(clinic_ids))
            )
            if veterinario_id:
                last_appt_query = last_appt_query.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            last_appt = last_appt_query.group_by(Appointment.animal_id).subquery()
            query = base_query.join(last_appt, Animal.id == last_appt.c.animal_id)
            last_reference = last_appt.c.last_at
        else:
            last_appt = (
                db.session.query(
                    Appointment.animal_id,
                    func.max(Appointment.scheduled_at).label('last_at'),
                )
                .filter(Appointment.clinica_id.in_(clinic_ids))
                .group_by(Appointment.animal_id)
                .subquery()
            )
            query = (
                base_query.outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
                .filter(Animal.clinica_id.in_(clinic_ids))
            )
            last_reference = func.coalesce(last_appt.c.last_at, Animal.date_added)
    else:
        query = base_query
        if effective_user_id:
            query = query.filter(Animal.added_by_id == effective_user_id)

    query = apply_search_filters(query)
    query = apply_sorting(query, last_reference)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return pagination.items, pagination, resolved_scope


def _get_recent_tutores(
    scope,
    page,
    clinic_id=None,
    user_id=None,
    require_appointments=False,
    veterinario_id=None,
    search=None,
    sort_option=None,
):
    """Return recent tutors and pagination metadata for dashboards."""

    resolved_scope = 'mine' if scope == 'mine' else 'all'
    effective_user_id = user_id or getattr(current_user, 'id', None)
    clinic_ids = _normalize_clinic_ids(clinic_id)

    if resolved_scope == 'mine' and not effective_user_id:
        resolved_scope = 'all'

    search_value = (search or '').strip().lower()
    sort_value = (sort_option or 'name_asc').strip().lower() or 'name_asc'
    per_page = 9

    def apply_search_filters(query):
        if not search_value:
            return query
        term = f"%{search_value}%"
        return query.filter(
            or_(
                func.lower(func.coalesce(User.name, '')).like(term),
                func.lower(func.coalesce(User.email, '')).like(term),
                func.lower(func.coalesce(User.cpf, '')).like(term),
                func.lower(func.coalesce(User.phone, '')).like(term),
            )
        )

    def apply_sorting(query):
        query = query.order_by(None)
        name_column = func.lower(func.coalesce(User.name, ''))
        age_expr = case(
            (User.date_of_birth != None, User.date_of_birth),
            else_=User.created_at,
        )

        if sort_value == 'name_desc':
            return query.order_by(name_column.desc(), User.id.asc())
        if sort_value == 'date_desc':
            return query.order_by(User.created_at.desc(), User.id.desc())
        if sort_value == 'date_asc':
            return query.order_by(User.created_at.asc(), User.id.asc())
        if sort_value == 'age_desc':
            return query.order_by(age_expr.asc(), User.created_at.desc(), User.id.desc())
        if sort_value == 'age_asc':
            return query.order_by(age_expr.desc(), User.created_at.desc(), User.id.desc())

        return query.order_by(name_column.asc(), User.id.asc())

    if resolved_scope == 'mine' and effective_user_id:
        base_query = (
            User.query.filter(User.created_at != None)
            .filter(_user_visibility_clause(clinic_scope=clinic_ids))
        )
        if clinic_ids and not require_appointments:
            base_query = base_query.filter(User.clinica_id.in_(clinic_ids))

        if require_appointments and clinic_ids:
            appointment_exists = (
                db.session.query(Appointment.id)
                .filter(
                    Appointment.tutor_id == User.id,
                    Appointment.clinica_id.in_(clinic_ids),
                )
            )
            if veterinario_id:
                appointment_exists = appointment_exists.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            base_query = base_query.filter(appointment_exists.exists())

        consultas_exist = (
            db.session.query(Consulta.id)
            .join(Animal, Consulta.animal_id == Animal.id)
            .filter(
                Consulta.created_by == effective_user_id,
                Animal.user_id == User.id,
            )
        )

        query = base_query.filter(
            or_(
                User.added_by_id == effective_user_id,
                consultas_exist.exists(),
            )
        )
    elif clinic_ids:
        query = (
            User.query.filter(User.created_at != None)
            .filter(_user_visibility_clause(clinic_scope=clinic_ids))
        )
        if require_appointments:
            appointment_exists = (
                db.session.query(Appointment.id)
                .filter(
                    Appointment.tutor_id == User.id,
                    Appointment.clinica_id.in_(clinic_ids),
                )
            )
            if veterinario_id:
                appointment_exists = appointment_exists.filter(
                    Appointment.veterinario_id == veterinario_id
                )
            query = query.filter(appointment_exists.exists())
        else:
            query = query.filter(User.clinica_id.in_(clinic_ids))
    else:
        query = User.query.filter(User.created_at != None)
        if effective_user_id:
            query = query.filter(User.added_by_id == effective_user_id)

    query = apply_search_filters(query)
    query = apply_sorting(query)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return pagination.items, pagination, resolved_scope


@cache
def list_rations():
    return TipoRacao.query.order_by(TipoRacao.marca.asc()).all()


# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────
PENDING_TIMEOUT = timedelta(minutes=20)

def _limpa_pendencia(payment):
    """
    Se o pagamento pendente ainda for válido (PENDING, não expirado e
    com init_point), devolve‑o. Caso contrário zera a chave na sessão.
    """
    if not payment:
        session.pop("last_pending_payment", None)
        return None

    expirou   = (datetime.utcnow() - payment.created_at) > PENDING_TIMEOUT
    sem_link  = not getattr(payment, "init_point", None)

    if payment.status != PaymentStatus.PENDING or expirou or sem_link:
        session.pop("last_pending_payment", None)
        return None
    return payment


def _mp_item_payload(it):
    """Return a Mercado Pago item dict with description."""
    if it.product:
        description = it.product.description or it.product.name
        return {
            "id": str(it.product.id),
            "title": it.product.name,
            "description": description,
            "category_id": "others",
            "quantity": int(it.quantity),
            "unit_price": float(it.product.price),
        }
    # Fallback in case product record was removed
    return {
        "id": str(it.id),
        "title": it.item_name,
        "description": it.item_name,
        "category_id": "others",
        "quantity": int(it.quantity),
        "unit_price": float(it.unit_price or 0),
    }

# Helper to fetch the current order from session and verify ownership
def _get_current_order():
    order_id = session.get("current_order")
    if not order_id:
        return None
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        session.pop("current_order", None)
        abort(403)
    # Se o pedido já possui um pagamento concluído não deve ser reutilizado
    if order.payment and order.payment.status == PaymentStatus.COMPLETED:
        session.pop("current_order", None)
        return None
    return order


def _setup_checkout_form(form, preserve_selected=True):
    """Preenche o CheckoutForm com os endereços do usuário."""
    default_address = None
    if current_user.endereco and current_user.endereco.full:
        default_address = current_user.endereco.full

    form.address_id.choices = []
    if default_address:
        form.address_id.choices.append((0, default_address))
    for addr in current_user.saved_addresses:
        form.address_id.choices.append((addr.id, addr.address))
    form.address_id.choices.append((-1, 'Novo endereço'))

    if preserve_selected and form.address_id.data is not None:
        selected = form.address_id.data
    else:
        selected = session.get("last_address_id")

    available = [c[0] for c in form.address_id.choices]
    try:
        selected = int(selected)
    except (TypeError, ValueError):
        selected = None
    if selected not in available:
        selected = None
    if selected is not None:
        form.address_id.data = selected
    elif available:
        form.address_id.data = available[0]

    return default_address



from flask import session, render_template, request, jsonify
from flask_login import login_required


def _build_loja_query(search_term: str, filtro: str):
    query = Product.query
    if search_term:
        like = f"%{search_term}%"
        query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

    if filtro == "lowStock":
        query = query.filter(Product.stock < 5)
    elif filtro == "new":
        query = query.order_by(Product.id.desc())
    elif filtro == "priceLow":
        query = query.order_by(Product.price.asc())
    elif filtro == "priceHigh":
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.name)

    return query


@app.route("/loja")
@login_required
def loja():
    pagamento_pendente = None
    payment_id = session.get("last_pending_payment")
    if payment_id:
        payment = Payment.query.get(payment_id)
        if payment and payment.status.name == "PENDING":
            pagamento_pendente = payment

    search_term = request.args.get("q", "").strip()
    filtro = request.args.get("filter", "all")
    page = request.args.get("page", 1, type=int)
    per_page = 12

    query = _build_loja_query(search_term, filtro)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    produtos = pagination.items
    form = AddToCartForm()

    # Verifica se há pedidos anteriores
    has_orders = Order.query.filter_by(user_id=current_user.id).first() is not None

    return render_template(
        "loja/loja.html",
        products=produtos,
        pagination=pagination,
        pagamento_pendente=pagamento_pendente,
        form=form,
        has_orders=has_orders,
        selected_filter=filtro,
        search_term=search_term,
    )


@app.route("/loja/data")
@login_required
def loja_data():
    search_term = request.args.get("q", "").strip()
    filtro = request.args.get("filter", "all")
    page = request.args.get("page", 1, type=int)
    per_page = 12

    query = _build_loja_query(search_term, filtro)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    produtos = pagination.items
    form = AddToCartForm()

    if request.args.get("format") == "json":
        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "image_url": p.image_url,
            }
            for p in produtos
        ]
        return jsonify(
            products=products_data,
            page=pagination.page,
            total_pages=pagination.pages,
            has_next=pagination.has_next,
            has_prev=pagination.has_prev,
        )

    html = render_template(
        "partials/_product_grid.html",
        products=produtos,
        pagination=pagination,
        form=form,
        selected_filter=filtro,
        search_term=search_term,
    )
    return html


@app.route('/produto/<int:product_id>', methods=['GET', 'POST'])
@login_required
def produto_detail(product_id):
    """Exibe detalhes do produto e permite edições para administradores."""
    product = Product.query.options(db.joinedload(Product.extra_photos)).get_or_404(product_id)

    update_form = ProductUpdateForm(obj=product, prefix='upd')
    photo_form = ProductPhotoForm(prefix='photo')
    form = AddToCartForm()

    if _is_admin():
        if update_form.validate_on_submit() and update_form.submit.data:
            product.name = update_form.name.data
            product.description = update_form.description.data
            product.price = float(update_form.price.data or 0)
            product.stock = update_form.stock.data
            product.mp_category_id = (update_form.mp_category_id.data or "others").strip()
            if update_form.image_upload.data:
                file = update_form.image_upload.data
                filename = secure_filename(file.filename)
                image_url = upload_to_s3(file, filename, folder='products')
                if image_url:
                    product.image_url = image_url
            db.session.commit()
            flash('Produto atualizado.', 'success')
            return redirect(url_for('produto_detail', product_id=product.id))

        if photo_form.validate_on_submit() and photo_form.submit.data:
            file = photo_form.image.data
            filename = secure_filename(file.filename)
            image_url = upload_to_s3(file, filename, folder='products')
            if image_url:
                db.session.add(ProductPhoto(product_id=product.id, image_url=image_url))
                db.session.commit()
                flash('Foto adicionada.', 'success')
            return redirect(url_for('produto_detail', product_id=product.id))

    return render_template(
        'loja/product_detail.html',
        product=product,
        update_form=update_form,
        photo_form=photo_form,
        form=form,
        is_admin=_is_admin(),
    )




# --------------------------------------------------------
#  ADICIONAR AO CARRINHO
# --------------------------------------------------------
@app.route("/carrinho/adicionar/<int:product_id>", methods=["POST"])
@login_required
def adicionar_carrinho(product_id):
    product = Product.query.get_or_404(product_id)
    form = AddToCartForm()
    if not form.validate_on_submit():
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify(success=False, error='invalid form'), 400
        return redirect(url_for("loja"))

    order = _get_current_order()
    if not order:
        order = Order(user_id=current_user.id)
        db.session.add(order)
        db.session.commit()
        session["current_order"] = order.id

    qty = form.quantity.data or 1

    # Verifica se o produto já está no carrinho para somar as quantidades
    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    if item:
        item.quantity += qty
    else:
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            item_name=product.name,
            unit_price=Decimal(str(product.price or 0)),
            quantity=qty,
        )
        db.session.add(item)

    db.session.commit()
    flash("Produto adicionado ao carrinho.", "success")
    if 'application/json' in request.headers.get('Accept', ''):
        total_value = order.total_value()
        total_qty = sum(i.quantity for i in order.items)
        return jsonify(
            message="Produto adicionado ao carrinho.",
            category="success",
            item_id=item.id,
            item_quantity=item.quantity,
            order_total=total_value,
            order_total_formatted=f"R$ {total_value:.2f}",
            order_quantity=total_qty,
        )
    return redirect(url_for("loja"))


# --------------------------------------------------------
#  ATUALIZAR QUANTIDADE DO ITEM DO CARRINHO
# --------------------------------------------------------
@app.route("/carrinho/increase/<int:item_id>", methods=["POST"])
@login_required
def aumentar_item_carrinho(item_id):
    """Incrementa a quantidade de um item no carrinho."""
    order = _get_current_order()
    item = OrderItem.query.get_or_404(item_id)
    if item.order_id != order.id:
        abort(404)
    item.quantity += 1
    db.session.commit()
    flash("Quantidade atualizada", "success")
    if 'application/json' in request.headers.get('Accept', ''):
        total_value = order.total_value()
        total_qty = sum(i.quantity for i in order.items)
        return jsonify(
            message="Quantidade atualizada",
            category="success",
            item_id=item.id,
            item_quantity=item.quantity,
            order_total=total_value,
            order_total_formatted=f"R$ {total_value:.2f}",
            order_quantity=total_qty,
        )
    return redirect(url_for("ver_carrinho"))


@app.route("/carrinho/decrease/<int:item_id>", methods=["POST"])
@login_required
def diminuir_item_carrinho(item_id):
    """Diminui a quantidade de um item; remove se chegar a zero."""
    order = _get_current_order()
    item = OrderItem.query.get_or_404(item_id)
    if item.order_id != order.id:
        abort(404)
    item.quantity -= 1
    if item.quantity <= 0:
        db.session.delete(item)
        db.session.commit()
        message = "Produto removido"
        category = "info"
        item_qty = 0
    else:
        db.session.commit()
        message = "Quantidade atualizada"
        category = "success"
        item_qty = item.quantity
    flash(message, category)
    if 'application/json' in request.headers.get('Accept', ''):
        total_value = order.total_value()
        total_qty = sum(i.quantity for i in order.items)
        payload = {
            "message": message,
            "category": category,
            "item_id": item.id,
            "item_quantity": item_qty,
            "order_total": total_value,
            "order_total_formatted": f"R$ {total_value:.2f}",
            "order_quantity": total_qty,
        }
        if total_qty == 0:
            payload["redirect"] = url_for("ver_carrinho")
        return jsonify(**payload)
    return redirect(url_for("ver_carrinho"))


# --------------------------------------------------------
#  VER CARRINHO
# --------------------------------------------------------
from forms import CheckoutForm, EditAddressForm

@app.route("/carrinho", methods=["GET", "POST"])
@login_required
def ver_carrinho():
    # 1) Cria o form
    form = CheckoutForm()
    addr_form = CartAddressForm()
    default_address = _setup_checkout_form(form)

    # 2) Verifica se há um pagamento pendente
    pagamento_pendente = None
    payment_id = session.get('last_pending_payment')
    if payment_id:
        pagamento = Payment.query.get(payment_id)
        if pagamento and pagamento.status == PaymentStatus.PENDING:
            pagamento_pendente = pagamento

    # 3) Busca o pedido atual
    order = _get_current_order()

    # 4) Renderiza o carrinho passando o form
    return render_template(
        'loja/carrinho.html',
        form=form,
        order=order,
        pagamento_pendente=pagamento_pendente,
        default_address=default_address,
        saved_addresses=current_user.saved_addresses,
        addr_form=addr_form
    )


@app.route('/carrinho/salvar_endereco', methods=['POST'])
@login_required
def carrinho_salvar_endereco():
    """Salva um novo endereço informado no carrinho."""
    form = CartAddressForm()
    if not form.validate_on_submit():
        flash('Preencha os campos obrigatórios do endereço.', 'warning')
        return redirect(url_for('ver_carrinho'))

    tmp_addr = Endereco(
        cep=form.cep.data,
        rua=form.rua.data,
        numero=form.numero.data,
        complemento=form.complemento.data,
        bairro=form.bairro.data,
        cidade=form.cidade.data,
        estado=form.estado.data,
    )
    address_text = tmp_addr.full
    sa = SavedAddress(user_id=current_user.id, address=address_text)
    db.session.add(sa)
    db.session.commit()
    session['last_address_id'] = sa.id
    flash('Endereço salvo com sucesso.', 'success')

    return redirect(url_for('ver_carrinho'))


@app.route("/checkout/confirm", methods=["POST"])
@login_required
def checkout_confirm():
    """Mostra um resumo antes de redirecionar ao pagamento externo."""
    form = CheckoutForm()
    _setup_checkout_form(form, preserve_selected=True)
    if not form.validate_on_submit():
        return redirect(url_for("ver_carrinho"))

    order = _get_current_order()
    if not order or not order.items:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("ver_carrinho"))

    # Determine the address text based on the chosen option
    selected_address = None
    if form.address_id.data is not None and form.address_id.data >= 0:
        if form.address_id.data == 0 and current_user.endereco and current_user.endereco.full:
            selected_address = current_user.endereco.full
        else:
            sa = SavedAddress.query.filter_by(
                id=form.address_id.data,
                user_id=current_user.id
            ).first()
            if sa:
                selected_address = sa.address

    if not selected_address and form.shipping_address.data:
        selected_address = form.shipping_address.data

    if not selected_address and current_user.endereco and current_user.endereco.full:
        selected_address = current_user.endereco.full

    return render_template(
        "loja/checkout_confirm.html",
        form=form,
        order=order,
        selected_address=selected_address,
    )

















#inicio pagamento


# --------------------------------------------------------
#  CHECKOUT (CSRF PROTECTED)
# --------------------------------------------------------
# ──────────────────────────────────────────────────────────────────────────────
# 1)  /checkout  –  cria Preference + Payment “pending”
# ──────────────────────────────────────────────────────────────────────────────
import json, logging, os
from flask import current_app, redirect, url_for, flash, session
from flask_login import login_required, current_user

@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    current_app.logger.setLevel(logging.DEBUG)

    form = CheckoutForm()
    _setup_checkout_form(form, preserve_selected=True)
    if not form.validate_on_submit():
        return redirect(url_for("ver_carrinho"))

    # 1️⃣ pedido atual do carrinho
    order = _get_current_order()
    if not order or not order.items:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("ver_carrinho"))

    address_text = None
    if form.address_id.data is not None and form.address_id.data >= 0:
        if form.address_id.data == 0 and current_user.endereco and current_user.endereco.full:
            address_text = current_user.endereco.full
        else:
            sa = SavedAddress.query.filter_by(id=form.address_id.data, user_id=current_user.id).first()
            if sa:
                address_text = sa.address
        session["last_address_id"] = form.address_id.data
    elif form.address_id.data == -1:
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')
        if any([cep, rua, cidade, estado]):
            tmp_addr = Endereco(
                cep=cep,
                rua=rua,
                numero=numero,
                complemento=complemento,
                bairro=bairro,
                cidade=cidade,
                estado=estado
            )
            address_text = tmp_addr.full
            sa = SavedAddress(user_id=current_user.id, address=address_text)
            db.session.add(sa)
            db.session.flush()
            session["last_address_id"] = sa.id
    if not address_text and form.shipping_address.data:
        address_text = form.shipping_address.data
        sa = SavedAddress(user_id=current_user.id, address=address_text)
        db.session.add(sa)
        db.session.flush()
        session["last_address_id"] = sa.id
    if not address_text and current_user.endereco and current_user.endereco.full:
        address_text = current_user.endereco.full
        session["last_address_id"] = 0 if address_text else None

    order.shipping_address = address_text
    db.session.add(order)
    db.session.commit()

    # 2️⃣ grava Payment PENDING
    payment = Payment(
        user_id=current_user.id,
        order_id=order.id,
        method=PaymentMethod.PIX,          # ou outro enum que prefira
        status=PaymentStatus.PENDING,
    )
    payment.amount = Decimal(str(order.total_value()))
    db.session.add(payment)
    db.session.flush()                     # gera payment.id sem fechar a transação
    payment.external_reference = str(payment.id)
    db.session.commit()

    # 3️⃣ itens do Preference
    # O Mercado Pago recomenda enviar um código no campo
    # ``items.id`` para agilizar a verificação antifraude.

    items = [
        {
            "id":          str(it.product.id),
            "title":       it.product.name,
            "description": it.product.description or it.product.name,
            "category_id": it.product.mp_category_id or "others",
            "quantity":    int(it.quantity),
            "unit_price":  float(it.product.price),
        }
        for it in order.items
    ]


    # 4️⃣ payload Preference

    # Separa o nome em partes para extrair primeiro e último nome
    name = (current_user.name or "").strip()
    parts = name.split()
    if parts:
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else first_name
    else:
        # Quando o usuário não tem um nome salvo, usa o prefixo do e‑mail
        first_name = current_user.email.split("@")[0]
        last_name = first_name
    payer_info = {
        "first_name": first_name,
        "last_name": last_name,

        "email": current_user.email,
    }
    if current_user.phone:
        digits = re.sub(r"\D", "", current_user.phone)
        if digits.startswith("55") and len(digits) > 11:
            digits = digits[2:]
        if len(digits) >= 10:
            payer_info["phone"] = {
                "area_code": digits[:2],
                "number": digits[2:],
            }
        else:
            payer_info["phone"] = {"number": digits}
    if current_user.cpf:
        payer_info["identification"] = {
            "type": "CPF",
            "number": re.sub(r"\D", "", current_user.cpf),
        }
    if order.shipping_address:
        payer_info["address"] = {"street_name": order.shipping_address}
        m = re.search(r"CEP\s*(\d{5}-?\d{3})", order.shipping_address)
        if m:
            payer_info["address"]["zip_code"] = m.group(1)

    preference_data = {
        "items": items,
        "external_reference": payment.external_reference,
        "notification_url":   url_for("notificacoes_mercado_pago", _external=True),
        "payment_methods":    {"installments": 1},
        "statement_descriptor": current_app.config.get("MERCADOPAGO_STATEMENT_DESCRIPTOR"),
        "binary_mode": current_app.config.get("MERCADOPAGO_BINARY_MODE", False),
        "back_urls": {
            s: url_for("payment_status", payment_id=payment.id, _external=True)
            for s in ("success", "failure", "pending")
        },
        "auto_return": "approved",
        "payer": payer_info,
    }
    current_app.logger.debug("MP Preference Payload:\n%s",
                             json.dumps(preference_data, indent=2, ensure_ascii=False))

    # 5️⃣ cria Preference no Mercado Pago
    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception:
        current_app.logger.exception("Erro de conexão com Mercado Pago")
        flash("Falha ao conectar com Mercado Pago.", "danger")
        return redirect(url_for("ver_carrinho"))

    if resp.get("status") != 201:
        current_app.logger.error("MP error (HTTP %s): %s", resp["status"], resp)
        flash("Erro ao iniciar pagamento.", "danger")
        return redirect(url_for("ver_carrinho"))

    pref = resp["response"]
    payment.transaction_id = str(pref["id"])       # preference_id
    payment.init_point     = pref["init_point"]
    db.session.commit()

    session["last_pending_payment"] = payment.id
    return redirect(pref["init_point"])






import re
import hmac
import hashlib
from flask import current_app, request, jsonify
from sqlalchemy.exc import SQLAlchemyError

# Regular expression for parsing X-Signature header
_SIG_RE = re.compile(r"(?i)(?:ts=(\d+),\s*)?v1=([a-f0-9]{64})")

def verify_mp_signature(req, secret: str) -> bool:
    """
    Verify the signature of a Mercado Pago webhook notification.
    
    Args:
        req: Flask request object
        secret: Webhook secret key from Mercado Pago
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not secret:
        current_app.logger.warning(
            "Webhook sem chave – verificacao impossivel"
        )
        return False

    x_signature = req.headers.get("X-Signature", "")
    m = _SIG_RE.search(x_signature)
    if not m:
        current_app.logger.warning("X-Signature mal-formado: %s", x_signature)
        return False

    ts, sig_mp = m.groups()
    if not ts or not sig_mp:
        current_app.logger.warning("Missing ts or v1 in X-Signature")
        return False

    x_request_id = req.headers.get("x-request-id", "")
    if not x_request_id:
        current_app.logger.warning("Missing x-request-id header")
        return False

    # Determine ID based on notification type
    topic = req.args.get("topic")
    type_ = req.args.get("type")
    if topic == "payment" or type_ == "payment":
        data_id = req.args.get("data.id", "")
    elif topic == "merchant_order":
        data_id = req.args.get("id", "")
    else:
        current_app.logger.warning("Unknown notification type")
        return False

    if not data_id:
        current_app.logger.warning("Missing ID in query parameters")
        return False

    # Construct manifest
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"

    # Compute HMAC-SHA256
    calc = hmac.new(
        secret.strip().encode(),
        manifest.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calc, sig_mp):
        current_app.logger.warning("Invalid signature: calc=%s recv=%s", calc, sig_mp)
        return False
    return True

@app.route("/notificacoes", methods=["POST", "GET"])
def notificacoes_mercado_pago():
    if request.method == "GET":
        return jsonify(status="pong"), 200

    secret = current_app.config.get("MERCADOPAGO_WEBHOOK_SECRET", "")
    if not verify_mp_signature(request, secret):
        return jsonify(error="invalid signature"), 400

    # Check notification type
    notification_type = request.args.get("type") or request.args.get("topic")
    if notification_type != "payment":
        current_app.logger.info("Ignoring non-payment notification: %s", notification_type)
        return jsonify(status="ignored"), 200

    # Extract mp_id
    data = request.get_json(silent=True) or {}
    mp_id = (data.get("data", {}).get("id") or  # v1
             data.get("resource", "").split("/")[-1])  # v2

    if not mp_id:
        return jsonify(status="ignored"), 200

    # Query payment
    resp = mp_sdk().payment().get(mp_id)
    if resp.get("status") == 404:
        with db.session.begin():
            p = PendingWebhook.query.filter_by(mp_id=mp_id).first()
            if not p:
                db.session.add(PendingWebhook(mp_id=mp_id))
        return jsonify(status="retry_later"), 202
    if resp.get("status") != 200:
        return jsonify(error="api error"), 500

    # Process payment info
    info = resp["response"]
    status = info["status"]
    extref = info.get("external_reference")
    if not extref:
        return jsonify(status="ignored"), 200

    # Update database
    status_map = {
        "approved": PaymentStatus.COMPLETED,
        "authorized": PaymentStatus.COMPLETED,
        "pending": PaymentStatus.PENDING,
        "in_process": PaymentStatus.PENDING,
        "in_mediation": PaymentStatus.PENDING,
        "rejected": PaymentStatus.FAILED,
        "cancelled": PaymentStatus.FAILED,
        "refunded": PaymentStatus.FAILED,
        "expired": PaymentStatus.FAILED,
    }

    bloco_id = None
    if extref and extref.startswith('bloco_orcamento-'):
        try:
            bloco_id = int(extref.split('-', 1)[1])
        except (ValueError, TypeError):
            bloco_id = None

    bloco_status_map = {
        'approved': 'paid',
        'authorized': 'paid',
        'pending': 'pending',
        'in_process': 'pending',
        'in_mediation': 'pending',
        'rejected': 'failed',
        'cancelled': 'failed',
        'refunded': 'failed',
        'expired': 'failed',
    }

    try:
        with db.session.begin():
            pay = Payment.query.filter_by(external_reference=extref).first()
            bloco = BlocoOrcamento.query.get(bloco_id) if bloco_id else None
            if not pay and not bloco:
                current_app.logger.warning("Payment %s not found for external_reference %s", mp_id, extref)
                return jsonify(error="payment not found"), 404

            if pay:
                pay.status = status_map.get(status, PaymentStatus.PENDING)
                pay.mercado_pago_id = mp_id

                if pay.external_reference and pay.external_reference.startswith('vet-membership-'):
                    _sync_veterinarian_membership_payment(pay)

                if pay.status == PaymentStatus.COMPLETED and pay.order_id:
                    if not DeliveryRequest.query.filter_by(order_id=pay.order_id).first():
                        db.session.add(DeliveryRequest(
                            order_id=pay.order_id,
                            requested_by_id=pay.user_id,
                            status="pendente",
                        ))

            if bloco:
                bloco.payment_status = bloco_status_map.get(status, 'pending')

    except SQLAlchemyError as e:
        current_app.logger.exception("DB error: %s", e)
        return jsonify(error="db failure"), 500

    return jsonify(status="updated"), 200






















































# ——— 3) Página de status final —————————————————————————————————————————
# --------------------------------------------------------
# 3)  /payment_status/<payment_id>   – página pós‑pagamento
#      (versão sem QR‑Code)
# --------------------------------------------------------
from flask import render_template, request, jsonify

def _refresh_mp_status(payment: Payment) -> None:
    if payment.status != PaymentStatus.PENDING:
        return
    resp = mp_sdk().payment().get(payment.mercado_pago_id or payment.transaction_id)
    if resp.get("status") != 200:
        current_app.logger.warning("MP lookup falhou: %s", resp)
        return
    mp = resp["response"]
    mapping = {
        "approved":   PaymentStatus.COMPLETED,
        "authorized": PaymentStatus.COMPLETED,
        "pending":    PaymentStatus.PENDING,
        "in_process": PaymentStatus.PENDING,
        "in_mediation": PaymentStatus.PENDING,
        "rejected":   PaymentStatus.FAILED,
        "cancelled":  PaymentStatus.FAILED,
        "refunded":   PaymentStatus.FAILED,
        "expired":    PaymentStatus.FAILED,
    }
    new_status = mapping.get(mp["status"], PaymentStatus.PENDING)
    if new_status != payment.status:
        payment.status = new_status
        if payment.external_reference and payment.external_reference.startswith('vet-membership-'):
            _sync_veterinarian_membership_payment(payment)
        db.session.commit()


@app.route("/pagamento/<status>")
def legacy_pagamento(status):
    extref = request.args.get("external_reference")
    payment = None

    if extref and extref.isdigit():
        payment = Payment.query.get(int(extref))

    if not payment:
        mp_id = (request.args.get("collection_id") or
                 request.args.get("payment_id"))
        if mp_id:
            payment = Payment.query.filter(
                (Payment.mercado_pago_id == mp_id) |
                (Payment.transaction_id == mp_id)
            ).first()

    if not payment:
        pref_id = request.args.get("preference_id")
        if pref_id:
            payment = Payment.query.filter_by(transaction_id=pref_id).first()

    mp_status = (request.args.get("status") or
                 request.args.get("collection_status") or
                 status)

    if not payment:
        if mp_status in {"success", "completed", "approved", "sucesso"}:
            return render_template("auth/sucesso.html")
        abort(404)

    return redirect(url_for("payment_status", payment_id=payment.id, status=mp_status))


@app.route("/order/<int:order_id>/edit_address", methods=["GET", "POST"])
@login_required
def edit_order_address(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        abort(403)

    form = EditAddressForm(obj=order)
    if form.validate_on_submit():
        order.shipping_address = form.shipping_address.data
        db.session.commit()
        flash("Endereço atualizado.", "success")
        if order.payment:
            return redirect(url_for("payment_status", payment_id=order.payment.id))
        return redirect(url_for("loja"))

    payment_id = order.payment.id if order.payment else None
    return render_template("loja/edit_address.html", form=form, payment_id=payment_id)


@app.route("/payment_status/<int:payment_id>")
def payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if current_user.is_authenticated and payment.user_id != current_user.id:
        abort(403)

    result  = request.args.get("status") or payment.status.name.lower()

    form = CheckoutForm()

    delivery_req = (DeliveryRequest.query
                    .filter_by(order_id=payment.order_id)
                    .first())

    # endpoint a usar
    endpoint = "delivery_detail"  # agora é um só

    # Limpa o pedido da sessão quando o pagamento foi concluído
    if result in {"success", "completed", "approved"}:
        session.pop("current_order", None)

    order = payment.order if (
        current_user.is_authenticated and payment.user_id == current_user.id
    ) else None

    delivery_estimate = None
    if order and order.created_at:
        delivery_estimate = order.created_at + timedelta(days=5)

    cancel_url = (
        url_for('buyer_cancel_delivery', req_id=delivery_req.id)
        if delivery_req and delivery_req.status not in ['cancelada', 'concluida']
        else None
    )
    edit_address_url = url_for('edit_order_address', order_id=payment.order_id) if order else None

    return render_template(
        "loja/payment_status.html",
        payment          = payment,
        result           = result,
        req_id           = delivery_req.id if delivery_req else None,
        req_endpoint     = endpoint,
        order            = order,
        form             = form,
        delivery_estimate= delivery_estimate,
        cancel_url       = cancel_url,
        edit_address_url = edit_address_url,
    )


@app.route("/api/payment_status/<int:payment_id>")
def api_payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if current_user.is_authenticated and payment.user_id != current_user.id:
        abort(403)
    return jsonify(status=payment.status.name)



#fim pagamento


from sqlalchemy.orm import joinedload


@app.route("/minhas-compras")
@login_required
def minhas_compras():
    page = request.args.get("page", 1, type=int)
    per_page = 20

    pagination = (Order.query
                  .join(Order.payment)
                  .options(joinedload(Order.payment))
                  .filter(Order.user_id == current_user.id,
                          Payment.status == PaymentStatus.COMPLETED)
                  .order_by(Order.created_at.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))

    return render_template(
        "loja/minhas_compras.html",
        orders=pagination.items,
        pagination=pagination,
        PaymentStatus=PaymentStatus,
    )



@app.route("/api/minhas-compras")
@login_required
def api_minhas_compras():
    orders = (Order.query
              .options(joinedload(Order.payment))
              .filter_by(user_id=current_user.id)
              .order_by(Order.created_at.desc())
              .all())
    data = [
        {
            "id": o.id,
            "data": o.created_at.isoformat(),
            "valor": float((getattr(o.payment, "amount", None) if o.payment else None) or o.total_value()),
            "status": (o.payment.status.value if o.payment else "Pendente"),
        }
        for o in orders
    ]
    return jsonify(data)


@app.route("/pedido/<int:order_id>")
@login_required
def pedido_detail(order_id):
    order = (Order.query
             .options(
                 joinedload(Order.items).joinedload(OrderItem.product),
                 joinedload(Order.user),
                 joinedload(Order.payment),
                 joinedload(Order.delivery_requests).joinedload(DeliveryRequest.pickup).joinedload(PickupLocation.endereco),
                 joinedload(Order.delivery_requests).joinedload(DeliveryRequest.worker)
             )
             .get_or_404(order_id))

    if not _is_admin() and order.user_id != current_user.id:
        abort(403)

    req = order.delivery_requests[0] if order.delivery_requests else None
    items = order.items
    buyer = order.user
    delivery_worker = req.worker if req else None
    total = sum(i.quantity * i.product.price for i in items if i.product)

    if _is_admin():
        role = "admin"
    elif current_user.worker == "delivery":
        if req and req.worker_id and req.worker_id != current_user.id:
            abort(403)
        role = "worker"
    elif current_user.id == buyer.id:
        role = "buyer"
    else:
        abort(403)

    form = CheckoutForm()
    edit_address_url = url_for("edit_order_address", order_id=order.id)
    cancel_url = (
        url_for("buyer_cancel_delivery", req_id=req.id)
        if req and req.status not in ['cancelada', 'concluida']
        else None
    )

    return render_template(
        "entregas/delivery_detail.html",
        req=req,
        order=order,
        items=items,
        buyer=buyer,
        delivery_worker=delivery_worker,
        total=total,
        role=role,
        form=form,
        edit_address_url=edit_address_url,
        cancel_url=cancel_url,
    )

























@app.route('/appointments/<int:appointment_id>/confirmation')
@login_required
def appointment_confirmation(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.tutor_id != current_user.id:
        abort(403)
    return render_template('agendamentos/appointment_confirmation.html', appointment=appointment)


@app.route('/appointments', methods=['GET', 'POST'])
@login_required
def appointments():
    from models import ExamAppointment, Veterinario, Clinica, User

    view_as = request.args.get('view_as')
    worker = getattr(current_user, 'worker', None)
    is_vet = is_veterinarian(current_user)
    if worker == 'veterinario' and not is_vet:
        worker = 'tutor'
    calendar_access_scope = get_calendar_access_scope(current_user)

    def _redirect_to_current_appointments():
        query_args = request.args.to_dict(flat=False)
        if query_args:
            return redirect(url_for('appointments', **query_args))
        return redirect(url_for('appointments'))
    if view_as:
        allowed_views = {'veterinario', 'colaborador', 'tutor'}
        if current_user.role == 'admin' and view_as in allowed_views:
            worker = view_as
        elif current_user.role != 'admin':
            # Non-admin users can only request the view matching their own role.
            user_view = worker if worker in allowed_views else 'tutor'
            if view_as not in allowed_views or view_as != user_view:
                flash('Você não tem permissão para acessar essa visão de agenda.', 'warning')
                return redirect(url_for('appointments'))

    agenda_users = []
    agenda_veterinarios = []
    agenda_colaboradores = []
    admin_selected_veterinario_id = None
    admin_selected_colaborador_id = None
    admin_default_selection_value = ''
    selected_colaborador = None
    calendar_summary_vets = []
    calendar_summary_clinic_ids = []
    calendar_redirect_url = None

    def _vet_clinic_ids(vet):
        return calendar_access_scope.get_veterinarian_clinic_ids(vet)

    if current_user.role == 'admin':
        agenda_users = User.query.order_by(User.name).all()
        agenda_veterinarios = (
            Veterinario.query.join(User).order_by(User.name).all()
        )
        agenda_colaboradores = (
            User.query.filter(User.worker == 'colaborador')
            .order_by(User.name)
            .all()
        )
        default_vet = getattr(current_user, 'veterinario', None)
        if default_vet and getattr(default_vet, 'id', None):
            admin_default_selection_value = f'veterinario:{default_vet.id}'

    admin_selected_view = (
        worker
        if current_user.role == 'admin' and worker in {'veterinario', 'colaborador'}
        else None
    )

    if request.method == 'POST' and worker not in ['veterinario', 'colaborador', 'admin']:
        abort(403)
    if worker == 'veterinario' and is_vet:
        if current_user.role == 'admin':
            veterinario_id_arg = request.args.get(
                'veterinario_id', type=int
            )
            if veterinario_id_arg:
                veterinario = next(
                    (v for v in agenda_veterinarios if v.id == veterinario_id_arg),
                    None,
                )
                if not veterinario:
                    veterinario = Veterinario.query.get_or_404(
                        veterinario_id_arg
                    )
            elif agenda_veterinarios:
                veterinario = agenda_veterinarios[0]
            else:
                abort(404)
            admin_selected_veterinario_id = veterinario.id
        else:
            veterinario = current_user.veterinario
        if not veterinario:
            abort(404)
        vet_user_id = getattr(veterinario, "user_id", None)
        clinic_ids = []
        if getattr(veterinario, "clinica_id", None):
            clinic_ids.append(veterinario.clinica_id)
        for clinica in getattr(veterinario, "clinicas", []) or []:
            clinica_id = getattr(clinica, "id", None)
            if clinica_id and clinica_id not in clinic_ids:
                clinic_ids.append(clinica_id)
        clinic_ids = calendar_access_scope.filter_clinic_ids(clinic_ids)
        associated_clinics = (
            Clinica.query.filter(Clinica.id.in_(clinic_ids)).all()
            if clinic_ids
            else []
        )
        calendar_summary_clinic_ids = clinic_ids
        if getattr(veterinario, "id", None) is not None:
            calendar_summary_vets = [
                {
                    'id': veterinario.id,
                    'name': veterinario.user.name
                    if getattr(veterinario, "user", None)
                    else None,
                    'full_name': getattr(getattr(veterinario, 'user', None), 'name', None),
                    'specialty_list': getattr(veterinario, 'specialty_list', None),
                    'is_specialist': bool(getattr(veterinario, 'specialty_list', None)),
                    'clinic_ids': _vet_clinic_ids(veterinario),
                }
            ]
        include_colleagues = bool(clinic_ids)
        if include_colleagues:
            colleagues_source = []
            if current_user.role == 'admin' and agenda_veterinarios:
                colleagues_source.extend(
                    v
                    for v in agenda_veterinarios
                    if getattr(v, 'clinica_id', None) in clinic_ids
                )
            elif clinic_ids:
                colleagues_source.extend(
                    Veterinario.query.filter(
                        Veterinario.clinica_id.in_(clinic_ids)
                    ).all()
                )
            for clinica in associated_clinics:
                owner_vet = getattr(getattr(clinica, 'owner', None), 'veterinario', None)
                if owner_vet and getattr(owner_vet, 'id', None) is not None:
                    colleagues_source.append(owner_vet)
                colleagues_source.extend(
                    vet
                    for vet in (getattr(clinica, 'veterinarios_associados', []) or [])
                    if getattr(vet, 'id', None) is not None
                )
            known_ids = {entry['id'] for entry in calendar_summary_vets}
            for colleague in unique_items_by_id(colleagues_source):
                colleague_id = getattr(colleague, 'id', None)
                if (
                    not colleague_id
                    or colleague_id in known_ids
                    or not calendar_access_scope.allows_veterinarian(colleague)
                ):
                    continue
                calendar_summary_vets.append(
                    {
                        'id': colleague_id,
                        'name': colleague.user.name
                        if getattr(colleague, 'user', None)
                        else None,
                        'full_name': getattr(getattr(colleague, 'user', None), 'name', None),
                        'specialty_list': getattr(colleague, 'specialty_list', None),
                        'is_specialist': bool(getattr(colleague, 'specialty_list', None)),
                        'clinic_ids': _vet_clinic_ids(colleague),
                    }
                )
                known_ids.add(colleague_id)
        calendar_redirect_url = url_for(
            'appointments', view_as='veterinario', veterinario_id=veterinario.id
        )
        query_args = request.args.to_dict()
        if current_user.role == 'admin':
            query_args['view_as'] = 'veterinario'
            query_args['veterinario_id'] = veterinario.id
        appointments_url = url_for('appointments', **query_args)
        schedule_form = VetScheduleForm(prefix='schedule')
        if _is_admin():
            vets_for_choices = agenda_veterinarios or Veterinario.query.all()
        else:
            vets_for_choices = [veterinario]
        schedule_form.veterinario_id.choices = [
            (v.id, v.user.name) for v in vets_for_choices
        ]
        appointment_form = None
        combined_vets = []
        clinic_vet_ids = set()
        specialist_ids = set()
        if not clinic_ids:
            flash(
                'Você precisa estar vinculado a uma clínica para agendar novas consultas.',
                'warning',
            )
            if request.method == 'POST' and 'appointment-submit' in request.form:
                return redirect(appointments_url)
        else:
            appointment_form = AppointmentForm(
                is_veterinario=True,
                clinic_ids=clinic_ids,
                prefix='appointment',
                require_clinic_scope=True,
            )
            clinic_vets = (
                Veterinario.query.filter(
                    Veterinario.clinica_id.in_(clinic_ids)
                ).all()
            ) if clinic_ids else []
            for clinica in associated_clinics:
                owner_vet = getattr(getattr(clinica, 'owner', None), 'veterinario', None)
                if owner_vet and getattr(owner_vet, 'id', None) is not None:
                    clinic_vets.append(owner_vet)
            specialists = []
            for clinica in associated_clinics:
                specialists.extend(
                    vet
                    for vet in (getattr(clinica, 'veterinarios_associados', []) or [])
                    if getattr(vet, 'id', None) is not None
                )
            combined_vets = unique_items_by_id(clinic_vets + specialists + [veterinario])

            def _vet_sort_key(vet):
                name = getattr(getattr(vet, 'user', None), 'name', '') or ''
                return name.lower()

            combined_vets = sorted(
                (
                    vet
                    for vet in combined_vets
                    if getattr(vet, 'id', None) is not None
                ),
                key=_vet_sort_key,
            )
            combined_vets = calendar_access_scope.filter_veterinarians(combined_vets)
            if not combined_vets:
                combined_vets = [veterinario]

            clinic_vet_ids = {
                getattr(vet, 'id', None) for vet in clinic_vets if getattr(vet, 'id', None)
            }
            specialist_ids = {
                getattr(vet, 'id', None)
                for vet in specialists
                if getattr(vet, 'id', None)
            }

            def _vet_label(vet):
                base_name = getattr(getattr(vet, 'user', None), 'name', None)
                label = base_name or f"Profissional #{getattr(vet, 'id', '—')}"
                vet_id = getattr(vet, 'id', None)
                if vet_id in specialist_ids and vet_id not in clinic_vet_ids:
                    return f"{label} (Especialista)"
                return label

            appointment_form.veterinario_id.choices = [
                (vet.id, _vet_label(vet)) for vet in combined_vets
            ]
            calendar_summary_vets = [
                {
                    'id': vet.id,
                    'name': _vet_label(vet),
                    'label': _vet_label(vet),
                    'full_name': getattr(getattr(vet, 'user', None), 'name', None),
                    'specialty_list': getattr(vet, 'specialty_list', None),
                    'is_specialist': getattr(vet, 'id', None) in specialist_ids
                    and getattr(vet, 'id', None) not in clinic_vet_ids,
                    'clinic_ids': _vet_clinic_ids(vet),
                }
                for vet in combined_vets
            ]
            calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)
            if not calendar_summary_vets:
                calendar_summary_vets = [
                    {
                        'id': veterinario.id,
                        'name': _vet_label(veterinario),
                        'label': _vet_label(veterinario),
                        'full_name': getattr(getattr(veterinario, 'user', None), 'name', None),
                        'specialty_list': getattr(veterinario, 'specialty_list', None),
                        'is_specialist': getattr(veterinario, 'id', None) in specialist_ids
                        and getattr(veterinario, 'id', None) not in clinic_vet_ids,
                        'clinic_ids': _vet_clinic_ids(veterinario),
                    }
                ]
            if request.method == 'GET':
                appointment_form.veterinario_id.data = veterinario.id
        if schedule_form.submit.data and not _is_admin():
            raw_vet_id = request.form.get(schedule_form.veterinario_id.name)
            if raw_vet_id is None:
                abort(403)
            try:
                submitted_vet_id = int(raw_vet_id)
            except (TypeError, ValueError):
                abort(403)
            if submitted_vet_id != veterinario.id:
                abort(403)

        if schedule_form.submit.data and schedule_form.validate_on_submit():
            if not _is_admin() and schedule_form.veterinario_id.data != veterinario.id:
                abort(403)

            vet_id = schedule_form.veterinario_id.data
            for dia in schedule_form.dias_semana.data:
                if has_schedule_conflict(
                    vet_id,
                    dia,
                    schedule_form.hora_inicio.data,
                    schedule_form.hora_fim.data,
                ):
                    flash(f'Conflito de horário em {dia}.', 'danger')
                    return redirect(appointments_url)
            added = False
            for dia in schedule_form.dias_semana.data:
                if has_schedule_conflict(
                    schedule_form.veterinario_id.data,
                    dia,
                    schedule_form.hora_inicio.data,
                    schedule_form.hora_fim.data,
                ):
                    flash(f'Horário em {dia} conflita com um existente.', 'danger')
                    continue
                horario = VetSchedule(
                    veterinario_id=vet_id,
                    dia_semana=dia,
                    hora_inicio=schedule_form.hora_inicio.data,
                    hora_fim=schedule_form.hora_fim.data,
                    intervalo_inicio=schedule_form.intervalo_inicio.data,
                    intervalo_fim=schedule_form.intervalo_fim.data,
                )
                db.session.add(horario)
                added = True
            if added:
                db.session.commit()
                flash('Horário salvo com sucesso.', 'success')
            else:
                flash('Nenhum novo horário foi salvo.', 'info')
            return redirect(appointments_url)
        if appointment_form and appointment_form.validate_on_submit():
            scheduled_at_local = datetime.combine(
                appointment_form.date.data, appointment_form.time.data
            )
            if not is_slot_available(
                appointment_form.veterinario_id.data,
                scheduled_at_local,
                kind=appointment_form.kind.data,
            ):
                flash(
                    'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                    'danger'
                )
            else:
                animal = get_animal_or_404(appointment_form.animal_id.data)
                tutor_id = animal.user_id
                requires_plan = current_app.config.get(
                    'REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT', False
                )
                if requires_plan and not Appointment.has_active_subscription(
                    animal.id, tutor_id
                ):
                    flash(
                        'O animal não possui uma assinatura de plano de saúde ativa.',
                        'danger',
                    )
                else:
                    scheduled_at = (
                        scheduled_at_local
                        .replace(tzinfo=BR_TZ)
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                    current_vet = getattr(current_user, 'veterinario', None)
                    selected_vet_id = appointment_form.veterinario_id.data
                    same_user = current_vet and current_vet.id == selected_vet_id
                    selected_vet = next(
                        (
                            vet
                            for vet in combined_vets
                            if getattr(vet, 'id', None) == selected_vet_id
                        ),
                        None,
                    )
                    if not selected_vet and selected_vet_id:
                        selected_vet = Veterinario.query.get(selected_vet_id)
                    selected_clinic_id = (
                        getattr(selected_vet, 'clinica_id', None)
                        if selected_vet
                        else None
                    )
                    appt = Appointment(
                        animal_id=animal.id,
                        tutor_id=tutor_id,
                        veterinario_id=selected_vet_id,
                        scheduled_at=scheduled_at,
                        clinica_id=selected_clinic_id or animal.clinica_id,
                        notes=appointment_form.reason.data,
                        kind=appointment_form.kind.data,
                        status='accepted' if same_user else 'scheduled',
                        created_by=current_user.id,
                        created_at=datetime.utcnow(),
                    )
                    db.session.add(appt)
                    db.session.commit()
                    flash('Agendamento criado com sucesso.', 'success')
            return redirect(appointments_url)
        horarios = VetSchedule.query.filter_by(
            veterinario_id=veterinario.id
        ).all()
        weekday_order = {
            'Segunda': 0,
            'Terça': 1,
            'Quarta': 2,
            'Quinta': 3,
            'Sexta': 4,
            'Sábado': 5,
            'Domingo': 6,
        }
        horarios.sort(key=lambda h: weekday_order.get(h.dia_semana, 7))
        horarios_grouped = []
        for h in horarios:
            if not horarios_grouped or horarios_grouped[-1]['dia'] != h.dia_semana:
                horarios_grouped.append({'dia': h.dia_semana, 'itens': []})
            horarios_grouped[-1]['itens'].append(h)
        now = datetime.utcnow()
        today_start_local = datetime.now(BR_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_start_utc = (
            today_start_local.astimezone(timezone.utc).replace(tzinfo=None)
        )
        start_str = request.args.get('start')
        end_str = request.args.get('end')
        if start_str and end_str:
            start_dt = datetime.fromisoformat(start_str)
            end_dt = datetime.fromisoformat(end_str) + timedelta(days=1)
            restrict_to_today = False
        else:
            today = date.today()
            start_dt = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
            end_dt = start_dt + timedelta(days=7)
            restrict_to_today = True
        start_dt_utc, end_dt_utc = local_date_range_to_utc(start_dt, end_dt)
        upcoming_start = start_dt_utc or today_start_utc
        if restrict_to_today and today_start_utc:
            upcoming_start = max(upcoming_start, today_start_utc)

        appointment_scope_conditions = [
            Appointment.veterinario_id == veterinario.id
        ]
        if vet_user_id:
            appointment_scope_conditions.append(Appointment.created_by == vet_user_id)
        if len(appointment_scope_conditions) == 1:
            appointment_scope_filter = appointment_scope_conditions[0]
        else:
            appointment_scope_filter = or_(*appointment_scope_conditions)

        pending_consultas = (
            Appointment.query.filter(Appointment.status == 'scheduled')
            .filter(Appointment.scheduled_at > now)
            .filter(appointment_scope_filter)
            .order_by(Appointment.scheduled_at)
            .all()
        )
        appointments_pending_consults = []
        pending_consults_for_me = []
        pending_consults_waiting_others = []
        for appt in pending_consultas:
            appt.time_left = (appt.scheduled_at - timedelta(hours=2)) - now
            kind = appt.kind or ('retorno' if appt.consulta_id else 'consulta')
            if kind == 'general':
                kind = 'consulta'
            item = {'kind': kind, 'appt': appt}
            appointments_pending_consults.append(item)
            if appt.veterinario_id == veterinario.id:
                pending_consults_for_me.append(item)
            else:
                pending_consults_waiting_others.append(item)

        from models import ExamAppointment, Message, BlocoExames

        exam_pending = (
            ExamAppointment.query.filter_by(specialist_id=veterinario.id, status='pending')
            .filter(ExamAppointment.scheduled_at > now)
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        exams_pending_to_accept = []
        for ex in exam_pending:
            ex.time_left = ex.confirm_by - now
            if ex.time_left.total_seconds() <= 0:
                ex.status = 'canceled'
                msg = Message(
                    sender_id=vet_user_id or getattr(current_user, "id", None),
                    receiver_id=ex.requester_id,
                    animal_id=ex.animal_id,
                    content=f"Especialista não aceitou exame para {ex.animal.name}. Reagende com outro profissional.",
                )
                db.session.add(msg)
                db.session.commit()
            else:
                exams_pending_to_accept.append(ex)

        if vet_user_id:
            pending_requested_exams = (
                ExamAppointment.query.filter(
                    ExamAppointment.requester_id == vet_user_id,
                    ExamAppointment.status.in_(['pending', 'confirmed']),
                    ExamAppointment.specialist_id != veterinario.id,
                    ExamAppointment.scheduled_at > now,
                )
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
        else:
            pending_requested_exams = []
        exams_waiting_other_vets = []
        status_styles = {
            'pending': {
                'badge_class': 'bg-warning text-dark',
                'icon_class': 'text-warning',
                'status_label': 'Aguardando confirmação',
                'show_time_left': True,
            },
            'confirmed': {
                'badge_class': 'bg-success',
                'icon_class': 'text-success',
                'status_label': 'Confirmado',
                'show_time_left': False,
            },
        }
        default_style = {
            'badge_class': 'bg-secondary',
            'icon_class': 'text-secondary',
            'status_label': 'Status desconhecido',
            'show_time_left': False,
        }
        for ex in pending_requested_exams:
            if ex.confirm_by:
                ex.time_left = ex.confirm_by - now
            else:
                ex.time_left = timedelta(0)
            style = status_styles.get(ex.status, default_style)
            include_exam = ex.status == 'confirmed'
            if ex.status == 'pending':
                include_exam = ex.time_left.total_seconds() > 0
            if not include_exam:
                continue
            exams_waiting_other_vets.append(
                {
                    'exam': ex,
                    'status': ex.status,
                    'status_label': style['status_label'],
                    'badge_class': style['badge_class'],
                    'icon_class': style['icon_class'],
                    'show_time_left': style['show_time_left'] and ex.time_left.total_seconds() > 0,
                }
            )

        accepted_consultas_in_range = (
            Appointment.query.filter(Appointment.status == 'accepted')
            .filter(Appointment.scheduled_at >= start_dt_utc)
            .filter(Appointment.scheduled_at < end_dt_utc)
            .filter(appointment_scope_filter)
            .order_by(Appointment.scheduled_at)
            .all()
        )
        future_cutoff = max(now, upcoming_start) if upcoming_start else now
        past_accepted_consultas = []
        upcoming_consultas = []
        for appt in accepted_consultas_in_range:
            scheduled_at = appt.scheduled_at
            if scheduled_at and scheduled_at >= future_cutoff:
                upcoming_consultas.append(appt)
            else:
                past_accepted_consultas.append(appt)

        upcoming_exams = (
            ExamAppointment.query.filter_by(specialist_id=veterinario.id, status='confirmed')
            .filter(ExamAppointment.scheduled_at >= future_cutoff)
            .filter(ExamAppointment.scheduled_at < end_dt_utc)
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        appointments_upcoming = []
        for appt in upcoming_consultas:
            kind = appt.kind or ('retorno' if appt.consulta_id else 'consulta')
            if kind == 'general':
                kind = 'consulta'
            appointments_upcoming.append({'kind': kind, 'appt': appt})
        for exam in upcoming_exams:
            appointments_upcoming.append({'kind': 'exame', 'appt': exam})
        appointments_upcoming.sort(key=lambda x: x['appt'].scheduled_at)

        appointments_upcoming_for_me = []
        appointments_upcoming_requested = []
        for item in appointments_upcoming:
            if item['kind'] == 'exame':
                appointments_upcoming_for_me.append(item)
                continue
            appt = item['appt']
            if getattr(appt, 'veterinario_id', None) == veterinario.id:
                appointments_upcoming_for_me.append(item)
            elif vet_user_id and getattr(appt, 'created_by', None) == vet_user_id:
                appointments_upcoming_requested.append(item)

        consulta_filters = [Consulta.status == 'finalizada']
        scope_filters = []
        if vet_user_id:
            scope_filters.append(Consulta.created_by == vet_user_id)
        if veterinario.clinica_id:
            scope_filters.append(Consulta.clinica_id == veterinario.clinica_id)
        if scope_filters:
            consulta_filters.append(or_(*scope_filters))

        consultas_query = (
            Consulta.query.outerjoin(Appointment, Consulta.appointment)
            .options(
                joinedload(Consulta.animal).joinedload(Animal.owner),
                joinedload(Consulta.veterinario),
                joinedload(Consulta.appointment)
                .joinedload(Appointment.animal)
                .joinedload(Animal.owner),
            )
            .filter(*consulta_filters)
        )

        consulta_timestamp_expr = case(
            (Consulta.finalizada_em.isnot(None), Consulta.finalizada_em),
            (Appointment.scheduled_at.isnot(None), Appointment.scheduled_at),
            else_=Consulta.created_at,
        )
        if start_dt_utc is not None:
            consultas_query = consultas_query.filter(consulta_timestamp_expr >= start_dt_utc)
        if end_dt_utc is not None:
            consultas_query = consultas_query.filter(consulta_timestamp_expr < end_dt_utc)

        consultas_finalizadas = consultas_query.all()

        consulta_animal_ids = {c.animal_id for c in consultas_finalizadas}
        exam_blocks_by_consulta = defaultdict(list)
        exam_blocks_by_animal = defaultdict(list)
        if consulta_animal_ids:
            blocos_query = (
                BlocoExames.query.options(joinedload(BlocoExames.exames))
                .filter(BlocoExames.animal_id.in_(consulta_animal_ids))
            )
            for bloco in blocos_query.all():
                exam_blocks_by_animal[bloco.animal_id].append(bloco)
                consulta_ref = getattr(bloco, 'consulta_id', None)
                if consulta_ref:
                    exam_blocks_by_consulta[consulta_ref].append(bloco)

        schedule_events = []

        def _consulta_timestamp(consulta_obj):
            if consulta_obj.finalizada_em:
                return consulta_obj.finalizada_em
            if consulta_obj.appointment and consulta_obj.appointment.scheduled_at:
                return consulta_obj.appointment.scheduled_at
            return consulta_obj.created_at

        for consulta in consultas_finalizadas:
            timestamp = _consulta_timestamp(consulta)
            if not timestamp or not (start_dt_utc <= timestamp < end_dt_utc):
                continue
            relevant_blocks = exam_blocks_by_consulta.get(consulta.id)
            if not relevant_blocks:
                relevant_blocks = [
                    bloco
                    for bloco in exam_blocks_by_animal.get(consulta.animal_id, [])
                    if bloco.data_criacao
                    and timestamp
                    and bloco.data_criacao.date() == timestamp.date()
                ]
            exam_summary = []
            exam_ids = []
            for bloco in relevant_blocks or []:
                for exame in bloco.exames:
                    exam_ids.append(exame.id)
                    exam_summary.append(
                        {
                            'nome': exame.nome,
                            'status': exame.status,
                            'justificativa': exame.justificativa,
                            'bloco_id': bloco.id,
                        }
                    )
            schedule_events.append(
                {
                    'kind': 'consulta_finalizada',
                    'timestamp': timestamp,
                    'animal': consulta.animal,
                    'consulta': consulta,
                    'consulta_id': consulta.id,
                    'appointment': consulta.appointment,
                    'exam_summary': exam_summary,
                    'exam_blocks': relevant_blocks or [],
                    'exam_ids': exam_ids,
                }
            )

        for appt in past_accepted_consultas:
            if not appt.scheduled_at or not (start_dt_utc <= appt.scheduled_at < end_dt_utc):
                continue
            schedule_events.append(
                {
                    'kind': 'consulta_aceita',
                    'timestamp': appt.scheduled_at,
                    'animal': appt.animal,
                    'consulta': appt.consulta,
                    'consulta_id': appt.consulta_id,
                    'appointment': appt,
                    'exam_summary': [],
                    'exam_blocks': [],
                    'exam_ids': [],
                }
            )

        for item in appointments_upcoming:
            if item['kind'] == 'retorno':
                appt = item['appt']
                schedule_events.append(
                    {
                        'kind': 'retorno',
                        'timestamp': appt.scheduled_at,
                        'animal': appt.animal,
                        'appointment': appt,
                        'consulta_id': appt.consulta_id,
                        'exam_summary': [],
                        'exam_blocks': [],
                        'exam_ids': [],
                    }
                )

        for exam in upcoming_exams:
            schedule_events.append(
                {
                    'kind': 'exame',
                    'timestamp': exam.scheduled_at,
                    'animal': exam.animal,
                    'exam': exam,
                    'consulta_id': None,
                    'exam_summary': [],
                    'exam_blocks': [],
                    'exam_ids': [exam.id],
                }
            )

        schedule_events.sort(
            key=lambda event: event.get('timestamp') or datetime.min,
            reverse=True,
        )

        session['exam_pending_seen_count'] = ExamAppointment.query.filter_by(
            specialist_id=veterinario.id, status='pending'
        ).count()
        session['appointment_pending_seen_count'] = (
            Appointment.query.filter(Appointment.status == 'scheduled')
            .filter(Appointment.scheduled_at >= now + timedelta(hours=2))
            .filter(appointment_scope_filter)
            .count()
        )
        clinic_pending_query = _clinic_pending_appointments_query(veterinario)
        session['clinic_pending_seen_count'] = (
            clinic_pending_query.count() if clinic_pending_query is not None else 0
        )

        vet_clinic_ids = _veterinarian_accessible_clinic_ids(veterinario)
        vet_clinic_scope = (
            vet_clinic_ids
            if len(vet_clinic_ids) > 1
            else vet_clinic_ids[0]
            if vet_clinic_ids
            else None
        )
        require_vet_appointments = _is_specialist_veterinarian(veterinario)
        pet_scope_param = request.args.get('scope', 'all')
        pet_page = request.args.get('page', 1, type=int)
        pet_search = (request.args.get('animal_search', '', type=str) or '').strip()
        pet_sort = (request.args.get('animal_sort', 'date_desc', type=str) or 'date_desc').strip()
        vet_animais_adicionados, vet_animais_pagination, vet_animais_scope = _get_recent_animais(
            pet_scope_param,
            pet_page,
            clinic_id=vet_clinic_scope,
            user_id=vet_user_id,
            require_appointments=require_vet_appointments,
            veterinario_id=veterinario.id if require_vet_appointments else None,
            search=pet_search,
            sort_option=pet_sort,
        )

        tutor_scope_param = request.args.get('tutor_scope', 'all')
        tutor_page = request.args.get('tutor_page', 1, type=int)
        tutor_search = (request.args.get('tutor_search', '', type=str) or '').strip()
        tutor_sort = (request.args.get('tutor_sort', 'name_asc', type=str) or 'name_asc').strip()
        vet_tutores_adicionados, vet_tutores_pagination, vet_tutores_scope = _get_recent_tutores(
            tutor_scope_param,
            tutor_page,
            clinic_id=vet_clinic_scope,
            user_id=vet_user_id,
            require_appointments=require_vet_appointments,
            veterinario_id=veterinario.id if require_vet_appointments else None,
            search=tutor_search,
            sort_option=tutor_sort,
        )

        species_list = list_species()
        breed_list = list_breeds()

        return render_template(
            'agendamentos/edit_vet_schedule.html',
            schedule_form=schedule_form,
            appointment_form=appointment_form,
            veterinario=veterinario,
            agenda_veterinarios=agenda_veterinarios,
            agenda_colaboradores=agenda_colaboradores,
            admin_selected_view=admin_selected_view,
            admin_selected_veterinario_id=admin_selected_veterinario_id,
            admin_selected_colaborador_id=admin_selected_colaborador_id,
            horarios_grouped=horarios_grouped,
            appointments_pending_consults=appointments_pending_consults,
            pending_consults_for_me=pending_consults_for_me,
            pending_consults_waiting_others=pending_consults_waiting_others,
            exams_pending_to_accept=exams_pending_to_accept,
            exams_waiting_other_vets=exams_waiting_other_vets,
            appointments_upcoming=appointments_upcoming,
            appointments_upcoming_for_me=appointments_upcoming_for_me,
            appointments_upcoming_requested=appointments_upcoming_requested,
            schedule_events=schedule_events,
            start_dt=start_dt,
            end_dt=end_dt,
            timedelta=timedelta,
            calendar_summary_vets=calendar_summary_vets,
            calendar_summary_clinic_ids=calendar_summary_clinic_ids,
            calendar_redirect_url=calendar_redirect_url,
            exam_confirm_default_hours=current_app.config.get(
                'EXAM_CONFIRM_DEFAULT_HOURS',
                2,
            ),
            species_list=species_list,
            breed_list=breed_list,
            vet_animais_adicionados=vet_animais_adicionados,
            vet_animais_pagination=vet_animais_pagination,
            vet_animais_scope=vet_animais_scope,
            vet_animal_search=pet_search,
            vet_animal_sort=pet_sort,
            vet_tutores_adicionados=vet_tutores_adicionados,
            vet_tutores_pagination=vet_tutores_pagination,
            vet_tutores_scope=vet_tutores_scope,
            vet_tutor_search=tutor_search,
            vet_tutor_sort=tutor_sort,
        )
    else:
        if worker in ['colaborador', 'admin']:
            clinica_id = current_user.clinica_id
            if current_user.role == 'admin' and worker == 'colaborador':
                colaborador_id_arg = request.args.get('colaborador_id', type=int)
                if colaborador_id_arg:
                    selected_colaborador = next(
                        (c for c in agenda_colaboradores if c.id == colaborador_id_arg),
                        None,
                    )
                    if not selected_colaborador:
                        selected_colaborador = (
                            User.query.filter_by(
                                id=colaborador_id_arg, worker='colaborador'
                            )
                            .first_or_404()
                        )
                elif agenda_colaboradores:
                    selected_colaborador = agenda_colaboradores[0]
                if selected_colaborador:
                    admin_selected_colaborador_id = selected_colaborador.id
                    if selected_colaborador.clinica_id:
                        clinica_id = selected_colaborador.clinica_id
                if not clinica_id:
                    clinica = Clinica.query.first()
                    clinica_id = clinica.id if clinica else None
            elif current_user.role == 'admin' and not clinica_id:
                clinica = Clinica.query.first()
                clinica_id = clinica.id if clinica else None
            appointment_form = None
            if not clinica_id:
                flash(
                    'Associe o colaborador a uma clínica para habilitar novos agendamentos.',
                    'warning',
                )
                if request.method == 'POST' and 'appointment-submit' in request.form:
                    return _redirect_to_current_appointments()
            else:
                appointment_form = AppointmentForm(
                    prefix='appointment',
                    clinic_ids=[clinica_id],
                    require_clinic_scope=True,
                )

                clinic = Clinica.query.get(clinica_id) if clinica_id else None
                vets = Veterinario.query.filter_by(clinica_id=clinica_id).all()
                specialists = []
                if clinic:
                    specialists = [
                        vet
                        for vet in getattr(clinic, 'veterinarios_associados', []) or []
                        if getattr(vet, 'id', None) is not None
                    ]
                combined_vets = unique_items_by_id(vets + specialists)

                def _vet_sort_key(vet):
                    name = (
                        getattr(getattr(vet, 'user', None), 'name', '')
                        or ''
                    )
                    return name.lower()

                combined_vets = sorted(
                    (vet for vet in combined_vets if getattr(vet, 'id', None) is not None),
                    key=_vet_sort_key,
                )
                combined_vets = calendar_access_scope.filter_veterinarians(combined_vets)

                clinic_vet_ids = {getattr(vet, 'id', None) for vet in vets if getattr(vet, 'id', None) is not None}
                specialist_ids = {getattr(vet, 'id', None) for vet in specialists}

                def _vet_label(vet):
                    base_name = getattr(getattr(vet, 'user', None), 'name', None)
                    label = base_name or f"Profissional #{getattr(vet, 'id', '—')}"
                    if getattr(vet, 'id', None) in specialist_ids and getattr(vet, 'id', None) not in clinic_vet_ids:
                        return f"{label} (Especialista)"
                    return label

                appointment_form.veterinario_id.choices = [
                    (vet.id, _vet_label(vet)) for vet in combined_vets
                ]
                calendar_summary_vets = [
                    {
                        'id': vet.id,
                        'name': _vet_label(vet),
                        'label': _vet_label(vet),
                        'full_name': getattr(getattr(vet, 'user', None), 'name', None),
                        'specialty_list': getattr(vet, 'specialty_list', None),
                        'is_specialist': getattr(vet, 'id', None) in specialist_ids
                        and getattr(vet, 'id', None) not in clinic_vet_ids,
                    }
                    for vet in combined_vets
                ]
                calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)
                calendar_summary_clinic_ids = calendar_access_scope.filter_clinic_ids([clinica_id]) if clinica_id else []
            if appointment_form and appointment_form.validate_on_submit():
                scheduled_at_local = datetime.combine(
                    appointment_form.date.data, appointment_form.time.data
                )
                if not is_slot_available(
                    appointment_form.veterinario_id.data,
                    scheduled_at_local,
                    kind=appointment_form.kind.data,
                ):
                    flash(
                        'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                        'danger'
                    )
                else:
                    scheduled_at = (
                        scheduled_at_local
                        .replace(tzinfo=BR_TZ)
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                    if appointment_form.kind.data == 'exame':
                        duration = get_appointment_duration('exame')
                        if has_conflict_for_slot(
                            appointment_form.veterinario_id.data,
                            scheduled_at_local,
                            duration,
                        ):
                            flash(
                                'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                                'danger'
                            )
                        else:
                            appt = ExamAppointment(
                                animal_id=appointment_form.animal_id.data,
                                specialist_id=appointment_form.veterinario_id.data,
                                requester_id=current_user.id,
                                scheduled_at=scheduled_at,
                                status='confirmed',
                            )
                            db.session.add(appt)
                            db.session.commit()
                            flash('Exame agendado com sucesso.', 'success')
                    else:
                        animal = get_animal_or_404(appointment_form.animal_id.data)
                        tutor_id = animal.user_id
                        requires_plan = current_app.config.get(
                            'REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT', False
                        )
                        if requires_plan and not Appointment.has_active_subscription(
                            animal.id, tutor_id
                        ):
                            flash(
                                'O animal não possui uma assinatura de plano de saúde ativa.',
                                'danger',
                            )
                            return _redirect_to_current_appointments()

                    appt = Appointment(
                        animal_id=animal.id,
                        tutor_id=tutor_id,
                        veterinario_id=appointment_form.veterinario_id.data,
                        scheduled_at=scheduled_at,
                        clinica_id=clinica_id,
                        notes=appointment_form.reason.data,
                        kind=appointment_form.kind.data,
                        created_by=current_user.id,
                        created_at=datetime.utcnow(),
                    )
                    db.session.add(appt)
                    db.session.commit()
                    flash('Agendamento criado com sucesso.', 'success')
                return _redirect_to_current_appointments()
            appointments = (
                Appointment.query
                .filter_by(clinica_id=clinica_id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            exam_appointments = (
                ExamAppointment.query
                .join(ExamAppointment.animal)
                .filter(Animal.clinica_id == clinica_id)
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
            vaccine_appointments = (
                Vacina.query
                .join(Vacina.animal)
                .filter(Animal.clinica_id == clinica_id)
                .filter(Vacina.aplicada_em >= date.today())
                .order_by(Vacina.aplicada_em)
                .all()
            )
            for vac in vaccine_appointments:
                vac.scheduled_at = datetime.combine(vac.aplicada_em, time.min, tzinfo=BR_TZ)
            form = appointment_form
        else:
            tutor_user = current_user
            if current_user.role == 'admin' and worker == 'tutor':
                tutor_user = User.query.filter(User.worker.is_(None)).first() or current_user
            appointments = (
                Appointment.query.filter_by(tutor_id=tutor_user.id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            exam_appointments = (
                ExamAppointment.query
                .join(ExamAppointment.animal)
                .filter(Animal.user_id == tutor_user.id)
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
            vaccine_appointments = (
                Vacina.query
                .join(Vacina.animal)
                .filter(Animal.user_id == tutor_user.id)
                .filter(Vacina.aplicada_em >= date.today())
                .order_by(Vacina.aplicada_em)
                .all()
            )
            for vac in vaccine_appointments:
                vac.scheduled_at = datetime.combine(vac.aplicada_em, time.min, tzinfo=BR_TZ)
            form = None
        appointments_grouped = group_appointments_by_day(appointments)
        exam_appointments_grouped = group_appointments_by_day(exam_appointments)
        vaccine_appointments_grouped = group_appointments_by_day(vaccine_appointments)
        if request.headers.get('X-Partial') == 'appointments_table' or request.args.get('partial') == 'appointments_table':
            return render_template(
                'partials/appointments_table.html',
                appointments_grouped=appointments_grouped,
            )

        return render_template(
            'agendamentos/appointments.html',
            appointments=appointments,
            appointments_grouped=appointments_grouped,
            exam_appointments=exam_appointments,
            exam_appointments_grouped=exam_appointments_grouped,
            vaccine_appointments=vaccine_appointments,
            vaccine_appointments_grouped=vaccine_appointments_grouped,
            form=form,
            agenda_users=agenda_users,
            agenda_veterinarios=agenda_veterinarios,
            agenda_colaboradores=agenda_colaboradores,
            admin_selected_view=admin_selected_view,
            admin_selected_veterinario_id=admin_selected_veterinario_id,
            admin_selected_colaborador_id=admin_selected_colaborador_id,
            admin_default_selection_value=admin_default_selection_value,
            calendar_summary_vets=calendar_summary_vets,
            calendar_summary_clinic_ids=calendar_summary_clinic_ids,
        )


@app.route('/appointments/calendar')
@login_required
def appointments_calendar():
    """Página experimental de calendário para tutores."""
    return render_template('agendamentos/appointments_calendar.html')


@app.route('/appointments/<int:veterinario_id>/schedule/<int:horario_id>/edit', methods=['POST'])
@login_required
def edit_vet_schedule_slot(veterinario_id, horario_id):
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )

    def json_response(success, status=200, message=None, errors=None, extra=None):
        if not wants_json:
            abort(status)
        payload = {'success': success}
        if message:
            payload['message'] = message
        if errors:
            payload['errors'] = errors
        if extra:
            payload.update(extra)
        response = jsonify(payload)
        response.status_code = status
        return response

    if not (
        _is_admin()
        or (
            is_veterinarian(current_user)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
        abort(403)
    veterinario = Veterinario.query.get_or_404(veterinario_id)
    horario = VetSchedule.query.get_or_404(horario_id)
    if not _is_admin() and horario.veterinario_id != veterinario_id:
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
        abort(403)
    form = VetScheduleForm(prefix='schedule')
    if _is_admin():
        vet_choices = Veterinario.query.all()
    else:
        vet_choices = [veterinario]
    form.veterinario_id.choices = [
        (v.id, v.user.name) for v in vet_choices
    ]
    if not _is_admin():
        raw_vet_id = request.form.get(form.veterinario_id.name)
        if raw_vet_id is None:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        try:
            submitted_vet_id = int(raw_vet_id)
        except (TypeError, ValueError):
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        if submitted_vet_id != veterinario_id:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
    redirect_response = redirect(url_for('appointments'))
    if form.validate_on_submit():
        novo_vet = form.veterinario_id.data
        if not _is_admin() and novo_vet != veterinario_id:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        dias_submetidos = form.dias_semana.data or []
        dias_unicos = []
        vistos = set()
        for dia in dias_submetidos:
            if not dia:
                continue
            if dia not in vistos:
                dias_unicos.append(dia)
                vistos.add(dia)
        if not dias_unicos:
            if wants_json:
                return json_response(False, status=400, message='Selecione ao menos um dia da semana.')
            flash('Selecione ao menos um dia da semana.', 'danger')
            return redirect_response

        inicio = form.hora_inicio.data
        fim = form.hora_fim.data
        intervalo_inicio = form.intervalo_inicio.data
        intervalo_fim = form.intervalo_fim.data

        original_inicio = horario.hora_inicio
        original_fim = horario.hora_fim
        original_intervalo_inicio = horario.intervalo_inicio
        original_intervalo_fim = horario.intervalo_fim

        primary_day = horario.dia_semana if horario.dia_semana in dias_unicos else dias_unicos[0]
        schedules_por_dia = {primary_day: horario}

        for dia in dias_unicos:
            if dia == primary_day:
                continue
            schedules_por_dia[dia] = (
                VetSchedule.query.filter_by(
                    veterinario_id=novo_vet,
                    dia_semana=dia,
                    hora_inicio=original_inicio,
                    hora_fim=original_fim,
                    intervalo_inicio=original_intervalo_inicio,
                    intervalo_fim=original_intervalo_fim,
                )
                .order_by(VetSchedule.id.asc())
                .first()
            )

        conflitos = []
        for dia, schedule_obj in schedules_por_dia.items():
            exclude_id = schedule_obj.id if schedule_obj else None
            if has_schedule_conflict(novo_vet, dia, inicio, fim, exclude_id=exclude_id):
                conflitos.append(dia)

        if conflitos:
            mensagem_conflito = 'Conflito de horário.'
            if len(conflitos) == 1:
                mensagem_conflito = f'Conflito de horário em {conflitos[0]}.'
            else:
                dias_texto = ', '.join(conflitos)
                mensagem_conflito = f'Conflitos de horário nos dias: {dias_texto}.'
            if wants_json:
                return json_response(False, status=400, message=mensagem_conflito)
            flash(mensagem_conflito, 'danger')
            return redirect_response

        horario.veterinario_id = novo_vet
        horario.dia_semana = primary_day
        horario.hora_inicio = inicio
        horario.hora_fim = fim
        horario.intervalo_inicio = intervalo_inicio
        horario.intervalo_fim = intervalo_fim

        processed_schedules = [horario]

        for dia, schedule_obj in schedules_por_dia.items():
            if dia == primary_day:
                continue
            if schedule_obj:
                schedule_obj.veterinario_id = novo_vet
                schedule_obj.dia_semana = dia
                schedule_obj.hora_inicio = inicio
                schedule_obj.hora_fim = fim
                schedule_obj.intervalo_inicio = intervalo_inicio
                schedule_obj.intervalo_fim = intervalo_fim
                processed_schedules.append(schedule_obj)
            else:
                novo_horario = VetSchedule(
                    veterinario_id=novo_vet,
                    dia_semana=dia,
                    hora_inicio=inicio,
                    hora_fim=fim,
                    intervalo_inicio=intervalo_inicio,
                    intervalo_fim=intervalo_fim,
                )
                db.session.add(novo_horario)
                processed_schedules.append(novo_horario)
                schedules_por_dia[dia] = novo_horario

        db.session.flush()
        db.session.commit()

        total_dias = len(dias_unicos)
        if total_dias > 1:
            mensagem_sucesso = f'Horários atualizados para {total_dias} dias.'
        else:
            mensagem_sucesso = 'Horário atualizado com sucesso.'

        def serialize_schedule(record):
            return {
                'id': record.id,
                'veterinario_id': record.veterinario_id,
                'dia_semana': record.dia_semana,
                'hora_inicio': record.hora_inicio.strftime('%H:%M') if record.hora_inicio else None,
                'hora_fim': record.hora_fim.strftime('%H:%M') if record.hora_fim else None,
                'intervalo_inicio': record.intervalo_inicio.strftime('%H:%M') if record.intervalo_inicio else None,
                'intervalo_fim': record.intervalo_fim.strftime('%H:%M') if record.intervalo_fim else None,
            }

        if wants_json:
            schedules_payload = []
            vistos_ids = set()
            for schedule in processed_schedules:
                if schedule.id in vistos_ids:
                    continue
                vistos_ids.add(schedule.id)
                schedules_payload.append(serialize_schedule(schedule))
            return json_response(
                True,
                message=mensagem_sucesso,
                extra={
                    'schedules': schedules_payload,
                    'processed_days': dias_unicos,
                },
            )
        flash(mensagem_sucesso, 'success')
        return redirect_response
    if wants_json:
        errors = form.errors or {}
        flat_errors = [err for field_errors in errors.values() for err in field_errors]
        message = flat_errors[0] if flat_errors else 'Não foi possível atualizar o horário.'
        return json_response(False, status=400, message=message, errors=errors if errors else None)
    flash('Não foi possível atualizar o horário. Verifique os dados e tente novamente.', 'danger')
    return redirect_response


@app.route('/appointments/<int:veterinario_id>/schedule/bulk_delete', methods=['POST'])
@login_required
def bulk_delete_vet_schedule(veterinario_id):
    from models import Veterinario, VetSchedule
    from sqlalchemy.exc import SQLAlchemyError

    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )

    def json_response(success, status=200, message=None, extra=None):
        if not wants_json:
            abort(status)
        payload = {'success': success}
        if message:
            payload['message'] = message
        if extra:
            payload.update(extra)
        response = jsonify(payload)
        response.status_code = status
        return response

    if not (
        _is_admin()
        or (
            is_veterinarian(current_user)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para excluir estes horários.')
        abort(403)

    Veterinario.query.get_or_404(veterinario_id)

    raw_ids = request.form.getlist('schedule_ids')
    if not raw_ids:
        message = 'Nenhum horário selecionado.'
        if wants_json:
            return json_response(False, status=400, message=message)
        flash(message, 'warning')
        return redirect(request.referrer or url_for('appointments'))

    schedule_ids = []
    for raw_id in raw_ids:
        try:
            schedule_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    unique_ids = list(dict.fromkeys(schedule_ids))
    if not unique_ids:
        message = 'Nenhum horário selecionado.'
        if wants_json:
            return json_response(False, status=400, message=message)
        flash(message, 'warning')
        return redirect(request.referrer or url_for('appointments'))

    schedules = (
        VetSchedule.query.filter(
            VetSchedule.id.in_(unique_ids),
            VetSchedule.veterinario_id == veterinario_id,
        )
        .order_by(VetSchedule.id.asc())
        .all()
    )

    if len(schedules) != len(unique_ids):
        message = 'Alguns horários selecionados não foram encontrados ou não pertencem a este profissional.'
        if wants_json:
            return json_response(False, status=400, message=message)
        flash(message, 'warning')
        return redirect(request.referrer or url_for('appointments'))

    try:
        for schedule in schedules:
            db.session.delete(schedule)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        message = 'Não foi possível excluir os horários selecionados.'
        if wants_json:
            return json_response(False, status=500, message=message)
        flash(message, 'danger')
        return redirect(request.referrer or url_for('appointments'))

    total = len(schedules)
    removed_ids = [schedule.id for schedule in schedules]
    if total == 1:
        message = 'Horário removido com sucesso.'
    else:
        message = f'{total} horários removidos com sucesso.'

    if wants_json:
        return json_response(True, message=message, extra={'removed_ids': removed_ids})

    flash(message, 'success')
    return redirect(request.referrer or url_for('appointments'))


@app.route('/appointments/<int:veterinario_id>/schedule/<int:horario_id>/delete', methods=['POST'])
@login_required
def delete_vet_schedule(veterinario_id, horario_id):
    if not (
        _is_admin()
        or (
            is_veterinarian(current_user)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        abort(403)
    horario = VetSchedule.query.get_or_404(horario_id)
    if not _is_admin() and horario.veterinario_id != veterinario_id:
        abort(403)
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('appointments'))


@app.route('/appointments/pending')
@login_required
def pending_appointments():
    return redirect(url_for('appointments'))


@app.route('/appointments/manage')
@login_required
def manage_appointments():
    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'
    if current_user.role != 'admin' and not (is_vet or is_collaborator):
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('index'))

    wants_json = 'application/json' in request.headers.get('Accept', '')
    page = max(request.args.get('page', type=int, default=1), 1)
    per_page = request.args.get('per_page', type=int, default=20)
    per_page = max(1, min(per_page or 20, 100))

    query = Appointment.query.order_by(Appointment.scheduled_at)
    if current_user.role != 'admin':
        if is_vet:
            query = query.filter_by(clinica_id=current_user.veterinario.clinica_id)
        elif is_collaborator:
            query = query.filter_by(clinica_id=current_user.clinica_id)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    appointments = pagination.items

    if wants_json:
        delete_form = AppointmentDeleteForm()
        items_html = render_template(
            'agendamentos/_appointments_admin_items.html',
            appointments=appointments,
            delete_form=delete_form,
        )
        next_page = pagination.next_num if pagination.has_next else None
        return jsonify({
            'success': True,
            'html': items_html,
            'next_page': next_page,
            'page': page,
        })

    delete_form = AppointmentDeleteForm()
    next_page = pagination.next_num if pagination.has_next else None
    return render_template(
        'agendamentos/appointments_admin.html',
        appointments=appointments,
        delete_form=delete_form,
        next_page=next_page,
        per_page=per_page,
    )


@app.route('/appointments/<int:appointment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'
    if is_vet or is_collaborator:
        if is_vet:
            user_clinic = current_user.veterinario.clinica_id
        else:
            user_clinic = current_user.clinica_id

        # Some legacy appointments might not have `clinica_id` stored.
        # In that case, fall back to the clinic of the assigned veterinarian
        # to validate access instead of denying with a 403.
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if appointment_clinic != user_clinic:
            abort(403)
    elif current_user.role != 'admin' and appointment.tutor_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        date_str = data.get('date')
        time_str = data.get('time')
        vet_id = data.get('veterinario_id')
        notes = data.get('notes')
        if not date_str or not time_str or not vet_id:
            return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
        try:
            scheduled_at_local = datetime.combine(
                datetime.strptime(date_str, '%Y-%m-%d').date(),
                datetime.strptime(time_str, '%H:%M').time(),
            )
            vet_id = int(vet_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Dados inválidos.'}), 400
        existing_local = (
            appointment.scheduled_at
            .replace(tzinfo=timezone.utc)
            .astimezone(BR_TZ)
            .replace(tzinfo=None)
        )
        if not is_slot_available(vet_id, scheduled_at_local, kind=appointment.kind) and not (
            vet_id == appointment.veterinario_id and scheduled_at_local == existing_local
        ):
            return jsonify({
                'success': False,
                'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
            }), 400
        appointment.veterinario_id = vet_id
        appointment.scheduled_at = (
            scheduled_at_local
            .replace(tzinfo=BR_TZ)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        if notes is not None:
            appointment.notes = notes
        db.session.commit()
        card_html = render_template('partials/_appointment_card.html', appt=appointment)
        return jsonify({
            'success': True,
            'message': 'Agendamento atualizado com sucesso.',
            'card_html': card_html,
            'appointment_id': appointment.id,
        })

    veterinarios = Veterinario.query.all()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template(
            'partials/edit_appointment_form.html',
            appointment=appointment,
            veterinarios=veterinarios,
        )
    return render_template('agendamentos/edit_appointment.html', appointment=appointment, veterinarios=veterinarios)


@app.route('/appointments/<int:appointment_id>/status', methods=['POST'])
@login_required
def update_appointment_status(appointment_id):
    """Update the status of an appointment."""
    appointment = Appointment.query.get_or_404(appointment_id)

    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if current_user.role == 'admin':
        pass
    elif is_vet or is_collaborator:
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if is_vet:
            veterinario = getattr(current_user, 'veterinario', None)
            vet_id = getattr(veterinario, 'id', None)
            if not (vet_id and appointment.veterinario_id == vet_id):
                clinic_ids = set()
                primary_clinic = getattr(veterinario, 'clinica_id', None)
                if primary_clinic is not None:
                    clinic_ids.add(primary_clinic)
                clinic_ids.update(
                    clinica_id
                    for clinica_id in (
                        getattr(clinica, 'id', None)
                        for clinica in getattr(veterinario, 'clinicas', [])
                    )
                    if clinica_id is not None
                )

                if appointment_clinic not in clinic_ids:
                    abort(403)
        else:
            user_clinic = getattr(current_user, 'clinica_id', None)
            if appointment_clinic != user_clinic:
                abort(403)
    elif appointment.tutor_id != current_user.id:
        abort(403)

    accepts = request.accept_mimetypes
    accept_json = accepts['application/json']
    accept_html = accepts['text/html']
    wants_json = (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or (accept_json > 0 and accept_json > accept_html)
    )
    redirect_url = request.referrer or url_for('appointments')

    status_value = request.form.get('status') or (request.get_json(silent=True) or {}).get('status')
    status = (status_value or '').strip().lower()
    allowed_statuses = {'scheduled', 'completed', 'canceled', 'accepted'}
    if status not in allowed_statuses:
        message = 'Status inválido.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 400
        flash(message, 'error')
        return redirect(redirect_url)

    if status == 'accepted' and current_user.role != 'admin':
        error_message = 'Somente o veterinário responsável pode aceitar este agendamento.'
        if not is_vet:
            if wants_json:
                return jsonify({'success': False, 'message': error_message}), 403
            flash(error_message, 'error')
            return redirect(redirect_url)
        veterinario = getattr(current_user, 'veterinario', None)
        vet_id = getattr(veterinario, 'id', None)
        if not (vet_id and appointment.veterinario_id == vet_id):
            if wants_json:
                return jsonify({'success': False, 'message': error_message}), 403
            flash(error_message, 'error')
            return redirect(redirect_url)

    should_enforce_deadline = False
    if status == 'accepted':
        should_enforce_deadline = current_user.role != 'admin'
    elif status == 'canceled':
        should_enforce_deadline = (
            current_user.role != 'admin'
            and not (is_vet or is_collaborator)
        )

    if should_enforce_deadline and appointment.scheduled_at - datetime.utcnow() < timedelta(hours=2):
        message = 'Prazo expirado.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 400
        # Mantém o comportamento simples de texto quando o prazo expira.
        return message, 400

    appointment.status = status
    db.session.commit()

    if wants_json:
        card_html = render_template('partials/_appointment_card.html', appt=appointment)
        return jsonify({
            'success': True,
            'message': 'Status atualizado.',
            'status': appointment.status,
            'appointment_id': appointment.id,
            'card_html': card_html,
        })

    flash('Status atualizado.', 'success')
    # Sempre redireciona de volta à página anterior para evitar exibir apenas
    # o JSON "{\"success\": true}".
    return redirect(request.referrer or url_for('appointments'))


@app.route('/appointments/<int:appointment_id>/delete', methods=['POST'])
@login_required
def delete_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')
    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if current_user.role == 'admin':
        pass
    elif is_vet or is_collaborator:
        if is_vet:
            veterinario = getattr(current_user, 'veterinario', None)
            user_clinic = getattr(veterinario, 'clinica_id', None)
        else:
            user_clinic = getattr(current_user, 'clinica_id', None)

        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if appointment_clinic != user_clinic:
            abort(403)
    else:
        abort(403)
    try:
        db.session.delete(appointment)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        message = 'Não foi possível remover o agendamento.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 500
        flash(message, 'danger')
        return redirect(request.referrer or url_for('manage_appointments'))

    message = 'Agendamento removido.'
    if wants_json:
        return jsonify({'success': True, 'message': message, 'appointment_id': appointment_id})

    flash(message, 'success')
    return redirect(request.referrer or url_for('manage_appointments'))


def _serialize_calendar_pet(pet):
    """Serialize ``Animal`` data for the experimental calendar widgets."""

    def _extract_name(value):
        if not value:
            return ""
        if hasattr(value, "name"):
            return value.name or ""
        return str(value)

    owner_name = ""
    owner = getattr(pet, "owner", None)
    if owner and getattr(owner, "name", None):
        owner_name = owner.name

    return {
        "id": pet.id,
        "name": pet.name,
        "species": _extract_name(getattr(pet, "species", "")),
        "breed": _extract_name(getattr(pet, "breed", "")),
        "date_added": pet.date_added.isoformat() if pet.date_added else None,
        "image": getattr(pet, "image", None),
        "tutor_name": owner_name,
        "age_display": pet.age_display if hasattr(pet, "age_display") else None,
        "clinica_id": getattr(pet, "clinica_id", None),
    }


@app.route('/api/my_pets')
@login_required
def api_my_pets():
    """Return the authenticated tutor's pets ordered by recency."""
    pets = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
        )
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.date_added.desc())
        .all()
    )
    return jsonify([_serialize_calendar_pet(p) for p in pets])


@app.route('/api/clinic_pets')
@login_required
def api_clinic_pets():
    """Return pets associated with the current clinic (or admin selection)."""

    if current_user.worker not in {"veterinario", "colaborador"} and current_user.role != 'admin':
        return api_my_pets()

    clinic_id = None
    view_as = request.args.get('view_as')

    if current_user.role == 'admin':
        if view_as == 'veterinario':
            vet_id = request.args.get('veterinario_id', type=int)
            if vet_id:
                veterinario = Veterinario.query.get(vet_id)
                clinic_id = veterinario.clinica_id if veterinario else None
        elif view_as == 'colaborador':
            colaborador_id = request.args.get('colaborador_id', type=int)
            if colaborador_id:
                colaborador = User.query.get(colaborador_id)
                clinic_id = colaborador.clinica_id if colaborador else None
        if clinic_id is None:
            clinic_id = request.args.get('clinica_id', type=int)
        if clinic_id is None:
            # Default to the first accessible clinic for the admin, if any.
            clinic_rows = clinicas_do_usuario().with_entities(Clinica.id).all()
            for row in clinic_rows:
                try:
                    clinic_id = row[0]
                except (TypeError, IndexError):
                    clinic_id = getattr(row, 'id', None)
                if clinic_id:
                    break
    else:
        clinic_id = current_user_clinic_id()

    if not clinic_id:
        return jsonify([])

    last_appt = (
        db.session.query(
            Appointment.animal_id,
            func.max(Appointment.scheduled_at).label('last_at'),
        )
        .filter(Appointment.clinica_id == clinic_id)
        .group_by(Appointment.animal_id)
        .subquery()
    )

    pets = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
        )
        .outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
        .filter(Animal.removido_em.is_(None))
        .filter(
            or_(
                Animal.clinica_id == clinic_id,
                last_appt.c.last_at.isnot(None),
            )
        )
        .order_by(func.coalesce(last_appt.c.last_at, Animal.date_added).desc())
        .all()
    )

    return jsonify([_serialize_calendar_pet(p) for p in pets])


@app.route('/api/my_appointments')
@login_required
def api_my_appointments():
    """Return the current user's appointments as calendar events."""
    from models import (
        Appointment,
        ExamAppointment,
        Vacina,
        Animal,
        Veterinario,
        User,
        Clinica,
    )

    query = Appointment.query
    is_vet = is_veterinarian(current_user)
    context = {
        'mode': None,
        'tutor_id': None,
        'vet': None,
        'clinic_ids': [],
    }
    is_vet = is_veterinarian(current_user)

    is_vet = is_veterinarian(current_user)

    if current_user.role == 'admin':
        def _coerce_first_int(values):
            if values is None:
                return None
            if isinstance(values, (list, tuple)):
                values = values[0] if values else None
            if values in (None, ""):
                return None
            try:
                return int(values)
            except (TypeError, ValueError):
                return None

        def _admin_view_context():
            referrer_params = {}
            if request.referrer:
                parsed = urlparse(request.referrer)
                referrer_params = parse_qs(parsed.query)
            view_as = request.args.get('view_as') or referrer_params.get('view_as', [None])[0]
            vet_id = request.args.get('veterinario_id', type=int)
            if vet_id is None:
                vet_id = _coerce_first_int(referrer_params.get('veterinario_id'))
            clinic_id = request.args.get('clinica_id', type=int)
            if clinic_id is None:
                clinic_id = _coerce_first_int(referrer_params.get('clinica_id'))
            tutor_id = request.args.get('tutor_id', type=int)
            if tutor_id is None:
                tutor_id = _coerce_first_int(referrer_params.get('tutor_id'))
            return view_as, vet_id, clinic_id, tutor_id

        accessible_clinic_ids = None

        def _accessible_clinic_ids():
            nonlocal accessible_clinic_ids
            if accessible_clinic_ids is None:
                rows = clinicas_do_usuario().with_entities(Clinica.id).all()
                clinic_ids = []
                for row in rows:
                    try:
                        clinic_id_value = row[0]
                    except (TypeError, IndexError):
                        clinic_id_value = getattr(row, 'id', None)
                    if clinic_id_value is None or clinic_id_value in clinic_ids:
                        continue
                    clinic_ids.append(clinic_id_value)
                accessible_clinic_ids = clinic_ids
            return accessible_clinic_ids

        view_as, vet_id, clinic_id, tutor_id = _admin_view_context()

        context['clinic_ids'] = list(_accessible_clinic_ids())
        if view_as == 'tutor' and tutor_id:
            context['mode'] = 'tutor'
            context['tutor_id'] = tutor_id
        elif view_as == 'veterinario':
            target_vet = Veterinario.query.get(vet_id) if vet_id else None
            context['mode'] = 'veterinario'
            context['vet'] = target_vet
            target_clinics = []
            if clinic_id:
                target_clinics.append(clinic_id)
            elif context['clinic_ids']:
                target_clinics.extend(context['clinic_ids'])
            context['clinic_ids'] = [cid for cid in target_clinics if cid]
        elif view_as == 'colaborador':
            target_clinics = []
            if clinic_id:
                target_clinics.append(clinic_id)
            elif context['clinic_ids']:
                target_clinics.extend(context['clinic_ids'])
            context['mode'] = 'clinics'
            context['clinic_ids'] = [cid for cid in target_clinics if cid]
        else:
            context['mode'] = 'clinics'

        def _creator_clinic_filter(clinic_ids):
            sanitized = [cid for cid in (clinic_ids or []) if cid]
            if not sanitized:
                return None
            return Appointment.creator.has(
                or_(
                    User.clinica_id.in_(sanitized),
                    User.veterinario.has(
                        or_(
                            Veterinario.clinica_id.in_(sanitized),
                            Veterinario.clinicas.any(Clinica.id.in_(sanitized)),
                        )
                    ),
                )
            )

        if view_as == 'veterinario':
            if not vet_id and getattr(current_user, 'veterinario', None):
                vet_id = current_user.veterinario.id
            filters = []
            if vet_id:
                filters.append(Appointment.veterinario_id == vet_id)
                target_vet = target_vet or Veterinario.query.get(vet_id)
            target_vet_user_id = getattr(target_vet, 'user_id', None) if target_vet else None
            if target_vet_user_id:
                filters.append(Appointment.created_by == target_vet_user_id)
            if filters:
                query = query.filter(or_(*filters) if len(filters) > 1 else filters[0])
        elif view_as == 'colaborador':
            clinic_ids = list(_accessible_clinic_ids())
            if clinic_id and clinic_id not in clinic_ids:
                clinic_ids.append(clinic_id)
            if clinic_ids:
                creator_filter = _creator_clinic_filter(clinic_ids)
                clinic_filters = [Appointment.clinica_id.in_(clinic_ids)]
                if creator_filter is not None:
                    clinic_filters.append(creator_filter)
                query = query.filter(
                    or_(*clinic_filters)
                    if len(clinic_filters) > 1
                    else clinic_filters[0]
                )
        elif view_as == 'tutor':
            target_tutor_id = tutor_id or current_user.id
            query = query.filter(Appointment.tutor_id == target_tutor_id)
        else:
            clinic_ids = _accessible_clinic_ids()
            if clinic_ids:
                creator_filter = _creator_clinic_filter(clinic_ids)
                clinic_filters = [
                    Appointment.clinica_id.in_(clinic_ids),
                    Appointment.veterinario.has(
                        Veterinario.clinica_id.in_(clinic_ids)
                    ),
                ]
                if creator_filter is not None:
                    clinic_filters.append(creator_filter)
                query = query.filter(
                    or_(*clinic_filters)
                    if len(clinic_filters) > 1
                    else clinic_filters[0]
                )
            if not context['clinic_ids']:
                context['clinic_ids'] = [cid for cid in (clinic_ids or []) if cid]
            context['mode'] = context['mode'] or 'clinics'
    elif is_vet:
        query = query.filter(
            or_(
                Appointment.veterinario_id == current_user.veterinario.id,
                Appointment.created_by == current_user.id,
            )
        )
        vet_profile = current_user.veterinario
        context['mode'] = 'veterinario'
        context['vet'] = vet_profile
        clinic_ids = []
        primary_clinic = getattr(vet_profile, 'clinica_id', None)
        if primary_clinic:
            clinic_ids.append(primary_clinic)
        for clinic in getattr(vet_profile, 'clinicas', []) or []:
            clinic_id_value = getattr(clinic, 'id', None)
            if clinic_id_value and clinic_id_value not in clinic_ids:
                clinic_ids.append(clinic_id_value)
        context['clinic_ids'] = clinic_ids
    elif current_user.worker == 'colaborador' and current_user.clinica_id:
        query = query.filter(
            or_(
                Appointment.clinica_id == current_user.clinica_id,
                Appointment.created_by == current_user.id,
            )
        )
        context['mode'] = 'clinics'
        context['clinic_ids'] = [current_user.clinica_id]
    else:
        query = query.filter_by(tutor_id=current_user.id)
        context['mode'] = 'tutor'
        context['tutor_id'] = current_user.id

    appts = query.order_by(Appointment.scheduled_at).all()
    events = appointments_to_events(appts)

    existing_event_ids = set()
    for event in events:
        event_id = event.get('id') if isinstance(event, dict) else None
        if event_id:
            existing_event_ids.add(event_id)

    def _append_event(event):
        if not event or not isinstance(event, dict):
            return
        event_id = event.get('id')
        if event_id and event_id in existing_event_ids:
            return
        events.append(event)
        if event_id:
            existing_event_ids.add(event_id)

    def _extend_exam_events(*, or_filters=None, and_filters=None):
        query_obj = ExamAppointment.query.outerjoin(ExamAppointment.animal)
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        exam_items = query_obj.order_by(ExamAppointment.scheduled_at).all()
        for exam in unique_items_by_id(exam_items):
            event = exam_to_event(exam)
            if event:
                _append_event(event)

    def _extend_vaccine_events(*, or_filters=None, and_filters=None):
        query_obj = Vacina.query.outerjoin(Vacina.animal)
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        vaccine_items = query_obj.order_by(Vacina.aplicada_em).all()
        for vaccine in unique_items_by_id(vaccine_items):
            event = vaccine_to_event(vaccine)
            if event:
                _append_event(event)

    def _extend_consulta_events(*, or_filters=None, and_filters=None):
        query_obj = (
            Consulta.query
            .outerjoin(Consulta.animal)
            .options(
                joinedload(Consulta.animal).joinedload(Animal.owner),
                joinedload(Consulta.veterinario),
                joinedload(Consulta.clinica),
            )
            .filter(~Consulta.appointment.has())
        )
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        consulta_items = query_obj.order_by(Consulta.created_at).all()
        for consulta in unique_items_by_id(consulta_items):
            event = consulta_to_event(consulta)
            if event:
                _append_event(event)

    def _extend_for_tutor(tutor_id):
        if not tutor_id:
            return
        tutor_vet = None
        if current_user.is_authenticated and current_user.id == tutor_id:
            tutor_vet = getattr(current_user, 'veterinario', None)
        else:
            tutor_obj = User.query.get(tutor_id)
            tutor_vet = getattr(tutor_obj, 'veterinario', None) if tutor_obj else None
        or_filters = [
            ExamAppointment.requester_id == tutor_id,
            Animal.user_id == tutor_id,
        ]
        if tutor_vet:
            or_filters.append(ExamAppointment.specialist_id == tutor_vet.id)
        _extend_exam_events(or_filters=or_filters)
        _extend_vaccine_events(
            or_filters=[
                Animal.user_id == tutor_id,
                Vacina.aplicada_por == tutor_id,
            ],
            and_filters=[
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            ],
        )
        _extend_consulta_events(or_filters=[Animal.user_id == tutor_id])

    def _extend_for_vet(vet_profile, clinic_ids=None):
        if not vet_profile:
            return
        vet_id = getattr(vet_profile, 'id', None)
        if not vet_id:
            return
        sanitized_clinic_ids = [cid for cid in (clinic_ids or []) if cid]
        vet_user_id = getattr(vet_profile, 'user_id', None)
        exam_filters = [ExamAppointment.specialist_id == vet_id]
        exam_filters.append(ExamAppointment.status.in_(['pending', 'confirmed']))
        if sanitized_clinic_ids:
            exam_filters.append(
                or_(
                    Animal.clinica_id.in_(sanitized_clinic_ids),
                    ExamAppointment.specialist.has(
                        Veterinario.clinica_id.in_(sanitized_clinic_ids)
                    ),
                )
            )
        _extend_exam_events(and_filters=exam_filters)

        vaccine_filters = [
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em >= date.today(),
        ]
        vet_user_id = getattr(vet_profile, 'user_id', None)
        if vet_user_id:
            vaccine_filters.append(Vacina.aplicada_por == vet_user_id)
        if sanitized_clinic_ids:
            vaccine_filters.append(Animal.clinica_id.in_(sanitized_clinic_ids))
        _extend_vaccine_events(and_filters=vaccine_filters)

        consulta_filters = []
        if vet_user_id:
            consulta_filters.append(Consulta.created_by == vet_user_id)
        if sanitized_clinic_ids:
            consulta_filters.append(Consulta.clinica_id.in_(sanitized_clinic_ids))
        if consulta_filters:
            _extend_consulta_events(and_filters=consulta_filters)

    def _extend_for_clinics(clinic_ids):
        sanitized = [cid for cid in (clinic_ids or []) if cid]
        if not sanitized:
            return
        clinic_filters = [
            or_(
                Animal.clinica_id.in_(sanitized),
                ExamAppointment.specialist.has(
                    Veterinario.clinica_id.in_(sanitized)
                ),
            ),
            ExamAppointment.status.in_(['pending', 'confirmed']),
        ]
        _extend_exam_events(and_filters=clinic_filters)
        vaccine_filters = [
            Animal.clinica_id.in_(sanitized),
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em >= date.today(),
        ]
        _extend_vaccine_events(and_filters=vaccine_filters)
        _extend_consulta_events(and_filters=[Consulta.clinica_id.in_(sanitized)])

    if context['mode'] == 'tutor':
        _extend_for_tutor(context.get('tutor_id'))
    elif context['mode'] == 'veterinario':
        _extend_for_vet(context.get('vet'), context.get('clinic_ids'))
    elif context['mode'] == 'clinics':
        _extend_for_clinics(context.get('clinic_ids'))

    return jsonify(events)


@app.route('/api/user_appointments/<int:user_id>')
@login_required
def api_user_appointments(user_id):
    """Return appointments for the selected user (admin only)."""
    if current_user.role != 'admin':
        abort(403)

    user = get_user_or_404(user_id)
    vet = getattr(user, 'veterinario', None)

    appointment_filters = [Appointment.tutor_id == user.id]
    if vet:
        appointment_filters.append(Appointment.veterinario_id == vet.id)
    appointments = (
        Appointment.query.filter(or_(*appointment_filters))
        .order_by(Appointment.scheduled_at)
        .all()
    ) if appointment_filters else []

    events = appointments_to_events(appointments)

    exam_filters = [ExamAppointment.requester_id == user.id]
    if vet:
        exam_filters.append(ExamAppointment.specialist_id == vet.id)
    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_filters.append(Animal.user_id == user.id)
    if exam_filters:
        exam_appointments = (
            exam_query.filter(or_(*exam_filters))
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        for exam in unique_items_by_id(exam_appointments):
            event = exam_to_event(exam)
            if event:
                events.append(event)

    vaccine_filters = [Animal.user_id == user.id, Vacina.aplicada_por == user.id]
    vaccine_query = Vacina.query.outerjoin(Vacina.animal)
    if vaccine_filters:
        vaccine_appointments = (
            vaccine_query.filter(
                or_(*vaccine_filters),
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            )
            .order_by(Vacina.aplicada_em)
            .all()
        )
        for vac in unique_items_by_id(vaccine_appointments):
            event = vaccine_to_event(vac)
            if event:
                events.append(event)

    return jsonify(events)


@app.route('/api/appointments/<int:appointment_id>/reschedule', methods=['POST'])
@login_required
def api_reschedule_appointment(appointment_id):
    """Update the schedule of an appointment after drag & drop operations."""

    appointment = Appointment.query.get_or_404(appointment_id)

    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if is_vet or is_collaborator:
        if is_vet:
            user_clinic = current_user.veterinario.clinica_id
        else:
            user_clinic = current_user.clinica_id
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id
        if appointment_clinic != user_clinic:
            abort(403)
    elif current_user.role != 'admin' and appointment.tutor_id != current_user.id:
        abort(403)

    data = request.get_json(silent=True) or {}
    start_str = data.get('start') or data.get('startStr')

    def _parse_client_datetime(value):
        if not value or not isinstance(value, str):
            return None
        value = value.strip()
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    new_start = _parse_client_datetime(start_str)
    if not new_start:
        return jsonify({'success': False, 'message': 'Horário inválido.'}), 400

    if new_start.tzinfo is None:
        new_start_with_tz = new_start.replace(tzinfo=BR_TZ)
        new_start_local = new_start
    else:
        new_start_with_tz = new_start.astimezone(BR_TZ)
        new_start_local = new_start_with_tz.replace(tzinfo=None)

    if appointment.scheduled_at.tzinfo is None:
        existing_local = (
            appointment.scheduled_at
            .replace(tzinfo=timezone.utc)
            .astimezone(BR_TZ)
            .replace(tzinfo=None)
        )
    else:
        existing_local = appointment.scheduled_at.astimezone(BR_TZ).replace(tzinfo=None)

    if (
        not is_slot_available(appointment.veterinario_id, new_start_local, kind=appointment.kind)
        and new_start_local != existing_local
    ):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.',
        }), 400

    appointment.scheduled_at = (
        new_start_with_tz
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    db.session.commit()

    updated_start = to_timezone_aware(appointment.scheduled_at)
    return jsonify({
        'success': True,
        'message': 'Agendamento atualizado com sucesso.',
        'start': updated_start.isoformat() if updated_start else None,
    })


@app.route('/api/clinic_appointments/<int:clinica_id>')
@login_required
def api_clinic_appointments(clinica_id):
    """Return appointments for a clinic as calendar events."""
    ensure_clinic_access(clinica_id)
    from models import User, Clinica

    calendar_access_scope = get_calendar_access_scope(current_user)
    full_calendar_clinic_ids = calendar_access_scope.full_access_clinic_ids
    has_full_clinic_access = calendar_access_scope.allows_all_veterinarians()
    if not has_full_clinic_access:
        if full_calendar_clinic_ids is None:
            has_full_clinic_access = True
        else:
            has_full_clinic_access = clinica_id in full_calendar_clinic_ids

    allowed_veterinarian_ids: Optional[Set[int]] = None
    if not has_full_clinic_access:
        vet_scope = calendar_access_scope.veterinarian_ids or set()
        allowed_veterinarian_ids = set(vet_scope)

    creator_filter = Appointment.creator.has(
        or_(
            User.clinica_id == clinica_id,
            User.veterinario.has(
                or_(
                    Veterinario.clinica_id == clinica_id,
                    Veterinario.clinicas.any(Clinica.id == clinica_id),
                )
            ),
        )
    )

    appt_filters = [Appointment.clinica_id == clinica_id, creator_filter]
    appts = (
        Appointment.query
        .filter(or_(*appt_filters))
        .order_by(Appointment.scheduled_at)
        .all()
    )

    if allowed_veterinarian_ids is not None:
        appts = [
            appt
            for appt in appts
            if getattr(appt, 'veterinario_id', None) in allowed_veterinarian_ids
        ]

    events = appointments_to_events(appts)

    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_appointments = (
        exam_query
        .filter(
            or_(
                Animal.clinica_id == clinica_id,
                ExamAppointment.specialist.has(Veterinario.clinica_id == clinica_id),
            ),
            ExamAppointment.status.in_(['pending', 'confirmed']),
        )
        .order_by(ExamAppointment.scheduled_at)
        .all()
    )

    if allowed_veterinarian_ids is not None:
        exam_appointments = [
            exam
            for exam in exam_appointments
            if getattr(exam, 'specialist_id', None) in allowed_veterinarian_ids
        ]

    for exam in unique_items_by_id(exam_appointments):
        event = exam_to_event(exam)
        if event:
            events.append(event)

    vaccine_events: list[dict] = []
    if has_full_clinic_access:
        vaccine_query = Vacina.query.outerjoin(Vacina.animal)
        vaccine_appointments = (
            vaccine_query
            .filter(
                Animal.clinica_id == clinica_id,
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            )
            .order_by(Vacina.aplicada_em)
            .all()
        )
        for vaccine in unique_items_by_id(vaccine_appointments):
            event = vaccine_to_event(vaccine)
            if event:
                vaccine_events.append(event)

    events.extend(vaccine_events)

    return jsonify(events)


@app.route('/api/vet_appointments/<int:veterinario_id>')
@login_required
def api_vet_appointments(veterinario_id):
    """Return appointments for a veterinarian as calendar events."""
    veterinario = Veterinario.query.get_or_404(veterinario_id)

    calendar_access_scope = get_calendar_access_scope(current_user)
    vet_clinic_ids = set()
    primary_clinic_id = getattr(veterinario, 'clinica_id', None)
    if primary_clinic_id:
        vet_clinic_ids.add(primary_clinic_id)
    for clinic in getattr(veterinario, 'clinicas', []) or []:
        clinic_id_value = getattr(clinic, 'id', None)
        if clinic_id_value:
            vet_clinic_ids.add(clinic_id_value)

    requested_clinic_ids = []
    for value in request.args.getlist('clinica_id'):
        try:
            clinic_id_value = int(value)
        except (TypeError, ValueError):
            continue
        if clinic_id_value not in requested_clinic_ids:
            requested_clinic_ids.append(clinic_id_value)

    query = Appointment.query.filter_by(veterinario_id=veterinario_id)
    target_clinic_ids = []

    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if current_user.role == 'admin':
        if requested_clinic_ids:
            filtered_requested = calendar_access_scope.filter_clinic_ids(requested_clinic_ids)
            if filtered_requested:
                query = query.filter(Appointment.clinica_id.in_(filtered_requested))
                target_clinic_ids = filtered_requested
            else:
                query = query.filter(false())
                target_clinic_ids = []
    elif is_vet:
        current_vet = getattr(current_user, 'veterinario', None)
        if not current_vet:
            abort(403)
        if current_vet.id != veterinario_id:
            if not calendar_access_scope.allows_veterinarian(veterinario):
                abort(403)
            candidate_clinic_ids = requested_clinic_ids or list(vet_clinic_ids)
            if requested_clinic_ids and vet_clinic_ids:
                candidate_clinic_ids = [
                    clinic_id
                    for clinic_id in requested_clinic_ids
                    if clinic_id in vet_clinic_ids
                ]
            filtered_clinic_ids = calendar_access_scope.filter_clinic_ids(
                candidate_clinic_ids
            )
            if filtered_clinic_ids:
                query = query.filter(Appointment.clinica_id.in_(filtered_clinic_ids))
                target_clinic_ids = filtered_clinic_ids
            elif candidate_clinic_ids:
                query = query.filter(false())
                target_clinic_ids = []
            elif requested_clinic_ids:
                query = query.filter(false())
                target_clinic_ids = []
    elif is_collaborator:
        collaborator_clinic_id = getattr(current_user, 'clinica_id', None)
        ensure_clinic_access(collaborator_clinic_id)
        if not collaborator_clinic_id:
            abort(404)
        if vet_clinic_ids and collaborator_clinic_id not in vet_clinic_ids:
            abort(404)
        authorized_clinics = calendar_access_scope.filter_clinic_ids(
            [collaborator_clinic_id]
        )
        if authorized_clinics:
            query = query.filter(Appointment.clinica_id.in_(authorized_clinics))
            target_clinic_ids = authorized_clinics
        else:
            query = query.filter(false())
            target_clinic_ids = []
    else:
        abort(403)

    appointments = query.order_by(Appointment.scheduled_at).all()
    events = appointments_to_events(appointments)

    exam_filters = [
        ExamAppointment.specialist_id == veterinario_id,
        ExamAppointment.status.in_(['pending', 'confirmed']),
    ]

    if target_clinic_ids:
        animal_clinic_filter = Animal.clinica_id.in_(target_clinic_ids)
        specialist_clinic_filter = ExamAppointment.specialist.has(
            Veterinario.clinica_id.in_(target_clinic_ids)
        )
        exam_filters.append(
            or_(
                animal_clinic_filter,
                and_(Animal.clinica_id.is_(None), specialist_clinic_filter),
            )
        )

    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_appointments = (
        exam_query.filter(*exam_filters)
        .order_by(ExamAppointment.scheduled_at)
        .all()
    )

    for exam in unique_items_by_id(exam_appointments):
        event = exam_to_event(exam)
        if event:
            events.append(event)

    vaccine_filters = [
        Vacina.aplicada_em.isnot(None),
        Vacina.aplicada_em >= date.today(),
    ]

    vet_user_id = getattr(veterinario, 'user_id', None)
    if vet_user_id:
        vaccine_filters.append(Vacina.aplicada_por == vet_user_id)

    if target_clinic_ids:
        vaccine_filters.append(Animal.clinica_id.in_(target_clinic_ids))

    vaccine_query = Vacina.query.outerjoin(Vacina.animal)
    vaccine_appointments = (
        vaccine_query.filter(*vaccine_filters)
        .order_by(Vacina.aplicada_em)
        .all()
    )

    for vaccine in unique_items_by_id(vaccine_appointments):
        event = vaccine_to_event(vaccine)
        if event:
            events.append(event)

    return jsonify(events)


@app.route('/api/specialists')
def api_specialists():
    from models import Veterinario, Specialty
    specialty_id = request.args.get('specialty_id', type=int)
    query = Veterinario.query
    if specialty_id:
        query = query.join(Veterinario.specialties).filter(Specialty.id == specialty_id)
    vets = query.all()
    return jsonify([
        {
            'id': v.id,
            'nome': v.user.name,
            'especialidades': [s.nome for s in v.specialties],
        }
        for v in vets
    ])


@app.route('/api/specialties')
def api_specialties():
    from models import Specialty
    specs = Specialty.query.order_by(Specialty.nome).all()
    return jsonify([{ 'id': s.id, 'nome': s.nome } for s in specs])


@app.route('/api/specialist/<int:veterinario_id>/available_times')
def api_specialist_available_times(veterinario_id):
    date_str = request.args.get('date')
    if not date_str:
        return jsonify([])
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    kind = request.args.get('kind', 'consulta')
    include_booked = request.args.get('include_booked', '').lower() in ('1', 'true', 'yes', 'on')
    times = get_available_times(
        veterinario_id,
        date_obj,
        kind=kind,
        include_booked=include_booked,
    )
    return jsonify(times)


@app.route('/api/specialist/<int:veterinario_id>/weekly_schedule')
def api_specialist_weekly_schedule(veterinario_id):
    start_str = request.args.get('start')
    days = int(request.args.get('days', 7))
    start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()
    data = get_weekly_schedule(veterinario_id, start_date, days)
    return jsonify(data)


@app.route('/animal/<int:animal_id>/schedule_exam', methods=['POST'])
@login_required
def schedule_exam(animal_id):
    from models import ExamAppointment, AgendaEvento, Veterinario, Animal, Message
    data = request.get_json(silent=True) or {}
    specialist_id = data.get('specialist_id')
    date_str = data.get('date')
    time_str = data.get('time')
    if not all([specialist_id, date_str, time_str]):
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    scheduled_at_local = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    scheduled_at = (
        scheduled_at_local
        .replace(tzinfo=BR_TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    # Ensure requested time falls within the veterinarian's available schedule
    available_times = get_available_times(specialist_id, scheduled_at_local.date(), kind='exame')
    if time_str not in available_times:
        if available_times:
            msg = (
                'Horário selecionado não está disponível. '
                f"Horários disponíveis: {', '.join(available_times)}"
            )
        else:
            msg = 'Nenhum horário disponível para a data escolhida.'
        return jsonify({'success': False, 'message': msg}), 400
    duration = get_appointment_duration('exame')
    if has_conflict_for_slot(specialist_id, scheduled_at_local, duration):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
        }), 400
    vet = Veterinario.query.get(specialist_id)
    animal = Animal.query.get(animal_id)
    same_user = vet and vet.user_id == current_user.id
    appt = ExamAppointment(
        animal_id=animal_id,
        specialist_id=specialist_id,
        requester_id=current_user.id,
        scheduled_at=scheduled_at,
        status='confirmed' if same_user else 'pending',
    )
    if vet and animal:
        evento = AgendaEvento(
            titulo=f"Exame de {animal.name}",
            inicio=scheduled_at,
            fim=scheduled_at + duration,
            responsavel_id=vet.user_id,
            clinica_id=animal.clinica_id,
        )
        db.session.add(evento)
        if not same_user:
            msg = Message(
                sender_id=current_user.id,
                receiver_id=vet.user_id,
                animal_id=animal_id,
                content=(
                    f"Exame agendado para {animal.name} em {scheduled_at_local.strftime('%d/%m/%Y %H:%M')}. "
                    f"Confirme até {appt.confirm_by.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime('%H:%M')}"
                ),
            )
            db.session.add(msg)
    db.session.add(appt)
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    confirm_by = None if same_user else appt.confirm_by.isoformat()
    return jsonify({'success': True, 'confirm_by': confirm_by, 'html': html})


@app.route('/exam_appointment/<int:appointment_id>/status', methods=['POST'])
@login_required
def update_exam_appointment_status(appointment_id):
    from models import ExamAppointment, Message
    appt = ExamAppointment.query.get_or_404(appointment_id)
    if current_user.id != appt.specialist.user_id and current_user.role != 'admin':
        abort(403)
    status = request.form.get('status') or (request.get_json(silent=True) or {}).get('status')
    if status not in {'confirmed', 'canceled'}:
        return jsonify({'success': False, 'message': 'Status inválido.'}), 400
    if status == 'confirmed' and datetime.utcnow() > appt.confirm_by:
        return jsonify({'success': False, 'message': 'Tempo de confirmação expirado.'}), 400
    appt.status = status
    if status == 'canceled':
        msg = Message(
            sender_id=current_user.id,
            receiver_id=appt.requester_id,
            animal_id=appt.animal_id,
            content=f"Especialista não aceitou exame para {appt.animal.name}. Reagende com outro profissional.",
        )
        db.session.add(msg)
    elif status == 'confirmed':
        scheduled_local = appt.scheduled_at.replace(tzinfo=timezone.utc).astimezone(BR_TZ)
        msg = Message(
            sender_id=current_user.id,
            receiver_id=appt.requester_id,
            animal_id=appt.animal_id,
            content=(
                f"Exame de {appt.animal.name} confirmado para "
                f"{scheduled_local.strftime('%d/%m/%Y %H:%M')} com {appt.specialist.user.name}."
            ),
        )
        db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/exam_appointment/<int:appointment_id>/update', methods=['POST'])
@login_required
def update_exam_appointment(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    data = request.get_json(silent=True) or {}
    date_str = data.get('date')
    time_str = data.get('time')
    specialist_id = data.get('specialist_id', appt.specialist_id)
    if not date_str or not time_str:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    scheduled_at_local = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    scheduled_at = (
        scheduled_at_local
        .replace(tzinfo=BR_TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    duration = get_appointment_duration('exame')
    if has_conflict_for_slot(
        specialist_id,
        scheduled_at_local,
        duration,
        exclude_exam_id=appointment_id,
    ):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
        }), 400
    appt.specialist_id = specialist_id
    appt.scheduled_at = scheduled_at
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=appt.animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    return jsonify({'success': True, 'html': html})


@app.route('/exam_appointment/<int:appointment_id>/requester_update', methods=['POST'])
@login_required
def update_exam_appointment_requester(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    if current_user.id != appt.requester_id and current_user.role != 'admin':
        abort(403)

    data = request.get_json(silent=True) or {}
    confirm_by_str = data.get('confirm_by')
    status = data.get('status')
    updated = False

    if appt.status == 'confirmed' and any(
        value is not None for value in (confirm_by_str, status)
    ):
        return jsonify({'success': False, 'message': 'Este exame já foi confirmado pelo especialista.'}), 400

    if confirm_by_str is not None:
        if not confirm_by_str:
            appt.confirm_by = None
            updated = True
        else:
            try:
                confirm_local = datetime.strptime(confirm_by_str, '%Y-%m-%dT%H:%M')
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Formato de data inválido.'}), 400
            confirm_utc = (
                confirm_local
                .replace(tzinfo=BR_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            if appt.confirm_by != confirm_utc:
                appt.confirm_by = confirm_utc
                updated = True

    if status is not None:
        normalized_status = str(status).strip().lower()
        allowed_statuses = {'pending', 'canceled'}
        if normalized_status not in allowed_statuses:
            return jsonify({'success': False, 'message': 'Status inválido.'}), 400
        if normalized_status != appt.status:
            appt.status = normalized_status
            updated = True

    if updated:
        db.session.commit()

    status_styles = {
        'pending': {
            'badge_class': 'bg-warning text-dark',
            'icon_class': 'text-warning',
            'status_label': 'Aguardando confirmação',
            'show_time_left': True,
        },
        'confirmed': {
            'badge_class': 'bg-success',
            'icon_class': 'text-success',
            'status_label': 'Confirmado',
            'show_time_left': False,
        },
        'canceled': {
            'badge_class': 'bg-secondary',
            'icon_class': 'text-secondary',
            'status_label': 'Cancelado',
            'show_time_left': False,
        },
    }

    style = status_styles.get(appt.status, status_styles['pending'])
    now = datetime.utcnow()
    time_left_seconds = None
    time_left_display = None
    if appt.confirm_by:
        time_left = appt.confirm_by - now
        time_left_seconds = time_left.total_seconds()
        if time_left_seconds > 0 and style.get('show_time_left'):
            time_left_display = format_timedelta(time_left)

    confirm_display = (
        appt.confirm_by.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')
        if appt.confirm_by
        else None
    )
    confirm_local_value = (
        appt.confirm_by.replace(tzinfo=timezone.utc).astimezone(BR_TZ).strftime('%Y-%m-%dT%H:%M')
        if appt.confirm_by
        else None
    )

    return jsonify({
        'success': True,
        'updated': updated,
        'exam': {
            'id': appt.id,
            'status': appt.status,
            'status_label': style['status_label'],
            'badge_class': style['badge_class'],
            'icon_class': style['icon_class'],
            'confirm_by': appt.confirm_by.isoformat() if appt.confirm_by else None,
            'confirm_by_display': confirm_display,
            'confirm_by_value': confirm_local_value,
            'show_time_left': bool(style.get('show_time_left') and time_left_seconds and time_left_seconds > 0),
            'time_left_seconds': time_left_seconds,
            'time_left_display': time_left_display,
        },
    })


@app.route('/exam_appointment/<int:appointment_id>/delete', methods=['POST'])
@login_required
def delete_exam_appointment(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    animal_id = appt.animal_id
    db.session.delete(appt)
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    return jsonify({'success': True, 'html': html})


@app.route('/animal/<int:animal_id>/exam_appointments')
@login_required
def animal_exam_appointments(animal_id):
    from models import ExamAppointment
    appointments = (
        ExamAppointment.query.filter_by(animal_id=animal_id)
        .order_by(ExamAppointment.scheduled_at.desc())
        .all()
    )
    return render_template('partials/historico_exam_appointments.html', appointments=appointments)


@app.route('/servico', methods=['POST'])
@login_required
def criar_servico_clinica():
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem adicionar itens.'}), 403
    data = request.get_json(silent=True) or {}
    descricao = data.get('descricao')
    valor = data.get('valor')
    procedure_code = (data.get('procedure_code') or '').strip() or None
    if not descricao or valor is None:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    clinica_id = None
    if getattr(current_user, 'veterinario', None):
        clinica_id = current_user.veterinario.clinica_id
    elif current_user.clinica_id:
        clinica_id = current_user.clinica_id
    servico = ServicoClinica(
        descricao=descricao,
        valor=valor,
        clinica_id=clinica_id,
        procedure_code=procedure_code,
    )
    db.session.add(servico)
    db.session.commit()
    return jsonify({
        'id': servico.id,
        'descricao': servico.descricao,
        'valor': float(servico.valor),
        'procedure_code': servico.procedure_code,
    }), 201


@app.route('/imprimir_orcamento/<int:consulta_id>')
@login_required
def imprimir_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal = consulta.animal
    tutor = animal.owner
    veterinario = consulta.veterinario
    clinica = consulta.clinica or (
        veterinario.veterinario.clinica if veterinario and veterinario.veterinario else None
    )
    return render_template(
        'orcamentos/imprimir_orcamento.html',
        itens=consulta.orcamento_items,
        total=consulta.total_orcamento,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
    )


@app.route('/imprimir_bloco_orcamento/<int:bloco_id>')
@login_required
def imprimir_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else current_user
    clinica = consulta.clinica if consulta and consulta.clinica else bloco.clinica
    return render_template(
        'orcamentos/imprimir_orcamento.html',
        itens=bloco.itens,
        total=bloco.total,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
    )


@app.route('/orcamento/<int:orcamento_id>/imprimir')
@login_required
def imprimir_orcamento_padrao(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    ensure_clinic_access(orcamento.clinica_id)
    return render_template(
        'orcamentos/imprimir_orcamento_padrao.html',
        itens=orcamento.items,
        total=orcamento.total,
        clinica=orcamento.clinica,
        orcamento=orcamento,
        veterinario=current_user,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
    )


@app.route('/pagar_orcamento/<int:bloco_id>', methods=['GET', 'POST'])
@login_required
def pagar_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if not bloco.itens:
        if request.accept_mimetypes.accept_json:
            return jsonify({'success': False, 'message': 'Nenhum item no orçamento.'}), 400
        flash('Nenhum item no orçamento.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    items = [
        {
            'id': str(it.id),
            'title': it.descricao,
            'quantity': 1,
            'unit_price': float(it.valor),
        }
        for it in bloco.itens
    ]

    preference_data = {
        'items': items,
        'external_reference': f'bloco_orcamento-{bloco.id}',
        'notification_url': url_for('notificacoes_mercado_pago', _external=True),
        'statement_descriptor': current_app.config.get('MERCADOPAGO_STATEMENT_DESCRIPTOR'),
        'back_urls': {
            s: url_for('consulta_direct', animal_id=bloco.animal_id, _external=True)
            for s in ('success', 'failure', 'pending')
        },
        'auto_return': 'approved',
    }

    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception:
        current_app.logger.exception('Erro de conexão com Mercado Pago')
        if request.accept_mimetypes.accept_json:
            return jsonify({'success': False, 'message': 'Falha ao conectar com Mercado Pago.'}), 502
        flash('Falha ao conectar com Mercado Pago.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    if resp.get('status') != 201:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        if request.accept_mimetypes.accept_json:
            return jsonify({'success': False, 'message': 'Erro ao iniciar pagamento.'}), 502
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    pref = resp['response']
    payment_url = pref.get('init_point')
    if not payment_url:
        if request.accept_mimetypes.accept_json:
            return jsonify({'success': False, 'message': 'Retorno de pagamento inválido.'}), 502
        flash('Retorno de pagamento inválido.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))
    bloco.payment_link = payment_url
    bloco.payment_reference = str(pref.get('id') or pref.get('external_reference') or f'bloco_orcamento-{bloco.id}')
    bloco.payment_status = 'pending'
    db.session.commit()
    if request.accept_mimetypes.accept_json:
        historico_html = _render_orcamento_history(bloco.animal, bloco.clinica_id)
        return jsonify({
            'success': True,
            'redirect_url': bloco.payment_link,
            'payment_status': bloco.payment_status,
            'html': historico_html,
            'message': 'Link de pagamento gerado com sucesso.'
        })
    return redirect(payment_url)

@app.route('/consulta/<int:consulta_id>/pagar_orcamento')
@login_required
def pagar_consulta_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not consulta.orcamento_items:
        flash('Nenhum item no orçamento.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    items = [
        {
            'id': str(it.id),
            'title': it.descricao,
            'quantity': 1,
            'unit_price': float(it.valor),
        }
        for it in consulta.orcamento_items
    ]

    preference_data = {
        'items': items,
        'external_reference': f'consulta-{consulta.id}',
        'notification_url': url_for('notificacoes_mercado_pago', _external=True),
        'statement_descriptor': current_app.config.get('MERCADOPAGO_STATEMENT_DESCRIPTOR'),
        'back_urls': {
            s: url_for('consulta_direct', animal_id=consulta.animal_id, _external=True)
            for s in ('success', 'failure', 'pending')
        },
        'auto_return': 'approved',
    }

    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception:
        current_app.logger.exception('Erro de conexão com Mercado Pago')
        flash('Falha ao conectar com Mercado Pago.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    if resp.get('status') != 201:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    pref = resp['response']
    return redirect(pref['init_point'])


@app.route('/consulta/<int:consulta_id>/orcamento_item', methods=['POST'])
@login_required
def adicionar_orcamento_item(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem adicionar itens.'}), 403
    clinic_id = consulta.clinica_id or current_user_clinic_id()
    if not clinic_id:
        return jsonify({'success': False, 'message': 'Consulta sem clínica associada.'}), 400
    if not consulta.clinica_id:
        consulta.clinica_id = clinic_id
    data = request.get_json(silent=True) or {}
    servico_id = data.get('servico_id')
    descricao = data.get('descricao')
    valor = data.get('valor')
    procedure_code = (data.get('procedure_code') or '').strip() or None
    payer_type = data.get('payer_type') or default_payer_type_for_consulta(consulta)
    if payer_type not in PAYER_TYPE_LABELS:
        return jsonify({'success': False, 'message': 'Tipo de pagador inválido.'}), 400

    servico = None
    if servico_id:
        servico = ServicoClinica.query.get(servico_id)
        if not servico:
            return jsonify({'success': False, 'message': 'Item não encontrado.'}), 404
        if servico.clinica_id and servico.clinica_id != clinic_id:
            return jsonify({'success': False, 'message': 'Item indisponível para esta clínica.'}), 403
        descricao = servico.descricao
        if valor is None:
            valor = servico.valor
        if not procedure_code:
            procedure_code = servico.procedure_code

    if not descricao or valor is None:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    orcamento = None
    orcamento = consulta.orcamento
    if not orcamento:
        desc = f"Orçamento da consulta {consulta.id} - {consulta.animal.name}"
        orcamento = Orcamento(
            clinica_id=clinic_id,
            consulta_id=consulta.id,
            descricao=desc,
        )
        db.session.add(orcamento)
        db.session.flush()

    item = OrcamentoItem(
        consulta_id=consulta.id,
        orcamento_id=orcamento.id if orcamento else None,
        descricao=descricao,
        valor=valor,
        servico_id=servico.id if servico else None,
        clinica_id=clinic_id,
        procedure_code=procedure_code,
        payer_type=payer_type,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({
        'id': item.id,
        'descricao': item.descricao,
        'valor': float(item.valor),
        'total': float(consulta.total_orcamento),
        'payer_type': item.payer_type,
        'payer_label': payer_type_label(item.payer_type),
        'coverage_status': item.coverage_status,
        'coverage_label': coverage_label(item.coverage_status),
        'coverage_badge': coverage_badge(item.coverage_status),
        'coverage_message': item.coverage_message,
    }), 201


@app.route('/consulta/orcamento_item/<int:item_id>', methods=['DELETE'])
@login_required
def deletar_orcamento_item(item_id):
    item = OrcamentoItem.query.get_or_404(item_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem remover itens.'}), 403
    consulta = item.consulta
    ensure_clinic_access(consulta.clinica_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'total': float(consulta.total_orcamento)}), 200


@app.route('/consulta/<int:consulta_id>/bloco_orcamento', methods=['POST'])
@login_required
def salvar_bloco_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem salvar orçamento.'}), 403
    if not consulta.orcamento_items:
        return jsonify({'success': False, 'message': 'Nenhum item no orçamento.'}), 400
    data = request.get_json(silent=True) or {}
    discount_percent = data.get('discount_percent')
    discount_value = data.get('discount_value')
    tutor_notes = (data.get('tutor_notes') or '').strip() or None
    bloco = BlocoOrcamento(
        animal_id=consulta.animal_id,
        clinica_id=consulta.clinica_id,
        tutor_notes=tutor_notes,
        payment_status='draft'
    )
    db.session.add(bloco)
    db.session.flush()
    for item in list(consulta.orcamento_items):
        item.bloco_id = bloco.id
        item.consulta_id = None
        db.session.add(item)
    total_bruto = sum((item.valor for item in bloco.itens), Decimal('0.00'))
    total_particular = sum(
        (item.valor for item in bloco.itens if (item.payer_type or 'particular') == 'particular'),
        Decimal('0.00')
    )
    desconto_decimal = Decimal('0.00')
    try:
        if discount_value is not None:
            desconto_decimal = Decimal(str(discount_value))
        elif discount_percent is not None:
            percentual = Decimal(str(discount_percent))
            desconto_decimal = (total_particular * percentual) / Decimal('100')
    except Exception:
        desconto_decimal = Decimal('0.00')

    if desconto_decimal < 0:
        desconto_decimal = Decimal('0.00')
    if desconto_decimal > total_particular:
        desconto_decimal = total_particular

    bloco.discount_percent = None
    if discount_percent is not None:
        try:
            bloco.discount_percent = Decimal(str(discount_percent))
        except Exception:
            bloco.discount_percent = None
    bloco.discount_value = desconto_decimal if desconto_decimal else None
    bloco.net_total = total_bruto - desconto_decimal if total_bruto is not None else None
    if bloco.net_total is not None and bloco.net_total < 0:
        bloco.net_total = Decimal('0.00')
    db.session.commit()
    historico_html = _render_orcamento_history(consulta.animal, consulta.clinica_id)
    return jsonify({'success': True, 'html': historico_html})


@app.route('/bloco_orcamento/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem excluir.'}), 403
    animal_id = bloco.animal_id
    clinic_id = bloco.clinica_id
    db.session.delete(bloco)
    db.session.commit()
    if request.accept_mimetypes.accept_json:
        animal = Animal.query.get(animal_id)
        historico_html = _render_orcamento_history(
            animal,
            clinic_id or getattr(animal, 'clinica_id', None)
        )
        return jsonify({'success': True, 'html': historico_html})
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@app.route('/bloco_orcamento/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403
    return render_template('orcamentos/editar_bloco_orcamento.html', bloco=bloco)


@app.route('/bloco_orcamento/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if current_user.worker != 'veterinario':
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403

    data = request.get_json(silent=True) or {}
    itens = data.get('itens', [])

    for item in list(bloco.itens):
        db.session.delete(item)

    for it in itens:
        descricao = (it.get('descricao') or '').strip()
        valor = it.get('valor')
        if not descricao or valor is None:
            continue
        try:
            valor_decimal = Decimal(str(valor))
        except Exception:
            continue
        bloco.itens.append(
            OrcamentoItem(
                descricao=descricao,
                valor=valor_decimal,
                clinica_id=bloco.clinica_id,
            )
        )

    db.session.commit()

    historico_html = _render_orcamento_history(bloco.animal, bloco.clinica_id)
    return jsonify(success=True, html=historico_html)


if __name__ == "__main__":
    # Usa a porta 8080 se existir no ambiente (como no Docker), senão usa 5000
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
