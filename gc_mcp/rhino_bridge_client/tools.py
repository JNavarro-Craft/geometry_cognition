from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from gc_mcp.rhino_bridge_client.backend_adapter import extract_objects as extract_objects_via_backend
from shared.contracts import validate_payload

logger = logging.getLogger(__name__)


def _identity_transform() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _transform_to_list(xform: Any) -> list[float] | None:
    if xform is None:
        return None
    try:
        arr = xform.ToFloatArray(True)
        if arr is None:
            return None
        out = [float(x) for x in arr]
        if len(out) == 16:
            return out
    except Exception:
        return None
    return None


def _normalize_fixture_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "objects" in data and isinstance(data["objects"], list):
        return data["objects"]
    if isinstance(data, dict):
        return [data]
    raise ValueError("Unsupported fixture format for extractor input.")


def _extract_from_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    objects = _normalize_fixture_payload(data)
    for obj in objects:
        validate_payload("object_schema.v1.json", obj)
    return objects


def _group_index_to_name(model: Any) -> dict[int, str]:
    mapping: dict[int, str] = {}
    try:
        for g in model.Groups:
            mapping[int(g.Index)] = str(g.Name or "")
    except Exception:
        pass
    return mapping


def _find_instance_definition(model: Any, idef_id: Any) -> Any | None:
    try:
        for idef in model.InstanceDefinitions:
            if str(idef.Id) == str(idef_id):
                return idef
    except Exception:
        return None
    return None


def _read_user_text(attrs: Any) -> tuple[dict[str, str], bool]:
    """
    Returns (user_text_dict, had_error).
    rhino3dm exposes GetUserStrings2() -> list of [key, value].
    """
    if attrs is None:
        return {}, False
    user_text: dict[str, str] = {}
    had_error = False
    try:
        pairs = attrs.GetUserStrings2()
        if pairs:
            for pair in pairs:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    user_text[str(pair[0])] = str(pair[1])
        if not user_text:
            tup = attrs.GetUserStrings()
            if tup:
                for item in tup:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        user_text[str(item[0])] = str(item[1])
    except Exception:
        had_error = True
    return user_text, had_error


def _geometry_bounding_box(geom: Any) -> dict[str, Any] | None:
    if geom is None:
        return None
    try:
        bb = geom.GetBoundingBox()
        if bb is None:
            return None
        if hasattr(bb, "IsValid") and not bb.IsValid:
            return None
        mn = [float(bb.Min.X), float(bb.Min.Y), float(bb.Min.Z)]
        mx = [float(bb.Max.X), float(bb.Max.Y), float(bb.Max.Z)]
        if any(mx[i] < mn[i] for i in range(3)):
            return None
        x0, y0, z0 = mn
        x1, y1, z1 = mx
        corners = [
            [x0, y0, z0],
            [x0, y0, z1],
            [x0, y1, z0],
            [x0, y1, z1],
            [x1, y0, z0],
            [x1, y0, z1],
            [x1, y1, z0],
            [x1, y1, z1],
        ]
        center = [(x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0]
        return {
            "bbox": {"min": mn, "max": mx},
            "bbox_corners": corners,
            "sample_points": [center, mn, mx],
            "source": "rhino3dm.GeometryBase.GetBoundingBox",
        }
    except Exception:
        return None


def _to_dict_from_rhino_object(
    file3dm: Any,
    rhino_obj: Any,
    group_index_to_name: dict[int, str],
    rhino3dm: Any,
) -> dict[str, Any]:
    attrs = getattr(rhino_obj, "Attributes", None)
    geom = getattr(rhino_obj, "Geometry", None)

    object_id = str(getattr(attrs, "ObjectId", "") or uuid4())
    raw_type = type(geom).__name__ if geom is not None else "UnknownGeometry"
    source_ref = str(getattr(attrs, "ObjectId", object_id))
    layer = ""
    extraction_warnings: list[str] = []

    try:
        layer_index = getattr(attrs, "LayerIndex", -1)
        if layer_index is not None and layer_index >= 0 and file3dm is not None:
            layer_obj = file3dm.Layers[layer_index]
            layer = str(getattr(layer_obj, "FullPath", "") or getattr(layer_obj, "Name", ""))
    except Exception:
        extraction_warnings.append("layer_lookup_failed")

    group_ids: list[str] = []
    group_names: list[str] = []
    try:
        group_list = attrs.GetGroupList() if attrs is not None else None
        indices: list[int] = []
        if group_list:
            for gid in group_list:
                try:
                    indices.append(int(gid))
                except (TypeError, ValueError):
                    continue
        for idx in sorted(set(indices)):
            group_ids.append(f"group_index:{idx}")
            gname = group_index_to_name.get(idx, "").strip()
            if gname:
                group_ids.append(f"group_name:{gname}")
                group_names.append(gname)
    except Exception:
        extraction_warnings.append("group_lookup_failed")

    user_text: dict[str, str] = {}
    if attrs is not None:
        user_text, user_text_read_failed = _read_user_text(attrs)
        declared_count = int(getattr(attrs, "UserStringCount", 0) or 0)
        if user_text_read_failed or (declared_count > 0 and not user_text):
            extraction_warnings.append("user_text_lookup_failed")

    raw_geometry_summary: dict[str, Any] | None = None
    is_instance = isinstance(geom, rhino3dm.InstanceReference) or "InstanceReference" in raw_type

    block_name: str | None = None
    instance_definition_id: str | None = None
    transform = _identity_transform()

    if is_instance and geom is not None:
        try:
            idef_id = geom.ParentIdefId
            instance_definition_id = str(idef_id)
            idef = _find_instance_definition(file3dm, idef_id)
            if idef is not None:
                block_name = str(idef.Name or "") or None
            else:
                block_name = None
            xf = _transform_to_list(geom.Xform)
            if xf:
                transform = xf
            else:
                extraction_warnings.append("instance_transform_not_resolved")
        except Exception:
            extraction_warnings.append("instance_reference_resolve_failed")
            block_name = None
        raw_geometry_summary = _geometry_bounding_box(geom)
        extraction_warnings.append("block_definition_not_expanded")
    else:
        if geom is not None:
            raw_geometry_summary = _geometry_bounding_box(geom)
        try:
            if attrs is not None:
                xf = _transform_to_list(attrs.Transform)
                if xf:
                    transform = xf
        except Exception:
            pass

    if raw_geometry_summary is None:
        raw_geometry_summary = {}
    if "bbox_corners" not in raw_geometry_summary:
        extraction_warnings.append("bbox_corners_not_available")

    return {
        "object_id": object_id,
        "source_system": "rhino",
        "source_ref": source_ref,
        "object_kind": "instance_reference" if is_instance else "geometric_object",
        "raw_type": raw_type,
        "layer": layer,
        "name": str(getattr(attrs, "Name", "") or ""),
        "group_ids": group_ids,
        "group_names": group_names,
        "block_context": {
            "is_block_instance": is_instance,
            "block_name": block_name,
            "instance_definition_id": instance_definition_id,
        },
        "user_text": user_text,
        "material": None,
        "transform": transform,
        "geometry_ref": f"rhino://{source_ref}",
        "raw_geometry_summary": raw_geometry_summary,
        "extraction_warnings": extraction_warnings,
    }


def _extract_from_rhino(path: Path) -> list[dict[str, Any]]:
    try:
        import rhino3dm  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "rhino3dm is required to read .3dm files. Install it or use a JSON fixture."
        ) from exc

    model = rhino3dm.File3dm.Read(str(path))
    if model is None:
        raise ValueError(f"Could not read Rhino file: {path}")

    group_index_to_name = _group_index_to_name(model)

    objects: list[dict[str, Any]] = []
    for rhino_obj in model.Objects:
        obj = _to_dict_from_rhino_object(model, rhino_obj, group_index_to_name, rhino3dm)
        validate_payload("object_schema.v1.json", obj)
        objects.append(obj)
    return objects


def _extract_objects_error(
    message: str,
    *,
    input_path_received: str | None,
    path_used: str | None,
) -> dict[str, Any]:
    return {
        "mcp_name": "rhino_bridge_client",
        "role": "extractor",
        "status": "error",
        "message": message,
        "expected_input_contract": "external.rhino_model_or_json_fixture",
        "output_contract": "object_schema.v1.json",
        "objects": [],
        "input_path_received": input_path_received,
        "path_used": path_used,
    }


def _extract_from_local_path(input_path: str | None) -> list[dict[str, Any]]:
    if input_path is None or not str(input_path).strip():
        raise ValueError("Missing required payload key: input_path")
    raw = str(input_path).strip()
    path = Path(raw).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _extract_from_json(path)
    if suffix == ".3dm":
        return _extract_from_rhino(path)
    raise ValueError("Unsupported input file extension. Use .json or .3dm")


def extract_objects(payload: dict[str, Any]) -> dict[str, Any]:
    input_path = payload.get("input_path")
    input_path_received = str(input_path) if input_path is not None else None
    raw = str(input_path).strip() if input_path is not None else None
    path_used: str | None = None
    if raw:
        path = Path(raw).expanduser()
        try:
            path_used = str(path.resolve())
        except OSError:
            path_used = str(path)
    logger.info("rhino_bridge_client: input_path received=%r path_used=%r", raw, path_used)
    try:
        objects, backend_mode, backend_warnings = extract_objects_via_backend(raw, _extract_from_local_path)
    except Exception as exc:
        return _extract_objects_error(
            str(exc),
            input_path_received=raw,
            path_used=path_used,
        )

    return {
        "mcp_name": "rhino_bridge_client",
        "role": "extractor",
        "status": "ok",
        "message": f"Extracted {len(objects)} normalized objects via {backend_mode}.",
        "expected_input_contract": "external.rhino_model_or_json_fixture",
        "output_contract": "object_schema.v1.json",
        "objects": objects,
        "backend_mode": backend_mode,
        "backend_warnings": backend_warnings,
    }
