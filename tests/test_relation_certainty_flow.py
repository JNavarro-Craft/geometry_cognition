import json
from pathlib import Path

from gc_mcp.evidence_graph.tools import build_evidence_graph
from gc_mcp.geometry_kernel.tools import compute_geometry_features
from gc_mcp.hypothesis_engine.tools import generate_hypotheses
from shared.contracts import validate_payload


FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    with (FIXTURES / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def test_relation_certainty_fields_from_kernel_and_metadata_candidate():
    objects = _load("interaction_layer.sample.json")
    ker = compute_geometry_features({"objects": objects})
    relations = ker["relations"]
    assert relations

    for rel in relations:
        validate_payload("relations_schema.v2.json", rel)
        assert rel["assertion_level"] in {"candidate", "measured", "confirmed"}
        assert rel["verification_status"] in {"unverified", "partially_verified", "verified", "contradicted"}

    intersects = [r for r in relations if r["predicate"] == "intersects"]
    assert intersects
    assert any(r["inference_basis"] == "bbox_overlap" for r in intersects)
    assert all("brep_intersection_check" in r["verification_required"] for r in intersects if r["inference_basis"] == "bbox_overlap")

    touches = [r for r in relations if r["predicate"] == "touches"]
    assert touches
    assert all("brep_contact_check" in r["verification_required"] for r in touches)

    metadata_rel = [r for r in relations if r["predicate"] == "declared_related_to"]
    if metadata_rel:
        for rel in metadata_rel:
            assert rel["assertion_level"] == "candidate"
            assert rel["inference_basis"] == "shared_metadata"
            assert "metadata_observational_only" in rel["limitations"]


def test_evidence_graph_preserves_relation_certainty_fields():
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
    rel_evidence = [e for e in evg["evidence_items"] if e["evidence_id"].startswith("ev-rel-")]
    assert rel_evidence
    for e in rel_evidence:
        ov = e.get("observed_value", {})
        assert ov.get("assertion_level") in {"candidate", "measured", "confirmed"}
        assert ov.get("inference_basis")
        assert ov.get("measurement_method")
        assert ov.get("verification_status")
        assert isinstance(ov.get("verification_required", []), list)
        assert isinstance(ov.get("confidence_basis", []), list)
        if ov.get("assertion_level") == "candidate":
            claim = e.get("claim", "")
            assert "candidate relation observed" in claim or "candidate touching relation observed" in claim


def test_hypothesis_confidence_weighted_by_relation_certainty_levels():
    evidence_items = [
        {
            "evidence_id": "ev-ent-ent-a",
            "evidence_type": "derived",
            "source_mcp": "evidence_graph",
            "source_object_ids": ["oa"],
            "claim": "entity formation observed from extraction",
            "observed_value": {"entity_type": "source_object"},
            "confidence": 1.0,
            "supports": [],
            "contradicts": [],
            "limitations": [],
        },
        {
            "evidence_id": "ev-ent-ent-b",
            "evidence_type": "derived",
            "source_mcp": "evidence_graph",
            "source_object_ids": ["ob"],
            "claim": "entity formation observed from extraction",
            "observed_value": {"entity_type": "source_object"},
            "confidence": 1.0,
            "supports": [],
            "contradicts": [],
            "limitations": [],
        },
        {
            "evidence_id": "ev-geom-oa",
            "evidence_type": "geometry",
            "source_mcp": "evidence_graph",
            "source_object_ids": ["oa"],
            "claim": "geometry feature observed for object",
            "observed_value": {"morphology": "compact_solid"},
            "confidence": 0.8,
            "supports": [],
            "contradicts": [],
            "limitations": [],
        },
        {
            "evidence_id": "ev-geom-ob",
            "evidence_type": "geometry",
            "source_mcp": "evidence_graph",
            "source_object_ids": ["ob"],
            "claim": "geometry feature observed for object",
            "observed_value": {"morphology": "compact_solid"},
            "confidence": 0.8,
            "supports": [],
            "contradicts": [],
            "limitations": [],
        },
        {
            "evidence_id": "ev-rel-rel-candidate",
            "evidence_type": "relation",
            "source_mcp": "evidence_graph",
            "source_object_ids": ["oa", "oc"],
            "claim": "candidate relation observed between objects",
            "observed_value": {"predicate": "intersects", "assertion_level": "candidate"},
            "confidence": 0.75,
            "supports": [],
            "contradicts": [],
            "limitations": ["candidate_relation"],
        },
        {
            "evidence_id": "ev-rel-rel-confirmed",
            "evidence_type": "relation",
            "source_mcp": "evidence_graph",
            "source_object_ids": ["ob", "od"],
            "claim": "confirmed relation observed between objects",
            "observed_value": {"predicate": "intersects", "assertion_level": "confirmed"},
            "confidence": 0.75,
            "supports": [],
            "contradicts": [],
            "limitations": [],
        },
    ]
    entities = [
        {
            "entity_id": "ent-a",
            "entity_type": "source_object",
            "member_object_ids": ["oa"],
            "source_refs": ["oa"],
            "formation_method": "direct_extraction",
            "confidence": 1.0,
            "observation_refs": [],
            "limitations": [],
            "warnings": [],
            "status": "observed",
            "notes": [],
        },
        {
            "entity_id": "ent-b",
            "entity_type": "source_object",
            "member_object_ids": ["ob"],
            "source_refs": ["ob"],
            "formation_method": "direct_extraction",
            "confidence": 1.0,
            "observation_refs": [],
            "limitations": [],
            "warnings": [],
            "status": "observed",
            "notes": [],
        },
    ]
    relations = [
        {
            "relation_id": "rel-candidate",
            "subject_id": "oa",
            "predicate": "intersects",
            "object_id": "oc",
            "relation_type": "spatial",
            "directionality": "symmetric",
            "confidence": 0.7,
            "tolerance_context": {"linear_tolerance": 0.05, "angular_tolerance": 2.0, "unit_system": "model_unit"},
            "observation_refs": ["obs:overlap:oa:oc"],
            "limitations": ["candidate_relation"],
            "derived_from": ["geometry_schema.v2.json"],
            "assertion_level": "candidate",
            "inference_basis": "bbox_overlap",
            "measurement_method": "aabb_overlap",
            "verification_status": "unverified",
            "verification_required": ["brep_intersection_check"],
            "confidence_basis": ["aabb overlap proxy"],
        },
        {
            "relation_id": "rel-confirmed",
            "subject_id": "ob",
            "predicate": "intersects",
            "object_id": "od",
            "relation_type": "spatial",
            "directionality": "symmetric",
            "confidence": 0.7,
            "tolerance_context": {"linear_tolerance": 0.05, "angular_tolerance": 2.0, "unit_system": "model_unit"},
            "observation_refs": ["obs:overlap:ob:od"],
            "limitations": [],
            "derived_from": ["geometry_schema.v2.json"],
            "assertion_level": "confirmed",
            "inference_basis": "brep_intersection",
            "measurement_method": "brep_intersection_curve",
            "verification_status": "verified",
            "verification_required": [],
            "confidence_basis": ["verified brep intersection"],
        },
    ]

    out = generate_hypotheses({"evidence_items": evidence_items, "entities": entities, "relations": relations})
    by_ent = {h["entity_id"]: h for h in out["hypotheses"]}
    assert by_ent["ent-a"]["confidence"] < by_ent["ent-b"]["confidence"]
    assert "verified geometric interaction required" in by_ent["ent-a"]["missing_information"]
