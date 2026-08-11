import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import (
    CALL_NAMESPACE,
    app as flask_app,
    call_room_members,
    call_room_players,
    call_session_players,
    call_session_rooms,
    socketio,
)


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True)
    yield flask_app


def _reset_call_state():
    call_room_members.clear()
    call_room_players.clear()
    call_session_players.clear()
    call_session_rooms.clear()


def _events(client, name):
    return [event for event in client.get_received(CALL_NAMESPACE) if event["name"] == name]


def test_call_page_is_available_from_the_secret_arcade(app):
    client = app.test_client()

    arcade = client.get("/surpresa")
    room = client.get("/surpresa/sala-a-dois.html")

    assert arcade.status_code == 200
    assert b"/surpresa/sala-a-dois.html" in arcade.data
    assert room.status_code == 200
    assert "Compartilhar tela" in room.get_data(as_text=True)
    assert "Jogo da Velha" not in room.get_data(as_text=True)


def test_call_room_relays_signals_only_to_the_other_participant(app):
    _reset_call_state()
    first = socketio.test_client(app, namespace=CALL_NAMESPACE, query_string="sala=AMOR123")
    second = socketio.test_client(app, namespace=CALL_NAMESPACE, query_string="sala=AMOR123")

    try:
        assert first.is_connected(CALL_NAMESPACE)
        assert second.is_connected(CALL_NAMESPACE)
        first.get_received(CALL_NAMESPACE)
        second.get_received(CALL_NAMESPACE)

        first.emit(
            "webrtc_signal",
            {"description": {"type": "offer", "sdp": "v=0\r\nexample"}},
            namespace=CALL_NAMESPACE,
        )

        assert _events(first, "webrtc_signal") == []
        relayed = _events(second, "webrtc_signal")
        assert relayed[0]["args"][0] == {
            "description": {"type": "offer", "sdp": "v=0\r\nexample"}
        }
    finally:
        if first.is_connected(CALL_NAMESPACE):
            first.disconnect(namespace=CALL_NAMESPACE)
        if second.is_connected(CALL_NAMESPACE):
            second.disconnect(namespace=CALL_NAMESPACE)
        _reset_call_state()


def test_call_room_accepts_only_two_people(app):
    _reset_call_state()
    first = socketio.test_client(app, namespace=CALL_NAMESPACE, query_string="sala=SO-DOIS")
    second = socketio.test_client(app, namespace=CALL_NAMESPACE, query_string="sala=SO-DOIS")
    third = socketio.test_client(app, namespace=CALL_NAMESPACE, query_string="sala=SO-DOIS")

    try:
        assert first.is_connected(CALL_NAMESPACE)
        assert second.is_connected(CALL_NAMESPACE)
        assert not third.is_connected(CALL_NAMESPACE)
        assert len(call_room_members["SO-DOIS"]) == 2
    finally:
        if first.is_connected(CALL_NAMESPACE):
            first.disconnect(namespace=CALL_NAMESPACE)
        if second.is_connected(CALL_NAMESPACE):
            second.disconnect(namespace=CALL_NAMESPACE)
        _reset_call_state()
