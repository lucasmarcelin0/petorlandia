"""JS/CSS saem comprimidos em produção: o build gera .br/.gz e o WhiteNoise os entrega."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "bin" / "post_compile"


def test_script_de_build_existe_e_e_executavel():
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    texto = SCRIPT.read_text(encoding="utf-8")
    assert "whitenoise.compress" in texto and " static" in texto
    assert texto.rstrip().endswith("exit 0")          # nunca derruba o deploy


def test_arquivos_gerados_nao_entram_no_git():
    regras = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "static/**/*.br" in regras and "static/**/*.gz" in regras


def test_whitenoise_entrega_a_versao_comprimida(tmp_path):
    pytest.importorskip("whitenoise")
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from whitenoise import WhiteNoise

    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_text("const x = 1;\n" * 2000, encoding="utf-8")
    env = dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    subprocess.run([sys.executable, "-m", "whitenoise.compress", "--quiet", str(tmp_path)], check=True, env=env)
    assert (tmp_path / "js" / "app.js.gz").exists()

    app = WhiteNoise(lambda e, s: Response("app")(e, s), root=str(tmp_path), prefix="static/", max_age=3600)
    cliente = Client(app)
    r = cliente.get("/static/js/app.js?v=1", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("Content-Encoding") == "gzip"
    assert int(r.headers["Content-Length"]) < 2000 * 13
    assert "Accept-Encoding" in r.headers.get("Vary", "")
    cru = cliente.get("/static/js/app.js?v=1")
    assert cru.headers.get("Content-Encoding") is None
    assert cru.get_data(as_text=True).startswith("const x = 1;")
