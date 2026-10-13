"""Import an authorized private property snapshot without printing personal data.

Usage: provide UTF-8 JSON encoded as one base64 line followed by a newline
on stdin with --stdin-base64. Reading that line does not wait for stdin EOF.
The snapshot is stored only in the database, separately from public atlas data.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def store_cadastro(contents: bytes) -> dict:
    """Validate, retire previous snapshots, and publish one private DB snapshot."""
    from extensions import db
    from models.entomologia import EntomologiaImportacao
    from services.entomologia_cadastro import (
        CADASTRO_IMPORT_TITLE, CADASTRO_IMPORT_TYPE, validate_cadastro,
    )
    from time_utils import utcnow

    validated = validate_cadastro(contents)
    metadata = validated["metadata"]
    canonical_source = {
        "collected_at": metadata["collected_at"],
        "collection_scope": metadata["scope"],
        "records": validated["records"],
        "owners": list(validated["owners"].values()),
    }
    encoded = json.dumps(canonical_source, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    now = utcnow()
    engine = db.engine
    previous_echo, previous_hide_parameters = engine.echo, engine.hide_parameters
    # Even if the deployment enables SQL echo, INSERT parameters contain the
    # private JSON and must not appear in application or terminal logs.
    engine.echo, engine.hide_parameters = False, True
    try:
        previous = (EntomologiaImportacao.query
                    .filter_by(tipo=CADASTRO_IMPORT_TYPE, titulo=CADASTRO_IMPORT_TITLE, status="ATIVA")
                    .order_by(EntomologiaImportacao.id).with_for_update().all())
        if len(previous) == 1 and previous[0].sha256 == digest:
            row = previous[0]
        else:
            for old in previous:
                old.status = "DESFEITA"
                old.desfeito_em = now
                old.desfeito_por = "import_sfa_cadastro"
            row = EntomologiaImportacao(
                tipo=CADASTRO_IMPORT_TYPE,
                titulo=CADASTRO_IMPORT_TITLE,
                status="ATIVA",
                nome_arquivo="cadastro-privado.json",
                sha256=digest,
                linhas=metadata["records_count"],
                responsavel="Administrador",
                ator="Importação autorizada do cadastro privado",
                confirmado_em=now,
                resumo_json=json.dumps({
                    "records_count": metadata["records_count"],
                    "owners_count": metadata["owners_count"],
                    "collected_at": metadata["collected_at"],
                }),
                dados_json=encoded,
            )
            db.session.add(row)
            db.session.flush()
        result = {
            "import_id": row.id,
            "records_count": metadata["records_count"],
            "owners_count": metadata["owners_count"],
            "sha256": digest,
        }
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise
    finally:
        engine.echo, engine.hide_parameters = previous_echo, previous_hide_parameters


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin-base64", action="store_true", required=True)
    parser.parse_args(argv)
    from services.entomologia_cadastro import MAX_FILE_BYTES

    max_encoded = ((MAX_FILE_BYTES + 2) // 3) * 4
    encoded = sys.stdin.buffer.readline(max_encoded + 3).strip()
    if not encoded or len(encoded) > max_encoded:
        print("Entrada do cadastro privado inválida ou maior que o limite.", file=sys.stderr)
        return 1
    try:
        contents = base64.b64decode(encoded, validate=True)
        # Validate before initializing the application or opening a transaction.
        from services.entomologia_cadastro import validate_cadastro
        validate_cadastro(contents)
        from app_factory import create_app
        with create_app().app_context():
            result = store_cadastro(contents)
    except (binascii.Error, ValueError):
        print("Cadastro privado inválido; nenhum dado foi importado.", file=sys.stderr)
        return 1
    except Exception:
        # Database exceptions can include statement parameters containing PII.
        # Keep their traceback and values out of deployment/terminal output.
        print("Não foi possível importar o cadastro privado; a transação foi revertida.", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
