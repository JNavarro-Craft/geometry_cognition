from __future__ import annotations

from typing import Any


FORBIDDEN_TERMS = {"beam", "panel", "stud", "track", "diagonal", "connector", "truss", "sip"}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _relation_supported_by_hypothesis(
    relation_id: str,
    hypotheses: list[dict[str, Any]],
) -> tuple[bool, int]:
    evidence_id = f"ev-rel-{relation_id}"
    hits = 0
    for hyp in hypotheses:
        supporting = {str(x) for x in _safe_list(hyp.get("supporting_evidence"))}
        if evidence_id in supporting:
            hits += 1
    return hits > 0, hits


def _entity_membership_from_evidence(evidence_items: list[dict[str, Any]]) -> dict[str, set[str]]:
    """
    Build object_id -> entity_id(s) mapping from ev-ent-* evidence items.
    """
    out: dict[str, set[str]] = {}
    for ev in evidence_items:
        ev_id = str(ev.get("evidence_id", ""))
        if not ev_id.startswith("ev-ent-"):
            continue
        entity_id = ev_id.removeprefix("ev-ent-")
        for obj_id in _safe_list(ev.get("source_object_ids")):
            key = str(obj_id)
            out.setdefault(key, set()).add(entity_id)
    return out


def _has_cluster_signal(rel: dict[str, Any]) -> bool:
    refs = {str(x) for x in _safe_list(rel.get("observation_refs"))}
    if any(ref.startswith("obs:group-overlap:") for ref in refs):
        return True
    if any(ref.startswith("obs:metadata-shared:") for ref in refs):
        return True
    return str(rel.get("predicate", "")) == "declared_related_to"


def _recommended_check(rel: dict[str, Any]) -> str:
    required = [str(x) for x in _safe_list(rel.get("verification_required")) if str(x)]
    if required:
        return required[0]
    basis = str(rel.get("inference_basis", ""))
    if basis == "bbox_overlap":
        return "brep_intersection_check"
    if basis == "bbox_gap_within_tolerance":
        return "brep_contact_check"
    return "human_review"


def _score_relation(
    rel: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    relation_signature_counts: dict[tuple[str, str], int],
    entity_by_object: dict[str, set[str]],
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0

    relation_id = str(rel.get("relation_id", ""))
    supported, support_count = _relation_supported_by_hypothesis(relation_id, hypotheses)
    if supported:
        score += 0.4
        reasons.append(f"supports {support_count} hypothesis entries")

    signature = (str(rel.get("predicate", "")), str(rel.get("inference_basis", "")))
    if relation_signature_counts.get(signature, 0) >= 2:
        score += 0.2
        reasons.append("repeated relation pattern detected")

    inference_basis = str(rel.get("inference_basis", ""))
    if inference_basis in {"bbox_overlap", "bbox_gap_within_tolerance"}:
        score += 0.2
        reasons.append(f"inference basis is {inference_basis}")

    if _has_cluster_signal(rel):
        score += 0.1
        reasons.append("cluster signal detected from grouping/metadata")

    subject_id = str(rel.get("subject_id", ""))
    object_id = str(rel.get("object_id", ""))
    affected_entities = set()
    affected_entities.update(entity_by_object.get(subject_id, set()))
    affected_entities.update(entity_by_object.get(object_id, set()))
    if len(affected_entities) >= 2:
        score += 0.1
        reasons.append("affects multiple entities")

    return min(1.0, score), reasons


def plan_verifications(payload: dict[str, Any]) -> dict[str, Any]:
    relations = [r for r in _safe_list(payload.get("relations")) if isinstance(r, dict)]
    hypotheses = [h for h in _safe_list(payload.get("hypotheses")) if isinstance(h, dict)]
    evidence_items = [e for e in _safe_list(payload.get("evidence_items")) if isinstance(e, dict)]

    candidates = [
        r
        for r in relations
        if str(r.get("assertion_level", "")) == "candidate" and len(_safe_list(r.get("verification_required"))) > 0
    ]
    relation_signature_counts: dict[tuple[str, str], int] = {}
    for rel in candidates:
        key = (str(rel.get("predicate", "")), str(rel.get("inference_basis", "")))
        relation_signature_counts[key] = relation_signature_counts.get(key, 0) + 1
    entity_by_object = _entity_membership_from_evidence(evidence_items)

    ranked: list[dict[str, Any]] = []
    for rel in candidates:
        score, reasons = _score_relation(rel, hypotheses, relation_signature_counts, entity_by_object)
        relation_id = str(rel.get("relation_id", ""))
        reason = "; ".join(reasons) if reasons else "candidate relation requires explicit verification"
        ranked.append(
            {
                "relation_id": relation_id,
                "priority": round(score, 3),
                "reason": reason,
                "recommended_check": _recommended_check(rel),
                "assertion_level": str(rel.get("assertion_level", "")),
                "inference_basis": str(rel.get("inference_basis", "")),
            }
        )

    ranked.sort(key=lambda x: (float(x["priority"]), x["relation_id"]), reverse=True)
    top_n = 10
    verification_plan = ranked[:top_n]

    # Guardrail: no forbidden vocabulary in planner output.
    for item in verification_plan:
        text = f"{item.get('reason', '')} {item.get('recommended_check', '')}".lower()
        if any(term in text for term in FORBIDDEN_TERMS):
            item["reason"] = "candidate relation requires explicit verification"
            item["recommended_check"] = "human_review"

    return {"verification_plan": verification_plan}

