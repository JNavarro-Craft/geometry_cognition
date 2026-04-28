import json
from pathlib import Path

from shared.contracts import validate_payload


FIXTURES = Path(__file__).parent / "fixtures"


def test_relations_v2_fixture_validates():
    payload = json.loads((FIXTURES / "relations_v2.sample.json").read_text(encoding="utf-8"))
    assert payload
    for rel in payload:
        validate_payload("relations_schema.v2.json", rel)
    metadata_rel = next(r for r in payload if r["predicate"] == "declared_related_to")
    assert metadata_rel["assertion_level"] == "candidate"
    assert metadata_rel["inference_basis"] == "shared_metadata"
    assert "metadata_observational_only" in metadata_rel["limitations"]
