import sys
from pathlib import Path

from shared.contracts import validate_payload

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.run_minimal_analysis import run  # noqa: E402


FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
FORBIDDEN_TERMS = ["panel", "beam", "truss", "sip", "connector", "wood", "steel"]
VALIDATION_FIELDS = {
    "validation_id",
    "rule_id",
    "rule_name",
    "severity",
    "recommendation",
    "skipped_reason",
}


def _contains_forbidden(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_forbidden(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden(v) for v in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in FORBIDDEN_TERMS)
    return False


def test_hypotheses_validate_schema_and_trace_to_evidence(tmp_path):
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "with_hypotheses",
        include_hypotheses=True,
    )

    evidence_ids = {item["evidence_id"] for item in bundle.get("evidence_items", [])}
    hypotheses = bundle.get("hypotheses", [])
    assert hypotheses, "Expected non-empty hypotheses when include_hypotheses=True"

    for hyp in hypotheses:
        validate_payload("hypothesis_schema.v1.json", hyp)
        for ev_id in hyp.get("supporting_evidence", []):
            assert ev_id in evidence_ids
        for ev_id in hyp.get("contradicting_evidence", []):
            assert ev_id in evidence_ids


def test_hypotheses_do_not_use_forbidden_vocabulary_or_validation_fields(tmp_path):
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        tmp_path / "hypothesis_boundaries",
        include_hypotheses=True,
    )
    hypotheses = bundle.get("hypotheses", [])
    assert not _contains_forbidden(hypotheses)

    for hyp in hypotheses:
        assert not (set(hyp.keys()) & VALIDATION_FIELDS)
        assert "status" in hyp  # hypothesis state only, not validation verdict
