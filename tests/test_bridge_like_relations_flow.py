import json
from pathlib import Path

from gc_mcp.evidence_graph.tools import build_evidence_graph
from gc_mcp.geometry_kernel.tools import compute_geometry_features
from gc_mcp.domain_interpreter.tools import generate_domain_interpretations
from gc_mcp.hypothesis_engine.tools import generate_hypotheses
from gc_mcp.validation_engine.tools import validate_hypotheses


FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    with (FIXTURES / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def test_bridge_like_objects_generate_relations_evidence_and_pass_r1_r2_r3():
    objects = _load("bridge_like_objects.sample.json")
    ker = compute_geometry_features({"objects": objects})
    assert len(ker["relations"]) > 0
    predicates = {r["predicate"] for r in ker["relations"]}
    assert {"near", "aligned_with", "parallel_to"}.intersection(predicates)
    assert "grouped_with" in predicates
    assert "declared_related_to" in predicates

    evg = build_evidence_graph(
        {
            "objects": objects,
            "geometry_features": ker["geometry_features"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    assert len(evg["edges"]) > 0
    assert any(e["evidence_id"].startswith("ev-rel-") for e in evg["evidence_items"])

    hyp = generate_hypotheses(
        {"evidence_items": evg["evidence_items"], "entities": ker["entities"], "relations": ker["relations"]}
    )
    assert hyp["hypotheses"]
    assert all(h.get("supporting_evidence") for h in hyp["hypotheses"])

    val = validate_hypotheses(
        {
            "hypotheses": hyp["hypotheses"],
            "evidence_items": evg["evidence_items"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    for rid in ("R1", "R2", "R3", "R7"):
        rows = [r for r in val["validation_results"] if r["rule_id"] == rid]
        assert rows and all(r["status"] == "pass" for r in rows), rid

    domain = generate_domain_interpretations({"hypotheses": hyp["hypotheses"]}, profile="prefab")
    assert len(domain["domain_interpretations"]) > 0
