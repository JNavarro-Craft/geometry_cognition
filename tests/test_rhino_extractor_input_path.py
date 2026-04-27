"""input_path handling: explicit errors, MCP argument normalization, real file reads."""

import json
from pathlib import Path

from gc_mcp.rhino_extractor.server import extract_objects_tool
from gc_mcp.rhino_extractor.tools import extract_objects

FIXTURES = Path(__file__).parent / "fixtures"
SMOKE_EQ = FIXTURES / "gc_smoke_test_01.equivalent.json"


def test_extract_objects_missing_path_returns_error():
    out = extract_objects({})
    assert out["status"] == "error"
    assert out["objects"] == []
    assert "input_path" in out["message"].lower()


def test_extract_objects_invalid_path_returns_error_not_raises(tmp_path: Path):
    missing = tmp_path / "nonexistent" / "missing_file_99.3dm"
    out = extract_objects({"input_path": str(missing)})
    assert out["status"] == "error"
    assert out["objects"] == []
    assert "does not exist" in out["message"].lower()
    assert out.get("input_path_received")
    assert out.get("path_used")


def test_extract_objects_unsupported_extension_returns_error(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("x", encoding="utf-8")
    out = extract_objects({"input_path": str(f)})
    assert out["status"] == "error"
    assert out["objects"] == []
    assert "extension" in out["message"].lower()


def test_extract_objects_reads_real_json_file():
    assert SMOKE_EQ.is_file()
    out = extract_objects({"input_path": str(SMOKE_EQ.resolve())})
    assert out["status"] == "ok"
    assert len(out["objects"]) >= 1
    assert out["objects"][0].get("object_id")


def test_mcp_tool_top_level_input_path_reads_file():
    out = extract_objects_tool(input_path=str(SMOKE_EQ.resolve()))
    assert out["status"] == "ok"
    assert len(out["objects"]) == 4


def test_mcp_tool_nested_payload_input_path_reads_file():
    out = extract_objects_tool(payload={"input_path": str(SMOKE_EQ.resolve())})
    assert out["status"] == "ok"
    assert len(out["objects"]) == 4


def test_mcp_tool_top_level_wins_over_payload_when_both_given(tmp_path: Path):
    decoy = tmp_path / "decoy.json"
    decoy.write_text("[]", encoding="utf-8")
    out = extract_objects_tool(
        input_path=str(SMOKE_EQ.resolve()),
        payload={"input_path": str(decoy)},
    )
    assert out["status"] == "ok"
    assert len(out["objects"]) == 4


def test_extract_objects_writes_minimal_json_and_reads(tmp_path: Path):
    minimal = [
        {
            "object_id": "t-1",
            "source_system": "rhino",
            "source_ref": "ref-1",
            "object_kind": "geometric_object",
            "raw_type": "Brep",
            "layer": "L",
            "name": "n",
            "group_ids": [],
            "block_context": {"is_block_instance": False, "block_name": None},
            "user_text": {},
            "material": None,
            "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "geometry_ref": "g://t-1",
            "extraction_warnings": [],
        }
    ]
    p = tmp_path / "one.json"
    p.write_text(json.dumps(minimal), encoding="utf-8")
    out = extract_objects({"input_path": str(p)})
    assert out["status"] == "ok"
    assert len(out["objects"]) == 1
