"""Desafio de Palitos (jogo Nim) em tempo real via Socket.IO.

Extraído do ``app.py`` sem mudança de comportamento: o estado das salas, as
regras e os handlers são os mesmos. O ``app.py`` reexporta estes nomes (para
``from app import ...`` continuar funcionando) e chama
``registrar_handlers_nim(socketio)`` no mesmo ponto em que os decoradores
eram aplicados.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable

from flask import request
from flask_socketio import disconnect, emit, join_room, leave_room


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


def _nim_parse_player(val, default_val: int | None) -> int | None:
    try:
        val = int(val)
        return val if val in (1, 2) else default_val
    except (TypeError, ValueError):
        return default_val


def _nim_has_restorations(current_rows: list[list[bool]], proposed_rows: list[list[bool]]) -> bool:
    for current_row, next_row in zip(current_rows, proposed_rows):
        for current_value, next_value in zip(current_row, next_row):
            if not current_value and next_value:
                return True
    return False


def _nim_count_removals(baseline_rows: list[list[bool]], proposed_rows: list[list[bool]]) -> list[int]:
    removed_by_row_turn: list[int] = [0] * len(NIM_TEMPLATE_ROWS)
    for row_index, (baseline_row, next_row) in enumerate(zip(baseline_rows, proposed_rows)):
        for baseline_value, next_value in zip(baseline_row, next_row):
            if baseline_value and not next_value:
                removed_by_row_turn[row_index] += 1
    return removed_by_row_turn


def _nim_normalize_alternates(current_alternates) -> list[bool]:
    if not isinstance(current_alternates, (list, tuple)):
        return [False] * len(NIM_TEMPLATE_ROWS)
    return [
        bool(current_alternates[index]) if index < len(current_alternates) else False
        for index in range(len(NIM_TEMPLATE_ROWS))
    ]


def _nim_next_alternates(normalized_alternates: list[bool], proposed_rows: list[list[bool]]) -> list[bool]:
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
    return next_alternates


def _nim_enforce_rules(current_state: dict, proposed_state: dict) -> dict | None:
    """Validate the proposed state according to the house rules."""

    proposed_rows = _nim_copy_rows(proposed_state.get("rows", []))
    current_rows = _nim_copy_rows(current_state.get("rows", _nim_default_rows()))

    current_start_int = _nim_parse_player(current_state.get("starting_player", 1), 1)
    proposed_state["starting_player"] = current_start_int

    origin_candidate = current_state.get("turn_origin_rows")
    if not isinstance(origin_candidate, list) or len(origin_candidate) != len(NIM_TEMPLATE_ROWS):
        baseline_rows = _nim_copy_rows(current_rows)
    else:
        baseline_rows = _nim_copy_rows(origin_candidate)

    default_rows = _nim_default_rows()
    proposed_turn_int = _nim_parse_player(proposed_state.get("turn"), None)
    has_played_bool = bool(proposed_state.get("has_played"))
    winner_flag = proposed_state.get("winner")

    current_turn_int = _nim_parse_player(current_state.get("turn"), 1)
    looks_like_reset = (
        proposed_rows == default_rows
        and (winner_flag is None or winner_flag == "")
        and not has_played_bool
        and proposed_turn_int in (1, 2)
    )
    # Com o tabuleiro ainda intacto, o cliente reenvia esse mesmo formato ao
    # entrar na sala (tema), ao editar um nome ou ao voltar do modo local. Nesses
    # casos a vez vem igual a do servidor; tratar como "Reiniciar" invertia quem
    # comeca a cada sincronizacao. O botao Reiniciar sempre propoe a outra vez.
    board_is_fresh = (
        current_rows == default_rows
        and current_state.get("winner") in (None, "")
        and not current_state.get("has_played")
    )
    is_reset = looks_like_reset and (
        not board_is_fresh or proposed_turn_int != current_turn_int
    )

    if _nim_has_restorations(current_rows, proposed_rows) and not is_reset:
        return None

    removed_by_row_turn = _nim_count_removals(baseline_rows, proposed_rows)
    total_removed_turn = sum(removed_by_row_turn)
    rows_with_removals = [index for index, count in enumerate(removed_by_row_turn) if count > 0]

    next_turn_int = _nim_parse_player(proposed_state.get("turn"), current_turn_int)

    proposed_state["turn"] = next_turn_int
    turn_changed = current_turn_int != next_turn_int

    normalized_alternates = _nim_normalize_alternates(current_state.get("alternate_rows"))

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

    proposed_state["rows"] = proposed_rows
    proposed_state["alternate_rows"] = _nim_next_alternates(normalized_alternates, proposed_rows)
    proposed_state["has_played"] = False if turn_changed else total_removed_turn > 0

    all_taken = all(not any(row) for row in proposed_rows)
    if not all_taken:
        proposed_state["winner"] = None
    else:
        proposed_state["winner"] = next_turn_int if turn_changed else (1 if next_turn_int == 2 else 2)

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


def _extract_nim_rows(payload: dict) -> list[list[bool]] | None:
    rows = payload.get("rows")
    if not isinstance(rows, (list, tuple)) or len(rows) != len(NIM_TEMPLATE_ROWS):
        return None

    normalized_rows: list[list[bool]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != len(NIM_TEMPLATE_ROWS[index]):
            return None
        normalized_rows.append([bool(value) for value in row])
    return normalized_rows


def _extract_nim_turn(payload: dict, current_state: dict) -> int:
    turn = payload.get("turn", current_state["turn"])
    try:
        turn_int = int(turn)
    except (TypeError, ValueError):
        turn_int = current_state["turn"]
    if turn_int not in (1, 2):
        turn_int = 1
    return turn_int


def _extract_nim_winner(payload: dict) -> int | None:
    winner_value = payload.get("winner")
    if winner_value in (None, "", "null"):
        return None
    try:
        winner_int = int(winner_value)
    except (TypeError, ValueError):
        return None
    if winner_int not in (1, 2):
        return None
    return winner_int


def _extract_nim_has_played(payload: dict, current_state: dict) -> bool:
    has_played_raw = payload.get("has_played")
    if has_played_raw is None:
        has_played_raw = current_state.get("has_played", False)
    if isinstance(has_played_raw, str):
        has_played_raw = has_played_raw.strip().lower()
        if has_played_raw in {"1", "true", "yes", "on"}:
            return True
        elif has_played_raw in {"0", "false", "no", "off", ""}:
            return False
        else:
            return current_state.get("has_played", False)
    return bool(has_played_raw)


def _extract_nim_active_row(payload: dict, current_state: dict) -> int | None:
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
    if active_row_int is not None and not (0 <= active_row_int < len(NIM_TEMPLATE_ROWS)):
        active_row_int = None
    return active_row_int


def _extract_nim_string_field(payload: dict, current_state: dict, snake_key: str, camel_key: str, max_length: int) -> str | None:
    value = payload.get(snake_key)
    if value is None:
        value = payload.get(camel_key)
    if value is None:
        return current_state.get(snake_key)
    text = str(value).strip()
    return text[:max_length] if text else current_state.get(snake_key)


def _extract_nim_player_emojis(payload: dict, current_state: dict) -> list[str]:
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
        return normalized_emojis
    else:
        current_emojis = current_state.get("player_emojis")
        if isinstance(current_emojis, (list, tuple)):
            player_emojis = [str(value)[:8] for value in current_emojis[:2]]
            if len(player_emojis) < 2:
                player_emojis.extend(["🐾"] * (2 - len(player_emojis)))
            return player_emojis
        else:
            return ["🐾", "🐾"]


def _extract_nim_starting_player(payload: dict, current_state: dict) -> int:
    starting_player_value = payload.get("starting_player")
    if starting_player_value is None:
        starting_player_value = payload.get("startingPlayer")
    if starting_player_value is None:
        return current_state.get("starting_player", 1)
    try:
        starting_player = int(starting_player_value)
    except (TypeError, ValueError):
        return current_state.get("starting_player", 1)
    if starting_player not in (1, 2):
        return current_state.get("starting_player", 1) or 1
    return starting_player


def _normalize_nim_payload(payload: dict | None, current_state: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None

    normalized_rows = _extract_nim_rows(payload)
    if normalized_rows is None:
        return None

    return {
        "rows": normalized_rows,
        "turn": _extract_nim_turn(payload, current_state),
        "winner": _extract_nim_winner(payload),
        "players": _normalize_nim_players(payload.get("players"), current_state.get("players", {})),
        "has_played": _extract_nim_has_played(payload, current_state),
        "active_row": _extract_nim_active_row(payload, current_state),
        "bg_gradient": _extract_nim_string_field(payload, current_state, "bg_gradient", "bgGradient", 200),
        "stick_color": _extract_nim_string_field(payload, current_state, "stick_color", "stickColor", 50),
        "player_emojis": _extract_nim_player_emojis(payload, current_state),
        "starting_player": _extract_nim_starting_player(payload, current_state),
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
    # O servidor so aceita jogadas de quem esta na vez; o cliente precisa saber
    # qual lugar ocupa para avisar isso em vez de desfazer o clique em silencio.
    emit("seat", {"seat": assigned_seat, "room": room})
    emit("update_state", _nim_payload(room))


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


def registrar_handlers_nim(socketio) -> None:
    """Liga os eventos do namespace padrão aos handlers do jogo."""
    socketio.on("connect")(nim_connect)
    socketio.on("move")(nim_move)
    socketio.on("disconnect")(nim_disconnect)
