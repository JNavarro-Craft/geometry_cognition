from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from shared.contracts import validate_payload


ALLOWED_MORPHOLOGIES = {
    "unknown",
    "linear_prismatic",
    "thin_plate",
    "compact_solid",
    "planar_surface",
    "irregular_solid",
}


def _translation_from_transform(transform: list[float]) -> list[float]:
    if len(transform) != 16:
        return [0.0, 0.0, 0.0]
    return [float(transform[3]), float(transform[7]), float(transform[11])]


def _base_dimensions(obj: dict[str, Any]) -> list[float]:
    raw_type = str(obj.get("raw_type", "")).lower()
    object_kind = str(obj.get("object_kind", "")).lower()
    if "curve" in raw_type:
        return [2.0, 0.2, 0.2]
    if "surface" in raw_type or "surface" in object_kind:
        return [2.0, 2.0, 0.08]
    return [1.0, 1.0, 1.0]


def _axis_aligned_bbox_from_extractor(obj: dict[str, Any]) -> tuple[list[float], list[float], list[float], list[float]] | None:
    """
    If object_schema.raw_geometry_summary.bbox is present and valid, returns
    (bbox_min, bbox_max, extents_xyz, centroid). Otherwise None.
    """
    rgs = obj.get("raw_geometry_summary")
    if not isinstance(rgs, dict):
        return None
    bb = rgs.get("bbox")
    if not isinstance(bb, dict):
        return None
    mn = bb.get("min")
    mx = bb.get("max")
    if not isinstance(mn, list) or not isinstance(mx, list) or len(mn) != 3 or len(mx) != 3:
        return None
    try:
        bbox_min = [float(mn[i]) for i in range(3)]
        bbox_max = [float(mx[i]) for i in range(3)]
    except (TypeError, ValueError):
        return None
    if any(bbox_max[i] < bbox_min[i] for i in range(3)):
        return None
    extents = [max(0.0, bbox_max[i] - bbox_min[i]) for i in range(3)]
    if max(extents) <= 1e-12:
        return None
    centroid = [(bbox_min[i] + bbox_max[i]) / 2.0 for i in range(3)]
    return bbox_min, bbox_max, extents, centroid


def _compute_morphology(dimensions: list[float], raw_type: str) -> tuple[str, float]:
    d1, d2, d3 = sorted(dimensions, reverse=True)
    min_dim = max(min(dimensions), 1e-6)

    if "surface" in raw_type.lower():
        return "planar_surface", 0.75
    if d1 >= 4.0 * max(d2, d3):
        return "linear_prismatic", 0.8
    if d3 <= 0.08 * d1:
        return "thin_plate", 0.8
    if d1 / min_dim <= 1.5:
        return "compact_solid", 0.7
    if d1 / min_dim > 1.5:
        return "irregular_solid", 0.65
    return "unknown", 0.5


def _dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _norm(v: list[float]) -> float:
    return math.sqrt(max(0.0, _dot(v, v)))


def _normalize(v: list[float]) -> list[float]:
    n = _norm(v)
    if n <= 1e-12:
        return [0.0, 0.0, 0.0]
    return [v[0] / n, v[1] / n, v[2] / n]


def _mat_vec(m: list[list[float]], v: list[float]) -> list[float]:
    return [
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    ]


def _power_iteration_symmetric(m: list[list[float]], seed: list[float]) -> tuple[float, list[float]]:
    v = _normalize(seed)
    if _norm(v) <= 1e-12:
        v = [1.0, 0.0, 0.0]
    for _ in range(24):
        mv = _mat_vec(m, v)
        if _norm(mv) <= 1e-12:
            break
        v = _normalize(mv)
    lam = _dot(v, _mat_vec(m, v))
    return lam, v


def _extract_point_cloud_for_obb(obj: dict[str, Any]) -> tuple[list[list[float]], str | None]:
    rgs = obj.get("raw_geometry_summary")
    if not isinstance(rgs, dict):
        return [], None

    def _parse_points(raw: Any) -> list[list[float]]:
        pts: list[list[float]] = []
        if not isinstance(raw, list):
            return pts
        for p in raw:
            if not isinstance(p, list) or len(p) != 3:
                continue
            try:
                pts.append([float(p[0]), float(p[1]), float(p[2])])
            except (TypeError, ValueError):
                continue
        return pts

    corners = _parse_points(rgs.get("bbox_corners"))
    if len(corners) >= 4:
        return corners, "bbox_corners"
    samples = _parse_points(rgs.get("sample_points"))
    if len(samples) >= 3:
        return samples, "sample_points"
    return [], None


def _oriented_bbox_from_points_pca(points: list[list[float]]) -> dict[str, Any] | None:
    if len(points) < 3:
        return None
    center = [
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
        sum(p[2] for p in points) / len(points),
    ]
    centered = [[p[0] - center[0], p[1] - center[1], p[2] - center[2]] for p in points]

    cov = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    inv_n = 1.0 / max(1, len(centered))
    for p in centered:
        cov[0][0] += p[0] * p[0]
        cov[0][1] += p[0] * p[1]
        cov[0][2] += p[0] * p[2]
        cov[1][0] += p[1] * p[0]
        cov[1][1] += p[1] * p[1]
        cov[1][2] += p[1] * p[2]
        cov[2][0] += p[2] * p[0]
        cov[2][1] += p[2] * p[1]
        cov[2][2] += p[2] * p[2]
    cov = [[cov[r][c] * inv_n for c in range(3)] for r in range(3)]

    lam1, e1 = _power_iteration_symmetric(cov, [1.0, 0.0, 0.0])
    c2 = [
        [cov[r][c] - lam1 * e1[r] * e1[c] for c in range(3)]
        for r in range(3)
    ]
    _, e2_raw = _power_iteration_symmetric(c2, [0.0, 1.0, 0.0])
    e2 = _normalize([e2_raw[i] - _dot(e2_raw, e1) * e1[i] for i in range(3)])
    if _norm(e2) <= 1e-8:
        e2 = _normalize(_cross(e1, [0.0, 0.0, 1.0]))
        if _norm(e2) <= 1e-8:
            e2 = _normalize(_cross(e1, [0.0, 1.0, 0.0]))
    e3 = _normalize(_cross(e1, e2))
    if _norm(e3) <= 1e-8:
        e1, e2, e3 = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]

    axes = [e1, e2, e3]
    extents: list[float] = []
    for axis in axes:
        projections = [_dot(p, axis) for p in centered]
        extents.append(max(projections) - min(projections))

    return {
        "center": [float(center[0]), float(center[1]), float(center[2])],
        "axes": [[float(c) for c in ax] for ax in axes],
        "extents": [float(extents[0]), float(extents[1]), float(extents[2])],
    }


def _oriented_bbox_approximation(
    center: list[float],
    dims: list[float],
    transform: Any,
) -> dict[str, Any]:
    """
    First-step OBB approximation from current proxy geometry:
    - center from current feature center
    - extents from current principal dimensions
    - axes from transform basis (fallback identity)
    """
    axes = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    if isinstance(transform, list) and len(transform) == 16:
        candidate_axes = [
            [float(transform[0]), float(transform[1]), float(transform[2])],
            [float(transform[4]), float(transform[5]), float(transform[6])],
            [float(transform[8]), float(transform[9]), float(transform[10])],
        ]

        norm_axes: list[list[float]] = []
        for axis in candidate_axes:
            n = math.sqrt(sum(c * c for c in axis))
            if n <= 1e-12:
                norm_axes.append([1.0, 0.0, 0.0])
            else:
                norm_axes.append([axis[0] / n, axis[1] / n, axis[2] / n])
        axes = norm_axes

    return {
        "center": [float(center[0]), float(center[1]), float(center[2])],
        "axes": axes,
        "extents": [float(dims[0]), float(dims[1]), float(dims[2])],
    }


def _build_geometry(obj: dict[str, Any]) -> dict[str, Any]:
    object_id = str(obj["object_id"])
    transform = obj.get("transform", [0.0] * 16)
    geometric_warnings: list[str] = []
    derived_from: list[str] = [object_id]

    extracted = _axis_aligned_bbox_from_extractor(obj)
    if extracted is not None:
        bbox_min, bbox_max, dims, center = extracted
        geometric_warnings.append("geometry_derived_from_extractor_bbox")
        derived_from.append("object_schema.raw_geometry_summary.bbox")
    else:
        center = _translation_from_transform(transform)
        dims = _base_dimensions(obj)
        half = [d / 2.0 for d in dims]
        bbox_min = [center[i] - half[i] for i in range(3)]
        bbox_max = [center[i] + half[i] for i in range(3)]
        geometric_warnings.append("geometry_used_proxy_extents")

    xy = dims[0] / max(dims[1], 1e-6)
    xz = dims[0] / max(dims[2], 1e-6)
    yz = dims[1] / max(dims[2], 1e-6)
    morphology, morphology_confidence = _compute_morphology(dims, str(obj.get("raw_type", "")))
    if morphology not in ALLOWED_MORPHOLOGIES:
        morphology = "unknown"
        morphology_confidence = 0.5

    area = 2.0 * (dims[0] * dims[1] + dims[0] * dims[2] + dims[1] * dims[2])
    volume = dims[0] * dims[1] * dims[2]
    points, point_source = _extract_point_cloud_for_obb(obj)
    oriented_bbox = _oriented_bbox_from_points_pca(points) if points else None
    if oriented_bbox is not None and point_source == "bbox_corners":
        geometric_warnings.append("oriented_bbox_pca_from_bbox_corners")
    elif oriented_bbox is not None and point_source == "sample_points":
        geometric_warnings.append("oriented_bbox_pca_from_sample_points")
    else:
        oriented_bbox = _oriented_bbox_approximation(center=center, dims=dims, transform=transform)
        geometric_warnings.append("oriented_bbox_approximation")

    feature = {
        "object_id": object_id,
        "bbox": {"min": bbox_min, "max": bbox_max},
        "centroid": center,
        "volume": volume,
        "area": area,
        "principal_dimensions": dims,
        "aspect_ratios": {"xy": xy, "xz": xz, "yz": yz},
        "local_frame": {
            "origin": center,
            "x_axis": [1.0, 0.0, 0.0],
            "y_axis": [0.0, 1.0, 0.0],
            "z_axis": [0.0, 0.0, 1.0],
        },
        "morphology": morphology,
        "morphology_confidence": morphology_confidence,
        "geometric_warnings": geometric_warnings,
        "derived_from": derived_from,
        "oriented_bbox": oriented_bbox,
    }
    validate_payload("geometry_schema.v2.json", feature)
    return feature


def _build_entities(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for obj in objects:
        object_id = str(obj["object_id"])
        source_ref = str(obj.get("source_ref", object_id))
        entities.append(
            {
                "entity_id": f"ent-src-{object_id}",
                "entity_type": "source_object",
                "member_object_ids": [object_id],
                "source_refs": [source_ref],
                "formation_method": "direct_extraction",
                "confidence": 1.0,
                "observation_refs": [f"obs:extract:{object_id}"],
                "limitations": [],
                "warnings": [],
                "status": "observed",
                "notes": ["Direct entity mapped from normalized object."],
            }
        )

        block_context = obj.get("block_context", {})
        if block_context.get("is_block_instance"):
            entities.append(
                {
                    "entity_id": f"ent-block-{object_id}",
                    "entity_type": "block_instance",
                    "member_object_ids": [object_id],
                    "source_refs": [source_ref, f"block:{block_context.get('block_name') or 'unknown'}"],
                    "formation_method": "block_context_inference",
                    "confidence": 0.9,
                    "observation_refs": [f"obs:block:{object_id}"],
                    "limitations": ["block_definition_not_expanded"],
                    "warnings": [],
                    "status": "observed",
                    "notes": ["Block instance entity from extractor context."],
                }
            )

    validate_entities = entities.copy()
    for ent in validate_entities:
        validate_payload("entity_schema.v1.json", ent)
    return entities


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _relation_payload(
    relation_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    relation_type: str,
    directionality: str,
    confidence: float,
    observation_refs: list[str],
    limitations: list[str],
    derived_from: list[str],
) -> dict[str, Any]:
    rel = {
        "relation_id": relation_id,
        "subject_id": subject_id,
        "predicate": predicate,
        "object_id": object_id,
        "relation_type": relation_type,
        "directionality": directionality,
        "confidence": confidence,
        "tolerance_context": {
            "linear_tolerance": 0.05,
            "angular_tolerance": 2.0,
            "unit_system": "model_unit",
        },
        "observation_refs": observation_refs,
        "limitations": limitations,
        "derived_from": derived_from,
    }
    validate_payload("relations_schema.v1.json", rel)
    return rel


def _build_relations(objects: list[dict[str, Any]], features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    feature_by_object = {item["object_id"]: item for item in features}

    relation_idx = 1
    for a, b in combinations(objects, 2):
        a_id = str(a["object_id"])
        b_id = str(b["object_id"])
        a_center = feature_by_object[a_id]["centroid"]
        b_center = feature_by_object[b_id]["centroid"]
        d = _distance(a_center, b_center)

        if d <= 3.0:
            relations.append(
                _relation_payload(
                    relation_id=f"rel-near-{relation_idx}",
                    subject_id=a_id,
                    predicate="near",
                    object_id=b_id,
                    relation_type="spatial",
                    directionality="symmetric",
                    confidence=0.8,
                    observation_refs=[f"obs:distance:{a_id}:{b_id}"],
                    limitations=["threshold_dependent"],
                    derived_from=["geometry_schema.v1.json"],
                )
            )
            relation_idx += 1

        a_dims = feature_by_object[a_id]["principal_dimensions"]
        b_dims = feature_by_object[b_id]["principal_dimensions"]
        if abs(max(a_dims) - max(b_dims)) <= 0.5:
            relations.append(
                _relation_payload(
                    relation_id=f"rel-aligned-{relation_idx}",
                    subject_id=a_id,
                    predicate="aligned_with",
                    object_id=b_id,
                    relation_type="spatial",
                    directionality="symmetric",
                    confidence=0.7,
                    observation_refs=[f"obs:principal-axis:{a_id}:{b_id}"],
                    limitations=["principal_axis_proxy"],
                    derived_from=["geometry_schema.v1.json"],
                )
            )
            relation_idx += 1
            relations.append(
                _relation_payload(
                    relation_id=f"rel-parallel-{relation_idx}",
                    subject_id=a_id,
                    predicate="parallel_to",
                    object_id=b_id,
                    relation_type="spatial",
                    directionality="symmetric",
                    confidence=0.7,
                    observation_refs=[f"obs:axis-orientation:{a_id}:{b_id}"],
                    limitations=["axis_orientation_proxy"],
                    derived_from=["geometry_schema.v1.json"],
                )
            )
            relation_idx += 1

        groups_a = set(a.get("group_ids", []))
        groups_b = set(b.get("group_ids", []))
        if groups_a and groups_b and groups_a.intersection(groups_b):
            relations.append(
                _relation_payload(
                    relation_id=f"rel-grouped-{relation_idx}",
                    subject_id=a_id,
                    predicate="grouped_with",
                    object_id=b_id,
                    relation_type="organizational",
                    directionality="symmetric",
                    confidence=0.9,
                    observation_refs=[f"obs:group-overlap:{a_id}:{b_id}"],
                    limitations=["declared_grouping_only"],
                    derived_from=["object_schema.v1.json"],
                )
            )
            relation_idx += 1

        a_block = a.get("block_context", {})
        b_block = b.get("block_context", {})
        if a_block.get("is_block_instance") and b_block.get("is_block_instance"):
            if a_block.get("block_name") and a_block.get("block_name") == b_block.get("block_name"):
                relations.append(
                    _relation_payload(
                        relation_id=f"rel-instanced-{relation_idx}",
                        subject_id=a_id,
                        predicate="instanced_with",
                        object_id=b_id,
                        relation_type="organizational",
                        directionality="symmetric",
                        confidence=0.9,
                        observation_refs=[f"obs:block-name:{a_id}:{b_id}"],
                        limitations=["depends_on_extractor_block_context"],
                        derived_from=["object_schema.v1.json"],
                    )
                )
                relation_idx += 1

    return relations


def compute_geometry_features(payload: dict[str, Any]) -> dict[str, Any]:
    objects = payload.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError("payload.objects must be a list of normalized objects")

    for obj in objects:
        validate_payload("object_schema.v1.json", obj)

    geometry_features = [_build_geometry(obj) for obj in objects]
    entities = _build_entities(objects)
    relations = _build_relations(objects, geometry_features)

    return {
        "mcp_name": "geometry_kernel",
        "role": "kernel",
        "status": "ok",
        "message": f"Processed {len(objects)} objects into geometry/entities/relations.",
        "expected_input_contract": "object_schema.v1.json",
        "output_contract": [
            "geometry_schema.v2.json",
            "entity_schema.v1.json",
            "relations_schema.v1.json",
        ],
        "geometry_features": geometry_features,
        "entities": entities,
        "relations": relations,
    }
