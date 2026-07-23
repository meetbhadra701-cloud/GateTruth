"""Small JSON-over-HTTP helper that never includes request headers in errors."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROVIDER_READ_TIMEOUT_S = 300


class ProviderHTTPError(RuntimeError):
    """Sanitized provider transport or response error."""


class ProviderTransportError(ProviderHTTPError):
    """Retryable provider connection or read-timeout failure."""


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read()
    except HTTPError as exc:
        exc.read()
        raise ProviderHTTPError(f"provider HTTP {exc.code}") from exc
    except URLError as exc:
        raise ProviderTransportError(
            f"provider transport error: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise ProviderTransportError("provider transport error: timed out") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderHTTPError("provider returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ProviderHTTPError("provider response must be a JSON object")
    return data
