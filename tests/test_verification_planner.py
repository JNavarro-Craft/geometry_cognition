from gc_mcp.verification_planner.tools import plan_verifications


def _candidate_relation(idx: int, *, supported: bool = False, overlap: bool = False) -> dict:
    basis = "bbox_overlap" if overlap else "shared_metadata"
    verification_required = ["brep_intersection_check"] if overlap else ["human_review"]
    return {
        "relation_id": f"rel-{idx:03d}",
        "subject_id": f"o{idx}",
        "predicate": "intersects" if overlap else "declared_related_to",
        "object_id": f"o{idx+1}",
        "relation_type": "spatial" if overlap else "organizational",
        "directionality": "symmetric",
        "confidence": 0.75,
        "tolerance_context": {"linear_tolerance": 0.05, "angular_tolerance": 2.0, "unit_system": "model_unit"},
        "observation_refs": [f"obs:metadata-shared:o{idx}:o{idx+1}"] if not overlap else [f"obs:overlap:o{idx}:o{idx+1}"],
        "limitations": ["candidate_relation"],
        "derived_from": ["geometry_schema.v2.json"],
        "assertion_level": "candidate",
        "inference_basis": basis,
        "measurement_method": "aabb_overlap" if overlap else "metadata_key_match",
        "verification_status": "unverified",
        "verification_required": verification_required,
        "confidence_basis": ["test"],
        "_supported": supported,
    }


def test_verification_planner_limits_to_top_10_for_large_candidate_set():
    relations = [_candidate_relation(i, overlap=(i % 2 == 0)) for i in range(1, 26)]
    hypotheses = []
    evidence_items = []

    out = plan_verifications({"relations": relations, "hypotheses": hypotheses, "evidence_items": evidence_items})
    assert "verification_plan" in out
    assert len(out["verification_plan"]) <= 10


def test_verification_planner_prioritizes_hypothesis_relevant_relations():
    relations = [
        _candidate_relation(1, overlap=True),
        _candidate_relation(2, overlap=False),
        _candidate_relation(3, overlap=True),
    ]
    hypotheses = [
        {
            "hypothesis_id": "hyp-001",
            "entity_id": "ent-1",
            "supporting_evidence": ["ev-rel-rel-001", "ev-rel-rel-003"],
        }
    ]
    evidence_items = [
        {"evidence_id": "ev-ent-ent-1", "source_object_ids": ["o1", "o2"], "evidence_type": "derived"},
        {"evidence_id": "ev-ent-ent-2", "source_object_ids": ["o2", "o3"], "evidence_type": "derived"},
    ]
    out = plan_verifications({"relations": relations, "hypotheses": hypotheses, "evidence_items": evidence_items})
    plan = out["verification_plan"]
    assert plan
    # supported overlap relation should outrank plain metadata-only relation
    top_ids = [x["relation_id"] for x in plan[:2]]
    assert "rel-001" in top_ids or "rel-003" in top_ids
    low = next(x for x in plan if x["relation_id"] == "rel-002")
    high = next(x for x in plan if x["relation_id"] == "rel-001")
    assert high["priority"] > low["priority"]


def test_verification_planner_traceability_relation_ids_are_from_input():
    relations = [_candidate_relation(i, overlap=True) for i in range(1, 8)]
    valid_ids = {r["relation_id"] for r in relations}
    out = plan_verifications({"relations": relations, "hypotheses": [], "evidence_items": []})
    assert out["verification_plan"]
    assert all(item["relation_id"] in valid_ids for item in out["verification_plan"])


def test_verification_planner_no_constructive_vocabulary_in_output():
    relations = [_candidate_relation(i, overlap=(i % 3 == 0)) for i in range(1, 15)]
    out = plan_verifications({"relations": relations, "hypotheses": [], "evidence_items": []})
    forbidden = ["beam", "panel", "stud", "track", "diagonal", "connector", "truss", "sip"]
    text = " ".join(
        f"{item.get('reason', '')} {item.get('recommended_check', '')}" for item in out["verification_plan"]
    ).lower()
    assert all(term not in text for term in forbidden)
