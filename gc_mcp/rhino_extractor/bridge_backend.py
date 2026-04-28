from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def extract_objects_bridge(base_url: str, timeout_seconds: float) -> dict:
    url = f"{base_url.rstrip('/')}/geometry/extract_scene"
    body = json.dumps({}).encode("utf-8")
    req = Request(url=url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            text = resp.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"bridge_http_error:{exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"bridge_connection_error:{exc.reason}") from exc

    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("bridge_invalid_json_response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("bridge_invalid_response_shape")
    return payload
