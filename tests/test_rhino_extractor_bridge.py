import os

from gc_mcp.rhino_extractor import backend_adapter
from gc_mcp.rhino_extractor.tools import extract_objects
from shared.contracts import validate_payload


def _bridge_sample_payload():
    return {
        "objects": [
            {
                "id": "bridge-obj-1",
                "type": "Brep",
                "name": "obj_from_bridge",
                "layer": "A::L1",
                "groups": ["g1"],
                "group_names": ["grp_A"],
                "user_text": {"k": "v"},
                "material": "mat",
                "bbox": {"min": [0, 0, 0], "max": [1, 2, 3]},
                "bbox_corners": [
                    [0, 0, 0],
                    [0, 0, 3],
                    [0, 2, 0],
                    [0, 2, 3],
                    [1, 0, 0],
                    [1, 0, 3],
                    [1, 2, 0],
                    [1, 2, 3],
                ],
                "sample_points": [[0.5, 1, 1.5]],
                "metadata": {
                    "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                    "block_info": {"is_block_instance": False, "block_name": None},
                },
            }
        ]
    }


def _bridge_sample_payload_with_bbox_center():
    payload = _bridge_sample_payload()
    payload["objects"][0]["bbox"] = {
        "min": [0, 0, 0],
        "max": [1, 2, 3],
        "center": [0.5, 1.0, 1.5],
    }
    return payload


def test_bridge_mode_maps_plugin_response_to_object_schema(monkeypatch):
    monkeypatch.setenv("GC_BACKEND_MODE", "bridge")
    monkeypatch.setenv("GC_BRIDGE_FETCH_STRATEGY", "extract_scene")
    monkeypatch.setenv("GC_BRIDGE_FALLBACK_LOCAL", "false")
    monkeypatch.setattr(
        backend_adapter,
        "extract_objects_bridge",
        lambda base_url, timeout_seconds: _bridge_sample_payload(),
    )
    out = extract_objects({})
    assert out["status"] == "ok"
    assert out["backend_mode"] == "bridge"
    assert len(out["objects"]) == 1
    obj = out["objects"][0]
    validate_payload("object_schema.v1.json", obj)
    assert obj["source_system"] == "rhino_bridge"
    assert obj["raw_type"] == "Brep"
    assert obj["raw_geometry_summary"]["source"] == "rhino_bridge"
    assert len(obj["raw_geometry_summary"]["bbox_corners"]) == 8


def test_bridge_bbox_center_is_normalized_out_of_bbox(monkeypatch):
    monkeypatch.setenv("GC_BACKEND_MODE", "bridge")
    monkeypatch.setenv("GC_BRIDGE_FETCH_STRATEGY", "extract_scene")
    monkeypatch.setenv("GC_BRIDGE_FALLBACK_LOCAL", "false")
    monkeypatch.setattr(
        backend_adapter,
        "extract_objects_bridge",
        lambda base_url, timeout_seconds: _bridge_sample_payload_with_bbox_center(),
    )
    out = extract_objects({})
    assert out["status"] == "ok"
    obj = out["objects"][0]
    validate_payload("object_schema.v1.json", obj)
    bbox = obj["raw_geometry_summary"]["bbox"]
    assert "center" not in bbox
    assert bbox["min"] == [0, 0, 0]
    assert bbox["max"] == [1, 2, 3]
    assert obj["raw_geometry_summary"]["bbox_center"] == [0.5, 1.0, 1.5]
    assert len(obj["raw_geometry_summary"]["bbox_corners"]) == 8


def test_bridge_failure_fallback_true_uses_local(monkeypatch, tmp_path):
    monkeypatch.setenv("GC_BACKEND_MODE", "bridge")
    monkeypatch.setenv("GC_BRIDGE_FETCH_STRATEGY", "extract_scene")
    monkeypatch.setenv("GC_BRIDGE_FALLBACK_LOCAL", "true")
    monkeypatch.setattr(
        backend_adapter,
        "extract_objects_bridge",
        lambda base_url, timeout_seconds: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    p = tmp_path / "local.json"
    p.write_text(
        '[{"object_id":"o1","source_system":"rhino","source_ref":"r1","object_kind":"geometric_object","raw_type":"Brep","layer":"","name":"","group_ids":[],"block_context":{"is_block_instance":false,"block_name":null},"user_text":{},"material":null,"transform":[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],"geometry_ref":"g://o1","extraction_warnings":[]}]',
        encoding="utf-8",
    )
    out = extract_objects({"input_path": str(p)})
    assert out["status"] == "ok"
    assert out["backend_mode"] == "local_fallback"
    assert out["objects"][0]["object_id"] == "o1"
    assert out["backend_warnings"]


def test_bridge_failure_fallback_false_returns_error(monkeypatch):
    monkeypatch.setenv("GC_BACKEND_MODE", "bridge")
    monkeypatch.setenv("GC_BRIDGE_FETCH_STRATEGY", "extract_scene")
    monkeypatch.setenv("GC_BRIDGE_FALLBACK_LOCAL", "false")
    monkeypatch.setattr(
        backend_adapter,
        "extract_objects_bridge",
        lambda base_url, timeout_seconds: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    out = extract_objects({})
    assert out["status"] == "error"
    assert "bridge_backend_failed" in out["message"]
