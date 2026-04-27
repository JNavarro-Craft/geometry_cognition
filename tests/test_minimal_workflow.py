import json
import sys
from pathlib import Path

from shared.contracts import validate_payload

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.run_minimal_analysis import run  # noqa: E402


FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
FORBIDDEN_TERMS = ["panel", "beam", "truss", "sip", "connector", "wood", "steel"]
HYPOTHESIS_ONLY_FIELDS = {
    "hypothesis_id",
    "hypothesis_label",
    "hypothesis_level",
    "supporting_evidence",
    "contradicting_evidence",
    "alternatives",
    "missing_information",
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


def _validate_output_files(
    output_dir: Path,
    include_evidence_graph: bool = False,
    include_hypotheses: bool = False,
    include_validation: bool = False,
    include_domain: bool = False,
) -> dict[str, list]:
    expected = {
        "objects.json": "object_schema.v1.json",
        "geometry_features.json": "geometry_schema.v1.json",
        "entities.json": "entity_schema.v1.json",
        "relations.json": "relations_schema.v1.json",
        "minimal_analysis_bundle.json": None,
    }
    if include_evidence_graph:
        expected["evidence_graph.json"] = None
    if include_hypotheses:
        expected["hypotheses.json"] = "hypothesis_schema.v1.json"
    if include_validation:
        expected["validation_results.json"] = "validation_schema.v1.json"
    if include_domain:
        expected["domain_interpretations.json"] = "domain_interpretation_schema.v1.json"

    loaded: dict[str, list] = {}
    for filename, schema in expected.items():
        file_path = output_dir / filename
        assert file_path.exists(), f"Expected output file not found: {filename}"
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        loaded[filename] = data
        if schema:
            assert isinstance(data, list), f"{filename} must contain a list payload."
            for item in data:
                validate_payload(schema, item)
    return loaded


def _assert_entity_boundary(entities: list[dict]) -> None:
    for entity in entities:
        assert "hypothesis_label" not in entity
        assert "evidence" not in entity
        assert not (set(entity.keys()) & HYPOTHESIS_ONLY_FIELDS)


def _assert_relation_boundary(relations: list[dict]) -> None:
    for relation in relations:
        assert "observation_refs" in relation
        assert "evidence" not in relation


def test_minimal_workflow_simple_linear_elements(tmp_path):
    input_path = FIXTURES_DIR / "simple_linear_elements.sample.json"
    output_dir = tmp_path / "linear_outputs"
    run(input_path, output_dir)
    loaded = _validate_output_files(output_dir)
    _assert_entity_boundary(loaded["entities.json"])
    _assert_relation_boundary(loaded["relations.json"])
    assert not _contains_forbidden(loaded["geometry_features.json"])
    assert not _contains_forbidden(loaded["entities.json"])
    assert not _contains_forbidden(loaded["relations.json"])


def test_minimal_workflow_simple_plate_elements(tmp_path):
    input_path = FIXTURES_DIR / "simple_plate_elements.sample.json"
    output_dir = tmp_path / "plate_outputs"
    run(input_path, output_dir)
    loaded = _validate_output_files(output_dir)
    _assert_entity_boundary(loaded["entities.json"])
    _assert_relation_boundary(loaded["relations.json"])
    assert not _contains_forbidden(loaded["geometry_features.json"])
    assert not _contains_forbidden(loaded["entities.json"])
    assert not _contains_forbidden(loaded["relations.json"])


def test_minimal_workflow_mixed_system(tmp_path):
    input_path = FIXTURES_DIR / "mixed_system.sample.json"
    output_dir = tmp_path / "mixed_outputs"
    run(input_path, output_dir)
    loaded = _validate_output_files(output_dir)
    _assert_entity_boundary(loaded["entities.json"])
    _assert_relation_boundary(loaded["relations.json"])
    assert not _contains_forbidden(loaded["geometry_features.json"])
    assert not _contains_forbidden(loaded["entities.json"])
    assert not _contains_forbidden(loaded["relations.json"])


def test_minimal_workflow_mixed_system_with_evidence_graph(tmp_path):
    input_path = FIXTURES_DIR / "mixed_system.sample.json"
    output_dir = tmp_path / "mixed_outputs_with_evidence"
    run(input_path, output_dir, include_evidence_graph=True)
    loaded = _validate_output_files(output_dir, include_evidence_graph=True)
    _assert_entity_boundary(loaded["entities.json"])
    _assert_relation_boundary(loaded["relations.json"])
    assert not _contains_forbidden(loaded["geometry_features.json"])
    assert not _contains_forbidden(loaded["entities.json"])
    assert not _contains_forbidden(loaded["relations.json"])

    with (output_dir / "evidence_graph.json").open("r", encoding="utf-8") as f:
        evidence_graph = json.load(f)
    for item in evidence_graph.get("evidence_items", []):
        validate_payload("evidence_schema.v1.json", item)


def test_minimal_workflow_mixed_system_with_evidence_and_hypotheses(tmp_path):
    input_path = FIXTURES_DIR / "mixed_system.sample.json"
    output_dir = tmp_path / "mixed_outputs_with_hypotheses"
    run(input_path, output_dir, include_hypotheses=True)
    loaded = _validate_output_files(
        output_dir, include_evidence_graph=True, include_hypotheses=True
    )
    _assert_entity_boundary(loaded["entities.json"])
    _assert_relation_boundary(loaded["relations.json"])
    assert not _contains_forbidden(loaded["geometry_features.json"])
    assert not _contains_forbidden(loaded["entities.json"])
    assert not _contains_forbidden(loaded["relations.json"])
    assert not _contains_forbidden(loaded["hypotheses.json"])


def test_minimal_workflow_mixed_system_with_evidence_hypotheses_validation(tmp_path):
    input_path = FIXTURES_DIR / "mixed_system.sample.json"
    output_dir = tmp_path / "mixed_outputs_with_validation"
    bundle = run(input_path, output_dir, include_validation=True)
    loaded = _validate_output_files(
        output_dir,
        include_evidence_graph=True,
        include_hypotheses=True,
        include_validation=True,
    )
    _assert_entity_boundary(loaded["entities.json"])
    _assert_relation_boundary(loaded["relations.json"])
    assert not _contains_forbidden(loaded["geometry_features.json"])
    assert not _contains_forbidden(loaded["entities.json"])
    assert not _contains_forbidden(loaded["relations.json"])
    assert not _contains_forbidden(loaded["hypotheses.json"])
    assert not _contains_forbidden(loaded["validation_results.json"])
    assert "automation_results" not in bundle
    assert "validation_summary" in bundle

    summary = bundle["validation_summary"]
    assert summary["total"] == len(loaded["validation_results.json"])
    assert summary["passed"] + summary["failed"] + summary["skipped"] + summary["inconclusive"] == summary["total"]
    assert isinstance(summary["by_rule"], dict)
    assert summary["highest_severity"] in {"info", "warning", "error", "critical"}


def test_minimal_workflow_mixed_system_with_domain_interpreter(tmp_path):
    input_path = FIXTURES_DIR / "mixed_system.sample.json"
    output_dir = tmp_path / "mixed_outputs_with_domain"
    bundle = run(input_path, output_dir, include_domain=True)
    loaded = _validate_output_files(
        output_dir,
        include_evidence_graph=True,
        include_hypotheses=True,
        include_validation=True,
        include_domain=True,
    )
    assert "domain_interpretations" in bundle
    assert "automation_results" not in bundle
    assert not _contains_forbidden(loaded["domain_interpretations.json"])
