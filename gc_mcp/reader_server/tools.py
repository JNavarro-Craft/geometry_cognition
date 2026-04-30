from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from gc_mcp.reader_server.loaders import OutputsLoader, structured_file_not_found
from gc_mcp.rhino_extractor.bridge_backend import extract_objects_bridge
from workflows.run_minimal_analysis import run as run_minimal_analysis


_LOADER = OutputsLoader()
_SNAPSHOT_FILES = [
    "objects.json",
    "geometry_features.json",
    "entities.json",
    "relations.json",
    "minimal_analysis_bundle.json",
]


def _load_required(filename: str) -> tuple[Any | None, dict[str, str] | None]:
    return _LOADER.load_json(filename)


def _artifact_not_generated(artifact: str, note: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available": False,
        "reason": "artifact_not_generated_in_current_pipeline",
        "expected_artifact": artifact,
    }
    if note:
        payload["note"] = note
    return payload


def _load_objects() -> tuple[list[dict[str, Any]] | None, dict[str, str] | None]:
    data, err = _load_required("objects.json")
    if err:
        return None, err
    if not isinstance(data, list):
        return [], None
    return [x for x in data if isinstance(x, dict)], None


def _collect_group_names(obj: dict[str, Any]) -> list[str]:
    names: list[str] = []
    raw_names = obj.get("group_names", [])
    if isinstance(raw_names, list):
        for item in raw_names:
            text = str(item or "")
            if text:
                names.append(text)
    raw_ids = obj.get("group_ids", [])
    if isinstance(raw_ids, list):
        for item in raw_ids:
            text = str(item or "")
            if text.startswith("group_name:"):
                name = text.split(":", 1)[1].strip()
                if name:
                    names.append(name)
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped


def _collect_group_ids(obj: dict[str, Any]) -> list[str]:
    group_ids = obj.get("group_ids", [])
    if not isinstance(group_ids, list):
        return []
    return [str(x) for x in group_ids if str(x)]


def _object_row(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_id": str(obj.get("object_id", "")),
        "name": str(obj.get("name", "")),
        "type": str(obj.get("raw_type", "")),
        "layer": str(obj.get("layer", "")),
    }


def _load_relations() -> tuple[list[dict[str, Any]] | None, dict[str, str] | None]:
    data, err, _ = _LOADER.load_first_available(["relations_verified.json", "relations.json"])
    if err:
        return None, err
    if not isinstance(data, list):
        return [], None
    return [x for x in data if isinstance(x, dict)], None


def _load_hypotheses() -> tuple[list[dict[str, Any]] | None, dict[str, str] | None]:
    data, err, _ = _LOADER.load_first_available(["hypotheses_verified.json", "hypotheses.json"])
    if err:
        return None, err
    if not isinstance(data, list):
        return [], None
    return [x for x in data if isinstance(x, dict)], None


def _load_evidence_graph() -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    data, err, _ = _LOADER.load_first_available(["evidence_graph_verified.json", "evidence_graph.json"])
    if err:
        return None, err
    if not isinstance(data, dict):
        return {}, None
    return data, None


def get_analysis_summary() -> dict[str, Any]:
    objects, err = _load_required("objects.json")
    if err:
        return err
    relations, err = _load_relations()
    if err:
        return err
    hypotheses, hyp_err = _load_hypotheses()
    evidence_graph, evg_err = _load_evidence_graph()

    if not isinstance(objects, list):
        objects = []
    evidence_items = evidence_graph.get("evidence_items", []) if isinstance(evidence_graph, dict) else []
    if not isinstance(evidence_items, list):
        evidence_items = []
    if hyp_err:
        hypotheses = []
    if evg_err:
        evidence_items = []

    breakdown = {"candidate": 0, "measured": 0, "confirmed": 0, "unknown": 0}
    for rel in relations or []:
        level = str(rel.get("assertion_level", "unknown")).lower()
        if level in breakdown:
            breakdown[level] += 1
        else:
            breakdown["unknown"] += 1

    out = {
        "total_objects": len(objects),
        "total_relations": len(relations or []),
        "relations_by_assertion_level": breakdown,
        "total_hypotheses": len(hypotheses or []),
        "total_evidence_items": len(evidence_items),
    }
    legacy_artifacts: dict[str, Any] = {}
    if hyp_err:
        legacy_artifacts["hypotheses"] = _artifact_not_generated(
            "hypotheses_verified.json | hypotheses.json",
            note="pipeline simplified to extractor + geometry_kernel snapshot",
        )
    if evg_err:
        legacy_artifacts["evidence_graph"] = _artifact_not_generated(
            "evidence_graph_verified.json | evidence_graph.json",
            note="pipeline simplified to extractor + geometry_kernel snapshot",
        )
    if legacy_artifacts:
        out["legacy_artifacts"] = legacy_artifacts
    return out


def get_objects(limit: int | None = None) -> dict[str, Any]:
    objects, err = _load_required("objects.json")
    if err:
        return err
    if not isinstance(objects, list):
        objects = []
    rows = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        rows.append(
            {
                "object_id": str(obj.get("object_id", "")),
                "name": str(obj.get("name", "")),
                "type": str(obj.get("raw_type", "")),
                "layer": str(obj.get("layer", "")),
            }
        )
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return {"objects": rows, "count": len(rows)}


def get_object_details(object_id: str) -> dict[str, Any]:
    objects, err = _load_required("objects.json")
    if err:
        return err
    if not isinstance(objects, list):
        objects = []
    target = next((obj for obj in objects if isinstance(obj, dict) and str(obj.get("object_id", "")) == str(object_id)), None)
    if target is None:
        return {"error": "not_found", "object_id": object_id}

    geom, geom_err = _load_required("geometry_features.json")
    geom_feature = None
    if geom_err is None and isinstance(geom, list):
        geom_feature = next(
            (g for g in geom if isinstance(g, dict) and str(g.get("object_id", "")) == str(object_id)),
            None,
        )
    return {
        "object": target,
        "geometry_feature": geom_feature,
    }


def get_confirmed_relations(predicate: str | None = None) -> dict[str, Any]:
    relations, err = _load_relations()
    if err:
        return err
    filtered = []
    for rel in relations or []:
        if str(rel.get("assertion_level", "")) != "confirmed":
            continue
        if predicate is not None and str(rel.get("predicate", "")) != str(predicate):
            continue
        filtered.append(
            {
                "relation_id": str(rel.get("relation_id", "")),
                "subject_id": str(rel.get("subject_id", "")),
                "object_id": str(rel.get("object_id", "")),
                "predicate": str(rel.get("predicate", "")),
                "assertion_level": str(rel.get("assertion_level", "")),
                "verification_status": str(rel.get("verification_status", "")),
                "verification_result": rel.get("verification_result", {}),
            }
        )
    return {"relations": filtered, "count": len(filtered)}


def get_relations_for_object(object_id: str, assertion_level: str | None = None) -> dict[str, Any]:
    relations, err = _load_relations()
    if err:
        return err
    out = []
    for rel in relations or []:
        sid = str(rel.get("subject_id", ""))
        oid = str(rel.get("object_id", ""))
        if sid != object_id and oid != object_id:
            continue
        if assertion_level is not None and str(rel.get("assertion_level", "")) != assertion_level:
            continue
        out.append(rel)
    return {"relations": out, "count": len(out)}


def get_evidence_for_relation(relation_id: str) -> dict[str, Any]:
    evidence_graph, err = _load_required("evidence_graph.json")
    if err:
        return {
            "relation_id": relation_id,
            "evidence_items": [],
            "count": 0,
            "artifact": _artifact_not_generated(
                "evidence_graph.json",
                note="evidence graph is not generated by the current simplified pipeline",
            ),
        }
    if not isinstance(evidence_graph, dict):
        return structured_file_not_found("evidence_graph.json")
    evidence_items = evidence_graph.get("evidence_items", [])
    if not isinstance(evidence_items, list):
        evidence_items = []
    exact_id = f"ev-rel-{relation_id}"
    matched = [
        item
        for item in evidence_items
        if isinstance(item, dict) and str(item.get("evidence_id", "")) == exact_id
    ]
    return {"relation_id": relation_id, "evidence_items": matched, "count": len(matched)}


def get_reasoning_output() -> dict[str, Any]:
    data, err = _load_required("reasoned_analysis_verified.json")
    if err:
        return _artifact_not_generated(
            "reasoned_analysis_verified.json",
            note="reasoning output is not generated by the current simplified pipeline",
        )
    return {"available": True, "reasoning_output": data}


def get_inventory_summary() -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    rows = objects or []

    type_counts: dict[str, int] = {}
    layer_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    with_user_text = 0

    for obj in rows:
        obj_type = str(obj.get("raw_type", ""))
        type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

        layer = str(obj.get("layer", ""))
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

        for group_name in _collect_group_names(obj):
            group_counts[group_name] = group_counts.get(group_name, 0) + 1

        user_text = obj.get("user_text")
        if isinstance(user_text, dict) and len(user_text) > 0:
            with_user_text += 1

    total = len(rows)
    without_user_text = max(0, total - with_user_text)
    coverage = 0.0
    if total > 0:
        coverage = round((with_user_text / total) * 100.0, 2)

    top_layers = sorted(layer_counts.items(), key=lambda x: (-x[1], x[0]))[:10]
    top_groups = sorted(group_counts.items(), key=lambda x: (-x[1], x[0]))[:10]

    return {
        "total_objects": total,
        "total_layers": len(layer_counts),
        "total_groups": len(group_counts),
        "object_types_breakdown": type_counts,
        "user_text_coverage": {
            "con_user_text": with_user_text,
            "sin_user_text": without_user_text,
            "percentage": coverage,
        },
        "top_layers": [{"name": name, "object_count": count} for name, count in top_layers],
        "top_groups": [{"name": name, "object_count": count} for name, count in top_groups],
    }


def get_layers() -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    buckets: dict[str, dict[str, Any]] = {}
    for obj in objects or []:
        layer = str(obj.get("layer", ""))
        row = buckets.setdefault(layer, {"name": layer, "object_count": 0, "object_types": set()})
        row["object_count"] += 1
        row["object_types"].add(str(obj.get("raw_type", "")))

    out: list[dict[str, Any]] = []
    for layer_name in sorted(buckets.keys()):
        row = buckets[layer_name]
        out.append(
            {
                "name": row["name"],
                "object_count": row["object_count"],
                "object_types": sorted([x for x in row["object_types"] if isinstance(x, str)]),
            }
        )
    return {"layers": out, "count": len(out)}


def get_groups() -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    buckets: dict[str, dict[str, Any]] = {}
    for obj in objects or []:
        group_names = _collect_group_names(obj)
        group_ids = _collect_group_ids(obj)
        user_text = obj.get("user_text", {})
        keys: list[str] = []
        if isinstance(user_text, dict):
            keys = [str(k) for k in user_text.keys()]

        for group_name in group_names:
            bucket = buckets.setdefault(
                group_name,
                {
                    "group_id": group_name,
                    "group_names": set([group_name]),
                    "object_ids": set(),
                    "user_text_keys": set(),
                },
            )
            for gid in group_ids:
                if gid.startswith("group_index:"):
                    bucket["group_id"] = gid
            bucket["group_names"].add(group_name)
            bucket["object_ids"].add(str(obj.get("object_id", "")))
            for key in keys:
                if key:
                    bucket["user_text_keys"].add(key)

    groups: list[dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        bucket = buckets[key]
        groups.append(
            {
                "group_id": bucket["group_id"],
                "group_names": sorted(list(bucket["group_names"])),
                "object_count": len(bucket["object_ids"]),
                "user_text_keys_in_group": sorted(list(bucket["user_text_keys"])),
            }
        )
    return {"groups": groups, "count": len(groups)}


def get_objects_by_layer(layer_name: str, limit: int | None = None) -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    layer = str(layer_name)
    matched: list[dict[str, Any]] = []
    layer_exists = False
    for obj in objects or []:
        obj_layer = str(obj.get("layer", ""))
        if obj_layer == layer:
            layer_exists = True
            row = _object_row(obj)
            row["group_ids"] = _collect_group_ids(obj)
            matched.append(row)
    if limit is not None:
        matched = matched[: max(0, int(limit))]
    if not layer_exists:
        return {"objects": [], "count": 0, "layer": layer, "warning": "layer_not_found"}
    return {"objects": matched, "count": len(matched), "layer": layer}


def get_objects_by_group(group_name: str, limit: int | None = None) -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    group = str(group_name)
    matched: list[dict[str, Any]] = []
    group_exists = False
    for obj in objects or []:
        names = _collect_group_names(obj)
        if group in names:
            group_exists = True
            matched.append(
                {
                    "object_id": str(obj.get("object_id", "")),
                    "name": str(obj.get("name", "")),
                    "type": str(obj.get("raw_type", "")),
                    "layer": str(obj.get("layer", "")),
                }
            )
    if limit is not None:
        matched = matched[: max(0, int(limit))]
    if not group_exists:
        return {"objects": [], "count": 0, "group": group, "warning": "group_not_found"}
    return {"objects": matched, "count": len(matched), "group": group}


def get_objects_by_user_text(key: str, value: str | None = None, limit: int | None = None) -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    key_text = str(key)
    value_text = str(value) if value is not None else None
    matched: list[dict[str, Any]] = []
    key_found = False
    for obj in objects or []:
        user_text = obj.get("user_text")
        if not isinstance(user_text, dict):
            continue
        if key_text not in user_text:
            continue
        key_found = True
        current_value = str(user_text.get(key_text, ""))
        if value_text is not None and current_value != value_text:
            continue
        matched.append(
            {
                "object_id": str(obj.get("object_id", "")),
                "name": str(obj.get("name", "")),
                "type": str(obj.get("raw_type", "")),
                "layer": str(obj.get("layer", "")),
                "matched_value": current_value,
            }
        )
    if limit is not None:
        matched = matched[: max(0, int(limit))]
    if not key_found:
        return {
            "objects": [],
            "count": 0,
            "key": key_text,
            "value": value_text,
            "warning": "key_not_found_in_model",
        }
    return {"objects": matched, "count": len(matched), "key": key_text, "value": value_text}


def find_orphans(criterion: str = "no_group", limit: int | None = None) -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    supported = ["no_group", "no_user_text", "no_name"]
    criterion_text = str(criterion)
    if criterion_text not in supported:
        return {
            "orphans": [],
            "count": 0,
            "criterion": criterion_text,
            "error": "unsupported_criterion",
            "supported": supported,
        }

    out: list[dict[str, Any]] = []
    for obj in objects or []:
        reason = None
        if criterion_text == "no_group":
            if len(_collect_group_ids(obj)) == 0 and len(_collect_group_names(obj)) == 0:
                reason = "no_group"
        elif criterion_text == "no_user_text":
            user_text = obj.get("user_text")
            if not isinstance(user_text, dict) or len(user_text) == 0:
                reason = "no_user_text"
        elif criterion_text == "no_name":
            if str(obj.get("name", "")).strip() == "":
                reason = "no_name"

        if reason is not None:
            out.append(
                {
                    "object_id": str(obj.get("object_id", "")),
                    "type": str(obj.get("raw_type", "")),
                    "layer": str(obj.get("layer", "")),
                    "group_ids": _collect_group_ids(obj),
                    "reason": reason,
                }
            )
    if limit is not None:
        out = out[: max(0, int(limit))]
    return {"orphans": out, "count": len(out), "criterion": criterion_text}


def get_user_text_keys_summary() -> dict[str, Any]:
    objects, err = _load_objects()
    if err:
        return err
    buckets: dict[str, dict[str, Any]] = {}
    for obj in objects or []:
        user_text = obj.get("user_text")
        if not isinstance(user_text, dict):
            continue
        for raw_key, raw_value in user_text.items():
            key = str(raw_key)
            value = str(raw_value)
            bucket = buckets.setdefault(key, {"occurrence_count": 0, "values": set(), "example_value": value})
            bucket["occurrence_count"] += 1
            bucket["values"].add(value)
            if bucket.get("example_value", "") == "":
                bucket["example_value"] = value

    keys: list[dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        bucket = buckets[key]
        keys.append(
            {
                "key": key,
                "occurrence_count": int(bucket["occurrence_count"]),
                "example_value": str(bucket.get("example_value", "")),
                "distinct_values_count": len(bucket["values"]),
            }
        )
    return {"keys": keys, "total_distinct_keys": len(keys)}


def _file_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "mtime": 0.0, "size": 0}
    stat = path.stat()
    return {"exists": True, "mtime": float(stat.st_mtime), "size": int(stat.st_size)}


def get_snapshot_status() -> dict[str, Any]:
    output_dir = _LOADER.outputs_dir
    files: dict[str, dict[str, Any]] = {}
    ready = True
    for name in _SNAPSHOT_FILES:
        status = _file_status(output_dir / name)
        files[name] = status
        if not status["exists"]:
            ready = False
    objects_count = 0
    objects, err = _load_required("objects.json")
    if err is None and isinstance(objects, list):
        objects_count = len([x for x in objects if isinstance(x, dict)])
    return {"output_dir": str(output_dir), "files": files, "ready": ready, "summary": {"objects": objects_count}}


def refresh_snapshot() -> dict:
    output_dir = _LOADER.outputs_dir
    mode = "bridge" if str(os.environ.get("GC_BACKEND_MODE", "")).strip().lower() == "bridge" else "local"
    bridge_url = str(os.environ.get("GC_BRIDGE_BASE_URL", "http://127.0.0.1:8765"))
    timeout = float(os.environ.get("GC_BRIDGE_TIMEOUT_SECONDS", "10") or "10")
    fallback_local = str(os.environ.get("GC_BRIDGE_FALLBACK_LOCAL", "true")).strip().lower() in {"1", "true", "yes", "on"}

    before: dict[str, dict[str, Any]] = {}
    for name in _SNAPSHOT_FILES:
        before[name] = _file_status(output_dir / name)

    try:
        bundle = run_minimal_analysis(input_path=None, output_dir=output_dir)
    except Exception as exc:
        message = str(exc)
        if mode == "bridge":
            if "Missing required payload key: input_path" in message:
                bridge_probe_error = None
                try:
                    extract_objects_bridge(bridge_url, timeout)
                except Exception as probe_exc:
                    bridge_probe_error = str(probe_exc)
                return {
                    "status": "error",
                    "error_type": "bridge_fallback_local_triggered",
                    "message": "bridge call failed and local fallback required input_path; snapshot refresh aborted",
                    "bridge_url": bridge_url,
                    "bridge_timeout_seconds": timeout,
                    "bridge_fallback_local": fallback_local,
                    "bridge_probe_error": bridge_probe_error,
                    "mode": mode,
                    "output_dir": str(output_dir),
                }
            if "bridge_backend_failed" in message:
                return {
                    "status": "error",
                    "error_type": "bridge_backend_failed",
                    "message": message,
                    "bridge_url": bridge_url,
                    "bridge_timeout_seconds": timeout,
                    "bridge_fallback_local": fallback_local,
                    "mode": mode,
                    "output_dir": str(output_dir),
                }
        return {
            "status": "error",
            "message": message,
            "mode": mode,
            "output_dir": str(output_dir),
        }

    _LOADER.invalidate(_SNAPSHOT_FILES)

    refreshed_files: dict[str, dict[str, Any]] = {}
    for name in _SNAPSHOT_FILES:
        after = _file_status(output_dir / name)
        before_mtime = float(before[name].get("mtime", 0.0))
        after_mtime = float(after.get("mtime", 0.0))
        refreshed_files[name] = {
            "exists": bool(after.get("exists", False)),
            "mtime_before": before_mtime,
            "mtime_after": after_mtime,
            "size_after": int(after.get("size", 0)),
            "changed": bool(after.get("exists", False) and after_mtime != before_mtime),
        }

    return {
        "status": "ok",
        "mode": mode,
        "output_dir": str(output_dir),
        "refreshed_files": refreshed_files,
        "summary": {
            "objects": len(bundle.get("objects", [])),
            "geometry_features": len(bundle.get("geometry_features", [])),
            "entities": len(bundle.get("entities", [])),
            "relations": len(bundle.get("relations", [])),
        },
        "message": "snapshot refreshed",
    }

