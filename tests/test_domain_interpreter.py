import sys
from pathlib import Path

from shared.contracts import validate_payload

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.run_minimal_analysis import run  # noqa: E402
from gc_mcp.domain_interpreter.tools import generate_domain_interpretations  # noqa: E402


FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
FORBIDDEN_TERMS = ["beam", "panel", "truss", "sip", "connector", "wood", "steel"]


def _contains_forbidden(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_forbidden(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden(v) for v in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in FORBIDDEN_TERMS)
    return False


def test_domain_interpretations_validate_schema_and_trace_to_hypotheses(tmp_path):
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "with_domain",
        include_domain=True,
    )
    hypothesis_ids = {item["hypothesis_id"] for item in bundle.get("hypotheses", [])}
    interpretations = bundle.get("domain_interpretations", [])
    assert interpretations

    for item in interpretations:
        validate_payload("domain_interpretation_schema.v1.json", item)
        assert item["status"] in {"tentative", "plausible", "weak", "unsupported"}
        assert set(item["derived_from_hypotheses"]).issubset(hypothesis_ids)


def test_domain_interpreter_has_no_forbidden_terms_and_no_knowledge_base_usage(tmp_path):
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "domain_boundaries",
        include_domain=True,
    )
    interpretations = bundle.get("domain_interpretations", [])
    assert not _contains_forbidden(interpretations)

    tools_path = PROJECT_ROOT / "gc_mcp" / "domain_interpreter" / "tools.py"
    text = tools_path.read_text(encoding="utf-8")
    assert "knowledge_base" not in text


def test_domain_interpreter_ignores_high_risk_rules():
    # High-risk-only mapping should produce conservative fallback, never silent skip.
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-test-001",
                "entity_id": "ent-test-001",
                "hypothesis_label": "morphological_pattern",
                "hypothesis_level": "morphological",
                "confidence": 0.8,
                "supporting_evidence": ["ev-001"],
                "contradicting_evidence": [],
                "alternatives": [],
                "missing_information": [],
                "status": "candidate",
            }
        ]
    }
    result = generate_domain_interpretations(payload, profile="prefab")
    assert len(result["domain_interpretations"]) == 1
    item = result["domain_interpretations"][0]
    assert item["derived_from_hypotheses"] == ["hyp-test-001"]
    assert item["interpretation_label"] in {"no_domain_mapping_available", "requires_human_review"}


def test_domain_interpreter_no_mapping_with_evidence_uses_no_domain_mapping_available():
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-nomap-001",
                "entity_id": "ent-test-001",
                "hypothesis_label": "label_without_profile_mapping",
                "hypothesis_level": "relational",
                "confidence": 0.82,
                "supporting_evidence": ["ev-001", "ev-002"],
                "contradicting_evidence": [],
                "alternatives": [],
                "missing_information": [],
                "status": "candidate",
            }
        ]
    }
    out = generate_domain_interpretations(payload, profile="prefab")
    assert len(out["domain_interpretations"]) == 1
    item = out["domain_interpretations"][0]
    assert item["interpretation_label"] == "no_domain_mapping_available"
    assert item["status"] == "unsupported"
    assert item["supporting_evidence"] == ["ev-001", "ev-002"]
    assert item["derived_from_hypotheses"] == ["hyp-nomap-001"]


def test_domain_interpreter_insufficient_evidence_uses_requires_human_review():
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-low-001",
                "entity_id": "ent-test-001",
                "hypothesis_label": "label_without_profile_mapping",
                "hypothesis_level": "relational",
                "confidence": 0.2,
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "alternatives": [],
                "missing_information": ["evidence needed"],
                "status": "candidate",
            }
        ]
    }
    out = generate_domain_interpretations(payload, profile="prefab")
    assert len(out["domain_interpretations"]) == 1
    item = out["domain_interpretations"][0]
    assert item["interpretation_label"] == "requires_human_review"
    assert item["status"] == "weak"
    assert item["derived_from_hypotheses"] == ["hyp-low-001"]


def test_domain_interpreter_never_silently_omits_hypotheses():
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-a",
                "entity_id": "ent-a",
                "hypothesis_label": "label_without_profile_mapping",
                "hypothesis_level": "relational",
                "confidence": 0.8,
                "supporting_evidence": ["ev-a"],
                "contradicting_evidence": [],
                "alternatives": [],
                "missing_information": [],
                "status": "candidate",
            },
            {
                "hypothesis_id": "hyp-b",
                "entity_id": "ent-b",
                "hypothesis_label": "label_without_profile_mapping",
                "hypothesis_level": "relational",
                "confidence": 0.2,
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "alternatives": [],
                "missing_information": ["missing"],
                "status": "candidate",
            },
        ]
    }
    out = generate_domain_interpretations(payload, profile="prefab")
    assert len(out["domain_interpretations"]) == len(payload["hypotheses"])
    assert not out["skipped_hypotheses"]


def test_domain_interpreter_returns_minimal_output_with_evidence_for_ambiguous():
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-min-001",
                "entity_id": "ent-min-001",
                "hypothesis_label": "ambiguous_entity",
                "hypothesis_level": "relational",
                "confidence": 0.7,
                "supporting_evidence": ["ev-ent-ent-min-001", "ev-geom-obj-1"],
                "contradicting_evidence": [],
                "alternatives": [],
                "missing_information": [],
                "status": "candidate",
            }
        ]
    }
    out = generate_domain_interpretations(payload, profile="prefab")
    assert len(out["domain_interpretations"]) == 1
    item = out["domain_interpretations"][0]
    assert item["interpretation_label"] == "observed_structural_pattern"
    assert item["status"] == "weak"
    assert item["derived_from_hypotheses"] == ["hyp-min-001"]
