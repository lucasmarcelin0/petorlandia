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


def test_nim_sync_on_fresh_board_does_not_flip_starting_player(app):
    """Entrar na sala, mandar o tema ou editar um nome nao e "Reiniciar".

    Com o tabuleiro intacto, essas sincronizacoes mandam o tabuleiro inicial com
    a mesma vez do servidor. Antes eram lidas como reset e a vez trocava de dono
    a cada nome digitado.
    """
    _reset_nim_state()
    room_code = "SYNCNOME"

    player_one = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")
    player_two = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")

    try:
        sync_payload = {
            "rows": _nim_default_rows(),
            "turn": 1,
            "winner": None,
            "players": {1: "Marcelino", 2: "Jogador 2"},
            "has_played": False,
            "active_row": None,
            "bg_gradient": "radial-gradient(circle at top left, red, blue)",
            "stick_color": "hsl(10, 70%, 68%)",
        }
        player_one.emit("move", sync_payload)
        state = nim_rooms[room_code]
        assert state["turn"] == 1
        assert state["starting_player"] == 1
        assert state["players"][1] == "Marcelino"
        assert state["bg_gradient"] == sync_payload["bg_gradient"]

        player_two.emit("move", {**sync_payload, "players": {1: "Marcelino", 2: "Novais"}})
        state = nim_rooms[room_code]
        assert state["turn"] == 1
        assert state["starting_player"] == 1
        assert state["players"] == {1: "Marcelino", 2: "Novais"}

        # O botao Reiniciar propoe a outra vez e continua funcionando.
        player_one.emit("move", {**sync_payload, "turn": 2})
        state = nim_rooms[room_code]
        assert state["turn"] == 2
        assert state["starting_player"] == 2
    finally:
        player_one.disconnect()
        player_two.disconnect()
        _reset_nim_state()


def test_nim_connect_tells_each_client_its_seat(app):
    _reset_nim_state()
    room_code = "LUGARES"

    player_one = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")
    player_two = socketio.test_client(app, namespace="/", query_string=f"sala={room_code}")

    try:
        def seats(client):
            return [
                event["args"][0]["seat"]
                for event in client.get_received("/")
                if event["name"] == "seat"
            ]

        assert seats(player_one) == [1]
        assert seats(player_two) == [2]
    finally:
        player_one.disconnect()
        player_two.disconnect()
        _reset_nim_state()


def test_desafio_page_loads_socket_client_allowed_by_csp(app):
    """O modo online depende de `io`; se o script for bloqueado, o jogo cai no local.

    A pagina carregava o cliente de cdn.socket.io, host fora do `script-src` da
    CSP. O navegador bloqueava o script e o Desafio Secreto mostrava "Modo
    online indisponivel" para todo mundo.
    """
    client = app.test_client()

    page = client.get("/surpresa/desafio.html")
    game_script = client.get("/surpresa/main.js")
    socket_client = client.get("/surpresa/socket.io.min.js")

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'src="/surpresa/socket.io.min.js"' in html
    assert "cdn.socket.io" not in html
    assert 'src="/surpresa/main.js?v=' in html

    script_src = next(
        directive
        for directive in page.headers["Content-Security-Policy"].split(";")
        if directive.strip().startswith("script-src")
    )
    assert "'self'" in script_src.split()

    assert socket_client.status_code == 200
    assert b"Socket.IO" in socket_client.data

    # Sem cache longo: uma copia antiga da pagina manteria o modo online quebrado.
    assert page.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
    assert game_script.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
    game_js = game_script.get_data(as_text=True)
    assert 'socket.on("connect_error"' in game_js
    assert 'socket.on("seat"' in game_js
