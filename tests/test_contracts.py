import json
from pathlib import Path

from gc_mcp.geometry_kernel.tools import compute_geometry_features
from shared.contracts import validate_payload


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_json(filename: str):
    with (FIXTURES_DIR / filename).open("r", encoding="utf-8") as f:
        return json.load(f)


def test_normalized_objects_fixture_matches_object_schema():
    payloads = _load_json("normalized_objects.sample.json")
    for payload in payloads:
        validate_payload("object_schema.v1.json", payload)


def test_geometry_features_fixture_matches_geometry_schema():
    payloads = _load_json("geometry_features.sample.json")
    for payload in payloads:
        validate_payload("geometry_schema.v1.json", payload)


def test_geometry_features_v2_fixture_matches_geometry_schema_v2():
    payloads = _load_json("geometry_features.v2.sample.json")
    for payload in payloads:
        validate_payload("geometry_schema.v2.json", payload)


def test_evidence_fixture_matches_evidence_schema():
    payloads = _load_json("evidence_graph.sample.json")
    for payload in payloads:
        validate_payload("evidence_schema.v1.json", payload)


def test_hypothesis_fixture_matches_hypothesis_schema():
    payloads = _load_json("hypotheses.sample.json")
    for payload in payloads:
        validate_payload("hypothesis_schema.v1.json", payload)


def test_relations_schema_sample_is_valid():
    relation = {
        "relation_id": "rel-sample-001",
        "subject_id": "obj-001",
        "predicate": "touches",
        "object_id": "obj-002",
        "relation_type": "spatial",
        "directionality": "symmetric",
        "confidence": 0.7,
        "tolerance_context": {
            "linear_tolerance": 0.01,
            "angular_tolerance": 1.0,
            "unit_system": "model_unit",
        },
        "observation_refs": ["obs:distance:001-002"],
        "limitations": [],
        "derived_from": ["geometry_schema.v1.json"],
    }
    validate_payload("relations_schema.v1.json", relation)


def test_entity_schema_sample_is_valid():
    entity = {
        "entity_id": "ent-sample-001",
        "entity_type": "source_object",
        "member_object_ids": ["obj-001"],
        "source_refs": ["guid:obj-001"],
        "formation_method": "direct_extraction",
        "confidence": 1.0,
        "observation_refs": ["obs:extract:obj-001"],
        "limitations": [],
        "warnings": [],
        "status": "observed",
        "notes": ["Directly observed extractor object."],
    }
    validate_payload("entity_schema.v1.json", entity)


def _validate_flow_fixture(filename: str) -> None:
    payload = _load_json(filename)
    for obj in payload.get("objects", []):
        validate_payload("object_schema.v1.json", obj)
    for item in payload.get("metadata", []):
        validate_payload("metadata_schema.v1.json", item)
    for item in payload.get("entities", []):
        validate_payload("entity_schema.v1.json", item)
    for item in payload.get("relations", []):
        validate_payload("relations_schema.v1.json", item)


def test_simple_linear_elements_fixture_matches_contracts():
    _validate_flow_fixture("simple_linear_elements.sample.json")


def test_simple_plate_elements_fixture_matches_contracts():
    _validate_flow_fixture("simple_plate_elements.sample.json")


def test_block_instance_fixture_matches_contracts():
    _validate_flow_fixture("block_instance.sample.json")


def test_contradictory_metadata_fixture_matches_contracts():
    _validate_flow_fixture("contradictory_metadata.sample.json")


def test_documentation_group_fixture_matches_contracts():
    _validate_flow_fixture("documentation_group.sample.json")


def test_mixed_system_fixture_matches_contracts():
    _validate_flow_fixture("mixed_system.sample.json")


def test_geometry_kernel_outputs_validate_against_contracts():
    objects = _load_json("normalized_objects.sample.json")
    result = compute_geometry_features({"objects": objects})
    for item in result["geometry_features"]:
        validate_payload("geometry_schema.v2.json", item)
    for item in result["entities"]:
        validate_payload("entity_schema.v1.json", item)
    for item in result["relations"]:
        validate_payload("relations_schema.v1.json", item)


def test_geometry_kernel_does_not_emit_forbidden_domain_vocabulary():
    objects = _load_json("mixed_system.sample.json")["objects"]
    result = compute_geometry_features({"objects": objects})
    forbidden_terms = ["panel", "beam", "truss", "sip", "connector", "wood", "steel"]

    def _contains_forbidden(value) -> bool:
        if isinstance(value, dict):
            return any(_contains_forbidden(v) for v in value.values())
        if isinstance(value, list):
            return any(_contains_forbidden(v) for v in value)
        if isinstance(value, str):
            lowered = value.lower()
            return any(term in lowered for term in forbidden_terms)
        return False

    assert not _contains_forbidden(result["geometry_features"])
    assert not _contains_forbidden(result["entities"])
    assert not _contains_forbidden(result["relations"])
