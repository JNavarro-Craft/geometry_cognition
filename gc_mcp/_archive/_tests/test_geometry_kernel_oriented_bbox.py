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
        assert any(
            w in feature.get("geometric_warnings", [])
            for w in (
                "oriented_bbox_approximation",
                "oriented_bbox_pca_from_bbox_corners",
                "oriented_bbox_pca_from_sample_points",
            )
        )


def test_geometry_kernel_oriented_bbox_uses_pca_from_bbox_corners():
    obj = {
        "object_id": "obb-test-1",
        "source_system": "rhino",
        "source_ref": "src-1",
        "object_kind": "geometric_object",
        "raw_type": "Brep",
        "layer": "L",
        "name": "n",
        "group_ids": [],
        "block_context": {"is_block_instance": False, "block_name": None},
        "user_text": {},
        "material": None,
        "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        "geometry_ref": "g://1",
        "raw_geometry_summary": {
            "bbox": {"min": [0.0, 0.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "bbox_corners": [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0],
                [0.0, 1.0, 0.0],
                [0.0, 1.0, 1.0],
                [2.0, 0.0, 0.0],
                [2.0, 0.0, 1.0],
                [2.0, 1.0, 0.0],
                [2.0, 1.0, 1.0],
            ],
        },
        "extraction_warnings": [],
    }
    result = compute_geometry_features({"objects": [obj]})
    feature = result["geometry_features"][0]
    validate_payload("geometry_schema.v2.json", feature)
    assert "oriented_bbox" in feature
    assert "oriented_bbox_pca_from_bbox_corners" in feature.get("geometric_warnings", [])
