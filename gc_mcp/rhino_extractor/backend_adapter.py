from __future__ import annotations

import os
from typing import Any, Callable
from uuid import uuid4

from shared.contracts import validate_payload

from gc_mcp.rhino_extractor.bridge_backend import extract_objects_bridge


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _identity_transform() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _normalize_transform(value: Any, warnings: list[str]) -> list[float]:
    if isinstance(value, list) and len(value) == 16:
        try:
            return [float(x) for x in value]
        except (TypeError, ValueError):
            pass
    warnings.append("bridge_transform_not_available")
    return _identity_transform()


def _normalize_raw_geometry_summary(src: dict[str, Any]) -> dict[str, Any]:
    raw_geometry_summary = src.get("raw_geometry_summary") if isinstance(src.get("raw_geometry_summary"), dict) else {}
    for key in ("bbox", "bbox_corners", "sample_points", "face_count", "face_normals", "face_areas", "edge_count", "is_closed", "volume", "area"):
        if key in src and key not in raw_geometry_summary:
            raw_geometry_summary[key] = src.get(key)

    # object_schema.v1 enforces bbox.additionalProperties=false -> keep only min/max.
    bbox = raw_geometry_summary.get("bbox")
    if isinstance(bbox, dict):
        if "center" in bbox and "bbox_center" not in raw_geometry_summary:
            raw_geometry_summary["bbox_center"] = bbox.get("center")
        cleaned_bbox: dict[str, Any] = {}
        if "min" in bbox:
            cleaned_bbox["min"] = bbox.get("min")
        if "max" in bbox:
            cleaned_bbox["max"] = bbox.get("max")
        raw_geometry_summary["bbox"] = cleaned_bbox

    raw_geometry_summary["source"] = "rhino_bridge"
    return raw_geometry_summary


def _normalize_bridge_objects(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any]
    if isinstance(payload.get("objects"), list):
        candidates = payload["objects"]
    elif isinstance(payload.get("items"), list):
        candidates = payload["items"]
    elif isinstance(payload.get("data"), list):
        candidates = payload["data"]
    elif isinstance(payload.get("object"), dict):
        candidates = [payload["object"]]
    else:
        candidates = []

    normalized: list[dict[str, Any]] = []
    for src in candidates:
        if not isinstance(src, dict):
            continue
        warnings: list[str] = []
        metadata = src.get("metadata") if isinstance(src.get("metadata"), dict) else {}
        oid = str(src.get("object_id") or src.get("id") or uuid4())
        source_ref = str(src.get("source_ref") or src.get("id") or oid)
        block_info = src.get("block_info") if isinstance(src.get("block_info"), dict) else {}
        if isinstance(metadata.get("block_info"), dict):
            block_info = metadata["block_info"]

        is_block = bool(block_info.get("is_block_instance") or src.get("is_block_instance") or False)
        block_name = block_info.get("block_name")
        instance_definition_id = block_info.get("instance_definition_id") or block_info.get("instance_definition_index")

        raw_geometry_summary = _normalize_raw_geometry_summary(src)

        transform_src = src.get("transform")
        if transform_src is None and isinstance(metadata, dict):
            transform_src = metadata.get("transform")
        transform = _normalize_transform(transform_src, warnings)

        out = {
            "object_id": oid,
            "source_system": "rhino_bridge",
            "source_ref": source_ref,
            "object_kind": str(src.get("object_kind") or ("instance_reference" if is_block else "geometric_object")),
            "raw_type": str(src.get("raw_type") or src.get("type") or "UnknownGeometry"),
            "layer": str(src.get("layer") or ""),
            "name": str(src.get("name") or ""),
            "group_ids": [str(x) for x in (src.get("group_ids") or src.get("groups") or [])],
            "group_names": [str(x) for x in (src.get("group_names") or [])],
            "block_context": {
                "is_block_instance": is_block,
                "block_name": str(block_name) if block_name is not None else None,
                "instance_definition_id": str(instance_definition_id) if instance_definition_id is not None else None,
            },
            "user_text": {str(k): str(v) for k, v in (src.get("user_text") or {}).items()} if isinstance(src.get("user_text"), dict) else {},
            "material": str(src.get("material")) if src.get("material") is not None else None,
            "transform": transform,
            "geometry_ref": str(src.get("geometry_ref") or f"rhino-bridge://{source_ref}"),
            "raw_geometry_summary": raw_geometry_summary,
            "extraction_warnings": [str(x) for x in (src.get("extraction_warnings") or [])] + warnings,
        }
        validate_payload("object_schema.v1.json", out)
        normalized.append(out)
    return normalized


def extract_objects(
    input_path: str | None,
    local_extractor: Callable[[str | None], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str, list[str]]:
    mode = str(os.getenv("GC_BACKEND_MODE", "local")).strip().lower() or "local"
    bridge_url = str(os.getenv("GC_BRIDGE_BASE_URL", "http://127.0.0.1:8765"))
    timeout = float(os.getenv("GC_BRIDGE_TIMEOUT_SECONDS", "10") or "10")
    fallback_local = _env_bool("GC_BRIDGE_FALLBACK_LOCAL", True)

    if mode != "bridge":
        return local_extractor(input_path), "local", []

    try:
        bridge_payload = extract_objects_bridge(bridge_url, timeout)
        objects = _normalize_bridge_objects(bridge_payload)
        return objects, "bridge", []
    except Exception as exc:
        if fallback_local:
            return local_extractor(input_path), "local_fallback", [f"bridge_backend_failed:{type(exc).__name__}"]
        raise RuntimeError(f"bridge_backend_failed:{type(exc).__name__}:{exc}") from exc
