import sys
from pathlib import Path

from shared.contracts import validate_payload

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.run_minimal_analysis import run  # noqa: E402


FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
FORBIDDEN_TERMS = ["panel", "beam", "truss", "sip", "connector", "wood", "steel"]


def _contains_forbidden(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_forbidden(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden(v) for v in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in FORBIDDEN_TERMS)
    return False


def test_validation_results_match_schema_and_no_new_hypotheses(tmp_path):
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "with_validation",
        include_validation=True,
    )

    hypotheses = bundle.get("hypotheses", [])
    validation_results = bundle.get("validation_results", [])
    assert hypotheses, "Expected hypotheses to exist before validation."
    assert validation_results, "Expected validation results."

    for item in validation_results:
        validate_payload("validation_schema.v1.json", item)
        assert "hypothesis_label" not in item

    # Validation must not create/modify hypothesis shape.
    for hyp in hypotheses:
        validate_payload("hypothesis_schema.v1.json", hyp)
        assert "validation_id" not in hyp
        assert "rule_id" not in hyp


def test_validation_results_no_forbidden_terms_and_no_automation(tmp_path):
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "validation_boundaries",
        include_validation=True,
    )
    assert not _contains_forbidden(bundle.get("validation_results", []))
    assert "automation" not in bundle
    assert "automation_results" not in bundle


def test_mixed_system_existing_entity_references_pass_rule_r2(tmp_path):
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "validation_entity_ref",
        include_validation=True,
    )
    hypothesis_by_id = {h["hypothesis_id"]: h for h in bundle.get("hypotheses", [])}
    existing_entity_ids = {e["entity_id"] for e in bundle.get("entities", [])}

    for result in bundle.get("validation_results", []):
        if result.get("rule_name") != "hypothesis_references_existing_entity":
            continue
        hyp = hypothesis_by_id.get(result.get("target_id"))
        assert hyp is not None
        assert hyp.get("entity_id") in existing_entity_ids
        assert result.get("status") == "pass"


def test_hypothesis_entity_id_exact_subset_of_entities_and_all_r2_pass(tmp_path):
    """hypothesis.entity_id must be verbatim entity_schema ids; R2 passes when entities exist."""
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "validation_r2_exact_ids",
        include_validation=True,
    )
    entities = bundle.get("entities", [])
    hypotheses = bundle.get("hypotheses", [])
    entity_ids = {e["entity_id"] for e in entities}
    assert entities and hypotheses
    for hyp in hypotheses:
        assert hyp["entity_id"] in entity_ids

    r2 = [r for r in bundle.get("validation_results", []) if r.get("rule_id") == "R2"]
    assert r2
    assert all(r.get("status") == "pass" for r in r2)


def test_validation_r2_fails_on_wrong_entity_id_string_not_truncated():
    from gc_mcp.validation_engine.tools import validate_hypotheses

    entities = [
        {
            "entity_id": "ent-src-obj-long-object-id-12345",
            "entity_type": "source_object",
            "member_object_ids": ["x"],
            "source_refs": ["r"],
            "formation_method": "direct_extraction",
            "confidence": 1.0,
            "observation_refs": [],
            "limitations": [],
            "warnings": [],
            "status": "observed",
            "notes": [],
        }
    ]
    hypotheses = [
        {
            "hypothesis_id": "hyp-0001",
            "entity_id": "ent-src-obj-long",  # truncated / wrong — must not pass R2
            "hypothesis_label": "ambiguous_entity",
            "hypothesis_level": "relational",
            "confidence": 0.5,
            "supporting_evidence": ["ev-1"],
            "contradicting_evidence": [],
            "alternatives": [],
            "missing_information": ["m"],
            "status": "candidate",
        }
    ]
    evidence_items = [
        {
            "evidence_id": "ev-1",
            "evidence_type": "geometry",
            "source_object_ids": ["x"],
            "confidence": 0.5,
            "observed_value": {},
            "limitations": [],
        }
    ]
    out = validate_hypotheses(
        {"hypotheses": hypotheses, "entities": entities, "evidence_items": evidence_items, "relations": []}
    )
    r2 = next(r for r in out["validation_results"] if r["rule_id"] == "R2")
    assert r2["status"] == "fail"


def test_mixed_system_r1_r2_r3_all_pass_on_official_references(tmp_path):
    """supporting_evidence and entity_id point at official evidence/entity ids."""
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "r1r2r3",
        include_validation=True,
    )
    evidence_ids = {e["evidence_id"] for e in bundle.get("evidence_items", [])}
    entity_ids = {e["entity_id"] for e in bundle.get("entities", [])}
    for hyp in bundle.get("hypotheses", []):
        assert hyp["entity_id"] in entity_ids
        for ev_id in hyp.get("supporting_evidence", []):
            assert ev_id in evidence_ids, (ev_id, sorted(list(evidence_ids))[:5])
    r1 = [r for r in bundle["validation_results"] if r["rule_id"] == "R1"]
    r2 = [r for r in bundle["validation_results"] if r["rule_id"] == "R2"]
    r3 = [r for r in bundle["validation_results"] if r["rule_id"] == "R3"]
    assert r1 and r2 and r3
    assert all(r.get("status") == "pass" for r in r1 + r2 + r3)


def test_validation_r3_fails_when_supporting_not_in_evidence():
    from gc_mcp.validation_engine.tools import validate_hypotheses

    ent_id = "ent-e1"
    entities = [
        {
            "entity_id": ent_id,
            "entity_type": "source_object",
            "member_object_ids": ["o1"],
            "source_refs": ["r1"],
            "formation_method": "direct_extraction",
            "confidence": 1.0,
            "observation_refs": [],
            "limitations": [],
            "warnings": [],
            "status": "observed",
            "notes": [],
        }
    ]
    ev_official = f"ev-ent-{ent_id}"
    evidence_items = [
        {
            "evidence_id": ev_official,
            "evidence_type": "derived",
            "source_mcp": "x",
            "source_object_ids": ["o1"],
            "claim": "c",
            "observed_value": {},
            "confidence": 0.5,
            "supports": [],
            "contradicts": [],
            "limitations": [],
        }
    ]
    hyp_bad = {
        "hypothesis_id": "h1",
        "entity_id": ent_id,
        "hypothesis_label": "ambiguous_entity",
        "hypothesis_level": "relational",
        "confidence": 0.5,
        "supporting_evidence": ["no-such-official-evidence-id-xyz"],
        "contradicting_evidence": [],
        "alternatives": [],
        "missing_information": ["m"],
        "status": "candidate",
    }
    out = validate_hypotheses(
        {"hypotheses": [hyp_bad], "entities": entities, "evidence_items": evidence_items, "relations": []}
    )
    r3 = next(r for r in out["validation_results"] if r["rule_id"] == "R3")
    assert r3["status"] == "fail"
