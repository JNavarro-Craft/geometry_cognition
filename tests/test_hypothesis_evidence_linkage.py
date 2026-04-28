"""hypothesis_engine links to evidence_graph by official evidence_id only (ev-ent, ev-geom, ev-rel)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.evidence_graph.tools import build_evidence_graph
from gc_mcp.hypothesis_engine.server import generate_hypotheses_tool
from gc_mcp.hypothesis_engine.tools import generate_hypotheses
from gc_mcp.validation_engine.tools import validate_hypotheses
from workflows.run_minimal_analysis import run  # noqa: E402

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


def test_mixed_system_each_entity_has_non_empty_supporting_from_graph(tmp_path):
    bundle = run(
        FIXTURES / "mixed_system.sample.json",
        tmp_path / "hyp_linkage",
        include_hypotheses=True,
    )
    eids = {e["evidence_id"] for e in bundle["evidence_items"]}
    ent_ids = {e["entity_id"] for e in bundle["entities"]}
    for hyp in bundle["hypotheses"]:
        assert hyp["entity_id"] in ent_ids
        assert hyp["supporting_evidence"], f"expected non-empty supporting: {hyp['hypothesis_id']}"
        for sid in hyp["supporting_evidence"]:
            assert sid in eids, sid
        assert f"ev-ent-{hyp['entity_id']}" in hyp["supporting_evidence"]


def test_r1_r2_r3_pass_when_references_legitimate(tmp_path):
    """R3 stays strict: bogus reference still fails in isolation."""
    bundle = run(
        FIXTURES / "mixed_system.sample.json",
        tmp_path / "hyp_val",
        include_validation=True,
    )
    for rule in ("R1", "R2", "R3"):
        rows = [r for r in bundle["validation_results"] if r["rule_id"] == rule]
        assert rows and all(r.get("status") == "pass" for r in rows), rule

    from gc_mcp.validation_engine.tools import validate_hypotheses

    bad = {
        "hypothesis_id": "hyp-x",
        "entity_id": bundle["entities"][0]["entity_id"],
        "hypothesis_label": "ambiguous_entity",
        "hypothesis_level": "relational",
        "confidence": 0.5,
        "supporting_evidence": ["definitely_not_in_graph_12345"],
        "contradicting_evidence": [],
        "alternatives": [],
        "missing_information": ["m"],
        "status": "candidate",
    }
    v = validate_hypotheses(
        {
            "hypotheses": [bad],
            "entities": bundle["entities"],
            "evidence_items": bundle["evidence_items"],
            "relations": bundle["relations"],
        }
    )
    r3 = next(r for r in v["validation_results"] if r["rule_id"] == "R3")
    assert r3["status"] == "fail"


def test_build_supporting_includes_rel_when_member_touches_edge():
    """ev-rel-* included only when subject_id or object_id is in entity.member_object_ids."""
    objects = [
        {
            "object_id": "oa",
            "source_system": "rhino",
            "source_ref": "r1",
            "object_kind": "geometric_object",
            "raw_type": "Brep",
            "layer": "L",
            "name": "a",
            "group_ids": [],
            "block_context": {"is_block_instance": False, "block_name": None},
            "user_text": {},
            "material": None,
            "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "geometry_ref": "g://oa",
            "extraction_warnings": [],
        },
        {
            "object_id": "ob",
            "source_system": "rhino",
            "source_ref": "r2",
            "object_kind": "geometric_object",
            "raw_type": "Brep",
            "layer": "L",
            "name": "b",
            "group_ids": [],
            "block_context": {"is_block_instance": False, "block_name": None},
            "user_text": {},
            "material": None,
            "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "geometry_ref": "g://ob",
            "extraction_warnings": [],
        },
    ]
    from gc_mcp.geometry_kernel.tools import compute_geometry_features

    ker = compute_geometry_features({"objects": objects})
    rels = [
        {
            "relation_id": "rel-t-1",
            "subject_id": "oa",
            "predicate": "near",
            "object_id": "ob",
            "relation_type": "spatial",
            "directionality": "symmetric",
            "confidence": 0.8,
            "tolerance_context": {"linear_tolerance": 0.1, "angular_tolerance": 1, "unit_system": "model_unit"},
            "observation_refs": ["obs:t"],
            "limitations": [],
            "derived_from": ["geometry_schema.v1.json"],
        }
    ]
    # attach relations to kernel output for graph
    ker2 = {**ker, "relations": rels}
    evg = build_evidence_graph(
        {
            "objects": objects,
            "geometry_features": ker["geometry_features"],
            "entities": ker["entities"],
            "relations": rels,
        }
    )
    hyp = generate_hypotheses(
        {"evidence_items": evg["evidence_items"], "entities": ker["entities"], "relations": rels}
    )
    by_ent = {h["entity_id"]: h for h in hyp["hypotheses"]}
    h_a = by_ent.get("ent-src-oa")
    h_b = by_ent.get("ent-src-ob")
    assert h_a and h_b
    assert "ev-rel-rel-t-1" in h_a["supporting_evidence"]
    assert "ev-rel-rel-t-1" in h_b["supporting_evidence"]


def test_mcp_style_flat_args_produces_supporting_and_r1_r2_r3_pass(tmp_path):
    bundle = run(
        FIXTURES / "mixed_system.sample.json",
        tmp_path / "mcp_flat_hyp",
        include_evidence_graph=True,
    )
    hyp_out = generate_hypotheses_tool(
        evidence_items=bundle["evidence_items"],
        entities=bundle["entities"],
        relations=bundle["relations"],
    )
    assert hyp_out["hypotheses"]
    assert all(h["supporting_evidence"] for h in hyp_out["hypotheses"])

    val = validate_hypotheses(
        {
            "hypotheses": hyp_out["hypotheses"],
            "evidence_items": bundle["evidence_items"],
            "entities": bundle["entities"],
            "relations": bundle["relations"],
        }
    )
    for rule in ("R1", "R2", "R3"):
        rows = [r for r in val["validation_results"] if r["rule_id"] == rule]
        assert rows and all(r["status"] == "pass" for r in rows), rule


def test_mcp_style_nested_evidence_graph_supported():
    objects = [
        {
            "object_id": "ox",
            "source_system": "rhino",
            "source_ref": "r1",
            "object_kind": "geometric_object",
            "raw_type": "Brep",
            "layer": "L",
            "name": "x",
            "group_ids": [],
            "block_context": {"is_block_instance": False, "block_name": None},
            "user_text": {},
            "material": None,
            "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "geometry_ref": "g://ox",
            "extraction_warnings": [],
        }
    ]
    from gc_mcp.geometry_kernel.tools import compute_geometry_features

    ker = compute_geometry_features({"objects": objects})
    evg = build_evidence_graph(
        {
            "objects": objects,
            "geometry_features": ker["geometry_features"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    out = generate_hypotheses_tool(evidence_graph={"evidence_items": evg["evidence_items"]}, entities=ker["entities"])
    assert out["hypotheses"]
    assert out["hypotheses"][0]["supporting_evidence"]


def test_missing_inputs_returns_clear_warning():
    out = generate_hypotheses_tool()
    assert out["status"] == "ok"
    assert "warnings" in out
    assert "missing_evidence_items_input" in out["warnings"]
    assert "missing_entities_input" in out["warnings"]


def test_full_evidence_coverage_for_entities(tmp_path):
    bundle = run(
        FIXTURES / "bridge_like_objects.sample.json",
        tmp_path / "full_evidence_coverage",
        include_hypotheses=True,
    )
    ent_ids = {e["entity_id"] for e in bundle["entities"]}
    assert bundle["hypotheses"]
    for hyp in bundle["hypotheses"]:
        assert hyp["entity_id"] in ent_ids
        assert hyp.get("supporting_evidence"), f"missing evidence for {hyp['hypothesis_id']}"


def test_r7_requires_missing_information_when_needed(tmp_path):
    bundle = run(
        FIXTURES / "bridge_like_objects.sample.json",
        tmp_path / "r7_missing_info",
        include_validation=True,
    )
    low_conf = [h for h in bundle["hypotheses"] if float(h.get("confidence", 0.0)) < 0.5]
    for h in low_conf:
        miss = h.get("missing_information", [])
        assert "insufficient relational evidence" in miss
        assert "additional spatial relationships required" in miss

    r7 = [r for r in bundle["validation_results"] if r["rule_id"] == "R7"]
    assert r7
    assert all(r["status"] == "pass" for r in r7)
