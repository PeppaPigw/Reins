"""Minimal JSON HTTP helpers for integrations.

This module intentionally uses the Python standard library so Reins can ship
integration templates without introducing extra runtime dependencies.
"""

from __future__ import annotations

import json
from base64 import b64encode
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def basic_auth_header(username: str, password: str) -> str:
    """Return a Basic auth header value for the given credentials."""
    token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    timeout_seconds: float = 30.0,
) -> Any:
    """Send a JSON HTTP request and decode the JSON response."""
    body = request_text(
        url,
        method=method,
        headers=headers,
        json_body=json_body,
        timeout_seconds=timeout_seconds,
    )
    if not body:
        return {}
    return json.loads(body)


def request_text(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    timeout_seconds: float = 30.0,
) -> str:
    """Send an HTTP request and return the decoded response body."""
    payload = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    request = Request(url, data=payload, method=method.upper())

    merged_headers = dict(headers or {})
    if payload is not None and "Content-Type" not in merged_headers:
        merged_headers["Content-Type"] = "application/json"
    if "Accept" not in merged_headers:
        merged_headers["Accept"] = "application/json"

    for key, value in merged_headers.items():
        request.add_header(key, value)

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:  # pragma: no cover - exercised via unit tests
        error_body = exc.read().decode("utf-8", errors="replace")
        detail = error_body or exc.reason
        raise RuntimeError(f"HTTP {exc.code} calling {url}: {detail}") from exc
    except URLError as exc:  # pragma: no cover - exercised via unit tests
        raise RuntimeError(f"Request failed for {url}: {exc.reason}") from exc

    return body
