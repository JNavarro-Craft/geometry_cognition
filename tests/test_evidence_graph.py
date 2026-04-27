import json
import sys
from pathlib import Path

from shared.contracts import validate_payload

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.evidence_graph.tools import build_evidence_graph  # noqa: E402
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


def test_evidence_graph_items_validate_schema_and_boundaries(tmp_path):
    output_dir = tmp_path / "e2e_with_evidence"
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        output_dir,
        include_evidence_graph=True,
    )

    evidence_items = bundle.get("evidence_items", [])
    assert evidence_items, "Expected non-empty evidence items."
    for item in evidence_items:
        validate_payload("evidence_schema.v1.json", item)
        assert "hypothesis_label" not in item
        assert "source_mcp" in item and item["source_mcp"]
        assert "claim" in item and item["claim"]
        assert "confidence" in item
        assert "limitations" in item

    assert not _contains_forbidden(evidence_items)


def test_evidence_items_reference_existing_objects_entities_or_relations(tmp_path):
    output_dir = tmp_path / "evidence_ref_check"
    bundle = run(
        FIXTURES_DIR / "mixed_system.sample.json",
        output_dir,
        include_evidence_graph=True,
    )

    objects = {obj["object_id"] for obj in bundle["objects"]}
    entities = {ent["entity_id"] for ent in bundle["entities"]}
    relations = {rel["relation_id"] for rel in bundle["relations"]}

    for item in bundle["evidence_items"]:
        observed_value = item.get("observed_value", {})
        source_ids = set(item.get("source_object_ids", []))
        assert source_ids, "source_object_ids must not be empty"
        assert source_ids.issubset(objects | entities | relations)

        if isinstance(observed_value, dict):
            entity_type = observed_value.get("entity_type")
            predicate = observed_value.get("predicate")
            if entity_type is not None:
                assert item["evidence_type"] in {"derived", "metadata"}
            if predicate is not None:
                assert item["evidence_type"] == "relation"


def test_evidence_graph_output_file_contains_expected_sections(tmp_path):
    output_dir = tmp_path / "evidence_file_check"
    run(FIXTURES_DIR / "mixed_system.sample.json", output_dir, include_evidence_graph=True)

    graph_path = output_dir / "evidence_graph.json"
    assert graph_path.exists()
    with graph_path.open("r", encoding="utf-8") as f:
        graph = json.load(f)

    assert "nodes" in graph
    assert "edges" in graph
    assert "evidence_items" in graph
    assert isinstance(graph["nodes"], list)
    assert isinstance(graph["edges"], list)
    assert isinstance(graph["evidence_items"], list)

    # Smoke check direct tool API boundary remains observation->evidence only.
    result = build_evidence_graph(
        {
            "objects": [],
            "geometry_features": [],
            "entities": [],
            "relations": [],
            "metadata": [],
        }
    )
    assert "hypothesis_label" not in json.dumps(result).lower()
