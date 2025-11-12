import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import (
    app as flask_app,
    _nim_default_rows,
    nim_room_members,
    nim_room_players,
    nim_rooms,
    nim_session_players,
    nim_session_rooms,
    socketio,
)


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True)
    yield flask_app


def _reset_nim_state():
    nim_rooms.clear()
    nim_session_rooms.clear()
    nim_session_players.clear()
    nim_room_members.clear()
    nim_room_players.clear()


def test_nim_rejects_out_of_turn_move(app):
    _reset_nim_state()
    room_code = "TURNTST"

    player_one = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")
    assert player_one.is_connected()

    player_two = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")
    assert player_two.is_connected()

    try:
        # Player two attempts to remove a stick while it's player one's turn.
        invalid_move = {
            "rows": [
                [False, True, True],
                [True, True, True],
                [True, True, True],
                [True, True],
                [True, True],
            ],
            "turn": 1,
            "winner": None,
            "players": {1: "Jogador 1", 2: "Jogador 2"},
            "has_played": True,
            "active_row": 0,
        }
        player_two.emit("move", invalid_move)

        current_state = nim_rooms[room_code]
        assert current_state["turn"] == 1
        assert current_state["rows"][0] == [True, True, True]

        # Player one makes the same move, which should now be accepted.
        valid_move = {
            **invalid_move,
            "rows": [row[:] for row in invalid_move["rows"]],
        }
        player_one.emit("move", valid_move)

        current_state = nim_rooms[room_code]
        assert current_state["rows"][0] == [False, True, True]
    finally:
        player_one.disconnect()
        player_two.disconnect()
        _reset_nim_state()


def test_nim_reset_alternates_starting_player(app):
    _reset_nim_state()
    room_code = "ALTSTRT"

    player_one = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")
    assert player_one.is_connected()

    player_two = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")
    assert player_two.is_connected()

    try:
        initial_state = nim_rooms[room_code]
        assert initial_state["turn"] == 1
        assert initial_state["starting_player"] == 1

        reset_payload_first = {
            "rows": _nim_default_rows(),
            "turn": 2,
            "winner": None,
            "players": {1: "Jogador 1", 2: "Jogador 2"},
            "has_played": False,
            "active_row": None,
        }
        player_one.emit("move", reset_payload_first)

        after_first_reset = nim_rooms[room_code]
        assert after_first_reset["turn"] == 2
        assert after_first_reset["starting_player"] == 2

        reset_payload_second = {
            "rows": _nim_default_rows(),
            "turn": 1,
            "winner": None,
            "players": {1: "Jogador 1", 2: "Jogador 2"},
            "has_played": False,
            "active_row": None,
        }
        player_two.emit("move", reset_payload_second)

        after_second_reset = nim_rooms[room_code]
        assert after_second_reset["turn"] == 1
        assert after_second_reset["starting_player"] == 1
    finally:
        player_one.disconnect()
        player_two.disconnect()
        _reset_nim_state()
