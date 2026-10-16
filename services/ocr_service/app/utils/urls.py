from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def mask_url_credentials(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid url>"
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username}:***@{host}" if parts.username else f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
