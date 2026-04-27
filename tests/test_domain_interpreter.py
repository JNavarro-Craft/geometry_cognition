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
    # Hypothesis label with only high-risk mapping in interpretation_rules should be skipped.
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
    assert result["domain_interpretations"] == []
