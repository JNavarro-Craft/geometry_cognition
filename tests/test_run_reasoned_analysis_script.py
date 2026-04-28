import json
from pathlib import Path

from scripts.run_reasoned_analysis_with_llm import build_payload_from_outputs


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_script_computes_verification_plan_when_file_missing(tmp_path):
    outputs = tmp_path / "outputs"
    _write(
        outputs / "relations.json",
        [
            {
                "relation_id": "rel-001",
                "subject_id": "oa",
                "predicate": "intersects",
                "object_id": "ob",
                "relation_type": "spatial",
                "directionality": "symmetric",
                "confidence": 0.78,
                "tolerance_context": {"linear_tolerance": 0.05, "angular_tolerance": 2.0, "unit_system": "model_unit"},
                "observation_refs": ["obs:overlapping_bbox:oa:ob"],
                "limitations": ["bbox_based", "candidate_relation"],
                "derived_from": ["geometry_schema.v2.json"],
                "assertion_level": "candidate",
                "inference_basis": "bbox_overlap",
                "measurement_method": "aabb_overlap",
                "verification_status": "unverified",
                "verification_required": ["brep_intersection_check"],
                "confidence_basis": ["aabb overlap proxy"],
            }
        ],
    )
    _write(outputs / "evidence_graph.json", {"evidence_items": [{"evidence_id": "ev-ent-ent-1", "source_object_ids": ["oa"]}]})
    _write(outputs / "hypotheses.json", [{"hypothesis_id": "hyp-001", "supporting_evidence": ["ev-rel-rel-001"]}])

    payload, source = build_payload_from_outputs(outputs)
    assert source == "computed_with_verification_planner"
    assert isinstance(payload["verification_plan"], list)
    assert len(payload["verification_plan"]) > 0
