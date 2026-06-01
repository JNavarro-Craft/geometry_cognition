"""Pure logic for developer_server: snapshot capture, diff, inspect, assert."""
from __future__ import annotations

import os
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
    live_object_detail_bridge,
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
        "transform": [float(x) for x in obj["transform"]] if isinstance(obj.get("transform"), list) and len(obj.get("transform")) == 16 else None,
        "bbox": bbox if isinstance(bbox, dict) else None,
        "bbox_center": list(bbox_center) if isinstance(bbox_center, list) else None,
        "volume": volume,
        "area": area,
        "face_count": face_count,
        "edge_count": edge_count,
        "is_closed": is_closed,
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
    return {f: obj.get(f) for f in fields}


def query_objects(
    filters: dict[str, Any] | None = None,
    source: str = "live",
    limit: int | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Query objects by AND-combined filters, over the live model or a snapshot.

    ``source``: ``"live"`` (default) queries the active bridge model;
    any other value is treated as a snapshot label to query the persisted objects.
    Snapshot mode lets you query a past state. Both report ``matched_count``;
    use ``describe_model`` first to discover valid filter values.
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
    if limit is not None:
        matched = matched[: max(0, int(limit))]
    rows = [_project_query_fields(o, field_list) for o in matched]

    out: dict[str, Any] = {
        "source": src_label,
        "filters": flt,
        "matched_count": total_matched,
        "returned_count": len(rows),
        "objects": rows,
    }
    out.update(extra)
    return out


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
