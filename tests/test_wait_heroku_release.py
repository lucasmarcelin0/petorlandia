# -*- coding: utf-8 -*-
"""O deploy so termina quando o release phase termina.

`git push heroku` volta assim que o build acaba, mas o `release: flask db
upgrade` do Procfile roda depois. Sem esperar por ele, uma migration quebrada
apareceria como deploy bem-sucedido enquanto o dyno novo se recusa a subir --
o erro que o DEPLOY.md descreve. Estes testes travam a espera.
"""

from __future__ import annotations

import pytest

from scripts import wait_heroku_release as waiter


def _releases(*sequencia):
    """Devolve um `latest_release` falso que percorre a sequencia dada."""
    restante = list(sequencia)

    def _fake(_app, _token):
        return restante.pop(0) if len(restante) > 1 else restante[0]

    return _fake


def test_release_anterior_nao_conta_como_deploy_novo():
    anterior = {"version": 412, "status": "succeeded"}

    assert waiter.is_new_release(anterior, after_version=412) is False
    assert waiter.is_new_release({"version": 413, "status": "pending"}, after_version=412) is True
    assert waiter.is_new_release(None, after_version=0) is False


def test_espera_o_pendente_virar_sucesso(monkeypatch):
    monkeypatch.setattr(
        waiter,
        "latest_release",
        _releases(
            {"version": 412, "status": "succeeded"},
            {"version": 413, "status": "pending", "description": "Deploy abc123"},
            {"version": 413, "status": "succeeded", "description": "Deploy abc123"},
        ),
    )

    assert waiter.wait_for_release("app", "token", after_version=412, timeout=5, interval=0) == 0


def test_release_que_falha_derruba_o_deploy(monkeypatch, capsys):
    monkeypatch.setattr(
        waiter,
        "latest_release",
        _releases({"version": 413, "status": "failed", "description": "Deploy abc123"}),
    )
    monkeypatch.setattr(waiter, "release_log", lambda *_args: "alembic: Multiple head revisions")

    assert waiter.wait_for_release("app", "token", after_version=412, timeout=5, interval=0) == 1
    erro = capsys.readouterr().err
    assert "FALHOU" in erro
    # O log do release phase e o que diz por que o dyno nao subiu.
    assert "Multiple head revisions" in erro


def test_release_que_nunca_sai_do_pendente_nao_vira_sucesso(monkeypatch):
    monkeypatch.setattr(
        waiter,
        "latest_release",
        _releases({"version": 413, "status": "pending"}),
    )

    assert waiter.wait_for_release("app", "token", after_version=412, timeout=0, interval=0) == 1


def test_falha_de_rede_pontual_nao_derruba_a_espera(monkeypatch):
    chamadas = {"n": 0}

    def _instavel(_app, _token):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise OSError("connection reset")
        return {"version": 413, "status": "succeeded", "description": "Deploy abc123"}

    monkeypatch.setattr(waiter, "latest_release", _instavel)

    assert waiter.wait_for_release("app", "token", after_version=412, timeout=5, interval=0) == 0
    assert chamadas["n"] >= 2


def test_token_ausente_falha_antes_de_consultar(monkeypatch):
    monkeypatch.delenv("HEROKU_API_KEY", raising=False)

    with pytest.raises(SystemExit) as saida:
        raise SystemExit(waiter.main(["--app", "qualquer"]))
    assert saida.value.code == 1
