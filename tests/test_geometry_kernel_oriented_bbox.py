import json
from pathlib import Path

from gc_mcp.geometry_kernel.tools import compute_geometry_features
from shared.contracts import validate_payload


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_json(filename: str):
    with (FIXTURES_DIR / filename).open("r", encoding="utf-8") as f:
        return json.load(f)


def test_geometry_kernel_outputs_oriented_bbox_with_valid_format():
    objects = _load_json("normalized_objects.sample.json")
    result = compute_geometry_features({"objects": objects})
    for feature in result["geometry_features"]:
        validate_payload("geometry_schema.v2.json", feature)
        assert "oriented_bbox" in feature
        obb = feature["oriented_bbox"]
        assert len(obb["center"]) == 3
        assert len(obb["axes"]) == 3
        assert all(len(axis) == 3 for axis in obb["axes"])
        assert len(obb["extents"]) == 3
        assert "oriented_bbox_approximation" in feature.get("geometric_warnings", [])
