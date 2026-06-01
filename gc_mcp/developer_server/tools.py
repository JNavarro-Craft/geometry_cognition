"""Pure logic for developer_server: snapshot capture, diff, inspect, assert."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from gc_mcp.developer_server.storage import (
    SNAPSHOT_SCHEMA,
    captured_at_iso,
    delete_existing_for_label,
    find_latest_by_label,
    list_snapshot_files,
    prune_snapshots,
    read_snapshot,
    slugify_label,
    snapshots_dir,
    write_snapshot,
)
from gc_mcp.rhino_extractor.backend_adapter import _normalize_bridge_objects
from gc_mcp.rhino_extractor.bridge_backend import (
    _bridge_json_request,
    extract_objects_bridge,
    fetch_scene_via_live_query_and_extract_objects,
    live_compute_contacts_bridge,
    live_definition_objects_bridge,
    live_list_definitions_bridge,
    live_object_detail_bridge,
    live_object_elements_bridge,
    live_project_to_plane_bridge,
    live_scene_summary_bridge,
)

BBOX_TOLERANCE_DEFAULT = 1e-6


def _bridge_settings() -> tuple[str, float]:
    base_url = str(os.environ.get("GC_BRIDGE_BASE_URL", "http://127.0.0.1:8765"))
    timeout = float(os.environ.get("GC_BRIDGE_TIMEOUT_SECONDS", "10") or "10")
    return base_url, timeout


def _live_only_error(message: str) -> dict[str, Any]:
    return {
        "error": "live_mode_unavailable",
        "message": message,
        "mode": "bridge_live",
    }


def _invalid_label_error(raw_label: Any) -> dict[str, Any]:
    return {
        "error": "invalid_label",
        "message": "label must contain at least one [a-z0-9_-] character after sanitization",
        "received": str(raw_label),
    }


def _snapshot_not_found(label_slug: str) -> dict[str, Any]:
    return {
        "error": "snapshot_not_found",
        "message": f"no snapshot found for label '{label_slug}'",
        "label": label_slug,
    }


def _fetch_objects(
    bridge_url: str,
    timeout: float,
    filters: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch normalized objects from the bridge using the live strategy,
    falling back to ``extract_scene`` on failure. Returns (objects, warnings).

    Filters are passed to the live query; the fallback path
    (``/geometry/extract_scene``) does not support filters, so if it is used
    while filters were requested, a ``capture_filter_not_applied`` warning is
    emitted and the full scene is returned.
    """
    warnings: list[str] = []
    has_filters = bool(filters)
    try:
        payload = fetch_scene_via_live_query_and_extract_objects(
            bridge_url,
            timeout,
            query_page_limit=int(os.getenv("GC_BRIDGE_LIVE_QUERY_LIMIT", "200") or "200"),
            extract_batch_size=int(os.getenv("GC_BRIDGE_EXTRACT_BATCH_SIZE", "80") or "80"),
            filters=filters,
        )
        warnings.append("bridge_strategy:live")
    except Exception as exc:
        warnings.append(f"bridge_live_failed:{type(exc).__name__}")
        payload = extract_objects_bridge(bridge_url, timeout)
        warnings.append("bridge_strategy:extract_scene_fallback")
        if has_filters:
            warnings.append("capture_filter_not_applied:fallback_does_not_support_filters")
    objects = _normalize_bridge_objects(payload)
    return objects, warnings


def _fetch_summarize_model(bridge_url: str, timeout: float) -> dict[str, Any] | None:
    try:
        return _bridge_json_request(
            bridge_url,
            "/summarize-model",
            timeout,
            method="GET",
            body=None,
            content_type=None,
        )
    except Exception:
        return None


def _as_float_or_none(v: Any) -> tuple[float | None, str | None]:
    """Return (value, unexpected_type_name).

    None or missing -> (None, None): legitimate absence, no warning.
    bool -> (None, "bool"): bool is a subclass of int in Python but is not a
    number for geometry; flag it.
    int/float -> (float(v), None).
    Anything else -> (None, type_name): coerced to null, warning recorded.
    """
    if v is None:
        return None, None
    if isinstance(v, bool):
        return None, "bool"
    if isinstance(v, (int, float)):
        return float(v), None
    return None, type(v).__name__


def _as_int_or_none(v: Any) -> tuple[int | None, str | None]:
    if v is None:
        return None, None
    if isinstance(v, bool):
        return None, "bool"
    if isinstance(v, int):
        return v, None
    if isinstance(v, float):
        if v.is_integer():
            return int(v), None
        return None, "float_non_integer"
    return None, type(v).__name__


def _as_bool_or_none(v: Any) -> tuple[bool | None, str | None]:
    if v is None:
        return None, None
    if isinstance(v, bool):
        return v, None
    return None, type(v).__name__


def _project_object_for_snapshot(
    obj: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Project a bridge object to the snapshot shape.

    Returns the projected dict and a list of ``(field, unexpected_type)`` tuples
    recording coercion incidents on the five geometric scalars. An empty list
    means the bridge delivered each field either as the expected type or as
    null/absent (both treated as legitimate).
    """
    raw_geo = obj.get("raw_geometry_summary") if isinstance(obj.get("raw_geometry_summary"), dict) else {}
    bbox = raw_geo.get("bbox") if isinstance(raw_geo, dict) else None
    bbox_center = raw_geo.get("bbox_center") if isinstance(raw_geo, dict) else None
    user_text = obj.get("user_text") if isinstance(obj.get("user_text"), dict) else {}

    incidents: list[tuple[str, str]] = []
    volume, bad = _as_float_or_none(raw_geo.get("volume") if raw_geo else None)
    if bad:
        incidents.append(("volume", bad))
    area, bad = _as_float_or_none(raw_geo.get("area") if raw_geo else None)
    if bad:
        incidents.append(("area", bad))
    face_count, bad = _as_int_or_none(raw_geo.get("face_count") if raw_geo else None)
    if bad:
        incidents.append(("face_count", bad))
    edge_count, bad = _as_int_or_none(raw_geo.get("edge_count") if raw_geo else None)
    if bad:
        incidents.append(("edge_count", bad))
    is_closed, bad = _as_bool_or_none(raw_geo.get("is_closed") if raw_geo else None)
    if bad:
        incidents.append(("is_closed", bad))
    length, bad = _as_float_or_none(raw_geo.get("length") if raw_geo else None)
    if bad:
        incidents.append(("length", bad))
    obb_longest, bad = _as_float_or_none(raw_geo.get("obb_longest") if raw_geo else None)
    if bad:
        incidents.append(("obb_longest", bad))
    obb_mid, bad = _as_float_or_none(raw_geo.get("obb_mid") if raw_geo else None)
    if bad:
        incidents.append(("obb_mid", bad))
    obb_shortest, bad = _as_float_or_none(raw_geo.get("obb_shortest") if raw_geo else None)
    if bad:
        incidents.append(("obb_shortest", bad))
    longest_edge, bad = _as_float_or_none(raw_geo.get("longest_edge") if raw_geo else None)
    if bad:
        incidents.append(("longest_edge", bad))

    block_context = obj.get("block_context") if isinstance(obj.get("block_context"), dict) else {}
    material = obj.get("material")

    projected = {
        "object_id": str(obj.get("object_id", "")),
        "layer": str(obj.get("layer", "")),
        "name": str(obj.get("name", "")),
        "raw_type": str(obj.get("raw_type", "")),
        "object_kind": str(obj.get("object_kind", "")),
        "user_text": {str(k): str(v) for k, v in user_text.items()},
        "group_ids": [str(x) for x in (obj.get("group_ids") or [])],
        "group_names": [str(x) for x in (obj.get("group_names") or [])],
        "block_context": {
            "is_block_instance": bool(block_context.get("is_block_instance", False)),
            "block_name": (str(block_context["block_name"]) if block_context.get("block_name") is not None else None),
            "instance_definition_id": (
                str(block_context["instance_definition_id"])
                if block_context.get("instance_definition_id") is not None
                else None
            ),
        },
        "material": str(material) if material is not None else None,
        "annotation_text": (
            str(obj["annotation_text"].get("plain_text", ""))
            if isinstance(obj.get("annotation_text"), dict)
            else None
        ),
        "transform": [float(x) for x in obj["transform"]] if isinstance(obj.get("transform"), list) and len(obj.get("transform")) == 16 else None,
        "bbox": bbox if isinstance(bbox, dict) else None,
        "bbox_center": list(bbox_center) if isinstance(bbox_center, list) else None,
        "volume": volume,
        "area": area,
        "length": length,
        "face_count": face_count,
        "edge_count": edge_count,
        "is_closed": is_closed,
        "obb_dimensions": list(raw_geo.get("obb_dimensions")) if isinstance(raw_geo.get("obb_dimensions"), list) else None,
        "obb_longest": obb_longest,
        "obb_mid": obb_mid,
        "obb_shortest": obb_shortest,
        "longest_edge": longest_edge,
    }
    return projected, incidents


def _aggregate_coercion_warnings(
    pairs: list[tuple[str, list[tuple[str, str]]]],
) -> list[dict[str, Any]]:
    """Aggregate per-object incidents into the snapshot-level summary.

    Input: list of (object_id, incidents) pairs. Each incident is
    (field, unexpected_type). Output: one row per (field, unexpected_type)
    with count and a sample_guid for diagnosis.
    """
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for obj_id, incidents in pairs:
        for field, unexpected in incidents:
            key = (field, unexpected)
            bucket = buckets.get(key)
            if bucket is None:
                buckets[key] = {
                    "field": field,
                    "unexpected_type": unexpected,
                    "count": 1,
                    "sample_guid": obj_id,
                }
            else:
                bucket["count"] += 1
    return sorted(
        buckets.values(),
        key=lambda r: (r["field"], r["unexpected_type"]),
    )


def _summarize_objects(objects: list[dict[str, Any]]) -> dict[str, Any]:
    layers: dict[str, int] = {}
    types: dict[str, int] = {}
    groups: dict[str, int] = {}
    with_user_text = 0
    for obj in objects:
        layers[obj["layer"]] = layers.get(obj["layer"], 0) + 1
        types[obj["raw_type"]] = types.get(obj["raw_type"], 0) + 1
        for g in obj.get("group_names") or []:
            groups[g] = groups.get(g, 0) + 1
        if obj.get("user_text"):
            with_user_text += 1
    return {
        "object_count": len(objects),
        "layers": layers,
        "types": types,
        "groups": groups,
        "objects_with_user_text": with_user_text,
    }


# ---------------------------------------------------------------------------
# take_snapshot
# ---------------------------------------------------------------------------


def _build_capture_filter(
    layers: list[str] | None,
    types: list[str] | None,
    name: str | None,
    user_text_key: str | None,
    bbox: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build the bridge-shaped filter dict from generic Rhino primitives.

    Returns ``None`` when no filter is requested, so the snapshot can record
    "captured the whole model" unambiguously. Only keys explicitly provided by
    the caller end up in the returned dict.

    The emitted keys MUST match the bridge's LiveQueryFilters contract exactly
    (layers, types, name_contains, user_text_key, user_text_value, has_user_text,
    bbox_intersects). The bridge silently ignores unknown keys (a null filter
    lets everything through), so a mismatch here filters nothing while looking
    successful. ``name`` -> ``name_contains`` and ``bbox`` -> ``bbox_intersects``
    are the friendly-param-to-contract translations.
    """
    out: dict[str, Any] = {}
    if isinstance(layers, list) and layers:
        out["layers"] = [str(x) for x in layers]
    if isinstance(types, list) and types:
        out["types"] = [str(x) for x in types]
    if isinstance(name, str) and name.strip():
        out["name_contains"] = name.strip()
    if isinstance(user_text_key, str) and user_text_key.strip():
        out["user_text_key"] = user_text_key.strip()
    if isinstance(bbox, dict) and bbox:
        out["bbox_intersects"] = bbox
    return out or None


def _build_filter_report(
    capture_filter: dict[str, Any] | None,
    warnings: list[str],
    matched_count: int,
) -> dict[str, Any]:
    """Tell the caller, without ambiguity, what the filter actually did.

    The dangerous case this guards against: the live strategy (which applies
    filters in the bridge) fails, the code falls back to ``extract_scene`` (which
    ignores filters and returns the whole model), and the result looks like a
    successful filtered capture. ``_fetch_objects`` records that as the warning
    ``capture_filter_not_applied:...``; here we surface it as a degraded status.

    Status values:
      - ``ok``: no filter requested, or filter applied as requested.
      - ``filter_not_applied``: a filter was requested but the fallback path
        returned the FULL model unfiltered. ``matched_count`` is NOT the filtered
        count. Treat this snapshot as unfiltered.
      - ``filter_valid_empty``: filter applied correctly and matched 0 objects.
        This is a real, trustworthy "nothing matched", not an error.
    """
    fallback_ignored_filter = any(
        str(w).startswith("capture_filter_not_applied") for w in warnings
    )
    has_filter = bool(capture_filter)

    if has_filter and fallback_ignored_filter:
        status = "filter_not_applied"
        note = (
            "live filter strategy failed; fell back to extract_scene which returns "
            "the FULL model. The requested filter was NOT applied — do not treat "
            "matched_count as a filtered result."
        )
    elif has_filter and matched_count == 0:
        status = "filter_valid_empty"
        note = "filter was applied by the bridge and matched 0 objects (trustworthy empty result)."
    else:
        status = "ok"
        note = None

    report: dict[str, Any] = {
        "status": status,
        "filter_requested": has_filter,
        "filter_applied": has_filter and not fallback_ignored_filter,
        "matched_count": matched_count,
    }
    if note:
        report["note"] = note
    return report


def take_snapshot(
    label: str,
    sample_limit: int = 20,
    layers: list[str] | None = None,
    types: list[str] | None = None,
    name: str | None = None,
    user_text_key: str | None = None,
    bbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label_slug = slugify_label(label)
    if not label_slug:
        return _invalid_label_error(label)

    capture_filter = _build_capture_filter(layers, types, name, user_text_key, bbox)

    bridge_url, timeout = _bridge_settings()
    try:
        normalized, warnings = _fetch_objects(bridge_url, timeout, filters=capture_filter)
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")

    summarize_payload = _fetch_summarize_model(bridge_url, timeout)
    scene_summary_payload: dict[str, Any] | None = None
    try:
        scene_summary_payload = live_scene_summary_bridge(
            bridge_url, timeout, sample_limit=int(sample_limit)
        )
    except Exception:
        scene_summary_payload = None

    projected_pairs = [_project_object_for_snapshot(obj) for obj in normalized]
    projected = [row for row, _ in projected_pairs]
    incident_pairs = [(row["object_id"], inc) for row, inc in projected_pairs if row["object_id"]]
    coercion_warnings = _aggregate_coercion_warnings(incident_pairs)
    objects_by_guid = {row["object_id"]: row for row in projected if row["object_id"]}

    summary = _summarize_objects(projected)
    summary["summarize_model"] = summarize_payload
    summary["scene_summary"] = scene_summary_payload

    filter_report = _build_filter_report(capture_filter, warnings, len(objects_by_guid))

    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "label": label_slug,
        "bridge": {
            "base_url": bridge_url,
            "fetch_warnings": warnings,
        },
        "capture_filter": capture_filter,
        "filter_report": filter_report,
        "coercion_warnings": coercion_warnings,
        "summary": summary,
        "objects_by_guid": objects_by_guid,
    }

    path, timestamp, replaced = write_snapshot(payload, label_slug)
    payload_captured_iso = captured_at_iso(timestamp)
    return {
        "status": filter_report["status"],
        "label": label_slug,
        "captured_at_utc": payload_captured_iso,
        "path": str(path),
        "summary": {
            "object_count": summary["object_count"],
            "layers_count": len(summary["layers"]),
            "groups_count": len(summary["groups"]),
            "objects_with_user_text": summary["objects_with_user_text"],
        },
        "replaced_previous": replaced,
        "fetch_warnings": warnings,
        "capture_filter": capture_filter,
        "filter_report": filter_report,
        "coercion_warnings": coercion_warnings,
    }


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------


def list_snapshots() -> dict[str, Any]:
    entries = list_snapshot_files()
    out: list[dict[str, Any]] = []
    for entry in entries:
        try:
            data = read_snapshot(Path(entry["path"]))
            object_count = len(data.get("objects_by_guid", {})) if isinstance(data.get("objects_by_guid"), dict) else 0
        except Exception:
            object_count = -1
        out.append(
            {
                "label": entry["label"],
                "captured_at_utc": captured_at_iso(entry["captured_at_utc_compact"]),
                "path": entry["path"],
                "object_count": object_count,
                "size_bytes": entry["size_bytes"],
            }
        )
    return {
        "snapshots_dir": str(snapshots_dir()),
        "snapshots": out,
        "count": len(out),
    }


# ---------------------------------------------------------------------------
# delete_snapshot / prune_snapshots
# ---------------------------------------------------------------------------


def delete_snapshot(label: str) -> dict[str, Any]:
    """Delete all snapshots for a given label. No-op (status ``not_found``) if none exist."""
    label_slug = slugify_label(label)
    if not label_slug:
        return _invalid_label_error(label)
    deleted = delete_existing_for_label(label_slug)
    return {
        "status": "ok" if deleted else "not_found",
        "label": label_slug,
        "deleted": deleted,
        "deleted_count": len(deleted),
    }


def prune_snapshots_tool_logic(keep_latest_n: int = 1) -> dict[str, Any]:
    """Keep only the ``keep_latest_n`` most recent snapshots per label; delete older ones."""
    try:
        keep = int(keep_latest_n)
    except (TypeError, ValueError):
        return {
            "error": "invalid_keep_latest_n",
            "message": "keep_latest_n must be an integer >= 0",
            "received": str(keep_latest_n),
        }
    if keep < 0:
        return {
            "error": "invalid_keep_latest_n",
            "message": "keep_latest_n must be >= 0",
            "received": keep,
        }
    kept, deleted = prune_snapshots(keep)
    return {
        "status": "ok",
        "keep_latest_n": keep,
        "kept_count": len(kept),
        "deleted": deleted,
        "deleted_count": len(deleted),
    }


# ---------------------------------------------------------------------------
# describe_model (discovery: "what is really here, so you can filter without guessing")
# ---------------------------------------------------------------------------


def _describe_from_objects(objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the discovery catalogue from a list of normalized objects.

    Pure function over normalized objects so it can run on either the live model
    or a persisted snapshot's stored objects. Domain-agnostic: it reports the
    real layers / Rhino types / groups / user_text keys / block definitions that
    exist, with counts and example values, so a caller never has to guess a
    filter key that may not exist in this model.
    """
    layers: dict[str, int] = {}
    types: dict[str, int] = {}
    groups: dict[str, int] = {}
    ut_keys: dict[str, dict[str, Any]] = {}
    block_defs: dict[str, dict[str, Any]] = {}
    block_instance_count = 0

    for obj in objects:
        layers[obj.get("layer", "")] = layers.get(obj.get("layer", ""), 0) + 1
        rt = obj.get("raw_type", "")
        types[rt] = types.get(rt, 0) + 1
        for g in obj.get("group_names") or []:
            groups[str(g)] = groups.get(str(g), 0) + 1

        user_text = obj.get("user_text") if isinstance(obj.get("user_text"), dict) else {}
        for k, v in user_text.items():
            key = str(k)
            bucket = ut_keys.setdefault(
                key, {"key": key, "occurrence_count": 0, "distinct_values": set(), "example_value": str(v)}
            )
            bucket["occurrence_count"] += 1
            bucket["distinct_values"].add(str(v))

        block_context = obj.get("block_context") if isinstance(obj.get("block_context"), dict) else {}
        if block_context.get("is_block_instance"):
            block_instance_count += 1
            name = block_context.get("block_name") or "(unnamed)"
            bdef = block_defs.setdefault(
                str(name),
                {"block_name": str(name), "instance_count": 0, "instance_definition_id": block_context.get("instance_definition_id")},
            )
            bdef["instance_count"] += 1

    user_text_keys = sorted(
        (
            {
                "key": b["key"],
                "occurrence_count": b["occurrence_count"],
                "distinct_values_count": len(b["distinct_values"]),
                "example_value": b["example_value"],
            }
            for b in ut_keys.values()
        ),
        key=lambda r: (-r["occurrence_count"], r["key"]),
    )

    return {
        "object_count": len(objects),
        "layers": [{"name": n, "object_count": c} for n, c in sorted(layers.items(), key=lambda x: (-x[1], x[0]))],
        "types": [{"raw_type": n, "object_count": c} for n, c in sorted(types.items(), key=lambda x: (-x[1], x[0]))],
        "groups": [{"name": n, "object_count": c} for n, c in sorted(groups.items(), key=lambda x: (-x[1], x[0]))],
        "user_text_keys": user_text_keys,
        "block_definitions": sorted(block_defs.values(), key=lambda r: (-r["instance_count"], r["block_name"])),
        "block_instance_count": block_instance_count,
    }


def describe_model() -> dict[str, Any]:
    """Discovery catalogue of the live model: real layers, Rhino types, groups,
    user_text keys (with counts and example values) and block definitions.

    Call this BEFORE building filters so you never guess a filter key (layer
    name, user_text key, type) that does not exist in this model. Filters are
    case-sensitive and layer names are full paths (``Parent::Child``).
    """
    bridge_url, timeout = _bridge_settings()
    try:
        normalized, warnings = _fetch_objects(bridge_url, timeout, filters=None)
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")
    catalogue = _describe_from_objects(normalized)
    catalogue["source"] = "bridge_live"
    catalogue["fetch_warnings"] = warnings
    return catalogue


# ---------------------------------------------------------------------------
# query_objects (filtered query over the live model OR a persisted snapshot)
# ---------------------------------------------------------------------------


QUERY_FIELDS_DEFAULT = ("object_id", "name", "raw_type", "layer")


def _object_matches_query(obj: dict[str, Any], flt: dict[str, Any]) -> bool:
    """Domain-agnostic AND-combined match over normalized object fields.

    Supported keys: layers (list, exact), types (list, exact on raw_type),
    name_contains (substring, case-insensitive), user_text_key (presence),
    user_text (dict of key=value, exact), is_block_instance (bool).
    """
    layers = flt.get("layers")
    if isinstance(layers, list) and layers and str(obj.get("layer", "")) not in {str(x) for x in layers}:
        return False
    types = flt.get("types")
    if isinstance(types, list) and types and str(obj.get("raw_type", "")) not in {str(x) for x in types}:
        return False
    needle = flt.get("name_contains")
    if isinstance(needle, str) and needle.strip():
        if needle.strip().lower() not in str(obj.get("name", "")).lower():
            return False
    user_text = obj.get("user_text") if isinstance(obj.get("user_text"), dict) else {}
    ut_key = flt.get("user_text_key")
    if isinstance(ut_key, str) and ut_key.strip() and ut_key.strip() not in user_text:
        return False
    ut_pairs = flt.get("user_text")
    if isinstance(ut_pairs, dict):
        for k, v in ut_pairs.items():
            if user_text.get(str(k)) != str(v):
                return False
    want_block = flt.get("is_block_instance")
    if isinstance(want_block, bool):
        bc = obj.get("block_context") if isinstance(obj.get("block_context"), dict) else {}
        if bool(bc.get("is_block_instance", False)) != want_block:
            return False
    return True


def _project_query_fields(obj: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    # Use _resolve_field (not a flat obj.get) so geometric scalars nested under
    # raw_geometry_summary (volume, obb_longest, longest_edge, ...) and user_text.<key>
    # resolve correctly. A flat get returned None for them — the reason fields-based
    # geometry queries came back null even when the bridge delivered the values.
    return {f: _resolve_field(obj, f) for f in fields}


def query_objects(
    filters: dict[str, Any] | None = None,
    source: str = "live",
    limit: int | None = None,
    fields: list[str] | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Query objects by AND-combined filters, over the live model or a snapshot.

    ``source``: ``"live"`` (default) queries the active bridge model;
    any other value is treated as a snapshot label to query the persisted objects.
    Snapshot mode lets you query a past state. Both report ``matched_count``;
    use ``describe_model`` first to discover valid filter values.

    Pagination: ``offset`` skips the first N matches; ``limit`` caps the page size.
    When more matches remain past the page, the result carries ``next_offset`` (and
    ``has_more: true``) so a caller can fetch the next page without re-listing — the
    way to read a large match set without blowing the token budget in one call.
    """
    flt = filters if isinstance(filters, dict) else {}
    field_list = [str(f) for f in fields] if isinstance(fields, list) and fields else list(QUERY_FIELDS_DEFAULT)

    if source == "live":
        bridge_url, timeout = _bridge_settings()
        try:
            normalized, warnings = _fetch_objects(bridge_url, timeout, filters=None)
        except Exception as exc:
            return _live_only_error(f"{type(exc).__name__}: {exc}")
        # Filtering is done here in Python (not pushed to the bridge) so the
        # result is honest regardless of the fetch strategy used.
        src_objects = normalized
        src_label = "bridge_live"
        extra: dict[str, Any] = {"fetch_warnings": warnings}
    else:
        label_slug = slugify_label(source)
        if not label_slug:
            return _invalid_label_error(source)
        path = find_latest_by_label(label_slug)
        if path is None:
            return _snapshot_not_found(label_slug)
        try:
            snap = read_snapshot(path)
        except Exception as exc:
            return {"error": "snapshot_unreadable", "message": str(exc)}
        objs_by_guid = snap.get("objects_by_guid") or {}
        src_objects = list(objs_by_guid.values()) if isinstance(objs_by_guid, dict) else []
        src_label = label_slug
        extra = {"snapshot_label": label_slug}

    matched = [o for o in src_objects if _object_matches_query(o, flt)]
    total_matched = len(matched)
    off = max(0, int(offset)) if offset is not None else 0
    page = matched[off:]
    if limit is not None:
        page = page[: max(0, int(limit))]
    rows = [_project_query_fields(o, field_list) for o in page]

    out: dict[str, Any] = {
        "source": src_label,
        "filters": flt,
        "matched_count": total_matched,
        "returned_count": len(rows),
        "offset": off,
        "objects": rows,
    }
    next_off = off + len(rows)
    if next_off < total_matched:
        out["next_offset"] = next_off
        out["has_more"] = True
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# aggregate (domain-agnostic group-by / sum over live or snapshot objects)
# ---------------------------------------------------------------------------


_GEO_SCALARS = (
    "volume", "area", "length", "face_count", "edge_count",
    # Oriented-bbox extents and longest edge — orientation-independent geometric
    # facts from the bridge. obb_longest/mid/shortest let a caller group or sum the
    # real part dimensions even when the part is rotated (the world bbox cannot).
    "obb_longest", "obb_mid", "obb_shortest", "longest_edge",
)


def _resolve_field(obj: dict[str, Any], field: str) -> Any:
    """Resolve a field name to a value on a normalized object.

    Works over both live objects (geometry scalars under raw_geometry_summary)
    and snapshot objects (scalars projected flat). Supported field forms:
      - top-level keys: "layer", "raw_type", "name", "object_kind", "material"
      - "user_text.<key>": a specific user_text value
      - geometry scalars: "volume", "area", "length", "face_count", "edge_count"
        (looked up flat first, then inside raw_geometry_summary)
      - "annotation_text": plain text if present
    Returns None when absent. Domain-agnostic: the field name is opaque.
    """
    if field.startswith("user_text."):
        key = field[len("user_text."):]
        ut = obj.get("user_text") if isinstance(obj.get("user_text"), dict) else {}
        return ut.get(key)
    if field in _GEO_SCALARS:
        if field in obj and obj[field] is not None:
            return obj[field]
        rgs = obj.get("raw_geometry_summary")
        if isinstance(rgs, dict):
            return rgs.get(field)
        return None
    if field == "annotation_text":
        at = obj.get("annotation_text")
        if isinstance(at, dict):
            return at.get("plain_text")
        return at
    return obj.get(field)


def _parse_metric(spec: str) -> tuple[str, str | None] | None:
    """Parse a metric spec into (op, field). 'count' -> ('count', None);
    'sum:volume' -> ('sum','volume'). Supported ops: count, sum, avg, min, max."""
    spec = str(spec).strip()
    if spec == "count":
        return ("count", None)
    if ":" in spec:
        op, _, field = spec.partition(":")
        op = op.strip().lower()
        field = field.strip()
        if op in ("sum", "avg", "min", "max") and field:
            return (op, field)
    return None


def compute_contacts(
    object_ids: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    tolerance: float = 1e-3,
) -> dict[str, Any]:
    """Detect REAL contacts between solids and report WHERE each contact is.

    This is the topological-reasoning primitive: it returns not just *which* pairs
    touch but the *location* of the touch (point / curve / surface patch). That
    location is what lets a caller (or an LLM) deduce extremities, joints, where a
    connector sits, etc. — none of which this tool computes or names.

    Inputs (one of):
      - ``object_ids``: explicit list of object GUIDs to test against each other.
      - ``filters``: same AND-combined filters as ``query_objects``; the matching
        objects' ids are resolved from the live model and used as the set. Lets you
        say "contacts among all breps on layer X" without listing GUIDs.
    ``tolerance``: max gap (model units) treated as touching. Default 1e-3.

    Each contact: ``{pair, contact_type, contact_point|contact_curve|
    contact_region_bbox, approx_area}``. ``contact_type`` is ``point`` | ``curve`` |
    ``surface``. Objects that are not solid breps are reported in ``skipped``.

    Agnostic acid test (see docs/agnostic_principle.md):
      1. Exists in any domain?  ✓ "two solids touch here" is meaningful for a
         mechanical assembly, a character mesh, an anatomy scan — nothing about wood.
      2. Needs to know what the object represents?  ✓ NO — it runs on raw breps and
         never asks whether a piece is a stud, plate or connector.
      3. Client can derive it from raw primitives?  ✓ NO — it needs an exact
         brep-brep intersection engine, unavailable to the client from bbox/edges.
      4. An LLM can conclude it from raw geometric data?  ✓ NO — an LLM cannot run
         exact intersection from coordinates; so this is a primitive to expose, not a
         use to bake in. (Building the contact graph, finding joints or extremities
         FROM these contacts is the LLM's job — those would be leaks.)
    """
    bridge_url, timeout = _bridge_settings()

    ids = [str(x) for x in (object_ids or [])]
    resolve_warnings: list[str] = []
    if not ids and filters:
        # Resolve ids from a filter set via the live query, so the caller can scope by
        # layer/type/user_text instead of enumerating GUIDs.
        try:
            objs, resolve_warnings = _fetch_objects(bridge_url, timeout, filters=None)
        except Exception as exc:
            return _live_only_error(f"{type(exc).__name__}: {exc}")
        flt = filters if isinstance(filters, dict) else {}
        ids = [str(o.get("object_id")) for o in objs if _object_matches_query(o, flt) and o.get("object_id")]

    if not ids:
        return {
            "error": "no_object_ids",
            "message": "compute_contacts needs object_ids, or filters that resolve to objects.",
        }

    try:
        result = live_compute_contacts_bridge(bridge_url, timeout, ids, tolerance=tolerance)
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")

    if resolve_warnings:
        existing = result.get("fetch_warnings")
        result["fetch_warnings"] = ([*existing] if isinstance(existing, list) else []) + resolve_warnings
    return result


def project_to_plane(
    plane: dict[str, Any],
    object_ids: list[str] | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project solids onto a plane; return 2D polygons in the plane's local (u,v).

    One polygon per face (Brep face loop / mesh facet) in the plane's (u,v) frame.
    This is the raw 3D->2D primitive: the client composes drawing, aperture detection
    (gaps between projected polygons), coverage analysis — the MCP names none of those.

    - ``plane``: ``{"origin": [x,y,z], "normal": [x,y,z]}``.
    - ``object_ids``: explicit GUIDs, OR ``filters`` (same keys as query_objects) to
      resolve the set from the live model.
    Each projection: ``{object_id, polygons_2d, warnings}``. A face perpendicular to
    the plane degenerates to a line -> returned as a near-zero-area polygon with a
    ``face_perpendicular_to_plane`` warning, not an error. Non-projectable objects
    are reported in ``skipped``.

    Agnostic acid test (docs/agnostic_principle.md):
      1. Exists in any domain?  ✓ projecting geometry to a plane is universal.
      2. Needs to know what the object represents?  ✓ NO — pure geometry.
      3. Client derivable from raw primitives?  ✓ NO — needs the kernel to map face
         loops to plane space.
      4. An LLM can conclude it from raw geometric data?  ✓ NO — cannot project exact
         loops from coordinates; expose the primitive, let the LLM reason on it.
    """
    if not isinstance(plane, dict) or "origin" not in plane or "normal" not in plane:
        return {"error": "invalid_plane", "message": 'plane must be {"origin":[x,y,z], "normal":[x,y,z]}'}

    bridge_url, timeout = _bridge_settings()
    ids = [str(x) for x in (object_ids or [])]
    resolve_warnings: list[str] = []
    if not ids and filters:
        try:
            objs, resolve_warnings = _fetch_objects(bridge_url, timeout, filters=None)
        except Exception as exc:
            return _live_only_error(f"{type(exc).__name__}: {exc}")
        flt = filters if isinstance(filters, dict) else {}
        ids = [str(o.get("object_id")) for o in objs if _object_matches_query(o, flt) and o.get("object_id")]

    if not ids:
        return {"error": "no_object_ids", "message": "project_to_plane needs object_ids, or filters that resolve to objects."}

    try:
        result = live_project_to_plane_bridge(bridge_url, timeout, ids, plane)
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")

    if resolve_warnings:
        existing = result.get("fetch_warnings")
        result["fetch_warnings"] = ([*existing] if isinstance(existing, list) else []) + resolve_warnings
    return result


def aggregate(
    group_by: list[str] | None = None,
    metrics: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    source: str = "live",
) -> dict[str, Any]:
    """Group objects and compute metrics — the agnostic primitive for counts/takeoffs.

    Groups objects (from the live model or a snapshot label) by any field(s) and
    computes metrics per group. The MCP does not interpret any field: it groups by
    whatever you name (e.g. ``user_text.Material``) and sums whatever scalar you ask.

    - ``group_by``: list of field names (see _resolve_field). Empty -> one total group.
    - ``metrics``: list like ``["count", "sum:volume", "avg:length"]``.
      Defaults to ``["count"]``.
    - ``filters``: same AND-combined filters as ``query_objects`` (applied first).
    - ``source``: ``"live"`` or a snapshot label.

    Non-numeric values are skipped for numeric metrics and counted in
    ``skipped_non_numeric`` per metric so the result stays honest.
    """
    group_fields = [str(f) for f in (group_by or [])]
    metric_specs = [str(m) for m in (metrics or ["count"])] or ["count"]
    parsed: list[tuple[str, str, str | None]] = []  # (label, op, field)
    for spec in metric_specs:
        p = _parse_metric(spec)
        if p is None:
            return {"error": "invalid_metric", "message": f"unsupported metric: {spec!r}", "supported": ["count", "sum:<field>", "avg:<field>", "min:<field>", "max:<field>"]}
        parsed.append((spec, p[0], p[1]))

    # Fetch full objects from the chosen source (live or a snapshot label).
    if source == "live":
        bridge_url, timeout = _bridge_settings()
        try:
            objects, warnings = _fetch_objects(bridge_url, timeout, filters=None)
        except Exception as exc:
            return _live_only_error(f"{type(exc).__name__}: {exc}")
        src_label = "bridge_live"
    else:
        label_slug = slugify_label(source)
        path = find_latest_by_label(label_slug)
        if path is None:
            return _snapshot_not_found(label_slug)
        try:
            snap = read_snapshot(path)
        except Exception as exc:
            return {"error": "snapshot_unreadable", "message": str(exc)}
        objs_by_guid = snap.get("objects_by_guid") or {}
        objects = list(objs_by_guid.values()) if isinstance(objs_by_guid, dict) else []
        warnings = []
        src_label = label_slug

    flt = filters if isinstance(filters, dict) else {}
    objects = [o for o in objects if _object_matches_query(o, flt)]

    # Build groups.
    groups: dict[tuple, dict[str, Any]] = {}
    for obj in objects:
        key = tuple(("" if (v := _resolve_field(obj, f)) is None else str(v)) for f in group_fields)
        bucket = groups.get(key)
        if bucket is None:
            bucket = {"_rows": []}
            groups[key] = bucket
        bucket["_rows"].append(obj)

    skipped: dict[str, int] = {}
    rows_out: list[dict[str, Any]] = []
    for key, bucket in groups.items():
        rows = bucket["_rows"]
        row: dict[str, Any] = {f: k for f, k in zip(group_fields, key)}
        for label, op, field in parsed:
            if op == "count":
                row[label] = len(rows)
                continue
            nums: list[float] = []
            for o in rows:
                v = _resolve_field(o, field) if field else None
                if _is_real_number(v):
                    nums.append(float(v))
                elif v is not None:
                    skipped[label] = skipped.get(label, 0) + 1
            if not nums:
                row[label] = None
            elif op == "sum":
                row[label] = sum(nums)
            elif op == "avg":
                row[label] = sum(nums) / len(nums)
            elif op == "min":
                row[label] = min(nums)
            elif op == "max":
                row[label] = max(nums)
        rows_out.append(row)

    rows_out.sort(key=lambda r: tuple(str(r.get(f, "")) for f in group_fields))

    out: dict[str, Any] = {
        "source": src_label,
        "group_by": group_fields,
        "metrics": metric_specs,
        "filters": flt,
        "object_count": len(objects),
        "group_count": len(rows_out),
        "groups": rows_out,
    }
    if skipped:
        out["skipped_non_numeric"] = skipped
    if warnings:
        out["fetch_warnings"] = warnings
    return out


# ---------------------------------------------------------------------------
# bill_of_materials (definitions x instances x content breakdown)
# ---------------------------------------------------------------------------


def _summarize_definition_content(objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Agnostic per-definition content summary: type counts, annotation texts, and
    total curve length / area of the member objects (raw, per single definition)."""
    type_counts: dict[str, int] = {}
    texts: list[str] = []
    total_length = 0.0
    total_area = 0.0
    has_length = False
    has_area = False
    for o in objects:
        rt = str(o.get("type") or o.get("raw_type") or "")
        type_counts[rt] = type_counts.get(rt, 0) + 1
        at = o.get("annotation_text")
        if isinstance(at, dict) and at.get("plain_text"):
            texts.append(str(at["plain_text"]))
        rgs = o.get("raw_geometry_summary") if isinstance(o.get("raw_geometry_summary"), dict) else {}
        length = rgs.get("length")
        if _is_real_number(length):
            total_length += float(length)
            has_length = True
        area = rgs.get("area")
        if _is_real_number(area):
            total_area += float(area)
            has_area = True
    return {
        "type_counts": type_counts,
        "annotation_texts": texts,
        "total_curve_length": total_length if has_length else None,
        "total_area": total_area if has_area else None,
    }


def bill_of_materials(only_with_instances: bool = True) -> dict[str, Any]:
    """Per block definition: instance count x content breakdown.

    Shortcut over list_block_definitions + expand_block: for each definition it
    reports instance_count and an agnostic content summary (member type counts,
    annotation texts, total curve length/area of members). The caller multiplies
    by instance_count and applies domain meaning (price, material) in the session —
    the MCP only provides the geometric facts.
    """
    bridge_url, timeout = _bridge_settings()
    try:
        defs_payload = live_list_definitions_bridge(bridge_url, timeout)
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")

    definitions = defs_payload.get("definitions") if isinstance(defs_payload, dict) else []
    if not isinstance(definitions, list):
        definitions = []

    rows: list[dict[str, Any]] = []
    for d in definitions:
        if not isinstance(d, dict):
            continue
        instance_count = int(d.get("instance_count", 0) or 0)
        if only_with_instances and instance_count <= 0:
            continue
        name = str(d.get("definition_name", ""))
        try:
            content = live_definition_objects_bridge(bridge_url, timeout, name)
            members = content.get("objects") if isinstance(content, dict) else []
            if not isinstance(members, list):
                members = []
            summary = _summarize_definition_content(members)
        except Exception as exc:
            summary = {"error": f"{type(exc).__name__}: {exc}"}
        rows.append(
            {
                "definition_name": name,
                "definition_id": str(d.get("definition_id", "")),
                "instance_count": instance_count,
                "member_count": int(d.get("object_count", 0) or 0),
                "content": summary,
            }
        )

    rows.sort(key=lambda r: (-r["instance_count"], r["definition_name"]))
    return {
        "source": "bridge_live",
        "only_with_instances": bool(only_with_instances),
        "definition_count": len(rows),
        "definitions": rows,
    }


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------


def _bbox_equal(a: Any, b: Any, tol: float) -> bool:
    if a is None and b is None:
        return True
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    for key in ("min", "max"):
        va = a.get(key)
        vb = b.get(key)
        if not isinstance(va, list) or not isinstance(vb, list):
            return False
        if len(va) != len(vb):
            return False
        for x, y in zip(va, vb):
            try:
                if abs(float(x) - float(y)) > tol:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _center_delta(a: Any, b: Any) -> list[float] | None:
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return None
    try:
        return [float(y) - float(x) for x, y in zip(a, b)]
    except (TypeError, ValueError):
        return None


GEOM_REL_TOLERANCE_DEFAULT = 1e-9
GEOM_ABS_TOLERANCE_DEFAULT = 1e-6


def _floats_equal(a: float, b: float, rel_tol: float, abs_tol: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def _is_real_number(v: Any) -> bool:
    """True for int/float that is NOT bool (bool is int subclass in Python)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _diff_nullable_float(
    field: str, a: Any, b: Any, rel_tol: float, abs_tol: float
) -> dict[str, Any] | None:
    """Diff for fields where null is a legitimate value (volume, area).

    Distinguishes:
      - both null -> no change
      - one null, other not -> presence transition (reported)
      - both numeric -> numeric diff with tolerance
      - either non-numeric (and not null) -> anomaly (reported), not silently dropped
    """
    if a is None and b is None:
        return None
    if a is None:
        if not _is_real_number(b):
            return {
                "field": field,
                "anomaly": "non_numeric_in_snapshot",
                "value_a_type": type(a).__name__,
                "value_b_type": type(b).__name__,
            }
        return {"field": field, "transition": "absent_to_present", "to": float(b)}
    if b is None:
        if not _is_real_number(a):
            return {
                "field": field,
                "anomaly": "non_numeric_in_snapshot",
                "value_a_type": type(a).__name__,
                "value_b_type": type(b).__name__,
            }
        return {"field": field, "transition": "present_to_absent", "from": float(a)}
    if not _is_real_number(a) or not _is_real_number(b):
        return {
            "field": field,
            "anomaly": "non_numeric_in_snapshot",
            "value_a_type": type(a).__name__,
            "value_b_type": type(b).__name__,
        }
    fa, fb = float(a), float(b)
    if _floats_equal(fa, fb, rel_tol, abs_tol):
        return None
    return {"field": field, "from": fa, "to": fb, "delta": fb - fa}


def _diff_nullable_int(field: str, a: Any, b: Any) -> dict[str, Any] | None:
    """Diff for integer counts (face_count, edge_count).

    Although today's bridge always sends them populated, the snapshot may
    legitimately hold null (coercion at capture, future bridge behaviour).
    Treats null/value transitions as transitions, value/value as equality,
    and non-null/non-int as an exposed anomaly.
    """
    if a is None and b is None:
        return None
    if a is None:
        if not (isinstance(b, int) and not isinstance(b, bool)):
            return {
                "field": field,
                "anomaly": "non_integer_in_snapshot",
                "value_a_type": type(a).__name__,
                "value_b_type": type(b).__name__,
            }
        return {"field": field, "transition": "absent_to_present", "to": b}
    if b is None:
        if not (isinstance(a, int) and not isinstance(a, bool)):
            return {
                "field": field,
                "anomaly": "non_integer_in_snapshot",
                "value_a_type": type(a).__name__,
                "value_b_type": type(b).__name__,
            }
        return {"field": field, "transition": "present_to_absent", "from": a}
    a_int = isinstance(a, int) and not isinstance(a, bool)
    b_int = isinstance(b, int) and not isinstance(b, bool)
    if not a_int or not b_int:
        return {
            "field": field,
            "anomaly": "non_integer_in_snapshot",
            "value_a_type": type(a).__name__,
            "value_b_type": type(b).__name__,
        }
    if a == b:
        return None
    return {"field": field, "from": a, "to": b, "delta": b - a}


def _diff_nullable_bool(field: str, a: Any, b: Any) -> dict[str, Any] | None:
    """Diff for boolean (is_closed). Same null tolerance as the other fields."""
    if a is None and b is None:
        return None
    if a is None:
        if not isinstance(b, bool):
            return {
                "field": field,
                "anomaly": "non_bool_in_snapshot",
                "value_a_type": type(a).__name__,
                "value_b_type": type(b).__name__,
            }
        return {"field": field, "transition": "absent_to_present", "to": b}
    if b is None:
        if not isinstance(a, bool):
            return {
                "field": field,
                "anomaly": "non_bool_in_snapshot",
                "value_a_type": type(a).__name__,
                "value_b_type": type(b).__name__,
            }
        return {"field": field, "transition": "present_to_absent", "from": a}
    if not isinstance(a, bool) or not isinstance(b, bool):
        return {
            "field": field,
            "anomaly": "non_bool_in_snapshot",
            "value_a_type": type(a).__name__,
            "value_b_type": type(b).__name__,
        }
    if a == b:
        return None
    return {"field": field, "from": a, "to": b}


def _diff_geometry(
    a: dict[str, Any], b: dict[str, Any], rel_tol: float, abs_tol: float
) -> dict[str, Any] | None:
    """Diff the 5 geometric scalars. Returns dict or None if no change.

    A reported entry can be either a real change (with from/to/delta or
    transition) or an anomaly (with anomaly/value_a_type/value_b_type).
    Anomalies are exposed, not silently dropped.
    """
    changed: list[dict[str, Any]] = []
    for field in ("volume", "area"):
        d = _diff_nullable_float(field, a.get(field), b.get(field), rel_tol, abs_tol)
        if d is not None:
            changed.append(d)
    for field in ("face_count", "edge_count"):
        d = _diff_nullable_int(field, a.get(field), b.get(field))
        if d is not None:
            changed.append(d)
    d = _diff_nullable_bool("is_closed", a.get("is_closed"), b.get("is_closed"))
    if d is not None:
        changed.append(d)
    if not changed:
        return None
    return {"changed_fields": changed}


def _diff_user_text(a: dict[str, str], b: dict[str, str]) -> dict[str, Any]:
    keys_a = set(a.keys())
    keys_b = set(b.keys())
    added = sorted(keys_b - keys_a)
    removed = sorted(keys_a - keys_b)
    changed: list[dict[str, str]] = []
    for k in sorted(keys_a & keys_b):
        if a[k] != b[k]:
            changed.append({"key": k, "from": a[k], "to": b[k]})
    return {"added": added, "removed": removed, "changed": changed}


def _diff_block_context(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Diff the block_context fields. Returns {} when unchanged.

    transform is intentionally not diffed here: positional change is already
    captured by the bbox diff in a more interpretable form. block_context tracks
    identity (is this an instance, of which definition), not pose.
    """
    out: dict[str, Any] = {}
    for field in ("is_block_instance", "block_name", "instance_definition_id"):
        if a.get(field) != b.get(field):
            out[field] = {"from": a.get(field), "to": b.get(field)}
    return out


def _diff_list(a: list[str], b: list[str]) -> dict[str, list[str]]:
    set_a, set_b = set(a or []), set(b or [])
    return {"added": sorted(set_b - set_a), "removed": sorted(set_a - set_b)}


def _diff_object(
    a: dict[str, Any],
    b: dict[str, Any],
    bbox_tolerance: float,
    geom_rel_tolerance: float,
    geom_abs_tolerance: float,
    geometry_enabled: bool,
) -> dict[str, Any] | None:
    changes: dict[str, Any] = {}
    if a.get("layer") != b.get("layer"):
        changes["layer"] = {"from": a.get("layer"), "to": b.get("layer")}
    if a.get("name") != b.get("name"):
        changes["name"] = {"from": a.get("name"), "to": b.get("name")}
    if a.get("raw_type") != b.get("raw_type"):
        changes["raw_type"] = {"from": a.get("raw_type"), "to": b.get("raw_type")}
    if a.get("object_kind") != b.get("object_kind"):
        changes["object_kind"] = {"from": a.get("object_kind"), "to": b.get("object_kind")}
    if a.get("material") != b.get("material"):
        changes["material"] = {"from": a.get("material"), "to": b.get("material")}
    if a.get("annotation_text") != b.get("annotation_text"):
        changes["annotation_text"] = {"from": a.get("annotation_text"), "to": b.get("annotation_text")}

    block_diff = _diff_block_context(a.get("block_context") or {}, b.get("block_context") or {})
    if block_diff:
        changes["block_context"] = block_diff

    ut_diff = _diff_user_text(a.get("user_text") or {}, b.get("user_text") or {})
    if ut_diff["added"] or ut_diff["removed"] or ut_diff["changed"]:
        changes["user_text"] = ut_diff

    gid_diff = _diff_list(a.get("group_ids") or [], b.get("group_ids") or [])
    if gid_diff["added"] or gid_diff["removed"]:
        changes["group_ids"] = gid_diff

    gname_diff = _diff_list(a.get("group_names") or [], b.get("group_names") or [])
    if gname_diff["added"] or gname_diff["removed"]:
        changes["group_names"] = gname_diff

    if not _bbox_equal(a.get("bbox"), b.get("bbox"), bbox_tolerance):
        delta = _center_delta(a.get("bbox_center"), b.get("bbox_center"))
        changes["bbox"] = {
            "changed": True,
            "from": a.get("bbox"),
            "to": b.get("bbox"),
            "delta_center": delta,
        }

    if geometry_enabled:
        geo = _diff_geometry(a, b, geom_rel_tolerance, geom_abs_tolerance)
        if geo is not None:
            changes["geometry"] = geo

    if not changes:
        return None
    return changes


GEOMETRY_DIFF_SUPPORTED_SCHEMA = "developer_snapshot.v2"


DIFF_DETAIL_LEVELS = ("full", "summary")


def diff_snapshots(
    label_a: str,
    label_b: str,
    bbox_tolerance: float = BBOX_TOLERANCE_DEFAULT,
    geom_rel_tolerance: float = GEOM_REL_TOLERANCE_DEFAULT,
    geom_abs_tolerance: float = GEOM_ABS_TOLERANCE_DEFAULT,
    detail: str = "full",
) -> dict[str, Any]:
    if detail not in DIFF_DETAIL_LEVELS:
        return {
            "error": "invalid_detail",
            "message": f"detail must be one of {list(DIFF_DETAIL_LEVELS)}",
            "received": str(detail),
        }
    slug_a, slug_b = slugify_label(label_a), slugify_label(label_b)
    if not slug_a:
        return _invalid_label_error(label_a)
    if not slug_b:
        return _invalid_label_error(label_b)

    path_a = find_latest_by_label(slug_a)
    path_b = find_latest_by_label(slug_b)
    if path_a is None:
        return _snapshot_not_found(slug_a)
    if path_b is None:
        return _snapshot_not_found(slug_b)

    try:
        snap_a = read_snapshot(path_a)
        snap_b = read_snapshot(path_b)
    except Exception as exc:
        return {
            "error": "snapshot_unreadable",
            "message": str(exc),
        }

    objs_a = snap_a.get("objects_by_guid") or {}
    objs_b = snap_b.get("objects_by_guid") or {}
    if not isinstance(objs_a, dict) or not isinstance(objs_b, dict):
        return {"error": "snapshot_invalid_shape"}

    schema_a = str(snap_a.get("schema") or "")
    schema_b = str(snap_b.get("schema") or "")
    geometry_enabled = (
        schema_a == GEOMETRY_DIFF_SUPPORTED_SCHEMA
        and schema_b == GEOMETRY_DIFF_SUPPORTED_SCHEMA
    )
    geometry_warning: dict[str, Any] | None = None
    if not geometry_enabled:
        geometry_warning = {
            "reason": "geometry_diff_skipped",
            "detail": (
                "both snapshots must be "
                f"{GEOMETRY_DIFF_SUPPORTED_SCHEMA} to compare geometric scalars"
            ),
            "schema_a": schema_a,
            "schema_b": schema_b,
        }

    guids_a, guids_b = set(objs_a.keys()), set(objs_b.keys())

    created = sorted(guids_b - guids_a)
    deleted = sorted(guids_a - guids_b)

    modified: list[dict[str, Any]] = []
    unchanged = 0
    for guid in sorted(guids_a & guids_b):
        changes = _diff_object(
            objs_a[guid],
            objs_b[guid],
            float(bbox_tolerance),
            float(geom_rel_tolerance),
            float(geom_abs_tolerance),
            geometry_enabled,
        )
        if changes is None:
            unchanged += 1
        else:
            modified.append(
                {
                    "object_id": guid,
                    "layer_a": objs_a[guid].get("layer"),
                    "layer_b": objs_b[guid].get("layer"),
                    "changes": changes,
                }
            )

    def _row_for(guid: str, src: dict[str, dict[str, Any]]) -> dict[str, Any]:
        item = src.get(guid, {})
        return {
            "object_id": guid,
            "layer": item.get("layer"),
            "name": item.get("name"),
            "raw_type": item.get("raw_type"),
            "user_text_keys": sorted((item.get("user_text") or {}).keys()),
        }

    geometry_diff_block: dict[str, Any] = {
        "enabled": geometry_enabled,
        "rel_tolerance": float(geom_rel_tolerance),
        "abs_tolerance": float(geom_abs_tolerance),
    }
    if geometry_warning is not None:
        geometry_diff_block["warning"] = geometry_warning

    if detail == "summary":
        modified_out: list[dict[str, Any]] = [
            {
                "object_id": row["object_id"],
                "layer_a": row["layer_a"],
                "layer_b": row["layer_b"],
                "changed_categories": sorted(row["changes"].keys()),
            }
            for row in modified
        ]
    else:
        modified_out = modified

    return {
        "label_a": slug_a,
        "label_b": slug_b,
        "filter_a": snap_a.get("capture_filter"),
        "filter_b": snap_b.get("capture_filter"),
        "schema_a": schema_a,
        "schema_b": schema_b,
        "bbox_tolerance": float(bbox_tolerance),
        "geometry_diff": geometry_diff_block,
        "summary": {
            "created_count": len(created),
            "deleted_count": len(deleted),
            "modified_count": len(modified),
            "unchanged_count": unchanged,
            "total_a": len(guids_a),
            "total_b": len(guids_b),
        },
        "created": [_row_for(g, objs_b) for g in created],
        "deleted": [_row_for(g, objs_a) for g in deleted],
        "modified": modified_out,
    }


# ---------------------------------------------------------------------------
# diff_object (zoom: detail for a single GUID across two snapshots)
# ---------------------------------------------------------------------------


def diff_object(
    label_a: str,
    label_b: str,
    guid: str,
    bbox_tolerance: float = BBOX_TOLERANCE_DEFAULT,
    geom_rel_tolerance: float = GEOM_REL_TOLERANCE_DEFAULT,
    geom_abs_tolerance: float = GEOM_ABS_TOLERANCE_DEFAULT,
) -> dict[str, Any]:
    """Return the full diff detail for a single GUID across two snapshots.

    Reuses ``_diff_object`` to guarantee that ``status == 'modified'`` returns
    exactly the same ``changes`` dict that ``diff_snapshots(detail='full')``
    would produce for that GUID. The four statuses are: ``modified``,
    ``unchanged``, ``created`` (only in B), ``deleted`` (only in A).
    """
    guid_text = str(guid or "").strip()
    if not guid_text:
        return {"error": "invalid_guid", "message": "guid is empty"}

    slug_a, slug_b = slugify_label(label_a), slugify_label(label_b)
    if not slug_a:
        return _invalid_label_error(label_a)
    if not slug_b:
        return _invalid_label_error(label_b)

    path_a = find_latest_by_label(slug_a)
    path_b = find_latest_by_label(slug_b)
    if path_a is None:
        return _snapshot_not_found(slug_a)
    if path_b is None:
        return _snapshot_not_found(slug_b)

    try:
        snap_a = read_snapshot(path_a)
        snap_b = read_snapshot(path_b)
    except Exception as exc:
        return {"error": "snapshot_unreadable", "message": str(exc)}

    objs_a = snap_a.get("objects_by_guid") or {}
    objs_b = snap_b.get("objects_by_guid") or {}
    if not isinstance(objs_a, dict) or not isinstance(objs_b, dict):
        return {"error": "snapshot_invalid_shape"}

    schema_a = str(snap_a.get("schema") or "")
    schema_b = str(snap_b.get("schema") or "")
    geometry_enabled = (
        schema_a == GEOMETRY_DIFF_SUPPORTED_SCHEMA
        and schema_b == GEOMETRY_DIFF_SUPPORTED_SCHEMA
    )

    in_a = guid_text in objs_a
    in_b = guid_text in objs_b

    envelope: dict[str, Any] = {
        "label_a": slug_a,
        "label_b": slug_b,
        "object_id": guid_text,
        "schema_a": schema_a,
        "schema_b": schema_b,
        "bbox_tolerance": float(bbox_tolerance),
        "geometry_diff_enabled": geometry_enabled,
    }

    if not in_a and not in_b:
        envelope["status"] = "object_not_in_snapshots"
        return envelope

    if in_a and not in_b:
        envelope["status"] = "deleted"
        envelope["full_object_a"] = objs_a[guid_text]
        return envelope

    if in_b and not in_a:
        envelope["status"] = "created"
        envelope["full_object_b"] = objs_b[guid_text]
        return envelope

    # GUID in both: run the same _diff_object used by diff_snapshots
    changes = _diff_object(
        objs_a[guid_text],
        objs_b[guid_text],
        float(bbox_tolerance),
        float(geom_rel_tolerance),
        float(geom_abs_tolerance),
        geometry_enabled,
    )
    if changes is None:
        envelope["status"] = "unchanged"
        envelope["layer"] = objs_a[guid_text].get("layer")
        envelope["raw_type"] = objs_a[guid_text].get("raw_type")
        return envelope

    envelope["status"] = "modified"
    envelope["layer_a"] = objs_a[guid_text].get("layer")
    envelope["layer_b"] = objs_b[guid_text].get("layer")
    envelope["changes"] = changes
    return envelope


# ---------------------------------------------------------------------------
# inspect_object
# ---------------------------------------------------------------------------


def list_block_definitions(summary: bool = False) -> dict[str, Any]:
    """List block definitions in the live model with instance and member counts.

    Returns one row per definition: definition_name, definition_id, object_count
    (members composing the definition), instance_count (placements in the model),
    and bbox. Use ``expand_block(name)`` to read the members' content.

    With ``summary=True`` the per-definition ``bbox`` is dropped, leaving only names
    and counts. In models with many definitions the bbox dicts dominate the response
    size; the summary keeps the catalogue readable in one call.
    """
    bridge_url, timeout = _bridge_settings()
    try:
        payload = live_list_definitions_bridge(bridge_url, timeout)
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")

    if summary and isinstance(payload.get("definitions"), list):
        slim = [
            {k: v for k, v in d.items() if k != "bbox"}
            for d in payload["definitions"]
            if isinstance(d, dict)
        ]
        out = {k: v for k, v in payload.items() if k != "definitions"}
        out["definitions"] = slim
        out["summarized"] = True
        return out
    return payload


def expand_block(
    definition_name: str, resolve_instances: bool = False, summary: bool = False
) -> dict[str, Any]:
    """Read the objects that compose a block definition (raw, no transform applied).

    This reaches data that lives INSIDE a block — child geometry, their user_text,
    materials and annotation text — which is invisible from the instance alone.
    The ``definition_name`` is matched exactly (case-sensitive); get valid names
    from ``list_block_definitions`` or ``describe_model``.

    With ``resolve_instances=True`` the result also carries an ``instances`` block:
    one row per placed instance, each member's bbox transformed by that instance's
    transform (lightweight — only the bbox is moved, not the heavy geometry).

    With ``summary=True`` the heavy per-member geometry is dropped and ``objects`` is
    replaced by a ``content_summary`` (member type counts, annotation texts, total
    member curve length/area). Use it when you only need to know WHAT is inside a
    definition without the full geometry — definitions with hundreds of members
    otherwise overflow the response. ``resolve_instances`` is ignored in summary mode.
    """
    name = str(definition_name or "").strip()
    if not name:
        return {"error": "invalid_definition_name", "message": "definition_name is empty"}
    bridge_url, timeout = _bridge_settings()
    try:
        payload = live_definition_objects_bridge(
            bridge_url, timeout, name, resolve_instances=bool(resolve_instances) and not summary
        )
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")

    if summary:
        objects = payload.get("objects") if isinstance(payload.get("objects"), list) else []
        out = {k: v for k, v in payload.items() if k != "objects"}
        out["content_summary"] = _summarize_definition_content(objects)
        out["summarized"] = True
        return out
    return payload


def inspect_object(
    guid: str, detail_level: str = "full", user_text: str = "values"
) -> dict[str, Any]:
    guid_text = str(guid or "").strip()
    if not guid_text:
        return {"error": "invalid_guid", "message": "guid is empty"}
    bridge_url, timeout = _bridge_settings()
    try:
        payload = live_object_detail_bridge(
            bridge_url,
            timeout,
            guid_text,
            detail_level=str(detail_level),
            user_text=str(user_text),
        )
    except Exception as exc:
        return _live_only_error(f"{type(exc).__name__}: {exc}")
    return {"status": "ok", "object_id": guid_text, "detail": payload}


# ---------------------------------------------------------------------------
# detailed per-element geometry: vertices / edges / faces
# ---------------------------------------------------------------------------


def _get_elements(guid: str, element: str) -> dict[str, Any]:
    guid_text = str(guid or "").strip()
    if not guid_text:
        return {"error": "invalid_guid", "message": "guid is empty"}
    bridge_url, timeout = _bridge_settings()
    try:
        return live_object_elements_bridge(bridge_url, timeout, guid_text, element)
    except Exception as exc:
        return _bridge_error_or_live_unavailable(exc, object_id=guid_text)


def _bridge_error_or_live_unavailable(exc: Exception, *, object_id: str | None = None) -> dict[str, Any]:
    """Classify a bridge call failure honestly.

    A 4xx from the bridge is a client/usage error (e.g. unsupported geometry type,
    object not found) and carries the bridge's own message — report it as such, NOT as
    ``live_mode_unavailable`` which means "the live model could not be reached" and is
    misleading for a 400. Connectivity/5xx still map to live_mode_unavailable.
    """
    msg = str(exc)
    m = re.match(r"bridge_http_error:(\d{3})(?::(.*))?$", msg)
    if m and m.group(1)[0] == "4":
        out: dict[str, Any] = {
            "error": "bridge_request_rejected",
            "http_status": int(m.group(1)),
            "message": (m.group(2) or "").strip() or "bridge rejected the request",
        }
        if object_id is not None:
            out["object_id"] = object_id
        return out
    return _live_only_error(f"{type(exc).__name__}: {exc}")


def get_vertices(guid: str) -> dict[str, Any]:
    """Vertex coordinates of one solid: list of {index, coord:[x,y,z]}.

    Works for Brep, Extrusion and Mesh; an unsupported type returns an honest error
    (not an empty list). This is the raw geometry the aggregate fields cannot give.

    Agnostic acid test (docs/agnostic_principle.md):
      1. Exists in any domain?  ✓ vertices are universal to any B-rep/mesh.
      2. Needs to know what the object represents?  ✓ NO — pure geometry.
      3. Client derivable from raw primitives?  ✓ NO — needs the geometry kernel's
         topology; not reconstructable from bbox/normals.
      4. An LLM can conclude it from raw geometric data?  ✓ NO — it cannot infer the
         real vertex coordinates from face_count/edge_count; expose the primitive.
    """
    return _get_elements(guid, "vertices")


def get_edges(guid: str) -> dict[str, Any]:
    """Edges of one solid: list of {index, start, end, length, is_curved, samples}.

    ``samples`` is a polyline approximation, present only when ``is_curved`` is true.
    Works for Brep, Extrusion and Mesh (mesh edges are straight); unsupported type ->
    honest error. ``index`` is referenced by get_faces' ``edge_indices`` (topology).

    Agnostic acid test (docs/agnostic_principle.md):
      1. Exists in any domain?  ✓ edges are universal.
      2. Needs to know what the object represents?  ✓ NO — pure geometry.
      3. Client derivable from raw primitives?  ✓ NO — needs the kernel's edge topology.
      4. An LLM can conclude it from raw geometric data?  ✓ NO — cannot derive each
         edge's endpoints/length from aggregate counts; expose the primitive.
    """
    return _get_elements(guid, "edges")


def get_faces(guid: str) -> dict[str, Any]:
    """Faces of one solid: list of {index, normal, area, centroid, perimeter,
    is_planar, edge_indices}.

    ``edge_indices`` references get_edges' indices, tying each face to the edges that
    bound it — the topology that makes a face part of a solid, not a floating normal.
    Works for Brep, Extrusion and Mesh; unsupported type -> honest error.

    Agnostic acid test (docs/agnostic_principle.md):
      1. Exists in any domain?  ✓ faces are universal.
      2. Needs to know what the object represents?  ✓ NO — pure geometry/topology.
      3. Client derivable from raw primitives?  ✓ NO — needs the kernel's face loops.
      4. An LLM can conclude it from raw geometric data?  ✓ NO — cannot reconstruct
         the boundary/edge membership of each face from aggregates; expose it.
    """
    return _get_elements(guid, "faces")


# ---------------------------------------------------------------------------
# assert_change
# ---------------------------------------------------------------------------


def _match_object_against_filter(obj: dict[str, Any], flt: dict[str, Any]) -> bool:
    if not isinstance(flt, dict):
        return True
    in_layer = flt.get("in_layer")
    if in_layer is not None and str(obj.get("layer", "")) != str(in_layer):
        return False
    with_key = flt.get("with_user_text_key")
    user_text = obj.get("user_text") or {}
    if with_key is not None and str(with_key) not in user_text:
        return False
    with_pairs = flt.get("with_user_text")
    if isinstance(with_pairs, dict):
        for k, v in with_pairs.items():
            if user_text.get(str(k)) != str(v):
                return False
    raw_type = flt.get("raw_type")
    if raw_type is not None and str(obj.get("raw_type", "")) != str(raw_type):
        return False
    return True


def _filter_diff_rows(rows: list[dict[str, Any]], src: dict[str, dict[str, Any]], flt: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(flt, dict) or not flt:
        return rows
    keep: list[dict[str, Any]] = []
    for row in rows:
        full = src.get(row["object_id"], {})
        if _match_object_against_filter(full, flt):
            keep.append(row)
    return keep


def _eval_count_rule(
    rule_name: str,
    expected: dict[str, Any],
    actual_count: int,
) -> dict[str, Any]:
    passed = True
    reasons: list[str] = []
    if "min" in expected:
        try:
            min_v = int(expected["min"])
            if actual_count < min_v:
                passed = False
                reasons.append(f"actual={actual_count} < min={min_v}")
        except (TypeError, ValueError):
            passed = False
            reasons.append("min not an integer")
    if "max" in expected:
        try:
            max_v = int(expected["max"])
            if actual_count > max_v:
                passed = False
                reasons.append(f"actual={actual_count} > max={max_v}")
        except (TypeError, ValueError):
            passed = False
            reasons.append("max not an integer")
    if "exact" in expected:
        try:
            exact_v = int(expected["exact"])
            if actual_count != exact_v:
                passed = False
                reasons.append(f"actual={actual_count} != exact={exact_v}")
        except (TypeError, ValueError):
            passed = False
            reasons.append("exact not an integer")
    return {
        "rule": rule_name,
        "expected": expected,
        "actual_count": actual_count,
        "passed": passed,
        "reasons": reasons,
    }


def assert_change(
    label_a: str, label_b: str, expectations: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(expectations, dict):
        return {"error": "invalid_expectations", "message": "expectations must be a dict"}

    bbox_tolerance = float(expectations.get("bbox_tolerance", BBOX_TOLERANCE_DEFAULT))
    diff = diff_snapshots(label_a, label_b, bbox_tolerance=bbox_tolerance)
    if "error" in diff:
        return {"passed": False, "results": [], "diff": diff}

    slug_a = slugify_label(label_a)
    slug_b = slugify_label(label_b)
    path_a = find_latest_by_label(slug_a)
    path_b = find_latest_by_label(slug_b)
    try:
        snap_a = read_snapshot(path_a) if path_a else {}
        snap_b = read_snapshot(path_b) if path_b else {}
    except Exception as exc:
        return {"passed": False, "error": "snapshot_unreadable", "message": str(exc)}
    objs_a = snap_a.get("objects_by_guid") or {}
    objs_b = snap_b.get("objects_by_guid") or {}

    results: list[dict[str, Any]] = []

    if "created" in expectations and isinstance(expectations["created"], dict):
        flt = {k: v for k, v in expectations["created"].items() if k not in ("min", "max", "exact")}
        filtered = _filter_diff_rows(diff["created"], objs_b, flt)
        results.append(_eval_count_rule("created", expectations["created"], len(filtered)))

    if "deleted" in expectations and isinstance(expectations["deleted"], dict):
        flt = {k: v for k, v in expectations["deleted"].items() if k not in ("min", "max", "exact")}
        filtered = _filter_diff_rows(diff["deleted"], objs_a, flt)
        results.append(_eval_count_rule("deleted", expectations["deleted"], len(filtered)))

    if "modified" in expectations and isinstance(expectations["modified"], dict):
        where = expectations["modified"].get("where") if isinstance(expectations["modified"].get("where"), dict) else {}
        filtered = _filter_diff_rows(diff["modified"], objs_b, where)
        rule_expected = {k: v for k, v in expectations["modified"].items() if k in ("min", "max", "exact")}
        results.append(_eval_count_rule("modified", rule_expected, len(filtered)))

    overall = all(r["passed"] for r in results) if results else True
    return {
        "passed": overall,
        "results": results,
        "diff_summary": diff.get("summary"),
        "label_a": slug_a,
        "label_b": slug_b,
    }
