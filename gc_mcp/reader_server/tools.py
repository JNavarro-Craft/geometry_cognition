from __future__ import annotations

from typing import Any

from gc_mcp.reader_server.loaders import OutputsLoader, structured_file_not_found


_LOADER = OutputsLoader()


def _load_required(filename: str) -> tuple[Any | None, dict[str, str] | None]:
    return _LOADER.load_json(filename)


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
    hypotheses, err = _load_hypotheses()
    if err:
        return err
    evidence_graph, err = _load_evidence_graph()
    if err:
        return err

    if not isinstance(objects, list):
        objects = []
    evidence_items = evidence_graph.get("evidence_items", []) if isinstance(evidence_graph, dict) else []
    if not isinstance(evidence_items, list):
        evidence_items = []

    breakdown = {"candidate": 0, "measured": 0, "confirmed": 0, "unknown": 0}
    for rel in relations or []:
        level = str(rel.get("assertion_level", "unknown")).lower()
        if level in breakdown:
            breakdown[level] += 1
        else:
            breakdown["unknown"] += 1

    return {
        "total_objects": len(objects),
        "total_relations": len(relations or []),
        "relations_by_assertion_level": breakdown,
        "total_hypotheses": len(hypotheses or []),
        "total_evidence_items": len(evidence_items),
    }


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
        return err
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
        return {"available": False, "reason": "no reasoning output found"}
    return {"available": True, "reasoning_output": data}

