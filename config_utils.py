"""Utility helpers for configuration bootstrapping."""

from __future__ import annotations

from urllib.parse import SplitResult, quote, urlsplit, urlunsplit


def normalize_database_uri(uri: str | bytes | None) -> str | None:
    """Return a DB URI that is safe for psycopg2/SQLAlchemy.

    Self-hosted deployments occasionally set ``SQLALCHEMY_DATABASE_URI`` with
    raw characters such as ``ã`` in the user, password or database name.  Those
    characters are invalid in a URI and psycopg2 raises ``UnicodeDecodeError``
    before even reaching Postgres.  We defensively percent-encode every URI
    component so that libpq always receives a pure ASCII connection string.
    """

    if uri in (None, ""):
        return uri

    if isinstance(uri, bytes):
        for encoding in ("utf-8", "latin-1"):
            try:
                uri = uri.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            uri = uri.decode("utf-8", errors="ignore")

    if not isinstance(uri, str):
        return uri

    try:
        parsed = urlsplit(uri)
    except ValueError:
        return uri

    sanitized = parsed._replace(
        netloc=_encode_netloc(parsed),
        path=_encode_path(parsed),
    )
    return urlunsplit(sanitized)


def _encode_netloc(parsed: SplitResult) -> str:
    host = parsed.hostname or ""
    if host and any(ord(ch) > 127 for ch in host):
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            host = host.encode("idna", errors="ignore").decode("ascii")

    if host and ":" in host and not host.startswith("["):
        host = f"[{host}]"

    port = f":{parsed.port}" if parsed.port else ""
    userinfo = ""
    if parsed.username is not None:
        userinfo = quote(parsed.username, safe="")
        if parsed.password is not None:
            userinfo += f":{quote(parsed.password, safe='')}"
        userinfo += "@"

    return f"{userinfo}{host}{port}"


def _encode_path(parsed: SplitResult) -> str:
    # ``SplitResult.path`` already contains the leading ``/`` so we keep it as
    # part of the safe characters while still percent-encoding non-ASCII text.
    if not parsed.path:
        return parsed.path
    return quote(parsed.path, safe="/.:@%")

