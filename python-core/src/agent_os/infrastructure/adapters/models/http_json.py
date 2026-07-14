from __future__ import annotations

import json
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def post_json(
    *,
    url: str,
    payload: Mapping[str, object],
    headers: Mapping[str, str],
    timeout_seconds: float,
    provider_label: str,
    error_type: type[RuntimeError],
    user_agent: str | None = None,
) -> Mapping[str, object]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **dict(headers),
    }
    if user_agent is not None:
        request_headers["User-Agent"] = user_agent
    request = Request(
        url,
        data=data,
        method="POST",
        headers=request_headers,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except HTTPError as exc:
        raise error_type(f"{provider_label} request failed with status {exc.code}.") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise error_type(
            f"{provider_label} request failed before a response was received."
        ) from exc
    return json_response(body=body, provider_label=provider_label, error_type=error_type)


def json_response(
    *,
    body: bytes,
    provider_label: str,
    error_type: type[RuntimeError],
) -> Mapping[str, object]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error_type(f"{provider_label} returned invalid JSON.") from exc
    if not isinstance(parsed, Mapping):
        raise error_type(f"{provider_label} returned an invalid response shape.")
    return parsed


def validate_base_url(
    *,
    value: str,
    field_name: str,
    error_type: type[ValueError],
) -> None:
    if not value.strip():
        raise error_type(f"{field_name} must be a non-empty string.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise error_type(f"{field_name} must be an absolute http or https URL.")


def require_non_empty(
    value: str,
    field_name: str,
    error_type: type[ValueError],
) -> None:
    if not value.strip():
        raise error_type(f"{field_name} must be a non-empty string.")


def provider_user_agent(
    defaults: Mapping[str, object],
    request_parameters: Mapping[str, object] | None,
    error_type: type[ValueError],
) -> str | None:
    selected: object | None = None
    for source in (defaults, request_parameters or {}):
        for key in ("provider_user_agent", "user_agent"):
            value = source.get(key)
            if value is not None:
                selected = value
    if selected is None:
        return None
    if not isinstance(selected, str):
        raise error_type("provider User-Agent must be a string.")
    normalized = selected.strip()
    if not normalized:
        raise error_type("provider User-Agent must be a non-empty string.")
    if "\r" in normalized or "\n" in normalized:
        raise error_type("provider User-Agent must not contain CR or LF.")
    if len(normalized) > 256:
        raise error_type("provider User-Agent must be 256 characters or fewer.")
    return normalized
