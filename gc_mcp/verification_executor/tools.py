from __future__ import annotations

import copy
import json
from typing import Any
from urllib import error, request


FORBIDDEN_TERMS = {"beam", "panel", "stud", "track", "diagonal", "connector", "truss", "sip"}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _post_verify_relations(bridge_base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = bridge_base_url.rstrip("/")
    url = f"{base}/geometry/verify_relations"
    raw = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"bridge verification request failed: {exc}") from exc


def execute_verification_plan(payload: dict[str, Any]) -> dict[str, Any]:
    verification_plan = payload.get("verification_plan", [])
    relations = payload.get("relations", [])
    bridge_base_url = str(payload.get("bridge_base_url", "http://127.0.0.1:8765"))
    max_items = int(payload.get("max_items", 5))
    linear_tolerance = float(payload.get("linear_tolerance", 0.05))
    angular_tolerance = float(payload.get("angular_tolerance", 2.0))

    if not isinstance(verification_plan, list):
        verification_plan = []
    if not isinstance(relations, list):
        relations = []
    max_items = max(0, max_items)

    updated_relations = copy.deepcopy(relations)
    rel_by_id: dict[str, dict[str, Any]] = {
        str(rel.get("relation_id", "")): rel for rel in updated_relations if isinstance(rel, dict)
    }

    selected = [x for x in verification_plan if isinstance(x, dict)][:max_items]
    verify_inputs: list[dict[str, str]] = []
    for item in selected:
        rel_id = str(item.get("relation_id", ""))
        rel = rel_by_id.get(rel_id)
        if not rel:
            continue
        verify_inputs.append(
            {
                "relation_id": rel_id,
                "subject_id": str(rel.get("subject_id", "")),
                "object_id": str(rel.get("object_id", "")),
                "check": str(item.get("recommended_check", "tolerance_review")),
            }
        )

    bridge_payload = {
        "relations": verify_inputs,
        "tolerance": {
            "linear_tolerance": linear_tolerance,
            "angular_tolerance": angular_tolerance,
            "unit_system": "model_unit",
        },
    }

    try:
        bridge_response = _post_verify_relations(bridge_base_url, bridge_payload)
    except RuntimeError as exc:
        return {
            "status": "error",
            "message": str(exc),
            "executed": 0,
            "verification_results": [],
            "updated_relations": updated_relations,
        }

    verification_results = bridge_response.get("results", [])
    if not isinstance(verification_results, list):
        verification_results = []

    for result in verification_results:
        if not isinstance(result, dict):
            continue
        rel_id = str(result.get("relation_id", ""))
        rel = rel_by_id.get(rel_id)
        if not rel:
            continue

        v_status = str(result.get("verification_status", ""))
        v_level = str(result.get("assertion_level", ""))
        method = str(result.get("method", ""))
        measurements = result.get("measurements", {})
        confidence = float(result.get("confidence", 0.0))

        limitations = [str(x) for x in rel.get("limitations", [])] if isinstance(rel.get("limitations"), list) else []
        limitations = [x for x in limitations if x != "verification_inconclusive"]

        if v_status == "verified" and v_level == "confirmed":
            rel["assertion_level"] = "confirmed"
            rel["verification_status"] = "verified"
            rel["measurement_method"] = method or str(rel.get("measurement_method", ""))
            rel["verification_required"] = []
            limitations = [x for x in limitations if x != "candidate_relation"]
            limitations = [x for x in limitations if x != "candidate_relation_contradicted_by_verification"]
        elif v_status == "contradicted":
            rel["verification_status"] = "contradicted"
            rel["assertion_level"] = "measured"
            limitations.append("candidate_relation_contradicted_by_verification")
        elif v_status == "inconclusive":
            rel["verification_status"] = "inconclusive"
            limitations.append("verification_inconclusive")

        rel["limitations"] = _dedupe(limitations)
        rel["verification_result"] = {
            "method": method,
            "measurements": measurements if isinstance(measurements, dict) else {},
            "confidence": max(0.0, min(1.0, confidence)),
            "source": "rhino_bridge",
        }

    # Post-verification minimal consistency pass:
    # 1) intersects confirmed dominates touches confirmed for same pair
    # 2) only one confirmed relation survives per (subject_id, object_id, predicate)
    def _pair_key(rel: dict[str, Any]) -> tuple[str, str]:
        return (str(rel.get("subject_id", "")), str(rel.get("object_id", "")))

    def _triple_key(rel: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(rel.get("subject_id", "")),
            str(rel.get("object_id", "")),
            str(rel.get("predicate", "")),
        )

    confirmed_intersects_pairs: set[tuple[str, str]] = set()
    for rel in updated_relations:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("assertion_level", "")) == "confirmed" and str(rel.get("predicate", "")) == "intersects":
            confirmed_intersects_pairs.add(_pair_key(rel))

    # Demote touches confirmed when intersects confirmed exists for same pair.
    for rel in updated_relations:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("assertion_level", "")) != "confirmed":
            continue
        if str(rel.get("predicate", "")) != "touches":
            continue
        if _pair_key(rel) in confirmed_intersects_pairs:
            rel["assertion_level"] = "measured"
            rel["verification_status"] = "partially_verified"
            limits = [str(x) for x in rel.get("limitations", [])] if isinstance(rel.get("limitations"), list) else []
            limits.append("subordinated_to_confirmed_intersection")
            rel["limitations"] = _dedupe(limits)

    # Consolidate duplicates: only one confirmed survives per (subject_id, object_id, predicate).
    seen_confirmed: dict[tuple[str, str, str], bool] = {}
    for rel in updated_relations:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("assertion_level", "")) != "confirmed":
            continue
        key = _triple_key(rel)
        if key not in seen_confirmed:
            seen_confirmed[key] = True
            continue
        # Demote redundant confirmed relation
        rel["assertion_level"] = "measured"
        rel["verification_status"] = "partially_verified"
        limits = [str(x) for x in rel.get("limitations", [])] if isinstance(rel.get("limitations"), list) else []
        limits.append("redundant_confirmed_relation_consolidated")
        rel["limitations"] = _dedupe(limits)

    # Guardrail: avoid constructive vocabulary in output text fields.
    for rel in updated_relations:
        if not isinstance(rel, dict):
            continue
        for field in ("assertion_level", "verification_status", "measurement_method"):
            text = str(rel.get(field, "")).lower()
            if any(term in text for term in FORBIDDEN_TERMS):
                rel[field] = ""

    return {
        "status": "ok",
        "executed": len(verify_inputs),
        "verification_results": verification_results,
        "updated_relations": updated_relations,
    }

