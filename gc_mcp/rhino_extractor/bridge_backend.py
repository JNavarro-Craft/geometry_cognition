from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _bridge_json_request(
    base_url: str,
    path: str,
    timeout_seconds: float,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = "application/json",
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    headers: dict[str, str] = {}
    if content_type and body is not None:
        headers["Content-Type"] = content_type
    req = Request(url=url, data=body, method=method, headers=headers)
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


def bridge_health(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url,
        "/health",
        timeout_seconds,
        method="GET",
        body=None,
        content_type=None,
    )


def live_scene_summary_bridge(
    base_url: str,
    timeout_seconds: float,
    *,
    sample_limit: int = 20,
) -> dict[str, Any]:
    q = max(0, min(100, int(sample_limit)))
    return _bridge_json_request(
        base_url,
        f"/v1/live/scene/summary?sample_limit={q}",
        timeout_seconds,
        method="GET",
        body=None,
        content_type=None,
    )


def live_objects_query_bridge(
    base_url: str,
    timeout_seconds: float,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    return _bridge_json_request(
        base_url,
        "/v1/live/objects/query",
        timeout_seconds,
        method="POST",
        body=body,
    )


def live_compute_contacts_bridge(
    base_url: str,
    timeout_seconds: float,
    object_ids: list[str],
    tolerance: float = 1e-3,
) -> dict[str, Any]:
    body = json.dumps({"object_ids": list(object_ids), "tolerance": tolerance}).encode("utf-8")
    return _bridge_json_request(
        base_url,
        "/v1/live/contacts",
        timeout_seconds,
        method="POST",
        body=body,
    )


def live_object_detail_bridge(
    base_url: str,
    timeout_seconds: float,
    object_id: str,
    *,
    detail_level: str = "basic",
    user_text: str = "keys",
) -> dict[str, Any]:
    from urllib.parse import quote

    oid = quote(str(object_id).strip(), safe=":")
    dl = quote(str(detail_level).strip(), safe="")
    ut = quote(str(user_text).strip(), safe="")
    return _bridge_json_request(
        base_url,
        f"/v1/live/objects/{oid}?detail_level={dl}&user_text={ut}",
        timeout_seconds,
        method="GET",
        body=None,
        content_type=None,
    )


def live_list_definitions_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    """List block definitions with instance counts (GET /v1/live/definitions)."""
    return _bridge_json_request(
        base_url,
        "/v1/live/definitions",
        timeout_seconds,
        method="GET",
        body=None,
        content_type=None,
    )


def live_definition_objects_bridge(
    base_url: str,
    timeout_seconds: float,
    definition_name: str,
    *,
    resolve_instances: bool = False,
) -> dict[str, Any]:
    """Objects composing a block definition (GET /v1/live/definition_objects?name=...).

    Raw definition content (no instance transform applied). Lets a caller read
    attributes/text/geometry that live INSIDE a block.

    When ``resolve_instances`` is True, the response also includes an ``instances``
    block: one row per placed instance with each member's bbox transformed by that
    instance's transform (lightweight; geometry is not moved).
    """
    from urllib.parse import quote

    name = quote(str(definition_name).strip(), safe="")
    path = f"/v1/live/definition_objects?name={name}"
    if resolve_instances:
        path += "&instances=true"
    return _bridge_json_request(
        base_url,
        path,
        timeout_seconds,
        method="GET",
        body=None,
        content_type=None,
    )


def extract_objects_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    """Legacy full-scene extraction (POST /geometry/extract_scene)."""
    return _bridge_json_request(
        base_url,
        "/geometry/extract_scene",
        timeout_seconds,
        method="POST",
        body=json.dumps({}).encode("utf-8"),
    )


def extract_objects_by_ids_bridge(
    base_url: str,
    timeout_seconds: float,
    object_ids: list[str],
) -> dict[str, Any]:
    """Partial extraction for specific ids (POST /geometry/extract_objects)."""
    if not object_ids:
        raise ValueError("extract_objects_by_ids_bridge: empty object_ids")
    body = json.dumps({"object_ids": object_ids}).encode("utf-8")
    return _bridge_json_request(
        base_url,
        "/geometry/extract_objects",
        timeout_seconds,
        method="POST",
        body=body,
    )


def collect_object_ids_via_live_query(
    base_url: str,
    timeout_seconds: float,
    *,
    page_limit: int = 200,
    filters: dict[str, Any] | None = None,
) -> list[str]:
    """Paginate POST /v1/live/objects/query and collect object_id values in order."""
    limit = max(1, min(500, int(page_limit)))
    cursor = 0
    ids: list[str] = []
    filters = filters if isinstance(filters, dict) else {}
    while True:
        page = live_objects_query_bridge(
            base_url,
            timeout_seconds,
            {
                "filters": filters,
                "limit": limit,
                "cursor": cursor,
            },
        )
        rows = page.get("objects")
        if not isinstance(rows, list):
            raise RuntimeError("bridge_live_query_missing_objects")
        for row in rows:
            if isinstance(row, dict) and row.get("object_id"):
                ids.append(str(row["object_id"]))
        next_c = page.get("next_cursor")
        if next_c is None:
            break
        try:
            cursor = int(next_c)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("bridge_live_query_bad_next_cursor") from exc
    return ids


def fetch_scene_via_live_query_and_extract_objects(
    base_url: str,
    timeout_seconds: float,
    *,
    query_page_limit: int = 200,
    extract_batch_size: int = 80,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    List object ids via live query, then hydrate with POST /geometry/extract_objects
    in batches. Response shape matches extract_scene (source, object_count, objects).
    """
    ids = collect_object_ids_via_live_query(
        base_url,
        timeout_seconds,
        page_limit=query_page_limit,
        filters=filters,
    )
    batch = max(1, min(200, int(extract_batch_size)))
    all_objects: list[Any] = []
    for i in range(0, len(ids), batch):
        chunk = ids[i : i + batch]
        part = extract_objects_by_ids_bridge(base_url, timeout_seconds, chunk)
        objs = part.get("objects")
        if not isinstance(objs, list):
            raise RuntimeError("bridge_extract_objects_missing_objects")
        all_objects.extend(objs)
    return {
        "source": "rhino_bridge",
        "object_count": len(all_objects),
        "objects": all_objects,
    }
