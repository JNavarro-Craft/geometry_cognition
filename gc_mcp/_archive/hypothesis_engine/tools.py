from __future__ import annotations

from typing import Any

from shared.contracts import validate_payload


ALLOWED_LABELS = {
    "morphological_pattern",
    "relational_pattern",
    "repeated_linear_pattern",
    "plate_like_cluster",
    "compact_cluster",
    "ambiguous_entity",
    "insufficient_evidence",
}

FORBIDDEN_TERMS = {"panel", "beam", "truss", "sip", "connector", "wood", "steel"}


def _entity_id_from_entity(ent: dict[str, Any]) -> str:
    """Must equal entities[].entity_id from geometry_kernel / entity_schema (no shortening)."""
    raw = ent["entity_id"]
    if isinstance(raw, str):
        return raw
    return str(raw)


def _dedupe_preserve_order(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _supporting_evidence_ids_for_entity(
    entity_id: str,
    members: set[str],
    relations: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    """
    Assemble official evidence_id values emitted by evidence_graph (no name/fuzzy heuristics):
    - ev-ent-{entity_id} from entity item
    - ev-geom-{object_id} for each object_id in member_object_ids
    - ev-rel-{relation_id} when the relation's subject_id or object_id is in that member set
    """
    ordered: list[str] = []

    ent_id = f"ev-ent-{entity_id}"
    if ent_id in evidence_by_id:
        ordered.append(ent_id)

    for m in sorted(members):
        gid = f"ev-geom-{m}"
        if gid in evidence_by_id:
            ordered.append(gid)

    for rel in sorted(relations, key=lambda r: str(r.get("relation_id", ""))):
        sub = str(rel.get("subject_id", ""))
        obj = str(rel.get("object_id", ""))
        if sub not in members and obj not in members:
            continue
        rid = str(rel.get("relation_id", ""))
        rel_eid = f"ev-rel-{rid}"
        if rel_eid in evidence_by_id:
            ordered.append(rel_eid)

    # Fallback by evidence index when relation list is absent/incomplete but evidence exists.
    # Keep this observational: match by source_object_ids/member ids and entity-level id.
    for eid, ev in evidence_by_id.items():
        if not isinstance(ev, dict):
            continue
        source_ids = {str(x) for x in ev.get("source_object_ids", []) if str(x)}
        if eid.startswith("ev-ent-") and eid.endswith(entity_id):
            ordered.append(eid)
            continue
        if eid.startswith("ev-geom-") and source_ids.intersection(members):
            ordered.append(eid)
            continue
        if eid.startswith("ev-rel-") and source_ids.intersection(members):
            ordered.append(eid)

    return _dedupe_preserve_order(ordered)


def _contains_forbidden_term(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in FORBIDDEN_TERMS)


def _relation_evidence_weight(ev: dict[str, Any]) -> float:
    observed = ev.get("observed_value", {})
    if isinstance(observed, dict):
        level = str(observed.get("assertion_level", "candidate"))
    else:
        level = "candidate"
    if level == "confirmed":
        return 1.0
    if level == "measured":
        return 0.65
    return 0.35


def _requires_verified_interaction(ev: dict[str, Any]) -> bool:
    observed = ev.get("observed_value", {})
    assertion_level = ""
    verification_status = ""
    verification_required: list[Any] = []
    if isinstance(observed, dict):
        assertion_level = str(observed.get("assertion_level", ""))
        verification_status = str(observed.get("verification_status", ""))
        raw_req = observed.get("verification_required", [])
        if isinstance(raw_req, list):
            verification_required = raw_req
    if assertion_level and assertion_level != "confirmed":
        return True
    if verification_status and verification_status != "verified":
        return True
    return len(verification_required) > 0


def _pending_checks(ev: dict[str, Any]) -> list[str]:
    observed = ev.get("observed_value", {})
    if not isinstance(observed, dict):
        return []
    raw_req = observed.get("verification_required", [])
    if not isinstance(raw_req, list):
        return []
    checks: list[str] = []
    for item in raw_req:
        check = str(item).strip()
        if check:
            checks.append(check)
    return checks


def _build_hypothesis(
    hypothesis_id: str,
    entity_id: str,
    label: str,
    level: str,
    confidence: float,
    supporting_evidence: list[str],
    contradicting_evidence: list[str],
    alternatives: list[str],
    missing_information: list[str],
    status: str,
) -> dict[str, Any]:
    if label not in ALLOWED_LABELS:
        label = "ambiguous_entity"
    if _contains_forbidden_term(label):
        label = "ambiguous_entity"
    item = {
        "hypothesis_id": hypothesis_id,
        "entity_id": entity_id,
        "hypothesis_label": label,
        "hypothesis_level": level,
        "confidence": max(0.0, min(1.0, confidence)),
        "supporting_evidence": supporting_evidence,
        "contradicting_evidence": contradicting_evidence,
        "alternatives": alternatives,
        "missing_information": missing_information,
        "status": status,
    }
    validate_payload("hypothesis_schema.v1.json", item)
    return item


def generate_hypotheses(payload: dict[str, Any]) -> dict[str, Any]:
    evidence_items = payload.get("evidence_items", [])
    evidence_graph = payload.get("evidence_graph", {})
    if (not isinstance(evidence_items, list) or len(evidence_items) == 0) and isinstance(evidence_graph, dict):
        nested = evidence_graph.get("evidence_items", [])
        if isinstance(nested, list):
            evidence_items = nested
    entities = payload.get("entities", [])
    relations = payload.get("relations", [])
    warnings: list[str] = []
    if not isinstance(relations, list):
        relations = []
    if not isinstance(evidence_items, list):
        evidence_items = []
    if not isinstance(entities, list):
        entities = []

    if not evidence_items:
        warnings.append("missing_evidence_items_input")
    if not entities:
        warnings.append("missing_entities_input")

    evidence_by_id: dict[str, dict[str, Any]] = {str(item["evidence_id"]): item for item in evidence_items}

    hypotheses: list[dict[str, Any]] = []
    sequence = 1
    for ent in entities:
        entity_id = _entity_id_from_entity(ent)
        members = {str(x) for x in ent.get("member_object_ids", [])}

        supporting_ids = _supporting_evidence_ids_for_entity(
            entity_id,
            members,
            relations,
            evidence_by_id,
        )

        unique_relevant = {eid: evidence_by_id[eid] for eid in supporting_ids if eid in evidence_by_id}
        avg_conf = (
            sum(float(ev.get("confidence", 0.0)) for ev in unique_relevant.values()) / len(unique_relevant)
            if unique_relevant
            else 0.0
        )

        if not supporting_ids:
            hypotheses.append(
                _build_hypothesis(
                    hypothesis_id=f"hyp-{sequence:04d}",
                    entity_id=entity_id,
                    label="insufficient_evidence",
                    level="relational",
                    confidence=0.15,
                    supporting_evidence=[],
                    contradicting_evidence=[],
                    alternatives=["ambiguous_entity"],
                    missing_information=["insufficient relational evidence", "additional spatial relationships required"],
                    status="candidate",
                )
            )
            sequence += 1
            continue

        label = "ambiguous_entity"
        level = "relational"
        alternatives = ["insufficient_evidence"]
        missing_information: list[str] = []
        status = "candidate"
        confidence = min(0.85, max(0.2, avg_conf))

        has_geom = any(ev.get("evidence_type") == "geometry" for ev in unique_relevant.values())
        has_relation = any(ev.get("evidence_type") == "relation" for ev in unique_relevant.values())
        relation_evidence = [ev for ev in unique_relevant.values() if ev.get("evidence_type") == "relation"]

        morph_values = [
            str(ev.get("observed_value", {}).get("morphology", ""))
            for ev in unique_relevant.values()
            if isinstance(ev.get("observed_value"), dict)
        ]
        predicates = [
            str(ev.get("observed_value", {}).get("predicate", ""))
            for ev in unique_relevant.values()
            if isinstance(ev.get("observed_value"), dict)
        ]

        if has_geom and "linear_prismatic" in morph_values:
            label = "repeated_linear_pattern" if "repeated_with" in predicates else "morphological_pattern"
            level = "morphological"
            alternatives = ["relational_pattern", "ambiguous_entity"]
        elif has_geom and ("thin_plate" in morph_values or "planar_surface" in morph_values):
            label = "plate_like_cluster"
            level = "morphological"
            alternatives = ["morphological_pattern", "ambiguous_entity"]
        elif has_geom and "compact_solid" in morph_values:
            label = "compact_cluster"
            level = "morphological"
            alternatives = ["morphological_pattern", "ambiguous_entity"]
        elif has_relation:
            label = "relational_pattern"
            level = "relational"
            alternatives = ["ambiguous_entity"]
        else:
            missing_information = ["clear_morphology_or_relation_pattern"]

        # Relational consistency weighting: confirmed > measured > candidate.
        if relation_evidence:
            rel_weights = [_relation_evidence_weight(ev) for ev in relation_evidence]
            rel_strength = sum(rel_weights) / len(rel_weights)
            confidence = min(0.9, confidence * 0.75 + rel_strength * 0.25)
            if len(relation_evidence) >= 2 and rel_strength >= 0.6:
                confidence = min(0.92, confidence + 0.04)
            if rel_strength <= 0.4:
                if "verified geometric interaction required" not in missing_information:
                    missing_information.append("verified geometric interaction required")
        requires_verified_interaction = any(_requires_verified_interaction(ev) for ev in relation_evidence)
        pending_checks: list[str] = []
        for ev in relation_evidence:
            pending_checks.extend(_pending_checks(ev))

        evidence_incomplete = not has_relation
        if confidence < 0.35:
            label = "insufficient_evidence"
            alternatives = ["ambiguous_entity"]
            missing_information = ["insufficient relational evidence", "additional spatial relationships required"]
        elif confidence < 0.5:
            label = "ambiguous_entity"
            missing_information = ["insufficient relational evidence", "additional spatial relationships required"]
        elif evidence_incomplete and len(missing_information) == 0:
            missing_information = ["insufficient relational evidence", "additional spatial relationships required"]
        elif confidence >= 0.7:
            status = "supported"
        if requires_verified_interaction and "verified geometric interaction required" not in missing_information:
            missing_information.append("verified geometric interaction required")
        for check in _dedupe_preserve_order(pending_checks):
            pending_entry = f"pending: {check}"
            if pending_entry not in missing_information:
                missing_information.append(pending_entry)

        hypothesis = _build_hypothesis(
            hypothesis_id=f"hyp-{sequence:04d}",
            entity_id=entity_id,
            label=label,
            level=level,
            confidence=confidence,
            supporting_evidence=supporting_ids,
            contradicting_evidence=[],
            alternatives=alternatives,
            missing_information=missing_information,
            status=status,
        )
        hypotheses.append(hypothesis)
        sequence += 1

    return {
        "mcp_name": "hypothesis_engine",
        "role": "hypothesis",
        "status": "ok",
        "message": (
            f"Generated {len(hypotheses)} abstract hypotheses from evidence."
            if not warnings
            else f"Generated {len(hypotheses)} abstract hypotheses with input warnings: {', '.join(warnings)}."
        ),
        "expected_input_contract": "evidence_schema.v1.json + entities + relations (optional, from same pipeline as evidence_graph)",
        "output_contract": "hypothesis_schema.v1.json",
        "hypotheses": hypotheses,
        "evidence_index": list(evidence_by_id.keys()),
        "warnings": warnings,
    }
