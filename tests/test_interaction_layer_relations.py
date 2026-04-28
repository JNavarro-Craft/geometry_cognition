import json
from pathlib import Path

from gc_mcp.evidence_graph.tools import build_evidence_graph
from gc_mcp.geometry_kernel.tools import compute_geometry_features
from gc_mcp.hypothesis_engine.tools import generate_hypotheses
from gc_mcp.validation_engine.tools import validate_hypotheses


FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    with (FIXTURES / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def _has_rel(relations, subject_id: str, object_id: str, predicate: str) -> bool:
    return any(
        r.get("subject_id") == subject_id and r.get("object_id") == object_id and r.get("predicate") == predicate
        for r in relations
    )


def test_interaction_layer_candidate_relations_generated():
    objects = _load("interaction_layer.sample.json")
    ker = compute_geometry_features({"objects": objects})
    relations = ker["relations"]

    assert _has_rel(relations, "i-touch-a", "i-touch-b", "touches")
    assert _has_rel(relations, "i-overlap-a", "i-overlap-b", "intersects")
    assert _has_rel(relations, "i-contained-inner", "i-contained-outer", "contained_by")
    assert _has_rel(relations, "i-contained-outer", "i-contained-inner", "contains")
    assert _has_rel(relations, "i-coplanar-a", "i-coplanar-b", "coplanar_with")

    # separated-by-gap candidate is represented as near + explicit observation ref.
    assert any(
        r.get("predicate") == "near"
        and "obs:separated_by_gap:i-sep-a:i-sep-b" in r.get("observation_refs", [])
        for r in relations
    )

    candidate_rels = [
        r
        for r in relations
        if any(str(ref).startswith("obs:touching_candidate:") for ref in r.get("observation_refs", []))
        or any(str(ref).startswith("obs:intersecting_candidate:") for ref in r.get("observation_refs", []))
        or any(str(ref).startswith("obs:contained_in_candidate:") for ref in r.get("observation_refs", []))
        or any(str(ref).startswith("obs:coplanar_candidate:") for ref in r.get("observation_refs", []))
        or any(str(ref).startswith("obs:overlapping_bbox:") for ref in r.get("observation_refs", []))
        or any(str(ref).startswith("obs:separated_by_gap:") for ref in r.get("observation_refs", []))
    ]
    assert candidate_rels
    for rel in candidate_rels:
        lim = set(rel.get("limitations", []))
        assert "bbox_based" in lim
        assert "candidate_relation" in lim
        assert "requires_brep_contact_check" in lim


def test_interaction_layer_evidence_and_validation_pass():
    objects = _load("interaction_layer.sample.json")
    ker = compute_geometry_features({"objects": objects})
    evg = build_evidence_graph(
        {
            "objects": objects,
            "geometry_features": ker["geometry_features"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    assert any(e["evidence_id"].startswith("ev-rel-") for e in evg["evidence_items"])

    hyp = generate_hypotheses(
        {"evidence_items": evg["evidence_items"], "entities": ker["entities"], "relations": ker["relations"]}
    )
    assert hyp["hypotheses"]
    assert all(h.get("supporting_evidence") for h in hyp["hypotheses"])

    val = validate_hypotheses(
        {
            "hypotheses": hyp["hypotheses"],
            "evidence_items": evg["evidence_items"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    for rid in ("R1", "R2", "R3", "R7"):
        rows = [r for r in val["validation_results"] if r["rule_id"] == rid]
        assert rows and all(r["status"] == "pass" for r in rows), rid
