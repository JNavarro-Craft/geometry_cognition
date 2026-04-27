"""
Smoke-level checks for gc_smoke_test_01 (JSON equivalent) and optional real .3dm.

- For a real file (e.g. ``gc_smoke_test_01.3dm`` or ``gc_smoke_test_02_complex.3dm``), set
  ``GC_SMOKE_3DM`` to the absolute path. Optional second check: use ``GC_SMOKE_3DM_02`` for
  a complex model if you want a separate test run.
"""

import json
import os
from pathlib import Path

import pytest

from gc_mcp.evidence_graph.tools import build_evidence_graph
from gc_mcp.geometry_kernel.tools import compute_geometry_features
from gc_mcp.hypothesis_engine.tools import generate_hypotheses
from gc_mcp.rhino_extractor.tools import extract_objects
from gc_mcp.validation_engine.tools import validate_hypotheses
from shared.contracts import validate_payload

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_json(name: str):
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def test_smoke_equivalent_objects_validate_object_schema():
    objects = _load_json("gc_smoke_test_01.equivalent.json")
    for obj in objects:
        validate_payload("object_schema.v1.json", obj)


def test_geometry_kernel_smoke_morphologies_and_groups():
    objects = _load_json("gc_smoke_test_01.equivalent.json")
    result = compute_geometry_features({"objects": objects})
    by_id = {f["object_id"]: f for f in result["geometry_features"]}

    assert by_id["obj_test_compact"]["morphology"] == "compact_solid"
    assert by_id["obj_test_linear"]["morphology"] == "linear_prismatic"
    assert by_id["obj_test_plate"]["morphology"] == "thin_plate"

    linear = next(o for o in objects if o["object_id"] == "obj_test_linear")
    assert "grp_test_linear_plate" in (linear.get("group_names") or [])
    assert any("group_name:grp_test_linear_plate" in g for g in linear.get("group_ids", []))
    assert linear["user_text"].get("Nombre")
    assert linear["user_text"].get("Subgrupo")

    block_obj = next(o for o in objects if o["object_id"] == "obj_block_instance_smoke")
    assert block_obj["block_context"]["block_name"] == "module_test_A"
    assert block_obj["block_context"]["is_block_instance"] is True


def test_extract_objects_loads_smoke_equivalent_json():
    path = FIXTURES_DIR / "gc_smoke_test_01.equivalent.json"
    out = extract_objects({"input_path": str(path)})
    assert out["status"] == "ok"
    assert len(out["objects"]) == 4
    for obj in out["objects"]:
        validate_payload("object_schema.v1.json", obj)


@pytest.mark.skipif(not os.environ.get("GC_SMOKE_3DM"), reason="Set GC_SMOKE_3DM to run real .3dm smoke.")
def test_real_3dm_gc_smoke_when_env_path_set():
    pytest.importorskip("rhino3dm")
    path = Path(os.environ["GC_SMOKE_3DM"])
    if not path.is_file():
        pytest.skip(f"GC_SMOKE_3DM not a file: {path}")

    out = extract_objects({"input_path": str(path)})
    assert out["status"] == "ok"
    by_name = {o.get("name"): o for o in out["objects"]}

    if "obj_test_linear" in by_name:
        lin = by_name["obj_test_linear"]
        assert "user_text_lookup_failed" not in lin.get("extraction_warnings", [])
        bb = (lin.get("raw_geometry_summary") or {}).get("bbox") or {}
        assert bb.get("min") and bb.get("max")
        ex = [bb["max"][i] - bb["min"][i] for i in range(3)]
        assert max(ex) > 1.5, "expected non-degenerate bbox for obj_test_linear"

    if "obj_test_plate" in by_name:
        pl = by_name["obj_test_plate"]
        bb = (pl.get("raw_geometry_summary") or {}).get("bbox") or {}
        ex = [bb["max"][i] - bb["min"][i] for i in range(3)] if bb.get("min") else []
        if ex:
            assert max(ex) > 1.5, "expected non-degenerate bbox for obj_test_plate"

    block_named = [o for o in out["objects"] if o.get("block_context", {}).get("block_name") == "module_test_A"]
    if block_named:
        assert any(o.get("object_kind") == "instance_reference" for o in block_named)

    geom = compute_geometry_features({"objects": out["objects"]})
    morph_by_id = {f["object_id"]: f["morphology"] for f in geom["geometry_features"]}
    name_to_id = {o.get("name"): o["object_id"] for o in out["objects"]}
    if "obj_test_linear" in name_to_id:
        assert morph_by_id[name_to_id["obj_test_linear"]] == "linear_prismatic"
    if "obj_test_plate" in name_to_id:
        assert morph_by_id[name_to_id["obj_test_plate"]] == "thin_plate"

    grouped = [o for o in out["objects"] if "grp_test_linear_plate" in (o.get("group_names") or [])]
    if grouped:
        assert all("grp_test_linear_plate" in (o.get("group_names") or []) for o in grouped)


@pytest.mark.skipif(not os.environ.get("GC_SMOKE_3DM_02"), reason="Set GC_SMOKE_3DM_02 to smoke-test gc_smoke_test_02_complex.3dm")
def test_complex_3dm_full_chain_r1_r2_r3_when_env_path_set():
    """End-to-end: extractor → kernel → evidence → hypotheses → validation (R1/R2/R3)."""
    pytest.importorskip("rhino3dm")
    path = Path(os.environ["GC_SMOKE_3DM_02"])
    if not path.is_file():
        pytest.skip(f"GC_SMOKE_3DM_02 not a file: {path}")

    ext = extract_objects({"input_path": str(path)})
    assert ext["status"] == "ok"
    ker = compute_geometry_features({"objects": ext["objects"]})
    evg = build_evidence_graph(
        {
            "objects": ext["objects"],
            "geometry_features": ker["geometry_features"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    hyp = generate_hypotheses(
        {
            "evidence_items": evg["evidence_items"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    val = validate_hypotheses(
        {
            "hypotheses": hyp["hypotheses"],
            "evidence_items": evg["evidence_items"],
            "entities": ker["entities"],
            "relations": ker["relations"],
        }
    )
    eids = {e["entity_id"] for e in ker["entities"]}
    vids = {e["evidence_id"] for e in evg["evidence_items"]}
    for h in hyp["hypotheses"]:
        assert h["entity_id"] in eids
        for s in h.get("supporting_evidence", []):
            assert s in vids
    for rule in val["validation_results"]:
        if rule.get("rule_id") in ("R1", "R2", "R3"):
            assert rule.get("status") == "pass", rule
