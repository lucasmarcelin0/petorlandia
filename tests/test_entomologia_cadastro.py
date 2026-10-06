"""Private cadastral service tests using entirely synthetic personal records."""

import copy
import base64
import io
import json

import pytest
from flask import Flask

from services import entomologia_cadastro as cadastro


def sample_data():
    return {
        "collected_at": "2026-01-02T10:00:00-03:00",
        "collection_scope": "Synthetic pilot for tests",
        "records": [
            {
                "property_code": "001",
                "registration": "100.200.300",
                "address": "Rua das Acácias, 12, Bairro Teste",
                "owner_name": "Pessoa Fictícia Alfa",
                "owner_code": "010",
                "registry_number": "ABC-123",
            },
            {
                "property_code": "002",
                "registration": "100.200.301",
                "address": "Rua das Acácias, 14, Bairro Teste",
                "owner_name": "Pessoa Fictícia Beta",
                "owner_code": "10",
                "registry_number": "",
            },
        ],
        "owners": [
            {
                "owner_code": "010",
                "owner_name": "Pessoa Fictícia Alfa",
                "status": "consultado",
                "collected_at": "2026-01-02T10:01:00-03:00",
                "source_url": "https://atendimento-tributos.betha.cloud/#/owner/synthetic-alfa",
                "fields": [
                    {"label": "CPF", "value": "DOCUMENTO-FICTICIO-ALFA"},
                    {"label": "Telefone(s)", "value": "TELEFONE-FICTICIO-ALFA"},
                    {"label": "Endereço(s)", "value": "Endereço fictício do proprietário"},
                    {"label": "E-mail(s)", "value": ""},
                ],
            },
            {
                "owner_code": "10",
                "owner_name": "Pessoa Fictícia Beta",
                "status": "consultado",
                "collected_at": "2026-01-02T10:02:00-03:00",
                "source_url": "https://atendimento-tributos.betha.cloud/#/owner/synthetic-beta",
                "fields": [{"label": "CPF", "value": "DOCUMENTO-FICTICIO-BETA"}],
            },
        ],
        "mirrors": [{"property_code": "001", "url": "UNUSED-SENSITIVE-DOWNLOAD"}],
    }


@pytest.fixture
def private_app(tmp_path, monkeypatch):
    monkeypatch.delenv("SFA_CADASTRO_PATH", raising=False)
    instance = tmp_path / "instance"
    instance.mkdir()
    app = Flask(
        __name__, instance_path=str(instance), static_folder=str(tmp_path / "static"),
    )
    return app


def write_data(app, data=None, name="sfa_cadastro.json"):
    path = app.instance_path + "/" + name
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data if data is not None else sample_data(), handle, ensure_ascii=False)
    app.config["SFA_CADASTRO_PATH"] = path
    return path


def test_empty_query_is_metadata_only_and_summary_excludes_owner_fields(private_app):
    write_data(private_app)
    with private_app.app_context():
        status = cadastro.search_cadastro("")
        results = cadastro.search_cadastro("acacias")
    assert status == {
        "available": True,
        "metadata": {
            "records_count": 2, "owners_count": 2,
            "collected_at": "2026-01-02T10:00:00-03:00", "scope": "Synthetic pilot for tests",
        },
        "results": [],
    }
    assert len(results["results"]) == 2
    assert all(set(record) == set(cadastro.PROPERTY_FIELDS) for record in results["results"])
    serialized = json.dumps(results)
    for value in ("DOCUMENTO-FICTICIO", "TELEFONE-FICTICIO", "UNUSED-SENSITIVE-DOWNLOAD"):
        assert value not in serialized


@pytest.mark.parametrize("query", ["acacias 12", "FICTICIA alfa", "100.200.300", "001", "010"])
def test_search_ignores_accents_case_and_matches_summary_fields(private_app, query):
    write_data(private_app)
    with private_app.app_context():
        result = cadastro.search_cadastro(query)
    assert [record["property_code"] for record in result["results"]] == ["001"]


def test_search_does_not_search_owner_documents_or_contacts(private_app):
    write_data(private_app)
    with private_app.app_context():
        assert cadastro.search_cadastro("DOCUMENTO-FICTICIO")["results"] == []
        assert cadastro.search_cadastro("TELEFONE-FICTICIO")["results"] == []
        assert cadastro.search_cadastro("Endereço fictício do proprietário")["results"] == []


def test_queries_and_results_are_bounded(private_app):
    data = sample_data()
    data["records"] = [dict(data["records"][0], property_code=f"P{index:03}") for index in range(75)]
    write_data(private_app, data)
    with private_app.app_context():
        assert len(cadastro.search_cadastro("acacias", 1)["results"]) == 1
        assert len(cadastro.search_cadastro("acacias", 100000)["results"]) == cadastro.MAX_RESULTS
        assert len(cadastro.search_cadastro("acacias", "bad-limit")["results"]) == 20
        assert cadastro.search_cadastro("a")["results"] == []
        assert cadastro.search_cadastro("a" * (cadastro.MAX_QUERY_LENGTH + 1))["results"] == []
        assert cadastro.search_cadastro(None)["results"] == []
        assert cadastro.search_cadastro("\u0301\u0301")["results"] == []
        assert cadastro.search_cadastro("a\u0301")["results"] == []


def test_detail_joins_by_exact_owner_code_preserves_fields_and_missing_values(private_app):
    data = sample_data()
    write_data(private_app, data)
    with private_app.app_context():
        detail = cadastro.get_cadastro_property("001")
        other = cadastro.get_cadastro_property("002")
        assert cadastro.get_cadastro_property("1") is None
        assert cadastro.get_cadastro_property("unknown") is None
    assert detail["property"] == data["records"][0]
    assert detail["owner"] == data["owners"][0]
    assert other["owner"]["owner_code"] == "10"
    assert other["owner"]["fields"][0]["value"] == "DOCUMENTO-FICTICIO-BETA"
    assert detail["owner"]["fields"][-1]["value"] == ""


def test_missing_owner_card_does_not_join_by_name_or_change_record(private_app):
    data = sample_data()
    data["owners"] = [data["owners"][1]]
    data["owners"][0]["owner_name"] = data["records"][0]["owner_name"]
    write_data(private_app, data)
    with private_app.app_context():
        detail = cadastro.get_cadastro_property("001")
    assert detail["owner"] is None
    assert detail["property"]["owner_code"] == "010"


def test_default_private_path_never_falls_back_to_preview_or_static(private_app, tmp_path):
    output_dir = tmp_path / "output" / "betha-access-test"
    output_dir.mkdir(parents=True)
    (output_dir / "sample.json").write_text(json.dumps(sample_data()), encoding="utf-8")
    with private_app.app_context():
        result = cadastro.search_cadastro("acacias")
        detail = cadastro.get_cadastro_property("001")
    assert result["available"] is False
    assert result["results"] == []
    assert result["metadata"]["records_count"] == 0
    assert detail is None


def test_relative_config_env_and_absolute_config_use_private_files(private_app, monkeypatch):
    data = sample_data()
    path = write_data(private_app, data, name="alternate.json")
    private_app.config.pop("SFA_CADASTRO_PATH", None)
    monkeypatch.setenv("SFA_CADASTRO_PATH", "alternate.json")
    with private_app.app_context():
        assert cadastro.search_cadastro("")["available"] is True
        private_app.config["SFA_CADASTRO_PATH"] = "missing.json"
        assert cadastro.search_cadastro("")["available"] is False
        private_app.config["SFA_CADASTRO_PATH"] = path
        assert cadastro.search_cadastro("")["available"] is True


def test_public_static_source_is_rejected(private_app):
    from pathlib import Path

    public_path = Path(private_app.static_folder) / "sample.json"
    public_path.parent.mkdir()
    public_path.write_text(json.dumps(sample_data()), encoding="utf-8")
    private_app.config["SFA_CADASTRO_PATH"] = str(public_path)
    with private_app.app_context():
        assert cadastro.search_cadastro("acacias")["available"] is False
        assert cadastro.get_cadastro_property("001") is None


def test_private_data_is_reread_instead_of_cached(private_app):
    data = sample_data()
    write_data(private_app, data)
    with private_app.app_context():
        assert cadastro.get_cadastro_property("001")["owner"]["fields"][0]["value"] == "DOCUMENTO-FICTICIO-ALFA"
        replacement = copy.deepcopy(data)
        replacement["owners"][0]["fields"][0]["value"] = "DOCUMENTO-SUBSTITUIDO"
        write_data(private_app, replacement)
        assert cadastro.get_cadastro_property("001")["owner"]["fields"][0]["value"] == "DOCUMENTO-SUBSTITUIDO"
        private_app.config["SFA_CADASTRO_PATH"] = "missing.json"
        assert cadastro.search_cadastro("acacias")["available"] is False


@pytest.mark.parametrize("invalid_case", [
    "duplicate_property", "duplicate_owner", "missing_field", "non_text_field",
    "invalid_owner_fields", "unknown_owner_status", "empty_owner_code", "non_object",
])
def test_malformed_or_ambiguous_files_fail_closed(private_app, invalid_case):
    data = sample_data()
    if invalid_case == "duplicate_property":
        data["records"].append(copy.deepcopy(data["records"][0]))
    elif invalid_case == "duplicate_owner":
        data["owners"].append(copy.deepcopy(data["owners"][0]))
    elif invalid_case == "missing_field":
        del data["records"][0]["address"]
    elif invalid_case == "non_text_field":
        data["owners"][0]["fields"][0]["value"] = {"unexpected": "object"}
    elif invalid_case == "invalid_owner_fields":
        data["owners"][0]["fields"] = "wrong"
    elif invalid_case == "unknown_owner_status":
        data["owners"][0]["status"] = "unknown"
    elif invalid_case == "empty_owner_code":
        data["records"][0]["owner_code"] = ""
    elif invalid_case == "non_object":
        data = [data]
    write_data(private_app, data)
    with private_app.app_context():
        assert cadastro.search_cadastro("acacias")["available"] is False
        assert cadastro.get_cadastro_property("001") is None


def test_file_size_and_duplicate_json_keys_fail_closed(private_app, monkeypatch):
    path = write_data(private_app)
    monkeypatch.setattr(cadastro, "MAX_FILE_BYTES", 128)
    with private_app.app_context():
        assert cadastro.search_cadastro("acacias")["available"] is False
    monkeypatch.undo()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"records": [], "records": []}')
    with private_app.app_context():
        assert cadastro.search_cadastro("acacias")["available"] is False


def test_signed_or_untrusted_owner_links_are_not_returned(private_app):
    data = sample_data()
    data["owners"][0]["source_url"] = "https://tributos.betha.cloud/?access_token=SECRET-FICTICIO"
    data["owners"][1]["source_url"] = "https://untrusted.example/owner"
    write_data(private_app, data)
    with private_app.app_context():
        assert cadastro.get_cadastro_property("001")["owner"]["source_url"] == ""
        assert cadastro.get_cadastro_property("002")["owner"]["source_url"] == ""


@pytest.fixture
def snapshot_app(private_app):
    from extensions import db
    from models.entomologia import EntomologiaImportacao

    private_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    db.init_app(private_app)
    with private_app.app_context():
        EntomologiaImportacao.__table__.create(db.engine)
        yield private_app
        db.session.remove()
        EntomologiaImportacao.__table__.drop(db.engine)


def synthetic_bytes(data=None):
    return json.dumps(data if data is not None else sample_data(), ensure_ascii=False).encode("utf-8")


def test_database_snapshot_import_is_private_idempotent_and_replaces_atomically(snapshot_app):
    from models.entomologia import EntomologiaImportacao
    from scripts.import_sfa_cadastro import store_cadastro

    first = store_cadastro(synthetic_bytes())
    assert set(first) == {"import_id", "records_count", "owners_count", "sha256"}
    assert cadastro.search_cadastro("acacias")["available"] is True
    assert cadastro.get_cadastro_property("001")["owner"]["fields"][0]["value"] == "DOCUMENTO-FICTICIO-ALFA"
    assert store_cadastro(synthetic_bytes()) == first
    assert EntomologiaImportacao.query.count() == 1
    replacement = sample_data()
    replacement["owners"][0]["fields"][0]["value"] = "DOCUMENTO-SUBSTITUIDO"
    second = store_cadastro(synthetic_bytes(replacement))
    assert second["import_id"] != first["import_id"]
    assert second["sha256"] != first["sha256"]
    assert EntomologiaImportacao.query.filter_by(status="ATIVA").count() == 1
    assert EntomologiaImportacao.query.filter_by(status="DESFEITA").count() == 1
    active = EntomologiaImportacao.query.filter_by(status="ATIVA").one()
    assert active.tipo == cadastro.CADASTRO_IMPORT_TYPE
    assert active.titulo == cadastro.CADASTRO_IMPORT_TITLE
    assert cadastro.get_cadastro_property("001")["owner"]["fields"][0]["value"] == "DOCUMENTO-SUBSTITUIDO"
    assert "DOCUMENTO" not in json.dumps(first)


def test_database_reader_rejects_hash_mismatch_and_ambiguous_active_snapshots(snapshot_app):
    from extensions import db
    from models.entomologia import EntomologiaImportacao
    from scripts.import_sfa_cadastro import store_cadastro

    store_cadastro(synthetic_bytes())
    active = EntomologiaImportacao.query.one()
    correct_hash = active.sha256
    active.sha256 = "0" * 64
    db.session.commit()
    assert cadastro.search_cadastro("acacias")["available"] is False
    active.sha256 = correct_hash
    duplicate = EntomologiaImportacao(
        tipo=active.tipo, titulo=active.titulo, status="ATIVA",
        nome_arquivo="synthetic.json", sha256=correct_hash,
        dados_json=active.dados_json, responsavel="Testes sintéticos",
    )
    db.session.add(duplicate)
    db.session.commit()
    assert cadastro.search_cadastro("acacias")["available"] is False
    assert cadastro.get_cadastro_property("001") is None


def test_database_reader_does_not_read_public_import_kind_or_other_title(snapshot_app):
    from extensions import db
    from models.entomologia import EntomologiaImportacao
    from scripts.import_sfa_cadastro import store_cadastro

    store_cadastro(synthetic_bytes())
    active = EntomologiaImportacao.query.one()
    active.tipo = "atlas_cadastre"
    db.session.commit()
    assert cadastro.search_cadastro("acacias")["available"] is False
    active.tipo = cadastro.CADASTRO_IMPORT_TYPE
    active.titulo = "Other private dataset"
    db.session.commit()
    assert cadastro.search_cadastro("acacias")["available"] is False


def test_import_failure_rolls_back_previous_snapshot(snapshot_app, monkeypatch):
    from extensions import db
    from models.entomologia import EntomologiaImportacao
    from scripts.import_sfa_cadastro import store_cadastro

    first = store_cadastro(synthetic_bytes())
    replacement = sample_data()
    replacement["owners"][0]["fields"][0]["value"] = "DOCUMENTO-SUBSTITUIDO"

    def fail_commit():
        raise RuntimeError("Synthetic transaction failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        store_cadastro(synthetic_bytes(replacement))
    assert EntomologiaImportacao.query.count() == 1
    assert EntomologiaImportacao.query.one().id == first["import_id"]
    assert EntomologiaImportacao.query.one().status == "ATIVA"
    assert cadastro.get_cadastro_property("001")["owner"]["fields"][0]["value"] == "DOCUMENTO-FICTICIO-ALFA"


def test_cli_accepts_one_base64_line_without_waiting_for_eof(snapshot_app, monkeypatch, capsys):
    import app_factory
    from types import SimpleNamespace
    from scripts import import_sfa_cadastro

    class LineInput:
        def readline(self, size):
            line = base64.b64encode(synthetic_bytes()) + b"\n"
            assert len(line) <= size
            return line

        def read(self, *_args):
            raise AssertionError("The importer must not wait for EOF")

    monkeypatch.setattr(app_factory, "create_app", lambda: snapshot_app)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=LineInput()))
    assert import_sfa_cadastro.main(["--stdin-base64"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    result = json.loads(output.out)
    assert set(result) == {"import_id", "records_count", "owners_count", "sha256"}
    assert result["records_count"] == 2
    assert result["owners_count"] == 2
    assert "DOCUMENTO" not in output.out
    assert "Rua" not in output.out


def test_cli_invalid_input_does_not_echo_the_source(monkeypatch, capsys):
    from scripts import import_sfa_cadastro

    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"INVALIDO-SENSIVEL-NAO-ECOAR\n")))
    assert import_sfa_cadastro.main(["--stdin-base64"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "INVALIDO-SENSIVEL" not in output.err
    assert "Cadastro privado inválido" in output.err


def test_importer_hides_personal_sql_parameters_even_when_echo_is_enabled(snapshot_app, caplog):
    from extensions import db
    from scripts.import_sfa_cadastro import store_cadastro

    db.engine.echo = True
    db.engine.hide_parameters = False
    with caplog.at_level("INFO", logger="sqlalchemy.engine.Engine"):
        result = store_cadastro(synthetic_bytes())
    assert result["records_count"] == 2
    assert "DOCUMENTO-FICTICIO" not in caplog.text
    assert "Pessoa Fictícia" not in caplog.text
    assert "Rua das Acácias" not in caplog.text
    assert db.engine.echo is True
    assert db.engine.hide_parameters is False
