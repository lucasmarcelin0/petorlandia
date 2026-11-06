# -*- coding: utf-8 -*-
"""O deploy de fallback compara com o que esta no ar, nao com o Git do Heroku.

A integracao GitHub do Heroku publica por tarball e deixa o `main` do
git.heroku.com parado no ultimo push manual. O fallback antigo comparava com
ele e se recusava a publicar justamente quando a integracao parou (06/11/2026).
"""

from __future__ import annotations

import pytest

from scripts import heroku_build_from_github as builder


def _nunca_ancestral(_a, _b):
    return False


def _sempre_ancestral(_a, _b):
    return True


def test_producao_no_mesmo_commit_nao_publica():
    assert builder.decide("abc", "abc", _nunca_ancestral) == "nada"


def test_producao_atras_do_ref_publica():
    assert builder.decide("velho", "novo", _sempre_ancestral) == "publicar"


def test_producao_com_commit_fora_do_ref_recusa():
    assert builder.decide("avulso", "novo", _nunca_ancestral) == "recusar"


def test_app_sem_commit_registrado_publica():
    assert builder.decide(None, "novo", _nunca_ancestral) == "publicar"


def test_commit_em_producao_vem_do_ultimo_release_concluido(monkeypatch):
    respostas = {
        "/apps/app/releases": [
            {"version": 9, "status": "failed", "slug": {"id": "s9"}},
            {"version": 8, "status": "succeeded", "slug": None},
            {"version": 7, "status": "succeeded", "slug": {"id": "s7"}},
        ],
        "/apps/app/slugs/s7": {"commit": "sha7"},
    }
    monkeypatch.setattr(builder, "_request", lambda path, *_a, **_k: respostas[path])

    assert builder.production_commit("app", "token") == "sha7"


def test_build_usa_tarball_do_github_no_sha(monkeypatch):
    chamadas = []

    def _fake(path, _token, data=None, **_k):
        chamadas.append((path, data))
        return {"id": "b1"}

    monkeypatch.setattr(builder, "_request", _fake)
    builder.create_build("app", "token", "dono/repo", "f" * 40)

    path, data = chamadas[0]
    assert path == "/apps/app/builds"
    assert data["source_blob"] == {
        "url": f"https://github.com/dono/repo/archive/{'f' * 40}.tar.gz",
        "version": "f" * 40,
    }


@pytest.mark.parametrize("status, esperado", [("succeeded", 0), ("failed", 1)])
def test_main_espera_o_build(monkeypatch, tmp_path, status, esperado):
    saida = tmp_path / "out"
    monkeypatch.setenv("HEROKU_API_KEY", "t")
    monkeypatch.setenv("GITHUB_OUTPUT", str(saida))
    monkeypatch.setattr(builder, "production_commit", lambda *_: "velho")
    monkeypatch.setattr(builder, "is_ancestor", _sempre_ancestral)
    monkeypatch.setattr(builder, "decide", lambda c, s: "publicar")
    monkeypatch.setattr(builder, "create_build", lambda *_: {"id": "b1"})
    monkeypatch.setattr(builder, "wait_build", lambda *_: {"status": status})
    monkeypatch.setattr(builder, "build_log", lambda *_: "")

    assert builder.main(["--app", "a", "--repo", "d/r", "--sha", "novo"]) == esperado
    publicou = saida.exists() and "publicou=true" in saida.read_text()
    assert publicou == (esperado == 0)


def test_main_recusa_sem_criar_build(monkeypatch):
    monkeypatch.setenv("HEROKU_API_KEY", "t")
    monkeypatch.setattr(builder, "production_commit", lambda *_: "avulso")
    monkeypatch.setattr(builder, "decide", lambda c, s: "recusar")
    monkeypatch.setattr(builder, "create_build", lambda *_: pytest.fail("nao deveria criar build"))

    assert builder.main(["--app", "a", "--repo", "d/r", "--sha", "novo"]) == 1
