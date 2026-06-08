from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import app, db  # noqa: E402
from models import OAuthClient  # noqa: E402


DEFAULT_SCOPES = "openid profile email tutors:write pets:write exams:write"
DEFAULT_CLIENT_ID = "petorlandia-chatgpt-connector"


def _split_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    values: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        value = chunk.strip()
        if value:
            values.append(value)
    return values


def _resolve_redirect_uris(args: argparse.Namespace) -> list[str]:
    values = list(args.redirect_uri or [])
    values.extend(_split_values(os.environ.get("CHATGPT_OAUTH_REDIRECT_URI")))
    values.extend(_split_values(os.environ.get("CHATGPT_CONNECTOR_REDIRECT_URI")))

    normalized: list[str] = []
    for value in values:
        if not value.startswith("https://"):
            raise SystemExit(f"redirect_uri precisa usar HTTPS: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cria ou atualiza o OAuth client confidencial usado pelo app/conector do ChatGPT."
    )
    parser.add_argument("--client-id", default=os.environ.get("CHATGPT_OAUTH_CLIENT_ID", DEFAULT_CLIENT_ID))
    parser.add_argument("--name", default=os.environ.get("CHATGPT_OAUTH_CLIENT_NAME", "ChatGPT - PetOrlandia"))
    parser.add_argument("--redirect-uri", action="append", help="Callback OAuth exato informado pelo ChatGPT.")
    parser.add_argument("--scopes", default=os.environ.get("CHATGPT_OAUTH_SCOPES", DEFAULT_SCOPES))
    parser.add_argument("--rotate-secret", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    redirect_uris = _resolve_redirect_uris(args)
    if not redirect_uris:
        raise SystemExit(
            "Informe o callback OAuth do ChatGPT com --redirect-uri ou CHATGPT_OAUTH_REDIRECT_URI."
        )

    with app.app_context():
        client = OAuthClient.query.filter_by(client_id=args.client_id).first()
        created = client is None
        secret_was_generated = created or args.rotate_secret or not (client and client.client_secret)
        client_secret = os.environ.get("CHATGPT_OAUTH_CLIENT_SECRET") or secrets.token_urlsafe(32)

        if client is None:
            client = OAuthClient(client_id=args.client_id, client_secret=client_secret)
            db.session.add(client)
        elif secret_was_generated:
            client.client_secret = client_secret

        client.name = args.name
        client.redirect_uris = "\n".join(redirect_uris)
        client.grant_types = "authorization_code refresh_token"
        client.scopes = args.scopes
        client.auth_method = "client_secret_post"
        client.is_confidential = True

        if args.dry_run:
            db.session.rollback()
        else:
            db.session.commit()

        payload = {
            "created": created,
            "dry_run": args.dry_run,
            "client_id": client.client_id,
            "client_secret": client.client_secret if secret_was_generated else "<secret existente preservado>",
            "token_endpoint_auth_method": client.auth_method,
            "grant_types": client.grant_types.split(),
            "scopes": client.scopes.split(),
            "redirect_uris": client.redirect_uri_list(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
